# SPDX-License-Identifier: Apache-2.0
"""Compile production RAM boundary mutants against unchanged strict probes.

Run manually after both strict SoC exports finish with PASS. The completed
positive receipts/logs are required; this tool never waits for, rewrites or
reruns a pending strict export. Only top-level RTL pin expressions change in
isolated copies. A compiled simulation must fail a RAM_RETURN_BOUNDARY or
RAM_SOURCE_BINDING assertion. Compile errors, timeouts, general deadlines and
unrelated failures are not passes. No static rejection is counted as a dynamic
control, and no physical timing qualification is implied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from check_admission_controls import replace_pin
from check_i2c_wiring_controls import hashes


def require(condition, diagnostic):
    if not condition:
        raise ValueError('RAM_WIRING_' + diagnostic)


def uncomment(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)


def compact(text):
    return re.sub(r'\s+', '', uncomment(text))


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


# Diagnostic endpoint identities, not an arbitrary RAM diagnostic from the run.
# The native return check precedes the matching source check in the strict probe;
# either direction of the same publication/drain boundary is an appropriate oracle.
CASE_ENDPOINTS = {
    'word-request': ('ram_return', 'word_request'),
    'word-data': ('ram_return', 'word_data'),
    'word-acknowledge': ('ram_return', 'word_acknowledge'),
    'publication-request': ('ram_return', 'publication_request'),
    'publication-data': ('ram_return', 'publication_data'),
    'publication-acknowledge': ('ram_return', 'publication_acknowledge'),
    'capture-request': ('ram_return', 'capture_request'),
    'capture-acknowledge': ('ram_return', 'capture_acknowledge'),
    'response-request': ('ram_return', 'response_request'),
    'response-data': ('ram_return', 'response_data'),
    'response-acknowledge': ('ram_return', 'response_acknowledge'),
    'eligibility': ('ram_return', 'eligible'),
    'presentation-reset-to-por': ('ram_return', 'application_reset'),
    'retained-owner-reset-to-application': ('ram_return', 'reset'),
    'access-reset-to-application': ('ram_access', 'reset'),
    'access-clock': ('ram_access', None),
    'return-idle': ('ram_return', 'idle'),
    'effects-drain-omitted': ('ram_source', 'word_drained'),
    'presentation-drain-omitted': ('ram_source', 'word_drained'),
    'full-busy-drain-cycle': ('ram_source', 'word_drained'),
}


def bind_diagnostics(mutations, manifest, receipt, probe):
    """Bind each case to exact fatal messages/lines in the attested strict probe."""
    children = {c['id']: c['contract'] for c in manifest['design']['children']}

    def endpoint(child, field):
        node = children[child]
        if field is None:
            return node['rtl_path'] + '.clock'
        matches = [e for e in node['endpoints'] if e['id'] == field]
        require(len(matches) == 1, 'DIAGNOSTIC_ENDPOINT:' + child + '.' + field)
        resolved = receipt.get('probe_paths', {}).get(matches[0]['probe'])
        require(isinstance(resolved, str) and resolved.startswith(node['rtl_path'] + '.') and
                re.fullmatch(r'[A-Za-z_][\w.]*(?:\[\d+(?::\d+)?\])?', resolved), 'DIAGNOSTIC_RESOLUTION:' + field)
        return resolved

    # Preserve line numbers while removing comments so quoted/commented fatal
    # examples cannot become allowed runtime assertion sites.
    source = re.sub(r'/\*.*?\*/|//[^\n]*', lambda m: '\n' * m[0].count('\n'), probe.decode('utf-8'), flags=re.S)
    sites = {}
    for number, line in enumerate(source.splitlines(), 1):
        match = re.fullmatch(r'\s*if\s*\(.+\)\s*\$fatal\(1,\s*"([^"\r\n]+)"\);\s*', line)
        if match:
            sites.setdefault(match[1], []).append(number)
    for mutation in mutations:
        name = mutation['name']
        require(name in CASE_ENDPOINTS, 'DIAGNOSTIC_CASE:' + name)
        child, field = CASE_ENDPOINTS[name]
        messages = ['RAM_RETURN_BOUNDARY:' + endpoint(child, field)]
        if name.startswith('publication-'):
            messages.append('RAM_SOURCE_BINDING:' + endpoint('ram_source', field))
        elif field == 'word_drained':
            messages.append('RAM_SOURCE_BINDING:' + endpoint(child, field))
        require(all(message in sites for message in messages), 'DIAGNOSTIC_NOT_IN_PROBE:' + name)
        mutation['allowed_fatals'] = [dict(source='contract_probe.sv', line=line, message=message, scope='ContractProbe.check')
            for message in messages for line in sites[message]]


def classify_simulation(compiled, simulated, log, allowed_fatals):
    """Only genuine Icarus fatal records at this case's assertions count."""
    require(compiled.get('exit_code') == 0 and not compiled.get('timed_out'), 'COMPILE_FAILED_NOT_A_PASS')
    require(simulated.get('exit_code') == 1 and not simulated.get('timed_out'), 'SIMULATION_EXIT_NOT_A_PASS')
    require(not re.search(r'TIMEOUT|DEADLINE|CONTRACT_PROBES_PASS:|\bERROR\b|syntax error', log, re.I),
            'FORBIDDEN_SIMULATION_RESULT')
    allowed = {(f['source'], f['line'], f['message'], f['scope']) for f in allowed_fatals}
    require(bool(allowed), 'NO_ALLOWED_FATAL')
    lines = log.splitlines()
    records = []
    for index, line in enumerate(lines):
        if 'fatal' not in line.lower():
            continue
        fatal = re.fullmatch(r'FATAL: ([^\r\n]+):(\d+): ([^\r\n]+)', line)
        require(fatal is not None and index + 1 < len(lines), 'MALFORMED_FATAL_NOT_A_PASS')
        context = re.fullmatch(r'\s+Time: (\d+)\s+Scope: ([A-Za-z_][\w.]*)\s*', lines[index + 1])
        require(context is not None, 'FATAL_CONTEXT_NOT_A_PASS')
        record = dict(source=fatal[1], line=int(fatal[2]), message=fatal[3], scope=context[2], time=int(context[1]))
        require((record['source'], record['line'], record['message'], record['scope']) in allowed,
                'UNEXPECTED_FATAL_NOT_A_PASS:' + fatal[3])
        records.append(record)
    require(bool(records), 'NO_TARGET_FATAL_NOT_A_PASS')
    return records


def validate_attestation(source, receipt, probe, current_hashes):
    """Require evidence that these exact inputs and executable actually passed."""
    attestation = json.loads((source / 'mapping-probe-attestation.json').read_text())
    require(attestation.get('schema') == 'riscay-mapping-probe-attestation-v1' and
            attestation.get('status') == 'PASS', 'ATTESTATION_STATUS')
    expected = dict(probe_sha256=hashlib.sha256(probe).hexdigest(),
        compiled_vvp_sha256=sha256(source / 'contract_probe.vvp'),
        simulation_log_sha256=sha256(source / 'contract_simulation.log'),
        mapping_checks=receipt['mapping_checks'], source_sha256=current_hashes,
        semantic_sha256=receipt['semantic_sha256'])
    for key, value in expected.items():
        require(attestation.get(key) == value, 'ATTESTATION_MISMATCH:' + key)
    return attestation


def pin_value(rtl, instance, pin):
    """Use the balanced named-port parser to isolate one complete expression."""
    marker = '__riscay_ram_wiring_mutation_marker__'
    require(marker not in rtl, 'MARKER_COLLISION')
    marked = replace_pin(rtl, instance, pin, marker)
    require(marked.count(marker) == 1, 'PIN_SHAPE:' + instance + '.' + pin)
    prefix, suffix = marked.split(marker)
    require(rtl.startswith(prefix) and rtl.endswith(suffix), 'PIN_BOUNDARY')
    expression = rtl[len(prefix):len(rtl)-len(suffix)]
    require(bool(expression.strip()), 'EMPTY_PIN')
    return uncomment(expression).strip()


def cases_for(rtl, manifest):
    """Twenty independent actual top-RTL substitutions for each native design."""
    top = manifest['top']
    require(top in ('FourPhaseSoc', 'ClickSoc'), 'TOP')
    children = {c['id']: c['contract'] for c in manifest['design']['children']}
    require({'ram_return', 'ram_source', 'ram_access', 'completion'} <= children.keys(), 'CHILDREN')
    paths = {name: children[name]['rtl_path'].rsplit('.', 1)[1]
             for name in ('ram_return', 'ram_source', 'ram_access', 'completion')}
    expected_prefix = 'Click' if top == 'ClickSoc' else 'FourPhase'
    require(re.fullmatch(expected_prefix + r'RamReturn(?:_[0-9]+)?', children['ram_return']['module']) and
            re.fullmatch(expected_prefix + r'RamSource(?:_[0-9]+)?', children['ram_source']['module']) and
            re.fullmatch(r'RamAccess(?:_[0-9]+)?', children['ram_access']['module']), 'NATIVE_OWNERS')
    result = []

    def add(name, child, pin, replacement=None, width=1, purpose=''):
        instance = paths[child]
        old = pin_value(rtl, instance, pin)
        new = replacement if replacement is not None else (
            f"({old}) ^ 32'h00000001" if width == 32 else f'~({old})')
        require(compact(old) != compact(new), 'NO_CHANGE:' + name)
        changed = replace_pin(rtl, instance, pin, new)
        require(changed != rtl and pin_value(changed, instance, pin) == new, 'SUBSTITUTION:' + name)
        result.append(dict(name=name, child=child, instance=instance, pin=pin, before=old, after=new, purpose=purpose))

    add('word-request', 'ram_return', 'word_req', purpose='native word request binding')
    add('word-data', 'ram_return', 'word_bits', width=32, purpose='retained word data binding')
    add('word-acknowledge', 'ram_access', 'word_ack', purpose='word capture acknowledgment binding')
    add('publication-request', 'ram_source', 'publication_req', purpose='native publication request binding')
    add('publication-data', 'ram_source', 'publication_bits', purpose='dynamic retained publication bit binding')
    add('publication-acknowledge', 'ram_return', 'publication_ack', purpose='source publication acknowledgment binding')
    add('capture-request', 'ram_access', 'captureRequest', purpose='real capture receipt request binding')
    add('capture-acknowledge', 'ram_return', 'captureAcknowledge', purpose='real capture receipt acknowledgment binding')
    add('response-request', 'completion', 'ram_req', purpose='application completion request binding')
    add('response-data', 'completion', 'ram_bits_data', width=32, purpose='application completion data binding')
    add('response-acknowledge', 'ram_return', 'response_ack', purpose='application completion acknowledgment binding')
    add('eligibility', 'ram_return', 'eligible', purpose='reservation eligibility before retained word capture')

    por = pin_value(rtl, paths['ram_return'], 'reset')
    application = pin_value(rtl, paths['ram_return'], 'applicationReset')
    require(compact(por) == 'reset' and compact(application) != compact(por), 'RESET_DOMAINS')
    add('presentation-reset-to-por', 'ram_return', 'applicationReset', por,
        purpose='application presentation must cancel on qualified reset')
    add('retained-owner-reset-to-application', 'ram_return', 'reset', application,
        purpose='retained word and POR transport must survive application reset')
    add('access-reset-to-application', 'ram_access', 'reset', application,
        purpose='accepted access effects and capture receipt must remain POR-owned')
    add('access-clock', 'ram_access', 'clock', purpose='capture receipt and macro access use the work clock')
    add('return-idle', 'ram_access', 'returnIdle', purpose='full busy and admission retain native return occupancy')

    effects = pin_value(rtl, paths['ram_access'], 'effectsDrained')
    presentation = pin_value(rtl, paths['ram_return'], 'presentationSettled')
    busy = pin_value(rtl, paths['ram_access'], 'io_busy')
    drained = pin_value(rtl, paths['ram_source'], 'wordDrained')
    require(all(re.fullmatch(r'\w+', n) for n in (effects, presentation, busy)), 'DRAIN_LEAVES')
    require(compact(drained) == compact(effects + '&' + presentation), 'DRAIN_EQUATION')
    add('effects-drain-omitted', 'ram_source', 'wordDrained', presentation,
        purpose='source publication cannot retire before captured effects and receipt drain')
    add('presentation-drain-omitted', 'ram_source', 'wordDrained', effects,
        purpose='source publication cannot retire before application presentation settles')
    add('full-busy-drain-cycle', 'ram_source', 'wordDrained', '~' + busy,
        purpose='full return occupancy must not become its own publication prerequisite')
    require(len(result) == 20 and len({c['name'] for c in result}) == 20, 'CASE_INVENTORY')
    return result


def read_baseline(variant, source):
    source = source.resolve()
    required = ('resolved.json', 'contract.json', 'contract_probe.sv', 'contract_simulation.log',
                'ram-return-reset-boundary.json', 'filelist.f', 'contract_probe.vvp', 'mapping-probe-attestation.json')
    require(all((source / name).is_file() for name in required), 'STRICT_BASELINE_FILES:' + variant)
    receipt = json.loads((source / 'resolved.json').read_text())
    require(receipt.get('status') == 'PASS', 'STRICT_BASELINE_NOT_COMPLETE:' + variant)
    document = json.loads((source / 'contract.json').read_text())
    manifest = document['manifest']
    require(manifest['top'] == ('ClickSoc' if variant == 'click' else 'FourPhaseSoc'), 'BASELINE_VARIANT')
    require(receipt.get('semantic_sha256') == document.get('semantic_sha256'), 'STRICT_SEMANTIC_HASH')
    semantic = hashlib.sha256(json.dumps(manifest, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    require(semantic == document['semantic_sha256'], 'MANIFEST_CHANGED_SINCE_STRICT_PASS')
    count = receipt.get('mapping_checks')
    require(type(count) is int and count > 0, 'MAPPING_COUNT')
    log = (source / 'contract_simulation.log').read_text()
    require(re.search(r'CONTRACT_PROBES_PASS:' + str(count) + r'(?!\d)', log) is not None and
            not re.search(r'FATAL|TIMEOUT|DEADLINE', log), 'STRICT_POSITIVE_LOG')
    record = json.loads((source / 'ram-return-reset-boundary.json').read_text())
    require(record.get('integration', {}).get('top') == manifest['top'] and
            record.get('capture_receipt', {}).get('receipt_clocked_bits') == 5 and
            record['capture_receipt'].get('access_clocked_bits') == 15, 'CAPTURE_BASELINE_RECORD')
    probe = (source / 'contract_probe.sv').read_bytes()
    require(b'RAM_RETURN_BOUNDARY:' in probe and b'RAM_SOURCE_BINDING:' in probe, 'UNCHANGED_ORACLE_MISSING')
    files = []
    for line in (source / 'filelist.f').read_text().splitlines():
        if not line.strip():
            continue
        relative = Path(line.strip())
        path = (source / relative).resolve()
        require(path.is_relative_to(source) and path.is_file(), 'NONLOCAL_FILELIST:' + line)
        files.append(path.relative_to(source))
    require(Path(manifest['top'] + '.sv') in files, 'TOP_NOT_IN_FILELIST')
    require(len({p.name for p in files}) == len(files), 'AMBIGUOUS_SOURCE_NAMES')
    current_hashes = {p.name: hashlib.sha256((source / p).read_bytes()).hexdigest() for p in files}
    require(receipt.get('source_sha256') == current_hashes, 'RTL_CHANGED_SINCE_STRICT_PASS')
    attestation = validate_attestation(source, receipt, probe, current_hashes)
    abi = manifest['probe_abi']
    require(abi.get('file') == 'ref_' + manifest['top'] + '.sv' and
            receipt.get('probe_abi_sha256') == abi.get('sha256') and
            hashlib.sha256((source / abi['file']).read_text().encode()).hexdigest() == abi['sha256'], 'PROBE_ABI_CHANGED')
    rtl = (source / (manifest['top'] + '.sv')).read_text(encoding='utf-8')
    mutations = cases_for(rtl, manifest)
    bind_diagnostics(mutations, manifest, receipt, probe)
    return dict(source=source, receipt=receipt, manifest=manifest, probe=probe, files=files,
        attestation=attestation, probe_sha256=hashlib.sha256(probe).hexdigest(), rtl=rtl, cases=mutations)


def copy_inputs(baseline, destination):
    """Copy exact inputs/evidence without cloning obsolete compiled VVP files."""
    destination.mkdir(parents=True, exist_ok=False)
    source = baseline['source']
    artifacts = ('filelist.f', 'contract.json', 'resolved.json', 'contract_probe.sv', 'contract_simulation.log',
                 'ram-return-reset-boundary.json', 'mapping-probe-attestation.json')
    files = set(baseline['files']) | {Path(n) for n in artifacts}
    files |= {p.relative_to(source) for p in source.glob('ref_*.sv')}
    for relative in files:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    require({p.name: sha256(destination / p) for p in baseline['files']} == baseline['receipt']['source_sha256'],
            'COPIED_RTL_CHANGED_SINCE_STRICT_PASS')
    require((destination / 'contract_probe.sv').read_bytes() == baseline['probe'], 'COPIED_ORACLE_CHANGED')
    require(json.loads((destination / 'mapping-probe-attestation.json').read_text()) == baseline['attestation'],
            'COPIED_ATTESTATION_CHANGED')


def run_command(argv, folder, log_name, timeout, commands):
    commands.append(dict(argv=list(map(str, argv)), cwd=str(folder), log=log_name, timeout_seconds=timeout))
    start = time.monotonic()
    try:
        result = subprocess.run(argv, cwd=folder, text=True, capture_output=True, timeout=timeout)
        output = result.stdout + result.stderr
        record = dict(exit_code=result.returncode, seconds=round(time.monotonic() - start, 3), log=str(folder / log_name))
    except subprocess.TimeoutExpired as error:
        decode = lambda text: text.decode(errors='replace') if isinstance(text, bytes) else text or ''
        output = decode(error.stdout) + decode(error.stderr) + '\nWALL_TIMEOUT_NOT_A_PASS\n'
        record = dict(exit_code=None, timed_out=True, seconds=round(time.monotonic() - start, 3), log=str(folder / log_name))
    (folder / log_name).write_text(output, encoding='utf-8')
    return record, output


def one_case(variant, baseline, mutation, out, args):
    label = variant + '-' + mutation['name']
    folder = out / label
    commands = []
    result = dict(passed=False, variant=variant, mutation=mutation,
        strict_semantic_sha256=baseline['receipt']['semantic_sha256'],
        probe_sha256=baseline['probe_sha256'], mode='compiled-actual-top-RTL-with-unchanged-strict-probe')
    try:
        copy_inputs(baseline, folder)
        top = baseline['manifest']['top']
        rtl = folder / (top + '.sv')
        require(pin_value(baseline['rtl'], mutation['instance'], mutation['pin']) == mutation['before'], 'STALE_MUTATION_SITE')
        text = replace_pin(baseline['rtl'], mutation['instance'], mutation['pin'], mutation['after'])
        rtl.write_text(text, encoding='utf-8')
        result['original_rtl_sha256'] = hashlib.sha256((baseline['source'] / (top + '.sv')).read_bytes()).hexdigest()
        result['mutated_rtl_sha256'] = hashlib.sha256(rtl.read_bytes()).hexdigest()
        require((folder / 'contract_probe.sv').read_bytes() == baseline['probe'], 'ORACLE_CHANGED')
        (folder / 'mutation.json').write_text(json.dumps(mutation, indent=2) + '\n', encoding='utf-8')
        files = [str((folder / p).resolve()) for p in baseline['files']]
        compiled, log = run_command([args.iverilog, '-g2012', '-DCHISEL_ASYNC_MAPPING', '-s', 'ContractProbe', '-s', top,
            '-o', 'control.vvp', *files, 'contract_probe.sv'], folder, 'compile.log', args.compile_timeout, commands)
        result['compile'] = compiled
        require(compiled['exit_code'] == 0, 'COMPILE_FAILED_NOT_A_PASS:' + label)
        simulated, log = run_command([args.vvp, 'control.vvp'], folder, 'simulation.log', args.probe_timeout, commands)
        result['simulation'] = simulated
        result['targeted_fatals'] = classify_simulation(compiled, simulated, log, mutation['allowed_fatals'])
        require((folder / 'contract_probe.sv').read_bytes() == baseline['probe'], 'ORACLE_CHANGED_AFTER_SIMULATION')
        result['passed'] = True
    except Exception as error:
        result['error'] = str(error)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'control-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
    (folder / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    (folder / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n', encoding='utf-8')
    return label, result, commands


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bd', type=Path, required=True)
    parser.add_argument('--click', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--probe-timeout', type=int, default=7200)
    parser.add_argument('--compile-timeout', type=int, default=600)
    parser.add_argument('--iverilog', default='iverilog')
    parser.add_argument('--vvp', default='vvp')
    parser.add_argument('--case', dest='selected', action='append', help='run only this catalogued case in both variants; repeat as needed')
    args = parser.parse_args()
    if min(args.jobs, args.probe_timeout, args.compile_timeout) < 1:
        parser.error('jobs and timeouts must be positive')
    sources = dict(bd=args.bd.resolve(), click=args.click.resolve())
    out = args.out.resolve()
    if any(out.is_relative_to(p) or p.is_relative_to(out) for p in sources.values()):
        parser.error('output must not overlap either input export')
    # Both completed baselines are mandatory before creating any mutation output.
    baselines = {v: read_baseline(v, p) for v, p in sources.items()}
    selected = set(args.selected or [c['name'] for c in baselines['bd']['cases']])
    require(selected and selected <= {c['name'] for c in baselines['bd']['cases']}, 'UNKNOWN_SELECTED_CASE')
    before = {v: hashes(p) for v, p in sources.items()}
    out.mkdir(parents=True, exist_ok=False)
    results = dict(schema='riscay-ram-return-wiring-controls-v1', passed=False, cases={},
        baselines={v: dict(source=str(p['source']), receipt=p['receipt'], attestation=p['attestation'], probe_sha256=p['probe_sha256'],
            source_sha256=before[v]) for v, p in baselines.items()}, selected_cases=sorted(selected))
    commands = []

    def save():
        (out / 'results.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n', encoding='utf-8')

    save()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(one_case, v, baseline, mutation, out, args)
                   for v, baseline in baselines.items() for mutation in baseline['cases'] if mutation['name'] in selected]
        for future in as_completed(futures):
            label, result, case_commands = future.result()
            results['cases'][label] = result
            commands.extend(case_commands)
            save()
            print(label, 'PASS' if result['passed'] else 'FAIL: ' + result.get('error', ''), flush=True)
    preserved = {v: hashes(p) == before[v] for v, p in sources.items()}
    results['originals_preserved'] = preserved
    results['actual_rtl_mutations'] = len(results['cases'])
    results['compiled_targeted_rejections'] = sum(r['passed'] for r in results['cases'].values())
    results['static_controls'] = 0
    results['complete_catalogue'] = len(selected) == 20
    results['passed'] = all(preserved.values()) and len(results['cases']) == len(selected) * 2 and all(r['passed'] for r in results['cases'].values())
    save()
    require(results['passed'], 'CAMPAIGN_FAILED_SEE_RESULTS')
    print('ALL_RAM_RETURN_WIRING_CONTROLS_PASS', flush=True)


if __name__ == '__main__':
    main()

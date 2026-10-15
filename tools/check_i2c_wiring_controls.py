# SPDX-License-Identifier: Apache-2.0
"""Replay intact strict probes and require exact faults in isolated RTL copies."""
from pathlib import Path
import argparse
import copy
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hashes(root):
    return {str(p.relative_to(root)): digest(p)
            for p in sorted(root.rglob('*')) if p.is_file()}


def run(command, folder, log, commands):
    commands.append(dict(cwd=str(folder), argv=[str(x) for x in command], log=log))
    started = time.monotonic()
    timed_out = False
    try:
        result = subprocess.run(command, cwd=folder, text=True, capture_output=True, timeout=600)
        code, output = result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired as error:
        def text(value):
            return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''
        code, timed_out = None, True
        output = text(error.stdout) + text(error.stderr) + '\nHARNESS_TIMEOUT:600\n'
    (folder / log).write_text(output, encoding='utf-8')
    return dict(exit_code=code, timed_out=timed_out, seconds=round(time.monotonic()-started, 3),
                log=str(folder / log)), output


def mutate_pin(source, instance, pin):
    block = re.compile(r'(\b'+re.escape(instance)+r'\s*\()(.*?)(\n\s*\);)', re.S)
    matches = list(block.finditer(source))
    if len(matches) != 1:
        raise AssertionError(('instance count', instance, len(matches)))
    match = matches[0]
    changed, count = re.subn(r'(\.'+re.escape(pin)+r'\s*\()([^)]*)(\))',
                             lambda m: m[1]+"1'b0"+m[3], match[2])
    if count != 1:
        raise AssertionError(('port count', instance, pin, count))
    return source[:match.start(2)]+changed+source[match.end(2):]


def mutate_projection_lane(source, instance, width, lane):
    """Flip one actual data-delay input lane, leaving the probe untouched."""
    assert width in (360, 362) and 0 <= lane < 15, (width, lane)
    blocks = list(re.finditer(r'\b'+re.escape(instance)+r'\s*\(', source))
    assert len(blocks) == 1, ('projection instance count', instance, len(blocks))
    start = blocks[0].end()
    end = source.find('\n  );', start)
    if end < 0:
        end = source.find(');', start)
    assert end > start, 'PROJECTION_INSTANCE_END'
    pins = list(re.finditer(r'\.a\s*\(', source[start:end]))
    assert len(pins) == 1, 'PROJECTION_INPUT_PIN'
    opening = start + pins[0].end() - 1
    depth = 1
    closing = opening + 1
    while depth:
        assert closing < end, 'PROJECTION_INPUT_BALANCE'
        depth += (source[closing] == '(') - (source[closing] == ')')
        closing += 1
    value = source[opening+1:closing-1]
    mask = 1 << (width-15+lane)
    changed = '(' + value + ') ^ ' + str(width) + "'h" + format(mask, 'x')
    return source[:opening+1]+changed+source[closing-1:]


def fault_site(probe, pin_path, bindings):
    """Resolve the exact independent comparison for the actual changed pin."""
    pairs = [(a, b) for a, b in bindings if pin_path in (a, b)]
    assert len(pairs) == 1, ('I2C_FAULT_PIN_COMPARISON', pin_path, pairs)
    a, b = pairs[0]
    expected = f'if ({a} !== {b}) $fatal(1,"DATA_PATH_BINDING_MISMATCH");'
    compact = lambda value: re.sub(r'\s+', '', value)
    lines = probe.read_text(encoding='utf-8').splitlines()
    matches = [i for i, line in enumerate(lines, 1) if compact(line) == compact(expected)]
    assert len(matches) == 1, ('I2C_FAULT_ASSERTION_SITE', pin_path, matches)
    prefix = '\n'.join(lines[:matches[0]])
    assert re.findall(r'\bmodule\s+(\w+)', prefix) == ['ContractProbe'], 'I2C_FAULT_MODULE'
    assert len(re.findall(r'\btask\s+check\s*;', prefix)) == 1, 'I2C_FAULT_TASK'
    assert not re.search(r'\bendtask\b', prefix), 'I2C_FAULT_OUTSIDE_TASK'
    return dict(file=str(probe.resolve()), line=matches[0], scope='ContractProbe.check',
                diagnostic='DATA_PATH_BINDING_MISMATCH', mutated_pin=pin_path,
                comparison=[a, b])


def resolved_node(manifest, references):
    """Use the exported probe ABI, just as the strict checker does."""
    result = copy.deepcopy(manifest['design'])
    assert manifest['top'] == result['rtl_path'] == 'I2cPublication', 'I2C_PROBE_OWNER'
    assert set(references) == {e['probe'] for e in result['endpoints']}, 'I2C_PROBE_SET'
    for endpoint in result['endpoints']:
        endpoint['rtl_path'] = manifest['top'] + '.' + references[endpoint['probe']]
    return result


def classify_simulation(result, output, folder, checks, expected=None):
    assert not result.get('timed_out'), 'I2C_SIMULATION_TIMEOUT'
    assert not re.search(r'\b(?:ERROR|TIMEOUT|DEADLINE)\b|HARNESS_TIMEOUT', output, re.I), \
        ('I2C_SIMULATION_DIAGNOSTIC', output[-4000:])
    markers = re.findall(r'CONTRACT_PROBES_PASS:(\d+)', output)
    if expected is None:
        assert result['exit_code'] == 0, ('I2C_POSITIVE_EXIT', output[-4000:])
        assert not re.search(r'\bFATAL\b', output, re.I), ('I2C_POSITIVE_FATAL', output[-4000:])
        assert markers == [str(checks)], ('I2C_POSITIVE_COVERAGE', markers, checks)
        return None
    assert result['exit_code'] not in (None, 0), ('I2C_NEGATIVE_EXIT', output[-4000:])
    assert not markers, 'I2C_NEGATIVE_REACHED_PASS'
    assert len(re.findall(r'\bFATAL\b', output, re.I)) == 1, 'I2C_NEGATIVE_FATAL_COUNT'
    fatals = re.findall(r'^FATAL: ([^\r\n]+):(\d+): ([^\r\n]+)\r?$', output, re.M)
    assert len(fatals) == 1, ('I2C_NEGATIVE_FATAL_FORMAT', output[-4000:])
    filename, line, message = fatals[0]
    observed_file = (folder / filename).resolve()
    assert observed_file == Path(expected['file']).resolve(), ('I2C_NEGATIVE_FATAL_FILE', filename)
    assert int(line) == expected['line'] and message == expected['diagnostic'], \
        ('I2C_NEGATIVE_FATAL_SITE', fatals, expected)
    times = re.findall(r'^\s*Time: (\d+)\s+Scope: ([^\s]+)\s*$', output, re.M)
    assert len(times) == 1 and times[0][1] == expected['scope'], ('I2C_NEGATIVE_FATAL_SCOPE', times)
    return dict(file=str(observed_file), line=int(line), diagnostic=message,
                time=int(times[0][0]), scope=times[0][1])


def compile_inputs(folder, sources, probe, mutated):
    """Inventory every compiler input before invocation; reject stale RTL roots."""
    folder = folder.resolve()
    paths = [Path(p).resolve() for p in sources] + [probe.resolve()]
    assert len(paths) == len(set(paths)), 'I2C_COMPILE_DUPLICATE_SOURCE'
    assert paths.count(mutated.resolve()) == 1, 'I2C_MUTATED_SOURCE_NOT_COMPILED'
    assert all(p.is_relative_to(folder) and p.is_file() for p in paths), 'I2C_COMPILE_SOURCE_OUTSIDE_CASE'
    return dict(source_sha256={str(p): digest(p) for p in paths},
                probe_sha256=digest(probe), filelist_sha256=digest(folder/'filelist.f'),
                contract_sha256=digest(folder/'contract.json'))


def unchanged_inputs(before, folder, sources, probe, mutated, stage, record=None):
    after = compile_inputs(folder, sources, probe, mutated)
    if record is not None:
        record[stage] = after
    assert after == before, ('I2C_COMPILER_INPUT_CHANGED', stage)
    return after


def execute_case(folder, checks, expected, baseline_probe_hash, commands, record):
    """Hash before/after each tool boundary, retaining evidence on every failure."""
    probe = folder/'contract_probe.sv'
    rtl = folder/'I2cPublication.sv'
    sources = [str((folder/x.strip()).resolve())
               for x in (folder/'filelist.f').read_text().splitlines() if x.strip()]
    record['status'] = 'STARTED'
    try:
        before = compile_inputs(folder, sources, probe, rtl)
        assert before['probe_sha256'] == baseline_probe_hash, 'I2C_ORIGINAL_PROBE_CHANGED'
        record.update(precompile=before, expected_fatal=expected, generic_probe_preserved=True)
        (folder/'case-receipt.json').write_text(json.dumps(record, indent=2)+'\n')
        binary = folder/'wiring-control.vvp'
        assert not binary.exists(), 'I2C_PREEXISTING_CASE_BINARY'
        command = ['iverilog', '-s', 'ContractProbe', '-g2012', '-DCHISEL_ASYNC_MAPPING',
                   '-s', 'I2cPublication', '-o', binary.name, *sources, 'contract_probe.sv']
        compiled, output = run(command, folder, 'negative-control-compile.log', commands)
        record['compile'] = compiled
        unchanged_inputs(before, folder, sources, probe, rtl, 'postcompile', record)
        assert compiled['exit_code'] == 0 and not compiled['timed_out'], ('I2C_COMPILE_FAILED', output[-4000:])
        assert not re.search(r'\b(?:ERROR|FATAL|TIMEOUT|DEADLINE)\b', output, re.I), 'I2C_COMPILE_DIAGNOSTIC'
        record['binary_path'] = str(binary)
        record['binary_before_execution_sha256'] = digest(binary)
        (folder/'case-receipt.json').write_text(json.dumps(record, indent=2)+'\n')
        simulated, output = run(['vvp', binary.name], folder, 'negative-control-simulation.log', commands)
        record['simulation'] = simulated
        unchanged_inputs(before, folder, sources, probe, rtl, 'postsimulation', record)
        record['binary_after_execution_sha256'] = digest(binary)
        assert record['binary_after_execution_sha256'] == record['binary_before_execution_sha256'], 'I2C_EXECUTED_BINARY_CHANGED'
        record['simulation_log_sha256'] = digest(folder/'negative-control-simulation.log')
        record['fatal_site'] = classify_simulation(simulated, output, folder, checks, expected)
        record.update(status='PASS', probe_sha256=before['probe_sha256'], rtl_sha256=digest(rtl),
                      binary_sha256=record['binary_after_execution_sha256'])
    except BaseException as error:
        record.update(status='FAIL', error=repr(error))
        raise
    finally:
        (folder/'case-receipt.json').write_text(json.dumps(record, indent=2)+'\n')


def main():
    from check_export import i2c_path_bindings

    parser = argparse.ArgumentParser()
    parser.add_argument('--bd', type=Path, required=True)
    parser.add_argument('--click', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    args.repo = args.repo.resolve()
    args.library = args.library.resolve()
    sys.path.insert(0, str(args.library/'tools'))
    spec = importlib.util.spec_from_file_location('i2c_control_library', args.library/'tools/check_export.py')
    library = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(library)
    out = args.out.resolve()
    inputs = [('bd', args.bd.resolve()), ('click', args.click.resolve())]
    if any(out.is_relative_to(source) for _, source in inputs):
        parser.error('--out must be outside both input export directories')
    out.mkdir(parents=True, exist_ok=False)
    results, commands = {}, []
    try:
        for name, source in inputs:
            before = hashes(source)
            results[name] = dict(source=str(source), source_before_sha256=before, cases={})
            try:
                baseline = out/(name+'-original')
                shutil.copytree(source, baseline)
                original, output = run([sys.executable, str(args.repo/'tools/check_export.py'), str(baseline),
                                        '--library', str(args.library)], baseline, 'strict.log', commands)
                results[name]['strict'] = original
                assert original['exit_code'] == 0 and not original['timed_out'], output[-4000:]
                assert not re.search(r'\b(?:ERROR|FATAL|TIMEOUT|DEADLINE)\b', output, re.I), 'I2C_STRICT_DIAGNOSTIC'
                summary = json.loads(output)
                assert summary['status'] == 'PASS' and summary['mapping_checks'] > 0, 'I2C_STRICT_NO_COVERAGE'
                checks = summary['mapping_checks']
                probe = baseline/'contract_probe.sv'
                probe_hash = digest(probe)
                manifest = json.loads((baseline/'contract.json').read_text())['manifest']
                abi = manifest['probe_abi']
                assert abi['file'] == 'ref_I2cPublication.sv', 'I2C_PROBE_ABI_FILE'
                assert digest(baseline/abi['file']) == abi['sha256'], 'I2C_PROBE_ABI_HASH'
                node = resolved_node(manifest, library.read_probe_abi((baseline/abi['file']).read_text(), manifest['top']))
                primitives = {p['id']: p for p in node['primitives']}
                bindings = i2c_path_bindings(node)
                results[name].update(mapping_checks=checks, original_probe_sha256=probe_hash)
                print(name, 'original strict PASS', checks, flush=True)
                cases = [('baseline', None, None), ('request-input-disconnected', 'request_delay', 'a'),
                         ('capture-trigger-disconnected', 'observation', 'trigger')]
                for prefix in (('capture_gate',) if name == 'click' else ('frame_publish', 'snapshot_publish')):
                    cases += [(primitive+'-internal-'+pin+'-disconnected', primitive, pin)
                              for primitive, pin in ((prefix+'_or', 'a'), (prefix+'_or', 'b'), (prefix, 'a'))]
                cases = [(label, primitive, pin, None) for label, primitive, pin in cases]
                cases += [('observation-lane-'+str(lane), 'data_delay', 'a', lane) for lane in range(15)]
                width = int(primitives['data_delay']['parameters']['WIDTH'])
                assert width == (362 if name == 'click' else 360), 'OBSERVATION_DATA_WIDTH'
                baseline_hashes = hashes(baseline)
                for label, primitive, pin, lane in cases:
                    case = out/(name+'-'+label)
                    shutil.copytree(baseline, case)
                    rtl = case/'I2cPublication.sv'
                    expected = None
                    if primitive:
                        instance = primitives[primitive]['rtl_path'].split('.')[-1]
                        changed = (mutate_projection_lane(rtl.read_text(), instance, width, lane) if lane is not None
                                   else mutate_pin(rtl.read_text(), instance, pin))
                        rtl.write_text(changed, encoding='utf-8')
                        expected = fault_site(case/'contract_probe.sv', primitives[primitive]['rtl_path']+'.'+pin, bindings)
                    copied_hashes = hashes(case)
                    difference = {p for p in baseline_hashes.keys() | copied_hashes.keys()
                                  if baseline_hashes.get(p) != copied_hashes.get(p)}
                    assert difference == ({'I2cPublication.sv'} if primitive else set()), ('I2C_MUTATION_SCOPE', difference)
                    record = dict(projection_lane=lane, mutated_pin=None if expected is None else expected['mutated_pin'],
                                  mutation_files=sorted(difference))
                    results[name]['cases'][label] = record
                    execute_case(case, checks, expected, probe_hash, commands, record)
                    print(name, label, 'PASS', 'exact fatal' if primitive else 'full probe', flush=True)
            finally:
                results[name]['source_after_sha256'] = hashes(source)
                results[name]['original_preserved'] = before == results[name]['source_after_sha256']
                assert results[name]['original_preserved'], 'ORIGINAL_EXPORT_MODIFIED'
    finally:
        (out/'results.json').write_text(json.dumps(results, indent=2)+'\n')
        (out/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
    print('ALL_ACTUAL_WIRING_CONTROLS_PASS', flush=True)


if __name__ == '__main__':
    main()

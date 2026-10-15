# SPDX-License-Identifier: Apache-2.0
"""Bind a fresh root regression, then replay intact C1e fixtures and exact faults.

Eleven fixtures, eleven baselines and 151 faults; no fixture generation or graph
substitution. The original eight/148 campaign is retained intact. Root owns the serialized clean/test/export and its provenance.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

from check_frame_store_controls import helper_closure, masked, pin_value, replace_pin
from check_program_return_fatals import fatal_sites, classify_fatal
from checker_successor import bind_sources as source_binding

KINDS = ('walk', 'invalid', 'work-stop', 'composed')
EXPECTED = {
    'payload': 'RECEIPT_OFFER', 'invalid-mask': 'RECEIPT_IDLE_ASYNC_LEAK',
    'work-enable': 'RECEIPT_ACK_WITHOUT_CONSUMER_CLOCK',
    'raw-source-reset': 'SOC_BOUNDARY_WORK_SOURCE_CHANGED_BEFORE_CLOSURE',
    'closed-mask': 'SOC_BOUNDARY_CLOSED_INGRESS_OUTPUT_NOT_MASKED',
}
CLASS_ROOTS = ('shared', 'soc', 'profiles', 'designs/four-phase-bd',
               'designs/two-phase-click', 'verification', 'physical')
REQUIRED_CLASSES = ('riscay/QuiescingReceiptSpec.class', 'riscay/QuiescingReceiptFixture.class',
    'riscay/ResetBoundarySocSpec.class', 'riscay/BdResetBoundarySocFixture.class',
    'riscay/ClickResetBoundarySocFixture.class', 'riscay/ClockedSimulation$.class',
    'riscay/bd/FourPhaseQuiescingReceipt.class', 'riscay/click/ClickQuiescingReceipt.class')
REQUIRED_INVENTORY = Path(__file__).resolve().parent / 'fixtures/quiescing_receipt/required-suites.json'
REQUIRED_INVENTORY_SHA256 = '8b1ac02ad68c6026e84059558fb6c4ef181cd47bdb7d188797865e7e2013b693'


def need(ok, why):
    if not ok:
        raise ValueError('QUIESCING_CONTROL_' + why)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique)


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def file_hashes(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def check_hashes(base, values):
    need(type(values) is dict and bool(values), 'EMPTY_HASH_INVENTORY')
    for name, digest in values.items():
        path = (base / name).resolve()
        need(path.is_file() and sha(path) == digest, 'INPUT_CHANGED:' + str(path))


def original_cases(kind):
    need(kind in KINDS, 'CASE_KIND')
    return ([('payload', lane) for lane in range(70)] if kind == 'walk' else
            [('invalid-mask', None)] if kind == 'invalid' else
            [('work-enable', None)] if kind == 'work-stop' else
            [('raw-source-reset', None), ('closed-mask', None)])


def validate_original_cohort(cohort):
    need(cohort.get('schema') == 'riscay-quiescing-controls-cohort-v1', 'COHORT_SCHEMA')
    groups = cohort['fixtures']
    need(len(groups) == 8 and {(g['variant'], g['kind']) for g in groups} ==
         {(v, k) for v in ('bd', 'click') for k in KINDS}, 'COMPLETE_EIGHT_FIXTURES')
    paths = []
    for g in groups:
        need(set(g) == {'variant', 'kind', 'path'} and Path(g['path']).is_absolute(), 'FIXTURE_FIELDS')
        prefix = g['variant'] + ('-soc-reset-work-stopped' if g['kind'] == 'composed'
                                else '-retained-quiescing-' + g['kind'])
        need(re.fullmatch(re.escape(prefix) + r'[0-9]+', Path(g['path']).name) is not None,
             'FIXTURE_NAME_IDENTITY')
        paths.append(str(Path(g['path']).resolve()))
    need(len(set(paths)) == 8, 'DUPLICATE_FIXTURE')
    return groups


def cases(kind):
    return [('actual-gate', None)] if kind == 'real-gate' else original_cases(kind)


def validate_cohort(cohort):
    need(cohort.get('schema') == 'riscay-quiescing-controls-cohort-v2', 'COHORT_SCHEMA')
    groups = cohort['fixtures']
    legacy = [g for g in groups if g.get('kind') != 'real-gate']
    gates = [g for g in groups if g.get('kind') == 'real-gate']
    validate_original_cohort(dict(schema='riscay-quiescing-controls-cohort-v1', fixtures=legacy))
    need(len(groups) == 11 and len(gates) == 3 and
         {(g['variant'], g['prefix']) for g in gates} == {('bd', 0), ('click', 0), ('click', 1)}, 'THREE_GATE_FIXTURES')
    for g in gates:
        need(set(g) == {'variant', 'kind', 'prefix', 'path'} and type(g['prefix']) is int and
             Path(g['path']).is_absolute(), 'GATE_FIXTURE_FIELDS')
        prefix = g['variant'] + '-soc-receipt-real-gate-' + str(g['prefix'])
        need(re.fullmatch(re.escape(prefix) + r'[0-9]+', Path(g['path']).name) is not None, 'GATE_FIXTURE_NAME_IDENTITY')
    need(len({str(Path(g['path']).resolve()) for g in groups}) == 11, 'DUPLICATE_FIXTURE')
    return groups


def gate_activity(log, variant, expected_phase=None, fault=False):
    phases = re.findall(r'^SOC_GATE_REQUEST_PHASE:([01])$', log, re.M)
    need(len(phases) == 1 and (variant != 'bd' or phases == ['1']), 'GATE_REQUEST_ACTIVITY')
    phase = int(phases[0])
    need(expected_phase is None or phase == expected_phase, 'GATE_PHASE_CHANGED')
    counts = re.findall(r'^SOC_GATE_CAPTURE_COUNTS:(.*)$', log, re.M)
    need(counts == ([] if fault else ['1:1:1:4']), 'GATE_EXACT_CAPTURE_ACTIVITY')
    return phase


def mutate(texts, manifest, variant, fault, lane=None):
    if fault == 'actual-gate':
        need(lane is None, 'GATE_HAS_NO_PAYLOAD_LANE')
        from quiescing_gate_control import mutate as gate_mutate
        return gate_mutate(texts, manifest, variant)
    return mutate_original(texts, manifest, variant, fault, lane)


def required_inventory():
    # Git uses autocrlf on this Windows checkout. Pin reviewed text after only
    # CRLF normalization; the regression still binds exact checkout bytes.
    digest = hashlib.sha256(REQUIRED_INVENTORY.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    need(digest == REQUIRED_INVENTORY_SHA256, 'REVIEWED_INVENTORY_CHANGED')
    inventory = read_json(REQUIRED_INVENTORY)
    need(inventory['schema'] == 'riscay-quiescing-required-regression-v1', 'REQUIRED_INVENTORY_SCHEMA')
    return inventory


def validate_commands(command, inventory):
    need(len(command) >= 4 and command[1] == 'tools/sbt.py' and command[2] == 'clean' and
         command.count('clean') == 1, 'SERIAL_CLEAN_COMMAND')
    tail = command[3:]
    need(tail.count(inventory['primary_command']) == 1 and len(tail) == len(set(tail)),
         'EXACT_REQUIRED_SUITE_COMMAND')
    required = {'riscay.' + s for s in inventory['suites']}
    exports = set()
    for item in tail:
        words = item.split()
        need(words and ' '.join(words) == item, 'COMMAND_SPELLING')
        if words[0] == 'verification/testOnly':
            # No ScalaTest selectors, tags, globs, reporter options, -- or sbt
            # settings. The required suites run exactly once, together.
            need(len(words) > 1 and len(words[1:]) == len(set(words[1:])) and
                 all(re.fullmatch(r'riscay\.[A-Za-z_]\w*', w) for w in words[1:]), 'TEST_SELECTORS_OR_FILTERS')
            need(item == inventory['primary_command'] or not required.intersection(words[1:]),
                 'REQUIRED_SUITE_REPEATED_OR_SPLIT')
        elif item == 'physical/test':
            continue
        else:
            models = {'fourPhaseBd/runMain': 'riscay.bd.EmitFourPhaseSoc',
                      'twoPhaseClick/runMain': 'riscay.click.EmitClickSoc',
                      'physical/runMain': 'riscay.physical.EmitPhysical'}
            need(len(words) == 3 and words[0] in models and words[1] == models[words[0]] and
                 re.fullmatch(r'build/[A-Za-z0-9_./-]+', words[2]) is not None and
                 '..' not in Path(words[2]).parts and words[0] not in exports, 'UNREVIEWED_COMMAND')
            exports.add(words[0])
    need(tail.count('physical/test') == 1 and exports ==
         {'fourPhaseBd/runMain', 'twoPhaseClick/runMain', 'physical/runMain'}, 'TEST_EXPORT_COMMAND_INVENTORY')


def completed_runs(log):
    """Read the serial ScalaTest reporter: named cases plus complete summaries.

    A suite header or aggregate pass alone is insufficient. Every named case,
    suite completion, test total and success total must agree in the same run.
    """
    runs = []; current = None; suite = None
    for line in log.splitlines():
        header = re.fullmatch(r'\[info\] ([A-Za-z_]\w*):', line)
        case = re.fullmatch(r'\[info\] - (.+)', line)
        total = re.fullmatch(r'\[info\] Total number of tests run: (\d+)', line)
        suites = re.fullmatch(r'\[info\] Suites: completed (\d+), aborted (\d+)', line)
        tests = re.fullmatch(r'\[info\] Tests: succeeded (\d+), failed (\d+), canceled (\d+), ignored (\d+), pending (\d+)', line)
        if header:
            if current is None:
                current = dict(suites={}, finished=False)
            need(not current['finished'] and header[1] not in current['suites'], 'DUPLICATE_OR_LATE_SUITE_HEADER')
            suite = header[1]; current['suites'][suite] = []
        elif case:
            need(current is not None and suite is not None and not current['finished'], 'CASE_OUTSIDE_RUNNING_SUITE')
            need(case[1] not in current['suites'][suite], 'DUPLICATE_NAMED_CASE')
            current['suites'][suite].append(case[1])
        elif line.startswith('[info] Run completed in '):
            need(current is not None and not current['finished'], 'DUPLICATE_OR_MISSING_RUN_COMPLETION')
            current['finished'] = True; suite = None
        elif total or suites or tests:
            need(current is not None and current['finished'], 'SUMMARY_BEFORE_COMPLETION')
            key = 'total' if total else 'completed' if suites else 'tests'
            need(key not in current, 'DUPLICATE_SUMMARY')
            current[key] = int(total[1]) if total else [int(x) for x in (suites.groups() if suites else tests.groups())]
        elif line == '[info] All tests passed.':
            need(current is not None and current['finished'] and
                 set(current) == {'suites', 'finished', 'total', 'completed', 'tests'}, 'MISSING_COMPLETION_INVENTORY')
            count = sum(len(names) for names in current['suites'].values())
            need(all(current['suites'].values()) and count > 0 and current['total'] == count and
                 current['tests'] == [count, 0, 0, 0, 0] and
                 current['completed'] == [len(current['suites']), 0], 'NAMED_CASE_OR_COMPLETED_SUITE_COUNTS')
            runs.append(current); current = None; suite = None
    need(current is None and runs, 'INCOMPLETE_TEST_RUN')
    return runs


def execution_header(execution, before, log, command):
    need(execution.get('status') == 'PASS_DIGITAL_REGRESSION_AND_FRESH_EXPORTS' and
         execution.get('exit_code') == 0 and execution.get('error') is None and
         not execution.get('snapshot_errors'), 'REGRESSION_NOT_PASS')
    need(execution.get('sources_unchanged') is True and execution.get('tools_unchanged') is True and
         execution['sources_sha256'] == before['sources_sha256'] and
         execution['tool_inputs_sha256'] == before['tool_inputs_sha256'], 'REGRESSION_INPUT_CHANGED')
    inventory = required_inventory()
    need(command == execution['command'], 'REGRESSION_COMMAND_BINDING')
    validate_commands(command, inventory)
    runs = completed_runs(log)
    commanded = [{w.removeprefix('riscay.') for w in item.split()[1:]}
                 for item in command[3:] if item.startswith('verification/testOnly ')]
    need(len(runs) == len(commanded) + 1, 'MISSING_OR_EXTRA_COMPLETED_RUN')
    for suites in commanded:
        need(sum(set(run['suites']) == suites for run in runs) == 1, 'COMMANDED_SUITE_COMPLETION')
    need([[str(n) for n in run['tests']] for run in runs] == execution['test_summaries'], 'REGRESSION_SUMMARIES')
    required = set(inventory['suites'])
    matching = [run for run in runs if required.intersection(run['suites'])]
    need(len(matching) == 1 and set(matching[0]['suites']) == required, 'EXACT_REQUIRED_SUITE_RUN')
    selected = matching[0]
    need(selected['total'] == inventory['expected_tests'] and
         selected['completed'] == [inventory['expected_completed_suites'], 0], 'REQUIRED_TEST_AND_SUITE_TOTALS')
    for suite, names in inventory['suites'].items():
        need(Counter(selected['suites'][suite]) == Counter(names), 'REQUIRED_NAMED_CASE_INVENTORY:' + suite)
    need(not re.search(r'\*\*\* (FAILED|ABORTED)|\[error\]', log) and
         re.search(r'compiling \d+ Scala sources? to .*verification', log) is not None,
         'FRESH_COMPILE_OR_FAILURE')
    need(0 < execution['started_unix'] <= execution['ended_unix'], 'REGRESSION_TIME_ORDER')
    fresh = execution['fresh_fixtures_sha256']
    need(fresh and not set(fresh).intersection(before['fixtures']), 'NONFRESH_FIXTURE')
    return dict(inventory_lf_sha256=REQUIRED_INVENTORY_SHA256, command=inventory['primary_command'],
                completed_suites=sorted(required), named_cases=selected['suites'], total=selected['total'])


def current_sources(execution, root, checker_successor=None):
    return source_binding(execution, root, checker_successor)['current_sources_sha256']


def bind_execution(path, root, checker_successor=None):
    execution = read_json(path); base = path.parent
    names = {'before_sha256': 'regression-before.json', 'command_sha256': 'regression-command.json',
             'preparation_sha256': 'preparation.json', 'log_sha256': 'regression.log'}
    for key, name in names.items():
        need(sha(base / name) == execution[key], 'REGRESSION_RECORD_HASH:' + name)
    before = read_json(base / names['before_sha256'])
    coverage = execution_header(execution, before, (base / 'regression.log').read_text(),
                                read_json(base / 'regression-command.json'))
    # Preserve the original execution; checker-only deltas have separate custody.
    source = source_binding(execution, root, checker_successor)
    if checker_successor is not None:
        need(read_json(checker_successor)['original_execution']['path'] == str(path.resolve()),
             'CHECKER_SUCCESSOR_EXECUTION_PATH')
    source_names = set(source['current_sources_sha256'])
    need(REQUIRED_INVENTORY.is_relative_to(root) and
         REQUIRED_INVENTORY.relative_to(root).as_posix() in source_names, 'UNBOUND_REQUIRED_INVENTORY')
    for relative, digest in required_inventory()['source_lf_sha256'].items():
        need(relative in source_names and hashlib.sha256((root / relative).read_bytes().replace(b'\r\n', b'\n')).hexdigest() == digest,
             'REVIEWED_SUITE_SOURCE_CHANGED:' + relative)
    actual_classes = {p.relative_to(root).as_posix(): sha(p) for folder in CLASS_ROOTS
                      for p in sorted((root / folder / 'target').glob('scala-*/*classes/**/*.class'))}
    need(actual_classes and actual_classes == execution['compiled_class_sha256'], 'CLASS_INVENTORY')
    for name in REQUIRED_CLASSES:
        need(sum(p.endswith('/' + name) for p in actual_classes) == 1, 'REQUIRED_CLASS:' + name)
    need(all(Path(p).is_absolute() for p in execution['tool_inputs_sha256']), 'ABSOLUTE_TOOL_PATHS')
    check_hashes(Path(), execution['tool_inputs_sha256'])
    tool_paths = {str(Path(p).resolve()) for p in execution['tool_inputs_sha256']}
    binaries = {}
    for name in ('iverilog', 'vvp'):
        value = shutil.which(name)
        need(value is not None and str(Path(value).resolve()) in tool_paths, 'UNBOUND_TOOL:' + name)
        binaries[name] = str(Path(value).resolve())
    ivl = Path(binaries['iverilog']).parent.parent / 'lib/ivl'
    need(ivl.is_dir() and {str(p.resolve()) for p in ivl.rglob('*') if p.is_file()} <= tool_paths,
         'INCOMPLETE_IVL_RUNTIME')
    for p in helper_closure([Path(__file__)]):
        need(p.is_relative_to(root) and p.relative_to(root).as_posix() in source_names,
             'UNBOUND_RUNNER_HELPER:' + str(p))
    return execution, {str(path): sha(path), **{str(base / n): sha(base / n) for n in names.values()},
                       **source['records']}, binaries, coverage


def one(pattern, text, why):
    matches = list(re.finditer(pattern, masked(text), re.S))
    need(len(matches) == 1, why)
    return matches[0]


def actual_child(manifest, top_text, identity, expected):
    nodes = [c['contract'] for c in manifest['design']['children'] if c['id'] == identity]
    need(len(nodes) == 1 and nodes[0]['module'] == expected, 'CHILD_MODEL:' + identity)
    node = nodes[0]; instance = node['rtl_path'].rsplit('.', 1)[1]
    need(node['rtl_path'] == manifest['top'] + '.' + instance, 'CHILD_PATH')
    one(r'\b' + re.escape(expected) + r'\s+' + re.escape(instance) + r'\s*\(', top_text, 'CONNECTED_INSTANCE')
    return instance


def literal_site(testbench, message):
    sites = fatal_sites(testbench, [message])
    need(len(sites) == 1, 'UNIQUE_FATAL_SITE:' + message)
    site = dict(sites[0]); offset = sum(len(x) for x in testbench.splitlines(True)[:site['line'] - 1])
    # Existing helper handles named begin blocks; add the enclosing task scope.
    tasks = list(re.finditer(r'\btask\s+(?:automatic\s+)?(\w+)\b[\s\S]*?\bendtask\b', masked(testbench)))
    owners = [m[1] for m in tasks if m.start() <= offset < m.end()]
    need(len(owners) <= 1, 'AMBIGUOUS_TASK_SCOPE')
    if owners:
        site['scope'] = 'Testbench.' + owners[0] + site['scope'][len('Testbench'):]
    return site


def classify(compiled, simulated, log, site=None):
    need(compiled.get('exit_code') == 0 and not compiled.get('timed_out'), 'COMPILE_FAILED')
    need(not simulated.get('timed_out'), 'SIMULATION_TIMEOUT')
    if site is None:
        need(simulated.get('exit_code') == 0 and log.splitlines().count('RISCAY_SOC_PASS') == 1 and
             not re.search(r'FATAL:|ERROR:|DEADLINE|TIMEOUT', log, re.I), 'BASELINE_NO_ACTIVITY_OR_FAILURE')
        return []
    need('RISCAY_SOC_PASS' not in log, 'FAULT_REACHED_PASS')
    records = classify_fatal(compiled, simulated, log, [site])
    need(len(records) == 1 and records[0]['time'] > 0, 'SINGLE_ACTIVE_EXACT_FATAL')
    return records


def mutate_original(texts, manifest, variant, fault, lane=None):
    """Resolve only connected actual RTL; testbench and old assertions never change."""
    need(fault in EXPECTED, 'UNKNOWN_FAULT')
    composed = fault in ('raw-source-reset', 'closed-mask')
    top = manifest['top']; prefix = 'FourPhase' if variant == 'bd' else 'Click'
    expected_top = ('Bd' if variant == 'bd' else 'Click') + 'ResetBoundarySocFixture' if composed else 'QuiescingReceiptFixture'
    need(top == expected_top, 'FIXTURE_TOP')
    top_name = top + '.sv'; owner_name = prefix + 'QuiescingReceipt.sv'
    body = texts[top_name]; owner = texts[owner_name]
    instance = actual_child(manifest, body, 'request_bridge' if composed else 'rx', prefix + 'QuiescingReceipt')
    need(pin_value(body, instance, 'clock') == 'serviceClock', 'RECEIPT_CLOCK')
    field = '_address' if composed else ''; width = 32 if composed else 70
    mask = one(r'wire\s+\[' + str(width-1) + r':0\]\s+(\w+)\s*=\s*(\w+)\s*\?\s*in_bits' +
               field + r"\s*:\s*" + str(width) + r"'h0\s*;", owner, 'EXACT_OUTPUT_MASK')
    value, valid = mask[1], mask[2]
    one(r'assign\s+out_valid\s*=\s*' + re.escape(valid) + r'\s*;', owner, 'MASK_VALID_ALIAS')
    assignment = one(r'assign\s+out_bits' + field + r'\s*=\s*' + re.escape(value) + r'\s*;', owner,
                     'ACTUAL_OUTPUT_ASSIGNMENT')
    if composed:
        output = pin_value(body, instance, 'out_bits_address')
        one(r'assign\s+captured_address\s*=\s*' + re.escape(output) + r'\s*;', body, 'COMPOSED_OBSERVER_ALIAS')
    else:
        need(pin_value(body, instance, 'out_ready') == 'ready' and
             pin_value(body, instance, 'in_bits') == 'data', 'RX_INPUT_READY')
        output = pin_value(body, instance, 'out_bits')
        one(r'assign\s+bits\s*=\s*' + re.escape(output) + r'\s*;', body, 'ACTUAL_OUTPUT_ALIAS')
    name = owner_name; changed = owner
    if fault == 'payload':
        need(type(lane) is int and 0 <= lane < 70, 'PAYLOAD_LANE')
        replacement = f"assign out_bits = {value} ^ ({valid} ? 70'h{1 << lane:x} : 70'h0);"
        changed = owner[:assignment.start()] + replacement + owner[assignment.end():]
    elif fault in ('invalid-mask', 'closed-mask'):
        expression = one(re.escape(valid) + r'\s*\?\s*in_bits' + field + r'\s*:\s*' + str(width) + r"'h0", owner,
                         'UNIQUE_MASK_EXPRESSION')
        changed = owner[:expression.start()] + 'in_bits' + field + owner[expression.end():]
    elif fault == 'work-enable':
        one(r'wire\s+workClock\s*=\s*serviceClock\s*&\s*enabled\s*;', body, 'ACTUAL_WORK_CLOCK')
        one(r'always\s*@\(posedge\s+workClock\s+or\s+posedge\s+reset\)', body, 'ACTUAL_CONSUMER_EDGE')
        ready = one(r'wire\s+ready\s*=\s*allow\s*&\s*enabled\s*;', body, 'ACTUAL_READY_GATE')
        name = top_name; changed = body[:ready.start()] + 'wire ready = allow;' + body[ready.end():]
    else:
        core = actual_child(manifest, body, 'core', prefix + 'Core')
        need(pin_value(body, core, 'reset') == 'nativeCoreReset', 'CORE_RESET_BINDING')
        name = top_name; changed = replace_pin(body, core, 'reset', 'nativeCoreReset | (systemReset & stopWorkClock)')
    need(changed != texts[name], 'NO_MUTATION')
    return name, changed, literal_site(texts['testbench.sv'], EXPECTED[fault])


def bind_fixture(group, recorded):
    root = Path(group['path']).resolve()
    need(file_hashes(root) == recorded, 'FRESH_FIXTURE_HASHES')
    for name in ('contract.json', 'ports.json', 'filelist.f', 'testbench.sv', 'sim.vvp', 'compile.log', 'simulation.log'):
        need(name in recorded, 'FIXTURE_INPUT:' + name)
    contract = read_json(root / 'contract.json'); manifest = contract['manifest']
    need(contract['semantic_sha256'] == hashlib.sha256(json.dumps(manifest, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest(), 'MANIFEST_HASH')
    need(manifest['schema'] == 'chisel-async-contract-v3', 'MANIFEST_SCHEMA')
    for field in ('port_abi', 'probe_abi'):
        entry = manifest[field]; need(recorded.get(entry['file']) == entry['sha256'], 'ABI_HASH')
    listed = [line.strip().replace('\\', '/') for line in (root / 'filelist.f').read_text().splitlines() if line.strip()]
    resources = [Path(p).name for p in manifest['resources']]
    files = list(dict.fromkeys(str(Path(n)).replace('\\', '/') for n in listed + resources))
    need(files and all(not Path(n).is_absolute() and '..' not in Path(n).parts and
         (root / n).resolve().is_relative_to(root) and (root / n).is_file() for n in files), 'LOCAL_COMPILE_INPUTS')
    files = list(dict.fromkeys((root / n).resolve().relative_to(root).as_posix() for n in files))
    need('testbench.sv' not in files and all(n.endswith('.sv') for n in files), 'COMPILE_INVENTORY')
    texts = {n: (root / n).read_text() for n in files + ['testbench.sv']}
    mutations = []
    for fault, lane in cases(group['kind']):
        name, changed, site = mutate(texts, manifest, group['variant'], fault, lane)
        mutations.append(dict(fault=fault, lane=lane, file=name, before_sha256=recorded[name],
                              after_sha256=hashlib.sha256(changed.encode()).hexdigest(), site=site))
    classify(dict(exit_code=0), dict(exit_code=0), (root / 'simulation.log').read_text())
    activity = {}
    if group['kind'] == 'real-gate': activity['gate_phase'] = gate_activity((root / 'simulation.log').read_text(), group['variant'])
    return dict(**group, inputs=recorded, files=files, mutations=mutations,
                oracle_sha256=recorded['testbench.sv'], **activity)


def bind_plan(execution_path, cohort_path, root, gate_graphs_path, checker_successor=None):
    root = root.resolve(); execution_path = execution_path.resolve(); cohort_path = cohort_path.resolve()
    groups = validate_cohort(read_json(cohort_path))
    execution, records, binaries, coverage = bind_execution(execution_path, root, checker_successor)
    fresh = execution['fresh_fixtures_sha256']
    need(all(Path(p).is_absolute() and Path(p).resolve().parent == root / 'build/soc-tests'
             for p in fresh), 'LOCAL_FRESH_FIXTURE_DELTA')
    selected = {str(Path(g['path']).resolve()) for g in groups}
    need(selected <= set(fresh), 'COHORT_NOT_FRESH_DELTA')
    # Every matching control fixture in the exact delta must be selected once.
    candidates = {p for p in fresh if re.fullmatch(
        r'(bd|click)-(retained-quiescing-(walk|invalid|work-stop)|soc-reset-work-stopped|soc-receipt-real-gate-[01])[0-9]+', Path(p).name)}
    need(candidates == selected, 'DUPLICATE_OR_OMITTED_FRESH_CONTROL')
    fixtures = [bind_fixture(g, fresh[str(Path(g['path']).resolve())]) for g in groups]
    from quiescing_gate_control import bind_gate_graphs
    graphs = bind_gate_graphs(gate_graphs_path, execution_path, execution, groups, root)
    if checker_successor is not None:
        checker_successor = Path(checker_successor).resolve()
        before = read_json(gate_graphs_path.parent / 'gate-graphs-before.json')
        gate_receipt = read_json(gate_graphs_path)
        for record in (before, gate_receipt):
            need(record['checker_successor'] == str(checker_successor) and
                 record['checker_successor_sha256'] == sha(checker_successor) and
                 record['current_sources_sha256'] == current_sources(execution, root, checker_successor),
                 'GATE_GRAPH_CHECKER_SUCCESSOR')
    for variant, expected in [('bd', [1]), ('click', [0, 1])]:
        need(sorted(g['gate_phase'] for g in fixtures if g['kind'] == 'real-gate' and g['variant'] == variant) == expected, 'GATE_COMPLETE_PHASES')
    plan = dict(schema='riscay-quiescing-controls-plan-v2', status='BOUND_TO_FRESH_REGRESSION',
        repository=str(root), execution=str(execution_path), cohort=str(cohort_path),
        regression_records=records, cohort_sha256=sha(cohort_path), binaries=binaries,
        gate_graphs=str(gate_graphs_path.resolve()), gate_graph_binding=graphs,
        required_regression=coverage,
        helpers={str(p): sha(p) for p in helper_closure([Path(__file__)])}, fixtures=fixtures,
        baselines=11, faults=151, maximum_compiler_simulator_processes=324)
    if checker_successor is not None:
        plan['checker_successor'] = str(Path(checker_successor).resolve())
    return plan


def validate_plan(plan):
    need(plan.get('schema') == 'riscay-quiescing-controls-plan-v2' and
         plan.get('status') == 'BOUND_TO_FRESH_REGRESSION', 'PLAN_SCHEMA_STATUS')
    need(plan == bind_plan(Path(plan['execution']), Path(plan['cohort']), Path(plan['repository']), Path(plan['gate_graphs']),
                          plan.get('checker_successor')), 'STALE_OR_EDITED_PLAN')


def run_process(command, folder, log_name, timeout):
    started = time.monotonic(); timed_out = False
    process = subprocess.Popen(command, cwd=folder, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=os.name != 'nt')
    try:
        output, _ = process.communicate(timeout=timeout)
    except BaseException as error:
        timed_out = isinstance(error, subprocess.TimeoutExpired)
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, timeout=10, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate(timeout=10)
        if not timed_out:
            (folder / log_name).write_text(output, encoding='utf-8')
            raise
    (folder / log_name).write_text(output, encoding='utf-8')
    return dict(argv=command, exit_code=process.returncode, timed_out=timed_out,
                seconds=time.monotonic()-started, timeout_seconds=timeout), output


def execute(plan, out):
    validate_plan(plan)
    out = out.resolve()
    for g in plan['fixtures']:
        source = Path(g['path']).resolve()
        need(not out.is_relative_to(source) and not source.is_relative_to(out), 'OUTPUT_SOURCE_OVERLAP')
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / 'plan.json', plan)
    records = []; failure = None
    try:
        for g in plan['fixtures']:
            validate_plan(plan)
            source = Path(g['path']); manifest = read_json(source / 'contract.json')['manifest']
            for job in [None] + g['mutations']:
                need(file_hashes(source) == g['inputs'], 'INPUT_CHANGED_BEFORE_CASE')
                label = g['variant'] + '-' + g['kind'] + (('-prefix-' + str(g['prefix'])) if g['kind'] == 'real-gate' else '') + '-' + ('baseline' if job is None else
                        job['fault'] + ('' if job['lane'] is None else '-' + str(job['lane'])))
                folder = out / label; folder.mkdir()
                names = g['files'] + ['testbench.sv', 'contract.json', 'ports.json', 'filelist.f']
                for name in names:
                    target = folder / name; target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source / name, target)
                record = dict(label=label, status='RUNNING', mutation=job, oracle_sha256=g['oracle_sha256'])
                try:
                    if job:
                        texts = {n: (folder / n).read_text() for n in g['files'] + ['testbench.sv']}
                        name, changed, site = mutate(texts, manifest, g['variant'], job['fault'], job['lane'])
                        need(name == job['file'] and site == job['site'] and
                             hashlib.sha256(changed.encode()).hexdigest() == job['after_sha256'], 'MUTATION_REBINDING')
                        (folder / name).write_text(changed, encoding='utf-8', newline='\n')
                    need(sha(folder / 'testbench.sv') == g['oracle_sha256'], 'ORACLE_CHANGED')
                    copied = {n: sha(folder / n) for n in names}
                    record['compiled_inputs_sha256'] = copied
                    compiled, compile_log = run_process([plan['binaries']['iverilog'], '-g2012', '-s', 'Testbench',
                        '-o', 'sim.vvp', *g['files'], 'testbench.sv'], folder, 'compile.log', 60)
                    record['compile'] = compiled
                    need(compiled['exit_code'] == 0 and not compiled['timed_out'], 'COMPILE_FAILED')
                    check_hashes(folder, copied)
                    record['compiled_binary_sha256'] = sha(folder / 'sim.vvp')
                    simulated, log = run_process([plan['binaries']['vvp'], 'sim.vvp'], folder, 'simulation.log', 90)
                    record['simulation'] = simulated
                    record['fatal'] = classify(compiled, simulated, log, None if job is None else job['site'])
                    if g['kind'] == 'real-gate': gate_activity(log, g['variant'], g['gate_phase'], fault=job is not None)
                    check_hashes(folder, copied)
                    need(sha(folder / 'sim.vvp') == record['compiled_binary_sha256'], 'EXECUTED_BINARY_CHANGED')
                    need(sha(folder / 'testbench.sv') == g['oracle_sha256'] and file_hashes(source) == g['inputs'],
                         'ORACLE_OR_SOURCE_CHANGED_AFTER_CASE')
                    record['status'] = 'PASS'
                except BaseException as error:
                    record.update(status='FAIL_OR_INCOMPLETE', error=repr(error))
                    raise
                finally:
                    record['evidence_sha256'] = file_hashes(folder)
                    write_json(folder / 'receipt.json', record); records.append(record)
        validate_plan(plan)
        need(len(records) == 162 and sum(r['mutation'] is None for r in records) == 11 and
             sum(r['mutation'] is not None for r in records) == 151, 'CASE_COUNT')
    except BaseException as error:
        failure = repr(error)
    write_json(out / 'receipt.json', dict(status='PASS_EXACT_DIGITAL_CONTROLS' if failure is None else 'FAIL_OR_INCOMPLETE',
        failure=failure, records=records, plan_sha256=sha(out / 'plan.json'),
        limits='Exact digital fixture faults only; full regression, strict actual graph/POR, physical aperture and cost gates remain separate.'))
    need(failure is None, 'CAMPAIGN_FAILED:' + str(failure))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    binder = sub.add_parser('bind')
    binder.add_argument('--execution', type=Path, required=True); binder.add_argument('--cohort', type=Path, required=True)
    binder.add_argument('--repository', type=Path, required=True); binder.add_argument('--out', type=Path, required=True)
    binder.add_argument('--gate-graphs', type=Path, required=True)
    binder.add_argument('--checker-successor', type=Path)
    runner = sub.add_parser('run'); runner.add_argument('--plan', type=Path, required=True); runner.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'bind':
        write_json(args.out, bind_plan(args.execution, args.cohort, args.repository, args.gate_graphs, args.checker_successor))
    else:
        execute(read_json(args.plan), args.out)


if __name__ == '__main__':
    main()

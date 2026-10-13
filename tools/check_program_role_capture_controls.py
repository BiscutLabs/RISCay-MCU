# SPDX-License-Identifier: Apache-2.0
"""Composed program role/capture controls on frozen, real ProgramSource fixtures.

The existing ns testbench and all its assertions remain intact. Added monitors
run in a separate 1 fs module and inspect actual EventRegister pins. CPU/loader
identity comes from the independent driver at word acceptance, never DUT role or
permission. This is digital integration evidence, not physical qualification.

The fixed inventory is eight fixtures per variant and three profiles: original,
slow source/fast return, and fast source/slow return. Only declared 1 ns variable
cells vary within 1..10 ns; data budgets and fixed guards retain their values.
All two BD and seven Click custom EventRegisters receive monitors. Forty-eight
fixture/profile positives plus nine legal 100 ps distributions accompany 45
pin timing faults, two independent permission-data faults and two actual
eligibility-reset binding faults (106 total). The original 104 cases remain. The
clocked fixtures retain their original service frequency and small capacities;
this is not a random-skew, whole-chip or configuration-complete qualification.
"""
import argparse
import copy
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from check_admission_controls import replace_pin
from check_capture_pins import capture_monitors
from check_program_return_contract import (CAPTURES, FIXED_GUARDS, MODEL_HASHES,
    validate_program_return, validate_program_return_rtl)
from check_program_return_fatals import fatal_sites, classify_fatal
from check_program_source_export import validate_program_source
from check_recovery_capture_controls import pin_expression, extra_wires
from check_i2c_wiring_controls import hashes

FIXTURES = ('late', 'effects', 'publication', 'busy', 'commit', 'roles', 'loader_reset', 'cpu_reset')
PROFILES = ('original', 'source-slow-return-fast', 'source-fast-return-slow')
PREFIX = 'PROGRAM_ROLE_CAPTURE'


def require(value, message):
    if not value:
        raise ValueError(PREFIX + '_' + message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def nodes(node):
    yield node
    for child in node.get('children', []):
        yield from nodes(child['contract'])


def resolve_node(node, top, references):
    result = copy.deepcopy(node)
    for sub in nodes(result):
        for endpoint in sub['endpoints']:
            name = 'ref_' + top + '_' + endpoint['probe']
            require(name in references, 'REFERENCE:' + name)
            path = top + '.' + references[name]
            require(path.startswith(sub['rtl_path'] + '.'), 'REFERENCE_OWNER:' + name)
            endpoint['rtl_path'] = path
    return result


def load_fixture(source, variant):
    source = Path(source).resolve()
    manifest = json.loads((source / 'contract.json').read_text())['manifest']
    top = 'ClickProgramSourceFixture' if variant == 'click' else 'BdProgramSourceFixture'
    require(manifest['top'] == top, 'FIXTURE_TOP')
    require(manifest['schema'] == 'chisel-async-contract-v3' and manifest['time_unit'] == 'fs', 'MANIFEST')
    ref = source / ('ref_' + top + '.sv')
    require(manifest['probe_abi'] == dict(file=ref.name, sha256=sha(ref)), 'PROBE_HASH')
    require(manifest['port_abi'] == dict(file='ports.json', sha256=sha(source / 'ports.json')), 'PORT_HASH')
    definitions = re.findall(r'^`define\s+(\w+)\s+([\w.]+)\s*$', ref.read_text(), re.M)
    require(len(definitions) == len(dict(definitions)), 'DUPLICATE_REFERENCE')
    references = dict(definitions)
    coordinated = [e for e in manifest['design']['endpoints'] if e['id'] == 'native_application_reset']
    require(len(coordinated) == 1 and coordinated[0]['width'] == 1 and
            coordinated[0]['source'] == '~|' + top + '>nativeApplicationReset', 'PRESENTATION_RESET_ENDPOINT')
    reference = 'ref_' + top + '_' + coordinated[0]['probe']
    require(reference in references and references[reference] == 'nativeApplicationReset',
            'PRESENTATION_RESET_REFERENCE')
    presentation_reset = top + '.' + references[reference]
    children = {c['id']: c['contract'] for c in manifest['design']['children']}
    require({'program_source', 'program_return', 'program_access'} <= children.keys(), 'OWNERS')
    owner = children['program_source']
    require(validate_program_source(owner) == (variant == 'click'), 'SOURCE_VARIANT')
    returned = children['program_return']
    require(validate_program_return(returned) == variant, 'RETURN_VARIANT')
    owner = resolve_node(owner, top, references)
    returned = resolve_node(returned, top, references)
    local = ''.join('`define ref_' + returned['module'] + '_ca_p_' + str(len(e['id'])) + '_' + e['id'] +
                    ' ' + e['rtl_path'].rsplit('.', 1)[1] + '\n' for e in returned['endpoints'])
    boundary = validate_program_return_rtl(returned, (source / (returned['module'] + '.sv')).read_text(), local, resolved=True)
    for model in {p['model'] for p in returned['primitives']}:
        require(sha(source / (model + '.sv')) == MODEL_HASHES[model] and
                manifest['resources']['chiselasync/sv/' + model + '.sv'] == MODEL_HASHES[model], 'MODEL:' + model)
    original = (source / 'testbench.sv').read_text()
    require(original.count('module Testbench;') == original.count('endmodule') == 1, 'ORACLE_MODULE')
    require(original.count('$display("RISCAY_SOC_PASS");') == 1 and
            'timeunit 1ns; timeprecision 1ps;' in original, 'ORACLE_TIME_OR_PASS')
    require(re.search(r'task host_write\([^;]+;\s*begin\s*loaderWordPending=1;', original) and
            re.search(r'task offer_read;\s*begin\s*loaderWordPending=0;', original), 'INDEPENDENT_ROLE_DRIVER')
    require('always @(posedge observedWorkClock)' in original and 'if(wordAccepted)' in original, 'WORD_ACCEPTANCE_DRIVER')
    log = (source / 'simulation.log').read_text()
    require(log.splitlines().count('RISCAY_SOC_PASS') == 1 and not re.search(r'FATAL:|TIMEOUT|DEADLINE|\bERROR\b', log), 'SOURCE_NOT_PASS')
    files = [line.strip() for line in (source / 'filelist.f').read_text().splitlines() if line.strip()]
    require(len(files) == len(set(files)), 'FILELIST_DUPLICATE')
    require(all((source / name).resolve().is_relative_to(source) and (source / name).is_file() for name in files), 'FILELIST_PATH')
    return dict(source=source, manifest=manifest, owner=owner, returned=returned,
                boundary=boundary, original=original, files=files, presentation_reset=presentation_reset)


def skew(original, owner, returned, profile):
    require(profile in PROFILES, 'PROFILE')
    if profile == 'original':
        return original, {}
    existing = dict(re.findall(r'defparam\s+(\S+)\s*=\s*(\d+)\s*;', original))
    changes = {}
    for tree, slow in ((owner, profile == 'source-slow-return-fast'), (returned, profile == 'source-fast-return-slow')):
        for node in nodes(tree):
            for cell in node['primitives']:
                # Data budgets and fixed guards are retained exactly. Vary only
                # the declared 1 ns control/register cells within 1..10 ns.
                if cell['id'] in FIXED_GUARDS or cell['parameters'].get('DELAY_FS') != '1000000':
                    continue
                name = 'dut.' + cell['rtl_path'].split('.', 1)[1] + '.DELAY_FS'
                value = '10000000' if slow else '1000000'
                pattern = r'\bdefparam\s+' + re.escape(name) + r'\s*=\s*\d+\s*;'
                require(len(re.findall(pattern, original)) <= 1, 'DUPLICATE_DELAY')
                if name in existing:
                    original = re.sub(pattern, 'defparam ' + name + '=' + value + ';', original)
                else:
                    anchor = 'timeunit 1ns; timeprecision 1ps;'
                    require(original.count(anchor) == 1, 'SKEW_TIME_ANCHOR')
                    original = original.replace(anchor, anchor + '\n' + 'defparam ' + name + '=' + value + ';', 1)
                changes[name] = dict(before=existing.get(name, '1000000'), after=value)
    require(changes, 'EMPTY_SKEW')
    after = dict(re.findall(r'defparam\s+(\S+)\s*=\s*(\d+)\s*;', original))
    require(all(after[name] == value for name, value in existing.items() if name not in changes), 'FIXED_DELAY_CHANGED')
    return original, changes


def absolute(path):
    return 'Testbench.dut.' + path.split('.', 1)[1]


def role_monitors(owner, returned, variant, presentation_reset):
    e = {p['id']: absolute(p['rtl_path']) for p in owner['endpoints']}
    r = {p['id']: absolute(p['rtl_path']) for p in returned['endpoints']}
    cells = {p['id']: p for p in returned['primitives']}
    src = {p['id']: absolute(p['rtl_path']) for p in owner['primitives']}
    capture = absolute(cells['payload']['rtl_path']) + '.trigger'
    permission = absolute(cells['permission']['rtl_path'])
    # Cancellation follows the expected POR/coordinated presentation inputs,
    # never the observed eligibility value or the register reset pin itself.
    # Explicit binding checks prevent a rewired reset from redefining the oracle.
    expected_reset = f"({e['reset']} | {e['application_reset']})"
    coordinated_reset = absolute(presentation_reset)
    owned = (f"({src['owned']}.q === 1'b1 && {src['armed_phase']}.q[0] === {e['reserved']})"
             if variant == 'click' else f"({e['reserved']} === 1'b1)")
    monitors = capture_monitors(returned, CAPTURES[variant], PREFIX).replace('dut.', 'Testbench.dut.')
    # Epoch checks exempt only the particular register's reset. POR data checks
    # continue even when presentation is cancelled by application reset.
    for name in CAPTURES[variant]:
        cell = cells[name]; path = absolute(cell['rtl_path']); width = int(cell['parameters']['WIDTH'])
        monitors += f'''
integer q_{name}_reset=0, q_{name}_capture=0, q_{name}_checked=0;
always @(posedge {path}.reset) q_{name}_reset=q_{name}_reset+1;
task automatic check_q_{name}(input [{width-1}:0] data, input integer reset_epoch, input integer capture_epoch);
begin
  #({path}.DELAY_FS+1);
  if({path}.reset === 1'b0 && q_{name}_reset==reset_epoch && q_{name}_capture==capture_epoch) begin
    if({path}.q !== data) $fatal(1,"{PREFIX}_CAPTURED_DATA:{name}");
    q_{name}_checked=q_{name}_checked+1;
  end
end
endtask
always @(posedge {path}.trigger) if({path}.reset === 1'b0) begin
  if((^{path}.d) === 1'bx) $fatal(1,"{PREFIX}_UNKNOWN_DATA:{name}");
  q_{name}_capture=q_{name}_capture+1;
  fork check_q_{name}({path}.d,q_{name}_reset,q_{name}_capture); join_none
end
'''
    monitors += f'''
wire role_presentation_reset={expected_reset};
always @({e['reset']} or {e['application_reset']} or {e['eligibility_reset']} or
         {src['eligibility']}.reset or {r['reset']} or {r['application_reset']} or
         {coordinated_reset} or Testbench.reset) begin
  #1;
  if({e['reset']} !== Testbench.reset || {r['reset']} !== Testbench.reset ||
     {e['application_reset']} !== {coordinated_reset} || {r['application_reset']} !== {coordinated_reset} ||
     {e['eligibility_reset']} !== {expected_reset} || {src['eligibility']}.reset !== {expected_reset})
    $fatal(1,"{PREFIX}_RESET_BINDING");
end
reg role_valid=0, role_loader=0, role_cancelled=0, role_captured=0;
integer role_commits=0, role_captures=0, role_cpu=0, role_loaders=0, role_cancellations=0;
integer role_loader_phase0=0, role_loader_phase1=0;
reg captured_permission, expected_permission;
integer permission_reset_epoch;
always @(posedge Testbench.reset) begin
  role_valid=0;role_loader=0;role_cancelled=0;role_captured=0;
end
always @(posedge Testbench.observedWorkClock) if(!Testbench.reset && Testbench.wordAccepted) begin
  if(role_valid) $fatal(1,"{PREFIX}_WORD_REUSE");
  role_valid=1;role_loader=Testbench.loaderWordPending;
  role_cancelled=role_presentation_reset;role_captured=0;role_commits=role_commits+1;
end
always @(posedge role_presentation_reset) if(!Testbench.reset && role_valid && !role_cancelled) begin
  role_cancelled=1;role_cancellations=role_cancellations+1;
end
always @(posedge {r['idle']}) if(!Testbench.reset && role_captured) role_valid=0;
always @(posedge {capture}) if(!Testbench.reset) begin
  #1;
  if(!role_valid || role_captured) $fatal(1,"{PREFIX}_UNCOMMITTED_CAPTURE");
  if({e['owner_loader']} !== role_loader) $fatal(1,"{PREFIX}_RETAINED_ROLE");
  if(!{owned}) $fatal(1,"{PREFIX}_OWNER_ARM_IDENTITY");
  if({r['eligible']} !== (!role_loader && !role_cancelled && !role_presentation_reset))
    $fatal(1,"{PREFIX}_COMPOSED_PERMISSION");
  role_captured=1;role_captures=role_captures+1;
  if(role_loader) begin
    role_loaders=role_loaders+1;
    if(Testbench.nativeResponsePhase) role_loader_phase1=role_loader_phase1+1;
    else role_loader_phase0=role_loader_phase0+1;
  end else role_cpu=role_cpu+1;
end
always @(posedge {permission}.trigger) if({permission}.reset === 1'b0) begin
  captured_permission={permission}.d;
  expected_permission=(!role_loader && !role_cancelled && !role_presentation_reset);
  permission_reset_epoch=q_permission_reset;
  #1;
  if({permission}.reset === 1'b0 && q_permission_reset==permission_reset_epoch &&
      captured_permission !== expected_permission)
    $fatal(1,"{PREFIX}_PERMISSION_DATA");
end
'''
    return monitors


def instrument(original, owner, returned, variant, fixture, presentation_reset):
    monitors = role_monitors(owner, returned, variant, presentation_reset)
    activity = '\n'.join(f'$display("{PREFIX}_ACTIVITY:{n}:%0d:%0d",pc_{n}_count,q_{n}_checked);' for n in CAPTURES[variant])
    activity += f'''
if(role_commits==0 || role_commits!=role_captures) $fatal(1,"{PREFIX}_CAPTURE_COUNT");
$display("{PREFIX}_ROLES:%0d:%0d:%0d:%0d:%0d:%0d",role_commits,role_cpu,role_loaders,role_cancellations,role_loader_phase0,role_loader_phase1);
'''
    if fixture == 'roles':
        activity += f'if(role_cpu!=6 || role_loaders!=4) $fatal(1,"{PREFIX}_ROLE_ACTIVITY");\n'
        if variant == 'click':
            activity += f'if(!role_loader_phase0 || !role_loader_phase1) $fatal(1,"{PREFIX}_PHASE_ACTIVITY");\n'
        for name in CAPTURES[variant]:
            activity += f'if(!pc_{name}_count || !q_{name}_checked) $fatal(1,"{PREFIX}_INACTIVE:{name}");\n'
    module = ('\nmodule ProgramRoleCaptureChecks;\ntimeunit 1fs; timeprecision 1fs;\n' + monitors +
              '\ntask finish_checks; begin\n' + activity + '\nend endtask\nendmodule\n')
    require(original.count('$display("RISCAY_SOC_PASS");') == 1, 'PASS_ANCHOR')
    require(original.count('timeunit 1ns; timeprecision 1ps;') == 1, 'TIME_ANCHOR')
    result = original.replace('timeunit 1ns; timeprecision 1ps;',
        'timeunit 1ns; timeprecision 1ps;\nProgramRoleCaptureChecks program_role_checks();', 1)
    result = result.replace('$display("RISCAY_SOC_PASS");', 'program_role_checks.finish_checks();\n$display("RISCAY_SOC_PASS");', 1)
    require(result.replace('ProgramRoleCaptureChecks program_role_checks();\n', '', 1).replace(
        'program_role_checks.finish_checks();\n', '', 1) == original, 'ORACLE_CHANGED')
    return result + module


def assertion_sites(test, expected):
    start = test.index('module ProgramRoleCaptureChecks;')
    found = fatal_sites(test[start:], expected)
    offset = test.count('\n', 0, start)
    for site in found:
        site['line'] += offset
        site['scope'] = site['scope'].replace('Testbench', 'Testbench.program_role_checks', 1)
    return found


def classify_result(compiled, simulated, log, sites=None):
    require(not re.search(r'RISCAY_SOC_PASS|PROGRAM_ROLE_CAPTURE_CONTROLS_PASS', log) if sites else True, 'MIXED_PASS_FAULT')
    if sites:
        return classify_fatal(compiled, simulated, log, sites)
    require(compiled.get('exit_code') == 0 and simulated.get('exit_code') == 0 and
            not compiled.get('timed_out') and not simulated.get('timed_out'), 'POSITIVE_EXIT')
    require(log.splitlines().count('RISCAY_SOC_PASS') == 1 and
            not re.search(r'FATAL:|TIMEOUT|DEADLINE|\bERROR\b', log, re.I), 'POSITIVE_LOG')
    return []


def mutation(text, node, name, kind):
    cell = next(c for c in node['primitives'] if c['id'] == name)
    instance = cell['rtl_path'].rsplit('.', 1)[1]
    trigger = pin_expression(text, instance, 'trigger')
    width = cell['parameters']['WIDTH']
    if kind == 'reset-binding':
        require(name == 'eligibility', 'RESET_MUTATION_OWNER')
        return replace_pin(text, instance, 'reset', 'reset'), PREFIX + '_RESET_BINDING'
    if kind == 'setup':
        return replace_pin(text, instance, 'd', '{' + width + '{' + trigger + '}}'), PREFIX + '_SETUP:' + name
    if kind == 'role-data':
        return replace_pin(text, instance, 'd', "1'b1"), PREFIX + '_PERMISSION_DATA'
    if kind == 'hold':
        text = replace_pin(text, instance, 'd', '{' + width + '{role_late_clock}}')
        wires = 'wire role_late_clock;'
        assignments = f'assign #100000 role_late_clock = {trigger};'
    else:
        text = replace_pin(text, instance, 'trigger', 'role_test_clock')
        wires = 'wire role_test_clock,role_late_clock,role_second_clock;'
        if kind in ('skew', 'legal-skew'):
            assignments = f'assign #{100000 if kind == "legal-skew" else 100001} role_test_clock = {trigger};'
        elif kind == 'high':
            assignments = f'assign #100000 role_late_clock = {trigger};\nassign role_test_clock = {trigger} & ~role_late_clock;'
        elif kind == 'low':
            assignments = (f'assign #1000000 role_late_clock = {trigger};\nassign #1100000 role_second_clock = {trigger};\n'
                           f'assign role_test_clock = {trigger} & (~role_late_clock | role_second_clock);')
        else:
            raise ValueError(PREFIX + '_MUTATION_KIND')
    expected = None if kind == 'legal-skew' else PREFIX + '_' + {
        'hold': 'HOLD', 'high': 'PULSE_HIGH', 'low': 'PULSE_LOW', 'skew': 'SKEW'}[kind] + ':' + name
    return extra_wires(text, node['module'], wires, assignments), expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True, help='Frozen BD/Click mapping, each with the eight FIXTURES keys')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    sources = json.loads(args.sources.read_text())
    require(set(sources) == {'bd', 'click'} and all(set(x) == set(FIXTURES) for x in sources.values()), 'SOURCE_INVENTORY')
    loaded = {v: {label: load_fixture(path, v) for label, path in group.items()} for v, group in sources.items()}
    paths = [r['source'] for group in loaded.values() for r in group.values()]
    require(len(paths) == len(set(paths)), 'DUPLICATE_SOURCE')
    out = args.out.resolve()
    require(all(not out.is_relative_to(p) and not p.is_relative_to(out) for p in paths), 'OUTPUT_OVERLAP')
    out.mkdir(parents=True, exist_ok=False)
    originals = {str(path): hashes(path) for path in paths}
    tools = [Path(__file__).with_name(name) for name in (
        'check_program_role_capture_controls.py', 'test_program_role_capture_controls.py',
        'check_program_return_contract.py', 'check_program_source_export.py',
        'check_program_return_fatals.py', 'check_capture_pins.py', 'check_admission_controls.py',
        'check_recovery_capture_controls.py', 'check_i2c_wiring_controls.py')]
    tool_hashes = {str(path.resolve()): sha(path) for path in tools}
    records = dict(status='RUNNING', scope='composed digital role and actual capture pins; physical qualification open',
                   sources= sources, source_index_sha256=sha(args.sources), source_sha256=originals,
                   tool_sha256=tool_hashes, cases={})
    commands = []

    def save():
        (out / 'results.json').write_text(json.dumps(records, indent=2) + '\n')
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')

    def run(command, case, logname):
        commands.append(dict(cwd=str(case), argv=command, log=str(case / logname)))
        start = time.monotonic()
        try:
            result = subprocess.run(command, cwd=case, text=True, capture_output=True, timeout=60)
            log = result.stdout + result.stderr
            outcome = dict(exit_code=result.returncode, seconds=time.monotonic() - start, timed_out=False)
        except subprocess.TimeoutExpired as error:
            log = 'PROCESS_TIMEOUT\n' + str(error.stdout or '') + str(error.stderr or '')
            outcome = dict(exit_code=None, seconds=time.monotonic() - start, timed_out=True)
        (case / logname).write_text(log)
        outcome.update(log=str(case / logname), sha256=sha(case / logname))
        return outcome, log

    def simulate(variant, label, profile, fault=None):
        fixture = loaded[variant][label]
        name = variant + '-' + label + '-' + profile + (('-' + '-'.join(fault)) if fault else '')
        case = out / name
        shutil.copytree(fixture['source'], case)
        test, delays = skew(fixture['original'], fixture['owner'], fixture['returned'], profile)
        test = instrument(test, fixture['owner'], fixture['returned'], variant, label, fixture['presentation_reset'])
        (case / 'testbench.sv').write_text(test)
        expected = None
        if fault:
            cell, kind = fault
            mutated_owner = fixture['owner'] if kind == 'reset-binding' else fixture['returned']
            rtl = case / (mutated_owner['module'] + '.sv')
            changed, expected = mutation(rtl.read_text(), mutated_owner, cell, kind)
            rtl.write_text(changed)
        entry = dict(source=str(fixture['source']), profile=profile, delay_changes=delays, fault=fault,
                     presentation_reset=fixture['presentation_reset'],
                     expected=expected, original_oracle_sha256=sha(fixture['source'] / 'testbench.sv'),
                     oracle_sha256=sha(case / 'testbench.sv'), existing_assertions_preserved=True,
                     source_sha256={f: sha(case / f) for f in fixture['files']},
                     exact_assertion_sites=assertion_sites(test, [expected]) if expected else [])
        records['cases'][name] = entry
        save()
        files = [str((case / f).resolve()) for f in fixture['files']]
        entry['compile'], log = run(['iverilog', '-g2012', '-s', 'Testbench', '-o', 'role-capture.vvp', *files, 'testbench.sv'], case, 'role-compile.log')
        save()
        require(entry['compile']['exit_code'] == 0, 'COMPILE:' + name + ':' + log[-2000:])
        entry['compiled_vvp_sha256'] = sha(case / 'role-capture.vvp')
        entry['simulation'], log = run(['vvp', 'role-capture.vvp'], case, 'role-simulation.log')
        save()
        entry['actual_fatals'] = classify_result(entry['compile'], entry['simulation'], log, entry['exact_assertion_sites'])
        entry['activity'] = [line for line in log.splitlines() if line.startswith(PREFIX + '_ACTIVITY:') or line.startswith(PREFIX + '_ROLES:')]
        require(sha(case / 'testbench.sv') == entry['oracle_sha256'], 'ORACLE_CHANGED_AFTER_COMPILE')
        require(sha(case / 'role-capture.vvp') == entry['compiled_vvp_sha256'], 'BINARY_CHANGED_AFTER_RUN')
        entry['status'] = 'PASS'
        save()
        print(name, 'PASS', flush=True)

    try:
        save()
        for variant in ('bd', 'click'):
            for label in FIXTURES:
                for profile in PROFILES:
                    simulate(variant, label, profile)
            for cell in CAPTURES[variant]:
                for kind in ('legal-skew', 'setup', 'hold', 'high', 'low', 'skew'):
                    simulate(variant, 'roles', 'original', (cell, kind))
            simulate(variant, 'roles', 'original', ('permission', 'role-data'))
            simulate(variant, 'roles', 'original', ('eligibility', 'reset-binding'))
        require(all(hashes(Path(p)) == values for p, values in originals.items()), 'ORIGINAL_CHANGED')
        require(all(sha(p) == value for p, value in tool_hashes.items()), 'TOOL_CHANGED')
        require(len(records['cases']) == 106, 'CAMPAIGN_INVENTORY')
        records.update(status='PASS', positive_cases=57, negative_cases=49, originals_preserved=True)
    except BaseException as error:
        records.update(status='FAILED', error=repr(error))
        save()
        raise
    save()
    print('PROGRAM_ROLE_CAPTURE_CONTROLS_PASS', flush=True)


if __name__ == '__main__':
    main()

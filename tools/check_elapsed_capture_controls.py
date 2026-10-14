# SPDX-License-Identifier: Apache-2.0
"""Replay the complete A1b cohort with actual history pins and exact-fatal controls.

These are digital model checks, not physical setup/hold or reset signoff. Every
original assertion remains in each replay. The source manifest must identify one
completed AsyncElapsedLoopSpec cohort; discovery by newest directory is forbidden.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import re
import shutil
from pathlib import Path

from check_capture_pins import capture_monitors
from check_i2c_wiring_controls import hashes, run

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'ELAPSED_CAPTURE'
CAPTURES = {'history': None}
FIXTURES = {
    variant: {'nibbles-normal', 'nibbles-extreme'} |
             {f'por-nibble-{i}' for i in range(8)} |
             ({'external-return', 'por-return-command', 'por-return-reply', 'por-reply-fall', 'por-command-fall'}
              if variant == 'bd' else {'early-next', 'por-phase-zero'})
    for variant in ('bd', 'click')}
IDENTITY_FILES = (
    'designs/four-phase-bd/src/main/scala/riscay/bd/ConstantScaling.scala',
    'designs/two-phase-click/src/main/scala/riscay/click/ConstantScaling.scala',
    'soc/src/main/scala/riscay/soc/ScalingSchema.scala',
    'verification/src/test/scala/riscay/AsyncElapsedLoopSpec.scala',
    '../chisel-async/src/main/resources/chiselasync/sv/ChiselAsyncEventRegister_v1.sv',
    '../chisel-async/src/main/resources/chiselasync/sv/ChiselAsyncXor_v1.sv',
    '../chisel-async/src/main/scala/chiselasync/testing/AsyncTest.scala')
# Every nonuniform assignment of minimum/maximum owner, step and publication
# delays. Uniform minimum and maximum are already original seeds 1 and 2.
PROFILES = tuple(x for x in itertools.product(('min', 'max'), repeat=3) if len(set(x)) > 1)
MUTATIONS = {
    'setup': 'ELAPSED_CAPTURE_SETUP:history',
    'hold': 'ELAPSED_CAPTURE_HOLD:history',
    'high': 'ELAPSED_CAPTURE_PULSE_HIGH:history',
    'low': 'ELAPSED_CAPTURE_PULSE_LOW:history',
    'skew': 'ELAPSED_CAPTURE_SKEW:history',
    'missing': 'ELAPSED_HISTORY_MISSING_CAPTURE',
    'rising-only': 'ELAPSED_HISTORY_MISSING_CAPTURE',
    'data': 'ELAPSED_HISTORY_D_BINDING',
    'q': 'ELAPSED_HISTORY_Q_VALUE',
    'output': 'ELAPSED_HISTORY_OUTPUT_BINDING',
}


def require(condition, message):
    if not condition:
        raise ValueError(PREFIX + '_' + message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def one(values, label):
    require(len(values) == 1, 'CARDINALITY:' + label)
    return values[0]


def clean(text):
    return re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.S)


def compact(text):
    return re.sub(r'\s+', '', text)


def primitive(node, name):
    return one([p for p in node['primitives'] if p['id'] == name], name)


def child(node, name):
    return one([c['contract'] for c in node['children'] if c['id'] == name], name)


def hierarchy(path):
    return 'dut.' + path.split('.', 1)[1]


def instance_block(text, instance):
    return one(list(re.finditer(r'\b' + re.escape(instance) + r'\s*\((.*?)\n\s*\);', text, re.S)), instance)


def pin(text, instance, name):
    block = instance_block(clean(text), instance)
    return compact(one(re.findall(r'\.' + re.escape(name) + r'\s*\(([^()]*)\)', block[1]), instance + '.' + name))


def replace_pin(text, instance, name, expression):
    block = instance_block(text, instance)
    changed, count = re.subn(r'(\.' + re.escape(name) + r'\s*\()([^()]*)(\))',
                            lambda m: m[1] + expression + m[3], block[0])
    require(count == 1, 'REPLACE_PIN:' + name)
    return text[:block.start()] + changed + text[block.end():]


def add_wires(text, top, statements):
    header = one(list(re.finditer(r'\bmodule\s+' + re.escape(top) + r'\b.*?\);', text, re.S)), top)
    declarations = '\n'.join(line for line in statements.splitlines() if line.startswith('wire '))
    assignments = '\n'.join(line for line in statements.splitlines() if not line.startswith('wire '))
    end = one(list(re.finditer(r'\bendmodule\b', text)), 'TOP_END')
    # Icarus requires referenced generated nets to be declared before assigns.
    text = text[:end.start()] + assignments + '\n' + text[end.start():]
    return '`timescale 1fs/1fs\n' + text[:header.end()] + '\n' + declarations + '\n' + text[header.end():]


def aliases(text):
    """Only resolve single continuous wire drivers, never arbitrary logic."""
    found = re.findall(r'\b(?:assign|wire\s*(?:\[[^]]+\]\s*)?)\s+(\w+)\s*=\s*([^;]+);', clean(text))
    result = {}
    for name, expression in found:
        require(name not in result, 'MULTIPLE_DRIVER:' + name)
        result[name] = compact(expression)
    return result


def resolve(expression, drivers, seen=()):
    # Substitute identifier aliases, preserving literals and bit selections.
    def substitute(match):
        name = match[0]
        if name not in drivers:
            return name
        require(name not in seen, 'ALIAS_CYCLE:' + name)
        return resolve(drivers[name], drivers, seen + (name,))
    return re.sub(r'(?<![\w\'])\b[A-Za-z_]\w*\b', substitute, compact(expression))


def source_port(export, node, channel, field, width=None):
    source = f'~|{node["module"]}>{channel}.{field}'
    if field.startswith('bits'):
        ch = one([c for c in node['channels'] if c['id'] == channel], channel)
        layout = one([f for f in ch['layout'] if f['field'] == field], field)
        require(layout['source'] == source and not layout['signed'], 'LAYOUT_SOURCE:' + field)
        if width is not None:
            require(layout['width'] == width, 'LAYOUT_WIDTH:' + field)
        width = layout['width']
    abi = json.loads((export / 'ports.json').read_text())
    owner = one([n for n in abi['nodes'] if n['rtl_path'] == node['rtl_path']], 'ABI_NODE')
    port = one([p for p in owner['ports'] if p['source'] == source], 'ABI_PORT:' + field)
    require(port['width'] == width and not port['signed'] and not port['clock'], 'ABI_SHAPE:' + field)
    output = (channel == 'out') != (field == 'ack')
    require(port['direction'] == ('output' if output else 'input'), 'ABI_DIRECTION:' + field)
    name = re.sub(r'[.\[]', '_', channel + '.' + field).replace(']', '')
    rtl = clean((export / (node['module'] + '.sv')).read_text())
    declared = one(re.findall(r'\b(input|output)\s+(?:wire\s+)?(\[\d+:\d+\]\s*)?' + re.escape(name) + r'\b', rtl), 'ACTUAL_PORT:' + field)
    declared_width = 1 if not declared[1] else int(re.findall(r'\d+', declared[1])[0]) + 1
    require(declared[0] == port['direction'] and declared_width == width, 'ACTUAL_PORT_SHAPE:' + field)
    return name


def bindings(export):
    export = Path(export)
    document = json.loads((export / 'contract.json').read_text())
    manifest = document['manifest']; node = manifest['design']; top = manifest['top']
    require(top in ('FourPhaseElapsed', 'ClickElapsed') and node['module'] == top, 'OWNER')
    require(document['semantic_sha256'] == hashlib.sha256(json.dumps(manifest, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest(), 'MANIFEST_HASH')
    for key in ('probe_abi', 'port_abi'):
        require(sha(export / manifest[key]['file']) == manifest[key]['sha256'], 'ABI_HASH:' + key)
    for name, digest in manifest['rtl_semantic_sha256'].items():
        text = (export / name).read_text()
        normalized = '\n'.join(line.split('\t//', 1)[0].rstrip() for line in text.splitlines()).rstrip() + '\n'
        require(hashlib.sha256(normalized.encode()).hexdigest() == digest, 'RTL_HASH:' + name)
    # Resources contain the generated firtool banner; resource hashes omit it.
    for name, digest in manifest['resources'].items():
        resource = (export / Path(name).name).read_text()
        resource = re.sub(r'^// Generated by CIRCT[^\n]*\n', '', resource)
        require(hashlib.sha256(resource.rstrip().encode() + b'\n').hexdigest() == digest, 'RESOURCE_HASH:' + name)
    for model in ('ChiselAsyncEventRegister_v1', 'ChiselAsyncXor_v1'):
        resource = 'chiselasync/sv/' + model + '.sv'
        if resource in manifest['resources']:
            require(manifest['resources'][resource] == sha(ROOT.parent / 'chisel-async/src/main/resources' / resource), 'MODEL_SOURCE:' + model)
    click = top == 'ClickElapsed'; history = primitive(node, 'history')
    require({p['id'] for p in node['primitives'] if p['model'] == 'ChiselAsyncEventRegister_v1'} == {'history'}, 'HISTORY_INVENTORY')
    require(history['parameters'] == {'DELAY_FS': '1000000', 'RESET_VALUE': '0', 'WIDTH': '2'} and
            history['reset_domain'] == 'root' and history['reset'] == 'reset', 'HISTORY_SHAPE')
    require(set(c['id'] for c in node['children']) == {'owner', 'step'}, 'CHILD_INVENTORY')
    timing = one([t for t in node['timing'] if t['id'] == 'history_aperture'], 'APERTURE')
    require(timing['setup_fs'] == timing['hold_fs'] == '100000' and timing['capture'] == 'publication_event', 'APERTURE')
    rtl = (export / (top + '.sv')).read_text(); stripped = clean(rtl); drivers = aliases(rtl)
    owner = child(node, 'owner'); instance = owner['rtl_path'].rsplit('.', 1)[1]
    require(bool(re.search(r'\b' + re.escape(owner['module']) + r'\s+' + re.escape(instance) + r'\s*\(', stripped)), 'ACTUAL_OWNER_MODEL')
    ports = {}
    for field in ('req', 'ack', 'bits.commandPhase', 'bits.replyPhase'):
        local = source_port(export, owner, 'out', field, 1)
        # out.ack is an input even though the channel carries output payload.
        ports[field] = pin(rtl, instance, local)
    history_instance = history['rtl_path'].rsplit('.', 1)[1]
    parameters = one(re.findall(r'ChiselAsyncEventRegister_v1\s*#\s*\((.*?)\)\s*' + re.escape(history_instance) + r'\s*\(', stripped, re.S), 'ACTUAL_HISTORY_MODEL')
    require(dict(re.findall(r'\.(\w+)\s*\((\d+)\)', parameters)) == history['parameters'], 'ACTUAL_HISTORY_PARAMETERS')
    require(pin(rtl, history_instance, 'reset') == 'reset', 'HISTORY_RESET_PIN')
    wanted = '{' + ports['bits.replyPhase'] + ',' + ports['bits.commandPhase'] + '}'
    require(resolve(pin(rtl, history_instance, 'd'), drivers) == resolve(wanted, drivers), 'HISTORY_D_PIN')
    q = pin(rtl, history_instance, 'q')
    for output, bit in (('command_ack', 0), ('reply_req', 1)):
        require(resolve(output, drivers) == resolve(q + f'[{bit}]', drivers), 'OUTPUT_ALIAS:' + output)
    if click:
        compare = primitive(node, 'publication_compare'); ci = compare['rtl_path'].rsplit('.', 1)[1]
        require(compare['model'] == 'ChiselAsyncXor_v1' and compare['reset_domain'] == 'root', 'PUBLICATION_MODEL')
        require(pin(rtl, ci, 'reset') == 'reset' and pin(rtl, ci, 'a') == ports['req'] and pin(rtl, ci, 'b') == ports['ack'], 'PUBLICATION_PINS')
        publication = compare['rtl_path'] + '.q'
        require(resolve(pin(rtl, history_instance, 'trigger'), drivers) == resolve(pin(rtl, ci, 'q'), drivers), 'TRIGGER_PIN')
    else:
        publication = owner['rtl_path'] + '.out_req'
        require(resolve(pin(rtl, history_instance, 'trigger'), drivers) == resolve(ports['req'], drivers), 'TRIGGER_PIN')
    return dict(node=node, top=top, click=click, history=history, publication=publication,
                expected='{' + hierarchy(owner['rtl_path']) + '.out_bits_replyPhase,' + hierarchy(owner['rtl_path']) + '.out_bits_commandPhase}',
                owner_request=hierarchy(owner['rtl_path']) + '.out_req', owner_request_net=ports['req'])


def fixture_seeds(name):
    return {1, 2, 19} if name.startswith('por-') else set(range(1, 17))


def fixture_name(source):
    """Identify a fixture from its generated oracle and contract, not its age."""
    node = json.loads((source / 'export/contract.json').read_text())['manifest']['design']
    variant = {'FourPhaseElapsed': 'bd', 'ClickElapsed': 'click'}.get(node['module'])
    require(variant is not None, 'FIXTURE_OWNER')
    oracle = (source / 'seed-1/testbench.sv').read_text()
    special = [name for name in ('por-reply-fall', 'por-command-fall', 'por-phase-zero') if source.name.startswith(variant + '-' + name)]
    if special:
        name = one(special, 'SPECIAL_POR_FIXTURE')
        markers = {'por-reply-fall': ('withdrawal_reset_test', 'ELAPSED_LOOP_POR_NOT_REPLY_WITHDRAWAL'),
                   'por-command-fall': ('withdrawal_reset_test', 'ELAPSED_LOOP_POR_NOT_COMMAND_WITHDRAWAL'),
                   'por-phase-zero': ('zero_phase_reset_test', 'ELAPSED_LOOP_POR_NOT_HELD_PHASE_ZERO')}
        block, diagnostic = markers[name]
        require('reset=1;' in oracle and 'begin : ' + block in oracle and
                re.search(r'\$fatal\(1,"' + diagnostic + r'"\)', oracle), 'SPECIAL_POR_ORACLE')
    elif 'begin : loop_test' in oracle:
        channel = one([c for c in node['channels'] if c['id'] == 'reply'], 'REPLY')
        lanes = len([f for f in channel['layout'] if re.fullmatch(r'bits.state.fraction\[\d+\]', f['field'])])
        require(lanes in (4, 5), 'FIXTURE_LANES')
        name = 'nibbles-normal' if lanes == 5 else 'nibbles-extreme'
    elif 'begin : reset_test' in oracle:
        selected = one(re.findall(r'selected_seen=\(([^;]+)\);', oracle), 'POR_SELECTOR')
        if re.search(r'\.in_bits_state_mode == 0$', selected):
            name = 'por-nibble-7'
        else:
            index = one(re.findall(r'\.in_bits_state_index == ([0-6])$', selected), 'POR_INDEX')
            name = 'por-nibble-' + index
    elif 'begin : return_reset_test' in oracle:
        held = one(re.findall(r'(reply_ack|command_req)=0;\s*wait\(dut\.\w+\.out_bits_mode == 3\)', oracle), 'RETURN_SELECTOR')
        name = 'por-return-command' if held == 'reply_ack' else 'por-return-reply'
    elif 'ELAPSED_LOOP_EARLY_NEXT_COUNT' in oracle:
        name = 'early-next'
    elif 'ELAPSED_LOOP_RETURN_COUNT' in oracle:
        name = 'external-return'
    else:
        raise ValueError(PREFIX + '_UNKNOWN_FIXTURE:' + str(source))
    require(name in FIXTURES[variant], 'FIXTURE_VARIANT:' + name)
    require(source.name.startswith(variant + '-' + ('nibbles' if name.startswith('nibbles') else
            'por-return' if name.startswith('por-return') else name)), 'FIXTURE_PATH_IDENTITY')
    return variant, name


def source_oracles(sources):
    require(set(sources) == {'bd', 'click'}, 'VARIANTS')
    selected = {}; oracles = {}
    for variant, expected in FIXTURES.items():
        require(set(sources[variant]) == expected, 'FIXTURE_INVENTORY:' + variant)
        for name, location in sources[variant].items():
            label = variant + '-' + name; source = Path(location).resolve()
            require((source / 'export/contract.json').is_file(), 'MISSING_SOURCE:' + label)
            require(fixture_name(source) == (variant, name), 'FIXTURE_IDENTITY:' + label)
            cases = sorted(source.glob('seed-*/testbench.sv'))
            require({p.parent.name for p in cases} == {f'seed-{s}' for s in fixture_seeds(name)} and
                    not list(source.glob('selected-skew-*')), 'ORACLE_INVENTORY:' + label)
            for oracle in cases:
                result = json.loads((oracle.parent / 'result.json').read_text())
                require(result['status'] == 'PASS' and str(result['seed']) == oracle.parent.name[5:], 'SOURCE_NOT_PASS:' + label)
                log = (oracle.parent / 'simulation.log').read_text()
                require('CA_TEST_PASS' in log and not re.search(r'FATAL:|ERROR:|TIMEOUT|DEADLINE', log), 'SOURCE_LOG_NOT_PASS:' + label)
            selected[label] = source; oracles[label] = cases
    require(len(set(selected.values())) == sum(map(len, FIXTURES.values())), 'COHORT_DUPLICATE_SOURCE')
    return selected, oracles


def validate_delays(source, binding):
    """Bind every seed's advertised delays to its actual defparam statements."""
    ranges = {}
    def visit(node):
        for cell in node['primitives']:
            if 'DELAY_FS' not in cell['parameters'] or cell['id'] in (
                    'request_delay', 'output_delay', 'request_guard', 'return_guard', 'acknowledge_guard', 'output_guard'):
                continue
            budget = dict(min_fs='1000000', max_fs='10000000')
            for timing in node['timing']:
                if timing['kind'] == 'click-bundling-v1':
                    budget = timing['cells']['fire' if cell['id'] == 'start_barrier' else cell['id']]
                elif timing['kind'] == 'long-hold-bundling-v2':
                    if cell['id'] == 'data_delay': budget = timing['data_delay']
                    elif cell['id'] == 'payload': budget = timing['latch_delay']
                    elif cell['id'] in timing['control_delays']: budget = timing['control_delays'][cell['id']]
                elif timing['kind'] == 'bundled-data-path-v1' and not timing['delay_owner'] and timing['delay_cell'] == cell['id']:
                    budget = timing['budget']
            ranges[cell['rtl_path']] = (int(budget['min_fs']), int(budget['max_fs']))
        for entry in node['children']:
            visit(entry['contract'])
    visit(binding['node'])
    for oracle in source.glob('seed-*/testbench.sv'):
        delay = json.loads((oracle.parent / 'delays.json').read_text())
        seed = int(oracle.parent.name[5:])
        require(str(delay['seed']) == str(seed) and delay['algorithm'] == 'java.util.Random; 1=min,2=max' and
                delay['pins_fs'] == {}, 'SEED_DELAY_IDENTITY')
        require(set(delay['cells_fs']) == set(ranges), 'SEED_DELAY_INVENTORY')
        actual = re.findall(r'defparam\s+(dut\.[\w.]+)\.DELAY_FS\s*=\s*(\d+)\s*;', oracle.read_text())
        expected = {hierarchy(path): value for path, value in delay['cells_fs'].items()}
        require(len(actual) == len(expected) and dict(actual) == expected, 'SEED_DELAY_BINDING')
        for path, value in delay['cells_fs'].items():
            low, high = ranges[path]; value = int(value)
            require(low <= value <= high and (seed != 1 or value == low) and (seed != 2 or value == high), 'SEED_DELAY_RANGE:' + path)


def validate_identity(document):
    require(document.get('schema') == 'riscay-elapsed-capture-sources-v1', 'SOURCE_SCHEMA')
    identity = document['source_identity']; recorded = identity['files']
    require(set(IDENTITY_FILES) <= set(recorded), 'SOURCE_IDENTITY_INVENTORY')
    for path, digest in recorded.items():
        require(sha(ROOT / path) == digest, 'SOURCE_IDENTITY_CHANGED:' + path)
    generation = identity['generation_log']
    require(sha(Path(generation['path'])) == generation['sha256'], 'GENERATION_LOG_CHANGED')
    log = Path(generation['path']).read_text()
    require('AsyncElapsedLoopSpec:' in log and 'All tests passed.' in log and
            not re.search(r'\*\*\* FAILED|Tests: succeeded \d+, failed [1-9]|\[error\]', log), 'GENERATION_NOT_PASS')
    # Current source hashes alone are insufficient if a source was edited after
    # the selected generation. Reject that stale cohort before simulation.
    generation_start = Path(generation['path']).stat()
    if hasattr(generation_start, 'st_birthtime'):
        require(all((ROOT / path).stat().st_mtime <= generation_start.st_birthtime for path in recorded), 'SOURCE_NEWER_THAN_GENERATION')
    return identity


def validate_cohort_identity(document, selected):
    """Explicit manifests have the same generation-window obligations as discovery."""
    identity = document['source_identity']; recorded = identity['generation_window']
    log = Path(identity['generation_log']['path']).stat()
    require(hasattr(log, 'st_birthtime'), 'GENERATION_BIRTHTIME_UNAVAILABLE')
    window = dict(start_unix=log.st_birthtime, end_unix=log.st_mtime)
    require(recorded == window, 'GENERATION_WINDOW_CHANGED')
    for name, source in selected.items():
        stamp = source.stat()
        require(hasattr(stamp, 'st_birthtime') and window['start_unix'] <= stamp.st_birthtime <= window['end_unix'],
                'STALE_COHORT_SOURCE:' + name)


def discover_cohort(cohort, generation_log):
    """Use one completed generation window; never silently mix latest fixtures."""
    cohort = cohort.resolve(); generation_log = generation_log.resolve()
    stamp = generation_log.stat()
    # ctime is a metadata-change time on some hosts, so it cannot attest creation.
    require(hasattr(stamp, 'st_birthtime'), 'GENERATION_BIRTHTIME_UNAVAILABLE')
    start = stamp.st_birthtime; end = stamp.st_mtime
    candidates = []
    for source in cohort.iterdir():
        if not source.is_dir() or not source.name.startswith(('bd-', 'click-')):
            continue
        created = source.stat().st_birthtime
        if start <= created <= end:
            candidates.append(source)
    require(len(candidates) == sum(map(len, FIXTURES.values())), 'GENERATION_COHORT_COUNT:' + str(len(candidates)))
    result = dict(schema='riscay-elapsed-capture-sources-v1', bd={}, click={},
                  source_identity=dict(files={path: sha(ROOT / path) for path in IDENTITY_FILES},
                  generation_log=dict(path=str(generation_log), sha256=sha(generation_log)),
                  generation_window=dict(start_unix=start, end_unix=end)))
    for source in candidates:
        variant, name = fixture_name(source)
        require(name not in result[variant], 'GENERATION_DUPLICATE_FIXTURE:' + name)
        result[variant][name] = str(source)
    validate_identity(result)
    selected, _ = source_oracles({v: result[v] for v in FIXTURES})
    validate_cohort_identity(result, selected)
    return result


def sidecar(binding):
    """Checks publication identity and delayed Q separately from shared pin timing."""
    hp = hierarchy(binding['history']['rtl_path']); pub = hierarchy(binding['publication'])
    owner = binding['owner_request']; expected = binding['expected']
    owner_event = owner if binding['click'] else 'posedge ' + owner
    return f'''
integer eh_epoch=0,eh_captures=0,eh_publications=0,eh_serial=0,eh_launches=0;
integer eh_total=0,eh_phase0=0,eh_phase1=0,eh_resets=0;
task automatic eh_reset_q(input integer epoch);
  #10000001;
  if({hp}.reset === 1'b1 && eh_epoch==epoch && {hp}.q !== 2'b00)
    $fatal(1,"ELAPSED_HISTORY_RESET_Q");
endtask
always @(posedge {hp}.reset) begin
  eh_epoch=eh_epoch+1; eh_captures=0; eh_publications=0; eh_serial=0; eh_launches=0;
  eh_resets=eh_resets+1;
  fork eh_reset_q(eh_epoch); join_none
end
task automatic eh_require_publication(input integer wanted,input integer epoch);
  #10000002;
  if({hp}.reset === 1'b0 && eh_epoch==epoch && eh_publications<wanted)
    $fatal(1,"ELAPSED_HISTORY_MISSING_PUBLICATION");
endtask
always @({owner_event}) if({hp}.reset === 1'b0) begin
  eh_launches=eh_launches+1;
  fork eh_require_publication(eh_launches,eh_epoch); join_none
end
task automatic eh_require_capture(input integer wanted,input integer epoch);
  #100002;
  if({hp}.reset === 1'b0 && eh_epoch==epoch && eh_captures<wanted)
    $fatal(1,"ELAPSED_HISTORY_MISSING_CAPTURE");
endtask
always @(posedge {pub}) if({hp}.reset === 1'b0) begin
  eh_publications=eh_publications+1;
  if({owner} === 1'b0) eh_phase0=eh_phase0+1; else eh_phase1=eh_phase1+1;
  fork eh_require_capture(eh_publications,eh_epoch); join_none
end
task automatic eh_require_q(input [1:0] wanted,input integer serial,input integer epoch);
  #10000001;
  if({hp}.reset === 1'b0 && eh_epoch==epoch) begin
    if(eh_serial != serial) $fatal(1,"ELAPSED_HISTORY_Q_OVERLAP");
    if({hp}.q !== wanted) $fatal(1,"ELAPSED_HISTORY_Q_VALUE");
  end
endtask
always @(posedge {hp}.trigger) if({hp}.reset === 1'b0) begin
  // Shared pin checks run at #0; their precise aperture failure takes priority.
  #1;
  if({hp}.d !== {expected}) $fatal(1,"ELAPSED_HISTORY_D_BINDING");
  eh_captures=eh_captures+1; eh_serial=eh_serial+1; eh_total=eh_total+1;
  if(eh_captures>eh_publications) $fatal(1,"ELAPSED_HISTORY_EXTRA_CAPTURE");
  fork eh_require_q({hp}.d,eh_serial,eh_epoch); join_none
end
always @(dut.command_ack or dut.reply_req or {hp}.q) begin
  #0;
  if({hp}.reset === 1'b0 && {{dut.reply_req,dut.command_ack}} !== {hp}.q)
    $fatal(1,"ELAPSED_HISTORY_OUTPUT_BINDING");
end
'''


def instrument(original, binding, reset_fixture=False):
    anchor = 'timeunit 1fs; timeprecision 1fs;'; marker = '$display("CA_TEST_PASS'
    require(original.count(anchor) == original.count(marker) == 1, 'ORACLE_SHAPE')
    monitors = capture_monitors(binding['node'], CAPTURES, PREFIX, {'history': binding['publication']})
    checks = '''
if(pc_history_count==0 || eh_total==0 || eh_captures!=eh_publications || eh_launches!=eh_publications)
  $fatal(1,"ELAPSED_HISTORY_ACTIVITY");
$display("ELAPSED_HISTORY_ACTIVITY captures=%0d publications=%0d phase0=%0d phase1=%0d resets=%0d",
  eh_total,eh_publications,eh_phase0,eh_phase1,eh_resets);
'''
    if binding['click']:
        checks += 'if(eh_phase0==0 || eh_phase1==0) $fatal(1,"ELAPSED_HISTORY_PHASE_COVERAGE");\n'
    if reset_fixture:
        checks += 'if(eh_resets<2) $fatal(1,"ELAPSED_HISTORY_RESET_COVERAGE");\n'
    return original.replace(anchor, anchor + '\n' + monitors + sidecar(binding)).replace(marker, checks + marker)


def apply_profile(original, source, binding, profile):
    low = json.loads((source / 'seed-1/delays.json').read_text())['cells_fs']
    high = json.loads((source / 'seed-2/delays.json').read_text())['cells_fs']
    require(low.keys() == high.keys(), 'DELAY_INVENTORY')
    result = original
    for path in low:
        group = 0 if '.ca_child_owner.' in path else 1 if '.ca_child_step.' in path else 2
        value = (low if profile[group] == 'min' else high)[path]
        pattern = r'(defparam\s+' + re.escape(hierarchy(path)) + r'\.DELAY_FS\s*=\s*)\d+(;)'
        result, count = re.subn(pattern, lambda m: m[1] + str(value) + m[2], result)
        require(count == 1, 'DELAY_BINDING:' + path)
    return result


def mutate(text, binding, kind):
    instance = binding['history']['rtl_path'].rsplit('.', 1)[1]
    trigger = pin(text, instance, 'trigger'); data = pin(text, instance, 'd')
    statements = ''
    if kind == 'setup':
        text = replace_pin(text, instance, 'd', '{2{' + trigger + '}}')
    elif kind == 'data':
        text = replace_pin(text, instance, 'd', '(' + data + " ^ 2'b01)")
    elif kind in ('missing', 'rising-only'):
        expression = "1'b0" if kind == 'missing' else '(' + trigger + ' & ' + binding['owner_request_net'] + ')'
        text = replace_pin(text, instance, 'trigger', expression)
    elif kind == 'q':
        # Clone just this primitive: retain POR and its actual Q/output aliases,
        # but drop its data load. Other owner/step EventRegisters stay untouched.
        pattern = r'ChiselAsyncEventRegister_v1(\s*#\s*\([^;]*?\)\s*' + re.escape(instance) + r'\s*\()'
        text, count = re.subn(pattern, r'ElapsedBadHistory\1', text, count=1)
        require(count == 1, 'Q_MUTATION')
        text += '''
module ElapsedBadHistory #(parameter integer WIDTH=2,parameter time DELAY_FS=1,
  parameter [WIDTH-1:0] RESET_VALUE=0)
  (input wire reset,trigger,input wire [WIDTH-1:0] d,output wire [WIDTH-1:0] q);
  timeunit 1fs; timeprecision 1fs;
  reg [WIDTH-1:0] state;
  always @(posedge reset or posedge trigger)
    if(reset) state<=RESET_VALUE; else state<=0;
  assign #DELAY_FS q=state;
endmodule
'''
    elif kind == 'output':
        text, count = re.subn(r'(assign\s+reply_req\s*=\s*)([^;]+);', lambda m: m[1] + "1'b0;", text)
        require(count == 1, 'OUTPUT_MUTATION')
    elif kind == 'hold':
        text = replace_pin(text, instance, 'd', '(' + data + " ^ {1'b0,eh_late})")
        statements = f'wire eh_late;\nassign #100000 eh_late={trigger};'
    else:
        text = replace_pin(text, instance, 'trigger', 'eh_clock')
        statements = 'wire eh_clock,eh_late,eh_second;\n'
        if kind in ('skew', 'legal'):
            statements += f'assign #{100000 if kind == "legal" else 100001} eh_clock={trigger};'
        elif kind == 'high':
            statements += f'assign #100000 eh_late={trigger};\nassign eh_clock={trigger} & ~eh_late;'
        elif kind == 'low':
            statements += f'assign #1000000 eh_late={trigger};\nassign #1100000 eh_second={trigger};\nassign eh_clock={trigger} & (~eh_late | eh_second);'
        else:
            raise ValueError('Unknown mutation: ' + kind)
    return add_wires(text, binding['top'], statements) if statements else text


def exact_fatal(case, expected, execution):
    require(execution['compile']['exit_code'] == 0 and execution['simulation']['exit_code'] == 1, 'CONTROL_EXIT')
    for name, digest in execution['sources_sha256'].items():
        require(sha(case / name) == digest, 'CONTROL_SOURCE_CHANGED:' + name)
    require(sha(case / 'sim.vvp') == execution['binary_sha256'] and
            sha(case / 'simulation.log') == execution['simulation']['log_sha256'], 'CONTROL_EXECUTION_CHANGED')
    text = (case / 'testbench.sv').read_text()
    lines = [i for i, line in enumerate(text.splitlines(), 1) if '$fatal' in line and '"' + expected + '"' in line]
    require(len(lines) == 1, 'CONTROL_FATAL_SITE')
    log = (case / 'simulation.log').read_text()
    require(not re.search(r'CA_TEST_PASS|TIMEOUT|DEADLINE|\bERROR\b', log), 'CONTROL_UNRELATED_FAILURE')
    found = re.search(r'^FATAL: (.*):(\d+): ([^\r\n]+)\r?\n\s+Time: (\d+)\s+Scope: ([^\r\n]+)', log, re.M)
    require(found is not None, 'CONTROL_NO_FATAL')
    fatal_path = Path(found[1]); fatal_path = fatal_path if fatal_path.is_absolute() else case / fatal_path
    require(fatal_path.resolve() == (case / 'testbench.sv').resolve() and int(found[2]) == lines[0] and found[3] == expected,
            'CONTROL_WRONG_FIRST_FATAL:' + (found[0] if found else 'none'))
    scope = 'Testbench' + ({'ELAPSED_HISTORY_MISSING_CAPTURE': '.eh_require_capture',
                          'ELAPSED_HISTORY_Q_VALUE': '.eh_require_q'}.get(expected, ''))
    require(found[5].strip() == scope, 'CONTROL_WRONG_FATAL_SCOPE')
    # A later unrelated failure is not permitted to hide behind the first match.
    records = re.findall(r'^FATAL: (.*):(\d+): ([^\r\n]+)', log, re.M)
    require(len(records) == 1, 'CONTROL_MULTIPLE_FATALS')
    return dict(file=str(fatal_path.resolve()), line=lines[0], diagnostic=expected, scope=found[5].strip(), time_fs=int(found[4]))


def simulate(case, source, oracle, binding, commands, profile=None, mutation=None, reset_fixture=False):
    require(not case.is_relative_to(source), 'SOURCE_OVERLAP')
    shutil.copytree(source / 'export', case)
    original = oracle.read_text()
    if profile:
        original = apply_profile(original, source, binding, profile)
    test = instrument(original, binding, reset_fixture)
    (case / 'testbench.sv').write_text(test, encoding='utf-8')
    rtl = case / (binding['top'] + '.sv')
    if mutation:
        rtl.write_text(mutate(rtl.read_text(), binding, mutation), encoding='utf-8')
    files = [(case / line.strip()).resolve() for line in (case / 'filelist.f').read_text().splitlines() if line.strip()]
    require(all(path.is_relative_to(case.resolve()) and path.is_file() for path in files) and rtl.resolve() in files, 'FILELIST')
    executables = {name: shutil.which(name) for name in ('iverilog', 'vvp')}
    require(all(executables.values()), 'MISSING_SIMULATION_TOOL')
    simulation_tools = {name: dict(path=str(Path(path).resolve()), sha256=sha(path)) for name, path in executables.items()}
    evidence = dict(source=str(source), oracle=str(oracle), oracle_sha256=sha(oracle),
                    source_result_sha256=sha(oracle.parent / 'result.json'), source_log_sha256=sha(oracle.parent / 'simulation.log'),
                    profile=profile, mutation=mutation, original_assertions_preserved=True,
                    sources_sha256=hashes(case), simulation_tools=simulation_tools, passed=False)
    try:
        compiled, log = run([simulation_tools['iverilog']['path'], '-g2012', '-s', 'Testbench', '-o', 'sim.vvp', *map(str, files), 'testbench.sv'], case, 'compile.log', commands)
        compiled['log_sha256'] = sha(case / 'compile.log'); evidence['compile'] = compiled
        require(compiled['exit_code'] == 0, 'COMPILE_FAILED:' + log[-2000:])
        evidence['binary_sha256'] = sha(case / 'sim.vvp')
        simulated, log = run([simulation_tools['vvp']['path'], 'sim.vvp'], case, 'simulation.log', commands)
        simulated['log_sha256'] = sha(case / 'simulation.log'); evidence['simulation'] = simulated
        if mutation in MUTATIONS:
            evidence['exact_fatal'] = exact_fatal(case, MUTATIONS[mutation], evidence)
        else:
            require(simulated['exit_code'] == 0 and 'CA_TEST_PASS' in log and 'ELAPSED_HISTORY_ACTIVITY captures=' in log and
                    not re.search(r'FATAL:|ERROR:|TIMEOUT|DEADLINE', log), 'SIMULATION_FAILED:' + log[-2000:])
            evidence['activity'] = re.findall(r'ELAPSED_HISTORY_ACTIVITY[^\r\n]+', log)
        evidence['passed'] = True
    except Exception as error:
        evidence['error'] = str(error)
        raise
    finally:
        (case / 'execution.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--sources', type=Path)
    inputs.add_argument('--cohort', type=Path)
    parser.add_argument('--generation-log', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if args.cohort:
        require(args.generation_log is not None, 'GENERATION_LOG_REQUIRED')
        document = discover_cohort(args.cohort, args.generation_log)
    else:
        document = json.loads(args.sources.read_text())
    identity = validate_identity(document)
    selected, oracles = source_oracles({v: document[v] for v in FIXTURES})
    validate_cohort_identity(document, selected)
    bound = {name: bindings(path / 'export') for name, path in selected.items()}
    for name, source in selected.items():
        validate_delays(source, bound[name])
    original_hashes = {name: hashes(path) for name, path in selected.items()}
    out = args.out.resolve()
    require(all(not out.is_relative_to(source) for source in selected.values()), 'SOURCE_OVERLAP')
    out.mkdir(parents=True, exist_ok=False)
    (out / 'sources.json').write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8')
    results = dict(schema='riscay-elapsed-capture-controls-v1', passed=False, source_identity=identity,
                   source_manifest_sha256=sha(out / 'sources.json'), source_hashes=original_hashes, cases={},
                   checker_sources={path: sha(ROOT / path) for path in ('tools/check_elapsed_capture_controls.py', 'tools/check_capture_pins.py', 'tools/check_i2c_wiring_controls.py')},
                   limitation='Digital actual-pin and protocol checks only; no physical qualification.')
    commands = []
    def record():
        (out / 'results.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n', encoding='utf-8')
    def replay(label, name, oracle, **kwargs):
        try:
            results['cases'][label] = simulate(out / label, selected[name], oracle, bound[name], commands,
                                              reset_fixture='-por-' in name, **kwargs)
        finally:
            failed = out / label / 'execution.json'
            if label not in results['cases'] and failed.is_file():
                results['cases'][label] = json.loads(failed.read_text())
            record()
        print(label, 'PASS', flush=True)
    for name, source in selected.items():
        for oracle in oracles[name]:
            replay(name + '-' + oracle.parent.name, name, oracle)
        oracle = source / 'seed-1/testbench.sv'
        for profile in PROFILES:
            replay(name + '-skew-' + '-'.join(profile), name, oracle, profile=profile)
        replay(name + '-legal-distribution', name, oracle, mutation='legal')
    for variant in FIXTURES:
        name = variant + '-nibbles-normal'; oracle = selected[name] / 'seed-1/testbench.sv'
        for mutation in MUTATIONS:
            if mutation == 'rising-only' and variant != 'click':
                continue
            replay(variant + '-bad-' + mutation, name, oracle, mutation=mutation)
    results['originals_preserved'] = all(hashes(path) == original_hashes[name] for name, path in selected.items())
    validate_identity(document)
    require(results['originals_preserved'], 'ORIGINAL_CHANGED')
    results['passed'] = True
    results['summary'] = dict(fixtures=len(selected), original_replays=sum(map(len, oracles.values())),
                              opposing_skews=len(selected) * len(PROFILES), legal_distribution=len(selected), negative_controls=19)
    record(); print('ALL_ELAPSED_CAPTURE_CONTROLS_PASS', flush=True)


if __name__ == '__main__':
    main()

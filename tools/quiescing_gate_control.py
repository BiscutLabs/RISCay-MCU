# SPDX-License-Identifier: Apache-2.0
"""Narrow actual-graph and fault helper for the three C1e real-gate fixtures.

No process launcher: the reviewed controls runner owns provenance and replay.
RAM-store branch only; no physical, natural-reachability or whole-chip claim.
"""
import re
import hashlib
import json
from functools import lru_cache
from itertools import product
from pathlib import Path

from check_frame_store_controls import masked, pin_value
from check_quiescing_receipt_controls import actual_child, literal_site, need, one
from reset_bridge_proof import Cone
from reset_coordinator_proof import register, work_clock


# Order is also the explicit testbench observation vector, MSB first. These are
# cuts at actual predicate outputs, not assumptions about their upstream state.
# Every cut must be observed true at runtime; the graph proves there is no
# omitted ready condition on the exercised RAM-store branch.
CPU = (
    ('fabric_completionAvailable', 1), ('applicationCancel', 0),
    ('fabric_resetRecovery', 0), ('_ca_child_admission_grant_bridge_out_valid', 1),
    ('fabric_bootWait', 0), ('fabric_eventWait', 0), ('fabric_memoryBusy', 0),
    ('fabric_loaderWrite', 0), ('fabric_telemetryBarrier', 0),
    ('fabric_housekeepingBarrierBusy', 0), ('telemetryBoundary_io_debt', 0),
    ('housekeepingBoundary_io_debt', 0))
PREDICATES = CPU + (('fabric_controlBusy', 0), ('_ca_child_ram_grant_bridge_out_valid', 1),
    ('fabric_io_ramSource_decision_ready', 1), ('ramServiceDebt', 0),
    ('_ca_child_ram_access_io_request_ready', 1))
BRANCH = {'fabric_ramOperation': 1, 'fabric_nativeMmio': 0, 'fabric_programCpuOperation': 0}
FORCES = ('gate_demandFirst', 'gate_drainFirst')
FATAL = 'SOC_GATE_ACK_WITHOUT_REAL_CAPTURE'


def compact(text):
    return re.sub(r'\s+', '', masked(text))


def combine(op, *values):
    """Canonical AND/OR normal form, not an exponential Boolean sweep."""
    neutral, absorbing = (1, 0) if op == 'and' else (0, 1)
    result = set()
    for value in values:
        if value == absorbing:
            return absorbing
        if value == neutral:
            continue
        result.update(value[1:] if isinstance(value, tuple) and value[0] == op else [value])
    if not result:
        return neutral
    if len(result) == 1:
        return next(iter(result))
    return (op, *sorted(result, key=repr))


def negate(value):
    if type(value) is int:
        return 1-value
    if value[0] == 'not':
        return value[1]
    return ('not', value)


def expression(cone, bit, cuts, cache=None):
    cache = {} if cache is None else cache
    if bit in ('0', '1'):
        return int(bit)
    if bit in cuts:
        return cuts[bit]
    if bit in cache:
        return cache[bit]
    if bit not in cone.drivers:
        return ('unbound', bit)
    name, cell, port, index = cone.drivers[bit]
    pins = cell['connections']; kind = cell['type']
    def arg(pin):
        if len(pins[pin]) != 1:
            return ('wide', name, pin)
        return expression(cone, pins[pin][0], cuts, cache)
    # Unsupported logic remains opaque, and cannot equal the required cofactor.
    # Constant branch folding may legitimately discard an unselected cone.
    if len(pins[port]) != 1 or index != 0:
        value = ('wide-output', name, index)
    elif kind in ('$and', '$logic_and', '$or', '$logic_or'):
        value = combine('and' if 'and' in kind else 'or', arg('A'), arg('B'))
    elif kind in ('$not', '$logic_not'):
        value = negate(arg('A'))
    elif kind in ('$reduce_or', '$reduce_bool', '$reduce_and'):
        value = arg('A')
    elif kind == '$mux':
        select = arg('S')
        value = arg('B') if select == 1 else arg('A') if select == 0 else ('mux', select, arg('A'), arg('B'))
    else:
        value = ('opaque', name, kind)
    cache[bit] = value
    return value


def prove_ready(cone):
    cuts = {}; atoms = {}
    for name, good in PREDICATES + (('gate_enabled', 1),):
        bits = cone.bits(name)
        need(len(bits) == 1 and type(bits[0]) is int and bits[0] not in cuts, 'GATE_DISTINCT_PREDICATE:' + name)
        atom = ('leaf', name); cuts[bits[0]] = atom
        atoms[name] = atom if good else negate(atom)
    for name, value in BRANCH.items():
        bits = cone.bits(name)
        need(len(bits) == 1 and type(bits[0]) is int and bits[0] not in cuts, 'GATE_BRANCH_CUT')
        cuts[bits[0]] = value
    expected_cpu = combine('and', atoms['gate_enabled'], *(atoms[n] for n, _ in CPU))
    expected_ready = combine('and', atoms['gate_enabled'], *(atoms[n] for n, _ in PREDICATES))
    need(expression(cone, cone.bits('fabric_cpuAvailable')[0], cuts) == expected_cpu, 'GATE_COMPLETE_CPU_COFACTOR')
    need(expression(cone, cone.bits('fabric_io_request_ready')[0], cuts) == expected_ready, 'GATE_COMPLETE_READY_COFACTOR')
    return dict(branch=BRANCH, observed_predicates=PREDICATES, cpu=repr(expected_cpu), ready=repr(expected_ready))


def prove_graph(module):
    cone = Cone(module); service = cone.bits('serviceClock'); reset = cone.bits('reset')
    clock = work_clock(cone)
    need(cone.bits('receivingClock') == clock, 'GATE_OBSERVED_WORK_CLOCK')
    rows = {}
    for name in FORCES + ('gate_needClock', 'gate_drain'):
        identity, cell = register(cone, name, service, reset, 1, 1)
        rows[name] = dict(identity=identity, pins=cell['connections'])
    for second, first in (('gate_needClock', 'gate_demandFirst'), ('gate_drain', 'gate_drainFirst')):
        need(rows[second]['pins']['D'] == cone.bits(first), 'GATE_TWO_STAGE_SYNCHRONIZER')
    for name in FORCES:
        need(all(type(bit) is int for bit in rows[name]['pins']['D']), 'GATE_CONSTANT_INPUT')
    _, grace = register(cone, 'gate_grace', service, reset, 3, 7)
    _, enabled = cone.flop('gate_enabled'); ep = enabled['parameters']; en = enabled['connections']
    need(en['ARST'] == reset and ep['ARST_POLARITY'] == '1' and
         int(ep['ARST_VALUE'], 2) == 1, 'GATE_ENABLE_POR')
    # Yosys may absorb the one-bit clock inverter into CLK_POLARITY.
    # Accept only a direct negative service edge or a positive edge of its
    # exact one-bit inversion. Neither form permits another clock/control.
    polarity = ep['CLK_POLARITY']
    need(re.fullmatch(r'0*[01]', polarity) is not None and len(en['CLK']) == 1,
         'GATE_FALLING_CLOCK')
    if int(polarity, 2) == 0:
        need(en['CLK'] == service, 'GATE_FALLING_CLOCK')
    else:
        driver = cone.drivers.get(en['CLK'][0])
        need(driver is not None, 'GATE_FALLING_CLOCK')
        _, inverter, port, index = driver
        need(inverter['type'] in ('$not', '$logic_not') and port == 'Y' and index == 0 and
             inverter['connections'] == dict(A=service, Y=en['CLK']) and
             inverter['port_directions'] == dict(A='input', Y='output'), 'GATE_FALLING_CLOCK')
    for drain, count in product(range(2), range(8)):
        env = {}; cone.bind(env, cone.bits('gate_drain'), drain); cone.bind(env, grace['connections']['Q'], count)
        need(cone.evaluate(grace['connections']['D'], env) == (7 if drain else max(0, count-1)), 'GATE_SEVEN_EDGE_GRACE')
    for demand, count, por in product(range(2), range(8), range(2)):
        env = {}; cone.bind(env, cone.bits('gate_needClock'), demand)
        cone.bind(env, cone.bits('gate_grace'), count); cone.bind(env, reset, por)
        need(cone.evaluate(en['D'], env) == bool(demand or count or por), 'GATE_ENABLE_RUN')
    for instance in ('ca_child_ram_access', 'ca_child_ram_grant_bridge', 'ca_child_ram_decision_bridge'):
        need(cone.bits(instance + '.clock') == clock, 'GATE_ACTUAL_CONSUMER_CLOCK:' + instance)
    need(cone.bits('ca_child_request_bridge.clock') == service, 'GATE_REQUEST_SERVICE_CLOCK')
    need(cone.bits('ca_child_request_bridge.out_ready') == cone.bits('fabric_io_request_ready'), 'GATE_ACTUAL_READY_PIN')
    for name, width in (('ca_child_ram_access.active', 1), ('fabric_ram_state', 2)):
        local = cone.flop(name)[1]['connections']['ARST']
        if local != reset:
            need(name == 'ca_child_ram_access.active', 'GATE_CONSUMER_POR')
            prefix = 'ca_child_ram_access.localReset_release_'
            _, first = register(cone, prefix+'0', clock, reset, 1, 1)
            _, second = register(cone, prefix+'1', clock, reset, 1, 1)
            need(first['connections']['D'] == ['0'] and
                 second['connections']['D'] == first['connections']['Q'] and
                 local == second['connections']['Q'], 'GATE_CONSUMER_POR_RELEASE')
        register(cone, name, clock, local, width, 0)
    for output, actual in (('rawRequest', 'ca_child_request_bridge.in_req'),
                           ('rawAck', 'ca_child_request_bridge.in_ack'),
                           ('offered', 'ca_child_request_bridge.out_valid'),
                           ('ramGrantWaiting', 'ca_child_ram_grant_bridge.out_valid')):
        need(cone.bits(output) == cone.bits(actual), 'GATE_OBSERVER_ALIAS:' + output)
    for field, width in (('operation', 2), ('address', 32), ('data', 32), ('mask', 4)):
        for output, actual in (('rawPayload_', 'ca_child_request_bridge.in_bits_'),
                               ('captured_', 'ca_child_request_bridge.out_bits_')):
            need(len(cone.bits(output+field)) == width and cone.bits(output+field) == cone.bits(actual+field),
                 'GATE_PAYLOAD_ALIAS:' + output+field)
    for output, valid, ready in (('accepted', 'ca_child_request_bridge.out_valid', 'fabric_io_request_ready'),
                                 ('wordAccepted', 'ca_child_ram_access.io_request_valid', 'ca_child_ram_access.io_request_ready')):
        for v, r in product(range(2), repeat=2):
            env = {}; cone.bind(env, cone.bits(valid), v); cone.bind(env, cone.bits(ready), r)
            need(cone.evaluate(cone.bits(output), env) == (v and r), 'GATE_FIRE_OBSERVER:' + output)
    macro = module['cells'].get('fabric_ram_macros_0')
    need(macro is not None and macro['type'] == 'gf180mcu_ocd_ip_sram__sram1024x8m8wm1' and
         macro['connections']['CLK'] == clock, 'GATE_ACTUAL_MACRO_CLOCK')
    return dict(forced_registers=rows, ready=prove_ready(cone), work_clock=clock,
                limits='Actual graph RAM-store cofactor and clock topology only; digital injected gate-input stall.')


def validate_testbench(text):
    code = masked(text)
    actual = re.findall(r'\bforce\s+dut\.(\w+)\s*=\s*([^;]+);', code)
    need(actual == [(name, "1'b0") for name in FORCES], 'GATE_FORCE_CATALOGUE')
    need(len(re.findall(r'\bforce\b', code)) == 2 and
         re.findall(r'\brelease\s+dut\.(\w+)\s*;', code) == list(FORCES), 'GATE_RELEASE_CATALOGUE')
    observed = one(r'wire\s+\[16:0\]\s+gatePredicates\s*=\s*\{([^}]+)\}\s*;', text, 'GATE_PREDICATE_OBSERVATION')
    expected = ','.join(('' if good else '~')+'dut.'+name for name, good in PREDICATES)
    need(compact(observed[1]) == expected, 'GATE_OBSERVED_ALL_PREDICATES')
    for wire, expression_text in (
        ('gateOtherReady', '&gatePredicates'),
        ('gateWithoutDecision', '&{gatePredicates[16:3],gatePredicates[1:0]}'),
        ('gateStoreBranch', 'dut.fabric_ramOperation&&!dut.fabric_nativeMmio&&!dut.fabric_programCpuOperation'),
        ('gateEligibleWrite', 'dut.ca_child_ram_source.eligible&&dut.ca_child_ram_grant_bridge.out_bits')):
        declaration = one(r'wire\s+'+wire+r'\s*=\s*([^;]+);', text, 'GATE_OBSERVER:' + wire)
        need(compact(declaration[1]) == expression_text, 'GATE_OBSERVER_EXPRESSION:' + wire)
    return literal_site(text, FATAL)


def mutate(texts, manifest, variant):
    prefix = 'FourPhase' if variant == 'bd' else 'Click'
    top = ('Bd' if variant == 'bd' else 'Click') + 'ResetBoundarySocFixture'
    need(variant in ('bd', 'click') and manifest['top'] == top, 'GATE_FIXTURE_TOP')
    name = top + '.sv'; body = texts[name]
    receipt = actual_child(manifest, body, 'request_bridge', prefix + 'QuiescingReceipt')
    need(pin_value(body, receipt, 'out_ready') == 'fabric_io_request_ready' and
         pin_value(body, receipt, 'clock') == 'serviceClock', 'GATE_CONNECTED_RECEIPT')
    for identity, kind in (('ram_source', prefix+'RamSource'), ('ram_grant_bridge', prefix+'ToDecoupled')):
        need(actual_child(manifest, body, identity, kind) == 'ca_child_'+identity, 'GATE_OBSERVED_CHILD')
    match = one(r'wire\s+fabric_cpuAvailable\s*=\s*([^;]+);', body, 'GATE_ACTUAL_CPU_ASSIGNMENT')
    terms = compact(match[1]).split('&')
    expected = [('' if good else '~')+net for net, good in CPU] + ['gate_enabled']
    need(len(terms) == len(expected) and sorted(terms) == sorted(expected), 'GATE_EXACT_CPU_FACTORS')
    # Change only the gate token at its original offset. No testbench or other
    # ready factor, clock, data, mask, reset, assertion or phase changes.
    token = one(r'\bgate_enabled\b', match[1], 'GATE_SINGLE_QUALIFICATION')
    start = match.start(1) + token.start(); end = match.start(1) + token.end()
    return name, body[:start] + "1'h1" + body[end:], validate_testbench(texts['testbench.sv'])


def _bind(inputs, path, digest=None):
    from check_quiescing_receipt_controls import sha
    path = Path(path).resolve(); value = sha(path)
    need(digest is None or value == digest, 'GATE_GRAPH_INPUT_CHANGED:' + str(path))
    need(str(path) not in inputs or inputs[str(path)] == value, 'GATE_GRAPH_CONFLICTING_INPUT')
    inputs[str(path)] = value
    return path


def _local(base, name):
    path = (base / name).resolve()
    need(not Path(name).is_absolute() and '..' not in Path(name).parts and path.is_relative_to(base.resolve()), 'GATE_GRAPH_LOCAL_PATH')
    return path


def _graph_inputs(export, folder, record, root, tool_inputs, inputs):
    """Bind prepare_graph's exact source transformations and producer commands.

    The graph directory stays outside the immutable regression fixture. Root
    captures its absence before invoking the existing bounded graph producer.
    """
    from check_quiescing_receipt_controls import read_json, sha
    need(record['contract_sha256'] == sha(export/'contract.json') and
         record['filelist_sha256'] == sha(export/'filelist.f'), 'GATE_GRAPH_EXPORT_BINDING')
    listed = [n.strip() for n in (export/'filelist.f').read_text().splitlines() if n.strip()]
    need(set(record['sources']) == set(listed) and len(listed) == len(set(listed)), 'GATE_GRAPH_SOURCES')
    lock = read_json(_bind(inputs, root/'tools/gf180-estimate-inputs.json'))
    sram_name = 'gf180mcu_ocd_ip_sram__sram1024x8m8wm1'
    sram = _bind(inputs, root/'soc/src/main/resources/riscay/sram'/(sram_name+'.blackbox.v'), record['sram_blackbox_sha256'])
    sram_lock = read_json(_bind(inputs, root/'soc/sram-lock.json'))
    need(sha(sram) == sram_lock['assets'][sram.name]['sha256'], 'GATE_GRAPH_SRAM_BLACKBOX')
    names = []
    for name in listed:
        original = _bind(inputs, _local(export, name), record['sources'][name]); names.append(original.name)
        text = original.read_text()
        if original.name.startswith('ChiselAsync'):
            a=text.index('module '); b=text.index(');',a)+2
            text='(* blackbox *)\n'+text[a:b]+'\nendmodule\n'
            text=text.replace('parameter time','parameter [63:0]').replace('parameter longint unsigned','parameter [63:0]').replace('parameter bit','parameter')
        elif original.name == sram_name+'.sv': text=sram.read_text()
        need(_bind(inputs, folder/original.name).read_text() == text, 'GATE_GRAPH_TRANSFORM:' + original.name)
    need(len(names) == len(set(names)), 'GATE_GRAPH_DUPLICATE_BASENAME')
    def linux(path):
        value=str(Path(path).resolve()).replace('\\','/')
        need(re.match(r'^[A-Za-z]:/',value) is not None, 'GATE_GRAPH_WINDOWS_ROOT')
        return '/mnt/'+value[0].lower()+value[2:]
    tools={name:Path(record['tools'][name]['path']) for name in ('sv2v','yosys')}
    need(set(record['tools']) == set(tools), 'GATE_GRAPH_TOOL_INVENTORY')
    for name,path in tools.items():
        need(record['tools'][name]['sha256'] == tool_inputs.get(str(path.resolve())) == lock['tools'][name]['sha256'], 'GATE_GRAPH_TOOL:' + name)
        _bind(inputs,path,record['tools'][name]['sha256'])
    script=(f'read_verilog -sv {linux(folder/"converted.v")}\n'
            f'hierarchy -check -top {record["top"]}\nproc\nflatten\nopt_clean\n'
            f'write_json {linux(folder/"netlist.json")}\n')
    need((folder/'graph.ys').read_text() == script, 'GATE_GRAPH_PROC_FLATTEN_SCRIPT')
    expected=[['wsl','-e',linux(tools['sv2v']),'-DSYNTHESIS',*[linux(folder/n) for n in names]],
              ['wsl','-e',linux(tools['yosys']),'-s',linux(folder/'graph.ys')]]
    need(record['commands'] == expected, 'GATE_GRAPH_PRODUCER_COMMANDS')
    for name,key in [('graph.ys','script_sha256'),('converted.v','converted_sha256'),('netlist.json','netlist_sha256')]:
        _bind(inputs,folder/name,record[key])
    for name in ('sv2v.log','yosys.log'): _bind(inputs,folder/name)
    log=(folder/'yosys.log').read_text()
    need('Executing JSON backend.' in log and 'End of script.' in log and not re.search(r'ERROR:|TIMEOUT',log), 'GATE_GRAPH_PRODUCER_COMPLETION')


@lru_cache(maxsize=3)
def _full_graph_proof(path, digest, helper_identity, top, capacities):
    # Validate the complete full audit once per immutable graph/helper identity.
    # Every binder call still rehashes every graph/source/runtime input before
    # consulting this bounded cache. Return immutable text, never a mutable proof.
    from check_quiescing_receipt_controls import sha, read_json
    from check_reset_crossings import audit_graph
    need(sha(Path(path)) == digest, 'GATE_GRAPH_CHANGED_BEFORE_PROOF')
    database=read_json(Path(path)); original=json.dumps(database,sort_keys=True)
    full=audit_graph(database,top,dict(capacities))
    need(full['status'] == 'pass' and full['violations'] == [], 'GATE_FULL_AUDIT_FAILED')
    need(sum(p['prefix'] == 'applicationResetCoordinator' for p in full['receiver_proofs']) == 1, 'GATE_REAL_COORDINATOR_REQUIRED')
    need(sum(p['prefix'] == 'ca_child_request_bridge' and p.get('masked_bits') == 70
             for p in full['receiver_proofs']) == 1, 'GATE_REAL_MASK_PROOF_REQUIRED')
    narrow=prove_graph(database['modules'][top])
    need(json.dumps(database,sort_keys=True) == original and sha(Path(path)) == digest, 'GATE_PROOF_CHANGED_INPUT')
    return json.dumps(dict(full=full, gate=narrow),sort_keys=True)


def bind_gate_graphs(receipt_path, regression_path, execution, groups, root):
    """Consume root's before/after receipt; never generate a graph or fixture."""
    from check_quiescing_receipt_controls import read_json, sha, file_hashes
    from check_frame_store_controls import helper_closure
    from reset_bridge_proof import sram_capacities
    inputs={}; receipt_path=Path(receipt_path).resolve(); regression_path=Path(regression_path).resolve()
    receipt=read_json(_bind(inputs,receipt_path))
    need(receipt['schema'] == 'riscay-quiescing-gate-graphs-v1' and receipt['status'] == 'PASS_GATE_GRAPH_PREPARATION' and
         receipt['regression_receipt_sha256'] == sha(regression_path), 'GATE_GRAPH_RECEIPT')
    before=read_json(_bind(inputs,receipt_path.parent/'gate-graphs-before.json',receipt['before_sha256']))
    need(before['regression_receipt_sha256'] == sha(regression_path) and
         before['sources_sha256'] == execution['sources_sha256'] and
         before['compiled_class_sha256'] == execution['compiled_class_sha256'], 'GATE_GRAPH_BEFORE_REGRESSION')
    for name in ('sources_unchanged','tools_unchanged','helpers_unchanged'):
        need(receipt.get(name) is True, 'GATE_GRAPH_CHANGED:' + name)
    need(execution['ended_unix']*1e9 <= before['captured_unix_ns'] <= receipt['started_unix_ns'] <= receipt['ended_unix_ns'], 'GATE_GRAPH_TIME_ORDER')
    need(before['helpers_sha256'] == receipt['helpers_sha256'] and before['tool_inputs_sha256'] == receipt['tool_inputs_sha256'], 'GATE_GRAPH_TOOL_SNAPSHOTS')
    for p,h in execution['tool_inputs_sha256'].items():
        need(before['tool_inputs_sha256'].get(p) == h, 'GATE_GRAPH_REGRESSION_RUNTIME')
    driver=Path(before['driver']).resolve()
    required=set(helper_closure([Path(__file__),root/'tools/check_reset_crossings.py'])) | {driver}
    need(required <= {Path(p).resolve() for p in before['helpers_sha256']}, 'GATE_GRAPH_COMPLETE_HELPERS')
    need(receipt['driver_sha256'] == before['helpers_sha256'].get(str(driver)), 'GATE_GRAPH_DRIVER')
    for field in ('helpers_sha256','tool_inputs_sha256'):
        for p,h in before[field].items():
            need(Path(p).is_absolute(), 'GATE_GRAPH_ABSOLUTE_INPUT')
            _bind(inputs,p,h)
    gates={str(Path(g['path']).resolve()):g for g in groups if g['kind'] == 'real-gate'}
    need(len(gates) == 3 and set(receipt['cases']) == set(before['fixtures_sha256']) == set(before['outputs']) == set(gates), 'GATE_GRAPH_COMPLETE_COHORT')
    need(all(Path(p).is_absolute() for p in before['outputs'].values()) and
         len({str(Path(p).resolve()).casefold() for p in before['outputs'].values()}) == 3 and
         len(set(before['outputs'].values())) == 3 and set(before['preexisting_outputs']) == set(before['outputs'].values()) and
         all(value == [] for value in before['preexisting_outputs'].values()), 'GATE_GRAPH_FRESH_OUTPUTS')
    identity=hashlib.sha256(json.dumps(before['helpers_sha256'],sort_keys=True).encode()).hexdigest()
    bindings=[]
    for path,g in gates.items():
        export=Path(path); case=receipt['cases'][path]; folder=Path(before['outputs'][path]).resolve()
        need(folder.is_relative_to(root/'build') and all(not folder.is_relative_to(Path(p)) and not Path(p).is_relative_to(folder) for p in execution['fresh_fixtures_sha256']), 'GATE_GRAPH_OUTPUT_OVERLAP')
        need(case['output'] == str(folder) and case['status'] == 'PASS' and case['exit_code'] == 0 and
             not case.get('exception') and not case.get('timed_out') and
             receipt['started_unix_ns'] <= case['started_unix_ns'] <= case['ended_unix_ns'] <= receipt['ended_unix_ns'], 'GATE_GRAPH_CASE_RESULT')
        need(before['fixtures_sha256'][path] == execution['fresh_fixtures_sha256'][path] == file_hashes(export), 'GATE_GRAPH_FRESH_FIXTURE')
        need(case['output_sha256'] == file_hashes(folder), 'GATE_GRAPH_OUTPUT_INVENTORY')
        for name,digest in case['output_sha256'].items(): _bind(inputs,_local(folder,name),digest)
        manifest=read_json(export/'contract.json')['manifest']; top=manifest['top']
        need(top == ('Bd' if g['variant'] == 'bd' else 'Click')+'ResetBoundarySocFixture', 'GATE_GRAPH_EXACT_TOP')
        report=read_json(folder/'report.json'); record=report['inputs']
        need(record['top'] == top and record == case['producer'], 'GATE_GRAPH_PRODUCER_RECORD')
        _graph_inputs(export,folder,record,root,before['tool_inputs_sha256'],inputs)
        inventory=read_json(_bind(inputs,export/'sram.json',record['sram_inventory_sha256']))
        capacities=sram_capacities(inventory,top)
        need(capacities == record['sram_capacities'], 'GATE_GRAPH_CAPACITIES')
        proved=json.loads(_full_graph_proof(str(folder/'netlist.json'),record['netlist_sha256'],identity,top,tuple(sorted(capacities.items()))))
        need(proved['full'] == {k:v for k,v in report.items() if k != 'inputs'}, 'GATE_GRAPH_FULL_REPORT')
        bindings.append(dict(fixture=path, graph=str(folder/'netlist.json'), graph_sha256=record['netlist_sha256'],
                             report_sha256=sha(folder/'report.json'), gate_proof=proved['gate']))
    for p,h in inputs.items(): need(sha(Path(p)) == h, 'GATE_GRAPH_CHANGED_AFTER_BIND')
    return dict(receipt=str(receipt_path), inputs_sha256=inputs, fixtures=bindings)

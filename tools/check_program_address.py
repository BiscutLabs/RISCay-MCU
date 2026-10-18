# SPDX-License-Identifier: Apache-2.0
"""Prove bounded program-address input bits from the actual emitted logic.

Only the input of ProgramAccess's command bridge is covered. Every native or
periodic storage output in its combinational cone is an unconstrained input.
There are no reset, valid, admission, or software-state assumptions. This finite
Boolean proof does not establish physical timing; every simulated check also
requires four-state zero at the proved bits.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from gf180_estimate import ROOT, linux
from reset_bridge_proof import sram_capacities
from check_service_reply_receipt import control_widths
from check_ram_return_integration import apply_return_literal_obligations


SAT_CELLS = frozenset(('$and', '$or', '$xor', '$xnor', '$not', '$logic_not',
    '$logic_and', '$logic_or', '$mux', '$eq', '$ne', '$lt', '$le', '$gt', '$ge',
    '$reduce_or', '$reduce_and', '$reduce_bool', '$reduce_xor', '$reduce_xnor', '$add', '$sub'))
BOUNDARIES = frozenset(('$adff', '$dff', 'ChiselAsyncAsymmetricC_v1',
    'ChiselAsyncClosingLatch_v1', 'ChiselAsyncEventRegister_v1',
    'ChiselAsyncPhaseRegister_v1', 'ChiselAsyncControlGate_v1', 'ChiselAsyncPassiveDataAllowance_v1',
    'ChiselAsyncAnd_v1', 'ChiselAsyncXor_v1'))
TOP = 'ProgramAddressProof'
MAX_CELLS = 1024
MAX_BOUNDARY_BITS = 2048
sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()


def need(condition, diagnostic):
    if not condition:
        raise ValueError('PROGRAM_ADDRESS_' + diagnostic)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def rehash(inputs):
    for path, digest in inputs.items():
        need(sha(path) == digest, 'INPUT_CHANGED:' + str(path))


def binding(directory, manifest, program_bytes):
    """Bind capacity, exact 69-bit schema, generated probe and graph aliases."""
    directory = Path(directory).resolve()
    top = manifest['top']
    need(top in ('FourPhaseSoc', 'ClickSoc'), 'TOP')
    children = [c['contract'] for c in manifest['design']['children'] if c['id'] == 'program_access']
    need(len(children) == 1, 'OWNER')
    owner = children[0]
    need(owner['module'] == 'ProgramAccess' and owner['rtl_path'] == top + '.ca_child_program_access', 'OWNER_IDENTITY')
    bridges = [c['contract'] for c in owner['children'] if c['id'] == 'command_bridge']
    need(len(bridges) == 1, 'BRIDGE')
    bridge = bridges[0]
    model = 'DecoupledToClick' if top == 'ClickSoc' else 'DecoupledToFourPhase'
    prefix = 'ca_child_program_access.ca_child_command_bridge'
    need(bridge['module'] == model and bridge['rtl_path'] == top + '.' + prefix, 'BRIDGE_IDENTITY')
    channels = [c for c in bridge['channels'] if c['id'] == 'in']
    expected = [('bits.mask', 0, 4), ('bits.data', 4, 32), ('bits.write', 36, 1), ('bits.address', 37, 32)]
    need(len(channels) == 1 and channels[0]['protocol'] == 'decoupled-v1' and
         channels[0]['role'] == 'input' and channels[0]['data'] == 'in_data', 'CHANNEL')
    need([(f['field'], f['lsb'], f['width']) for f in channels[0]['layout']] == expected and
         all(f['signed'] is False and f['source'] == '~|' + model + '>in.' + f['field']
             for f in channels[0]['layout']), 'LAYOUT')
    endpoints = [e for e in bridge['endpoints'] if e['id'] == 'in_data']
    need(len(endpoints) == 1, 'ENDPOINT')
    endpoint = endpoints[0]
    need(endpoint['width'] == 69 and endpoint['source'] == '~|' + model + '>in.bits', 'ENDPOINT_SCHEMA')
    ref = directory / ('ref_' + top + '.sv')
    macro = 'ref_' + top + '_' + endpoint['probe']
    resolved = re.findall(r'^`define\s+' + re.escape(macro) + r'\s+(\S+)\s*$', ref.read_text(), re.M)
    need(len(resolved) == 1 and resolved[0].startswith(prefix + '.') and
         re.fullmatch(r'\w+(?:\.\w+)+', resolved[0]), 'PROBE_ALIAS')
    alias = resolved[0]
    need(endpoint['rtl_path'] in (top + '.' + alias, top + '.' + prefix + '.ca_p_7_in_data'), 'RESOLVED_ENDPOINT')
    capacities = sram_capacities(load(directory / 'sram.json'), top)
    need(capacities['program'] == program_bytes, 'CAPACITY')
    width, _ = control_widths(program_bytes)
    need(0 < width < 32, 'COUNT_WIDTH')
    return dict(top=top, endpoint=top + '.' + alias, alias=alias, prefix=prefix,
                program_bytes=program_bytes, count_width=width, packed_width=69,
                zero_lsb=37 + width, zero_width=32 - width, reference=str(ref))


def extract_cone(database, bound):
    """Exact graph restriction with universal unconstrained state cutpoints."""
    modules = database['modules']
    module = modules[bound['top']]
    cells, nets = module['cells'], module['netnames']
    def bits(name, width):
        need(name in nets and len(nets[name]['bits']) == width, 'NET_SHAPE:' + name)
        return nets[name]['bits']
    prefix = bound['prefix']
    address = bits(prefix + '.in_bits_address', 32)
    packed = bits(bound['alias'], 69)
    pieces = bits(prefix + '.in_bits_mask', 4) + bits(prefix + '.in_bits_data', 32) + bits(prefix + '.in_bits_write', 1) + address
    need(packed == pieces, 'PACKED_ALIAS')
    need(address == bits('ca_child_program_access.io_request_bits_address', 32), 'ACCESS_ALIAS')
    # The capacity-derived width is independently bound to both actual sources.
    bits('_ca_child_control_reply_bridge_out_bits_state_received', bound['count_width'])
    bits('fabric_controlState_imageLength', bound['count_width'])
    need(all(type(bit) is int for bit in address), 'ADDRESS_NOT_DYNAMIC_VECTOR')

    drivers = {}
    top_inputs = {bit for port in module['ports'].values() if port['direction'] == 'input'
                  for bit in port['bits'] if type(bit) is int}
    for name, cell in cells.items():
        for port, direction in cell['port_directions'].items():
            need(direction in ('input', 'output'), 'PORT_DIRECTION:' + name)
            if direction != 'output':
                continue
            for bit in cell['connections'][port]:
                if type(bit) is int:
                    need(bit not in drivers and bit not in top_inputs, 'MULTIPLE_DRIVERS')
                    drivers[bit] = (name, cell, port)
    selected, free, boundary_owners, active, done = {}, set(), {}, set(), set()
    def visit(bit):
        if bit in ('0', '1') or bit in done:
            return
        need(type(bit) is int, 'UNDEFINED_CONSTANT')
        need(bit not in active, 'COMBINATIONAL_CYCLE')
        if bit in top_inputs:
            free.add(bit)
            need(len(free) <= MAX_BOUNDARY_BITS, 'BOUNDARY_LIMIT')
            done.add(bit); return
        need(bit in drivers, 'UNDRIVEN_BIT')
        name, cell, port = drivers[bit]
        model = modules.get(cell['type'], {}).get('attributes', {}).get('hdlname', cell['type']).split()[0]
        if model in BOUNDARIES:
            if cell['type'] in ('$adff', '$dff'):
                need(port == 'Q', 'NONSTATE_FLOP_OUTPUT')
            else:
                need(modules.get(cell['type'], {}).get('attributes', {}).get('blackbox') in ('1', '00000000000000000000000000000001'), 'NATIVE_NOT_BLACKBOX')
            free.add(bit)
            boundary_owners[name] = dict(model=model, output_pin=port)
            done.add(bit)
            need(len(free) <= MAX_BOUNDARY_BITS, 'BOUNDARY_LIMIT')
            return
        need(cell['type'] in SAT_CELLS and port == 'Y', 'UNSUPPORTED_LOGIC:' + cell['type'])
        need(set(cell['port_directions']) == set(cell['connections']) and
             cell['port_directions'].get('Y') == 'output' and
             all(d == 'input' for p, d in cell['port_directions'].items() if p != 'Y'), 'COMB_PORTS')
        active.add(bit)
        for pin, direction in cell['port_directions'].items():
            if direction == 'input':
                for source in cell['connections'][pin]:
                    visit(source)
        active.remove(bit)
        done.update(cell['connections']['Y'])
        selected[name] = copy.deepcopy(cell)
        need(len(selected) <= MAX_CELLS, 'CELL_LIMIT')
    upper = address[bound['count_width']:]
    for bit in upper:
        visit(bit)
    need(selected and free and len(upper) == bound['zero_width'], 'EMPTY_PROOF')
    ports = {f'free_{bit}': dict(direction='input', bits=[bit]) for bit in sorted(free)}
    ports['upper'] = dict(direction='output', bits=upper)
    netnames = {name: dict(hide_name=0, bits=port['bits'], attributes={}) for name, port in ports.items()}
    cone = dict(creator='RISCay exact program-address combinational cone', modules={TOP: dict(
        attributes={'top': '00000000000000000000000000000001'}, ports=ports, cells=selected, netnames=netnames)})
    return cone, dict(combinational_cells=len(selected), boundary_bits=len(free),
                     boundary_owners=boundary_owners, state_assumptions=[],
                     boundary_semantics='Every retained output and top input is an unconstrained binary input.')


def source_inputs(directory, bound):
    directory = Path(directory).resolve()
    graph = directory / 'reset-crossings'
    report = load(graph / 'report.json')
    need(report['status'] == 'pass' and not report['violations'], 'RDC_NOT_PASS')
    record = report['inputs']
    need(record['top'] == bound['top'], 'RDC_TOP')
    listed = [line.strip() for line in (directory / 'filelist.f').read_text().splitlines() if line.strip()]
    need(len(listed) == len(set(listed)) and set(listed) == set(record['sources']), 'SOURCE_SET')
    inputs = {}
    for name, digest in record['sources'].items():
        path = (directory / name).resolve()
        need(path.is_relative_to(directory), 'SOURCE_OUTSIDE_EXPORT')
        inputs[str(path)] = digest
    for file, key in ((directory / 'filelist.f', 'filelist_sha256'),
                      (directory / 'contract.json', 'contract_sha256'),
                      (directory / 'sram.json', 'sram_inventory_sha256'),
                      (graph / 'netlist.json', 'netlist_sha256'),
                      (graph / 'converted.v', 'converted_sha256'),
                      (graph / 'graph.ys', 'script_sha256')):
        inputs[str(file)] = record[key]
    for tool in record['tools'].values():
        inputs[tool['path']] = tool['sha256']
    need(record['sram_capacities']['program'] == bound['program_bytes'], 'RDC_CAPACITY')
    inputs[str(graph / 'report.json')] = sha(graph / 'report.json')
    inputs[bound['reference']] = sha(bound['reference'])
    sram = ROOT / 'soc/src/main/resources/riscay/sram/gf180mcu_ocd_ip_sram__sram1024x8m8wm1.blackbox.v'
    inputs[str(sram)] = record['sram_blackbox_sha256']
    for name in ('check_program_address.py', 'check_service_reply_receipt.py',
                 'check_ram_return_integration.py', 'reset_bridge_proof.py',
                 'gf180_estimate.py', 'gf180-estimate-inputs.json'):
        path = ROOT / 'tools' / name
        inputs[str(path)] = sha(path)
    rehash(inputs)
    need(bound == binding(directory, load(directory / 'contract.json')['manifest'], bound['program_bytes']),
         'PERSISTED_CONTRACT_BINDING')
    return inputs


def sat_prove(cone, output, inputs):
    """One bounded SAT execution. Failure evidence is retained and never reused."""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    binary = ROOT / '.tools/physical/root/usr/bin/yosys'
    expected = load(ROOT / 'tools/gf180-estimate-inputs.json')['tools']['yosys']['sha256']
    need(sha(binary) == expected, 'YOSYS_IDENTITY')
    inputs = dict(inputs)
    inputs[str(binary)] = expected
    cone_path, script, log = output / 'cone.json', output / 'proof.ys', output / 'yosys.log'
    cone_path.write_text(json.dumps(cone, indent=2) + '\n', encoding='utf-8')
    script.write_text(f'read_json {linux(cone_path)}\nhierarchy -check -top {TOP}\n'
        'check -assert\nsat -prove upper 0 -verify -show-inputs -show-outputs -timeout 20\n', encoding='utf-8')
    inputs.update({str(cone_path): sha(cone_path), str(script): sha(script)})
    # Kill the Linux process group as well as the host launcher if the solver
    # fails to honor its own bound. The host bound is the last containment layer.
    command = ['wsl', '-e', 'timeout', '--signal=TERM', '--kill-after=2s', '25s', linux(binary), '-s', linux(script)]
    record = dict(status='FAIL_OR_INCOMPLETE', command=command, inputs_sha256=inputs,
                  solver_timeout_seconds=20, linux_timeout_seconds=25, linux_kill_after_seconds=2,
                  host_timeout_seconds=30, started_unix=time.time(),
                  exit_code=None, timed_out=False, physical_qualification=False)
    try:
        rehash(inputs)
        with log.open('x', encoding='utf-8') as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=30)
        record['exit_code'] = result.returncode
        record['timed_out'] = result.returncode in (124, 137)
        text = log.read_text(encoding='utf-8')
        need(result.returncode == 0 and text.count('SAT proof finished - no model found: SUCCESS!') == 1 and
             not re.search(r'ERROR:|Warning:|TIMEOUT|FAIL!', text), 'SAT_NOT_PROVED')
        rehash(inputs)
        record['status'] = 'PASS_UNIVERSAL_COMBINATIONAL_ZERO'
    except BaseException as error:
        record['error'] = repr(error)
        record['timed_out'] = record['timed_out'] or isinstance(error, subprocess.TimeoutExpired)
    finally:
        record.update(ended_unix=time.time(), log_sha256=sha(log) if log.exists() else None)
        (output / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    need(record['status'] == 'PASS_UNIVERSAL_COMBINATIONAL_ZERO', 'PROOF_FAILED:' + str(output))
    return record


def next_attempt(root):
    """Never overwrite a previous proof, including incomplete/failed attempts."""
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for index in range(1, 10001):
        target = root / f'attempt-{index:04d}'
        if not target.exists():
            return target
    raise ValueError('PROGRAM_ADDRESS_ATTEMPT_LIMIT')


def prove_program_address(directory, manifest, program_bytes, output=None):
    directory = Path(directory).resolve()
    bound = binding(directory, manifest, program_bytes)
    inputs = source_inputs(directory, bound)
    database = load(directory / 'reset-crossings/netlist.json')
    cone, scope = extract_cone(database, bound)
    target = next_attempt(output if output is not None else directory / 'verification/program-address-proof')
    receipt = sat_prove(cone, target, inputs)
    proof = dict(status=receipt['status'], binding=bound, scope=scope,
                 inputs_sha256={**receipt['inputs_sha256'], str(target.resolve() / 'receipt.json'): sha(target / 'receipt.json'),
                                str(target.resolve() / 'yosys.log'): receipt['log_sha256']},
                 physical_qualification=False)
    record = target / 'proof.json'
    record.write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    return {**proof, 'proof_record': str(record), 'proof_record_sha256': sha(record)}


def program_address_probe(source, proof):
    """Discharge only proved one-polarities; assert zero at every check (X fails)."""
    record = proof.get('proof_record')
    need(record and sha(record) == proof.get('proof_record_sha256'), 'PROOF_RECORD_HASH')
    body = {k: v for k, v in proof.items() if k not in ('proof_record', 'proof_record_sha256')}
    need(load(record) == body, 'PROOF_RECORD_BINDING')
    need(proof['status'] == 'PASS_UNIVERSAL_COMBINATIONAL_ZERO' and proof['physical_qualification'] is False,
         'PROOF_STATUS')
    rehash(proof['inputs_sha256'])
    bound = proof['binding']
    need(bound['packed_width'] == 69 and bound['zero_lsb'] == 37 + bound['count_width'] and
         bound['zero_width'] == 32 - bound['count_width'] and 0 < bound['count_width'] < 32,
         'PROOF_BOUND')
    endpoint = bound['endpoint']
    need(source.count('task check; begin') == 1, 'CHECK_SHAPE')
    assertion = f'\nif ({endpoint}[68:{bound["zero_lsb"]}] !== {bound["zero_width"]}\'h0) $fatal(1, "PROGRAM_ADDRESS_UPPER_NOT_ZERO");'
    source = source.replace('task check; begin', 'task check; begin' + assertion)
    return apply_return_literal_obligations(source, [(endpoint, 69, bit) for bit in range(bound['zero_lsb'], 69)])

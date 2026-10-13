# SPDX-License-Identifier: Apache-2.0
"""Closed emitted-RTL audit of program-bank access/capture bookkeeping.

The five-bit POR receipt acknowledges the edge that clears the access owner's
active bit. Its acceptance cannot depend on owner idle, publication or reset
debt. The access owner's fifteen clocked bits observe return and admission;
effectsDrained deliberately excludes native return occupancy, while full busy
and new admission include it. This is digital structural evidence, not timing,
metastability, mapped-state minimality or physical qualification.

This parser deliberately accepts only the inspected firtool spelling. All module
body text is consumed by an independent expected policy, including initializers,
child ports and declarations. An emitter change requires review, not a fallback.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

RELEASE = ('localReset_release_0', 'localReset_release_1')
RECEIPT_REGISTERS = RELEASE + ('requestMeta', 'requestSync', 'phase')
BYTE_STAGES = tuple((f'bytesReturned_stages_{i}_0', f'bytesReturned_stages_{i}_1')
                    if i else ('bytesReturned_stages_0', 'bytesReturned_stages_1') for i in range(4))
ACCESS_REGISTERS = RELEASE + ('returned_stages_0', 'returned_stages_1') + tuple(
    name for stages in BYTE_STAGES for name in stages) + ('ownerReturned_stages_0', 'ownerReturned_stages_1', 'active')
RECEIPT_ENDPOINTS = dict(request_meta='requestMeta', request_sync='requestSync', acknowledge_phase='phase',
    request='request', acknowledge='acknowledge', accept='accept', accepted='accepted', idle='idle',
    local_reset='localReset', reset='reset')
ACCESS_ENDPOINTS = dict(word_request='word_req', word_data='word_bits', word_acknowledge='word_ack',
    active='active', capture_request='captureRequest', capture_acknowledge='captureAcknowledge',
    return_idle='returnIdle', effects_drained='effectsDrained', reset='reset')
HEADER_POLICY = '''`ifndef RANDOMIZE `ifdef RANDOMIZE_REG_INIT `define RANDOMIZE `endif `endif
`ifndef SYNTHESIS `ifndef ENABLE_INITIAL_REG_ `define ENABLE_INITIAL_REG_ `endif `endif
`ifndef RANDOM `define RANDOM $random `endif
`ifndef INIT_RANDOM `define INIT_RANDOM `endif
`ifndef RANDOMIZE_DELAY `define RANDOMIZE_DELAY 0.002 `endif
`ifndef INIT_RANDOM_PROLOG_ `ifdef RANDOMIZE `ifdef VERILATOR
`define INIT_RANDOM_PROLOG_ `INIT_RANDOM `else
`define INIT_RANDOM_PROLOG_ `INIT_RANDOM #`RANDOMIZE_DELAY begin end `endif
`else `define INIT_RANDOM_PROLOG_ `endif `endif'''


def require(value, diagnostic):
    if not value:
        raise ValueError('PROGRAM_CAPTURE_' + diagnostic)


def clean(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)


def compact(text):
    return re.sub(r'\s+', '', clean(text))


def unique(pairs, diagnostic):
    result = dict(pairs)
    require(len(result) == len(pairs), diagnostic)
    return result


def width_text(width):
    return '' if width == 1 else f'[{width-1}:0]'


def receipt_ports():
    return {name: (direction, 1) for name, direction in (
        ('reset', 'input'), ('clock', 'input'), ('request', 'input'), ('acknowledge', 'output'),
        ('accept', 'input'), ('accepted', 'output'), ('idle', 'output'))}


def access_ports():
    ports = {n: ('input', 1) for n in ('reset', 'clock', 'io_request_valid', 'word_ack', 'captureRequest', 'returnIdle')}
    ports.update({n: ('output', 1) for n in ('io_request_ready', 'io_busy', 'word_req', 'captureAcknowledge', 'effectsDrained')})
    ports['word_bits'] = ('output', 32)
    for name, width in (('address', 32), ('write', 1), ('data', 32), ('mask', 4)):
        ports['io_request_bits_' + name] = ('input', width)
    for lane in range(4):
        ports[f'io_bytes_{lane}_ready'] = ('input', 1)
        ports[f'io_bytes_{lane}_valid'] = ('output', 1)
        for name, width in (('address', 32), ('write', 1), ('data', 8), ('enable', 1)):
            ports[f'io_bytes_{lane}_bits_' + name] = ('output', width)
        ports[f'io_completions_{lane}_ready'] = ('output', 1)
        ports[f'io_completions_{lane}_valid'] = ('input', 1)
        ports[f'io_completions_{lane}_bits'] = ('input', 8)
    return ports


def initial_policy(registers, local_reset):
    """Exact nonfunctional firtool initialization wrapper, with closed writers."""
    random = ''.join(f"{n}=_RANDOM[1'b0][{i}];" for i, n in enumerate(registers))
    release = ''.join(f"{n}=1'h1;" for n in RELEASE)
    ordinary = ''.join(f"{n}=1'h0;" for n in registers if n not in RELEASE)
    return ("`ifdef ENABLE_INITIAL_REG_ `ifdef FIRRTL_BEFORE_INITIAL `FIRRTL_BEFORE_INITIAL `endif "
        "logic [31:0] _RANDOM[0:0]; initial begin `ifdef INIT_RANDOM_PROLOG_ `INIT_RANDOM_PROLOG_ `endif "
        "`ifdef RANDOMIZE_REG_INIT _RANDOM[1'b0]=`RANDOM;" + random + "`endif "
        "if(reset)begin" + release + "end if(" + local_reset + ")begin" + ordinary + "end end "
        "`ifdef FIRRTL_AFTER_INITIAL `FIRRTL_AFTER_INITIAL `endif `endif")


def release_policy():
    return ("always@(posedge clock or posedge reset)begin if(reset)begin "
        "localReset_release_0<=1'h1;localReset_release_1<=1'h1;end else begin "
        "localReset_release_0<=1'h0;localReset_release_1<=localReset_release_0;end end")


class ClosedModule:
    def __init__(self, rtl, model, ports):
        un = clean(rtl)
        matches = list(re.finditer(r'\bmodule\s+(\w+)\s*\((.*?)\);', un, re.S))
        require(len(matches) == 1 and matches[0][1] == model, 'MODULE')
        match = matches[0]
        # Standard firtool macros precede the module. Close them too: changing
        # a macro can rewrite otherwise validated pins or inject a writer.
        prefix = un[:match.start()]
        require(compact(prefix) == compact(HEADER_POLICY), 'PREFIX')
        actual = []
        for declaration in match[2].split(','):
            p = re.fullmatch(r'\s*(input|output)\s*(?:\[(\d+):0\]\s*)?(\w+)\s*', declaration)
            require(p is not None, 'PORT_DECLARATION')
            actual.append((p[3], (p[1], int(p[2]) + 1 if p[2] else 1)))
        require(unique(actual, 'DUPLICATE_PORT') == ports, 'PORTS')
        self.remaining = compact(un[match.end():])

    def consume(self, fragment, diagnostic):
        value = compact(fragment)
        require(self.remaining.count(value) == 1, diagnostic)
        self.remaining = self.remaining.replace(value, '', 1)

    def close(self):
        require(self.remaining == 'endmodule', 'UNCONSUMED_RTL:' + self.remaining[:120])


def validate_receipt_rtl(rtl, model, click):
    module = ClosedModule(rtl, model, receipt_ports())
    for name in RECEIPT_REGISTERS:
        module.consume('reg ' + name + ';', 'RECEIPT_REGISTER:' + name)
    accepted = 'accept & requestSync != phase & ~packed_8_probe' if click else 'accept & requestSync & ~phase & ~packed_8_probe'
    for name, value in dict(packed_9_probe='reset', localReset='localReset_release_1',
                            packed_8_probe='localReset', _accepted_output=accepted).items():
        module.consume('wire ' + name + '=' + value + ';', 'RECEIPT_WIRE:' + name)
    module.consume(release_policy(), 'RECEIPT_RESET_RELEASE')
    phase = 'if(_accepted_output) phase<=requestSync;' if click else 'phase<=_accepted_output|requestSync&phase;'
    module.consume("always@(posedge clock or posedge localReset)begin if(localReset)begin "
        "requestMeta<=1'h0;requestSync<=1'h0;phase<=1'h0;end else begin "
        "requestMeta<=request;requestSync<=requestMeta;" + phase + 'end end', 'RECEIPT_ACCEPTANCE')
    module.consume(initial_policy(RECEIPT_REGISTERS, 'localReset'), 'RECEIPT_INITIALIZATION')
    for name, value in dict(acknowledge='phase', accepted='_accepted_output',
                            idle='requestSync==phase' if click else '~requestSync&~phase').items():
        module.consume('assign ' + name + '=' + value + ';', 'RECEIPT_OUTPUT:' + name)
    module.close()


def access_policy(click):
    """Expected glue, independent of the elaborated metadata and expressions."""
    wires = {'packed_1': (32, None), 'packed_0': (1, None), 'packed_8_probe': (1, 'reset')}
    children = {}
    def wire(name, width=1):
        require(name not in wires, 'POLICY_DUPLICATE_WIRE')
        wires[name] = (width, None)
        return name
    receipt = dict(reset='reset', clock='clock', request='captureRequest', acknowledge='captureAcknowledge', accept='active',
        accepted=wire('_ca_child_capture_receipt_accepted'), idle=wire('_ca_child_capture_receipt_idle'))
    children['capture_receipt'] = receipt
    native = dict(reset='reset', request_ack=wire('_ca_child_native_request_ack'), response_req='packed_0',
                  response_bits='packed_1', response_ack='word_ack')
    command = dict(reset='reset', clock='clock', in_ready=wire('_ca_child_command_bridge_in_ready'),
        in_valid='ca_child_command_bridge_in_valid', out_req=wire('_ca_child_command_bridge_out_req'),
        out_ack=native['request_ack'])
    native['request_req'] = command['out_req']
    for name, width in (('address', 32), ('write', 1), ('data', 32), ('mask', 4)):
        command['in_bits_' + name] = 'io_request_bits_' + name
        command['out_bits_' + name] = wire('_ca_child_command_bridge_out_bits_' + name, width)
        native['request_bits_' + name] = command['out_bits_' + name]
    if click:
        native['start'] = '~localReset_release_1'
    children.update(native=native, command_bridge=command)
    for i in range(4):
        request = dict(reset='reset', clock='clock', in_ack=wire(f'_ca_child_byte_request_{i}_in_ack'),
                       out_ready=f'io_bytes_{i}_ready', out_valid=f'io_bytes_{i}_valid')
        request['in_req'] = wire(f'_ca_child_native_byteRequest_{i}_req')
        native[f'byteRequest_{i}_req'] = request['in_req']
        native[f'byteRequest_{i}_ack'] = request['in_ack']
        for name, width in (('address', 32), ('write', 1), ('data', 8), ('enable', 1)):
            request['in_bits_' + name] = wire(f'_ca_child_native_byteRequest_{i}_bits_' + name, width)
            request['out_bits_' + name] = f'io_bytes_{i}_bits_' + name
            native[f'byteRequest_{i}_bits_' + name] = request['in_bits_' + name]
        reply = dict(reset='reset', clock='clock', in_ready=wire(f'_ca_child_byte_reply_{i}_in_ready'),
            in_valid=f'io_completions_{i}_valid', in_bits=f'io_completions_{i}_bits',
            out_req=wire(f'_ca_child_byte_reply_{i}_out_req'), out_bits=wire(f'_ca_child_byte_reply_{i}_out_bits', 8),
            out_ack=wire(f'_ca_child_native_byteResponse_{i}_ack'))
        for field in ('req', 'bits', 'ack'):
            native[f'byteResponse_{i}_' + field] = reply['out_' + field]
        children[f'byte_request_{i}'] = request
        children[f'byte_reply_{i}'] = reply
    # Both word phases are native. Only their complete synchronized idle
    # predicate may enter the POR access owner's admission decision.
    terms = ['returned_stages_1']
    for i, (_, stage) in enumerate(BYTE_STAGES):
        terms += [stage] + ([] if click else [f'~_ca_child_byte_request_{i}_in_ack'])
    terms += ['_ca_child_command_bridge_in_ready'] + [f'_ca_child_byte_reply_{i}_in_ready' for i in range(4)]
    terms += ['_ca_child_capture_receipt_idle']
    wires['drained'] = (1, '&'.join(terms))
    wires['ca_child_command_bridge_in_valid'] = (1, 'io_request_valid&~active&drained&ownerReturned_stages_1')
    ordinary = ACCESS_REGISTERS[2:]
    reset_assignments = ''.join(n + "<=1'h0;" for n in ordinary)
    advance = 'returned_stages_0<=' + ('packed_0==word_ack;' if click else '~packed_0&~word_ack;')
    advance += 'returned_stages_1<=returned_stages_0;'
    for i, (first, second) in enumerate(BYTE_STAGES):
        source = f'_ca_child_native_byteRequest_{i}_req'
        source = source + f'==_ca_child_byte_request_{i}_in_ack' if click else '~' + source
        advance += first + '<=' + source + ';' + second + '<=' + first + ';'
    advance += ('ownerReturned_stages_0<=returnIdle;ownerReturned_stages_1<=ownerReturned_stages_0;'
                'active<=~_ca_child_capture_receipt_accepted&(ca_child_command_bridge_in_valid|active);')
    sequential = ('always@(posedge clock or posedge localReset_release_1)begin if(localReset_release_1)begin ' +
                  reset_assignments + 'end else begin ' + advance + 'end end')
    outputs = dict(io_request_ready='~active&drained&ownerReturned_stages_1',
        io_busy='active|~drained|~ownerReturned_stages_1|localReset_release_1', word_req='packed_0', word_bits='packed_1',
        effectsDrained='~active&drained&~localReset_release_1')
    outputs.update({f'io_completions_{i}_ready': f'_ca_child_byte_reply_{i}_in_ready' for i in range(4)})
    return wires, children, sequential, outputs


def validate_access_rtl(rtl, model, click, models):
    module = ClosedModule(rtl, model, access_ports())
    for name in ACCESS_REGISTERS:
        module.consume('reg ' + name + ';', 'ACCESS_REGISTER:' + name)
    wires, children, sequential, outputs = access_policy(click)
    for name, (width, value) in wires.items():
        module.consume('wire ' + width_text(width) + name + ('' if value is None else '=' + value) + ';', 'ACCESS_WIRE:' + name)
    module.consume(release_policy(), 'ACCESS_RESET_RELEASE')
    module.consume(sequential, 'ACCESS_ACTIVE_AND_OBSERVATION')
    module.consume(initial_policy(ACCESS_REGISTERS, 'localReset_release_1'), 'ACCESS_INITIALIZATION')
    for name, pins in children.items():
        # Port order is immaterial, but every actual named port must match and
        # every instance body is consumed, rejecting extra writers/instances.
        pattern = re.escape(models[name] + 'ca_child_' + name) + r'\((.*?)\);'
        matches = list(re.finditer(pattern, module.remaining))
        require(len(matches) == 1, 'ACCESS_INSTANCE:' + name)
        match = matches[0]
        actual = []
        for connection in match[1].split(','):
            p = re.fullmatch(r'\.(\w+)\(([^()]*)\)', connection)
            require(p is not None, 'ACCESS_PIN_SYNTAX:' + name)
            actual.append((p[1], p[2]))
        require(unique(actual, 'ACCESS_DUPLICATE_PIN:' + name) == pins, 'ACCESS_PINS:' + name)
        module.consume(match[0], 'ACCESS_INSTANCE:' + name)
    for name, value in outputs.items():
        module.consume('assign ' + name + '=' + value + ';', 'ACCESS_OUTPUT:' + name)
    module.close()


def child_models(click):
    return dict(capture_receipt=('Click' if click else 'FourPhase') + 'ProgramCaptureReceipt',
        native=('Click' if click else 'FourPhase') + 'Sram', command_bridge='DecoupledToClick' if click else 'DecoupledToFourPhase',
        **{f'byte_request_{i}': 'ClickToDecoupled' if click else 'FourPhaseToDecoupled' for i in range(4)},
        **{f'byte_reply_{i}': 'DecoupledToClick' if click else 'DecoupledToFourPhase' for i in range(4)})


def endpoint_policy(node, fields):
    endpoints = unique([(e['id'], e) for e in node['endpoints']], 'ENDPOINT_DUPLICATE')
    require({n: e['width'] for n, e in endpoints.items()} ==
            {n: 32 if n == 'word_data' else 1 for n in fields}, 'ENDPOINT_INVENTORY')
    require(all(e['rtl_path'].startswith(node['rtl_path'] + '.') for e in endpoints.values()), 'ENDPOINT_PATH')
    return [(endpoints[n]['rtl_path'], node['rtl_path'] + '.' + field) for n, field in fields.items()]


def resolve(node, directory, scopes, base, registers=None):
    scope = scopes.get(node['rtl_path'], {})
    model = scope.get('model', '')
    require(re.fullmatch(re.escape(base) + r'(?:_[0-9]+)?', node['module']) and
            re.fullmatch(re.escape(base) + r'(?:_[0-9]+)?', model), 'RESOLVED_OWNER:' + base)
    if registers is not None:
        require(scope.get('registers', {}) == {n: 1 for n in registers}, 'REGISTER_INVENTORY:' + base)
        require(not scope.get('memories', {}), 'MEMORY_INVENTORY:' + base)
        ports = access_ports() if base == 'ProgramAccess' else receipt_ports()
        require(scope.get('ports', {}) == {n: dict(name=n, direction=d, width=w) for n, (d, w) in ports.items()},
                'SCOPE_PORTS:' + base)
    path = Path(directory) / (model + '.sv')
    require(path.is_file(), 'MISSING_RTL:' + model)
    return model, path.read_text(encoding='utf-8')


def validate_program_access(access, directory, scopes):
    """Validate resolved access/receipt nodes; return actual-pin probe bindings.

    The caller validates top-level peer connections and POR source. This function
    closes all logic within the access and receipt modules and all immediate
    child reset/clock/data/control pins. Child SRAM/crossing implementations stay
    under the library's existing independent export checks.
    """
    children = unique([(c['id'], c['contract']) for c in access['children']], 'CHILD_DUPLICATE')
    require('capture_receipt' in children, 'RECEIPT_MISSING')
    receipt = children['capture_receipt']
    click = bool(re.fullmatch(r'ClickProgramCaptureReceipt(?:_[0-9]+)?', receipt['module']))
    expected = child_models(click)
    require(set(children) == set(expected), 'ACCESS_CHILD_INVENTORY')
    require(not access['primitives'] and not access['timing'] and access['capacity'] is None, 'ACCESS_METADATA')
    require(not receipt['children'] and not receipt['channels'] and not receipt['primitives'] and
            not receipt['timing'] and receipt['capacity'] is None, 'RECEIPT_METADATA')
    require(all(c['rtl_path'] == access['rtl_path'] + '.ca_child_' + n and
                c['reset_domain'] == access['reset_domain'] for n, c in children.items()), 'CHILD_DOMAIN_OR_PATH')
    descendants = [p[len(access['rtl_path']) + 1:] for p in scopes if p.startswith(access['rtl_path'] + '.')]
    require({p for p in descendants if '.' not in p} == {'ca_child_' + n for n in children}, 'SCOPE_CHILD_INVENTORY')
    require(not any(p.startswith(receipt['rtl_path'] + '.') for p in scopes), 'RECEIPT_SCOPE_CHILDREN')
    channels = access['channels']
    require(len(channels) == 1, 'ACCESS_CHANNELS')
    ch = channels[0]
    require(ch['id'] == 'word' and ch['protocol'] == ('two-phase-bundled-v1' if click else 'four-phase-bundled-v1') and
        ch['role'] == 'output' and ch['reset_domain'] == access['reset_domain'] and
        all(ch[k] == 'word_' + k for k in ('request', 'data', 'acknowledge')) and
        len(ch['layout']) == 1 and all(ch['layout'][0].get(k) == v for k, v in
            dict(field='bits', lsb=0, width=32, signed=False).items()), 'ACCESS_CHANNEL_SCHEMA')
    bindings = endpoint_policy(access, ACCESS_ENDPOINTS) + endpoint_policy(receipt, RECEIPT_ENDPOINTS)
    model, rtl = resolve(access, directory, scopes, 'ProgramAccess', ACCESS_REGISTERS)
    models = {}
    for name, base in expected.items():
        child = children[name]
        models[name], child_rtl = resolve(child, directory, scopes, base,
                                          RECEIPT_REGISTERS if name == 'capture_receipt' else None)
        if name == 'capture_receipt':
            validate_receipt_rtl(child_rtl, models[name], click)
    validate_access_rtl(rtl, model, click, models)
    for name, pins in access_policy(click)[1].items():
        path = children[name]['rtl_path']
        for pin, net in pins.items():
            expression = ('~' + access['rtl_path'] + '.' + net[1:]) if net.startswith('~') else access['rtl_path'] + '.' + net
            bindings.append((path + '.' + pin, expression))
    return dict(schema='riscay-program-capture-receipt-v1', variant='click' if click else 'bd',
        access=access['rtl_path'], receipt=receipt['rtl_path'], access_clocked_bits=len(ACCESS_REGISTERS),
        receipt_clocked_bits=len(RECEIPT_REGISTERS), por=access['rtl_path'] + '.reset',
        clock=access['rtl_path'] + '.clock', bindings=bindings,
        scope='closed digital RTL and POR state ownership; no physical qualification')


def load_export(directory, library=Path('P:/Personal/chisel-async')):
    """Read the existing Icarus scope inventory, without recompiling anything."""
    directory = Path(directory)
    manifest = json.loads((directory / 'contract.json').read_text())['manifest']
    sys.path.insert(0, str(Path(library) / 'tools'))
    spec = importlib.util.spec_from_file_location('program_capture_library_checker', Path(library) / 'tools/check_export.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scopes = module.read_vvp((directory / 'sim.vvp').read_text())
    require(scopes.get('Testbench.dut', {}).get('model') == manifest['top'], 'FIXTURE_TOP')
    # Functional fixture VVP has a Testbench.dut prefix; strict export VVP uses
    # the emitted top directly. Only this CLI helper renames the known fixture.
    scopes = {manifest['top'] + key[len('Testbench.dut'):]: value
              for key, value in scopes.items() if key == 'Testbench.dut' or key.startswith('Testbench.dut.')}
    access = next(c['contract'] for c in manifest['design']['children'] if c['id'] == 'program_access')
    return access, scopes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--library', type=Path, default=Path('P:/Personal/chisel-async'))
    args = parser.parse_args()
    access, scopes = load_export(args.directory, args.library)
    print(json.dumps(validate_program_access(access, args.directory, scopes), indent=2))

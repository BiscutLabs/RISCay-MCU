# SPDX-License-Identifier: Apache-2.0
"""Generate storage from the clocked proc/opt netlist; never copy its RTL.

The storage scaffold is deliberately NOT an executable desynchronized chip.
It exposes controller enables for an area lower bound while controller wiring
is assembled. Production export requires that wiring and measured delays.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from desync_partition import flatten, partition


def latch_techmap():
    """Ordinary GF180 storage mapping; no protection or per-bit delay cells.

    Yosys dfflibmap does not map latches. Preserve enable/reset polarities,
    including set latches; let ordinary ABC share the polarity inverters.
    """
    rows = []
    for ep in ('P', 'N'):
        enable = 'E' if ep == 'P' else '~E'
        rows.append(f'module \\$_DLATCH_{ep}_ (input D,E,output Q);\n'
                    f'gf180mcu_fd_sc_mcu7t5v0__latq_1 _TECHMAP_REPLACE_ (.D(D),.E({enable}),.Q(Q));\nendmodule')
        for rp in ('P', 'N'):
            reset = '~R' if rp == 'P' else 'R'
            for value in (0, 1):
                kind, pin = ('latsnq_1', 'SETN') if value else ('latrnq_1', 'RN')
                rows.append(f'module \\$_DLATCH_{ep}{rp}{value}_ (input D,E,R,output Q);\n'
                            f'gf180mcu_fd_sc_mcu7t5v0__{kind} _TECHMAP_REPLACE_ '
                            f'(.D(D),.E({enable}),.{pin}({reset}),.Q(Q));\nendmodule')
    return '\n'.join(rows) + '\n'


def integer(cell, name):
    return int(cell['parameters'][name], 2)


def flatten_input(netlist, policy):
    """Ordinary flattened logic with non-protecting storage ownership aliases."""
    part = partition(netlist, policy)
    original, aliases = flatten(netlist['modules'], policy['top'])
    bits = {b for c in original.values() for bs in c['connections'].values() for b in bs}
    bits.update(b for bs in aliases.values() for b in bs)
    numbers = {b: i + 2 for i, b in enumerate(sorted(b for b in bits if b[0] != 'constant'))}
    def translate(b):
        return b[1] if b[0] == 'constant' else numbers[b]
    def vector(bs):
        return list(map(translate, bs))
    top = dict(attributes=dict(top='1'), ports={}, cells={}, netnames={})
    for n, p in netlist['modules'][policy['top']]['ports'].items():
        top['ports'][n] = dict(p, bits=vector(aliases[n]))
    for n, bs in aliases.items():
        top['netnames'][n] = dict(hide_name=0, bits=vector(bs), attributes={})
    for name, cell in original.items():
        top['cells'][name] = deepcopy(cell)
        top['cells'][name]['connections'] = {p: vector(bs) for p, bs in cell['connections'].items()}
    for index, row in enumerate(part['registers']):
        name = 'desync_owner/' + row['bank'] + '/' + str(index)
        top['netnames'][name] = dict(hide_name=0, bits=top['cells'][row['path']]['connections']['Q'], attributes={})
    modules = {name: deepcopy(m) for name, m in netlist['modules'].items()
               if int(m.get('attributes', {}).get('blackbox', '0'), 2)}
    modules[policy['top']] = top
    return dict(creator='RISCay desync preparation', modules=modules)


def storage_scaffold(netlist, policy, flop_banks=('cpu',)):
    """Preserve each next-state function, reset polarity and enable priority.

    Only the architectural slave is work-gated; its master tracks normally.
    Falling slaves use the existing previous-enable FF. Their resettable masters
    are also defined, since the opposite-phase slave is open at reset release.
    Added controller ports are analysis inputs, not silicon clock sources.
    """
    part = partition(netlist, policy)
    flops = set(flop_banks)
    if not flops <= part['banks'].keys():
        raise ValueError('DESYNC_UNKNOWN_FLOP_BANK')
    result = flatten_input(netlist, policy)
    top = result['modules'][policy['top']]
    next_bit = 1 + max(b for w in top['netnames'].values() for b in w['bits'] if isinstance(b, int))
    def allocate(name, width):
        nonlocal next_bit
        result = list(range(next_bit, next_bit + width)); next_bit += width
        top['netnames'][name] = dict(hide_name=0, bits=result, attributes={})
        return result
    def add(name, kind, params, connections, outputs=('Q',)):
        if name in top['cells']:
            raise ValueError('DESYNC_TRANSFORM_NAME_COLLISION:' + name)
        top['cells'][name] = dict(hide_name=0, type=kind,
            parameters={k: format(v, '032b') if isinstance(v, int) else v for k, v in params.items()},
            attributes={}, port_directions={p: 'output' if p in outputs else 'input' for p in connections},
            connections=connections)
    enables = {}
    for bank in sorted(part['banks']):
        for phase in (('capture',) if bank in flops else ('m', 's')):
            name = 'desync_' + bank + '_' + phase
            enables[bank, phase] = allocate(name, 1)
            top['ports'][name] = dict(direction='input', bits=enables[bank, phase])
    gates = {}
    def gated(bank, phase, domain, falling):
        signal = enables[bank, phase]
        if domain not in policy['gated_domains']:
            return signal
        key = bank, phase, domain, falling
        if key not in gates:
            alias = policy['falling_gate_conditions' if falling else 'gated_domains'][domain]
            name = 'desync/' + bank + '/' + phase + '/gate_' + domain
            gates[key] = allocate(name + '_q', 1)
            add(name, '$and', dict(A_SIGNED=0, B_SIGNED=0, A_WIDTH=1, B_WIDTH=1, Y_WIDTH=1),
                dict(A=signal, B=top['netnames'][alias]['bits'], Y=gates[key]), ('Y',))
        return gates[key]
    state = []
    reset_aliases = set(policy.get('defined_master_reset_aliases', []))
    matched_reset_aliases = set()
    for row in part['registers']:
        path = row['path']; c = top['cells'][path]
        ports, params = c['connections'], c['parameters']
        entry = dict(path=path, bank=row['bank'], domain=row['domain'], bits=row['bits'],
                     reset=row['reset'], falling=row['falling'], original_type=c['type'],
                     original_parameters=deepcopy(params), original_connections=deepcopy(ports))
        if not row['transformed']:
            entry.update(kind='retained', storage=[path]); state.append(entry); continue
        bank = row['bank']
        declared_reset = reset_aliases.intersection(row['aliases'])
        matched_reset_aliases.update(declared_reset)
        if declared_reset and (bank in flops or 'ARST' not in ports):
            raise ValueError('DESYNC_MASTER_RESET_BINDING:' + path)
        if bank in flops:
            if row['falling']:
                raise ValueError('DESYNC_FALLING_FLOP_EXCEPTION')
            ports['CLK'] = gated(bank, 'capture', row['domain'], False)
            params['CLK_POLARITY'] = format(1, '032b')
            entry.update(kind='flop-exception', storage=[path]); state.append(entry); continue
        del top['cells'][path]
        width = row['bits']
        def mux(suffix, a, b, select, polarity):
            output = allocate(path + '/' + suffix + '_d', width)
            add(path + '/' + suffix, '$mux', dict(WIDTH=width),
                dict(A=a if polarity else b, B=b if polarity else a, S=select, Y=output), ('Y',))
            return output
        data = ports['D']
        # Yosys sdffe: reset overrides CE; sdffce: CE overrides reset.
        operations = (('SRST', 'EN') if c['type'] == '$sdffce' else ('EN', 'SRST'))
        for op in operations:
            if op == 'EN' and op in ports:
                data = mux('enable', ports['Q'], data, ports[op], integer(c, 'EN_POLARITY'))
            elif op == 'SRST' and op in ports:
                value = list(reversed(params['SRST_VALUE']))
                if len(value) != width:
                    raise ValueError('DESYNC_RESET_WIDTH')
                data = mux('sync_reset', data, value, ports[op], integer(c, 'SRST_POLARITY'))
        master_phase, slave_phase = ('s', 'm') if row['falling'] else ('m', 's')
        middle = allocate(path + '/master_q', width)
        reset_master = (row['falling'] or bool(declared_reset)) and 'ARST' in ports
        storage = []
        for label, d, q, en, reset in (
            ('master', data, middle, enables[bank, master_phase], reset_master),
            ('slave', middle, ports['Q'], gated(bank, slave_phase, row['domain'], row['falling']), 'ARST' in ports)):
            p = dict(WIDTH=width, EN_POLARITY=1)
            connections = dict(D=d, Q=q, EN=en)
            if reset:
                connections['ARST'] = ports['ARST']
                p.update(ARST_POLARITY=params['ARST_POLARITY'], ARST_VALUE=params['ARST_VALUE'])
            name = path + '/' + label
            add(name, '$adlatch' if reset else '$dlatch', p, connections)
            storage.append(name)
        entry.update(kind='latch-pair', storage=storage, master_reset=reset_master,
                     master_reset_aliases=sorted(declared_reset))
        state.append(entry)
    if matched_reset_aliases != reset_aliases:
        raise ValueError('DESYNC_MASTER_RESET_ALIAS_MISSING:' + ','.join(sorted(reset_aliases - matched_reset_aliases)))
    for macro in part['macros']:
        top['cells'][macro['path']]['connections']['CLK'] = gated(macro['bank'], 's', macro['domain'], False)
    report = dict(schema=1, status='storage-scaffold-only',
        scope='Area lower bound; external enable placeholders, no controller/delay/stop implementation',
        state=state, partition=part, controller_ports=sorted(n for n in top['ports'] if n.startswith('desync_')),
        architectural_bits_before_optimization=sum(r['bits'] for r in state))
    return result, report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('netlist', type=Path); p.add_argument('bank_map', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--storage-scaffold', action='store_true', help='Area lower bound only; not a desync export')
    a = p.parse_args()
    if not a.storage_scaffold:
        p.error('Complete controller wiring and measured bank delays are required for a production export')
    result, report = storage_scaffold(json.loads(a.netlist.read_text()), json.loads(a.bank_map.read_text()))
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output/'storage.json').write_text(json.dumps(result) + '\n')
    (a.output/'transform.json').write_text(json.dumps(report, indent=2) + '\n')

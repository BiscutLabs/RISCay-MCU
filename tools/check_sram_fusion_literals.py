# SPDX-License-Identifier: Apache-2.0
"""Exact constant-result aliases exposed by SRAM prepare-stage removal.

Only a literal-zero input projection qualifies. Native storage is never evaluated
at reset and no activity is inferred from finite simulation samples.
"""
import hashlib
import json
from pathlib import Path
import re

from check_ram_return_integration import apply_return_literal_obligations


LAYOUT = [('bits.result', 0, 32), ('bits.request.mask', 32, 4),
          ('bits.request.data', 36, 32), ('bits.request.write', 68, 1),
          ('bits.request.address', 69, 32)]


def require(value, message):
    if not value:
        raise ValueError('SRAM_FUSION_LITERAL_'+message)


def obligations(manifest, graph):
    top = manifest['top']
    if top not in ('FourPhaseSoc', 'ClickSoc'):
        return []
    click = top == 'ClickSoc'; style = 'Click' if click else 'FourPhase'
    protocol = ('two' if click else 'four')+'-phase-bundled-v1'
    topnodes = {c['id']: c['contract'] for c in manifest['design']['children']}
    nets = graph['modules'][top]['netnames']
    result = []
    for owner in ('ram', 'program'):
        require(owner+'_access' in topnodes, 'ACCESS_MISSING')
        access = topnodes[owner+'_access']
        children = {c['id']: c['contract'] for c in access['children']}
        require('native' in children, 'NATIVE_MISSING')
        native = children['native']
        require(re.fullmatch(style+r'Sram(?:_\d+)?', native['module']), 'NATIVE_MODEL')
        children = {c['id']: c['contract'] for c in native['children']}
        require('prepare' not in children and {'lane_0_fork', 'lane_0_issue', 'lane_0_join'} <= children.keys(),
                'FUSED_TOPOLOGY')
        join = children['lane_0_join']
        stores = {c['id']: c['contract'] for c in join['children']}
        storeid = 'left_storage' if click else 'left'
        require(storeid in stores, 'LEFT_STORAGE')
        selected = [(children['lane_0_fork'], x) for x in
                    (('in', 'left', 'right') if click else ('in', 'out0', 'out1'))]
        selected += [(children['lane_0_issue'], 'in'),
                     (join, 'left' if click else 'left_input'), (stores[storeid], 'in')]
        canonical = None
        for node, channelid in selected:
            channels = [c for c in node['channels'] if c['id'] == channelid]
            require(len(channels) == 1, 'CHANNEL_INVENTORY')
            channel = channels[0]
            require(channel['protocol'] == protocol and
                    [(x['field'], x['lsb'], x['width']) for x in channel['layout']] == LAYOUT and
                    all(x['signed'] is False for x in channel['layout']), 'CHANNEL_SCHEMA')
            endpoints = [e for e in node['endpoints'] if e['id'] == channel['data']]
            require(len(endpoints) == 1 and endpoints[0]['width'] == 101, 'ENDPOINT_SCHEMA')
            endpoint = endpoints[0]['rtl_path']
            require(endpoint.startswith(top+'.'), 'ENDPOINT_ROOT')
            name = endpoint[len(top)+1:]
            require(name in nets and len(nets[name]['bits']) == 101, 'ELABORATED_ENDPOINT')
            bits = nets[name]['bits']
            require(bits[:32] == ['0']*32, 'NOT_LITERAL_ZERO:'+endpoint)
            require(all(type(b) is int for b in bits[32:]), 'REQUEST_IS_NOT_DYNAMIC:'+endpoint)
            if canonical is None:
                canonical = bits
            else:
                require(bits == canonical, 'PROJECTION_ALIAS:'+endpoint)
            result.append(dict(owner=owner, endpoint=endpoint, width=101, zero_lanes=list(range(32))))
    require(len(result) == 12 and len({r['endpoint'] for r in result}) == 12, 'ENDPOINT_INVENTORY')
    return result


def apply(source, records):
    if not records:
        return source
    require(source.count('task check; begin') == 1, 'PROBE_SHAPE')
    source = apply_return_literal_obligations(source,
        [(r['endpoint'], r['width'], lane) for r in records for lane in r['zero_lanes']])
    checks = '\n'.join(f'if ({r["endpoint"]}[31:0] !== 32\'h0) '
        f'$fatal(1,"SRAM_FUSION_LITERAL_VALUE:{r["endpoint"]}");' for r in records)
    return source.replace('task check; begin', 'task check; begin\n'+checks)


def sram_fusion_literal_probe(source, manifest, directory):
    if manifest['top'] not in ('FourPhaseSoc', 'ClickSoc'):
        return source
    # check_export has just regenerated and validated this graph from the same
    # emitted RTL. Native cells are blackboxes: their outputs stay unconstrained.
    directory = Path(directory)
    graphpath = directory/'reset-crossings/netlist.json'
    records = obligations(manifest, json.loads(graphpath.read_text()))
    result = apply(source, records)
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    proof = dict(schema='riscay-sram-fusion-literal-aliases-v1', status='PASS',
        graph_sha256=digest(graphpath), contract_sha256=digest(directory/'contract.json'),
        proof_source_sha256=digest(Path(__file__)), records=records,
        source_sha256={str(p): digest(p) for p in sorted(directory.glob('*.sv'))
                       if p.name not in ('contract_probe.sv', 'contract_first_probe.sv')},
        literal_lanes=384, dynamic_request_lanes_preserved=828)
    (directory/'sram-fusion-literal-aliases.json').write_text(json.dumps(proof, indent=2)+'\n')
    return result

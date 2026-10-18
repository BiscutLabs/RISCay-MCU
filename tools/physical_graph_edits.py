# SPDX-License-Identifier: Apache-2.0
"""Graph-preserving edits used by the production ordering-guard sizing tool."""
from collections import defaultdict
from copy import deepcopy
import subprocess
import native_stage_timing as stage
from gf180_physical import ROOT, SC, write_json
from repair_gf180_control import require


def narrow_chain(body, count):
    """Keep the reset gate and terminal DLYD; reject branches or other logic."""
    result = deepcopy(body)
    cells = result['cells']
    delays = {n: c for n, c in cells.items() if c['type'] == SC + 'dlyd_1'}
    other = {n: c for n, c in cells.items() if n not in delays}
    require(type(count) is int and 1 <= count <= len(delays), 'A7_CHAIN_COUNT')
    require(len(other) == 2 and sorted(c['type'] for c in other.values()) ==
            sorted(SC + c for c in ('inv_1', 'and2_1')), 'A7_CHAIN_RECIPE')
    inv = next(c for c in other.values() if c['type'] == SC + 'inv_1')
    gate = next(c for c in other.values() if c['type'] == SC + 'and2_1')
    require(inv['connections']['I'] == body['ports']['reset']['bits'] and
            gate['connections']['A1'] == body['ports']['a']['bits'] and
            gate['connections']['A2'] == inv['connections']['ZN'], 'A7_RESET_AND_ENDPOINT')
    node = gate['connections']['Z']; ordered = []
    while len(ordered) < len(delays):
        found = [n for n, c in delays.items() if c['connections']['I'] == node]
        require(len(found) == 1 and found[0] not in ordered, 'A7_CHAIN_BRANCH_OR_CYCLE')
        ordered.append(found[0]); node = delays[found[0]]['connections']['Z']
    terminal = cells[ordered[-1]]
    require(terminal['connections']['Z'] == body['ports']['q']['bits'], 'A7_CHAIN_TERMINUS')
    removed = ordered[count - 1:-1]
    for name in removed:
        del cells[name]
    terminal['connections']['I'] = (gate if count == 1 else cells[ordered[count - 2]])['connections']['Z'][:]
    # Every retained cell except this one terminal input must be byte-identical.
    for name, cell in cells.items():
        old = deepcopy(body['cells'][name])
        if cell is terminal:
            old['connections']['I'] = cell['connections']['I']
        require(old == cell, 'A7_UNEXPECTED_CELL_CHANGE')
    return result, ordered, removed


def partition(graph, aliases=None, omitted=()):
    """Cell-pin/top-port equivalence classes, independent of Yosys net numbers."""
    aliases = aliases or {}
    def canonical(net):
        seen=set()
        while net in aliases:
            require(net not in seen, 'PASSIVE_ALIAS_CYCLE')
            seen.add(net); net=aliases[net]
        return net
    groups=defaultdict(list)
    for name,cell in graph['cells'].items():
        if name in omitted:continue
        for pin,bits in cell['connections'].items():
            for i,bit in enumerate(bits):groups[canonical(bit)].append(('pin',name,pin,i))
    for name,port in graph['ports'].items():
        for i,bit in enumerate(port['bits']):groups[canonical(bit)].append(('port',name,'',i))
    return {tuple(sorted(tags)):(net[1] if net[0]=='constant' else 'wire') for net,tags in groups.items()}


def write_verilog(graph, output, yosys):
    # A selected repaired instance gets cloned definitions; old definitions that
    # become unreferenced are not hardware and Yosys drops them during hierarchy.
    reachable=set()
    def visit(kind):
        if kind in reachable:return
        reachable.add(kind)
        for cell in graph['modules'][kind].get('cells',{}).values():visit(cell['type'])
    visit('RiscayMcuDigital')
    graph['modules']={k:v for k,v in graph['modules'].items() if k in reachable}
    write_json(output/'netlist.json',graph)
    source=output/'write.ys'
    def filename(path):
        name=yosys.path(path);require(not any(c in name for c in '\r\n"\\'),'PASSIVE_YOSYS_PATH')
        return '"'+name+'"'
    source.write_text('read_json '+filename(output/'netlist.json')+'\n'+
                      'hierarchy -check -top RiscayMcuDigital\nwrite_verilog -noattr '+filename(output/'netlist.v')+'\n',newline='\n')
    with (output/'write.log').open('w') as stream:
        subprocess.run(yosys.command(['-s',yosys.path(source)],timeout=110),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
    stage.roundtrip(output,output,graph,yosys,ROOT/'.tools/physical/pdk')

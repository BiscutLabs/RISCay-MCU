# SPDX-License-Identifier: Apache-2.0
"""Matched ordinary flat repair/placement/CTS reference; no async-owner flow.

Uses the existing graph proof and independent clock-pin inventory. The same
script/settings must be used for the eventual desync physical comparison.
"""
import argparse
import json
from pathlib import Path
import subprocess
from gf180_physical import ROOT, SC, SRAM, write_json
from gf180_estimate import library
from gf180_netgraph import graph
from characterize_gf180_liberty import CORNERS
from repair_gf180_design import (read_verilog_json, graph_proof, buffer_sram_clocks,
                                prune_added_orphan_ties)
from physical_tools import tool
from run_receipt import RunReceipt
from gf180_slew_policy import write_views, report_rows


def root_pin(netlist, alias):
    cells, aliases = graph(netlist['modules'])
    bits = aliases[alias]
    if len(bits) != 1: raise ValueError('DESYNC_CLOCK_ROOT_WIDTH')
    drivers = [path + '/' + pin for path, c in cells.items() for pin, value in c['connections'].items()
               if value == bits and c['port_directions'][pin] == 'output']
    if len(drivers) != 1: raise ValueError('DESYNC_CLOCK_ROOT_DRIVER')
    return drivers[0]


def check_clock_coverage(expected, text):
    observed={}
    for line in text.splitlines():
        domain,edge,pin=line.split('\t')
        if edge not in ('rise','fall'):raise ValueError('CLOCKED_CTS_EDGE')
        observed.setdefault(pin,set()).add(domain)
    required={r['path']+'/'+r['clock_pin']:r['domain'] for r in expected}
    if required.keys()!=observed.keys():raise ValueError('CLOCKED_CTS_SINK_INVENTORY')
    for pin,domain in required.items():
        domain='i2c_start' if domain=='host_event' else domain
        allowed={domain,'service'} if domain=='work' else {domain}
        if domain not in observed[pin] or not observed[pin]<=allowed:
            raise ValueError('CLOCKED_CTS_SINK_DOMAIN:'+pin)
    return dict(sinks=len(required),all_sinks_reached=True)


def electrical_gate(out):
    rows={c:report_rows((out/('cts-'+c+'-electrical.rpt')).read_text()) for c in CORNERS}
    if any(rows.values()):raise ValueError('CLOCKED_PHYSICAL_ELECTRICAL_VIOLATIONS')
    return {c:len(values) for c,values in rows.items()}


def run(mapping, out):
    out.mkdir(parents=True, exist_ok=False)
    pdk = ROOT/'.tools/physical/pdk'; sram = ROOT/'.tools/gf180-sram'
    routing = ROOT/'.tools/physical/routing'
    yosys, road = tool('yosys'), tool('openroad')
    source = json.loads((mapping/'netlist.json').read_text())
    write_views(pdk,out/'liberty',CORNERS)
    libs = [library(pdk/(SC+c+'.lib')) for c in CORNERS]
    files = [mapping/'netlist.v', mapping/'netlist.json',mapping/'clocks.json',
        *[pdk/(SC+c+'.lib') for c in CORNERS], *[sram/(SRAM+'__'+c+'.lib') for c in CORNERS],
        *[out/'liberty'/(SC+c+'.lib') for c in CORNERS],
        routing/'technology.tlef', pdk/'gf180mcu_fd_sc_mcu7t5v0.lef', sram/(SRAM+'.lef')]
    receipt = RunReceipt(out/'receipt.json', inputs=files, tools=[Path(__file__),
        ROOT/'physical/gf180/clocked-physical.tcl', ROOT/'tools/repair_gf180_design.py',
        ROOT/'tools/area_ratio.py', ROOT/'tools/report_clock_owners.py',ROOT/'tools/gf180_slew_policy.py',
        *yosys.input_files(), *road.input_files()])
    outputs = []
    try:
        tied = read_verilog_json(mapping/'netlist.v', out/'tied.json', 'RiscayMcuDigital',
            yosys, pdk, source, tie_verilog=out/'tied.v')
        prune_added_orphan_ties(source, tied, 'RiscayMcuDigital', {}, libs)
        buffers = buffer_sram_clocks(tied, 'RiscayMcuDigital')
        write_json(out/'prepared.json', tied)
        prep_proof = graph_proof(source, tied, 'RiscayMcuDigital', {}, libs)
        write_json(out/'prepare-proof.json', prep_proof)
        script = out/'prepare.ys'
        script.write_text(f'read_json "{yosys.path(out/"prepared.json")}"\n'
            f'write_verilog -norename -noattr -noexpr "{yosys.path(out/"prepared.v")}"\n')
        if receipt.command(yosys.command(['-s', yosys.path(script)], timeout=180), cwd=ROOT, log=out/'prepare.log'):
            raise ValueError('CLOCKED_PHYSICAL_PREPARATION')
        work = root_pin(source, 'soc.workClock')
        cells, _ = graph(source['modules'])
        macros = sorted(n for n, c in cells.items() if c['type'] == SRAM)
        if len(macros) != 3: raise ValueError('CLOCKED_PHYSICAL_MACROS')
        config = out/'run.tcl'
        def brace(p): return '{' + road.path(p) + '}'
        text = '\n'.join('set '+name+' '+brace(value) for name, value in
            [('pdk',pdk),('liberty',out/'liberty'),('sram',sram),('routing',routing),('out',out)]) + '\n'
        text += f'set sc {SC}\nset sram_cell {SRAM}\nset work_root {{{work}}}\n'
        text += 'set macros {' + ' '.join('{'+n+'}' for n in macros) + '}\n'
        text += 'source '+brace(ROOT/'physical/gf180/clocked-physical.tcl')+'\n'
        config.write_text(text)
        if receipt.command(road.command(['-exit',road.path(config)],timeout=1800), cwd=ROOT,log=out/'physical.log'):
            raise ValueError('CLOCKED_PHYSICAL_FLOW')
        for stage in ('repaired','placed','cts'):
            candidate = read_verilog_json(out/(stage+'.v'),out/(stage+'.json'),
                'RiscayMcuDigital',yosys,pdk,source)
            removed = prune_added_orphan_ties(source,candidate,'RiscayMcuDigital',{},libs)
            if removed: raise ValueError('CLOCKED_PHYSICAL_UNUSED_ADDED_CELLS')
            proof = graph_proof(source,candidate,'RiscayMcuDigital',{},libs)
            write_json(out/(stage+'-proof.json'),proof)
        coverage=check_clock_coverage(json.loads((mapping/'clocks.json').read_text())['sinks'],
            (out/'clock-sinks.tsv').read_text())
        electrical=electrical_gate(out)
        write_json(out/'summary.json',dict(status='graph-preserved',clock_coverage=coverage,electrical_violations=electrical,
            scope='repair + placement-estimated RC + CTS; not routed signoff',
            die_um=[1940,2530],density=0.60,work_root=work,sram_clock_buffers=buffers))
    except BaseException:
        receipt.finish(outputs=[p for p in out.rglob('*') if p.is_file() and p.name!='receipt.json'],status='fail')
        raise
    outputs = [p for p in out.rglob('*') if p.is_file() and p.name!='receipt.json']
    receipt.finish(outputs=outputs)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mapping',type=Path); p.add_argument('output',type=Path)
    a=p.parse_args(); run(a.mapping.resolve(),a.output.resolve())

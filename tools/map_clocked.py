# SPDX-License-Identifier: Apache-2.0
"""GF180 mapping-only comparison for the ordinary synchronous implementation.

Uses the async flow's digital pin/reset shell, SRAM view, library and ABC recipe.
There are no async bindings or timing claims. Repair/CTS/routing remain separate.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from gf180_estimate import groups, scalar
from gf180_implement import leaves
from gf180_netgraph import graph
from report_clock_owners import inventory
from gf180_physical import ROOT, SC, SRAM, physical_top, pdk_verify, write_json
from physical_tools import tool
from run_receipt import RunReceipt
from sram_assets import validate_export, verify


def run(export, output, *, ideal_region=False):
    descriptor=export/('desync.json' if ideal_region else 'clocked.json')
    metadata = json.loads(descriptor.read_text())
    expected=('riscay-desync-v1','ideal-clock-region') if ideal_region else ('riscay-clocked-v1','synchronous')
    if (metadata['schema'],metadata['clocking']) != expected:
        raise ValueError('NOT_A_CLOCKED_EXPORT')
    validate_export(export,'1.160.0')
    macro_lock=ROOT/'soc/sram-lock.json'
    lock=json.loads(macro_lock.read_text())
    macro_library=ROOT/'.tools/gf180-sram'/(SRAM+'__tt_025C_3v30.lib')
    verify(macro_library.read_bytes(),lock['assets'][macro_library.name]['sha256'])
    output.mkdir(parents=True, exist_ok=False)
    pdk = ROOT/'.tools/physical/pdk'
    pdk_verify(pdk)
    liberty = pdk/(SC+'tt_025C_3v30.lib')
    sources = [export/s.strip() for s in (export/'filelist.f').read_text().splitlines() if s.strip()]
    if not sources or any(not p.resolve().is_relative_to(export.resolve()) for p in sources):
        raise ValueError('CLOCKED_EXPORT_SOURCES')
    if any('ChiselAsync' in p.read_text() for p in sources):
        raise ValueError('ASYNC_PRIMITIVE_IN_CLOCKED_CHIP')
    physical_top(export, output, metadata, metadata,chip_shell=not ideal_region)
    # The common shell copies the async SDC; it is not valid for this design.
    if not ideal_region:(output/'base.sdc').unlink()
    sources += [output/'RiscayMcuDigital.sv',output/'riscay_reset_hold.sv']
    yosys = tool('yosys')
    abc = yosys.executable.rsplit('/',1)[0]+'/yosys-abc'
    selected=tool('sv2v')
    receipt = RunReceipt(output/'receipt.json', inputs=[descriptor,export/'filelist.f',export/'ports.json',macro_lock,macro_library,*sources,liberty],
                         tools=[Path(__file__),ROOT/'tools/gf180_physical.py',ROOT/'tools/gf180_estimate.py',
                                ROOT/'tools/gf180_implement.py',ROOT/'tools/gf180_netgraph.py',
                                ROOT/'tools/report_clock_owners.py',ROOT/'tools/sram_assets.py',
                                ROOT/'tools/run_receipt.py',*yosys.input_files(),
                                yosys.host_path(abc),*selected.input_files()])
    converted = output/'converted.v'
    code = receipt.command(selected.command(['-DSYNTHESIS',*[selected.path(p) for p in sources]],timeout=120),
                           cwd=ROOT,log=converted)
    if code:
        receipt.finish(outputs=[converted],status='fail')
        raise ValueError('CLOCKED_CONVERSION_FAILED')
    script = output/'synth.ys'
    # Flatten ordinary RTL, as in the matched flat BD comparison. No protected
    # native leaves exist here; all logic is available to ordinary synthesis.
    script.write_text(f'read_liberty -lib {yosys.path(liberty)}\n'
        f'read_verilog -defer -sv {yosys.path(converted)}\n'
        'hierarchy -check -top RiscayMcuDigital\nflatten -noscopeinfo\n'
        'synth -top RiscayMcuDigital -noabc\n'
        f'dfflibmap -liberty {yosys.path(liberty)}\n'
        f'abc -exe {abc} -liberty {yosys.path(liberty)}\n'
        f'clean\ncheck\nstat -liberty {yosys.path(liberty)}\n'
        f'write_json {yosys.path(output/"netlist.json")}\n'
        f'write_verilog -norename -noattr -noexpr {yosys.path(output/"netlist.v")}\n')
    code = receipt.command(yosys.command(['-s',yosys.path(script)],timeout=1200),cwd=ROOT,log=output/'synth.log')
    if code:
        receipt.finish(outputs=[converted,script,output/'synth.log'],status='fail')
        raise ValueError('CLOCKED_SYNTHESIS_FAILED')
    modules = json.loads((output/'netlist.json').read_text())['modules']
    counts = Counter(c['type'] for _,c in leaves(modules,'RiscayMcuDigital'))
    area = {name:scalar(body,'area') for name,body in groups(liberty.read_text(),'cell')}
    if set(counts)-set(area)-{SRAM}:
        raise ValueError('UNMAPPED_CLOCKED_CELLS')
    expected_macros = sum((metadata[k]+1023)//1024 for k in ('program_bytes','ram_bytes'))
    if counts[SRAM] != expected_macros:
        raise ValueError('CLOCKED_SRAM_INVENTORY')
    pins = {kind:{pin:scalar(body,'capacitance') for pin,body in groups(cell,'pin')
                  if re.search(r'\bclock\s*:\s*true\s*;',body)}
            for lib in (liberty,macro_library) for kind,cell in groups(lib.read_text(),'cell') if kind in counts}
    cells, aliases = graph(modules)
    clocks = inventory(cells,aliases,pins,roots={'serviceClock':'service',
        'watchdogClock':'lf','soc.workClock':'work','sda':'host_event'})
    if clocks['native_or_unclassified_clock_sinks']:
        raise ValueError('UNCLASSIFIED_CLOCKED_SINK')
    write_json(output/'clocks.json',clocks)
    result = dict(logic_mm2=sum(n*area[k] for k,n in counts.items() if k!=SRAM)/1e6,
                  sram_macros=counts[SRAM],cells=sum(counts.values()),masters=dict(counts),
                  periodic_sinks=clocks['periodic_sinks'],clock_domains=clocks['clock_domains'],
                  rom_bytes=metadata['rom_bytes'],scope='Flat mapped logic; before repair, CTS or routing',
                  timing_qualified=False,complete_chip=not ideal_region)
    if ideal_region:
        result['scope']='Ideal-clock region ONLY: generator excluded; not a desync area-budget result'
    write_json(output/'area.json',result)
    receipt.finish(outputs=[converted,script,output/'synth.log',output/'netlist.json',output/'netlist.v',output/'area.json',output/'clocks.json'])
    print(json.dumps({k:v for k,v in result.items() if k!='masters'},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--ideal-region',action='store_true',help='Desync region lower bound; excludes generator and cannot pass the desync acceptance gate')
    args=parser.parse_args();run(args.export.resolve(),args.output.resolve(),ideal_region=args.ideal_region)

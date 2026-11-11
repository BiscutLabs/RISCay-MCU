# SPDX-License-Identifier: Apache-2.0
"""Cheap matched mapping of generated storage and optional candidate controls.

This scaffold mode exposes bank enables as analysis inputs. Its area excludes
controllers, joins, delays, stop/wake and distribution trees. It cannot emit a
production desync descriptor or claim to meet the whole-chip area budget.
Controller preparation connects the complete candidate graph, but deliberately
retains external delay apertures until measured recipes are available.
"""
import argparse
from collections import Counter
import json
import re
from pathlib import Path

from area_ratio import storage_width
from desync_transform import flatten_input, latch_techmap, storage_scaffold
from gf180_estimate import groups, scalar
from gf180_physical import ROOT, SC, SRAM
from physical_tools import tool
from run_receipt import RunReceipt


def run(source, bank_map, output, *, reference=False, controller_preparation=False, mutex_liberty=None):
    if controller_preparation and (reference or mutex_liberty is None):
        raise ValueError('DESYNC_PREPARATION_REQUIRES_MUTEX_VIEW')
    output.mkdir(parents=True, exist_ok=False)
    netlist = json.loads(source.read_text())
    policy = json.loads(bank_map.read_text())
    prepared = output/'prepared.json'
    prepared.write_text(json.dumps(flatten_input(netlist, policy)) + '\n')
    generated = output/'input.json'
    latch_map = output/'latches.v'; latch_map.write_text(latch_techmap())
    y = tool('yosys'); abc = y.executable.rsplit('/', 1)[0] + '/yosys-abc'
    lib = ROOT/'.tools/physical/pdk'/(SC+'tt_025C_3v30.lib')
    normalize = output/'normalize.ys'
    normalized = output/'normalized.json'
    normalize.write_text(f'read_json {y.path(prepared)}\nopt -full\nwreduce\npeepopt\nopt -full\n'
                         f'write_json {y.path(normalized)}\n')
    script = output/'synth.ys'
    script.write_text(f'read_liberty -lib {y.path(lib)}\nread_json {y.path(generated)}\n'
        f'hierarchy -check -top {policy["top"]}\nflatten -noscopeinfo\n'
        f'synth -top {policy["top"]} -noabc\n'
        f'dfflibmap -liberty {y.path(lib)}\n'
        f'techmap -map {y.path(latch_map)}\ntechmap\nopt\n'
        f'abc -exe {abc} -liberty {y.path(lib)}\nclean\ncheck -assert\n'
        f'stat -liberty {y.path(lib)}\nwrite_json {y.path(output/"netlist.json")}\n'
        f'write_verilog -norename -noattr -noexpr {y.path(output/"netlist.v")}\n')
    receipt = RunReceipt(output/'receipt.json', inputs=[source, bank_map, prepared, normalize, latch_map, script, lib,
        *([mutex_liberty] if mutex_liberty else [])],
        tools=[Path(__file__), ROOT/'tools/desync_transform.py', ROOT/'tools/desync_partition.py',
               ROOT/'tools/area_ratio.py',ROOT/'tools/desync_assemble.py',ROOT/'tools/desync_network.py',
               ROOT/'tools/primitives.py',ROOT/'tools/audit_desync_protection.py',ROOT/'tools/gf180_netgraph.py',
               ROOT/'tools/report_clock_owners.py',
               *y.input_files(), y.host_path(abc)])
    files = [output/'synth.log', output/'netlist.json', output/'netlist.v']
    try:
        if receipt.command(y.command(['-s', y.path(normalize)], timeout=180), cwd=ROOT, log=output/'normalize.log'):
            raise ValueError('DESYNC_STORAGE_NORMALIZE_FAILED')
        files += [normalized, output/'normalize.log']
        netlist = json.loads(normalized.read_text())
        if not reference:
            netlist, transform = storage_scaffold(netlist, policy)
            (output/'transform.json').write_text(json.dumps(transform, indent=2) + '\n')
            files.append(output/'transform.json')
        if controller_preparation:
            from desync_assemble import assemble
            netlist, control = assemble(netlist,transform,timing_preparation=True)
            (output/'control.json').write_text(json.dumps(control,indent=2)+'\n')
            files.append(output/'control.json')
        generated.write_text(json.dumps(netlist) + '\n')
        receipt.inputs += receipt.capture([generated], initial=True)
        if receipt.command(y.command(['-s', y.path(script)], timeout=1200), cwd=ROOT, log=files[0]):
            raise ValueError('DESYNC_STORAGE_MAP_FAILED')
        mapped=json.loads(files[1].read_text());top=mapped['modules'][policy['top']]
        cells = top['cells']; counts = Counter(c['type'] for c in cells.values())
        library = dict(groups(lib.read_text(), 'cell'))
        if mutex_liberty:library.update(groups(mutex_liberty.read_text(),'cell'))
        if set(counts) - library.keys() - {SRAM}:
            raise ValueError('DESYNC_STORAGE_UNMAPPED:' + ','.join(set(counts) - library.keys() - {SRAM}))
        storage = {n: storage_width(b) for n, b in library.items() if storage_width(b)}
        area = {n: scalar(b, 'area')/1e6 for n, b in library.items()}
        report = dict(status='reference-map' if reference else 'storage-scaffold-only',
            logic_mm2=sum(counts[n]*a for n, a in area.items()),
            storage_area_mm2=sum(counts[n]*area[n] for n in storage),
            storage_bits=sum(counts[n]*width for n, width in storage.items()),
            storage_by_cell={n: counts[n]*w for n, w in storage.items() if counts[n]},
            masters=dict(counts), sram_macros=counts[SRAM],
            includes_controllers=False, includes_matched_delays=False, includes_stop_wake=False,
            scope='Mapped storage experiment; no whole-chip acceptance or timing claim')
        if controller_preparation:
            from audit_desync_protection import audit
            from primitives import classified_cells, primitive
            from gf180_netgraph import graph
            from report_clock_owners import inventory
            report.update(status='controller-connected-timing-preparation',includes_controllers=True,includes_stop_wake=True,
                scope='Connected control and storage; delay apertures remain external, no whole-chip acceptance',
                protection=audit(mapped,control['bindings'],experimental=True))
            roles=Counter()
            for path,(role,cell) in classified_cells(control['bindings'],experimental=True).items():
                roles[role]+=area[cell['cell']]
            report['special_area_mm2']=dict(roles)
            report['keeper_bits']=sum(primitive(b['primitive']).keeper_bits for b in control['bindings'])
            report['total_storage_bits']=report['storage_bits']+report['keeper_bits']
            # A retired input must have no leaf consumers, including ordinary
            # gates. A zero count from a clock-name classifier alone is weaker.
            fast=top['ports']['serviceClock']['bits']
            if any(set(fast)&set(bs) for c in cells.values() for p,bs in c['connections'].items()
                   if c['port_directions'][p]=='input'):
                raise ValueError('DESYNC_RETIRED_SERVICE_CLOCK_LIVE')
            macro_lib=ROOT/'.tools/gf180-sram'/(SRAM+'__tt_025C_3v30.lib')
            receipt.inputs += receipt.capture([macro_lib],initial=True)
            library.update(groups(macro_lib.read_text(),'cell'))
            pins={k:{p:scalar(b,'capacitance') for p,b in groups(library[k],'pin')
                     if re.search(r'\bclock\s*:\s*true\s*;',b)} for k in counts}
            flat,aliases=graph(mapped['modules'])
            clocks=inventory(flat,aliases,pins,roots=dict(serviceClock='service',watchdogClock='lf',sda='host_event'))
            report['clock_inventory']=clocks
            report['retired_service_clock_has_consumers']=False
        (output/'area.json').write_text(json.dumps(report, indent=2) + '\n')
        files.append(output/'area.json')
        receipt.finish(outputs=files)
        print(json.dumps({k: v for k, v in report.items() if k not in ('masters', 'storage_by_cell','clock_inventory')}, indent=2))
    except BaseException:
        if not receipt.finished:
            receipt.finish(outputs=[p for p in files if p.is_file()], status='fail')
        raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path); p.add_argument('bank_map', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--reference', action='store_true')
    p.add_argument('--controller-preparation',action='store_true',help='Connect experimental controls, with explicit unmeasured delay apertures')
    p.add_argument('--mutex-liberty',type=Path,help='Measured experimental Mutex cell view, required for controller preparation')
    a = p.parse_args(); run(a.source.resolve(), a.bank_map.resolve(), a.output.resolve(), reference=a.reference,
        controller_preparation=a.controller_preparation,mutex_liberty=a.mutex_liberty.resolve() if a.mutex_liberty else None)

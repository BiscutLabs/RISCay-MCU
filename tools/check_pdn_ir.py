# SPDX-License-Identifier: Apache-2.0
"""Static PDN experiments with explicit perimeter sources and current assumptions.

No package, transient droop, internal SRAM grid, or signoff claim is made. The
normalized solve deliberately loads no Liberty: OpenROAD 26Q2 adds manual power
to STA current instead of replacing it. Keep the STA diagnostic in a separate
process and never mix the two current models.
"""
from __future__ import annotations
import argparse
import csv
import html
import json
import math
from pathlib import Path
import re

from gf180_constraints import brace
from gf180_pnr import pnr_tool
from gf180_physical import ROOT, SC, SRAM, sha
from run_receipt import RunReceipt

CORNERS = {'tt_025C_3v30': 3.3, 'ss_125C_3v00': 3.0,
           'ss_n40C_3v00': 3.0, 'ff_125C_3v60': 3.6, 'ff_n40C_3v60': 3.6}
# The PNR flow's nominal fit, converted to ohms/square using default LEF widths.
# M1 and all cuts are LEF fallbacks; these are exploratory, not foundry RC corners.
RESISTANCE = {'Metal1': .09, 'Metal2': .385861*.28,
              'Metal3': .206673*.28, 'Metal4': .168609*.28,
              'Metal5': .0792778*.44,
              'Via1': 4.5, 'Via2': 4.5, 'Via3': 4.5, 'Via4': 4.5}


def positive(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError('EXPECTED_FINITE_POSITIVE')
    return value


def validate_solver_log(text, expected_power):
    """Check actual solver load/source totals, not just Tcl exit status."""
    powers = [float(x) for x in re.findall(r'Total power\s*:\s*([\d.eE+-]+) W',text)]
    sources = [int(x) for x in re.findall(r'^Source nodes:\s*(\d+)',text,re.M)]
    if len(powers)!=2 or len(sources)!=2 or min(sources)<=0:
        raise ValueError('MISSING_SOLVER_POWER_OR_SOURCES')
    # The solver formats power to three significant figures.
    if any(not math.isfinite(p) or abs(p-expected_power)>max(1e-12,.006*expected_power) for p in powers):
        raise ValueError('SOLVER_CURRENT_LOAD_MISMATCH')
    return dict(zip(('VDD','VSS'),sources))


def read_inventory(path):
    records = []
    with Path(path).open(newline='') as stream:
        for row in csv.DictReader(stream, delimiter='\t'):
            for key in ('x0', 'y0', 'x1', 'y1'):
                row[key] = float(row[key])
                if not math.isfinite(row[key]):
                    raise ValueError('NONFINITE_PLACEMENT')
            row['area_um2'] = positive((row['x1']-row['x0'])*(row['y1']-row['y0']))
            records.append(row)
    if not records or len({r['instance'] for r in records}) != len(records):
        raise ValueError('EMPTY_OR_DUPLICATE_INVENTORY')
    return records


def load_powers(inventory, voltage, logic_ma, macro_ma):
    """Area-weight standard cells; assign the stated current to each SRAM."""
    logic = [r for r in inventory if r['kind'] == 'logic']
    macros = [r for r in inventory if r['kind'] == 'macro']
    area = sum(r['area_um2'] for r in logic)
    if not logic or not macros:
        raise ValueError('MISSING_LOGIC_OR_MACRO_LOADS')
    return {r['instance']: voltage * .001 * (logic_ma*r['area_um2']/area
            if r['kind'] == 'logic' else macro_ma) for r in logic+macros}


def perimeter_sources(rectangles):
    """Tile M5 rings and clamp M5 stripe ends at the ring's left/right edge.

    Explicit source files override PDNSim's automatic ideal supply-BPin sources.
    Squares have the ring width, so they do not clamp interior straps.
    """
    rings = [r for r in rectangles if r['shape'] == 'RING']
    if len(rings) != 2:
        raise ValueError('EXPECTED_TWO_HORIZONTAL_M5_RINGS')
    widths = [r['y1']-r['y0'] for r in rings]
    size = min(widths)
    positive(size)
    left, right = min(r['x0'] for r in rings), max(r['x1'] for r in rings)
    points = set()
    for ring in rings:
        if ring['x1']-ring['x0'] <= ring['y1']-ring['y0']:
            raise ValueError('EXPECTED_HORIZONTAL_RING')
        count = math.ceil((ring['x1']-ring['x0'])/size)
        for i in range(count):
            x = min(ring['x0']+size*(i+.5), ring['x1']-size/2)
            points.add((x, (ring['y0']+ring['y1'])/2, size))
    for rect in rectangles:
        for x in (left+size/2, right-size/2):
            if rect['x0'] <= x <= rect['x1']:
                points.add((x, (rect['y0']+rect['y1'])/2, size))
    return sorted(points)


def read_voltages(path, voltage, ground=False):
    by_instance = {}
    with Path(path).open(newline='') as stream:
        for row in csv.DictReader(stream):
            value = float(row['Voltage'])
            if not math.isfinite(value) or (ground and value < -2e-6) or (not ground and value > voltage+2e-6):
                raise ValueError('INVALID_NODE_VOLTAGE')
            inst = row['Instance']
            by_instance[inst] = (max if ground else min)(value, by_instance.get(inst, value))
    if not by_instance:
        raise ValueError('EMPTY_VOLTAGE_MAP')
    return by_instance


def combine_voltage_maps(inventory, vdd, vss, voltage):
    active = [r for r in inventory if r['kind'] != 'physical']
    missing = {r['instance'] for r in active} - (vdd.keys() & vss.keys())
    if missing:
        raise ValueError('MISSING_SUPPLY_VOLTAGES_' + ','.join(sorted(missing)[:5]))
    return [{**r, 'vdd_v': vdd[r['instance']], 'vss_v': vss[r['instance']],
             'drop_v': voltage-vdd[r['instance']]+vss[r['instance']]}
            for r in active]


def spatial_bins(records, die, pitch):
    """Overlap-weight footprint density; retain worst terminal drop per bin."""
    x0, y0, x1, y1 = die
    bins = {}
    for r in records:
        for iy in range(max(0, int((r['y0']-y0)//pitch)), math.ceil((r['y1']-y0)/pitch)):
            for ix in range(max(0, int((r['x0']-x0)//pitch)), math.ceil((r['x1']-x0)/pitch)):
                bx0, by0 = x0+ix*pitch, y0+iy*pitch
                bx1, by1 = min(bx0+pitch, x1), min(by0+pitch, y1)
                overlap = max(0, min(bx1,r['x1'])-max(bx0,r['x0'])) * max(0,min(by1,r['y1'])-max(by0,r['y0']))
                if overlap == 0:
                    continue
                b = bins.setdefault((ix,iy), dict(x0=bx0,y0=by0,x1=bx1,y1=by1,
                    logic_area_um2=0.,macro_area_um2=0.,drop_v=0.))
                b['logic_area_um2' if r['kind']=='logic' else 'macro_area_um2'] += overlap
                b['drop_v'] = max(b['drop_v'], r['drop_v'])
    for b in bins.values():
        area = (b['x1']-b['x0'])*(b['y1']-b['y0'])
        b['logic_density'] = b['logic_area_um2']/area
        b['macro_density'] = b['macro_area_um2']/area
    return list(bins.values())


def write_map(path, bins, die, field, title, unit, factor=1.):
    maximum = max(b[field]*factor for b in bins)
    x0,y0,x1,y1 = die
    scale = 760/(x1-x0)
    height = (y1-y0)*scale
    body = [f'<svg xmlns="http://www.w3.org/2000/svg" width="920" height="{height+120:.0f}" viewBox="0 0 920 {height+120:.0f}">',
            '<rect width="100%" height="100%" fill="white"/>',
            f'<text x="30" y="28" font-family="sans-serif" font-size="18">{html.escape(title)}</text>',
            f'<text x="30" y="50" font-family="sans-serif" font-size="13">Static exploratory model; die coordinates in µm. Scale 0–{maximum:.4g} {unit}</text>']
    for b in bins:
        value = b[field]*factor
        t = value/maximum if maximum else 0
        color = f'rgb({int(25+225*t)},{int(65+100*(1-t))},{int(210-180*t)})'
        body.append(f'<rect x="{30+(b["x0"]-x0)*scale:.3f}" y="{70+(y1-b["y1"])*scale:.3f}" width="{(b["x1"]-b["x0"])*scale:.3f}" height="{(b["y1"]-b["y0"])*scale:.3f}" fill="{color}"><title>({b["x0"]},{b["y0"]}) {value:.6g} {unit}; logic density {b["logic_density"]:.1%}</title></rect>')
    for i in range(100):
        t = 1-i/99
        body.append(f'<rect x="815" y="{80+i*2}" width="18" height="2.2" fill="rgb({int(25+225*t)},{int(65+100*(1-t))},{int(210-180*t)})"/>')
    body += [f'<text x="840" y="90" font-family="sans-serif" font-size="12">{maximum:.3g}</text>',
             '<text x="840" y="280" font-family="sans-serif" font-size="12">0</text>',
             f'<text x="30" y="{height+95:.0f}" font-family="sans-serif" font-size="12">({x0:g}, {y0:g})</text>',
             f'<text x="720" y="{height+95:.0f}" font-family="sans-serif" font-size="12">x={x1:g}</text>', '</svg>']
    Path(path).write_text('\n'.join(body), encoding='utf-8')


def inventory_script(database, out, selected):
    return f'''read_db {brace(selected.path(database))}
set block [ord::get_db_block]
set units [$block getDbUnitsPerMicron]
set f [open {brace(selected.path(out/'inventory.tsv'))} w]
puts $f "instance\tmaster\tkind\tx0\ty0\tx1\ty1"
foreach inst [$block getInsts] {{
  set master [$inst getMaster]
  set kind physical
  if {{[$master getType] eq "CORE" || [$master getType] eq "CORE_TIEHIGH" || [$master getType] eq "CORE_TIELOW"}} {{set kind logic}}
  if {{[$master isBlock]}} {{set kind macro}}
  set box [$inst getBBox]
  puts $f [join [list [$inst getName] [$master getName] $kind [expr {{double([$box xMin])/$units}}] [expr {{double([$box yMin])/$units}}] [expr {{double([$box xMax])/$units}}] [expr {{double([$box yMax])/$units}}]] "\t"]
}}
close $f
set f [open {brace(selected.path(out/'m5.tsv'))} w]
puts $f "net\tshape\tx0\ty0\tx1\ty1"
foreach netname {{VDD VSS}} {{
  set net [$block findNet $netname]
  foreach sw [$net getSWires] {{foreach box [$sw getWires] {{
    if {{[$box isVia]}} {{continue}}
    if {{[[$box getTechLayer] getName] ne "Metal5"}} {{continue}}
    puts $f [join [list $netname [$box getWireShapeType] [expr {{double([$box xMin])/$units}}] [expr {{double([$box yMin])/$units}}] [expr {{double([$box xMax])/$units}}] [expr {{double([$box yMax])/$units}}]] "\t"]
  }}}}
}}
close $f
puts PDN_INVENTORY_COMPLETE
exit
'''


def solve_script(database, out, selected, model, corner, voltage, powers, sdc, spef, density):
    lines = ['set_thread_count 4']
    if model == 'sta':
        lines += [f'read_liberty {brace(selected.path(ROOT/".tools/physical/pdk"/(SC+corner+".lib")))}',
                  f'read_liberty {brace(selected.path(ROOT/".tools/gf180-sram"/(SRAM+"__"+corner+".lib")))}']
    lines += ['report_units', f'read_db {brace(selected.path(database))}', 'set block [ord::get_db_block]',
              'set tech [$block getTech]']
    # Set database sheet/cut R consistently in both processes. Signal SPEF only
    # supplies STA signal capacitance; it does not extract the PDN resistance.
    lines += [f'[$tech findLayer {layer}] setResistance {value:.12g}' for layer,value in RESISTANCE.items()]
    if model == 'sta':
        lines += [f'read_sdc {brace(selected.path(sdc))}']
        if spef:
            lines += [f'read_spef {brace(selected.path(spef))}']
        else:
            lines += ['set_wire_rc -signal -layer Metal3', 'set_wire_rc -clock -layer Metal4', 'estimate_parasitics -placement']
        lines += [f'set_power_activity -global -density {density} -duty 0.5',
                  f'report_power -digits 9 > {brace(selected.path(out/"sta-power.rpt"))}',
                  f'report_activity_annotation > {brace(selected.path(out/"sta-activity.rpt"))}',
                  f'set f [open {brace(selected.path(out/"sta-instance-power.tsv"))} w]',
                  'puts $f "instance\tinternal_w\tswitching_w\tleakage_w\ttotal_w"',
                  'foreach inst [sta::network_leaf_instances] {puts $f [join [linsert [sta::instance_power $inst [sta::cmd_scene]] 0 [sta::get_full_name $inst]] "\t"]}',
                  'close $f']
    else:
        lines += [f'set_pdnsim_inst_power -inst {brace(name)} -power {power:.14g}' for name,power in powers.items()]
    lines += [f'set_pdnsim_net_voltage -net VDD -voltage {voltage}',
              'set_pdnsim_net_voltage -net VSS -voltage 0',
              'set_pdnsim_source_settings -external_resistance 0',
              'set_debug_level PSM resistance 1', 'set_debug_level PSM solve 3']
    for net in ('VDD','VSS'):
        prefix = out/f'{model}-{net.lower()}'
        lines += [f'check_power_grid -net {net} -error_file {brace(selected.path(prefix.with_suffix(".errors")))}',
                  f'analyze_power_grid -net {net} -vsrc {brace(selected.path(out/(net+".loc")))} -voltage_file {brace(selected.path(prefix.with_suffix(".csv")))} -enable_em -em_outfile {brace(selected.path(prefix.with_suffix(".em.csv")))}']
    lines += ['puts PDN_SOLVE_COMPLETE', 'exit']
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('output', type=Path, help='Fresh evidence directory')
    parser.add_argument('--checkpoint', default='extract')
    parser.add_argument('--corner', choices=CORNERS, default='tt_025C_3v30')
    parser.add_argument('--logic-current-ma', type=positive, default=1.)
    parser.add_argument('--macro-current-ma', type=positive, default=.1, help='Current per SRAM in normalized case')
    parser.add_argument('--density-per-ns', type=positive, default=.002, help='STA global vectorless transition density')
    parser.add_argument('--bin-um', type=positive, default=50.)
    parser.add_argument('--models', nargs='+', choices=('normalized','sta'), default=['normalized','sta'])
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.checkpoint):
        parser.error('Invalid checkpoint')
    run, out = args.run.resolve(), args.output.resolve()
    meta = json.loads((run/'run.json').read_text())
    database, sdc = run/(args.checkpoint+'.odb'), run/(args.checkpoint+'.sdc')
    recorded = meta.get('checkpoints',{}).get(args.checkpoint,{}).get('odb_sha256')
    if recorded is None or sha(database)!=recorded:
        raise ValueError('PNR_CHECKPOINT_HASH_MISMATCH')
    spef = run/'routed-nom.spef' if args.checkpoint.startswith('extract') else None
    selected = pnr_tool(meta)
    voltage = CORNERS[args.corner]
    inputs = [run/'run.json', database]
    if 'sta' in args.models:
        inputs += [sdc, ROOT/'.tools/physical/pdk'/(SC+args.corner+'.lib'), ROOT/'.tools/gf180-sram'/(SRAM+'__'+args.corner+'.lib')]
        if spef:
            inputs.append(spef)
    out.mkdir(parents=True, exist_ok=False)
    runtime_files = selected.input_files()
    wrapped = selected.host_path().with_name('.'+selected.host_path().name+'-wrapped')
    if wrapped.is_file():
        runtime_files.append(wrapped)
    receipt = RunReceipt(out/'receipt.json', inputs=inputs,
                         tools=[Path(__file__),*runtime_files])
    outputs = []
    def execute(name, script, sentinel):
        path, log = out/(name+'.tcl'), out/(name+'.log')
        path.write_text(script, encoding='utf-8')
        outputs.extend([path,log])
        code = receipt.command(selected.command(['-no_init','-exit',selected.path(path)], timeout=args.timeout), cwd=run, log=log)
        text = log.read_text(errors='replace')
        if code or sentinel not in text or re.search(r'\[ERROR |\[CRITICAL ', text):
            raise ValueError('PDN_COMMAND_FAILED_'+name)
        return text
    try:
        execute('inventory', inventory_script(database,out,selected), 'PDN_INVENTORY_COMPLETE')
        inventory = read_inventory(out/'inventory.tsv')
        with (out/'m5.tsv').open(newline='') as f:
            rectangles = [{**r, **{k:float(r[k]) for k in ('x0','y0','x1','y1')}} for r in csv.DictReader(f,delimiter='\t')]
        source_counts = {}
        for net in ('VDD','VSS'):
            points = perimeter_sources([r for r in rectangles if r['net']==net])
            (out/(net+'.loc')).write_text(''.join(f'{x:.6f},{y:.6f},{size:.6f},{voltage if net=="VDD" else 0}\n' for x,y,size in points))
            source_counts[net] = len(points)
        powers = load_powers(inventory,voltage,args.logic_current_ma,args.macro_current_ma)
        results = {}
        for model in dict.fromkeys(args.models):
            log = execute(model, solve_script(database,out,selected,model,args.corner,voltage,powers,sdc,spef,args.density_per_ns), 'PDN_SOLVE_COMPLETE')
            values = combine_voltage_maps(inventory,
                read_voltages(out/f'{model}-vdd.csv',voltage),
                read_voltages(out/f'{model}-vss.csv',voltage,ground=True),voltage)
            bins = spatial_bins(values,meta['die_um'],args.bin_um)
            (out/f'{model}-bins.json').write_text(json.dumps(bins,indent=2)+'\n')
            total_power = sum(powers.values()) if model=='normalized' else None
            if model=='sta':
                with (out/'sta-instance-power.tsv').open(newline='') as f:
                    total_power = sum(float(r['total_w']) for r in csv.DictReader(f,delimiter='\t'))
            positive(total_power)
            actual_sources = validate_solver_log(log,total_power)
            write_map(out/f'{model}-drop.svg',bins,meta['die_um'],'drop_v',f'{model}: VDD loss + VSS rise','mV',1000.)
            write_map(out/f'{model}-density.svg',bins,meta['die_um'],'logic_density',f'{model}: standard-cell footprint density','%',100.)
            maximum = max(r['drop_v'] for r in values)
            results[model] = dict(total_power_w=total_power,total_current_ma=1000*total_power/voltage,
                worst_effective_drop_mv=1000*maximum,
                normalized_mv_per_ma=maximum*voltage/total_power if model=='normalized' else None,
                maximum_vdd_drop_mv=1000*max(voltage-r['vdd_v'] for r in values),
                maximum_ground_rise_mv=1000*max(r['vss_v'] for r in values),
                checked_instances=len(values),top_instances=sorted(values,key=lambda r:r['drop_v'],reverse=True)[:20],
                mapped_source_nodes=actual_sources,
                densest_bins=sorted(bins,key=lambda r:r['logic_density'],reverse=True)[:20],
                worst_bins=sorted(bins,key=lambda r:r['drop_v'],reverse=True)[:20],
                warnings=[line for line in log.splitlines() if '[WARNING' in line])
        summary = dict(schema='riscay-pdn-ir-v1',physical_signoff=False,source_commit=meta.get('source_commit'),
            checkpoint=str(database),corner=args.corner,voltage_v=voltage,bin_um=args.bin_um,
            source_model='Optimistic ideal four-edge perimeter sources on M5 ring and strap ends; zero external resistance; explicit VSRC overrides automatic BPin sourcing',
            source_square_counts=source_counts,resistance_ohms=RESISTANCE,
            normalized_load=dict(logic_current_ma=args.logic_current_ma,distribution='standard-cell footprint area',macro_current_ma_each=args.macro_current_ma),
            sta_load=dict(global_transition_density_per_ns=args.density_per_ns,duty=.5,
                signal_parasitics=str(spef) if spef else 'placement estimate using LEF capacitance',
                activity='vectorless synthetic; SDC clock activity; no workload waveform'),
            limitations=['No actual pad, bondwire, package, regulator or board model.',
                'Static average current; no transient wake droop, decap or inductance.',
                'Nominal flow-fit sheet resistance; M1 and via resistance are unqualified LEF fallbacks. Signal SPEF does not extract the PDN.',
                'SRAM power is applied to external LEF supply terminals; macro-internal grid drop is absent.',
                'Normalized and STA loads are separate processes to avoid the pinned PDNSim additive override bug.',
                'Per-instance effective drop conservatively combines minimum VDD and maximum VSS terminals; not a matched internal transistor location.',
                'Signal-routing DRC, electrical closure and async timing remain separate gates; see the source PNR run.'],results=results)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        outputs = sorted(out.iterdir())
        receipt.finish(outputs=outputs,coverage=dict(models=list(results),physical_signoff=False))
        print(json.dumps({k:{field:v[field] for field in ('total_current_ma','worst_effective_drop_mv','checked_instances')} for k,v in results.items()},indent=2))
    except Exception:
        if not receipt.finished:
            receipt.finish(outputs=sorted(out.iterdir()),status='fail')
        raise


if __name__ == '__main__':
    main()

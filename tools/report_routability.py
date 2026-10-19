# SPDX-License-Identifier: Apache-2.0
"""Read retained OpenDB geometry and GCells; diagnose density, never claim signoff.

Example: python tools/report_routability.py build/pnr-run build/pnr-run-maps --png
The output directory must be fresh. Historical runs need not pass today's flow
provenance checks: this report identifies the exact databases it actually reads.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
import csv
import json
import math
from pathlib import Path
import re

from gf180_constraints import brace
from physical_tools import tool
from run_receipt import RunReceipt


@dataclass(frozen=True)
class Instance:
    name: str
    master: str
    kind: str
    orientation: str
    box: tuple[float, float, float, float]


def overlap(a, b):
    return max(0.0, min(a[2], b[2])-max(a[0], b[0])) * max(0.0, min(a[3], b[3])-max(a[1], b[1]))


def cell_kind(master, master_type):
    if master_type.startswith('BLOCK'):
        return 'macro'
    if master_type in {'CORE_SPACER', 'CORE_WELLTAP', 'ENDCAP_PRE', 'ENDCAP_POST'} or re.search(r'__(?:filltie|endcap|fill_\d+|decap_\d+)$', master):
        return 'physical'
    return 'logic'


def owner(instance):
    """Retained hierarchy only: never invent RTL ownership for flattened cells."""
    if instance.kind != 'logic':
        return instance.kind
    parts = instance.name.split('/')
    if len(parts) >= 3 and parts[0] == 'soc' and parts[1].startswith('ca_child_'):
        return '/'.join(parts[:2])
    if parts[0] == 'soc':
        return 'soc (flattened logic / repair; owner unresolved)'
    if instance.name.startswith(('clkbuf_', 'clknet_')):
        return 'CTS'
    return parts[0] if len(parts) > 1 else 'top (logic / repair; owner unresolved)'


def region_summary(instances, box):
    kinds = Counter()
    owners = Counter()
    counts = Counter()
    for inst in instances:
        area = overlap(inst.box, box)
        if area:
            kinds[inst.kind] += area
            owners[owner(inst)] += area
            counts[owner(inst)] += 1
    area = overlap(box, box)
    available = max(0.0, area-kinds['macro'])
    return dict(box_um=list(box), region_area_um2=area, area_um2=dict(kinds),
                footprint_density=sum(kinds.values())/area if area else None,
                standard_cell_density=(kinds['logic']+kinds['physical'])/available if available > 1e-8 else None,
                owners=[dict(owner=k, overlap_area_um2=v, intersecting_instances=counts[k])
                        for k, v in owners.most_common()])


def density_bins(instances, core, size):
    """Exact clipped rectangle intersections; no centre-point area assignment."""
    if not math.isfinite(size) or size <= 0:
        raise ValueError('INVALID_BIN_SIZE')
    nx, ny = (math.ceil((core[i+2]-core[i])/size) for i in (0, 1))
    bins = {}
    for ix in range(nx):
        for iy in range(ny):
            box = (core[0]+ix*size, core[1]+iy*size,
                   min(core[2], core[0]+(ix+1)*size), min(core[3], core[1]+(iy+1)*size))
            bins[ix, iy] = dict(box_um=list(box), area_um2=Counter(), owners=Counter())
    for inst in instances:
        lo = [max(0, math.floor((inst.box[i]-core[i])/size)) for i in (0, 1)]
        hi = [min((nx, ny)[i]-1, math.ceil((inst.box[i+2]-core[i])/size)-1) for i in (0, 1)]
        for ix in range(lo[0], hi[0]+1):
            for iy in range(lo[1], hi[1]+1):
                row = bins[ix, iy]
                area = overlap(inst.box, row['box_um'])
                if area:
                    row['area_um2'][inst.kind] += area
                    row['owners'][owner(inst)] += area
    result = []
    for (ix, iy), row in bins.items():
        area = overlap(row['box_um'], row['box_um'])
        available = max(0.0, area-row['area_um2']['macro'])
        row.update(ix=ix, iy=iy, region_area_um2=area,
                   footprint_density=sum(row['area_um2'].values())/area,
                   standard_cell_density=(row['area_um2']['logic']+row['area_um2']['physical'])/available if available > 1e-8 else None,
                   owners=[dict(owner=k, overlap_area_um2=v) for k, v in row['owners'].most_common()])
        row['area_um2'] = dict(row['area_um2'])
        result.append(row)
    return result


def congestion_summary(rows):
    """Keep zero-capacity demand visible and separate every routing layer."""
    grouped = defaultdict(list)
    for row in rows:
        if any(not math.isfinite(row[k]) or row[k] < 0 for k in ('capacity', 'usage')):
            raise ValueError('INVALID_GCELL_VALUE')
        grouped[row['layer']].append(row)
    result = {}
    for layer, cells in grouped.items():
        ratios = sorted(c['usage']/c['capacity'] for c in cells if c['capacity'] > 0)
        cap, use = (sum(c[k] for c in cells) for k in ('capacity', 'usage'))
        ranked = sorted(cells, key=lambda c: (c['usage']-c['capacity'], c['usage']/c['capacity'] if c['capacity'] else (math.inf if c['usage'] else 0)), reverse=True)
        result[layer] = dict(gcells=len(cells), capacity=cap, usage=use,
            aggregate_usage_ratio=use/cap if cap else None,
            max_usage_ratio=max(ratios) if ratios else None,
            p99_usage_ratio=ratios[max(0, math.ceil(len(ratios)*.99)-1)] if ratios else None,
            overflow=sum(max(0, c['usage']-c['capacity']) for c in cells),
            overflow_gcells=sum(c['usage'] > c['capacity'] for c in cells),
            zero_capacity_with_demand=sum(c['capacity'] == 0 and c['usage'] > 0 for c in cells),
            hottest_gcells=ranked[:10])
    if not result or not any(r['usage'] for r in result.values()):
        raise ValueError('GCELL_CONGESTION_MISSING')
    return result


def export_script(database, destination, instances, grid):
    lines = [f'read_db {brace(database)}', 'set block [ord::get_db_block]',
             f'set f [open {brace(destination)} w]',
             'puts $f "units\t[$block getDbUnitsPerMicron]"']
    for label, getter in [('die', 'getDieArea'), ('core', 'getCoreArea')]:
        lines += [f'set b [$block {getter}]', f'puts $f "{label}\t[$b xMin]\t[$b yMin]\t[$b xMax]\t[$b yMax]"']
    if instances:
        lines += ['foreach inst [$block getInsts] {',
            '  set b [$inst getBBox]; set m [$inst getMaster]',
            '  puts $f "inst\t[$inst getName]\t[$m getName]\t[$m getType]\t[$inst getOrient]\t[$b xMin]\t[$b yMin]\t[$b xMax]\t[$b yMax]"', '}']
    if grid:
        lines += ['set grid [$block getGCellGrid]',
            'if {$grid eq "NULL"} {error GCELL_GRID_MISSING}',
            'set xs [$grid getGridX]; set ys [$grid getGridY]',
            'puts $f "grid_x\t[join $xs \\t]"', 'puts $f "grid_y\t[join $ys \\t]"',
            'foreach layer [[ord::get_db_tech] getLayers] {',
            '  if {[$layer getRoutingLevel] == 0} {continue}',
            '  puts $f "layer\t[$layer getName]\t[$layer getDirection]"',
            '  for {set ix 0} {$ix < [llength $xs]} {incr ix} {',
            '    for {set iy 0} {$iy < [llength $ys]} {incr iy} {',
            '      puts $f "gcell\t[$layer getName]\t$ix\t$iy\t[$grid getCapacity $layer $ix $iy]\t[$grid getUsage $layer $ix $iy]"',
            '    }', '  }', '}']
    return '\n'.join(lines+['close $f', 'puts ROUTABILITY_EXPORT_COMPLETE', 'exit', ''])


def parse_export(path):
    meta, instances, cells = {}, [], []
    with Path(path).open(encoding='utf-8') as stream:
        for row in csv.reader(stream, delimiter='\t', quoting=csv.QUOTE_NONE):
            tag = row[0]
            if tag == 'units':
                units = float(row[1]); meta['dbu_per_um'] = units
            elif tag in {'die', 'core', 'grid_x', 'grid_y'}:
                meta[tag] = [float(v)/units for v in row[1:]]
            elif tag == 'inst':
                instances.append(Instance(row[1], row[2], cell_kind(row[2], row[3]), row[4], tuple(float(v)/units for v in row[5:])))
            elif tag == 'layer':
                meta.setdefault('layer_directions', {})[row[1]] = row[2]
            elif tag == 'gcell':
                cells.append(dict(layer=row[1], ix=int(row[2]), iy=int(row[3]), capacity=float(row[4]), usage=float(row[5])))
    for cell in cells:
        x, y = cell['ix'], cell['iy']
        xs, ys = meta['grid_x'], meta['grid_y']
        cell['box_um'] = [xs[x], ys[y], xs[x+1] if x+1 < len(xs) else meta['die'][2], ys[y+1] if y+1 < len(ys) else meta['die'][3]]
    return meta, instances, cells


def drc_boxes(text):
    pattern = r'bbox\s*=\s*\(([-\d.]+),\s*([-\d.]+)\)\s*-\s*\(([-\d.]+),\s*([-\d.]+)\)\s*on Layer (\S+)'
    return [dict(box_um=list(map(float, m[:4])), layer=m[4]) for m in re.findall(pattern, text)]


def region_argument(value):
    parts = value.split(',')
    if len(parts) != 5 or not parts[0]:
        raise argparse.ArgumentTypeError('Region must be NAME,X0,Y0,X1,Y1 in microns')
    try:
        box = tuple(float(x) for x in parts[1:])
        if not all(math.isfinite(x) for x in box) or box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError()
    except ValueError:
        raise argparse.ArgumentTypeError('Region must have finite, ordered coordinates') from None
    return parts[0], box


def render_png(output, density, cells, instances, core, drcs, regions):
    # Optional plotting dependency: all numerical reports use only the stdlib.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Rectangle
    layers = sorted({c['layer'] for c in cells if c['capacity'] or c['usage']})
    fig, axes = plt.subplots(1, 1+len(layers), figsize=(4*(1+len(layers)), 5.2), squeeze=False)
    panels = [('Standard-cell density', density, 'standard_cell_density')]
    panels += [(f'{layer} usage / capacity', [c for c in cells if c['layer'] == layer], None) for layer in layers]
    for ax, (title, records, field) in zip(axes[0], panels):
        patches, values = [], []
        for r in records:
            value = r[field] if field else (r['usage']/r['capacity'] if r['capacity'] else (1.2 if r['usage'] else None))
            if value is None:
                continue
            x0, y0, x1, y1 = r['box_um']
            patches.append(Rectangle((x0, y0), x1-x0, y1-y0)); values.append(value)
        collection = PatchCollection(patches, cmap='YlOrRd', edgecolor='none', rasterized=True)
        collection.set_array(values); collection.set_clim(0, 1)
        ax.add_collection(collection)
        for inst in instances:
            if inst.kind == 'macro':
                x0, y0, x1, y1 = inst.box
                ax.add_patch(Rectangle((x0, y0), x1-x0, y1-y0, fill=False, edgecolor='#26364a', linewidth=1.2))
                ax.text((x0+x1)/2, (y0+y1)/2, inst.name.split('fabric_')[-1].replace('_macros_', '\n'), ha='center', va='center', fontsize=7)
        for drc in drcs:
            b = drc['box_um']; ax.plot((b[0]+b[2])/2, (b[1]+b[3])/2, marker='x', color='#008ac5', markersize=8, markeredgewidth=2)
        for name, summary in regions.items():
            x0, y0, x1, y1 = summary['box_um']
            ax.add_patch(Rectangle((x0, y0), x1-x0, y1-y0, fill=False, linestyle='--', edgecolor='#005ca9', linewidth=1))
            ax.text(x0, y1+15, name, color='#005ca9', fontsize=6)
        ax.set(xlim=(core[0], core[2]), ylim=(core[1], core[3]), aspect='equal', title=title, xlabel='x (µm)')
        ax.set_ylabel('y (µm)')
        fig.colorbar(collection, ax=ax, shrink=.65, label='fraction; red ≥ 1')
    fig.suptitle('Saved database diagnostics — cyan × marks detailed-router DRC', fontsize=15)
    fig.text(.5, .03, 'Density excludes macro footprint. Saved GCell usage/capacity includes blockage reservations; no fresh route or signoff.', ha='center', fontsize=10)
    fig.tight_layout(rect=(0, .06, 1, .93)); fig.savefig(output, dpi=160); plt.close(fig)


def report(run, output, checkpoint='route', congestion_checkpoint='global', bin_size=100, png=False, regions=()):
    run, output = Path(run).resolve(), Path(output).resolve()
    meta = json.loads((run/'run.json').read_text())
    selected = replace(tool('openroad'), executable=meta['openroad'])
    inputs = [run/'run.json', run/(checkpoint+'.odb'), run/(congestion_checkpoint+'.odb')]
    drc_path = run/'route-drc.rpt'
    if drc_path.exists(): inputs.append(drc_path)
    output.mkdir(parents=True, exist_ok=False)
    receipt = RunReceipt(output/'receipt.json', inputs=inputs, tools=[Path(__file__), *selected.input_files()])
    try:
        for name, database, inst, grid in [('geometry', inputs[1], True, False), ('congestion', inputs[2], False, True)]:
            script, raw, log = (output/(name+suffix) for suffix in ('.tcl', '.tsv', '.log'))
            script.write_text(export_script(selected.path(database), selected.path(raw), inst, grid), encoding='utf-8')
            code = receipt.command(selected.command(['-exit', selected.path(script)]), cwd=output, log=log)
            if code or 'ROUTABILITY_EXPORT_COMPLETE' not in log.read_text():
                raise ValueError('ROUTABILITY_EXPORT_FAILED_'+name)
        geometry, instances, _ = parse_export(output/'geometry.tsv')
        routing, _, cells = parse_export(output/'congestion.tsv')
        if geometry['die'] != routing['die']:
            raise ValueError('ROUTABILITY_OUTLINE_MISMATCH')
        bins = density_bins(instances, geometry['core'], bin_size)
        drc_text = drc_path.read_text() if drc_path.exists() else ''
        drcs = drc_boxes(drc_text)
        if drc_text.count('violation type:') != len(drcs):
            raise ValueError('DRC_REPORT_UNPARSED')
        requested_regions = {}
        core = geometry['core']
        for name, box in regions:
            if name in requested_regions:
                raise ValueError('DUPLICATE_ANALYSIS_REGION_'+name)
            clipped = (max(core[0], box[0]), max(core[1], box[1]), min(core[2], box[2]), min(core[3], box[3]))
            if not overlap(clipped, clipped):
                raise ValueError('ANALYSIS_REGION_OUTSIDE_CORE_'+name)
            requested_regions[name] = region_summary(instances, clipped)
            requested_regions[name]['requested_box_um'] = list(box)
        hotspot_regions = {}
        macros = [i for i in instances if i.kind == 'macro']
        if macros:
            band = [geometry['core'][0], max(geometry['core'][1], min(i.box[1] for i in macros)-100), geometry['core'][2], geometry['core'][3]]
            hotspot_regions['macro_band'] = region_summary(instances, band)
        for n, drc in enumerate(drcs):
            x0, y0, x1, y1 = drc['box_um']; x, y = (x0+x1)/2, (y0+y1)/2
            for side in (100, 200):
                box = [max(geometry['core'][0], x-side/2), max(geometry['core'][1], y-side/2), min(geometry['core'][2], x+side/2), min(geometry['core'][3], y+side/2)]
                hotspot_regions[f'drc_{n}_{side}um'] = region_summary(instances, box)
        dense = sorted((b for b in bins if b['standard_cell_density'] is not None and b['region_area_um2']-b['area_um2'].get('macro', 0) >= bin_size**2/2), key=lambda b: b['standard_cell_density'], reverse=True)
        result = dict(schema='riscay-routability-v1', source_run=str(run), source_commit=meta.get('source_commit'),
            geometry_checkpoint=checkpoint, congestion_checkpoint=congestion_checkpoint,
            die_um=geometry['die'], core_um=geometry['core'], bin_size_um=bin_size,
            instances=len(instances), macros=[dict(name=i.name, orientation=i.orientation, box_um=i.box) for i in macros],
            whole_core=region_summary(instances, geometry['core']), density_bins=bins, dense_hotspots=dense[:20],
            drc_report_present=drc_path.exists(), detailed_drc_boxes=drcs, hotspot_regions=hotspot_regions, analysis_regions=requested_regions,
            congestion=congestion_summary(cells), layer_directions=routing['layer_directions'],
            interpretation=['Standard-cell density = (logic + physical cell footprints) / (region area - macro footprint).',
                'Module ownership uses surviving instance hierarchy; flattened logic and inserted repair remain explicitly unresolved.',
                'Saved GCell usage/capacity may include routing blockage reservations; it is not the demand summary printed by the initial global-route pass.',
                'Global-route congestion and detailed-router DRC are separate measurements; zero GCell overflow does not prove zero detailed DRC.',
                'No database was modified or rerouted. Historical provenance is identified, not requalified.'])
        (output/'report.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        if png:
            render_png(output/'routability.png', bins, cells, instances, geometry['core'], drcs, requested_regions)
        receipt.finish(outputs=[p for p in output.iterdir() if p.is_file()], coverage=dict(instances=len(instances), density_bins=len(bins), gcells=len(cells), detailed_drc_boxes=len(drcs), database_mutated=False, physical_qualification=False))
        return result
    except Exception:
        if not receipt.finished:
            receipt.finish(outputs=[p for p in output.iterdir() if p.is_file()], status='fail')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--checkpoint', default='route', choices=['place', 'clock', 'global', 'route', 'extract'])
    parser.add_argument('--congestion-checkpoint', default='global', choices=['global', 'route', 'extract'])
    parser.add_argument('--bin-size', type=float, default=100)
    parser.add_argument('--png', action='store_true', help='Also render PNG; requires matplotlib')
    parser.add_argument('--region', action='append', type=region_argument, default=[], help='Ownership box NAME,X0,Y0,X1,Y1 in microns; repeatable, clipped to actual core')
    args = parser.parse_args()
    report(args.run, args.output, args.checkpoint, args.congestion_checkpoint, args.bin_size, args.png, args.region)
    print(args.output/'report.json')

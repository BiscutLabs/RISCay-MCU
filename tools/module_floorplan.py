# SPDX-License-Identifier: Apache-2.0
"""BD module inventory, soft placement seeds and persistent bounded regions.

Pinned GPL treats grouped regions as bounds. These unattached OpenDB SUGGESTED
(DEF GUIDE) regions describe a deterministic seed, then Nesterov placement may
spill. Checkpoint geometry measures the result; metadata is not enforcement.
"""
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re

from gf180_constraints import brace
from gf180_estimate import groups, scalar
from gf180_implement import leaves
from gf180_physical import ROOT, SC, SRAM, write_json, sha

LABELS = {
    'cpu': 'CPU / RF / boot ROM', 'program': 'Program access', 'ram': 'RAM access',
    'control': 'Control / loader / CRC', 'i2c': 'I2C', 'spi': 'SPI / ADC',
    'telemetry': 'Telemetry / GPIO outputs', 'housekeeping': 'Housekeeping / elapsed',
    'services': 'Services / completion', 'lf_reset': 'LF / watchdog / reset',
    'platform': 'Platform / GPIO isolation',
}


def owner(path):
    """Exact hierarchy prefixes; unknown native owners fail rather than disappear."""
    p = path.replace('\\', '').split('/')
    if p[0] == 'resetHold': return 'lf_reset'
    if p[0] != 'soc': return 'platform'  # top-level repair/tie plumbing
    if len(p) < 3: return 'platform'
    root = p[1]
    if root == 'fabric': return 'services'
    if root in ('watchdog', 'timebase', 'resetBoundary'): return 'lf_reset'
    if not root.startswith('ca_child_'): return 'platform'
    n = root.removeprefix('ca_child_')
    for prefix, group in (('program_', 'program'), ('ram_', 'ram'),
                          ('telemetry', 'telemetry'), ('housekeeping', 'housekeeping'),
                          ('control', 'control'), ('completion', 'services'), ('admission', 'services')):
        if n.startswith(prefix): return group
    exact = {'core': 'cpu', 'transactions': 'cpu', 'request_bridge': 'services',
             'elapsed_scaler': 'housekeeping', 'i2c': 'i2c', 'spi_adc': 'spi'}
    if n not in exact: raise ValueError('FLOORPLAN_UNKNOWN_NATIVE_OWNER_' + root)
    return exact[n]


def region_boxes(areas, core, macro_bottom, fill=.60, grid=None, macro_locations=None):
    if not .55 <= fill <= .65 or set(areas) != set(LABELS) or any(a <= 0 for a in areas.values()):
        raise ValueError('FLOORPLAN_REGION_INVENTORY_OR_FILL')
    x0, y0, x1, y1 = core
    width = x1-x0
    # Regions stop below the partial-density SRAM escape band. Thus their usable
    # row area has no macro/halo deduction. Taps are accounted in actual density.
    top = macro_bottom-112
    boxes = {}
    rows=(('cpu', 'program', 'ram'), ('control', 'services', 'spi'),
                ('i2c', 'housekeeping', 'telemetry'))
    if macro_locations is not None:
        # Use the real gap between the two program macros, outside their hard
        # halos. The partial escape-band blockage is retained and reported.
        program=sorted((x,y) for name,x,y in macro_locations if 'program_macros_' in name)
        if len(program)!=2: raise ValueError('FLOORPLAN_PROGRAM_MACRO_INVENTORY')
        left=program[0][0]+301.3+24+8; right=program[1][0]-24-8
        bottom=macro_bottom-104+8
        height=y1-16-bottom
        usable_height=height-.5*max(0,min(y1-16,macro_bottom+146)-max(bottom,macro_bottom-104))
        w=areas['program']/(fill*usable_height)
        if height<=0 or w>right-left: raise ValueError('FLOORPLAN_PROGRAM_GAP_TOO_SMALL')
        boxes['program']=[left,bottom,left+w,y1-16]
        rows=(('cpu','ram'),rows[1],rows[2])
    for row in rows:
        height = sum(areas[n] for n in row)/(fill*(width-32))
        left = x0+16
        for n in row:
            w = areas[n]/(fill*height)
            boxes[n] = [left, top-height, left+w, top]
            left += w
        top -= height+24
    corner_height=math.sqrt(areas['lf_reset']/fill)
    for n in ('lf_reset','platform'):
        height=corner_height if macro_locations is not None else math.sqrt(areas[n]/fill)
        w=areas[n]/(fill*height)
        left=x0+16 if n=='lf_reset' else x1-w-16
        boxes[n] = [left, y0+16, left+w, y0+16+height]
    if grid is not None:
        # Fences contain complete sites/rows. Shrink rather than expand so
        # adjacent regions retain their separation. Verify fill after snapping.
        for n,b in boxes.items():
            b[:] = [round((math.ceil(v/grid[i%2]-1e-9) if i<2 else
                           math.floor(v/grid[i%2]+1e-9))*grid[i%2], 6)
                    for i,v in enumerate(b)]
            effective_height=b[3]-b[1]
            if macro_locations is not None:
                effective_height-=.5*max(0,min(b[3],macro_bottom+146)-max(b[1],macro_bottom-104))
            if b[2]<=b[0] or effective_height<=0 or not .55<=areas[n]/((b[2]-b[0])*effective_height)<=.65:
                raise ValueError('FLOORPLAN_SNAPPED_FILL_'+n)
    if any(b[0] < x0 or b[1] < y0 or b[2] > x1 or b[3] > (y1 if n=='program' and macro_locations is not None else macro_bottom-104) for n,b in boxes.items()):
        raise ValueError('FLOORPLAN_REGIONS_DO_NOT_FIT')
    for i, (a, p) in enumerate(boxes.items()):
        for b, q in list(boxes.items())[i+1:]:
            if min(p[2],q[2]) > max(p[0],q[0]) and min(p[3],q[3]) > max(p[1],q[1]):
                raise ValueError('FLOORPLAN_REGIONS_OVERLAP_' + a + '_' + b)
    return boxes


def site_grid(technology):
    match=re.search(r'(?ms)^SITE\s+GF018hv5v_mcu_sc7\s*$(.*?)^END\s+GF018hv5v_mcu_sc7\s*$',
                    technology.read_text())
    if match is None: raise ValueError('FLOORPLAN_SITE_MISSING')
    size=re.search(r'\bSIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;',match[1])
    if size is None: raise ValueError('FLOORPLAN_SITE_SIZE_MISSING')
    result=[float(v) for v in size.groups()]
    if any(v<=0 or not math.isfinite(v) for v in result): raise ValueError('FLOORPLAN_SITE_SIZE_INVALID')
    return result


def units(cells, compact, cell_area):
    """A native cluster is indivisible even when its parent driver crosses owners."""
    remaining = set(cells)
    result = []
    for group in compact:
        names = [n.replace('\\', '') for n in group['cells']]
        if not set(names) <= remaining: raise ValueError('FLOORPLAN_CLUSTER_INVENTORY')
        votes = Counter()
        for n in names: votes[owner(n)] += cell_area[cells[n]['type']]
        selected = sorted(votes, key=lambda n: (-votes[n], n))[0]
        result.append(dict(owner=selected, cells=sorted(names)))
        remaining.difference_update(names)
    result.extend(dict(owner=owner(n), cells=[n]) for n in sorted(remaining))
    return sorted(result, key=lambda r: (r['owner'], r['cells']))


def repair_budget(path, mapped, inventory=None):
    if path is None: return dict(mapped),None
    record=json.loads(path.read_text())
    expected=record.get('owner_area_um2',{})
    inputs=record.get('inputs_sha256',{})
    if (set(expected)!=set(LABELS) or not inputs or
        any(not isinstance(a,(int,float)) or not math.isfinite(a) or a<=0 for a in expected.values()) or
        any(not Path(p).is_file() or sha(Path(p))!=h for p,h in inputs.items())):
        raise ValueError('FLOORPLAN_REPAIR_BUDGET_INVALID')
    sources=record.get('sources',{})
    if (inventory is None or set(sources)!={'netlist','native','modules','checkpoint'} or
        any(p not in inputs for p in sources.values()) or
        inputs[sources['netlist']]!=inventory['netlist_sha256'] or
        json.loads(Path(sources['native']).read_text())['groups']!=inventory['native_groups'] or
        json.loads(Path(sources['modules']).read_text())['units']!=inventory['module_units']):
        raise ValueError('FLOORPLAN_REPAIR_BUDGET_INVENTORY')
    return {n:max(mapped[n],expected[n]) for n in LABELS},dict(path=str(path.resolve()),sha256=sha(path),evidence=record)


def generate(mapping, out, geometry, enabled=False, budget_path=None):
    modules = json.loads((mapping/'netlist.json').read_text())['modules']
    cells = {n.replace('\\',''): c for n,c in leaves(modules,'RiscayMcuDigital') if c['type'] != SRAM}
    areas = {n: scalar(b,'area') for n,b in groups((ROOT/'.tools/physical/pdk'/(SC+'tt_025C_3v30.lib')).read_text(),'cell')}
    compact = json.loads((out/'native-placement.json').read_text())['groups']
    # insert_tiecells/repair_tie_fanout replaces mapped constant drivers at
    # floorplanning. They are not movable functional/native placement units.
    # Retain their inventory and area; actual occupancy counts replacement ties.
    ties={n:c for n,c in cells.items() if c['type'] in (SC+'tieh',SC+'tiel')}
    seed_cells={n:c for n,c in cells.items() if n not in ties}
    # Hierarchy is mandatory for meaningful Services attribution in this mode.
    retained = any(n.startswith('soc/fabric/') for n in cells)
    if enabled and not retained:
        raise ValueError('FLOORPLAN_REQUIRES_RETAINED_SERVICES')
    assignment = units(seed_cells, compact, areas) if retained else []
    totals = Counter()
    for unit in assignment:
        totals[unit['owner']] += sum(areas[cells[n]['type']] for n in unit['cells'])
    for n,c in ties.items(): totals[owner(n)] += areas[c['type']]
    reference_error=None
    grid=site_grid(ROOT/'.tools/physical/routing/technology.tlef')
    planned,budget=repair_budget(budget_path,totals,dict(netlist_sha256=sha(mapping/'netlist.json'),
                                                       native_groups=compact,module_units=assignment))
    fill=.62 if budget else .60
    try:
        boxes = region_boxes(planned, geometry['core_um'], min(r[2] for r in geometry['macro_locations']), fill=fill, grid=grid,
                             macro_locations=geometry['macro_locations'] if budget else None) if retained else {}
    except ValueError as error:
        if enabled or not str(error).startswith(('FLOORPLAN_REGIONS_DO_NOT_FIT','FLOORPLAN_REGIONS_OVERLAP','FLOORPLAN_PROGRAM_GAP_TOO_SMALL')):
            raise
        # Unrestricted placement is allowed on outlines where our reference
        # region arrangement does not fit. It must not inherit a fence limit.
        boxes={}; reference_error=str(error)
    rows = [dict(id=n,label=LABELS[n],box_um=b,repaired_logic_um2=totals[n],target_fill=fill,
                 planning_area_um2=planned[n],planning_fill=planned[n]/((b[2]-b[0])*(b[3]-b[1])),
                 snapped_fill=totals[n]/((b[2]-b[0])*(b[3]-b[1])))
            for n,b in boxes.items()]
    bottom=min(r[2] for r in geometry['macro_locations'])
    for row in rows:
        b=row['box_um']; effective=(b[2]-b[0])*((b[3]-b[1])-.5*max(0,min(b[3],bottom+146)-max(b[1],bottom-104)))
        row['effective_region_um2']=effective
        row['capacity_scope']='Band-adjusted rectangle; fixed taps/endcaps are reported separately in actual occupancy'
        row['planning_effective_fill']=planned[row['id']]/effective
        if not .55<=row['planning_effective_fill']<=.65: raise ValueError('FLOORPLAN_EFFECTIVE_FILL_'+row['id'])
    bounded = enabled in ('bounded','guided')
    record = dict(mode='guided-regions' if enabled=='guided' else ('bounded-regions' if bounded else ('movable-region-seed' if enabled else 'unrestricted')),regions=rows,
                  site_grid_um=grid,
                  repair_budget=budget,
                  units=assignment, logical_owners={n: owner(n) for n in cells} if retained else {},
                  replaceable_mapped_ties={n:c['type'] for n,c in ties.items()},
                  reference_region_error=reference_error,
                  scope=('Bounded GPL and initial legalization; local repair may spill after explicit release' if enabled=='guided' else
                         ('Persistent placement bounds' if bounded else 'GUIDE metadata plus movable seed; unrestricted GPL may spill; not power islands')))
    write_json(out/'module-regions.json',record)
    text = f'set module_region_seed {int(bool(enabled))}\nset module_region_bounded {int(bounded)}\nset module_region_guided {int(enabled=="guided")}\nset module_region_grid {{{grid[0]} {grid[1]}}}\nset module_regions {{\n'
    for r in rows: text += '  {'+r['id']+' {'+' '.join(map(str,r['box_um']))+'}}\n'
    text += '}\nset module_units {\n'
    for r in assignment:
        text += '  {'+r['owner']+' {'+' '.join(brace(n) for n in r['cells'])+'}}\n'
    (out/'module-regions.tcl').write_text(text+'}\n')
    return record

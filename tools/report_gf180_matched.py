# SPDX-License-Identifier: Apache-2.0
"""Current mapped area/leakage accounting; no timing or whole-chip power claim."""
from collections import Counter
import ast
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from gf180_estimate import groups, library, scalar, read_activity
from gf180_implement import leaves
from gf180_physical import SC, SRAM, pdk_verify, sha
from gf180_netgraph import periodic_loads


def measurement_helper_hashes():
    """Bind the complete local static-import closure, including function imports."""
    pending=[Path(__file__).resolve(),ROOT/'tools/gf180_matched.py']
    hashes={}
    while pending:
        path=pending.pop().resolve()
        name=str(path.relative_to(ROOT))
        if name in hashes: continue
        hashes[name]=sha(path)
        for node in ast.walk(ast.parse(path.read_text(),filename=str(path))):
            imports=([node.module] if isinstance(node,ast.ImportFrom) and node.module
                     else [alias.name for alias in node.names] if isinstance(node,ast.Import) else [])
            for module in imports:
                helper=ROOT/'tools'/(module.split('.')[0]+'.py')
                if helper.is_file(): pending.append(helper)
    return dict(sorted(hashes.items()))


def validate_measurement_helpers(expected):
    if measurement_helper_hashes()!=expected:
        raise ValueError('MEASUREMENT_HELPER_CHANGED')


def validate_independent_audit(path,base):
    """Validate the actual independently reviewed artifacts, not receipt labels alone."""
    path=path.resolve()
    audit=json.loads(path.read_text())
    if (audit.get('status')!='PASS_WITH_SCOPE_CAVEATS' or
        set(audit.get('variants',{}))!={'baseline-bd','baseline-click','current-bd','current-click'} or
        not audit.get('inputs') or not audit.get('working_source_sha256')):
        raise ValueError('INDEPENDENT_AUDIT_INCOMPLETE')
    audit_script=path.parent/'audit_cost.py'
    if sha(audit_script)!=audit.get('script_sha256'):
        raise ValueError('INDEPENDENT_AUDIT_SCRIPT_CHANGED')
    for name,expected in audit['inputs'].items():
        target=(ROOT/name).resolve()
        if not target.is_relative_to(ROOT) or sha(target)!=expected:
            raise ValueError('INDEPENDENT_AUDIT_INPUT_CHANGED_'+name)
    for name,expected in audit['working_source_sha256'].items():
        revision,relative=name.split(':',1)
        if revision not in ('baseline','current'):
            raise ValueError('INDEPENDENT_AUDIT_UNKNOWN_REVISION')
        checkout=base/'baseline' if revision=='baseline' else ROOT
        target=(checkout/relative).resolve()
        if not target.is_relative_to(checkout) or sha(target)!=expected:
            raise ValueError('INDEPENDENT_AUDIT_SOURCE_CHANGED_'+name)
    # Require the executed testbench/binary/log for every measured candidate.
    for revision in ('baseline','current'):
        for variant in ('four-phase','click'):
            for name in ('testbench.sv','sim.vvp','simulation.log'):
                target=base/(revision+'-'+variant+'-activity-r1')/name
                if str(target.relative_to(ROOT)) not in audit['inputs']:
                    raise ValueError('INDEPENDENT_AUDIT_ACTIVITY_BINDING_MISSING')
    return dict(receipt=str(path.relative_to(ROOT)),receipt_sha256=sha(path),
                script=str(audit_script.relative_to(ROOT)),script_sha256=sha(audit_script),
                checked_input_files=len(audit['inputs']),
                checked_source_files=len(audit['working_source_sha256']),
                status=audit['status'],common_workload_sha256=audit['common_workload_sha256'])


import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base',type=Path,default=ROOT/'build/matched-service-comparison')
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--audit-receipt',type=Path,
                    help='Defaults to BASE/cost-review/independent-accounting.json; all recorded bytes must still match.')
args=parser.parse_args()
BASE=args.base.resolve()
if args.output.exists(): raise ValueError('REPORT_ALREADY_EXISTS')
audit_path=args.audit_receipt or BASE/'cost-review/independent-accounting.json'
measurement_helpers=measurement_helper_hashes()
independent_audit=validate_independent_audit(audit_path,BASE)
PDK = ROOT / '.tools/physical/pdk'
pdk_verify(PDK)
lock = json.loads((ROOT / 'soc/sram-lock.json').read_text())
corners = ('tt_025C_3v30', 'ss_n40C_3v00', 'ss_125C_3v00', 'ff_n40C_3v60', 'ff_125C_3v60')
metrics = {}
inputs = {}
macro_lef = ROOT / '.tools/gf180-sram' / (SRAM + '.lef')
assert sha(macro_lef) == lock['assets'][macro_lef.name]['sha256'], 'SRAM_LEF_HASH'
sizes = re.findall(r'^\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;', macro_lef.read_text(), re.M)
assert len(sizes) == 1, 'SRAM_LEF_SIZE'
macro_footprint_um2 = float(sizes[0][0]) * float(sizes[0][1])
inputs[str(macro_lef.relative_to(ROOT))] = sha(macro_lef)
for corner in corners:
    path = PDK / (SC + corner + '.lib')
    cells = library(path)
    inputs[str(path.relative_to(ROOT))] = sha(path)
    metric = {}
    for name, body in cells.items():
        conditional = [scalar(x, 'value') for _, x in groups(body, 'leakage_power') if 'when' in x]
        values = conditional or [scalar(x, 'value') for _, x in groups(body, 'leakage_power')]
        assert values, ('MISSING_LEAKAGE', name)
        metric[name] = dict(area_um2=scalar(body, 'area'), min_uw=min(values), max_uw=max(values))
    path = ROOT / '.tools/gf180-sram' / (SRAM + '__' + corner + '.lib')
    assert sha(path) == lock['assets'][path.name]['sha256'], 'SRAM_HASH'
    inputs[str(path.relative_to(ROOT))] = sha(path)
    text = path.read_text()
    assert re.search(r'leakage_power_unit\s*:\s*"1mW"', text), 'SRAM_LEAK_UNIT'
    cells = dict(groups(text, 'cell'))
    assert set(cells) == {SRAM}, 'SRAM_CELL_INVENTORY'
    body = cells[SRAM]
    # This pinned SRAM has one state-independent aggregate leakage datum.
    assert not list(groups(body, 'leakage_power')), 'SRAM_NEW_STATE_TABLE'
    value = scalar(body, 'cell_leakage_power') * 1000
    metric[SRAM] = dict(area_um2=scalar(body, 'area'), min_uw=value, max_uw=value)
    assert all(math.isfinite(v) and v >= 0 for m in metric.values() for v in m.values())
    metrics[corner] = metric

result = dict(status='PRELIMINARY_LIBRARY_ESTIMATE_NOT_PHYSICAL_QUALIFICATION',
    baseline='8637099bb603543b4d8e1d76de2bf165bbaa171a', candidate='2e4169c2f1befd1e8c5dfc704d9e936fe70e1a90',
    scope='Actual synthesized physical candidate including preserved native adapters and three SRAMs',
    exclusions=['Analog circuits and pads', 'Placement/clock-tree/route overhead',
                'State-correlated standby measurement', 'Dynamic wake energy', 'Storage-clock pin capacitance excludes clock buffers, CTS and wires',
                'Qualification of the currently overlong physical guards'],
    leakage_method='Independent listed-state SC envelope plus the SRAM aggregate datum, converted mW to uW; not a reachable standby state.',
    area_method='area_um2 sums Liberty area. area_with_sram_lef_um2 replaces the three SRAM Liberty areas with pinned LEF dimensions; no placement utilization or routing overhead.',
    leakage_limit='Listed-state SC envelope plus one SRAM aggregate datum; not measured standby power or a complete silicon bound.',
    variants={}, input_sha256=inputs, script_sha256=sha(__file__),
    measurement_helpers_sha256=measurement_helpers,independent_audit=independent_audit)
for revision, variant, activity_variant in ((r,v,a) for r in ('baseline','current') for v,a in (('bd','four-phase'),('click','click'))):
    folder = BASE / ('mapped-' + revision + '-' + variant + '-r1')
    record = json.loads((folder / 'mapping.json').read_text())
    audit = json.loads((folder / 'netlist-audit.json').read_text())
    assert audit['status'] == 'pass'
    assert audit['mapping_sha256'] == sha(folder / 'mapping.json')
    assert audit['netlist_sha256'] == sha(folder / 'netlist.v')
    modules = json.loads((folder / 'netlist.json').read_text())['modules']
    clock_library=library(PDK/(SC+corners[0]+'.lib'))
    clock_library.update(dict(groups((ROOT/'.tools/gf180-sram'/(SRAM+'__'+corners[0]+'.lib')).read_text(),'cell')))
    actual = dict(leaves(modules, 'RiscayMcuDigital'))
    counts = Counter(c['type'] for c in actual.values())
    assert counts == audit['cell_counts'] and counts[SRAM] == 3, 'LEAF_AUDIT'
    categories = {'ordinary_logic': counts.copy(), 'native_control_guards': Counter(),
                  'native_other': Counter(), 'sram': Counter({SRAM: 3})}
    categories['ordinary_logic'][SRAM] -= 3
    for binding in record['bindings']:
        category = 'native_control_guards' if binding['requirements'].get('role') == 'matched-control-delay' else 'native_other'
        for instance in binding['instances']:
            prefix = audit['adapter_instances'][instance] + '/'
            for cell in binding['cells']:
                assert actual[prefix + cell['name']]['type'] == cell['cell'], 'ADAPTER_CELL'
                categories[category][cell['cell']] += 1
                categories['ordinary_logic'][cell['cell']] -= 1
    assert all(v >= 0 for c in categories.values() for v in c.values()), 'OVERLAPPING_CATEGORIES'
    assert sum(sum(c.values()) for c in categories.values()) == len(actual)
    per_category = {}
    for category, count in categories.items():
        per_category[category] = dict(cells=sum(count.values()), area_um2=sum(n * metrics[corners[0]][k]['area_um2'] for k,n in count.items()),
            leakage_uw={corner:{bound:sum(n * metrics[corner][k][bound+'_uw'] for k,n in count.items()) for bound in ('min','max')} for corner in corners})
    totals = dict(cells=len(actual), area_um2=sum(v['area_um2'] for v in per_category.values()),
                  leakage_uw={corner:{bound:sum(v['leakage_uw'][corner][bound] for v in per_category.values()) for bound in ('min','max')} for corner in corners})
    totals['area_with_sram_lef_um2'] = totals['area_um2'] - per_category['sram']['area_um2'] + 3 * macro_footprint_um2
    totals['sram_area_per_macro'] = dict(liberty_um2=metrics[corners[0]][SRAM]['area_um2'], lef_um2=macro_footprint_um2)
    totals['clock_loads']=periodic_loads(modules,clock_library)
    owners={}
    for path,cell in actual.items():
        parts=path.split('/')
        owner='/'.join(parts[:2]) if len(parts)>2 else parts[0]
        row=owners.setdefault(owner,dict(cells=0,area_um2=0.0))
        row['cells']+=1; row['area_um2']+=metrics[corners[0]][cell['type']]['area_um2']
    for name in ('mapping.json', 'netlist-audit.json', 'netlist.json', 'netlist.v'):
        inputs[str((folder / name).relative_to(ROOT))] = sha(folder / name)
    log = BASE / (revision + '-' + activity_variant + '-activity-r1') / 'simulation.log'
    totals['wakes'] = read_activity(log)
    windows = [line.split(',') for line in log.read_text().splitlines() if line.startswith('WAKE,')]
    assert all(int(w[4]) == 43 for w in windows if int(w[4]) > 0), 'PER_WINDOW_RETIREMENT_MISMATCH'
    totals['wake_windows'] = windows
    inputs[str(log.relative_to(ROOT))] = sha(log)
    result['variants'][revision+'-'+variant] = dict(total=totals, categories=per_category,
        owners=dict(sorted(owners.items(),key=lambda kv:-kv[1]['area_um2'])))
validate_measurement_helpers(measurement_helpers)
if validate_independent_audit(audit_path,BASE)!=independent_audit:
    raise ValueError('INDEPENDENT_AUDIT_CHANGED_DURING_MEASUREMENT')
with args.output.open('x') as output:
    output.write(json.dumps(result, indent=2)+'\n')
print(json.dumps({k:v['total'] for k,v in result['variants'].items()}, indent=2))

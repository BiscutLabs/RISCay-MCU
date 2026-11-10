# SPDX-License-Identifier: Apache-2.0
"""One JSON record per matched comparison; SRAM excluded from logic/storage.

Read ordinary storage from Liberty, special keeper state from the one registry.
Never substitute estimated area for an unavailable physical primitive.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import subprocess
from gf180_estimate import groups, direct_groups, scalar, sha
from gf180_netgraph import graph
from gf180_physical import ROOT, SRAM
from report_clock_owners import inventory
from primitives import classified_cells, primitive
from audit_desync_protection import audit


def context(netlist, physical=False):
    """Bind CLI comparisons to successful runs and their actual mapped inputs."""
    folder=netlist.parent
    receipt=json.loads((folder/'receipt.json').read_text())
    key=str(netlist.resolve())
    if receipt['status']!='pass' or receipt['sha256'].get(key)!=sha(netlist):
        raise ValueError('DESYNC_UNACCEPTED_NETLIST')
    if physical:
        if netlist.name!='cts.json' or not (folder/'cts-proof.json').is_file():
            raise ValueError('DESYNC_CTS_REQUIRED')
        summary=json.loads((folder/'summary.json').read_text())
        if (not summary.get('clock_coverage',{}).get('all_sinks_reached') or
                not summary.get('electrical_violations') or any(summary['electrical_violations'].values())):
            raise ValueError('DESYNC_PHYSICAL_ACCEPTANCE_REQUIRED')
        mapped=[Path(p) for p in receipt['inputs'] if Path(p).name=='netlist.json']
        if len(mapped)!=1:raise ValueError('DESYNC_PHYSICAL_REFERENCE')
        result=context(mapped[0])
        result['physical_flow']=dict(die_um=summary['die_um'],density=summary['density'],
            tools={Path(p).name:receipt['sha256'][p] for p in receipt['tools']})
        return result
    descriptors=[Path(p) for p in receipt['inputs'] if Path(p).name in ('clocked.json','desync.json')]
    if len(descriptors)!=1:raise ValueError('DESYNC_CONFIGURATION_MISSING')
    metadata=json.loads(descriptors[0].read_text())
    if sha(descriptors[0])!=receipt['sha256'][str(descriptors[0])]:raise ValueError('DESYNC_CONFIGURATION_CHANGED')
    script=(folder/'synth.ys').read_text().replace(str(folder.resolve()).replace('\\','/'),'@mapping')
    from physical_tools import tool
    script=script.replace(tool('yosys').path(folder),'@mapping')
    return dict(configuration={k:metadata[k] for k in ('gpio_count','spi_boot','rom_bytes','program_bytes','ram_bytes')},
        synthesis=script, tools={Path(p).name:receipt['sha256'][p] for p in receipt['tools']
            if Path(p).name in ('yosys','yosys-abc','sv2v')})


def storage_width(body):
    total = 0
    for kind in ('ff', 'latch', 'ff_bank', 'latch_bank'):
        for args, _ in direct_groups(body, kind):
            total += int(args.split(',')[-1]) if kind.endswith('_bank') else 1
    return total


def measure(netlist, liberties, bindings=(), *, self_timed=False):
    modules = json.loads(netlist.read_text())['modules']
    cells, aliases = graph(modules)
    library = {name: body for path in liberties for name, body in groups(path.read_text(), 'cell')}
    missing = {c['type'] for c in cells.values()} - library.keys()
    if missing:
        raise ValueError('DESYNC_UNPRICED_CELL:' + ','.join(sorted(missing)))
    native = classified_cells(bindings)
    if not native.keys() <= cells.keys():
        raise ValueError('DESYNC_MISSING_PRIMITIVE')
    counts = Counter(c['type'] for c in cells.values() if c['type'] != SRAM)
    storage = {k: n * storage_width(library[k]) for k, n in counts.items() if storage_width(library[k])}
    roles = Counter()
    for path, (role, _) in native.items():
        roles[role] += scalar(library[cells[path]['type']], 'area') / 1e6
    keeper_bits = sum(primitive(b['primitive']).keeper_bits for b in bindings)
    pins = {k: {pin: scalar(body, 'capacitance') for pin, body in groups(library[k], 'pin')
                if re.search(r'\bclock\s*:\s*true\s*;', body)} for k in {c['type'] for c in cells.values()}}
    roots = {'serviceClock': 'service', 'soc.workClock': 'work', 'watchdogClock': 'lf', 'sda': 'host_event'}
    if 'soc.workClock' not in aliases and (netlist.parent/'summary.json').is_file():
        # OpenROAD retains the root leaf but may choose another wire alias.
        root=json.loads((netlist.parent/'summary.json').read_text())['work_root']
        path,pin=root.rsplit('/',1)
        matches=[name for name in (path,'\\'+path) if name in cells]
        if len(matches)!=1:raise ValueError('DESYNC_PHYSICAL_WORK_ROOT')
        aliases['soc.workClock']=cells[matches[0]]['connections'][pin]
    if self_timed:
        # The registry has no qualified generator/mutex yet. Do not let a flag
        # turn externally clocked flops into a claimed clockless result.
        from primitives import require_recipe
        require_recipe('RiscayDesyncController')
        require_recipe('RiscayDesyncMutex')
        if {b['primitive'] for b in bindings} != {'RiscayDesyncController','RiscayDesyncDelay','RiscayDesyncMutex'}:
            raise ValueError('DESYNC_GENERATOR_INVENTORY')
        roots['soc.generatedClock'] = roots.pop('serviceClock')
    clocks = inventory(cells, aliases, pins, roots=roots)
    if clocks['native_or_unclassified_clock_sinks']:
        raise ValueError('DESYNC_UNCLASSIFIED_CLOCK_SINK')
    protection = audit(dict(modules=modules), bindings, ['soc.workClock', 'soc.generatedClock'])
    logic = sum(n * scalar(library[k], 'area') for k, n in counts.items()) / 1e6
    return dict(logic_mm2=logic, storage_by_cell=storage,
        storage_bits=sum(storage.values()) + keeper_bits, keeper_bits=keeper_bits,
        special_area_mm2={k: roles[k] for k in ('delay_line', 'controller', 'mutex')},
        protected_cells=protection['protected_cells'], clock_sinks=clocks['clock_domains'],
        periodic_sinks=clocks['clock_domains']['lf'] if self_timed else clocks['periodic_sinks'],
        sram_macros=sum(c['type'] == SRAM for c in cells.values()), netlist_sha256=sha(netlist),
        liberty_sha256={str(p.resolve()): sha(p) for p in liberties})


def compare(candidate, reference, budget, *, physical=False):
    for record in (candidate, reference):
        if not math.isfinite(record['logic_mm2']) or record['logic_mm2'] <= 0 or record['storage_bits'] <= 0:
            raise ValueError('DESYNC_INVALID_AREA_OR_STORAGE')
    if candidate['liberty_sha256'] != reference['liberty_sha256'] or candidate['sram_macros'] != reference['sram_macros']:
        raise ValueError('DESYNC_UNMATCHED_REFERENCE')
    ratios = dict(area=candidate['logic_mm2'] / reference['logic_mm2'],
                  storage=candidate['storage_bits'] / reference['storage_bits'],
                  control=sum(candidate['special_area_mm2'].values()) / candidate['logic_mm2'])
    failures = [k for k, limit in (('area', budget['repaired_tree_ratio' if physical else 'mapped_ratio']),
                ('storage', budget['storage_ratio']), ('control', budget['control_area_fraction'])) if ratios[k] > limit]
    return dict(status='fail' if failures else 'pass', ratios=ratios, exceeded=failures,
                variant=candidate, reference=reference, scope='repaired+trees' if physical else 'flat-mapped')


def check_budget(current, previous):
    for key in ('mapped_ratio', 'repaired_tree_ratio', 'storage_ratio', 'control_area_fraction'):
        if not math.isfinite(current[key]) or not 0 < current[key] <= previous[key]:
            raise ValueError('DESYNC_BUDGET_LOOSENED:' + key)


def check_budget_history(path, root=ROOT):
    current=json.loads(path.read_text())
    ceiling=dict(mapped_ratio=1.15,repaired_tree_ratio=1.20,storage_ratio=1.05,control_area_fraction=.05)
    check_budget(current,ceiling)
    revisions=[]
    for ref in ('HEAD','HEAD^'):
        value=subprocess.run(['git','show',ref+':physical/gf180/desync-budget.json'],cwd=root,capture_output=True,text=True)
        revisions.append(json.loads(value.stdout) if value.returncode==0 else ceiling)
    check_budget(current,revisions[0])
    check_budget(revisions[0],revisions[1])
    return current


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('candidate', type=Path); p.add_argument('reference', type=Path)
    p.add_argument('--liberty', type=Path, action='append', required=True)
    p.add_argument('--bindings', type=Path); p.add_argument('--self-timed', action='store_true')
    p.add_argument('--physical', action='store_true'); p.add_argument('--output', type=Path)
    p.add_argument('--budget', type=Path, default=ROOT/'physical/gf180/desync-budget.json')
    a = p.parse_args()
    budget=check_budget_history(a.budget)
    if context(a.candidate,a.physical)!=context(a.reference,a.physical):
        raise ValueError('DESYNC_UNMATCHED_FLOW_OR_CONFIGURATION')
    result = compare(measure(a.candidate, a.liberty,
        json.loads(a.bindings.read_text()) if a.bindings else [], self_timed=a.self_timed),
        measure(a.reference, a.liberty), budget, physical=a.physical)
    line = json.dumps(result, separators=(',', ':'))
    if a.output:
        with a.output.open('a', encoding='utf-8') as stream: stream.write(line + '\n')
    print(line)
    raise SystemExit(result['status'] != 'pass')

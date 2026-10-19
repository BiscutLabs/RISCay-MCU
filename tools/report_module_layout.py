# SPDX-License-Identifier: Apache-2.0
"""Actual module geometry, soft-region spill and every C-element internal net."""
import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import re

from check_gf180_coupling import read_spef, unescape, rank
from check_gf180_keeper_coupling import connectivity, eligible_hotspots
from gf180_physical import write_json
from gf180_pnr import pnr_tool, validate_provenance, rc_inputs
from module_floorplan import LABELS
from report_routability import export_script, parse_export, overlap
from run_receipt import RunReceipt


def added_buffer_area(instances, proofs):
    """Use graph-proven additions, including delay buffers, not cell-name guesses."""
    actual={i.name:i for i in instances}
    names=[n for proof in proofs for n in proof['added_buffers']]
    if (len(names)!=len(set(names)) or any(n not in actual or actual[n].kind!='logic' for n in names)):
        raise ValueError('MODULE_BUFFER_INVENTORY')
    return sum(overlap(actual[n].box,actual[n].box) for n in names)


def internal_plan(mapping):
    record=json.loads((mapping/'mapping.json').read_text())
    audit=json.loads((mapping/'netlist-audit.json').read_text())
    plan=[]
    for b in record['bindings']:
        if b['model']=='ChiselAsyncCElement_v1': raise ValueError('CEL_UNCLASSIFIED_RECIPE')
        if b['model']!='ChiselAsyncAsymmetricC_v1': continue
        ports={p['name'] for p in b['ports']}
        internal=defaultdict(list)
        for c in b['cells']:
            for pin,net in c['pins'].items():
                if net.split('[')[0] not in ports and net not in ("1'b0","1'b1"):
                    internal[net].append([c['name'],pin])
        if not {'state','next_n'} <= internal.keys(): raise ValueError('CEL_INTERNAL_KEEPER_MISSING')
        for instance in b['instances']:
            root=audit['adapter_instances'][instance]
            plan.append(dict(instance=instance,root=root,nets={n:[[root+'/'+c,p] for c,p in pins] for n,pins in internal.items()}))
    if not plan: raise ValueError('CEL_EMPTY_INVENTORY')
    return plan


def spill(regions,assignments,instances,initial=None):
    actual={i.name:i for i in instances}; result={}
    boxes={r['id']:r['box_um'] for r in regions}
    for unit in assignments:
        key=unit['owner']; row=result.setdefault(key,dict(area_um2=0.,inside_um2=0.,cells=0,weighted_xy=[0.,0.],weighted_displacement=0.,max_displacement=0.))
        for name in unit['cells']:
            if name not in actual: raise ValueError('MODULE_LAYOUT_MISSING_'+name)
            b=actual[name].box
            area=overlap(b,b); xy=[(b[i]+b[i+2])/2 for i in (0,1)]
            row['area_um2']+=area;row['inside_um2']+=overlap(b,boxes[key]);row['cells']+=1
            for i in (0,1):row['weighted_xy'][i]+=area*xy[i]
            if initial is not None:
                old=initial[name];distance=math.dist(xy,[(old[i]+old[i+2])/2 for i in (0,1)])
                row['weighted_displacement']+=area*distance
                row['max_displacement']=max(row['max_displacement'],distance)
    for n,r in result.items():
        r['spill_fraction']=1-r['inside_um2']/r['area_um2']
        r['centroid_um']=[v/r['area_um2'] for v in r.pop('weighted_xy')]
        mean=r.pop('weighted_displacement')/r['area_um2'];maximum=r.pop('max_displacement')
        if initial is not None:r['from_initial_legal_um']=dict(area_weighted_mean=mean,maximum=maximum)
        region_area=overlap(boxes[n],boxes[n])
        r['owner_fill']=r['inside_um2']/region_area
        # Count every intersecting cell, including foreign owners, added repair /
        # CTS buffers and taps. Owner retention alone is not region congestion.
        r['occupancy_um2']={kind:sum(overlap(i.box,boxes[n]) for i in instances if i.kind==kind)
                            for kind in ('logic','macro','physical')}
        r['total_logic_fill']=r['occupancy_um2']['logic']/region_area
        r['total_physical_fill']=sum(r['occupancy_um2'].values())/region_area
    return result


def render(instances,meta,regions,owners,destination,title):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import PatchCollection
    from matplotlib.patches import Rectangle, Patch
    colors=dict(zip(LABELS,['#537dd2','#7172a8','#a48bd3','#dc9a43','#38a5a8','#d96975',
                           '#5ca46c','#b7a542','#a37761','#e5be6e','#8c9aa6']))
    colors.update(macro='#283548',physical='#e3e6ea',added='#aeb5bf')
    fig,ax=plt.subplots(figsize=(12,10),layout='constrained')
    boxes=defaultdict(list); centres=defaultdict(lambda:[0.,0.,0.])
    for i in instances:
        key=owners.get(i.name,'added') if i.kind=='logic' else i.kind
        x0,y0,x1,y1=i.box
        boxes[key].append(Rectangle((x0,y0),x1-x0,y1-y0))
        a=overlap(i.box,i.box)
        if key in LABELS:
            centres[key][0]+=a*(x0+x1)/2;centres[key][1]+=a*(y0+y1)/2;centres[key][2]+=a
        if i.kind=='macro':
            label=i.name.rsplit('/',1)[-1].replace('fabric_','').replace('_macros_',' SRAM ')
            ax.text((x0+x1)/2,(y0+y1)/2,label,ha='center',va='center',color='white',fontsize=8,zorder=5)
    for key,patches in boxes.items():
        ax.add_collection(PatchCollection(patches,facecolor=colors[key],edgecolor='none',rasterized=True,zorder=1))
    for r in regions:
        x0,y0,x1,y1=r['box_um']
        ax.add_patch(Rectangle((x0,y0),x1-x0,y1-y0,fill=False,linestyle='--',edgecolor=colors[r['id']],lw=1,zorder=3))
    for n,(x,y,a) in centres.items():
        ax.annotate(n.replace('_',' / '),(x/a,y/a),ha='center',fontsize=7,fontweight='bold',
                    bbox=dict(boxstyle='round,pad=.25',fc='white',alpha=.85,ec=colors[n]),zorder=4)
    d=meta['die']; ax.set(xlim=(d[0],d[2]),ylim=(d[1],d[3]),aspect='equal',xlabel='µm',ylabel='µm',title=title)
    legend=[Patch(facecolor=colors[n],label=label) for n,label in LABELS.items()]
    legend += [Patch(facecolor=colors['added'],label='Added repair / CTS'),Patch(facecolor=colors['macro'],label='Fixed SRAM')]
    ax.legend(handles=legend,loc='upper left',bbox_to_anchor=(1.01,1),frameon=False,fontsize=9)
    fig.savefig(destination,dpi=180);plt.close(fig)


def run(mapping,routed,out,stage='extract',png=False):
    meta=validate_provenance(mapping,routed,stage); t=pnr_tool(meta)
    out.mkdir(parents=True,exist_ok=False)
    database=routed/(stage+'.odb')
    region_file=routed/'module-regions.json'; regions=json.loads(region_file.read_text())
    inputs=[database,region_file,routed/'place.log',mapping/'mapping.json',mapping/'netlist-audit.json']
    stages=('place','clock','global','route','extract')
    proof_files=[routed/name for when,name in (
        ('place','place-repair-proof.json'),('clock','clock-coverage-proof.json'),
        ('global','global-repair-proof.json')) if stages.index(when)<=stages.index(stage)]
    inputs.extend(proof_files)
    initial=None
    if regions['mode']=='guided-regions':
        initial_file=routed/'guided-legal-module-geometry.tsv'; inputs.append(initial_file)
        lines=[line.split('\t') for line in initial_file.read_text().splitlines()]
        initial={r[1]:list(map(float,r[2:])) for r in lines}
        expected={n for u in regions['units'] for n in u['cells']}
        if len(initial)!=len(lines) or set(initial)!=expected or any(len(b)!=4 or not all(math.isfinite(v) for v in b) for b in initial.values()):
            raise ValueError('MODULE_INITIAL_GEOMETRY_COVERAGE')
    views={rc:rc_inputs(mapping,routed,rc)[1] for rc in ('min','max')} if stage=='extract' else {}
    if views:inputs.append(routed/'global-repair-after.tsv')
    helpers=[Path(__file__).with_name(n) for n in ('check_gf180_coupling.py','check_gf180_keeper_coupling.py',
        'check_gf180_cells.py','report_routability.py','module_floorplan.py')]
    receipt=RunReceipt(out/'receipt.json',inputs=[*inputs,*views.values()],tools=[Path(__file__),*helpers,*t.input_files()])
    script=out/'geometry.tcl'; raw=out/'geometry.tsv'
    script.write_text(export_script(t.path(database),t.path(raw),True,False))
    if receipt.command(t.command(['-exit',t.path(script)]),cwd=out,log=out/'geometry.log'):
        receipt.finish(outputs=[script,out/'geometry.log'],status='fail')
    geometry,instances,_=parse_export(raw)
    if regions['mode']=='bounded-regions' and not regions['regions']:raise ValueError('MODULE_MISSING_REGIONS')
    result=dict(stage=stage,mode=regions['mode'],regions=spill(regions['regions'],regions['units'],instances,initial) if regions['regions'] else {},
                reference_region_error=regions.get('reference_region_error'),
                area_um2=sum(overlap(i.box,i.box) for i in instances),
                limits=[('Persistent module bounds; not power islands' if regions['mode']=='bounded-regions' else 'Seed regions are not hard bounds'),
                        'Geometry is not timing, coupling immunity or IR qualification'])
    result['area_by_kind_um2']={k:sum(overlap(i.box,i.box) for i in instances if i.kind==k)
                                for k in ('logic','macro','physical')}
    result['added_buffer_area_um2']=added_buffer_area(instances,[json.loads(p.read_text()) for p in proof_files])
    placement_log=(routed/'place.log').read_text()
    densities=re.findall(r'Initialize Nesterov Region: ([^\n]+)\n(?:(?!Initialize Nesterov Region:).)*?Placement target density:\s+([\d.]+)',placement_log,re.S)
    expected_regions={'Top-level'}|({'riscay_'+r['id'] for r in regions['regions']} if regions['mode'] in ('bounded-regions','guided-regions') else set())
    if (len(densities)!=len(dict(densities)) or set(dict(densities))!=expected_regions or
        any(not 0<float(d)<=1 for _,d in densities)):raise ValueError('MODULE_PLACEMENT_DENSITY_COVERAGE')
    result['initial_effective_target_density']={n:float(d) for n,d in densities}
    result['subsequent_density_updates']=re.findall(r'New target density:\s+([^\n]+)',placement_log)
    result['density_scope']='Initial targets include feasibility adjustments; later tool updates have no region label. Final all-cell occupancy is reported separately.'
    if views:
        plan=internal_plan(mapping); write_json(out/'internal-plan.json',plan)
        # The extractor reads actual pin-connected nets, not a guessed net name.
        driver=out/'internals.py'
        driver.write_text('import json,odb\n'
            f'db=odb.dbDatabase.create();odb.read_db(db,{t.path(database)!r})\n'
            'b=db.getChip().getBlock();u=b.getDbUnitsPerMicron();rows=[]\n'
            f'plan=json.load(open({t.path(out/"internal-plan.json")!r}))\n'
            'for owner in plan:\n'
            ' for logical,pins in owner["nets"].items():\n'
            '  ns=[b.findInst(c).findITerm(p).getNet() for c,p in pins]\n'
            '  assert len({n.getName() for n in ns})==1,"CEL_SPLIT_NET"\n'
            '  n=ns[0];assert n.getITermCount()==len(pins) and n.getBTermCount()==0,"CEL_EXTERNAL_INTERNAL_NET"\n'
            '  box=n.getTermBBox();wire=n.getWire();assert wire is not None,"CEL_UNROUTED_INTERNAL_NET"\n'
            '  rows.append(dict(instance=owner["instance"],logical=logical,net=n.getName(),wire_um=wire.getLength()/u,hpwl_um=(box.dx()+box.dy())/u))\n'
            f'json.dump(rows,open({t.path(out/"internal-geometry.json")!r},"w"))\n')
        if receipt.command(t.command(['-exit','-python',t.path(driver)]),cwd=out,log=out/'internals.log'):
            receipt.finish(outputs=[driver,out/'internals.log'],status='fail')
        rows=json.loads((out/'internal-geometry.json').read_text()); selected={r['net'] for r in rows}
        expected={(p['instance'],n) for p in plan for n in p['nets']}
        actual=[(r['instance'],r['logical']) for r in rows]
        if len(actual)!=len(set(actual)) or set(actual)!=expected: raise ValueError('CEL_INTERNAL_NET_COVERAGE')
        networks={}
        expected_pins={(p['instance'],logical):{unescape(c+':'+pin) for c,pin in pins}
                       for p in plan for logical,pins in p['nets'].items()}
        for rc,spef in views.items():
            parsed=read_spef(spef,selected)
            if parsed['missing']: raise ValueError('CEL_MISSING_EXTRACTED_NET_'+str(parsed['missing'][:5]))
            networks[rc]=parsed['networks']
        byowner=defaultdict(list)
        for r in rows:
            r['rc']={}
            for rc,nets in networks.items():
                n=nets[r['net']]
                pins=[c['pin'] for c in n['connections'] if c['kind']=='*I']
                if (len(pins)!=len(n['connections']) or len(pins)!=len(set(pins)) or
                    set(pins)!=expected_pins[(r['instance'],r['logical'])]):
                    raise ValueError('CEL_EXTRACTED_TERMINAL_COVERAGE_'+r['net'])
                r['rc'][rc]=dict(ground_pf=sum(n['ground'].values()),coupling_pf=sum(c[2] for c in n['coupling']),
                                 sum_segment_resistance_ohm=sum(v[2] for v in n['resistors']))
            byowner[r['instance']].append(r)
        if set(byowner)!={p['instance'] for p in plan}: raise ValueError('CEL_OWNER_COVERAGE')
        result['celements']=[dict(instance=n,longest=max(rs,key=lambda r:r['wire_um']),nets=rs) for n,rs in sorted(byowner.items())]
        with (out/'celement-longest-nets.csv').open('w',newline='') as f:
            table=csv.writer(f)
            table.writerow(['instance','internal_net','routed_net','wire_um','pin_hpwl_um',
                            'min_ground_pf','min_coupling_pf','max_ground_pf','max_coupling_pf'])
            for item in result['celements']:
                r=item['longest']
                table.writerow([item['instance'],r['logical'],r['net'],r['wire_um'],r['hpwl_um'],
                                *[r['rc'][rc][k] for rc in ('min','max') for k in ('ground_pf','coupling_pf')]])
        result['worst_internal_wire']=max(rows,key=lambda r:r['wire_um'])
        result['worst_keeper_total_coupling']=max((r for r in rows if r['logical'] in ('state','next_n')),key=lambda r:r['rc']['max']['coupling_pf'])
        cells,nets=connectivity(routed/'global-repair-after.tsv')
        record=json.loads((mapping/'mapping.json').read_text()); audit=json.loads((mapping/'netlist-audit.json').read_text())
        result['keeper_external_coupling']={rc:eligible_hotspots(record,audit,cells,nets,[rank(n,3.3) for n in networks[rc].values()]) for rc in networks}
        result['coupling_scope']='Every internal net is measured. External-aggressor ranking excludes same-owner nets and lists ineligible owners; transient immunity requires the representative keeper campaign.'
    write_json(out/'report.json',result)
    if png: render(instances,geometry,regions['regions'],regions['logical_owners'],out/'modules.png',
                   f'BD {geometry["die"][2]/1000:.2f} × {geometry["die"][3]/1000:.2f} mm · {regions["mode"]} · {stage}')
    receipt.finish(outputs=[p for p in out.iterdir() if p.is_file()])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('mapping','routed','output'):p.add_argument(n,type=Path)
    p.add_argument('--stage',choices=('place','clock','global','route','extract'),default='extract');p.add_argument('--png',action='store_true')
    a=p.parse_args();run(a.mapping.resolve(),a.routed.resolve(),a.output.resolve(),a.stage,a.png)

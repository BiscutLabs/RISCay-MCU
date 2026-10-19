# SPDX-License-Identifier: Apache-2.0
"""Compact native keeper/output groups; geometry is not noise qualification."""
import json
from gf180_physical import SC, write_json
from gf180_constraints import brace
from repair_gf180_control import require


def groups(mapping,audit,drivers):
    raw=[]
    for binding in mapping['bindings']:
        if binding['model']!='ChiselAsyncAsymmetricC_v1':continue
        cells=binding['cells']
        keeper=[c for c in cells if c['cell']==SC+'aoi21_1' and c['pins'].get('A1')=='state']
        hold=[c for c in cells if c['cell']==SC+'nor2_1' and c['pins'].get('ZN')=='state']
        first=[c for c in cells if c['cell'].startswith(SC+'buf_') and c['pins'].get('I')=='state']
        require(len(keeper)==len(hold)==len(first)==1,'PLACEMENT_KEEPER_RECIPE')
        require(keeper[0]['pins']['ZN']==hold[0]['pins']['A1'],'PLACEMENT_KEEPER_LOOP')
        for instance in binding['instances']:
            owner=audit['adapter_instances'][instance]
            raw.append(dict(kinds=['keeper'],cells=[owner+'/'+c['name'] for c in [*keeper,*hold,*first]]))
    for r in drivers:
        require(not r['buffer'].startswith(r['owner']+'/'),'PLACEMENT_PARENT_INSIDE_NATIVE')
        raw.append(dict(kinds=['output'],cells=[r['driver'],r['buffer']]))
    # A physical cell can belong to only one placement cluster.
    parent={}
    def root(n):
        parent.setdefault(n,n)
        if parent[n]!=n:parent[n]=root(parent[n])
        return parent[n]
    for row in raw:
        for c in row['cells']:parent[root(c)]=root(row['cells'][0])
    merged={}
    for row in raw:
        record=merged.setdefault(root(row['cells'][0]),dict(cells=set(),kinds=set()))
        record['cells'].update(row['cells']);record['kinds'].update(row['kinds'])
    require(raw,'PLACEMENT_EMPTY_NATIVE_GROUPS')
    return [dict(id=i,cells=sorted(r['cells']),kinds=sorted(r['kinds']),maximum_span_um=64)
            for i,(_,r) in enumerate(sorted(merged.items()))]


def generate(mapping,out):
    m=json.loads((mapping/'mapping.json').read_text());a=json.loads((mapping/'netlist-audit.json').read_text())
    proof=json.loads((mapping/'electrical-repair/proof.json').read_text())
    require('native_output_drivers' in proof,'PLACEMENT_PARENT_DRIVERS_REQUIRED')
    rows=groups(m,a,proof['native_output_drivers'])
    text='set native_placement_groups {\n'
    for r in rows:
        text+='  {'+str(r['id'])+' '+str(r['maximum_span_um'])+' {'+' '.join(brace(c) for c in r['cells'])+'}}\n'
    text+='}\nset native_output_feeders {\n'
    for r in proof['native_output_drivers']:
        text+='  {'+brace(r['driver'])+' '+brace(r['pin'])+' '+brace(r['buffer'])+'}\n'
    (out/'native-placement.tcl').write_text(text+'}\n')
    write_json(out/'native-placement.json',dict(groups=rows,drivers=proof['native_output_drivers'],
        scope='GPL clusters, 100/500um ordinary DPL search, bounded 48um local repack, 64um final native XY-span acceptance; not a coupling/capacitance bound'))

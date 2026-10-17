# SPDX-License-Identifier: Apache-2.0
"""Loaded native capture-tree envelope on the complete repaired netlist (no RC)."""
import argparse
import json
import math
from pathlib import Path
import subprocess

from characterize_gf180_liberty import CORNERS
from control_relative_timing import PROBE, brace
from gf180_physical import ROOT, SC, SRAM, sha, write_json
from native_leaf_timing import LeafIndex, keeper_cuts, SLEW_TCL
from native_stage_timing import receipt_original, receipt_proof
from physical_tools import tool
from repair_gf180_control import require
from repair_gf180_design import validate_receipt


def plans(mapping,record,audit):
    result=[]
    for b in record['bindings']:
        width=b['requirements'].get('storage_bits',0)
        for instance in b['instances']:
            if width<256 and '.ca_child_register_file.' not in instance:continue
            if not width:continue
            latch='ClosingLatch' in b['model'];root_port='closed' if latch else 'trigger'
            roots=[c['name']+'/I' for c in b['cells'] if c['pins'].get('I')==root_port]
            require(len(roots)==1,'DISTRIBUTION_ROOT_PIN')
            prefix=audit['adapter_instances'][instance]+'/'
            targets=[prefix+c['name']+'/'+p for c in b['cells'] for p in ('E','CLK') if p in c['pins']]
            require(len(targets)==width,'DISTRIBUTION_STORAGE_COUNT')
            result.append(dict(instance=instance,root=prefix+roots[0],targets=targets,latch=latch,
                tree_cells=[prefix+c['name'] for c in b['cells'] if c['cell'].startswith((SC+'buf_',SC+'inv_'))],
                propagation_and_spread_budget_ns=b['requirements']['clock_distribution_max_ns']))
    require(result,'DISTRIBUTION_EMPTY_PLAN');return result


def script(mapping,plan,cuts,corner,slew,sta,*,period=1000,sdf=None):
    text='read_liberty '+brace(sta.path(ROOT/'.tools/physical/pdk'/(SC+corner+'.lib')))+'\n'
    text+='read_liberty '+brace(sta.path(ROOT/'.tools/gf180-sram'/(SRAM+'__'+corner+'.lib')))+'\n'
    text+=PROBE.read_text()+'\n'+SLEW_TCL+'\nread_verilog '+brace(sta.path(mapping/'netlist.v'))+'\nlink_design RiscayMcuDigital\n'
    text+=f'set_input_transition {slew} [all_inputs]\nset_load 0.05 [all_outputs]\nset_case_analysis 0 [get_ports reset]\n'
    for cell in cuts:text+='set_disable_timing -from A1 -to ZN [get_cells '+brace(cell)+']\n'
    for i,p in enumerate(plan):
        text+='create_clock -name tree'+str(i)+f' -period {period} -waveform {{0 1}} [exact_object pin '+brace(p['root'])+']\n'
    if sdf is not None:text+='read_sdf '+brace(sta.path(sdf))+'\n'
    text+='set_propagated_clock [all_clocks]\nsta::find_delays\n'
    for i,p in enumerate(plan):
        text+='set root [exact_object pin '+brace(p['root'])+']\n'
        text+='foreach v [$root vertices] {foreach mode {min max} {foreach edge {rise fall} {sta::set_annotated_slew $v [sta::cmd_corner] $mode $edge [sta::time_ui_sta '+str(slew)+']}}}\n'
    text+='set sources [all_clocks]; set targets [list '+' '.join('[exact_object pin '+brace(t)+']' for p in plan for t in p['targets'])+']\n'
    text+='set_max_delay 100000 -from $sources -to $targets\nset_min_delay 0 -from $sources -to $targets\n'
    # Batch all leaves of a polarity in one search. Replacing constraints per
    # primitive repeatedly invalidated the full-chip timing graph.
    for latch in (False,True):
        group=[(i,p) for i,p in enumerate(plan) if p['latch']==latch]
        if not group:continue
        for source in ('rise','fall'):
            sink=('fall' if source=='rise' else 'rise') if latch else source
            for mode in ('min','max'):
                text+='control_batch '+mode+' '+source+' '+sink+' $sources pin [list '
                text+=' '.join(brace(f'{i}:{source}:{mode}:{j}')+' '+brace(t) for i,p in group for j,t in enumerate(p['targets']))+']\n'
    for i,p in enumerate(plan):
        text+='foreach mode {min max} {foreach edge {rise fall} {row TREE_SLEW '+str(i)+' $mode $edge [leaf_slew [exact_object pin '+brace(p['root'])+'] $edge $mode]}}\n'
    text+='puts TREE_COMPLETE\nexit\n';return text


def parse(log,plan,slew):
    require('TREE_COMPLETE' in log and not any(x in log for x in ('Error:','Warning:','ERROR','WARNING','CONTROL_MISSING')),'DISTRIBUTION_TIMING_INCOMPLETE')
    rows={};points={};slews={}
    for line in log.splitlines():
        x=line.split('\t')
        if x[0]=='CONTROL_PATH':
            require(len(x)==11,'DISTRIBUTION_ROW')
            i,edge,mode,j=x[1].split(':');i=int(i);j=int(j);p=plan[i]
            require(x[1] not in rows and mode in ('min','max') and edge in ('rise','fall'),'DISTRIBUTION_DUPLICATE')
            nums=list(map(float,x[2:7]));origin,arrival,data,delay,worst=nums
            require(all(math.isfinite(v) for v in nums) and delay>=0 and worst>=0 and
                abs(origin-(0 if edge=='rise' else 1))<1e-5 and abs(delay-data)<1e-5 and abs(arrival-origin-delay)<1e-5,
                'DISTRIBUTION_NUMERIC')
            require(x[7]==p['root'] and x[8]==p['targets'][j] and x[9]==edge and
                x[10]==(('fall' if edge=='rise' else 'rise') if p['latch'] else edge),'DISTRIBUTION_PATH_BINDING')
            rows[x[1]]=(delay,worst)
        elif x[0]=='CONTROL_POINTS':
            require(x[1] in rows and x[1] not in points,'DISTRIBUTION_PATH_POINTS');points[x[1]]=x[2:]
        elif x[0]=='TREE_SLEW':
            key=tuple(x[1:4]);require(key not in slews and abs(float(x[4])-slew)<1e-5,'DISTRIBUTION_SOURCE_SLEW');slews[key]=float(x[4])
    expected={f'{i}:{edge}:{mode}:{j}' for i,p in enumerate(plan) for edge in ('rise','fall') for mode in ('min','max') for j in range(len(p['targets']))}
    require(rows.keys()==points.keys()==expected and set(slews)=={(str(i),m,e) for i in range(len(plan)) for m in ('min','max') for e in ('rise','fall')},'DISTRIBUTION_COVERAGE')
    result=[]
    for i,p in enumerate(plan):
        for edge in ('rise','fall'):
            low=[rows[f'{i}:{edge}:min:{j}'][0] for j in range(len(p['targets']))]
            high=[rows[f'{i}:{edge}:max:{j}'][0] for j in range(len(p['targets']))]
            require(all(lo<=hi+1e-6 for lo,hi in zip(low,high)),'DISTRIBUTION_REVERSED_BOUND')
            for mode in ('min','max'):
                for j,target in enumerate(p['targets']):
                    path=points[f'{i}:{edge}:{mode}:{j}'];require(path[0]==p['root'] and path[-1]==target and
                        all(pin.rsplit('/',1)[0] in p['tree_cells'] for pin in path[:-1]),'DISTRIBUTION_POINT_BINDING')
            latest=max(high);spread=latest-min(low);budget=p['propagation_and_spread_budget_ns']
            result.append(dict(instance=p['instance'],edge=edge,leaves=len(low),earliest_ns=min(low),latest_ns=latest,
                spread_bound_ns=spread,budget_ns=budget,within_budget=latest<=budget and spread<=budget,
                maximum_path_slew_ns=max(rows[f'{i}:{edge}:{m}:{j}'][1] for m in ('min','max') for j in range(len(low)))))
    return result


def run(mapping,out):
    require(not out.exists(),'DISTRIBUTION_OUTPUT_EXISTS');receipt=validate_receipt(mapping)
    record=json.loads((mapping/'mapping.json').read_text());audit=json.loads((mapping/'netlist-audit.json').read_text())
    proof=receipt_proof(mapping,receipt);live=json.loads((mapping/'netlist.json').read_text())
    index=LeafIndex(receipt_original(mapping,receipt),live,proof['added_buffers'],proof['added_ties'])
    plan=plans(mapping,record,audit);cuts=keeper_cuts(index,audit);sta=tool('sta')
    files=[Path(__file__),PROBE,*sta.input_files(),*[mapping/n for n in ('netlist.v','mapping.json','netlist-audit.json','electrical-repair/receipt.json')],
        *[ROOT/'tools'/n for n in ('native_leaf_timing.py','native_stage_timing.py','control_relative_timing.py','gf180_physical.py','repair_gf180_design.py','physical_tools.py')],
        *[ROOT/'.tools/physical/pdk'/(SC+c+'.lib') for c in CORNERS],*[ROOT/'.tools/gf180-sram'/(SRAM+'__'+c+'.lib') for c in CORNERS]]
    frozen={str(p.resolve()):sha(p) for p in files};out.mkdir(parents=True);write_json(out/'plan.json',plan);results=[]
    for corner in CORNERS:
        for slew in (.02,2.0):
            key=corner+'-s'+str(slew);tcl=out/(key+'.tcl');log=out/(key+'.log')
            tcl.write_text(script(mapping,plan,cuts,corner,slew,sta),newline='\n')
            with log.open('w') as stream:subprocess.run(sta.command(['-no_init','-exit',sta.path(tcl)],timeout=180),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=190)
            rows=parse(log.read_text(),plan,slew);results.extend(dict(corner=corner,slew=slew,**r) for r in rows)
            print(key,len(rows),'rows',flush=True)
    validate_receipt(mapping);require(all(sha(Path(p))==h for p,h in frozen.items()),'DISTRIBUTION_INPUT_CHANGED')
    write_json(out/'results.json',dict(physical_qualification=False,scope='loaded primitive-local trees, zero wire RC; no upstream driver or capture/ACK composition',
        rows=results,inputs_sha256=frozen,evidence_sha256={p.name:sha(p) for p in out.iterdir() if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mapping',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();run(a.mapping,a.output)

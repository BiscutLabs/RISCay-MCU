# SPDX-License-Identifier: Apache-2.0
"""Conditional Control capture-to-ACK permission and BD hold-fork measurements.

Uses the sealed loaded Join slice; not an earliest-reuse or full-cycle proof.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import subprocess

import control_join_timing as j

FORK_ARCS=Path(__file__).with_name('control_fork_arc.tcl')


def fork_chain(stage):
    """Prove A = !ACK for B=1, keeper=1, reset=0, either request level.

    Enumerate the exact mapped Boolean graph, then extract every changing arc.
    The request minterm must be inactive; no guessed cell-name path is accepted.
    """
    n=stage['native'];cells=[c for c in n['cells'] if c['path'].startswith('ca_primitive_a/')]
    functions={'inv_1':lambda p:1-p['I'],'buf_1':lambda p:p['I'],
               'and2_1':lambda p:p['A1'] & p['A2'],'or2_1':lambda p:p['A1'] | p['A2'],
               'nor2_1':lambda p:1-(p['A1'] | p['A2']),
               'aoi21_1':lambda p:1-((p['A1'] & p['A2']) | p['B'])}
    keeper=[c for c in cells if c['cell']==j.SC+'aoi21_1'];j.require(len(keeper)==1,'RETENTION_COFACTOR_KEEPER')
    def evaluate(req,ack):
        values={n['signals']['b']:1,n['ports']['reset']:0,n['signals']['request_delay']:req,n['ports']['out_ack']:ack}
        remaining=list(cells);pins={}
        while remaining:
            done=[]
            for c in remaining:
                inputs={p:(1 if c==keeper[0] and p=='A1' else values.get(v)) for p,v in c['pins'].items() if p not in ('Z','ZN')}
                if any(v is None for v in inputs.values()):continue
                kind=c['cell'].removeprefix(j.SC);j.require(kind in functions,'RETENTION_COFACTOR_CELL')
                output=[p for p in c['pins'] if p in ('Z','ZN')];j.require(len(output)==1,'RETENTION_COFACTOR_OUTPUT')
                value=functions[kind](inputs);values[c['pins'][output[0]]]=value
                pins[c['path']]={**inputs,output[0]:value};done.append(c)
            j.require(done,'RETENTION_COFACTOR_CYCLE')
            remaining=[c for c in remaining if c not in done]
        j.require(values[n['signals']['a']]==1-ack,'RETENTION_COFACTOR_FUNCTION')
        return pins
    cases={(req,ack):evaluate(req,ack) for req in (0,1) for ack in (0,1)}
    active={}
    for c in cells:
        changes=[]
        for req in (0,1):
            before,after=cases[req,0][c['path']],cases[req,1][c['path']]
            changed=[p for p in before if before[p]!=after[p]]
            if changed:
                ins=[p for p in changed if p not in ('Z','ZN')];outs=[p for p in changed if p in ('Z','ZN')]
                j.require(len(ins)==len(outs)==1,'RETENTION_COFACTOR_RECONVERGENCE')
                a,b=ins[0],outs[0];changes.append((a,b,'^' if before[a]==0 else 'v','^' if before[b]==0 else 'v'))
        if changes:
            j.require(len(changes)==2 and changes[0]==changes[1],'RETENTION_COFACTOR_REQUEST_DEPENDENCE')
            active[c['path']]=(c,changes[0])
    node=n['ports']['out_ack'];chain=[];used=set();edge='^'
    while node!=n['signals']['a']:
        matches=[(c,v) for c,v in active.values() if c['pins'][v[0]]==node]
        j.require(len(matches)==1,'RETENTION_COFACTOR_CHAIN');c,v=matches[0]
        j.require(c['path'] not in used and v[2]==edge,'RETENTION_COFACTOR_POLARITY');used.add(c['path'])
        chain.append([stage['prefix']+c['path']+'/'+v[0],stage['prefix']+c['path']+'/'+v[1],v[2],v[3]])
        node=c['pins'][v[1]];edge=v[3]
    j.require(used==set(active) and edge=='v','RETENTION_COFACTOR_COVERAGE')
    return chain

def ack_pin(plan):
    p=plan['stages']['update']
    return p['prefix']+j.relative.driver(p['native'],'acknowledge' if plan['variant']=='bd' else 'acknowledge_guard')


def fork_pins(stage):
    n=stage['native']
    cells=[c for c in n['cells'] if c['path'].startswith('ca_primitive_long_hold/') and c['cell']==j.SC+'or2_1']
    j.require(len(cells)==1,'RETENTION_FORK_CELL')
    c=cells[0];result={}
    for key,node in [('a',n['signals']['a']),('ack',n['ports']['out_ack'])]:
        pins=[p for p,v in c['pins'].items() if v==node and p in ('A1','A2')]
        j.require(len(pins)==1,'RETENTION_FORK_WIRING')
        result[key]=stage['prefix']+c['path']+'/'+pins[0]
    j.require(result['a']!=result['ack'],'RETENTION_FORK_ALIAS')
    return result


def contexts(plan,cells):
    result=[];u=plan['stages']['update'];bd=plan['variant']=='bd'
    for request in [c for c in plan['contexts'] if c['kind']=='request']:
        side,phase=request['side'],request['phase'];state=deepcopy(request['state'])
        # Recompute the upstream event slew and compare every retained request row.
        result.append(dict(id=side+'-arrival-'+str(phase),kind='arrival',side=side,phase=phase,request=request))
        qs=[dict(id=f'capture:{l["lane"]}:{m}',role='capture',lane=l['lane'],mode=m,
                 source_edge='rise',sink_edge='fall' if bd else 'rise',sink_kind='pin',sink=u['prefix']+l['capture'])
            for l in u['lane_map'] for m in ('min','max')]
        qs += [dict(id='ack:'+m,role='ack',mode=m,source_edge='rise' if bd else 'any',
                    sink_edge='rise' if phase==0 else 'fall',sink_kind='port',sink='probe_update_ack') for m in ('min','max')]
        result.append(dict(id=side+'-permission-'+str(phase),kind='permission',side=side,phase=phase,
            state=state,sources=[u['prefix']+u['event']],queries=qs))
    if bd:
        for side in ('left','right'):
            src=plan['stages'][side];state=deepcopy(j.state(plan,cells,side,0))
            receivers={src['prefix']+c['path']+'/'+pin for c in src['native']['cells'] for pin,node in c['pins'].items()
                       if node==src['native']['ports']['out_ack'] and pin not in ('Q','Z','ZN')}
            b=src['prefix']+j.relative.driver(src['native'],'b')
            keeper=[src['prefix']+c['path']+'/A1' for c in src['native']['cells']
                    if c['cell']==j.SC+'aoi21_1' and c['path'].startswith('ca_primitive_a/')]
            j.require(len(keeper)==1,'RETENTION_A_KEEPER')
            state['cases']=[(kind,pin,1 if pin in {b,keeper[0]} else value)
                            for kind,pin,value in state['cases'] if pin not in receivers]
            pins=fork_pins(src)
            qs=[dict(id=key+':'+m,role=key,mode=m,source_edge='rise',sink_edge='fall' if key=='a' else 'rise',
                     sink_kind='pin',sink=pin) for key,pin in pins.items() for m in ('min','max')]
            result.append(dict(id=side+'-fork',kind='fork',side=side,phase=0,state=state,sources=[ack_pin(plan)],queries=qs,
                               chain=fork_chain(src),fork_pins=pins))
    return result


def script(netlist,corner,slew,plan,ctx,sta,*,period=1000,sdf=None,ack_slews=None):
    b=j.relative.brace;u=plan['stages']['update'];event=u['prefix']+u['event']
    measure='set p [exact_object pin '+b(event)+']\nrow RETENTION_EVENT_SLEW [join_slew $p rise min] [join_slew $p rise max]\n'
    edge='rise' if ctx['phase']==0 else 'fall'
    measure+='set p [exact_object pin '+b(ack_pin(plan))+f']\nrow RETENTION_ACK_SLEW [join_slew $p {edge} min] [join_slew $p {edge} max]\n'
    if ctx['kind']=='arrival':
        return j.script(netlist,corner,slew,plan,ctx['request'],sta=sta,period=period,sdf=sdf).replace('row JOIN_COMPLETE\n',measure+'row JOIN_COMPLETE\n')
    text='read_liberty '+b(sta.path(j.ROOT/'.tools/physical/pdk'/(j.SC+corner+'.lib')))+'\n'
    text+=j.relative.PROBE.read_text()+'\n'+j.JOIN_PROBE+'\n'
    text+='read_verilog '+b(sta.path(netlist))+'\nlink_design '+j.TOP+'\n'
    text+=f'set_input_transition {slew} [all_inputs]\nset_load 0.05 [all_outputs]\nset_load 0 [exact_object port probe_update_ack]\nset_max_transition 2 [current_design]\n'
    for kind,pin,value in ctx['state']['cases']:text+=f'set_case_analysis {value} [exact_object {kind} {b(pin)}]\n'
    for cell in ctx['state']['keeper_cuts']:text+='set_disable_timing -from A1 -to ZN [get_cells '+b(cell)+']\n'
    if sdf:text+='read_sdf '+b(sta.path(sdf))+'\n'
    root=ctx['sources'][0]
    text+=f'create_clock -name event -period {period} -waveform {{0 1}} [exact_object pin {b(root)}]\nset_propagated_clock [all_clocks]\n'
    if ctx['kind']=='fork':
        j.require(ack_slews is not None,'RETENTION_ACK_SLEW_REQUIRED')
        text+='sta::find_delays\nset p [exact_object pin '+b(root)+']\n'
        for m,v in zip(('min','max'),ack_slews):
            text+=f'foreach vertex [$p vertices] {{sta::set_annotated_slew $vertex [sta::cmd_corner] {m} rise [sta::time_ui_sta {v}]}}\n'
    text+='set sources [get_clocks event]\nset targets {}\nrow RETENTION_BEGIN\n'
    if ctx['kind']=='fork':
        # Whole-path STA automatically cuts the return loop. Evaluate the exact
        # cofactored first-event chain's loaded arcs directly instead; no graph
        # cell delay of a loop-disabled edge is accepted as a measurement.
        text+=FORK_ARCS.read_text()+'\nset path [list '+ ' '.join('[list '+ ' '.join(map(b,step))+']' for step in ctx['chain'])+']\n'
        for mode,v in zip(('min','max'),ack_slews):
            text+=f'reviewed_path {b(root)} {b(ctx["fork_pins"]["a"])} {mode} {v} $path\n'
            text+=f'reviewed_wire {b(root)} {b(ctx["fork_pins"]["ack"])} ^ {mode}\n'
        return text+measure+'row RETENTION_COMPLETE\nexit\n'
    for kind,pin in sorted({(q['sink_kind'],q['sink']) for q in ctx['queries']}):text+='lappend targets [exact_object '+kind+' '+b(pin)+']\n'
    text+='set_max_delay 100000 -from $sources -to $targets\nset_min_delay 0 -from $sources -to $targets\n'
    batches=defaultdict(list)
    for q in ctx['queries']:batches[(q['mode'],q['source_edge'],q['sink_edge'],q['sink_kind'])].append(q)
    for (mode,se,te,kind),qs in batches.items():
        text+='join_batch '+mode+' '+se+' '+te+' $sources '+kind+' [list '+" ".join(b(q[k]) for q in qs for k in ('id','sink'))+']\n'
    text+=measure+'row RETENTION_ELECTRICAL_BEGIN\nreport_check_types -max_slew -max_capacitance -violators -digits 6\nrow RETENTION_ELECTRICAL_END\nrow RETENTION_COMPLETE\nexit\n'
    return text


def slews(log):
    result={}
    for key in ('EVENT','ACK'):
        lines=re.findall('^RETENTION_'+key+'_SLEW\t([^\n]+)$',log,re.M)
        j.require(len(lines)==1,'RETENTION_SLEW_COVERAGE');v=list(map(float,lines[0].split('\t')))
        j.require(len(v)==2 and all(math.isfinite(x) and x>=0 for x in v) and v[0]<=v[1],'RETENTION_SLEW_NUMERIC')
        result[key.lower()]=v
    return result


def parse_fork(log,ctx,allow_annotations=False):
    reports=re.findall(r'FORK_DCALC_BEGIN\t([^\n]+)\n(.*?)FORK_DCALC_END\n',log,re.S)
    records={};wire_records={};totals={};source=slews(log)['ack']
    raw={}
    for header,body in reports:
        key=tuple(header.split('\t'));j.require(len(key)==3 and key not in raw,'RETENTION_ARC_REPORT_ID');raw[key]=body
    for line in log.splitlines():
        f=line.split('\t')
        if f[0]=='FORK_CELL':
            j.require(len(f)==12,'RETENTION_ARC_ROW');key=tuple(f[1:4])
            j.require(key not in records and key in raw and f[11] in ('0','1'),'RETENTION_ARC_ID')
            values=list(map(float,f[6:11]));j.require(all(math.isfinite(v) and 0<=v<1e6 for v in values),'RETENTION_ARC_NUMERIC')
            ins,load,delay,outs,effective=values
            # f[11] is the annotation flag (kept separate from numerical evidence).
            records[key]=dict(edges=f[4:6],input_slew_ns=ins,load_pf=load,delay_ns=delay,output_slew_ns=outs,effective_ns=effective,annotated=bool(int(f[11])))
        elif f[0]=='FORK_WIRE':
            j.require(len(f)==7,'RETENTION_WIRE_ROW');key=tuple(f[1:4]);v=float(f[5])
            j.require(key not in wire_records and f[6] in ('0','1') and math.isfinite(v) and 0<=v<1e6,'RETENTION_WIRE_NUMERIC')
            wire_records[key]=dict(edge=f[4],delay_ns=v,annotated=bool(int(f[6])))
        elif f[0]=='FORK_PATH':
            j.require(len(f)==5 and f[1] not in totals,'RETENTION_ARC_TOTAL_ID');totals[f[1]]=[float(f[2]),float(f[3]),f[4]]
    expected_cells={(m,a,b) for m in ('min','max') for a,b,_,_ in ctx['chain']};expected_wires=set();rows={}
    j.require(set(raw)==set(records)==expected_cells and set(totals)=={'min','max'},'RETENTION_ARC_COVERAGE')
    for m,initial_slew in zip(('min','max'),source):
        value=0.;slew=initial_slew;previous=ctx['sources'][0];edge='^'
        for a,b,ae,be in ctx['chain']:
            wk=(m,previous,a);expected_wires.add(wk);j.require(wk in wire_records,'RETENTION_WIRE_COVERAGE');w=wire_records[wk]
            key=(m,a,b);rec=records[key];body=raw[key]
            j.require(rec['edges']==[ae,be] and edge==ae and w['edge']==edge,'RETENTION_ARC_POLARITY')
            j.require(abs(rec['input_slew_ns']-slew)<2e-6,'RETENTION_ARC_SLEW_CHAIN')
            for label,field,count in [('input_net_transition','input_slew_ns',2),('total_output_net_capacitance','load_pf',2),('Delay','delay_ns',1),('Slew','output_slew_ns',1)]:
                matches=re.findall(r'(?m)^(?:------- |\|       )?'+label+r' = ([^\n]+)$',body)
                j.require(len(matches)==count and all(float(v)==rec[field] for v in matches),'RETENTION_ARC_REPORT_MISMATCH')
            j.require((allow_annotations or not rec['annotated'] and not w['annotated']) and
                      (rec['annotated'] or rec['effective_ns']==rec['delay_ns']) and
                      (w['annotated'] or w['delay_ns']==0),'RETENTION_UNMODELED_ANNOTATION')
            value+=w['delay_ns']+rec['effective_ns'];slew=rec['output_slew_ns'];previous=b;edge=be
        for role,last,rf in [('a',previous,edge),('ack',ctx['sources'][0],'^')]:
            wk=(m,last,ctx['fork_pins'][role]);expected_wires.add(wk);j.require(wk in wire_records,'RETENTION_WIRE_COVERAGE');w=wire_records[wk]
            j.require(w['edge']==rf and (allow_annotations or not w['annotated']) and (w['annotated'] or w['delay_ns']==0),'RETENTION_UNMODELED_WIRE')
            rows[role+':'+m]=dict(delay_ns=(value if role=='a' else 0)+w['delay_ns'])
        j.require(all(math.isfinite(v) and v>=0 for v in totals[m][:2]) and abs(totals[m][0]-rows['a:'+m]['delay_ns'])<1e-6 and
                  totals[m][1]==slew and totals[m][2]=='v','RETENTION_ARC_TOTAL')
    j.require(set(wire_records)==expected_wires,'RETENTION_WIRE_COVERAGE')
    j.require(all(rows[k+':min']['delay_ns']<=rows[k+':max']['delay_ns']+1e-6 for k in ('a','ack')),'RETENTION_REVERSED_BOUNDS')
    return dict(rows=rows,slews=slews(log),cell_arcs=[dict(mode=k[0],source=k[1],sink=k[2],**v) for k,v in records.items()],
                wires=[dict(mode=k[0],source=k[1],sink=k[2],**v) for k,v in wire_records.items()],method='loaded_first_transition_arc_composition')


def parse(log,plan,ctx,*,allow_annotations=False):
    if ctx['kind']=='arrival':return dict(request=j.parse(log,plan,ctx['request']),slews=slews(log))
    j.require(log.count('RETENTION_BEGIN\n')==log.count('RETENTION_COMPLETE\n')==1,'RETENTION_INCOMPLETE')
    j.require(not re.search(r'(?mi)^(?:Error:|ERROR|Warning:)',log),'RETENTION_TOOL_DIAGNOSTIC')
    if ctx['kind']=='fork':return parse_fork(log,ctx,allow_annotations)
    qs={q['id']:q for q in ctx['queries']};rows={};paths={};u=plan['stages']['update'];bd=plan['variant']=='bd'
    for line in log.splitlines():
        f=line.split('\t')
        if f[0]=='CONTROL_PATH':
            j.require(len(f)==11 and f[1] in qs and f[1] not in rows,'RETENTION_QUERY_ROW')
            q=qs[f[1]];sa,arr,data,delay,slew=map(float,f[2:7]);start,end,se,te=f[7:]
            j.require(all(math.isfinite(v) and v>=0 for v in (sa,arr,data,delay,slew)) and abs(arr-sa-delay)<1e-5,'RETENTION_NUMERIC')
            sequential=not bd and q['role']=='ack'
            expected=u['prefix']+u['phase']['Q']['pin'] if sequential else ctx['sources'][0]
            j.require(start==expected and end==q['sink'] and se==(q['sink_edge'] if sequential else q['source_edge']) and te==q['sink_edge'],'RETENTION_PATH_BINDING')
            j.require(abs(data-(arr if sequential else delay))<1e-4,'RETENTION_ARRIVAL_ACCOUNTING')
            if not sequential:j.require(abs(sa)<1e-6,'RETENTION_EVENT_ORIGIN')
            rows[f[1]]=dict(delay_ns=arr if sequential else delay,start=start,end=end,max_slew_ns=slew)
        elif f[0]=='CONTROL_POINTS':
            j.require(f[1] in rows and f[1] not in paths,'RETENTION_POINTS_ID');paths[f[1]]=f[2:]
    j.require(set(rows)==set(paths)==set(qs),'RETENTION_QUERY_COVERAGE')
    for key,points in paths.items():
        q=qs[key];j.require(points[0]==ctx['sources'][0] and points[-1]==q['sink'],'RETENTION_POINTS_BINDING')
        if q['role']=='ack' and ctx['kind']=='permission':
            j.require(ack_pin(plan) in points,'RETENTION_ACK_PROVENANCE')
            if not bd:
                clk=u['prefix']+u['phase']['CLK']['pin'];qn=u['prefix']+u['phase']['Q']['pin']
                j.require(points.count(clk)==points.count(qn)==1 and points.index(qn)==points.index(clk)+1,'RETENTION_CLK_Q_PROVENANCE')
        if q['role']=='a':
            src=plan['stages'][ctx['side']];a=src['prefix']+j.relative.driver(src['native'],'a')
            j.require(points.count(a)==1 and any(p.startswith(src['prefix']+'ca_primitive_a/') for p in points[:-1]),'RETENTION_A_PROVENANCE')
        if q['mode']=='min':j.require(rows[key]['delay_ns']<=rows[key.replace(':min',':max')]['delay_ns']+1e-6,'RETENTION_REVERSED_BOUNDS')
    j.require(log.count('RETENTION_ELECTRICAL_BEGIN\n')==log.count('RETENTION_ELECTRICAL_END\n')==1,'RETENTION_ELECTRICAL_COVERAGE')
    electrical=log.split('RETENTION_ELECTRICAL_BEGIN\n')[1].split('RETENTION_ELECTRICAL_END\n')[0]
    return dict(rows=rows,paths=paths,slews=slews(log),electrical_violations=[l for l in electrical.splitlines() if '(VIOLATED)' in l])


def margins(results,plan,aperture):
    summary=[]
    for ctx in [c for c in plan['retention_contexts'] if c['kind']=='permission']:
        name=ctx['id'];r=results[name];arrival=results[name.replace('-permission-','-arrival-')]
        j.require(r['slews']==arrival['slews'],'RETENTION_COMMON_SLEW_CHANGED')
        rows=r['rows'];ack=rows['ack:min']['delay_ns']
        values=[dict(lane=l['lane'],ack_after_capture_ns=ack-rows[f'capture:{l["lane"]}:max']['delay_ns'])
                for l in plan['stages']['update']['lane_map']]
        summary.append(dict(side=ctx['side'],phase=ctx['phase'],minimum_ack_after_capture_ns=min(v['ack_after_capture_ns'] for v in values),
            zero_contamination_hold_margin_ns=min(v['ack_after_capture_ns'] for v in values)-aperture['hold_ns'],lanes=values))
    forks=[]
    if plan['variant']=='bd':
        for side in ('left','right'):
            r=results[side+'-fork'];v=results[side+'-permission-0']['slews']['ack']
            j.require(r['slews']['ack']==v,'RETENTION_FORK_SLEW_CHANGED')
            margin=r['rows']['a:min']['delay_ns']-r['rows']['ack:max']['delay_ns']
            forks.append(dict(side=side,margin_ns=margin,strict_order=margin>0))
    return dict(permission=summary,forks=forks,physical_qualification=False)


def verify_baseline(baseline):
    receipt=json.loads((baseline/'results.json').read_text())
    for p,h in receipt['inputs_sha256'].items():j.require(j.sha(Path(p))==h,'RETENTION_STALE_SOURCE')
    for p,h in receipt['files_sha256'].items():j.require(j.sha(baseline/p)==h,'RETENTION_STALE_BASELINE')
    return receipt


def run(baseline,output,campaign=False):
    j.require(not output.exists(),'RETENTION_OUTPUT_EXISTS');receipt=verify_baseline(baseline);sta=j.tool('sta')
    j.require(all(receipt['inputs_sha256'].get(str(p.resolve()))==j.sha(p) for p in sta.input_files()),'RETENTION_RUNTIME')
    frozen={str(p.resolve()):j.sha(p) for p in (Path(__file__),FORK_ARCS,baseline/'results.json')}
    plan=json.loads((baseline/'plan.json').read_text());cells=j.flat_cells(json.loads((baseline/'slice.json').read_text()))
    plan['retention_contexts']=contexts(plan,cells);output.mkdir(parents=True);j.write_json(output/'plan.json',plan);cases=[]
    for old in receipt['cases'] if campaign else receipt['cases'][:1]:
        j.require(not old['failure'] and not old['negative_metrics'] and old['status']=='CONDITIONAL_SETUP_MEASUREMENTS','RETENTION_SOURCE_SETUP_UNPROVEN')
        saved=json.loads((baseline/(old['key']+'.json')).read_text());results={};failure=None
        for ctx in plan['retention_contexts']:
            tcl=output/(old['key']+'-'+ctx['id']+'.tcl');log=tcl.with_suffix('.log')
            ack=results[ctx['side']+'-permission-0']['slews']['ack'] if ctx['kind']=='fork' else None
            tcl.write_text(script(baseline/'slice.v',old['corner'],old['slew_ns'],plan,ctx,sta,ack_slews=ack),newline='\n')
            with log.open('w') as stream:subprocess.run(sta.command(['-no_init','-exit',sta.path(tcl)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
            try:
                r=parse(log.read_text(),plan,ctx)
                if ctx['kind']=='arrival':j.require(r['request']==saved['results'][ctx['request']['id']],'RETENTION_REQUEST_CHANGED')
                results[ctx['id']]=r
            except ValueError as e:failure=dict(context=ctx['id'],diagnostic=str(e));break
        summary=None if failure else margins(results,plan,saved['aperture'])
        negative=[] if failure else [dict(side=s['side'],phase=s['phase'],metric='zero_contamination_hold') for s in summary['permission'] if s['zero_contamination_hold_margin_ns']<0]
        if summary:negative += [dict(side=s['side'],metric='fork_order') for s in summary['forks'] if not s['strict_order']]
        case=dict(key=old['key'],corner=old['corner'],slew_ns=old['slew_ns'],failure=failure,negative_metrics=negative,summary=summary)
        j.write_json(output/(old['key']+'.json'),dict(case=case,results=results,aperture=saved['aperture']));cases.append(case)
        print(old['key']+' '+json.dumps(dict(failure=failure,negative=negative)),flush=True)
    verify_baseline(baseline);j.require(all(j.sha(Path(p))==h for p,h in frozen.items()),'RETENTION_INPUT_CHANGED')
    j.write_json(output/'results.json',dict(physical_qualification=False,baseline=str(baseline.resolve()),cases=cases,inputs_sha256=frozen,
        files_sha256={str(p.relative_to(output)).replace('\\','/'):j.sha(p) for p in sorted(output.rglob('*')) if p.is_file()}))
    j.require(all(not c['failure'] for c in cases),'RETENTION_UNRESOLVED')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('output',type=Path);p.add_argument('--campaign',action='store_true')
    a=p.parse_args();run(a.baseline,a.output,a.campaign)

# SPDX-License-Identifier: Apache-2.0
"""Exact-arc fault controls for Control's conditional capture retention bounds."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import subprocess

import control_retention_timing as r
from check_control_join_controls import fault_sdf as join_fault_sdf, check_period

j=r.j


def fault_sdf(plan,cells,fault):
    u=plan['stages']['update'];arcs=[];blocks=[]
    if fault=='late_fork':
        source=r.ack_pin(plan);sink=r.fork_pins(plan['stages']['left'])['ack'];a,b=[x.replace('.','\\.') for x in (source,sink)]
        return ('(DELAYFILE (SDFVERSION "3.0") (DESIGN "'+j.TOP+'") (DIVIDER /) (TIMESCALE 1ns)\n'
                '(CELL (CELLTYPE "'+j.TOP+'") (INSTANCE) (DELAY (ABSOLUTE (INTERCONNECT '+a+' '+b+' (1000:1000:1000) (1000:1000:1000))))))\n',
                [dict(source=source,sink=sink,delay_ns=1000)])
    if fault=='zero_fork':
        for a,b,_,_ in r.fork_chain(plan['stages']['left']):
            name,src=a.rsplit('/',1);dst=b.rsplit('/',1)[1];c=next(c for c in cells if c['path']==name)
            instance=name.replace('.','\\.');blocks.append(f'(CELL (CELLTYPE "{c["cell"]}") (INSTANCE {instance}) (DELAY (ABSOLUTE (IOPATH {src} {dst} (0:0:0) (0:0:0)))))')
            arcs.append(dict(cell=name,source=src,sink=dst,delay_ns=0))
        return '(DELAYFILE (SDFVERSION "3.0") (DESIGN "'+j.TOP+'") (DIVIDER /) (TIMESCALE 1ns)\n'+"\n".join(blocks)+')\n',arcs
    if fault=='late_capture':
        # Reuse the exact physical 16-pin branch resolver, targeting update.
        p=deepcopy(plan);p['stages']['left']=u
        return join_fault_sdf(p,cells,'late_source_capture')
    j.require(fault=='early_ack','RETENTION_CONTROL_FAULT')
    owner='acknowledge' if plan['variant']=='bd' else 'acknowledge_guard'
    selected=[c for c in cells if c['path'].startswith(u['prefix']+'ca_primitive_'+owner+'/')]
    if plan['variant']=='click':
        selected += [c for c in cells if c['path'].startswith(u['prefix']+'ca_primitive_input_phase/')]
    j.require(selected,'RETENTION_CONTROL_EMPTY')
    for c in selected:
        outputs=[p for p in c['pins'] if c['directions'][p]=='output'];j.require(len(outputs)==1,'RETENTION_CONTROL_OUTPUT')
        dst=outputs[0];entries=[]
        for src in c['pins']:
            if c['directions'][src]!='input' or c['cell']==j.SC+'dffrnq_1' and src!='CLK':continue
            entries.append(f'(IOPATH {src} {dst} (0.000001:0.000001:0.000001) (0.000001:0.000001:0.000001))')
            arcs.append(dict(cell=c['path'],source=src,sink=dst,delay_ns=.000001))
        instance=c['path'].replace('.','\\.')
        blocks.append(f'(CELL (CELLTYPE "{c["cell"]}") (INSTANCE {instance}) (DELAY (ABSOLUTE '+" ".join(entries)+')))')
    return '(DELAYFILE (SDFVERSION "3.0") (DESIGN "'+j.TOP+'") (DIVIDER /) (TIMESCALE 1ns)\n'+"\n".join(blocks)+')\n',arcs


def verify(directory):
    receipt=json.loads((directory/'results.json').read_text());r.verify_baseline(Path(receipt['baseline']))
    for p,h in receipt['inputs_sha256'].items():j.require(j.sha(Path(p))==h,'RETENTION_CONTROL_STALE_SOURCE')
    for p,h in receipt['files_sha256'].items():j.require(j.sha(directory/p)==h,'RETENTION_CONTROL_STALE_BASELINE')
    return receipt


def run(baseline,output):
    j.require(not output.exists(),'RETENTION_CONTROL_OUTPUT_EXISTS');receipt=verify(baseline);sta=j.tool('sta')
    original=Path(receipt['baseline']);old=json.loads((original/'results.json').read_text())
    j.require(all(old['inputs_sha256'].get(str(p.resolve()))==j.sha(p) for p in sta.input_files()),'RETENTION_CONTROL_RUNTIME')
    sources={str(p.resolve()):j.sha(p) for p in (Path(__file__),j.ROOT/'tools/check_control_join_controls.py')}
    plan=json.loads((baseline/'plan.json').read_text());cells=j.flat_cells(json.loads((original/'slice.json').read_text()))
    case=receipt['cases'][0];saved=json.loads((baseline/(case['key']+'.json')).read_text())
    j.require(not case['failure'] and not case['negative_metrics'],'RETENTION_CONTROL_NEGATIVE_BASELINE')
    output.mkdir(parents=True);verdicts=[]
    for fault in ['period','late_capture','early_ack']+(['late_fork','zero_fork'] if plan['variant']=='bd' else []):
        results={};sdf=None;arcs=[]
        if fault!='period':
            text,arcs=fault_sdf(plan,cells,fault);sdf=output/(fault+'.sdf');sdf.write_text(text,newline='\n')
        for ctx in plan['retention_contexts']:
            ack=results[ctx['side']+'-permission-0']['slews']['ack'] if ctx['kind']=='fork' else None
            tcl=output/(fault+'-'+ctx['id']+'.tcl');log=tcl.with_suffix('.log')
            tcl.write_text(r.script(original/'slice.v',case['corner'],case['slew_ns'],plan,ctx,sta,
                period=2000 if fault=='period' else 1000,sdf=sdf,ack_slews=ack),newline='\n')
            with log.open('w') as stream:subprocess.run(sta.command(['-no_init','-exit',sta.path(tcl)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
            results[ctx['id']]=r.parse(log.read_text(),plan,ctx,allow_annotations=sdf is not None)
        summary=r.margins(results,plan,saved['aperture'])
        if fault=='period':check_period(results,saved['results'],summary,case['summary'])
        elif fault in ('late_fork','zero_fork'):
            j.require(summary['permission']==case['summary']['permission'] and results['right-fork']==saved['results']['right-fork'],'RETENTION_CONTROL_FORK_SCOPE')
            before=case['summary']['forks'][0];after=summary['forks'][0]
            j.require(before['strict_order'] and not after['strict_order'],'RETENTION_CONTROL_FORK_NO_FAILURE')
            if fault=='late_fork':
                a,b=results['left-fork'],saved['results']['left-fork']
                j.require(a['cell_arcs']==b['cell_arcs'],'RETENTION_CONTROL_FORK_COLLATERAL')
                changed=[(x,y) for x,y in zip(a['wires'],b['wires']) if x!=y]
                j.require(len(changed)==2 and all(x['source']==arcs[0]['source'] and x['sink']==arcs[0]['sink'] and
                          x['delay_ns']>y['delay_ns']+999 for x,y in changed),'RETENTION_CONTROL_FORK_WIRE_MEMBERSHIP')
            else:j.require(after['margin_ns']==0,'RETENTION_CONTROL_FORK_EQUALITY')
        else:
            j.require(all(b['zero_contamination_hold_margin_ns']>0>a['zero_contamination_hold_margin_ns']
                          for a,b in zip(summary['permission'],case['summary']['permission'])),'RETENTION_CONTROL_NO_NEW_FAILURE')
            for ctx in [c for c in plan['retention_contexts'] if c['kind']=='permission']:
                after=results[ctx['id']]['rows'];before=saved['results'][ctx['id']]['rows']
                for q in ctx['queries']:
                    if q['role']==('ack' if fault=='late_capture' else 'capture'):
                        j.require(after[q['id']]==before[q['id']],'RETENTION_CONTROL_COLLATERAL_CHANGE')
                    if fault=='early_ack' and q['role']=='ack':
                        j.require(after[q['id']]['delay_ns']<before[q['id']]['delay_ns'],'RETENTION_CONTROL_ACK_NOT_EARLIER')
            if fault=='late_capture':
                branch=next(c for c in cells if c['path']==arcs[0]['cell']);node=branch['pins']['Z'];cap='E' if plan['variant']=='bd' else 'CLK'
                pins={c['path']+'/'+cap for c in cells if c['pins'].get(cap)==node}
                expected={l['lane'] for l in plan['stages']['update']['lane_map'] if plan['stages']['update']['prefix']+l['capture'] in pins}
                j.require(len(expected)==16,'RETENTION_CONTROL_BRANCH_SIZE')
                for ctx in [c for c in plan['retention_contexts'] if c['kind']=='permission']:
                    changed={q['lane'] for q in ctx['queries'] if q['role']=='capture' and
                        abs(results[ctx['id']]['rows'][q['id']]['delay_ns']-saved['results'][ctx['id']]['rows'][q['id']]['delay_ns'])>1e-4}
                    j.require(changed==expected,'RETENTION_CONTROL_CAPTURE_MEMBERSHIP')
        j.write_json(output/(fault+'.json'),dict(summary=summary,results=results,arcs=arcs))
        verdicts.append(dict(fault=fault,status='EXPECTED',arc_count=len(arcs)));print(fault+' EXPECTED',flush=True)
    verify(baseline);j.require(all(j.sha(Path(p))==h for p,h in sources.items()),'RETENTION_CONTROL_SOURCE_CHANGED')
    j.write_json(output/'controls.json',dict(status='PASS',physical_qualification=False,baseline_sha256=j.sha(baseline/'results.json'),
        sources_sha256=sources,verdicts=verdicts,files_sha256={str(p.relative_to(output)).replace('\\','/'):j.sha(p) for p in output.iterdir() if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();run(a.baseline,a.output)

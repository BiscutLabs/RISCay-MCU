# SPDX-License-Identifier: Apache-2.0
"""Period invariance and real parent ACK-guard sensitivity on the loaded graph."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import control_join_timing as j
from check_control_relative_controls import verify_runtime
from repair_gf180_design import flat


def run(baseline, output):
    j.require(not output.exists(),'JOIN_LEAF_CONTROL_OUTPUT_EXISTS')
    receipt=json.loads((baseline/'results.json').read_text())
    plan=json.loads((baseline/'plan.json').read_text())
    j.require(plan.get('leaf_anchored'),'JOIN_LEAF_CONTROL_PLAN')
    sta=j.tool('sta');runtime=verify_runtime(sta,receipt['inputs_sha256'])
    frozen=dict(receipt['inputs_sha256']);frozen[str(Path(__file__).resolve())]=j.sha(Path(__file__))
    def verify():
        for p,h in frozen.items():j.require(j.sha(Path(p))==h,'JOIN_LEAF_CONTROL_SOURCE_CHANGED')
        for p,h in receipt['files_sha256'].items():j.require(j.sha(baseline/p)==h,'JOIN_LEAF_CONTROL_EVIDENCE_CHANGED')
    verify()
    netlist=next(Path(p) for p in receipt['inputs_sha256'] if Path(p).name=='netlist.v')
    cells=flat(json.loads(netlist.with_suffix('.json').read_text()),'RiscayMcuDigital')['cells']
    key='tt_025C_3v30-s0.2';saved=json.loads((baseline/(key+'.json')).read_text())
    j.require(saved['case']['failure'] is None and not saved['case']['negative_metrics'],'JOIN_LEAF_CONTROL_BASELINE')
    output.mkdir(parents=True);verdicts=[]
    faults=['period']+(['parent_ack_arc'] if plan.get('acknowledge_guard') else [])
    for fault in faults:
        results=deepcopy(saved['results']);sdf=None;arc=None
        if fault=='parent_ack_arc':
            prefix=plan['physical_prefix']+plan['acknowledge_guard']+'/'
            matches=[(p,c) for p,c in cells.items() if p.startswith(prefix) and c['type']==j.SC+'dlyd_1']
            j.require(matches,'JOIN_LEAF_ACK_GUARD_ARC')
            path,cell=matches[0];arc=dict(cell=path,source='I',sink='Z',delay_ns=1000)
            instance=path.replace('.',r'\.')
            text='(DELAYFILE (SDFVERSION "3.0") (DESIGN "RiscayMcuDigital") (DIVIDER /) (TIMESCALE 1ns)\n'
            text+=f'(CELL (CELLTYPE "{cell["type"]}") (INSTANCE {instance}) (DELAY (ABSOLUTE (IOPATH I Z (1000:1000:1000) (1000:1000:1000)))))\n)\n'
            sdf=output/(fault+'.sdf');sdf.write_text(text,newline='\n')
        for ctx in plan['contexts']:
            if fault!='period' and ctx['kind']!='request':continue
            dq=saved['results'][ctx['side']+'-input']['dq'] if ctx['kind']=='launch' and plan['variant']=='bd' else None
            if ctx['kind']=='launch' and plan['variant']=='click':
                a,b=saved['results'][f"{ctx['side']}-request-{ctx['phase']}"]['event_slews']
                ctx['root_slew_ns']=dict(min=a,max=b)
            tcl=output/(fault+'-'+ctx['id']+'.tcl');log=tcl.with_suffix('.log')
            tcl.write_text(j.script(netlist,'tt_025C_3v30',.2,plan,ctx,sta=sta,period=2000 if fault=='period' else 1000,dq=dq,sdf=sdf),newline='\n')
            with log.open('w') as stream:
                subprocess.run(sta.command(['-no_init','-exit',sta.path(tcl)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
            results[ctx['id']]=j.parse(log.read_text(),plan,ctx,cells=cells)
        summary=j.margins(results,plan,saved['aperture'])
        if fault=='period':
            j.require(results==saved['results'] and summary==saved['case']['summary'],'JOIN_LEAF_PERIOD_DEPENDENCE')
            verdict=dict(fault=fault,status='IDENTICAL')
        else:
            changed=[]
            for ctx in plan['contexts']:
                old,new=saved['results'][ctx['id']],results[ctx['id']]
                for q in ctx['queries']:
                    a,b=old['rows'][q['id']],new['rows'][q['id']]
                    if q['role']=='return':
                        j.require(b['delay_ns']-a['delay_ns']>900,'JOIN_LEAF_ACK_ARC_NOT_MEASURED')
                        j.require(arc['cell']+'/Z' in new['paths'][q['id']],'JOIN_LEAF_ACK_ARC_PATH')
                        changed.append((ctx['id'],q['id']))
                    else:j.require(a==b and old['paths'][q['id']]==new['paths'][q['id']],'JOIN_LEAF_ACK_OFF_PATH_CHANGE')
            j.require(changed,'JOIN_LEAF_ACK_NO_RETURN')
            verdict=dict(fault=fault,status='EXPECTED_SENSITIVITY',changed=changed,arc=arc)
        j.write_json(output/(fault+'.json'),dict(verdict=verdict,results=results,summary=summary))
        verdicts.append(verdict);print(json.dumps(dict(fault=fault,status=verdict['status'])),flush=True)
    verify()
    j.write_json(output/'controls.json',dict(status='PASS',physical_qualification=False,verdicts=verdicts,
        inputs_sha256=frozen,runtime_sha256=runtime,baseline_sha256=j.sha(baseline/'results.json'),
        files_sha256={p.name:j.sha(p) for p in output.iterdir() if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();run(args.baseline,args.output)

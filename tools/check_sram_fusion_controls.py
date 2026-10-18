# SPDX-License-Identifier: Apache-2.0
"""Period invariance and actual-arc capture/source fault controls for SRAM fusion."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import subprocess

import sram_fusion_timing as f
from check_control_relative_controls import verify_runtime
from repair_gf180_design import flat


def run(baseline,output):
    f.require(not output.exists(),'SRAM_FUSION_CONTROLS_OUTPUT_EXISTS')
    receipt=json.loads((baseline/'results.json').read_text());plan=json.loads((baseline/'plan.json').read_text())
    key='tt_025C_3v30-s0.2';saved=json.loads((baseline/(key+'.json')).read_text())
    f.require(saved['case']['failure'] is None and not saved['case']['negative_metrics'],'SRAM_FUSION_CONTROLS_BASELINE')
    sta=f.tool('sta');runtime=verify_runtime(sta,receipt['inputs_sha256'])
    frozen=dict(receipt['inputs_sha256']);frozen[str(Path(__file__).resolve())]=f.sha(Path(__file__))
    frozen[str((baseline/'results.json').resolve())]=f.sha(baseline/'results.json')
    def verify():
        for p,h in frozen.items():f.require(f.sha(Path(p))==h,'SRAM_FUSION_CONTROLS_INPUT_CHANGED')
        for p,h in receipt['files_sha256'].items():f.require(f.sha(baseline/p)==h,'SRAM_FUSION_CONTROLS_EVIDENCE_CHANGED')
    verify()
    netlist=next(Path(p) for p in receipt['inputs_sha256'] if Path(p).name=='netlist.v')
    cells=flat(json.loads(netlist.with_suffix('.json').read_text()),'RiscayMcuDigital')['cells']
    dest=plan['stages']['update'];pin=dest['prefix']+dest['lane_map'][0]['capture']
    path,port=pin.rsplit('/',1);net=cells[path]['connections'][port]
    drivers=[(p,c,k) for p,c in cells.items() for k,bits in c['connections'].items() if c['directions'][k]=='output' and bits==net]
    f.require(len(drivers)==1,'SRAM_FUSION_CONTROLS_CAPTURE_DRIVER')
    capture_path,capture_cell,capture_pin=drivers[0]
    f.require(capture_cell['type'].startswith(f.SC+'buf_') and capture_pin=='Z','SRAM_FUSION_CONTROLS_CAPTURE_BUFFER')
    capture_lanes={l['lane'] for l in dest['lane_map'] if cells[(dest['prefix']+l['capture']).rsplit('/',1)[0]]['connections'][(dest['prefix']+l['capture']).rsplit('/',1)[1]]==net}
    output.mkdir(parents=True);verdicts=[]
    faults=['period','late_capture']+(['late_source_cq'] if plan['variant']=='click' else [])
    for fault in faults:
        results=deepcopy(saved['results']);sdf=None;arc=None
        if fault!='period':
            if fault=='late_capture':arc=dict(cell=capture_path,master=capture_cell['type'],source='I',sink='Z',delay_ns=1000)
            else:
                rows=saved['results']['right-launch-0']['rows']
                row=max((v for k,v in rows.items() if k.startswith('data:')),key=lambda v:v['delay_ns'])
                p,q=row['start'].rsplit('/',1)
                f.require(q=='Q' and p.startswith(plan['stages']['right']['prefix']) and cells[p]['type']==f.SC+'dffrnq_1','SRAM_FUSION_CONTROLS_SOURCE_CQ')
                arc=dict(cell=p,master=cells[p]['type'],source='CLK',sink='Q',delay_ns=1000)
            instance=arc['cell'].replace('.',r'\.')
            text='(DELAYFILE (SDFVERSION "3.0") (DESIGN "RiscayMcuDigital") (DIVIDER /) (TIMESCALE 1ns)\n'
            text+=f'(CELL (CELLTYPE "{arc["master"]}") (INSTANCE {instance}) (DELAY (ABSOLUTE (IOPATH {arc["source"]} {arc["sink"]} (1000:1000:1000) (1000:1000:1000)))))\n)\n'
            sdf=output/(fault+'.sdf');sdf.write_text(text,newline='\n')
        changed=[]
        for ctx in plan['contexts']:
            wanted=('request' if plan['variant']=='bd' else 'launch')
            if fault!='period' and (ctx['kind']!=wanted or fault=='late_source_cq' and ctx['side']!='right'):continue
            dq=saved['results'][ctx['side']+'-input']['dq'] if ctx['kind']=='launch' and plan['variant']=='bd' else None
            if ctx['kind']=='launch' and plan['variant']=='click':
                a,b=saved['results'][f"{ctx['side']}-request-{ctx['phase']}"]['event_slews'];ctx['root_slew_ns']=dict(min=a,max=b)
            tcl=output/(fault+'-'+ctx['id']+'.tcl');log=tcl.with_suffix('.log')
            tcl.write_text(f.join.script(netlist,'tt_025C_3v30',.2,plan,ctx,sta=sta,period=2000 if fault=='period' else 1000,dq=dq,sdf=sdf),newline='\n')
            with log.open('w') as stream:
                subprocess.run(sta.command(['-no_init','-exit',sta.path(tcl)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
            actual=f.join.parse(log.read_text(),plan,ctx,cells=cells);results[ctx['id']]=actual
            for q in ctx['queries']:
                old=saved['results'][ctx['id']]['rows'][q['id']];new=actual['rows'][q['id']]
                expected=fault=='late_capture' and q['role']=='capture' and q['lane'] in capture_lanes
                if fault=='late_source_cq' and q['role']=='data':
                    expected=arc['cell']+'/'+arc['sink'] in actual['paths'][q['id']]
                if expected:
                    f.require(new['delay_ns']-old['delay_ns']>900,'SRAM_FUSION_CONTROLS_ARC_NOT_MEASURED')
                    f.require(arc['cell']+'/'+arc['sink'] in actual['paths'][q['id']],'SRAM_FUSION_CONTROLS_ARC_PATH')
                    changed.append((ctx['id'],q['id']))
                else:f.require(new==old and actual['paths'][q['id']]==saved['results'][ctx['id']]['paths'][q['id']],
                               'SRAM_FUSION_CONTROLS_OFF_PATH_CHANGE')
        summary=f.source_margins(results,plan,saved['aperture']);ordering=f.return_ordering(results,plan,saved['aperture'])
        if fault=='period':
            f.require(results==saved['results'] and summary==saved['case']['summary'] and ordering==saved['case']['return_ordering'],
                      'SRAM_FUSION_CONTROLS_PERIOD_DEPENDENCE')
        else:
            f.require(changed,'SRAM_FUSION_CONTROLS_NO_CHANGED_QUERY')
            if plan['variant']=='bd':f.require(all(r['zero_contamination_hold_margin_ns']<0 for r in ordering),'SRAM_FUSION_CONTROLS_LATE_CAPTURE_ACCEPTED')
            if fault=='late_source_cq':f.require(all(r['minimum_conditional_setup_margin_ns']<0 for r in summary),'SRAM_FUSION_CONTROLS_LATE_DATA_ACCEPTED')
        verdict=dict(fault=fault,status='IDENTICAL' if fault=='period' else 'EXPECTED_SENSITIVITY',changed=changed,arc=arc)
        f.write_json(output/(fault+'.json'),dict(verdict=verdict,results=results,summary=summary,return_ordering=ordering))
        verdicts.append(verdict);print(json.dumps(dict(fault=fault,status=verdict['status'])),flush=True)
    verify()
    f.write_json(output/'controls.json',dict(status='PASS',physical_qualification=False,verdicts=verdicts,
        inputs_sha256=frozen,runtime_sha256=runtime,baseline_sha256=frozen[str((baseline/'results.json').resolve())],
        files_sha256={p.name:f.sha(p) for p in output.iterdir() if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();run(a.baseline,a.output)

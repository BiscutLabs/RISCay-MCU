# SPDX-License-Identifier: Apache-2.0
"""Exact mapped-path controls for the reusable ordering-guard campaign."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess

import control_relative_timing as r
import native_leaf_timing as leaf
import native_stage_timing as stage
import size_ordering_guards as g
from gf180_physical import ROOT, SC, sha, write_json
from physical_tools import tool
from repair_gf180_control import require


def context_for(plan, context, results):
    ctx = deepcopy(context)
    if ctx['kind'] in ('common', 'sequential_ack'):
        values = [v['event_slew_ns'] for k,v in results.items() if k.startswith(('request-', 'release-'))]
        ctx['root_slew_ns'] = dict(min=min(v[0] for v in values), max=max(v[1] for v in values))
    elif ctx['kind'] == 'rearm':
        ctx['root_slew_ns'] = results['ack']['phase_q_slew_ns'][ctx['queries'][0]['source_edge']]
    elif ctx['kind'] == 'publication':
        launch='a-launch' if plan.get('guard_only') else 'request-0'
        values = [results[launch]['a_slew_ns']['rise'], results['a-return']['a_slew_ns']['fall']]
        ctx['root_slew_ns'] = dict(min=min(v['min'] for v in values), max=max(v['max'] for v in values))
    bound = dict(plan, event=ctx['sources'][0]) if ctx['kind'] in ('publication','rearm','a-return','a-launch','launch') else plan
    return ctx, bound


def sdf(plan, fault):
    cells = plan['native']['cells']; prefix = plan['native']['physical_prefix']
    if fault == 'short-guard':
        name = 'output_delay' if plan['variant'] == 'bd' else 'acknowledge_guard'
        selected = [c for c in cells if c['path'].startswith(prefix+'ca_primitive_'+name+'/') and c['cell'] == SC+'dlyd_1']
        delay = .000001
    elif fault == 'late-rearm':
        driver=r.driver(plan['native'],'input_compare').rsplit('/',1)[0]
        selected = [c for c in cells if c['path']==driver]
        delay = 1000.
    else:
        require(fault == 'late-capture', 'GUARD_CONTROL_FAULT')
        capture = plan['lane_map'][0]['capture']; cell,pin = capture.rsplit('/',1)
        net = next(c for c in cells if c['path']==cell)['pins'][pin]
        selected = [c for c in cells if c['pins'].get('Z')==net]
        require(len(selected)==1 and selected[0]['cell'].startswith(SC+'buf_'), 'GUARD_CONTROL_CAPTURE_DRIVER')
        delay = 1000.
    require(selected, 'GUARD_CONTROL_EMPTY_ARCS')
    rows=[]; arcs=[]
    for cell in selected:
        require(set(cell['pins'])=={'I','Z'}, 'GUARD_CONTROL_ARC_SHAPE')
        path=cell['path'].replace('.',r'\.')
        value=f'{delay:.6f}'
        rows.append(f'(CELL (CELLTYPE "{cell["cell"]}") (INSTANCE {path}) (DELAY (ABSOLUTE '
                    f'(IOPATH I Z ({value}:{value}:{value}) ({value}:{value}:{value})))))')
        arcs.append(dict(cell=cell['path'],source='I',sink='Z',delay_ns=delay))
    return '(DELAYFILE (SDFVERSION "3.0") (DESIGN "RiscayMcuDigital") (DIVIDER /) (TIMESCALE 1ns)\n'+'\n'.join(rows)+')\n',arcs


def run(mapping, source, output):
    require(not output.exists(), 'GUARD_CONTROL_OUTPUT_EXISTS')
    receipt=g.validate_historical_receipt(mapping)
    proof=stage.receipt_proof(mapping,receipt)
    index=leaf.LeafIndex(stage.receipt_original(mapping,receipt),json.loads((mapping/'netlist.json').read_text()),
                         proof['added_buffers'],proof['added_ties'])
    plan=json.loads((source/'plan.json').read_text())
    key='tt_025C_3v30-s0.02'; saved=json.loads((source/(key+'.json')).read_text())
    liberty=r.library(ROOT/'.tools/physical/pdk'/(SC+r.CORNERS[0]+'.lib'))
    sta=tool('sta'); output.mkdir(parents=True)
    files=[Path(__file__),ROOT/'tools/size_ordering_guards.py',ROOT/'tools/native_leaf_timing.py',
           ROOT/'tools/control_relative_timing.py',source/'plan.json',source/(key+'.json'),
           *source.glob(key+'-*.tcl'),mapping/'netlist.json',mapping/'netlist.v',*sta.input_files()]
    frozen={str(p.resolve()):sha(p) for p in files}
    verdicts=[]
    faults=['period','short-guard','late-capture','wrong-slew']+(['wrong-return-cofactor'] if plan['variant']=='bd' else ['late-rearm'])
    for fault in faults:
        results=deepcopy(saved['results']); arcs=[]; caught=None
        if fault in ('short-guard','late-capture','late-rearm'):
            text,arcs=sdf(plan,fault); (output/(fault+'.sdf')).write_text(text,newline='\n')
        relevant = (None if fault in ('period','late-capture') else
                    {'publication'} if fault=='short-guard' and plan['variant']=='bd' else
                    {'ack'} if fault=='short-guard' else {'publication' if plan['variant']=='bd' else 'rearm-0'}
                    if fault=='wrong-slew' else {'a-return'} if fault=='wrong-return-cofactor' else {'rearm-0','rearm-1'})
        for original in plan['contexts']:
            if relevant is not None and original['id'] not in relevant:continue
            ctx,bound=context_for(plan,original,results)
            text=(source/(key+'-'+ctx['id']+'.tcl')).read_text()
            if fault=='period':
                text,count=re.subn(r'-period 1000\b','-period 2000',text)
                require(count==1, 'GUARD_CONTROL_PERIOD_BINDING')
            elif fault in ('short-guard','late-capture','late-rearm'):
                require(text.count('row RELATIVE_BEGIN')==1, 'GUARD_CONTROL_SDF_BINDING')
                text=text.replace('row RELATIVE_BEGIN',f'read_sdf {r.brace(sta.path(output/(fault+".sdf")))}\nrow RELATIVE_BEGIN')
            elif fault=='wrong-slew':
                text,count=re.subn(r'(sta::time_ui_sta )([0-9.eE+-]+)(\]\}\})',r'\g<1>7.0\3',text)
                require(count==2, 'GUARD_CONTROL_SLEW_BINDING')
            else:
                pin=r.driver(plan['native'],'b')
                marker='set_case_analysis 1 [exact_object pin {'+pin+'}]'
                require(text.count(marker)==1, 'GUARD_CONTROL_COFACTOR_BINDING')
                text=text.replace(marker,marker.replace('analysis 1','analysis 0'))
            tcl=output/(fault+'-'+ctx['id']+'.tcl'); log=tcl.with_suffix('.log')
            tcl.write_text(text,newline='\n')
            with log.open('w') as stream:
                execution=subprocess.run(sta.command(['-no_init','-exit',sta.path(tcl)],timeout=55),
                               stdout=stream,stderr=subprocess.STDOUT,check=False,timeout=65)
            output_text=log.read_text()
            if fault=='wrong-return-cofactor':
                # The contradictory state removes the actual outACK -> A fall
                # path. Require that exact reader failure, not any STA error.
                require(execution.returncode==1 and 'LEAF_ACK_MISSING' in output_text and 'RELATIVE_COMPLETE' not in output_text,
                        'GUARD_CONTROL_WRONG_COFACTOR_ACCEPTED')
                require(all('LEAF_ACK_MISSING' in line for line in output_text.splitlines() if line.startswith('Error:')),
                        'GUARD_CONTROL_UNRELATED_ERROR')
                caught='LEAF_ACK_MISSING'; break
            require(execution.returncode==0,'GUARD_CONTROL_STA_FAILED')
            try:
                results[ctx['id']]=leaf.parse(output_text,bound,ctx,.02,index)
            except ValueError as error:
                require(fault=='wrong-slew' and str(error)=='LEAF_SLEW_CHANGED', 'GUARD_CONTROL_WRONG_FAILURE')
                caught=str(error);break
            require(fault!='wrong-slew','GUARD_CONTROL_WRONG_SLEW_ACCEPTED')
            if ctx['kind']=='sequential_ack':results[ctx['id']]['phase_q_slew_ns']=g.phase_slews(output_text)
            if plan['variant']=='bd' and ctx['id'] in ('request-0','a-return','a-launch'):
                results[ctx['id']]['a_slew_ns']=g.phase_slews(output_text)
        if caught:
            verdict=dict(fault=fault,status='EXPECTED_DIAGNOSTIC',diagnostic=caught)
            checked=None
        else:
            checked=g.margins(results,plan,saved['aperture'],liberty)
            if fault=='period':
                require(results==saved['results'] and checked['rows']==saved['rows'], 'GUARD_CONTROL_PERIOD_DEPENDENCE')
                verdict=dict(fault=fault,status='IDENTICAL')
            else:
                target='publication-rise' if plan['variant']=='bd' else 'ack-after-rearm'
                if fault=='late-capture':target='publication-rise' if plan['variant']=='bd' else 'hold'
                require(checked['minima'][target]<0 and checked['minima'][target]<saved['minima'][target]-1,
                        'GUARD_CONTROL_FAULT_NOT_DETECTED')
                require(checked['minima'].get('setup')==saved['minima'].get('setup') or fault=='late-capture',
                        'GUARD_CONTROL_SETUP_SCOPE')
                verdict=dict(fault=fault,status='EXPECTED_NEGATIVE_MARGIN',metric=target,
                             before=saved['minima'][target],after=checked['minima'][target],arcs=arcs)
        write_json(output/(fault+'.json'),dict(verdict=verdict,checked=checked,results=results))
        verdicts.append(verdict);print(json.dumps({k:v for k,v in verdict.items() if k!='arcs'}),flush=True)
    require(all(sha(Path(p))==h for p,h in frozen.items()),'GUARD_CONTROL_INPUT_CHANGED')
    g.validate_historical_receipt(mapping)
    write_json(output/'results.json',dict(status='PASS_EXACT_CONTROLS',physical_qualification=False,
        verdicts=verdicts,inputs_sha256=frozen,files_sha256={p.name:sha(p) for p in output.iterdir() if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('mapping','source','output'):parser.add_argument(name,type=Path)
    args=parser.parse_args();run(args.mapping.resolve(),args.source.resolve(),args.output.resolve())

# SPDX-License-Identifier: Apache-2.0
"""Actual-arc and graph-binding controls for conditional Control Join evidence."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import control_join_timing as j


def check_period(results,saved,summary,before):
    # Aggregate minima can hide a changed noncritical lane or source slew.
    j.require(results==saved and summary==before,'JOIN_CONTROL_PERIOD_DEPENDENCE')


def fault_sdf(plan,cells,fault,side='left'):
    src=plan['stages'][side];dest=plan['stages']['update'];value=1000.0
    if fault=='late_input':
        selected=[c for c in cells if c['path'].startswith(src['prefix']+'ca_primitive_data_delay/') and c['cell']==j.SC+'buf_1'][:1]
    elif fault=='late_source_capture':
        pin=src['prefix']+src['lane_map'][0]['capture'];cell,p=pin.rsplit('/',1)
        node=next(c for c in cells if c['path']==cell)['pins'][p]
        selected=[c for c in cells if c['pins'].get('Z')==node]
        j.require(len(selected)==1 and selected[0]['cell']==j.SC+'buf_4','JOIN_CONTROL_CAPTURE_BRANCH')
    elif fault=='late_offer':
        owner='output_delay' if plan['variant']=='bd' else 'output_guard'
        pin=src['prefix']+j.relative.driver(src['native'],owner)
        selected=[c for c in cells if c['path']==pin.rsplit('/',1)[0]]
    elif fault=='late_rendezvous':
        inputs={n for c in cells if c['path'].startswith(dest['prefix']+'ca_primitive_request_delay/')
                for p,n in c['pins'].items() if c['directions'][p]=='input'}
        selected=[c for c in cells if c['path'].startswith(plan['rendezvous']) and
                  any(n in inputs for p,n in c['pins'].items() if c['directions'][p]=='output')]
        j.require(len(selected)==1,'JOIN_CONTROL_RENDEZVOUS_DRIVER')
    else:
        j.require(fault=='early_control','JOIN_CONTROL_FAULT');value=.000001
        owner='output_delay' if plan['variant']=='bd' else 'output_guard'
        roots=(src['prefix']+'ca_primitive_'+owner+'/',dest['prefix']+'ca_primitive_request_delay/')
        selected=[c for c in cells if c['path'].startswith(roots) and c['cell']==j.SC+'dlyd_1']
    j.require(selected,'JOIN_CONTROL_EMPTY');rows=[];arcs=[]
    for c in selected:
        outputs=[p for p in c['pins'] if c['directions'][p]=='output'];j.require(len(outputs)==1,'JOIN_CONTROL_OUTPUT')
        output=outputs[0];entries=[]
        for pin in c['pins']:
            if c['directions'][pin]!='input':continue
            v=f'{value:.6f}';entries.append(f'(IOPATH {pin} {output} ({v}:{v}:{v}) ({v}:{v}:{v}))')
            arcs.append(dict(cell=c['path'],source=pin,sink=output,delay_ns=value))
        instance=c['path'].replace('.','\\.')
        rows.append(f'(CELL (CELLTYPE "{c["cell"]}") (INSTANCE {instance}) (DELAY (ABSOLUTE '+" ".join(entries)+')))')
    return '(DELAYFILE (SDFVERSION "3.0") (DESIGN "'+j.TOP+'") (DIVIDER /) (TIMESCALE 1ns)\n'+"\n".join(rows)+')\n',arcs


def graph_controls(mapping,variant,target='control'):
    manifest=json.loads((mapping/'timing-intent.json').read_text())['manifest'];record=json.loads((mapping/'mapping.json').read_text())
    original=json.loads((mapping/'netlist.json').read_text());prefix='FourPhase' if variant=='bd' else 'Click';verdicts=[]
    # A differently named, actual instance must win over an unused named sibling.
    net=deepcopy(original);soc=net['modules'][net['modules']['RiscayMcuDigital']['cells']['soc']['type']]
    cfg=j.selection(variant,target);parent_name=cfg['parent_path'].split('.')[-1]
    parent=soc['cells'][parent_name]['type'];renamed=cfg['parent_family']+'_999'
    net['modules'][renamed]=deepcopy(net['modules'][parent]);soc['cells'][parent_name]['type']=renamed
    net['modules'][parent]['cells'].clear()
    _,plan=j.bound_slice(net,record,manifest,variant,target=target)
    j.require(plan['parent_module']==renamed,'JOIN_CONTROL_DEDUP_PARENT')
    verdicts.append(dict(fault='deduplicated_parent',status='EXPECTED'))
    # All rejection controls must also follow the actual renamed instance.
    # The unused unsuffixed sibling is deliberately empty, so a name-based
    # lookup cannot accidentally validate a mutation of the wrong module.
    original=net
    faults=['identity_permutation','external_load','unmodeled_lane','operand_wiring']
    if target=='execute':faults+=['rf_permutation','rf_tieoff','rf_duplicate','rf_undeclared','rf_only_lane']
    for fault in faults:
        net=deepcopy(original);kind='RiscayMcuDigital'
        for name in ('soc',*cfg['parent_path'].split('.')[1:]):kind=net['modules'][kind]['cells'][name]['type']
        parent=net['modules'][kind];join=net['modules'][parent['cells']['ca_child_join']['type']]
        left='ca_child_left'+('_storage' if variant=='click' else '')
        if fault=='identity_permutation':
            a=net['modules'][join['cells'][left]['type']]['cells']['ca_primitive_data_delay']['connections']['a'];a[0],a[1]=a[1],a[0]
            expected='JOIN_IDENTITY_DATA'
        elif fault=='external_load':
            bits=parent['cells']['ca_child_join']['connections']['out_req']
            parent['cells']['extra']=dict(type=j.SC+'buf_1',connections=dict(I=bits,Z=[987654321]),port_directions=dict(I='input',Z='output'),parameters={},attributes={})
            expected='JOIN_EXTERNAL_INTERNAL_LOAD'
        elif fault=='operand_wiring':
            conn=join['cells'][left]['connections'];name=next(n for n,b in conn.items() if n.startswith('in_bits') and len(b)>1)
            conn[name]=list(reversed(conn[name]));expected='JOIN_OPERAND_WIRING'
        elif fault.startswith('rf_'):
            sink=parent['cells'][cfg['sink_name']];conn=sink['connections'];pin='in_bits_registers_0'
            if fault=='rf_permutation':conn[pin]=list(reversed(conn[pin]));expected='JOIN_SIDE_INPUT_BINDING'
            elif fault=='rf_tieoff':conn[pin]=['0']*32;expected='JOIN_SIDE_INPUT_BINDING'
            elif fault=='rf_duplicate':conn[pin]=list(conn['in_bits_registers_1']);expected='JOIN_SIDE_INPUT_BINDING'
            elif fault=='rf_undeclared':
                conn['in_bits_hidden']=[987654321];sink['port_directions']['in_bits_hidden']='input';expected='JOIN_INPUT_COVERAGE'
            else:
                body=net['modules'][sink['type']]
                body['cells']['ca_primitive_data_delay']['connections']['a'][0]=body['ports'][pin]['bits'][0]
                expected='JOIN_DYNAMIC_LANE_COVERAGE'
        else:
            body=net['modules'][parent['cells'][cfg['sink_name']]['type']]
            body['cells']['ca_primitive_data_delay']['connections']['a'][0]=body['ports']['in_req']['bits'][0]
            expected='JOIN_DYNAMIC_LANE_COVERAGE'
        try:
            sliced,plan=j.bound_slice(net,record,manifest,variant,target=target);j.contexts(plan,j.flat_cells(sliced))
        except ValueError as e:j.require(str(e)==expected,'JOIN_CONTROL_WRONG_REJECTION_'+str(e))
        else:raise ValueError('JOIN_CONTROL_ACCEPTED_'+fault)
        verdicts.append(dict(fault=fault,status='EXPECTED',diagnostic=expected))
    return verdicts


def run(baseline,output):
    j.require(not output.exists(),'JOIN_CONTROL_OUTPUT_EXISTS');receipt=json.loads((baseline/'results.json').read_text())
    def verify():
        for p,h in receipt['inputs_sha256'].items():j.require(j.sha(Path(p))==h,'JOIN_CONTROL_STALE_SOURCE')
        for p,h in receipt['files_sha256'].items():j.require(j.sha(baseline/p)==h,'JOIN_CONTROL_STALE_BASELINE')
    verify();sta=j.tool('sta')
    j.require(all(receipt['inputs_sha256'].get(str(p.resolve()))==j.sha(p) for p in sta.input_files()),'JOIN_CONTROL_RUNTIME')
    own_hash=j.sha(Path(__file__));plan=json.loads((baseline/'plan.json').read_text());cells=j.flat_cells(json.loads((baseline/'slice.json').read_text()))
    case=receipt['cases'][0];saved=json.loads((baseline/(case['key']+'.json')).read_text())
    j.require(not case['failure'] and not case['negative_metrics'],'JOIN_CONTROL_BASELINE_NEGATIVE')
    output.mkdir(parents=True);verdicts=[]
    for fault in ('period','late_input','late_source_capture','late_offer','late_rendezvous','early_control'):
        results=deepcopy(saved['results']);arcs=[];sdf=None
        shared=fault in ('late_rendezvous','early_control')
        if fault!='period':
            text,arcs=fault_sdf(plan,cells,fault);sdf=output/(fault+'.sdf');sdf.write_text(text,newline='\n')
        for ctx in plan['contexts']:
            if fault=='period' and ctx['kind']!='launch':continue
            # Run all contexts for the selected operand: input slew and timing
            # provenance must be recomputed under the same physical mutation.
            if fault!='period' and not shared and ctx['side']!='left':continue
            dq=results[ctx['side']+'-input']['dq'] if ctx['kind']=='launch' and plan['variant']=='bd' else None
            text=j.script(baseline/'slice.v',case['corner'],case['slew_ns'],plan,ctx,sta=sta,
                period=2000 if fault=='period' else 1000,dq=dq,sdf=sdf)
            tcl=output/(fault+'-'+ctx['id']+'.tcl');log=tcl.with_suffix('.log');tcl.write_text(text,newline='\n')
            with log.open('w') as stream:subprocess.run(sta.command(['-no_init','-exit',sta.path(tcl)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
            results[ctx['id']]=j.parse(log.read_text(),plan,ctx)
        summary=j.margins(results,plan,saved['aperture']);before=case['summary']
        if fault=='late_source_capture':
            branch=next(c for c in cells if c['path']==arcs[0]['cell']);node=branch['pins']['Z']
            cp='E' if plan['variant']=='bd' else 'CLK';src=plan['stages']['left']
            pins={c['path']+'/'+cp for c in cells if c['pins'].get(cp)==node}
            expected={l['lane'] for l in src['lane_map'] if src['prefix']+l['capture'] in pins}
            for ctx in plan['contexts']:
                if ctx['side']!='left' or ctx['kind']!='request':continue
                changed={q['lane'] for q in ctx['queries'] if q['role']=='source_capture' and
                         abs(results[ctx['id']]['rows'][q['id']]['delay_ns']-saved['results'][ctx['id']]['rows'][q['id']]['delay_ns'])>1e-4}
                j.require(changed==expected and len(expected)==16,'JOIN_CONTROL_CAPTURE_MEMBERSHIP')
        if fault in ('late_offer','late_rendezvous','early_control'):
            for ctx in plan['contexts']:
                if (not shared and ctx['side']!='left') or not any(q['role']=='capture' for q in ctx['queries']):continue
                qs=[q for q in ctx['queries'] if q['role']=='capture']
                changed={q['id'] for q in qs if abs(results[ctx['id']]['rows'][q['id']]['delay_ns']-saved['results'][ctx['id']]['rows'][q['id']]['delay_ns'])>1e-4}
                j.require(changed=={q['id'] for q in qs},'JOIN_CONTROL_RENDEZVOUS_COVERAGE')
        if fault=='late_input':
            ctx=next(c for c in plan['contexts'] if c['id']=='left-input');src=plan['stages']['left']
            node=next(c for c in cells if c['path']==arcs[0]['cell'])['pins']['Z']
            affected={c['path']+'/D' for c in cells if c['pins'].get('D')==node}
            expected={q['id'] for q in ctx['queries'] if q['sink'] in affected}
            changed={q['id'] for q in ctx['queries'] if abs(results[ctx['id']]['rows'][q['id']]['delay_ns']-saved['results'][ctx['id']]['rows'][q['id']]['delay_ns'])>1e-4}
            j.require(changed==expected and len(expected)==2,'JOIN_CONTROL_INPUT_MEMBERSHIP')
        metrics=('maximum_input_data_lag_ns','minimum_conditional_setup_margin_ns','return_after_source_close_ns')
        changes=[dict(side=a['side'],phase=a['phase'],metric=k,before=b[k],after=a[k])
                 for a,b in zip(summary,before) for k in metrics if a[k] is not None and abs(a[k]-b[k])>1e-4]
        if fault=='period':check_period(results,saved['results'],summary,before)
        else:
            j.require({c['side'] for c in changes}==({'left','right'} if shared else {'left'}),'JOIN_CONTROL_SCOPE')
            metric='maximum_input_data_lag_ns' if fault=='late_input' else 'minimum_conditional_setup_margin_ns'
            changed=[c for c in changes if c['metric']==metric]
            j.require(changed,'JOIN_CONTROL_NO_MOVEMENT')
            if fault in ('late_offer','late_rendezvous'):
                j.require(all(c['after']>c['before']+900 for c in changed),'JOIN_CONTROL_LATE_ORDER')
            else:j.require(any(c['before']>0>c['after'] for c in changed),'JOIN_CONTROL_NO_NEW_FAILURE')
        j.write_json(output/(fault+'.json'),dict(summary=summary,results=results,changes=changes,arcs=arcs))
        verdicts.append(dict(fault=fault,status='EXPECTED',arc_count=len(arcs),changes=changes));print(fault+' EXPECTED',flush=True)
    mapping=next(Path(p).parent for p in receipt['inputs_sha256'] if p.endswith('mapping.json'))
    verdicts+=graph_controls(mapping,plan['variant'],plan.get('target','control'));verify();j.require(j.sha(Path(__file__))==own_hash,'JOIN_CONTROL_SOURCE_CHANGED')
    j.write_json(output/'controls.json',dict(status='PASS',physical_qualification=False,verdicts=verdicts,
        baseline_sha256=j.sha(baseline/'results.json'),source_sha256=own_hash,
        files_sha256={str(p.relative_to(output)).replace('\\','/'):j.sha(p) for p in output.iterdir() if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();run(a.baseline,a.output)

# SPDX-License-Identifier: Apache-2.0
"""Read-only actual-graph controls for C1e's native held-data proof handoff.

This never elaborates, converts, simulates or maps. It records exact input
identities and is separate from the 304 existing mask/clock controls and from
strict-export execution. A saved failed strict graph may be replayed explicitly;
success here does not rewrite or supersede that failed execution.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time

from check_reset_crossings import audit_graph, SRAM
from quiescing_request_hold_proof import prove_request_hold, canonical
from quiescing_receipt_proof import prove_masked_request
from reset_bridge_proof import Cone, sram_capacities


def need(value, reason):
    if not value: raise ValueError('QUIESCING_HANDOFF_CONTROL_'+reason)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def jobs(database, top, baseline):
    module=database['modules'][top];cells=module['cells'];cone=Cone(module);click=top=='ClickSoc'
    address='ca_child_core.ca_child_address';fabric='ca_child_transactions';receipt='ca_child_request_bridge'
    raw=cone.bits('systemReset')[0];native=cone.bits('ca_child_program_return.eligible')[0]
    masks=next(p for p in baseline['receiver_proofs'] if p.get('held_data_inputs'))
    result=[]
    def add(label,cell,pin,index,after,checker,expected):
        before=cells[cell]['connections'][pin][index]
        need(before!=after,'VACUOUS_'+label)
        result.append(dict(label=label,cell=cell,field='connections',pin=pin,index=index,before=before,after=after,
                           checker=checker,expected=expected))
    def parameter(label,cell,pin,after,owner=None,checker='hold',expected=None):
        before=cells[cell]['parameters'][pin];need(before!=after,'VACUOUS_'+label)
        result.append(dict(label=label,cell=cell,field='parameters',pin=pin,index=None,before=before,after=after,
                           checker=checker,expected=expected or 'RDC_QUIESCING_HOLD_OWNER_TOPOLOGY_'+owner))
    for item in masks['held_data_inputs']:
        for pin,value in [('A',raw),('S',native)]:
            add('mask-'+item['field']+'-'+pin,item['cell'],pin,0,value,'mask',
                'RDC_QUIESCING_RECEIPT_EXACT_MASK_'+item['field'])
    add('source-capture',address+'.ca_primitive_payload','trigger' if click else 'closed',0,'0','hold',
        'RDC_QUIESCING_HOLD_OWNER_TOPOLOGY_address')
    ack_cell=address+('.ca_primitive_output_compare' if click else '.ca_primitive_long_hold')
    add('source-early-receipt-ack',ack_cell,'b',0,cone.bits(receipt+'.in_ack')[0],'hold',
        'RDC_QUIESCING_HOLD_FOREIGN_OR_CLOCKED_OWNER_'+address)
    parameter('source-payload-parameter',address+'.ca_primitive_payload','DELAY_FS','1','address')
    parameter('source-hold-logic-parameter',address+('.ca_primitive_fire' if click else '.ca_primitive_long_hold'),
              'INVERT' if click else 'OP','0','address')
    reset_cell=address+'.ca_primitive_payload'
    add('source-raw-reset',reset_cell,'reset',0,raw,'audit',
        'RDC_NATIVE_RESET_OWNER_'+reset_cell)
    release_cell=fabric+('.ca_primitive_accepted_phase' if click else '.ca_primitive_completion')
    add('fabric-early-completion',release_cell,'trigger' if click else 'common',0,'1','hold',
        'RDC_QUIESCING_HOLD_OWNER_TOPOLOGY_fabric')
    parameter('fabric-controller-parameter',release_cell,'RESET_VALUE','1','fabric')
    ack=cone.bits(receipt+'.in_ack');request=cone.bits(fabric+'.serviceRequest_req')
    if click:
        candidates=[(n,p) for n,c in cells.items() if c['type']=='$eq' for p in ('A','B')]
        candidates=[(n,p) for n,p in candidates if cells[n]['connections'][p]==ack and
                    cells[n]['connections']['B' if p=='A' else 'A']==request]
    else:
        candidates=[(n,'a') for n,c in cells.items() if n.startswith(fabric+'.') and
                    n.endswith('ca_primitive_service_returned_na') and c['connections'].get('a')==ack]
    need(len(candidates)==1,'UNIQUE_ACTUAL_SERVICE_ACK_DEPENDENCY')
    add('fabric-service-ack-dependency',*candidates[0],0,'1','hold','RDC_QUIESCING_HOLD_OWNER_TOPOLOGY_fabric')
    return_cell=fabric+('.ca_primitive_service_response_phase' if click else '.ca_primitive_completion')
    if click:pin,index='trigger',0
    else:
        pin='falling';indices=[i for i,b in enumerate(cells[return_cell]['connections'][pin]) if b==ack[0]]
        need(len(indices)==1,'ACTUAL_BD_RETURN_ACK');index=indices[0]
    add('fabric-return-history',return_cell,pin,index,'0','hold','RDC_QUIESCING_HOLD_OWNER_TOPOLOGY_fabric')
    sink,cell=cone.flop('housekeepingBoundary_issued')
    for label,source,value in [('native-sidepath','native:ca_child_program_return.eligible',native),
                               ('raw-sidepath','raw-reset',raw)]:
        add(label,sink,'D',0,value,'audit-violation',dict(source=source,sink=sink,pin='D'))
    add('unexpected-raw-register-reset',sink,'ARST',0,raw,'audit',
        'RDC_HELD_DATA_RESET_'+sink)
    masked=cone.bits(receipt+'.out_bits_address')[0]
    for pin in ('CLK','ARST'):
        add('masked-periodic-'+pin,sink,pin,0,masked,'audit',
            'RDC_HELD_DATA_DESTINATION_'+sink+'_'+pin)
    add('consumer-unrelated-clock',sink,'CLK',0,cone.bits('watchdogClock')[0],'audit',
        'RDC_HELD_DATA_CLOCK_'+sink)
    parameter('consumer-falling-edge',sink,'CLK_POLARITY','0',checker='audit',
              expected='RDC_HELD_DATA_CLOCK_'+sink)
    add('consumer-nonpor-reset',sink,'ARST',0,cone.bits('watchdogClock')[0],'audit',
        'RDC_HELD_DATA_RESET_'+sink)
    model=lambda c:database['modules'].get(c['type'],{}).get('attributes',{}).get('hdlname',c['type']).split()[0]
    macro='fabric_ram_macros_0';need(model(cells[macro])==SRAM,'ACTUAL_MACRO_MODEL')
    macro_inputs={p for p,d in cells[macro]['port_directions'].items() if d=='input'}
    need(macro_inputs=={'A','CEN','CLK','D','GWEN','WEN'},'ACTUAL_MACRO_INPUTS')
    for pin in sorted(macro_inputs):
        add('masked-macro-'+pin,macro,pin,0,masked,'audit',
            'RDC_HELD_DATA_DESTINATION_'+macro+'_'+pin)
    intermediate='ca_child_housekeeping.ca_child_update.ca_primitive_payload'
    need(model(cells[intermediate])==('ChiselAsyncEventRegister_v1' if click else 'ChiselAsyncClosingLatch_v1'),
         'ACTUAL_DOWNSTREAM_NATIVE_OWNER')
    for pin in ('trigger' if click else 'closed','d'):
        add('masked-native-'+pin,intermediate,pin,0,masked,'audit',
            'RDC_HELD_DATA_DESTINATION_'+intermediate+'_'+pin)
        # Also expose this owner's Q at a generic periodic D. A pre-mask cut
        # must not launder control/data through another retained native owner.
        before=cells[sink]['connections']['D'][0];after=cells[intermediate]['connections']['q'][0]
        need(before!=after,'VACUOUS_NATIVE_Q_SIDEPATH')
        result[-1]['sidepath']=dict(cell=sink,pin='D',index=0,before=before,after=after)
    need(len(result)==33 and len({j['label'] for j in result})==33,'EXACT_33_CONTROLS')
    return result


def mutate(database, top, job):
    changed=copy.deepcopy(database);pins=changed['modules'][top]['cells'][job['cell']][job['field']]
    if job['index'] is None:
        need(pins[job['pin']]==job['before'],'CHANGED_MUTATION_TARGET');pins[job['pin']]=job['after']
    else:
        need(pins[job['pin']][job['index']]==job['before'],'CHANGED_MUTATION_TARGET')
        pins[job['pin']][job['index']]=job['after']
    if 'sidepath' in job:
        side=job['sidepath'];vector=changed['modules'][top]['cells'][side['cell']]['connections'][side['pin']]
        need(vector[side['index']]==side['before'],'CHANGED_SIDEPATH_TARGET');vector[side['index']]=side['after']
    return changed


def negative(database, top, capacities, baseline, job):
    changed=mutate(database,top,job);before=canonical(changed)
    try:
        if job['checker']=='hold':result=prove_request_hold(changed,top,capacities)
        elif job['checker']=='mask':
            control=next(p for p in baseline['receiver_proofs'] if p['prefix']=='ca_child_request_bridge' and 'first' in p)
            result=prove_masked_request(changed,top,control)
        else:result=audit_graph(changed,top,capacities)
    except ValueError as error:
        need(job['checker']!='audit-violation' and str(error)==job['expected'],'WRONG_REJECTION:'+str(error))
        outcome=dict(status='EXACT_REJECTION',diagnostic=str(error))
    else:
        need(job['checker']=='audit-violation','SURVIVED:'+job['label'])
        need(result['status']=='fail' and job['expected'] in result['violations'],'MISSING_EXACT_VIOLATION:'+job['label'])
        outcome=dict(status='EXACT_VIOLATION',violation=job['expected'],total_violations=len(result['violations']))
    need(canonical(changed)==before,'AUDIT_MUTATED_GRAPH')
    return dict(**job,**outcome,mutant_sha256=before)


def run(exports, output):
    output=Path(output).resolve();need(not output.exists(),'OUTPUT_EXISTS');output.mkdir(parents=True)
    inputs={};records=[];started=time.time()
    for path in sorted(Path(__file__).parent.glob('*.py')):
        if path.name in ('check_quiescing_handoff_controls.py','check_reset_crossings.py','quiescing_request_hold_proof.py',
                          'quiescing_receipt_proof.py','reset_bridge_proof.py','reset_coordinator_proof.py'):
            inputs[str(path.resolve())]=sha(path)
    try:
        for index,export in enumerate(exports):
            export=Path(export).resolve()
            for name in ('contract.json','sram.json','reset-crossings/netlist.json','reset-crossings/report.json'):
                path=export/name;inputs[str(path)]=sha(path)
            manifest=json.loads((export/'contract.json').read_text())['manifest'];top=manifest['top']
            need(top in ('FourPhaseSoc','ClickSoc'),'EXACT_TOP')
            database=json.loads((export/'reset-crossings/netlist.json').read_text())
            caps=sram_capacities(json.loads((export/'sram.json').read_text()),top);original=canonical(database)
            baseline=audit_graph(database,top,caps)
            need(baseline['status']=='pass' and not baseline['violations'] and len(baseline['held_data_handoffs'])==4,
                 'FULL_BASELINE_FAILED')
            case=output/str(index);case.mkdir()
            (case/'baseline.json').write_text(json.dumps(baseline,indent=2)+'\n')
            planned=jobs(database,top,baseline);outcomes=[]
            for job in planned:
                outcome=negative(database,top,caps,baseline,job);outcomes.append(outcome)
                (case/'controls.json').write_text(json.dumps(outcomes,indent=2)+'\n')
            need(canonical(database)==original,'ORIGINAL_GRAPH_CHANGED')
            records.append(dict(export=str(export),top=top,baseline_sha256=sha(case/'baseline.json'),
                controls_sha256=sha(case/'controls.json'),negative_controls=len(outcomes),baseline_discharged=len(baseline['held_data_discharged'])))
            print(top,'full baseline PASS;',len(outcomes),'exact graph negatives PASS',flush=True)
        for name,digest in inputs.items():need(sha(name)==digest,'INPUT_CHANGED:'+name)
        result=dict(status='PASS_ACTUAL_GRAPH_HANDOFF_CONTROLS',started_unix=started,ended_unix=time.time(),
            scope='Read-only graph replay only; no hardware or strict-execution qualification',inputs_sha256=inputs,cases=records)
    except BaseException as error:
        result=dict(status='FAIL',error=repr(error),inputs_sha256=inputs,cases=records)
        (output/'receipt.json').write_text(json.dumps(result,indent=2)+'\n');raise
    (output/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export',dest='exports',action='append',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();run(args.exports,args.out)

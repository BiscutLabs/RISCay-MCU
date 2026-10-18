# SPDX-License-Identifier: Apache-2.0
"""First SRAM fork composition on the actual repaired graph; never signoff.

The eliminated prepare stage's transform only projected its input. This
binds both retained Join operands, the complete native fork, and both receiving
stores. Each receiving branch is measured with the other branch already done,
so return timing cannot borrow delay from the other consumer.
"""
from collections import defaultdict
from copy import deepcopy
import argparse
import json
from pathlib import Path
import re
import subprocess

import control_join_timing as join
import control_relative_timing as relative
import native_stage_timing as stages
import native_leaf_timing as leaf
from characterize_gf180_control_native import audit_bindings
from gf180_physical import ROOT, SC, nodes, sha, write_json, pdk_verify
from physical_tools import tool
from repair_gf180_control import require
from repair_gf180_design import validate_receipt


def module_at(netlist,path):
    kind='RiscayMcuDigital'
    for name in ('soc',*path.split('.')[1:]):
        require(name in netlist['modules'][kind]['cells'],'SRAM_FUSION_INSTANCE')
        kind=netlist['modules'][kind]['cells'][name]['type']
    return kind,netlist['modules'][kind]


def projection(parent,variant):
    """Exact complete projection and both fork branches, including zero lanes."""
    names=('ca_child_owner','ca_child_lane_0_fork','ca_child_lane_0_issue','ca_child_lane_0_join')
    require(all(n in parent['cells'] for n in names) and 'ca_child_prepare' not in parent['cells'],
            'SRAM_FUSION_CHILDREN')
    owner,fork,issue,dest=[parent['cells'][n]['connections'] for n in names]
    require(owner['reset']==fork['reset']==issue['reset']==dest['reset'],'SRAM_FUSION_RESET')
    require(owner['out_req']==fork['in_req'] and owner['out_ack']==fork['in_ack'],
            'SRAM_FUSION_OWNER_HANDSHAKE')
    fields=dict(address=32,data=32,write=1,mask=4)
    require({p for p in fork if p.startswith('in_bits_')}==
            {'in_bits_request_'+f for f in fields}|{'in_bits_result'},'SRAM_FUSION_PROJECTION_FIELDS')
    for field,width in fields.items():
        require(len(owner['out_bits_right_'+field])==width and
                owner['out_bits_right_'+field]==fork['in_bits_request_'+field],
                'SRAM_FUSION_PROJECTION_LANES')
    require(fork['in_bits_result']==['0']*32,'SRAM_FUSION_RESULT_ZERO')
    # The unused credit payload may have an open parent connection after Yosys;
    # its one-bit retained storage is still checked through the source plan.
    require('out_bits_left' in owner and len(owner['out_bits_left']) in (0,1),'SRAM_FUSION_CREDIT_PORT')
    branches=('out_0','out_1') if variant=='bd' else ('left','right')
    for branch,receiver,prefix in ((branches[0],issue,'in'),(branches[1],dest,'left')):
        expected={branch+suffix for suffix in ('_req','_ack','_bits_result',
                  *('_bits_request_'+field for field in fields))}
        require({p for p in fork if p.startswith(branch+'_')}==expected,'SRAM_FUSION_BRANCH_FIELDS')
        for pin in expected:
            require(fork[pin]==receiver[prefix+pin[len(branch):]],'SRAM_FUSION_BRANCH_WIRING')
    return branches


def composition(netlist,record,manifest,path,variant,*,fork=False):
    kind,body=module_at(netlist,path)
    node=next(n for n in nodes(manifest['design']) if n['rtl_path']==path)
    family=('FourPhase' if variant=='bd' else 'Click')+('Fork' if fork else 'Join')
    require(re.fullmatch(family+r'(?:_\d+)?',kind) is not None,'SRAM_FUSION_COMPOSITION_FAMILY')
    ps={p['id']:p for p in node['primitives'] if p['view']!='constraint-marker'}
    ids=({'request0','request1','completion'} if variant=='bd' else {'left_delay','right_delay','completion'}) if fork else {'rendezvous'}
    require(set(ps)==ids,'SRAM_FUSION_COMPOSITION_PRIMITIVES')
    expected={};roots={}
    shape=dict(COMMON=2,COMMON_INVERT=0,RISING=0,RISING_INVERT=0,FALLING=0,FALLING_INVERT=0,RESET_VALUE=0,DELAY_FS=1000000)
    for name,p in ps.items():
        root=p['rtl_path'][len(path)+1:];params={k:int(v) for k,v in p['parameters'].items()}
        require('.' not in root and p['version']==1,'SRAM_FUSION_PRIMITIVE_PATH')
        if name in ('completion','rendezvous'):
            require(p['model']=='ChiselAsyncAsymmetricC_v1' and params==shape,'SRAM_FUSION_COMPLETION')
        else:
            require(p['model']=='ChiselAsyncControlGate_v1' and params==dict(OP=0,WIDTH=1,RESET_VALUE=0,DELAY_FS=1000000),
                    'SRAM_FUSION_REQUEST_BUFFER')
        expected[root]=(p['model'],params);roots[name]=root
    audit_bindings(netlist,record,dict(module=kind,variant=variant,aliases=[],verify_roots=list(expected),
        expected_bindings=expected,physical_prefix='soc/'+'/'.join(path.split('.')[1:])+'/'))
    ports={p:v['bits'] for p,v in body['ports'].items()}
    if fork:
        branches=('out_0','out_1') if variant=='bd' else ('left','right')
        require(set(body['cells'])==set(roots.values()),'SRAM_FUSION_FORK_CHILDREN')
        for branch,name in zip(branches,('request0','request1') if variant=='bd' else ('left_delay','right_delay')):
            c=body['cells'][roots[name]]['connections']
            require(c==dict(a=ports['in_req'],b=['0'],q=ports[branch+'_req'],reset=ports['reset']),
                    'SRAM_FUSION_FORK_REQUEST')
            for pin,bits in ports.items():
                if pin.startswith('in_bits'):
                    require(ports[branch+pin[2:]]==bits,'SRAM_FUSION_FORK_COPY')
        c=body['cells'][roots['completion']]['connections']
        require(c==dict(common=[ports[p+'_ack'][0] for p in branches],falling=['0'],rising=['1'],
                        reset=ports['reset'],q=ports['in_ack']),'SRAM_FUSION_FORK_COMPLETION')
    else:
        children={s:'ca_child_'+s+('_storage' if variant=='click' else '') for s in ('left','right')}
        require(set(body['cells'])==set(children.values())|set(roots.values()),'SRAM_FUSION_JOIN_CHILDREN')
        c=body['cells'][roots['rendezvous']]['connections']
        require(c==dict(common=[body['cells'][children[s]]['connections']['out_req'][0] for s in ('left','right')],
            falling=['0'],rising=['1'],reset=ports['reset'],q=ports['out_req']),'SRAM_FUSION_JOIN_RENDEZVOUS')
        for side,child in children.items():
            for pin,bits in body['cells'][child]['connections'].items():
                outer=(side+pin[2:] if pin.startswith('in_') else 'out_bits_'+side+pin[8:] if pin.startswith('out_bits') else
                       'out_ack' if pin=='out_ack' else 'reset' if pin=='reset' else None)
                if outer is not None:require(bits==ports[outer],'SRAM_FUSION_JOIN_WIRING')
    return roots


def bind(netlist,record,manifest,variant,owner,branch,index,cuts):
    require(owner in ('ram','program') and branch in ('issue','store'),'SRAM_FUSION_TARGET')
    path=manifest['top']+'.ca_child_'+owner+'_access.ca_child_native'
    _,parent=module_at(netlist,path);branches=projection(parent,variant)
    source_path=path+'.ca_child_owner';fork_path=path+'.ca_child_lane_0_fork'
    sr=composition(netlist,record,manifest,source_path,variant)
    fr=composition(netlist,record,manifest,fork_path,variant,fork=True)
    composition(netlist,record,manifest,path+'.ca_child_lane_0_join',variant)
    suffix='_storage' if variant=='click' else ''
    stage_paths=dict(left=source_path+'.ca_child_left'+suffix,right=source_path+'.ca_child_right'+suffix,
        update=path+('.ca_child_lane_0_issue' if branch=='issue' else '.ca_child_lane_0_join.ca_child_left'+suffix))
    plans={}
    for name,p in stage_paths.items():
        desc=stages.descriptor(manifest,netlist,record,p,variant,storage=name!='update' or branch=='store')
        plans[name]=relative.make_plan(netlist,record,variant,desc)
        plans[name]['prefix']='soc/'+'/'.join(p.split('.')[1:])+'/'
        if name!='update' or branch=='store':join.identity_storage(netlist['modules'][desc['module']])
        # The projection's zero result is constant only in this parent. Bind
        # each exact physical D lane, never a local port name or global zero bus.
        for lane in plans[name]['lane_map']:
            cell,pin=(plans[name]['prefix']+lane['D']).rsplit('/',1)
            bits=index.before['cells'][cell]['connections'][pin]
            require(len(bits)==1,'SRAM_FUSION_CAPTURE_LANE')
            if bits[0][0]=='constant':
                require(bits[0][1] in ('0','1'),'SRAM_FUSION_CAPTURE_UNKNOWN')
                plans[name]['constant_lanes'][str(lane['lane'])]=int(bits[0][1])
    prefix='soc/'+'/'.join(path.split('.')[1:])+'/'
    plan=dict(variant=variant,module='RiscayMcuDigital',stages=plans,owner=owner,branch=branch,
        parent_instance=path,rendezvous=prefix+'ca_child_owner/'+sr['rendezvous']+'/',
        fork=prefix+'ca_child_lane_0_fork/',fork_request=fr['request0' if branch=='issue' else 'request1'] if variant=='bd' else fr['left_delay' if branch=='issue' else 'right_delay'],
        fork_completion=fr['completion'],leaf_anchored=True,keeper_cuts=cuts,
        wire_rc_scope='zero; receiver wire delay unmeasured',acknowledge_guard=None)
    cells=[dict(path=p,cell=c['type'],pins={k:v[0] for k,v in c['connections'].items()},directions=c['directions'])
           for p,c in index.after['cells'].items() if all(len(v)==1 for v in c['connections'].values())]
    contexts=join.contexts(plan,cells)
    # The credit token has no downstream data lanes. Its request still traverses
    # the rendezvous and both fork branches; Click also needs its phase launch.
    contexts=[c for c in contexts if c['queries']]
    drivers=defaultdict(list)
    for p,c in index.after['cells'].items():
        for pin,bs in c['connections'].items():
            if c['directions'][pin]=='output':
                for bit in bs:drivers[bit].append(p+'/'+pin)
    dest=plans['update']['prefix'][:-1]
    signals={p:index.scalar(dest,s) for p,s in (('reset','reset'),('update_out_ack','out_ack'))}
    other=branches[1 if branch=='issue' else 0]
    completion=plan['fork']+plan['fork_completion']+'/'
    keeper=[c['path'] for c in cells if c['path'].startswith(completion) and c['cell']==SC+'aoi21_1']
    require(len(keeper)==1,'SRAM_FUSION_COMPLETION_KEEPER')
    other_rows=index.boundary(plan['fork'][:-1],other+'_ack')
    require(len(other_rows)==1 and other_rows[0]['kind']=='pin' and other_rows[0]['consumers'] and
            all(p.startswith(completion) for p in other_rows[0]['consumers']),'SRAM_FUSION_OTHER_ACK')
    for ctx in contexts:
        phase=ctx['phase'];src=plans[ctx['side']];source=src['prefix'][:-1]
        state=ctx['state']
        state['cases']=[(*signals[p],v) if k=='port' else (k,p,v) for k,p,v in state['cases']]
        state['cases'] += [('pin',keeper[0]+'/A1',phase)]
        state['cases'] += [('pin',p,1-phase) for p in other_rows[0]['consumers']]
        state['keeper_cuts']=cuts
        if ctx['kind']=='input':
            ports=sorted({re.sub(r'\[\d+\]$','',p) for p in next(c for c in src['contexts'] if c['id']=='data')['sources']})
            rows=[row for p in ports for row in index.boundary(source,p)]
            require(all(r['kind']=='pin' for r in rows),'SRAM_FUSION_INPUT_SOURCE')
            ctx['sources']=sorted({r['source'] for r in rows})
        elif ctx['kind']=='request':
            kind,pin=index.scalar(source,'in_req');require(kind=='pin','SRAM_FUSION_REQUEST_SOURCE');ctx['sources']=[pin]
        ctx['source_kind']='clock'
        qs=[]
        for q in ctx['queries']:
            if q['role']!='return':qs.append(q);continue
            rows=index.boundary(source,'out_ack');require(len(rows)==1,'SRAM_FUSION_RETURN')
            conditioned={p for k,p,v in state['cases'] if k=='pin'}
            for i,p in enumerate(rows[0]['consumers']):
                require(p in conditioned,'SRAM_FUSION_RETURN_CONDITION')
                actual=drivers[index.live_net('pin',p)];require(len(actual)==1,'SRAM_FUSION_RETURN_DRIVER')
                qs.append(dict(q,id=q['id'].replace('return:',f'return:{i}:'),sink=actual[0],sink_kind='pin',receiver=p))
        ctx['queries']=qs
    plan['contexts']=contexts
    return plan


def source_margins(results,plan,aperture):
    """Use real right-operand launch; credit has ordering but no payload cone."""
    rows=[];src=plan['stages']['right'];inp=results['right-input']
    for phase in ([0] if plan['variant']=='bd' else [0,1]):
        request=results[f'right-request-{phase}'];launch=results[f'right-launch-{phase}']
        req=request['rows'];data=launch['rows'];edge='fall' if plan['variant']=='bd' else 'rise'
        if plan['variant']=='bd':
            for i,lane in enumerate(src['lane_map']):
                measured=[inp['dq'][str(lane['lane'])][e]['slew_ns'] for e in ('rise','fall')]
                require(all(abs(a-b)<1e-6 for a,b in zip(launch['source_slews'][str(i)],measured)),'SRAM_FUSION_DQ_SLEW')
            latest=max(v['delay_ns'] for k,v in req.items() if k.startswith('source_capture:') and ':max:' in k)
            captures=req
        else:
            require(all(abs(a-b)<1e-5 for a,b in zip(launch['event_slews'],request['event_slews'])),'SRAM_FUSION_EVENT_SLEW')
            latest=0;captures=data
        leads=[]
        for lane in src['lane_map']:
            n=lane['lane'];close=req[f'source_capture:{n}:min:{edge}']['delay_ns']
            for e in ('rise','fall'):
                arrival=inp['rows'][f'input:{n}:max:{e}']['delay_ns']
                leads.append(close-arrival-aperture['setup_ns'])
                if plan['variant']=='bd':leads.append(close-arrival-inp['dq'][str(n)][e]['delay_ns'])
        slacks=[captures[f"capture:{q['lane']}:min:{edge}"]['delay_ns']-latest-data[q['id']]['delay_ns']-aperture['setup_ns']
            for q in next(c for c in plan['contexts'] if c['id']==f'right-launch-{phase}')['queries'] if q['role']=='data']
        require(slacks,'SRAM_FUSION_NO_DATA_MEASUREMENTS')
        return_min=min(v['delay_ns'] for k,v in req.items() if k.startswith('return:') and k.endswith(':min')) if plan['variant']=='bd' else None
        capture_max=max(v['delay_ns'] for k,v in captures.items() if k.startswith('capture:') and ':max:' in k)
        rows.append(dict(side='right',phase=phase,maximum_input_data_lag_ns=min(leads),
            minimum_conditional_setup_margin_ns=min(slacks),source_q_bound_ns=latest,
            return_after_source_close_ns=return_min-latest if return_min is not None else None,
            return_after_latest_capture_hold_ns=return_min-capture_max-aperture['hold_ns'] if return_min is not None else None,
            checked_data_transitions=len(slacks),physical_qualification=False))
    return rows


def return_ordering(results,plan,aperture):
    """Both source arrival orders; no contamination or reopening credit."""
    if plan['variant']!='bd':return []
    result=[]
    for side in ('left','right'):
        rows=results[side+'-request-0']['rows']
        ack=min(v['delay_ns'] for k,v in rows.items() if k.startswith('return:') and k.endswith(':min'))
        capture=max(v['delay_ns'] for k,v in rows.items() if k.startswith('capture:') and ':max:' in k)
        result.append(dict(last_operand=side,earliest_return_ns=ack,latest_capture_ns=capture,
            zero_contamination_hold_margin_ns=ack-capture-aperture['hold_ns']))
    return result


def run(mapping,output,variant,owner,branch,campaign=False):
    require(not output.exists(),'SRAM_FUSION_OUTPUT_EXISTS')
    receipt=validate_receipt(mapping)
    record=json.loads((mapping/'mapping.json').read_text());live=json.loads((mapping/'netlist.json').read_text())
    audit=json.loads((mapping/'netlist-audit.json').read_text());policy=json.loads((mapping/'physical-policy.json').read_text())
    require(record['variant']==variant and audit['status']=='pass' and audit['netlist_sha256']==sha(mapping/'netlist.v') and
        audit['mapping_sha256']==sha(mapping/'mapping.json'),'SRAM_FUSION_STALE_AUDIT')
    require(record['physical_policy_sha256']==sha(mapping/'physical-policy.json') and policy['contract_sha256']==sha(mapping/'timing-intent.json'),
        'SRAM_FUSION_STALE_CONTRACT')
    manifest=json.loads((mapping/'timing-intent.json').read_text())['manifest']
    original=stages.receipt_original(mapping,receipt);proof=stages.receipt_proof(mapping,receipt)
    index=leaf.LeafIndex(original,live,proof['added_buffers'],proof['added_ties'])
    plan=bind(original,record,manifest,variant,owner,branch,index,leaf.keeper_cuts(index,audit))
    sta=tool('sta');yosys=tool('yosys');pdk=ROOT/'.tools/physical/pdk';pdk_verify(pdk)
    files=[mapping/f for f in ('mapping.json','netlist.json','netlist.v','netlist-audit.json','timing-intent.json','physical-policy.json')]
    files += [mapping/'electrical-repair/receipt.json',mapping/'electrical-repair/reference/netlist.json',mapping/'electrical-repair/proof.json']
    files += [Path(m.__file__) for m in (join,relative,stages,leaf)]+[Path(__file__),relative.PROBE]+sta.input_files()+yosys.input_files()
    files += [ROOT/'tools'/f for f in ('repair_gf180_design.py','characterize_gf180_control_native.py',
        'screen_gf180_control_repair.py','repair_gf180_control.py','physical_tools.py',
        'gf180_physical.py','gf180_implement.py','gf180_estimate.py','characterize_gf180_liberty.py')]
    files += [pdk/(SC+c+'.lib') for c in relative.CORNERS]+[ROOT/'.tools/gf180-sram'/(leaf.SRAM+'__tt_025C_3v30.lib')]
    frozen={str(p.resolve()):sha(p) for p in files}
    output.mkdir(parents=True);stages.roundtrip(mapping,output,live,yosys,pdk)
    write_json(output/'plan.json',plan);cases=[]
    for corner in (relative.CORNERS if campaign else relative.CORNERS[:1]):
        aperture=relative.aperture(relative.library(pdk/(SC+corner+'.lib')),variant)
        for slew in ([0.02,2.] if campaign else [0.2]):
            key=corner+'-s'+str(slew);results={};failure=None
            for ctx in plan['contexts']:
                tcl=output/(key+'-'+ctx['id']+'.tcl');log=tcl.with_suffix('.log')
                dq=results[ctx['side']+'-input']['dq'] if ctx['kind']=='launch' and variant=='bd' else None
                if ctx['kind']=='launch' and variant=='click':
                    a,b=results[f"{ctx['side']}-request-{ctx['phase']}"]['event_slews'];ctx['root_slew_ns']=dict(min=a,max=b)
                tcl.write_text(join.script(mapping/'netlist.v',corner,slew,plan,ctx,sta=sta,dq=dq),newline='\n')
                with log.open('w') as stream:
                    subprocess.run(sta.command(['-no_init','-exit',sta.path(tcl)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
                try:
                    result=join.parse(log.read_text(),plan,ctx,cells=index.after['cells'])
                    for q in ctx['queries']:
                        if q['role'] in ('capture','return'):
                            points=result['paths'][q['id']]
                            require(any(p.startswith(plan['fork']+plan['fork_request']+'/') for p in points),'SRAM_FUSION_FORK_REQUEST_PROVENANCE')
                            if q['role']=='return':require(any(p.startswith(plan['fork']+plan['fork_completion']+'/') for p in points),'SRAM_FUSION_FORK_RETURN_PROVENANCE')
                    results[ctx['id']]=result
                except ValueError as error:failure=dict(context=ctx['id'],diagnostic=str(error));break
            summary=None if failure else source_margins(results,plan,aperture)
            ordering=None if failure else return_ordering(results,plan,aperture)
            fields=('maximum_input_data_lag_ns','minimum_conditional_setup_margin_ns','return_after_source_close_ns','return_after_latest_capture_hold_ns')
            negative=[] if failure else [dict(phase=row['phase'],metric=k) for row in summary for k in fields if row[k] is not None and row[k]<0]
            if ordering:negative += [dict(last_operand=row['last_operand'],metric='zero_contamination_hold_margin_ns') for row in ordering if row['zero_contamination_hold_margin_ns']<0]
            case=dict(key=key,corner=corner,slew_ns=slew,status='UNRESOLVED' if failure else 'CONDITIONAL_SETUP_MEASUREMENTS',
                negative_metrics=negative,failure=failure,summary=summary,return_ordering=ordering)
            write_json(output/(key+'.json'),dict(case=case,results=results,aperture=aperture));cases.append(case);print(json.dumps(case),flush=True)
    require(all(sha(Path(p))==h for p,h in frozen.items()),'SRAM_FUSION_INPUT_CHANGED')
    validate_receipt(mapping)
    write_json(output/'results.json',dict(physical_qualification=False,owner=owner,branch=branch,cases=cases,
        scope='Conditional right-operand setup and native fork return; complete source-reuse/return-to-zero and extracted RC remain separate obligations.',
        inputs_sha256=frozen,files_sha256={p.name:sha(p) for p in output.iterdir() if p.is_file()}))
    require(all(c['status']!='UNRESOLVED' for c in cases),'SRAM_FUSION_UNRESOLVED')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mapping',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--variant',choices=('bd','click'),required=True)
    p.add_argument('--owner',choices=('ram','program'),required=True)
    p.add_argument('--branch',choices=('issue','store'),required=True);p.add_argument('--campaign',action='store_true')
    a=p.parse_args();run(a.mapping,a.output,a.variant,a.owner,a.branch,a.campaign)

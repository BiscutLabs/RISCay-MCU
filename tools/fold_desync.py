# SPDX-License-Identifier: Apache-2.0
"""Check bank storage shape, then prove next-state logic at ideal bank cycles.

This abstraction folds a closed master/slave transfer into the original clock
event. It does not prove that physical controllers produce those events safely.
All generated D logic remains in the proof; no payload output is excluded.
"""
from copy import deepcopy
import argparse
import json
from pathlib import Path
from gf180_physical import ROOT, write_json
from physical_tools import tool
from primitives import resolve_candidate
from run_receipt import RunReceipt


def fold(reference, generated, transform, control=None, *, policy):
    result=deepcopy(generated);top=result['modules']['RiscayMcuDigital'];gold=reference['modules']['RiscayMcuDigital']
    cells=top['cells'];state=transform['state']
    def require(ok,why):
        if not ok:raise ValueError('DESYNC_FOLD_'+why)
    if control:
        expected=set()
        # Regenerate the graph from the independently partitioned reference;
        # aliases and a binding changed together must not erase a wiring fault.
        from desync_transform import storage_scaffold
        from desync_assemble import assemble
        expected_storage,expected_transform=storage_scaffold(reference,policy)
        expected_net,expected_control=assemble(expected_storage,expected_transform,timing_preparation=True)
        require(control==expected_control,'CONTROL_BINDING')
        expected_top=expected_net['modules']['RiscayMcuDigital']
        for binding in control['bindings']:
            prefix=binding['instance']+'/'
            recipe=resolve_candidate(binding['primitive'],binding.get('parameters'))
            for leaf in recipe['cells']:
                name=prefix+leaf['name'];expected.add(name);actual=cells[name]
                pins={p:([n] if n in ('0','1') else top['netnames'][prefix+n]['bits']) for p,n in leaf['pins'].items()}
                require(actual['type']==leaf['cell'] and actual['connections']==pins,'CONTROL_RECIPE')
                require(actual==expected_top['cells'][name],'CONTROL_NETWORK')
        require(expected=={n for n in cells if n.startswith('desync_control/')},'CONTROL_SET')
        for n in expected:del cells[n]
    seen=set()
    for row in state:
        name=row['path'];original=gold['cells'][name];seen.add(name)
        require(original['type']==row['original_type'] and original['connections']==row['original_connections']
                and original['parameters']==row['original_parameters'],'ORIGINAL_STATE')
        if row['kind']=='retained':
            require(cells[name]==original,'RETAINED_STATE');continue
        bank=row['bank'];domain=row['domain']
        def enable(phase,gated):
            alias='desync/'+bank+'/'+phase+'/gate_'+domain+'_q' if gated else 'desync_'+bank+'_'+phase
            require(alias in top['netnames'],'ENABLE_ALIAS')
            if gated:
                gate=cells[alias.removesuffix('_q')]
                qualifier=policy['falling_gate_conditions' if row['falling'] else 'gated_domains'][domain]
                require(gate['type']=='$and' and gate['connections']==dict(
                    A=top['netnames']['desync_'+bank+'_'+phase]['bits'],
                    B=gold['netnames'][qualifier]['bits'],Y=top['netnames'][alias]['bits']),'GATE_CONDITION')
            return top['netnames'][alias]['bits']
        gated=domain in policy['gated_domains']
        if row['kind']=='flop-exception':
            actual=cells[name];ports=deepcopy(actual['connections']);params=deepcopy(actual['parameters'])
            require(ports['CLK']==enable('capture',gated),'FLOP_ENABLE')
            ports['CLK']=original['connections']['CLK'];params['CLK_POLARITY']=original['parameters']['CLK_POLARITY']
            require(actual['type']==original['type'] and ports==original['connections'] and params==original['parameters'],'FLOP_STATE')
            actual['connections']=ports;actual['parameters']=params;continue
        require(row['kind']=='latch-pair' and len(row['storage'])==2,'STORAGE_KIND')
        master,slave=[cells[n] for n in row['storage']]
        mphase,sphase=('s','m') if row['falling'] else ('m','s')
        require(master['type']==('$adlatch' if row['master_reset'] else '$dlatch') and
                slave['type']==('$adlatch' if 'ARST' in original['connections'] else '$dlatch'),'LATCH_KIND')
        require(master['connections']['Q']==slave['connections']['D'] and slave['connections']['Q']==original['connections']['Q'],'PAIR_WIRING')
        require(master['connections']['EN']==enable(mphase,False) and slave['connections']['EN']==enable(sphase,gated),'PAIR_ENABLE')
        for latch in (master,slave):
            require(int(latch['parameters']['EN_POLARITY'],2)==1 and int(latch['parameters']['WIDTH'],2)==row['bits'],'LATCH_PARAMETERS')
            require(set(latch['connections'])==({'D','Q','EN','ARST'} if latch['type']=='$adlatch' else {'D','Q','EN'}),'LATCH_PORTS')
            if latch['type']=='$adlatch':
                require(latch['connections']['ARST']==original['connections']['ARST'] and
                        all(latch['parameters'][p]==original['parameters'][p] for p in ('ARST_POLARITY','ARST_VALUE')),'ASYNC_RESET')
        ports=dict(D=master['connections']['D'],Q=slave['connections']['Q'],CLK=original['connections']['CLK'])
        params={p:original['parameters'][p] for p in ('WIDTH','CLK_POLARITY')}
        kind='$dff'
        if 'ARST' in original['connections']:
            kind='$adff';ports['ARST']=original['connections']['ARST']
            params.update({p:original['parameters'][p] for p in ('ARST_POLARITY','ARST_VALUE')})
        for n in row['storage']:del cells[n]
        cells[name]=dict(type=kind,parameters=params,attributes={},connections=ports,
                         port_directions={p:'output' if p=='Q' else 'input' for p in ports})
    registers={n for n,c in gold['cells'].items() if c['type'].startswith(('$dff','$adff','$sdff'))}
    require(seen==registers,'STATE_INVENTORY')
    # Clock gating and SRAM capture wiring are separately validated from the
    # transform. Restore only macro CLK at the abstract original clock event.
    for row in transform['partition']['macros']:
        name=row['path'];actual=cells[name];original=gold['cells'][name]
        alias='desync/'+row['bank']+'/s/gate_'+row['domain']+'_q' if row['domain'] in policy['gated_domains'] else 'desync_'+row['bank']+'_s'
        require(actual['connections']['CLK']==top['netnames'][alias]['bits'],'MACRO_CLOCK')
        actual['connections']['CLK']=original['connections']['CLK']
        require(actual==original,'MACRO_STATE')
    for n,p in gold['ports'].items():require(top['ports'][n]==p,'FUNCTIONAL_PORT')
    require(set(top['ports'])-set(gold['ports'])<=set(transform['controller_ports'])|
            {'desync_delay_'+b+'_'+d for b in transform['partition']['banks'] for d in ('in','out')},'ADDED_PORT')
    top['ports']=deepcopy(gold['ports'])
    return result


def run(mapping,out,policy_path):
    out.mkdir(parents=True,exist_ok=False);y=tool('yosys')
    inputs=[mapping/n for n in ('normalized.json','input.json','transform.json')]
    cp=mapping/'control.json'
    if cp.exists():inputs.append(cp)
    receipt=RunReceipt(out/'receipt.json',inputs=[*inputs,policy_path],tools=[Path(__file__),ROOT/'tools/primitives.py',
        ROOT/'tools/desync_assemble.py',ROOT/'tools/desync_transform.py',ROOT/'tools/desync_network.py',*y.input_files()])
    try:
        data=[json.loads(p.read_text(encoding='utf-8')) for p in inputs]
        folded=fold(*data,policy=json.loads(policy_path.read_text(encoding='utf-8')));write_json(out/'folded.json',folded)
        gold=deepcopy(data[0]);g=gold['modules']['RiscayMcuDigital'];f=folded['modules']['RiscayMcuDigital']
        qbits=sorted({b for row in data[2]['state'] for b in g['cells'][row['path']]['connections']['Q']})
        # Ownership aliases can be narrower than a register after wreduce;
        # the actual reference Q pins, not aliases, define proof coverage.
        if len(qbits)!=sum(row['bits'] for row in data[2]['state']):raise ValueError('DESYNC_FOLD_Q_COVERAGE')
        observed=list(qbits);macro_inputs=[]
        for row in data[2]['partition']['macros']:
            n=row['path'];c=g['cells'][n]
            for p,bs in sorted(c['connections'].items()):
                if c['port_directions'][p]=='input':
                    if f['cells'][n]['connections'][p]!=bs:raise ValueError('DESYNC_FOLD_MACRO_OBSERVER')
                    observed+=bs;macro_inputs.append(dict(instance=n,pin=p,bits=len(bs)))
        for body in (g,f):
            if 'desyncProofStateAndEffects' in body['ports']:raise ValueError('DESYNC_FOLD_OBSERVER_COLLISION')
            body['ports']['desyncProofStateAndEffects']=dict(direction='output',bits=observed)
        write_json(out/'gold.json',gold);write_json(out/'folded.json',folded)
        write_json(out/'coverage.json',dict(architectural_q_bits=len(qbits),macro_inputs=macro_inputs,
            required_observer_bits=len(observed),scope='Ideal-cycle state and memory effects; no physical flow or reset-release proof'))
        q=lambda p:'"'+y.path(p)+'"'
        commands=[]
        for name,path in (('gold',out/'gold.json'),('gate',out/'folded.json')):
            # Canonicalize both sides' CE/SRST to their next-state muxes before
            # edge sampling. Otherwise equiv_make pairs implementation-local
            # sampled-D helpers with different CE placement.
            commands += ['read_json '+q(path),'hierarchy -top RiscayMcuDigital','memory_map','opt -full','dffunmap','opt_clean',
                         'rename -hide w:* t:$*','clk2fflogic','opt_clean',
                         'rename RiscayMcuDigital '+name,'design -stash '+name]
        commands += ['design -copy-from gold =A:blackbox','design -copy-from gold -as gold gold','design -copy-from gate -as gate gate',
                     'equiv_make gold gate equiv','hierarchy -top equiv','opt_merge','equiv_struct -fwd','equiv_simple',
                     'equiv_induct -seq 8','equiv_status -assert']
        script=out/'fold.ys';script.write_text('\n'.join(commands)+'\n',encoding='utf-8')
        if receipt.command(y.command(['-s',y.path(script)],timeout=1200),cwd=ROOT,log=out/'fold.log'):
            raise ValueError('DESYNC_FOLD_EQUIVALENCE')
        text=(out/'fold.log').read_text(encoding='utf-8')
        if 'Equivalence successfully proven!' not in text:raise ValueError('DESYNC_FOLD_PROOF_MISSING')
    except BaseException:
        receipt.finish(outputs=[p for p in out.iterdir() if p.is_file() and p.name!='receipt.json'],status='fail');raise
    receipt.finish(outputs=[p for p in out.iterdir() if p.is_file() and p.name!='receipt.json'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mapping',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--policy',type=Path,default=ROOT/'physical/desync/bank-map.json')
    a=p.parse_args();run(a.mapping.resolve(),a.output.resolve(),a.policy.resolve())

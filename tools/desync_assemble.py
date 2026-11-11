# SPDX-License-Identifier: Apache-2.0
"""Assemble registered controller candidates around generic generated storage.

Timing-preparation mode leaves exactly one joined-request delay aperture per
bank. It is not executable chip evidence or a complete area-budget comparison.
Every instantiated control cell is taken from the one primitive registry.
"""
from copy import deepcopy
from desync_network import connections
from primitives import resolve_candidate


def assemble(storage, transform, *, timing_preparation=False):
    if not timing_preparation:
        raise ValueError('DESYNC_MEASURED_BANK_DELAYS_REQUIRED')
    result=deepcopy(storage); top=result['modules']['RiscayMcuDigital']
    if transform['status']!='storage-scaffold-only':raise ValueError('DESYNC_STORAGE_INPUT_REQUIRED')
    plan=connections(transform['partition']);bindings=[]
    next_bit=max(b for w in top['netnames'].values() for b in w['bits'] if isinstance(b,int))+1
    nets={}; joins=0
    def net(name):
        nonlocal next_bit
        if name in ('0','1'):return [name]
        if name not in nets:
            nets[name]=[next_bit];next_bit+=1
            top['netnames']['desync_control/'+name]=dict(hide_name=0,bits=nets[name],attributes={})
        return nets[name]
    nets['reset']=top['netnames']['resetHold/unsafe_supply']['bits']
    nets['run']=top['ports']['serviceClockEnable']['bits']
    # Bind outputs to the generated storage enable roots. Delete the
    # external controls: only the LF and pin-event clock inputs remain.
    for bank in transform['partition']['banks']:
        for phase in ('capture',) if bank=='cpu' else ('m','s'):
            name='desync_'+bank+'_'+phase
            signal='cpu.m.A' if bank=='cpu' else bank+'.'+phase+'.N'
            nets[signal]=top['ports'].pop(name)['bits']
    # Ordinary synthesis removes the old, now-unused work-clock AND cone.
    # Keep its source port until that cleanup; a mapped sink audit must find
    # no remaining fanout before the retired port can be removed.
    def instantiate(name,primitive,ports,parameters=None):
        recipe=resolve_candidate(primitive,parameters)
        if set(ports)!=set(recipe['ports']):raise ValueError('DESYNC_ASSEMBLY_PORTS:'+name)
        prefix='desync_control/'+name
        local={n:net(v) for n,v in ports.items()}
        for c in recipe['cells']:
            for n in c['pins'].values():
                if n not in local:local[n]=net(n if n in ('0','1') else name+'/'+n)
        for n,bits in local.items():
            top['netnames'][prefix+'/'+n]=dict(hide_name=0,bits=bits,attributes={})
        for c in recipe['cells']:
            directions={p:('output' if p in ('Z','ZN','G0','G1') else 'input') for p in c['pins']}
            top['cells'][prefix+'/'+c['name']]=dict(hide_name=0,type=c['cell'],parameters={},
                attributes={'keep':'1','dont_touch':'1'},port_directions=directions,
                connections={p:local[n] for p,n in c['pins'].items()})
        bindings.append(dict(instance=prefix,primitive=primitive,parameters=parameters or {},
                             ports=ports,cells=recipe['cells']))
    def join(name,inputs,initial):
        nonlocal joins
        if not inputs:raise ValueError('DESYNC_EMPTY_JOIN')
        current=list(inputs);level=0
        while len(current)>1:
            following=[]
            for index in range(0,len(current),2):
                if index+1==len(current):following.append(current[index]);continue
                tag=name+'/'+str(level)+'_'+str(index//2);out=tag+'/Q'
                instantiate(tag,'RiscayDesyncJoin',dict(reset='reset',input0=current[index],input1=current[index+1],out=out),
                            dict(initial_open=bool(initial)))
                following.append(out);joins+=1
            current=following;level+=1
        return current[0]
    downstream=join('cpu.downstream',plan['cpu.s']['ack'],0)
    delays=[]
    for label,row in plan.items():
        request=join(label+'.R',row['request'],0)
        ack=(join('cpu.publication',[downstream,'cpu.m.A'],0) if label=='cpu.s' else
             join(label+'.O',row['ack'],int(label.endswith('.m'))))
        bank,phase=label.split('.')
        master_phase='s' if transform['partition']['bank_phases'][bank]=='fall' else 'm'
        if phase==master_phase:
            delayed=label+'.delayed'
            for direction,signal,suffix in (('output',request,'in'),('input',delayed,'out')):
                top['ports']['desync_delay_'+bank+'_'+suffix]=dict(direction=direction,bits=net(signal))
            delays.append(dict(bank=bank,source=request,target=delayed,kind='relative',status='unmeasured-aperture'))
            request=delayed
        if label=='power.m':
            instantiate('stop','RiscayDesyncStop',dict(reset='reset',run='run',pauseRequest='stopPending',pauseGrant='grant1'))
            instantiate('mutex','RiscayDesyncMutex',dict(reset='reset',request0=request,request1='stopPending',grant0='grant0',grant1='grant1'))
            request='grant0'
        if label=='cpu.m':
            instantiate('cpu.capture','RiscayDesyncCaptureJoin',dict(reset='reset',request=request,downstream=downstream,rearmed='cpu.s.B',out='cpu.captureReady'))
            request='cpu.captureReady'
        ports=dict(reset='reset',requestIn=request,acknowledgeIn=ack,
                   requestOut=label+'.B',acknowledgeOut=label+'.A',enable=label+'.N')
        ports.update({'same'+str(i):v for i,v in enumerate(row['same'])})
        ports.update({'closed'+str(i):v for i,v in enumerate(row['closed'])})
        if len(row['rise'])>1:raise ValueError('DESYNC_CPU_RISE_QUALIFIERS')
        if row['rise']:ports['riseAllowed']=row['rise'][0]
        instantiate(label,'RiscayDesyncQualifiedController',ports,dict(initial_open=label.endswith('.m'),
            same_count=len(row['same']),closed_count=len(row['closed']),rise_qualified=bool(row['rise'])))
    # Leaf cell remains a black box with the experimental layout's pin names.
    result['modules']['ca_mutex_gf180_candidate']=dict(attributes={'blackbox':'1'},cells={},netnames={},
        ports={p:dict(direction='output' if p.startswith('G') else 'input',bits=[i+2])
               for i,p in enumerate(('RESET','R0','R1','G0','G1'))})
    report=dict(status='controller-connected-timing-preparation',bindings=bindings,delays=delays,
        joins=joins,controller_roots={b:{p:net(b+'.'+p+'.N') for p in 'ms'} for b in transform['partition']['banks']},
        storage_roots={b:({'capture':net('cpu.m.A')} if b=='cpu' else
                         {p:net(b+'.'+p+'.N') for p in 'ms'}) for b in transform['partition']['banks']},
        storage_root_scope='Before existing per-register work-enable gating',
        physical_qualification=False,complete_chip_area=False)
    report['protection']=dict(status='required-after-mapping')
    return result,report

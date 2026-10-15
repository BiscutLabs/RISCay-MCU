# SPDX-License-Identifier: Apache-2.0
"""Exact retained CPU request source, masked receipt and probe obligations.

No derived endpoint may be forced. Control/close/rebase/RDC equations are proved
independently on the flattened graph; these checks add packing and execution
evidence without removing generic mapping campaigns or polarity coverage.
"""
import re

FIELDS={'mask':(0,4),'data':(4,32),'address':(36,32),'operation':(68,2)}
REGISTERS=dict(localReset_release_0=1,localReset_release_1=1,stopped=1,rebased_REG=1,
               request_first=1,request=1,state=2,acknowledge=1)

def require(value,reason):
    if not value: raise ValueError('QUIESCING_REQUEST_'+reason)

def child(node,identity):
    found=[c['contract'] for c in node.get('children',[]) if c.get('id')==identity]
    require(len(found)==1,'OWNER_'+identity)
    return found[0]

def port(name,width,direction):
    return dict(name=name,width=width,direction=direction)

def request_channel(node,identity,signal,role,protocol):
    channels=[c for c in node.get('channels',[]) if c.get('id')==identity]
    require(len(channels)==1,'CHANNEL_'+identity)
    channel=channels[0]
    require(channel.get('protocol')==protocol and channel.get('role')==role and
        channel.get('reset_domain')=='root','CHANNEL_CONTRACT_'+identity)
    declared=channel.get('layout',[])
    expected=[dict(field='bits.'+field,lsb=offset,width=width,signed=False,
        source=f"~|{node['module']}>{signal}.bits.{field}") for field,(offset,width) in FIELDS.items()]
    require(declared==expected and all(type(f.get('lsb')) is int and type(f.get('width')) is int and
        f.get('signed') is False for f in declared),'LAYOUT_'+identity)
    endpoints=[e for e in node.get('endpoints',[]) if e.get('id')==channel.get('data')]
    require(len(endpoints)==1 and endpoints[0].get('width')==70 and
        endpoints[0].get('source')==f"~|{node['module']}>{signal}.bits" and
        type(endpoints[0].get('width')) is int,'DATA_ENDPOINT_'+identity)
    signals=({'valid':signal+'.valid','ready':signal+'.ready','clock':'clock'} if protocol=='decoupled-v1'
             else {'request':signal+'.req','acknowledge':signal+'.ack'})
    for key,value in signals.items():
        found=[e for e in node.get('endpoints',[]) if e.get('id')==channel.get(key)]
        require(len(found)==1 and type(found[0].get('width')) is int and found[0]['width']==1 and
            found[0].get('source')==f"~|{node['module']}>{value}",'PHASE_ENDPOINT_'+identity+'_'+key)
    return channel

def native_request_source(manifest,scopes,header=None):
    top=manifest.get('top');require(top in ('FourPhaseSoc','ClickSoc'),'TOP')
    click=top=='ClickSoc';prefix='Click' if click else 'FourPhase'
    protocol='two-phase-bundled-v1' if click else 'four-phase-bundled-v1'
    root=manifest['design'];core=child(root,'core');address=child(core,'address')
    fabric=child(root,'transactions');receipt=child(root,'request_bridge')
    specifications=[(core,'Core',top+'.ca_child_core'),
        (address,'Stage',top+'.ca_child_core.ca_child_address'),
        (fabric,'Fabric',top+'.ca_child_transactions'),
        (receipt,'QuiescingReceipt',top+'.ca_child_request_bridge')]
    for node,kind,path in specifications:
        require(re.fullmatch(prefix+kind+r'(?:_\d+)?',node.get('module','')) and
            node.get('rtl_path')==path and node.get('reset_domain')=='root','OWNER_'+kind)
        require(scopes.get(path,{}).get('model')==node['module'],'SCOPE_'+kind)
    for node,identity,signal,role,p in [(address,'out','out','output',protocol),
        (core,'request','request','output',protocol),(fabric,'request','request','input',protocol),
        (fabric,'service_request','serviceRequest','output',protocol),
        (receipt,'in','in','input',protocol),(receipt,'out','out','output','decoupled-v1')]:
        request_channel(node,identity,signal,role,p)
        for field,(_,width) in FIELDS.items():
            name=signal+'_bits_'+field
            require(scopes[node['rtl_path']].get('ports',{}).get(name)==
                port(name,width,'input' if role=='input' else 'output'),'PORT_'+identity+'_'+field)
        if p!='decoupled-v1':
            for suffix,direction in [('req','input' if role=='input' else 'output'),
                                     ('ack','output' if role=='input' else 'input')]:
                name=signal+'_'+suffix;actual=scopes[node['rtl_path']].get('ports',{}).get(name,{})
                require(actual==port(name,1,direction) and type(actual.get('width')) is int,
                    'PHASE_PORT_'+identity+'_'+suffix)
    cells=[p for p in address.get('primitives',[]) if p.get('id')=='payload']
    model='ChiselAsyncEventRegister_v1' if click else 'ChiselAsyncClosingLatch_v1'
    parameters=dict(WIDTH='70',DELAY_FS='1000000')
    if click:parameters['RESET_VALUE']='0'
    target=address['rtl_path']+'.ca_primitive_payload';q=port('q',70,'output')
    require(len(cells)==1 and cells[0].get('model')==model and cells[0].get('rtl_path')==target and
        cells[0].get('parameters')==parameters and cells[0].get('reset')=='reset' and
        cells[0].get('reset_domain')=='root' and [p for p in cells[0].get('ports',[]) if p.get('name')=='q']==[q] and
        scopes.get(target,{}).get('model')==model and scopes[target].get('parameters')==parameters and
        scopes[target].get('ports',{}).get('q')==q,'NATIVE_STORAGE')
    if header is not None:require(header.count(f"force {target}.q = 70'h0;")==1,'CATALOGUED_FORCE')
    require(receipt.get('capacity')==1 and all(receipt.get(k)==[] for k in ('children','primitives','timing')) and
        [c.get('id') for c in receipt['channels']]==['in','out'],'RECEIPT_OWNER')
    scope=scopes[receipt['rtl_path']]
    require(scope.get('registers')==REGISTERS and not scope.get('memories'),'RECEIPT_STORAGE')
    ports={n:port(n,1,d) for n,d in [('clock','input'),('reset','input'),('close','input'),
        ('rebase','input'),('closed','output'),('rebased','output'),('in_req','input'),('in_ack','output'),
        ('out_ready','input'),('out_valid','output')]}
    for side,direction in [('in','input'),('out','output')]:
        for field,(_,width) in FIELDS.items():
            name=side+'_bits_'+field;ports[name]=port(name,width,direction)
    require(scope.get('ports')==ports,'RECEIPT_PORTS')
    endpoints={e['id']:e for e in receipt['endpoints']}
    expected=dict(close=(1,'close'),closed=(1,'closed'),rebase=(1,'rebase'),rebased=(1,'rebased'),reset=(1,'reset'),
        in_request=(1,'in.req'),in_data=(70,'in.bits'),in_acknowledge=(1,'in.ack'),
        out_valid=(1,'out.valid'),out_data=(70,'out.bits'),out_ready=(1,'out.ready'),out_clock=(1,'clock'))
    require(len(endpoints)==len(receipt['endpoints']) and endpoints.keys()==expected.keys() and
        all(type(endpoints[k].get('width')) is int and endpoints[k]['width']==w and
            endpoints[k].get('source')==f"~|{receipt['module']}>{signal}" for k,(w,signal) in expected.items()),
        'RECEIPT_ENDPOINTS')
    return dict(path=target+'.q',width=70,fields=FIELDS)

def pack_request(**values):
    require(set(values)<=FIELDS.keys(),'PACK_FIELD')
    result=0
    for field,value in values.items():
        shift,width=FIELDS[field]
        require(type(value) is int and 0<=value<1<<width,'PACK_RANGE_'+field)
        result|=value<<shift
    return result

def request_receipt_probe(source,manifest,scopes):
    if manifest.get('top') not in ('FourPhaseSoc','ClickSoc'):return source
    retained=native_request_source(manifest,scopes)
    top=manifest['top'];path=top+'.ca_child_request_bridge'
    valid=f"(({path}.state == 2'h2) && !{path}.close && !{path}.localReset_release_1)"
    bindings=[(path+'.out_valid',valid),(path+'.in_ack',path+'.acknowledge')]
    # These are alias checks only. Fabric's selected dispatch/response gating
    # and temporal source hold remain mandatory composed functional contracts.
    # No phase, request, ACK, validity or derived bus is forced by this probe.
    for pin in ('req','ack'):
        bindings += [(top+'.ca_child_core.ca_child_address.out_'+pin,top+'.ca_child_core.request_'+pin),
            (top+'.ca_child_core.request_'+pin,top+'.ca_child_transactions.request_'+pin),
            (top+'.ca_child_transactions.serviceRequest_'+pin,path+'.in_'+pin)]
    for field,(offset,width) in FIELDS.items():
        value=retained['path']+f'[{offset+width-1}:{offset}]'
        for owner,pin in [('ca_child_core.ca_child_address','out'),('ca_child_core','request'),
            ('ca_child_transactions','request'),('ca_child_transactions','serviceRequest'),('ca_child_request_bridge','in')]:
            bindings.append((top+'.'+owner+'.'+pin+'_bits_'+field,value))
        bindings.append((path+'.out_bits_'+field,f"({valid} ? {value} : {width}'h0)"))
    # Exact per-call comparisons accompany every original generic campaign.
    matches=list(re.finditer(r'\btask(?:\s+automatic)?\s+check\s*;\s*begin',source))
    require(len(matches)==1,'CHECK_SHAPE')
    inserted=''.join(f'\nif ({left} !== {right}) $fatal(1,"QUIESCING_REQUEST_BINDING:{left}");'
        for left,right in bindings)
    point=matches[0].end()
    return source[:point]+inserted+source[point:]

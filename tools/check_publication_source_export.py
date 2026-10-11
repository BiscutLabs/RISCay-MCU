# SPDX-License-Identifier: Apache-2.0
"""Closed digital policy for native exclusive service publication receipts."""
import re

CHANNELS=('reserve','grant','decision','publication','drain')
IDENTITY_CHANNELS=('reserve','grant','drain')


def channel_layout(module,channel,identity):
    fields=('bits.tag','bits.recovery') if identity else ('bits',)
    return [dict(field=field,lsb=bit,width=1,signed=False,source=f'~|{module}>{channel}.{field}')
            for bit,field in enumerate(fields)]

PATHS=(
    ('arm_path','publication source reservation and independent next targets','arm_sources','arm_data','arm_data_delay'),
    ('publication_path','independent publication phase capture','publication_request','publication_phase_data','publication_data_delay'),
    ('drain_path','committed drain target before issue','drain_target','drain_phase_data','drain_data_delay'),
    ('retirement_path','publication source retirement phase feedback','retirement_sources','register_data','data_delay'))
APERTURES=(
    ('arm_aperture','reserved','arm_sources','arm_data','arm_event','armed'),
    ('publication_aperture','publication_request','publication_request','publication_phase_data','publication_event','publication_captured'),
    ('drain_aperture','decision_request','decision_data','drain_phase_data','drain_event','drain_issued'),
    ('retirement_aperture','decision_request','decision_data','register_data','capture_event','captured'))


def publication_recovery_background(source,manifest,scopes,checks):
    """Add joint recovery source states without forcing derived command fields.

    A recovery command needs the native role, eligibility and debt, plus its
    matching queued grant. Individual/paired source walks cannot form that
    conjunction. Preserve every existing stimulus and dynamic coverage check.
    """
    children={c['id']:c['contract'] for c in manifest['design'].get('children',[])}
    owners=('telemetry','housekeeping')
    if not any(name+'_source' in children for name in owners):return source,checks
    if not all(name+'_source' in children for name in owners):raise ValueError('RECOVERY_BACKGROUND_INVENTORY')
    top=manifest['top'];anchor=f"initial begin\nforce {top}.reset = 1'b1; #1;\n"
    if source.count(anchor)!=1:raise ValueError('RECOVERY_BACKGROUND_SHAPE')
    start=source.index(anchor)+len(anchor);end=source.index('\n#1;\n',start)+len('\n#1;\n')
    header=source[start:end]
    coverage=list(re.finditer(r'^if \(ones_\d+ !==.*INACTIVE_ENDPOINT:.*$',source,re.M))
    marker=f'CONTRACT_PROBES_PASS:{checks}'
    if not coverage or source.count(marker)!=1:raise ValueError('RECOVERY_BACKGROUND_SHAPE')
    extra=[];steps=0

    def force(path,width,value,primitive=None):
        node,field=path.rsplit('.',1);scope=scopes.get(node,{})
        valid=(scope.get('ports',{}).get(field)==dict(name=field,width=width,direction='output') and
            scope.get('model')==primitive) if primitive else scope.get('registers',{}).get(field)==width
        if not valid or f"force {path} = {width}'h0;" not in header:raise ValueError('RECOVERY_BACKGROUND_DRIVER')
        if not 0<=value<1<<width:raise ValueError('RECOVERY_BACKGROUND_RANGE')
        extra.append(f"force {path} = {width}'h{value:x};\n")

    for name in owners:
        owner=children[name+'_source']
        if not re.fullmatch(r'(?:FourPhase|Click)PublicationSource(?:_[0-9]+)?',owner['module']):
            raise ValueError('RECOVERY_BACKGROUND_OWNER')
        cells={p['id']:p for p in owner['primitives']}
        for identity,initial in (('eligibility','0'),('debt_storage','1')):
            cell=cells.get(identity,{})
            if (cell.get('model')!='ChiselAsyncEventRegister_v1' or
                cell.get('parameters',{}).get('WIDTH')!='1' or cell['parameters'].get('RESET_VALUE')!=initial):
                raise ValueError('RECOVERY_BACKGROUND_STORAGE')
        reservations=[c['contract'] for c in owner['children'] if c['id']=='reservation']
        if len(reservations)!=1:raise ValueError('RECOVERY_BACKGROUND_STORAGE')
        reservation=reservations[0]
        layouts=[c['layout'] for c in reservation['channels'] if c['id']=='out']
        if len(layouts)!=1 or layouts[0]!=channel_layout(reservation['module'],'out',True):
            raise ValueError('RECOVERY_BACKGROUND_LAYOUT')
        payloads=[p for p in reservation['primitives'] if p['id']=='payload']
        if (len(payloads)!=1 or payloads[0]['model'] not in ('ChiselAsyncClosingLatch_v1','ChiselAsyncEventRegister_v1') or
            payloads[0]['parameters'].get('WIDTH')!='2'):raise ValueError('RECOVERY_BACKGROUND_STORAGE')
        payload=payloads[0]
        # Exercise both values and every combination of the four prerequisites.
        # The all-one combination makes the real command recovery bit high.
        for bits in range(16):
            extra.append(header)
            force(top+f'.ca_child_{name}_grant_bridge.state',2,2)
            force(top+f'.ca_child_{name}_grant_bridge.data_recovery',1,(bits>>0)&1)
            force(cells['eligibility']['rtl_path']+'.q',1,(bits>>1)&1,'ChiselAsyncEventRegister_v1')
            force(cells['debt_storage']['rtl_path']+'.q',1,(bits>>2)&1,'ChiselAsyncEventRegister_v1')
            force(payload['rtl_path']+'.q',2,((bits>>3)&1)<<1,payload['model'])
            extra.append('#1; check;\n');steps+=1
    count=checks+steps*len(coverage);position=coverage[0].start()
    result=source[:position]+''.join(extra)+source[position:]
    return result.replace(marker,f'CONTRACT_PROBES_PASS:{count}'),count


def validate_publication_source(node):
    if not re.fullmatch(r'(?:FourPhase|Click)PublicationSource(?:_[0-9]+)?',node['module']):
        raise ValueError('PUBLICATION_SOURCE_OWNER')
    click=node['module'].startswith('Click')
    protocol='two-phase-bundled-v1' if click else 'four-phase-bundled-v1'
    if (node['capacity']!=1 or len(node['channels'])!=5 or
        {c['id']:(c['protocol'],c['role']) for c in node['channels']}!=
        {n:(protocol,'output' if n in ('grant','drain') else 'input') for n in CHANNELS} or
        any(c['layout']!=channel_layout(node['module'],c['id'],c['id'] in IDENTITY_CHANNELS)
            for c in node['channels'])):
        raise ValueError('PUBLICATION_SOURCE_SCHEMA')
    if (len(node['children'])!=1 or node['children'][0]['id']!='reservation' or
        not re.fullmatch(('ClickBuffer' if click else 'LongHoldBuffer')+r'(?:_[0-9]+)?',node['children'][0]['contract']['module']) or
        node['children'][0]['contract']['capacity']!=1):
        raise ValueError('PUBLICATION_SOURCE_STORAGE')
    storage=node['children'][0]['contract']
    if (len(storage['channels'])!=2 or {c['id'] for c in storage['channels']}!={'in','out'} or
        any(c['layout']!=channel_layout(storage['module'],c['id'],True) for c in storage['channels'])):
        raise ValueError('PUBLICATION_SOURCE_STORAGE_SCHEMA')
    widths={n+'_'+f:1 for n in CHANNELS for f in ('request','data','acknowledge')}
    widths.update({n+'_data':2 for n in IDENTITY_CHANNELS})
    widths.update({n:1 for n in ('reset','eligibility_reset','application_reset','eligible','idle','reserved',
                               'owner_recovery','recovery_debt','recovery_event')})
    if click:
        widths.update(recovery_select=1,arm_sources=3,arm_data=3,arm_event=1,armed=3,
            publication_phase_data=1,publication_event=1,publication_captured=1,
            drain_target=1,drain_phase_data=1,drain_event=1,drain_issued=1,
            retirement_sources=2,register_data=2,capture_event=1,captured=2)
    if len(node['endpoints'])!=len(widths) or {e['id']:e['width'] for e in node['endpoints']}!=widths:
        raise ValueError('PUBLICATION_SOURCE_ENDPOINTS')
    timings={t['id']:t for t in node['timing']}
    expected={p[0] for p in PATHS+APERTURES} if click else set()
    if len(node['timing'])!=len(expected) or set(timings)!=expected:
        raise ValueError('PUBLICATION_SOURCE_TIMING')
    if click:
        for name,logic,source,sink,delay in PATHS:
            policy=dict(kind='bundled-data-path-v1',logic=logic,source=source,sink=sink,delay_owner=[],delay_cell=delay,
                logic_model_fs='0',budget=dict(min_fs='10000000',max_fs='10000000',model_fs='10000000'))
            if any(timings[name].get(k)!=v for k,v in policy.items()):raise ValueError('PUBLICATION_SOURCE_PATH:'+name)
        for name,launch,transaction,data,capture,captured in APERTURES:
            policy=dict(kind='bundled-setup-hold-v1',launch=launch,transaction=transaction,data_valid=data,
                capture=capture,captured=captured,setup_fs='100000',hold_fs='100000')
            if any(timings[name].get(k)!=v for k,v in policy.items()):raise ValueError('PUBLICATION_SOURCE_APERTURE:'+name)
    cells={p['id']:p for p in node['primitives']};expected={}
    def cell(name,model,**params):expected[name]=('ChiselAsync'+model+'_v1',{k:str(v) for k,v in params.items()})
    def gate(name,width=1,op=0,delay=1000000,initial=0):cell(name,'ControlGate',WIDTH=width,OP=op,DELAY_FS=delay,RESET_VALUE=initial)
    def phase(name,width=1):cell(name,'EventRegister',WIDTH=width,DELAY_FS=1000000,RESET_VALUE=0)
    def and_gate(name):
        gate(name+'_na',op=1,initial=1);gate(name+'_nb',op=1,initial=1)
        gate(name+'_or',op=2,initial=1);gate(name,op=1)
    phase('eligibility')
    cell('debt_storage','EventRegister',WIDTH=1,DELAY_FS=1000000,RESET_VALUE=1)
    gate('request_guard',delay=11000000 if click else 200000000)
    gate('request_delay',delay=11000000)
    gate('output_guard',delay=241200001 if click else 200000000)
    gate('acknowledge_guard',width=3 if click else 1,delay=241200001 if click else 200000000)
    if click:
        phase('armed_phase',3)
        for n in ('publication_phase','drain_phase','retired_phase','decision_phase'):phase(n)
        for n in ('arm_pending','owned','decision_pending','publication_pending','publication_unused','drain_unused'):
            cell(n,'Xor',DELAY_FS=1000000)
        gate('arm_data_delay',width=3,delay=10000000);gate('data_delay',width=2,delay=10000000)
        gate('publication_data_delay',delay=10000000);gate('drain_data_delay',delay=10000000)
        gate('return_guard',delay=241200001)
        for n in ('publication_fire','publication_owner','publication_committed','publication_selected','publication_decision',
            'drain_fire','drain_owner','drain_selected','drain_decision',
            'retire_fire','retire_left','retire_source','retire_effect','retire_right','retire_decision','retire_owner',
            'recovery_live','recovery_selected','recovery_clear'):and_gate(n)
    else:
        for n,r,f in (('receipt_seen',1,0),('receipt_accept',2,0),('drain_issue',3,0),('retirement',6,2),
                      ('reservation_return',0,8),('recovery_clear',4,0)):
            cell(n,'AsymmetricC',COMMON=1,RISING=r,FALLING=f,DELAY_FS=1000000,RESET_VALUE=0,
                COMMON_INVERT=0,RISING_INVERT=0,FALLING_INVERT=0)
    markers={t['marker'] for t in node['timing']}
    for t in node['timing']:
        params={name:0 for name in (
            'ACKNOWLEDGE_MAX_FS','ACKNOWLEDGE_MIN_FS','ACKNOWLEDGE_MODEL_FS',
            'A_MAX_FS','A_MIN_FS','A_MODEL_FS','B_MAX_FS','B_MIN_FS','B_MODEL_FS',
            'DATA_MAX_FS','DATA_MIN_FS','DATA_MODEL_FS','HOLD_FS','KIND',
            'LATCH_MAX_FS','LATCH_MIN_FS','LATCH_MODEL_FS',
            'LONG_HOLD_MAX_FS','LONG_HOLD_MIN_FS','LONG_HOLD_MODEL_FS',
            'MATCHED_FS','OUTPUT_FS','SETUP_FS','WIDTH')}
        if t['kind']=='bundled-data-path-v1':
            params.update(KIND=3,WIDTH=widths[t['source']]+widths[t['sink']],
                DATA_MIN_FS=10000000,DATA_MAX_FS=10000000,DATA_MODEL_FS=10000000)
        else:
            params.update(KIND=1,SETUP_FS=100000,HOLD_FS=100000,
                WIDTH=sum(widths[t[k]] for k in ('launch','transaction','data_valid','capture','captured')))
        cell(t['marker'],'TimingMarker',**params)
    if len(cells)!=len(node['primitives']) or set(cells)!=set(expected)|markers:
        raise ValueError('PUBLICATION_SOURCE_CELL_INVENTORY')
    for name,(model,params) in expected.items():
        if cells[name]['model']!=model or cells[name]['parameters']!=params:raise ValueError('PUBLICATION_SOURCE_CELL_POLICY:'+name)
    for name,c in cells.items():
        if c['reset']!=('eligibility_reset' if name in ('eligibility','debt_storage') else 'reset'):
            raise ValueError('PUBLICATION_SOURCE_RESET_OWNER:'+name)
    return click


def publication_source_bindings(node):
    click=validate_publication_source(node)
    e={x['id']:x['rtl_path'] for x in node['endpoints']};c={x['id']:x['rtl_path'] for x in node['primitives']}
    r={x['id']:x['rtl_path'] for x in node['children'][0]['contract']['endpoints']}
    cat=lambda xs:'{'+','.join(xs)+'}'
    q=lambda n:c[n]+'.q'
    pairs=[(e['eligibility_reset'],f"({e['reset']} | {e['application_reset']})"),
        (c['eligibility']+'.reset',e['eligibility_reset']),(c['eligibility']+'.d',"1'b1"),
        (c['debt_storage']+'.reset',e['eligibility_reset']),(c['debt_storage']+'.d',"1'b0"),
        (c['debt_storage']+'.trigger',e['recovery_event']),(e['recovery_debt'],q('debt_storage')),
        (e['owner_recovery'],r['out_data']+'[1]'),
        (e['eligible'],q('eligibility')),(e['reserved'],r['in_acknowledge']),
        (e['reserve_request'],r['in_request']),(e['reserve_data'],r['in_data']),
        (e['grant_data'],r['out_data']),(e['drain_data'],r['out_data']),
        (e['grant_acknowledge'],r['out_acknowledge']),(e['grant_request'],q('output_guard')),
        (r['out_request'],c['output_guard']+'.a'),(e['publication_request'],c['request_delay']+'.a')]
    def gate_inputs(n,a,b):
        pairs.extend([(a,c[n+'_na']+'.a'),(b,c[n+'_nb']+'.a'),
            (q(n+'_na'),c[n+'_or']+'.a'),(q(n+'_nb'),c[n+'_or']+'.b'),(q(n+'_or'),c[n]+'.a')])
    if click:
        same=f"({e['armed']}[0] == {e['reserved']})"
        for n,a,b in (
            ('arm_pending',e['reserved'],e['armed']+'[0]'),('owned',e['reserved'],q('retired_phase')),
            ('decision_pending',q('return_guard'),q('decision_phase')),
            ('publication_pending',q('request_delay'),q('publication_phase')),
            ('publication_unused',e['armed']+'[1]',q('publication_phase')),
            ('drain_unused',e['armed']+'[2]',q('drain_phase'))):
            pairs.extend([(a,c[n]+'.a'),(b,c[n]+'.b')])
        pairs.extend([(q('arm_pending'),c['request_guard']+'.a'),(q('request_guard'),e['arm_event']),
            (e['arm_event'],c['armed_phase']+'.trigger'),(e['arm_event'],c['eligibility']+'.trigger'),
            (cat(['!'+q('drain_phase'),'!'+q('publication_phase'),e['reserved']]),e['arm_sources']),
            (e['arm_sources'],c['arm_data_delay']+'.a'),(q('arm_data_delay'),e['arm_data']),
            (e['arm_data'],c['armed_phase']+'.d'),(e['armed'],q('armed_phase')),
            (e['decision_request'],c['return_guard']+'.a'),(e['publication_request'],c['publication_data_delay']+'.a'),
            (e['drain_target'],e['armed']+'[2]'),(e['drain_target'],c['drain_data_delay']+'.a')])
        for name,a,b in (
            ('publication_owner',q('owned'),same),('publication_selected',q('publication_pending'),q('publication_unused')),
            ('publication_decision',q('decision_pending'),e['decision_data']),
            ('publication_committed',q('publication_selected'),q('publication_decision')),
            ('publication_fire',q('publication_owner'),q('publication_committed')),
            ('drain_owner',q('owned'),same),('drain_decision',q('decision_pending'),e['decision_data']),
            ('drain_selected',q('drain_decision'),q('drain_unused')),('drain_fire',q('drain_owner'),q('drain_selected'))):gate_inputs(name,a,b)
        for name,phase,port in (('publication','publication_phase','publication_captured'),('drain','drain_phase','drain_issued')):
            pairs.extend([(q(name+'_data_delay'),e[name+'_phase_data']),(e[name+'_phase_data'],c[phase]+'.d'),
                (e[name+'_event'],q(name+'_fire')),(e[name+'_event'],c[phase]+'.trigger'),(e[port],q(phase))])
        pairs.append((e['drain_request'],q('drain_phase')))
        drained=f"({q('drain_phase')} == {e['armed']}[2] && {e['drain_acknowledge']} == {e['armed']}[2])"
        seen=f"({q('publication_phase')} == {e['armed']}[1])"
        # The Scala Cat places these conditions high-to-low; the balanced tree
        # consumes bit 0 first. All eight must hold without a clocked selector.
        bits=[q('owned'),same,q('decision_pending'),f"(!{e['decision_data']} || {drained})",
            f"(!{e['decision_data']} || {seen} || !{e['eligible']})",
            f"({e['publication_request']} == {e['publication_acknowledge']})",
            f"({e['grant_request']} == {e['reserved']} && {e['grant_acknowledge']} == {e['reserved']})",
            f"(!{q('publication_fire')} && !{q('drain_fire')})"][::-1]
        for name,a,b in (('retire_source',bits[0],bits[1]),('retire_effect',bits[2],bits[3]),
            ('retire_left',q('retire_source'),q('retire_effect')),('retire_decision',bits[4],bits[5]),
            ('retire_owner',bits[6],bits[7]),('retire_right',q('retire_decision'),q('retire_owner')),
            ('retire_fire',q('retire_left'),q('retire_right'))):gate_inputs(name,a,b)
        pairs.extend([(cat([e['decision_request'],e['reserved']]),e['retirement_sources']),
            (e['retirement_sources'],c['data_delay']+'.a'),(e['register_data'],q('data_delay')),
            (e['capture_event'],q('retire_fire'))])
        for bit,(phase,port) in enumerate((('retired_phase','reserve'),('decision_phase','decision'))):
            pairs.extend([(e['register_data']+f'[{bit}]',c[phase]+'.d'),(e['capture_event'],c[phase]+'.trigger'),
                (q(phase),e['captured']+f'[{bit}]'),(q(phase),c['acknowledge_guard']+f'.a[{bit}]'),
                (e[port+'_acknowledge'],c['acknowledge_guard']+f'.q[{bit}]')])
        pairs.extend([(q('publication_phase'),c['acknowledge_guard']+'.a[2]'),
            (e['publication_acknowledge'],c['acknowledge_guard']+'.q[2]')])
        gate_inputs('recovery_live',e['decision_data'],e['eligible'])
        gate_inputs('recovery_selected',e['owner_recovery'],q('recovery_live'))
        gate_inputs('recovery_clear',e['capture_event'],e['recovery_select'])
        pairs.extend([(e['recovery_select'],q('recovery_selected')),(e['recovery_event'],q('recovery_clear'))])
        idle=' && '.join(f"({e[n+'_request']} == {e[n+'_acknowledge']})" for n in CHANNELS)
        idle+=f" && ({e['reserved']} == {e['reserve_acknowledge']}) && !{e['capture_event']} && !{e['arm_event']} && !{e['publication_event']} && !{e['drain_event']} && !{e['recovery_event']}"
    else:
        pairs.extend([(e['reserved'],c['eligibility']+'.trigger'),(e['decision_request'],c['request_guard']+'.a'),
            (q('request_delay'),c['receipt_accept']+'.common'),
            (cat([e['reserved'],'!'+q('receipt_seen')]),c['receipt_accept']+'.rising'),
            ("1'b0",c['receipt_accept']+'.falling'),(e['publication_acknowledge'],q('receipt_accept')),
            (e['reserve_request'],c['receipt_seen']+'.common'),(q('receipt_accept'),c['receipt_seen']+'.rising'),
            ("1'b0",c['receipt_seen']+'.falling'),(e['reserve_request'],c['drain_issue']+'.common'),
            (cat([e['reserved'],q('request_guard'),e['decision_data']]),c['drain_issue']+'.rising'),
            ("1'b0",c['drain_issue']+'.falling'),(e['drain_request'],q('drain_issue')),
            (e['reserve_request'],c['retirement']+'.common'),
            (cat([e['reserved'],q('request_guard'),f"(!{e['decision_data']} || ({q('drain_issue')} && {e['drain_acknowledge']}))",
                f"(!{e['decision_data']} || {q('receipt_seen')} || !{e['eligible']})",
                f"(!{e['publication_request']} && !{e['publication_acknowledge']})",
                f"(!{e['grant_request']} && !{e['grant_acknowledge']})"]),c['retirement']+'.rising'),
            (cat([e['decision_request'],e['publication_request']]),c['retirement']+'.falling'),
            (e['decision_acknowledge'],q('retirement')),(q('retirement'),c['reservation_return']+'.common'),
            ("1'b1",c['reservation_return']+'.rising'),
            (cat([e['decision_acknowledge'],e['publication_request'],e['publication_acknowledge'],e['reserved'],
                q('receipt_seen'),e['drain_request'],e['drain_acknowledge'],e['recovery_event']]),c['reservation_return']+'.falling'),
            (q('retirement'),c['recovery_clear']+'.common'),
            (cat([e['owner_recovery'],q('drain_issue'),q('receipt_seen'),e['eligible']]),c['recovery_clear']+'.rising'),
            ("1'b0",c['recovery_clear']+'.falling'),(q('recovery_clear'),e['recovery_event']),
            (q('reservation_return'),c['acknowledge_guard']+'.a'),(e['reserve_acknowledge'],q('acknowledge_guard'))])
        idle=' && '.join('!'+e[n+'_'+f] for n in CHANNELS for f in ('request','acknowledge'))
        idle+=f" && !{e['reserved']} && !{q('receipt_seen')} && !{e['recovery_event']}"
    pairs.append((e['idle'],'('+idle+')'))
    return pairs


def publication_source_probe(source,manifest,scopes):
    pairs=[]
    def visit(node):
        nonlocal source
        if re.fullmatch(r'(?:FourPhase|Click)PublicationSource(?:_[0-9]+)?',node['module']):
            pairs.extend(publication_source_bindings(node))
            e={x['id']:x['rtl_path'] for x in node['endpoints']}
            for name in ('eligibility','debt_storage'):
                cell=next(p['rtl_path'] for p in node['primitives'] if p['id']==name)
                old=f'if ({cell}.reset !== {e["eligibility_reset"]} || {e["eligibility_reset"]} !== {node["rtl_path"]}.reset) $fatal(1, "RESET_BINDING_MISMATCH");'
                new=f'if ({cell}.reset !== {e["eligibility_reset"]} || {e["eligibility_reset"]} !== ({e["reset"]} | {e["application_reset"]})) $fatal(1, "RESET_BINDING_MISMATCH");'
                if source.count(old)!=1:raise ValueError('PUBLICATION_SOURCE_RESET_PROBE_SHAPE:'+name)
                source=source.replace(old,new)
        for child in node['children']:visit(child['contract'])
    visit(manifest['design'])
    top=manifest['top']
    if top in ('FourPhaseSoc','ClickSoc'):
        children={c['id']:c['contract'] for c in manifest['design']['children']}
        click=top=='ClickSoc';prefix='Click' if click else 'FourPhase'
        consumer_clock=next(x['rtl_path'] for x in children['control_command_bridge']['endpoints'] if x['id']=='in_clock')
        for owner in ('telemetry','housekeeping'):
            names={owner+'_source'}|{owner+'_'+n+'_bridge' for n in CHANNELS}
            if not names<=children.keys():raise ValueError('PUBLICATION_SOURCE_SOC_INVENTORY')
            node=children[owner+'_source']
            if not re.fullmatch(prefix+r'PublicationSource(?:_[0-9]+)?',node['module']):raise ValueError('PUBLICATION_SOURCE_SOC_OWNER')
            e={x['id']:x['rtl_path'] for x in node['endpoints']}
            for name in CHANNELS:
                bridge=children[owner+'_'+name+'_bridge'];output=name in ('grant','drain')
                model=('ClickToDecoupled' if click else 'FourPhaseToDecoupled') if output else ('DecoupledToClick' if click else 'DecoupledToFourPhase')
                protocol='two-phase-bundled-v1' if click else 'four-phase-bundled-v1'
                if (not re.fullmatch(model+r'(?:_[0-9]+)?',bridge['module']) or
                    {c['id']:(c['protocol'],c['role']) for c in bridge['channels']}!=
                    {'in':(protocol if output else 'decoupled-v1','input'),'out':('decoupled-v1' if output else protocol,'output')} or
                    any(c['layout']!=channel_layout(bridge['module'],c['id'],name in IDENTITY_CHANNELS)
                        for c in bridge['channels'])):raise ValueError('PUBLICATION_SOURCE_BRIDGE_SCHEMA')
                b={x['id']:x['rtl_path'] for x in bridge['endpoints']}
                pairs.extend((e[name+'_'+f],b[('in_' if output else 'out_')+f]) for f in ('request','data','acknowledge'))
                pairs.append((b['out_clock' if output else 'in_clock'],consumer_clock))
            pairs.append((e['application_reset'],top+'.systemReset'))
    anchor='task check; begin'
    if source.count(anchor)!=1:raise ValueError('PUBLICATION_SOURCE_PROBE_SHAPE')
    checks=[f'if ({a} !== {b}) $fatal(1,"PUBLICATION_SOURCE_BINDING:{a}");' for a,b in pairs]
    return source.replace(anchor,anchor+'\n'+'\n'.join(checks))

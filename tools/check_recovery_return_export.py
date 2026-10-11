# SPDX-License-Identifier: Apache-2.0
"""Closed digital policy for native final-return proof and temporary receipts."""
import re

PHASES=(('target','target_sources','target_data','fresh','target','target_data_delay'),
        ('issue','target','issue_data','issue_event','issued','issue_data_delay'),
        ('complete','issued','complete_data','complete_event','completed','complete_data_delay'),
        ('admission','requested','admission_data','admitting','admitted','admission_data_delay'))
PATHS=tuple((n+'_path','recovery return '+n+' phase data',src,data,delay)
            for n,src,data,event,captured,delay in PHASES)


def validate_recovery_return(node):
    if not re.fullmatch(r'(?:FourPhase|Click)RecoveryReturn(?:_[0-9]+)?',node['module']):
        raise ValueError('RECOVERY_RETURN_OWNER')
    click=node['module'].startswith('Click')
    ids={'reset','requested','admitted','original_returned','fresh','eligible','final_request',
         'final_acknowledge','clear_event','quiet','cleanup'}
    if click:ids.update(('admitting','capacity','target_sources','target_data','issue_event','issue_data',
        'wire_returned','complete_event','complete_data','admission_data','target','issued','completed'))
    if (node['capacity']!=1 or node['channels'] or node['children'] or len(node['endpoints'])!=len(ids) or
        {e['id']:e['width'] for e in node['endpoints']}!={n:1 for n in ids}):
        raise ValueError('RECOVERY_RETURN_INVENTORY')
    timings={t['id']:t for t in node['timing']}
    expected={n+'_'+kind for n,*_ in PHASES for kind in ('path','aperture')} if click else set()
    if len(node['timing'])!=len(expected) or set(timings)!=expected:raise ValueError('RECOVERY_RETURN_TIMING')
    if click:
        for n,src,data,event,captured,delay in PHASES:
            path=dict(kind='bundled-data-path-v1',logic='recovery return '+n+' phase data',source=src,sink=data,
                delay_owner=[],delay_cell=delay,logic_model_fs='0',
                budget=dict(min_fs='10000000',max_fs='10000000',model_fs='10000000'))
            aperture=dict(kind='bundled-setup-hold-v1',launch=src,transaction=src,data_valid=data,
                capture=event,captured=captured,setup_fs='100000',hold_fs='100000')
            for kind,policy in (('path',path),('aperture',aperture)):
                if any(timings[n+'_'+kind].get(k)!=v for k,v in policy.items()):
                    raise ValueError('RECOVERY_RETURN_'+kind.upper()+':'+n)
    cells={p['id']:p for p in node['primitives']};expected={}
    def cell(name,model,**params):expected[name]=('ChiselAsync'+model+'_v1',{k:str(v) for k,v in params.items()})
    def gate(name,op=0,delay=1000000,initial=0):cell(name,'ControlGate',WIDTH=1,OP=op,DELAY_FS=delay,RESET_VALUE=initial)
    def and_gate(name):
        gate(name+'_na',op=1,initial=1);gate(name+'_nb',op=1,initial=1)
        gate(name+'_or',op=2,initial=1);gate(name,op=1)
    gate('acknowledge_guard',delay=200000000);and_gate('clear')
    if click:
        for n in ('admitted_phase','target_phase','issued_phase','completed_phase'):
            cell(n,'EventRegister',WIDTH=1,DELAY_FS=1000000,RESET_VALUE=0)
        for n in ('issue_pending','complete_pending','admission_pending'):cell(n,'Xor',DELAY_FS=1000000)
        for n in ('issue_selected','complete_selected','complete_wire','complete_source','admission_selected'):and_gate(n)
        for n in ('request_delay','return_guard','request_guard'):gate(n,delay=11000000)
        for n,*_,delay in PHASES:gate(delay,delay=10000000)
    else:
        gate('offer_ack_invert',op=1,initial=1);and_gate('offer')
        for n,r,ci,ri in (('pending',1,1,0),('issued',1,0,0),('ack_seen',3,0,0),('done',3,0,3),('admission',2,0,0)):
            cell(n,'AsymmetricC',COMMON=1,RISING=r,FALLING=0,DELAY_FS=1000000,RESET_VALUE=0,
                COMMON_INVERT=ci,RISING_INVERT=ri,FALLING_INVERT=0)
    for t in node['timing']:
        params={name:0 for name in ('ACKNOWLEDGE_MAX_FS','ACKNOWLEDGE_MIN_FS','ACKNOWLEDGE_MODEL_FS',
            'A_MAX_FS','A_MIN_FS','A_MODEL_FS','B_MAX_FS','B_MIN_FS','B_MODEL_FS','DATA_MAX_FS','DATA_MIN_FS',
            'DATA_MODEL_FS','HOLD_FS','KIND','LATCH_MAX_FS','LATCH_MIN_FS','LATCH_MODEL_FS',
            'LONG_HOLD_MAX_FS','LONG_HOLD_MIN_FS','LONG_HOLD_MODEL_FS','MATCHED_FS','OUTPUT_FS','SETUP_FS','WIDTH')}
        if t['kind']=='bundled-data-path-v1':
            params.update(KIND=3,WIDTH=2,DATA_MIN_FS=10000000,DATA_MAX_FS=10000000,DATA_MODEL_FS=10000000)
        else:params.update(KIND=1,WIDTH=5,SETUP_FS=100000,HOLD_FS=100000)
        cell(t['marker'],'TimingMarker',**params)
    if len(cells)!=len(node['primitives']) or set(cells)!=set(expected):raise ValueError('RECOVERY_RETURN_CELLS')
    for n,(model,params) in expected.items():
        if cells[n]['model']!=model or cells[n]['parameters']!=params:raise ValueError('RECOVERY_RETURN_CELL_POLICY:'+n)
        if cells[n]['reset']!='reset':raise ValueError('RECOVERY_RETURN_RESET:'+n)
    return click


def recovery_return_bindings(node):
    click=validate_recovery_return(node)
    e={x['id']:x['rtl_path'] for x in node['endpoints']};c={x['id']:x['rtl_path'] for x in node['primitives']}
    q=lambda n:c[n]+'.q';cat=lambda xs:'{'+','.join(xs)+'}'
    pairs=[]
    def and_inputs(n,a,b):
        pairs.extend([(a,c[n+'_na']+'.a'),(b,c[n+'_nb']+'.a'),(q(n+'_na'),c[n+'_or']+'.a'),
            (q(n+'_nb'),c[n+'_or']+'.b'),(q(n+'_or'),c[n]+'.a')])
    # Unused gate pins and all POR inputs are closed too.
    for p in node['primitives']:
        pairs.append((c[p['id']]+'.reset',e['reset']))
        if p['model']=='ChiselAsyncControlGate_v1' and p['parameters']['OP']!='2':
            pairs.append((c[p['id']]+'.b',"1'b0"))
    if click:
        for n,port in (('target_phase','target'),('issued_phase','issued'),('completed_phase','completed'),('admitted_phase','admitted')):
            pairs.append((q(n),e[port]))
        pairs.extend([(e['target_sources'],'!'+e['target']),
            (e['final_request'],e['issued']),
            (e['wire_returned'],f"({e['final_request']} == {e['target']} && {e['final_acknowledge']} == {e['target']})"),
            (e['completed'],c['acknowledge_guard']+'.a'),(e['cleanup'],q('acknowledge_guard')),
            (e['capacity'],f"({e['original_returned']} && {e['quiet']})")])
        for n,a,b in (('issue_pending',e['target'],e['issued']),('complete_pending',e['issued'],e['cleanup']),
                     ('admission_pending',e['requested'],e['admitted'])):
            pairs.extend([(a,c[n]+'.a'),(b,c[n]+'.b')])
        for n,a,b in (('issue_selected',q('issue_pending'),e['original_returned']),
            ('complete_source',e['original_returned'],'!'+e['issue_event']),
            ('complete_wire',e['wire_returned'],q('complete_source')),
            ('complete_selected',q('complete_pending'),q('complete_wire')),
            ('admission_selected',q('admission_pending'),e['capacity']),('clear',e['complete_event'],e['eligible'])):
            and_inputs(n,a,b)
        for n,guard,event in (('issue_selected','request_delay','issue_event'),('complete_selected','return_guard','complete_event'),
                               ('admission_selected','request_guard','admitting')):
            pairs.extend([(q(n),c[guard]+'.a'),(q(guard),e[event])])
        for (n,src,data,event,captured,delay),phase in zip(PHASES,('target_phase','issued_phase','completed_phase','admitted_phase')):
            pairs.extend([(e[src],c[delay]+'.a'),(q(delay),e[data]),(e[data],c[phase]+'.d'),(e[event],c[phase]+'.trigger')])
        quiet=f"(!{e['fresh']} && {e['target']} == {e['issued']} && {e['issued']} == {e['completed']} && {e['completed']} == {e['cleanup']} && {e['final_acknowledge']} == {e['final_request']} && !{e['issue_event']} && !{e['complete_event']} && !{e['clear_event']})"
    else:
        for n,common,rising in (('pending',e['cleanup'],e['fresh']),('issued',q('pending'),e['original_returned']),
            ('ack_seen',q('pending'),cat([q('issued'),e['final_request'],e['final_acknowledge']])),
            ('done',q('pending'),cat([q('ack_seen'),e['final_request'],e['final_acknowledge']])),
            ('admission',e['requested'],cat([e['original_returned'],e['quiet']]))):
            pairs.extend([(common,c[n]+'.common'),(rising,c[n]+'.rising'),("1'b0",c[n]+'.falling')])
        pairs.extend([(q('ack_seen'),c['offer_ack_invert']+'.a'),(e['final_request'],q('offer')),
            (q('done'),c['acknowledge_guard']+'.a'),(e['cleanup'],q('acknowledge_guard')),(e['admitted'],q('admission'))])
        and_inputs('offer',q('issued'),q('offer_ack_invert'));and_inputs('clear',q('done'),e['eligible'])
        quiet='('+' && '.join('!'+x for x in [e['fresh'],q('pending'),q('issued'),q('ack_seen'),q('done'),
            e['cleanup'],e['final_request'],e['final_acknowledge'],e['clear_event']])+')'
    pairs.extend([(e['clear_event'],q('clear')),(e['quiet'],quiet)])
    return pairs


def validate_return_receipt(node):
    if not re.fullmatch(r'(?:FourPhase|Click)ReturnReceipt(?:_[0-9]+)?',node['module']):raise ValueError('RETURN_RECEIPT_OWNER')
    ids={'reset','local_reset','clock','request','request_meta','request_sync','ack_state','acknowledge','quiet'}
    if (node['capacity']!=1 or node['channels'] or node['children'] or node['primitives'] or node['timing'] or
        len(node['endpoints'])!=len(ids) or {e['id']:e['width'] for e in node['endpoints']}!={n:1 for n in ids}):
        raise ValueError('RETURN_RECEIPT_INVENTORY')
    return node['module'].startswith('Click')


def return_receipt_bindings(node,scopes):
    validate_return_receipt(node);path=node['rtl_path']
    if scopes.get(path,{}).get('registers',{})!={n:1 for n in ('localReset_release_0','localReset_release_1','requestMeta','requestSync','ack')}:
        raise ValueError('RETURN_RECEIPT_REGISTER_INVENTORY')
    e={x['id']:x['rtl_path'] for x in node['endpoints']}
    return [(e[port],path+'.'+field) for port,field in (('request_meta','requestMeta'),('request_sync','requestSync'),
        ('ack_state','ack'),('local_reset','localReset_release_1'),('clock','clock'),('request','request'),('quiet','quiet'))]+[
        (e['acknowledge'],e['ack_state'])]


def validate_return_receipt_rtl(node,rtl):
    """Close every sequential, initial and combinational writer of the receipt."""
    click=validate_return_receipt(node)
    clean=lambda s:re.sub(r'\s+','',re.sub(r'/\*.*?\*/|//[^\n]*','',s,flags=re.S))
    blocks=[clean(b) for b in re.findall(r'\balways\s*@\(.*?^\s*end\s*//\s*always[^\n]*',rtl,re.S|re.M)]
    release=("always@(posedgeclockorposedgereset)beginif(reset)begin"
        "localReset_release_0<=1'h1;localReset_release_1<=1'h1;endelsebegin"
        "localReset_release_0<=1'h0;localReset_release_1<=localReset_release_0;endend")
    ack='if(requestSync!=ack&quiet)ack<=requestSync;' if click else 'ack<=requestSync&(quiet|ack);'
    receipt=("always@(posedgeclockorposedgelocalReset)beginif(localReset)begin"
        "requestMeta<=1'h0;requestSync<=1'h0;ack<=1'h0;endelsebegin"
        "requestMeta<=request;requestSync<=requestMeta;"+ack+'endend')
    uncommented=re.sub(r'/\*.*?\*/|//[^\n]*','',rtl,flags=re.S)
    registers=[clean(s) for s in re.findall(r'\breg\s+([^;]+);',uncommented)]
    logic=[clean(s) for s in re.findall(r'\blogic\s+([^;]+);',uncommented)]
    # A declaration initializer is an additional state writer even without an
    # initial keyword. Close scalar declarations and the optional random array.
    declared={'localReset_release_0','localReset_release_1','requestMeta','requestSync','ack'}
    if len(registers)!=5 or set(registers)!=declared or logic!=['[31:0]_RANDOM[0:0]']:
        raise ValueError('RETURN_RECEIPT_DECLARATIONS')
    writers=re.findall(r'\b(\w+)\s*<=',uncommented)
    expected={n:2 for n in ('localReset_release_0','localReset_release_1','requestMeta','requestSync','ack')}
    if (blocks!=[release,receipt] or len(re.findall(r'\balways(?:_\w+)?\b',uncommented))!=2 or
        {n:writers.count(n) for n in set(writers)}!=expected):raise ValueError('RETURN_RECEIPT_SEQUENTIAL_LOGIC')
    initial="""initial begin
      `ifdef INIT_RANDOM_PROLOG_
        `INIT_RANDOM_PROLOG_
      `endif
      `ifdef RANDOMIZE_REG_INIT
        _RANDOM[1'b0] = `RANDOM;
        localReset_release_0 = _RANDOM[1'b0][0];
        localReset_release_1 = _RANDOM[1'b0][1];
        requestMeta = _RANDOM[1'b0][2];
        requestSync = _RANDOM[1'b0][3];
        ack = _RANDOM[1'b0][4];
      `endif
      if(reset) begin localReset_release_0 = 1'h1; localReset_release_1 = 1'h1; end
      if(localReset) begin requestMeta = 1'h0; requestSync = 1'h0; ack = 1'h0; end
    end"""
    initials=[clean(b) for b in re.findall(r'\binitial\s+begin.*?^\s*end\s*//\s*initial[^\n]*',rtl,re.S|re.M)]
    if (initials!=[clean(initial)] or len(re.findall(r'\binitial\b',uncommented))!=1 or
        re.search(r'\b(?:force|release|final)\b',uncommented)):raise ValueError('RETURN_RECEIPT_INITIALIZERS')
    wire_drivers=re.findall(r'\bwire\s+(\w+)\s*=\s*([^;]+);',uncommented)
    wires={n:clean(v) for n,v in wire_drivers}
    continuous=[clean(s) for s in re.findall(r'\bassign\s+[^;]+;',uncommented)]
    if (len(wire_drivers)!=4 or len(re.findall(r'\bwire\b',uncommented))!=4 or
        wires!={'packed_6_probe':'clock','packed_8_probe':'reset','localReset':'localReset_release_1','packed_7_probe':'localReset'} or
        continuous!=['assignacknowledge=ack;']):raise ValueError('RETURN_RECEIPT_COMBINATIONAL_LOGIC')


def validate_return_receipts(manifest,directory,scopes):
    def visit(node):
        if re.fullmatch(r'(?:FourPhase|Click)ReturnReceipt(?:_[0-9]+)?',node['module']):
            # CIRCT deduplicates identical receipt instances. The logical
            # contract name may retain _1 while both instances use one emitted
            # module; inspect the actual resolved model, never a guessed alias.
            prefix='Click' if validate_return_receipt(node) else 'FourPhase'
            model=scopes.get(node['rtl_path'],{}).get('model','')
            if not re.fullmatch(prefix+r'ReturnReceipt(?:_[0-9]+)?',model):
                raise ValueError('RETURN_RECEIPT_RESOLVED_OWNER')
            validate_return_receipt_rtl(node,(directory/(model+'.sv')).read_text(encoding='utf-8'))
        for child in node['children']:visit(child['contract'])
    visit(manifest['design'])

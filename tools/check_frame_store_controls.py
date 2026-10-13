# SPDX-License-Identifier: Apache-2.0
"""Replay native frame-bank oracles and reject actual RTL/capture-pin faults.

Every original seed and assertion is preserved. Additional min/opposing cell
profiles retain the 11 ns request, 10 ns data, and declared fixed guards. A
negative passes only at its catalogued compiled fatal source/line/scope.
This is a digital model campaign, not physical timing qualification.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from check_program_return_fatals import fatal_sites, classify_fatal
from check_frame_store import validate_frame_store


CAMPAIGNS=('rotation','por-route','por-captured','por-offered','por-acknowledged','por-return')
PROFILES=('minimum','capture-slow','feedback-slow','route-late','route-early',
          'route-slow-accepted-fast','route-fast-accepted-slow')
FIXED={'request_delay','output_delay','request_guard','return_guard','acknowledge_guard','output_guard'}


def require(value, name):
    if not value:
        raise ValueError('FRAME_STORE_CONTROL_'+name)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hashes(path):
    return {str(p.relative_to(path)):sha(p) for p in sorted(Path(path).rglob('*')) if p.is_file()}


def helper_closure(roots):
    """Include every repository-local Python import, recursively and once."""
    pending=[Path(p).resolve() for p in roots];result=set()
    while pending:
        file=pending.pop()
        if file in result:continue
        require(file.is_file(),'MISSING_HELPER:'+str(file));result.add(file)
        if file.suffix!='.py':continue
        for node in ast.walk(ast.parse(file.read_text(encoding='utf-8'))):
            modules=([alias.name for alias in node.names] if isinstance(node,ast.Import) else
                     [node.module] if isinstance(node,ast.ImportFrom) and node.level==0 and node.module else [])
            for module in modules:
                candidate=file.parent/(module.split('.')[0]+'.py')
                if candidate.is_file():pending.append(candidate.resolve())
    return sorted(result)


def masked(text):
    """Mask comments/strings at original offsets before parsing named ports."""
    token=re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"',re.S)
    return token.sub(lambda m: ''.join('\n' if c=='\n' else ' ' for c in m[0]),text)


def closing(code,start):
    stack=[];pairs={')':'(',']':'[','}':'{'}
    for i in range(start,len(code)):
        if code[i] in '([{':stack.append(code[i])
        elif code[i] in pairs:
            require(bool(stack) and stack.pop()==pairs[code[i]],'PORT_DELIMITER')
            if not stack:return i
    raise ValueError('FRAME_STORE_CONTROL_PORT_UNCLOSED')


def port_span(text,instance,pin):
    code=masked(text)
    matches=list(re.finditer(r'(?<![\w$])'+re.escape(instance)+r'(?![\w$])\s*\(',code))
    require(len(matches)==1,'INSTANCE_ANCHOR:'+instance)
    start=matches[0].end()-1;end=closing(code,start)
    require(re.match(r'\s*;',code[end+1:]) is not None,'INSTANCE_TERMINATOR')
    cursor=start+1;seen=set();result=[]
    while cursor<end:
        while cursor<end and code[cursor].isspace():cursor+=1
        if cursor==end:break
        match=re.match(r'\.([A-Za-z_$][\w$]*)\s*\(',code[cursor:end])
        require(match is not None and match[1] not in seen,'PORT_INVENTORY')
        seen.add(match[1]);a=cursor+match.end()-1;b=closing(code,a)
        if match[1]==pin:result.append((a+1,b))
        cursor=b+1
        while cursor<end and code[cursor].isspace():cursor+=1
        if cursor==end:break
        require(code[cursor]==',','PORT_SEPARATOR');cursor+=1
        require(bool(code[cursor:end].strip()),'PORT_TRAILING_COMMA')
    require(len(result)==1,'PORT_ANCHOR:'+pin)
    return result[0]


def pin_value(text,instance,pin):
    a,b=port_span(text,instance,pin)
    return text[a:b].strip()


def replace_pin(text,instance,pin,value):
    a,b=port_span(text,instance,pin)
    return text[:a]+value+text[b:]


def replace_one(text,pattern,value):
    changed,n=re.subn(pattern,lambda _:value,text,flags=re.S)
    require(n==1,'MUTATION_ANCHOR')
    return changed


def cells(node,prefix=''):
    result={prefix+p['id']:dict(p,owner=node['module']) for p in node['primitives']}
    for child in node['children']:
        nested=cells(child['contract'],prefix+child['id']+'.')
        require(not set(result)&set(nested),'DUPLICATE_CELL')
        result.update(nested)
    return result


def instance(cell):
    return cell['rtl_path'].rsplit('.',1)[1]


def path(cell):
    return 'dut.'+cell['rtl_path'].split('.',1)[1]


def validate_node(node,click):
    require(node['module']==('ClickFrameStore' if click else 'FourPhaseFrameStore'),'OWNER')
    all_cells=cells(node)
    expected=({f'payload{i}' for i in range(4)}|{f'phase{i}' for i in range(4)}|{'route'}) if click else {'route'}
    require({k for k,c in all_cells.items() if c['model']=='ChiselAsyncEventRegister_v1'}==expected,'EVENT_REGISTER_INVENTORY')
    latches={k for k,c in all_cells.items() if c['model']=='ChiselAsyncClosingLatch_v1'}
    require(latches==(set() if click else {f'storage{i}.payload' for i in range(4)}),'LATCH_INVENTORY')
    require({k for k,c in all_cells.items() if c['model']=='ChiselAsyncPhaseRegister_v1'}==({'accepted_phase'} if click else set()),'PHASE_REGISTER_INVENTORY')
    for key,c in all_cells.items():
        if c['id']=='data_delay':require(c['parameters']['DELAY_FS']=='10000000','DATA_BUDGET')
        if c['id']=='request_delay':require(c['parameters']['DELAY_FS']=='11000000','REQUEST_BUDGET')
        if c['id'] in {'request_guard','return_guard','acknowledge_guard'}:
            require(c['parameters']['DELAY_FS']=='32000000','GUARD_BUDGET')
        if c['id']=='output_guard':require(c['parameters']['DELAY_FS']=='110000000','OUTPUT_GUARD')
    return all_cells


def profile(test,node,name):
    require(name in PROFILES,'PROFILE_NAME')
    all_cells=cells(node);changes={}
    assignments=re.findall(r'defparam (dut\.[A-Za-z_][\w.]*)\.DELAY_FS=(\d+);',test)
    require(len(assignments)==len({p for p,_ in assignments}),'DUPLICATE_DELAY')
    by_path={path(c):c for c in all_cells.values()}
    for target,old in assignments:
        require(target in by_path,'UNKNOWN_DELAY_CELL')
        c=by_path[target];identifier=c['id']
        require(identifier not in FIXED,'FIXED_GUARD_OVERRIDDEN')
        if identifier=='data_delay':
            require(old=='10000000','DATA_DELAY_OVERRIDE');continue
        require(1000000<=int(old)<=10000000,'CELL_DELAY_BOUNDS')
        capture=c['model'] in {'ChiselAsyncEventRegister_v1','ChiselAsyncClosingLatch_v1'} or identifier=='route_decode'
        slow=((name=='capture-slow' and capture) or (name=='feedback-slow' and not capture) or
              (name=='route-late' and identifier in {'route','accepted_phase','pending'}) or
              (name=='route-early' and identifier not in {'route','accepted_phase','pending'}) or
              (name=='route-slow-accepted-fast' and identifier=='route') or
              (name=='route-fast-accepted-slow' and identifier=='accepted_phase'))
        new=10000000 if slow else 1000000
        test=replace_one(test,re.escape(f'defparam {target}.DELAY_FS={old};'),f'defparam {target}.DELAY_FS={new};')
        changes[target]=dict(before=int(old),after=new)
    require(bool(changes),'PROFILE_NO_CELLS')
    return test,changes


def source_oracles(sources):
    require(set(sources)=={'bd','click'},'VARIANT_INVENTORY')
    selected={};oracles={}
    for variant,group in sources.items():
        require(set(group)==set(CAMPAIGNS),'SOURCE_INVENTORY:'+variant)
        selected[variant]={};oracles[variant]={}
        for label,value in group.items():
            root=Path(value).resolve();require((root/'export/contract.json').is_file(),'MISSING_SOURCE:'+label)
            expected={f'seed-{i}' for i in (range(1,25) if label=='rotation' else (1,2,7,19))}
            tests=sorted(root.glob('seed-*/testbench.sv'))
            require({p.parent.name for p in tests}==expected,'SEED_INVENTORY:'+variant+':'+label)
            node=json.loads((root/'export/contract.json').read_text(encoding='utf-8'))['manifest']['design']
            validate_node(node,variant=='click')
            validate_frame_store(node,root/'export')
            for test in tests:
                result=json.loads((test.parent/'result.json').read_text(encoding='utf-8'))
                log=(test.parent/'simulation.log').read_text(encoding='utf-8')
                require(result['status']=='PASS' and result['seed']==test.parent.name[5:] and
                    log.count('CA_TEST_PASS seed='+result['seed'])==1 and
                    not re.search(r'FATAL|TIMEOUT|DEADLINE',log),'SOURCE_NOT_PASS')
            selected[variant][label]=root;oracles[variant][label]=tests
    return selected,oracles


def extra_rtl(text,declarations,assignments):
    code=masked(text);matches=list(re.finditer(r'\bendmodule\b',code))
    require(len(matches)==1,'EXTRA_RTL_MODULE')
    at=matches[0].start()
    header=re.search(r'\bmodule\s+\w+\s*\(',code)
    require(header is not None,'EXTRA_RTL_HEADER')
    ending=closing(code,header.end()-1)
    end_header=re.match(r'\s*;',code[ending+1:])
    require(end_header is not None,'EXTRA_RTL_HEADER_END')
    after_header=ending+1+end_header.end()
    return ('`timescale 1fs/1fs\n'+text[:after_header]+'\n'+declarations+'\n'+
            text[after_header:at]+'\n'+assignments+'\n'+text[at:])


def extra_monitors(node,click):
    all_cells=cells(node);blocks=[];reports=[]
    # These measurements supplement, never replace, the original monitors.
    measured={k:c for k,c in all_cells.items() if c['model'] in
        {'ChiselAsyncEventRegister_v1','ChiselAsyncClosingLatch_v1','ChiselAsyncPhaseRegister_v1'}}
    for key,c in measured.items():
        label=key.replace('.','_');p=path(c)
        trigger='closed' if c['model']=='ChiselAsyncClosingLatch_v1' else 'trigger'
        data=c['model']!='ChiselAsyncPhaseRegister_v1'
        blocks.append(f'''
time fs_{label}_rise=0,fs_{label}_fall=0,fs_{label}_change=0;
time fs_{label}_setup=64'h7fffffffffffffff,fs_{label}_hold=64'h7fffffffffffffff;
time fs_{label}_high=64'h7fffffffffffffff,fs_{label}_low=64'h7fffffffffffffff;
integer fs_{label}_captures=0,fs_{label}_setups=0,fs_{label}_holds=0;
bit fs_{label}_rose=0,fs_{label}_fell=0,fs_{label}_seen=0;
always @(posedge {p}.reset) begin fs_{label}_rose=0;fs_{label}_fell=0;fs_{label}_seen=0;end
always @(posedge {p}.{trigger}) if(!{p}.reset) begin
  if(fs_{label}_fell && $time-fs_{label}_fall<=100000) $fatal(1,"FRAME_STORE_PIN_PULSE_LOW_{label}");
  if(fs_{label}_fell && $time-fs_{label}_fall<fs_{label}_low) fs_{label}_low=$time-fs_{label}_fall;
  {'if(fs_'+label+'_seen) begin fs_'+label+'_setups=fs_'+label+'_setups+1; if($time-fs_'+label+'_change<fs_'+label+'_setup) fs_'+label+'_setup=$time-fs_'+label+'_change; end' if data else ''}
  fs_{label}_rise=$time;fs_{label}_rose=1;fs_{label}_captures=fs_{label}_captures+1;
end
always @(negedge {p}.{trigger}) if(!{p}.reset && fs_{label}_rose) begin
  if($time-fs_{label}_rise<fs_{label}_high) fs_{label}_high=$time-fs_{label}_rise;
  fs_{label}_fall=$time;fs_{label}_fell=1;
end
'''+(f'''
always @({p}.d) if(!{p}.reset) begin
  if(fs_{label}_rose) begin fs_{label}_holds=fs_{label}_holds+1;
    if($time-fs_{label}_rise<fs_{label}_hold) fs_{label}_hold=$time-fs_{label}_rise;end
  fs_{label}_change=$time;fs_{label}_seen=1;
end
''' if data else ''))
        reports.append(f'''if(fs_{label}_captures==0) $fatal(1,"FRAME_STORE_PIN_INACTIVE_{label}");
$display("FRAME_STORE_PIN {label} captures=%0d setups=%0d holds=%0d setup_fs=%0d hold_fs=%0d high_fs=%0d low_fs=%0d",fs_{label}_captures,fs_{label}_setups,fs_{label}_holds,fs_{label}_setup,fs_{label}_hold,fs_{label}_high,fs_{label}_low);''')
    if not click:
        for i in range(4):
            active=[path(all_cells[f'storage{i}.{cell}'])+'.q' for cell in ('a','b','acknowledge','long_hold')]
            blocks.append(f'''always @(available_{i} or {" or ".join(active)} or reset) begin #1;
  if(!reset && available_{i} && ({{{','.join(active)}}}!==4'b0))
    $fatal(1,"FRAME_STORE_AVAILABLE_BEFORE_INTERNAL_RETURN_{i}");
end''')
    else:
        packed='{in_bits_ingress_frame_length,in_bits_ingress_frame_overflow,'+','.join(
            f'in_bits_ingress_frame_bytes_{i}' for i in reversed(range(33)))+',in_bits_ingress_resetActive,in_bits_ingress_programBusy,in_bits_resetEpoch}'
        blocks.append(f'''
integer fs_offer_seq=0,fs_copy_seq[0:3]; integer fs_init;
reg [1:0] fs_offered_slot; reg [336:0] fs_offered_bits;
time fs_copy_time[0:3];
initial for(fs_init=0;fs_init<4;fs_init=fs_init+1) begin fs_copy_seq[fs_init]=0;fs_copy_time[fs_init]=0;end
always @(in_req) if(!reset) begin fs_offer_seq=fs_offer_seq+1;fs_offered_slot=nextBank;fs_offered_bits={packed};end
always @(posedge {path(all_cells['capture'])}.q) if(!reset) begin
  fs_copy_seq[nextBank]=fs_offer_seq;fs_copy_time[nextBank]=$time;
end
always @(in_ack) begin #1;if(!reset && in_req==in_ack) begin
  case(fs_offered_slot)
'''+''.join(f'''{i}: begin if(fs_copy_seq[{i}]!=fs_offer_seq ||
    $time-fs_copy_time[{i}]<={path(all_cells[f'payload{i}'])}.DELAY_FS)
      $fatal(1,"FRAME_STORE_ACK_BEFORE_CAPTURE_{i}");
    if({path(all_cells[f'payload{i}'])}.q!==fs_offered_bits)
      $fatal(1,"FRAME_STORE_ACK_CAPTURE_IDENTITY_{i}"); end
''' for i in range(4))+'''  endcase
end end
''')
    return '\n'.join(blocks),'\n'.join(reports)


def instrument(test,node,click):
    anchor='timeunit 1fs; timeprecision 1fs;';marker='$display("CA_TEST_PASS'
    require(test.count(anchor)==1 and test.count(marker)==1,'TESTBENCH_SHAPE')
    blocks,reports=extra_monitors(node,click)
    # Icarus resolves event-expression names in declaration order. Insert after
    # the original top-level ports/instance/defparams and before its monitors.
    insertion=re.search(r'^integer delivered_[A-Za-z_][\w]* = 0;',test,re.M)
    require(insertion is not None,'MONITOR_INSERTION')
    at=insertion.start()
    return (test[:at]+blocks+'\n'+test[at:]).replace(marker,reports+'\n'+marker)


def mutation_jobs(click):
    jobs=[]
    def add(name,expected,fixture='rotation',profile_name='minimum'):
        jobs.append(dict(name=name,expected=expected if isinstance(expected,list) else [expected],fixture=fixture,profile=profile_name))
    if click:
        add('capture-memory-bypassed','FRAME_STORE_COPY_MISSED_ORIGINAL_A',profile_name='route-late')
        add('global-bank-phase','FRAME_STORE_UNSELECTED_PHASE_1')
        add('input-phase-as-bank-phase','FRAME_STORE_UNSELECTED_PHASE_0')
        add('unselected-payload-cleared','DATA_HOLD banks_0')
        add('selected-bank-disconnected','FRAME_STORE_COPY_MISSED_ORIGINAL_A')
        add('global-history-disconnected','FRAME_STORE_COPY_MISSED_ORIGINAL_A')
        add('ack-before-capture','FRAME_STORE_ACK_BEFORE_CAPTURE_0',profile_name='feedback-slow')
        add('por-phase-disconnected','UNKNOWN_HANDSHAKE in',fixture='por-offered')
        registers=[f'{kind}{i}' for i in range(4) for kind in ('payload','phase')]+['accepted_phase','route']
        for register in registers:
            add('disconnect-trigger-'+register,'FRAME_STORE_CAPTURE_DISTRIBUTION')
            add('short-high-'+register,'FRAME_STORE_PULSE_HIGH_'+register)
            # Both independent monitors now observe every actual trigger edge.
            # Icarus may schedule either exact causal assertion first.
            add('short-low-'+register,['FRAME_STORE_PULSE_LOW_'+register,'FRAME_STORE_PIN_PULSE_LOW_'+register])
            add('late-trigger-'+register,'FRAME_STORE_CAPTURE_DISTRIBUTION')
            if register!='accepted_phase':
                add('setup-'+register,['FRAME_STORE_SETUP_'+register,'FRAME_STORE_HOLD_'+register])
                add('hold-'+register,'FRAME_STORE_HOLD_'+register)
    else:
        add('route-tag-disconnected','FRAME_STORE_COPY_MISSED_ORIGINAL_A')
        # Routing from the increment feedback selects the next bank instead of
        # retaining the active captured tag through old source RTZ.
        add('route-live-slot','FRAME_STORE_COPY_MISSED_ORIGINAL_A')
        add('selected-bank-disconnected','FRAME_STORE_COPY_MISSED_ORIGINAL_A')
        add('request-guard-bypassed','HANDSHAKE_ORDER in',fixture='por-return',profile_name='capture-slow')
        add('return-guard-bypassed','FRAME_STORE_AVAILABLE_BEFORE_INTERNAL_RETURN_0')
        add('por-route-disconnected','UNKNOWN_HANDSHAKE in',fixture='por-offered')
        add('setup-route',['FRAME_STORE_SETUP_route','FRAME_STORE_HOLD_route'])
        add('hold-route','FRAME_STORE_HOLD_route')
        add('short-high-route','FRAME_STORE_PULSE_HIGH_route')
        add('short-low-route',['FRAME_STORE_PULSE_LOW_route','FRAME_STORE_PIN_PULSE_LOW_route'])
        add('latch-setup',['FRAME_STORE_LATCH_SETUP_0','FRAME_STORE_LATCH_HOLD_0'])
        add('latch-hold','FRAME_STORE_LATCH_HOLD_0')
    add('route-counter-stuck','FRAME_STORE_NATIVE_ROUTE_ADVANCE' if click else 'FRAME_STORE_ONE_NEW_COPY_PER_OFFER')
    add('route-reset-wrong','FRAME_STORE_NATIVE_ROUTE_ORDINAL')
    add('payload-bit-corrupted','FRAME_STORE_ACK_CAPTURE_IDENTITY_0' if click else 'FRAME_STORE_COPY_AT_A_0')
    add('epoch-bit-corrupted','FRAME_STORE_ACK_CAPTURE_IDENTITY_0' if click else 'FRAME_STORE_COPY_AT_A_0')
    return jobs


def mutate_rtl(texts,node,fault,click):
    all_cells=cells(node);top=node['module']+'.sv';text=texts[top]
    def get(key,pin):return pin_value(texts[all_cells[key]['owner']+'.sv'],instance(all_cells[key]),pin)
    def set_pin(key,pin,value):
        c=all_cells[key];file=c['owner']+'.sv'
        texts[file]=replace_pin(texts[file],instance(c),pin,value)
    if fault=='route-counter-stuck':set_pin('route','d',get('route','q'))
    elif fault=='route-reset-wrong':
        inst=instance(all_cells['route'])
        pattern=r'(ChiselAsyncEventRegister_v1\s*#\s*\([^;]*?\.RESET_VALUE\s*\(\s*)'+('0' if click else '3')+r'(\s*\)[^;]*?\)\s*'+re.escape(inst)+r'\s*\()'
        changed,count=re.subn(pattern,lambda m:m[1]+('1' if click else '0')+m[2],texts[top])
        require(count==1,'ROUTE_RESET_BINDING');texts[top]=changed
    elif fault=='capture-memory-bypassed':
        q=get('capture','q');pending=get('capture','common');ready=get('capture','rising')
        set_pin('capture','q','fs_unused_capture')
        texts[top]=extra_rtl(texts[top],'wire fs_unused_capture;',f'assign #1000000 {q} = {pending} & {ready};')
    elif fault=='route-tag-disconnected':set_pin('route','d',"2'h0")
    elif fault=='route-live-slot':set_pin('route_decode','a',"4'h1 << nextBank")
    elif fault=='selected-bank-disconnected':
        set_pin('capture' if click else 'route0','rising' if click else 'd',"1'b0" if click else "2'b0")
    elif fault=='global-history-disconnected':set_pin('pending','b',"1'b0")
    elif fault=='global-bank-phase':
        for i in range(4):set_pin(f'phase{i}','d','~'+get(f'phase{i}','q'))
    elif fault=='input-phase-as-bank-phase':set_pin('phase0','d','in_req')
    elif fault=='unselected-payload-cleared':
        a=get('data_delay','a');q=get('payload0','q')
        set_pin('data_delay','a',replace_one(a,r':\s*'+re.escape(q)+r'\b',": 337'h0"))
    elif fault=='request-guard-bypassed':
        for i in range(4):
            old=get(f'route{i}','d')
            wire=get('request_guard','q')
            require(old.count(wire)==1,'REQUEST_BRANCH')
            set_pin(f'route{i}','d',old.replace(wire,'in_req'))
    elif fault=='return-guard-bypassed':
        q=get('return_guard','q');a=get('return_guard','a')
        set_pin('return_guard','q','fs_unused_return')
        texts[top]=extra_rtl(texts[top],'wire [3:0] fs_unused_return;',f'assign {q} = {a};')
    elif fault=='ack-before-capture':
        q=get('acknowledge_guard','q');set_pin('acknowledge_guard','q','fs_unused_ack')
        texts[top]=extra_rtl(texts[top],'wire fs_unused_ack;',f'assign #1000000 {q} = in_req;')
    elif fault in ('por-phase-disconnected','por-route-disconnected'):
        set_pin('accepted_phase' if click else 'route','reset',"1'b0")
    elif fault in ('payload-bit-corrupted','epoch-bit-corrupted'):
        bit=64 if fault=='payload-bit-corrupted' else 63
        if click:set_pin('payload0','d',f"({get('payload0','d')} ^ 337'h{1<<bit:x})")
        else:
            child=next(c['contract'] for c in node['children'] if c['id']=='storage0')
            inst=child['rtl_path'].rsplit('.',1)[1]
            pin='in_bits_ingress_frame_bytes_0' if fault=='payload-bit-corrupted' else 'in_bits_resetEpoch'
            old=pin_value(texts[top],inst,pin)
            texts[top]=replace_pin(texts[top],inst,pin,f"({old} ^ {8 if bit==64 else 64}'h{1 if bit==64 else 1<<63:x})")
    elif fault in ('latch-setup','latch-hold') or any(fault.startswith(k+'-') for k in
            ('disconnect-trigger','short-high','short-low','late-trigger','setup','hold')):
        latch=fault.startswith('latch-')
        if latch:kind=fault[6:];key='storage0.payload';trigger_pin='closed'
        else:
            prefix=next(k for k in ('disconnect-trigger','short-high','short-low','late-trigger','setup','hold') if fault.startswith(k+'-'))
            kind=prefix;key=fault[len(prefix)+1:];trigger_pin='trigger'
        c=all_cells[key];file=c['owner']+'.sv';trigger=get(key,trigger_pin)
        width=int(c['parameters'].get('WIDTH','1'))
        if kind=='disconnect-trigger':set_pin(key,trigger_pin,"1'b0")
        elif kind=='setup':set_pin(key,'d',f'{{{width}{{{trigger}}}}}')
        elif kind=='hold':
            old=get(key,'d');set_pin(key,'d',f'({old} ^ {{{width}{{fs_delayed_trigger}}}})')
            texts[file]=extra_rtl(texts[file],'wire fs_delayed_trigger;',f'assign #100000 fs_delayed_trigger = {trigger};')
        else:
            set_pin(key,trigger_pin,'fs_mutated_trigger')
            if kind=='short-high':assign=f'assign #100000 fs_delayed_trigger = {trigger};\nassign fs_mutated_trigger = {trigger} & ~fs_delayed_trigger;'
            elif kind=='short-low':assign=f'assign #1000000 fs_delayed_trigger = {trigger};\nassign #1100000 fs_recovered_trigger = {trigger};\nassign fs_mutated_trigger = {trigger} & (~fs_delayed_trigger | fs_recovered_trigger);'
            elif kind=='late-trigger':assign=f'assign #200000 fs_mutated_trigger = {trigger};'
            else:raise ValueError('FRAME_STORE_CONTROL_PIN_MUTATION')
            texts[file]=extra_rtl(texts[file],'wire fs_delayed_trigger,fs_recovered_trigger,fs_mutated_trigger;',assign)
    else:raise ValueError('FRAME_STORE_CONTROL_UNKNOWN_FAULT')
    return texts


def parse_metrics(log,node):
    expected={k.replace('.','_') for k,c in cells(node).items() if c['model'] in
        {'ChiselAsyncEventRegister_v1','ChiselAsyncClosingLatch_v1','ChiselAsyncPhaseRegister_v1'}}
    result={}
    for line in log.splitlines():
        if not line.startswith('FRAME_STORE_PIN '):continue
        m=re.fullmatch(r'FRAME_STORE_PIN (\w+) captures=(\d+) setups=(\d+) holds=(\d+) setup_fs=(\d+) hold_fs=(\d+) high_fs=(\d+) low_fs=(\d+)',line)
        require(m is not None and m[1] not in result,'METRIC_SHAPE')
        result[m[1]]=dict(zip(('captures','setups','holds','setup_fs','hold_fs','high_fs','low_fs'),map(int,m.groups()[1:])))
    require(set(result)==expected and all(v['captures']>0 for v in result.values()),'CAPTURE_ACTIVITY')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();sources=json.loads(args.sources.read_text(encoding='utf-8'))
    selected,oracles=source_oracles(sources)
    out=args.out.resolve();require(not out.exists(),'OUTPUT_EXISTS')
    require(all(not out.is_relative_to(p) and not p.is_relative_to(out) for g in selected.values() for p in g.values()),'SOURCE_OVERLAP')
    out.mkdir(parents=True)
    tools=Path(__file__).resolve().parent
    helpers=helper_closure([tools/'check_frame_store_controls.py',tools/'test_frame_store_controls.py',
        tools.parent/'verification/src/test/scala/riscay/AsyncFrameStoreSpec.scala',
        tools.parent/'designs/four-phase-bd/src/main/scala/riscay/bd/FourPhaseFrameStore.scala',
        tools.parent/'designs/two-phase-click/src/main/scala/riscay/click/ClickFrameStore.scala'])
    result=dict(status='RUNNING',sources_sha256=sha(args.sources),helpers_sha256={str(p):sha(p) for p in helpers},
        source_sha256={variant:{label:hashes(root) for label,root in group.items()} for variant,group in selected.items()},cases={})
    def save():(out/'results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    def run(command,directory,label):
        try:
            completed=subprocess.run(command,cwd=directory,text=True,capture_output=True,timeout=90)
            log=completed.stdout+completed.stderr;code=completed.returncode;timed_out=False
        except subprocess.TimeoutExpired as error:
            log=str(error.stdout or '')+str(error.stderr or '');code=None;timed_out=True
        logfile=directory/(label+'.log');logfile.write_text(log,encoding='utf-8')
        return dict(command=command,exit_code=code,timed_out=timed_out,log_sha256=sha(logfile)),log
    def simulate(variant,label,oracle,profile_name=None,job=None):
        source=selected[variant][label];click=variant=='click'
        name=variant+'-'+label+'-'+(job['name'] if job else oracle.parent.name+'-'+(profile_name or 'original'))
        case=out/name;shutil.copytree(source/'export',case)
        manifest=json.loads((case/'contract.json').read_text(encoding='utf-8'))['manifest'];node=manifest['design']
        policy=validate_frame_store(node,case)
        original=oracle.read_text(encoding='utf-8');test=original;changes={}
        if profile_name:test,changes=profile(test,node,profile_name)
        test=instrument(test,node,click)
        (case/'testbench.sv').write_text(test,encoding='utf-8')
        files=[line.strip() for line in (case/'filelist.f').read_text(encoding='utf-8').splitlines() if line.strip()]
        require(files and len(files)==len(set(files)) and all((case/f).resolve().is_relative_to(case) and (case/f).is_file() for f in files),'FILELIST')
        expected=job['expected'] if job else []
        before={f:(case/f).read_text(encoding='utf-8') for f in files}
        modified={}
        if job:
            texts={Path(f).name:v for f,v in before.items()};original_texts=dict(texts)
            mutate_rtl(texts,node,job['name'],click)
            for f in files:
                if texts[Path(f).name]!=original_texts[Path(f).name]:
                    (case/f).write_text(texts[Path(f).name],encoding='utf-8');modified[f]=dict(before=sha(source/'export'/f),after=sha(case/f))
            require(bool(modified),'EMPTY_ACTUAL_MUTATION')
        record=dict(source=str(source),oracle=str(oracle),original_testbench_sha256=sha(oracle),
            source_structural_policy=policy,
            original_assertions_preserved=True,profile=profile_name or 'original',cell_overrides=changes,mutation=job,
            mutated_rtl=modified,testbench_sha256=sha(case/'testbench.sv'),rtl_sha256={f:sha(case/f) for f in files},
            fatal_sites=fatal_sites(test,expected) if expected else [])
        result['cases'][name]=record;save()
        record['compile'],log=run(['iverilog','-g2012','-s','Testbench','-o','store.vvp',
            *[str((case/f).resolve()) for f in files],'testbench.sv'],case,'compile')
        require(record['compile']['exit_code']==0 and not record['compile']['timed_out'],'COMPILE:'+name+':'+log[-1200:])
        record['binary_sha256']=sha(case/'store.vvp')
        record['simulation'],log=run(['vvp','store.vvp'],case,'simulation');save()
        if expected:record['fatal_records']=classify_fatal(record['compile'],record['simulation'],log,record['fatal_sites'])
        else:
            require(record['simulation']['exit_code']==0 and not record['simulation']['timed_out'] and
                len(re.findall(r'^CA_TEST_PASS seed=\d+$',log,re.M))==1 and not re.search(r'FATAL|TIMEOUT|DEADLINE',log),'POSITIVE:'+name+':'+log[-1600:])
            record['capture_metrics']=parse_metrics(log,node)
        require(record['binary_sha256']==sha(case/'store.vvp') and record['testbench_sha256']==sha(case/'testbench.sv') and
            record['rtl_sha256']=={f:sha(case/f) for f in files},'ARTIFACT_CHANGED')
        record['status']='PASS';save();print(name,'PASS',flush=True)
    try:
        for variant in ('bd','click'):
            for label in CAMPAIGNS:
                for oracle in oracles[variant][label]:simulate(variant,label,oracle)
                for profile_name in PROFILES:simulate(variant,label,selected[variant][label]/'seed-1/testbench.sv',profile_name)
            for job in mutation_jobs(variant=='click'):
                label=job['fixture'];simulate(variant,label,selected[variant][label]/'seed-1/testbench.sv',job['profile'],job)
        require(result['sources_sha256']==sha(args.sources),'SOURCE_INDEX_CHANGED')
        require(result['helpers_sha256']=={str(p):sha(p) for p in helpers},'HELPERS_CHANGED')
        require(result['source_sha256']=={v:{label:hashes(root) for label,root in g.items()} for v,g in selected.items()},'ORIGINALS_CHANGED')
        result.update(status='PASS',positives=sum(not r['mutation'] for r in result['cases'].values()),
            negatives=sum(bool(r['mutation']) for r in result['cases'].values()),
            scope='Actual native frame-store RTL, all source seeds and fixed-budget opposing profiles; original assertions unchanged; no physical timing qualification')
        save();print('FRAME_STORE_CONTROLS_PASS',flush=True)
    except BaseException as error:
        result.update(status='FAILED',error=repr(error));save();raise


if __name__=='__main__':main()

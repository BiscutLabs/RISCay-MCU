# SPDX-License-Identifier: Apache-2.0
"""Actual-pin campaign for the isolated experimental native byte owners.

Each attempt gets a fresh directory. A failure writes a FAILED receipt and is
retained. Only a complete passing campaign can receive the digital PASS status.
"""
from pathlib import Path
import argparse, hashlib, json, re, subprocess, traceback, os, shutil
from macro_byte_source_binding import SOURCE_FILES, verify_cohort, verify_rtl_inventory

BASE=Path(__file__).resolve().parent
ROOT=BASE.parent
TESTS=ROOT/'verification/src/test/resources/riscay/macro-byte'
EXPECTED_PRIMITIVES = {'bd': {'stop_history': 'ChiselAsyncAsymmetricC_v1', 'armed_history': 'ChiselAsyncAsymmetricC_v1', 'request_guard': 'ChiselAsyncControlGate_v1', 'launch_contender': 'ChiselAsyncAsymmetricC_v1', 'retired_history': 'ChiselAsyncAsymmetricC_v1', 'launch_stop_mutex': 'ChiselAsyncMutex_v1', 'pin_payload': 'ChiselAsyncClosingLatch_v1', 'pins_guard': 'ChiselAsyncControlGate_v1', 'source_hold_guard': 'ChiselAsyncControlGate_v1', 'setup_guard': 'ChiselAsyncControlGate_v1', 'cen_driver': 'ChiselAsyncControlGate_v1', 'clock_driver': 'ChiselAsyncControlGate_v1', 'high_guard': 'ChiselAsyncControlGate_v1', 'access_guard': 'ChiselAsyncControlGate_v1', 'period_guard': 'ChiselAsyncControlGate_v1', 'period_history': 'ChiselAsyncAsymmetricC_v1', 'capture_driver': 'ChiselAsyncControlGate_v1', 'result_payload': 'ChiselAsyncEventRegister_v1', 'capture_hold_guard': 'ChiselAsyncControlGate_v1', 'pulse_done_history': 'ChiselAsyncAsymmetricC_v1', 'low_guard': 'ChiselAsyncControlGate_v1', 'cycle_history': 'ChiselAsyncAsymmetricC_v1', 'publication_guard': 'ChiselAsyncControlGate_v1', 'result_taken_history': 'ChiselAsyncAsymmetricC_v1', 'result_offer': 'ChiselAsyncControlGate_v1'}, 'click': {'stop_history': 'ChiselAsyncAsymmetricC_v1', 'armed_history': 'ChiselAsyncAsymmetricC_v1', 'request_guard': 'ChiselAsyncControlGate_v1', 'launch_contender': 'ChiselAsyncAsymmetricC_v1', 'retired_history': 'ChiselAsyncAsymmetricC_v1', 'launch_stop_mutex': 'ChiselAsyncMutex_v1', 'pin_payload': 'ChiselAsyncEventRegister_v1', 'target_input': 'ChiselAsyncEventRegister_v1', 'target_output': 'ChiselAsyncEventRegister_v1', 'pins_guard': 'ChiselAsyncControlGate_v1', 'source_hold_guard': 'ChiselAsyncControlGate_v1', 'setup_guard': 'ChiselAsyncControlGate_v1', 'cen_driver': 'ChiselAsyncControlGate_v1', 'clock_driver': 'ChiselAsyncControlGate_v1', 'high_guard': 'ChiselAsyncControlGate_v1', 'access_guard': 'ChiselAsyncControlGate_v1', 'period_guard': 'ChiselAsyncControlGate_v1', 'period_history': 'ChiselAsyncAsymmetricC_v1', 'capture_driver': 'ChiselAsyncControlGate_v1', 'result_payload': 'ChiselAsyncEventRegister_v1', 'capture_hold_guard': 'ChiselAsyncControlGate_v1', 'pulse_done_history': 'ChiselAsyncAsymmetricC_v1', 'low_guard': 'ChiselAsyncControlGate_v1', 'cycle_history': 'ChiselAsyncAsymmetricC_v1', 'publication_guard': 'ChiselAsyncControlGate_v1', 'accepted_input': 'ChiselAsyncEventRegister_v1', 'published_output': 'ChiselAsyncEventRegister_v1'}}
MACRO='gf180mcu_ocd_ip_sram__sram1024x8m8wm1'
IV=None; VVP=None; BACKEND=None

def executable(value):
    resolved=shutil.which(value)
    if resolved is None:
        raise RuntimeError('REQUIRED_SIMULATOR_NOT_FOUND:'+value)
    return Path(resolved).resolve()

def backend_path(compiler, configured):
    if configured:
        candidates=[Path(configured).resolve()]
    else:
        prefix=compiler.parent.parent
        candidates=[prefix/'lib/ivl',prefix/'lib64/ivl',*sorted((prefix/'lib').glob('*/ivl'))]
    matches=[x for x in candidates if x.is_dir() and any(x.glob('ivl*'))]
    if len(matches)!=1:
        raise RuntimeError('SET_IVERILOG_BACKEND_TO_EXACT_ACTIVE_DIRECTORY')
    return matches[0]
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,s): p.write_text(s,encoding='utf-8',newline='\n')
def command(argv,cwd,log):
    p=subprocess.run([str(x) for x in argv],cwd=cwd,capture_output=True,text=True,timeout=90)
    write(log,p.stdout+p.stderr)
    return p.returncode,p.stdout+p.stderr

def inventory(export,variant):
    contract=json.loads((export/'contract.json').read_text())
    design=contract['manifest']['design']; top=contract['manifest']['top']
    expected=('Click' if variant=='click' else 'FourPhase')+'MacroByte'
    assert top==expected+'Fixture',top
    children=design['children']; assert len(children)==1
    owner=children[0]['contract']; assert children[0]['id']=='byte_owner'
    assert owner['module']==expected+'Owner' and not owner['children']
    primitives={p['id']:p for p in owner['primitives']}
    assert len(primitives)==len(owner['primitives'])
    assert {key:p['model'] for key,p in primitives.items()}==EXPECTED_PRIMITIVES[variant],'EXACT_NATIVE_PRIMITIVE_INVENTORY'
    allowed={'ChiselAsyncControlGate_v1','ChiselAsyncAsymmetricC_v1',
             'ChiselAsyncClosingLatch_v1','ChiselAsyncEventRegister_v1','ChiselAsyncMutex_v1'}
    assert all(p['model'] in allowed for p in primitives.values())
    assert primitives['pin_payload']['parameters']['WIDTH']=='42'
    assert primitives['result_payload']['parameters']['WIDTH']=='8'
    assert primitives['launch_stop_mutex']['model']=='ChiselAsyncMutex_v1'
    assert sum(p['model']=='ChiselAsyncMutex_v1' for p in primitives.values())==1
    assert primitives['pin_payload']['model']==('ChiselAsyncEventRegister_v1' if variant=='click' else 'ChiselAsyncClosingLatch_v1')
    paths={key:'dut.'+p['rtl_path'].split('.',1)[1] for key,p in primitives.items()}
    sources={p.name:p.read_text() for p in export.glob('*.sv') if p.name!='ref_'+top+'.sv'}
    assert top+'.sv' in sources and owner['module']+'.sv' in sources
    toptext=sources[top+'.sv']
    matches=re.findall(r'\b'+re.escape(MACRO)+r'\s+(\w+)\s*\(',toptext)
    assert len(matches)==1, matches
    macro='dut.'+matches[0]
    ownertext=sources[owner['module']+'.sv']
    verify_rtl_inventory(contract, sources, (export/'filelist.f').read_text())
    bindings=[]
    for signal,width in [('CLK',1),('CEN',1),('GWEN',1),('WEN',8),('A',10),('D',8),('Q',8)]:
        bindings.append(f'wire {"" if width==1 else f"[{width-1}:0] "}macro{signal}={macro}.{signal};')
    pin=paths['pin_payload']; result=paths['result_payload']
    trigger='trigger' if variant=='click' else 'closed'
    bindings += [f'wire [41:0] pinD={pin}.d;',f'wire pinTrigger={pin}.{trigger};',
                 f'wire pinReset={pin}.reset;',f'wire [7:0] resultD={result}.d;',
                 f'wire resultTrigger={result}.trigger;',f'wire resultReset={result}.reset;',
                 f'wire arbLaunch={paths["launch_stop_mutex"]}.request[0];']
    phase=[]
    if variant=='click':
        for key in ('target_input','target_output','accepted_input','published_output'):
            p=paths[key]
            phase.append(f'PinAperture #(1,1000000,2000000,1000000,1000000,"{key}") m_{key}(railValid,{p}.trigger,1\'b1,{p}.d);')
    return dict(top=top,owner=owner['module'],primitives=primitives,paths=paths,macro=macro,
                sources=sources,bindings='\n'.join(bindings),phase='\n'.join(phase))

def actual_port_mutation(sources,owner,instance,port,expression):
    # Locate one exact instance block, then mutate one actual input connection.
    text=sources[owner+'.sv']
    pattern=re.compile(r'\b'+re.escape(instance)+r'\s*\((.*?)\);',re.S)
    matches=list(pattern.finditer(text)); assert len(matches)==1,(instance,len(matches))
    m=matches[0]; block=m.group(0)
    pat=re.compile(r'(\.'+re.escape(port)+r'\s*\()([^\n]*?)(\)\s*[,\n])')
    b,n=pat.subn(lambda x:x.group(1)+expression(x.group(2).strip())+x.group(3),block)
    assert n==1,(instance,port,n)
    sources[owner+'.sv']=text[:m.start()]+b+text[m.end():]

def cases(variant):
    # Positive opposing delays are explicit finite digital parameter overrides.
    c=[dict(name='full-default',scenario='full'),
       dict(name='full-fast-control-slow-data',scenario='full',overrides={'clock_driver':100000,'pin_payload':2000000,'result_payload':2000000}),
       dict(name='full-slow-control-fast-data',scenario='full',overrides={'clock_driver':2000000,'pin_payload':100000,'result_payload':100000}),
       dict(name='rearm-idle-positive',scenario='rearm-idle'),
       dict(name='closed-offer-positive',scenario='closed-offer')]
    for policy in (0,1,2,3):
        c.append(dict(name=f'competition-policy-{policy}',scenario='competition',mutex=(policy,10000000,10000000,17)))
    c.append(dict(name='unresolved-1us',scenario='unresolved',mutex=(0,1000000000,1000000000,1)))
    c += [
      dict(name='bad-source-reset',scenario='early-source-reset',fatal='A4_SOURCE_RESET_BEFORE_JOIN:source.reset'),
      dict(name='bad-old-request-rebase',scenario='old-request-rebase',fatal='A4_REBASE_REQUIRED:external.phases'),
      dict(name='bad-pin-reset',scenario='stop-high',port=('pin_payload','reset','reset-stop'),fatal='A4_PIN_RESET_BEFORE_JOIN:pin_payload.reset'),
      dict(name='bad-pulse-clear',scenario='stop-high',port=('clock_driver','a','gate-stop'),fatal='A4_MACRO_HIGH:macro.CLK'),
      dict(name='bad-setup-guard',scenario='setup-pins',overrides={'setup_guard':6000000},fatal='A4_PIN_SETUP:macro.CEN:0'),
      dict(name='bad-early-capture',scenario='read',fault='early-capture',fatal='A4_READ_ACCESS:result.trigger'),
      dict(name='bad-high',scenario='setup-pins',fault='high',fatal='A4_MACRO_HIGH:macro.CLK'),
      dict(name='bad-low',scenario='setup-pins',fault='low',fatal='A4_MACRO_LOW:macro.CLK'),
      dict(name='bad-period',scenario='setup-pins',fault='period',fatal='A4_MACRO_PERIOD:macro.CLK'),
      dict(name='bad-a9-setup',scenario='setup-pins',fault='a9',fatal='A4_PIN_SETUP:macro.A:9'),
      dict(name='bad-input-hold',scenario='setup-pins',fault='hold',fatal='A4_PIN_HOLD:macro.D:0'),
      dict(name='bad-source-capture-hold',scenario='setup-pins',fault='source-hold',fatal='A4_PIN_HOLD:source.capture:1'),
      dict(name='bad-result-capture-hold',scenario='read',fault='result-hold',fatal='A4_PIN_HOLD:result.capture:0'),
      dict(name='a9-monitor-omission-witness',scenario='setup-pins',fault='a9',monitor_omission=True),
      dict(name='bad-stale-event-rearm',scenario='rearm-idle',fault='stale-event',fatal='A4_STALE_EVENT_AFTER_REBASE:macro.CLK'),
      dict(name='bad-post-stop-contender',scenario='closed-offer',fault='post-stop',fatal='A4_CONTENDER_AFTER_STOP:mutex.request0')]
    capture_targets=[('pin_payload','source.capture'),('result_payload','result.capture')]
    if variant=='bd':
        c.append(dict(name='bad-bd-early-result-retirement',scenario='setup-pins',
                      fault='bd-retire',fatal='A4_DUPLICATE_PUBLICATION:result.req'))
    if variant=='click':
        capture_targets += [(x,x) for x in ('target_input','target_output','accepted_input','published_output')]
    for target,label in capture_targets:
        for edge in ('high','low'):
            c.append(dict(name=f'bad-{target}-{edge}',scenario='setup-pins',
                fault='capture-'+edge,capture_target=target,fatal=f'A4_CAPTURE_{edge.upper()}:{label}'))
    c += [dict(name='bad-idle-cen',scenario='rearm-idle',fault='idle-cen',fatal='A4_CEN_WITHOUT_GRANT:macro.CEN'),
          dict(name='bad-disabled-cen',scenario='full',fault='disabled-cen',fatal='A4_CEN_DISABLED_BYTE:macro.CEN'),
          dict(name='bad-held-result',scenario='full',fault='held-result',fatal='A4_HELD_RESULT:result.bits')]
    if variant=='bd':
        c.append(dict(name='bad-bd-rtz-result',scenario='full',fault='rtz-result',fatal='A4_RESULT_RTZ_RETENTION:result.bits'))
    return c

def fault_wiring(info,sources,variant,case):
    """Isolate faults at exact input expressions; never force a collapsed grant net."""
    fault=case.get('fault')
    if not fault: return
    def primitive(key,port,fn):
        actual_port_mutation(sources,info['owner'],info['primitives'][key]['rtl_path'].split('.')[-1],port,fn)
    def macro(port,fn):
        actual_port_mutation(sources,info['top'],info['macro'].split('.')[-1],port,fn)
    if fault in ('high','low','period','stale-event'):
        macro('CLK',lambda old:f'(Testbench.faultClockMode==1 ? 1\'b0 : (Testbench.faultClockMode==2 ? 1\'b1 : ({old})))')
    elif fault=='a9': macro('A',lambda old:f'({old}) ^ (Testbench.faultActive ? 10\'h200 : 10\'h000)')
    elif fault=='hold': macro('D',lambda old:f'({old}) ^ (Testbench.faultActive ? 8\'h01 : 8\'h00)')
    elif fault=='source-hold': primitive('pin_payload','d',lambda old:f'({old}) ^ (Testbench.faultActive ? 42\'h2 : 42\'h0)')
    elif fault=='result-hold': primitive('result_payload','d',lambda old:f'({old}) ^ (Testbench.faultActive ? 8\'h01 : 8\'h00)')
    elif fault=='early-capture': primitive('result_payload','trigger',lambda old:f'({old}) | Testbench.faultActive')
    elif fault=='post-stop': primitive('launch_stop_mutex','request',lambda old:f'({old}) | (Testbench.faultActive ? 2\'b01 : 2\'b00)')
    elif fault=='bd-retire':
        def regression(old):
            assert variant=='bd' and old=='publication',('WRONG_BD_RETURN_BINDING',old)
            return 'cycleComplete'
        primitive('result_taken_history','common',regression)
    elif fault in ('idle-cen','disabled-cen'):
        macro('CEN',lambda old:f'({old}) & ~Testbench.faultActive')
    elif fault in ('held-result','rtz-result'):
        top=info['top']+'.sv'; old='assign result_bits = result_bits_0;'
        assert sources[top].count(old)==1,'ACTUAL_CONSUMER_BUS_ASSIGNMENT_CHANGED'
        sources[top]=sources[top].replace(old,"assign result_bits = result_bits_0 ^ (Testbench.faultActive ? 8'h01 : 8'h00);")
    elif fault in ('capture-high','capture-low'):
        target=case['capture_target']; trigger='closed' if target=='pin_payload' and variant=='bd' else 'trigger'
        primitive(target,trigger,lambda old:f'({old}) & ~Testbench.faultActive')
    else: raise AssertionError('UNKNOWN_FAULT_WIRING:'+fault)

def bench(info,variant,case):
    text=(TESTS/'ByteOwnerBench.sv.in').read_text()
    paths=info['paths']; macro=info['macro']; fault=[]
    for key,value in case.get('overrides',{}).items():
        fault.append(f'defparam {paths[key]}.DELAY_FS={value};')
    if 'mutex' in case:
        for field,value in zip(('POLICY','RESOLVE_FS','RESOLVE_MAX_FS','SEED'),case['mutex']):
            fault.append(f'defparam {paths["launch_stop_mutex"]}.{field}={value};')
    marker=f'$display("A4_FAULT_APPLIED|{case["name"]}|%0t",$time);'
    snippets={
      'high':'wait(macroCLK); #1000000; @MARK@ faultClockMode=1;',
      'low':'wait(macroCLK); wait(!macroCLK); #1000000; @MARK@ faultClockMode=2;',
      'period':'wait(macroCLK); #6000000; @MARK@ faultClockMode=1; #6000000; faultClockMode=2;',
      'a9':'wait(dut.observe_setupReady); #1; @MARK@ faultActive=1; #499999; faultActive=0;',
      'hold':'wait(macroCLK); #500000; @MARK@ faultActive=1;',
      'source-hold':'wait(grant); #100000; @MARK@ faultActive=1;',
      'result-hold':'wait(resultTrigger); #100000; @MARK@ faultActive=1;',
      'early-capture':'wait(commits==2); wait(macroCLK); #2000000; @MARK@ faultActive=1;',
      'stale-event':'wait(commits==1); wait(rebases==2); #20000000; @MARK@ faultClockMode=2;',
      'post-stop':'wait(stopGrant); wait(request_req); #10000000; @MARK@ faultActive=1;'
    }
    snippets['bd-retire']='wait(dut.observe_cycleComplete); @MARK@'
    snippets['idle-cen']='wait(rebases==2); wait(ready); #20000000; @MARK@ faultActive=1; #20000000; faultActive=0;'
    snippets['disabled-cen']='wait(grant && !request_bits_enable); #10000000; @MARK@ faultActive=1; #5000000; faultActive=0;'
    snippets['held-result']='wait(publications==1); #5000000; @MARK@ faultActive=1; #20000000; faultActive=0;'
    snippets['rtz-result']='wait(publications==1); wait(result_ack); wait(!result_req); #5000000; @MARK@ faultActive=1; #20000000; faultActive=0;'
    if case.get('fault','').startswith('capture-'):
        target=case['capture_target']; trigger='closed' if target=='pin_payload' and variant=='bd' else 'trigger'
        if case['fault']=='capture-high': snippet=f'wait({paths[target]}.{trigger}); #100000; @MARK@ faultActive=1;'
        else: snippet=f'wait({paths[target]}.{trigger}); #2500000; @MARK@ faultActive=1; #100000; faultActive=0;'
    else: snippet=snippets.get(case.get('fault'))
    if snippet: fault.append('initial begin wait(railValid); '+snippet.replace('@MARK@',marker)+' end')
    substitutions={'CLICK':str(int(variant=='click')),'TOP':info['top'],
       'ACTUAL_BINDINGS':info['bindings'],'PHASE_MONITORS':info['phase'],'FAULT_INJECTION':'\n'.join(fault)}
    for k,v in substitutions.items(): text=text.replace('@'+k+'@',v)
    if case.get('monitor_omission'):
        old='PinAperture #(10,3594800,2042150,0,0,"macro.A")'
        assert text.count(old)==1
        text=text.replace(old,'PinAperture #(10,3594800,2042150,0,0,"macro.A",10\'h1ff)')
    assert not re.search(r'@[A-Z_]+@',text)
    return text

def coverage(log,case,variant):
    rows=[x for x in log.splitlines() if x.startswith('A4_COVERAGE|')]
    assert len(rows)==1,('MISSING_COVERAGE_RECORD',case)
    pairs=[x.split('=') for x in rows[0].split('|')[1:]]
    assert len(pairs)==len({x[0] for x in pairs})
    counts={key:int(value) for key,value in pairs}
    lifetime=re.findall(r'^A4_RESULT_LIFETIME\|accepted=(\d+)\|bdRtz=(\d+)\|outstanding=(\d+)$',log,re.M)
    assert len(lifetime)==1
    accepted,rtz,outstanding=map(int,lifetime[0])
    assert accepted==counts['publications'] and outstanding==0
    assert rtz==(counts['publications'] if variant=='bd' else 0)
    assert counts['commits']==counts['publications']==counts['reuseChecks']
    assert counts['effects']==counts['read']+counts['write']
    assert counts['commits']==counts['effects']+counts['disabled']
    pins=re.findall(r'^A4_PIN_POLARITY\|([AD])\|(\d+)\|(\d+)\|(\d+)$',log,re.M)
    assert len(pins)==18 and {(bus,int(bit)) for bus,bit,_,_ in pins}=={('A',i) for i in range(10)}|{('D',i) for i in range(8)}
    stop=re.findall(r'^A4_STOP_PHASE\|(\d+)\|(\d+)$',log,re.M)
    assert len(stop)==11 and {int(i) for i,_ in stop}==set(range(11))
    byte=re.findall(r'^A4_BYTE_VALUE\|(\d+)\|(\d+)\|(\d+)$',log,re.M)
    assert len(byte)==256 and {int(i) for i,_,_ in byte}==set(range(256))
    if case['scenario']=='full':
        # Independent stimulus accounting: 512 byte-value accesses +30 address
        # accesses +16 walking data writes +3 fixed writes +9 repeated reads
        # +2 disabled +2 delayed-return +4 immediate-reuse/writeback checks
        # +20 stop/retention +1 final read =599 committed accesses.
        expected={'commits':599,'effects':597,'publications':599,'offers':601,
                  'disabled':2,'invalidPark':1,'legalPark':1,'immediateReuse':1,
                  'inputReturn':1,'outputReturn':1,'stops':12,'rebases':13}
        assert all(counts[k]==v for k,v in expected.items()),('FULL_COUNT_MISMATCH',counts,expected)
        assert counts['held']>=12
        assert all(int(r)>0 and int(f)>0 for _,_,r,f in pins)
        assert all(counts[k]>0 for k in ('cenRise','cenFall','gwenRise','gwenFall'))
        assert all(int(n)==(0 if int(i)==0 else 1) for i,n in stop)
        assert all(int(w)>0 and int(r)>0 for _,w,r in byte)
        if variant=='click': assert all(counts[k]>0 for k in ('requestPhase0','requestPhase1','resultPhase0','resultPhase1'))
    elif case['scenario']=='competition':
        policy=case['mutex'][0]
        if policy in (0,2): assert counts['commits']==1,('LAUNCH_OUTCOME_MISSING',counts)
        if policy==1: assert counts['commits']==0,('STOP_OUTCOME_MISSING',counts)
        assert counts['stops']==1
    elif case['scenario']=='closed-offer': assert counts['commits']==0 and counts['offers']==1
    elif case['scenario']=='rearm-idle': assert counts['commits']==1 and counts['rebases']==2
    elif case.get('monitor_omission'): assert counts['commits']==1 and counts['effects']==1
    return dict(counts=counts,result_lifetime=dict(accepted=accepted,bd_rtz=rtz,outstanding=outstanding),
                pin_polarities=[dict(bus=b,bit=int(i),rise=int(r),fall=int(f)) for b,i,r,f in pins],
                stop_phases={i:int(n) for i,n in stop},byte_values={i:dict(writes=int(w),reads=int(r)) for i,w,r in byte})

def main():
    global IV,VVP,BACKEND
    parser=argparse.ArgumentParser(); parser.add_argument('exports',type=Path); parser.add_argument('output',type=Path)
    parser.add_argument('--case',action='append',help='narrow debug only; cannot receive complete PASS')
    parser.add_argument('--variant',action='append',choices=('bd','click'),help='debug subset only')
    parser.add_argument('--iverilog',default=os.environ.get('IVERILOG','iverilog'))
    parser.add_argument('--vvp',default=os.environ.get('VVP','vvp'))
    parser.add_argument('--iverilog-backend',default=os.environ.get('IVERILOG_BACKEND'))
    args=parser.parse_args(); out=args.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    IV=executable(args.iverilog); VVP=executable(args.vvp); BACKEND=backend_path(IV,args.iverilog_backend)
    inputs={str(p):sha(p) for p in [IV,VVP,*[ROOT/x for x in SOURCE_FILES]]}
    for p in BACKEND.glob('*'):
        if p.is_file(): inputs[str(p)]=sha(p)
    receipt=dict(status='RUNNING',scope='BUILD_ONLY_DIGITAL_PHYSICAL_UNQUALIFIED',inputs_sha256=inputs,cases=[],inventory={})
    try:
        source_cohort,binding_inputs=verify_cohort(args.exports,ROOT)
        inputs.update(binding_inputs)
        receipt['source_cohort']=source_cohort
        receipt['iverilog_backend']=str(BACKEND)
        for variant in (args.variant or ('bd','click')):
            export=(args.exports/variant).resolve(); info=inventory(export,variant)
            for p in export.rglob('*'):
                if p.is_file(): inputs[str(p)]=sha(p)
            receipt['inventory'][variant]={k:v for k,v in info.items() if k not in ('sources','bindings','phase')}
            for case in cases(variant):
                if args.case and case['name'] not in args.case: continue
                folder=out/variant/case['name']; folder.mkdir(parents=True)
                sources=info['sources'].copy()
                if 'port' in case:
                    key,port,kind=case['port']; instance=info['primitives'][key]['rtl_path'].split('.')[-1]
                    fn=(lambda old:f'({old}) | stopRequest') if kind=='reset-stop' else (lambda old:f'({old}) & ~stopRequest')
                    actual_port_mutation(sources,info['owner'],instance,port,fn)
                fault_wiring(info,sources,variant,case)
                for name,value in sources.items(): write(folder/name,value)
                write(folder/'testbench.sv',bench(info,variant,case))
                write(folder/'PinAperture.sv',(TESTS/'PinAperture.sv').read_text())
                argv=[IV,'-B',BACKEND,'-g2012','-s','Testbench','-o','sim.vvp',*sorted(sources),'PinAperture.sv','testbench.sv']
                code,log=command(argv,folder,folder/'compile.log')
                result=dict(variant=variant,case=case,compile_command=[str(x) for x in argv],compile_returncode=code)
                receipt['cases'].append(result)
                assert code==0, f'{folder}: compile failed'
                code,log=command([VVP,'sim.vvp','+scenario='+case['scenario']],folder,folder/'simulation.log')
                result.update(simulation_returncode=code,files_sha256={p.name:sha(p) for p in folder.iterdir() if p.is_file()})
                fatal=re.findall(r'^FATAL: (.*?):(\d+):\s*(.+)$',log,re.M)
                if case.get('fault'):
                    assert log.count('A4_FAULT_APPLIED|'+case['name']+'|')==1,('FAULT_NOT_EXECUTED',case,log)
                if case.get('fatal'):
                    assert code!=0 and len(fatal)==1 and fatal[0][2]==case['fatal'], (case,log)
                    f,line,_=fatal[0]; bound=(folder/f).resolve()
                    assert bound.parent==folder and bound.name in ('testbench.sv','PinAperture.sv')
                    sourceLine=bound.read_text().splitlines()[int(line)-1]
                    assert '$fatal' in sourceLine and case['fatal'].split(':')[0] in sourceLine
                    result['exact_fatal']=dict(file=bound.name,line=int(line),text=fatal[0][2],source_line=sourceLine)
                else:
                    assert code==0 and log.count('A4_BYTE_OWNER_PASS|')==1 and not fatal,(case,log)
                    result['pass_record']=next(x for x in log.splitlines() if x.startswith('A4_BYTE_OWNER_PASS|'))
                    result['coverage']=coverage(log,case,variant)
                    if case.get('monitor_omission'):
                        result['witness']='DELIBERATELY_BROKEN_A9_MONITOR_ESCAPES_IDENTICAL_FAULT; not an owner pass'
                result['status']='PASS'
        final_cohort,final_bindings=verify_cohort(args.exports,ROOT)
        assert source_cohort==final_cohort and binding_inputs==final_bindings,'COHORT_CHANGED_DURING_CAMPAIGN'
        for p,h in inputs.items(): assert sha(p)==h, f'INPUT_CHANGED_DURING_RUN:{p}'
        assert receipt['cases'],'EMPTY_CAMPAIGN'
        if not args.case and not args.variant:
            expected={(v,c['name']) for v in ('bd','click') for c in cases(v)}
            actual={(r['variant'],r['case']['name']) for r in receipt['cases']}
            assert actual==expected and len(actual)==len(receipt['cases']),'INCOMPLETE_OR_DUPLICATED_COHORT'
            receipt['cohort']={v:{'required':len(cases(v)),
               'positive':sum('fatal' not in c and not c.get('monitor_omission') for c in cases(v)),
               'negative':sum('fatal' in c for c in cases(v)),
               'monitor_omission_witnesses':sum(bool(c.get('monitor_omission')) for c in cases(v))} for v in ('bd','click')}
        receipt['status']='DEBUG_SUBSET_PASS' if args.case or args.variant else 'FINITE_DIGITAL_CANDIDATE_CAMPAIGN_PASS_PHYSICAL_UNQUALIFIED'
    except Exception:
        receipt['status']='FAILED'; receipt['failure']=traceback.format_exc(); raise
    finally:
        write(out/'receipt.json',json.dumps(receipt,indent=2)+'\n')
        print(json.dumps({'status':receipt['status'],'completed_cases':sum(c.get('status')=='PASS' for c in receipt['cases'])}))

if __name__=='__main__': main()

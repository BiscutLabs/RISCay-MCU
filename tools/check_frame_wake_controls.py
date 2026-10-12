# SPDX-License-Identifier: Apache-2.0
"""Observe native frame return at the real service-source stop/wake boundary.

Replay every original FrameWake oracle, then append twelve real I2C commands.
No retained register, derived signal, request or clock is forced. Supplemental
checks observe actual production receipt state, bank availability and oscillator
enable pins. Legal skew keeps all data/request/fixed guard budgets intact.
This digital campaign does not establish physical timing or analog behavior.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from check_frame_store_controls import (sha, hashes, helper_closure, cells,
    pin_value, replace_pin, replace_one, masked)
from check_frame_store import validate_frame_store
from check_frame_receipt import actual_receipt_rtl
from check_program_return_fatals import fatal_sites, classify_fatal


PROFILES=('original','minimum','publisher-fast-banks-slow','publisher-slow-banks-fast')
FIXED={'request_delay','output_delay','request_guard','return_guard','acknowledge_guard','output_guard'}


def require(value, message):
    if not value:raise ValueError('FRAME_WAKE_CONTROL_'+message)


def child(node, name):
    matches=[c['contract'] for c in node['children'] if c['id']==name]
    require(len(matches)==1,'CHILD:'+name)
    return matches[0]


def rtl_path(node):
    return 'dut.soc.'+node['rtl_path'].split('.',1)[1]


def actual(source, parent, node):
    instance=node['rtl_path'].rsplit('.',1)[1]
    model=re.findall(r'\b(\w+)\s+'+re.escape(instance)+r'\s*\(',masked(parent))
    require(len(model)==1 and re.sub(r'_\d+$','',model[0])==re.sub(r'_\d+$','',node['module']),'ACTUAL_MODEL')
    return model[0],(source/(model[0]+'.sv')).read_text(encoding='utf-8'),instance


def bindings(source):
    source=Path(source)
    manifest=json.loads((source/'contract.json').read_text(encoding='utf-8'))['manifest']
    top=manifest['top'];require(top in ('BdFrameWakeFixture','ClickFrameWakeFixture'),'TOP')
    root=manifest['design'];target=child(root,'i2c');store=child(target,'frame_store')
    publication=child(child(target,'native'),'publication')
    receipts=[child(target,'frame_bridge')]+[child(target,f'frame_head{i}_bridge') for i in range(4)]
    top_rtl=(source/(top+'.sv')).read_text(encoding='utf-8')
    target_model,target_rtl,target_instance=actual(source,top_rtl,target)
    store_model,store_rtl,store_instance=actual(source,target_rtl,store)
    require(pin_value(top_rtl,target_instance,'clock')=='serviceClock','FRONT_CLOCK')
    require(pin_value(top_rtl,target_instance,'reset')=='reset','POR_OWNER')
    require(re.sub(r'\s+','',pin_value(top_rtl,target_instance,'frameAcceptEnable'))=='gate_enabled&~holdFrame','FIXTURE_ACCEPT_MASK')
    require(pin_value(target_rtl,store_instance,'slot')=='frameSlot','ROTATING_SLOT')
    require(pin_value(target_rtl,store_instance,'reset')=='reset','STORE_POR')
    policy=validate_frame_store(store,source)
    receipt_models=[]
    for node in receipts:
        model,body,instance=actual(source,target_rtl,node)
        actual_receipt_rtl(node,source,target_rtl)
        require(pin_value(target_rtl,instance,'clock')=='clock' and pin_value(target_rtl,instance,'reset')=='reset','RECEIPT_CLOCK_RESET')
        receipt_models.append(model)
    chip=source/'chip'/(top+'Chip.sv');chip_rtl=chip.read_text(encoding='utf-8')
    require(pin_value(chip_rtl,'serviceOscillator','enable')=='fastEnable','OSCILLATOR_ENABLE')
    require(pin_value(chip_rtl,'serviceOscillator','clk')=='serviceClock','OSCILLATOR_CLOCK')
    require(pin_value(chip_rtl,'soc','reset')=='~porReleased','CHIP_POR')
    require(pin_value(chip_rtl,'soc','serviceClock')=='serviceClock','CHIP_FRONT_CLOCK')
    require(pin_value(chip_rtl,'soc','serviceClockEnable')=='serviceClockEnable','CHIP_ENABLE_ALIAS')
    require(re.search(r'wire\s+fastEnable\s*=\s*powerGood\s*&&\s*\(reset\s*\|\|\s*!porReleased\s*\|\|\s*serviceClockEnable\)\s*;',chip_rtl),'CHIP_ENABLE_POLICY')
    return dict(manifest=manifest,top=top,click=top.startswith('Click'),target=target,store=store,
        publication=publication,receipts=receipts,receipt_models=receipt_models,target_model=target_model,
        target_instance=target_instance,store_model=store_model,store_instance=store_instance,policy=policy,
        chip='chip/'+chip.name)


def profile(body,b,name):
    require(name in PROFILES,'PROFILE')
    overrides={}
    if name=='original':return body,overrides
    for owner,slow in ((b['store'],name=='publisher-fast-banks-slow'),
                       (b['publication'],name=='publisher-slow-banks-fast')):
        for cell in cells(owner).values():
            old=cell['parameters'].get('DELAY_FS')
            if old is None or cell['id'] in FIXED or old!='1000000':continue
            path=rtl_path(cell);value=10000000 if slow else 1000000
            require(not re.search(r'defparam\s+'+re.escape(path)+r'\.DELAY_FS',body),'EXISTING_OVERRIDE')
            overrides[path]=dict(before=int(old),after=value)
    require(overrides,'NO_PROFILE_CELLS')
    addition='\n'.join('defparam '+path+'.DELAY_FS='+str(v['after'])+';' for path,v in overrides.items())
    return body.replace('reg clockEnabled=1;',addition+'\nreg clockEnabled=1;',1),overrides


def monitor(b):
    store=rtl_path(b['store']);receipts=[rtl_path(n) for n in b['receipts']]
    target=rtl_path(b['target']);receipt=receipts[0];command=rtl_path(child(b['manifest']['design'],'control_command_bridge'))
    states=['{'+','.join(r+'.'+leaf for leaf in ('requestMeta','requestSync','acknowledge'))+'}' for r in receipts]
    quiet=[]
    for r in receipts:
        quiet.append(f'({r}.in_req=={r}.acknowledge && {r}.requestMeta=={r}.acknowledge && {r}.requestSync=={r}.acknowledge && !{r}.out_valid)' if b['click'] else
                     f'(!{r}.in_req && !{r}.requestMeta && !{r}.requestSync && !{r}.acknowledge && !{r}.out_valid)')
    banks='{'+','.join(f'{store}.packed_17_probe[{i}]' for i in reversed(range(4)))+'}'
    owners=cells(b['store'])
    payloads=[rtl_path(owners[f'payload{i}' if b['click'] else f'storage{i}.payload'])+'.q' for i in range(4)]
    return f'''
// Independent actual-pin observations. Time is in the original 1 ns/1 ps unit.
wire [3:0] fw_available={banks};
wire [14:0] fw_receipt_state={{{','.join(states)}}};
wire fw_receipts_quiet={' && '.join(quiet)};
wire fw_quiet=(&fw_available) && !{store}.busy && fw_receipts_quiet && dut.soc.fabric_hostFrames_count==0;
wire fw_actual_enable=dut.serviceOscillator.enable;
wire fw_por=dut.soc.reset;
wire [336:0] fw_bank_data[0:3];
{''.join(f'assign fw_bank_data[{i}]={q};' for i,q in enumerate(payloads))}
wire [1347:0] fw_all_payload={{{','.join(reversed(payloads))}}};
integer fw_offers=0,fw_accepts=0,fw_dispatches=0,fw_next=0,fw_front_edges=0,fw_work_edges=0,fw_source_stops=0;
integer fw_bank_offers[0:3],fw_bank_dispatches[0:3],fw_return_edges[0:3];
integer fw_front_at_stop=0,fw_work_at_stop=0,fw_low_edges=0,fw_lf_edges=0,fw_lf_at_stop=0;
integer fw_index,fw_ring_index,fw_before;
reg [3:0] fw_live=0,fw_returning=0;
reg [14:0] fw_stopped_state;
reg [1347:0] fw_stopped_payload;
reg [336:0] fw_expected[0:3];
reg [3:0] fw_was_available=0;
reg fw_saw_stop=0;
realtime fw_front_at=-1000,fw_last_state_edge=-1000,fw_last_quiet=-1000,fw_stopped_at=-1000;
realtime fw_min_quiet_margin=1.0e30,fw_min_state_margin=1.0e30;
initial for(fw_index=0;fw_index<4;fw_index=fw_index+1) begin
 fw_bank_offers[fw_index]=0;fw_bank_dispatches[fw_index]=0;fw_return_edges[fw_index]=0;
end
always @(posedge serviceClock) if(!fw_por) begin fw_front_edges=fw_front_edges+1;fw_front_at=$realtime;end
always @(posedge watchdogClock) if(!fw_por) fw_lf_edges=fw_lf_edges+1;
always @(posedge observedWorkClock) if(!fw_por) begin
 fw_work_edges=fw_work_edges+1;
 if(frameAccepted!==({receipt}.out_valid && {receipt}.out_ready)) $fatal(1,"FRAME_WAKE_CONTROL_A_ALIAS");
 if(frameDispatched!==({command}.in_valid && {command}.in_ready && {command}.in_bits_kind==0)) $fatal(1,"FRAME_WAKE_CONTROL_D_ALIAS");
 if(frameAccepted) begin
  if(!workRunning || !fw_actual_enable || fw_accepts>=fw_offers) $fatal(1,"FRAME_WAKE_CONTROL_A_WITHOUT_O");
  if(fw_bank_data[{store}.slot]!==fw_expected[{store}.slot] || {store}.in_ack!=={store}.in_req)
   $fatal(1,"FRAME_WAKE_CONTROL_COPY_AT_A");
  fw_accepts=fw_accepts+1;
 end
 if(frameDispatched) begin
  if(!workRunning || !fw_actual_enable || !fw_live[dut.soc.fabric_hostFrames_first_bank]) $fatal(1,"FRAME_WAKE_CONTROL_D_WITHOUT_O");
  if(fw_bank_data[dut.soc.fabric_hostFrames_first_bank]!==fw_expected[dut.soc.fabric_hostFrames_first_bank])
   $fatal(1,"FRAME_WAKE_CONTROL_PAYLOAD_AT_D");
  fw_live[dut.soc.fabric_hostFrames_first_bank]=0;
  fw_returning[dut.soc.fabric_hostFrames_first_bank]=1;
  fw_bank_dispatches[dut.soc.fabric_hostFrames_first_bank]=fw_bank_dispatches[dut.soc.fabric_hostFrames_first_bank]+1;
  fw_dispatches=fw_dispatches+1;
 end
end
always @({store}.in_req) if(!fw_por && ({"1'b1" if b['click'] else store+'.in_req'})) begin
 if({store}.slot!==fw_next || !fw_available[fw_next] || fw_live[fw_next]) $fatal(1,"FRAME_WAKE_CONTROL_UNAVAILABLE_AT_O");
 fw_live[fw_next]=1;fw_bank_offers[fw_next]=fw_bank_offers[fw_next]+1;
 fw_expected[fw_next]=observedNativeFrame;
 fw_next=(fw_next+1)%4;fw_offers=fw_offers+1;
end
always @(fw_receipt_state) if(!fw_por) begin
 if($realtime!=fw_front_at) $fatal(1,"FRAME_WAKE_CONTROL_RECEIPT_WITHOUT_FRONT_EDGE");
 fw_last_state_edge=$realtime;
 if(!fw_actual_enable) $fatal(1,"FRAME_WAKE_CONTROL_RECEIPT_WHILE_SOURCE_OFF");
end
always @(posedge serviceClock) if(!fw_por) begin : fw_final_return_edges
 integer k;
 for(k=0;k<4;k=k+1) if(fw_returning[k]) fw_return_edges[k]=fw_return_edges[k]+1;
 #0.001;
 for(k=0;k<4;k=k+1) if(fw_available[k]) fw_returning[k]=0;
end
always @(posedge fw_quiet) if(!fw_por) fw_last_quiet=$realtime;
always @(negedge fw_actual_enable) if(!fw_por) begin : fw_stop
 if(!fw_quiet) $fatal(1,"FRAME_WAKE_CONTROL_RETURN_AT_SOURCE_STOP");
 if(!sleeping || workRunning) $fatal(1,"FRAME_WAKE_CONTROL_WORK_AT_SOURCE_STOP");
 // The production oscillator model completes an already-high phase. Its
 // enable request may fall high; the actual stopped boundary is the last fall.
 if(serviceClock===1) @(negedge serviceClock);
 #0.001;
 if(fw_actual_enable || serviceClock!==0 || !fw_quiet) $fatal(1,"FRAME_WAKE_CONTROL_FINAL_STOP_EDGE");
 fw_source_stops=fw_source_stops+1;fw_stopped_at=$realtime;fw_saw_stop=1;
 fw_front_at_stop=fw_front_edges;fw_work_at_stop=fw_work_edges;fw_stopped_state=fw_receipt_state;fw_lf_at_stop=fw_lf_edges;
 fw_stopped_payload=fw_all_payload;
 if(fw_last_state_edge>=0 && $realtime-fw_last_state_edge<fw_min_state_margin) fw_min_state_margin=$realtime-fw_last_state_edge;
 if(fw_last_quiet>=0 && $realtime-fw_last_quiet<fw_min_quiet_margin) fw_min_quiet_margin=$realtime-fw_last_quiet;
end
always @(posedge serviceClock) if(!fw_por && !fw_actual_enable) $fatal(1,"FRAME_WAKE_CONTROL_FRONT_EDGE_WHILE_OFF");
always @(posedge sleeping) if(!fw_por && !fw_quiet) $fatal(1,"FRAME_WAKE_CONTROL_RETURN_AT_WORK_STOP");
task fw_stopped_check;
 begin
  if(CHECK_SOURCE_STOP) begin
   wait(!fw_actual_enable);#250;
   if(!fw_saw_stop || fw_front_edges!=fw_front_at_stop || fw_work_edges!=fw_work_at_stop ||
      fw_receipt_state!==fw_stopped_state || fw_all_payload!==fw_stopped_payload || !fw_quiet || serviceClock!==0)
    $fatal(1,"FRAME_WAKE_CONTROL_STOPPED_STATE_CHANGED");
   fw_low_edges=fw_low_edges+1;
  end
 end
endtask
task fw_finish;
 integer k;
 begin
  if(fw_offers!=14 || fw_accepts!=14 || fw_dispatches!=14 || fw_live || fw_returning || !fw_quiet)
   $fatal(1,"FRAME_WAKE_CONTROL_RING_COUNTS");
  for(k=0;k<4;k=k+1) begin
   if(fw_bank_offers[k] < 3 || fw_bank_offers[k]!=fw_bank_dispatches[k]) $fatal(1,"FRAME_WAKE_CONTROL_BANK_WRAP");
   $display("FRAME_WAKE_CONTROL_BANK %0d offers=%0d dispatches=%0d return_edges=%0d",k,fw_bank_offers[k],fw_bank_dispatches[k],fw_return_edges[k]);
  end
  if(CHECK_SOURCE_STOP && (fw_source_stops<5 || fw_low_edges!=3 || fw_min_state_margin<=0 || fw_min_quiet_margin<=0))
   $fatal(1,"FRAME_WAKE_CONTROL_STOP_ACTIVITY");
  $display("FRAME_WAKE_CONTROL_METRICS offers=%0d accepts=%0d dispatches=%0d stops=%0d stopped_checks=%0d front_edges=%0d work_edges=%0d last_state_margin_ns=%0.3f quiet_margin_ns=%0.3f",fw_offers,fw_accepts,fw_dispatches,fw_source_stops,fw_low_edges,fw_front_edges,fw_work_edges,fw_min_state_margin,fw_min_quiet_margin);
  $display("FRAME_WAKE_CONTROL_PASS");
 end
endtask
'''


def instrument(original,b):
    require(original.count('reg clockEnabled=1;')==1 and original.count('$display("RISCAY_SOC_PASS"); $finish;')==1,'ORACLE_ANCHOR')
    # Insert only: every original assertion and its stimulus remain verbatim.
    anchors=re.findall(r'localparam CHECK_SOURCE_STOP=[01];',original)
    require(len(anchors)==1,'MODE_ANCHOR')
    body=original.replace(anchors[0],anchors[0]+'\n'+monitor(b),1)
    extension='''
        for(fw_ring_index=0;fw_ring_index<12;fw_ring_index=fw_ring_index+1) begin
          // Four wire commands rotate all banks before each complete source
          // stop. This remains inside the unchanged original 5 ms deadline.
          if(fw_ring_index%4==0) fw_stopped_check();
          fw_before=accepted;
          command(9);
          wait(accepted==fw_before+1 && dispatched==fw_before+1);
          wait(sleeping);
          if(CHECK_SOURCE_STOP && fw_ring_index%4==3) wait(!fw_actual_enable);
          #251;
        end
        fw_finish();
'''
    return body.replace('$display("RISCAY_SOC_PASS"); $finish;',extension+'\n$display("RISCAY_SOC_PASS"); $finish;',1)


def mutate(case,b,fault):
    if fault=='premature-source-stop':
        file=case/b['chip'];text=file.read_text(encoding='utf-8')
        # Fault the actual oscillator enable connection while an actual native
        # head remains pending; never force a testbench observation signal.
        head=rtl_path(b['receipts'][1]).removeprefix('dut.')
        changed=replace_pin(text,'serviceOscillator','enable','fastEnable && !fw_fault_stop')
        # One ns separates the injected disable from the front-edge NBA that
        # creates out_valid, so its exact failure is not scheduler-order based.
        anchor='wire lfClock, serviceClock, serviceClockEnable, powerGood, porReleased;'
        require(changed.count(anchor)==1,'CHIP_WIRE_ANCHOR')
        changed='`timescale 1fs/1fs\n'+changed.replace(anchor,anchor+f'\nwire fw_fault_stop;\nassign #1000000 fw_fault_stop={head}.out_valid;',1)
        expected='FRAME_WAKE_CONTROL_RETURN_AT_SOURCE_STOP'
    elif fault=='head-clock-polarity':
        file=case/(b['target_model']+'.sv');text=file.read_text(encoding='utf-8')
        instance=b['receipts'][1]['rtl_path'].rsplit('.',1)[1]
        changed=replace_pin(text,instance,'clock','~clock')
        expected='FRAME_WAKE_CONTROL_RECEIPT_WITHOUT_FRONT_EDGE'
    else:raise ValueError('FRAME_WAKE_CONTROL_UNKNOWN_FAULT')
    require(changed!=text,'EMPTY_MUTATION');file.write_text(changed,encoding='utf-8')
    return expected,dict(file=str(file.relative_to(case)),before_sha256=__import__('hashlib').sha256(text.encode()).hexdigest(),after_sha256=sha(file))


def sources_policy(sources):
    require(set(sources)=={'bd','click'},'SOURCE_VARIANTS');result={}
    for variant,group in sources.items():
        require(set(group)=={'running','stopped'},'SOURCE_MODES')
        result[variant]={}
        for mode,value in group.items():
            source=Path(value).resolve();b=bindings(source)
            require(b['click']==(variant=='click'),'SOURCE_VARIANT')
            body=(source/'testbench.sv').read_text(encoding='utf-8');log=(source/'simulation.log').read_text(encoding='utf-8')
            require(f'localparam CHECK_SOURCE_STOP={int(mode=="stopped")};' in body,'SOURCE_MODE')
            require(log.count('RISCAY_SOC_PASS')==1 and not re.search(r'FATAL|DEADLINE|TIMEOUT',log),'SOURCE_NOT_PASS')
            require('force ' not in body and 'release ' not in body,'SOURCE_FORCE')
            result[variant][mode]=(source,b)
    return result


def metrics(log,stopped):
    require(log.splitlines().count('FRAME_WAKE_CONTROL_PASS')==1,'POSITIVE_MARKER')
    banks={}
    for m in re.finditer(r'^FRAME_WAKE_CONTROL_BANK (\d) offers=(\d+) dispatches=(\d+) return_edges=(\d+)$',log,re.M):
        require(m[1] not in banks,'DUPLICATE_BANK_METRIC')
        banks[m[1]]=dict(zip(('offers','dispatches','return_edges'),map(int,m.groups()[1:])))
    require(set(banks)==set('0123') and all(v['offers']>=3 and v['offers']==v['dispatches'] for v in banks.values()),'BANK_METRICS')
    found=re.findall(r'^FRAME_WAKE_CONTROL_METRICS offers=(\d+) accepts=(\d+) dispatches=(\d+) stops=(\d+) stopped_checks=(\d+) front_edges=(\d+) work_edges=(\d+) last_state_margin_ns=([0-9.]+) quiet_margin_ns=([0-9.]+)$',log,re.M)
    require(len(found)==1,'METRIC_RECORD')
    values=found[0];counts=dict(zip(('offers','accepts','dispatches','stops','stopped_checks','front_edges','work_edges'),map(int,values[:7])))
    require(counts['offers']==counts['accepts']==counts['dispatches']==14 and counts['front_edges']>=counts['work_edges']>0,'COUNT_METRICS')
    require((counts['stops']>=5 and counts['stopped_checks']==3) if stopped else (counts['stops']==0 and counts['stopped_checks']==0),'STOP_METRICS')
    margins=dict(last_state_margin_ns=float(values[7]),quiet_margin_ns=float(values[8])) if stopped else None
    require(not stopped or all(v>0 for v in margins.values()),'STOP_MARGIN')
    return dict(banks=banks,counts=counts,margins=margins)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();selected=sources_policy(json.loads(args.sources.read_text(encoding='utf-8')))
    out=args.out.resolve();require(not out.exists(),'OUTPUT_EXISTS')
    require(all(not out.is_relative_to(s) and not s.is_relative_to(out) for g in selected.values() for s,b in g.values()),'SOURCE_OVERLAP')
    out.mkdir(parents=True)
    tools=Path(__file__).resolve().parent
    helpers=helper_closure([Path(__file__),tools/'test_frame_wake_controls.py',
        tools.parent/'verification/src/test/scala/riscay/FrameWakeSpec.scala',
        tools.parent/'verification/src/test/scala/riscay/ClockedSimulation.scala']+
        [tools.parent/('designs/'+design+'/src/main/scala/riscay/'+package+'/'+file+'.scala')
         for design,package,prefix in (('four-phase-bd','bd','FourPhase'),('two-phase-click','click','Click'))
         for file in (prefix+'FrameStore','I2cTarget',prefix+'Platform','SleepTiming')])
    result=dict(status='RUNNING',sources_sha256=sha(args.sources),helper_sha256={str(p):sha(p) for p in helpers},
        source_sha256={v:{m:hashes(s) for m,(s,b) in g.items()} for v,g in selected.items()},cases={})
    def save():(out/'results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    def run(command,case,label):
        try:
            completed=subprocess.run(command,cwd=case,text=True,capture_output=True,timeout=180)
            record=dict(command=command,cwd=str(case),exit_code=completed.returncode,timed_out=False);log=completed.stdout+completed.stderr
        except subprocess.TimeoutExpired as error:
            record=dict(command=command,cwd=str(case),exit_code=None,timed_out=True);log=str(error.stdout or '')+str(error.stderr or '')
        (case/(label+'.log')).write_text(log,encoding='utf-8');record['log_sha256']=sha(case/(label+'.log'))
        return record,log
    def simulate(variant,mode,profile_name,fault=None):
        source,_=selected[variant][mode];name='-'.join([variant,mode,profile_name]+([fault] if fault else []))
        case=out/name;shutil.copytree(source,case);b=bindings(case)
        original=(source/'testbench.sv').read_text(encoding='utf-8')
        body,overrides=profile(instrument(original,b),b,profile_name)
        (case/'testbench.sv').write_text(body,encoding='utf-8');expected=None;mutation=None
        if fault:expected,mutation=mutate(case,b,fault)
        files=[s.strip() for s in (case/'filelist.f').read_text(encoding='utf-8').splitlines() if s.strip()]
        def nodes(n):
            yield n
            for c in n['children']:yield from nodes(c['contract'])
        files += sorted({p['resource'].split('/')[-1] for n in nodes(b['manifest']['design']) for p in n['primitives']})
        files += [b['chip']]+['chip/'+s for s in ('riscay_lf_osc_model.sv','riscay_service_osc_model.sv','riscay_supply_monitor_model.sv','riscay_reset_hold.sv')]
        files=list(dict.fromkeys(Path(f).as_posix() for f in files));require(all((case/f).is_file() and (case/f).resolve().is_relative_to(case) for f in files),'FILELIST')
        record=dict(source=str(source),original_testbench_sha256=sha(source/'testbench.sv'),original_oracles_preserved=True,
            structural_policy=b['policy'],profile=profile_name,overrides=overrides,mutation=mutation,
            expected=expected,fatal_sites=fatal_sites(body,[expected]) if expected else [],
            testbench_sha256=sha(case/'testbench.sv'),rtl_sha256={f:sha(case/f) for f in files})
        result['cases'][name]=record;save()
        record['compile'],log=run(['iverilog','-g2012','-s','Testbench','-o','wake.vvp',*files,'testbench.sv'],case,'control-compile')
        require(record['compile']['exit_code']==0 and not record['compile']['timed_out'],'COMPILE:'+name+':'+log[-1500:])
        record['binary_sha256']=sha(case/'wake.vvp')
        record['simulation'],log=run(['vvp','wake.vvp'],case,'control-simulation');save()
        if expected:record['fatal_records']=classify_fatal(record['compile'],record['simulation'],log,record['fatal_sites'])
        else:
            require(record['simulation']['exit_code']==0 and not record['simulation']['timed_out'] and log.count('RISCAY_SOC_PASS')==1 and not re.search(r'FATAL|DEADLINE|TIMEOUT',log),'POSITIVE:'+name+':'+log[-1600:])
            record['metrics']=metrics(log,mode=='stopped')
        require(record['binary_sha256']==sha(case/'wake.vvp') and record['testbench_sha256']==sha(case/'testbench.sv') and record['rtl_sha256']=={f:sha(case/f) for f in files},'ARTIFACT_CHANGED')
        record['status']='PASS';save();print(name,'PASS',flush=True)
    try:
        for variant in ('bd','click'):
            for mode in ('running','stopped'):
                for p in PROFILES:simulate(variant,mode,p)
            for fault in ('premature-source-stop','head-clock-polarity'):simulate(variant,'stopped','original',fault)
        require(result['helper_sha256']=={str(p):sha(p) for p in helpers},'HELPER_CHANGED')
        require(result['sources_sha256']==sha(args.sources),'SOURCE_INDEX_CHANGED')
        require(result['source_sha256']=={v:{m:hashes(s) for m,(s,b) in g.items()} for v,g in selected.items()},'SOURCE_CHANGED')
        result.update(status='PASS',positives=16,negatives=4);save();print('FRAME_WAKE_CONTROLS_PASS',flush=True)
    except BaseException as error:
        result.update(status='FAILED',error=repr(error));save();raise


if __name__=='__main__':main()

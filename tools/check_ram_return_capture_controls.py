# SPDX-License-Identifier: Apache-2.0
"""Standalone native RAM-return actual capture-pin campaign.

Require one complete, passing 40-fixture/24-seed exported cohort. Validate the
closed RTL/reset contract first, preserve every existing oracle, and add actual
pin setup/hold/pulse/distribution assertions. No physical or SoC qualification.
"""
import argparse,hashlib,json,re,shutil,sys
from pathlib import Path
from check_capture_pins import capture_monitors
from check_admission_controls import replace_pin
from check_recovery_capture_controls import pin_expression,extra_wires
from check_i2c_wiring_controls import hashes,run
from check_ram_return_contract import CAPTURES,validate_export,validate_ram_return,require

RESET_STAGES=('held','arm','issue','offered','ack','cleanup','repeated','release_arm','release_issue','receipt_hold')
CAMPAIGNS={v:{'stalls','cancel','offer-bound'} |
 {f'reset-{stage}-{prior}' for stage in RESET_STAGES for prior in ((1,2) if v=='click' else (1,))} |
 ({'full-return-'+branch for branch in ('input','publication','receipt','application')} if v=='bd' else set())
 for v in CAPTURES}


def source_oracles(sources,validate=validate_export):
 require(set(sources)==set(CAPTURES),'CAPTURE_VARIANTS')
 selected={};records={};cohorts={};all_paths=[]
 for variant,fixtures in sources.items():
  require(set(fixtures)==CAMPAIGNS[variant],'CAPTURE_FIXTURES:'+variant)
  selected[variant]={};records[variant]={}
  for label,value in fixtures.items():
   source=Path(value).resolve();all_paths.append(source)
   require((source/'export/contract.json').is_file(),'CAPTURE_MISSING_SOURCE:'+label)
   record=validate(source/'export')
   require(record['owner']==('ClickRamReturn' if variant=='click' else 'FourPhaseRamReturn'),'CAPTURE_SOURCE_OWNER')
   expected={'seed-'+str(i) for i in range(1,25)}
   require({p.name for p in source.glob('seed-*')}==expected,'CAPTURE_SEED_INVENTORY:'+label)
   for seed in range(1,25):
    case=source/f'seed-{seed}'
    require(all((case/f).is_file() for f in ('testbench.sv','result.json','simulation.log','compile.log','delays.json')),
            'CAPTURE_SEED_FILES:'+label)
    result=json.loads((case/'result.json').read_text())
    require(result.get('status')=='PASS' and result.get('seed')==str(seed),'CAPTURE_SEED_PASS:'+label)
    log=(case/'simulation.log').read_text()
    require('CA_TEST_PASS' in log and not re.search(r'(?i)fatal|deadline|timeout|fail',log.replace('CA_TEST_PASS','')),
            'CAPTURE_SEED_LOG:'+label)
    activity=result.get('activity',[])
    require(len(activity)==2 and all(any(re.fullmatch(r'CA_ACTIVITY channel='+channel+r' delivered=[1-9][0-9]*',a)
                    for a in activity) for channel in ('word','publication')),'CAPTURE_SEED_ACTIVITY:'+label)
    delays=json.loads((case/'delays.json').read_text());delay_policy=record['delay_policy']
    require(delays.get('seed')==str(seed) and delays.get('algorithm')=='java.util.Random; 1=min,2=max' and
            delays.get('pins_fs')=={} and set(delays.get('cells_fs',{}))==set(delay_policy) and
            result.get('varied_cells')==len(delay_policy),'CAPTURE_DELAYS:'+label)
    for cell,bounds in delay_policy.items():
     value=int(delays['cells_fs'][cell]);fixed=bounds['fixed_fs']
     require((value==fixed if fixed is not None else bounds['minimum_fs']<=value<=bounds['maximum_fs']) and
             (fixed is not None or seed>2 or value==bounds['minimum_fs' if seed==1 else 'maximum_fs']),
             'CAPTURE_DELAY_VALUE:'+label+':'+cell)
    bench=(case/'testbench.sv').read_text()
    assignments=re.findall(r'\bdefparam\s+(\S+)\s*=\s*(\d+)\s*;',bench)
    expected_delays={'dut.'+cell.split('.',1)[1]+'.DELAY_FS':value for cell,value in delays['cells_fs'].items()}
    require(len(assignments)==len(expected_delays) and dict(assignments)==expected_delays and
            bench.count('defparam')==len(assignments) and
            bench.count('$display("CA_TEST_PASS seed='+str(seed)+'");')==1,
            'CAPTURE_ORACLE_DELAYS:'+label)
   cohort=record['export_sha256']
   if variant in cohorts:require(cohorts[variant]==cohort,'CAPTURE_EXPORT_COHORT:'+variant+':'+label)
   else:cohorts[variant]=cohort
   records[variant][label]=record;selected[variant][label]=source
 require(len(all_paths)==len(set(all_paths)),'CAPTURE_DUPLICATE_SOURCE')
 return selected,records,cohorts

def inventory(node,variant):
 require(validate_ram_return(node)==variant,'CAPTURE_OWNER')
 return capture_monitors(node,CAPTURES[variant],'RAM_CAPTURE')

def skew(test,node,variant,profile):
 prefixes=({'capture':('received_phase','payload','permission','application_target'),
             'feedback':('incoming','owned','issue_pending','terminal','issue_seen','completed_phase'),
             'shutdown':('arm_selected','finish_selected','branches_returned')}
           if variant=='click' else {
             'capture':('payload','permission','pending'),
             'feedback':('released','input_seen','input_withdrawn','history_common'),
             'shutdown':('issued','publication_offer','receipt_offer','application_offer','application_request')})
 selected=[p for p in node['primitives'] if any(p['id']==n or profile=='shutdown' and p['id'].startswith(n+'_') for n in prefixes[profile])]
 assert selected,'RAM_CAPTURE_SKEW_INVENTORY'
 paths=[]
 for p in selected:
  path='dut.'+p['rtl_path'].split('.',1)[1];old=f'defparam {path}.DELAY_FS=1000000;'
  assert test.count(old)==1,('RAM_CAPTURE_SKEW_SHAPE',p['id'])
  test=test.replace(old,f'defparam {path}.DELAY_FS=10000000;');paths.append(path)
 return test,paths

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--sources',type=Path,required=True)
 ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
 sources,reset_records,cohorts=source_oracles(json.loads(args.sources.read_text()))
 out=args.out.resolve()
 require(not any(out.is_relative_to(p) or p.is_relative_to(out) for fixtures in sources.values() for p in fixtures.values()),
         'CAPTURE_SOURCE_OVERLAP')
 out.mkdir(parents=True,exist_ok=False)
 tool_paths=[Path(__file__).resolve().parent/name for name in ('check_ram_return_capture_controls.py',
     'check_ram_return_contract.py','check_capture_pins.py','check_admission_controls.py',
     'check_recovery_capture_controls.py','check_i2c_wiring_controls.py')]
 tool_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in tool_paths}
 (out/'tool-hashes.json').write_text(json.dumps(tool_hashes,indent=2)+'\n')
 (out/'reset-boundaries.json').write_text(json.dumps(reset_records,indent=2)+'\n')
 (out/'cohort.json').write_text(json.dumps(dict(source_manifest_sha256=hashlib.sha256(args.sources.read_bytes()).hexdigest(),
     fixtures={v:sorted(x) for v,x in sources.items()},seeds=list(range(1,25)),exports=cohorts),indent=2)+'\n')
 results={};commands=[];originals={}
 def record():
  (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
  (out/'commands.json').write_text(json.dumps(commands,indent=2)+'\n')
 def simulate(label,variant,source,seed,profile=None,mutate=None,release=None):
  case=out/label;assert not out.is_relative_to(source);shutil.copytree(source/'export',case)
  node=json.loads((case/'contract.json').read_text())['manifest']['design']
  oracle=source/f'seed-{seed}/testbench.sv';test=oracle.read_text();paths=[]
  if profile:test,paths=skew(test,node,variant,profile)
  marker='$display("CA_TEST_PASS';anchor='timeunit 1fs; timeprecision 1fs;'
  assert test.count(marker)==test.count(anchor)==1
  checks='\n'.join(f'if(pc_{n}_count==0) $fatal(1,"RAM_CAPTURE_INACTIVE:{n}");\n'
    f'$display("RAM_CAPTURE_ACTIVITY:{n}:%0d",pc_{n}_count);' for n in CAPTURES[variant])
  extra=''
  if release:
   name,direction=release;cell=next(p for p in node['primitives'] if p['id']==name)
   pin='dut.'+cell['rtl_path'].split('.',1)[1]+'.trigger'
   extra=f"""
+time rr_release_time=0,rr_trigger_time=0;
+reg rr_release_seen=0,rr_trigger_seen=0;
+integer rr_before=0,rr_after=0;
+always @(negedge dut.applicationReset) if(!dut.reset) begin
+  rr_release_time=$time;rr_release_seen=1;
+  if(rr_trigger_seen && $time-rr_trigger_time<=100000) rr_after=rr_after+1;
+end
+always @(posedge {pin}) if(!dut.reset) begin
+  rr_trigger_time=$time;rr_trigger_seen=1;
+  if(rr_release_seen && $time-rr_release_time<=100000) rr_before=rr_before+1;
+end
+""".replace('\n+','\n')
   checks+=f'\nif(rr_{direction}==0) $fatal(1,"RAM_RELEASE_CAPTURE_INACTIVE:{name}:{direction}");\n'
   checks+=f'$display("RAM_RELEASE_CAPTURE_COVERAGE:{name}:{direction}:%0d",rr_{direction});\n'
  test=test.replace(marker,checks+'\n'+marker).replace(anchor,anchor+'\n'+inventory(node,variant)+extra)
  (case/'testbench.sv').write_text(test);expected=None
  if mutate:
   rtl=case/(node['module']+'.sv');changed,expected=mutate(rtl.read_text(),node);rtl.write_text(changed)
  files=[str((case/x.strip()).resolve()) for x in (case/'filelist.f').read_text().splitlines() if x.strip()]
  compiled,log=run(['iverilog','-g2012','-s','Testbench','-o','sim.vvp',*files,'testbench.sv'],case,'compile.log',commands)
  assert compiled['exit_code']==0,log[-4000:]
  simulated,log=run(['vvp','sim.vvp'],case,'simulation.log',commands)
  results[label]=dict(source=str(source),oracle=str(oracle),original_oracle_sha256=hashlib.sha256(oracle.read_bytes()).hexdigest(),
    assertions_only_added=True,selected_skew=paths,release_overlap=release,mutated=mutate is not None,expected=expected,compile=compiled,simulation=simulated)
  record()
  if expected:assert simulated['exit_code']!=0 and expected in log and 'DEADLINE' not in log and 'TIMEOUT' not in log,log[-4000:]
  else:assert simulated['exit_code']==0 and 'CA_TEST_PASS' in log,log[-4000:]
  print(label,'PASS',flush=True)
 def mutation(name,kind,delay=0):
  def change(text,node):
   p=next(p for p in node['primitives'] if p['id']==name);instance=p['rtl_path'].rsplit('.',1)[1]
   trigger=pin_expression(text,instance,'trigger');width=p['parameters']['WIDTH']
   if kind=='setup':return replace_pin(text,instance,'d','{'+width+'{'+trigger+'}}'),'RAM_CAPTURE_SETUP:'+name
   if kind=='hold':
    text=replace_pin(text,instance,'d','{'+width+'{ram_late_clock}}')
    wires='wire ram_late_clock;';assignments=f'assign #100000 ram_late_clock = {trigger};'
   else:
    text=replace_pin(text,instance,'trigger','ram_test_clock')
    wires='wire ram_test_clock,ram_late_clock,ram_second_clock;'
    if kind=='skew':assignments=f'assign #{delay} ram_test_clock = {trigger};'
    elif kind=='high':assignments=f'assign #100000 ram_late_clock = {trigger};\nassign ram_test_clock = {trigger} & ~ram_late_clock;'
    else:assignments=(f'assign #1000000 ram_late_clock = {trigger};\nassign #1100000 ram_second_clock = {trigger};\n'
      f'assign ram_test_clock = {trigger} & (~ram_late_clock | ram_second_clock);')
   expected=None if kind=='skew' and delay==100000 else 'RAM_CAPTURE_'+{
     'hold':'HOLD','high':'PULSE_HIGH','low':'PULSE_LOW','skew':'SKEW'}[kind]+':'+name
   return extra_wires(text,node['module'],wires,assignments),expected
  return change
 for variant,fixtures in sources.items():
  for label,path in fixtures.items():
   source=Path(path).resolve();originals[str(source)]=hashes(source)
   assert {p.parent.name for p in source.glob('seed-*/result.json')}=={'seed-'+str(i) for i in range(1,25)},label
   for seed in range(1,25):simulate(variant+'-'+label+'-seed-'+str(seed),variant,source,seed)
   for profile in ('capture','feedback','shutdown'):simulate(variant+'-'+label+'-skew-'+profile,variant,source,1,profile)
   release_stage='arm' if label.startswith('reset-release_arm-') else 'issue' if label.startswith('reset-release_issue-') else None
   origin=('pending' if variant=='bd' else 'request_guard') if release_stage=='arm' else 'request_delay'
   for name,fire in CAPTURES[variant].items():
    if release_stage and fire==origin:
     simulate(variant+'-'+label+'-'+name+'-release-after',variant,source,1,release=(name,'after'))
     simulate(variant+'-'+label+'-'+name+'-release-before',variant,source,1,
       mutate=mutation(name,'skew',100000),release=(name,'before'))
  source=Path(fixtures['stalls']).resolve()
  for name in CAPTURES[variant]:
   simulate(variant+'-'+name+'-legal-distribution',variant,source,1,mutate=mutation(name,'skew',100000))
   for kind in ('setup','hold','high','low','skew'):
    simulate(variant+'-'+name+'-bad-'+kind,variant,source,1,mutate=mutation(name,kind,100001))
 assert all(hashes(Path(p))==h for p,h in originals.items()),'RAM_CAPTURE_ORIGINAL_CHANGED'
 require(all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in tool_hashes.items()),'CAPTURE_TOOLS_CHANGED')
 positives=sum(r['expected'] is None for r in results.values());negatives=sum(r['expected'] is not None for r in results.values())
 overlaps=sum(r['release_overlap'] is not None for r in results.values())
 require((positives,negatives,overlaps)==(1117,45,28),'CAPTURE_FINAL_INVENTORY')
 results['summary']=dict(positive_replays=positives,
   mutations=negatives,reset_release_overlap_replays=overlaps,originals_preserved=True,
   closed_standalone_contract=True,fixtures=40,seeds_per_fixture=24,
   scope='standalone digital capture pins and resolved mixed-reset contract; SoC integration and physical qualification remain open')
 record();print('ALL_RAM_CAPTURE_CONTROLS_PASS',flush=True)

if __name__=='__main__':main()

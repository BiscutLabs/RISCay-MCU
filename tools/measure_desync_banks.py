# SPDX-License-Identifier: Apache-2.0
"""Measure native-bank data/storage/enable segments on the repaired netlist.

Controller outputs are analysis frontiers. Transparent D-to-Q arcs are measured
separately, never waived from the composed proof. Empty source/target pairs are
inventoried explicitly. Paths are ranked by constraint slack, NOT by pure Q-D
delay: subtracting their first/last arrivals does not find segment extrema.
Latch max-delay exceptions reference opening, not the closing/setup aperture.
Transparent D-Q slew must also be propagated in a composed view. These samples
cannot alone qualify a matched delay or a hold constraint.
"""
import argparse,json,math
from copy import deepcopy
from pathlib import Path
from gf180_physical import ROOT,SC,SRAM,write_json
from physical_tools import tool
from run_receipt import RunReceipt
from primitives import resolve_candidate
from repair_gf180_design import flat,ident
from characterize_gf180_liberty import CORNERS
from gf180_estimate import groups,direct_groups,scalar
from concurrent.futures import ThreadPoolExecutor

def parse_segments(text,corner):
    if 'SEGMENTS_DONE' not in text or 'Error:' in text or 'combinational loop' in text.lower():
        raise ValueError('DESYNC_BANK_SEGMENTS_INCOMPLETE')
    expected={};observed={};storage=None
    for line in text.splitlines():
        f=line.split()
        if not f:continue
        if f[0]=='STORAGE':storage=list(map(int,f[1:]))
        if f[0]=='PAIR_COVERAGE':
            key=tuple(f[1:4]);count=int(f[4])
            if key in expected or count not in (0,1):raise ValueError('DESYNC_BANK_PAIR_COVERAGE')
            expected[key]=count
        if f[0]=='PAIR':
            key=tuple(f[1:4]);values=list(map(float,f[4:6]))+[float(f[8])]
            if key in observed or not all(math.isfinite(v) for v in values):raise ValueError('DESYNC_BANK_PAIR_INVALID')
            observed[key]=dict(source=key[0],target=key[1],mode=key[2],
                selected_q_arrival_ns=values[0],selected_d_arrival_ns=values[1],q=f[6],d=f[7],
                constraint_slack_ns=values[2])
    if not storage or min(storage)<=0 or not expected or set(observed)!={k for k,v in expected.items() if v}:
        raise ValueError('DESYNC_BANK_PAIR_COVERAGE')
    clocks={k[0] for k in expected};targets={k[1] for k in expected}
    if set(expected)!={(s,t,m) for s in clocks for t in targets for m in ('min','max')}:
        raise ValueError('DESYNC_BANK_PAIR_COVERAGE')
    return dict(corner=corner,storage_q_and_d_pins=storage,rows=list(observed.values()),
                empty_pairs=[dict(source=s,target=t,mode=m) for (s,t,m),v in expected.items() if not v])

def run(m,p,o,input_slew,mutex_libs):
    o.mkdir(parents=True,exist_ok=False)
    n=json.loads((p/'repaired.json').read_text());n['modules']['RiscayMcuDigital']['cells']={ident(k):v for k,v in n['modules']['RiscayMcuDigital']['cells'].items()};b=json.loads((m/'control.json').read_text())['bindings'];g=flat(n,'RiscayMcuDigital');a=deepcopy(n);body=a['modules']['RiscayMcuDigital'];cells=body['cells'];roots={};native=set()
    for v in b:
     r=resolve_candidate(v['primitive'],v.get('parameters'));prefix=v['instance']+'/'
     for c in r['cells']:native.add(prefix+c['name'])
     for port,direction in r['ports'].items():
      if direction!='output':continue
      driver=[(c['name'],pin) for c in r['cells'] for pin,net in c['pins'].items() if net==port and pin in ('Z','ZN','G0','G1')]
      assert len(driver)==1
      name,pin=driver[0];bits=cells[prefix+name]['connections'][pin];alias='analysis_'+str(len(roots));roots[v['instance']+'/'+port]=alias
      body['ports'][alias]=dict(direction='input',bits=bits);body['netnames'][alias]=dict(hide_name=0,attributes={},bits=bits)
    for name in list(cells):
     if name in native:del cells[name]
    # No architectural logic or storage is removed. This analysis view replaces
    # control outputs by frontiers; local controller delay is measured separately.
    from collections import defaultdict
    from functools import lru_cache
    reverse_roots={g['cells'][v['instance']+'/'+c['name']]['connections'][pin][0]:roots[v['instance']+'/'+port] for v in b for port,d in resolve_candidate(v['primitive'],v.get('parameters'))['ports'].items() if d=='output' for c in resolve_candidate(v['primitive'],v.get('parameters'))['cells'] for pin,netname in c['pins'].items() if netname==port and pin in ('Z','ZN','G0','G1')}
    drivers={bit:(name,pin) for name,c in g['cells'].items() for pin,bits in c['connections'].items() if c['directions'][pin]=='output' for bit in bits}
    @lru_cache(None)
    def route(bit):
     if bit in reverse_roots:return reverse_roots[bit],[]
     if bit not in drivers:return None
     name,pin=drivers[bit];c=g['cells'][name];kind=c['type'].removeprefix(SC).rsplit('_',1)[0]
     if kind not in ('buf','clkbuf','inv','clkinv','and2'):return None
     candidates=[]
     for ip,bs in c['connections'].items():
      if c['directions'][ip]!='input':continue
      prior=route(bs[0])
      if prior:candidates.append((prior[0],prior[1]+[(name,ip,pin)]))
     if len(candidates)>1:raise ValueError('MULTIPLE_NATIVE_ROOTS')
     return candidates[0] if candidates else None
    routes={};arcs=set()
    for name,c in g['cells'].items():
     if c['type'].startswith(SC+'lat') or c['type'].startswith(SC+'dff') or c['type']==SRAM:
      clock=next(p for p in ('E','CLK','CLKN') if p in c['connections'])
      path=route(c['connections'][clock][0])
      if path:routes[name+'/'+clock]=dict(root=path[0],arcs=path[1]);arcs.update(path[1])
    for v in b:
     recipe=resolve_candidate(v['primitive'],v.get('parameters'))
     for cell in recipe['cells']:
      mapped=g['cells'][v['instance']+'/'+cell['name']]
      for pin,port in cell['pins'].items():
       if recipe['ports'].get(port)!='input':continue
       path=route(mapped['connections'][pin][0])
       if path:routes[v['instance']+'/'+port+'/'+cell['name']+'/'+pin]=dict(root=path[0],arcs=path[1]);arcs.update(path[1])
    # Preserve the capacitance of every removed native input on any live
    # analysis net. Otherwise parent drivers and enable trees look too fast.
    live={bit for row in cells.values() for pin,bits in row['connections'].items()
          if row['port_directions'][pin]=='output' for bit in bits}
    live.update(bit for row in body['ports'].values() if row['direction']=='input' for bit in row['bits'])
    removed={}
    for name in sorted(native):
        c=n['modules']['RiscayMcuDigital']['cells'][name]
        for pin,bits in c['connections'].items():
            if c['port_directions'][pin]=='input':
                for bit in bits:
                    if bit in live and isinstance(bit,int):removed.setdefault(bit,[]).append((c['type'],pin))
    load_cells=[]
    for i,(bit,pins) in enumerate(sorted(removed.items())):
        kind='DesyncAnalysisLoad'+str(i)
        a['modules'][kind]=dict(attributes={'blackbox':'1'},cells={},netnames={},ports={'I':dict(direction='input',bits=[2])})
        cells['analysis_load_'+str(i)]=dict(type=kind,parameters={},attributes={},port_directions={'I':'input'},connections={'I':[bit]})
        load_cells.append(dict(cell=kind,pins=pins))
    write_json(o/'restored-loads.json',load_cells)
    write_json(o/'routes.json',routes)
    write_json(o/'analysis.json',a);write_json(o/'roots.json',roots)
    y=tool('yosys');s=tool('sta');pd=ROOT/'.tools/physical/pdk';sr=ROOT/'.tools/gf180-sram'
    r=RunReceipt(o/'receipt.json',inputs=[p/'repaired.json',m/'control.json',*[pd/(SC+c+'.lib') for c in CORNERS],*[sr/(SRAM+'__'+c+'.lib') for c in CORNERS],*[mutex_libs/('ca_mutex_gf180_candidate__'+c+'__scenarios.lib') for c in CORNERS]],tools=[Path(__file__),ROOT/'tools/primitives.py',*y.input_files(),*s.input_files()])
    reports=[]
    try:
     script=o/'emit.ys';script.write_text(f'read_json "{y.path(o/"analysis.json")}"\nwrite_verilog -norename -noattr -noexpr "{y.path(o/"analysis.v")}"\n',encoding='utf-8')
     assert r.command(y.command(['-s',y.path(script)],timeout=120),cwd=ROOT,log=o/'emit.log')==0
     jobs=[]
     for corner in CORNERS:
      lib={k:v for file in (pd/(SC+corner+'.lib'),sr/(SRAM+'__'+corner+'.lib'),mutex_libs/('ca_mutex_gf180_candidate__'+corner+'__scenarios.lib')) for k,v in groups(file.read_text(encoding='utf-8'),'cell')}
      pin_cache={};load_text=['library(desync_analysis_loads) { time_unit : "1ns"; capacitive_load_unit(1,pf);']
      load_text += [f'{kind}_threshold_pct_{edge} : {value};' for edge in ('rise','fall') for kind,value in (('input',50),('output',50),('slew_lower',30),('slew_upper',70))]
      for row in load_cells:
       cap=0
       for cell,pin in row['pins']:
        if cell not in pin_cache:pin_cache[cell]=dict(direct_groups(lib[cell],'pin'))|dict(direct_groups(lib[cell],'bus'))
        cap+=scalar(pin_cache[cell][pin],'capacitance')
       load_text.append('cell('+row['cell']+') { area : 0; pin(I) { direction : input; capacitance : '+str(cap)+';} }')
      loadlib=o/(corner+'-loads.lib');loadlib.write_text('\n'.join(load_text+['}']),encoding='utf-8')
      text=[f'read_liberty {{{s.path(loadlib)}}}',f'read_liberty {{{s.path(pd/(SC+corner+".lib"))}}}',f'read_liberty {{{s.path(sr/(SRAM+"__"+corner+".lib"))}}}',f'read_verilog {{{s.path(o/"analysis.v")}}}','link_design RiscayMcuDigital']
      for bank in ('cpu','fabric','control','program','ram','i2c','adc','time','power','falling'):
       for phase in ('m','s'):
        if bank=='cpu' and phase=='s':continue
        port=roots['desync_control/'+bank+'.'+phase+('/acknowledgeOut' if bank=='cpu' else '/enable')]
        text.append(f'create_clock -name {bank}_{phase} -period 1000 [get_ports {port}]')
      text+=['create_clock -name lf -period 1000 [get_ports watchdogClock]','create_clock -name sda_event -period 1000 -waveform {-500 0} [get_ports sda]',f'set_clock_transition {input_slew} [all_clocks]','set_propagated_clock [all_clocks]']
      # Transparent D-to-Q arcs are separated at each actual storage frontier.
      # Enable-to-Q launch and D setup/hold remain separate mandatory segments.
      for name,c in g['cells'].items():
       if c['type'].startswith(SC+'lat'):text.append(f'set_disable_timing -from D -to Q [get_cells {{{name}}}]')
      text += ['create_clock -name analysis -period 1000','set_input_delay 0 -clock analysis [all_inputs]',f'set_input_transition {input_slew} [all_inputs]']
      text += [r'''
     set src [all_registers -output_pins]
     set dst [all_registers -data_pins]
     puts "STORAGE [llength $src] [llength $dst]"
     set_max_delay 1000 -to $dst
     set_min_delay 0 -to $dst
     set qnames {}; foreach pin $src {dict set qnames [get_full_name $pin] 1}

     foreach sc [all_clocks] {
      set sn [get_full_name $sc];if {$sn eq "analysis"} {continue}
      set qs [all_registers -clock $sc -output_pins]
      foreach tc [all_clocks] {
       set tn [get_full_name $tc];if {$tn in {analysis lf sda_event}} {continue}
       set ds [all_registers -clock $tc -data_pins]
       foreach mode {min max} {
        set paths [find_timing_paths -through $qs -to $ds -path_delay $mode -group_path_count 1 -endpoint_path_count 1]
        puts "PAIR_COVERAGE $sn $tn $mode [llength $paths]"
        foreach path $paths {
         set points [get_property $path points];set q [lindex $points 0];set last [lindex $points end]
         puts "PAIR $sn $tn $mode [get_property $q arrival] [get_property $last arrival] [get_full_name [get_property $q pin]] [get_full_name [get_property $last pin]] [get_property $path slack]"
        }
       }
      }
     }
     puts DATA_DONE
     ''']
      for name,ip,op in sorted(arcs):
       text += [f'set es [get_timing_edges -from [get_pins {{{name}/{ip}}}] -to [get_pins {{{name}/{op}}}]]',
                'if {[llength $es]!=1} {error DISTRIBUTION_ARC_COVERAGE}',
                f'foreach mode {{min max}} {{foreach edge {{rise fall}} {{puts [list WIRE {{{name}}} {ip} {op} $mode $edge [get_property [lindex $es 0] delay_${{mode}}_${{edge}}]]}}}}']
      for name,c in g['cells'].items():
       if not (c['type'].startswith(SC+'lat') or c['type'].startswith(SC+'dff')):continue
       clock=next(p for p in ('E','CLK','CLKN') if p in c['connections'])
       for ip,op,kind in ((clock,'Q','launch'),('D','Q','data'),(clock,'D','aperture')):
        if kind=='data' and 'lat' not in c['type']:continue
        text += [f'set es [get_timing_edges -from [get_pins {{{name}/{ip}}}] -to [get_pins {{{name}/{op}}}]]',
                 f'if {{![llength $es]}} {{error STORAGE_ARC_COVERAGE:{name}:{kind}}}',
                 f'foreach arc $es {{foreach mode {{min max}} {{foreach edge {{rise fall}} {{puts [list CELL {{{name}}} {kind} $mode $edge [get_property $arc delay_${{mode}}_${{edge}}]]}}}}}}']
      text += ['puts SEGMENTS_DONE','exit']
      script=o/(corner+'.tcl');script.write_text('\n'.join(text),encoding='utf-8')
      jobs.append((corner,script))
     with ThreadPoolExecutor(max_workers=5) as pool:
      futures={c:pool.submit(r.command,s.command(['-exit',s.path(script)],timeout=600),cwd=ROOT,log=o/(c+'.log')) for c,script in jobs}
      for corner,future in futures.items():
       if future.result():raise ValueError('STA_FAILED')
       reports.append(parse_segments((o/(corner+'.log')).read_text(encoding='utf-8'),corner))
     write_json(o/'summary.json',dict(status='path-samples-only',
         scope='Worst constraint-slack samples; not Q-D extrema, closing-aperture timing or transparent-slew qualification',
         analysis_max_delay_ns=1000,input_slew_ns=input_slew,corners=reports))
     r.finish(outputs=[f for f in o.iterdir() if f.is_file() and f.name!='receipt.json'])
    except BaseException:
     if not r.finished:r.finish(outputs=[f for f in o.iterdir() if f.is_file() and f.name!='receipt.json'],status='fail')
     raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mapping',type=Path);p.add_argument('repaired',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--input-slew',type=float,choices=(.02,2.),required=True)
    p.add_argument('--mutex-libs',type=Path,required=True)
    a=p.parse_args();run(a.mapping.resolve(),a.repaired.resolve(),a.output.resolve(),a.input_slew,a.mutex_libs.resolve())

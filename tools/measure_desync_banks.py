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
from area_ratio import storage_width
from report_clock_owners import clock_nets


def cut_storage(analysis, original, routes, roots, library):
    """Analysis only: equal-arrival Q ports and equal-required-time D ports.

    No clock/tree/setup contribution can affect path ranking. All removed input
    pins are returned to the common load-restoration pass, including reset and
    enable pins. Sampling Q slew is not a proof of transparent-latch slew bounds.
    """
    body=analysis['modules']['RiscayMcuDigital']; before=original['modules']['RiscayMcuDigital']
    retained=clock_nets(before['cells'],{k:v['bits'] for k,v in before['netnames'].items()},
                       roots={'watchdogClock':'lf','sda':'sda_event'})
    named={alias:owner.removeprefix('desync_control/').split('/')[0].replace('.','_') for owner,alias in roots.items()}
    state_types={kind for kind in {c['type'] for c in before['cells'].values()}
                 if kind in library and (storage_width(library[kind]) or kind==SRAM)}
    removed=set(); ports=[]; qbits=set()
    for name,cell in sorted(before['cells'].items()):
        if cell['type'] not in library:raise ValueError('DESYNC_DATA_LIBRARY_MISSING')
        if cell['type'] not in state_types:continue
        clock=next(p for p in ('E','CLK','CLKN') if p in cell['connections'])
        route=routes.get(name+'/'+clock)
        domain=named[route['root']] if route else retained.get(cell['connections'][clock][0])
        if domain is None:raise ValueError('DESYNC_DATA_DOMAIN_MISSING:'+name)
        removed.add(name);del body['cells'][name]
        for pin,bits in cell['connections'].items():
            direction=cell['port_directions'][pin]
            is_q=direction=='output'
            is_d=pin in (('A','D','CEN','GWEN','WEN') if cell['type']==SRAM else ('D',))
            if not (is_q or is_d):continue
            for lane,bit in enumerate(bits):
                if is_q and (not isinstance(bit,int) or bit in qbits):raise ValueError('DESYNC_DATA_DUPLICATE_Q')
                if is_q:qbits.add(bit)
                alias='segment_'+str(len(ports))
                body['ports'][alias]=dict(direction='input' if is_q else 'output',bits=[bit])
                body['netnames'][alias]=dict(hide_name=0,attributes={},bits=[bit])
                ports.append(dict(port=alias,domain=domain,kind='q' if is_q else 'd',cell=name,
                                  pin=pin,lane=lane,bit=bit))
    if not removed:raise ValueError('DESYNC_DATA_STORAGE_MISSING')
    return removed,ports


def data_reachability(body, ports):
    """Independent net-graph reachability; empty STA pairs must really be empty.

    Treat all cell inputs as dependencies, conservatively. A library-masked path
    must be explained rather than silently disappear from the coverage report.
    """
    from functools import lru_cache
    drivers={};origins={};active=set()
    for row in ports:
        if row['kind']=='q':origins[row['bit']]={row['domain']}
    for cell in body['cells'].values():
        inputs={b for p,bs in cell['connections'].items() if cell['port_directions'][p]=='input' for b in bs}
        for pin,bits in cell['connections'].items():
            if cell['port_directions'][pin]!='output':continue
            for bit in bits:
                if bit in drivers or bit in origins:raise ValueError('DESYNC_DATA_MULTIPLE_DRIVER')
                drivers[bit]=inputs
    @lru_cache(None)
    def sources(bit):
        if bit in active:raise ValueError('DESYNC_DATA_LOOP')
        active.add(bit)
        value=set(origins.get(bit,()))
        for prior in drivers.get(bit,()):value.update(sources(prior))
        active.remove(bit)
        return frozenset(value)
    return {(source,row['domain']) for row in ports if row['kind']=='d' for source in sources(row['bit'])}


def data_queries(ports, period):
    text=[f'create_clock -name analysis -period {period}',
          'set_input_delay 0 -clock analysis [all_inputs]',
          'set_output_delay 0 -clock analysis [all_outputs]',
          # Zero required time avoids float cancellation when ranking near ties.
          # Negative max-path slack is expected, not a setup verdict.
          'set_max_delay 0 -from [all_inputs] -to [all_outputs]',
          'set_min_delay 0 -from [all_inputs] -to [all_outputs]']
    # Only the original top outputs have external load. Cut D ports are loaded
    # by the restored original pin capacitances, never a second artificial load.
    text += ['puts {STORAGE '+str(sum(p['kind']=='q' for p in ports))+' '+str(sum(p['kind']=='d' for p in ports))+'}']
    for kind in ('q','d'):
        for domain in sorted({p['domain'] for p in ports if p['kind']==kind}):
            names=' '.join(p['port'] for p in ports if p['kind']==kind and p['domain']==domain)
            text.append(f'set {kind}_{domain} [get_ports {{{names}}}]')
    for source in sorted({p['domain'] for p in ports if p['kind']=='q'}):
        for target in sorted({p['domain'] for p in ports if p['kind']=='d'}):
            for mode in ('min','max'):
                text += [f'set paths [find_timing_paths -from $q_{source} -to $d_{target} -path_delay {mode} -group_path_count 1 -endpoint_path_count 1]',
                    f'puts "PAIR_COVERAGE {source} {target} {mode} [llength $paths]"',
                    'foreach path $paths {set points [get_property $path points]; set q [lindex $points 0]; set d [lindex $points end]',
                    f'puts "PAIR {source} {target} {mode} [get_property $q arrival] [get_property $d arrival] [get_full_name [get_property $q pin]] [get_full_name [get_property $d pin]] [get_property $path slack]"'+'}']
    return text+['puts SEGMENTS_DONE','exit']


def audit_data_view(original, analysis, ports, removed, library, loads, bindings=()):
    """Check the actual view and loads against original cell pins, not totals."""
    from collections import Counter
    before=original['modules']['RiscayMcuDigital'];after=analysis['modules']['RiscayMcuDigital']
    kinds={kind for kind in {c['type'] for c in before['cells'].values()}
           if storage_width(library[kind]) or kind==SRAM}
    native={b['instance']+'/'+c['name'] for b in bindings
            for c in resolve_candidate(b['primitive'],b.get('parameters'))['cells']}
    if removed!=native|{n for n,c in before['cells'].items() if c['type'] in kinds}:
        raise ValueError('DESYNC_DATA_REMOVAL_COVERAGE')
    expected={(name,p,i,b) for name,c in before['cells'].items() if c['type'] in kinds
              for p,bs in c['connections'].items()
              if c['port_directions'][p]=='output' or p in (('A','D','CEN','GWEN','WEN') if c['type']==SRAM else ('D',))
              for i,b in enumerate(bs)}
    actual={(p['cell'],p['pin'],p['lane'],p['bit']) for p in ports}
    if actual!=expected or len(actual)!=len(ports):raise ValueError('DESYNC_DATA_ENDPOINT_COVERAGE')
    for row in ports:
        is_q=before['cells'][row['cell']]['port_directions'][row['pin']]=='output'
        if row['kind']!=('q' if is_q else 'd'):raise ValueError('DESYNC_DATA_ENDPOINT_KIND')
        expected_port=dict(direction='input' if row['kind']=='q' else 'output',bits=[row['bit']])
        if after['ports'].get(row['port'])!=expected_port:raise ValueError('DESYNC_DATA_ENDPOINT_BINDING')
    helpers={r['instance'] for r in loads}
    ordinary={n:c for n,c in after['cells'].items() if n not in helpers}
    if ordinary!={n:c for n,c in before['cells'].items() if n not in removed}:raise ValueError('DESYNC_DATA_LOGIC_CHANGED')
    live={b for c in ordinary.values() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs}
    live.update(b for p in after['ports'].values() if p['direction']=='input' for b in p['bits'])
    expected_loads=Counter((before['cells'][n]['type'],p,b) for n in removed
        for p,bs in before['cells'][n]['connections'].items() if before['cells'][n]['port_directions'][p]=='input'
        for b in bs if isinstance(b,int) and b in live)
    actual_loads=Counter((cell,pin,row['bit']) for row in loads for cell,pin in row['pins'])
    if expected_loads!=actual_loads:raise ValueError('DESYNC_DATA_LOAD_COVERAGE')
    for row in loads:
        helper=after['cells'].get(row['instance'])
        if not helper or helper['type']!=row['cell'] or helper['connections']!={'I':[row['bit']]}:
            raise ValueError('DESYNC_DATA_LOAD_BINDING')
    return dict(q_pins=sum(r['kind']=='q' for r in ports),d_pins=sum(r['kind']=='d' for r in ports),
                ordinary_cells=len(ordinary),restored_pin_loads=sum(actual_loads.values()))


def validate_data_report(report,ports,reachable):
    if report['storage_q_and_d_pins']!=[sum(p['kind']=='q' for p in ports),sum(p['kind']=='d' for p in ports)]:
        raise ValueError('DESYNC_DATA_STORAGE_COVERAGE')
    for mode in ('min','max'):
        found={(row['source'],row['target']) for row in report['rows'] if row['mode']==mode}
        if found!=reachable:raise ValueError('DESYNC_DATA_REACHABILITY:'+str(sorted(reachable^found)))
    names={p['port']:p for p in ports}
    for row in report['rows']:
        if abs(row['selected_q_arrival_ns'])>1e-9:raise ValueError('DESYNC_DATA_NONZERO_LAUNCH')
        q,d=names.get(row['q']),names.get(row['d'])
        if not q or not d or q['kind']!='q' or d['kind']!='d' or (q['domain'],d['domain'])!=(row['source'],row['target']):
            raise ValueError('DESYNC_DATA_PATH_BINDING')
        row.update(segment_ns=row['selected_d_arrival_ns'],
                   source_pin=f"{q['cell']}/{q['pin']}[{q['lane']}]",target_pin=f"{d['cell']}/{d['pin']}[{d['lane']}]")

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

def run(m,p,o,input_slew,mutex_libs,data_only=False,period=1000):
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
    pd=ROOT/'.tools/physical/pdk';sr=ROOT/'.tools/gf180-sram'
    removed_nodes=set(native);data_ports=[];reachable=set()
    if data_only:
        library={k:v for path in (pd/(SC+CORNERS[0]+'.lib'),sr/(SRAM+'__'+CORNERS[0]+'.lib'),mutex_libs/('ca_mutex_gf180_candidate__'+CORNERS[0]+'__scenarios.lib')) for k,v in groups(path.read_text(encoding='utf-8'),'cell')}
        storage_nodes,data_ports=cut_storage(a,n,routes,roots,library);removed_nodes.update(storage_nodes)
        reachable=data_reachability(body,data_ports)
        write_json(o/'data-ports.json',data_ports)
    # Preserve the capacitance of every removed native/storage input on any live
    # analysis net. Otherwise parent drivers and enable trees look too fast.
    live={bit for row in cells.values() for pin,bits in row['connections'].items()
          if row['port_directions'][pin]=='output' for bit in bits}
    live.update(bit for row in body['ports'].values() if row['direction']=='input' for bit in row['bits'])
    removed={}
    for name in sorted(removed_nodes):
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
        load_cells.append(dict(cell=kind,pins=pins,bit=bit,instance='analysis_load_'+str(i)))
    if data_only:write_json(o/'view-audit.json',audit_data_view(n,a,data_ports,removed_nodes,library,load_cells,b))
    write_json(o/'restored-loads.json',load_cells)
    write_json(o/'routes.json',routes)
    write_json(o/'analysis.json',a);write_json(o/'roots.json',roots)
    y=tool('yosys');s=tool('sta')
    r=RunReceipt(o/'receipt.json',inputs=[p/'repaired.json',m/'control.json',*[pd/(SC+c+'.lib') for c in CORNERS],*[sr/(SRAM+'__'+c+'.lib') for c in CORNERS],*[mutex_libs/('ca_mutex_gf180_candidate__'+c+'__scenarios.lib') for c in CORNERS]],tools=[Path(__file__),*[ROOT/'tools'/name for name in ('primitives.py','area_ratio.py','report_clock_owners.py','gf180_estimate.py','repair_gf180_design.py')],*y.input_files(),*s.input_files()])
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
      if data_only:
       text += [f'set_input_transition {input_slew} [all_inputs]']
       for name,port in n['modules']['RiscayMcuDigital']['ports'].items():
        if port['direction']=='output':text.append(f'set_load .05 [get_ports {{{name}}}]')
       text += data_queries(data_ports,period)
       script=o/(corner+'.tcl');script.write_text('\n'.join(text),encoding='utf-8');jobs.append((corner,script));continue
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
       report=parse_segments((o/(corner+'.log')).read_text(encoding='utf-8'),corner)
       if data_only:validate_data_report(report,data_ports,reachable)
       reports.append(report)
     write_json(o/'summary.json',dict(status='cut-segment-samples' if data_only else 'path-samples-only',
         scope=('True combinational extrema at the sampled Q slew; not a continuous slew envelope, closing-aperture or transparent-latch qualification' if data_only else 'Worst constraint-slack samples; not Q-D extrema, closing-aperture timing or transparent-slew qualification'),
         analysis_max_delay_ns=0 if data_only else 1000,analysis_period_ns=period if data_only else 1000,
         input_slew_ns=input_slew,corners=reports))
     r.finish(outputs=[f for f in o.iterdir() if f.is_file() and f.name!='receipt.json'])
    except BaseException:
     if not r.finished:r.finish(outputs=[f for f in o.iterdir() if f.is_file() and f.name!='receipt.json'],status='fail')
     raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mapping',type=Path);p.add_argument('repaired',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--input-slew',type=float,choices=(.02,2.),required=True)
    p.add_argument('--mutex-libs',type=Path,required=True)
    p.add_argument('--data-only',action='store_true',help='Cut all storage to measure pure data segments at the selected Q slew')
    p.add_argument('--period',type=float,default=1000,help='Analysis period for invariance control (data-only mode)')
    a=p.parse_args();run(a.mapping.resolve(),a.repaired.resolve(),a.output.resolve(),a.input_slew,a.mutex_libs.resolve(),a.data_only,a.period)

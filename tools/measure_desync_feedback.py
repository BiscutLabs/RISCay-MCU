# SPDX-License-Identifier: Apache-2.0
"""Full-feedback, loaded direct-latch handoff characterization (not signoff).

Retain the actual controller, distribution trees and every paired latch. Cut
only source D at the timing frontier; retain its old pin load on any live net.
External omitted sinks are lumped Liberty capacitances. No keeper timing cuts,
Liberty slew interpolation, delay sizing or physical qualification is performed.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
import json
import math
from pathlib import Path
import re

from characterize_desync_primitives import CORNERS, subcircuits
from gf180_estimate import groups, direct_groups, scalar
from gf180_physical import ROOT, SC, write_json
from measure_desync_handoff import pair_inventory
from physical_tools import tool
from primitives import resolve_candidate
from repair_gf180_design import ident
from run_receipt import RunReceipt


def prepare(body, bindings, roots, routes, bank):
    """Discover real paired sinks and retain their complete enable/ACK cones."""
    cells=body['cells']; indexed={b['instance']:b for b in bindings}
    source=indexed['desync_control/'+bank+'.m']; target=indexed['desync_control/'+bank+'.s']
    parameters=dict(initial_open=True,same_count=0,closed_count=0,rise_qualified=False)
    if source['primitive']!='RiscayDesyncQualifiedController' or source['parameters']!=parameters:
        raise ValueError('FEEDBACK_UNSUPPORTED_CONTROLLER')
    if source['ports']['acknowledgeIn']!=target['ports']['acknowledgeOut']:
        raise ValueError('FEEDBACK_NOT_DIRECT_ACK')
    pairs=pair_inventory(body,routes,roots,source,target)
    recipe=resolve_candidate(source['primitive'],source['parameters'])
    selected={source['instance']+'/'+c['name'] for c in recipe['cells']}
    # Registry-to-actual-pin correspondence, including the two feedback loops.
    nets={}
    for leaf in recipe['cells']:
        c=cells[source['instance']+'/'+leaf['name']]
        if c['type']!=leaf['cell'] or set(c['connections'])!=set(leaf['pins']):
            raise ValueError('FEEDBACK_NATIVE_RECIPE')
        for pin,net in leaf['pins'].items():
            bit=c['connections'][pin]
            if len(bit)!=1 or nets.setdefault(net,bit[0])!=bit[0]:raise ValueError('FEEDBACK_NATIVE_WIRING')
    target_inverter=target['instance']+'/enable_invert__cell'
    if cells[target_inverter]['type']!=SC+'inv_1':raise ValueError('FEEDBACK_CAPTURE_INVERTER')
    selected.add(target_inverter); root=cells[target_inverter]['connections']['I'][0]
    drivers={b:(n,p) for n,c in cells.items() for p,bs in c['connections'].items()
             if c['port_directions'][p]=='output' for b in bs}
    def route(bit,visited=None):
        visited=set() if visited is None else visited
        if bit==root:return
        if bit in visited:raise ValueError('FEEDBACK_DISTRIBUTION_LOOP')
        visited.add(bit)
        if bit not in drivers:raise ValueError('FEEDBACK_UNKNOWN_FRONTIER')
        n,p=drivers[bit]
        if n in selected:return
        c=cells[n]
        if not c['type'].startswith((SC+'buf_',SC+'clkbuf_')):raise ValueError('FEEDBACK_NONBUFFER_ROUTE')
        route(c['connections']['I'][0],visited);selected.add(n)
    ends={}
    for q,d in pairs:
        for p,rise in ((q,True),(d,False)):
            bit=cells[p.rsplit('/',1)[0]]['connections']['E'][0]
            if bit in ends and ends[bit]!=rise:raise ValueError('FEEDBACK_SHARED_ENABLE')
            ends[bit]=rise;route(bit)
    # ACK must reach the same receiver-A frontier, never an already-selected
    # source feedback node that the enable-cone traversal is allowed to stop at.
    ack=nets['acknowledgeIn'];seen=set()
    while ack!=root:
        if ack in seen or ack not in drivers:raise ValueError('FEEDBACK_ACK_FRONTIER')
        seen.add(ack);n,p=drivers[ack];c=cells[n]
        if not c['type'].startswith((SC+'buf_',SC+'clkbuf_')):raise ValueError('FEEDBACK_ACK_FRONTIER')
        selected.add(n);ack=c['connections']['I'][0]
    selected.update(p.rsplit('/',1)[0] for pair in pairs for p in pair)
    view={n:deepcopy(cells[n]) for n in sorted(selected)};cuts=[]
    for q,d in pairs:
        n=q.rsplit('/',1)[0];bit=view[n]['connections']['D'][0]
        cuts.append(dict(cell=n,pin='D',bit=bit));view[n]['connections']['D']=['data']
    driven={b for c in view.values() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs}
    # Include every omitted input pin AND each cut source-D load on live nets.
    loads=defaultdict(list)
    for n,c in cells.items():
        for p,bs in c['connections'].items():
            if c['port_directions'][p]!='input':continue
            for bit in bs:
                if bit in driven and (n not in selected or view[n]['connections'][p]!=bs):
                    loads[bit].append(dict(cell=n,type=c['type'],pin=p))
    frontier=defaultdict(set)
    for c in view.values():
        for p,bs in c['connections'].items():
            if c['port_directions'][p]=='input':
                for bit in bs:
                    if bit not in driven:frontier[bit].add(p)
    reset,request=nets['reset'],nets['requestIn']
    other=set(frontier)-{root,reset,request,'data','0','1'}
    if any(not frontier[b]<= {'RN','SETN'} for b in other):raise ValueError('FEEDBACK_UNKNOWN_FRONTIER')
    if root in driven or not {root,reset,request,'data'}<=set(frontier):raise ValueError('FEEDBACK_FRONTIER_ALIAS')
    return dict(cells=view,pairs=pairs,loads=dict(loads),cuts=cuts,root=root,reset=reset,request=request,
        inactive_resets=sorted(other),ends=ends,source_nets=nets,target_inverter=target_inverter)


def deck(fixture,library,headers,pdk,runtime,corner,slew,old,step,late,wave):
    _,process,temp,voltage=corner
    net=lambda b: '0' if b=='0' else 'vdd' if b=='1' else 'data' if b=='data' else 'n'+str(b)
    pins={k:dict(direct_groups(v,'pin')) for k,v in library.items()}
    lines=['Actual direct handoff, full feedback and latch bank; zero wire RC',
        f'.include "{runtime.path(pdk/"design.ngspice")}"',
        f'.lib "{runtime.path(pdk/"sm141064.ngspice")}" {process}',
        f'.include "{runtime.path(pdk/"gf180mcu_fd_sc_mcu7t5v0.spice")}"',
        '.param sw_stat_global=0 sw_stat_mismatch=0',f'.temp {temp}',
        '.options method=gear reltol=1e-5 abstol=1e-13 vntol=1e-7',f'Vdd vdd 0 {voltage}']
    # Slew here is physical 30--70%, not an unconverted Liberty table index.
    ramp=slew/.4
    root_wave=[(0,1),(80,1),(80+ramp,0),(160,0),(160+ramp,1)]
    waves={'reset':(net(fixture['reset']),[(0,1),(10,1),(10.05,0)]),
           'request':(net(fixture['request']),[(0,0),(40,0),(40.05,1),(120,1),(120.05,0)]),
           'root':(net(fixture['root']),root_wave),
           'data':('data',[(0,old),(140,old),(140.05,1-old)])}
    if late:waves['late']=('late_root',[(t+(late if t else 0),v) for t,v in root_wave])
    for name,(node,points) in waves.items():
        lines.append(f'V{name} {node} 0 PWL('+' '.join(f'{t}n {v*voltage}' for t,v in points)+')')
    for bit in fixture['inactive_resets']:lines.append(f'Vr{bit} {net(bit)} 0 {voltage}')
    for i,(name,c) in enumerate(fixture['cells'].items()):
        conn={p:net(bs[0]) for p,bs in c['connections'].items()}|dict(VDD='vdd',VNW='vdd',VPW='0',VSS='0')
        if late and name==fixture['target_inverter']:conn['I']='late_root'
        if set(conn)!=set(headers[c['type']]):raise ValueError('FEEDBACK_SPICE_PINS')
        lines.append(f'X{i} '+' '.join(conn[p] for p in headers[c['type']])+' '+c['type'])
    for bit,loads in fixture['loads'].items():
        cap=sum(scalar(pins[r['type']][r['pin']],'capacitance') for r in loads)
        if not math.isfinite(cap) or cap<=0:raise ValueError('FEEDBACK_INVALID_LOAD')
        lines.append(f'C{bit} {net(bit)} 0 {cap}p')
    for i,(q,d) in enumerate(fixture['pairs']):
        for label,p in (('m',q),('s',d)):
            c=fixture['cells'][p.rsplit('/',1)[0]];node=net(c['connections']['Q'][0])
            # Entire old-value window, not just an endpoint that can hide a glitch.
            for bound in ('MIN','MAX'):
                end=155 if label=='m' else 210
                lines.append(f'.meas tran {label}{i}_{bound.lower()} {bound} v({node}) FROM=110n TO={end}n')
            lines.append(f'.meas tran {label}{i}_end FIND v({node}) AT=205n')
        source=net(fixture['cells'][q.rsplit('/',1)[0]]['connections']['Q'][0])
        lines.append(f'.meas tran q{i}_time WHEN v({source})={voltage*.5} TD=159n '+('FALL' if old else 'RISE')+'=1')
    signals=sorted(set(fixture['ends'])|{fixture['root'],*[fixture['source_nets'][n] for n in ('acknowledgeOut','requestOut','enable')]})
    lines += [f'.tran {step}n 210n 0 {step}n','.control','set numdgt=15','set wr_singlescale','run',
              'wrdata '+runtime.path(wave)+' '+' '.join('v('+net(b)+')' for b in signals),'quit','.endc','.end']
    return '\n'.join(lines)+'\n',signals


def check_wave(rows,signals,fixture,voltage,step):
    if len(rows)<2 or any(len(r)!=len(signals)+1 or not all(math.isfinite(v) for v in r) for r in rows):
        raise ValueError('FEEDBACK_WAVEFORM_INVALID')
    times=[r[0]*1e9 for r in rows]
    if times[0]>0 or times[-1]<210-1e-6 or any(not 0<b-a<=step*1.00001 for a,b in zip(times,times[1:])):
        raise ValueError('FEEDBACK_WAVEFORM_COVERAGE')
    traces={b:[r[i+1]/voltage for r in rows] for i,b in enumerate(signals)}
    def at(trace,t):
        return next(a+(b-a)*(t-x)/(y-x) for x,y,a,b in zip(times,times[1:],trace,trace[1:]) if x<=t<=y)
    states=[(5,0,0,1),(30,0,0,1),(70,1,0,0),(110,1,1,0),(150,1,1,0),(205,0,0,1)]
    for t,a,b,n in states:
        for name,value in (('acknowledgeOut',a),('requestOut',b),('enable',n)):
            if abs(at(traces[fixture['source_nets'][name]],t)-value)>.1:raise ValueError('FEEDBACK_LEGAL_HISTORY')
    transitions=fixture['ends']|{fixture['source_nets'][name]:rise for name,rise in
        (('acknowledgeOut',False),('requestOut',False),('enable',True))}
    crossings={}
    for bit,rise in transitions.items():
        trace=traces[bit]
        if any(not -.1<=v<=1.1 for v in trace):raise ValueError('FEEDBACK_VOLTAGE_RANGE')
        if bit in fixture['ends']:
            for t,value in ((30,int(rise)),(70,0),(110,int(not rise)),(150,int(not rise)),(205,int(rise))):
                if abs(at(trace,t)-value)>.1:raise ValueError('FEEDBACK_ENABLE_HISTORY')
        progress=trace if rise else [1-v for v in trace];cross={}
        for threshold in (.3,.5,.7):
            forward=[];reverse=[]
            for x,y,a,b in zip(times,times[1:],progress,progress[1:]):
                if y<110:continue
                if a<threshold<=b:forward.append(x+(y-x)*(threshold-a)/(b-a))
                if a>threshold>=b:reverse.append(x+(y-x)*(threshold-a)/(b-a))
            if len(forward)!=1 or reverse or forward[0]<160:raise ValueError('FEEDBACK_ENABLE_RETAINED_EDGE')
            cross[str(threshold)]=forward[0]
        crossings[bit]=dict(time_ns=cross['0.5'],slew_ns=cross['0.7']-cross['0.3'])
    return crossings


def check_measurements(text,pair_count,old,voltage):
    if re.search(r'\b(error|failed|warning)\b',text,re.I):raise ValueError('FEEDBACK_SPICE_ERROR')
    entries=re.findall(r'^\s*([msq]\d+_\w+)\s*=\s*([-+0-9.eE]+)',text,re.M)
    values={n:float(v) for n,v in entries}
    needed={f'{p}{i}_{k}' for i in range(pair_count) for p in ('m','s') for k in ('min','max','end')}
    needed|={f'q{i}_time' for i in range(pair_count)}
    if len(entries)!=len(values) or set(values)!=needed or not all(math.isfinite(v) for v in values.values()):raise ValueError('FEEDBACK_MEASUREMENT_COVERAGE')
    for i in range(pair_count):
        for p in ('m','s'):
            for bound in ('min','max'):
                if abs(values[f'{p}{i}_{bound}']/voltage-old)>.1:raise ValueError('FEEDBACK_DATA_RETENTION:'+p+str(i))
            expected=1-old if p=='m' else old
            if abs(values[f'{p}{i}_end']/voltage-expected)>.1:raise ValueError('FEEDBACK_SOURCE_REUSE:'+p+str(i))
        if not 160<values[f'q{i}_time']*1e9<205:raise ValueError('FEEDBACK_REUSE_TIME')
    return [values[f'q{i}_time']*1e9 for i in range(pair_count)]


def run(mapping,repaired,segments,output,pdk,bank,step,late,corners,slews,polarities):
    if not math.isfinite(step) or not 0<step<=.2 or not math.isfinite(late) or not 0<=late<=10:
        raise ValueError('FEEDBACK_TIMING_POLICY')
    if not corners or any(c not in CORNERS for c in corners) or not slews or any(s not in (.02,2.) for s in slews) or not polarities or any(p not in (0,1) for p in polarities):
        raise ValueError('FEEDBACK_CASE_INVENTORY')
    output.mkdir(parents=True,exist_ok=False);runtime=tool('ngspice');read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    files=[mapping/'control.json',repaired/'repaired.json',segments/'roots.json',segments/'routes.json']
    files += [pdk/n for n in ('design.ngspice','sm141064.ngspice','gf180mcu_fd_sc_mcu7t5v0.spice')]
    files += [pdk/(SC+c[0]+'.lib') for c in corners]
    receipt=RunReceipt(output/'receipt.json',inputs=files,tools=[Path(__file__),*[ROOT/'tools'/n for n in
        ('primitives.py','measure_desync_handoff.py','characterize_desync_primitives.py','gf180_estimate.py',
         'gf180_physical.py','repair_gf180_design.py','run_receipt.py')],*runtime.input_files()])
    try:
        body=read(repaired/'repaired.json')['modules']['RiscayMcuDigital']
        body['cells']={ident(n):c for n,c in body['cells'].items()}
        f=prepare(body,read(mapping/'control.json')['bindings'],read(segments/'roots.json'),read(segments/'routes.json'),bank)
        write_json(output/'fixture.json',f);headers=subcircuits((pdk/'gf180mcu_fd_sc_mcu7t5v0.spice').read_text(encoding='utf-8'));results=[]
        for corner in corners:
            library=dict(groups((pdk/(SC+corner[0]+'.lib')).read_text(encoding='utf-8'),'cell'))
            for slew in slews:
                for old in polarities:
                    label=f'{corner[0]}-s{slew}-old{old}';wave=output/(label+'.dat')
                    source=output/(label+'.spice');log=output/(label+'.log')
                    text,signals=deck(f,library,headers,pdk,runtime,corner,slew,old,step,late,wave)
                    source.write_text(text,encoding='utf-8')
                    if receipt.command(runtime.command(['-b',runtime.path(source)],timeout=600),cwd=ROOT,log=log):raise ValueError('FEEDBACK_SPICE_PROCESS')
                    edge=check_wave([list(map(float,l.split())) for l in wave.read_text(encoding='utf-8').splitlines()],signals,f,corner[3],step)
                    qtime=check_measurements(log.read_text(encoding='utf-8'),len(f['pairs']),old,corner[3])
                    separations=[qt-edge[f['cells'][d.rsplit('/',1)[0]]['connections']['E'][0]]['time_ns'] for qt,(q,d) in zip(qtime,f['pairs'])]
                    row=dict(corner=corner[0],physical_slew_30_70_ns=slew,old=old,enable_edges=edge,
                        q_times_ns=qtime,minimum_data_separation_ns=min(separations))
                    results.append(row);write_json(output/'samples.json',dict(scope='Full-feedback schematic samples with lumped external loads; no mismatch/routed/pulse/continuous-envelope qualification',
                        bank=bank,pairs=len(f['pairs']),max_step_ns=step,late_capture_ns=late,rows=results))
                    print(label,'retained',len(f['pairs']),'minimum raw data separation',min(separations),flush=True)
    except BaseException:
        if not receipt.finished:receipt.finish(outputs=[p for p in output.iterdir() if p.is_file() and p.name!='receipt.json'],status='fail')
        raise
    receipt.finish(outputs=[p for p in output.iterdir() if p.is_file() and p.name!='receipt.json'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('mapping','repaired','segments','output'):p.add_argument(n,type=Path)
    p.add_argument('--pdk',type=Path,default=ROOT/'.tools/physical/pdk');p.add_argument('--bank',default='i2c')
    p.add_argument('--max-step',type=float,default=.2);p.add_argument('--late-capture',type=float,default=0)
    p.add_argument('--corner',choices=[c[0] for c in CORNERS]);p.add_argument('--slew',type=float,choices=(.02,2.))
    p.add_argument('--old',type=int,choices=(0,1));a=p.parse_args()
    run(a.mapping,a.repaired,a.segments,a.output,a.pdk,a.bank,a.max_step,a.late_capture,
        [c for c in CORNERS if not a.corner or c[0]==a.corner],[a.slew] if a.slew is not None else [.02,2.],
        [a.old] if a.old is not None else [0,1])

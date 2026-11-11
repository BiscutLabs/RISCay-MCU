# SPDX-License-Identifier: Apache-2.0
"""Sample actual work-gate return ordering with native feedback intact.

This checks closing, not qualifier setup before opening. Omitted external sinks
are inventoried pin capacitances; finite schematic samples are not OCV/RC bounds.
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
from gf180_physical import ROOT, SC, SRAM, write_json
from physical_tools import tool
from primitives import resolve_candidate
from repair_gf180_design import ident
from run_receipt import RunReceipt


def inventory(body,bindings):
    """Walk actual storage clock pins; routes.json is not a coverage authority."""
    cells=body['cells'];ports={};native={};owners={}
    for b in bindings:
        recipe=resolve_candidate(b['primitive'],b['parameters']);nets={}
        for leaf in recipe['cells']:
            name=b['instance']+'/'+leaf['name'];c=cells[name];owners[name]=b['instance']
            if c['type']!=leaf['cell'] or set(c['connections'])!=set(leaf['pins']):raise ValueError('GATE_NATIVE_RECIPE')
            for pin,net in leaf['pins'].items():
                bits=c['connections'][pin]
                if len(bits)!=1 or nets.setdefault(net,bits[0])!=bits[0]:raise ValueError('GATE_NATIVE_WIRING')
        ports[b['instance']]={p:nets[p] for p in recipe['ports']}
        for p,d in recipe['ports'].items():
            if d=='output':native[nets[p]]=(b['instance'],p)
    drivers={bit:(n,p) for n,c in cells.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for bit in bs}
    retained={b:('retained:'+n,'clock') for n,p in body.get('ports',{}).items()
              if n in ('watchdogClock','sda') and p['direction']=='input' for b in p['bits']}
    found={};cache={};active=set()
    def route(bit):
        if bit in native:return native[bit],[]
        if bit in retained:return retained[bit],[]
        if bit in cache:return cache[bit]
        if bit in active:raise ValueError('GATE_CLOCK_LOOP')
        if bit not in drivers:return None
        active.add(bit);n,p=drivers[bit];c=cells[n];result=None
        if c['type'].startswith((SC+'buf_',SC+'clkbuf_',SC+'and2_')):
            paths=[(ip,route(bs[0])) for ip,bs in c['connections'].items() if c['port_directions'][ip]=='input']
            paths=[(ip,r) for ip,r in paths if r]
            if len(paths)>1:raise ValueError('GATE_MULTIPLE_CLOCK_ROOTS')
            if paths:
                ip,(root,path)=paths[0];result=root,path+[n]
                if c['type'].startswith(SC+'and2_'):
                    if root[0].startswith('retained:'):raise ValueError('GATE_RETAINED_CLOCK_LOGIC')
                    qp=next(k for k in c['connections'] if k!=ip and c['port_directions'][k]=='input')
                    found[n]=dict(gate=n,clock_pin=ip,qualifier_pin=qp,target=root[0],root_port=root[1],clock_path=path)
        active.remove(bit);cache[bit]=result;return result
    for n,c in cells.items():
        if c['type'].startswith((SC+'lat',SC+'dff')) or c['type']==SRAM:
            pin=next(p for p in ('E','CLK','CLKN') if p in c['connections'])
            if not route(c['connections'][pin][0]):raise ValueError('GATE_UNKNOWN_STORAGE_CLOCK:'+n+'/'+pin)
    if not found:raise ValueError('GATE_INVENTORY_EMPTY')
    for row in found.values():
        bit=cells[row['gate']]['connections'][row['qualifier_pin']][0];path=[]
        while True:
            if bit not in drivers:raise ValueError('GATE_QUALIFIER_DRIVER')
            n,p=drivers[bit];c=cells[n]
            if c['type'].startswith((SC+'buf_',SC+'clkbuf_')):
                if n in path:raise ValueError('GATE_QUALIFIER_LOOP')
                path.append(n);bit=c['connections']['I'][0];continue
            if p!='Q' or not c['type'].startswith(SC+'lat'):raise ValueError('GATE_QUALIFIER_NOT_LATCH')
            phase=route(c['connections']['E'][0])
            if not phase or phase[0][1]!='enable' or any(cells[k]['type'].startswith(SC+'and') for k in phase[1]):
                raise ValueError('GATE_QUALIFIER_ENABLE')
            row.update(qualifier=n,qualifier_path=path,source=phase[0][0],source_enable_path=phase[1]);break
        if row['root_port'] not in ('enable','acknowledgeOut'):raise ValueError('GATE_ROOT_KIND')
    # Fixtures/artifacts are indexed by target. Never overwrite a second gate
    # silently if a future graph gives one controller multiple gated branches.
    if len({r['target'] for r in found.values()})!=len(found):raise ValueError('GATE_DUPLICATE_TARGET')
    return sorted(found.values(),key=lambda r:r['target']),ports,owners,native,drivers


def prepare(body,bindings,row,ports,owners,native,drivers):
    cells=body['cells'];indexed={b['instance']:b for b in bindings};selected={row['gate'],row['qualifier']}
    source=indexed[row['source']];params=source['parameters']
    if source['primitive']!='RiscayDesyncQualifiedController' or params['same_count'] or params['rise_qualified']:
        raise ValueError('GATE_UNSUPPORTED_OWNER')
    root=ports[row['target']]['acknowledgeOut'];clock_falls=row['root_port']=='acknowledgeOut'
    frontiers=set();resets=set();visited=set();active=set()
    def keep(b):
        for leaf in resolve_candidate(b['primitive'],b['parameters'])['cells']:selected.add(b['instance']+'/'+leaf['name'])
        resets.add(ports[b['instance']]['reset'])
    keep(source)
    target_inverter=row['target']+'/enable_invert__cell'
    def trace(bit):
        if bit==root:return
        if bit in active:raise ValueError('GATE_RETURN_LOOP')
        if bit in visited:return
        active.add(bit)
        trace_input(bit)
        active.remove(bit);visited.add(bit)
    def trace_input(bit):
        if bit in native:
            owner,p=native[bit]
            if owner==row['target'] and p=='enable':
                selected.add(target_inverter);trace(cells[target_inverter]['connections']['I'][0]);return
            binding=indexed[owner]
            if binding['primitive']=='RiscayDesyncJoin':
                keep(binding)
                for p in ('input0','input1'):trace(ports[owner][p])
            elif owner==row['source']:
                raise ValueError('GATE_RETURN_SELF_FRONTIER')
            else:frontiers.add(bit)
            return
        if bit not in drivers:raise ValueError('GATE_RETURN_UNKNOWN_FRONTIER')
        n,p=drivers[bit];c=cells[n]
        if not c['type'].startswith((SC+'buf_',SC+'clkbuf_')):raise ValueError('GATE_RETURN_NONBUFFER')
        selected.add(n);trace(c['connections']['I'][0])
    trace(ports[row['source']]['acknowledgeIn'])
    for i in range(params['closed_count']):trace(ports[row['source']]['closed'+str(i)])
    selected.update(row['source_enable_path']+row['qualifier_path']+row['clock_path'])
    if row['root_port']=='enable':selected.add(target_inverter)
    view={n:deepcopy(cells[n]) for n in sorted(selected)}
    qualifier=view[row['qualifier']];cut=dict(cell=row['qualifier'],pin='D',bit=qualifier['connections']['D'][0])
    qualifier['connections']['D']=['data']
    inactive={b for p,bs in qualifier['connections'].items() if p in ('RN','SETN') for b in bs}
    request=ports[row['source']]['requestIn'];driven={b for c in view.values() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs}
    inputs={b for c in view.values() for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for b in bs if b not in driven}
    expected={root,request,'data'}|resets|frontiers|inactive
    if inputs!=expected or driven&expected or len({root,request,'data'})!=3:raise ValueError('GATE_FIXTURE_FRONTIER')
    loads=defaultdict(list)
    for n,c in cells.items():
        for p,bs in c['connections'].items():
            if c['port_directions'][p]=='input':
                for b in bs:
                    if b in driven and (n not in view or view[n]['connections'][p]!=bs):loads[b].append(dict(cell=n,type=c['type'],pin=p))
    # The clock-only mutation splits the first root-fed pin on the actual arm.
    clock_entry=target_inverter if row['root_port']=='enable' else row['clock_path'][0]
    if view[clock_entry]['connections']['I']!=[root]:raise ValueError('GATE_CLOCK_ARM')
    initial={}
    for bit in frontiers|{root}:
        owner,p=native[bit];b=indexed[owner]
        if b['primitive']!='RiscayDesyncQualifiedController' or p not in ('acknowledgeOut','enable'):
            raise ValueError('GATE_FRONTIER_RESET_MARKING')
        initial[bit]=int(b['parameters']['initial_open']) if p=='enable' else int(not b['parameters']['initial_open'])
    return dict(row=row,cells=view,loads=dict(loads),cut=cut,root=root,root_rise=not clock_falls,initial=initial,
        source_ports=ports[row['source']],frontiers=sorted(frontiers),resets=sorted(resets),inactive=sorted(inactive),
        request=request,clock_entry=clock_entry)


def deck(f,library,headers,pdk,runtime,corner,slew,old,step,late,wave):
    _,process,temp,v=corner;net=lambda b:'data' if b=='data' else 'n'+str(b)
    lines=['Work-gate return, actual feedback; lumped external loads, zero wires',
        f'.include "{runtime.path(pdk/"design.ngspice")}"',f'.lib "{runtime.path(pdk/"sm141064.ngspice")}" {process}',
        f'.include "{runtime.path(pdk/"gf180mcu_fd_sc_mcu7t5v0.spice")}"','.param sw_stat_global=0 sw_stat_mismatch=0',
        f'.temp {temp}','.options method=gear reltol=1e-5 abstol=1e-13 vntol=1e-7',f'Vdd vdd 0 {v}']
    def pwl(name,node,points):lines.append('V'+name+' '+node+' 0 PWL('+' '.join(f'{t}n {val*v}' for t,val in points)+')')
    def activity(last,initial):return [(0,initial),(20,initial),(20+slew/.4,1),(100,1),(100+slew/.4,0),(last,0),(last+slew/.4,1)]
    root=activity(200,f['initial'][f['root']] if f['root_rise'] else 1-f['initial'][f['root']])
    if not f['root_rise']:root=[(t,1-val) for t,val in root]
    pwl('root',net(f['root']),root)
    if late:pwl('late','late_root',[(t+(late if t else 0),val) for t,val in root])
    for b in f['frontiers']:pwl('f'+str(b),net(b),activity(180,f['initial'][b]))
    for b in f['resets']:pwl('r'+str(b),net(b),[(0,1),(10,1),(10.05,0)])
    for b in f['inactive']:lines.append('Va'+str(b)+' '+net(b)+f' 0 {v}')
    pwl('request',net(f['request']),[(0,0),(60,0),(60.05,1),(140,1),(140.05,0)])
    pwl('data','data',[(0,old),(160,old),(160.05,1-old)])
    for i,(n,c) in enumerate(f['cells'].items()):
        conn={p:net(bs[0]) for p,bs in c['connections'].items()}|dict(VDD='vdd',VNW='vdd',VPW='0',VSS='0')
        if late and n==f['clock_entry']:conn['I']='late_root'
        if set(conn)!=set(headers[c['type']]):raise ValueError('GATE_SPICE_PINS')
        lines.append(f'X{i} '+' '.join(conn[p] for p in headers[c['type']])+' '+c['type'])
    pins={k:dict(direct_groups(t,'pin')) for k,t in library.items()}
    for b,loads in f['loads'].items():
        cap=sum(scalar(pins[r['type']][r['pin']],'capacitance') for r in loads)
        if not math.isfinite(cap) or cap<=0:raise ValueError('GATE_LOAD')
        lines.append(f'C{b} {net(b)} 0 {cap}p')
    c=f['cells'][f['row']['gate']];q=f['cells'][f['row']['qualifier']]
    observed=dict(root=f['root'],clock=c['connections'][f['row']['clock_pin']][0],condition=c['connections'][f['row']['qualifier_pin']][0],
        out=c['connections']['Z'][0],q=q['connections']['Q'][0],e=q['connections']['E'][0],
        a=f['source_ports']['acknowledgeOut'],b=f['source_ports']['requestOut'],n=f['source_ports']['enable'])
    signals=sorted(set(observed.values()))
    lines += [f'.tran {step}n 250n 0 {step}n','.control','set numdgt=15','set wr_singlescale','run',
              'wrdata '+runtime.path(wave)+' '+' '.join('v('+net(b)+')' for b in signals),'quit','.endc','.end']
    return '\n'.join(lines)+'\n',observed,signals


def check(rows,observed,signals,voltage,old,step):
    if len(rows)<2 or any(len(r)!=len(signals)+1 or not all(math.isfinite(v) for v in r) for r in rows):raise ValueError('GATE_WAVE_INVALID')
    times=[r[0]*1e9 for r in rows]
    if times[0]>0 or times[-1]<250-1e-6 or any(not 0<y-x<=step*1.00001 for x,y in zip(times,times[1:])):raise ValueError('GATE_WAVE_COVERAGE')
    traces={k:[r[signals.index(b)+1]/voltage for r in rows] for k,b in observed.items()}
    def window(name,start,end):return [v for t,v in zip(times,traces[name]) if start<=t<=end]
    def stable(name,start,end,value):
        vs=window(name,start,end)
        if not vs or any(abs(v-value)>.1 for v in vs):raise ValueError('GATE_STATE:'+name)
    for start,end,a,b,n in ((35,45,0,0,1),(90,95,1,0,0),(130,135,1,1,0),(190,195,1,1,0),(240,250,0,0,1)):
        for name,val in (('a',a),('b',b),('n',n)):stable(name,start,end,val)
    stable('q',130,195,old);stable('q',240,250,1-old)
    stable('clock',130,195,1);stable('out',130,195,old)
    transitions=dict(a=False,b=False,n=True,e=True,clock=False,condition=not old,q=not old)
    cross={}
    for name,rise in transitions.items():
        vals=traces[name] if rise else [1-v for v in traces[name]];cross[name]={}
        for th in (.3,.5,.7):
            up=[];down=[]
            for x,y,a,b in zip(times,times[1:],vals,vals[1:]):
                if y<130:continue
                if a<th<=b:up.append(x+(y-x)*(th-a)/(b-a))
                if a>th>=b:down.append(x+(y-x)*(th-a)/(b-a))
            if len(up)!=1 or down or up[0]<200:raise ValueError('GATE_RETURN_EDGE:'+name)
            cross[name][str(th)]=up[0]
    # No new gate pulse when enabling after closure; one clean falling edge
    # when disabling. AND output need not wait until its input reaches 30%.
    if not old:stable('out',130,250,0)
    else:
        for th in (.3,.5,.7):
            vals=traces['out'];up=[];down=[]
            for x,y,a,b in zip(times,times[1:],vals,vals[1:]):
                if y<130:continue
                if a<th<=b:up.append(y)
                if a>th>=b:down.append(x+(y-x)*(th-a)/(b-a))
            if up or len(down)!=1 or down[0]<200:raise ValueError('GATE_OUTPUT_PULSE')
        stable('out',240,250,0)
    margin=cross['condition']['0.3']-cross['clock']['0.7']
    if margin<.1:raise ValueError('GATE_RETURN_SEPARATION_BELOW_100PS:'+str(margin))
    return dict(input_order_separation_ns=margin,crossings=cross)


def run(mapping,repaired,output,pdk,selected,corner_filter,slew_filter,old_filter,step,late):
    if not all(math.isfinite(x) for x in (step,late)) or not 0<step<=.1 or not 0<=late<=10:raise ValueError('GATE_TIMING_POLICY')
    output.mkdir(parents=True,exist_ok=False);runtime=tool('ngspice');read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    corners=[c for c in CORNERS if not corner_filter or c[0]==corner_filter]
    sources=[pdk/n for n in ('design.ngspice','sm141064.ngspice','gf180mcu_fd_sc_mcu7t5v0.spice')]
    receipt=RunReceipt(output/'receipt.json',inputs=[mapping/'control.json',repaired/'repaired.json',*sources,*[pdk/(SC+c[0]+'.lib') for c in corners]],
        tools=[Path(__file__),*[ROOT/'tools'/n for n in ('primitives.py','characterize_desync_primitives.py','gf180_estimate.py','gf180_physical.py','repair_gf180_design.py','run_receipt.py')],*runtime.input_files()])
    try:
        body=read(repaired/'repaired.json')['modules']['RiscayMcuDigital'];body['cells']={ident(n):c for n,c in body['cells'].items()}
        bindings=read(mapping/'control.json')['bindings'];gates,ports,owners,native,drivers=inventory(body,bindings)
        write_json(output/'inventory.json',gates);wanted=[g for g in gates if not selected or g['target'].removeprefix('desync_control/')==selected]
        if not wanted or not corners:raise ValueError('GATE_CASE_INVENTORY')
        headers=subcircuits(sources[2].read_text(encoding='utf-8'));results=[]
        fixtures={g['target']:prepare(body,bindings,g,ports,owners,native,drivers) for g in wanted}
        for name,f in fixtures.items():write_json(output/(name.split('/')[-1]+'-fixture.json'),f)
        for corner in corners:
            library=dict(groups((pdk/(SC+corner[0]+'.lib')).read_text(encoding='utf-8'),'cell'))
            for name,f in fixtures.items():
                for slew in ([slew_filter] if slew_filter is not None else [.02,2.]):
                    for old in ([old_filter] if old_filter is not None else [0,1]):
                        label=f'{name.split("/")[-1]}-{corner[0]}-s{slew}-old{old}';source=output/(label+'.spice');wave=output/(label+'.dat');log=output/(label+'.log')
                        text,observed,signals=deck(f,library,headers,pdk,runtime,corner,slew,old,step,late,wave);source.write_text(text,encoding='utf-8')
                        if receipt.command(runtime.command(['-b',runtime.path(source)],timeout=180),cwd=ROOT,log=log):raise ValueError('GATE_SPICE_PROCESS')
                        if re.search(r'\b(error|failed|warning)\b',log.read_text(encoding='utf-8'),re.I):raise ValueError('GATE_SPICE_LOG')
                        result=check([list(map(float,l.split())) for l in wave.read_text(encoding='utf-8').splitlines()],observed,signals,corner[3],old,step)
                        results.append(dict(gate=name,corner=corner[0],physical_slew_30_70_ns=slew,old=old,**result))
                        write_json(output/'samples.json',dict(scope='Sampled gate-return ordering only; no opening/setup, OCV, continuous-envelope or routed qualification',max_step_ns=step,late_clock_ns=late,rows=results))
                        print(label,result['input_order_separation_ns'],flush=True)
    except BaseException:
        if not receipt.finished:receipt.finish(outputs=[p for p in output.iterdir() if p.is_file() and p.name!='receipt.json'],status='fail')
        raise
    receipt.finish(outputs=[p for p in output.iterdir() if p.is_file() and p.name!='receipt.json'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('mapping','repaired','output'):p.add_argument(n,type=Path)
    p.add_argument('--pdk',type=Path,default=ROOT/'.tools/physical/pdk');p.add_argument('--gate')
    p.add_argument('--corner',choices=[c[0] for c in CORNERS]);p.add_argument('--slew',type=float,choices=(.02,2.))
    p.add_argument('--old',type=int,choices=(0,1));p.add_argument('--max-step',type=float,default=.1);p.add_argument('--late-clock',type=float,default=0)
    a=p.parse_args();run(a.mapping,a.repaired,a.output,a.pdk,a.gate,a.corner,a.slew,a.old,a.max_step,a.late_clock)

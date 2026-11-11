# SPDX-License-Identifier: Apache-2.0
"""Sample work-gate return and conditional opening with feedback intact.

Opening admits D at a checked Liberty setup aperture; upstream arrival and
retention remain separate obligations. Omitted external sinks are inventoried
pin capacitances. Finite schematic samples are not continuous/OCV/RC bounds.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
from itertools import product
import json
import math
from pathlib import Path
import re
from characterize_desync_primitives import CORNERS, subcircuits
from gf180_estimate import groups, direct_groups, scalar, numbers, table_value
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


def prepare(body,bindings,row,ports,owners,native,drivers,opening=False):
    cells=body['cells'];indexed={b['instance']:b for b in bindings};selected={row['gate'],row['qualifier']}
    controller=row['target'] if opening else row['source']
    frontier_owner=row['source'] if opening else row['target']
    source=indexed[controller];params=source['parameters']
    if source['primitive']!='RiscayDesyncQualifiedController' or params['same_count'] or (params['rise_qualified'] and not opening):
        raise ValueError('GATE_UNSUPPORTED_OWNER')
    root=ports[frontier_owner]['acknowledgeOut'];clock_falls=not opening and row['root_port']=='acknowledgeOut'
    frontiers=set();resets=set();visited=set();active=set()
    def keep(b):
        for leaf in resolve_candidate(b['primitive'],b['parameters'])['cells']:selected.add(b['instance']+'/'+leaf['name'])
        resets.add(ports[b['instance']]['reset'])
    keep(source)
    target_inverter=frontier_owner+'/enable_invert__cell'
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
            if owner==frontier_owner and p=='enable':
                selected.add(target_inverter);trace(cells[target_inverter]['connections']['I'][0]);return
            binding=indexed[owner]
            if binding['primitive']=='RiscayDesyncJoin':
                keep(binding)
                for p in ('input0','input1'):trace(ports[owner][p])
            elif owner==controller:
                raise ValueError('GATE_RETURN_SELF_FRONTIER')
            else:frontiers.add(bit)
            return
        if bit not in drivers:raise ValueError('GATE_RETURN_UNKNOWN_FRONTIER')
        n,p=drivers[bit];c=cells[n]
        if not c['type'].startswith((SC+'buf_',SC+'clkbuf_')):raise ValueError('GATE_RETURN_NONBUFFER')
        selected.add(n);trace(c['connections']['I'][0])
    trace(ports[controller]['acknowledgeIn'])
    for i in range(params['closed_count']):trace(ports[controller]['closed'+str(i)])
    if params['rise_qualified']:trace(ports[controller]['riseAllowed'])
    selected.update(row['source_enable_path']+row['qualifier_path']+row['clock_path'])
    if opening or row['root_port']=='enable':selected.add(target_inverter)
    view={n:deepcopy(cells[n]) for n in sorted(selected)}
    qualifier=view[row['qualifier']];cut=dict(cell=row['qualifier'],pin='D',bit=qualifier['connections']['D'][0])
    qualifier['connections']['D']=['data']
    inactive={b for p,bs in qualifier['connections'].items() if p in ('RN','SETN') for b in bs}
    request=ports[controller]['requestIn'];driven={b for c in view.values() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs}
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
    clock_entry=None if opening else target_inverter if row['root_port']=='enable' else row['clock_path'][0]
    if clock_entry and view[clock_entry]['connections']['I']!=[root]:raise ValueError('GATE_CLOCK_ARM')
    initial={}
    for bit in frontiers|{root}:
        owner,p=native[bit];b=indexed[owner]
        if b['primitive']!='RiscayDesyncQualifiedController' or p not in ('acknowledgeOut','enable'):
            raise ValueError('GATE_FRONTIER_RESET_MARKING')
        initial[bit]=int(b['parameters']['initial_open']) if p=='enable' else int(not b['parameters']['initial_open'])
    return dict(row=row,cells=view,loads=dict(loads),cut=cut,root=root,root_rise=not clock_falls,initial=initial,opening=opening,
        source_ports=ports[controller],frontiers=sorted(frontiers),resets=sorted(resets),inactive=sorted(inactive),
        request=request,clock_entry=clock_entry)


def qualifier_chains(body,gates,native,drivers):
    """Exact upstream direct-latch links; stop at logic, never a bank maximum."""
    cells=body['cells'];result={}
    for row in gates:
        name=row['qualifier'];chain=[];seen=set()
        while True:
            if name in seen:raise ValueError('GATE_QUALIFIER_DATA_LOOP')
            seen.add(name);c=cells[name];enable=c['connections']['E'][0];route=[]
            while enable not in native:
                if enable not in drivers:raise ValueError('GATE_CHAIN_CLOCK_FRONTIER')
                n,p=drivers[enable];clock=cells[n]
                if n in route or not clock['type'].startswith((SC+'buf_',SC+'clkbuf_')):raise ValueError('GATE_CHAIN_CLOCK_ROUTE')
                route.append(n);enable=clock['connections']['I'][0]
            if native[enable][1]!='enable':raise ValueError('GATE_CHAIN_CLOCK_KIND')
            data=c['connections']['D'][0];driver=drivers.get(data)
            chain.append(dict(cell=name,phase=native[enable][0],d_bit=data,q_bit=c['connections']['Q'][0],enable_path=route))
            if not driver or driver[1]!='Q' or not cells[driver[0]]['type'].startswith(SC+'lat'):
                result[row['qualifier']]=dict(links=chain,upstream_frontier=driver,data_pin=name+'/D');break
            name=driver[0]
    return result


def deck(f,library,headers,pdk,runtime,corner,slew,old,step,late,wave,data_at=190,data_slew=.02):
    _,process,temp,v=corner;net=lambda b:'data' if b=='data' else 'n'+str(b)
    lines=['Work-gate timing, actual feedback; lumped external loads, zero wires',
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
    request=[(0,0),(60,0),(60.05,1),(140,1),(140.05,0)]
    if f.get('opening') and f['row']['root_port']=='acknowledgeOut':request += [(190,0),(190.05,1)]
    pwl('request',net(f['request']),request)
    pwl('data','data',[(0,old),(data_at-data_slew/0.8,old),(data_at+data_slew/0.8,1-old)] if f.get('opening') else [(0,old),(160,old),(160.05,1-old)])
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
    if f.get('opening'):observed.update(data='data',request=f['request'],ack=f['source_ports']['acknowledgeIn'])
    signals=sorted(set(observed.values()),key=str)
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


def setup_table(text,kind,rise):
    """Liberty's D/E axes, with physical slew converted to table slew.

    OpenSTA include/sta/Graph.hh: reported = measured / slew_derate_from_library.
    https://github.com/The-OpenROAD-Project/OpenSTA/blob/master/include/sta/Graph.hh
    """
    pin=dict(direct_groups(dict(groups(text,'cell'))[kind],'pin'))['D']
    checks=[t for _,t in direct_groups(pin,'timing') if re.search(r'timing_type\s*:\s*setup_falling\s*;',t)]
    if len(checks)!=1 or not re.search(r'related_pin\s*:\s*"E"',checks[0]):raise ValueError('GATE_SETUP_ARC')
    when=re.search(r'when\s*:\s*"([^"]+)"',checks[0])
    if when and when[1] not in ('RN','SETN'):raise ValueError('GATE_SETUP_CONDITION')
    tables=list(groups(checks[0],'rise_constraint' if rise else 'fall_constraint'))
    if len(tables)!=1:raise ValueError('GATE_SETUP_TABLE')
    name,body=tables[0];template=dict(groups(text,'lu_table_template'))[name]
    if not all(re.search(r'variable_'+str(i)+r'\s*:\s*'+v+r'\s*;',template) for i,v in
               ((1,'constrained_pin_transition'),(2,'related_pin_transition'))):raise ValueError('GATE_SETUP_AXES')
    derate=scalar(text,'slew_derate_from_library')
    if not math.isfinite(derate) or derate<=0:raise ValueError('GATE_SLEW_DERATE')
    return body,derate


def setup_value(table,d_slew,e_slew):
    body,derate=table;values=(d_slew/derate,e_slew/derate)
    for i,value in enumerate(values,1):
        axis=numbers(body,'index_'+str(i))
        if not math.isfinite(value) or not axis[0]<=value<=axis[-1]:raise ValueError('GATE_SETUP_OUTSIDE_TABLE')
    result=table_value(body,*values)
    if not math.isfinite(result):raise ValueError('GATE_SETUP_NONFINITE')
    return result


def opening_check(rows,observed,signals,voltage,old,step,cpu,table):
    if len(rows)<2 or any(len(r)!=len(signals)+1 or not all(math.isfinite(v) for v in r) for r in rows):raise ValueError('GATE_WAVE_INVALID')
    times=[r[0]*1e9 for r in rows]
    if times[0]>0 or times[-1]<250-1e-6 or any(not 0<y-x<=step*1.00001 for x,y in zip(times,times[1:])):raise ValueError('GATE_WAVE_COVERAGE')
    traces={k:[r[signals.index(b)+1]/voltage for r in rows] for k,b in observed.items()}
    def stable(name,start,end,value):
        vs=[v for t,v in zip(times,traces[name]) if start<=t<=end]
        if not vs or any(abs(v-value)>.1 for v in vs):raise ValueError('GATE_OPEN_STATE:'+name)
    def crossing(name,rise,start,end=250):
        vals=traces[name] if rise else [1-v for v in traces[name]];result={}
        for th in (.3,.5,.7):
            ups=[];downs=[]
            for x,y,a,b in zip(times,times[1:],vals,vals[1:]):
                if y<start or x>end:continue
                if a<th<=b:ups.append(x+(y-x)*(th-a)/(b-a))
                if a>th>=b:downs.append(x+(y-x)*(th-a)/(b-a))
            if len(ups)!=1 or downs:raise ValueError('GATE_OPEN_EDGE:'+name)
            result[str(th)]=ups[0]
        return result
    for name,value in (('a',int(not cpu)),('b',int(not cpu)),('n',int(cpu)),('clock',0),('e',1)):
        stable(name,190.1,195,value)
    for name,value in (('a',int(cpu)),('b',0),('n',int(not cpu)),('clock',1),('e',0),('q',1-old),('condition',1-old),('data',1-old),('out',1-old)):
        stable(name,240,250,value)
    stable('q',130,170,old);stable('data',130,170,old)
    stable('out',130,170,old if cpu else 0);stable('out',190.1,195,0)
    stable('request',195,250,int(cpu))
    if cpu:stable('ack',195,250,1);stable('b',190.1,250,0)
    directions=dict(root=True,a=cpu,n=not cpu,e=False,clock=True,data=not old,q=not old,condition=not old)
    if not cpu:directions['b']=False
    edges={n:crossing(n,r,170 if n in ('q','condition','data') else 190) for n,r in directions.items()}
    if cpu:
        edges['previous_clock']=crossing('clock',False,130,195)
        if edges['condition']['0.3']-edges['previous_clock']['0.7']<.1:raise ValueError('GATE_OPEN_PRELUDE_REUSE')
        if old:edges['previous_out']=crossing('out',False,130,195)
        else:stable('out',130,195,0)
    else:stable('out',130,195,0)
    for n in ('root','a','n','e','clock',*(() if cpu else ('b',))):
        if edges[n]['0.3']<200:raise ValueError('GATE_OPEN_EARLY:'+n)
    if old:stable('out',190,250,0)
    else:
        out=crossing('out',True,190)
        if out['0.3']<200:raise ValueError('GATE_OPEN_OUTPUT_EARLY')
        edges['out']=out
    aperture=setup_value(table,edges['data']['0.7']-edges['data']['0.3'],edges['e']['0.7']-edges['e']['0.3'])
    return dict(crossings=edges,setup_ns=aperture,
        setup_headroom_ns=edges['e']['0.5']-edges['data']['0.5']-aperture,
        qualifier_before_clock_ns=edges['clock']['0.3']-edges['condition']['0.7'],
        closed_before_clock_ns=edges['clock']['0.3']-edges['e']['0.7'],
        tested_d_lead_before_root_ns=edges['root']['0.5']-edges['data']['0.5'])


def opening_verdict(result):
    if result['setup_headroom_ns']<.1:raise ValueError('GATE_OPEN_INVALID_APERTURE_PREMISE')
    if result['qualifier_before_clock_ns']<.1:raise ValueError('GATE_QUALIFIER_ORDER_BELOW_100PS')


def run(mapping,repaired,output,pdk,selected,corner_filter,slew_filter,old_filter,step,late,opening=False,late_data=0,data_slew_filter=None):
    if not all(math.isfinite(x) for x in (step,late,late_data)) or not 0<step<=.1 or not 0<=late<=10 or not 0<=late_data<=10 or (opening and late) or (not opening and late_data):raise ValueError('GATE_TIMING_POLICY')
    if data_slew_filter is not None and (not opening or data_slew_filter not in (.02,2.)):raise ValueError('GATE_DATA_SLEW_POLICY')
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
        if opening:write_json(output/'qualifier-chains.json',qualifier_chains(body,gates,native,drivers))
        headers=subcircuits(sources[2].read_text(encoding='utf-8'));results=[]
        fixtures={g['target']:prepare(body,bindings,g,ports,owners,native,drivers,opening) for g in wanted}
        for name,f in fixtures.items():write_json(output/(name.split('/')[-1]+'-fixture.json'),f)
        for corner in corners:
            libtext=(pdk/(SC+corner[0]+'.lib')).read_text(encoding='utf-8');library=dict(groups(libtext,'cell'));tables={}
            for name,f in fixtures.items():
                for slew in ([slew_filter] if slew_filter is not None else [.02,2.]):
                    for old,data_slew in product([old_filter] if old_filter is not None else [0,1],
                            ([data_slew_filter] if data_slew_filter is not None else [.02,2.]) if opening else [.02]):
                        label=f'{name.split("/")[-1]}-{corner[0]}-s{slew}-old{old}'+(f'-d{data_slew}' if opening else '')
                        def simulate(suffix='',data_at=190):
                            source=output/(label+suffix+'.spice');wave=output/(label+suffix+'.dat');log=output/(label+suffix+'.log')
                            text,observed,signals=deck(f,library,headers,pdk,runtime,corner,slew,old,step,late,wave,data_at,data_slew);source.write_text(text,encoding='utf-8')
                            if receipt.command(runtime.command(['-b',runtime.path(source)],timeout=180),cwd=ROOT,log=log):raise ValueError('GATE_SPICE_PROCESS')
                            if re.search(r'\b(error|failed|warning)\b',log.read_text(encoding='utf-8'),re.I):raise ValueError('GATE_SPICE_LOG')
                            args=([list(map(float,l.split())) for l in wave.read_text(encoding='utf-8').splitlines()],observed,signals,corner[3],old,step)
                            return opening_check(*args,f['row']['root_port']=='acknowledgeOut',table) if opening else check(*args)
                        if opening:
                            key=(f['cells'][f['row']['qualifier']]['type'],not old)
                            if key not in tables:tables[key]=setup_table(libtext,*key)
                            table=tables[key];pilot=simulate('-early');edge=pilot['crossings']['e']
                            # Simulation stimulus only: target 200 ps of Liberty
                            # setup headroom, then verify >=100 ps on the final
                            # actual data-dependent D/E waveforms. No guard sized.
                            data_at=edge['0.5']-setup_value(table,data_slew,edge['0.7']-edge['0.3'])-.2+late_data
                            if not 175<data_at-data_slew/.8<data_at+data_slew/.8<230:raise ValueError('GATE_OPEN_STIMULUS_WINDOW')
                            result=simulate(data_at=data_at)
                        else:result=simulate()
                        results.append(dict(gate=name,corner=corner[0],physical_slew_30_70_ns=slew,old=old,
                                            **(dict(data_slew_30_70_ns=data_slew) if opening else {}),**result))
                        write_json(output/'samples.json',dict(scope=('Conditional opening/aperture samples; upstream data arrival/retention, pulses, reset, OCV and routed qualification remain open' if opening else 'Sampled gate-return ordering only; no opening/setup, OCV, continuous-envelope or routed qualification'),max_step_ns=step,late_clock_ns=late,late_data_ns=late_data,rows=results))
                        if opening:opening_verdict(result)
                        print(label,result['qualifier_before_clock_ns' if opening else 'input_order_separation_ns'],flush=True)
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
    p.add_argument('--opening',action='store_true');p.add_argument('--late-data',type=float,default=0)
    p.add_argument('--data-slew',type=float,choices=(.02,2.))
    a=p.parse_args();run(a.mapping,a.repaired,a.output,a.pdk,a.gate,a.corner,a.slew,a.old,a.max_step,a.late_clock,a.opening,a.late_data,a.data_slew)

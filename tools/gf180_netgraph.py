# SPDX-License-Identifier: Apache-2.0
"""Exact mapped connectivity for cost accounting; no timing qualification."""
from gf180_physical import SC, SRAM


def graph(modules):
    parent={}; aliases={}; cells={}
    def find(n):
        p=parent.setdefault(n,n)
        if p!=n: parent[n]=find(p)
        return parent[n]
    def union(a,b):
        a,b=find(a),find(b)
        if a==b:return
        if a[0]==b[0]=='constant': raise ValueError('CONFLICTING_CONSTANTS')
        if a[0]=='constant':parent[b]=a
        else:parent[a]=b
    def walk(kind,path,ports):
        mod=modules[kind]
        def net(b):return ('constant',b) if isinstance(b,str) else (path,b)
        for name,p in mod['ports'].items():
            if ports.get(name):
                if len(ports[name])!=len(p['bits']):raise ValueError('PORT_WIDTH_CHANGED')
                for a,b in zip(p['bits'],ports[name]):union(net(a),b)
        for name,n in mod.get('netnames',{}).items():aliases[path+name]=[net(b) for b in n['bits']]
        for name,c in mod.get('cells',{}).items():
            p={k:[net(b) for b in bs] for k,bs in c['connections'].items()}
            instance=path+name
            if c['type'].startswith(SC) or c['type']==SRAM:cells[instance]=dict(c,connections=p)
            else:walk(c['type'],instance+'/',p)
    walk('RiscayMcuDigital','',{})
    for c in cells.values():c['connections']={p:[find(b) for b in bs] for p,bs in c['connections'].items()}
    return cells,{n:[find(b) for b in bs] for n,bs in aliases.items()}


def periodic_loads(modules,library):
    """Count mapped input capacitance, not CTS energy or switching power."""
    import re
    from gf180_estimate import groups,scalar
    cells,aliases=graph(modules)
    clocks={aliases[n][0]:d for n,d in [('serviceClock','service'),('watchdogClock','lf'),
        ('sda','host'),('soc/gate_io_clockOut','work')]}
    if len(clocks)!=4:raise ValueError('CLOCK_ROOT_ALIAS_COLLISION')
    changed=True
    while changed:
        changed=False
        for c in cells.values():
            kind=c['type'].removeprefix(SC)
            if not kind.startswith(('inv_','clkinv_','buf_','clkbuf_')):continue
            p=c['connections']; source=p['I'][0]; dest=p.get('Z',p.get('ZN'))[0]
            if source in clocks and dest not in clocks:clocks[dest]=clocks[source]; changed=True
    result={d:dict(storage_cells=0,clock_input_pf=0.0) for d in ('service','work','lf','host','native_or_other')}
    clock_pins={}
    for c in cells.values():
        kind=c['type']; p=c['connections']
        if kind not in clock_pins:
            clock_pins[kind]={name:scalar(body,'capacitance') for name,body in groups(library[kind],'pin')
                              if re.search(r'\bclock\s*:\s*true\s*;',body)}
        if len(clock_pins[kind])>1:raise ValueError('MULTIPLE_STORAGE_CLOCK_PINS_'+kind)
        for clock,capacitance in clock_pins[kind].items():
            d=clocks.get(p[clock][0],'native_or_other'); result[d]['storage_cells']+=1
            result[d]['clock_input_pf']+=capacitance
    return result

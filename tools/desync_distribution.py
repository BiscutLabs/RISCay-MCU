# SPDX-License-Identifier: Apache-2.0
"""Real parent drivers and balanced enable trees, without touching keeper loops.

Only ordinary buffers are inserted. The graph proof must still pass; these
buffers count as distribution area and are not matched-delay recipes.
"""
from collections import defaultdict
from copy import deepcopy
import math
import re
from gf180_estimate import direct_groups
from gf180_physical import SC, SRAM
from primitives import resolve_candidate


def prepare(netlist, bindings, library, *, branch_loads=16, repair_drivers=()):
    if type(branch_loads) is not int or branch_loads < 2:
        raise ValueError('DESYNC_DISTRIBUTION_BRANCH_LOADS')
    result = deepcopy(netlist); body = result['modules']['RiscayMcuDigital']
    cells, names = body['cells'], body['netnames']
    # In-memory generator JSON may share Python lists; a physical pin rewrite
    # must not mutate another pin's list through that implementation alias.
    for c in cells.values(): c['connections']={p:list(bs) for p,bs in c['connections'].items()}
    fresh = max(b for c in cells.values() for bs in c['connections'].values()
                for b in bs if isinstance(b, int)) + 1
    outputs = []; resets = []; trees = []; buffer_index = 0
    def buffer(source, kind):
        nonlocal fresh, buffer_index
        target = fresh; fresh += 1
        name = 'desync_distribution_' + str(buffer_index); buffer_index += 1
        cells[name] = dict(type=SC+kind, parameters={}, attributes={},
            port_directions=dict(I='input', Z='output'), connections=dict(I=[source], Z=[target]))
        names[name+'_out'] = dict(hide_name=0, attributes={}, bits=[target])
        return target, name
    # Snapshot consumers before adding drivers, so an output shared with its
    # own keeper is isolated only on external branches. Input aliases of other
    # primitives follow their actual input pins; local feedback aliases do not.
    original = tuple(sorted(cells))
    measured_repairs=[]
    for driver,pin in repair_drivers:
        if driver not in cells or cells[driver]['port_directions'].get(pin)!='output':
            raise ValueError('DESYNC_ELECTRICAL_REPAIR_DRIVER')
        if any(driver.startswith(b['instance']+'/') for b in bindings):
            raise ValueError('DESYNC_ELECTRICAL_REPAIR_KEEPER')
        raw=cells[driver]['connections'][pin][0]
        loads=[(n,p,i) for n in original for p,bs in cells[n]['connections'].items()
               if cells[n]['port_directions'][p]=='input' for i,b in enumerate(bs) if b==raw]
        ports=[p for p in body['ports'].values() if p['direction']=='output' and raw in p['bits']]
        if not loads and not ports:raise ValueError('DESYNC_ELECTRICAL_REPAIR_UNUSED')
        root,root_name=buffer(raw,'buf_2');branches=[]
        for p in ports:p['bits']=[root if bit==raw else bit for bit in p['bits']]
        native=defaultdict(list);ordinary=[]
        for load in loads:
            owners=[b['instance'] for b in bindings if load[0].startswith(b['instance']+'/')]
            if owners:native[owners[0]].append(load)
            else:ordinary.append(load)
        groups=[(None,ordinary[i:i+branch_loads]) for i in range(0,len(ordinary),branch_loads)]+sorted(native.items())
        def repair_branch(source,groups):
            if not groups:return
            target,name=buffer(source,'buf_8');branches.append(name)
            if len(groups)>branch_loads:
                size=branch_loads**max(1,math.ceil(math.log(len(groups),branch_loads))-1)
                for start in range(0,len(groups),size):repair_branch(target,groups[start:start+size])
                return
            source=target
            for owner,group in groups:
                target,name=buffer(source,'buf_8');branches.append(name)
                for n,p,i in group:cells[n]['connections'][p][i]=target
                # Never split a protected primitive's local input partition.
                if owner:
                    for alias,value in names.items():
                        if alias.startswith(owner+'/'):value['bits']=[target if b==raw else b for b in value['bits']]
        repair_branch(root,groups)
        measured_repairs.append(dict(driver=driver+'/'+pin,root=root_name,branches=branches,loads=len(loads)))
    for binding in bindings:
        prefix = binding['instance']+'/'
        recipe = resolve_candidate(binding['primitive'], binding.get('parameters'))
        for port, direction in recipe['ports'].items():
            if direction != 'output': continue
            raw = names[prefix+port]['bits']
            if len(raw) != 1 or not isinstance(raw[0], int):
                raise ValueError('DESYNC_DISTRIBUTION_OUTPUT')
            bit = raw[0]
            loads = [(n,p,i) for n in original if not n.startswith(prefix)
                     for p,bs in cells[n]['connections'].items()
                     if cells[n]['port_directions'][p]=='input'
                     for i,b in enumerate(bs) if b==bit]
            ports = [p for p in body['ports'].values() if p['direction']=='output' and bit in p['bits']]
            if not loads and not ports: continue
            target, driver = buffer(bit, 'buf_2')
            for n,p,i in loads: cells[n]['connections'][p][i] = target
            for p in ports: p['bits'] = [target if b==bit else b for b in p['bits']]
            for alias,value in names.items():
                if not alias.startswith(prefix): value['bits'] = [target if b==bit else b for b in value['bits']]
            outputs.append(dict(owner=binding['instance'],port=port,driver=driver,loads=len(loads)))
    # OpenROAD cannot reconnect a protected cell's reset pin while splitting
    # the POR fanout. Give each primitive one ordinary input-side reset driver;
    # its input is repairable and its output keeps that primitive's partition.
    for binding in bindings:
        prefix=binding['instance']+'/'
        bit=names[prefix+'reset']['bits'][0]
        loads=[(n,p,i) for n in original if n.startswith(prefix)
               for p,bs in cells[n]['connections'].items() if cells[n]['port_directions'][p]=='input'
               for i,b in enumerate(bs) if b==bit]
        if not loads: continue
        target,driver=buffer(bit,'buf_2')
        for n,p,i in loads:cells[n]['connections'][p][i]=target
        for alias,value in names.items():
            if alias.startswith(prefix):value['bits']=[target if b==bit else b for b in value['bits']]
        resets.append(dict(owner=binding['instance'],driver=driver,loads=len(loads)))
    clock_pins = {kind:[pin for pin,p in direct_groups(lib,'pin') if re.search(r'\bclock\s*:\s*true\s*;',p)]
                  for kind,lib in library.items()}
    groups = defaultdict(list)
    # Native roots may already pass through the clocked design's work-enable
    # AND. Build after that gate; moving it would change falling-edge semantics.
    lf_bits = {b for n in ('watchdogClock','sda') for b in body['ports'][n]['bits']}
    for n,c in list(cells.items()):
        if c['type'] not in clock_pins: raise ValueError('DESYNC_DISTRIBUTION_UNKNOWN_CELL:'+c['type'])
        for p in clock_pins[c['type']]:
            bit = c['connections'][p][0]
            if bit not in lf_bits: groups[bit].append((n,p,0))
    for root,loads in sorted(groups.items(), key=lambda x:str(x[0])):
        if not isinstance(root,int): raise ValueError('DESYNC_DISTRIBUTION_CONSTANT_ENABLE')
        depth = max(1, math.ceil(math.log(len(loads), branch_loads)))
        branches = []
        def distribute(source, sinks, levels):
            target, name = buffer(source,'clkbuf_8')
            branches.append(name)
            if levels == 1:
                if len(sinks)>branch_loads: raise ValueError('DESYNC_DISTRIBUTION_FANOUT')
                for n,p,i in sinks: cells[n]['connections'][p][i] = target
            else:
                size = branch_loads**(levels-1)
                for i in range(0,len(sinks),size): distribute(target,sinks[i:i+size],levels-1)
        distribute(root,loads,depth)
        trees.append(dict(root=root,depth=depth,sinks=[n+'/'+p for n,p,_ in loads],buffers=branches))
    # Each SRAM gets its own last driver even when sharing a bank enable root.
    macros = []
    for n,c in list(cells.items()):
        if c['type'] != SRAM: continue
        pins = clock_pins[SRAM]
        if len(pins)!=1: raise ValueError('DESYNC_DISTRIBUTION_SRAM_CLOCK')
        p=pins[0];target,name=buffer(c['connections'][p][0],'clkbuf_8')
        c['connections'][p]=[target];macros.append(dict(macro=n,pin=p,driver=name))
    for name,port in body['ports'].items():
        if name in names:names[name]['bits']=list(port['bits'])
    return result, dict(measured_repairs=measured_repairs,parent_drivers=outputs,reset_drivers=resets,enable_trees=trees,sram_drivers=macros,
        buffer_count=buffer_index,branch_loads=branch_loads,
        scope='Explicit distribution only; post-repair fanout, electrical and timing checks required')


def failed_drivers(netlist, failures, bindings):
    """Resolve failed nets through repair buffers to ordinary source cells."""
    from repair_gf180_design import ident
    cells={ident(n):c for n,c in netlist['modules']['RiscayMcuDigital']['cells'].items()}
    outputs={bit:(n,p) for n,c in cells.items() for p,bs in c['connections'].items()
             if c['port_directions'][p]=='output' for bit in bs}
    protected=[b['instance']+'/' for b in bindings]
    result=set()
    for row in (r for rows in failures.values() for r in rows):
        if row['kind']!='max slew':continue
        if '/' not in row['pin']:continue
        n,p=row['pin'].rsplit('/',1);bit=cells[ident(n)]['connections'][p][0];seen=set()
        while bit in outputs:
            n,p=outputs[bit]
            if n in seen:raise ValueError('DESYNC_ELECTRICAL_REPAIR_CYCLE')
            seen.add(n);c=cells[n]
            if re.fullmatch(re.escape(SC)+r'(?:clkbuf|buf)_\d+',c['type']):bit=c['connections']['I'][0];continue
            if not any(n.startswith(owner) for owner in protected):result.add((n,p))
            break
    return sorted(result)


def validate_trees(prepared, repaired, report):
    """Re-enumerate actual paths after repair; graph contraction is not enough."""
    from repair_gf180_design import ident
    before=prepared['modules']['RiscayMcuDigital'];after=repaired['modules']['RiscayMcuDigital']
    before=dict(before,cells={ident(n):c for n,c in before['cells'].items()})
    after=dict(after,cells={ident(n):c for n,c in after['cells'].items()})
    def outputs(body):
        drivers={}
        for n,c in body['cells'].items():
            for p,bs in c['connections'].items():
                if c['port_directions'][p]=='output':
                    for bit in bs:
                        if bit in drivers:raise ValueError('DESYNC_TREE_MULTIPLE_DRIVERS')
                        drivers[bit]=(n,p)
        return drivers
    old_drivers=outputs(before);drivers=outputs(after)
    external={bit:name for name in ('watchdogClock','sda') for bit in after['ports'].get(name,{}).get('bits',[])}
    def external_root(bit):
        visited=set()
        while bit not in external:
            if bit in visited:raise ValueError('DESYNC_TREE_CYCLE')
            visited.add(bit)
            if bit not in drivers:return None
            name,pin=drivers[bit];cell=after['cells'][name]
            if not re.fullmatch(re.escape(SC)+r'(?:clkbuf|buf|clkinv|inv)_\d+',cell['type']):return None
            bit=cell['connections']['I'][0]
        return external[bit]
    expected=set();excluded={};actual_macros=set()
    for name,cell in after['cells'].items():
        if cell['type']==SRAM or cell['type'].startswith((SC+'lat',SC+'dff')):
            pins=[p for p in ('E','CLK','CLKN') if p in cell['connections']]
            if len(pins)!=1:raise ValueError('DESYNC_TREE_STORAGE_CLOCK')
            pin=pins[0];sink=name+'/'+pin;domain=external_root(cell['connections'][pin][0])
            if cell['type']==SRAM:actual_macros.add(sink)
            if domain:excluded[sink]=domain
            else:expected.add(sink)
    loads=defaultdict(list)
    for n,c in after['cells'].items():
        for p,bs in c['connections'].items():
            if c['port_directions'][p]=='input':
                for bit in bs:loads[bit].append(n+'/'+p)
    macro_sinks={r['macro']+'/'+r['pin'] for r in report['sram_drivers']}
    if macro_sinks!=actual_macros:raise ValueError('DESYNC_TREE_MACRO_COVERAGE')
    seen=set();measured=[]
    for tree in report['enable_trees']:
        root_cell,root_pin=old_drivers[tree['root']]
        root=after['cells'][root_cell]['connections'][root_pin][0]
        paths=[]
        for sink in tree['sinks']:
            if sink in seen:raise ValueError('DESYNC_TREE_DUPLICATE_SINK')
            seen.add(sink);name,pin=sink.rsplit('/',1)
            bit=after['cells'][name]['connections'][pin][0];path=[]
            while bit!=root:
                if bit not in drivers:raise ValueError('DESYNC_TREE_UNDRIVEN')
                n,p=drivers[bit];c=after['cells'][n]
                if n in path:raise ValueError('DESYNC_TREE_CYCLE')
                if not re.fullmatch(re.escape(SC)+r'(?:clkbuf|buf)_\d+',c['type']):
                    raise ValueError('DESYNC_TREE_NONBUFFER')
                if len(loads[bit])>report['branch_loads']:raise ValueError('DESYNC_TREE_FANOUT')
                path.append(n);bit=c['connections']['I'][0]
            if len(path)!=tree['depth']+int(sink in macro_sinks):raise ValueError('DESYNC_TREE_DEPTH')
            paths.append(dict(sink=sink,leaf_to_root=path))
        measured.append(dict(root=root_cell+'/'+root_pin,paths=paths))
    if not macro_sinks<=seen:raise ValueError('DESYNC_TREE_MACRO_MISSING')
    if seen!=expected:raise ValueError('DESYNC_TREE_SINK_COVERAGE')
    return dict(status='pass',sinks=len(seen),trees=measured,branch_loads=report['branch_loads'],
                excluded_external_sinks=excluded,
                scope='Connectivity/depth only; load-dependent skew and routed geometry remain timing obligations')

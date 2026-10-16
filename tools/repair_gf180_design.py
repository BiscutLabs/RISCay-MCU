# SPDX-License-Identifier: Apache-2.0
"""Global electrical repair with preserved native cells and whole-graph proof.

The accepted graph is the real repaired graph, never its proof contraction.
Buffer contraction and Liberty function comparison prove only connectivity and
logic preservation. Electrical, relative timing, reset and routed checks remain
independent acceptance gates.
"""
from collections import defaultdict
from functools import lru_cache
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from gf180_physical import ROOT, SC, SRAM, sha, write_json, pdk_verify
from gf180_estimate import library, direct_groups
from physical_tools import tool
from repair_gf180_control import require
from characterize_gf180_liberty import CORNERS

EVIDENCE=('proof.json','repair.tcl','repair.log','candidate/netlist-audit.json',
          'reference/readback.json','tied.v','tied.json','prepared.v','prepared.json','preparation.json',
          'repaired-raw.v','serializer-corrected.v','serializer-readback.json','serializer-corrections.json',
          'pruned.json','orphan-ties.json','before-electrical.rpt','after-electrical.rpt')


def ident(name):
    return name[1:] if name.startswith('\\$') else name


def flat(netlist, top):
    cells={}; ports={}; boundaries={}; directions={}; used_ports={}; parents={}; module_usage={}
    def root(n):
        parents.setdefault(n,n)
        if parents[n]!=n:parents[n]=root(parents[n])
        return parents[n]
    def union(a,b):
        a,b=root(a),root(b)
        if a==b:return
        require(not (a[0]==b[0]=='constant'),'REPAIR_CONSTANT_SHORT')
        if a[0]=='constant':parents[b]=a
        else:parents[a]=b
    def walk(kind,path,connection,stack=()):
        require(kind not in stack and len(stack)<64,'REPAIR_HIERARCHY_CYCLE')
        body=netlist['modules'][kind]
        if kind not in module_usage:
            module_usage[kind]={bit for c in body.get('cells',{}).values() for bs in c['connections'].values() for bit in bs}
        def net(b):return ('constant',b) if isinstance(b,str) else (path,b)
        for pin,p in body['ports'].items():
            ns=[net(b) for b in p['bits']]
            if path:
                actual=connection.get(pin,[])
                require(len(actual)==len(ns) or (not actual and p['direction']=='output'),
                    'REPAIR_PORT_WIDTH_'+path+pin)
                for a,b in zip(ns,actual):union(a,b)
            else:ports[pin]=dict(direction=p['direction'],bits=ns)
            boundaries[path+pin]=ns
            directions[path+pin]=p['direction']
            used_ports[path+pin]=any(bit in module_usage[kind] for bit in p['bits'])
        for name,c in body.get('cells',{}).items():
            name=path+ident(name);child=c['type'];conn={p:[net(b) for b in bs] for p,bs in c['connections'].items()}
            if child.startswith(SC) or child==SRAM:
                require(name not in cells,'REPAIR_DUPLICATE_CELL')
                cells[name]=dict(type=child,connections=conn,directions=c['port_directions'])
            else:walk(child,name+'/',conn,stack+(kind,))
    walk(top,'',{})
    for c in cells.values():c['connections']={p:[root(b) for b in bs] for p,bs in c['connections'].items()}
    for p in ports.values():p['bits']=[root(b) for b in p['bits']]
    return dict(cells=cells,ports=ports,boundaries={p:[root(b) for b in bs] for p,bs in boundaries.items()},
                boundary_directions=directions,boundary_pin_use=used_ports)


def logic_signature(lib,kind):
    require(kind in lib,'REPAIR_UNKNOWN_LIBERTY_CELL')
    return body_signature(lib[kind])


@lru_cache(maxsize=1024)
def body_signature(body):
    require(not any(any(direct_groups(body,k)) for k in ('ff','ff_bank','latch','latch_bank')),'REPAIR_SEQUENTIAL_RESIZE')
    pins={}
    for name,p in direct_groups(body,'pin'):
        direction=re.search(r'\bdirection\s*:\s*(\w+)\s*;',p)
        require(direction is not None,'REPAIR_LIBERTY_DIRECTION')
        values=[]
        for field in ('function','three_state'):
            found=re.findall(r'\b'+field+r'\s*:\s*"([^"]*)"',p)
            require(len(found)<=1,'REPAIR_LIBERTY_FUNCTION')
            values.append(re.sub(r'\s+','',found[0]) if found else None)
        require(direction[1]!='output' or values[0] is not None,'REPAIR_LIBERTY_FUNCTION')
        pins[name]=(direction[1],*values)
    require(pins,'REPAIR_LIBERTY_PINS')
    return pins


def graph_proof(before,after,top,protected,libs):
    """Original cells/pins/ports/constants must survive exactly after contraction."""
    a,b=flat(before,top),flat(after,top)
    require(a['cells'].keys()<=b['cells'].keys(),'REPAIR_ORIGINAL_CELL_REMOVED')
    require(a['ports'].keys()==b['ports'].keys(),'REPAIR_TOP_PORT_SET')
    for pin,p in a['ports'].items():
        require((p['direction'],len(p['bits']))==(b['ports'][pin]['direction'],len(b['ports'][pin]['bits'])),'REPAIR_TOP_PORT_SHAPE')
    added=set(b['cells'])-set(a['cells']);aliases={};resized=[]
    ties={}
    for name in added:
        c=b['cells'][name]
        if c['type'] in (SC+'tieh',SC+'tiel'):
            pin,value=('Z','1') if c['type']==SC+'tieh' else ('ZN','0')
            require(all(logic_signature(lib,c['type'])=={pin:('output',value,None)} for lib in libs),'REPAIR_TIE_FUNCTION')
            require(c['directions']=={pin:'output'} and list(c['connections'])==[pin] and
                len(c['connections'][pin])==1,'REPAIR_TIE_PINS')
            n=c['connections'][pin][0]
            require(n not in aliases and n[0]!='constant','REPAIR_TIE_DRIVER')
            aliases[n]=('constant',value);ties[name]=n
    constants=dict(aliases)
    require(set(protected)<=set(a['cells']), 'REPAIR_PROTECTED_INVENTORY')
    # Adapter ports and every native pin retain their exact local connectivity,
    # including output/feedback nets exposed on the boundary. Contraction alone
    # must not authorize buffering an internal keeper branch.
    owner_pins=defaultdict(list)
    for name,owner in protected.items():owner_pins[owner].append(name)
    def boundary_names(g):
        result=defaultdict(list)
        for p in g['boundaries']:
            if '/' in p:result[p.rsplit('/',1)[0]].append(p)
        return result
    a_ports,b_ports=boundary_names(a),boundary_names(b);omitted=[]
    for owner in owner_pins:
        require(not any(n.startswith(owner+'/') for n in added),'REPAIR_NATIVE_INTERNAL_BUFFER')
        # OpenROAD omits wholly unused specialized inputs (for example the
        # falling side of a C-element with no falling operands). Never exempt a
        # real pin, output, dynamic input, or a changed port that still exists.
        for p in set(a_ports[owner])-set(b_ports[owner]):
            bits=a['boundaries'][p]
            require(a['boundary_directions'][p]=='input' and not a['boundary_pin_use'][p] and
                all(bit[0]=='constant' and bit[1] in ('0','1') for bit in bits),'REPAIR_NATIVE_PORT_REMOVED_'+p)
            omitted.append(dict(port=p,direction='input',width=len(bits),constants=[bit[1] for bit in bits]))
            a_ports[owner].remove(p)
        def native_partition(g,ports):
            groups=defaultdict(list)
            for n in owner_pins[owner]:
                for p,bs in g['cells'][n]['connections'].items():
                    for i,bit in enumerate(bs):groups[constants.get(bit,bit) if g is b else bit].append(('pin',n,p,i))
            for p in ports[owner]:
                for i,bit in enumerate(g['boundaries'][p]):groups[constants.get(bit,bit) if g is b else bit].append(('port',p,'',i))
            return {tuple(sorted(tags)):(n[1] if n[0]=='constant' else 'wire') for n,tags in groups.items()}
        require(native_partition(a,a_ports)==native_partition(b,b_ports),'REPAIR_NATIVE_CONNECTIVITY_'+owner)
    for name in sorted(added-set(ties)):
        c=b['cells'][name]
        require(all(logic_signature(lib,c['type'])=={'I':('input',None,None),'Z':('output','I',None)} for lib in libs),
                'REPAIR_NONBUFFER_ADDITION')
        require(c['directions']=={'I':'input','Z':'output'} and all(len(v)==1 for v in c['connections'].values()),'REPAIR_BUFFER_PORTS')
        src,dst=[c['connections'][p][0] for p in ('I','Z')]
        require(dst not in aliases and dst[0]!='constant','REPAIR_BUFFER_DRIVER')
        aliases[dst]=src
    def contract(n):
        seen=set()
        while n in aliases:
            require(n not in seen,'REPAIR_BUFFER_CYCLE');seen.add(n);n=aliases[n]
        return n
    for n in aliases:contract(n)
    # Audit physical drivers before contraction too: otherwise a buffer driving
    # the same wire as an original output can disappear in the proof.
    drivers=defaultdict(list)
    for pin,p in b['ports'].items():
        if p['direction']=='input':
            for n in p['bits']:drivers[n].append(('port',pin))
    for name,c in b['cells'].items():
        for pin,ns in c['connections'].items():
            if c['directions'][pin]=='output':
                for n in ns:
                    require(n[0]!='constant','REPAIR_DRIVEN_CONSTANT')
                    drivers[n].append((name,pin))
    require(all(len(ds)<=1 for ds in drivers.values()),'REPAIR_MULTIPLE_DRIVERS')
    for name,old in a['cells'].items():
        new=b['cells'][name]
        require(old['directions']==new['directions'] and old['connections'].keys()==new['connections'].keys(), 'REPAIR_CELL_PINS')
        require(all(len(old['connections'][p])==len(new['connections'][p]) for p in old['connections']),'REPAIR_CELL_WIDTH')
        if old['type']!=new['type']:
            require(name not in protected and old['type']!=SRAM,'REPAIR_PROTECTED_MASTER')
            require(all(logic_signature(lib,old['type'])==logic_signature(lib,new['type']) for lib in libs),'REPAIR_CHANGED_FUNCTION')
            resized.append(dict(cell=name,before=old['type'],after=new['type']))
    def nets(g,normalize):
        result=defaultdict(list);drivers=defaultdict(list)
        for pin,p in g['ports'].items():
            for i,n in enumerate(p['bits']):
                n=normalize(n);tag=('port',pin,i);result[n].append(tag)
                if p['direction']=='input':drivers[n].append(tag)
        for name,c in g['cells'].items():
            if name in added:continue
            for pin,ns in c['connections'].items():
                for i,n in enumerate(ns):
                    n=normalize(n);tag=('cell',name,pin,i);result[n].append(tag)
                    if c['directions'][pin]=='output':drivers[n].append(tag)
        require(all(len(ds)<=1 for ds in drivers.values()),'REPAIR_MULTIPLE_DRIVERS')
        return {tuple(sorted(tags)):(n[1] if n[0]=='constant' else 'wire') for n,tags in result.items()},result
    old_nets,old_members=nets(a,lambda n:n);new_nets,new_members=nets(b,contract)
    require(old_nets==new_nets,'REPAIR_GRAPH_CHANGED')
    # Every added output must reach an original sink; unused/buffer-only islands
    # cannot hide arbitrary extra logic in an otherwise equivalent partition.
    used={n for c in b['cells'].values() for p,bs in c['connections'].items() if c['directions'][p]=='input' for n in bs}
    used.update(n for p in b['ports'].values() if p['direction']=='output' for n in p['bits'])
    # Unconsumed native constant ports still belong to the exact primitive
    # boundary above. Their tie drivers preserve that contract even when no
    # downstream leaf consumes the port. This exception is for proved ties,
    # never for buffers or unobserved signal aliases.
    native_constants={bit for owner in owner_pins for p in b_ports[owner]
        for bit in b['boundaries'][p] if bit in constants}
    require(set(aliases)-set(constants)<=used and set(constants)<=used|native_constants and
        all(contract(n) in new_members or n in native_constants for n in aliases),'REPAIR_UNUSED_BUFFER')
    # protected maps exact leaf -> adapter root. Native internal nets may never
    # acquire buffers; only external adapter ports may gain distribution.
    # The uncontracted native pin/port partition above covers keeper feedback
    # even where its signal is also exposed at an adapter boundary.
    return dict(status='exact-original-graph-after-buffer-contraction-and-equivalent-resize',
                original_cells=len(a['cells']),added_buffers=sorted(added-set(ties)),added_ties=sorted(ties),
                resized=resized,protected_cells=len(protected),omitted_dead_native_inputs=sorted(omitted,key=lambda p:p['port']))


def split_output_feedback(netlist,top='RiscayMcuDigital',*,skipped=None):
    """Isolate internal data fanout from exported hierarchical output buses.

    The pinned OpenROAD hierarchical writer otherwise splits some of these
    aliases. Explicit, real buffers avoid that serialization defect. They are
    charged to physical area and included in subsequent timing, never hidden
    by the logical contraction proof. Primitive-local feedback is excluded.
    Declared child inputs are only candidates: the complete instantiated graph
    must show a real leaf-input or top-output consumer before retaining a buffer.
    """
    inserted=[];restores={}
    for kind,body in netlist['modules'].items():
        cells=body.get('cells',{})
        outputs={b for p in body['ports'].values() if p['direction']=='output' and len(p['bits'])>1
            for b in p['bits'] if isinstance(b,int)}
        if not outputs:continue
        drivers=defaultdict(list);loads=defaultdict(list)
        for name,c in cells.items():
            for pin,bits in c['connections'].items():
                for index,b in enumerate(bits):
                    if b not in outputs:continue
                    if c['port_directions'][pin]=='output' and not c['type'].startswith(SC) and c['type']!=SRAM:
                        drivers[b].append(name)
                    if c['port_directions'][pin]=='input':loads[b].append((name,pin,index))
        needs=sorted(b for b in outputs if len(drivers[b])==1 and loads[b] and
            all(n!=drivers[b][0] for n,p,i in loads[b]))
        if not needs:continue
        bits=[b for c in cells.values() for bs in c['connections'].values() for b in bs]
        bits += [b for p in (*body['ports'].values(),*body.get('netnames',{}).values()) for b in p['bits']]
        fresh=max(b for b in bits if isinstance(b,int))+1
        for bit in needs:
            name='riscay_output_feedback_'+str(bit)
            require(name not in cells,'REPAIR_FEEDBACK_NAME_COLLISION')
            for n,p,i in loads[bit]:cells[n]['connections'][p][i]=fresh
            cells[name]=dict(type=SC+'buf_1',parameters={},attributes={},
                port_directions={'I':'input','Z':'output'},connections={'I':[bit],'Z':[fresh]})
            inserted.append(dict(module=kind,cell=name,loads=len(loads[bit])))
            restores[(kind,name)]=(bit,list(loads[bit]))
            fresh+=1
    if not inserted:return []
    locations=instance_locations(netlist,top);paths=defaultdict(list)
    for path,location in locations.items():
        if location in restores:paths[location].append(path)
    require(set(paths)==set(restores),'REPAIR_FEEDBACK_UNREACHABLE_MODULE')
    g=flat(netlist,top);candidates={path for ps in paths.values() for path in ps}
    live={n for name,c in g['cells'].items() if name not in candidates
        for p,bs in c['connections'].items() if c['directions'][p]=='input' for n in bs}
    live.update(n for p in g['ports'].values() if p['direction']=='output' for n in p['bits'])
    # Nested helper buffers may form a chain. Keep it only when it terminates
    # in a genuine consumer, not merely in another newly created buffer.
    changed=True
    while changed:
        changed=False
        for path in candidates:
            conn=g['cells'][path]['connections'];src,dst=conn['I'][0],conn['Z'][0]
            if dst in live and src not in live:live.add(src);changed=True
    dead={}
    for location,physical in paths.items():
        unused=[path for path in physical if g['cells'][path]['connections']['Z'][0] not in live]
        require(not unused or len(unused)==len(physical),'REPAIR_FEEDBACK_SHARED_LIVENESS')
        if unused:dead[location]=sorted(unused)
    for (kind,name),physical in sorted(dead.items()):
        bit,loads=restores[(kind,name)];cells=netlist['modules'][kind]['cells']
        for n,p,i in loads:cells[n]['connections'][p][i]=bit
        del cells[name]
        if skipped is not None:skipped.append(dict(module=kind,cell=name,instances=physical,
            reason='no-leaf-input-or-top-output-consumer'))
    return [e for e in inserted if (e['module'],e['cell']) not in dead]


def instance_locations(netlist,top):
    """Resolve exact physical paths to their containing JSON module/cell key."""
    result={}
    def walk(kind,prefix='',stack=()):
        require(kind not in stack,'REPAIR_HIERARCHY_CYCLE')
        for key,c in netlist['modules'][kind].get('cells',{}).items():
            path=prefix+ident(key)
            require(path not in result,'REPAIR_DUPLICATE_CELL')
            result[path]=(kind,key)
            if not c['type'].startswith(SC) and c['type']!=SRAM:
                walk(c['type'],path+'/',stack+(kind,))
    walk(top)
    return result


def buffer_native_resets(netlist,top,adapter_instances):
    """Put an ordinary distribution sink outside each exact native reset port.

    Native cells and their owner-local reset partitions stay untouched. The
    parent-side buffers are real cells, counted in preparation and subsequent
    mapping/timing; OpenROAD may size or distribute their unprotected inputs.
    """
    locations=instance_locations(netlist,top);edited={};evidence=[]
    require(len(set(adapter_instances.values()))==len(adapter_instances),'REPAIR_RESET_ADAPTER_DUPLICATE')
    for owner in sorted(adapter_instances.values()):
        require(owner in locations,'REPAIR_RESET_ADAPTER_MISSING')
        kind,key=locations[owner];body=netlist['modules'][kind];c=body['cells'][key]
        ports=netlist['modules'][c['type']]['ports']
        require('reset' in ports and ports['reset']['direction']=='input' and len(ports['reset']['bits'])==1 and
            c['port_directions'].get('reset')=='input' and len(c['connections'].get('reset',[]))==1,
            'REPAIR_RESET_BOUNDARY_SHAPE')
        if (kind,key) not in edited:
            bits=[b for cell in body['cells'].values() for bs in cell['connections'].values() for b in bs]
            bits += [b for p in (*body['ports'].values(),*body.get('netnames',{}).values()) for b in p['bits']]
            fresh=max((b for b in bits if isinstance(b,int)),default=1)+1
            name='riscay_native_reset_'+str(len(edited))
            require(name not in body['cells'],'REPAIR_RESET_BUFFER_NAME_COLLISION')
            source=c['connections']['reset'][0]
            c['connections']['reset']=[fresh]
            body['cells'][name]=dict(type=SC+'buf_1',parameters={},attributes={},
                port_directions={'I':'input','Z':'output'},connections={'I':[source],'Z':[fresh]})
            edited[(kind,key)]=name
        parent=owner.rsplit('/',1)[0]+'/' if '/' in owner else ''
        evidence.append(dict(owner=owner,port='reset',buffer=parent+edited[(kind,key)],master=SC+'buf_1'))
    require(len({e['buffer'] for e in evidence})==len(evidence),'REPAIR_RESET_BUFFER_IDENTITY')
    return evidence


def prune_added_orphan_ties(before,after,top,protected,libs):
    """Delete only added constant drivers with no live physical consumer.

    The writer can omit unused native inputs, leaving preparation ties attached
    only to dead wrapper aliases. Original cells, all buffers, top outputs and
    every retained native boundary remain untouched. Shared-module ambiguity
    fails closed instead of deleting a tie still used by another instance.
    """
    a,b=flat(before,top),flat(after,top)
    require(a['cells'].keys()<=b['cells'].keys(),'REPAIR_ORIGINAL_CELL_REMOVED')
    added=set(b['cells'])-set(a['cells']);owners=set(protected.values())
    used={n for c in b['cells'].values() for p,bs in c['connections'].items() if c['directions'][p]=='input' for n in bs}
    used.update(n for p in b['ports'].values() if p['direction']=='output' for n in p['bits'])
    used.update(n for p,bs in b['boundaries'].items() if p.rsplit('/',1)[0] in owners for n in bs)
    drivers=defaultdict(int)
    for c in b['cells'].values():
        for p,bs in c['connections'].items():
            if c['directions'][p]=='output':
                for n in bs:drivers[n]+=1
    for p in b['ports'].values():
        if p['direction']=='input':
            for n in p['bits']:drivers[n]+=1
    removals={}
    for name in sorted(added):
        c=b['cells'][name]
        if c['type'] not in (SC+'tieh',SC+'tiel'):continue
        pin,value=('Z','1') if c['type']==SC+'tieh' else ('ZN','0')
        require(all(logic_signature(lib,c['type'])=={pin:('output',value,None)} for lib in libs),'REPAIR_TIE_FUNCTION')
        require(c['directions']=={pin:'output'} and list(c['connections'])==[pin] and
            len(c['connections'][pin])==1,'REPAIR_TIE_PINS')
        if c['connections'][pin][0] not in used:
            require(drivers[c['connections'][pin][0]]==1,'REPAIR_ORPHAN_TIE_MULTIPLE_DRIVERS')
            removals[name]=dict(cell=name,master=c['type'],pin=pin,value=value,
                reason='no-leaf-input-top-output-or-retained-native-boundary-consumer')
    locations=instance_locations(after,top);groups=defaultdict(set)
    for path,location in locations.items():groups[location].add(path)
    selected={locations[path] for path in removals}
    require(all(groups[location]<=removals.keys() for location in selected),'REPAIR_ORPHAN_TIE_SHARED_MODULE')
    for kind,key in sorted(selected):del after['modules'][kind]['cells'][key]
    return list(removals.values())


def correct_scalar_port_escaping(text):
    """Repair one pinned writer defect, never infer a missing logical wire.

    Newly inserted hierarchy ports can be escaped scalar names such as
    ``\\owner_bus[3]`` while their uses are emitted as an unescaped bus select.
    Only an exact scalar declaration in the same module authorizes escaping a
    use. Any real declaration of the base name is ambiguous and rejected. Raw
    output and exact edit offsets are retained; whole-graph proof still gates
    acceptance of the corrected file.
    """
    blank=lambda m:re.sub(r'[^\n]',' ',m[0])
    masked=re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"',blank,text)
    edits=[];evidence=[]
    modules=list(re.finditer(r'(?m)^\s*module\s+(\\[^\s]+|[A-Za-z_$][\w$]*)\b[\s\S]*?\bendmodule\b',masked))
    require(len(modules)==len(re.findall(r'(?m)^\s*module\s',masked)),'REPAIR_SERIALIZER_MODULE_SHAPE')
    for module in modules:
        body=module[0]
        declarations=list(re.finditer(r'(?m)^\s*(?:input|output|inout|wire|tri|reg|logic)\b([^;]*);',body))
        scalars=[];ordinary=set()
        for declaration in declarations:
            value=declaration[1]
            # Escaped identifiers terminate at whitespace, not punctuation.
            require(not re.search(r'\\[A-Za-z_$][\w$]*\[\d+\](?=[,;()])',declaration[0]),
                    'REPAIR_SERIALIZER_MALFORMED_ESCAPE')
            scalar=re.fullmatch(r'\s*\\([A-Za-z_$][\w$]*\[\d+\])\s+',value)
            if scalar:scalars.append(scalar[1])
            ordinary.update(re.findall(r'\\([A-Za-z_$][\w$]*)\s',value))
            unescaped=re.sub(r'\\[^\s]+',blank,value)
            unescaped=re.sub(r'\[[^\]]*\]',blank,unescaped)
            ordinary.update(re.findall(r'[A-Za-z_$][\w$]*',unescaped))
        require(len(scalars)==len(set(scalars)),'REPAIR_SERIALIZER_DUPLICATE_SCALAR')
        # Do not edit comments, strings, escaped declarations/references or a
        # different escaped identifier containing the same spelling.
        uses=re.sub(r'\\[^\s]+',blank,body)
        for name in scalars:
            base=name[:name.index('[')]
            require(base not in ordinary,'REPAIR_SERIALIZER_AMBIGUOUS_BASE_'+base)
            require(not re.search(r'\\'+re.escape(name)+r'(?=[,;()])',body),
                    'REPAIR_SERIALIZER_MALFORMED_ESCAPE')
            matches=list(re.finditer(r'(?<![\w$])'+re.escape(name)+r'(?![\w$])',uses))
            offsets=[module.start()+m.start() for m in matches]
            for offset in offsets:edits.append((offset,offset+len(name),'\\'+name+' '))
            if offsets:evidence.append(dict(module=module[1],identifier=name,offsets=offsets))
    pieces=[];cursor=0
    for start,end,replacement in sorted(edits):
        require(start>=cursor,'REPAIR_SERIALIZER_OVERLAPPING_EDIT')
        pieces.extend((text[cursor:start],replacement));cursor=end
    pieces.append(text[cursor:])
    return ''.join(pieces),evidence


def protected_cells(mapping):
    record=json.loads((mapping/'mapping.json').read_text());audit=json.loads((mapping/'netlist-audit.json').read_text())
    require(audit['status']=='pass' and audit['mapping_sha256']==sha(mapping/'mapping.json') and
        audit['netlist_sha256']==sha(mapping/'netlist.v'),'REPAIR_STALE_AUDIT')
    return {audit['adapter_instances'][i]+'/'+c['name']:audit['adapter_instances'][i]
            for b in record['bindings'] for i in b['instances'] for c in b['cells']}


def read_verilog_json(verilog,output,top,yosys,pdk,reference,*,tie_verilog=None):
    # Include exact fixed blackboxes (SRAM), never a behavioral macro substitute.
    black=output.with_suffix('.blackboxes.json')
    write_json(black,dict(modules={n:m for n,m in reference['modules'].items() if not n.startswith(SC) and
        int(m.get('attributes',{}).get('blackbox','0'),2)}))
    q=lambda p:'"'+yosys.path(p)+'"'
    commands='read_liberty -lib '+q(pdk/(SC+CORNERS[0]+'.lib'))+'\nread_json '+q(black)+\
        '\nread_verilog '+q(verilog)+'\nhierarchy -check -top '+top+'\n'
    if tie_verilog is not None:
        # Keep every original cell, then discard only unused additions/aliases.
        # hilomap otherwise creates thousands of drivers for constant netnames
        # which do not feed any pin. The subsequent graph proof is mandatory.
        commands+='setattr -set keep 1 */c:*\nhilomap -singleton -hicell '+SC+'tieh Z -locell '+SC+'tiel ZN\nopt_clean -purge\n'
        commands+='write_verilog -norename -noattr -noexpr '+q(tie_verilog)+'\n'
    script=output.with_suffix('.ys');script.write_text(commands+'write_json '+q(output)+'\n',newline='\n')
    with output.with_suffix('.log').open('w') as stream:
        subprocess.run(yosys.command(['-s',yosys.path(script)],timeout=180),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=190)
    return json.loads(output.read_text())


def validate_receipt(mapping):
    """Require the accepted repaired graph, never an unverified stale side file."""
    mapping=mapping.resolve();out=mapping/'electrical-repair'
    require((out/'receipt.json').is_file(),'REPAIR_RECEIPT_REQUIRED')
    receipt=json.loads((out/'receipt.json').read_text())
    require(receipt.get('schema')=='riscay-electrical-repair-v1' and
        receipt['status']=='structurally-accepted-electrically-unqualified' and
        receipt['physical_qualification'] is False,'REPAIR_RECEIPT_STATUS')
    require(set(receipt['evidence_sha256'])==set(EVIDENCE),'REPAIR_EVIDENCE_INVENTORY')
    require(set(receipt['inputs_sha256'])=={str(p.resolve()) for p in input_files(mapping)},'REPAIR_INPUT_INVENTORY')
    require(sha(mapping/'netlist-audit.json')==receipt['evidence_sha256']['candidate/netlist-audit.json'],
        'REPAIR_AUDIT_CHANGED')
    for name,key in (('netlist.v','repaired_verilog_sha256'),('netlist.json','repaired_json_sha256')):
        require(sha(mapping/name)==receipt[key],'REPAIR_REPAIRED_NETLIST_CHANGED')
    for name,digest in receipt['evidence_sha256'].items():
        p=(out/name).resolve()
        require(p.is_relative_to(out) and sha(p)==digest,'REPAIR_EVIDENCE_CHANGED')
    for name,digest in receipt['inputs_sha256'].items():
        p=Path(name)
        if p.parent==mapping and p.name in ('netlist.v','netlist.json','netlist-audit.json'):
            p=out/'reference'/p.name
        require(sha(p)==digest,'REPAIR_INPUT_CHANGED')
    return receipt


def input_files(mapping):
    pdk=ROOT/'.tools/physical/pdk'
    files=[mapping/n for n in ('mapping.json','netlist.v','netlist.json','netlist-audit.json')]
    files += [ROOT/'tools'/n for n in ('repair_gf180_design.py','physical_tools.py','gf180_physical.py',
        'gf180_estimate.py','gf180_implement.py','repair_gf180_control.py','characterize_gf180_liberty.py')]
    files += tool('openroad').input_files()+tool('yosys').input_files()
    files += [pdk/(SC+c+'.lib') for c in CORNERS]+[ROOT/'.tools/physical/routing/technology.tlef',pdk/'gf180mcu_fd_sc_mcu7t5v0.lef',
        ROOT/'.tools/gf180-sram'/(SRAM+'.lef'),ROOT/'.tools/gf180-sram'/(SRAM+'__tt_025C_3v30.lib')]
    return files


def repair(mapping,*,timeout=600):
    """Default post-map pass. Publish repaired netlists only after the proof."""
    out=mapping/'electrical-repair';require(not out.exists(),'REPAIR_OUTPUT_EXISTS')
    pdk=ROOT/'.tools/physical/pdk';pdk_verify(pdk);openroad=tool('openroad');yosys=tool('yosys')
    before=json.loads((mapping/'netlist.json').read_text());protected=protected_cells(mapping)
    out.mkdir();reference=out/'reference';reference.mkdir()
    for name in ('netlist.v','netlist.json','netlist-audit.json'):shutil.copyfile(mapping/name,reference/name)
    frozen={str(p.resolve()):sha(p) for p in input_files(mapping)}
    write_json(out/'inputs.json',frozen)
    libs=[library(pdk/(SC+c+'.lib')) for c in CORNERS]
    original=read_verilog_json(reference/'netlist.v',reference/'readback.json','RiscayMcuDigital',yosys,pdk,before)
    original_proof=graph_proof(before,original,'RiscayMcuDigital',protected,libs)
    require(not original_proof['added_buffers'] and not original_proof['added_ties'] and not original_proof['resized'],
        'REPAIR_SOURCE_GRAPH_MISMATCH')
    tied=read_verilog_json(reference/'netlist.v',out/'tied.json','RiscayMcuDigital',yosys,pdk,before,tie_verilog=out/'tied.v')
    tie_proof=graph_proof(before,tied,'RiscayMcuDigital',protected,libs)
    require(not tie_proof['added_buffers'] and not tie_proof['resized'],'REPAIR_TIE_PREPARATION_CHANGED_GRAPH')
    reset_preparation=buffer_native_resets(tied,'RiscayMcuDigital',
        json.loads((reference/'netlist-audit.json').read_text())['adapter_instances'])
    skipped_feedback=[]
    preparation=split_output_feedback(tied,'RiscayMcuDigital',skipped=skipped_feedback)
    prepared_proof=graph_proof(before,tied,'RiscayMcuDigital',protected,libs)
    require(not prepared_proof['resized'],'REPAIR_PREPARATION_CHANGED_MASTER')
    write_json(out/'prepared.json',tied)
    write_json(out/'preparation.json',dict(buffers=preparation,skipped_feedback_buffers=skipped_feedback,reset_buffers=reset_preparation,
        added_buffer_cells=dict(reset_distribution=len(reset_preparation),
            hierarchy_output_feedback=len(prepared_proof['added_buffers'])-len(reset_preparation)),proof=prepared_proof))
    q=lambda p:'"'+yosys.path(p)+'"'
    emit=out/'prepared.ys'
    emit.write_text('read_json '+q(out/'prepared.json')+'\nwrite_verilog -norename -noattr -noexpr '+q(out/'prepared.v')+'\n',newline='\n')
    with (out/'prepared.log').open('w') as stream:
        subprocess.run(yosys.command(['-s',yosys.path(emit)],timeout=180),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=190)
    b=lambda p:'{'+openroad.path(p)+'}'
    text='define_corners '+' '.join(CORNERS)+'\n'
    for c in CORNERS:
        text+='read_liberty -corner '+c+' '+b(pdk/(SC+c+'.lib'))+'\n'
        # Macro cell graph is fixed and protected. This TT view supplies pin
        # loading only; it is not a multi-corner SRAM timing qualification.
        text+='read_liberty -corner '+c+' '+b(ROOT/'.tools/gf180-sram'/(SRAM+'__tt_025C_3v30.lib'))+'\n'
    text+='read_lef '+b(ROOT/'.tools/physical/routing/technology.tlef')+'\nread_lef '+b(pdk/'gf180mcu_fd_sc_mcu7t5v0.lef')+'\n'
    text+='read_lef '+b(ROOT/'.tools/gf180-sram'/(SRAM+'.lef'))+'\nread_verilog '+b(out/'prepared.v')+'\nlink_design -hier RiscayMcuDigital\n'
    text+='initialize_floorplan -die_area {0 0 5000 5000} -core_area {30 30 4970 4970} -site GF018hv5v_mcu_sc7\n'
    text+='set_wire_rc -resistance 0 -capacitance 0\nset_input_transition 2 [all_inputs]\nset_load 0.05 [all_outputs]\nset_max_transition 2 [current_design]\n'
    # Constant drivers were inserted into their real owning modules by Yosys.
    # OpenROAD's insertion creates flat drivers which its hierarchical writer
    # cannot reliably connect back into child modules in this pinned version.
    text+='set protected [dict create]\nforeach name {'+' '.join('{'+n+'}' for n in sorted(protected))+'} {dict set protected $name 1}\n'
    text+='set count 0\nforeach inst [[ord::get_db_block] getInsts] {\n'
    text+='if {[dict exists $protected [$inst getName]]} {$inst setDoNotTouch true; incr count}\n'
    text+='if {[[$inst getMaster] getName] eq "'+SRAM+'"} {$inst setDoNotTouch true}\n}\n'
    # Ordinary FFs may receive distribution buffers. Exclude sequential cells
    # as resize replacements; the independent proof rejects any master change.
    text+='set_dont_use [get_lib_cells */*dff*]\nset_dont_use [get_lib_cells */*lat*]\n'
    text+='if {$count != '+str(len(protected))+'} {error REPAIR_PROTECTED_INVENTORY}\n'
    text+='report_check_types -max_slew -max_capacitance -violators -digits 6 > '+b(out/'before-electrical.rpt')+'\n'
    text+='repair_design -pre_placement -max_wire_length 0 -verbose\n'
    text+='report_check_types -max_slew -max_capacitance -violators -digits 6 > '+b(out/'after-electrical.rpt')+'\n'
    text+='write_verilog '+b(out/'repaired-raw.v')+'\nputs REPAIR_COMPLETE\nexit\n'
    script=out/'repair.tcl';script.write_text(text,newline='\n')
    with (out/'repair.log').open('w') as stream:
        subprocess.run(openroad.command(['-exit',openroad.path(script)],timeout=timeout),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=timeout+15)
    require((out/'repair.log').read_text().count('REPAIR_COMPLETE\n')==1,'REPAIR_INCOMPLETE')
    corrected,edits=correct_scalar_port_escaping((out/'repaired-raw.v').read_text())
    (out/'serializer-corrected.v').write_text(corrected,newline='\n')
    write_json(out/'serializer-corrections.json',dict(status='syntax-only-requires-graph-proof',
        raw_sha256=sha(out/'repaired-raw.v'),corrected_sha256=sha(out/'serializer-corrected.v'),edits=edits))
    serialized=read_verilog_json(out/'serializer-corrected.v',out/'serializer-readback.json',
        'RiscayMcuDigital',yosys,pdk,before)
    removed=prune_added_orphan_ties(before,serialized,'RiscayMcuDigital',protected,libs)
    write_json(out/'orphan-ties.json',dict(status='removed-added-unused-ties-requires-graph-proof',cells=removed))
    write_json(out/'pruned.json',serialized)
    emit=out/'pruned.ys'
    emit.write_text('read_json '+q(out/'pruned.json')+'\nwrite_verilog -norename -noattr -noexpr '+q(out/'repaired.v')+'\n',newline='\n')
    with (out/'pruned.log').open('w') as stream:
        subprocess.run(yosys.command(['-s',yosys.path(emit)],timeout=180),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=190)
    after=read_verilog_json(out/'repaired.v',out/'repaired.json','RiscayMcuDigital',yosys,pdk,before)
    proof=graph_proof(before,after,'RiscayMcuDigital',protected,libs)
    # Run the existing exact adapter audit before publishing either output.
    candidate=out/'candidate';candidate.mkdir()
    shutil.copyfile(mapping/'mapping.json',candidate/'mapping.json')
    shutil.copyfile(out/'repaired.v',candidate/'netlist.v')
    shutil.copyfile(out/'repaired.json',candidate/'netlist.json')
    from gf180_implement import audit
    audit(candidate,adapter_instances=json.loads((reference/'netlist-audit.json').read_text())['adapter_instances'])
    require(all(sha(Path(p))==h for p,h in frozen.items()),'REPAIR_INPUT_CHANGED')
    write_json(out/'proof.json',proof)
    write_json(out/'receipt.json',dict(schema='riscay-electrical-repair-v1',status='structurally-accepted-electrically-unqualified',physical_qualification=False,
        inputs_sha256=frozen,repaired_verilog_sha256=sha(out/'repaired.v'),repaired_json_sha256=sha(out/'repaired.json'),
        evidence_sha256={name:sha(out/name) for name in EVIDENCE}))
    try:
        for name in ('netlist.v','netlist.json','netlist-audit.json'):shutil.copyfile(candidate/name,mapping/name)
        validate_receipt(mapping)
    except BaseException:
        for name in ('netlist.v','netlist.json','netlist-audit.json'):shutil.copyfile(reference/name,mapping/name)
        raise
    return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mapping',type=Path)
    args=parser.parse_args();proof=repair(args.mapping)
    print(json.dumps(dict(status=proof['status'],added_buffers=len(proof['added_buffers']),resized=len(proof['resized']))))

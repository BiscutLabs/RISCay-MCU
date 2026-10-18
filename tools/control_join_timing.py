# SPDX-License-Identifier: Apache-2.0
"""Reusable canonical Join-to-stage timing; conditional measurements, never signoff.

Control is the default caller. Instance wiring and every independent data source
are explicit: destination reachability alone cannot prove source coverage.
"""
from copy import deepcopy
from collections import defaultdict
from run_receipt import RunReceipt
import argparse
import json
import math
from pathlib import Path
import re
import subprocess

import control_relative_timing as relative
import native_stage_timing as stages
from characterize_gf180_control_native import audit_bindings
from gf180_physical import ROOT, SC, nodes, write_json, sha, pdk_verify
from repair_gf180_control import require, connectivity
from physical_tools import tool

TOP="RiscayControlJoinTiming"

# Unlike the generic probe's pin summary property, the graph-vertex slew accessor
# preserves explicit Q-slew annotations. Never substitute zero for a missing slew.
JOIN_PROBE=r'''
proc join_slew {pin edge {mode max}} {
  set values {}
  foreach vertex [$pin vertices] {
    lappend values [sta::time_sta_ui [$vertex slew_corner $edge [sta::cmd_corner] $mode]]
  }
  if {![llength $values]} {error JOIN_SLEW_VERTEX}
    return [tcl::mathfunc::$mode {*}$values]
}
proc join_batch {mode source_edge sink_edge sources sink_kind members} {
  set sinks {}; set ids [dict create]
  foreach {id name} $members {
    if {[dict exists $ids $name]} {error JOIN_DUPLICATE_ENDPOINT}
    dict set ids $name $id; lappend sinks [exact_object $sink_kind $name]
  }
  if {$source_edge eq "any"} {set from -from} else {set from -${source_edge}_from}
  foreach end [find_timing_paths $from $sources -${sink_edge}_to $sinks -path_delay $mode -group_path_count [expr {[dict size $ids]+1}] -endpoint_path_count 1] {
    set name [get_full_name [$end pin]]
    if {![dict exists $ids $name]} {error JOIN_DUPLICATE_PATH}
    if {[$end is_unconstrained] || ![$end is_path_delay]} {error JOIN_PATH_DELAY_REQUIRED}
    set id [dict get $ids $name]; dict unset ids $name
    set path [$end path]; set start [$path start_path]
    set source [sta::time_sta_ui [$start arrival]]; set arrival [sta::time_sta_ui [$path arrival]]
    set names {}; set slew 0.0
    foreach pin [$path pins] {
      lappend names [get_full_name $pin]
      foreach edge {rise fall} {set slew [tcl::mathfunc::max $slew [join_slew $pin $edge]]}
    }
    row CONTROL_PATH $id $source $arrival [sta::time_sta_ui [$end data_arrival_time]] [expr {$arrival-$source}] $slew [get_full_name [$start pin]] $name [string map {^ rise v fall} [$start edge]] [string map {^ rise v fall} [$end end_transition]]
    row CONTROL_POINTS $id {*}[lreverse $names]
  }
  dict for {name id} $ids {row CONTROL_MISSING $id}
}
'''


def selection(variant, target):
    prefix = "FourPhase" if variant == "bd" else "Click"
    if target == "control":
        return dict(parent_path=prefix+"Soc.ca_child_control", parent_family=prefix+"Control",
                    sink_name="ca_child_update", operand_fields={"left":"left", "right":"right"}, side_inputs={})
    require(target == "execute", "JOIN_TARGET")
    return dict(parent_path=prefix+"Soc.ca_child_core", parent_family=prefix+"Core",
                sink_name="ca_child_execute", operand_fields={"left":"state", "right":"response"},
                side_inputs={f"in_bits_registers_{i}":dict(cell="ca_child_register_file", port=f"values_{i}", width=32)
                             for i in range(15)})


def bind_inputs(parent, join, sink, operand_fields, side_inputs, ack_guard=None):
    """Account for each sink input, including inputs overlapping a Join cone."""
    jc, uc = join["connections"], sink["connections"]
    require(set(operand_fields) == {"left", "right"} and len(set(operand_fields.values())) == 2,
            "JOIN_OPERAND_FIELDS")
    covered = {"reset"}
    bindings = []
    for pin in jc:
        if not pin.startswith("out_"): continue
        dest = "in_" + pin[4:]
        for side, field in operand_fields.items():
            root = "in_bits_"+side
            if dest == root or dest.startswith(root+"_"):
                dest = "in_bits_"+field+dest[len(root):]
                break
        if pin=='out_ack' and ack_guard is not None:
            require(ack_guard['a']==uc.get(dest) and ack_guard['q']==jc[pin] and
                    ack_guard['reset']==jc['reset'] and ack_guard['b']==['0'], 'JOIN_ACK_GUARD_WIRING')
        else:require(dest in uc and jc[pin] == uc[dest], "JOIN_UPDATE_WIRING")
        covered.add(dest)
        bindings.append(dict(source=pin, destination=dest, width=len(uc[dest]), kind="join"))
    side_bits=set()
    for pin, spec in side_inputs.items():
        require(pin.startswith("in_bits_") and pin not in covered and pin in uc, "JOIN_SIDE_INPUT_PORT")
        require(set(spec) == {"cell", "port", "width"} and spec["cell"] in parent["cells"], "JOIN_SIDE_INPUT_SPEC")
        source = parent["cells"][spec["cell"]]
        require(source["port_directions"].get(spec["port"]) == "output" and
                source["connections"].get(spec["port"]) == uc[pin] and
                len(uc[pin]) == spec["width"], "JOIN_SIDE_INPUT_BINDING")
        require(all(type(b)==int for b in uc[pin]) and len(set(uc[pin]))==len(uc[pin]) and
                not side_bits.intersection(uc[pin]), "JOIN_SIDE_INPUT_ALIAS")
        side_bits.update(uc[pin])
        covered.add(pin)
        bindings.append(dict(destination=pin, kind="uncomposed-side-source", **spec,
            lanes=[dict(source_bit=i,destination_bit=i,parent_net=b) for i,b in enumerate(uc[pin])]))
    required = {p for p, direction in sink["port_directions"].items() if direction == "input" and p != "out_ack"}
    # in_ack is an output, but is deliberately included in the channel identity check above.
    require(covered == required | {"in_ack"}, "JOIN_INPUT_COVERAGE")
    return bindings


def bound_slice(netlist, record, manifest, variant, *, target="control"):
    prefix=("FourPhase" if variant=="bd" else "Click")
    config=selection(variant,target)
    path=config['parent_path'];sink_name=config['sink_name']
    kind="RiscayMcuDigital"
    for name in ("soc",*path.split('.')[1:]):kind=netlist["modules"][kind]["cells"][name]["type"]
    require(re.fullmatch(config['parent_family']+r"(?:_\d+)?",kind) is not None,"JOIN_PARENT_FAMILY")
    parent=netlist["modules"][kind]
    selected={name:deepcopy(parent["cells"][name]) for name in ("ca_child_join",sink_name)}
    ack_guard=None
    guard_name='ca_primitive_acknowledge_guard'
    if guard_name in parent['cells']:
        require(variant=='bd' and target=='control','JOIN_UNEXPECTED_ACK_GUARD')
        pnode=next(n for n in nodes(manifest['design']) if n['rtl_path']==path)
        ps=[p for p in pnode['primitives'] if p['id']=='acknowledge_guard' and p['view']!='constraint-marker']
        require(len(ps)==1,'JOIN_ACK_GUARD_CONTRACT')
        p=ps[0];params={k:int(v) for k,v in p['parameters'].items()}
        require(p['model']=='ChiselAsyncControlGate_v1' and p['rtl_path']==path+'.'+guard_name and p['version']==1 and
                set(params)=={'OP','WIDTH','RESET_VALUE','DELAY_FS'} and params['DELAY_FS']>0 and
                {k:v for k,v in params.items() if k!='DELAY_FS'}==dict(OP=0,WIDTH=1,RESET_VALUE=0),
                'JOIN_ACK_GUARD_SPECIALIZATION')
        audit_bindings(netlist,record,dict(module=kind,variant=variant,aliases=[],verify_roots=[guard_name],
            expected_bindings={guard_name:(p['model'],params)},physical_prefix='soc/'+'/'.join(path.split('.')[1:])+'/'))
        selected[guard_name]=deepcopy(parent['cells'][guard_name]);ack_guard=selected[guard_name]['connections']
    join=netlist["modules"][selected["ca_child_join"]["type"]]
    update=netlist["modules"][selected[sink_name]["type"]]
    plans={}
    for name in ("left","right","update"):
        suffix=(sink_name if name=="update" else
                "ca_child_join.ca_child_"+name+("_storage" if variant=="click" else ""))
        desc=stages.descriptor(manifest,netlist,record,path+"."+suffix,variant,storage=name!="update")
        plans[name]=relative.make_plan(netlist,record,variant,desc)
        plans[name]["prefix"]=suffix.replace(".","/")+"/"
        if name!='update':identity_storage(netlist['modules'][desc['module']])
    jnode=next(n for n in nodes(manifest["design"]) if n["rtl_path"]==path+".ca_child_join")
    require(re.fullmatch(prefix+"Join"+r"(?:_\d+)?",jnode["module"]) is not None,"JOIN_CONTROLLER_FAMILY")
    primitives=[p for p in jnode["primitives"] if p["view"]!="constraint-marker"]
    shape=dict(COMMON=2,COMMON_INVERT=0,RISING=0,RISING_INVERT=0,FALLING=0,FALLING_INVERT=0,RESET_VALUE=0,DELAY_FS=1000000)
    require(len(primitives)==1 and primitives[0]["id"]=="rendezvous" and
            primitives[0]["model"]=="ChiselAsyncAsymmetricC_v1" and
            {k:int(v) for k,v in primitives[0]["parameters"].items()}==shape,"JOIN_RENDEZVOUS_CONTRACT")
    rname="out_req_ca_primitive_rendezvous"
    require(primitives[0]['rtl_path']==path+'.ca_child_join.'+rname and primitives[0]['version']==1,"JOIN_RENDEZVOUS_PATH")
    selected_bindings=[b for b in record['bindings'] if primitives[0]['rtl_path'] in b['instances']]
    require(len(selected_bindings)==1 and selected_bindings[0]['parameters']==shape and
            selected_bindings[0]['model']==primitives[0]['model'],"JOIN_RENDEZVOUS_MAPPING")
    audit_bindings(netlist,record,dict(module=selected["ca_child_join"]["type"],variant=variant,aliases=[],
        verify_roots=[rname],expected_bindings={rname:("ChiselAsyncAsymmetricC_v1",shape)},
        physical_prefix='soc/'+'/'.join(path.split('.')[1:])+'/ca_child_join/'))
    children={s:plans[s]["prefix"].split("/")[-2] for s in ("left","right")}
    require(set(join["cells"])==set(children.values())|{rname},"JOIN_CHILD_INVENTORY")
    require(selected[sink_name]['type']==plans['update']['module'] and
            all(join['cells'][children[s]]['type']==plans[s]['module'] for s in children),"JOIN_RESOLVED_CHILD_BINDING")
    rc=join["cells"][rname]["connections"]
    require(rc==dict(common=[join["cells"][children[s]]["connections"]["out_req"][0] for s in ("left","right")],
        falling=["0"],rising=["1"],reset=join["ports"]["reset"]["bits"],q=join["ports"]["out_req"]["bits"]),"JOIN_RENDEZVOUS_WIRING")
    for side,child in children.items():
        conn=join["cells"][child]["connections"]
        for pin in conn:
            outer=(side+pin[2:] if pin.startswith("in_") else "out_bits_"+side+pin[8:] if pin.startswith("out_bits") else
                   "out_ack" if pin=="out_ack" else "reset" if pin=="reset" else None)
            if outer is not None:require(conn[pin]==join["ports"][outer]["bits"],"JOIN_OPERAND_WIRING")
    jc,uc=[selected[n]["connections"] for n in ("ca_child_join",sink_name)]
    input_bindings=bind_inputs(parent,selected['ca_child_join'],selected[sink_name],config['operand_fields'],config['side_inputs'],ack_guard)
    internal={b for pin in jc if pin.startswith('out_') for b in jc[pin]}
    require(jc["reset"]==uc["reset"],"JOIN_RESET_WIRING")
    # The retained Join output must have exactly the consumers in this slice.
    require(not any(b in internal for name,c in parent["cells"].items() if name not in selected
                    for bs in c["connections"].values() for b in bs),"JOIN_EXTERNAL_INTERNAL_LOAD")
    require(not any(b in internal for p in parent["ports"].values() for b in p["bits"]),"JOIN_EXPORTED_INTERNAL_NET")
    ports={}
    for label,body,conn in (("join",join,jc),("update",update,uc)):
        for pin,p in body["ports"].items():
            if label=="join" and pin.startswith("out_") or label=="update" and (pin.startswith("in_") and pin not in config['side_inputs'] or pin=="reset"):continue
            name="reset" if pin=="reset" else label+"_"+pin
            ports[name]=dict(direction=p["direction"],bits=conn[pin])
    body=dict(attributes={},ports=ports,cells=selected,netnames={})
    # Zero-load observation alias only; no new receiver or physical cell.
    ports['probe_update_ack']=dict(direction='output',bits=uc['in_ack'])
    # Retain every reachable module verbatim, not a reconstructed adapter model.
    modules={TOP:body}
    def visit(kind):
        if kind in modules:return
        modules[kind]=deepcopy(netlist["modules"][kind])
        for c in modules[kind]["cells"].values():visit(c["type"])
    for c in selected.values():visit(c["type"])
    return dict(modules=modules),dict(variant=variant,module=TOP,stages=plans,join_module=selected["ca_child_join"]["type"],
        parent_module=kind,parent_instance=path,target=target,input_bindings=input_bindings,
        uncomposed_side_input_bits=sum(b['width'] for b in input_bindings if b['kind']=='uncomposed-side-source'),
        whole_stage_setup_established=False,rendezvous="ca_child_join/"+rname+"/",
        acknowledge_guard=guard_name if ack_guard else None)


def identity_storage(body):
    payload=body['cells']['ca_primitive_payload']['connections'];data=body['cells']['ca_primitive_data_delay']['connections']
    require(len(set(payload['q']))==len(payload['q']) and payload['d']==data['q'],'JOIN_IDENTITY_CAPTURE')
    q_index={bit:i for i,bit in enumerate(payload['q'])};seen=[]
    for name,port in body['ports'].items():
        if name=='in_bits' or name.startswith('in_bits_'):
            output=body['ports']['out_'+name[3:]]['bits']
            require(len(port['bits'])==len(output),'JOIN_IDENTITY_WIDTH')
            for bit,q in zip(port['bits'],output):
                require(q in q_index and data['a'][q_index[q]]==bit,'JOIN_IDENTITY_DATA')
                seen.append(q)
    require(len(seen)==len(q_index) and set(seen)==set(q_index),'JOIN_IDENTITY_COVERAGE')


def emit_slice(netlist, output, yosys, pdk):
    write_json(output/"slice.json",netlist)
    def filename(p):
        v=yosys.path(p);require(not any(c in v for c in '\r\n"\\'),"JOIN_YOSYS_FILENAME")
        return '"'+v+'"'
    script=output/"slice.ys"
    script.write_text('read_json '+filename(output/"slice.json")+'\nhierarchy -check -top '+TOP+'\n'+
        'write_verilog -noattr -norename '+filename(output/"slice.v")+'\ndesign -reset\nread_liberty -lib '+
        filename(pdk/(SC+"tt_025C_3v30.lib"))+'\nread_verilog '+filename(output/"slice.v")+
        '\nhierarchy -check -top '+TOP+'\nwrite_json '+filename(output/"slice-roundtrip.json")+'\n',newline="\n")
    with (output/"slice.log").open("w") as stream:
        subprocess.run(yosys.command(["-s",yosys.path(script)],timeout=110),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
    require(connectivity(netlist)==connectivity(json.loads((output/"slice-roundtrip.json").read_text())),"JOIN_SLICE_ROUNDTRIP")


def flat_cells(netlist, kind=TOP):
    """Exact physical pins/nets for reachability and reviewed feedback cuts."""
    cells=[]
    def descend(kind,path,connections):
        body=netlist["modules"][kind]
        if kind.startswith(SC):
            cells.append(dict(path=path,cell=kind,pins={k:v[0] for k,v in connections.items()},
                              directions={k:v["direction"] for k,v in body["ports"].items()}));return
        local={"0":"0","1":"1"}
        for pin,bs in connections.items():
            for b,n in zip(body["ports"][pin]["bits"],bs):
                require(b not in local or local[b]==n,"JOIN_FLAT_ALIAS");local[b]=n
        for name,c in body["cells"].items():
            mapped={}
            for p,bs in c["connections"].items():
                mapped[p]=[local.setdefault(b,path+":"+str(b)) for b in bs]
            descend(c["type"],path+"/"+name if path else name,mapped)
    descend(kind,"",{k:["port:"+str(b) for b in p["bits"]] for k,p in netlist["modules"][kind]["ports"].items()})
    return cells


def state(plan, cells, side, phase, *, transparent=False):
    cases=[("port","reset",0),("port","update_out_ack",phase)]
    cuts=[]
    for name,p in plan["stages"].items():
        prefix=p["prefix"]
        local=relative.conditions(p["native"],phase)
        cases += [("pin",prefix+pin,value) for kind,pin,value in local["cases"] if kind=="pin"]
        # Initial admission only: downstream has not acknowledged this operand.
        # Preserve the receiving boundary condition of the canonical template;
        # otherwise STA treats later ACK feedback as a second first-close path.
        if name!='update':
            ack=p['native']['ports']['out_ack']
            receivers=[(c['path'],pin) for c in p['native']['cells'] for pin,node in c['pins'].items()
                       if node==ack and pin not in ('Q','Z','ZN')]
            require(receivers,"JOIN_ACK_RECEIVERS")
            cases += [('pin',prefix+cell+'/'+pin,phase) for cell,pin in receivers]
        cuts += [prefix+c for c in local["keeper_cuts"]]
    other="right" if side=="left" else "left"
    p=plan["stages"][other]
    cases.append(("pin",p["prefix"]+relative.driver(p["native"],"output_delay" if plan["variant"]=="bd" else "output_guard"),1-phase))
    keeper=[c for c in cells if c["path"].startswith(plan["rendezvous"]) and c["cell"]==SC+"aoi21_1"]
    require(len(keeper)==1,"JOIN_KEEPER_COUNT")
    cuts.append(keeper[0]["path"]);cases.append(("pin",keeper[0]["path"]+"/A1",phase))
    if transparent:
        require(plan["variant"]=="bd","JOIN_TRANSPARENT_VARIANT")
        for lane in plan["stages"][side]["lane_map"]:
            cases.append(("pin",plan["stages"][side]["prefix"]+lane["capture"],1))
    return dict(cases=cases,keeper_cuts=cuts)


def reachable_from(cells, reached, destination):
    pins={c["path"]+"/"+p:n for c in cells for p,n in c["pins"].items()}
    reached=set(reached)
    # Independent of STA availability: a missing query is never called static.
    changed=True
    while changed:
        before=len(reached)
        for c in cells:
            if c["cell"].endswith(("latrnq_1","dffrnq_1")):continue
            if any(n in reached for p,n in c["pins"].items() if c["directions"][p]=="input"):
                reached.update(n for p,n in c["pins"].items() if c["directions"][p]=="output")
        changed=len(reached)!=before
    return [l["lane"] for l in destination["lane_map"] if pins[destination["prefix"]+l["D"]] in reached]


def reachable_lanes(cells, source, destination):
    pins={c["path"]+"/"+p:n for c in cells for p,n in c["pins"].items()}
    return reachable_from(cells,{pins[source["prefix"]+l["Q"]] for l in source["lane_map"]},destination)


def side_reachability(sliced,plan,cells):
    result=[]
    for entry in plan['input_bindings']:
        if entry['kind']!='uncomposed-side-source':continue
        pin='update_'+entry['destination'];bits=sliced['modules'][TOP]['ports'][pin]['bits']
        result.append(dict(input=pin,width=len(bits),destination_lanes=reachable_from(
            cells,{'port:'+str(b) for b in bits},plan['stages']['update']),
            obligation='Uncomposed launch and hold; symbolic input must already be stable.'))
    return result


def contexts(plan,cells):
    result=[];dest=plan["stages"]["update"]
    reach={side:reachable_lanes(cells,plan['stages'][side],dest) for side in ('left','right')}
    dynamic={l['lane'] for l in dest['lane_map'] if str(l['lane']) not in dest['constant_lanes']}
    require(set(reach['left'])|set(reach['right'])==dynamic,"JOIN_DYNAMIC_LANE_COVERAGE")
    for side in ("left","right"):
        src=plan["stages"][side];reachable=reach[side]
        def queries(stage,role,pin,modes,edges,lanes=None):
            return [dict(id=f"{role}:{l['lane']}:{m}:{e}",role=role,lane=l["lane"],mode=m,source_edge="any",sink_edge=e,
                         sink_kind="pin",sink=stage["prefix"]+l[pin])
                    for l in stage["lane_map"] if lanes is None or l["lane"] in lanes for m in modes for e in edges]
        inputs=["join_"+side+name[2:] for name in next(c for c in src["contexts"] if c["id"]=="data")["sources"]]
        result.append(dict(id=side+"-input",kind="input",side=side,phase=0,state=state(plan,cells,side,0),
            sources=inputs,source_kind="port",queries=queries(src,"input","D",["max"],["rise","fall"])))
        for phase in ([0] if plan["variant"]=="bd" else [0,1]):
            qs=queries(src,"source_capture","capture",["min","max"],["fall" if plan["variant"]=="bd" else "rise"])
            if plan["variant"]=="bd":qs+=queries(dest,"capture","capture",["min","max"],["fall"])
            if plan['variant']=='bd':
                qs += [dict(id=f'return:{m}',role='return',mode=m,source_edge='rise',sink_edge='rise',sink_kind='port',
                            sink='probe_update_ack') for m in ('min','max')]
            for q in qs:q["source_edge"]="rise" if phase==0 else "fall"
            result.append(dict(id=f"{side}-request-{phase}",kind="request",side=side,phase=phase,state=state(plan,cells,side,phase),
                sources=["join_"+side+"_req"],source_kind="port",queries=qs))
            qs=queries(dest,"data","D",["max"],["rise","fall"],reachable)
            if plan["variant"]=="click":qs+=queries(dest,"capture","capture",["min","max"],["rise"])
            sources=([src["prefix"]+l["Q"] for l in src["lane_map"]] if plan["variant"]=="bd" else [src["prefix"]+src["event"]])
            result.append(dict(id=f"{side}-launch-{phase}",kind="launch",side=side,phase=phase,
                state=state(plan,cells,side,phase,transparent=plan["variant"]=="bd"),sources=sources,source_kind="clock",queries=qs,
                reachable_lanes=reachable,absent_lanes=sorted(set(range(dest['payload_width']))-set(reachable))))
    return result


def bind_leaf_plan(plan, index, cuts):
    """Resolve identities on the original graph; measure the full live graph."""
    prefix='soc/'+'/'.join(plan['parent_instance'].split('.')[1:])+'/'
    plan=deepcopy(plan)
    for p in plan['stages'].values():p['prefix']=prefix+p['prefix']
    plan['rendezvous']=prefix+plan['rendezvous']
    cells=[dict(path=p,cell=c['type'],pins={k:v[0] for k,v in c['connections'].items()},directions=c['directions'])
           for p,c in index.after['cells'].items() if all(len(v)==1 for v in c['connections'].values())]
    generated=contexts(plan,cells)
    drivers=defaultdict(list)
    for path,cell in index.after['cells'].items():
        for pin,ns in cell['connections'].items():
            if cell['directions'][pin]=='output':
                for lane,net in enumerate(ns):drivers[net].append(path+'/'+pin+(f'[{lane}]' if len(ns)>1 else ''))
    dest_path=plan['stages']['update']['prefix'][:-1]
    signals={p:index.scalar(dest_path,s) for p,s in (('reset','reset'),('update_out_ack','out_ack'))}
    for ctx in generated:
        ctx['state']['cases']=[(*signals[p],v) if k=='port' else (k,p,v) for k,p,v in ctx['state']['cases']]
        ctx['state']['keeper_cuts']=cuts
        src=plan['stages'][ctx['side']]
        path=src['prefix'][:-1]
        if ctx['kind']=='input':
            ports=sorted({re.sub(r'\[\d+\]$','',p) for p in next(c for c in src['contexts'] if c['id']=='data')['sources']})
            lanes=[row for p in ports for row in index.boundary(path,p)]
            require(all(row['kind']=='pin' for row in lanes),'JOIN_LEAF_INPUT_SOURCE')
            ctx['sources']=sorted({row['source'] for row in lanes})
            ctx['input_lanes']=lanes
        elif ctx['kind']=='request':
            kind,pin=index.scalar(path,'in_req');require(kind=='pin','JOIN_LEAF_REQUEST_SOURCE')
            ctx['sources']=[pin]
        ctx['source_kind']='clock'
        qs=[]
        for q in ctx['queries']:
            if q['role']!='return':qs.append(q);continue
            rows=index.boundary(path,'out_ack')
            require(len(rows)==1 and rows[0]['kind']=='pin','JOIN_LEAF_RETURN_SOURCE')
            # Receiver case analysis proves initial admission but removes its
            # timing arrival. Observe its actual loaded driver instead. This
            # zero-wire-RC campaign does not bound receiver wire propagation.
            conditioned={p for k,p,v in ctx['state']['cases'] if k=='pin'}
            for i,p in enumerate(rows[0]['consumers']):
                require(p in conditioned,'JOIN_RETURN_RECEIVER_CONDITION')
                actual=drivers[index.live_net('pin',p)]
                require(len(actual)==1,'JOIN_RETURN_DRIVER_COUNT')
                qs.append(dict(q,id=q['id'].replace('return:',f'return:{i}:'),sink=actual[0],sink_kind='pin',
                               receiver=p,measurement='conditioned-receiver-driver-arrival'))
        ctx['queries']=qs
    plan.update(module='RiscayMcuDigital',leaf_anchored=True,contexts=generated,
                physical_prefix=prefix,keeper_cuts=cuts,wire_rc_scope='zero; receiver wire delay unmeasured')
    return plan


def script(netlist,corner,slew,plan,ctx,*,sta,period=1000,dq=None,sdf=None):
    b=relative.brace
    leaf=plan.get('leaf_anchored',False)
    if leaf:
        require(plan['wire_rc_scope']=='zero; receiver wire delay unmeasured','JOIN_LEAF_WIRE_RC_MODE')
        if sdf:validate_leaf_sdf(sdf.read_text())
        values=ctx.get('root_slew_ns',dict(min=slew,max=slew))
        ctx['expected_root_slews']={(i,m,e):(dq[str(plan['stages'][ctx['side']]['lane_map'][i]['lane'])][e]['slew_ns']
            if plan['variant']=='bd' and ctx['kind']=='launch' else values[m])
            for i in range(len(ctx['sources'])) for m in ('min','max') for e in ('rise','fall')}
    text='read_liberty '+b(sta.path(ROOT/".tools/physical/pdk"/(SC+corner+".lib")))+'\n'+relative.PROBE.read_text()+'\n'+JOIN_PROBE+'\n'
    if leaf:
        from native_leaf_timing import SRAM, SLEW_TCL
        text+='read_liberty '+b(sta.path(ROOT/'.tools/gf180-sram'/(SRAM+'__tt_025C_3v30.lib')))+'\n'+SLEW_TCL+'\n'
    text+='read_verilog '+b(sta.path(netlist))+'\nlink_design '+plan.get('module',TOP)+'\n'
    text+=f'set_input_transition {slew} [all_inputs]\nset_load 0.05 [all_outputs]\nset_max_transition 2 [current_design]\n'
    if not leaf:text+='set_load 0 [exact_object port probe_update_ack]\n'
    for kind,pin,value in ctx["state"]["cases"]:text+=f'set_case_analysis {value} [exact_object {kind} {b(pin)}]\n'
    for cell in ctx["state"]["keeper_cuts"]:text+='set_disable_timing -from A1 -to ZN [get_cells '+b(cell)+']\n'
    if sdf:text+='read_sdf '+b(sta.path(sdf))+'\n'
    text+='set sources {}; foreach name [list '+" ".join(map(b,ctx["sources"]))+'] {lappend sources [exact_object '+('pin' if ctx['source_kind']=='clock' else 'port')+' $name]}\n'
    if ctx["source_kind"]=="clock":
        # Fixed event offsets avoid subtracting a period/2 floating-point epoch
        # from falling-data paths. Neither offset is used as a timing budget.
        text+=f'create_clock -name event -period {period} -waveform {{0 1}} $sources\nset_propagated_clock [all_clocks]\n'
        if plan["variant"]=="bd" and ctx['kind']=='launch':
            require(dq is not None,"JOIN_DQ_SLEW_REQUIRED")
            text+='sta::find_delays\n'
            for lane in plan["stages"][ctx["side"]]["lane_map"]:
                pin=plan["stages"][ctx["side"]]["prefix"]+lane["Q"]
                for edge in ("rise","fall"):
                    value=dq[str(lane["lane"])][edge]["slew_ns"]
                    text+='set vertices [[exact_object pin '+b(pin)+'] vertices]\nif {![llength $vertices]} {error JOIN_SLEW_VERTEX}\n'
                    text+='foreach vertex $vertices {foreach mode {min max} {sta::set_annotated_slew $vertex [sta::cmd_corner] $mode '+edge+' [sta::time_ui_sta '+str(value)+']}}\n'
        elif leaf:
            values=ctx.get('root_slew_ns',dict(min=slew,max=slew))
            require(ctx['kind']!='launch' or 'root_slew_ns' in ctx,'JOIN_LEAF_EVENT_SLEW_REQUIRED')
            text+='sta::find_delays\n'
            for mode in ('min','max'):
                text+='foreach pin $sources {foreach vertex [$pin vertices] {foreach edge {rise fall} {sta::set_annotated_slew $vertex [sta::cmd_corner] '+mode+' $edge [sta::time_ui_sta '+str(values[mode])+']}}}\n'
        text+='set sources [get_clocks event]\n'
    text+='row JOIN_BEGIN\nset targets {}\n'
    for kind,pin in sorted({(q['sink_kind'],q['sink']) for q in ctx['queries'] if not (leaf and q['role']=='return')}):text+='lappend targets [exact_object '+kind+' '+b(pin)+']\n'
    text+='set_max_delay 100000 -from $sources -to $targets\nset_min_delay 0 -from $sources -to $targets\n'
    batches=defaultdict(list)
    for q in ctx['queries']:
        if leaf and q['role']=='return':
            text+='leaf_ack '+' '.join(map(b,[q['id'],q['mode'],q['sink_edge'],ctx['sources'][0],'','',q['sink']]))+'\n'
        else:batches[(q['mode'],q['source_edge'],q['sink_edge'],q['sink_kind'])].append(q)
    for (mode,se,te,kind),qs in batches.items():
        text+='join_batch '+mode+' '+se+' '+te+' $sources '+kind+' [list '+" ".join(b(q[k]) for q in qs for k in ('id','sink'))+']\n'
    if plan["variant"]=="bd" and ctx["kind"]=="input":
        src=plan["stages"][ctx["side"]]
        for lane in src["lane_map"]:
            text+=f'row JOIN_DQ_BEGIN {lane["lane"]} '+b(src['prefix']+lane['D'])+' '+b(src['prefix']+lane['Q'])+'\n'
            text+='set d [exact_object pin '+b(src['prefix']+lane['D'])+']\nrow JOIN_DQ_INPUT_SLEW [join_slew $d rise] [join_slew $d fall]\n'
            text+='report_dcalc -from '+b(src["prefix"]+lane["D"])+' -to '+b(src["prefix"]+lane["Q"])+' -max -digits 9\nrow JOIN_DQ_END\n'
    slew_sources=(ctx['sources'] if ctx['kind']=='launch' else
                  [plan['stages'][ctx['side']]['prefix']+plan['stages'][ctx['side']]['event']] if ctx['kind']=='request' and plan['variant']=='click' else [])
    for i,pin in enumerate(slew_sources):
        text+='set p [exact_object pin '+b(pin)+']\nrow JOIN_SOURCE_SLEW '+str(i)+' [join_slew $p rise] [join_slew $p fall]\n'
    if plan['variant']=='click' and ctx['kind'] in ('request','launch'):
        text+='row JOIN_EVENT_SLEW [join_slew $p rise min] [join_slew $p rise max]\n'
    if leaf:
        for i,pin in enumerate(ctx['sources']):
            text+='set p [exact_object pin '+b(pin)+']\n'
            for mode in ('min','max'):
                for edge in ('rise','fall'):text+=f'row JOIN_ROOT_SLEW {i} {mode} {edge} [leaf_slew $p {edge} {mode}]\n'
    text+='row JOIN_ELECTRICAL_BEGIN\nreport_check_types -max_slew -max_capacitance -violators -digits 6\nrow JOIN_ELECTRICAL_END\nrow JOIN_COMPLETE\nexit\n'
    return text


def validate_leaf_sdf(text):
    # Driver-only return observations cannot accept a wire annotation. Keep
    # faults limited to explicit cell arcs, as in the actual-arc campaigns.
    forms=set(re.findall(r'\(\s*([A-Za-z_][A-Za-z_0-9]*)',text))
    require(forms<={'DELAYFILE','SDFVERSION','DESIGN','DIVIDER','TIMESCALE','CELL','CELLTYPE',
                    'INSTANCE','DELAY','ABSOLUTE','IOPATH'},'JOIN_LEAF_SDF_WIRE_OR_UNSUPPORTED')


def validate_leaf_paths(paths,plan,ctx,cells):
    require(cells is not None,'JOIN_LEAF_PHYSICAL_CELLS_REQUIRED')
    src=plan['stages'][ctx['side']]
    allowed=({src['prefix']+l['Q'] for l in src['lane_map']}|{src['prefix']+src['phase']['Q']['pin']}
             if plan['variant']=='click' and ctx['kind']=='launch' else set())
    for points in paths.values():
        for i,pin in enumerate(points):
            path,port=pin.rsplit('/',1)
            require(path in cells and port in cells[path]['connections'],'JOIN_LEAF_PATH_PIN')
            if i and port in ('Q','QN') and cells[path]['type'].startswith((SC+'dff',SC+'lat')):
                require(pin in allowed,'JOIN_LEAF_INTERMEDIATE_STORAGE')


def parse(log,plan,ctx,*,cells=None):
    require(log.count('JOIN_BEGIN\n')==log.count('JOIN_COMPLETE\n')==1,"JOIN_INCOMPLETE")
    require(not re.search(r'(?mi)^(?:Error:|ERROR|Warning:)',log),"JOIN_TOOL_DIAGNOSTIC")
    expected={q['id']:q for q in ctx['queries']};rows={};paths={};slews={};event_slews=None;src=plan['stages'][ctx['side']]
    source_q={src['prefix']+l['Q']:src['prefix']+l['capture'] for l in src['lane_map']}
    phase_q=src['prefix']+src['phase']['Q']['pin'] if plan['variant']=='click' else None
    root_slews={}
    for line in log.splitlines():
        f=line.split('\t')
        if f[0] in ('CONTROL_PATH','LEAF_ACK_PATH'):
            require(len(f)==11 and f[1] in expected and f[1] not in rows,"JOIN_QUERY_ROW")
            q=expected[f[1]];start_arrival,arrival,data,delay,slew=map(float,f[2:7]);start,end,se,te=f[7:]
            require((f[0]=='LEAF_ACK_PATH')==(plan.get('leaf_anchored',False) and q['role']=='return'),'JOIN_RETURN_MEASUREMENT')
            require(all(math.isfinite(v) and v>=0 for v in (start_arrival,arrival,data,delay,slew)) and
                    abs(arrival-start_arrival-delay)<1e-5,"JOIN_NUMERIC")
            require(end==q['sink'] and te==q['sink_edge'] and se in ('rise','fall') and
                    (q['source_edge']=='any' or se==q['source_edge']),"JOIN_PATH_BINDING")
            sequential=ctx['kind']=='launch' and plan['variant']=='click'
            if sequential:
                require(start in (source_q if q['role']=='data' else {phase_q}) and abs(data-arrival)<1e-5,"JOIN_SEQUENTIAL_SOURCE")
                if q['role']=='capture':require(se==('rise' if ctx['phase']==0 else 'fall'),"JOIN_PHASE_TRANSITION")
                measured=arrival
            else:
                require(start in ctx['sources'] and abs(data-delay)<1e-4,"JOIN_COMBINATIONAL_SOURCE")
                if ctx['source_kind']=='port':require(abs(start_arrival)<1e-6,"JOIN_INPUT_ARRIVAL")
                measured=delay
            rows[f[1]]=dict(delay_ns=measured,start=start,end=end,max_slew_ns=slew)
        elif f[0] in ('CONTROL_POINTS','LEAF_ACK_POINTS'):
            require(f[1] in rows and f[1] not in paths,"JOIN_POINTS_ID");paths[f[1]]=f[2:]
            require((f[0]=='LEAF_ACK_POINTS')==(plan.get('leaf_anchored',False) and expected[f[1]]['role']=='return'),'JOIN_RETURN_POINTS')
        elif f[0]=='JOIN_SOURCE_SLEW':
            require(len(f)==4 and f[1] not in slews,"JOIN_SOURCE_SLEW_ROW")
            values=list(map(float,f[2:]));require(all(math.isfinite(v) and v>=0 for v in values),"JOIN_SOURCE_SLEW_MISSING")
            slews[f[1]]=values
        elif f[0]=='JOIN_EVENT_SLEW':
            require(event_slews is None and len(f)==3,"JOIN_EVENT_SLEW_ROW")
            event_slews=list(map(float,f[1:]));require(all(math.isfinite(v) and v>=0 for v in event_slews) and
                event_slews[0]<=event_slews[1],"JOIN_EVENT_SLEW_NUMERIC")
        elif f[0]=='JOIN_ROOT_SLEW':
            require(plan.get('leaf_anchored') and len(f)==5,'JOIN_ROOT_SLEW_ROW')
            key=(int(f[1]),f[2],f[3]);value=float(f[4])
            require(key not in root_slews and key in ctx['expected_root_slews'] and math.isfinite(value) and
                    abs(value-ctx['expected_root_slews'][key])<1e-5,'JOIN_ROOT_SLEW_CHANGED')
            root_slews[key]=value
    if plan.get('leaf_anchored'):require(root_slews.keys()==ctx['expected_root_slews'].keys(),'JOIN_ROOT_SLEW_COVERAGE')
    require(set(rows)==set(paths)==set(expected),"JOIN_QUERY_COVERAGE")
    if plan.get('leaf_anchored'):validate_leaf_paths(paths,plan,ctx,cells)
    for key,points in paths.items():
        q=expected[key];row=rows[key]
        sequential=ctx['kind']=='launch' and plan['variant']=='click'
        require(points[0]==(ctx['sources'][0] if sequential else row['start']) and points[-1]==q['sink'],"JOIN_POINTS_BINDING")
        if sequential:
            cap=source_q[row['start']] if q['role']=='data' else src['prefix']+src['phase']['CLK']['pin']
            require(points.count(cap)==points.count(row['start'])==1 and points.index(cap)+1==points.index(row['start']),"JOIN_CLK_Q_PROVENANCE")
        if q['role']=='source_capture':
            owners=('request_delay','a','long_hold') if plan['variant']=='bd' else ('request_delay','input_compare','fire')
            ordered=[src['prefix']+relative.driver(src['native'],owner) for owner in owners]
            require(all(points.count(pin)==1 for pin in ordered) and [points.index(pin) for pin in ordered]==sorted(points.index(pin) for pin in ordered),"JOIN_SOURCE_CONTROL_PROVENANCE")
        if q['role'] in ('capture','return'):
            # Both variants must cross the actual rendezvous and update controller.
            require(any(pin.startswith(plan['rendezvous']) for pin in points),"JOIN_RENDEZVOUS_PROVENANCE")
            dest=plan['stages']['update']
            owners=('request_delay','a','long_hold') if plan['variant']=='bd' else ('request_delay','input_compare','fire')
            ordered=[dest['prefix']+relative.driver(dest['native'],owner) for owner in owners]
            require(all(points.count(pin)==1 for pin in ordered) and [points.index(pin) for pin in ordered]==sorted(points.index(pin) for pin in ordered),"JOIN_UPDATE_PROVENANCE")
        if q['role']=='return' and plan.get('leaf_anchored') and plan.get('acknowledge_guard'):
            guard=plan['physical_prefix']+plan['acknowledge_guard']+'/'
            require(any(p.startswith(guard) for p in points),'JOIN_ACK_GUARD_PROVENANCE')
    count=len(ctx['sources']) if ctx['kind']=='launch' else 1 if ctx['kind']=='request' and plan['variant']=='click' else 0
    require(set(slews)=={str(i) for i in range(count)},"JOIN_SLEW_COVERAGE")
    require((event_slews is not None)==(plan['variant']=='click' and ctx['kind'] in ('request','launch')),"JOIN_EVENT_SLEW_COVERAGE")
    for q in ctx['queries']:
        if q['mode']=='min':
            hi=dict(q,mode='max');hi['id']=q['id'].replace(':min',':max')
            require(hi['id'] in rows and rows[q['id']]['delay_ns']<=rows[hi['id']]['delay_ns']+1e-6,"JOIN_REVERSED_BOUNDS")
    dq={}
    if plan['variant']=='bd' and ctx['kind']=='input':
        blocks=re.findall(r'JOIN_DQ_BEGIN\t(\d+)\t([^\n]+)\n(.*?)JOIN_DQ_END\n',log,re.S)
        for lane,pins,block in blocks:
            require(lane not in dq,"JOIN_DQ_DUPLICATE")
            selected=[l for l in src['lane_map'] if str(l['lane'])==lane]
            require(len(selected)==1 and pins.split('\t')==[src['prefix']+selected[0][k] for k in ('D','Q')],"JOIN_DQ_PAIRING")
            input_slew=re.findall(r'JOIN_DQ_INPUT_SLEW\t([^\n]+)',block)
            require(len(input_slew)==1 and len(input_slew[0].split('\t'))==2,"JOIN_DQ_INPUT_SLEW")
            input_slew=list(map(float,input_slew[0].split('\t')))
            sections=re.findall(r'D ([\^v]) -> Q ([\^v])\n(.*?)(?=D [\^v] -> Q|\Z)',block,re.S)
            require(len(sections)==2 and [(a,b) for a,b,_ in sections]==[('^','^'),('v','v')] and 'Arc type: Latch D to Q' in block,"JOIN_DQ_ARC")
            dq[lane]={}
            for index,(a,_,section) in enumerate(sections):
                values={}
                transitions=re.findall(r'input_net_transition = ([0-9.eE+-]+)',section)
                caps=re.findall(r'total_output_net_capacitance = ([0-9.eE+-]+)',section)
                require(len(transitions)==len(caps)==2 and all(abs(float(v)-input_slew[index])<1e-6 for v in transitions),"JOIN_DQ_INPUT_SLEW_CHANGED")
                require(all(math.isfinite(float(v)) and float(v)>=0 for v in caps) and caps[0]==caps[1],"JOIN_DQ_LOAD")
                values.update(input_slew_ns=input_slew[index],load_pf=float(caps[0]))
                for label in ('Delay','Slew'):
                    matches=re.findall(r'^'+label+r' = ([0-9.eE+-]+)$',section,re.M)
                    require(len(matches)==1,"JOIN_DQ_VALUE");value=float(matches[0])
                    require(math.isfinite(value) and value>=0,"JOIN_DQ_NUMERIC");values[label.lower()+'_ns']=value
                dq[lane]['rise' if a=='^' else 'fall']=values
        require(set(dq)=={str(l['lane']) for l in src['lane_map']},"JOIN_DQ_COVERAGE")
    require(log.count('JOIN_ELECTRICAL_BEGIN\n')==log.count('JOIN_ELECTRICAL_END\n')==1,"JOIN_ELECTRICAL_COVERAGE")
    electrical=log.split('JOIN_ELECTRICAL_BEGIN\n')[1].split('JOIN_ELECTRICAL_END\n')[0]
    return dict(rows=rows,paths=paths,dq=dq,source_slews=slews,event_slews=event_slews,electrical_violation_rows=electrical.count('(VIOLATED)'))


def margins(results,plan,aperture):
    summaries=[]
    for side in ('left','right'):
        inp=results[side+'-input'];src=plan['stages'][side]
        for phase in ([0] if plan['variant']=='bd' else [0,1]):
            req=results[f'{side}-request-{phase}']['rows'];launch=results[f'{side}-launch-{phase}']['rows']
            launch_slews=results[f'{side}-launch-{phase}']['source_slews']
            if plan['variant']=='bd':
                for i,lane in enumerate(src['lane_map']):
                    measured=[inp['dq'][str(lane['lane'])][edge]['slew_ns'] for edge in ('rise','fall')]
                    require(all(abs(a-b)<1e-6 for a,b in zip(launch_slews[str(i)],measured)),"JOIN_DQ_SLEW_CHANGED")
            else:
                a=results[f'{side}-launch-{phase}']['event_slews'];b=results[f'{side}-request-{phase}']['event_slews']
                require(all(abs(x-y)<1e-5 for x,y in zip(a,b)),"JOIN_EVENT_SLEW_CHANGED")
            capture_edge='fall' if plan['variant']=='bd' else 'rise'
            leads=[]
            for lane in src['lane_map']:
                n=lane['lane'];close=req[f'source_capture:{n}:min:{capture_edge}']['delay_ns']
                for edge in ('rise','fall'):
                    data=inp['rows'][f'input:{n}:max:{edge}']['delay_ns']
                    leads.append(close-data-aperture['setup_ns'])
                    if plan['variant']=='bd':leads.append(close-data-inp['dq'][str(n)][edge]['delay_ns'])
            if plan['variant']=='bd':
                latest=max(v['delay_ns'] for k,v in req.items() if k.startswith('source_capture:') and ':max:' in k)
                captures=req
            else:latest=0;captures=launch
            slacks=[]
            for q in next(c for c in plan['contexts'] if c['id']==f'{side}-launch-{phase}')['queries']:
                if q['role']!='data':continue
                capture=captures[f"capture:{q['lane']}:min:{capture_edge}"]['delay_ns']
                slacks.append(capture-latest-launch[q['id']]['delay_ns']-aperture['setup_ns'])
            summaries.append(dict(side=side,phase=phase,maximum_input_data_lag_ns=min(leads),
                minimum_conditional_setup_margin_ns=min(slacks),source_q_bound_ns=latest,
                return_after_source_close_ns=min(v['delay_ns'] for k,v in req.items() if k.startswith('return:') and k.endswith(':min'))-latest if plan['variant']=='bd' else None,
                checked_data_transitions=len(slacks),physical_qualification=False))
    return summaries


def run(mapping,output,variant,campaign=False,*,target="control"):
    require(not output.exists(),"JOIN_OUTPUT_EXISTS")
    from repair_gf180_design import validate_receipt
    receipt=validate_receipt(mapping)
    record=json.loads((mapping/'mapping.json').read_text());netlist=json.loads((mapping/'netlist.json').read_text())
    audit=json.loads((mapping/'netlist-audit.json').read_text());policy=json.loads((mapping/'physical-policy.json').read_text())
    require(record['variant']==variant and audit['status']=='pass' and audit['netlist_sha256']==sha(mapping/'netlist.v') and
            audit['mapping_sha256']==sha(mapping/'mapping.json'),"JOIN_STALE_AUDIT")
    require(record['physical_policy_sha256']==sha(mapping/'physical-policy.json') and policy['contract_sha256']==sha(mapping/'timing-intent.json'),"JOIN_STALE_CONTRACT")
    manifest=json.loads((mapping/'timing-intent.json').read_text())['manifest']
    import native_leaf_timing as leaf
    original=stages.receipt_original(mapping,receipt)
    proof=stages.receipt_proof(mapping,receipt)
    index=leaf.LeafIndex(original,netlist,proof['added_buffers'],proof['added_ties'])
    cuts=leaf.keeper_cuts(index,audit)
    sliced,plan=bound_slice(original,record,manifest,variant,target=target);cells=flat_cells(sliced)
    plan['side_input_reachability']=side_reachability(sliced,plan,cells)
    plan=bind_leaf_plan(plan,index,cuts)
    sta=tool('sta');yosys=tool('yosys');pdk=ROOT/'.tools/physical/pdk';pdk_verify(pdk)
    files=[mapping/f for f in ('mapping.json','netlist.json','netlist.v','netlist-audit.json','timing-intent.json','physical-policy.json')]
    files += [mapping/'electrical-repair/receipt.json',mapping/'electrical-repair/reference/netlist.json',
              mapping/'electrical-repair/proof.json',ROOT/'tools/repair_gf180_design.py']
    files += [ROOT/'tools'/f for f in ('control_join_timing.py','native_leaf_timing.py','native_stage_timing.py','control_relative_timing.py',
        'characterize_gf180_control_native.py','screen_gf180_control_repair.py','repair_gf180_control.py',
        'gf180_physical.py','gf180_implement.py','gf180_estimate.py','characterize_gf180_liberty.py')]
    files += [relative.PROBE]+sta.input_files()+yosys.input_files()+[pdk/(SC+c+'.lib') for c in relative.CORNERS]
    files += [ROOT/'.tools/gf180-sram'/(leaf.SRAM+'__tt_025C_3v30.lib')]
    run_receipt=RunReceipt(output/'receipt.json',inputs=files,tools=[ROOT/'tools/run_receipt.py'])
    status='fail'
    try:
        output.mkdir(parents=True);stages.roundtrip(mapping,output,netlist,yosys,pdk)
        write_json(output/'plan.json',plan);cases=[]
        for corner in (relative.CORNERS if campaign else relative.CORNERS[:1]):
            aperture=relative.aperture(relative.library(pdk/(SC+corner+'.lib')),variant)
            for slew in ([0.02,2.0] if campaign else [0.2]):
                key=corner+'-s'+str(slew);results={};failure=None
                for ctx in plan['contexts']:
                    tcl=output/(key+'-'+ctx['id']+'.tcl');log=tcl.with_suffix('.log')
                    dq=results[ctx['side']+'-input']['dq'] if ctx['kind']=='launch' and variant=='bd' else None
                    if ctx['kind']=='launch' and variant=='click':
                        a,b=results[f"{ctx['side']}-request-{ctx['phase']}"]['event_slews']
                        ctx['root_slew_ns']=dict(min=a,max=b)
                    tcl.write_text(script(mapping/'netlist.v',corner,slew,plan,ctx,sta=sta,dq=dq),newline='\n')
                    with log.open('w') as stream:
                        subprocess.run(sta.command(['-no_init','-exit',sta.path(tcl)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
                    try:results[ctx['id']]=parse(log.read_text(),plan,ctx,cells=index.after['cells'])
                    except ValueError as e:failure=dict(context=ctx['id'],diagnostic=str(e));break
                summary=None if failure else margins(results,plan,aperture)
                fields=('maximum_input_data_lag_ns','minimum_conditional_setup_margin_ns','return_after_source_close_ns')
                negative=[] if failure else [dict(side=s['side'],phase=s['phase'],metric=k) for s in summary for k in fields if s[k] is not None and s[k]<0]
                case=dict(key=key,corner=corner,slew_ns=slew,status='UNRESOLVED' if failure else 'CONDITIONAL_SETUP_MEASUREMENTS',
                          negative_metrics=negative,failure=failure,summary=summary)
                write_json(output/(key+'.json'),dict(case=case,results=results,aperture=aperture))
                cases.append(case);print(json.dumps(case),flush=True)
        write_json(output/'results.json',dict(physical_qualification=False,target=target,
            uncomposed_side_input_bits=plan['uncomposed_side_input_bits'],whole_stage_setup_established=False,
            side_input_obligation='Stable throughout each measured Join launch and sink aperture; launch/hold not measured here. Symbolic boundary slew equals the case input slew.',
            cases=cases))
        require(all(c['status']!='UNRESOLVED' for c in cases),'JOIN_CAMPAIGN_UNRESOLVED')
        status='pass'
    finally:
        run_receipt.finish(outputs=[p for p in output.rglob('*') if p.is_file()],status=status)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mapping',type=Path);p.add_argument('output',type=Path);p.add_argument('--variant',choices=('bd','click'),required=True)
    p.add_argument('--campaign',action='store_true');p.add_argument('--target',choices=('control','execute'),default='control')
    a=p.parse_args();run(a.mapping,a.output,a.variant,a.campaign,target=a.target)

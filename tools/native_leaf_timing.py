# SPDX-License-Identifier: Apache-2.0
"""Physical leaf anchors for the live repaired design; never a contracted timing graph.

The original netlist supplies logical identities only. Timing uses the full live
netlist, including parent distribution and every load. A zero-phase clock on a
source Q describes a conditional boundary, not that register's launch latency.
"""
from collections import defaultdict
from copy import deepcopy
import math
import re

from repair_gf180_control import require
from repair_gf180_design import flat
from gf180_physical import SC, SRAM, ROOT


class LeafIndex:
    def __init__(self, original, live, buffers, ties=()):
        self.before = flat(original, 'RiscayMcuDigital')
        self.after = flat(live, 'RiscayMcuDigital')
        self.drivers = defaultdict(list)
        self.consumers = defaultdict(list)
        self.aliases = {}
        for path, cell in self.before['cells'].items():
            for pin, bits in cell['connections'].items():
                for lane, net in enumerate(bits):
                    label = path+'/'+pin+(f'[{lane}]' if len(bits)>1 else '')
                    (self.drivers if cell['directions'][pin]=='output' else self.consumers)[net].append(('pin',label))
        for pin, port in self.before['ports'].items():
            for lane, net in enumerate(port['bits']):
                label = pin+(f'[{lane}]' if len(port['bits'])>1 else '')
                (self.drivers if port['direction']=='input' else self.consumers)[net].append(('port',label))
        for path in buffers:
            cell=self.after['cells'][path]
            require(re.fullmatch(re.escape(SC)+r'buf_\d+',cell['type']) is not None and
                    set(cell['connections'])=={'I','Z'},'LEAF_BUFFER_SHAPE')
            a,q=[cell['connections'][p] for p in ('I','Z')]
            require(len(a)==len(q)==1 and q[0] not in self.aliases,'LEAF_BUFFER_DRIVER')
            self.aliases[q[0]]=a[0]
        for path in ties:
            cell=self.after['cells'][path]
            require(cell['type'] in (SC+'tieh',SC+'tiel'),'LEAF_TIE_SHAPE')
            pin,value=('Z','1') if cell['type']==SC+'tieh' else ('ZN','0')
            require(set(cell['connections'])=={pin} and len(cell['connections'][pin])==1,'LEAF_TIE_SHAPE')
            self.aliases[cell['connections'][pin][0]]=('constant',value)

    def normalized(self, net):
        seen=set()
        while net in self.aliases:
            require(net not in seen,'LEAF_BUFFER_CYCLE');seen.add(net);net=self.aliases[net]
        return net

    def live_net(self, kind, label):
        if kind=='port':
            match=re.fullmatch(r'(.+)\[(\d+)\]',label)
            name,lane=(match[1],int(match[2])) if match else (label,0)
            require(name in self.after['ports'],'LEAF_PORT_MISSING')
            return self.after['ports'][name]['bits'][lane]
        path,pin=label.rsplit('/',1)
        match=re.fullmatch(r'(.+)\[(\d+)\]',pin)
        name,lane=(match[1],int(match[2])) if match else (pin,0)
        require(path in self.after['cells'] and name in self.after['cells'][path]['connections'],'LEAF_PIN_MISSING')
        return self.after['cells'][path]['connections'][name][lane]

    def boundary(self, path, port):
        key=path+'/'+port
        require(key in self.before['boundaries'],'LEAF_REFERENCE_PORT')
        result=[]
        for lane,net in enumerate(self.before['boundaries'][key]):
            sinks=[(k,p) for k,p in self.consumers[net] if k=='pin' and p.startswith(path+'/')]
            # A removed logical input is admissible only if the original graph
            # has no physical consumer in this instance, including aliases.
            outputs=[p for p,ns in self.before['boundaries'].items() if p.startswith(path+'/') and
                     self.before['boundary_directions'][p]=='output' and net in ns]
            if not sinks and not outputs:
                result.append(dict(port=port,lane=lane,kind='unused',consumers=[]));continue
            if net[0]=='constant':
                require(net[1] in ('0','1'),'LEAF_UNKNOWN_CONSTANT')
                for k,p in sinks:require(self.normalized(self.live_net(k,p))==net,'LEAF_CONSTANT_CHANGED')
                result.append(dict(port=port,lane=lane,kind='constant',value=int(net[1]),consumers=[p for _,p in sinks]));continue
            drivers=self.drivers[net]
            require(len(drivers)==1,'LEAF_REFERENCE_DRIVER')
            kind,pin=drivers[0];source=self.normalized(self.live_net(kind,pin))
            for k,p in self.consumers[net]:
                require(self.normalized(self.live_net(k,p))==source,'LEAF_FANOUT_CHANGED')
            result.append(dict(port=port,lane=lane,kind=kind,source=pin,
                               consumers=[p for _,p in sinks],complete_fanout=[p for _,p in self.consumers[net]]))
        return result

    def scalar(self,path,port):
        rows=self.boundary(path,port)
        require(len(rows)==1 and rows[0]['kind'] in ('pin','port'),'LEAF_SCALAR_SOURCE')
        return rows[0]['kind'],rows[0]['source']


def keeper_cuts(index, audit):
    """Only the reviewed A1 feedback arc in protected AOI/NOR keeper pairs."""
    roots=tuple(p+'/' for p in audit['adapter_instances'].values())
    result=[]
    for path,cell in index.before['cells'].items():
        if cell['type']==SC+'aoi21_1' and path.startswith(roots):
            drivers=index.drivers[cell['connections']['A1'][0]]
            require(len(drivers)==1 and drivers[0][0]=='pin','LEAF_KEEPER_DRIVER')
            keeper,pin=drivers[0][1].rsplit('/',1)
            feedback=index.before['cells'][keeper]
            require(pin=='ZN' and keeper.rsplit('/',1)[0]==path.rsplit('/',1)[0] and
                    feedback['type']==SC+'nor2_1' and feedback['connections']['A1']==cell['connections']['ZN'],
                    'LEAF_KEEPER_FEEDBACK')
            live=index.after['cells'][path]
            live_feedback=index.after['cells'][keeper]
            require(live['type']==cell['type'] and live_feedback['type']==feedback['type'] and
                    live['connections']['A1']==live_feedback['connections']['ZN'] and
                    live_feedback['connections']['A1']==live['connections']['ZN'],
                    'LEAF_LIVE_KEEPER_FEEDBACK')
            result.append(path)
    require(result,'LEAF_NO_KEEPER_CUTS')
    return sorted(result)


def bind_plan(plan, index, descriptor, original, cuts):
    """Lift the reviewed local controller template onto unchanged physical pins."""
    result=deepcopy(plan)
    prefix='soc/'+'/'.join(descriptor['instance'].split('.')[1:])+'/'
    body=original['modules'][descriptor['module']]
    lanes=[row for port in body['ports'] if port=='in_bits' or port.startswith('in_bits_')
           for row in index.boundary(prefix[:-1],port)]
    require(len(lanes)==descriptor['input_width'],'LEAF_LOGICAL_WIDTH')
    data=sorted({(row['kind'],row['source']) for row in lanes if row['kind'] in ('pin','port')})
    if not data and all(row['kind']=='constant' for row in lanes):
        input_bits=[bit for port,p in body['ports'].items()
                    if port=='in_bits' or port.startswith('in_bits_') for bit in p['bits']]
        values={bit:row['value'] for bit,row in zip(input_bits,lanes)}
        allowance=body['cells']['ca_primitive_data_delay']['connections']['a']
        for row in result['lane_map']:
            bit=allowance[row['logical']]
            if bit in values:result['constant_lanes'][str(row['lane'])]=values[bit]
        for context in result['contexts']:
            if context['kind']=='data':
                context['queries']=[q for q in context['queries']
                                    if str(q['lane']) not in result['constant_lanes']]
    constant_only=(not data and len(result.get('constant_lanes',{}))==result['payload_width'] and
                   all(row['kind']=='constant' for row in lanes))
    require((data or constant_only) and all(kind=='pin' for kind,_ in data),'LEAF_DATA_SOURCE_PIN_REQUIRED')
    signals={p:index.scalar(prefix[:-1],p) for p in ('reset','in_req','out_ack','in_ack')}
    require(all(k=='pin' for k,p in signals.values()),'LEAF_CONTROL_SOURCE_PIN_REQUIRED')
    ack_net=index.before['boundaries'][prefix+'in_ack'][0]
    ack_targets=sorted(p for k,p in index.consumers[ack_net] if k=='pin')
    require(ack_targets,'LEAF_ACK_RECEIVERS')
    for c in result['native']['cells']:c['path']=prefix+c['path']
    result['native']['physical_prefix']=prefix
    result['event']=prefix+result['event']
    for p in result['phase'].values():p['pin']=prefix+p['pin']
    # `phase` is copied separately from native by deepcopy only when the source
    # already had separate dictionaries; make the identity explicit.
    result['native']['phase']=result['phase']
    for lane in result['lane_map']:
        for p in ('D','Q','capture'):lane[p]=prefix+lane[p]
    for ctx in result['contexts']:
        ctx['state']['cases']=[(k,prefix+p,v) if k=='pin' else (*signals[p],v)
                               for k,p,v in ctx['state']['cases']]
        ctx['state']['keeper_cuts']=cuts
        if ctx['kind']=='data':
            # A literal-only token has no data launch path. Use the request
            # source solely as a clock object for an empty query context; no
            # data arrival or polarity coverage is inferred from it.
            require(not constant_only or not ctx['queries'],'LEAF_CONSTANT_DATA_QUERIES')
            ctx['sources']=[p for _,p in data] if data else [signals['in_req'][1]]
        elif ctx['source_kind']=='clock':ctx['sources']=[result['event']]
        else:ctx['sources']=[signals[p][1] for p in ctx['sources']]
        ctx['source_kind']='clock'
        queries=[]
        for q in ctx['queries']:
            if q['sink_kind']=='port':
                require(q['role']=='ack' and q['sink']=='in_ack','LEAF_OUTPUT_QUERY')
                queries.extend(dict(q,id=q['id'].replace('ack:',f'ack:{i}:'),sink=p,sink_kind='pin',
                                    receiver_role='internal-feedback' if p.startswith(prefix) else 'external-receiver')
                               for i,p in enumerate(ack_targets))
            else:queries.append(dict(q,sink=prefix+q['sink']))
        ctx['queries']=queries
    result.update(module='RiscayMcuDigital',leaf_anchored=True,input_lanes=lanes,
                  ack_targets=ack_targets,keeper_cuts=cuts,
                  boundary_alignment='conditional-zero-phase; upstream launch remains uncomposed')
    return result


SLEW_TCL = r'''
proc leaf_check_loop_cuts {roots targets phase_clk phase_q} {
  # Inspect every enabled alternative in the launch-to-target corridor, not
  # only the extremal path eventually printed by STA. Ignore automatic loop
  # flags during reachability, then reject any such cut in that corridor.
  set root_vertices {}; set target_vertices {}; set queue {}; set seen {}; set forward {}
  foreach pin $roots {
    if {[llength [$pin vertices]] != 1} {error LEAF_LOOP_PIN_VERTICES}
    foreach vertex [$pin vertices] {dict set root_vertices $vertex 1}
  }
  foreach pin $targets {
    if {[llength [$pin vertices]] != 1} {error LEAF_LOOP_PIN_VERTICES}
    foreach vertex [$pin vertices] {dict set target_vertices $vertex 1; lappend queue $vertex}
  }
  while {[llength $queue]} {
    set vertex [lindex $queue end]; set queue [lrange $queue 0 end-1]
    if {[dict exists $seen $vertex]} {continue}; dict set seen $vertex 1
    if {[llength [[$vertex pin] vertices]] != 1} {error LEAF_LOOP_PIN_VERTICES}
    if {[dict exists $root_vertices $vertex]} {continue}
    set iterator [$vertex in_edge_iterator]
    while {[$iterator has_next]} {
      set arc [$iterator next]
      set from [$arc from]; set role [$arc role]
      if {$role ni {wire combinational}} {
        if {$phase_q eq "" || [get_full_name [$arc from_pin]] ne $phase_clk ||
            [get_full_name [$arc to_pin]] ne $phase_q} {continue}
      }
      if {[llength [[$arc from_pin] vertices]] != 1 ||
          [llength [[$arc to_pin] vertices]] != 1} {error LEAF_LOOP_PIN_VERTICES}
      # is_disabled_constant means ANY transition arc is disabled in old STA;
      # dropping that entire edge would hide an enabled competing transition.
      # Keep uncertain conditional alternatives conservatively in the corridor.
      if {[$arc is_disabled_constraint] || ($role eq "combinational" && [$arc sim_timing_sense] eq "none") ||
          [sta::pin_sim_logic_value [$arc from_pin]] in {0 1} ||
          [sta::pin_sim_logic_value [$arc to_pin]] in {0 1} ||
          [$arc is_disabled_cond_default]} {continue}
      dict lappend forward $from [list $vertex $arc]
      lappend queue $from
    }
    $iterator finish
  }
  set queue [dict keys $root_vertices]; set reached {}; set arcs 0
  while {[llength $queue]} {
    set vertex [lindex $queue end]; set queue [lrange $queue 0 end-1]
    if {[dict exists $reached $vertex]} {continue}; dict set reached $vertex 1
    if {![dict exists $forward $vertex]} {continue}
    foreach pair [dict get $forward $vertex] {
      lassign $pair target arc; incr arcs
      if {[$arc is_disabled_loop]} {error "LEAF_ACTIVE_LOOP_CUT [$arc to_string]"}
      lappend queue $target
    }
  }
  foreach vertex [dict keys $target_vertices] {
    if {![dict exists $reached $vertex]} {error "LEAF_LOOP_TARGET_UNREACHABLE [get_full_name [$vertex pin]]"}
  }
  row LEAF_LOOP_CUT_COVERAGE [dict size $root_vertices] [llength $targets] $arcs
}
proc leaf_analysis_view {} {
  # OpenSTA renamed its single-corner analysis context to Scene. Each generated
  # experiment loads one PVT only; preserve that context on both pinned runtimes.
  if {[llength [info commands sta::cmd_scene]]} {return [sta::cmd_scene]}
  return [sta::cmd_corner]
}
proc leaf_slew {pin edge mode} {
  set values {}
  foreach vertex [$pin vertices] {
    if {[llength [info commands sta::cmd_scene]]} {
      set slew [$vertex slew $edge $mode]
    } else {
      set slew [$vertex slew_corner $edge [leaf_analysis_view] $mode]
    }
    lappend values [sta::time_sta_ui $slew]
  }
  if {![llength $values]} {error LEAF_SLEW_VERTEX}
  return [tcl::mathfunc::$mode {*}$values]
}
proc leaf_ack {id mode edge root phase_q phase_clk target {record LEAF_ACK_PATH}} {
  # Built-in report_path uses this same graph-path iterator. No invented output
  # port, electrical load or invalid combinational PathEnd constraint is needed.
  # These are local combinational or explicit phase-launch paths. Populate the
  # target's arrivals without unrelated whole-graph transparent-latch iteration.
  get_property [exact_object pin $target] arrival_${mode}_${edge}
  set chosen {}; set visits 0
  foreach vertex [[exact_object pin $target] vertices] {
    set iterator [$vertex path_iterator $edge $mode]
    while {[$iterator has_next]} {
      incr visits; if {$visits > 10000} {error LEAF_ACK_PATH_LIMIT}
      set path [$iterator next]; set start [$path start_path]
      set pin [get_full_name [$start pin]]
      set start_edge [string map {^ rise v fall} [$start edge]]
      if {$phase_q ne ""} {
        if {$pin ne $phase_q || $start_edge ne $edge} {continue}
      } elseif {$pin ne $root || $start_edge ne "rise"} {continue}
      set names {}; set max_slew 0.0
      foreach p [$path pins] {
        lappend names [get_full_name $p]
        foreach e {rise fall} {set s [get_property $p slew_max_$e]; if {$s>$max_slew} {set max_slew $s}}
      }
      set names [lreverse $names]
      if {[lindex $names 0] ne $root || [lindex $names end] ne $target} {continue}
      set arrival [sta::time_sta_ui [$path arrival]]
      set origin [sta::time_sta_ui [$start arrival]]
      if {![llength $chosen] || ($mode eq "min" && $arrival<[lindex $chosen 0]) || ($mode eq "max" && $arrival>[lindex $chosen 0])} {
        set chosen [list $arrival $origin $pin $start_edge $names $max_slew]
      }
    }
    $iterator finish
  }
  if {![llength $chosen]} {error LEAF_ACK_MISSING}
  lassign $chosen arrival origin pin start_edge names max_slew
  if {$phase_q ne ""} {
    set arc [get_timing_edges -from [exact_object pin $phase_clk] -to [exact_object pin $phase_q]]
    if {[llength $arc] != 1} {error RELATIVE_CLK_Q_ARC}
    row LEAF_ACK_SEQUENTIAL $id $arrival $origin [get_property [lindex $arc 0] delay_${mode}_${edge}]
    row LEAF_ACK_POINTS $id {*}$names
  } else {
    set delay [expr {$arrival-$origin}]
    row $record $id $origin $arrival $delay $delay $max_slew $pin $target $start_edge $edge
    if {$record eq "CONTROL_PATH"} {row CONTROL_POINTS $id {*}$names} else {row LEAF_ACK_POINTS $id {*}$names}
  }
}
'''


def script(netlist,corner,slew,plan,ctx,*,sta,period=1000,odb=None,spef=None,routed_netlist=None):
    import control_relative_timing as relative
    b=relative.brace
    root_slew=ctx.get('root_slew_ns',dict(min=slew,max=slew))
    require(ctx['kind'] not in ('common','sequential_ack') or 'root_slew_ns' in ctx,
            'LEAF_COMMON_SLEW_REQUIRED')
    text='read_liberty '+b(sta.path(ROOT/'.tools/physical/pdk'/(SC+corner+'.lib')))+'\n'
    text+='read_liberty '+b(sta.path(ROOT/'.tools/gf180-sram'/(SRAM+'__'+corner+'.lib')))+'\n'
    text+=relative.PROBE.read_text()+'\n'+SLEW_TCL+'\n'
    require((odb is None and routed_netlist is None)==(spef is None) and
            not (odb is not None and routed_netlist is not None),'LEAF_ROUTED_INPUT_PAIR')
    if routed_netlist is not None:
        from routed_annotation import REPORT_TCL
        text+='read_verilog '+b(sta.path(routed_netlist))+'\nlink_design RiscayMcuDigital\n'
        text+='read_spef '+b(sta.path(spef))+'\n'+REPORT_TCL
    elif odb is None:
        text+='read_verilog '+b(sta.path(netlist))+'\nlink_design RiscayMcuDigital\n'
    else:
        text+='read_db '+b(sta.path(odb))+'\nread_spef '+b(sta.path(spef))+'\n'
    text+=f'set_input_transition {slew} [all_inputs]\nset_load 0.05 [all_outputs]\nset_max_transition 2 [current_design]\n'
    for kind,pin,value in ctx['state']['cases']:text+=f'set_case_analysis {value} [exact_object {kind} {b(pin)}]\n'
    for cell in ctx['state']['keeper_cuts']:text+='set_disable_timing -from A1 -to ZN [get_cells '+b(cell)+']\n'
    text+='set roots {}; foreach name [list '+ ' '.join(map(b,ctx['sources']))+'] {lappend roots [exact_object pin $name]}\n'
    text+=f'create_clock -name event -period {period} -waveform {{0 1}} $roots\nset_propagated_clock [all_clocks]\nsta::find_delays\n'
    for mode in ('min','max'):
        text+='foreach pin $roots {foreach vertex [$pin vertices] {foreach edge {rise fall} {sta::set_annotated_slew $vertex [leaf_analysis_view] '+mode+' $edge [sta::time_ui_sta '+str(root_slew[mode])+']}}}\n'
    text+='set sources [get_clocks event]\nrow RELATIVE_BEGIN\n'
    text+='set targets {}\n'
    for pin in sorted({q['sink'] for q in ctx['queries'] if q['role']!='ack'}):text+='lappend targets [exact_object pin '+b(pin)+']\n'
    text+='if {[llength $targets]} {set_max_delay 100000 -from $sources -to $targets; set_min_delay 0 -from $sources -to $targets}\n'
    if routed_netlist is not None:
        text+='set audit_targets {}\n'
        for pin in sorted({q['sink'] for q in ctx['queries']}):
            text+='lappend audit_targets [exact_object pin '+b(pin)+']\n'
        phase=[plan['phase'][p]['pin'] for p in ('CLK','Q')] if ctx['kind']=='sequential_ack' else ['','']
        text+='sta::find_delays\nleaf_check_loop_cuts $roots $audit_targets '+' '.join(map(b,phase))+'\n'
    if ctx['kind']=='sequential_ack':
        # Read propagated graph arrivals at actual receivers. Combinational
        # input pins are not artificial constrained PathEnd endpoints.
        for q in ctx['queries']:
            text+='leaf_ack '+' '.join(map(b,[q['id'],q['mode'],q['sink_edge'],plan['event'],plan['phase']['Q']['pin'],plan['phase']['CLK']['pin'],q['sink']]))+'\n'
    else:
        batches=defaultdict(list)
        for q in ctx['queries']:
            if q['role']=='ack':
                text+='leaf_ack '+' '.join(map(b,[q['id'],q['mode'],q['sink_edge'],plan['event'],'','',q['sink']]))+'\n'
            elif spef is not None and ctx['kind']!='data':
                # In the routed OpenSTA runtime a latch enable is a clock pin,
                # not a constrained data PathEnd. Query its real propagated
                # graph arrival, exactly as for an ACK receiver. No path waiver
                # or substitute output/load is introduced.
                require(len(ctx['sources'])==1 and q['source_edge']=='rise',
                        'LEAF_CAPTURE_LAUNCH_SHAPE')
                text+='leaf_ack '+' '.join(map(b,[q['id'],q['mode'],q['sink_edge'],ctx['sources'][0],'','',q['sink'],'CONTROL_PATH']))+'\n'
            else:batches[tuple(q[k] for k in ('mode','source_edge','sink_edge'))].append(q)
        for (mode,se,te),qs in batches.items():
            text+='control_batch '+' '.join(map(b,(mode,se,te)))+' $sources pin [list '
            text+=' '.join(b(q[k]) for q in qs for k in ('id','sink'))+']\n'
    for i,pin in enumerate(ctx['sources']):
        text+='set p [exact_object pin '+b(pin)+']\n'
        for mode in ('min','max'):
            for edge in ('rise','fall'):text+=f'row LEAF_SOURCE_SLEW {i} {mode} {edge} [leaf_slew $p {edge} {mode}]\n'
    text+='set event_pin [exact_object pin '+b(plan['event'])+']\n'
    text+='row RELATIVE_EVENT_SLEW [get_property $event_pin slew_min_rise] [get_property $event_pin slew_max_rise]\n'
    text+='row RELATIVE_ELECTRICAL_BEGIN\nreport_check_types -max_slew -max_capacitance -violators -digits 6\nrow RELATIVE_ELECTRICAL_END\nrow RELATIVE_COMPLETE\nexit\n'
    return text


def parse(log,plan,ctx,slew,index,*,routed_drivers=None):
    import control_relative_timing as relative
    from routed_annotation import SPEF_WARNING
    require(re.search(SPEF_WARNING,log) is None,
            'LEAF_SPEF_ANNOTATION_INCOMPLETE')
    if routed_drivers is not None:
        from routed_annotation import check_loaded_drivers
        check_loaded_drivers(log+'\n'+routed_drivers)
        coverage=[l.split('\t')[1:] for l in log.splitlines() if l.startswith('LEAF_LOOP_CUT_COVERAGE\t')]
        expected_targets=len({q['sink'] for q in ctx['queries']})
        require(len(coverage)==1 and len(coverage[0])==3 and
                all(re.fullmatch(r'\d+',v) for v in coverage[0]) and
                list(map(int,coverage[0][:2]))==[len(ctx['sources']),expected_targets] and
                (int(coverage[0][2])>0 or not expected_targets),'LEAF_LOOP_CUT_COVERAGE')
    measured={}
    root_slew=ctx.get('root_slew_ns',dict(min=slew,max=slew))
    for line in log.splitlines():
        f=line.split('\t')
        if f[0]!='LEAF_SOURCE_SLEW':continue
        require(len(f)==5,'LEAF_SLEW_ROW')
        key=(int(f[1]),f[2],f[3]);value=float(f[4])
        require(key not in measured and math.isfinite(value) and key[1] in root_slew and
                abs(value-root_slew[key[1]])<1e-5,'LEAF_SLEW_CHANGED')
        measured[key]=value
    require(set(measured)=={(i,m,e) for i in range(len(ctx['sources'])) for m in ('min','max') for e in ('rise','fall')},'LEAF_SLEW_COVERAGE')
    result=relative.parse(log,plan,ctx)
    for points in result['paths'].values():
        for pin in points[1:]:
            name,port=pin.rsplit('/',1)
            require(name in index.after['cells'],'LEAF_PATH_UNKNOWN_CELL')
            kind=index.after['cells'][name]['type']
            if port in ('Q','QN') and kind.startswith((SC+'dff',SC+'lat')):
                require(ctx['kind']=='sequential_ack' and pin==plan['phase']['Q']['pin'],
                        'LEAF_INTERMEDIATE_STORAGE')
    return result

# SPDX-License-Identifier: Apache-2.0
"""BD retained-bank reader apertures after electrical repair (zero wire RC).

Usage: telemetry_bank_timing.py MAPPING NEW_OUTPUT
Every reached periodic D pin must belong to an inventoried reader. Application
bank paths use a conservative next-edge bound (50 ns); sample bank readers reopen
at A+5 or later after full return (250 ns). Both check same-edge old-bank hold.
The independent upper-time accumulator and its readers always use one period. It grants no multicycle or disabled-functional-path waiver.
Routed skew/RC and full electrical acceptance remain the tape-out gate.
"""
import sys,json,subprocess,re,math,argparse
from pathlib import Path
from collections import defaultdict,deque
from gf180_physical import ROOT,SC,SRAM
from repair_gf180_design import validate_receipt,flat
from native_stage_timing import receipt_original,receipt_proof
from native_leaf_timing import LeafIndex,keeper_cuts,SLEW_TCL
from physical_tools import tool
from control_relative_timing import CORNERS,PROBE,brace,library
from size_ordering_guards import scalar_table_max
from run_receipt import RunReceipt

# Enclose both sampled propagated-slew mode graphs before path search.
# This is not a continuous-slew or extracted-RC qualification.
SAMPLED_ARC_ENVELOPE = r"""
# Conservative enclosure of both sampled OpenSTA mode graphs. The caller must
# provide every combinational cell in the queried source-to-target cone.
# No source/capture sequential arc, net, or keeper cut is modified.
proc sampled_arc_envelope {cells profile} {
  sta::find_timing
  set records [dict create]
  set inversions 0
  set max_inversion 0.0
  # get_timing_edges -of_objects returns one edge list per cell.
  foreach edge [concat {*}[get_timing_edges -of_objects $cells]] {
    set from [$edge from_pin]
    set to [$edge to_pin]
    set from_name [get_full_name $from]
    set to_name [get_full_name $to]
    foreach arc [$edge timing_arcs] {
      set pol [$arc to_edge_name]
      if {$pol ni {rise fall}} {error ENVELOPE_EDGE_POLARITY}
      # Do not use get_property delay_*: that API rounds to six decimals.
      set early [sta::time_sta_ui [$edge arc_delay $arc [sta::cmd_corner] min]]
      set late [sta::time_sta_ui [$edge arc_delay $arc [sta::cmd_corner] max]]
      if {$early > $late} {
        incr inversions
        set max_inversion [expr {max($max_inversion,$early-$late)}]
        puts [join [list ARC_INVERSION $from_name $to_name $pol $early $late] "\t"]
      }
      # Merge all conditional/non-unate arcs sharing the endpoint and output
      # transition. set_assigned_delay addresses that same group of arcs.
      set key [list $from_name $to_name $pol]
      if {[dict exists $records $key]} {
        lassign [dict get $records $key] unused_from unused_to unused_pol lo hi
        set lo [expr {min($lo,$early,$late)}]
        set hi [expr {max($hi,$early,$late)}]
      } else {
        set lo [expr {min($early,$late)}]
        set hi [expr {max($early,$late)}]
      }
      dict set records $key [list $from $to $pol $lo $hi]
    }
  }
  # Snapshot every arc BEFORE changing any annotation, so recalculation cannot
  # contaminate later samples. Each query/source profile gets a fresh STA run.
  dict for {key record} $records {
    lassign $record from to pol lo hi
    set_assigned_delay -cell -from $from -to $to -$pol -min $lo
    set_assigned_delay -cell -from $from -to $to -$pol -max $hi
  }
  puts [join [list ARC_ENVELOPE $profile [dict size $records] $inversions $max_inversion] "\t"]
  return [dict size $records]
}
"""

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mapping',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--bank',choices=('application','software','adc'),default='application')
    args=parser.parse_args();mapping=args.mapping;output=args.output;output.mkdir(parents=True)
    owner='soc/ca_child_spi_adc/ca_child_native' if args.bank=='adc' else 'soc/ca_child_telemetry'
    primitive='register_bank' if args.bank=='application' else 'sample_bank'
    # Sample readers reopen only after ACK return and the returning flag clear.
    # A is ACK rise; request sync sees earliest fall at A+2; ACK falls at A+3;
    # returning clears at A+4; the next qualified readStart is A+5. Same-edge
    # old-bank reads still require the complete min-delay hold check below.
    read_edges=1 if args.bank=='application' else 5
    status='fail'
    run=RunReceipt(output/'receipt.json',inputs=[mapping/x for x in ('netlist.v','netlist.json','mapping.json','timing-intent.json','electrical-repair/receipt.json','electrical-repair/proof.json')],tools=[Path(__file__)])
    try:
        receipt=validate_receipt(mapping)
        original=receipt_original(mapping,receipt);live=json.loads((mapping/'netlist.json').read_text())
        proof=receipt_proof(mapping,receipt);index=LeafIndex(original,live,proof['added_buffers'],proof['added_ties'])
        cells=index.after['cells'];before=index.before
        bank=[p for p,c in cells.items() if p.startswith(owner+'/ca_primitive_'+primitive+'/') and c['type'].startswith(SC+'dff')]
        assert bank
        ack=index.scalar(owner,'commitAck' if args.bank=='application' else 'reply_ack')[1]
        base=index.scalar(owner,'reply_ack')[1]
        def driving_ff(pin):
            while not cells[pin.rsplit('/',1)[0]]['type'].startswith(SC+'dff'):
                c=cells[pin.rsplit('/',1)[0]]
                assert c['type'].startswith(SC+'buf_')
                net=index.normalized(c['connections']['I'][0])
                sources=index.drivers[net];assert len(sources)==1
                pin=sources[0][1]
            return pin
        ack=driving_ff(ack);base=driving_ff(base)
        guard=index.scalar(owner+'/ca_primitive_output_guard','q')[1]
        feedback_input=index.boundary(owner+'/ca_child_state','in_req')
        assert len(feedback_input)==1 and feedback_input[0]['source']==guard, 'BANK_FEEDBACK_BINDING'
        feedback_sinks=feedback_input[0]['consumers']
        assert feedback_sinks, 'BANK_FEEDBACK_RECEIVERS'
        completion_other=None
        if args.bank!='adc':
            completion=index.boundary(owner+'/ca_primitive_bank_completion','common')
            assert len(completion)==2
            def source_net(pin):
                path,port=pin.rsplit('/',1)
                return index.normalized(cells[path]['connections'][port][0])
            ack_inputs=[p for p in completion if source_net(p['source'])==source_net(base)]
            assert len(ack_inputs)==1, 'BANK_COMPLETION_ACK_BINDING'
            completion_other=next(p['source'] for p in completion if p is not ack_inputs[0])
        # Trace combinational fanout to every storage input; sequential elements stop it.
        consumers=defaultdict(list);all_drivers=defaultdict(list)
        for p,c in cells.items():
            for pin,ns in c['connections'].items():
                if c['directions'][pin]=='input':
                    for n in ns:consumers[n].append((p,pin))
                else:
                    for n in ns:all_drivers[n].append((p,pin))
        def endpoints(sources):
            pending=deque(cells[p.rsplit('/',1)[0]]['connections'][p.rsplit('/',1)[1]][0] for p in sources)
            seen=set();ends=set()
            while pending:
                n=pending.popleft()
                if n in seen:continue
                seen.add(n)
                for p,pin in consumers[n]:
                    c=cells[p]
                    if c['type'].startswith((SC+'dff',SC+'lat')):
                        assert pin=='D',('NON_DATA_STORAGE_FANOUT',p,pin)
                        ends.add(p+'/D')
                    elif c['type']==SRAM:continue
                    else:
                        pending.extend(n for k,ns in c['connections'].items() if c['directions'][k]=='output' for n in ns)
            return sorted(ends)
        def combinational_cone(sources,sinks):
            def walk(pins,adjacency,forward):
                todo=deque(cells[p.rsplit('/',1)[0]]['connections'][p.rsplit('/',1)[1]][0] for p in pins)
                seen=set();found=set()
                while todo:
                    net=todo.popleft()
                    if net in seen:continue
                    seen.add(net)
                    for path,pin in adjacency[net]:
                        cell=cells[path]
                        if cell['type'].startswith((SC+'dff',SC+'lat')) or cell['type']==SRAM:continue
                        found.add(path)
                        direction='output' if forward else 'input'
                        todo.extend(n for port,ns in cell['connections'].items() if cell['directions'][port]==direction for n in ns)
                return found
            return sorted(walk(sources,consumers,True)&walk(sinks,all_drivers,False))
        targets=endpoints([p+'/Q' for p in bank])
        # Native storage is a separate handshake obligation; this screen enumerates the
        # actual periodic sinks reached by the retained view.
        from gf180_netgraph import graph
        from report_clock_owners import clock_nets
        g,aliases=graph(live['modules']);clocks=clock_nets(g,aliases)
        domains={p.replace('\\',''):clocks[c['connections']['CLK'][0]] for p,c in g.items() if 'CLK' in c['connections'] and c['connections']['CLK'][0] in clocks}
        periodic=set(domains)
        targets=[p for p in targets if p.rsplit('/',1)[0] in periodic]
        print('TARGET_DOMAINS',[(p,domains[p.rsplit('/',1)[0]]) for p in targets if domains[p.rsplit('/',1)[0]]!='work'],flush=True)
        assert targets and all(domains[p.rsplit('/',1)[0]] in ('work','service') for p in targets)
        og,oa=graph(original['modules'])
        snapshot_bits={bit for name,bits in oa.items() if name.startswith('soc/fabric_snapshot_') for bit in bits}
        snapshot_cells={p.replace('\\','') for p,c in og.items() if set(c['connections'].get('Q',())) & snapshot_bits}

        # Repair preserves logical nets but may interpose buffers. Classify readers
        # from pre-repair storage identity, never guessed new synthesis numbers.
        control_bits=set(oa['soc/ca_child_control_command_bridge/data_peripheralData'])
        control_cells={p.replace('\\','') for p,c in og.items() if set(c['connections'].get('Q',())) & control_bits}
        reader={p:('snapshot' if p.rsplit('/',1)[0] in snapshot_cells else 'control') for p in targets}
        assert all(p.rsplit('/',1)[0] in snapshot_cells | control_cells for p in targets), 'BANK_UNQUALIFIED_READER'
        time_cells=[];time_targets=[];time_launch_cells=[];native_time_ingress=[];native_time_targets=[];elapsed_ingress=[];other_time_ingress=[];elapsed_ack=None
        if args.bank!='application':
            time_bits=set(oa['soc/fabric_upperTime'])
            time_cells=sorted(p.replace('\\','') for p,c in og.items() if set(c['connections'].get('Q',())) & time_bits)
            assert time_cells and all(p in periodic for p in time_cells), 'TIME_COUNTER_BINDING'
            time_targets=[p for p in endpoints([p+'/Q' for p in time_cells]) if p.rsplit('/',1)[0] in periodic]
            accepted_bits={bit for name,bits in oa.items() if name in
                ('soc/fabric_softwareTimestamp','soc/ca_child_spi_adc/admissionTime') for bit in bits}
            admission_cells={p.replace('\\','') for p,c in og.items() if set(c['connections'].get('Q',())) & accepted_bits}
            allowed=set(time_cells)|snapshot_cells|admission_cells
            assert time_targets and all(p.rsplit('/',1)[0] in allowed for p in time_targets), 'TIME_UNQUALIFIED_READER'
            # Inventory *all* sequential launches into the accumulator/admission
            # arithmetic. In particular, receipt valid and ElapsedTicks.active
            # gate the elapsed operand on a real work-clock edge. Checking only
            # upperTime.Q misses those ordinary one-period paths.
            drivers=defaultdict(list)
            for p,c in cells.items():
                for pin,ns in c['connections'].items():
                    if c['directions'][pin]=='output':
                        for n in ns:drivers[n].append((p,pin))
            pending=deque(cells[p]['connections']['D'][0] for p in set(time_cells)|admission_cells)
            seen=set();launches=set();native=set()
            while pending:
                n=pending.popleft()
                if n in seen:continue
                seen.add(n)
                for p,pin in drivers[n]:
                    c=cells[p]
                    if c['type'].startswith((SC+'dff',SC+'lat')):
                        assert pin=='Q', 'TIME_NON_DATA_LAUNCH'
                        if p in periodic:launches.add(p)
                        else:native.add(p+'/'+pin)
                    elif c['type']!=SRAM:
                        pending.extend(n for k,ns in c['connections'].items() if c['directions'][k]=='input' for n in ns)
            time_launch_cells=sorted(set(time_cells)|launches)
            native_time_ingress=sorted(native)
            elapsed_owner='soc/ca_child_elapsed_scaler/ca_child_native'
            elapsed_ingress=sorted({row['source'] for lane in (0,2)
                for row in index.boundary(elapsed_owner,f'reply_bits_elapsed_{lane}') if row['kind']=='pin'})
            assert set(elapsed_ingress)<=set(native_time_ingress), 'TIME_ELAPSED_OPERAND_BINDING'
            other_time_ingress=sorted(set(native_time_ingress)-set(elapsed_ingress))
            native_time_targets=sorted(set(endpoints(elapsed_ingress)) & set(time_targets))
            elapsed_ack=driving_ff(index.scalar('soc/ca_child_elapsed_scaler/ca_child_native','reply_ack')[1])
            assert native_time_targets and elapsed_ack.rsplit('/',1)[0] in periodic, 'TIME_RECEIPT_BINDING'
            assert all(domains[p] in ('work','service') for p in time_launch_cells), 'TIME_LAUNCH_DOMAIN'
        native_boundaries=sorted(p+'/Q' for p,c in cells.items()
            if c['type'].startswith((SC+'dff',SC+'lat')) and p not in periodic)
        cuts=keeper_cuts(index,json.loads((mapping/'netlist-audit.json').read_text()))
        sta=tool('sta');b=brace
        run.inputs+=run.capture([PROBE,*sta.input_files(),
          *[ROOT/'.tools/physical/pdk'/(SC+c+'.lib') for c in CORNERS],
          ROOT/'.tools/gf180-sram'/(SRAM+'__tt_025C_3v30.lib'),
          *[ROOT/'tools'/x for x in ('native_leaf_timing.py','control_relative_timing.py','size_ordering_guards.py','physical_tools.py','report_clock_owners.py','gf180_estimate.py','gf180_netgraph.py','native_stage_timing.py','repair_gf180_design.py','run_receipt.py')]], initial=True)
        inventory=dict(time_cells=time_cells,time_launch_cells=time_launch_cells,time_targets=time_targets,
         native_time_ingress=native_time_ingress,native_time_targets=native_time_targets,elapsed_ingress=elapsed_ingress,other_time_ingress=other_time_ingress,elapsed_ack=elapsed_ack,native_sequential_boundaries=native_boundaries,
         native_ingress_obligation='Conditional receiver-side check: payload stable by receipt request detection, 100 ns to earliest acceptance; hypothetical source reuse immediately on receipt ACK.Q. Source Q versus elapsed publication/history composition remains open. Source Q slew cases are 0.02 and 2 ns; routed loaded-source slew remains open. Periodic valid/active paths are checked independently at 50 ns.',
         owner=owner,bank_kind=args.bank,earliest_later_read_edges=read_edges,bank=bank,qualified_ack=ack,base_ack=base,periodic_targets=targets,readers=reader,feedback_sinks=feedback_sinks,
         target_domains={p:domains[p.rsplit('/',1)[0]] for p in targets},
         reader_qualification={
          'snapshot':'actual readStart = snapshot receipt fire; selected native bank requires its full-return ready gate; only application bank selects zero during reset',
          'control':'MMIO command fire requires !telemetryBarrier && telemetryBankReady && !applicationCancel; unrelated commands mask native peripheralData'},
         clock_contract='work is gated service clock: same active edge, 50 ns minimum period; qualified read-edge bound plus same-edge hold; actual CTS skew remains open')
        (output/'inventory.json').write_text(json.dumps(inventory,indent=2))
        results=[]
        def run_tcl(text,path):
            path.write_text(text+'\nrow BANK_COMPLETE\nexit\n')
            log=path.with_suffix('.log')
            with log.open('w') as f:subprocess.run(sta.command(['-no_init','-exit',sta.path(path)],timeout=55),stdout=f,stderr=subprocess.STDOUT,check=True,timeout=65)
            text=log.read_text()
            assert text.count('BANK_COMPLETE\n')==1 and 'CONTROL_MISSING' not in text and not re.search(r'(?mi)^(?:Error:|ERROR|Warning:)',text),log
            return text
        def header(corner,slew):
            text='read_liberty '+b(sta.path(ROOT/'.tools/physical/pdk'/(SC+corner+'.lib')))+'\n'
            text+='read_liberty '+b(sta.path(ROOT/'.tools/gf180-sram'/(SRAM+'__tt_025C_3v30.lib')))+'\n'
            text+=PROBE.read_text()+'\n'+SLEW_TCL+'\nread_verilog '+b(sta.path(mapping/'netlist.v'))+'\nlink_design RiscayMcuDigital\n'
            text+=f'set_input_transition {slew} [all_inputs]\nset_load .05 [all_outputs]\n'
            reset=index.scalar(owner,'reset')[1]
            text+='set_case_analysis 0 [exact_object pin '+b(reset)+']\n'
            for c in cuts:text+='set_disable_timing -from A1 -to ZN [get_cells '+b(c)+']\n'
            return text
        def annotate(pin,values):
            text='set p [exact_object pin '+b(pin)+']\n'
            for mode in ('min','max'):
              for edge in ('rise','fall'):
                text+=f'foreach v [$p vertices] {{sta::set_annotated_slew $v [sta::cmd_corner] {mode} {edge} [sta::time_ui_sta {values[mode,edge]}]}}\n'
            return text
        def sequential(corner,slew,seq,clkslews,path):
            profiles=('min','max') if any(v['min',e]!=v['max',e] for v in clkslews.values() for e in ('rise','fall')) else ('min',)
            logs=[]
            for profile in profiles:
              text=header(corner,slew)
              text+='create_clock -name arc_event -period 1000 [get_pins [list '+' '.join(b(p+'/CLK') for p in seq)+']]\nset_propagated_clock [all_clocks]\nsta::find_delays\n'
              for p in seq:text+=annotate(p+'/CLK',{(m,e):clkslews[p][profile,e] for m in ('min','max') for e in ('rise','fall')})
              text+='sta::find_delays\n'
              for i,p in enumerate(seq):
                text+='set arcs [get_timing_edges -from [exact_object pin '+b(p+'/CLK')+'] -to [exact_object pin '+b(p+'/Q')+']]\nif {[llength $arcs]!=1} {error BANK_CLK_Q_ARC}\n'
                for mode in ('min','max'):
                  for edge in ('rise','fall'):
                    text+=f'row ARC {profile}:{i} {mode} {edge} [get_property [lindex $arcs 0] delay_{mode}_{edge}] [get_property [exact_object pin '+b(p+'/Q')+f'] slew_{mode}_{edge}]\n'
              logs.append(run_tcl(text,path.with_stem(path.stem+'-'+profile)))
            a=[l.split('\t') for log in logs for l in log.splitlines() if l.startswith('ARC\t')]
            expected={(f'{profile}:{i}',m,e) for profile in profiles for i in range(len(seq)) for m in ('min','max') for e in ('rise','fall')}
            assert all(len(x)==6 for x in a), 'BANK_ARC_SHAPE'
            assert len(a)==len(expected) and {tuple(x[1:4]) for x in a}==expected, 'BANK_ARC_COVERAGE'
            delays={};qslews={}
            for x in a:
              p=seq[int(x[1].split(':')[1])];key=x[2],x[3];d,s=map(float,x[4:])
              assert math.isfinite(d) and math.isfinite(s) and d>=0 and s>=0
              reduce=min if x[2]=='min' else max
              prior=delays.setdefault(p,{});prior[key]=reduce(prior.get(key,d),d)
              prior=qslews.setdefault(p+'/Q',{});prior[key]=reduce(prior.get(key,s),s)
            return delays,qslews
        for corner in CORNERS:
          lib=library(ROOT/'.tools/physical/pdk'/(SC+corner+'.lib'))
          kinds={cells[p.rsplit('/',1)[0]]['type'] for p in targets}
          setup=max(scalar_table_max(lib[k],'setup',('rise_constraint','fall_constraint')) for k in kinds)
          hold=max(scalar_table_max(lib[k],'hold',('rise_constraint','fall_constraint')) for k in kinds)
          for slew in (.02,2.):
            rows={};hostrows={};arcs={};envelopes=[];source_cells=list(dict.fromkeys(p.rsplit('/',1)[0] for p in (ack,base,*([elapsed_ack] if elapsed_ack else []))))
            source_delays,source_slews=sequential(corner,slew,source_cells,{p:{(m,e):slew for m in ('min','max') for e in ('rise','fall')} for p in source_cells},output/f'{corner}-{slew}-source-arcs.tcl')
            time_delays={};time_slews={}
            if time_cells:
                time_delays,time_slews=sequential(corner,slew,time_launch_cells,{p:{(m,e):slew for m in ('min','max') for e in ('rise','fall')} for p in time_launch_cells},output/f'{corner}-{slew}-time-arcs.tcl')
            bank_delays={};bank_slews={};time_paths={};ingress_paths={}
            queries=[('trigger',[ack],[p+'/CLK' for p in bank]),('read',[p+'/Q' for p in bank],targets),('feedback',[base],feedback_sinks)]
            if time_cells:
                queries.append(('time',[p+'/Q' for p in time_launch_cells],time_targets))
                queries.append(('ingress',elapsed_ingress,native_time_targets))
            for kind,sources,sinks in queries:
              source_envelope=({p:{(m,e):slew for m in ('min','max') for e in ('rise','fall')} for p in sources} if kind=='ingress' else time_slews if kind=='time' else bank_slews if kind=='read' else source_slews)
              profiles=('min','max') if any(source_envelope[p]['min',e]!=source_envelope[p]['max',e] for p in sources for e in ('rise','fall')) else ('min',)
              cone=combinational_cone(sources,sinks) if kind in ('read','time','ingress') else []
              texts=[]
              for profile in profiles:
                t=header(corner,slew)
                if kind=='feedback' and completion_other is not None:t+='set_case_analysis 1 [exact_object pin '+b(completion_other)+']\n'
                t+='set roots {}; foreach name [list '+' '.join(map(b,sources))+'] {lappend roots [exact_object pin $name]}\n'
                t+='create_clock -name event -period 1000 -waveform {0 1} $roots\n'
                if kind=='time':
                  # A receipt ACK can clock a native bank. Stop the periodic
                  # analysis reference at that sequential boundary; otherwise STA
                  # includes a second CLK-to-Q launch in this combinational cone.
                  # These are analysis roots, not disabled arcs. Native launches
                  # have their separate bank/receipt composition obligations.
                  t+='create_clock -name sequential_boundary -period 1000 [get_pins [list '+' '.join(map(b,native_boundaries))+']]\n'
                t+='set_propagated_clock [get_clocks event]\nsta::find_delays\n'
                for p in sources:t+=annotate(p,{(m,e):source_envelope[p][profile,e] for m in ('min','max') for e in ('rise','fall')})
                t+='sta::find_delays\n'
                if kind in ('read','time','ingress'):
                  if cone:
                    t+=SAMPLED_ARC_ENVELOPE+'\nset cone {}; foreach name [list '+' '.join(map(b,cone))+'] {set c [get_cells $name]; if {[llength $c]!=1 || [get_full_name [lindex $c 0]] ne $name} {error ENVELOPE_CELL_BINDING}; lappend cone [lindex $c 0]}\nsampled_arc_envelope $cone '+b(profile)+'\nsta::find_delays\n'
                if kind!='feedback':
                  t+='set sinks {}; foreach name [list '+' '.join(map(b,sinks))+'] {lappend sinks [exact_object pin $name]}\nset_max_delay 100000 -from [get_clocks event] -to $sinks\nset_min_delay 0 -from [get_clocks event] -to $sinks\n'
                for mode in ('min','max'):
                  for edge in ('rise','fall'):
                    if kind in ('trigger','feedback') and edge=='fall':continue
                    pairs=' '.join(b(x) for i,p in enumerate(sinks) for x in (f'{mode}:{edge}:{i}:{profile}',p))
                    if kind=='feedback':
                      for i,pin in enumerate(sinks):
                        t+='leaf_ack '+' '.join(map(b,[f'{mode}:{edge}:{i}:{profile}',mode,edge,base,'','',pin]))+'\n'
                    else:t+=f'control_batch {mode} any {edge} [get_clocks event] pin [list {pairs}]\n'
                for i,p in enumerate(sinks):
                  for mode in ('min','max'):
                    for edge in ('rise','fall'):
                      t+=f'row SINK_SLEW {profile}:{i} {mode} {edge} [get_property [exact_object pin '+b(p)+f'] slew_{mode}_{edge}]\n'
                t+='report_check_types -max_slew -max_capacitance -violators -digits 6\n'
                path=output/f'{corner}-{slew}-{kind}-{profile}.tcl'
                result_text=run_tcl(t,path)
                evidence=[line.split('\t') for line in result_text.splitlines() if line.startswith('ARC_ENVELOPE\t')]
                assert len(evidence)==(1 if cone else 0), 'BANK_ARC_ENVELOPE_COVERAGE'
                for x in evidence:
                  assert len(x)==5 and x[1]==profile, 'BANK_ARC_ENVELOPE_PROFILE'
                  count,inversions=int(x[2]),int(x[3]);widening=float(x[4])
                  assert count>0 and inversions>=0 and math.isfinite(widening) and widening>=0
                  envelopes.append(dict(query=kind,profile=profile,cone_cells=len(cone),arc_groups=count,inversions=inversions,max_arc_inversion_ns=widening))
                texts.append(result_text)
              text='\n'.join(texts)
              if kind=='feedback':text=re.sub(r'(?m)^LEAF_ACK_(PATH|POINTS)\t',r'CONTROL_\1\t',text)
              r=[l.split('\t') for l in text.splitlines() if l.startswith('CONTROL_PATH\t')]
              expected={f'{m}:{e}:{i}:{profile}':(m,e,p) for profile in profiles for m in ('min','max') for e in
                (('rise',) if kind in ('trigger','feedback') else ('rise','fall')) for i,p in enumerate(sinks)}
              points_rows=[l.split('\t') for l in text.splitlines() if l.startswith('CONTROL_POINTS\t')]
              points={x[1]:x[2:] for x in points_rows}
              assert len(r)==len(expected) and {x[1] for x in r}==set(expected), 'BANK_PATH_COVERAGE'
              assert len(points_rows)==len(points)==len(expected) and set(points)==set(expected), 'BANK_POINTS_COVERAGE'
              delays={}
              for x in r:
                assert len(x)==11, 'BANK_PATH_SHAPE'
                mode,edge,sink=expected[x[1]]
                ps=points[x[1]];assert x[7] in sources and x[8]==sink and ps[0]==x[7] and ps[-1]==sink
                assert x[9] in ('rise','fall') and x[10]==edge, 'BANK_PATH_POLARITY'
                source,arrival,data,delay,sink_slew=map(float,x[2:7])
                assert all(math.isfinite(v) for v in (source,arrival,data,delay,sink_slew)), 'BANK_NONFINITE'
                assert abs(source-(0 if x[9]=='rise' else 1))<1e-6 and abs(arrival-source-delay)<1e-4 and abs(data-delay)<1e-4, 'BANK_PATH_ARITHMETIC'
                assert sink_slew>=0 and (delay>=0 or kind in ('read','time','ingress')), 'BANK_NEGATIVE_CONTROL'
                assert all(not(cells[p.rsplit('/',1)[0]]['type'].startswith((SC+'dff',SC+'lat')) and p.rsplit('/',1)[1] in ('Q','QN')) for p in ps[1:])
                delays[mode,edge,sink,x[1].split(':')[-1]]=delay
              assert all(delays['min',e,p,profile]<=v+1e-6 for (m,e,p,profile),v in delays.items() if m=='max'), 'BANK_REVERSED_BOUNDS'
              if kind=='read': read_paths={p:{m:[float(x[5]) for x in r if x[1].startswith(m+':') and int(x[1].split(':')[2])==i] for m in ('min','max')} for i,p in enumerate(sinks)}
              if kind=='ingress': ingress_paths={p:{m:[float(x[5]) for x in r if x[1].startswith(m+':') and int(x[1].split(':')[2])==i] for m in ('min','max')} for i,p in enumerate(sinks)}
              if kind=='time': time_paths={p:{m:[float(x[5]) for x in r if x[1].startswith(m+':') and int(x[1].split(':')[2])==i] for m in ('min','max')} for i,p in enumerate(sinks)}
              rows[kind]={m:([float(x[5]) for x in r if x[1].startswith(m+':')]) for m in ('min','max')}
              if kind=='trigger':
                a=[l.split('\t') for l in text.splitlines() if l.startswith('SINK_SLEW\t')]
                expected={(f'{profile}:{i}',m,e) for profile in profiles for i in range(len(bank)) for m in ('min','max') for e in ('rise','fall')}
                assert all(len(x)==5 for x in a), 'BANK_SLEW_SHAPE'
                assert len(a)==len(expected) and {tuple(x[1:4]) for x in a}==expected, 'BANK_SLEW_COVERAGE'
                cs={p:{} for p in bank}
                for x in a:
                  value=float(x[4]);assert math.isfinite(value) and value>=0, 'BANK_INVALID_SLEW'
                  p=bank[int(x[1].split(':')[1])];key=x[2],x[3]
                  cs[p][key]=(min if x[2]=='min' else max)(cs[p].get(key,value),value)
                bank_delays,bank_slews=sequential(corner,slew,bank,cs,output/f'{corner}-{slew}-bank-arcs.tcl')
            def d(which,m):return [v for (mode,e),v in source_delays[which.rsplit('/',1)[0]].items() if mode==m]
            bc={m:[v for p in bank for (mode,e),v in bank_delays[p].items() if mode==m] for m in ('min','max')}
            earliest=min(d(ack,'min'))+min(rows['trigger']['min'])+min(bc['min'])+min(rows['read']['min'])
            latest=max(d(ack,'max'))+max(rows['trigger']['max'])+max(bc['max'])+max(rows['read']['max'])
            bank_latest=max(d(ack,'max'))+max(rows['trigger']['max'])+max(bc['max'])
            feedback_earliest=min(d(base,'min'))+min(rows['feedback']['min'])
            lanes=[]
            for pin in targets:
              kind=cells[pin.rsplit('/',1)[0]]['type']
              setup=scalar_table_max(lib[kind],'setup',('rise_constraint','fall_constraint'))
              hold=scalar_table_max(lib[kind],'hold',('rise_constraint','fall_constraint'))
              first_segments=[min(d(ack,'min')),min(rows['trigger']['min']),min(bc['min']),min(read_paths[pin]['min'])]
              last_segments=[max(d(ack,'max')),max(rows['trigger']['max']),max(bc['max']),max(read_paths[pin]['max'])]
              lanes.append(dict(pin=pin,reader=reader[pin],setup_aperture_ns=setup,hold_aperture_ns=hold,
                  hold_residual_ns=sum(min(.8*x,1.2*x) for x in first_segments)-hold,
                  next_edge_residual_ns=50*read_edges-sum(max(.8*x,1.2*x) for x in last_segments)-setup))
            result=dict(corner=corner,slew=slew,bank_min_ns=earliest,bank_max_ns=latest,
              hold_residual_ns=min(x['hold_residual_ns'] for x in lanes),
              next_edge_residual_ns=min(x['next_edge_residual_ns'] for x in lanes),
              feedback_after_bank_ns=.8*feedback_earliest-1.2*bank_latest,wire_rc='zero',clock_skew='not included',sampled_arc_envelopes=envelopes)
            if time_cells:
                periodic_rows=[]
                ctq={m:[v for p in time_launch_cells for (mode,e),v in time_delays[p].items() if mode==m] for m in ('min','max')}
                for pin in time_targets:
                    kind=cells[pin.rsplit('/',1)[0]]['type']
                    setup=scalar_table_max(lib[kind],'setup',('rise_constraint','fall_constraint'))
                    hold=scalar_table_max(lib[kind],'hold',('rise_constraint','fall_constraint'))
                    lower=[min(ctq['min']),min(time_paths[pin]['min'])]
                    upper=[max(ctq['max']),max(time_paths[pin]['max'])]
                    periodic_rows.append(dict(pin=pin,hold_residual_ns=sum(min(.8*x,1.2*x) for x in lower)-hold,
                        setup_residual_ns=50-sum(max(.8*x,1.2*x) for x in upper)-setup))
                ingress_rows=[]
                for pin in native_time_targets:
                    kind=cells[pin.rsplit('/',1)[0]]['type']
                    setup=scalar_table_max(lib[kind],'setup',('rise_constraint','fall_constraint'))
                    hold=scalar_table_max(lib[kind],'hold',('rise_constraint','fall_constraint'))
                    lower=[min(d(elapsed_ack,'min')),min(ingress_paths[pin]['min'])]
                    upper=max(ingress_paths[pin]['max'])
                    ingress_rows.append(dict(pin=pin,hold_residual_ns=sum(min(.8*x,1.2*x) for x in lower)-hold,
                        setup_residual_ns=100-max(.8*upper,1.2*upper)-setup))
                result['conditional_ingress_setup_residual_ns']=min(x['setup_residual_ns'] for x in ingress_rows)
                result['conditional_ingress_hold_residual_ns']=min(x['hold_residual_ns'] for x in ingress_rows)
                (output/f'{corner}-{slew}-ingress-readers.json').write_text(json.dumps(ingress_rows,indent=2))
                result['periodic_setup_residual_ns']=min(x['setup_residual_ns'] for x in periodic_rows)
                result['periodic_hold_residual_ns']=min(x['hold_residual_ns'] for x in periodic_rows)
                (output/f'{corner}-{slew}-time-readers.json').write_text(json.dumps(periodic_rows,indent=2))
            (output/f'{corner}-{slew}-readers.json').write_text(json.dumps(lanes,indent=2))
            results.append(result);print(json.dumps(result),flush=True)
        (output/'results.json').write_text(json.dumps(results,indent=2))

        passed=all(r['hold_residual_ns']>=0 and r['next_edge_residual_ns']>=0 and r['feedback_after_bank_ns']>=2 and r.get('periodic_setup_residual_ns',0)>=0 and r.get('periodic_hold_residual_ns',0)>=0 and r.get('conditional_ingress_setup_residual_ns',0)>=0 and r.get('conditional_ingress_hold_residual_ns',0)>=0 for r in results)
        status='pass' if passed else 'fail'
        if not passed:raise ValueError('BANK_READER_APERTURE_FAILED')
    finally:
        run.finish(outputs=[p for p in output.rglob("*") if p.is_file()],status=status)


if __name__ == "__main__":
    main()

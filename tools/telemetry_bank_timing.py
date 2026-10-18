# SPDX-License-Identifier: Apache-2.0
"""BD retained-bank reader apertures after electrical repair (zero wire RC).

Usage: telemetry_bank_timing.py MAPPING NEW_OUTPUT
Every reached periodic D pin must belong to the host snapshot or Control receipt.
The RTL reader qualifications exclude the bank settling interval. This screen
conservatively also checks a next-edge read (50 ns), and the allowed same-edge
old-bank snapshot hold. It grants no multicycle or disabled-functional-path waiver.
Routed skew/RC and full electrical acceptance remain the tape-out gate.
"""
import sys,json,subprocess,re,math
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

def main():
    mapping=Path(sys.argv[1]);output=Path(sys.argv[2]);output.mkdir(parents=True)
    status='fail'
    run=RunReceipt(output/'receipt.json',inputs=[mapping/x for x in ('netlist.v','netlist.json','mapping.json','timing-intent.json','electrical-repair/receipt.json','electrical-repair/proof.json')],tools=[Path(__file__)])
    try:
        receipt=validate_receipt(mapping)
        original=receipt_original(mapping,receipt);live=json.loads((mapping/'netlist.json').read_text())
        proof=receipt_proof(mapping,receipt);index=LeafIndex(original,live,proof['added_buffers'],proof['added_ties'])
        cells=index.after['cells'];before=index.before
        bank=[p for p,c in cells.items() if '/ca_primitive_register_bank/' in p and c['type'].startswith(SC+'dff')]
        assert bank
        ack=index.scalar('soc/ca_child_telemetry','commitAck')[1]
        base=index.scalar('soc/ca_child_telemetry','reply_ack')[1]
        def driving_ff(pin):
            while not cells[pin.rsplit('/',1)[0]]['type'].startswith(SC+'dff'):
                c=cells[pin.rsplit('/',1)[0]]
                assert c['type'].startswith(SC+'buf_')
                net=index.normalized(c['connections']['I'][0])
                sources=index.drivers[net];assert len(sources)==1
                pin=sources[0][1]
            return pin
        ack=driving_ff(ack);base=driving_ff(base)
        guard=index.scalar('soc/ca_child_telemetry/ca_primitive_output_guard','q')[1]
        feedback_input=index.boundary('soc/ca_child_telemetry/ca_child_state','in_req')
        assert len(feedback_input)==1 and feedback_input[0]['source']==guard, 'BANK_FEEDBACK_BINDING'
        feedback_sinks=feedback_input[0]['consumers']
        assert feedback_sinks, 'BANK_FEEDBACK_RECEIVERS'
        completion=index.boundary('soc/ca_child_telemetry/ca_primitive_bank_completion','common')
        assert len(completion)==2
        def source_net(pin):
            path,port=pin.rsplit('/',1)
            return index.normalized(cells[path]['connections'][port][0])
        ack_inputs=[p for p in completion if source_net(p['source'])==source_net(base)]
        assert len(ack_inputs)==1, 'BANK_COMPLETION_ACK_BINDING'
        completion_other=next(p['source'] for p in completion if p is not ack_inputs[0])
        # Trace combinational fanout to every storage input; sequential elements stop it.
        consumers=defaultdict(list)
        for p,c in cells.items():
            for pin,ns in c['connections'].items():
                if c['directions'][pin]=='input':
                    for n in ns:consumers[n].append((p,pin))
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
        cuts=keeper_cuts(index,json.loads((mapping/'netlist-audit.json').read_text()))
        sta=tool('sta');b=brace
        run.inputs+=run.capture([PROBE,*sta.input_files(),
          *[ROOT/'.tools/physical/pdk'/(SC+c+'.lib') for c in CORNERS],
          ROOT/'.tools/gf180-sram'/(SRAM+'__tt_025C_3v30.lib'),
          *[ROOT/'tools'/x for x in ('native_leaf_timing.py','control_relative_timing.py','size_ordering_guards.py','physical_tools.py','report_clock_owners.py','gf180_estimate.py','gf180_netgraph.py','native_stage_timing.py','repair_gf180_design.py','run_receipt.py')]], initial=True)
        inventory=dict(bank=bank,qualified_ack=ack,base_ack=base,periodic_targets=targets,readers=reader,feedback_sinks=feedback_sinks,
         target_domains={p:domains[p.rsplit('/',1)[0]] for p in targets},
         reader_qualification={
          'snapshot':'actual readStart = snapshot receipt fire; app bank requires !telemetryReturning; reset/recovery selects constant zero',
          'control':'MMIO command fire requires !telemetryBarrier && telemetryBankReady && !applicationCancel; unrelated commands mask native peripheralData'},
         clock_contract='work is gated service clock: same active edge, 50 ns minimum period; next-edge bound is conservative even when qualification withholds reads; actual CTS skew remains open')
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
            reset=index.scalar('soc/ca_child_telemetry','reset')[1]
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
            text=header(corner,slew)
            text+='create_clock -name arc_event -period 1000 [get_pins [list '+' '.join(b(p+'/CLK') for p in seq)+']]\nset_propagated_clock [all_clocks]\nsta::find_delays\n'
            for p in seq:text+=annotate(p+'/CLK',clkslews[p])
            text+='sta::find_delays\n'
            for i,p in enumerate(seq):
              text+='set arcs [get_timing_edges -from [exact_object pin '+b(p+'/CLK')+'] -to [exact_object pin '+b(p+'/Q')+']]\nif {[llength $arcs]!=1} {error BANK_CLK_Q_ARC}\n'
              for mode in ('min','max'):
                for edge in ('rise','fall'):
                  text+=f'row ARC {i} {mode} {edge} [get_property [lindex $arcs 0] delay_{mode}_{edge}] [get_property [exact_object pin '+b(p+'/Q')+f'] slew_{mode}_{edge}]\n'
            log=run_tcl(text,path);a=[l.split('\t') for l in log.splitlines() if l.startswith('ARC\t')]
            expected={(str(i),m,e) for i in range(len(seq)) for m in ('min','max') for e in ('rise','fall')}
            assert all(len(x)==6 for x in a), 'BANK_ARC_SHAPE'
            assert len(a)==len(expected) and {tuple(x[1:4]) for x in a}==expected, 'BANK_ARC_COVERAGE'
            delays={};qslews={}
            for x in a:
              p=seq[int(x[1])];key=x[2],x[3];d,s=map(float,x[4:])
              assert math.isfinite(d) and math.isfinite(s) and d>=0 and s>=0
              delays.setdefault(p,{})[key]=d;qslews.setdefault(p+'/Q',{})[key]=s
            return delays,qslews
        for corner in CORNERS:
          lib=library(ROOT/'.tools/physical/pdk'/(SC+corner+'.lib'))
          kinds={cells[p.rsplit('/',1)[0]]['type'] for p in targets}
          setup=max(scalar_table_max(lib[k],'setup',('rise_constraint','fall_constraint')) for k in kinds)
          hold=max(scalar_table_max(lib[k],'hold',('rise_constraint','fall_constraint')) for k in kinds)
          for slew in (.02,2.):
            rows={};hostrows={};arcs={};source_cells=list(dict.fromkeys(p.rsplit('/',1)[0] for p in (ack,base)))
            source_delays,source_slews=sequential(corner,slew,source_cells,{p:{(m,e):slew for m in ('min','max') for e in ('rise','fall')} for p in source_cells},output/f'{corner}-{slew}-source-arcs.tcl')
            bank_delays={};bank_slews={}
            for kind,sources,sinks in [('trigger',[ack],[p+'/CLK' for p in bank]),('read',[p+'/Q' for p in bank],targets),('feedback',[base],feedback_sinks)]:
              t=header(corner,slew)
              if kind=='feedback':t+='set_case_analysis 1 [exact_object pin '+b(completion_other)+']\n'
              t+='set roots {}; foreach name [list '+' '.join(map(b,sources))+'] {lappend roots [exact_object pin $name]}\n'
              t+='create_clock -name event -period 1000 -waveform {0 1} $roots\nset_propagated_clock [all_clocks]\nsta::find_delays\n'
              source_envelope=bank_slews if kind=='read' else source_slews
              for p in sources:t+=annotate(p,source_envelope[p])
              t+='sta::find_delays\n'
              if kind!='feedback':
                t+='set sinks {}; foreach name [list '+' '.join(map(b,sinks))+'] {lappend sinks [exact_object pin $name]}\nset_max_delay 100000 -from [get_clocks event] -to $sinks\nset_min_delay 0 -from [get_clocks event] -to $sinks\n'
              for mode in ('min','max'):
                for edge in ('rise','fall'):
                  if kind in ('trigger','feedback') and edge=='fall':continue
                  pairs=' '.join(b(x) for i,p in enumerate(sinks) for x in (f'{mode}:{edge}:{i}',p))
                  if kind=='feedback':
                    for i,pin in enumerate(sinks):
                      t+='leaf_ack '+' '.join(map(b,[f'{mode}:{edge}:{i}',mode,edge,base,'','',pin]))+'\n'
                  else:t+=f'control_batch {mode} any {edge} [get_clocks event] pin [list {pairs}]\n'
              for i,p in enumerate(sinks):
                for mode in ('min','max'):
                  for edge in ('rise','fall'):
                    t+=f'row SINK_SLEW {i} {mode} {edge} [get_property [exact_object pin '+b(p)+f'] slew_{mode}_{edge}]\n'
              t+='report_check_types -max_slew -max_capacitance -violators -digits 6\n'
              path=output/f'{corner}-{slew}-{kind}.tcl'
              text=run_tcl(t,path)
              if kind=='feedback':text=re.sub(r'(?m)^LEAF_ACK_(PATH|POINTS)\t',r'CONTROL_\1\t',text)
              r=[l.split('\t') for l in text.splitlines() if l.startswith('CONTROL_PATH\t')]
              expected={f'{m}:{e}:{i}':(m,e,p) for m in ('min','max') for e in
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
                assert sink_slew>=0 and (delay>=0 or kind=='read'), 'BANK_NEGATIVE_CONTROL'
                assert all(not(cells[p.rsplit('/',1)[0]]['type'].startswith((SC+'dff',SC+'lat')) and p.rsplit('/',1)[1] in ('Q','QN')) for p in ps[1:])
                delays[mode,edge,sink]=delay
              assert all(delays['min',e,p]<=v+1e-6 for (m,e,p),v in delays.items() if m=='max'), 'BANK_REVERSED_BOUNDS'
              if kind=='read': read_paths={p:{m:[float(x[5]) for x in r if x[1].startswith(m+':') and int(x[1].split(':')[-1])==i] for m in ('min','max')} for i,p in enumerate(sinks)}
              rows[kind]={m:([float(x[5]) for x in r if x[1].startswith(m+':')]) for m in ('min','max')}
              if kind=='trigger':
                a=[l.split('\t') for l in text.splitlines() if l.startswith('SINK_SLEW\t')]
                expected={(str(i),m,e) for i in range(len(bank)) for m in ('min','max') for e in ('rise','fall')}
                assert all(len(x)==5 for x in a), 'BANK_SLEW_SHAPE'
                assert len(a)==len(expected) and {tuple(x[1:4]) for x in a}==expected, 'BANK_SLEW_COVERAGE'
                cs={p:{} for p in bank}
                for x in a:
                  value=float(x[4]);assert math.isfinite(value) and value>=0, 'BANK_INVALID_SLEW'
                  cs[bank[int(x[1])]][x[2],x[3]]=value
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
                  next_edge_residual_ns=50-sum(max(.8*x,1.2*x) for x in last_segments)-setup))
            result=dict(corner=corner,slew=slew,bank_min_ns=earliest,bank_max_ns=latest,
              hold_residual_ns=min(x['hold_residual_ns'] for x in lanes),
              next_edge_residual_ns=min(x['next_edge_residual_ns'] for x in lanes),
              feedback_after_bank_ns=.8*feedback_earliest-1.2*bank_latest,wire_rc='zero',clock_skew='not included')
            (output/f'{corner}-{slew}-readers.json').write_text(json.dumps(lanes,indent=2))
            results.append(result);print(json.dumps(result),flush=True)
        (output/'results.json').write_text(json.dumps(results,indent=2))

        passed=all(r['hold_residual_ns']>=0 and r['next_edge_residual_ns']>=0 and r['feedback_after_bank_ns']>=2 for r in results)
        status='pass' if passed else 'fail'
        if not passed:raise ValueError('BANK_READER_APERTURE_FAILED')
    finally:
        run.finish(outputs=[p for p in output.rglob("*") if p.is_file()],status=status)


if __name__ == "__main__":
    main()

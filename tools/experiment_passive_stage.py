# SPDX-License-Identifier: Apache-2.0
"""A8b isolated passive-allowance experiment; never a production mapper policy.

Only RAM's standard prepare stage changes. Its whole-transform simulation
allowance becomes an unmasked inertial wire; its physical view is an alias.
Controller, capture storage/reset and markers remain unchanged. The complete
repaired graph is measured with the existing actual-leaf timing templates.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import re
import shutil
import subprocess

import control_relative_timing as r
import native_leaf_timing as leaf
import native_stage_timing as stage
from gf180_physical import ROOT, SC, sha, write_json, pdk_verify
from repair_gf180_design import flat, validate_receipt
from repair_gf180_control import require, connectivity
from physical_tools import tool
from check_control_relative_controls import fault_sdf
from check_native_stage_controls import capture_fault_pin, verdict


MODEL = "RiscayPassiveAllowanceExperiment_v1"
PASSIVE_MODEL = '''// A8b experiment: model delay represents the entire transform.
// Physical view is q=a. No reset masking, storage, clock or control behavior.
module RiscayPassiveAllowanceExperiment_v1 #(
  parameter integer WIDTH=1, OP=0, parameter time DELAY_FS=0,
  parameter [WIDTH-1:0] RESET_VALUE=0
)(input wire reset, input wire [WIDTH-1:0] a,b, output wire [WIDTH-1:0] q);
  timeunit 1fs; timeprecision 1fs;
  initial if (WIDTH<1 || OP!=0 || RESET_VALUE!=0)
    $fatal(1,"PASSIVE_ALLOWANCE_PARAMETERS");
  assign #DELAY_FS q = a;
endmodule
'''


def partition(graph, aliases=None, omitted=()):
    """Cell-pin/top-port equivalence classes, independent of Yosys net numbers."""
    aliases = aliases or {}
    def canonical(net):
        seen=set()
        while net in aliases:
            require(net not in seen, 'PASSIVE_ALIAS_CYCLE')
            seen.add(net); net=aliases[net]
        return net
    groups=defaultdict(list)
    for name,cell in graph['cells'].items():
        if name in omitted:continue
        for pin,bits in cell['connections'].items():
            for i,bit in enumerate(bits):groups[canonical(bit)].append(('pin',name,pin,i))
    for name,port in graph['ports'].items():
        for i,bit in enumerate(port['bits']):groups[canonical(bit)].append(('port',name,'',i))
    return {tuple(sorted(tags)):(net[1] if net[0]=='constant' else 'wire') for net,tags in groups.items()}


def passive_graph(original, path):
    """Clone exactly one hierarchy path and replace one adapter with a wire."""
    graph=deepcopy(original);body=graph['modules']['RiscayMcuDigital']
    parts=['soc',*path.split('.')[1:],'ca_primitive_data_delay']
    for index,part in enumerate(parts):
        require(part in body['cells'],'PASSIVE_INSTANCE_MISSING')
        cell=body['cells'][part];prior=cell['type']
        name=f'A8bExperiment_{index}_{prior}'
        require(name not in graph['modules'],'PASSIVE_MODULE_COLLISION')
        graph['modules'][name]=deepcopy(graph['modules'][prior]);cell['type']=name
        body=graph['modules'][name]
    require(set(body['ports'])=={'reset','a','b','q'},'PASSIVE_ADAPTER_PORTS')
    require(len(body['ports']['a']['bits'])==len(body['ports']['q']['bits'])==101,
            'PASSIVE_PREPARE_WIDTH')
    body['cells']={};body['ports']['q']['bits']=list(body['ports']['a']['bits'])
    body['netnames']={k:v for k,v in body.get('netnames',{}).items() if k in body['ports']}
    if 'q' in body['netnames']:body['netnames']['q']['bits']=list(body['ports']['a']['bits'])
    return graph,prove_passive_graph(original,graph,path,parts)


def prove_passive_graph(original, graph, path, parts):
    prefix='/'.join(parts)+'/'
    before,after=flat(original,'RiscayMcuDigital'),flat(graph,'RiscayMcuDigital')
    removed={n for n in before['cells'] if n.startswith(prefix)}
    require(removed and set(before['cells'])-removed==set(after['cells']),'PASSIVE_CELL_SCOPE')
    for name,c in after['cells'].items():
        require((c['type'],c['directions'])==(before['cells'][name]['type'],before['cells'][name]['directions']),
                'PASSIVE_OTHER_CELL_CHANGED')
    a=before['boundaries'][prefix+'a'];q=before['boundaries'][prefix+'q']
    aliases={out:source for source,out in zip(a,q)}
    require(partition(before,aliases,removed)==partition(after),'PASSIVE_GRAPH_CHANGED')
    return dict(instance=path,removed=sorted(removed),removed_cell_counts=dict(Counter(before['cells'][n]['type'] for n in removed)),
                unchanged_cells=len(after['cells']),width=101,
                proof='Complete pin/top-port partition after exactly q[i]=a[i]; all other leaf types/directions identical')


def write_verilog(graph, output, yosys):
    # A selected repaired instance gets cloned definitions; old definitions that
    # become unreferenced are not hardware and Yosys drops them during hierarchy.
    reachable=set()
    def visit(kind):
        if kind in reachable:return
        reachable.add(kind)
        for cell in graph['modules'][kind].get('cells',{}).values():visit(cell['type'])
    visit('RiscayMcuDigital')
    graph['modules']={k:v for k,v in graph['modules'].items() if k in reachable}
    write_json(output/'netlist.json',graph)
    source=output/'write.ys'
    def filename(path):
        name=yosys.path(path);require(not any(c in name for c in '\r\n"\\'),'PASSIVE_YOSYS_PATH')
        return '"'+name+'"'
    source.write_text('read_json '+filename(output/'netlist.json')+'\n'+
                      'hierarchy -check -top RiscayMcuDigital\nwrite_verilog -noattr '+filename(output/'netlist.v')+'\n',newline='\n')
    with (output/'write.log').open('w') as stream:
        subprocess.run(yosys.command(['-s',yosys.path(source)],timeout=110),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
    stage.roundtrip(output,output,graph,yosys,ROOT/'.tools/physical/pdk')


def passive_source(text):
    # This is an explicitly named experimental view, never a rewrite of the
    # library's versioned ControlGate semantics. Require one exact data instance.
    require(text.count('ca_primitive_data_delay (')==1,'PASSIVE_MODEL_INSTANCE')
    marker=text.index('ca_primitive_data_delay (')
    start=text.rfind('ChiselAsyncControlGate_v1',0,marker)
    require(start>=0 and ';' not in text[start:marker] and text.count('ca_primitive_data_delay (')==1,
            'PASSIVE_MODEL_INSTANCE')
    return text[:start]+MODEL+text[start+len('ChiselAsyncControlGate_v1'):]


def digital_bench(module, variant, passive, fault):
    click=variant=='click'
    capture='posedge dut.ca_primitive_payload.trigger' if click else 'posedge dut.ca_primitive_payload.closed'
    offer='out_req != out_ack' if click else 'out_req'
    # The independent transform oracle is request concatenated with zero result.
    return f'''module Testbench;
timeunit 1fs; timeprecision 1fs;
reg reset=0, in_req=0, out_ack=0, credit=0;
reg [31:0] address='x, data='x; reg wr=0; reg [3:0] mask='x;
wire in_ack,out_req; wire [31:0] oa,od,result; wire ow; wire [3:0] om;
wire [100:0] output_word={{oa,ow,od,om,result}};
reg [100:0] expected; integer captures=0, offers=0, resets=0; reg capture_expected=0;
{module} dut(.reset(reset),.in_req(in_req),.out_ack(out_ack),.in_ack(in_ack),.out_req(out_req),
 .in_bits_left(credit),.in_bits_right_address(address),.in_bits_right_write(wr),
 .in_bits_right_data(data),.in_bits_right_mask(mask),.out_bits_request_address(oa),
 .out_bits_request_write(ow),.out_bits_request_data(od),.out_bits_request_mask(om),.out_bits_result(result));
always @({capture}) if (!reset) begin
  if (!capture_expected) $fatal(1,"PASSIVE_STAGE_UNEXPECTED_CAPTURE");
  if (dut.ca_primitive_payload.d !== expected) $fatal(1,"PASSIVE_STAGE_CAPTURE_IDENTITY");
  captures=captures+1;
end
task reset_domain;
begin
 #1; reset=1; in_req=0; out_ack=0; capture_expected=0; address='x; data='x; mask='x;
 #100000000;
 if (output_word !== 0 || out_req !== 0 || in_ack !== 0) $fatal(1,"PASSIVE_STAGE_RESET");
 {'if (!$isunknown(dut.ca_primitive_payload.d)) $fatal(1,"PASSIVE_STAGE_MISSING_UNMASKED_VIEW");' if passive else ''}
 resets=resets+1; reset=0; #100000000;
 if (out_req !== out_ack || in_ack !== in_req) $fatal(1,"PASSIVE_STAGE_INVALID_OFFER");
end endtask
task token(input [31:0] a,input [31:0] d,input w,input [3:0] m,input integer stall);
begin
 address=a; data=d; wr=w; mask=m; credit=~credit;
 expected={{a,w,d,m,32'b0}}; capture_expected=1;
 #1000000; in_req={'~in_req' if click else '1'};
 wait({offer}); #1000;
 if (output_word !== expected) $fatal(1,"PASSIVE_STAGE_OUTPUT_IDENTITY");
 offers=offers+1;
 wait(in_ack == in_req);
 {'capture_expected=0; address=~a; data=~d; mask=~m;' if click else 'in_req=0; wait(!in_ack); capture_expected=0; address=~a; data=~d; mask=~m;'}
 repeat(stall) begin #1000000; if (output_word !== expected) $fatal(1,"PASSIVE_STAGE_STALLED_OUTPUT"); end
 out_ack={'out_req' if click else '1'};
 {'#100000000;' if click else 'wait(!out_req); #1000000; out_ack=0; #100000000;'}
end endtask
integer i; initial begin
 {'force dut.ca_primitive_payload.reset=0;' if fault=='storage-reset' else ''}
 reset_domain();
 for(i=0;i<24;i=i+1) token(32'h80000000^(i*32'h10204081),32'h55aa3311^(i*32'h112233),i[0],i[3:0],50+i);
 // Reset with an occupied output, then with a new request in flight.
 address=32'h12345678; data=32'h89abcdef; wr=1; mask=15;
 expected={{address,wr,data,mask,32'b0}}; capture_expected=1;
 #1000000; in_req={'~in_req' if click else '1'}; wait({offer}); #1000;
 reset_domain(); token(32'hffffffff,32'haaaaaaaa,1,15,60);
 address=32'h99999999; data=32'hffffffff; expected={{address,wr,data,mask,32'b0}};
 capture_expected=1; #1000000; in_req={'~in_req' if click else '1'}; #1000000; reset_domain();
 token(32'hdeadbeef,32'h12345678,0,3,60);
 if (captures!=27 || offers!=26 || resets!=3) $fatal(1,"PASSIVE_STAGE_ACTIVITY");
 $display("PASSIVE_STAGE_PASS captures=%0d offers=%0d resets=%0d",captures,offers,resets); $finish;
end
{'defparam dut.ca_primitive_data_delay.DELAY_FS=200000000;' if fault=='late-data' else ''}
initial begin #20000000000; $fatal(1,"PASSIVE_STAGE_TIMEOUT"); end
endmodule
'''


def bind_export(record, paths):
    require(len({p.name for p in paths})==len(paths),'PASSIVE_EXPORT_NAME_COLLISION')
    for path in paths:
        require(path.name in record['inputs'] and sha(path)==record['inputs'][path.name],
                'PASSIVE_EXPORT_SOURCE_MISMATCH_'+path.name)


def classify_digital(log, returncode, bench, path, expected):
    if expected:
        sites=[i for i,line in enumerate(bench.splitlines(),1) if f'$fatal(1,"{expected}")' in line]
        fatals=re.findall(r'^FATAL: (.+?):(\d+): (\S+)',log,re.M)
        require(returncode!=0 and len(fatals)==1 and fatals[0][2]==expected and int(fatals[0][1]) in sites and
                Path(fatals[0][0]).resolve()==path.resolve(),'PASSIVE_WRONG_FATAL_'+str(path))
    else:require(returncode==0 and log.count('PASSIVE_STAGE_PASS ')==1 and 'FATAL:' not in log,'PASSIVE_DIGITAL_FAILED_'+str(path))


def run_digital(export, output, desc, variant, record):
    compiler=shutil.which('iverilog') or str(ROOT/'.tools/iverilog/bin/iverilog.exe')
    runtime=shutil.which('vvp') or str(Path(compiler).with_name('vvp.exe'))
    require(Path(compiler).is_file() and Path(runtime).is_file(),'PASSIVE_ICARUS_MISSING')
    original=(export/(desc['module']+'.sv')).read_text()
    models=set(re.findall(r'\b(ChiselAsync\w+_v1)\s*#\s*\(',original))
    cells=[export/(name+'.sv') for name in sorted(models)]
    require(cells and all(p.is_file() for p in cells),'PASSIVE_MODEL_FILES')
    bind_export(record,[export/(desc['module']+'.sv'),*cells])
    backend=Path(compiler).parent.parent/'lib/ivl'
    compiler_files=[Path(compiler),Path(runtime),*([p for p in backend.iterdir() if p.is_file()] if backend.is_dir() else [])]
    inputs={str(p.resolve()):sha(p) for p in [export/(desc['module']+'.sv'),*cells,*compiler_files]}
    results=[]
    for passive,fault in ((False,'none'),(True,'none'),(True,'storage-reset'),(True,'late-data')):
        case=output/('passive' if passive else 'baseline')/fault;case.mkdir(parents=True)
        (case/'stage.sv').write_text(passive_source(original) if passive else original,newline='\n')
        (case/'passive.sv').write_text(PASSIVE_MODEL,newline='\n')
        bench=digital_bench(desc['module'],variant,passive,fault);(case/'testbench.sv').write_text(bench,newline='\n')
        compile_args=[compiler,'-g2012','-s','Testbench','-o','test.vvp',str(case/'stage.sv'),str(case/'passive.sv'),*map(str,cells),str(case/'testbench.sv')]
        result=subprocess.run(compile_args,cwd=case,capture_output=True,text=True,timeout=30)
        (case/'compile.log').write_text(result.stdout+result.stderr)
        require(result.returncode==0,'PASSIVE_COMPILE_FAILED_'+str(case))
        result=subprocess.run([runtime,'test.vvp'],cwd=case,capture_output=True,text=True,timeout=20)
        log=result.stdout+result.stderr;(case/'simulation.log').write_text(log)
        expected={'none':None,'storage-reset':'PASSIVE_STAGE_RESET','late-data':'PASSIVE_STAGE_CAPTURE_IDENTITY'}[fault]
        classify_digital(log,result.returncode,bench,case/'testbench.sv',expected)
        results.append(dict(passive=passive,fault=fault,status='PASS',expected=expected,command=compile_args,
                            binary_sha256=sha(case/'test.vvp'),log_sha256=sha(case/'simulation.log')))
    require(all(sha(Path(p))==h for p,h in inputs.items()),'PASSIVE_DIGITAL_INPUT_CHANGED')
    write_json(output/'results.json',dict(cases=results,inputs_sha256=inputs))
    return results


def measure(netlist, plan, index, output, campaign, sta):
    cases=[];output.mkdir()
    write_json(output/'plan.json',plan)
    for corner in (r.CORNERS if campaign else r.CORNERS[:1]):
        aperture=r.aperture(r.library(ROOT/'.tools/physical/pdk'/(SC+corner+'.lib')),plan['variant'])
        for slew in ([0.02,2.0] if campaign else [0.2]):
            results={};key=f'{corner}-s{slew}'
            for ctx in deepcopy(plan['contexts']):
                if ctx['kind'] in ('common','sequential_ack'):
                    prior=[v['event_slew_ns'] for k,v in results.items() if k.startswith(('request-','release-'))]
                    ctx['root_slew_ns']=dict(min=min(v[0] for v in prior),max=max(v[1] for v in prior))
                script=output/(key+'-'+ctx['id']+'.tcl');log=script.with_suffix('.log')
                script.write_text(leaf.script(netlist,corner,slew,plan,ctx,sta=sta),newline='\n')
                with log.open('w') as stream:
                    subprocess.run(sta.command(['-no_init','-exit',sta.path(script)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
                results[ctx['id']]=leaf.parse(log.read_text(),plan,ctx,slew,index)
            margins=r.margins(results,plan,aperture)
            case=dict(key=key,summary={k:v for k,v in margins.items() if k!='lanes'},numerical=stage.numerical_status(margins))
            write_json(output/(key+'.json'),dict(case=case,results=results,summary=margins,aperture=aperture))
            print(json.dumps(case),flush=True);cases.append(case)
    return cases


def controls(netlist,plan,index,source,output,campaign,sta):
    output.mkdir();slew=0.02 if campaign else 0.2
    saved=json.loads((source/(r.CORNERS[0]+f'-s{slew}.json')).read_text());checked=[]
    for fault in ('period','late_data_wire','late_capture'):
        results=deepcopy(saved['results']);arcs=[]
        if fault=='late_data_wire':
            query=next(q for c in plan['contexts'] if c['kind']=='data' for q in c['queries']
                       if len(saved['results']['data']['paths'][q['id']])==2)
            source_pin,sink_pin=saved['results']['data']['paths'][query['id']]
            source_name=source_pin.replace('.',r'\.');sink_name=sink_pin.replace('.',r'\.')
            sdf='(DELAYFILE (SDFVERSION "3.0") (DESIGN "RiscayMcuDigital") (DIVIDER /) (TIMESCALE 1ns)\n'
            sdf+=f'(CELL (CELLTYPE "RiscayMcuDigital") (INSTANCE) (DELAY (ABSOLUTE (INTERCONNECT {source_name} {sink_name} (1000:1000:1000) (1000:1000:1000))))))\n'
            arcs=[dict(source=source_pin,sink=sink_pin,lane=query['lane'],delay_ns=1000)]
            (output/(fault+'.sdf')).write_text(sdf,newline='\n')
        elif fault!='period':
            sdf,arcs=fault_sdf(plan,fault,capture_fault_pin(plan) if fault=='late_capture' else None)
            (output/(fault+'.sdf')).write_text(sdf,newline='\n')
        for ctx in deepcopy(plan['contexts']):
            if ctx['kind'] in ('common','sequential_ack'):
                prior=[v['event_slew_ns'] for k,v in results.items() if k.startswith(('request-','release-'))]
                ctx['root_slew_ns']=dict(min=min(v[0] for v in prior),max=max(v[1] for v in prior))
            script=output/(fault+'-'+ctx['id']+'.tcl');log=script.with_suffix('.log')
            text=leaf.script(netlist,r.CORNERS[0],slew,plan,ctx,sta=sta,period=2000 if fault=='period' else 1000)
            if fault!='period':text=text.replace('row RELATIVE_BEGIN',f'read_sdf {r.brace(sta.path(output/(fault+".sdf")))}\nrow RELATIVE_BEGIN')
            script.write_text(text,newline='\n')
            with log.open('w') as stream:
                subprocess.run(sta.command(['-no_init','-exit',sta.path(script)],timeout=55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=65)
            results[ctx['id']]=leaf.parse(log.read_text(),plan,ctx,slew,index)
        summary=r.margins(results,plan,saved['aperture'])
        if fault=='period':
            require(results==saved['results'] and summary==saved['summary'],'PASSIVE_PERIOD_DEPENDENCE')
            check=dict(fault=fault,status='IDENTICAL')
        elif fault=='late_data_wire':
            affected=[]
            for before,after in zip(saved['summary']['lanes'],summary['lanes']):
                require(before['lane']==after['lane'] and before['phase']==after['phase'],'PASSIVE_FAULT_LANES')
                if before['lane']==query['lane']:
                    require(before['maximum_input_data_lag_ns']>0 and after['maximum_input_data_lag_ns']<0 and
                            abs(before['maximum_input_data_lag_ns']-after['maximum_input_data_lag_ns']-1000)<1e-4,
                            'PASSIVE_DATA_FAULT_UNDETECTED')
                    affected.append((after['lane'],after['phase']))
                else:require(before['maximum_input_data_lag_ns']==after['maximum_input_data_lag_ns'],'PASSIVE_DATA_FAULT_SCOPE')
                require(before['zero_reuse_hold_margin_ns']==after['zero_reuse_hold_margin_ns'] and
                        before['ack_after_capture_ns']==after['ack_after_capture_ns'],'PASSIVE_DATA_FAULT_CONTROL_CHANGED')
            check=dict(fault=fault,status='EXPECTED',affected=affected)
        else:check=verdict(saved['summary'],summary,plan,fault,arcs)
        write_json(output/(fault+'.json'),dict(verdict=check,summary=summary,results=results,arcs=arcs));checked.append(check)
    return checked


def run(mapping, export, output, variant, campaign):
    require(not output.exists(),'PASSIVE_OUTPUT_EXISTS')
    receipt=validate_receipt(mapping);record=json.loads((mapping/'mapping.json').read_text())
    audit=json.loads((mapping/'netlist-audit.json').read_text());original=stage.receipt_original(mapping,receipt)
    live=json.loads((mapping/'netlist.json').read_text());proof=stage.receipt_proof(mapping,receipt)
    require(record['variant']==variant and audit['status']=='pass' and audit['netlist_sha256']==sha(mapping/'netlist.v') and
            audit['mapping_sha256']==sha(mapping/'mapping.json'),'PASSIVE_STALE_MAPPING')
    policy=json.loads((mapping/'physical-policy.json').read_text())
    require(record['physical_policy_sha256']==sha(mapping/'physical-policy.json') and
            policy['contract_sha256']==sha(mapping/'timing-intent.json'),'PASSIVE_STALE_CONTRACT')
    manifest=json.loads((mapping/'timing-intent.json').read_text())['manifest']
    path=manifest['top']+'.ca_child_ram_access.ca_child_native.ca_child_prepare'
    desc=stage.descriptor(manifest,original,record,path,variant)
    index=leaf.LeafIndex(original,live,proof['added_buffers'],proof['added_ties'])
    plan=leaf.bind_plan(r.make_plan(original,record,variant,desc),index,desc,original,leaf.keeper_cuts(index,audit))
    sta,yosys=tool('sta'),tool('yosys');pdk_verify(ROOT/'.tools/physical/pdk')
    files=[mapping/f for f in ('netlist.json','netlist.v','mapping.json','timing-intent.json','physical-policy.json','netlist-audit.json',
        'electrical-repair/receipt.json','electrical-repair/reference/netlist.json','electrical-repair/proof.json')]
    files += [Path(__file__),*[ROOT/'tools'/f for f in ('native_stage_timing.py','native_leaf_timing.py','control_relative_timing.py',
        'characterize_gf180_control_native.py','screen_gf180_control_repair.py','repair_gf180_design.py','repair_gf180_control.py',
        'gf180_physical.py','gf180_estimate.py','gf180_implement.py','characterize_gf180_liberty.py',
        'check_control_relative_controls.py','check_native_stage_controls.py')],r.PROBE,*sta.input_files(),*yosys.input_files()]
    files += [ROOT/'.tools/physical/pdk'/(SC+c+'.lib') for c in r.CORNERS]
    files += [ROOT/'.tools/physical/pdk/gf180mcu_fd_sc_mcu7t5v0.lef',ROOT/'.tools/gf180-sram'/(leaf.SRAM+'__tt_025C_3v30.lib')]
    frozen={str(p.resolve()):sha(p) for p in files}
    output.mkdir(parents=True);digital=run_digital(export,output/'digital',desc,variant,record)
    experiment,graph_proof=passive_graph(live,path)
    physical=output/'physical';physical.mkdir();write_verilog(experiment,physical,yosys)
    write_json(output/'graph-proof.json',graph_proof)
    removed=set(graph_proof['removed'])
    experimental_index=leaf.LeafIndex(original,experiment,[p for p in proof['added_buffers'] if p not in removed],
                                     [p for p in proof['added_ties'] if p not in removed])
    baseline=measure(mapping/'netlist.v',plan,index,output/'baseline',campaign,sta)
    passive=measure(physical/'netlist.v',plan,experimental_index,output/'passive',campaign,sta)
    checked=controls(physical/'netlist.v',plan,experimental_index,output/'passive',output/'controls',campaign,sta)
    require(all(c['numerical']['status']=='NONNEGATIVE_LOCAL_MARGINS' for c in baseline+passive),
            'PASSIVE_CONDITIONAL_MARGIN_NEGATIVE')
    lef=(ROOT/'.tools/physical/pdk/gf180mcu_fd_sc_mcu7t5v0.lef').read_text();areas={}
    for name,body in re.findall(r'^\s*MACRO\s+(\S+)\s*\n(.*?)^\s*END\s+\1\s*$',lef,re.M|re.S):
        size,=re.findall(r'^\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;',body,re.M)
        areas[name]=Decimal(size[0])*Decimal(size[1])
    saved=sum(areas[k]*v for k,v in graph_proof['removed_cell_counts'].items())
    require(all(sha(Path(p))==h for p,h in frozen.items()),'PASSIVE_INPUT_CHANGED');validate_receipt(mapping)
    write_json(output/'results.json',dict(status='EXPERIMENT_MEASURED',physical_qualification=False,variant=variant,instance=path,
        baseline=baseline,passive=passive,digital=digital,controls=checked,removed_cell_area_um2=str(saved),hold_repair_cells=0,
        limits=['One unseeded RAM prepare stage; no production default or library change',
                'Conditional local timing; no upstream launch or reset/wire/mismatch qualification',
                'Existing repair and loads retained; no new global repair or place/route'],
        inputs_sha256=frozen,files_sha256={str(p.relative_to(output)).replace('\\','/'):sha(p) for p in sorted(output.rglob('*')) if p.is_file()}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mapping',type=Path);parser.add_argument('export',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--variant',choices=('bd','click'),required=True);parser.add_argument('--campaign',action='store_true')
    a=parser.parse_args();run(a.mapping.resolve(),a.export.resolve(),a.output.resolve(),a.variant,a.campaign)

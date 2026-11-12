# SPDX-License-Identifier: Apache-2.0
"""Executable generated-chip backend; functional evidence, not physical signoff.

The data/storage netlist is the actual transform output. Only registered control
recipes and the explicit delay apertures receive behavioral simulation models.
Bounds are read from retained STA results, never used to size physical cells.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
import re
import subprocess
import hashlib
import math
import shutil
import sys

from physical_tools import tool
from primitives import resolve_candidate, simulation_equations
from audit_desync_protection import audit
from desync_transform import flatten_input, storage_scaffold
from desync_partition import flatten, partition
from desync_assemble import assemble


def flow_monitor(top, transform, *, data=True):
    """Check original register next-state values at real generated captures.

    This complements the folded next-state proof: it checks the transfers that
    actually occur. Uninitialized payload values are counted separately, not
    silently presented as defined-value comparisons.
    """
    from desync_graph import compose
    code=['module DesyncFlowChecks; timeunit 1ns; timeprecision 1ps;',
          'integer checked=0, undefined_values=0;',
          'initial forever begin #1000000; $display("DESYNC_PROGRESS,ns=%0.3f,checked_bits=%0d",$realtime,checked); end']
    def probe(name,bits):
        top['netnames'][name]=dict(hide_name=0,bits=bits,attributes={})
        return 'Testbench.dut.'+name
    raw=probe('desync_flow_reset',top['netnames']['resetHold/unsafe_supply']['bits'])
    for i,row in enumerate(transform['state'] if data else []):
        ports=row['original_connections'];params=row['original_parameters'];width=row['bits']
        names={p:probe(f'desync_flow_{i}_{p}',bits) for p,bits in ports.items() if p!='CLK'}
        active=lambda p: names[p] if int(params[p+'_POLARITY'],2) else '!'+names[p]
        value=names['D']
        order=('SRST','EN') if row['original_type']=='$sdffce' else ('EN','SRST')
        for p in order:
            if p not in ports:continue
            value=(f'({active(p)} ? {value} : {names["Q"]})' if p=='EN' else
                   f'({active(p)} ? {width}\'b{params["SRST_VALUE"]} : {value})')
        cancel=raw+(' || '+active('ARST') if 'ARST' in ports else '')
        prefix=f'f{i}'
        priming=int(row['falling']) # Falling S/M has an initially open slave holding the reset token.
        seed=(f"{width}'b{params['ARST_VALUE']}" if row.get('master_reset') else None)
        on_reset=(f'else if({active("ARST")}) begin {prefix}_expected={seed}; {prefix}_valid=1; end' if seed else
                  f'else if({active("ARST")}) {prefix}_valid=0;' if 'ARST' in ports else '')
        code += [f'reg [{width-1}:0] {prefix}_expected; reg {prefix}_valid=0, {prefix}_priming={priming};',
                 f'wire [{width-1}:0] {prefix}_actual={names["Q"]};',
                 f'integer {prefix}_captures=0, {prefix}_bit;',
                 f'always @({raw}'+(' or '+names['ARST'] if 'ARST' in ports else '')+') '
                 f'if({raw}) begin {prefix}_valid=0; {prefix}_priming={priming}; end {on_reset}']
        if 'ARST' in ports:
            code.append(f'always @({active("ARST")}) if({active("ARST")}) begin #0.001; '
                        f'if({names["Q"]} !== {width}\'b{params["ARST_VALUE"]}) $fatal(1,"DESYNC_RESET_VALUE:{i}"); end')
        def check():
            return (f'if({prefix}_valid && !({cancel})) begin '
                    f'if(!$isunknown({prefix}_expected)) begin '
                    f'if({prefix}_actual !== {prefix}_expected) $fatal(1,"DESYNC_REGISTER_FLOW:{i}:{row["bank"]} expected=%h actual=%h",{prefix}_expected,{prefix}_actual); '
                    f'checked=checked+{width}; {prefix}_captures={prefix}_captures+1; end '
                    f'else if({prefix}_expected === {{{width}{{1\'bx}}}}) undefined_values=undefined_values+{width}; '
                    'else begin '
                    f'for({prefix}_bit=0; {prefix}_bit<{width}; {prefix}_bit={prefix}_bit+1) begin '
                    f'if({prefix}_expected[{prefix}_bit]===1\'b0 || {prefix}_expected[{prefix}_bit]===1\'b1) begin '
                    f'if({prefix}_actual[{prefix}_bit] !== {prefix}_expected[{prefix}_bit]) '
                    f'$fatal(1,"DESYNC_REGISTER_FLOW:{i}:{row["bank"]} bit=%0d expected=%h actual=%h",{prefix}_bit,{prefix}_expected,{names["Q"]}); '
                    f'checked=checked+1; {prefix}_captures={prefix}_captures+1; end '
                    f'else undefined_values=undefined_values+1; end end end')
        if row['kind']=='latch-pair':
            master,slave=[top['cells'][p] for p in row['storage']]
            if seed and (master['connections'].get('ARST')!=ports['ARST'] or
                         master['parameters'].get('ARST_VALUE')!=params['ARST_VALUE'] or
                         int(master['parameters'].get('ARST_POLARITY','0'),2)!=int(params['ARST_POLARITY'],2)):
                raise ValueError('DESYNC_FLOW_RESET_SEED_MISMATCH')
            m=probe(f'desync_flow_{i}_master',master['connections']['EN'])
            s=probe(f'desync_flow_{i}_slave',slave['connections']['EN'])
            sample=(f'if({active("ARST")}) begin {prefix}_expected={seed}; {prefix}_valid=!{raw}; end else ' if seed else '')
            code += [f'always @(negedge {m}) begin {sample}begin {prefix}_expected={value}; {prefix}_valid=!({cancel}); end end',
                     f'always @(negedge {s}) begin #0.001; '
                     f'if(!({cancel}) && !{prefix}_valid && !{prefix}_priming) $fatal(1,"DESYNC_DUPLICATE_CAPTURE:{i}"); '
                     f'{check()} if(!({cancel})) begin {prefix}_valid=0; {prefix}_priming=0; end end']
        else:
            cell=top['cells'][row['storage'][0]]
            clock=probe(f'desync_flow_{i}_clock',cell['connections']['CLK'])
            edge='posedge' if int(cell['parameters']['CLK_POLARITY'],2) else 'negedge'
            code += [f'always @({edge} {clock}) begin {prefix}_expected={value}; {prefix}_valid=!({cancel}); #0.001; {check()} end']
        code.append(f'final $display("DESYNC_FLOW_COVERAGE,{i},{row["bank"]},{width},%0d",{prefix}_captures);')
    graph=compose(transform['partition'],('cpu',),phase_aware=True)
    arcs=graph['arcs'];width=len(arcs);initial=sum(r['tokens']<<i for i,r in enumerate(arcs))
    code += [f'reg [{width-1}:0] tokens={width}\'h{initial:x};',
             f'always @(posedge {raw}) tokens={width}\'h{initial:x};']
    for j,event in enumerate(sorted({r['source'] for r in arcs})):
        pre=sum(1<<i for i,r in enumerate(arcs) if r['target']==event)
        post=sum(1<<i for i,r in enumerate(arcs) if r['source']==event)
        label='cpu.m' if event.startswith('cpu.') else event[:-1]
        pin='acknowledgeOut' if event.startswith('cpu.') else 'enable'
        signal=probe('desync_graph_'+str(j),top['netnames']['desync_control/'+label+'/'+pin]['bits'])
        edge='posedge' if event=='cpu.rise' or event.endswith('+') else 'negedge'
        code += [f'integer events_{j}=0; realtime previous_{j}=0, min_period_{j}=1e30, max_period_{j}=0;',
                 f'always @({edge} {signal}) if({raw}===0) begin',
                 'if(!Testbench.clockEnabled) $fatal(1,"DESYNC_CAPTURE_DURING_PROGRESS_FAULT");',
                 f'if((tokens & {width}\'h{pre:x}) !== {width}\'h{pre:x}) $fatal(1,"DESYNC_GRAPH_ORDER:{event}");',
                 f'if((tokens & ~{width}\'h{pre:x} & {width}\'h{post:x}) !== 0) $fatal(1,"DESYNC_GRAPH_UNSAFE:{event}");',
                 f'tokens=(tokens & ~{width}\'h{pre:x}) | {width}\'h{post:x};',
                 f'events_{j}=events_{j}+1;',
                 f'if(events_{j}>100) begin if($realtime-previous_{j}<min_period_{j}) min_period_{j}=$realtime-previous_{j}; '
                 f'if($realtime-previous_{j}>max_period_{j}) max_period_{j}=$realtime-previous_{j}; end',
                 f'previous_{j}=$realtime; end',
                 f'final $display("DESYNC_EVENT_ACTIVITY,{event},%0d,%0.6f,%0.6f",events_{j},min_period_{j},max_period_{j});']
    gates=set();part=transform['partition']
    for row in transform['state'] if data else []:
        if row['kind']=='retained' or row['domain'] not in part['gated_domains']:continue
        phase='capture' if row['kind']=='flop-exception' else 'm' if row['falling'] else 's'
        qualifier=part['falling_gate_conditions' if row['falling'] else 'gated_domains'][row['domain']]
        gates.add((row['bank'],phase,qualifier))
    for macro in part['macros'] if data else []:
        if macro['domain'] in part['gated_domains']:gates.add((macro['bank'],'s',part['gated_domains'][macro['domain']]))
    for i,(bank,phase,qualifier) in enumerate(sorted(gates)):
        q=probe('desync_gate_qualifier_'+str(i),top['netnames'][qualifier]['bits'])
        root=probe('desync_gate_root_'+str(i),top['netnames']['desync_'+bank+'_'+phase]['bits'])
        code.append(f'always @({q}) begin #0; if(!{raw} && {root} !== 0) $fatal(1,"DESYNC_GATE_CHANGED_OPEN:{bank}:{phase}"); end')
    code+=['final $display("DESYNC_FLOW_TOTAL,defined_bits=%0d,undefined_bits=%0d",checked,undefined_values);','endmodule']
    return '\n'.join(code)


def fixture(export, policy_path, output):
    """Transform the exact clocked test fixture, preserving its configuration.

    Test fixtures expose POR directly, so the adapter aliases raw reset without
    inserting the production pin shell's qualifier. No test RTL is rewritten.
    """
    output.mkdir(parents=True,exist_ok=False)
    metadata=json.loads((export/'clocked.json').read_text())
    original=metadata['top']; y=tool('yosys'); converter=tool('sv2v')
    sources=[export/s.strip() for s in (export/'filelist.f').read_text().splitlines() if s.strip()]
    converted=output/'converted.v'
    with converted.open('w') as log:
        r=subprocess.run(converter.command(['-DSYNTHESIS',*[converter.path(s) for s in sources]],timeout=120),stdout=log,stderr=subprocess.STDOUT)
    if r.returncode:raise ValueError('DESYNC_SIM_CONVERSION_FAILED')
    generic=output/'generic.json'; script=output/'generic.ys'
    script.write_text(f'read_verilog -sv {y.path(converted)}\nhierarchy -check -top {original}\nproc\nopt\nwrite_json {y.path(generic)}\n')
    with (output/'generic.log').open('w') as log:
        r=subprocess.run(y.command(['-s',y.path(script)],timeout=120),stdout=log,stderr=subprocess.STDOUT)
    if r.returncode:raise ValueError('DESYNC_SIM_GENERIC_FAILED')
    net=json.loads(generic.read_text()); ports=deepcopy(net['modules'][original]['ports'])
    net['modules'][original]['attributes'].pop('top',None)
    net['modules']['RiscayMcuDigital']=dict(attributes={'top':'1'},ports=ports,
        cells={'soc':dict(type=original,parameters={},attributes={},port_directions={p:v['direction'] for p,v in ports.items()},
                          connections={p:v['bits'] for p,v in ports.items()})},
        netnames={p:dict(hide_name=0,bits=v['bits'],attributes={}) for p,v in ports.items()})
    net['modules']['RiscayMcuDigital']['netnames']['resetHold/unsafe_supply']=dict(hide_name=0,bits=ports['reset']['bits'],attributes={})
    policy=json.loads(policy_path.read_text()); _,aliases=flatten(net['modules'],'RiscayMcuDigital')
    # A fixture without the optional low-power gate has only the service domain.
    if aliases.get('soc/workClock')==aliases['serviceClock']:
        policy['clock_roots'].pop('soc/workClock');policy['gated_domains']={};policy['falling_gate_conditions']={}
    policy['defined_master_reset_aliases']=[a for a in policy['defined_master_reset_aliases'] if a in aliases]
    prepared=output/'prepared.json';prepared.write_text(json.dumps(flatten_input(net,policy))+'\n')
    normalized=output/'normalized.json';script=output/'normalize.ys'
    script.write_text(f'read_json {y.path(prepared)}\nopt -full\nwreduce\npeepopt\nopt -full\nwrite_json {y.path(normalized)}\n')
    with (output/'normalize.log').open('w') as log:
        r=subprocess.run(y.command(['-s',y.path(script)],timeout=120),stdout=log,stderr=subprocess.STDOUT)
    if r.returncode:raise ValueError('DESYNC_SIM_NORMALIZE_FAILED')
    normalized_net=json.loads(normalized.read_text())
    part=partition(normalized_net,policy)
    live={b for b,r in part['banks'].items() if r['bits']} | {m['bank'] for m in part['macros']}
    policy['banks']=[b for b in policy['banks'] if b in live]
    policy['bank_phases']={b:v for b,v in policy['bank_phases'].items() if b in live}
    storage,transform=storage_scaffold(normalized_net,policy)
    connected,control=assemble(storage,transform,timing_preparation=True)
    for name,value in [('input',connected),('control',control),('transform',transform),('bank-map',policy)]:
        (output/(name+'.json')).write_text(json.dumps(value)+'\n')
    return output/'input.json',output/'control.json'


def bounds(rows, instance, target, corner):
    values = [r['delay_ns'] for r in rows if r['instance'] == instance
              and r['target'] == target and r['corner'] == corner]
    if not values or any(not math.isfinite(v) or v<=0 for v in values):
        raise ValueError('DESYNC_SIM_MISSING_STA_BOUND:' + instance + '/' + target)
    return min(values), max(values)


def controller_bounds(rows, instance, target, corner):
    selected=[r for r in rows if r['instance']==instance and r['corner']==corner]
    if target=='enable':
        # Source->N already includes Source->A. Only add the inverter segment
        # after the separately delayed A keeper, using matched STA contexts.
        key=lambda r:(r['context'],r['source'],r['source_rise'],r['sense'],r['input_slew_ns'])
        a={key(r):r['delay_ns'] for r in selected if r['target']=='acknowledgeOut'}
        values=[r['delay_ns']-a[key(r)] for r in selected if r['target']=='enable' and key(r) in a]
        if not values or min(values)<=0:raise ValueError('DESYNC_SIM_ENABLE_INCREMENT')
        return min(values),max(values)
    if target=='requestOut':
        rows=[r for r in rows if r['context'].startswith('N_to_B_') or r['context']=='O_to_Bplus']
    return bounds(rows,instance,target,corner)


def prepare(source, controls, chains, transitions, output, *, corner, seed=1, top_name='RiscayMcuDigital', selection='random'):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',top_name):raise ValueError('DESYNC_SIM_TOP_NAME')
    output.mkdir(parents=True, exist_ok=False)
    net = deepcopy(json.loads(source.read_text()))
    control = json.loads(controls.read_text())
    samples = json.loads(chains.read_text())
    rows = json.loads(transitions.read_text())['rows']
    top = net['modules']['RiscayMcuDigital']
    audit(net,control['bindings'],experimental=True,generic=True)
    rng = random.Random(seed)
    if selection not in ('min','max','random'):raise ValueError('DESYNC_SIM_SELECTION')
    choose=lambda lo,hi: lo if selection=='min' else hi if selection=='max' else rng.uniform(lo,hi)
    models, evidence = [], []
    def delay(instance, target, controller=False):
        lo, hi = (controller_bounds if controller else bounds)(rows, instance, target, corner)
        selected = choose(lo, hi)
        evidence.append(dict(instance=instance, target=target, min_ns=lo, max_ns=hi, selected_ns=selected))
        return selected
    for i, binding in enumerate(control['bindings']):
        primitive, instance = binding['primitive'], binding['instance']
        recipe = resolve_candidate(primitive, binding['parameters'])
        ports = recipe['ports']
        connections = {p: top['netnames'][instance+'/'+p]['bits'] for p in ports}
        for cell in recipe['cells']:
            removed = top['cells'].pop(instance+'/'+cell['name'])
            if removed['type'] != cell['cell']:
                raise ValueError('DESYNC_SIM_RECIPE_MISMATCH:' + instance)
        name = 'DesyncModel_'+str(i)
        output_ports = [p for p, d in ports.items() if d == 'output']
        ds = {p: delay(instance, p, primitive=='RiscayDesyncQualifiedController') for p in output_ports} if primitive != 'RiscayDesyncMutex' else {}
        models.append('module '+name+'('+','.join(d+' wire '+p for p,d in ports.items())+');\n'
                      'timeunit 1ns; timeprecision 1ps;\n'+
                      simulation_equations(primitive, binding['parameters'], ds,freeze='!Testbench.clockEnabled')+'\nendmodule\n')
        net['modules'][name] = dict(attributes={'blackbox':'1'}, cells={}, netnames={},
            ports={p:dict(direction=d,bits=[j+2]) for j,(p,d) in enumerate(ports.items())})
        top['cells'][instance] = dict(type=name,parameters={},attributes={},
            port_directions=ports,connections=connections)
    for entry in control['delays']:
        bank = entry['bank']
        values = [r['delay_ns'] for r in samples if r['bank']==bank and r['corner']==corner]
        if not values or min(values)<=0:
            raise ValueError('DESYNC_SIM_MISSING_CHAIN_BOUND:'+bank)
        lo,hi = min(values),max(values); selected=choose(lo,hi)
        name='DesyncLine_'+bank
        models.append(f'module {name}(input wire reset, input wire i, output wire o);\n'
                      f'timeunit 1ns; timeprecision 1ps;\nwire delayed;\n'
                      f'assign #({selected:.9f}) delayed=reset ? 1\'b0 : i;\n'
                      'assign o=reset ? 1\'b0 : delayed;\nendmodule\n')
        ports=dict(reset='input',i='input',o='output')
        net['modules'][name]=dict(attributes={'blackbox':'1'},cells={},netnames={},
            ports={p:dict(direction=d,bits=[j+2]) for j,(p,d) in enumerate(ports.items())})
        top['cells']['desync_model_line/'+bank]=dict(type=name,parameters={},attributes={},port_directions=ports,
            connections=dict(reset=top['netnames']['resetHold/unsafe_supply']['bits'],
                             i=top['ports'].pop('desync_delay_'+bank+'_in')['bits'],
                             o=top['ports'].pop('desync_delay_'+bank+'_out')['bits']))
        evidence.append(dict(instance='matched.'+bank,target='out',min_ns=lo,max_ns=hi,selected_ns=selected))
    transform_path=source.parent/'transform.json'
    data=True
    if transform_path.exists():
        transform=json.loads(transform_path.read_text())
        data=transform.get('scope')!='timed-control-graph-only'
        models.append(flow_monitor(top,transform,data=data))
        net['modules']['DesyncFlowChecks']=dict(attributes={'blackbox':'1'},ports={},cells={},netnames={})
        top['cells']['desync_flow_checks']=dict(type='DesyncFlowChecks',parameters={},attributes={},connections={},port_directions={})
    (output/'models.sv').write_text('\n'.join(models))
    (output/'simulation.json').write_text(json.dumps(dict(scope=(
        'Behavioral generated chip; zero-delay ordinary logic; no physical qualification' if data else
        'Timed control graph only; no data/storage or physical throughput qualification'),
        corner=corner,seed=seed,selection=selection,delays=evidence,
        input_sha256={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,controls,chains,transitions)},
        reset='Behavioral immediate output clamp; release flushing/minimum POR are not qualified',
        bounds_scope='Retained production trial STA samples; fixture configurations borrow these simulation bounds, not physical timing qualification',
        mutex='Simulation-only atomic exclusion; no resolution/reliability claim'),indent=2)+'\n')
    prepared=output/'input.json';prepared.write_text(json.dumps(net)+'\n')
    y=tool('yosys'); script=output/'emit.ys'
    rename=f'rename RiscayMcuDigital {top_name}\n' if top_name!='RiscayMcuDigital' else ''
    script.write_text(f'read_json {y.path(prepared)}\n{rename}write_verilog -noattr {y.path(output/"generated.v")}\n')
    with (output/'emit.log').open('w') as log:
        result=subprocess.run(y.command(['-s',y.path(script)],timeout=120),stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:raise ValueError('DESYNC_SIM_EMIT_FAILED')
    # Icarus's lexer has a fixed token limit. Preserve wide ROM constants by
    # spelling them as a concatenation of equally valued, bounded literals.
    verilog=output/'generated.v'
    def split_literal(match):
        width=int(match[1]);digits=match[2]
        if len(digits)*4 != width:raise ValueError('DESYNC_SIM_ROM_LITERAL_WIDTH')
        return '{'+','.join(str(len(digits[i:i+256])*4)+"'h"+digits[i:i+256]
                            for i in range(0,len(digits),256))+'}'
    verilog.write_text(re.sub(r"(\d+)'h([0-9a-fxz]{4096,})",split_literal,verilog.read_text()))
    return output


def flow_coverage(text, transform):
    """Require the live inventory, while exposing unexercised state explicitly."""
    rows=re.findall(r'^DESYNC_FLOW_COVERAGE,(\d+),([^,]+),(\d+),(\d+)$',text,re.M)
    expected={i:(r['bank'],r['bits']) for i,r in enumerate(transform['state'])}
    if (len(rows)!=len(expected) or len({int(r[0]) for r in rows})!=len(rows) or
            {int(i):(bank,int(width)) for i,bank,width,_ in rows}!=expected):
        raise ValueError('DESYNC_SIM_FLOW_COVERAGE')
    totals=re.findall(r'^DESYNC_FLOW_TOTAL,defined_bits=(\d+),undefined_bits=(\d+)$',text,re.M)
    if len(totals)!=1 or int(totals[0][0])<=0:
        raise ValueError('DESYNC_SIM_FLOW_TOTAL')
    return dict(registers=len(rows),defined_bit_comparisons=int(totals[0][0]),
        undefined_bits=int(totals[0][1]),
        unexercised=[transform['state'][int(i)]['path'] for i,_,_,count in rows if int(count)==0],
        scope='Tested transfers, not complete sequential flow equivalence')


def replay(export, samples, output, *, corner, seed, selection='random', execute=True, wall_timeout=180):
    """Reuse an existing pin testbench unchanged against its generated fixture."""
    from run_receipt import RunReceipt
    from gf180_physical import ROOT
    output.mkdir(parents=True,exist_ok=False)
    sources=[export/s.strip() for s in (export/'filelist.f').read_text().splitlines() if s.strip()]
    metadata=json.loads((export/'clocked.json').read_text())
    chains=samples/'line-area-trial-r3/chain-samples.json'; transitions=samples/'transitions-r9/summary.json'
    policy=ROOT/'physical/desync/bank-map.json'
    receipt=RunReceipt(output/'receipt.json',inputs=[export/'clocked.json',export/'testbench.sv',*sources,chains,transitions,policy],
        tools=[Path(__file__),Path(sys.executable),Path(shutil.which('iverilog') or 'iverilog'),Path(shutil.which('vvp') or 'vvp'),
               *[ROOT/'tools'/p for p in ('primitives.py','desync_transform.py','desync_partition.py','desync_assemble.py','desync_network.py','desync_graph.py','run_receipt.py','audit_desync_protection.py','gf180_netgraph.py','physical_tools.py')],
               *tool('yosys').input_files(),*tool('sv2v').input_files()])
    try:
        source,control=fixture(export,policy,output/'fixture')
        model=prepare(source,control,chains,transitions,output/'model',corner=corner,seed=seed,
                      top_name=metadata['top'],selection=selection)
        macro=[s for s in sources if s.name.startswith('gf180mcu_ocd_ip_sram__')]
        compile_args=['iverilog','-g2012','-s','Testbench','-o',str(output/'sim.vvp'),str(model/'generated.v'),str(model/'models.sv'),*map(str,macro),str(export/'testbench.sv')]
        if receipt.command(compile_args,cwd=ROOT,log=output/'compile.log',timeout=180):raise ValueError('DESYNC_SIM_COMPILE_FAILED')
        coverage={}
        if execute:
            if receipt.command(['vvp',str(output/'sim.vvp')],cwd=ROOT,log=output/'simulation.log',timeout=wall_timeout):
                diagnostic='; '.join(l for l in (output/'simulation.log').read_text().splitlines() if l.startswith(('FATAL','RUN_WALL_TIMEOUT')))
                raise ValueError('DESYNC_SIM_TEST_FAILED:'+diagnostic)
            if (output/'simulation.log').read_text().splitlines().count('RISCAY_SOC_PASS')!=1:raise ValueError('DESYNC_SIM_MISSING_COMPLETION')
            coverage=flow_coverage((output/'simulation.log').read_text(),json.loads((source.parent/'transform.json').read_text()))
            (output/'flow-summary.json').write_text(json.dumps(coverage,indent=2)+'\n')
        receipt.finish(outputs=[p for p in output.rglob('*') if p.is_file() and p.name!='receipt.json'],coverage=coverage)
    except BaseException:
        if not receipt.finished:
            try:receipt.finish(outputs=[p for p in output.rglob('*') if p.is_file() and p.name!='receipt.json'],status='fail')
            except ValueError:pass # Receipt retains the failed command; preserve its original diagnostic.
        raise


if __name__ == '__main__':
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='replay':
        p=argparse.ArgumentParser(description=replay.__doc__)
        p.add_argument('export',type=Path);p.add_argument('samples',type=Path);p.add_argument('output',type=Path)
        p.add_argument('--corner',default='tt_025C_3v30');p.add_argument('--seed',type=int,default=1)
        p.add_argument('--selection',choices=('min','max','random'),default='random')
        p.add_argument('--wall-timeout',type=int,default=180)
        a=p.parse_args(sys.argv[2:]);replay(a.export,a.samples,a.output,corner=a.corner,seed=a.seed,selection=a.selection,wall_timeout=a.wall_timeout)
        sys.exit(0)
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('controls',type=Path)
    p.add_argument('chains',type=Path);p.add_argument('transitions',type=Path)
    p.add_argument('output',type=Path);p.add_argument('--corner',default='tt_025C_3v30')
    p.add_argument('--seed',type=int,default=1)
    p.add_argument('--top',default='RiscayMcuDigital')
    p.add_argument('--selection',choices=('min','max','random'),default='random')
    a=p.parse_args();prepare(a.source,a.controls,a.chains,a.transitions,a.output,corner=a.corner,seed=a.seed,top_name=a.top,selection=a.selection)

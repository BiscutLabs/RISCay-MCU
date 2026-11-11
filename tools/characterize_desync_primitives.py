# SPDX-License-Identifier: Apache-2.0
"""Loaded transistor-level samples of registry candidates; not a binding approval.

No timing cuts: the keeper feedback remains in the SPICE circuit. Stimulus times
are testbench-only and never become physical delay counts. The report contains
uncontended sequence samples, not a minimum pulse width or a hazard proof.
"""
import argparse
import json
import math
from pathlib import Path
import re
from gf180_estimate import groups, scalar
from physical_tools import tool
from primitives import REGISTRY, candidate_recipe, emit_candidate
from run_receipt import RunReceipt

ROOT = Path(__file__).resolve().parents[1]
CORNERS = [('tt_025C_3v30', 'typical', 25, 3.3), ('ss_125C_3v00', 'ss', 125, 3.0),
           ('ss_n40C_3v00', 'ss', -40, 3.0), ('ff_125C_3v60', 'ff', 125, 3.6),
           ('ff_n40C_3v60', 'ff', -40, 3.6)]


def subcircuits(text):
    return {name: pins.split() for name, pins in re.findall(r'^\.SUBCKT\s+(\S+)\s+([^\n]+)', text, re.M | re.I)}


def deck(recipe, pdk, headers, corner, slew, load, runtime):
    _, process, temperature, voltage = corner
    def path(name):
        return runtime.path(pdk / name)
    lines = ['Desync registry candidate, schematic only',
             f'.include "{path("design.ngspice")}"',
             f'.lib "{path("sm141064.ngspice")}" {process}',
             f'.include "{path("gf180mcu_fd_sc_mcu7t5v0.spice")}"',
             '.param sw_stat_global=0 sw_stat_mismatch=0', f'.temp {temperature}',
             '.options method=gear reltol=1e-5 abstol=1e-13 vntol=1e-7', f'VDD vdd 0 {voltage}']
    for name, points in recipe['stimulus'].items():
        edge_slew = slew[name] if isinstance(slew, dict) else slew
        pwl = [(0, points[0][1])]
        for (at, value), (_, old) in zip(points[1:], points):
            pwl.extend([(at, old), (at + edge_slew, value)])
        pwl=recipe.get('pwl_override',{}).get(name,pwl)
        lines.append(f'V_{name} {name} 0 PWL(' + ' '.join(f'{t}n {v*voltage}' for t, v in pwl) + ')')
    for cell in recipe['cells']:
        pins = cell['pins'] | dict(VDD='vdd', VNW='vdd', VPW='0', VSS='0')
        if set(headers[cell['cell']]) != set(pins):
            raise ValueError('DESYNC_SPICE_PIN_SET:' + cell['cell'])
        lines.append('X_' + cell['name'] + ' ' + ' '.join(pins[p] for p in headers[cell['cell']]) + ' ' + cell['cell'])
    for name, direction in recipe['ports'].items():
        if direction == 'output':
            lines.append(f'C_{name} {name} 0 {load}p')
    for i, sample in enumerate(recipe['samples']):
        for name in sample['values']:
            lines.append(f'.meas tran state_{i}_{name} FIND v({name}) AT={sample["at_ns"]}n')
    for i, (trigger, at, rise, target, target_rise) in enumerate(recipe['transitions']):
        edge, to_edge = ('RISE' if rise else 'FALL'), ('RISE' if target_rise else 'FALL')
        lines.append(f'.meas tran delay_{i} TRIG v({trigger}) VAL={voltage*.5} TD={at-1}n {edge}=1 '
                     f'TARG v({target}) VAL={voltage*.5} TD={at-1}n {to_edge}=1')
        lo, hi = (.2, .8) if target_rise else (.8, .2)
        lines.append(f'.meas tran slew_{i} TRIG v({target}) VAL={voltage*lo} TD={at-1}n {to_edge}=1 '
                     f'TARG v({target}) VAL={voltage*hi} TD={at-1}n {to_edge}=1')
    for order in recipe.get('ordering', []):
        a, b = ('RISE' if order['source_rise'] else 'FALL'), ('RISE' if order['target_rise'] else 'FALL')
        lines.append(f'.meas tran order_{order["name"]} TRIG v({order["source"]}) '
            f'VAL={voltage*order["source_fraction"]} TD={order["after_ns"]}n {a}=1 '
            f'TARG v({order["target"]}) VAL={voltage*order["target_fraction"]} TD={order["after_ns"]}n {b}=1')
    end = max(s['at_ns'] for s in recipe['samples']) + 5
    lines += [f'.tran .02n {end}n 0 .02n', '.end']
    return '\n'.join(lines) + '\n'


def measurements(text, recipe, voltage):
    values = {n: float(v) for n, v in re.findall(r'^\s*(\w+)\s*=\s*([-+0-9.eE]+)', text, re.M)}
    expected = {f'state_{i}_{name}'.lower(): bit for i, s in enumerate(recipe['samples']) for name, bit in s['values'].items()}
    needed = set(expected) | {f'{kind}_{i}' for i in range(len(recipe['transitions'])) for kind in ('delay', 'slew')}
    needed |= {'order_' + o['name'] for o in recipe.get('ordering', [])}
    if not expected.keys() <= values.keys():
        raise ValueError('DESYNC_SPICE_MEASUREMENT_MISSING')
    for name, bit in expected.items():
        v = values[name]
        if (v < .7*voltage if bit else v > .3*voltage) or not -.1*voltage <= v <= 1.1*voltage:
            raise ValueError('DESYNC_PRIMITIVE_STATE:' + name)
    if re.search(r'\b(error|failed)\b', text, re.I):
        raise ValueError('DESYNC_SPICE_ERROR')
    if not needed <= values.keys() or any(not math.isfinite(values[n]) for n in needed):
        raise ValueError('DESYNC_SPICE_MEASUREMENT_MISSING')
    times = {n: v*1e9 for n, v in values.items() if n in needed and not n.startswith('state_')}
    if any(v <= 0 for v in times.values()):
        raise ValueError('DESYNC_PRIMITIVE_NONPOSITIVE_TIMING')
    return times


def retained_wave(points, initial, voltage):
    """Check both ACK thresholds on the sampled piecewise-linear waveform."""
    trace=[(t*1e9,(1-v/voltage) if initial else v/voltage) for t,v in points]
    if any(not math.isfinite(x) for row in trace for x in row) or any(a[0]>=b[0] for a,b in zip(trace,trace[1:])):
        raise ValueError('DESYNC_C_WAVEFORM_INVALID')
    if not trace or trace[0][0]>30 or trace[-1][0]<115:
        raise ValueError('DESYNC_C_WAVEFORM_COVERAGE')
    if any(b[0]-a[0]>.020000001 for a,b in zip(trace,trace[1:]) if a[0]<115 and b[0]>30):
        raise ValueError('DESYNC_C_WAVEFORM_STEP')
    def crossing(level,start):
        for i in range(max(1,start),len(trace)):
            t,v=trace[i];pt,pv=trace[i-1]
            if t>=30 and pv<level<=v:return i,pt+(t-pt)*(level-pv)/(v-pv)
        raise ValueError('DESYNC_C_ACK_MISSING')
    first,accepted=crossing(.3,1);full,full_time=crossing(.7,first)
    if full_time>115:raise ValueError('DESYNC_C_ACK_MISSING')
    end=next(a[1]+(b[1]-a[1])*(115-a[0])/(b[0]-a[0])
             for a,b in zip(trace,trace[1:]) if a[0]<=115<=b[0])
    recognition=min(v for _,v in trace[first:full+1])
    retained=min([end,*[v for t,v in trace[full:] if t<=115]])
    if recognition<.3:raise ValueError('DESYNC_C_ACK_WITHDRAWN')
    if retained<.7:raise ValueError('DESYNC_C_KEEPER_LOST')
    return dict(accepted_ns=accepted,full_ack_ns=full_time,recognition_progress=recognition,retained_progress=retained)


def earliest_return(output, pdk, runtime, *, negative=False):
    """Return either C input at the first admitted ACK threshold, without a wait.

    A first pass measures the undisturbed output crossing; the second returns
    one input at that time, reversing even an unfinished input ramp. The
    other input stays asserted. Check the entire retention window, not just
    isolated samples. Both initial markings, arrival orders and asymmetric
    slews are included. This is schematic evidence, not variation qualification.
    """
    sources=[pdk/n for n in ('design.ngspice','sm141064.ngspice','gf180mcu_fd_sc_mcu7t5v0.spice')]
    receipt=RunReceipt(output/'receipt.json',inputs=sources,
        tools=[Path(__file__),ROOT/'tools/primitives.py',*runtime.input_files()])
    headers=subcircuits(sources[2].read_text(encoding='utf-8')); rows=[]; files=[]
    def simulate(recipe,corner,slews,load,label):
        source,log,wave=output/(label+'.spice'),output/(label+'.log'),output/(label+'.dat')
        text=deck(recipe,pdk,headers,corner,slews,load,runtime)
        extra=f'.control\nset numdgt=15\nset wr_singlescale\nrun\nwrdata {runtime.path(wave)} v(out)\nquit\n.endc'
        source.write_text(text.replace('.end\n',extra+'\n.end\n'),encoding='utf-8');files.extend((source,log))
        if receipt.command(runtime.command(['-b',runtime.path(source)],timeout=60),cwd=ROOT,log=log):
            raise ValueError('DESYNC_EARLY_RETURN_SPICE')
        data=log.read_text(encoding='utf-8')
        if re.search(r'\b(error|failed)\b',data,re.I):raise ValueError('DESYNC_EARLY_RETURN_MEASUREMENT')
        files.append(wave)
        return retained_wave([tuple(map(float,line.split())) for line in wave.read_text().splitlines()],recipe['initial_open'],corner[3])
    try:
        for corner in CORNERS:
            voltage=corner[3]
            for initial in (False,True):
                for skew in (-20,0,20):
                    for s0,s1 in ((.02,.02),(.02,2.),(2.,.02),(2.,2.)):
                        for load in (.003,.05):
                            recipe=candidate_recipe('RiscayDesyncJoin',initial_open=initial)
                            start=int(initial);new=1-start;t0=40+max(0,-skew);t1=40+max(0,skew)
                            recipe['stimulus']=dict(reset=[(0,1),(10,0)],input0=[(0,start),(t0,new)],input1=[(0,start),(t1,new)])
                            recipe['samples']=[dict(at_ns=25,values=dict(out=start)),dict(at_ns=115,values=dict(out=new))]
                            recipe['transitions']=[];slews=dict(reset=.02,input0=s0,input1=s1)
                            label=f'{corner[0]}-i{start}-k{skew}-s{s0}-{s1}-c{load}'
                            edge='FALL' if initial else 'RISE';threshold=.7 if initial else .3
                            measured=simulate(recipe,corner,slews,load,label+'-probe')
                            accepted=measured['accepted_ns']
                            if not 30<accepted<100:raise ValueError('DESYNC_EARLY_RETURN_ACK')
                            for returned,at,sl in (('input0',t0,s0),('input1',t1,s1)):
                                actual=accepted
                                fraction=min(1.,max(0.,(actual-at)/sl))
                                level=start+(new-start)*fraction
                                ramp=[(0,start),(at,start)]
                                if actual>at+sl:ramp.append((at+sl,new))
                                ramp += [(actual,level),(actual+.02,start)]
                                recipe['pwl_override']={returned:ramp}
                                if negative:
                                    next(c for c in recipe['cells'] if c['name']=='keeper')['pins']['A1']='0'
                                got=simulate(recipe,corner,slews,load,label+'-'+returned)
                                rows.append(dict(corner=corner[0],initial=start,skew_ns=skew,input_slews_ns=[s0,s1],
                                    load_pf=load,returned=returned,return_ns=actual,return_level=level,
                                    **got))
                                recipe.pop('pwl_override')
        write=(output/'early-return.json');write.write_text(json.dumps(dict(scope='Schematic earliest-return samples; no mismatch/wire qualification',rows=rows),indent=2)+'\n',encoding='utf-8');files.append(write)
        receipt.finish(outputs=files)
    except BaseException:
        if not receipt.finished:receipt.finish(outputs=[p for p in files if p.is_file()],status='fail')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--pdk', type=Path, default=ROOT/'.tools/physical/pdk')
    parser.add_argument('--negative-control', action='store_true', help='Break the controller request keeper; the state check must fail')
    parser.add_argument('--earliest-return', action='store_true', help='Return either C input immediately after its loaded ACK threshold')
    args = parser.parse_args()
    output, pdk = args.output.resolve(), args.pdk.resolve()
    output.mkdir(parents=True, exist_ok=False)
    runtime = tool('ngspice')
    if args.earliest_return:
        earliest_return(output,pdk,runtime,negative=args.negative_control)
        return
    sources = [pdk/name for name in ('design.ngspice', 'sm141064.ngspice', 'gf180mcu_fd_sc_mcu7t5v0.spice',
                                     'gf180mcu_fd_sc_mcu7t5v0__tt_025C_3v30.lib')]
    run = RunReceipt(output/'receipt.json', inputs=sources,
                     tools=[Path(__file__), ROOT/'tools/primitives.py', *runtime.input_files()])
    headers = subcircuits(sources[2].read_text(encoding='utf-8'))
    library = dict(groups(sources[3].read_text(encoding='utf-8'), 'cell'))
    results, files = [], []
    try:
        for name, primitive in REGISTRY.items():
            if primitive.candidate is None:
                continue
            for initial_open in primitive.initial_markings:
                recipe = candidate_recipe(name, initial_open=initial_open)
                if args.negative_control and name == 'RiscayDesyncController':
                    next(c for c in recipe['cells'] if c['name'] == 'request_hold')['pins']['A2'] = '0'
                tag = name + ('-open' if initial_open else '-closed')
                rtl = output/(tag+'.v'); rtl.write_text(emit_candidate(recipe), encoding='utf-8'); files.append(rtl)
                area = sum(scalar(library[c['cell']], 'area') for c in recipe['cells'])/1e6
                for corner in CORNERS:
                    for slew in (.02, 2.0):
                        for load in (.003, .05):
                            label = f'{tag}-{corner[0]}-s{slew}-c{load}'
                            source, log = output/(label+'.spice'), output/(label+'.log')
                            source.write_text(deck(recipe, pdk, headers, corner, slew, load, runtime), encoding='utf-8')
                            files += [source, log]
                            if run.command(runtime.command(['-b', runtime.path(source)], timeout=60), cwd=ROOT, log=log):
                                raise ValueError('DESYNC_SPICE_PROCESS_FAILED:' + label)
                            measured = measurements(log.read_text(encoding='utf-8'), recipe, corner[3])
                            results.append(dict(primitive=name, initial_open=initial_open, corner=corner[0],
                                input_slew_ns=slew, output_load_pf=load, cell_area_mm2=area, **measured))
        report = output/'samples.json'
        report.write_text(json.dumps(dict(status='schematic-samples-pass', scope='No layout, mismatch, minimum-pulse or graph-correspondence qualification',
                                         rows=results), indent=2)+'\n', encoding='utf-8')
        files.append(report); run.finish(outputs=files)
        print(json.dumps(dict(status='schematic-samples-pass', cases=len(results))))
    except BaseException:
        if not run.finished:
            run.finish(outputs=[p for p in files if p.is_file()], status='fail')
        raise


if __name__ == '__main__':
    main()

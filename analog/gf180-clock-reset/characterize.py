# SPDX-License-Identifier: Apache-2.0
"""Independent measurements for clock/reset schematic candidates, not signoff."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

from circuits import service_osc, supply_monitor

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
LF=BASE.parent/'gf180-lf-osc'
# Reuse the pinned PDK loader and independently checked resistor compatibility fix.
sys.path.insert(0,str(LF))
spec=importlib.util.spec_from_file_location('lf_characterize',LF/'characterize.py')
lf=importlib.util.module_from_spec(spec); sys.modules[spec.name]=lf; spec.loader.exec_module(lf)


@dataclass(frozen=True)
class Case:
    name: str
    kind: str
    mos: str='typical'
    resistor: str='typical'
    bjt: str='typical'
    temperature: int=25
    voltage: float=3.3
    load: float=100e-15
    ramp: float=.002
    phase: float=13e-9
    step: float=1e-9
    control: str=''
    profile: str='ramps'


def crossing(a,b,index,level):
    return a[0]+(b[0]-a[0])*(level-a[index])/(b[index]-a[index])


def edges(rows,index,level,rise=True):
    return [crossing(a,b,index,level) for a,b in zip(rows,rows[1:])
            if (a[index]<level<=b[index] if rise else a[index]>level>=b[index])]


def interpolated(rows,time,index):
    for a,b in zip(rows,rows[1:]):
        if a[0]<=time<=b[0]:
            return a[index]+(b[index]-a[index])*(time-a[0])/(b[0]-a[0])
    raise ValueError('INCOMPLETE_WAVEFORM')


def check_clock(rows,c):
    if not rows or rows[-1][0]<9.999e-6:
        raise ValueError('INCOMPLETE_WAVEFORM')
    rises=edges(rows,1,c.voltage/2)
    falls=edges(rows,1,c.voltage/2,False)
    off=5e-6+c.phase
    windows=((3e-6,4.9e-6),(8e-6,9.9e-6))
    periods=[]
    for lo,hi in windows:
        window=[t for t in rises if lo<t<hi]
        if len(window)<8: raise ValueError('NO_SUSTAINED_CLOCK')
        cycles=[b-a for a,b in zip(window,window[1:])]
        if max(cycles)/min(cycles)>1.01: raise ValueError('UNSTABLE_CLOCK')
        periods.extend(cycles)
        if not 8e6 <= (len(window)-1)/(window[-1]-window[0]) <= 20e6:
            raise ValueError('FREQUENCY_CONTRACT')
    for start in (2.001e-6,7.001e-6):
        after=[t for t in rises if t>=start]
        if not after or after[0]-start>100e-6: raise ValueError('STARTUP_CONTRACT')
    if any(off+max(periods)*1.5<t<7e-6 for t in rises): raise ValueError('CLOCK_NOT_STOPPED')
    for a,b in zip(rows,rows[1:]):
        if 6e-6<a[0]<6.9e-6 and abs(a[1])>.1*c.voltage: raise ValueError('STOPPED_CLOCK_NOT_LOW')
    # Includes first and final pulses of both sessions. POR assertion is separate.
    widths=[next((f-r for f in falls if f>r),math.inf) for r in rises]
    if not widths or min(widths)<20e-9: raise ValueError('RUNT_HIGH_PULSE')
    lows=[next((r-f for r in rises if r>f),math.inf) for f in falls]
    if min(lows)<20e-9: raise ValueError('RUNT_LOW_PULSE')
    startup=[next(t for t in rises if t>=start)-start for start in (2.001e-6,7.001e-6)]
    return dict(hz=1/(sum(periods)/len(periods)),minimum_high_ns=min(widths)*1e9,
                minimum_low_ns=min(lows)*1e9,startup_ns=max(startup)*1e9,
                active_current_a=-lf.integrate(rows,5,3e-6,4.9e-6)/1.9e-6,
                stopped_current_a=-lf.integrate(rows,5,6e-6,6.9e-6)/.9e-6)


def monitor_times(c):
    # Three complete supply ramps exercise release, brownout and restart.
    up=c.ramp; down=up+.002; bottom=down+c.ramp
    again=bottom+.002; top=again+c.ramp; end=top+.002
    return up,down,bottom,again,top,end


def check_monitor(rows,c):
    # A raw startup pulse below the usable rail must never satisfy the 5 ms
    # qualification counter. Check from 0.5 V, including slow-ramp low-voltage
    # behavior outside the normal digital operating range.
    start=None; unsafe_duration=0
    for row in rows:
        if .5<row[4]<3.0 and row[1]>.5*row[4]:
            if start is None: start=row[0]
            unsafe_duration=max(unsafe_duration,row[0]-start)
            if unsafe_duration>=.002: raise ValueError('UNSAFE_STARTUP_PULSE')
        else: start=None
    if c.profile=='plateau':
        end=c.ramp+.01
        if not rows or rows[-1][0]<end*.99999: raise ValueError('INCOMPLETE_WAVEFORM')
        steady=[r for r in rows if c.ramp+.001<r[0]]
        if c.voltage>=3.3:
            if min(r[1]/r[4] for r in steady)<.9: raise ValueError('PLATEAU_DID_NOT_RELEASE')
        elif max(r[1]/r[4] for r in steady)>.1:
            raise ValueError('UNSAFE_PLATEAU_RELEASE')
        return dict(supply_current_a=-lf.integrate(rows,5,end-.001,end)/.001,
                    unsafe_startup_high_us=unsafe_duration*1e6)
    if c.profile=='dip':
        if not rows or rows[-1][0]<.012: raise ValueError('INCOMPLETE_WAVEFORM')
        falls=[t for t in edges(rows,1,1.5,False) if .005<t<.006]
        if not falls or falls[0]>.005101: raise ValueError('BROWNOUT_RESPONSE')
        for lo,hi,high in ((.003,.005,True),(.0052,.006,False),(.009,.012,True)):
            values=[r[1]/r[4] for r in rows if lo<r[0]<hi]
            if not values or (min(values)<.9 if high else max(values)>.1): raise ValueError('DIP_STATE')
        return dict(response_us=(falls[0]-.005)*1e6)
    up,down,bottom,again,top,end=monitor_times(c)
    if not rows or rows[-1][0]<end*.99999: raise ValueError('INCOMPLETE_WAVEFORM')
    # Classify only where powered; a zero-volt pin is not a meaningful logic level.
    signal=[(r[0],r[1]-.5*r[4]) for r in rows if r[4]>1.8]
    rise=edges(signal,1,0); fall=edges(signal,1,0,False)
    up_edges=[t for t in rise if t<down]
    down_edges=[t for t in fall if down<t<again]
    restart=[t for t in rise if t>again]
    # Raw comparator chatter during reference startup is permitted ONLY before
    # the digital 5 ms continuous-good hold can expire. Recovery must be clean.
    if not up_edges or len(down_edges)!=1 or len(restart)!=1 or any(up+.001<t<down for t in fall):
        raise ValueError(f'SUPPLY_TRANSITIONS rise={rise} fall={fall}')
    if up_edges[-1]>up+.001: raise ValueError('REFERENCE_STARTUP')
    release=interpolated(rows,restart[0],4)
    trip=interpolated(rows,down_edges[0],4)
    if not 3.1<=release<=3.3: raise ValueError(f'RELEASE_VOLTAGE:{release}')
    if not 3.0<=trip<=3.2: raise ValueError(f'BROWNOUT_VOLTAGE:{trip}')
    if not .025<=release-trip<=.18: raise ValueError('HYSTERESIS_CONTRACT')
    steady=[r for r in rows if top+.001<r[0]<end]
    if min(r[1]/r[4] for r in steady)<.9: raise ValueError('POWER_GOOD_NOT_HIGH')
    if max(r[2] for r in steady)-min(r[2] for r in steady)>.002:
        raise ValueError('UNSTABLE_REFERENCE')
    low=[r for r in rows if bottom+.001<r[0]<again]
    if max(r[1]/r[4] for r in low)>.1: raise ValueError('BROWNOUT_NOT_HELD')
    return dict(release_v=release,brownout_v=trip,hysteresis_v=release-trip,
                initial_transitions=len(up_edges)+len([t for t in fall if t<down]),
                unsafe_startup_high_us=unsafe_duration*1e6,
                reference_v=sum(r[2] for r in steady)/len(steady),
                supply_current_a=-lf.integrate(rows,5,top+.001,end)/.001)


def deck(c,paths):
    if c.kind=='clock':
        off=5e-6+c.phase
        enable=f'0 0 2u 0 2.001u {c.voltage} {off} {c.voltage} {off+1e-9} 0 7u 0 7.001u {c.voltage}'
        if c.control=='disabled': enable='0 0'
        sources=f'''VDD vdd 0 pwl(0 0 1u {c.voltage})
VR rst_n 0 pwl(0 0 1.5u 0 1.501u {c.voltage})
VE enable 0 pwl({enable})
XDUT vdd 0 rst_n enable clk riscay_service_osc_gf180
CLOAD clk 0 {c.load}
'''
        vectors='v(clk) v(enable) v(rst_n) v(vdd) i(vdd)'
        end=10e-6; step=c.step
    else:
        up,down,bottom,again,top,end=monitor_times(c)
        supply=f'0 0 {up} 3.6 {down} 3.6 {bottom} 2.4 {again} 2.4 {top} 3.6'
        if c.profile=='plateau':
            supply=f'0 0 {c.ramp} {c.voltage}'; end=c.ramp+.01
        elif c.profile=='dip':
            supply='0 0 .0001 3.3 .005 3.3 .005001 2.7 .006 2.7 .0061 3.3'; end=.0121
        sources=f'VDD vdd 0 pwl({supply})\nXDUT vdd 0 good riscay_supply_monitor_gf180\nCLOAD good 0 {c.load}\n'
        vectors='v(good) v(xdut.vref) v(xdut.pbias) v(vdd) i(vdd)'
        step=min(c.ramp/2000,1e-5) if c.profile!='dip' else 1e-6
        if c.profile=='plateau': step=min(c.ramp/100,1e-5)
    return f'''RISCay clock/reset schematic experiment {c.name}
.include "{paths['design.ngspice'].as_posix()}"
.lib "{paths['sm141064.ngspice'].as_posix()}" {c.mos}
.lib "{paths['sm141064.ngspice'].as_posix()}" res_{c.resistor}
.lib "{paths['sm141064.ngspice'].as_posix()}" bjt_{c.bjt}
.param sw_stat_global=0 sw_stat_mismatch=0
.temp {c.temperature}
.options reltol=1e-4 abstol=1e-14 vntol=1e-7 gmin=1e-15 method=gear maxord=2
.include "dut.spice"
{sources}
.control
set wr_singlescale
set wr_vecnames
set numdgt=12
set num_threads=1
save {vectors}
tran {step} {end} 0 {step}
wrdata wave.txt {vectors}
quit
.endc
.end
'''


def run(c,paths,out):
    folder=out/c.name; folder.mkdir()
    circuit=service_osc() if c.kind=='clock' else supply_monitor()
    if c.control=='no-hysteresis':
        circuit='\n'.join(line for line in circuit.splitlines() if not line.startswith('Xhysteresis'))+'\n'
    (folder/'dut.spice').write_text(circuit)
    (folder/'tb.spice').write_text(deck(c,paths))
    result=dict(case=asdict(c),passed=False,netlist_sha256=hashlib.sha256(circuit.encode()).hexdigest())
    try:
        with (folder/'ngspice.log').open('w') as log:
            p=subprocess.run(['ngspice','-b','tb.spice'],cwd=folder,stdout=log,stderr=subprocess.STDOUT,timeout=120)
        log=(folder/'ngspice.log').read_text()
        if p.returncode or re.search(r'\b(error|fatal)\b|timestep too small|run simulation\(s\) aborted',log,re.I):
            raise ValueError('SIMULATOR_FAILURE')
        rows=[tuple(map(float,line.split())) for line in (folder/'wave.txt').read_text().splitlines()[1:]]
        result.update(check_clock(rows,c) if c.kind=='clock' else check_monitor(rows,c))
        result['passed']=True
    except (OSError,ValueError,subprocess.TimeoutExpired) as e:
        result['error']=str(e)
    (folder/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(c.name,json.dumps({k:v for k,v in result.items() if k not in ('case','netlist_sha256')}),flush=True)
    return result


def campaign(suite):
    if suite=='smoke': return [Case('clock','clock'),Case('monitor','monitor')]
    if suite=='controls': return [Case('disabled','clock',control='disabled'),Case('no-hysteresis','monitor',ramp=.1,control='no-hysteresis')]
    if suite=='clock':
        cases=[Case(f'{m}-{r}-{t}-{v}','clock',mos=m,resistor=r,temperature=t,voltage=v)
               for m in ('typical','ss','ff','fs','sf') for r in ('typical','ss','ff')
               for t in (-40,25,125) for v in (3.0,3.3,3.6)]
        cases += [Case(f'stop-phase-{i}','clock',phase=i*5e-9) for i in range(20)]
        cases += [Case('light-load','clock',load=20e-15),Case('half-step','clock',step=.5e-9)]
        return cases
    if suite=='monitor':
        cases=[Case(f'{m}-{r}-{b}-{t}','monitor',mos=m,resistor=r,bjt=b,temperature=t)
               for m in ('typical','ss','ff','fs','sf') for r in ('typical','ss','ff')
               for b in ('typical','ss','ff') for t in (-40,25,125)]
        cases += [Case('slow-ramp','monitor',ramp=.1),Case('very-slow-ramp','monitor',ramp=1)]
        return cases
    if suite=='supply-events':
        corners=[('typical','typical','typical',25),('ss','ss','ff',125),('ff','ff','ss',-40),('sf','typical','ss',-40)]
        cases=[Case(f'{m}-{r}-{b}-{t}-{v}-{ramp}','monitor',mos=m,resistor=r,bjt=b,temperature=t,
                    voltage=v,ramp=ramp,profile='plateau') for m,r,b,t in corners
               for v in (2.7,3.0,3.3) for ramp in (1e-5,.002,.1,1)]
        cases += [Case(f'dip-{m}-{r}-{b}-{t}','monitor',mos=m,resistor=r,bjt=b,temperature=t,profile='dip') for m,r,b,t in corners]
        return cases
    raise ValueError(suite)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=['smoke','clock','monitor','supply-events','controls'],default='smoke')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=3)
    args=parser.parse_args()
    output=args.output.resolve()
    if not output.is_relative_to(ROOT/'build') or output.exists(): parser.error('Use a fresh directory under build/')
    if not 1<=args.jobs<=8: parser.error('jobs must be 1..8')
    if not shutil.which('ngspice'): parser.error('ngspice is required')
    paths=lf.models(False); output.mkdir(parents=True)
    resistor_checks=lf.check_resistor(paths,output/'resistor-check','ngspice')
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results=list(pool.map(lambda c:run(c,paths,output),campaign(args.suite)))
    passed=all(r['passed'] for r in results)
    if args.suite=='controls':
        passed=results[0].get('error')=='NO_SUSTAINED_CLOCK' and results[1].get('error')=='HYSTERESIS_CONTRACT'
    report=dict(scope='SCHEMATIC_ONLY_NOT_PHYSICAL_SIGNOFF',suite=args.suite,passed=passed,
                ngspice=subprocess.check_output(['ngspice','--version'],text=True),
                generator_sha256=lf.sha(BASE/'circuits.py'),checker_sha256=lf.sha(Path(__file__)),
                prepared_model_sha256=lf.sha(paths['sm141064.ngspice']),
                pdk_sources=json.loads((LF/'sources.json').read_text()),resistor_checks=resistor_checks,results=results)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return 0 if passed else 1


if __name__=='__main__': sys.exit(main())

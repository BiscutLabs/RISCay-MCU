# SPDX-License-Identifier: Apache-2.0
"""Exploratory SPICE runner; reports measurements, never qualification."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[1]
sys.path.insert(0,str(BASE.parent/'gf180-lf-osc'))
from characterize import models, rising, integrate
from circuits import service_osc, supply_monitor


def run(kind, name, mos='typical', resistor='typical', temp=25, voltage=3.3, ramp=1e-5, resistance=240000, gain=9.5):
    path=ROOT/'build/clock-reset-probes'/name
    path.mkdir(parents=True,exist_ok=False)
    paths=models(False)
    (path/'dut.spice').write_text(service_osc(resistance) if kind=='osc' else supply_monitor(gain=gain))
    source = f'VDD vdd 0 pwl(0 0 {ramp} {voltage})\n'
    if kind=='osc':
        source = f'VDD vdd 0 pwl(0 0 1u {voltage})\n'
        source += (f'VR rst_n 0 pwl(0 0 1.5u 0 1.501u {voltage})\n'
                   f'VE enable 0 pwl(0 0 2u 0 2.001u {voltage} 3.513u {voltage} 3.514u 0 4.5u 0 4.501u {voltage})\n'
                   'XOSC vdd 0 rst_n enable clk riscay_service_osc_gf180\nCLOAD clk 0 100f\n')
        vectors='v(clk) v(enable) v(rst_n) v(vdd) i(vdd)'
        control='tran .5n 6u 0 .5n'
    else:
        source+='XDUT vdd 0 good riscay_supply_monitor_gf180\nCLOAD good 0 100f\n'
        vectors='v(good) v(xdut.vref) v(xdut.pbias) v(vdd) i(vdd) v(xdut.e1) v(xdut.sense2)'
        control='tran 1u 2m 0 1u'
    deck=f'''RISCay exploratory {kind}
.include "{paths['design.ngspice'].as_posix()}"
.lib "{paths['sm141064.ngspice'].as_posix()}" {mos}
.lib "{paths['sm141064.ngspice'].as_posix()}" res_{resistor}
.lib "{paths['sm141064.ngspice'].as_posix()}" bjt_typical
.param sw_stat_global=0 sw_stat_mismatch=0
.temp {temp}
.options reltol=1e-4 abstol=1e-14 vntol=1e-7 gmin=1e-15 method=gear maxord=2
.include "dut.spice"
{source}
.control
set wr_singlescale
set wr_vecnames
set numdgt=12
save {vectors}
{control}
wrdata wave.txt {vectors}
quit
.endc
.end
'''
    (path/'tb.spice').write_text(deck)
    with (path/'ngspice.log').open('w') as log:
        p=subprocess.run(['ngspice','-b','tb.spice'],cwd=path,stdout=log,stderr=subprocess.STDOUT,timeout=120)
    if p.returncode or not (path/'wave.txt').exists():
        raise RuntimeError((path/'ngspice.log').read_text()[-2000:])
    rows=[tuple(map(float,line.split())) for line in (path/'wave.txt').read_text().splitlines()[1:]]
    if kind=='osc':
        edges=rising([row for row in rows if 2.5e-6<row[0]<3.4e-6],voltage/2)
        hz=(len(edges)-1)/(edges[-1]-edges[0]) if len(edges)>2 else 0
        result=dict(hz=hz,current=-integrate(rows,5,2.5e-6,3.4e-6)/.9e-6,off_current=-integrate(rows,5,4e-6,4.4e-6)/.4e-6)
    else:
        result=dict(good=rows[-1][1],vref=rows[-1][2],pbias=rows[-1][3],current=-rows[-1][5],e1=rows[-1][6],sense2=rows[-1][7])
    (path/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(name,json.dumps(result),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('kind',choices=['osc','por'])
    p.add_argument('name')
    p.add_argument('--mos',default='typical')
    p.add_argument('--resistor',default='typical')
    p.add_argument('--temp',type=float,default=25)
    p.add_argument('--voltage',type=float,default=3.3)
    p.add_argument('--ramp',type=float,default=1e-5)
    p.add_argument('--resistance',type=float,default=240000)
    p.add_argument('--gain',type=float,default=9.5)
    run(**vars(p.parse_args()))

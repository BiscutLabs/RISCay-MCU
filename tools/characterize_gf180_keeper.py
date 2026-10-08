# SPDX-License-Identifier: Apache-2.0
"""Transistor-level PVT checks of the complete mapped asymmetric C keepers.

Five matching std-cell/SRAM corners, two input ramps, two output loads. Gray
walks cover input ordering and both retained histories. Unextracted schematic
evidence only; metastability/variation and routed feedback remain separate.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import subprocess
from check_gf180_cells import vectors
from gf180_estimate import linux
from gf180_physical import ROOT, pdk_verify, sha, write_json

CORNERS=[("tt", "typical",25,3.3),("ss_hot","ss",125,3.0),("ss_cold","ss",-40,3.0),
         ("ff_hot","ff",125,3.6),("ff_cold","ff",-40,3.6)]

def spice_net(name):
    return name.replace('[','_').replace(']','').replace("1'b0","0").replace("1'b1","vdd")

def deck(binding,pdk,corner,ramp,load,path):
    _,model,temp,voltage=corner
    portorders={m[0]:m[1].split() for m in re.findall(r'^\.SUBCKT\s+(\S+)\s+([^\r\n]+)',
        (pdk/"gf180mcu_fd_sc_mcu7t5v0.spice").read_text(),re.M|re.I)}
    text=f'GF180 static keeper {binding["module"]}\n'
    text+=f'.include "{linux(pdk/"design.ngspice")}"\n.lib "{linux(pdk/"sm141064.ngspice")}" {model}\n'
    text+=f'.include "{linux(pdk/"gf180mcu_fd_sc_mcu7t5v0.spice")}"\n'
    text+=f'.param sw_stat_global=0 sw_stat_mismatch=0\n.temp {temp}\nVDD vdd 0 {voltage}\n'
    for c in binding["cells"]:
        pins=dict(c["pins"],VDD="vdd",VNW="vdd",VPW="0",VSS="0")
        text+='X'+c["name"]+' '+" ".join(spice_net(pins[p]) for p in portorders[c["cell"]])+" "+c["cell"]+"\n"
    text+=f'COUT q 0 {load}p\n'
    events=vectors(binding)
    inputs=[]
    for p in binding["ports"]:
        if p["direction"]!="input": continue
        for i in range(p["width"]): inputs.append((p["name"],i,p["width"]))
    for name,bit,width in inputs:
        net=name if width==1 and name=="reset" else f'{name}_{bit}'
        waveform=[f'0 {voltage*((events[0][0][name]>>bit)&1)}']
        previous=(events[0][0][name]>>bit)&1
        for index,(values,expected) in enumerate(events[1:],1):
            new=(values[name]>>bit)&1
            if new!=previous:
                waveform.extend([f'{index*100}n {previous*voltage}',f'{index*100+ramp}n {new*voltage}'])
            previous=new
        text+=f'V_{net} {net} 0 PWL('+" ".join(waveform)+")\n"
    end=len(events)*100
    text+=f'.tran 0.1n {end}n\n'
    for i,(_,expected) in enumerate(events):
        text+=f'.meas tran q{i} FIND v(q) AT={i*100+90}n\n'
        if i and expected!=events[i-1][1]:
            direction="RISE" if expected else "FALL"
            text+=f'.meas tran t{i} WHEN v(q)={voltage/2} {direction}=1 TD={i*100}n\n'
        elif i:
            text+=f'.meas tran low{i} MIN v(q) FROM={i*100}n TO={i*100+90}n\n'
            text+=f'.meas tran high{i} MAX v(q) FROM={i*100}n TO={i*100+90}n\n'
    text+='.end\n'; path.write_text(text)
    return events

def experiment(binding,pdk,corner,ramp,load,out):
    name=f'{binding["module"]}-{corner[0]}-r{ramp}-c{load}'
    path=out/(name+".spice"); events=deck(binding,pdk,corner,ramp,load,path)
    process=subprocess.run(["wsl","--cd",linux(pdk),"-e","ngspice","-b",linux(path)],capture_output=True,text=True,timeout=90)
    log=process.stdout+process.stderr; (out/(name+".log")).write_text(log)
    values={k:float(v) for k,v in re.findall(r'^([a-z]+\d+)\s*=\s*([-+\deE.]+)',log,re.M)}
    if process.returncode or len(values)<len(events): raise ValueError("SPICE_INCOMPLETE_"+name)
    delays=[]; voltage=corner[3]
    for i,(_,expected) in enumerate(events):
        q=values[f'q{i}']
        if not (-0.1*voltage<=q<=1.1*voltage and (q>0.9*voltage if expected else q<0.1*voltage)):
            raise ValueError(f'KEEPER_FUNCTION_{name}_vector{i}_{q}')
        if f't{i}' in values:
            delay=values[f't{i}']*1e9-(i*100+ramp/2); delays.append(delay)
        elif i:
            if (expected and values[f'low{i}']<0.9*voltage) or (not expected and values[f'high{i}']>0.1*voltage):
                raise ValueError(f'KEEPER_GLITCH_{name}_vector{i}')
    if not delays: raise ValueError("NO_KEEPER_ACTIVITY")
    # Include reset assertion/release in the maximum; guards require quiescence
    # through reset. Min bound on reset is not a handshake requirement.
    return dict(name=name,minimum_ns=min(delays),maximum_ns=max(delays),vectors=len(events),
                deck_sha256=sha(path),log_sha256=sha(out/(name+".log")))

def run(mapping,pdk,out,jobs,quick):
    pdk_verify(pdk); out.mkdir(parents=True,exist_ok=False)
    bindings=[b for b in json.loads((mapping/"mapping.json").read_text())["bindings"] if "AsymmetricC" in b["model"]]
    cases=[(b,c,r,l) for b in bindings for c in CORNERS for r in ([0.2] if quick else [0.02,2.0]) for l in ([0.02] if quick else [0.003,0.05])]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results=list(pool.map(lambda x:experiment(x[0],pdk,x[1],x[2],x[3],out),cases))
    write_json(out/"results.json",dict(status="schematic-pass",corners=CORNERS,cases=results,
        minimum_ns=min(x["minimum_ns"] for x in results),maximum_ns=max(x["maximum_ns"] for x in results),
        mapping_sha256=sha(mapping/"mapping.json"),pdk_lock_sha256=sha(ROOT/"physical/gf180/pdk-lock.json"),
        limits="No extracted wire parasitics, statistical mismatch, metastability qualification or full-chip timing"))
    print(f'PASS {len(results)} keeper PVT cases; min={min(x["minimum_ns"] for x in results):.3f} ns max={max(x["maximum_ns"] for x in results):.3f} ns')

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("mapping",type=Path); p.add_argument("output",type=Path)
    p.add_argument("--pdk",type=Path,default=ROOT/".tools/physical/pdk"); p.add_argument("--jobs",type=int,default=4)
    p.add_argument("--quick",action="store_true"); a=p.parse_args(); run(a.mapping,a.pdk,a.output,a.jobs,a.quick)

# SPDX-License-Identifier: Apache-2.0
"""Exercise every exact adapter against independent Boolean/storage oracles.

Uses upstream GF180 functional models, never behavioral ChiselAsync cells.
Timing is tested separately; zero-delay truth-table success is not qualification.
"""
import argparse
import json
from pathlib import Path
import random
import subprocess
from gf180_physical import ROOT, pdk_verify, sha, write_json

def vectors(b):
    k=b["parameters"]; model=b["model"]; width=k.get("WIDTH",1)
    rng=random.Random(0x180); q=0; result=[]
    inputs={p["name"]:0 for p in b["ports"] if p["direction"]=="input"}
    def put(values, expected):
        inputs.update(values); result.append((dict(inputs),expected))
    reset_value=k.get("RESET_VALUE",0)
    q=reset_value
    put({"reset":1},reset_value)
    if "ClosingLatch" in model: inputs["closed"]=1
    after_reset=reset_value
    if "ControlGate" in model: after_reset=((1<<width)-1) if k["OP"]==1 else 0
    elif "And_v1" in model: after_reset=int(k["INVERT"]==(1<<k["INPUTS"])-1)
    put({"reset":0},after_reset)
    if "AsymmetricC" in model:
        # Gray walk changes one normalized input at a time. Forward/reverse
        # rounds visit every state from both retained histories; then reset
        # while requests are present and exercise release.
        counts=[k[x] for x in ("COMMON","RISING","FALLING")]
        total=sum(counts)
        walks=list(range(1<<total))+list(reversed(range(1<<total)))
        for code in walks*3:
            raw=code^(code>>1); normalized={}; shift=0; v={}
            for port,count in zip(("common","rising","falling"),counts):
                value=(raw>>shift)&((1<<count)-1); shift+=count
                normalized[port]=value
                v[port]=value^k[port.upper()+"_INVERT"]
            set_bit=normalized["common"]==(1<<counts[0])-1 and normalized["rising"]==(1<<counts[1])-1
            hold=bool(normalized["common"] or normalized["falling"])
            q=int(set_bit or (q and hold)); put(v,q)
        put({"reset":1},0)
        # Do not assume the state remains zero after reset if set is asserted.
        put({"reset":0},int(set_bit))
    elif "EventRegister" in model or "PhaseRegister" in model or "ClosingLatch" in model:
        for i in range(64):
            data=rng.getrandbits(width)
            if "ClosingLatch" in model:
                put({"d":data,"closed":0},data); put({"closed":1},data)
                put({"d":data^((1<<width)-1)},data)
            elif "PhaseRegister" in model:
                put({"trigger":0},q); q=1-q; put({"trigger":1},q)
            else:
                put({"trigger":0,"d":data},q); q=data; put({"trigger":1},q)
                put({"d":data^((1<<width)-1)},q)
        put({"reset":1},reset_value)
    else:
        for i in range(128):
            v={p:rng.getrandbits(next(x["width"] for x in b["ports"] if x["name"]==p)) for p in inputs if p!="reset"}
            v["reset"]=int(i%13==0)
            if "ControlGate" in model:
                q=v["a"] if k["OP"]==0 else (~v["a"]&((1<<width)-1)) if k["OP"]==1 else v["a"]|v["b"]
            elif "Xor" in model: q=v["a"]^v["b"]
            else: q=int((v["d"]^k["INVERT"])==(1<<k["INPUTS"])-1)
            put(v,reset_value if v["reset"] else q)
    return result

def run(mapping,pdk):
    pdk_verify(pdk)
    record=json.loads((mapping/"mapping.json").read_text())
    tests=[]; blocks=[]; count=0
    for b in record["bindings"]:
        # Deduplicate modules shared between variants outside this test runner.
        declarations=[f'{"reg" if p["direction"]=="input" else "wire"} [{p["width"]-1}:0] {p["name"]};' for p in b["ports"]]
        body=["module test_"+b["module"]+"(output reg done=0);",*declarations,
            b["module"]+" dut ("+", ".join(f'.{p["name"]}({p["name"]})' for p in b["ports"])+");", "initial begin"]
        for index,(values,expected) in enumerate(vectors(b)):
            count+=1
            body+= ["; ".join(f'{name}={next(p["width"] for p in b["ports"] if p["name"]==name)}\'h{value:x}' for name,value in values.items())+"; #20;",
                f'if(q !== {next(p["width"] for p in b["ports"] if p["name"]=="q")}\'h{expected:x}) $fatal(1,"{b["module"]} vector {index} got %h",q);']
        body += ["done=1; end endmodule"]
        blocks.append("\n".join(body)); tests.append(b["module"])
    tb="`timescale 1ns/1ps\n"+"\n".join(blocks)+"\nmodule tb;\n"
    tb+=f'wire [{len(tests)-1}:0] done;\n'+"\n".join(f'test_{n} t{i}(done[{i}]);' for i,n in enumerate(tests))
    tb+='\ninitial begin wait(&done); $display("GF180_FUNCTIONAL_PASS"); $finish; end\ninitial begin #100000; $fatal(1,"TIMEOUT"); end\nendmodule\n'
    (mapping/"cells-test.sv").write_text(tb)
    files=[pdk/"primitives.v",pdk/"gf180mcu_fd_sc_mcu7t5v0.v",mapping/"riscay_gf180_cells.v",mapping/"cells-test.sv"]
    subprocess.run(["iverilog","-g2012","-DFUNCTIONAL","-s","tb","-o",str(mapping/"cells-test.vvp"),*map(str,files)],check=True,timeout=60)
    result=subprocess.run(["vvp",str(mapping/"cells-test.vvp")],capture_output=True,text=True,timeout=60)
    (mapping/"cells-test.log").write_text(result.stdout+result.stderr)
    if result.returncode or "GF180_FUNCTIONAL_PASS" not in result.stdout: raise ValueError(result.stdout+result.stderr)
    write_json(mapping/"cells-functional.json",dict(status="pass",specializations=len(tests),vectors=count,
        mapping_sha256=sha(mapping/"mapping.json"),scope="upstream functional cell models; no delay qualification"))
    print(f"PASS {len(tests)} adapters, {count} vectors")

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("mapping",type=Path)
    p.add_argument("--pdk",type=Path,default=ROOT/".tools/physical/pdk"); a=p.parse_args(); run(a.mapping,a.pdk)

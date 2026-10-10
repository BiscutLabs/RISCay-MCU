# SPDX-License-Identifier: Apache-2.0
"""Independent unchanged oracles against actual RAM-owner and reset RTL mutations."""
import argparse,copy,hashlib,json,re,shutil
from pathlib import Path
from check_i2c_wiring_controls import hashes,run
from check_admission_controls import replace_pin
from check_ram_source_export import validate_ram_source


def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError("RAM_CONTROL_MUTATION_SHAPE:"+old)
    return text.replace(old,new)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--sources",type=Path,required=True,help="JSON with bd/click native, publication_native, reservation, publication and reset fixture paths")
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();sources=json.loads(args.sources.read_text())
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False);results={};commands=[]
    def record():
        (out/"results.json").write_text(json.dumps(results,indent=2)+"\n")
        (out/"commands.json").write_text(json.dumps(commands,indent=2)+"\n")
    def simulate(label,source,native,mutation=None,seed=1):
        source=Path(source).resolve()
        if out.is_relative_to(source):raise ValueError("RAM_CONTROLS_OVERLAP_SOURCE")
        before=hashes(source);case=out/label
        shutil.copytree(source/"export" if native else source,case)
        if native:shutil.copy2(source/f"seed-{seed}/testbench.sv",case/"testbench.sv")
        manifest=json.loads((case/"contract.json").read_text())["manifest"]
        rtl=case/(manifest["top"]+".sv")
        oracle=hashlib.sha256((case/"testbench.sv").read_bytes()).hexdigest()
        if mutation:rtl.write_text(mutation(rtl.read_text(),manifest),encoding="utf-8")
        files=[str((case/x.strip()).resolve()) for x in (case/"filelist.f").read_text().splitlines() if x.strip()]
        compiled,log=run(["iverilog","-g2012","-s","Testbench","-o","control.vvp",*files,"testbench.sv"],case,"control-compile.log",commands)
        assert compiled["exit_code"]==0,log[-4000:]
        simulated,log=run(["vvp","control.vvp"],case,"control-simulation.log",commands)
        assert (simulated["exit_code"]==0)==(mutation is None),log[-4000:]
        if mutation:
            assert any(x in log for x in ("RAM_SOURCE_","APPLICATION_RESET_","HANDSHAKE_ORDER","PROTOCOL_",
                "TIMING_LONG_HOLD_FORK","DATA_HOLD")),log[-4000:]
            assert "DEADLINE" not in log and "TIMEOUT" not in log,log[-4000:]
        else:assert ("CA_TEST_PASS" in log if native else "RISCAY_SOC_PASS" in log),log[-4000:]
        assert hashlib.sha256((case/"testbench.sv").read_bytes()).hexdigest()==oracle,"RAM_ORACLE_CHANGED"
        assert hashes(source)==before,"ORIGINAL_RAM_EVIDENCE_CHANGED"
        results[label]=dict(compile=compiled,simulation=simulated,oracle_sha256=oracle,
            oracle_kind="native-behavior-and-timing" if native else "integrated-behavior",
            rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest(),source=str(source),seed=seed if native else None)
        record();print(label,"PASS",flush=True)
    for variant in ("bd","click"):
        s=sources[variant]
        node=json.loads((Path(s["native"])/"export/contract.json").read_text())["manifest"]["design"]
        validate_ram_source(node);bad_nodes=[]
        for field,value in (("module","ClockedOwner"),("capacity",2)):
            bad=copy.deepcopy(node);bad[field]=value;bad_nodes.append(bad)
        for i in range(4):
            for field,value in (("signed",True),("width",2),("lsb",1),("source","wrong")):
                bad=copy.deepcopy(node);bad["channels"][i]["layout"][0][field]=value;bad_nodes.append(bad)
        for i,p in enumerate(node["primitives"]):
            bad=copy.deepcopy(node);bad["primitives"][i]["reset"]="reset" if p["reset"]!="reset" else "eligibility_reset";bad_nodes.append(bad)
            if "DELAY_FS" in p["parameters"]:
                bad=copy.deepcopy(node);bad["primitives"][i]["parameters"]["DELAY_FS"]="0";bad_nodes.append(bad)
        for i in range(len(node["timing"])):
            bad=copy.deepcopy(node);bad["timing"].pop(i);bad_nodes.append(bad)
        for bad in bad_nodes:
            try:validate_ram_source(bad)
            except ValueError:pass
            else:raise AssertionError("RAM_SOURCE_METADATA_MUTATION_ACCEPTED")
        results[variant+"-metadata"]=dict(rejected=len(bad_nodes));record()
        def pin(text,m,cell,pin,value):
            c=next(p for p in m["design"]["primitives"] if p["id"]==cell)
            return replace_pin(text,c["rtl_path"].rsplit(".",1)[1],pin,value)
        simulate(variant+"-native-baseline",s["native"],True)
        def reset_retained_reservation(text,m):
            child=next(c for c in m["design"]["children"] if c["id"]=="reservation")
            instance=child["contract"]["rtl_path"].rsplit(".",1)[1]
            return replace_pin(text,instance,"reset","reset | applicationReset")
        simulate(variant+"-retained-reservation-reset",s["native"],True,reset_retained_reservation)
        simulate(variant+"-eligibility-reset-bypass",s["native"],True,
                 lambda text,m:pin(text,m,"eligibility","reset","reset"))
        simulate(variant+"-arm-after-grant",s["native"],True,
                 lambda text,m:pin(text,m,"eligibility","trigger","grant_ack"))
        if variant=="bd":
            simulate(variant+"-reservation-ack-bypass",s["native"],True,
                     lambda text,m:pin(text,m,"acknowledge_guard","a","ca_child_reservation.in_ack"))
        else:
            def guard_bypass(text,m):
                instance=next(p["rtl_path"].rsplit(".",1)[1] for p in m["design"]["primitives"] if p["id"]=="output_guard")
                pattern=r"(ChiselAsyncControlGate_v1\s+#\(\s*\.DELAY_FS\()221200001(\),(?:\s*\.\w+\([^)]*\),?)+\s*\)\s+"+re.escape(instance)+r"\s*\()"
                changed,count=re.subn(pattern,lambda x:x[1]+"1"+x[2],text)
                if count!=1:raise ValueError("RAM_GUARD_MUTATION_SHAPE")
                return changed
            simulate(variant+"-grant-guard-bypass",s["native"],True,guard_bypass)
        simulate(variant+"-publication-native-baseline",s["publication_native"],True)
        if variant=="click":
            mutation=lambda text,m:pin(text,m,"effect_ready_nb","a","1'b1")
        else:
            def mutation(text,m):
                # Keep reserve, decision, word drainage and grant RTZ conditions;
                # bypass only selected publication in the actual C-element input.
                c=next(p for p in m["design"]["primitives"] if p["id"]=="retirement")
                guard=next(p["rtl_path"].rsplit(".",1)[1] for p in m["design"]["primitives"] if p["id"]=="request_guard")
                expr="{reserved,"+guard+".q,1'b1,wordDrained,(!grant_req & !grant_ack)}"
                return replace_pin(text,c["rtl_path"].rsplit(".",1)[1],"rising",expr)
        simulate(variant+"-publication-bypass",s["publication_native"],True,mutation)
        if variant=="click":
            # Preserve the exact skew/oracle which exposed the selector race.
            # Removing only the phase qualification must reproduce that failure.
            simulate("click-selection-baseline",s["publication_native"],True,seed=4)
            simulate("click-decision-selection-guard-bypass",s["publication_native"],True,
                lambda text,m:pin(text,m,"decision_pending","a","decision_req"),seed=4)
        simulate(variant+"-reservation-baseline",s["reservation"],False)
        simulate(variant+"-cpu-grant-bypass",s["reservation"],False,
                 lambda text,m:replace_once(text,"(~fabric_ramOperation | fabric_io_ramSource_grant_valid",
                                                "(~fabric_ramOperation | 1'b1"))
        simulate(variant+"-reset-debt-bypass",s["reservation"],False,
                 lambda text,m:replace_once(text,"ramResetDebt <= 1'h1;","ramResetDebt <= 1'h0;"))
        simulate(variant+"-publication-baseline",s["publication"],False)
        simulate(variant+"-early-debt-release",s["publication"],False,
                 lambda text,m:replace_once(text,"~(ramResetDebt_previousSafe & ramSourceEmpty & ~cpuResetActive) & ramResetDebt;",
                                                "cpuResetActive & ramResetDebt;"))
        simulate(variant+"-reset-baseline",s["reset"],False)
        def reset_mutation(text,m,second=False):
            pattern=r"(always @\(posedge serviceClock or posedge applicationResetRequest\) begin[^\n]*\n\s*)if \(applicationResetRequest\)"
            matches=list(re.finditer(pattern,text))
            if len(matches)!=1:raise ValueError("RAM_RESET_MUTATION_SHAPE")
            if second:
                return re.sub(pattern,lambda x:x[1]+"if (reset || (applicationResetRequest && release_0 == 0))",text)
            # The register shifts left; only its two HIGH bits produce two edges.
            return replace_once(text,"release_0 <= 8'hFF;","release_0 <= 8'hC0;")
        simulate(variant+"-short-reset-hold",s["reset"],False,reset_mutation)
        simulate(variant+"-second-reset-ignored",s["reset"],False,
                 lambda text,m:reset_mutation(text,m,True))
    print("ALL_RAM_SOURCE_CONTROLS_PASS",flush=True)

if __name__=="__main__":main()

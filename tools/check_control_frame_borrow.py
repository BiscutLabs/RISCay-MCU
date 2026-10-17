# SPDX-License-Identifier: Apache-2.0
"""Compile the retained-bank regression and exact ownership faults in both variants.

Uses freshly emitted *BorrowedControlFixture exports. Original wire, reset,
native-acceptance and final-drain assertions remain present in every case.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from check_program_return_fatals import fatal_sites, classify_fatal
from check_frame_integration import child, pins


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError("BORROW_CONTROL_SHAPE:" + old)
    return text.replace(old, new)


def campaign(sources, output):
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status="RUNNING", cases={}, inputs={})
    helpers = [Path(__file__).resolve(), Path(__file__).with_name("check_program_return_fatals.py").resolve(),
               Path(__file__).with_name("check_frame_integration.py").resolve(),
               Path(__file__).with_name("check_frame_capture_controls.py").resolve()]
    report["helpers"] = {str(p): sha(p) for p in helpers}
    executables = {name: Path(shutil.which(name) or "").resolve() for name in ("iverilog", "vvp")}
    if not all(p.is_file() for p in executables.values()):
        raise ValueError("BORROW_EXECUTABLE_MISSING")
    compiler_files = set(executables.values())
    backend = executables["iverilog"].parent.parent / "lib" / "ivl"
    if backend.is_dir():
        compiler_files.update(p for p in backend.iterdir() if p.is_file())
    report["compiler_sha256"] = {str(p): sha(p) for p in compiler_files}
    def save():
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    def run(command, case, name):
        result = subprocess.run(command, cwd=case, capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        path = case / name
        path.write_text(log, encoding="utf-8")
        return dict(exit_code=result.returncode, timed_out=False, command=command, log=str(path), sha256=sha(path)), log
    variants = set()
    try:
        report["versions"] = {name: run([str(path), "-V"], output, name + "-version.log")[0]
                              for name, path in executables.items()}
        if any(v["exit_code"] for v in report["versions"].values()):
            raise ValueError("BORROW_COMPILER_VERSION")
        for source in sources:
            source = source.resolve()
            manifest = json.loads((source / "contract.json").read_text())["manifest"]["design"]
            top = manifest["module"]
            variant = {"BdBorrowedControlFixture": "bd", "ClickBorrowedControlFixture": "click"}[top]
            if variant in variants:
                raise ValueError("BORROW_DUPLICATE_VARIANT")
            variants.add(variant)
            files = (source / "filelist.f").read_text().splitlines()
            if any(not (source / f).resolve().is_relative_to(source) for f in files):
                raise ValueError("BORROW_SOURCE_PATH")
            inputs = [source / f for f in files] + [source / "testbench.sv", source / "contract.json", source / "filelist.f"]
            report["inputs"].update({str(p): sha(p) for p in inputs})
            raw = (source / (top + ".sv")).read_text(encoding="utf-8")
            test = (source / "testbench.sv").read_text(encoding="utf-8")
            # Keep all four identical monitors, with explicit constant indices,
            # so the exact fatal-site parser need not guess compiler genblk names.
            loop=re.search(r"for\(genvar bank=0;bank<4;bank=bank\+1\) begin\n(.*?)\n    end",test,re.S)
            if loop is None or loop[1].count('FRAME_BORROW_NATIVE_BANK_RETURN_ORDER')!=1 or loop[1].count('always @')!=1:
                raise ValueError("BORROW_BANK_MONITOR_SHAPE")
            expanded="\n".join(re.sub(r"\bbank\b",str(i),loop[1]) for i in range(4))
            test=test[:loop.start()]+expanded+test[loop.end():]
            if variant=="bd":
                sender=child(manifest,"control_command_bridge")
                sender_rtl=(source/(sender["module"]+".sv")).read_text(encoding="utf-8")
                if not re.search(r"\breg\s+ack_stages_1\s*;",sender_rtl):
                    raise ValueError("BORROW_ACK_OBSERVER_SHAPE")
                # The ordinary BD tag may retire before the Control reply. Hold
                # only an already observed high ACK through its falling return
                # to exercise the legal late-observation R/new-D ordering.
                test=replace(test,'$display("RISCAY_SOC_PASS");',"""
holdHostCommands=1;
command(9);native_return();command(10);native_return();
if(mailboxCount!=2 || admissions!=4) $fatal(1,"FRAME_BORROW_OVERLAP_PRECONDITION");
@(negedge serviceClock);#1;holdNativeCommand=1;holdHostCommands=0;
wait(dispatches==3);
fork
  begin
    wait(dut.ca_child_control_command_bridge.ack_stages_1===1'b1);
    force dut.ca_child_control_command_bridge.ack_stages_1=1'b1;
  end
  begin @(negedge serviceClock);#1;holdNativeCommand=0;end
join
wait(nativeAcceptances==3);
wait(!dut.fabric_controlOutstanding);
wait(!nativeCommandRequest && !nativeCommandAcknowledge);
if(retirements!=2 || !retirementPending || commandSenderIdle)
  $fatal(1,"FRAME_BORROW_LATE_ACK_OBSERVATION_PRECONDITION");
@(negedge serviceClock);#1;release dut.ca_child_control_command_bridge.ack_stages_1;
control_done();
if(dispatches!=4 || nativeAcceptances!=4 || retirements!=4 || liveBanks || mailboxCount)
  $fatal(1,"FRAME_BORROW_OVERLAP_COMPLETION_COUNTS");
$display("RISCAY_SOC_PASS");""")
            test = replace(test, "always @(posedge observedWorkClock) if(!reset) begin", """
integer borrowSameEdge=0;
always @(posedge observedWorkClock) if(!reset) begin
  if(dut.fabric_hostRetiring !== retirementPending ||
     (retirementPending && dut.fabric_hostRetiringBank !== retirementBank))
    $fatal(1,"FRAME_BORROW_OWNER_STATE");
  if(observedBorrowRetire && hostDispatched) borrowSameEdge=borrowSameEdge+1;
""")
            test = replace(test, '$display("RISCAY_SOC_PASS");', """
if(borrowSameEdge==0) $fatal(1,"FRAME_BORROW_NO_SAME_EDGE_R_D");
$display("FRAME_BORROW_SAME_EDGE:%0d",borrowSameEdge);
$display("RISCAY_SOC_PASS");""")
            test = replace(test, "// Finish native capture while deliberately retaining the old head.", """
// Exercise application reset with the owner clock running and native acceptance
// still stalled, as well as the original stopped-work reset episodes.
@(negedge serviceClock);#1;stopWorkClock=0;applicationReset=1;
repeat(12) @(negedge serviceClock);
if(!currentReset || !retirementPending || nativeAcceptances || retirements)
  $fatal(1,"FRAME_BORROW_RUNNING_RESET_PRECONDITION");
applicationReset=0;repeat(12) @(negedge serviceClock);
// Finish native capture while deliberately retaining the old head.""")
            state = re.search(r"fabric_hostRetiring <= (fabric__\w+) \| ~fabric_hostRetire & fabric_hostRetiring;", raw)
            if state is None:
                raise ValueError("BORROW_STATE_SHAPE")
            original, dispatch = state[0], state[1]
            cases = {
                "original": (raw, None),
                "clear-wins-same-edge": (replace(raw, original,
                    f"fabric_hostRetiring <= ({dispatch} | fabric_hostRetiring) & ~fabric_hostRetire;"), "FRAME_BORROW_OWNER_STATE"),
                "application-reset-clears-owner": (replace(raw, original,
                    f"fabric_hostRetiring <= ({dispatch} | ~fabric_hostRetire & fabric_hostRetiring) & ~cpuResetActive;"), "FRAME_BORROW_OWNER_STATE"),
                "wrong-retiring-tag": (replace(raw,
                    "fabric_hostRetiringBank <= fabric_hostFrames_first_bank;",
                    "fabric_hostRetiringBank <= 2'h0;"), "FRAME_BORROW_OWNER_STATE"),

            }
            control=child(manifest,"control")
            expression=pins(raw,control["rtl_path"].rsplit(".",1)[1],control["module"])["command_bits_frame_bytes_0"]
            # Use the actual selected byte input, not a compiler temporary number.
            if re.fullmatch(r"\w+",expression):
                declaration=re.search(r"\bwire\s+\[7:0\]\s+"+re.escape(expression)+r"\s*=\s*([^;]+);",raw)
                if declaration is None:raise ValueError("BORROW_PAYLOAD_ALIAS_SHAPE")
                expression=re.sub(r"\s+","",declaration[1])
            spaced=re.compile(r"\s*".join(re.escape(c) for c in expression))
            matches=list(spaced.finditer(raw))
            if len(matches)!=1:raise ValueError("BORROW_PAYLOAD_PIN_SHAPE")
            m=matches[0]
            cases["descriptor-selects-payload"]=(raw[:m.start()]+expression.replace("fabric_hostRetiringBank","fabric_hostFrames_first_bank")+raw[m.end():],
                "FRAME_BORROW_NATIVE_ACCEPTANCE_IDENTITY" if variant=="click" else "FRAME_BORROW_NATIVE_RTZ_PAYLOAD_CHANGED")
            early,count=re.subn(r"(fabric_hostRetire\s*=\s*fabric_hostRetiring\s*)&\s*_ca_child_control_command_bridge_in_ready",r"\1",raw)
            if count!=1:raise ValueError("BORROW_READY_SHAPE:"+str(count))
            cases["early-retirement"]=(early,"FRAME_ADMISSION_HEAD_RETIRE_IDENTITY")
            cases={label:(top+".sv",text,expected) for label,(text,expected) in cases.items()}
            if variant=="bd":
                completion=child(child(manifest,"i2c"),"bank_completion")
                path=completion["module"]+".sv";body=(source/path).read_text()
                primitive=next(p for p in completion["primitives"] if p["id"]=="completion0")
                instance=primitive["rtl_path"].rsplit(".",1)[1]
                ps=pins(body,instance,primitive["model"],primitive["parameters"])
                selected=ps["common"].split(",",1)[1].removesuffix("}")
                from check_frame_capture_controls import replace_pin
                for label,value in (("receipt-only","{receiptAck_0,receiptAck_0}"),("native-only","{"+selected+","+selected+"}")):
                    cases["completion-"+label]=(path,replace_pin(body,instance,"common",value),"FRAME_BORROW_NATIVE_BANK_RETURN_ORDER")
                old="assign bankAck_0 = "+ps["q"]+";"
                if ps["q"]=="bankAck_0":
                    changed=replace_pin(body,instance,"q","mutant_join_q")
                    changed,count=re.subn(r"(module FourPhaseFrameCompletion\s*\([^;]*?\);)",r"\1\nwire mutant_join_q;",changed)
                    if count!=1:raise ValueError("BORROW_COMPLETION_HEADER_SHAPE")
                    changed=replace(changed,"endmodule","assign bankAck_0 = receiptAck_0 & "+selected+";\nendmodule")
                else:
                    changed=replace(body,old,"assign bankAck_0 = receiptAck_0 & "+selected+";")
                cases["completion-and-return"]=(path,changed,"FRAME_BORROW_NATIVE_BANK_RETURN_ORDER")
            for label, (modified_file, rtl, expected) in cases.items():
                case = output / (variant + "-" + label)
                case.mkdir()
                for f in files:
                    target = case / f
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source / f, target)
                (case / modified_file).write_text(rtl, encoding="utf-8")
                (case / "testbench.sv").write_text(test, encoding="utf-8")
                record = dict(expected=expected, source=str(source), source_sha256={f: sha(case / f) for f in [*files, "testbench.sv"]})
                report["cases"][case.name] = record
                record["compile"], log = run([str(executables["iverilog"]), "-g2012", "-s", "Testbench", "-o", "borrow.vvp", *files, "testbench.sv"], case, "compile.log")
                if record["compile"]["exit_code"]:
                    raise ValueError("BORROW_COMPILE:" + case.name + ":" + log[-1000:])
                record["binary_sha256"] = sha(case / "borrow.vvp")
                record["simulation"], log = run([str(executables["vvp"]), "borrow.vvp"], case, "simulation.log")
                if expected:
                    record["sites"] = fatal_sites(test, [expected])
                    record["actual_fatals"] = classify_fatal(record["compile"], record["simulation"], log, record["sites"])
                elif record["simulation"]["exit_code"] or "RISCAY_SOC_PASS" not in log or not re.search(r"FRAME_BORROW_SAME_EDGE:[1-9]\d*", log) or re.search(r"FATAL|ERROR", log):
                    raise ValueError("BORROW_POSITIVE:" + case.name + ":" + log[-1000:])
                if any(sha(case / f) != h for f, h in record["source_sha256"].items()) or sha(case / "borrow.vvp") != record["binary_sha256"]:
                    raise ValueError("BORROW_EXECUTED_BYTES_CHANGED")
                record["status"] = "PASS"
                save()
                print(case.name, "PASS", flush=True)
        if variants != {"bd", "click"} or len(report["cases"]) != 15:
            raise ValueError("BORROW_INCOMPLETE_CATALOGUE")
        if any(sha(Path(p)) != h for group in (report["inputs"], report["helpers"], report["compiler_sha256"]) for p, h in group.items()):
            raise ValueError("BORROW_INPUT_CHANGED")
        report["status"] = "PASS"
    except BaseException as error:
        report.update(status="FAILED", error=repr(error))
        raise
    finally:
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    campaign(args.source, args.out)

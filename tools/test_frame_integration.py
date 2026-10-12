# SPDX-License-Identifier: Apache-2.0
"""Unit tests and actual emitted RTL controls for the frame integration policy.

The source controls record sensitivity of the validator, not simulation or
physical qualification. Original exports are read-only; mutated text is saved.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

from check_frame_integration import (child, clean, compact, driver, initial_policy,
                                     pins, projected_tree, statement_tree,
                                     validate_frame_integration, frame_receipt_probe)
from test_frame_receipt import receipt_node, registers


class FrameIntegrationTests(unittest.TestCase):
    def test_driver_rejects_additional_scalar_partial_and_force_writers(self):
        good = "wire [7:0] value = source;"
        self.assertEqual(driver(good, "value", "source"), "value")
        for extra in ("assign value = 8'h0;", "always_comb value = source;",
                      "always @(posedge clock) value <= source;", "initial value = 0;",
                      "assign value[0] = 1'b0;", "always_comb {value,other} = 0;",
                      "always_comb {{value}} = 0;", "always_comb value += 1;",
                      "always_comb value >>>= 1;", "always_comb value <<<= 1;",
                      "always_comb value++;", "always_comb --value;", "initial force value = 0;"):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "^FRAME_INTEGRATION_"):
                driver(good + extra, "value", "source")

    def test_projection_keeps_every_ancestor_condition(self):
        good = projected_tree(statement_tree("begin if(reset) q<=0; else if(load) q<=d; end"), {"q"})
        extra = projected_tree(statement_tree("begin if(enable)begin if(reset)q<=0;else if(load)q<=d;end end"), {"q"})
        unrelated = projected_tree(statement_tree("begin other<=3;if(reset)q<=0;else if(load)q<=d;end"), {"q"})
        self.assertNotEqual(good, extra)
        self.assertEqual(good, unrelated)
        for malformed in ("begin q<=d; end extra", "begin if(load) q=d;end", "begin q<=d;"):
            with self.assertRaisesRegex(ValueError, "^FRAME_INTEGRATION_"):
                statement_tree(malformed)

    def test_named_instance_pins_preserve_expressions(self):
        good = "Model instance (\n .in(a & (b | c)),\n .out(q)\n);"
        self.assertEqual(pins(good, "instance", "Model"), {"in":"a&(b|c)", "out":"q"})
        for bad in (good + good, good.replace(".out(q)", ".in(q)"), good.replace("Model", "Different")):
            with self.assertRaisesRegex(ValueError, "^FRAME_INTEGRATION_"):
                pins(bad, "instance", "Model")

    def test_initializer_guards_are_closed(self):
        good = """initial begin
`ifdef INIT_RANDOM_PROLOG_
`INIT_RANDOM_PROLOG_
`endif
`ifdef RANDOMIZE_REG_INIT
for(logic [0:0] i=1'h0; i<1'h1; i+=1'h1)begin _RANDOM[i]=`RANDOM;end
q=_RANDOM[1'h0][0];
`endif
if(reset)begin q=1'h0;end
end // initial
"""
        initial_policy(good, {"q":"1'h0"}, "reset")
        for bad in (good.replace("if(reset)", "if(other)"), good.replace("q=1'h0", "q=1'h1"),
                    good.replace("q=_RANDOM", "if(enable) q=_RANDOM"),
                    good.replace("`ifdef RANDOMIZE_REG_INIT", "`ifndef RANDOMIZE_REG_INIT"),
                    good + "initial q=0;"):
            with self.assertRaisesRegex(ValueError, "^FRAME_INTEGRATION_"):
                initial_policy(bad, {"q":"1'h0"}, "reset")

    def test_unrelated_design_probe_is_unchanged(self):
        manifest = {"top":"Unrelated", "design":{"module":"Unrelated", "children":[]}}
        self.assertIsNone(validate_frame_integration(manifest, {}, Path("unused")))
        self.assertEqual(frame_receipt_probe("module test; endmodule", manifest, {}, Path("unused")), "module test; endmodule")
        manifest["top"] = "FourPhaseSoc"
        with self.assertRaisesRegex(ValueError, "FRAME_INTEGRATION_MISSING_I2C"):
            validate_frame_integration(manifest, {}, Path("unused"))

    def test_standalone_receipt_injects_fifteen_bindings(self):
        for click in (False, True):
            node = receipt_node(click)
            manifest = {"top":"Top", "design":node}
            source = "task check; begin\nend endtask"
            result = frame_receipt_probe(source, manifest, {node["rtl_path"]:dict(registers=registers())}, Path("unused"))
            self.assertEqual(result.count("FRAME_RECEIPT_BINDING:"), 15)
            self.assertIn("Top.receipt.in_bits_resetEpoch", result)


def actual_controls(directory, saved):
    directory = directory.resolve(); saved = saved.resolve(); saved.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "contract.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))["manifest"]
    top = manifest["design"]; target = child(top,"i2c"); native = child(target,"native")
    receipt = child(target,"frame_bridge")
    paths = {"top":Path(top["module"] + ".sv"), "target":Path(target["module"] + ".sv"),
             "native":Path(native["module"] + ".sv"),
             "assertion":Path("verification/assert") / (target["module"] + "_Verification_Assert.sv"),
             "bind":Path("verification/assert") / ("layers-" + target["module"] + "-Verification-Assert.sv")}
    texts = {key:(directory / path).read_text(encoding="utf-8") for key,path in paths.items()}
    original_bytes = {key:(directory / path).read_bytes() for key,path in paths.items()}
    baseline = validate_frame_integration(manifest, {}, directory)
    if len(baseline["slots"]["first"]) != 37 or sum(x["width"] for x in baseline["slots"]["second"]) != 273:
        raise AssertionError("Independent slot shape mismatch")
    result = dict(directory=str(directory), baseline="PASS", bindings=len(baseline["pairs"]),
                  files={str(paths[k]):hashlib.sha256(v).hexdigest() for k,v in original_bytes.items()},
                  contract_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(), cases={})
    real_read = Path.read_text

    def validate_overlay(key, text, changed_manifest=None):
        selected = (directory / paths[key]).resolve()
        def read(path, *args, **kwargs):
            return text if path.resolve() == selected else real_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", read):
            return validate_frame_integration(changed_manifest or manifest, {}, directory)

    def check(label, key, text, expected):
        if text == texts[key]: raise AssertionError("Mutation not applied: " + label)
        try: validate_overlay(key, text)
        except ValueError as error:
            if str(error) != "FRAME_INTEGRATION_" + expected:
                raise AssertionError((label, expected, str(error))) from error
        else: raise AssertionError("Undetected actual RTL mutation: " + label)
        dest = saved / label / paths[key]; dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        result["cases"][label] = dict(status="PASS", diagnostic="FRAME_INTEGRATION_" + expected,
                                     source=str(dest), sha256=hashlib.sha256(dest.read_bytes()).hexdigest())

    def replace(label, key, old, new, expected, count=1):
        if texts[key].count(old) != count: raise AssertionError((label,"shape",texts[key].count(old),count))
        check(label,key,texts[key].replace(old,new),expected)

    def inject(label, key, text, expected):
        replace(label,key,"endmodule",text + "\nendmodule",expected)

    # Independently enumerate native frame leaves, without importing policy FIELDS.
    leaves = ["resetEpoch", "ingress_programBusy", "ingress_resetActive"] + [
        f"ingress_frame_bytes_{i}" for i in range(33)] + ["ingress_frame_overflow","ingress_frame_length"]
    for field in leaves:
        expression = "_ca_child_native_frame_bits_" + field
        pattern = r"(\.in_bits_" + field + r"\s*\()" + expression + r"(\))"
        mutated, count = re.subn(pattern,r"\g<1>~" + expression + r"\g<2>",texts["target"])
        if count != 1: raise AssertionError((field,"input pin",count))
        check("native-receipt-" + field,"target",mutated,"NATIVE_RECEIPT_PIN:bits_" + field)
        pattern = r"(\.out_bits_" + field + r"\s*\()([^)]*)(\))"
        mutated, count = re.subn(pattern,r"\g<1>broken\g<3>",texts["target"])
        if count != 1: raise AssertionError((field,"output pin",count))
        check("receipt-target-" + field,"target",mutated,"FRAME_OUTPUT_PIN:" + field)

    # Keep explicitly expected failures at the owning policy boundary.
    entries = [
        ("epoch-increment-removed","target","resetEpoch_epoch <= resetEpoch_epoch + 64'h1","resetEpoch_epoch <= resetEpoch_epoch","STATE_TRANSITIONS:resetEpoch_epoch"),
        ("epoch-previous-live-zero","target","resetEpoch_previous <= host_resetActive","resetEpoch_previous <= 1'h0","STATE_TRANSITIONS:resetEpoch_epoch"),
        ("epoch-clock-changed","target","posedge clock or posedge localReset_layerCapture","posedge otherClock or posedge localReset_layerCapture","STATE_CLOCK_RESET:resetEpoch_epoch"),
        ("ready-reset-removed","target","~_resetEpoch_T_2_layerCapture & frameAcceptEnable","frameAcceptEnable","DRIVER:ca_child_frame_bridge_out_ready"),
        ("epoch-width-truncated","target","reg  [63:0] resetEpoch_epoch","reg  [62:0] resetEpoch_epoch","STATE_REGISTER:resetEpoch_epoch"),
        ("gate-clock-inverted","top","serviceClock & gate_enabled","serviceClock | gate_enabled","DRIVER:fabric_clock"),
        ("gate-extra-high-edge","top","posedge gate__enabled_T_3 or posedge reset","posedge serviceClock or posedge reset","WORK_GATE_STATE"),
        ("wrap-upper-bit-lost","assertion","(&I2cTarget.resetEpoch_epoch)","(&I2cTarget.resetEpoch_epoch[31:0])","EPOCH_ASSERTION_LOGIC"),
        ("wrap-clock-changed","assertion","always @(posedge I2cTarget.clock) begin","always @(negedge I2cTarget.clock) begin","EPOCH_ASSERTION_LOGIC"),
        ("wrap-bind-disabled","bind","bind I2cTarget I2cTarget_Verification_Assert","bind Unrelated I2cTarget_Verification_Assert","EPOCH_ASSERTION_BIND"),
        ("wrap-stop-macro-disabled","assertion","`define STOP_COND_ 1","`define STOP_COND_ 0","EPOCH_ASSERTION_MACRO")]
    for row in entries: replace(*row)
    replace("wrap-disabled","assertion","$fatal;",";","EPOCH_ASSERTION_LOGIC",2)
    for name in ("fabric_hostFrames_io_enq_bits_resetActive", "fabric_hostFrames_io_enq_bits_programBusy",
                 "fabric__loaderControlPending_T", "fabric__loaderControlPending_T_1", "fabric__loaderControlPending_T_3",
                 "fabric_hostFrames_io_enq_ready", "fabric_hostFrames__1", "fabric_hostFrames__2"):
        changed,count=re.subn(r"(\bwire\s+"+name+r"\s*=)[^;]+;",r"\g<1> 1'h0;",texts["top"])
        if count!=1:raise AssertionError((name,"driver shape",count))
        check("context-"+name,"top",changed,"DRIVER:"+name)
    replace("mailbox-load-ancestor","top","if (fabric_hostFrames__1) begin","if (fabric_hostFrames__1 & gate_enabled) begin","MAILBOX_TRANSITIONS")
    for name,old in (("gate_enabled","1'h1"),("fabric_hostFrames_first_frame_length","6'h0")):
        pattern=r"(\b"+name+r"\s*=\s*)"+re.escape(old)+r";"
        changed,count=re.subn(pattern,r"\g<1> 1'h0;" if name=="gate_enabled" else r"\g<1> 6'h1;",texts["top"])
        if count!=1:raise AssertionError((name,"initializer shape",count))
        check("initializer-value-"+name,"top",changed,"INITIAL_GUARDS:"+name if name=="gate_enabled" else "MAILBOX_INITIALIZERS:"+name)
    changed,count=re.subn(r"(\bgate_enabled\s*=\s*1'h1;)",r"if(gate_needClock) \g<1>",texts["top"])
    if count!=1:raise AssertionError("Initializer ancestor shape")
    check("initializer-extra-ancestor","top",changed,"INITIAL_GUARDS:gate_enabled")
    for name,key in (("gate_enabled","top"),("resetEpoch_epoch","target"),("fabric_hostFrames_first_frame_length","top")):
        for suffix,extra,error in (
            ("blocking",f"always_comb {name} = 0;", "STATE_INITIAL_WRITERS:" + name if name.startswith("resetEpoch") else "STATE_INITIAL_WRITERS:gate_enabled" if name=="gate_enabled" else "MAILBOX_INITIALIZERS:" + name),
            ("partial",f"always_comb {name}[0] = 0;", "STATE_PARTIAL_WRITER" if not name.startswith("fabric_") else "MAILBOX_PARTIAL_WRITER"),
            ("nested",f"always @(posedge serviceClock) {{{{{name}}}}} <= 0;", "STATE_PARTIAL_WRITER" if not name.startswith("fabric_") else "MAILBOX_PARTIAL_WRITER"),
            ("compound",f"always_comb {name} >>>= 1;", "STATE_PARTIAL_WRITER" if not name.startswith("fabric_") else "MAILBOX_PARTIAL_WRITER"),
            ("update",f"always_comb {name}++;", "STATE_PARTIAL_WRITER" if not name.startswith("fabric_") else "MAILBOX_PARTIAL_WRITER"),
            ("initial","initial begin other=1; end", "INITIAL_BLOCK_COUNT"),
            ("force",f"initial force {name} = 0;", "ALIAS_WRITER_CONSTRUCT")):
            inject(name + "-" + suffix,key,extra,error)
    for key,name in (("target","ca_child_frame_bridge_out_ready"),("target","resetEpoch"),("top","fabric_clock")):
        inject("alias-procedural-"+name,key,f"always_comb {name} = 0;","ALIAS_WRITERS:"+name)
    for field in ("frame_length","frame_bytes_0","frame_bytes_16","frame_bytes_32","resetActive","programBusy"):
        net = "fabric_hostFrames_first_" + field
        inject("mailbox-extra-clocked-"+field,"top",f"always @(negedge serviceClock) {net} <= 0;","MAILBOX_WRITERS:"+net)
    # Dynamic enable cannot be changed to a literal by metadata or probe alone.
    endpoint = next(e["rtl_path"] for e in target["endpoints"] if e["id"]=="frame_accept_enable")
    scopes={receipt["rtl_path"]:dict(registers=registers())}
    probe="task check; begin\nend endtask\n" + f'if (ones_7 !== 1\'h1 || zeros_7 !== 1\'h1) $fatal(1, "INACTIVE_ENDPOINT:{endpoint}");'
    generated=frame_receipt_probe(probe,manifest,scopes,directory)
    if "zeros_7 !== 1'h1" not in generated: raise AssertionError("Dynamic gate coverage was masked")
    # Validate a deliberately ungated exact literal binding independently of the
    # production baseline, with all other existing gates retained but unused.
    changed, count=re.subn(r"(\.frameAcceptEnable\s*\()gate_enabled(\))",r"\g<1>1'h1\g<2>",texts["top"])
    if count!=1:raise AssertionError("Enable pin shape")
    changed=changed.replace("serviceClock & gate_enabled","serviceClock")
    record=validate_overlay("top",changed)
    if record["literal_enable_endpoint"]!=endpoint or record["gate"]!="1'b1":raise AssertionError("Literal endpoint binding missing")
    selected=(directory/paths["top"]).resolve()
    with patch.object(Path,"read_text",lambda path,*a,**kw:changed if path.resolve()==selected else real_read(path,*a,**kw)):
        generated=frame_receipt_probe(probe,manifest,scopes,directory)
    if "zeros_7 !== 1'h0" not in generated or generated.count(endpoint+" !== 1'b1")!=1:raise AssertionError("Literal coverage/check mismatch")
    result["literal_enable_policy"]="PASS: dynamic unmasked; exact literal-one zero mask and comparisons"
    for key,path in paths.items():
        if (directory/path).read_bytes()!=original_bytes[key]:raise AssertionError("Original export changed")
    result["original_preserved"]=True
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export",type=Path,action="append",default=[])
    parser.add_argument("--out",type=Path)
    args,unit_args=parser.parse_known_args()
    if bool(args.export)!=bool(args.out):parser.error("--export and --out must be supplied together")
    run=unittest.main(argv=[sys.argv[0],*unit_args],exit=False)
    if not run.result.wasSuccessful():raise SystemExit(1)
    if args.export:
        results=[actual_controls(path,args.out.parent/(args.out.stem+"-mutants")/path.name) for path in args.export]
        report=dict(schema="riscay-frame-integration-policy-controls-v1",status="PASS",exports=results,
                    qualification="emitted RTL validator sensitivity only; no simulation or physical qualification")
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
        print("FRAME_INTEGRATION_POLICY_CONTROLS_PASS",sum(len(r["cases"]) for r in results))

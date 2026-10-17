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
import tempfile
import unittest
from unittest.mock import patch

from check_frame_integration import (child, clean, compact, completion_metadata, driver, initial_policy,
                                     pins, projected_tree, statement_tree,
                                     validate_frame_integration, frame_receipt_probe, top_spelling,
                                     validated_service_clock, frame_arrays)
from test_frame_receipt import PolicyRunEvidence, receipt_node, registers


class FrameIntegrationTests(unittest.TestCase):
    def test_coordinated_service_clock_closes_both_aliases(self):
        for model in ("FourPhaseSoc", "ClickSoc"):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                marker = directory / "verification/assert/I2cTarget_Verification_Assert.sv"
                marker.parent.mkdir(parents=True); marker.write_text("// extracted form\n")
                root = dict(module=model, rtl_path=model, children=[dict(id="i2c", contract=dict(
                    module="I2cTarget", rtl_path=model + ".ca_child_i2c"))])
                good = f"""module {model}();
wire workClock;
assign workClock = serviceClock & gate_enabled;
wire fabric_clock = workClock;
I2cTarget ca_child_i2c (.frameAcceptEnable(gate_enabled));
endmodule"""
                source = directory / (model + ".sv"); source.write_text(good)
                self.assertEqual(validated_service_clock(root, directory), model + ".fabric_clock")
                for old, new, diagnostic in (
                    ("fabric_clock = workClock", "fabric_clock = serviceClock", "DRIVER:fabric_clock"),
                    ("serviceClock & gate_enabled", "serviceClock | gate_enabled", "DRIVER:workClock"),
                    ("wire workClock;", "wire [1:0] workClock;", "SERVICE_CLOCK_DECLARATION"),
                    ("endmodule", "assign workClock = serviceClock; endmodule", "DRIVER:workClock"),
                    ("endmodule", "always_comb workClock = serviceClock; endmodule", "ALIAS_WRITERS:workClock")):
                    source.write_text(good.replace(old, new))
                    with self.subTest(diagnostic=diagnostic), self.assertRaisesRegex(ValueError, "FRAME_INTEGRATION_" + diagnostic + "$"):
                        validated_service_clock(root, directory)

    def test_service_clock_forms_have_independent_closed_equations(self):
        root = dict(module="Top", rtl_path="Top", children=[dict(id="i2c", contract=dict(
            module="I2cTarget", rtl_path="Top.ca_child_i2c"))])
        for inline in (False, True):
            for gated in (False, True):
                with self.subTest(inline=inline, gated=gated), tempfile.TemporaryDirectory() as temp:
                    directory = Path(temp)
                    if not inline:
                        path = directory / "verification/assert/I2cTarget_Verification_Assert.sv"
                        path.parent.mkdir(parents=True); path.write_text("// form marker\n")
                    name = "gate_io_clockOut" if inline else "fabric_clock"
                    other = "fabric_clock" if inline else "gate_io_clockOut"
                    expression = "serviceClock & gate_enabled" if gated else "serviceClock"
                    pin = "gate_enabled" if gated else "1'h1"
                    good = f"module Top(); wire {name} = {expression}; I2cTarget ca_child_i2c (.frameAcceptEnable({pin})); endmodule"
                    source = directory / "Top.sv"
                    source.write_text(good)
                    self.assertEqual(validated_service_clock(root, directory), "Top." + name)
                    faults = [good.replace(expression + ";", "wrongClock;"),
                              good.replace("endmodule", f"wire {other} = serviceClock; endmodule"),
                              good.replace("endmodule", f"always_comb {name} = serviceClock; endmodule"),
                              good.replace("endmodule", f"assign {name}[0] = 1'b0; endmodule"),
                              good.replace("endmodule", f"initial force {name} = 0; endmodule"),
                              good.replace(f"wire {name}", f"wire [1:0] {name}"),
                              good.replace(f"wire {name}", f"wire signed {name}"),
                              good.replace("endmodule", f"wire {name}; endmodule"),
                              good.replace("endmodule", f"wire unrelated = 1'b0, {name}; endmodule"),
                              good.replace(f"({pin})", "(corrupt)"), good.replace(name, other)]
                    if gated:
                        faults.append(good.replace(expression + ";", "serviceClock;"))
                    for faulty in faults:
                        source.write_text(faulty)
                        with self.assertRaisesRegex(ValueError, "^FRAME_INTEGRATION_"):
                            validated_service_clock(root, directory)

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

    def test_named_primitive_parameters_are_exact(self):
        good = "Other #(.VALUE(7)) earlier (.q(other)); Model #(.COMMON(3), .RESET_VALUE(0)) instance (.in({a,b,c}), .out(q));"
        parameters = dict(COMMON="3", RESET_VALUE="0")
        self.assertEqual(pins(good, "instance", "Model", parameters), {"in":"{a,b,c}", "out":"q"})
        for bad in (good.replace(".COMMON(3)", ".COMMON(2)"),
                    good.replace(".COMMON(3)", ".COMMON(3), .COMMON(3)"),
                    good.replace(".COMMON(3)", ".COMMON(3), .EXTRA(0)"),
                    good.replace(".COMMON(3), ", ""),
                    good.replace("#(.COMMON(3), .RESET_VALUE(0)) ", "")):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "^FRAME_INTEGRATION_INSTANCE_PARAMETERS:instance$"):
                pins(bad, "instance", "Model", parameters)
        with self.assertRaisesRegex(ValueError, "^FRAME_INTEGRATION_INSTANCE_PARAMETERS:instance$"):
            pins(good, "instance", "Model")

    def test_completion_metadata_pins_native_join_without_clocked_copy_state(self):
        for click in (False, True):
            common = 2
            cell = dict(id="frame_completion", model="ChiselAsyncAsymmetricC_v1", version=1,
                        resource="chiselasync/sv/ChiselAsyncAsymmetricC_v1.sv", reset="frame_completion_reset",
                        reset_domain="root", rtl_path="Top.i2c.ca_primitive_frame_completion",
                        parameters=dict(COMMON=str(common), COMMON_INVERT="0", DELAY_FS="1000000",
                                        FALLING="0", FALLING_INVERT="0", RESET_VALUE="0", RISING="0", RISING_INVERT="0"),
                        ports=[dict(name=n, width=w, direction=d) for n,w,d in
                               (("reset",1,"input"),("common",common,"input"),("rising",1,"input"),("falling",1,"input"),("q",1,"output"))])
            target = dict(module="I2cTarget", rtl_path="Top.i2c", primitives=[cell], endpoints=[
                dict(id=i, width=1, source="~|I2cTarget>" + s, rtl_path=f"Top.i2c.ca_p_{len(i)}_{i}") for i,s in
                dict(frame_completion_reset="reset").items()])
            self.assertEqual(completion_metadata(target, click), (cell, cell["parameters"]))
            lowered = copy.deepcopy(target)
            resolved = dict(frame_completion_reset="packed_probe")
            for endpoint in lowered["endpoints"]:
                endpoint["rtl_path"] = "Top.i2c." + resolved[endpoint["id"]]
            self.assertEqual(completion_metadata(lowered, click), (cell, cell["parameters"]))
            for identity in resolved:
                changed = copy.deepcopy(lowered)
                next(e for e in changed["endpoints"] if e["id"] == identity)["rtl_path"] = "Top.i2c.acknowledge"
                with self.subTest(click=click, resolved=identity), self.assertRaisesRegex(ValueError, "FRAME_INTEGRATION_COMPLETION_ENDPOINT:" + identity + "$"):
                    completion_metadata(changed, click)
            for parameter in cell["parameters"]:
                changed = copy.deepcopy(target); changed["primitives"][0]["parameters"][parameter] = "999"
                with self.subTest(click=click, parameter=parameter), self.assertRaisesRegex(ValueError, "FRAME_INTEGRATION_COMPLETION_CONTRACT$"):
                    completion_metadata(changed, click)
            for identity in ("frame_completion_reset",):
                changed = copy.deepcopy(target)
                next(e for e in changed["endpoints"] if e["id"] == identity)["source"] = "~|I2cTarget>wrong"
                with self.subTest(click=click, identity=identity), self.assertRaisesRegex(ValueError, "FRAME_INTEGRATION_COMPLETION_ENDPOINT:" + identity + "$"):
                    completion_metadata(changed, click)

    def test_completion_metadata_rejects_reintroduced_copy_crossing(self):
        for identity in ("frame_copy_meta", "frame_copy_sync", "frame_copy_ready", "frame_offered"):
            # Exercise the complete valid native metadata first, then mutate its endpoint inventory.
            cell=dict(id="frame_completion",model="ChiselAsyncAsymmetricC_v1",version=1,
                      resource="chiselasync/sv/ChiselAsyncAsymmetricC_v1.sv",reset="frame_completion_reset",reset_domain="root",
                      rtl_path="Top.i2c.ca_primitive_frame_completion",
                      parameters=dict(COMMON="2",COMMON_INVERT="0",DELAY_FS="1000000",FALLING="0",FALLING_INVERT="0",RESET_VALUE="0",RISING="0",RISING_INVERT="0"),
                      ports=[dict(name=n,width=w,direction=d) for n,w,d in
                             (("reset",1,"input"),("common",2,"input"),("rising",1,"input"),("falling",1,"input"),("q",1,"output"))])
            target=dict(module="I2cTarget",rtl_path="Top.i2c",primitives=[cell],endpoints=[
                dict(id="frame_completion_reset",width=1,source="~|I2cTarget>reset",rtl_path="Top.i2c.packed_probe")])
            completion_metadata(target,False)
            target["endpoints"].append(dict(id=identity,width=1))
            with self.subTest(identity=identity),self.assertRaisesRegex(ValueError,"FRAME_INTEGRATION_CLOCKED_COPY_COMPLETION_ENDPOINT$"):
                completion_metadata(target,False)

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
             "bind":Path("verification/assert") / ("layers-" + target["module"] + "-Verification-Assert.sv"),
             "top_assertion":Path("verification/assert") / (top["module"] + "_Verification_Assert.sv"),
             "top_bind":Path("verification/assert") / ("layers-" + top["module"] + "-Verification-Assert.sv")}
    if not receipt["module"].startswith("Click"):
        paths["bank_completion"] = Path(child(target,"bank_completion")["module"] + ".sv")
    inline = not (directory / paths["assertion"]).is_file()
    if inline:
        paths["assertion"] = paths["target"]
        paths["top_assertion"] = paths["top"]
        del paths["bind"], paths["top_bind"]
    coordinated = top["module"] in ("FourPhaseSoc", "ClickSoc")
    spell = top_spelling(inline, coordinated)
    texts = {key:(directory / path).read_text(encoding="utf-8") for key,path in paths.items()}
    original_bytes = {key:(directory / path).read_bytes() for key,path in paths.items()}
    baseline = validate_frame_integration(manifest, {}, directory)
    # The upstream strict runner replaces semantic endpoint paths with the
    # hash-bound probe ABI's actual nets before calling this policy hook.
    lowered = copy.deepcopy(manifest)
    macros = dict(re.findall(r"^`define\s+ref_" + re.escape(manifest["top"]) + r"_(\w+)\s+(\S+)$",
                             (directory / manifest["probe_abi"]["file"]).read_text(), re.M))
    def lower(node):
        for endpoint in node["endpoints"]:
            endpoint["rtl_path"] = manifest["top"] + "." + macros[endpoint["probe"]]
        for item in node.get("children", []): lower(item["contract"])
    lower(lowered["design"])
    lowered_record = validate_frame_integration(lowered, {}, directory)
    if len(lowered_record["pairs"]) != len(baseline["pairs"]): raise AssertionError("Resolved endpoint binding count changed")
    if len(baseline["slots"]["first"]) != 3 or sum(x["width"] for x in baseline["slots"]["second"]) != 4:
        raise AssertionError("Independent slot shape mismatch")
    result = dict(directory=str(directory), assertion_form="inline" if inline else "extracted", baseline="PASS", resolved_baseline="PASS", bindings=len(baseline["pairs"]),
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
        if key in ("top", "top_assertion"): expected = spell(expected)
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
        if key in ("top", "top_assertion"):
            old, new = spell(old), spell(new)
        if texts[key].count(old) != count: raise AssertionError((label,"shape",texts[key].count(old),count))
        check(label,key,texts[key].replace(old,new),expected)

    def inject(label, key, text, expected):
        replace(label,key,"endmodule",text + "\nendmodule",expected)

    def mutate_pin(label, key, instance, pin, value, expected):
        match = re.search(r"\b\w+\s+(?:#\s*\([^;]*?\)\s*)?" + re.escape(instance) + r"\s*\((.*?)\);", texts[key], re.S)
        if match is None: raise AssertionError((label, "instance missing"))
        body = match[1]
        pm = re.search(r"\." + re.escape(pin) + r"\s*\(", body)
        if pm is None: raise AssertionError((label, "pin missing"))
        begin = pm.end(); end = begin; depth = 1
        while end < len(body) and depth:
            depth += (body[end] == "(") - (body[end] == ")"); end += 1
        if depth: raise AssertionError((label, "unbalanced pin"))
        raw = texts[key]; left = match.start(1) + begin; right = match.start(1) + end - 1
        check(label, key, raw[:left] + value + raw[right:], expected)

    def remove_pin(label, key, instance, pin, expected):
        match = re.search(r"\b\w+\s+" + re.escape(instance) + r"\s*\((.*?)\);", texts[key], re.S)
        if match is None: raise AssertionError((label, "instance missing"))
        body, count = re.subn(r"\s*\." + re.escape(pin) + r"\s*\([^()]*\)\s*,", "", match[1])
        if count != 1: raise AssertionError((label, "pin removal shape", count))
        check(label, key, texts[key][:match.start(1)] + body + texts[key][match.end(1):], expected)

    # Native route ownership must not turn admission into a copy crossing.
    mutate_pin("snapshot-ready-bypasses-work-clock", "target", "ca_child_snapshot_bridge", "out_ready",
               "1'h1", "SNAPSHOT_RECEIPT_PINS")
    mutate_pin("snapshot-clock-disconnected", "target", "ca_child_snapshot_bridge", "clock",
               "1'h0", "SNAPSHOT_RECEIPT_PINS")
    mutate_pin("snapshot-accept-enable-always", "top", "ca_child_i2c", "snapshotAcceptEnable",
               "1'h1", "SNAPSHOT_CONSUMER_BINDING")
    click = receipt["module"].startswith("Click")
    copy_input = "_ca_child_frame_store_in_ack"
    mutate_pin("original-offer-hidden-behind-copy", "target", "ca_child_frame_bridge", "in_req",
               copy_input, "NATIVE_RECEIPT_PIN:req")
    mutate_pin("publisher-ack-before-copy", "target", "ca_child_native", "frame_ack",
               "_ca_child_frame_bridge_in_ack", "COMPLETION_ACK_BINDING")
    mutate_pin("publisher-ack-before-admission", "target", "ca_child_native", "frame_ack",
               copy_input, "COMPLETION_ACK_BINDING")
    for pin, value in (("reset", "host_resetActive"), ("rising", "1'h0"), ("falling", "1'h1"),
                       ("q", "_ca_child_frame_bridge_in_ack"),
                       ("common", "{"+copy_input+","+copy_input+"}")):
        mutate_pin("completion-join-" + pin, "target", "ca_primitive_frame_completion", pin, value, "COMPLETION_JOIN_PINS")
    mutate_pin("completion-reintroduces-third-clocked-input", "target", "ca_primitive_frame_completion", "common",
               "{"+copy_input+",1'b0,_ca_child_frame_bridge_in_ack}", "COMPLETION_JOIN_PINS")
    for parameter in ("COMMON", "COMMON_INVERT", "RISING", "FALLING", "RESET_VALUE"):
        value = "3" if parameter == "COMMON" else "999"
        cell = next(p for p in target["primitives"] if p["id"] == "frame_completion")
        replace("join-parameter-" + parameter, "target", f'.{parameter}({cell["parameters"][parameter]})', f".{parameter}({value})", "INSTANCE_PARAMETERS:ca_primitive_frame_completion")
    for name in ("copied_frameCopyMeta", "copied", "frameCopyReady", "host_frameOffered"):
        inject("clocked-copy-reintroduced-"+name,"target","reg "+name+";","CLOCKED_COPY_COMPLETION_STATE")
    for name in ("fabric_hostOfferedReset", "fabric_hostOfferedBusy"):
        inject("sticky-context-reintroduced-"+name,"top","reg "+name+";","STICKY_OFFER_CONTEXT")
    ready_reset="localReset_release_1" if inline else "_resetEpoch_T_2_layerCapture"
    ready="~"+ready_reset+" & frameAcceptEnable"
    for label,extra in (("copy-qualifies-admission",copy_input),("request-qualifies-admission","_ca_child_native_frame_req")):
        replace(label,"target",ready,ready+" & "+extra,"DRIVER:ca_child_frame_bridge_out_ready")
    for identity in ("frame_completion_reset",):
        for mode in ("missing", "wrong-source", "wrong-width", "wrong-path"):
            changed = copy.deepcopy(manifest); altered_target = child(changed["design"], "i2c")
            endpoint = next(e for e in altered_target["endpoints"] if e["id"] == identity)
            if mode == "missing": altered_target["endpoints"].remove(endpoint)
            elif mode == "wrong-source": endpoint["source"] = f"~|{target['module']}>corrupt"
            elif mode == "wrong-width": endpoint["width"] = 2
            else: endpoint["rtl_path"] = target["rtl_path"] + ".wrong"
            diagnostic = "FRAME_INTEGRATION_COMPLETION_ENDPOINT:" + identity
            try: validate_overlay("target", texts["target"], changed)
            except ValueError as error:
                if str(error) != diagnostic: raise
            else: raise AssertionError("Completion endpoint downgrade accepted: " + identity + ":" + mode)
            label = identity + "-" + mode
            dest = saved / label / "manifest.json"; dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(changed, indent=2) + "\n")
            result["cases"][label] = dict(status="PASS", diagnostic=diagnostic, source=str(dest),
                                          sha256=hashlib.sha256(dest.read_bytes()).hexdigest())

    if coordinated:
        for name in ("applicationCancel",) + (() if inline else ("fabric_io_applicationCancel",)):
            changed, count = re.subn(r"(\bassign\s+" + name + r"\s*=)[^;]+;",
                                    r"\g<1> cpuResetActive;", texts["top"])
            if count != 1: raise AssertionError((name, "cutoff alias shape", count))
            check("cutoff-alias-" + name, "top", changed, "DRIVER:" + name)
        for register in ("gate_demandFirst", "gate_drainFirst"):
            changed, count = re.subn(r"(\b" + register + r"\s*<=\s*)applicationCancel\b",
                                    r"\g<1>cpuResetActive", texts["top"])
            if count != 1: raise AssertionError((register, "cutoff demand shape", count))
            check("cutoff-" + register, "top", changed, "STATE_TRANSITIONS:gate_demandFirst")
        mutate_pin("cutoff-host-uses-old-observer", "top", "ca_child_i2c", "host_resetActive",
                   "cpuResetActive", "TOP_ADMISSION_PINS")
        command = child(top, "control_command_bridge")
        command_pin = pins(texts["top"], "ca_child_control_command_bridge", command["module"])["in_bits_cpuResetActive"]
        mutate_pin("cutoff-command-uses-old-observer", "top", "ca_child_control_command_bridge", "in_bits_cpuResetActive",
                   command_pin.replace(spell("fabric_io_applicationCancel"), "cpuResetActive"), "COMMAND_CONTEXT_PIN:cpuResetActive")
        changed, count = re.subn(r"(\bfabric_hostFrames_io_enq_bits_resetActive\s*=\s*)" + spell("fabric_io_applicationCancel") + r"\b",
                                r"\g<1>cpuResetActive", texts["top"])
        if count != 1: raise AssertionError("Cutoff descriptor shape")
        check("cutoff-descriptor-uses-old-observer", "top", changed, "DRIVER:fabric_hostFrames_io_enq_bits_resetActive")
        for name in ("fabric_io_controlCommand_valid", "fabric_io_controlCommand_bits_kind"):
            match = re.search(r"\b(?:wire\s+(?:\[[^]]+\]\s*)?|assign\s+)" + name + r"\s*=([^;]+);", texts["top"])
            if match is None: raise AssertionError((name, "halt cutoff shape"))
            old = match[1]; new, count = re.subn(r"fabric_haltPending\s*&\s*~" + spell("fabric_io_applicationCancel"), "fabric_haltPending", old)
            if count != 1: raise AssertionError((name, "halt cutoff missing"))
            check("cutoff-halt-" + name, "top", texts["top"][:match.start(1)] + new + texts["top"][match.end(1):], "DRIVER:" + name)
        for mode in ("missing", "old-source", "wrong-width"):
            changed = copy.deepcopy(manifest)
            endpoints = changed["design"]["endpoints"]
            endpoint = next(e for e in endpoints if e["id"] == "application_cutoff")
            if mode == "missing": endpoints.remove(endpoint)
            elif mode == "old-source": endpoint["source"] = f"~|{top['module']}>cpuResetActive"
            else: endpoint["width"] = 2
            try: validate_overlay("top", texts["top"], changed)
            except ValueError as error:
                if str(error) != "FRAME_INTEGRATION_CUTOFF_ENDPOINT": raise
            else: raise AssertionError("Coordinated endpoint downgrade accepted: " + mode)
            dest = saved / ("cutoff-endpoint-" + mode) / "manifest.json"
            dest.parent.mkdir(parents=True, exist_ok=True); dest.write_text(json.dumps(changed, indent=2) + "\n")
            result["cases"]["cutoff-endpoint-" + mode] = dict(status="PASS", diagnostic="FRAME_INTEGRATION_CUTOFF_ENDPOINT",
                    source=str(dest), sha256=hashlib.sha256(dest.read_bytes()).hexdigest())

    # Independently enumerate the full 337-bit native frame and each copied bank.
    leaves = ["resetEpoch", "ingress_programBusy", "ingress_resetActive"] + [
        f"ingress_frame_bytes_{i}" for i in range(33)] + ["ingress_frame_overflow", "ingress_frame_length"]
    for field in leaves:
        mutate_pin("native-receipt-" + field, "target", "ca_child_frame_bridge", "in_bits_" + field,
                   "corrupt", "NATIVE_RECEIPT_PIN:bits_" + field)
        mutate_pin("receipt-output-" + field, "target", "ca_child_frame_bridge", "out_bits_" + field,
                   "corrupt", "FRAME_OUTPUT_PIN:" + field)
        mutate_pin("borrowed-source-" + field, "target", "ca_child_frame_store", "in_bits_" + field,
                   "corrupt", "BORROWED_SOURCE:bits_" + field)
        for i in range(4):
            mutate_pin(f"bank{i}-head-input-" + field, "target", f"ca_child_frame_head{i}_bridge", "in_bits_" + field,
                       "corrupt", f"BANK_HEAD_PIN:{i}:bits_" + field)
            mutate_pin(f"bank{i}-head-output-" + field, "target", f"ca_child_frame_head{i}_bridge", "out_bits_" + field,
                       "corrupt", f"HEAD_OUTPUT_PIN:{i}:bits_" + field)
            mutate_pin(f"bank{i}-top-field-" + field, "top", "ca_child_i2c", f"host_heads_{i}_bits_" + field,
                       "corrupt", f"TOP_HEAD_PIN:{i}:bits_" + field)
            if field in ("ingress_resetActive", "ingress_programBusy"):
                pin = f"host_heads_{i}_bits_" + field
                mutate_pin(f"bank{i}-context-disconnected-" + field, "target", f"ca_child_frame_head{i}_bridge",
                           "out_bits_" + field, "", f"HEAD_OUTPUT_PIN:{i}:bits_" + field)
                remove_pin(f"bank{i}-context-port-pruned-" + field, "top", "ca_child_i2c", pin,
                           f"TOP_HEAD_PIN:{i}:bits_" + field)
                inject(f"bank{i}-context-extra-writer-" + field, "target", f"assign {pin} = 1'b0;", "ALIAS_WRITERS:" + pin)
        if field.startswith("ingress_frame_"):
            pin = "host_frame_bits_" + field.removeprefix("ingress_")
            mutate_pin("receipt-payload-disconnected-" + field, "target", "ca_child_frame_bridge",
                       "out_bits_" + field, "", "FRAME_OUTPUT_PIN:" + field)
            mutate_pin("unused-frame-top-field-" + field, "top", "ca_child_i2c", pin,
                       "corrupt", "TOP_UNUSED_FRAME_PIN:" + field)
            remove_pin("unused-frame-top-port-pruned-" + field, "top", "ca_child_i2c", pin,
                       "TOP_UNUSED_FRAME_PIN:" + field)
            inject("receipt-payload-extra-writer-" + field, "target", f"assign {pin} = 1'b0;", "ALIAS_WRITERS:" + pin)
    for i in range(4):
        for suffix in ("req", "ack"):
            mutate_pin(f"bank{i}-head-" + suffix, "target", f"ca_child_frame_head{i}_bridge", "in_" + suffix,
                       "corrupt", "BANK_COMPLETION_PARENT_PINS" if suffix=="ack" and not click else f"BANK_HEAD_PIN:{i}:" + suffix)
        for suffix in ("ready", "valid"):
            mutate_pin(f"bank{i}-head-" + suffix, "target", f"ca_child_frame_head{i}_bridge", "out_" + suffix,
                       "corrupt", f"HEAD_OUTPUT_PIN:{i}:" + suffix)
            mutate_pin(f"bank{i}-top-" + suffix, "top", "ca_child_i2c", f"host_heads_{i}_" + suffix,
                       "corrupt", f"TOP_HEAD_PIN:{i}:" + suffix)
        mutate_pin(f"bank{i}-clock", "target", f"ca_child_frame_head{i}_bridge", "clock", "wrongClock", f"HEAD_CLOCK_RESET:{i}")
        mutate_pin(f"bank{i}-reset", "target", f"ca_child_frame_head{i}_bridge", "reset", "applicationReset", f"HEAD_CLOCK_RESET:{i}")
    for field in ["length", "overflow"] + [f"bytes_{i}" for i in range(33)]:
        mutate_pin("command-frame-" + field, "top", "ca_child_control", "command_bits_frame_" + field,
                   "corrupt", "BORROWED_FRAME_PIN:" + field)
    for field in ("cpuResetActive", "programBusy"):
        mutate_pin("command-context-" + field, "top", "ca_child_control_command_bridge", "in_bits_" + field,
                   "corrupt", "COMMAND_CONTEXT_PIN:" + field)
    for pin in ("reset", "nextBank", "in_ack", "busy"):
        mutate_pin("store-" + pin, "target", "ca_child_frame_store", pin, "corrupt", "STORE_CONTROL_PINS")
    mutate_pin("store-request", "target", "ca_child_frame_store", "in_req", "corrupt", "BORROWED_SOURCE:req")
    for i in range(4):
        mutate_pin(f"store-availability-connected-{i}", "target", "ca_child_frame_store", f"available_{i}",
                   "corrupt", f"STORE_AVAILABILITY_PIN:{i}")
        remove_pin(f"store-availability-pruned-{i}", "target", "ca_child_frame_store", f"available_{i}",
                   f"STORE_AVAILABILITY_PIN:{i}")
    # Keep explicitly expected failures at the owning policy boundary.
    entries = [
        ("epoch-increment-removed","target","resetEpoch_epoch <= resetEpoch_epoch + 64'h1","resetEpoch_epoch <= resetEpoch_epoch","STATE_TRANSITIONS:resetEpoch_epoch"),
        ("epoch-previous-live-zero","target","resetEpoch_previous <= host_resetActive","resetEpoch_previous <= 1'h0","STATE_TRANSITIONS:resetEpoch_epoch"),
        ("epoch-clock-changed","target","posedge clock or posedge " + ("localReset_release_1" if inline else "localReset_layerCapture"),"posedge otherClock or posedge " + ("localReset_release_1" if inline else "localReset_layerCapture"),"STATE_CLOCK_RESET:resetEpoch_epoch"),
        ("ready-reset-removed","target","~" + ("localReset_release_1" if inline else "_resetEpoch_T_2_layerCapture") + " & frameAcceptEnable","frameAcceptEnable","DRIVER:ca_child_frame_bridge_out_ready"),

        ("gate-clock-inverted","top","serviceClock & gate_enabled","serviceClock | gate_enabled","DRIVER:workClock" if coordinated and not inline else "DRIVER:fabric_clock"),
        ("gate-extra-high-edge","top","posedge gate__enabled_T_3 or posedge reset","posedge serviceClock or posedge reset","WORK_GATE_STATE"),
        ("wrap-upper-bit-lost","assertion","(&" + ("" if inline else "I2cTarget.") + "resetEpoch_epoch)","(&" + ("" if inline else "I2cTarget.") + "resetEpoch_epoch[31:0])","EPOCH_ASSERTION_LOGIC"),
        ("wrap-clock-changed","assertion","always @(posedge " + ("" if inline else "I2cTarget.") + "clock) begin","always @(negedge " + ("" if inline else "I2cTarget.") + "clock) begin","EPOCH_ASSERTION_LOGIC"),
        ("wrap-stop-macro-disabled","assertion","`define STOP_COND_ 1","`define STOP_COND_ 0","EPOCH_ASSERTION_HEADER" if inline else "EPOCH_ASSERTION_MACRO")]
    if not inline:
        entries.append(("wrap-bind-disabled","bind","bind I2cTarget I2cTarget_Verification_Assert","bind Unrelated I2cTarget_Verification_Assert","EPOCH_ASSERTION_BIND"))
    for row in entries: replace(*row)
    replace("wrap-disabled","assertion","$fatal;",";","EPOCH_ASSERTION_LOGIC",2)
    for role in ("fabric_hostFrames_io_enq_bits_resetActive", "fabric_hostFrames_io_enq_bits_programBusy",
                 "fabric__loaderControlPending_T", "fabric__loaderControlPending_T_1", "fabric__loaderControlPending_T_3",
                 "fabric_hostFrames_io_enq_ready", "fabric_hostFrames__1", "fabric_hostFrames__2"):
        name = spell(role)
        changed,count=re.subn(r"(\bwire\s+"+name+r"\s*=)[^;]+;",r"\g<1> 1'h0;",texts["top"])
        if count!=1:raise AssertionError((name,"driver shape",count))
        check("context-"+name,"top",changed,"DRIVER:"+name)
    replace("mailbox-load-ancestor","top","if (fabric_hostFrames__1) begin","if (fabric_hostFrames__1 & gate_enabled) begin","MAILBOX_TRANSITIONS")
    for name,old in (("gate_enabled","1'h1"),("fabric_hostFrames_first_bank","2'h0")):
        pattern=r"(\b"+name+r"\s*=\s*)"+re.escape(old)+r";"
        changed,count=re.subn(pattern,r"\g<1> 1'h0;" if name=="gate_enabled" else r"\g<1> 2'h1;",texts["top"])
        if count!=1:raise AssertionError((name,"initializer shape",count))
        check("initializer-value-"+name,"top",changed,"INITIAL_GUARDS:"+name if name=="gate_enabled" else "MAILBOX_INITIALIZERS:"+name)
    changed,count=re.subn(r"(\bgate_enabled\s*=\s*1'h1;)",r"if(gate_needClock) \g<1>",texts["top"])
    if count!=1:raise AssertionError("Initializer ancestor shape")
    check("initializer-extra-ancestor","top",changed,"INITIAL_GUARDS:gate_enabled")
    for name,key in (("gate_enabled","top"),("resetEpoch_epoch","target"),("fabric_hostFrames_first_bank","top")):
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
        inject("alias-procedural-"+name,key,f"always_comb {spell(name) if key == 'top' else name} = 0;","ALIAS_WRITERS:"+name)
    for field in ("bank","resetActive","programBusy"):
        net = "fabric_hostFrames_first_" + field
        inject("mailbox-extra-clocked-"+field,"top",f"always @(negedge serviceClock) {net} <= 0;","MAILBOX_WRITERS:"+net)
    arrays=frame_arrays(texts["top"])
    array_fields={name:field for field,name in arrays.items()}
    for name in ["fabric_mmioLaunch", "fabric_hostHeadValid", "fabric_controlBusy", "fabric__io_i2c_heads_0_ready_T", "fabric_io_controlCommand_valid", "fabric_io_controlCommand_bits_kind", "fabric_hostRetire", "_ca_child_control_command_bits_frame_T" if click else "_ca_child_i2c_frameCommandHost_T", *array_fields, *(["_GEN_13"] if click else [])]:
        changed, count = re.subn(r"(\b(?:wire\s+(?:\[[^\]]+\]\s*)*|assign\s+)" + re.escape(name) + r"\s*=)[^;]+;", r"\g<1> 1'h0;", texts["top"])
        if count != 1: raise AssertionError((name, "driver shape", count))
        check("dispatch-driver-" + name, "top", changed, "FRAME_ARRAY:" + array_fields[name] if name in array_fields else "DRIVER:" + name)
    if not click:
        completion=child(target,"bank_completion")
        cells={c["id"]:c for c in completion["primitives"]}
        for identity,c in cells.items():
            instance=c["rtl_path"].rsplit(".",1)[1]
            actual=pins(texts["bank_completion"],instance,c["model"],c["parameters"])
            for pin in actual:
                if pin=="q": continue
                mutate_pin("bank-completion-"+identity+"-"+pin,"bank_completion",instance,pin,"corrupt","BANK_COMPLETION_PINS:"+identity)
            match=re.search(r"\b"+c["model"]+r"\s+#\s*\([^;]*?\)\s*"+instance+r"\s*\([^;]*?\);",texts["bank_completion"],re.S)
            if match is None:raise AssertionError("Completion instance")
            replace("bank-completion-hidden-"+identity,"bank_completion",match[0],"if(1'b0) begin : absent " + match[0] + " end","BANK_COMPLETION_SCOPE")
            replace("bank-completion-ifdef-"+identity,"bank_completion",match[0],"`ifdef NEVER_ENABLE\n" + match[0] + "\n`endif","BANK_COMPLETION_SCOPE")
        for pin in ("bank","host","commandAck","reset"):
            mutate_pin("bank-completion-parent-"+pin,"target","ca_child_bank_completion",pin,"corrupt","BANK_COMPLETION_PARENT_PINS")
        for pin in ("frameCommandBank","frameCommandHost","frameCommandAck"):
            mutate_pin("bank-completion-source-"+pin,"top","ca_child_i2c",pin,"corrupt","BANK_COMPLETION_SOURCE")
        for i in range(4):
            for pin in (f"receiptAck_{i}",f"bankAck_{i}"):
                mutate_pin("bank-completion-parent-"+pin,"target","ca_child_bank_completion",pin,"corrupt","BANK_COMPLETION_PARENT_PINS")
        q=lambda identity:pins(texts["bank_completion"],cells[identity]["rtl_path"].rsplit(".",1)[1],cells[identity]["model"],cells[identity]["parameters"])["q"]
        aliased=texts["bank_completion"].replace(q("bank1_ack_nb"),q("bank0_ack_nb"))
        # Preserve a single declaration so this specifically exercises output aliasing.
        aliased=re.sub(r"\bwire\s+"+re.escape(q("bank0_ack_nb"))+r"\s*;", "", aliased, count=1)
        check("bank-completion-shorted-decoders","bank_completion",aliased,"BANK_COMPLETION_OUTPUT_ALIAS:bank1_ack_nb")
        output=q("host_ack_na")
        for port in ("reset","bank","host","commandAck",*(f"receiptAck_{i}" for i in range(4)),*(f"bankAck_{i}" for i in range(4))):
            aliased=re.sub(r"\b"+re.escape(output)+r"\b",port,texts["bank_completion"])
            check("bank-completion-output-short-"+port,"bank_completion",aliased,"BANK_COMPLETION_INTERNAL_OUTPUT:host_ack_na")
        declaration=r"\bwire\s+"+re.escape(output)+r"\s*;"
        for label,replacement in (("missing",""),("vector","wire [1:0] "+output+";"),("duplicate","wire "+output+"; wire "+output+";")):
            changed,count=re.subn(declaration,replacement,texts["bank_completion"])
            if count!=1: raise AssertionError("Completion scalar output declaration shape changed")
            check("bank-completion-output-declaration-"+label,"bank_completion",changed,"BANK_COMPLETION_INTERNAL_OUTPUT:host_ack_na")
        replace("bank-completion-extra-input","bank_completion","module FourPhaseFrameCompletion(","module FourPhaseFrameCompletion(input unexpected,","BANK_COMPLETION_PORTS")
        for i in range(4):
            instance=cells[f"completion{i}"]["rtl_path"].rsplit(".",1)[1]
            for destination in ("receiptAck_0",f"bankAck_{(i+1)%4}"):
                mutate_pin(f"bank-completion-final-{i}-to-{destination}","bank_completion",instance,"q",destination,f"BANK_COMPLETION_INTERNAL_OUTPUT:completion{i}")
        inject("bank-completion-clocked-state","bank_completion","reg inserted;","BANK_COMPLETION_CLOCKED_STATE")
        inject("bank-completion-defparam","bank_completion","defparam ca_primitive_completion0.COMMON=1;","BANK_COMPLETION_SCOPE")
    # Borrowed data must use the retained identity, and its three state bits
    # must survive application cancellation until native completion and R.
    frame_pin = pins(texts["top"], "ca_child_control", child(top,"control")["module"])["command_bits_frame_bytes_0"]
    mutate_pin("borrow-live-descriptor", "top", "ca_child_control", "command_bits_frame_bytes_0",
               frame_pin.replace("fabric_hostRetiringBank", "fabric_hostFrames_first_bank"), "BORROWED_FRAME_PIN:bytes_0")
    replace("retire-pending-not-in-clock-demand", "top", "fabric_controlOutstanding | fabric_hostRetiring",
            "fabric_controlOutstanding", "DRIVER:fabric_controlBusy")
    changed,count=re.subn(r"(fabric_hostRetiring\s*<=\s*[^;]+)~fabric_hostRetire",r"\1fabric_hostRetire",texts["top"])
    if count!=1:raise AssertionError("Retirement clear shape")
    check("retire-clear-polarity", "top", changed, "RETIRE_DISPATCH_ALIAS")
    replace("retire-tag-wrong-bank", "top", "fabric_hostRetiringBank <= fabric_hostFrames_first_bank;",
            "fabric_hostRetiringBank <= 2'h0;", "RETIRE_STATE_POLICY")
    for name in ("fabric_hostRetiring", "fabric_hostRetiringBank"):
        inject("retire-extra-writer-"+name,"top",f"always @(negedge serviceClock) {name} <= 0;", "RETIRE_WRITERS")
    changed,count=re.subn(r"(fabric_hostRetiringBank\s*=\s*)2'h0;",r"\g<1>2'h1;",texts["top"])
    if count!=1:raise AssertionError("Retiring tag initializer shape")
    check("retire-initial-tag", "top", changed, "INITIAL_GUARDS:fabric_hostRetiringBank")
    for label, old, new, diagnostic in (
        ("tail-does-not-advance", "frameSlot <= frameSlot + 2'h1", "frameSlot <= frameSlot", "STATE_TRANSITIONS:frameSlot"),
        ("tail-starts-wrong-bank", "frameSlot <= 2'h0", "frameSlot <= 2'h1", "STATE_TRANSITIONS:frameSlot"),
        ("busy-sync-bypass", "frameStoreBusy_stages_1 <= frameStoreBusy_stages_0", "frameStoreBusy_stages_1 <= _ca_child_frame_store_busy", "STATE_TRANSITIONS:frameStoreBusy_stages_0")):
        replace(label, "target", old, new, diagnostic)
    top_name = top["module"]
    assert_prefix = "" if inline else top_name + "."
    overflow_offer = re.findall(r"~" + re.escape(spell(assert_prefix + "fabric_io_i2c_frame_valid")) +
                               r"\s*\|", texts["top_assertion"])
    if len(overflow_offer) != 1: raise AssertionError(("overflow-offer-masked", "shape", len(overflow_offer), 1))
    replace("overflow-offer-masked", "top_assertion", overflow_offer[0], "1'b1 |", "OVERFLOW_ASSERTION_LOGIC")
    if inline:
        # Only the assertion operand changes; the source's real enqueue driver
        # and its other users remain present and unchanged.
        replace("overflow-capacity-masked", "top_assertion", "| fabric_hostFrames_io_enq_ready))", "| 1'b1))", "OVERFLOW_ASSERTION_LOGIC")
    else:
        replace("overflow-capacity-masked", "top_assertion", top_name + ".fabric_hostFrames_io_enq_ready", "1'b1", "OVERFLOW_ASSERTION_LOGIC")
    # Changing only the mailbox failure action must fail independently of every other assertion.
    old = '$error("Assertion failed: CONTROL_HOST_MAILBOX_OVERFLOW\\n");'
    replace("overflow-message-removed", "top_assertion", old, '$error("UNRELATED_FAILURE");', "OVERFLOW_ASSERTION_COUNT")
    if not inline:
        replace("overflow-bind-disabled", "top_bind", "bind " + top_name + " ", "bind Unrelated ", "OVERFLOW_ASSERTION_BIND")
        replace("overflow-child-bind-removed", "top_bind", '`include "layers-I2cTarget-Verification-Assert.sv"', "", "OVERFLOW_ASSERTION_BIND")
    for key, diagnostic, model in (("assertion", "EPOCH_ASSERTION", target["module"]), ("top_assertion", "OVERFLOW_ASSERTION", top_name)):
        module_header = "module " + model + ("(" if inline else "_Verification_Assert();")
        replace(key + "-extra-header-macro", key, module_header, "`define SYNTHESIS\n" + module_header, diagnostic + "_HEADER")
        if key == "top_assertion":
            # Restrict mutations to the executable module, preserving the separate
            # synthesis guard in the standard initializer header.
            offset = texts[key].index(module_header)
            head, body = texts[key][:offset], texts[key][offset:]
            check("overflow-inverted-synthesis-wrapper", key, head + body.replace("`ifndef SYNTHESIS", "`ifdef SYNTHESIS", 1), diagnostic + "_WRAPPER")
            check("overflow-extra-disabled-wrapper", key, head + body.replace("`ifndef SYNTHESIS", "`ifdef NEVER_EXECUTE\n`ifndef SYNTHESIS", 1).replace("endmodule", "`endif\nendmodule"), diagnostic + "_WRAPPER")
            check("overflow-inner-disabled-wrapper", key, head + body.replace("`ifndef SYNTHESIS", "`ifndef SYNTHESIS\n`ifdef NEVER_EXECUTE", 1).replace("endmodule", "`endif\nendmodule"), diagnostic + "_WRAPPER")
            replace("overflow-stop-macro-disabled", key, "`define STOP_COND_ 1", "`define STOP_COND_ 0", diagnostic + "_HEADER")
    if not inline:
        replace("overflow-bind-directives-joined", "top_bind", "`ifndef layers_" + top_name + "_Verification_Assert", "`ifndef layers_" + top_name + "_Verification_Assert `define DISABLED", "OVERFLOW_ASSERTION_BIND")
    # A literal assertion inside a dead lexical scope is not executable proof.
    # Exercise these against both real emitted forms, including the reviewer's
    # false-generate counterexample and an implicit generate without the keyword.
    raw = texts["top_assertion"]
    module_start = raw.index("module " + top_name)
    guard = re.search(r"`ifndef SYNTHESIS[^\n]*\n", raw[module_start:])
    if guard is None: raise AssertionError("Missing original assertion guard")
    begin = module_start + guard.end()
    end = raw.index("`endif // not def SYNTHESIS", begin)
    for name, prefix, suffix in (
            ("false-generate", "generate if (1'b0) begin : unreachable_assertions\n", "end endgenerate\n"),
            ("implicit-false-generate", "if (1'b0) begin : unreachable_assertions\n", "end\n"),
            ("uninstantiated-module", "endmodule\nmodule Uninstantiated();\n", "endmodule\nmodule Continuation();\n"),
            ("uninvoked-task", "task never_called; begin\n", "end endtask\n"),
            ("uninvoked-function", "function never_called; begin\n", "end endfunction\n")):
        changed = raw[:begin] + prefix + raw[begin:end] + suffix + raw[end:]
        diagnostic = "UNEXPECTED_WRITER_CONSTRUCT" if inline and name in ("uninvoked-task", "uninvoked-function") else "OVERFLOW_ASSERTION_OWNERSHIP"
        check("overflow-" + name, "top_assertion", changed, diagnostic)
    # The surrounding module scope must also remain direct (outside the guard).
    changed = raw[:module_start + guard.start()] + "if (1'b0) begin : disabled_outer\n" + raw[module_start + guard.start():end] + "\nend\n" + raw[end:]
    check("overflow-outer-false-generate", "top_assertion", changed, "OVERFLOW_ASSERTION_OWNERSHIP")
    if inline:
        changed = raw[:begin] + "wire hidden; `define STOP_COND_ 0\n" + raw[begin:]
        check("overflow-same-line-macro", "top_assertion", changed, "OVERFLOW_ASSERTION_WRAPPER")
        clock = spell("fabric_clock")
        fragment = raw[begin:end]
        changed = fragment.replace("always @(posedge " + clock + ")", "always @(negedge " + clock + ")")
        if changed == fragment: raise AssertionError("Overflow clock mutation missing")
        check("overflow-clock-inverted", "top_assertion", raw[:begin] + changed + raw[end:], "OVERFLOW_ASSERTION_CLOCK")
    for role in ("fabric__5", "fabric__6", "fabric__27"):
        name = spell(role)
        changed, count = re.subn(r"(\bwire\s+" + name + r"\s*=)[^;]+;", r"\g<1> 1'h0;", texts["top"])
        if count != 1: raise AssertionError((name, "fire/select driver shape", count))
        check("fire-or-select-driver-" + role, "top", changed, "DRIVER:" + role)
    inject("descriptor-hidden-register", "top", "reg fabric_hostFrames_shadow;", "MAILBOX_REGISTER_INVENTORY")
    inject("descriptor-hidden-memory", "top", "reg [336:0] fabric_hostFrames_shadow[0:1];", "MAILBOX_REGISTER_INVENTORY")
    # Dynamic enable cannot be changed to a literal by metadata or probe alone.
    endpoint = next(e["rtl_path"] for e in target["endpoints"] if e["id"]=="frame_accept_enable")
    snapshot_endpoint = next(e["rtl_path"] for e in target["endpoints"] if e["id"]=="snapshot_accept_enable")
    scopes={c["contract"]["rtl_path"]:dict(registers=registers()) for c in target["children"] if "FrameReceipt" in c["contract"]["module"]}
    probe="task check; begin\nend endtask\n" + f'if (ones_7 !== 1\'h1 || zeros_7 !== 1\'h1) $fatal(1, "INACTIVE_ENDPOINT:{endpoint}");'
    probe += '\n' + f'if (ones_8 !== 1\'h1 || zeros_8 !== 1\'h1) $fatal(1, "INACTIVE_ENDPOINT:{snapshot_endpoint}");'
    generated=frame_receipt_probe(probe,manifest,scopes,directory)
    if "zeros_7 !== 1'h1" not in generated: raise AssertionError("Dynamic gate coverage was masked")
    # Validate a deliberately ungated exact literal binding independently of the
    # production baseline, with all other existing gates retained but unused.
    changed, count=re.subn(r"(\.frameAcceptEnable\s*\()gate_enabled(\))",r"\g<1>1'h1\g<2>",texts["top"])
    if count!=1:raise AssertionError("Enable pin shape")
    changed,count=re.subn(r"(\.snapshotAcceptEnable\s*\()gate_enabled(\))",r"\g<1>1'h1\g<2>",changed)
    if count!=1:raise AssertionError("Snapshot enable pin shape")
    changed=changed.replace("serviceClock & gate_enabled","serviceClock").replace("gate_enabled & fabric_hostRetiring", "fabric_hostRetiring").replace("gate_enabled & fabric_hostFrames_io_deq_ready", "fabric_hostFrames_io_deq_ready").replace("_ca_child_control_command_bridge_in_ready & gate_enabled", "_ca_child_control_command_bridge_in_ready")
    record=validate_overlay("top",changed)
    if record["literal_enable_endpoint"]!=endpoint or record["gate"]!="1'b1":raise AssertionError("Literal endpoint binding missing")
    selected=(directory/paths["top"]).resolve()
    with patch.object(Path,"read_text",lambda path,*a,**kw:changed if path.resolve()==selected else real_read(path,*a,**kw)):
        generated=frame_receipt_probe(probe,manifest,scopes,directory)
    if "zeros_7 !== 1'h0" not in generated or generated.count(endpoint+" !== 1'b1")!=1:raise AssertionError("Literal coverage/check mismatch")
    if "zeros_8 !== 1'h0" not in generated or generated.count(snapshot_endpoint+" !== 1'b1")!=1:raise AssertionError("Snapshot literal coverage/check mismatch")
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
    evidence=PolicyRunEvidence(args.export, [Path(__file__).with_name(name) for name in
                               ("test_frame_integration.py", "check_frame_integration.py",
                                "test_frame_receipt.py", "check_frame_receipt.py")])
    run=unittest.main(argv=[sys.argv[0],*unit_args],exit=False)
    if not run.result.wasSuccessful():raise SystemExit(1)
    if args.export:
        results=[actual_controls(path,args.out.parent/(args.out.stem+"-mutants")/(str(index)+"-"+path.name)) for index,path in enumerate(args.export)]
        report=dict(schema="riscay-frame-integration-policy-controls-v1",status="PASS",exports=results,
                    attestation=evidence.finish(),
                    qualification="emitted RTL validator sensitivity only; no simulation or physical qualification")
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
        print("FRAME_INTEGRATION_POLICY_CONTROLS_PASS",sum(len(r["cases"]) for r in results))

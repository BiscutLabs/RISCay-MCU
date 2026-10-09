# SPDX-License-Identifier: Apache-2.0
"""Independent controls for the MCU fabric export extension."""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from check_export import (BD_FABRIC_PATH, CLICK_FABRIC_PATH, validate_fabric_path,
                          fabric_path_bindings, fabric_checker_source, validate_native_click,
                          validate_fabric_inventory, validate_click_fabric_controls)


def fixture(click):
    def primitive(name, model="ChiselAsyncControlGate_v1", **params):
        return {"id": name, "rtl_path": "Top." + name, "model": model,
                "parameters": params}
    source, sink = ("reply_sources", "register_data") if click else ("mux_sources", "mux_result")
    protocol = "two-phase-bundled-v1" if click else "four-phase-bundled-v1"
    node = {"module": "ClickFabric" if click else "FourPhaseFabric", "children": [],
            "channels": [{"id": name, "protocol": protocol, "role": role} for name, role in
                         (("request", "input"), ("response", "output"),
                          ("service_request", "output"), ("service_response", "input"))],
            "endpoints": [{"id": name, "rtl_path": "Top." + name, "width": width} for name, width in
                          ((source, 103), (sink, 33), ("capture_event", 1), ("request_data", 70),
                           ("response_data", 33), ("service_request_data", 70), ("service_response_data", 33), ("service_response_request", 1),
                           ("request_acknowledge", 1), ("response_request", 1), ("service_response_acknowledge", 1), ("service_request_request", 1))],
            "primitives": [primitive("data_delay"), primitive("accepted_phase")], "timing": []}
    if click:
        node["primitives"] += [primitive("payload", "ChiselAsyncEventRegister_v1", WIDTH="33"),
                               primitive("service_response_phase", "ChiselAsyncEventRegister_v1", WIDTH="1")]
        node["primitives"] += [primitive(name, WIDTH="1", OP="0", RESET_VALUE="0", DELAY_FS="110200001")
                               for name in ("request_guard", "request_delay", "output_delay", "acknowledge_guard", "output_guard", "return_guard")]
        node["primitives"] += [primitive("service_request_phase")]
    else:
        node["children"] = [{"id": "reply", "contract": {"module": "FourPhaseStage_2", "children": [],
                             "primitives": [primitive("data_delay")],
                             "endpoints": [{"id": "in_data", "rtl_path": "Top.storage_data"}]}}]
    timing = {"id": "response_mux", "kind": "bundled-data-path-v1", "logic": CLICK_FABRIC_PATH if click else BD_FABRIC_PATH,
              "delay_owner": [] if click else ["reply"], "delay_cell": "data_delay",
              "source": source, "sink": sink}
    node["timing"] = [timing]
    if click:
        node["timing"].append(dict(id="capture_aperture", kind="bundled-setup-hold-v1", launch="request_request",
            transaction="request_data", data_valid="register_data", capture="capture_event", captured="response_data",
            setup_fs="100000", hold_fs="100000"))
        models = {"accepted_phase": "PhaseRegister", "service_request_phase": "PhaseRegister",
                  "payload": "EventRegister", "service_response_phase": "EventRegister",
                  "dispatch": "AsymmetricC", "request_pending": "Xor", "response_occupied": "Xor"}
        models.update({prefix + suffix: "ControlGate" for prefix in ("runnable", "capture") for suffix in ("_na", "_nb", "_or", "")})
        for name, model in models.items():
            cell = next((p for p in node["primitives"] if p["id"] == name), None)
            if cell is None:
                cell = primitive(name); node["primitives"].append(cell)
            cell["model"] = "ChiselAsync" + model + "_v1"
            cell["parameters"]["DELAY_FS"] = "1000000"
        for name, delay in (("data_delay", 10000000), ("request_guard", 11000000), ("request_delay", 11000000), ("output_delay", 32000000)):
            next(p for p in node["primitives"] if p["id"] == name)["parameters"]["DELAY_FS"] = str(delay)
    return node, timing


class FabricExportTest(unittest.TestCase):
    def test_timing_obligations_cannot_be_removed_or_renamed(self):
        for click in (False, True):
            node, _ = fixture(click)
            validate_fabric_inventory({"design": node})
            for index in range(len(node["timing"])):
                for remove in (False, True):
                    bad = copy.deepcopy(node)
                    if remove:
                        bad["timing"].pop(index)
                    else:
                        bad["timing"][index]["id"] = "unrecognized"
                    with self.assertRaisesRegex(ValueError, "TIMING_INVENTORY"):
                        validate_fabric_inventory({"design": {"module": "Top", "children": [{"contract": bad}]}})

    def test_click_composed_drain_bound_aperture_and_cell_envelope(self):
        node, _ = fixture(True)
        validate_click_fabric_controls(node)
        for name in ("acknowledge_guard", "output_guard", "return_guard"):
            for delay in (1, 32000000, 80200000):
                bad = copy.deepcopy(node)
                next(p for p in bad["primitives"] if p["id"] == name)["parameters"]["DELAY_FS"] = str(delay)
                with self.assertRaisesRegex(ValueError, "DRAIN_GUARD"):
                    validate_click_fabric_controls(bad)
        for name in ("payload", "accepted_phase", "dispatch", "request_pending", "capture_na", "runnable"):
            bad = copy.deepcopy(node)
            next(p for p in bad["primitives"] if p["id"] == name)["parameters"]["DELAY_FS"] = "1000001"
            with self.assertRaisesRegex(ValueError, "CELL_POLICY"):
                validate_click_fabric_controls(bad)
        bad = copy.deepcopy(node); bad["timing"][1]["hold_fs"] = "0"
        with self.assertRaisesRegex(ValueError, "APERTURE"):
            validate_click_fabric_controls(bad)

    def test_custom_paths_reject_changed_owner_schema_and_protocol(self):
        for click in (False, True):
            node, timing = fixture(click)
            validate_fabric_path(node, timing)
            for key, wrong in (("delay_owner", ["unrelated"]), ("delay_cell", "capture"),
                               ("source", "request_data"), ("sink", "response_data")):
                bad = dict(timing, **{key: wrong})
                with self.assertRaisesRegex(ValueError, "PATH_IDENTITY"):
                    validate_fabric_path(node, bad)
            for mutation in (lambda n: n.update(module="Unrelated"),
                             lambda n: n["channels"][0].update(protocol="four-phase-bundled-v1" if click else "two-phase-bundled-v1"),
                             lambda n: n["channels"].pop()):
                bad = copy.deepcopy(node); mutation(bad)
                with self.assertRaisesRegex(ValueError, "PATH_IDENTITY"):
                    validate_fabric_path(bad, timing)
            bad = copy.deepcopy(node); bad["endpoints"][0]["width"] -= 1
            with self.assertRaisesRegex(ValueError, "PATH_WIDTH"):
                validate_fabric_path(bad, timing)
        node, timing = fixture(False); node["children"][0]["contract"]["module"] = "ClickBuffer"
        with self.assertRaisesRegex(ValueError, "REPLY_OWNER"):
            validate_fabric_path(node, timing)

    def test_click_requires_event_storage_and_each_preserved_guard(self):
        node, timing = fixture(True)
        bad = copy.deepcopy(node); bad["primitives"][2]["model"] = "ChiselAsyncClosingLatch_v1"
        with self.assertRaisesRegex(ValueError, "CAPTURE_CELL"):
            validate_fabric_path(bad, timing)
        for name in ("request_guard", "request_delay", "acknowledge_guard", "output_guard", "return_guard"):
            for mutation in (lambda p: p["parameters"].update(OP="1"),
                             lambda p: p["parameters"].update(DELAY_FS="0"),
                             lambda p: p.update(model="Unrelated")):
                bad = copy.deepcopy(node)
                mutation(next(p for p in bad["primitives"] if p["id"] == name))
                with self.assertRaisesRegex(ValueError, "GUARD_CELL"):
                    validate_fabric_path(bad, timing)

    def test_native_click_rejects_rtz_even_in_nested_helpers(self):
        node, _ = fixture(True)
        manifest = {"top": "ClickSoc", "design": node}
        validate_native_click(manifest)
        for mutation in (lambda n: n.update(module="FourPhaseAdapter"),
                         lambda n: n["channels"][0].update(protocol="four-phase-bundled-v1"),
                         lambda n: n["primitives"][2].update(model="ChiselAsyncClosingLatch_v1")):
            bad = copy.deepcopy(node); mutation(bad)
            parent = copy.deepcopy(node); parent["children"] = [{"id": "hidden", "contract": bad}]
            for top in ("ClickSoc", "ClickTelemetry"):
                with self.assertRaisesRegex(ValueError, "HAS_RTZ_IMPLEMENTATION"):
                    validate_native_click({"top": top, "design": parent})

    def test_extension_retains_original_checks_and_fails_on_api_drift(self):
        anchor = '\"initial-token-literal-mux\": ([], \"data\", \"mux_state\", \"out_data\")}'
        binding = 'if timing["logic"] in ("exclusive-merge-input-mux", "controlled-multiplexer-input-mux"):'
        original = anchor + "\n" + binding + "\nrequire(marker_ok, 'MARKER')\nrequire(budget_ok, 'BUDGET')"
        adapted = fabric_checker_source(original)
        self.assertIn("validate_fabric_path(node, timing)", adapted)
        self.assertIn("fabric_path_bindings(node, timing)", adapted)
        self.assertIn("require(marker_ok, 'MARKER')", adapted)
        self.assertIn("require(budget_ok, 'BUDGET')", adapted)
        self.assertIn("el" + binding, adapted)
        for wrong in ("", original + anchor, original.replace(binding, "")):
            with self.assertRaisesRegex(ValueError, "SHAPE_CHANGED"):
                fabric_checker_source(wrong)

    def test_mux_data_and_capture_comparisons_reject_each_disconnection(self):
        # Independent pins, no production RTL or generated connection oracle.
        for click in (False, True):
            node, timing = fixture(click)
            pairs = fabric_path_bindings(node, timing)
            signals = sorted({s for pair in pairs for s in pair})
            flat = {s: s.replace(".", "_") for s in signals}
            for broken in [None] + [b for _, b in pairs]:
                declarations = "\n".join("reg [32:0] " + flat[s] + ";" for s in signals)
                checks = "\n".join(f'if ({flat[a]} !== {flat[b]}) $fatal(1,"FABRIC_PIN_BINDING");' for a, b in pairs)
                stimulus = "\n".join(f"{flat[s]}=0;" for s in signals) + "\n#1;\n" + checks
                stimulus += "\n" + "\n".join(flat[s] + "=" + ("0" if s == broken else "33'h1ffffffff") + ";" for s in signals)
                text = ("module Testbench;\n" + declarations + "\ninitial begin\n" + stimulus +
                        '\n#1;\n' + checks + '\n$display("FABRIC_PINS_PASS"); $finish; end endmodule\n')
                with tempfile.TemporaryDirectory(prefix="riscay-fabric-export-") as folder:
                    path = Path(folder); (path / "test.sv").write_text(text)
                    built = subprocess.run(["iverilog", "-g2012", "-s", "Testbench", "-o", "sim.vvp", "test.sv"],
                                           cwd=path, capture_output=True, text=True, timeout=30)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    result = subprocess.run(["vvp", "sim.vvp"], cwd=path, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode == 0, broken is None, result.stdout)
                    self.assertIn("FABRIC_PINS_PASS" if broken is None else "FABRIC_PIN_BINDING", result.stdout)

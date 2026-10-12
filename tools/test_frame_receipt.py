# SPDX-License-Identifier: Apache-2.0
"""Receipt policy unit tests and controls against actual emitted fixture RTL.

Run unit tests directly, or add --export DIR for both variants and --out FILE
to record the separate emitted-RTL policy controls. These controls establish
validator sensitivity; production simulation/capture mutations remain separate.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest

from check_frame_receipt import (validate_frame_receipt, validate_frame_receipt_rtl,
                                 frame_receipt_bindings, validate_frame_receipts, actual_receipt_rtl)


class PolicyRunEvidence:
    """Bind a structural-policy run to unchanged helpers and emitted inputs."""
    def __init__(self, exports, helpers):
        self.started = datetime.now(timezone.utc).isoformat()
        self.command = [sys.executable, *sys.argv]
        self.cwd = str(Path.cwd().resolve())
        self.exports = [Path(directory).resolve() for directory in exports]
        self.helpers = [Path(path).resolve() for path in helpers]
        self.sources = self.source_inventory()
        self.before = self.hashes([*self.helpers, *self.sources, Path(sys.executable)])

    def source_inventory(self):
        return sorted({path.resolve() for directory in self.exports
                       for path in [*directory.rglob("*.sv"), directory / "contract.json",
                                    directory / "filelist.f"] if path.is_file()})

    @staticmethod
    def hashes(paths):
        return {str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

    def finish(self):
        if (self.source_inventory() != self.sources or
                self.hashes([*self.helpers, *self.sources, Path(sys.executable)]) != self.before):
            raise AssertionError("POLICY_RUN_INPUT_CHANGED")
        select = lambda paths: {str(path): self.before[str(path)] for path in paths}
        return dict(command=self.command, cwd=self.cwd, started_utc=self.started,
                    finished_utc=datetime.now(timezone.utc).isoformat(),
                    python=dict(path=str(Path(sys.executable).resolve()),
                                sha256=self.before[str(Path(sys.executable).resolve())]),
                    helpers=select(self.helpers), sources=select(self.sources), unchanged=True)


def receipt_node(click=False):
    """Independent schema fixture; do not import the validator's field policy."""
    module = ("Click" if click else "FourPhase") + "FrameReceipt"
    sources = (("request_meta", "requestMeta", 1), ("request_sync", "requestSync", 1),
               ("acknowledge", "acknowledge", 1), ("in_request", "in.req", 1),
               ("in_data", "in.bits", 337), ("in_acknowledge", "in.ack", 1),
               ("out_valid", "out.valid", 1), ("out_data", "out.bits", 337),
               ("out_ready", "out.ready", 1), ("out_clock", "clock", 1),
               ("local_reset", "localReset", 1), ("reset", "reset", 1))
    node = dict(module=module, rtl_path="Top.receipt", reset_domain="root", capacity=1,
                children=[], primitives=[], timing=[], channels=[], endpoints=[
                    dict(id=name, width=width, source=f"~|{module}>{source}", rtl_path="Top.receipt." + name)
                    for name, source, width in sources])
    fields = [("resetEpoch", 64), ("ingress.programBusy", 1), ("ingress.resetActive", 1)]
    fields += [(f"ingress.frame.bytes[{i}]", 8) for i in range(33)]
    fields += [("ingress.frame.overflow", 1), ("ingress.frame.length", 6)]
    for name in ("in", "out"):
        offset = 0
        layout = []
        for field, width in fields:
            layout.append(dict(field="bits." + field, lsb=offset, width=width,
                               signed=False, source=f"~|{module}>{name}.bits.{field}"))
            offset += width
        assert offset == 337
        channel = dict(id=name, role="input" if name == "in" else "output", layout=layout,
                       reset_domain="root", token_contract="ordered-lossless-reset-abort-v1")
        if name == "in":
            channel.update(protocol="two-phase-bundled-v1" if click else "four-phase-bundled-v1",
                           request="in_request", acknowledge="in_acknowledge", data="in_data",
                           phases=["00", "10", "11", "01", "00"], environment=(
                               "binary inputs; coordinated reset to 00; every ack edge delivers; data held while req != ack"
                               if click else "binary inputs; coordinated reset; data held through return to idle"))
        else:
            channel.update(protocol="decoupled-v1", valid="out_valid", ready="out_ready", data="out_data",
                           clock="out_clock", phases=["rising-edge-fire"],
                           environment="transfer only at rising clock with ready and valid; no input irrevocability assumed; coordinated reset")
        node["channels"].append(channel)
    return node


def registers():
    return {name: 1 for name in ("localReset_release_0", "localReset_release_1",
                                 "requestMeta", "requestSync", "acknowledge")}


class FrameReceiptPolicyTests(unittest.TestCase):
    def test_exact_schemas_and_bindings(self):
        for click in (False, True):
            node = receipt_node(click)
            self.assertEqual(validate_frame_receipt(node), click)
            bindings = frame_receipt_bindings(node, {node["rtl_path"]: dict(registers=registers())})
            self.assertEqual(len(bindings), 15)
            by_lhs = {}
            for lhs, rhs in bindings:
                by_lhs.setdefault(lhs, []).append(rhs)
            self.assertIn("Top.receipt.reset", by_lhs["Top.receipt.reset"])
            self.assertIn("Top.receipt.in_req", by_lhs["Top.receipt.in_request"])
            for direction in ("in", "out"):
                bus = next(x for x in by_lhs[f"Top.receipt.{direction}_data"] if x.startswith("{"))
                self.assertEqual(bus.count(","), 37)
                self.assertTrue(bus.startswith(f"{{Top.receipt.{direction}_bits_ingress_frame_length,"))
                self.assertTrue(bus.endswith(f",Top.receipt.{direction}_bits_resetEpoch}}"))
                for index in range(33):
                    self.assertEqual(len(re.findall(r"\b" + direction + r"_bits_ingress_frame_bytes_" +
                                                   str(index) + r"\b", bus)), 1)

    def test_unknown_owner_is_rejected(self):
        for module in ("FourPhaseStoredReceipt", "ClickFrameReceiptRTZ", "FrameReceipt",
                       "ClickFrameReceipt_", "ClickFrameReceipt_7Injected"):
            with self.assertRaisesRegex(ValueError, "^FRAME_RECEIPT_OWNER$"):
                validate_frame_receipt(dict(module=module))

    def test_inventory_is_closed(self):
        for click in (False, True):
            node = receipt_node(click)
            for key, values in (("capacity", [0, 2, True]), ("children", [[{}]]),
                                ("timing", [[{}]]), ("primitives", [[{}]]),
                                ("endpoints", [node["endpoints"][:-1], node["endpoints"] * 2])):
                for value in values:
                    bad = copy.deepcopy(node); bad[key] = value
                    with self.subTest(click=click, key=key, value=value):
                        with self.assertRaisesRegex(ValueError, "^FRAME_RECEIPT_(SCHEMA|INVENTORY)$"):
                            validate_frame_receipt(bad)
            for domain in (None, "", 3):
                bad = copy.deepcopy(node); bad["reset_domain"] = domain
                with self.assertRaisesRegex(ValueError, "^FRAME_RECEIPT_RESET_DOMAIN$"):
                    validate_frame_receipt(bad)

    def test_every_endpoint_width_and_source_is_closed(self):
        for click in (False, True):
            node = receipt_node(click)
            for index, endpoint in enumerate(node["endpoints"]):
                for key, value in (("width", endpoint["width"] + 1), ("width", True),
                                   ("source", "~|Unrelated>" + endpoint["id"]), ("id", "unknown")):
                    bad = copy.deepcopy(node); bad["endpoints"][index][key] = value
                    with self.subTest(click=click, endpoint=endpoint["id"], key=key):
                        with self.assertRaisesRegex(ValueError, "^FRAME_RECEIPT_INVENTORY$"):
                            validate_frame_receipt(bad)

    def test_every_payload_leaf_layout_and_source_is_closed(self):
        for click in (False, True):
            node = receipt_node(click)
            for channel_index in range(2):
                layout = node["channels"][channel_index]["layout"]
                for index, field in enumerate(layout):
                    for key, value in (("lsb", field["lsb"] + 1), ("width", field["width"] + 1),
                                       ("signed", True), ("source", field["source"] + "Wrong"),
                                       ("field", field["field"] + "Wrong"), ("signed", 0),
                                       ("lsb", float(field["lsb"])), ("width", float(field["width"]))):
                        bad = copy.deepcopy(node); bad["channels"][channel_index]["layout"][index][key] = value
                        with self.subTest(click=click, channel=channel_index, field=field["field"], key=key):
                            with self.assertRaisesRegex(ValueError, "^FRAME_RECEIPT_SCHEMA$"):
                                validate_frame_receipt(bad)

    def test_channel_protocol_reset_and_semantics_are_closed(self):
        for click in (False, True):
            node = receipt_node(click)
            for channel_index, channel in enumerate(node["channels"]):
                for key in channel:
                    bad = copy.deepcopy(node); bad["channels"][channel_index].pop(key)
                    with self.subTest(click=click, channel=channel_index, key=key):
                        with self.assertRaisesRegex(ValueError, "^FRAME_RECEIPT_SCHEMA$"):
                            validate_frame_receipt(bad)
                for key, value in (("reset_domain", "application"), ("protocol", "four-phase-bundled-v1"
                                    if channel_index == 1 or click else "two-phase-bundled-v1"),
                                   ("phases", []), ("token_contract", "drop-on-stall"),
                                   ("layout", channel["layout"][:-1])):
                    bad = copy.deepcopy(node); bad["channels"][channel_index][key] = value
                    with self.assertRaisesRegex(ValueError, "^FRAME_RECEIPT_SCHEMA$"):
                        validate_frame_receipt(bad)

    def test_every_register_and_hidden_storage_is_closed(self):
        for click in (False, True):
            node = receipt_node(click); path = node["rtl_path"]
            for name in registers():
                for replacement in (None, 2, True):
                    regs = registers()
                    if replacement is None: regs.pop(name)
                    else: regs[name] = replacement
                    with self.assertRaisesRegex(ValueError, "^FRAME_RECEIPT_REGISTER_INVENTORY$"):
                        frame_receipt_bindings(node, {path: dict(registers=regs)})
            for scope in ({}, dict(registers={**registers(), "hiddenPayload": 337}),
                          dict(registers=registers(), memories={"hidden": (1, 337)})):
                with self.assertRaisesRegex(ValueError, "^FRAME_RECEIPT_REGISTER_INVENTORY$"):
                    frame_receipt_bindings(node, {path: scope})

    def test_i2c_target_cannot_omit_duplicate_or_replace_receipt(self):
        for click in (False, True):
            receipt = receipt_node(click)
            target = dict(module="I2cTarget", children=[
                dict(id="native", contract=dict(module=("Click" if click else "FourPhase") + "I2c", children=[])),
                dict(id="frame_bridge", contract=receipt),
                dict(id="frame_store", contract=dict(module=("Click" if click else "FourPhase") + "FrameStore", children=[])),
                dict(id="snapshot_bridge", contract=dict(module=("Click" if click else "FourPhase") + "ToDecoupled", children=[]))] + [
                    dict(id=f"frame_head{i}_bridge", contract=copy.deepcopy(receipt)) for i in range(4)])
            for mutate, error in (
                    (lambda n: n["children"].pop(), "TARGET_INVENTORY"),
                    (lambda n: n["children"].append(n["children"][-1]), "TARGET_INVENTORY"),
                    (lambda n: n["children"][2]["contract"].update(module="HiddenRTZAdapter"), "TARGET_STORE_OWNER"),
                    (lambda n: n["children"][4]["contract"].update(module="ClickToDecoupled"), "TARGET_OWNER"),
                    (lambda n: n["children"][1]["contract"].update(module="ClickToDecoupled"), "TARGET_OWNER"),
                    (lambda n: n["children"][1]["contract"].update(module=("FourPhase" if click else "Click") + "FrameReceipt"), "TARGET_OWNER")):
                bad = copy.deepcopy(target); mutate(bad)
                with self.assertRaisesRegex(ValueError, "^FRAME_RECEIPT_" + error + "$"):
                    validate_frame_receipts(dict(design=bad), Path("unused"))


def actual_rtl_controls(directory, ordinal=0, saved=None):
    """Mutate real emitted text without weakening its expected policy."""
    directory = Path(directory).resolve()
    manifest_path = directory / "contract.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))["manifest"]
    found = []

    def visit(node, parent=None):
        if re.fullmatch(r"(?:FourPhase|Click)FrameReceipt(?:_[0-9]+)?", node.get("module", "")):
            found.append((node, parent))
        for child in node.get("children", []): visit(child["contract"], node)

    visit(manifest["design"])
    if len(found) not in (1, 5) or ordinal >= len(found):
        raise AssertionError("Expected one standalone or five production receipts in " + str(directory))
    node, parent = found[ordinal]
    parent_rtl = (directory / (parent["module"] + ".sv")).read_text(encoding="utf-8") if parent else None
    actual, _ = actual_receipt_rtl(node, directory, parent_rtl)
    click = validate_frame_receipt(node)
    rtl_path = directory / (actual + ".sv")
    original = rtl_path.read_text(encoding="utf-8")
    original_bytes = rtl_path.read_bytes()
    validate_frame_receipts(manifest, directory)
    result = dict(directory=str(directory), module=node["module"], actual_module=actual, receipt=node["rtl_path"],
                  rtl_sha256=hashlib.sha256(original_bytes).hexdigest(),
                  contract_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                  baseline="PASS", cases={})
    if saved is not None:
        saved = Path(saved).resolve() / node["rtl_path"].rsplit(".", 1)[1]
        saved.mkdir(parents=True, exist_ok=True)

    def check(label, mutated, error):
        if mutated == original: raise AssertionError("Mutation was not applied: " + label)
        try:
            normalized = re.sub(r"\bmodule\s+" + re.escape(actual) + r"\s*\(", "module " + node["module"] + " (", mutated)
            validate_frame_receipt_rtl(node, normalized)
        except ValueError as caught:
            if str(caught) != "FRAME_RECEIPT_" + error:
                raise AssertionError((label, error, str(caught))) from caught
        else:
            raise AssertionError("Undetected actual RTL mutation: " + label)
        result["cases"][label] = dict(expected="FRAME_RECEIPT_" + error,
                                      rtl_sha256=hashlib.sha256(mutated.encode()).hexdigest(), status="PASS")
        if saved is not None:
            dest = saved / label / (actual + ".sv")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(mutated, encoding="utf-8")
            result["cases"][label].update(source=str(dest),
                                          sha256=hashlib.sha256(dest.read_bytes()).hexdigest())

    def replace(label, old, new, error, count=1):
        if original.count(old) != count: raise AssertionError((label, "emitter shape", original.count(old)))
        check(label, original.replace(old, new), error)

    for label, old, new in (
            ("request-meta-disconnected", "requestMeta <= in_req", "requestMeta <= 1'b0"),
            ("request-sync-bypass", "requestSync <= requestMeta", "requestSync <= in_req"),
            ("ack-before-fire", "out_ready & packed_6", "packed_6"),
            ("local-release-bypass", "localReset_release_1 <= localReset_release_0", "localReset_release_1 <= 1'b0"),
            ("application-reset-owner", "posedge clock or posedge reset", "posedge clock or posedge applicationReset"),
            ("receipt-clock-replaced", "posedge clock or posedge localReset", "posedge otherClock or posedge localReset"),
            ("receipt-reset-removed", "posedge clock or posedge localReset", "posedge clock"),
            ("ack-reset-inverted", "acknowledge <= 1'h0", "acknowledge <= 1'h1")):
        replace(label, old, new, "SEQUENTIAL_LOGIC")
    if click:
        replace("ack-live-phase", "acknowledge <= requestSync", "acknowledge <= in_req", "SEQUENTIAL_LOGIC")
    else:
        replace("ack-no-return-retention", "out_ready & packed_6 | requestSync & acknowledge",
                "out_ready & packed_6", "SEQUENTIAL_LOGIC")
    for label, old, new in (
            ("local-release-alias", "localReset = localReset_release_1", "localReset = reset"),
            ("clock-probe-alias", "packed_9_probe = clock", "packed_9_probe = reset"),
            ("reset-probe-alias", "packed_11_probe = reset", "packed_11_probe = clock"),
            ("local-reset-probe-alias", "packed_10_probe = localReset", "packed_10_probe = reset"),
            ("ack-output-alias", "in_ack_0 = acknowledge", "in_ack_0 = in_req"),
            ("valid-reset-mask-removed", "& ~packed_10_probe", "")):
        replace(label, old, new, "REGISTERS_OR_PROBES")
    for field in ["ingress_frame_length", "ingress_frame_overflow"] + [
            f"ingress_frame_bytes_{i}" for i in range(33)] + ["ingress_resetActive", "ingress_programBusy", "resetEpoch"]:
        replace("output-" + field, f"assign out_bits_{field} = in_bits_{field};",
                f"assign out_bits_{field} = ~in_bits_{field};", "COMBINATIONAL_LOGIC")
        for probe in ("packed_4_probe", "packed_7_probe"):
            pattern = re.compile(r"(wire\s+\[336:0\]\s+" + probe + r"\s*=)(.*?);", re.S)
            matches = list(pattern.finditer(original))
            if len(matches) != 1: raise AssertionError((probe, "emitter shape"))
            match = matches[0]
            changed, count = re.subn(r"\bin_bits_" + re.escape(field) + r"\b", "~in_bits_" + field, match[2])
            if count != 1: raise AssertionError((probe, field, count))
            check(probe + "-" + field, original[:match.start(2)] + changed + original[match.end(2):],
                  "REGISTERS_OR_PROBES")
    replace("initializer-phase-inverted", "acknowledge = 1'h0", "acknowledge = 1'h1", "INITIALIZERS")
    replace("initializer-not-synthesis-guarded", "`ifdef ENABLE_INITIAL_REG_", "`ifndef ENABLE_INITIAL_REG_", "INITIALIZERS")
    replace("preamble-macro-code", "`define INIT_RANDOM\n", "`define INIT_RANDOM acknowledge = 1;\n", "PORTS_OR_PREAMBLE")
    replace("preamble-macro-swallowed-directive", "`define RANDOMIZE\n  `endif",
            "`define RANDOMIZE `endif", "PREPROCESSOR_LINES")
    for label, extra in (
            ("extra-clocked-writer", "always @(posedge clock) acknowledge <= 1'b1;"),
            ("extra-combinational-writer", "always_comb requestSync = in_req;"),
            ("extra-initial", "initial begin #100 acknowledge = 1'b1; end"),
            ("extra-initial-force", "initial begin force requestSync = 1'b1; end"),
            ("extra-final", "final acknowledge = 1'b1;"),
            ("extra-assignment", "assign out_valid = in_req;"),
            ("extra-instance", "Unknown hidden();"),
            ("extra-task", "task corrupt; acknowledge = 1'b1; endtask"),
            ("extra-initial-macro", "`define INIT_RANDOM acknowledge = 1'b1;")):
        check(label, original.replace("endmodule", extra + "\nendmodule"), "COMBINATIONAL_LOGIC")
    # Declarations are source of truth too, not only the scope catalogue supplied by a caller.
    replace("extra-register", "  wire         packed_9_probe", "  reg extra;\n  wire         packed_9_probe",
            "REGISTERS_OR_PROBES")
    replace("port-width-truncation", "[63:0] in_bits_resetEpoch", "[62:0] in_bits_resetEpoch", "PORTS_OR_PREAMBLE")
    # Original inputs are read-only throughout this campaign.
    if rtl_path.read_bytes() != original_bytes: raise AssertionError("ORIGINAL_RECEIPT_RTL_MODIFIED")
    result["original_preserved"] = True
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path)
    args, unit_args = parser.parse_known_args()
    if bool(args.export) != bool(args.out): parser.error("--export and --out must be supplied together")
    evidence = PolicyRunEvidence(args.export, [Path(__file__), Path(__file__).with_name("check_frame_receipt.py")])
    tests = unittest.main(argv=[sys.argv[0], *unit_args], exit=False)
    if not tests.result.wasSuccessful(): raise SystemExit(1)
    if args.export:
        results = []
        for directory in args.export:
            saved = args.out.parent / (args.out.stem + "-mutants") / directory.name
            first = actual_rtl_controls(directory, saved=saved)
            results.append(first)
            if first["receipt"].endswith("ca_child_frame_bridge"):
                results.extend(actual_rtl_controls(directory, i, saved=saved) for i in range(1, 5))
        if {r["module"].split("FrameReceipt")[0] for r in results} != {"FourPhase", "Click"}:
            raise AssertionError("Actual receipt controls require both native variants")
        report = dict(schema="riscay-frame-receipt-policy-controls-v1", status="PASS", exports=results,
                      attestation=evidence.finish(),
                      qualification="emitted-RTL validator controls; not simulation or physical qualification")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("FRAME_RECEIPT_POLICY_CONTROLS_PASS", sum(len(r["cases"]) for r in results))

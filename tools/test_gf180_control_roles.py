# SPDX-License-Identifier: Apache-2.0
"""Role/binding rejection and independent gate-graph functional controls."""
import copy
import itertools
import json
from pathlib import Path
import tempfile
import unittest
import unittest.mock
from unittest.mock import patch

from gf180_control_roles import CONTROL, DATA, MODEL, load_catalogue, resolve_roles
from gf180_physical import adapter, prepare, sha, SC


def primitive(name, width=1, delay=10000000, reset=0, op=0):
    return dict(id=name, rtl_path="Top." + name, model=MODEL, view="behavioral",
                parameters=dict(WIDTH=str(width), DELAY_FS=str(delay), RESET_VALUE=str(reset), OP=str(op)))


def fixture():
    return dict(module="Top", rtl_path="Top", children=[],
                primitives=[primitive("scalar_data"), primitive("vector_guard", 4, 32000000)],
                timing=[dict(id="transform", kind="bundled-data-path-v1", delay_owner=[],
                             delay_cell="scalar_data", budget=dict(min_fs="10000000",
                             model_fs="10000000", max_fs="10000000"))])


CATALOGUE = {"Top": {"scalar_data": DATA, "vector_guard": CONTROL}}


def evaluate(circuit, a, b, reset, width):
    values = {"reset": reset}
    values.update({f"{port}[{i}]": (value >> i) & 1 for port, value in (("a", a), ("b", b)) for i in range(width)})
    for cell in circuit.cells:
        kind, p = cell["cell"].removeprefix(SC), cell["pins"]
        if kind == "inv_1": values[p["ZN"]] = 1 - values[p["I"]]
        elif kind in ("buf_1", "buf_4", "buf_8", "dlyd_1"): values[p["Z"]] = values[p["I"]]
        elif kind == "and2_1": values[p["Z"]] = values[p["A1"]] & values[p["A2"]]
        elif kind == "or2_1": values[p["Z"]] = values[p["A1"]] | values[p["A2"]]
        else: raise AssertionError("UNREVIEWED_GRAPH_CELL_" + kind)
    return sum(values[f"q[{i}]"] << i for i in range(width))


class ControlRoles(unittest.TestCase):
    def test_prepare_binds_roles_before_emitting_parameter_wrappers(self):
        # Exercise the real inventory, resolver, grouping and wrapper writer.
        # Only unrelated PDK/SRAM assets and chip-shell generation are stubbed.
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder); export = base / "export"; export.mkdir()
            (base / "soc").mkdir()
            (base / "soc/sram-lock.json").write_text('{"assets":{}}')
            root = fixture(); root.update(module="FourPhaseFrameStore", rtl_path="FourPhaseSoc.store", endpoints=[])
            root["timing"][0]["delay_cell"] = "data_delay"
            for p, name in zip(root["primitives"], ("data_delay", "return_guard")):
                p.update(id=name, rtl_path="FourPhaseSoc.store." + name,
                         ports=[dict(name="reset", width=1, direction="input"),
                                dict(name="a", width=int(p["parameters"]["WIDTH"]), direction="input"),
                                dict(name="q", width=int(p["parameters"]["WIDTH"]), direction="output")])
            contract = dict(manifest=dict(top="FourPhaseSoc", design=dict(module="FourPhaseSoc",
                rtl_path="FourPhaseSoc", primitives=[], timing=[], endpoints=[], children=[dict(id="store", contract=root)])))
            (export / "contract.json").write_text(json.dumps(contract))
            (export / "ports.json").write_text('{"top":"FourPhaseSoc","nodes":[]}')
            (export / "filelist.f").write_text("FourPhaseSoc.sv\nFourPhaseFrameStore.sv\n" + MODEL + ".sv\n")
            (export / "FourPhaseSoc.sv").write_text("module FourPhaseSoc(); FourPhaseFrameStore store (); endmodule\n")
            (export / "FourPhaseFrameStore.sv").write_text("module FourPhaseFrameStore();\n" +
                "\n".join(MODEL + " " + p["id"] + " ();" for p in root["primitives"]) + "\nendmodule\n")
            (export / (MODEL + ".sv")).write_text("module " + MODEL +
                " #(parameter WIDTH=1, OP=0, RESET_VALUE=0, DELAY_FS=1)(input reset, input [WIDTH-1:0] a, output [WIDTH-1:0] q); endmodule\n")
            (export / "physical-policy.json").write_text(json.dumps(dict(schema="riscay-physical-policy-v3",
                policy_enabled=True, variant="bd", timing_policy="current-supported-digital", qualification="unqualified",
                verification_layers="inline", timing_intent="contract.json",
                service_max_hz=20000000, application_reset=dict(qualifier_edges=8, native_hold_edges=64, native_release_edges=64,
        digital_delay_limit_fs="250000000", measured_local_guard_reset_max_fs="1550000000",
        minimum_native_hold_fs="3150000000", minimum_native_release_fs="3150000000",
        qualification="unqualified", scope="local-guard-margin-only"),
                contract_sha256=sha(export / "contract.json"), ports_sha256=sha(export / "ports.json"))))
            def shell(_export, out, _manifest, _policy):
                for name in ("RiscayMcuDigital.sv", "riscay_reset_hold.sv"): (out / name).write_text("// shell stub\n")
            with patch("gf180_physical.ROOT", base), patch("export_structure.validate"), patch("gf180_physical.pdk_verify"), \
                 patch("gf180_physical.guard_floor", return_value=1.4), patch("gf180_physical.physical_top", side_effect=shell):
                out = base / "mapped"
                self.assertEqual(prepare(export, out, base), 2)
                mapping = json.loads((out / "mapping.json").read_text())
                by_role = {b["requirements"]["role"]: b for b in mapping["bindings"]}
                self.assertEqual(sum(c["cell"] == SC + "dlyd_1" for c in by_role[CONTROL]["cells"]), 112)
                self.assertEqual(sum(c["cell"] == SC + "buf_1" for c in by_role[DATA]["cells"]), 1)
                self.assertEqual(by_role[DATA]["role_evidence"]["FourPhaseSoc.store.data_delay"]["timing"][0]["timing_id"], "transform")
                from gf180_control_roles import CATALOGUE as catalogue_path
                self.assertEqual(mapping["control_roles_sha256"], sha(catalogue_path))
                wrapper = (out / (MODEL + ".sv")).read_text()
                self.assertIn("RISCAY_UNMAPPED_ASYNC_PARAMETERIZATION reject", wrapper)
                root["primitives"][1]["view"] = "constraint-marker"
                (export / "contract.json").write_text(json.dumps(contract))
                with self.assertRaisesRegex(ValueError, "NONBEHAVIORAL_GATE"):
                    prepare(export, base / "passive-rejected", base)
                self.assertFalse((base / "passive-rejected").exists())
                root["primitives"][1]["view"] = "behavioral"
                root["primitives"][1]["parameters"] = dict(root["primitives"][0]["parameters"])
                root["primitives"][1]["ports"] = copy.deepcopy(root["primitives"][0]["ports"])
                (export / "contract.json").write_text(json.dumps(contract))
                with self.assertRaisesRegex(ValueError, "PARAMETER_ROLE_COLLISION"):
                    prepare(export, base / "rejected", base)
                self.assertFalse((base / "rejected").exists())

    def test_scalar_data_and_vector_guard_are_independent_of_width(self):
        result = resolve_roles(fixture(), CATALOGUE)
        self.assertEqual(result["Top.scalar_data"]["role"], DATA)
        self.assertEqual(result["Top.vector_guard"]["role"], CONTROL)
        self.assertEqual(result["Top.scalar_data"]["timing"][0]["timing_id"], "transform")

    def test_exact_child_id_resolves_delegated_delay_owner(self):
        root = fixture()
        data = root["primitives"].pop(0)
        data["rtl_path"] = "Top.physical_child.renamed_wire"
        root["children"] = [dict(id="logical_child", contract=dict(module="Top_17",
            rtl_path="Top.physical_child", children=[], timing=[], primitives=[data]))]
        root["timing"][0]["delay_owner"] = ["logical_child"]
        result = resolve_roles(root, CATALOGUE)
        self.assertEqual(result[data["rtl_path"]]["timing"][0]["owner"], "Top")
        root["timing"][0]["delay_owner"] = ["physical_child"]
        with self.assertRaisesRegex(ValueError, "MISSING_DELAY_OWNER"):
            resolve_roles(root, CATALOGUE)

    def test_canonical_contracts_resolve_exact_data_delay(self):
        for kind in ("click-bundling-v1", "long-hold-bundling-v2"):
            root = fixture()
            root["primitives"][0]["id"] = "data_delay"
            budget = root["timing"][0]["budget"]
            t = dict(id="bundle", kind=kind)
            if kind == "click-bundling-v1": t["cells"] = {"data_delay": budget}
            else: t["data_delay"] = budget
            root["timing"] = [t]
            result = resolve_roles(root, {"Top": {"data_delay": DATA, "vector_guard": CONTROL}})
            self.assertEqual(result["Top.scalar_data"]["role"], DATA)

    def test_missing_retargeted_and_inconsistent_timing_references_reject(self):
        mutations = [
            (lambda r: r.update(timing=[]), "REFERENCE_DISAGREES"),
            (lambda r: r["timing"][0].update(delay_cell="absent"), "MISSING_DELAY_CELL"),
            (lambda r: r["timing"][0].update(delay_owner=["absent"]), "MISSING_DELAY_OWNER"),
            (lambda r: r["timing"][0]["budget"].update(model_fs="9000000"), "INVALID_DATA_BUDGET"),
            (lambda r: r["primitives"][0]["parameters"].update(DELAY_FS="9000000"), "DATA_BUDGET_DISAGREES"),
            (lambda r: r["primitives"][0]["parameters"].update(OP="1"), "UNSUPPORTED_DATA_OPERATION"),
            (lambda r: r["primitives"][0].update(model="Different"), "UNSUPPORTED_DATA_MARKER"),
            (lambda r: r["primitives"][1].update(id="new_guard"), "UNREVIEWED"),
            (lambda r: r["primitives"][1].update(view="constraint-marker"), "NONBEHAVIORAL_GATE"),
            (lambda r: r.update(module="Other"), "UNREVIEWED"),
        ]
        for mutation, error in mutations:
            with self.subTest(error=error):
                root = fixture(); mutation(root)
                with self.assertRaisesRegex(ValueError, error): resolve_roles(root, CATALOGUE)
        root = fixture()
        root["timing"][0].update(delay_cell="vector_guard")
        root["timing"][0]["budget"] = dict(min_fs="32000000", model_fs="32000000", max_fs="32000000")
        with self.assertRaisesRegex(ValueError, "REFERENCE_DISAGREES"): resolve_roles(root, CATALOGUE)

    def test_duplicate_identifiers_paths_and_parameter_roles_reject(self):
        for field in ("primitives", "timing"):
            root = fixture(); root[field].append(copy.deepcopy(root[field][0]))
            with self.assertRaisesRegex(ValueError, "DUPLICATE_" + field.upper()): resolve_roles(root, CATALOGUE)
        root = fixture(); root["primitives"][1]["rtl_path"] = root["primitives"][0]["rtl_path"]
        with self.assertRaisesRegex(ValueError, "DUPLICATE_PRIMITIVE_PATH"): resolve_roles(root, CATALOGUE)
        root = fixture(); root["primitives"][1]["parameters"] = dict(root["primitives"][0]["parameters"])
        with self.assertRaisesRegex(ValueError, "PARAMETER_ROLE_COLLISION"): resolve_roles(root, CATALOGUE)
        root = fixture(); child = dict(id="x", contract=dict(module="Other", rtl_path="Child", primitives=[], timing=[], children=[]))
        root["children"] = [child, copy.deepcopy(child)]
        with self.assertRaisesRegex(ValueError, "DUPLICATE_CHILDREN"): resolve_roles(root, CATALOGUE)
        root["children"][1]["id"] = "y"
        with self.assertRaisesRegex(ValueError, "DUPLICATE_NODE"): resolve_roles(root, CATALOGUE)

    def test_catalogue_rejects_duplicate_keys_and_unknown_roles(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "roles.json"
            path.write_text('{"schema":"riscay-controlgate-roles-v1","owners":{"Top":{"x":"matched-control-delay","x":"whole-transform-allowance"}}}')
            with self.assertRaisesRegex(ValueError, "DUPLICATE_CATALOGUE_KEY"): load_catalogue(path)
            path.write_text(json.dumps(dict(schema="riscay-controlgate-roles-v1", owners={"Top": {"x": "width-dependent"}})))
            with self.assertRaisesRegex(ValueError, "UNKNOWN_ROLE"): load_catalogue(path)

    def test_explicit_role_required_and_invalid_parameters_reject(self):
        p = primitive("guard", 4)
        for role in (None, "guessed"):
            with self.assertRaisesRegex(ValueError, "EXPLICIT_CONTROL_ROLE_REQUIRED"): adapter(p, 1.4, role=role)
        for changes in (dict(WIDTH="0"), dict(RESET_VALUE="16"), dict(RESET_VALUE="-1"), dict(DELAY_FS="0")):
            bad = copy.deepcopy(p); bad["parameters"].update(changes)
            with self.assertRaisesRegex(ValueError, "INVALID_CONTROL_PARAMETERS"): adapter(bad, 1.4, role=CONTROL)
        for floor in (0, -1, float("inf"), float("nan")):
            with self.assertRaisesRegex(ValueError, "INVALID_GUARD_FLOOR"): adapter(p, floor, role=CONTROL)

    def test_scalar_data_has_no_inserted_guard_chain(self):
        for width in (1, 4, 278):
            graph, req = adapter(primitive("data", width), 1.4, role=DATA)
            self.assertEqual(sum(x["cell"] == SC + "buf_1" for x in graph.cells), width)
            self.assertFalse(any(x["cell"] == SC + "dlyd_1" for x in graph.cells))
            self.assertEqual(req, dict(role=DATA, data_max_ns=10,
                distribution_fanout_limit=16, reset_branch_levels=2 if width>256 else 1,
                distribution_structure=dict(maximum_input_fanout=min(width,16),
                    reset_depth=4 if width>256 else 3)))

    def test_vector_controls_have_independent_preserved_lane_chains(self):
        for delay, count, kind in ((1000000, 9, "buf_1"), (32000000, 28, "dlyd_1"), (110000000, 95, "dlyd_1")):
            graph, req = adapter(primitive("guard", 4, delay), 1.4, role=CONTROL)
            cells = [c for c in graph.cells if c["cell"] == SC + kind]
            self.assertEqual(len(cells), 4 * count)
            # Follow each output backwards: no shared guard segment is allowed.
            drivers = {c["pins"]["Z"]: c["pins"]["I"] for c in cells}
            used = set()
            for lane in range(4):
                node = f"q[{lane}]"; chain = []
                while node in drivers:
                    chain.append(node); node = drivers[node]
                self.assertEqual(len(chain), count)
                self.assertFalse(used.intersection(chain)); used.update(chain)
            self.assertEqual(req["control_min_ns"], delay / 1e6)
            self.assertIn('dont_touch = "yes"', graph.verilog("test", []))

    def test_vector_operation_and_mixed_reset_truth_table(self):
        # Independent mathematical oracle covers all 4-bit lane combinations.
        for role, op, reset_value in itertools.product((CONTROL, DATA), range(3), (0, 5, 10, 15)):
            p = primitive("test", 4, reset=reset_value, op=op)
            if role == DATA and (op or reset_value):
                with self.assertRaisesRegex(ValueError, "UNKNOWN_DATA_ALLOWANCE"): adapter(p, 1.4, role=role)
                continue
            graph, _ = adapter(p, 1.4, role=role)
            for reset, a, b in itertools.product(range(2), range(16), range(16)):
                expected = reset_value if reset else (a if op == 0 else a ^ 15 if op == 1 else a | b)
                self.assertEqual(evaluate(graph, a, b, reset, 4), expected)


if __name__ == "__main__": unittest.main()

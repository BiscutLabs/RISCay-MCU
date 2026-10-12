# SPDX-License-Identifier: Apache-2.0
"""Resolve reviewed ControlGate intent, independently of vector width.

The catalogue is a closed owner/primitive-ID declaration. Data allowances must
also resolve to the contract's exact delay cell and budget. Parameter wrappers
cannot distinguish different roles at the same tuple, so reject that collision.
This binds intent; it does not qualify a complete data path or control envelope.
"""
import json
from pathlib import Path
import re

CATALOGUE = Path(__file__).resolve().parents[1] / "physical/gf180/controlgate-roles.json"
DATA = "whole-transform-allowance"
CONTROL = "matched-control-delay"
MODEL = "ChiselAsyncControlGate_v1"


def require(condition, reason):
    if not condition:
        raise ValueError("CONTROL_ROLE_" + reason)


def load_catalogue(path=CATALOGUE):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            require(name not in result, "DUPLICATE_CATALOGUE_KEY_" + name)
            result[name] = value
        return result
    value = json.loads(Path(path).read_text(), object_pairs_hook=unique)
    require(value["schema"] == "riscay-controlgate-roles-v1", "CATALOGUE_SCHEMA")
    owners = value["owners"]
    require(bool(owners), "EMPTY_CATALOGUE")
    for owner, entries in owners.items():
        require(bool(entries), "EMPTY_OWNER_" + owner)
        require(all(role in (DATA, CONTROL) for role in entries.values()), "UNKNOWN_ROLE_" + owner)
    return owners


def resolve_roles(root, catalogue=None):
    catalogue = load_catalogue() if catalogue is None else catalogue
    ns, paths, primitives = [], set(), {}

    def visit(node):
        path = node["rtl_path"]
        require(path not in paths, "DUPLICATE_NODE_" + path)
        paths.add(path)
        ns.append(node)
        for field in ("primitives", "children", "timing"):
            ids = [x["id"] for x in node[field]]
            require(len(ids) == len(set(ids)), "DUPLICATE_" + field.upper() + "_" + path)
        for p in node["primitives"]:
            require(p["rtl_path"] not in primitives, "DUPLICATE_PRIMITIVE_PATH_" + p["rtl_path"])
            primitives[p["rtl_path"]] = p
        for child in node["children"]:
            visit(child["contract"])
    visit(root)
    references = {}
    for node in ns:
        for timing in node["timing"]:
            kind = timing["kind"]
            if kind == "bundled-data-path-v1":
                dest = node
                require(isinstance(timing["delay_owner"], list), "DELAY_OWNER_TYPE")
                for child_id in timing["delay_owner"]:
                    matches = [c["contract"] for c in dest["children"] if c["id"] == child_id]
                    require(len(matches) == 1, "MISSING_DELAY_OWNER_" + str(child_id))
                    dest = matches[0]
                cell, budget = timing["delay_cell"], timing["budget"]
            elif kind in ("click-bundling-v1", "long-hold-bundling-v2"):
                dest, cell = node, "data_delay"
                budget = timing["cells"][cell] if kind == "click-bundling-v1" else timing[cell]
            else:
                continue
            matches = [p for p in dest["primitives"] if p["id"] == cell]
            require(len(matches) == 1, "MISSING_DELAY_CELL_" + str(cell))
            p = matches[0]
            require(p["model"] == MODEL, "UNSUPPORTED_DATA_MARKER_" + p["model"])
            params = p["parameters"]
            require(int(params["OP"]) == 0 and int(params["RESET_VALUE"]) == 0,
                    "UNSUPPORTED_DATA_OPERATION_" + p["rtl_path"])
            lo, nominal, hi = (int(budget[x]) for x in ("min_fs", "model_fs", "max_fs"))
            require(0 < lo <= nominal <= hi, "INVALID_DATA_BUDGET_" + p["rtl_path"])
            require(nominal == int(params["DELAY_FS"]), "DATA_BUDGET_DISAGREES_" + p["rtl_path"])
            references.setdefault(p["rtl_path"], []).append(dict(
                owner=node["rtl_path"], timing_id=timing["id"], kind=kind, budget=budget))
    roles, tuples = {}, {}
    for node in ns:
        # FIRRTL appends numeric module specializations. No primitive ID or
        # width convention is used to infer intent.
        owner = re.sub(r"_\d+$", "", node["module"])
        for p in node["primitives"]:
            if p["model"] != MODEL:
                continue
            require(p["view"] == "behavioral", "NONBEHAVIORAL_GATE_" + p["rtl_path"])
            role = catalogue.get(owner, {}).get(p["id"])
            require(role in (DATA, CONTROL), "UNREVIEWED_" + owner + "." + p["id"])
            refs = references.get(p["rtl_path"], [])
            require(bool(refs) == (role == DATA), "REFERENCE_DISAGREES_" + p["rtl_path"])
            key = tuple(sorted((k, int(v)) for k, v in p["parameters"].items()))
            require(key not in tuples or tuples[key] == role, "PARAMETER_ROLE_COLLISION")
            tuples[key] = role
            roles[p["rtl_path"]] = dict(role=role, owner=owner, primitive_id=p["id"], timing=refs)
    return roles

# SPDX-License-Identifier: Apache-2.0
"""Closed digital contracts for the MCU-owned selected completion joins."""
import re

BD_COMPLETION_PATH = "held plan selects immediate or completed memory reply"
CLICK_COMPLETION_PATH = "complete response and selected phase feedback before common capture"


def validate_completion(node):
    if not re.fullmatch(r"(?:FourPhase|Click)Completion(?:_[0-9]+)?", node["module"]):
        raise ValueError("COMPLETION_OWNER")
    click = node["module"].startswith("Click")
    protocol = "two-phase-bundled-v1" if click else "four-phase-bundled-v1"
    if ({c["id"]: (c["protocol"], c["role"]) for c in node["channels"]} !=
            {n: (protocol, "output" if n in ("response", "creditReturn") else "input")
             for n in ("plan", "memory", "telemetry", "housekeeping", "response", "creditReturn")}):
        raise ValueError("COMPLETION_PROTOCOL")
    timing = {t["id"]: t for t in node["timing"]}
    expected = {"completion_mux", "capture_aperture"} if click else {"completion_mux"}
    if set(timing) != expected or len(node["timing"]) != len(expected):
        raise ValueError("COMPLETION_TIMING_INVENTORY")
    path = dict(kind="bundled-data-path-v1", logic=CLICK_COMPLETION_PATH if click else BD_COMPLETION_PATH,
                delay_owner=[] if click else ["reply"], delay_cell="data_delay",
                source="result_sources", sink="register_data" if click else "result")
    if any(timing["completion_mux"].get(k) != v for k, v in path.items()):
        raise ValueError("COMPLETION_PATH_IDENTITY")
    widths = {"plan_data": 36, "memory_data": 33, "telemetry_data": 1, "housekeeping_data": 1,
              "response_data": 33, "creditReturn_data": 1, "result_sources": 76 if click else 69,
              "register_data" if click else "result": 37 if click else 33}
    if click:
        widths.update(captured=37, capture_event=1)
    endpoints = {e["id"]: e["width"] for e in node["endpoints"]}
    if any(endpoints.get(k) != v for k, v in widths.items()):
        raise ValueError("COMPLETION_PATH_WIDTH")
    cells = {p["id"]: p for p in node["primitives"]}
    expected_cells = {}
    def cell(name, model, **params):
        expected_cells[name] = ("ChiselAsync" + model + "_v1", {k: str(v) for k, v in params.items()})
    def gate(name, width=1, op=0, delay=1000000, initial=0):
        cell(name, "ControlGate", WIDTH=width, OP=op, DELAY_FS=delay, RESET_VALUE=initial)
    def and_gate(name):
        gate(name+"_na", op=1, initial=1); gate(name+"_nb", op=1, initial=1)
        gate(name+"_or", op=2, initial=1); gate(name, op=1)
    def asym(name, common, rising, falling):
        cell(name, "AsymmetricC", COMMON=common, RISING=rising, FALLING=falling,
             DELAY_FS=1000000, RESET_VALUE=0, COMMON_INVERT=0, RISING_INVERT=0, FALLING_INVERT=0)
    if click:
        if node["children"]:
            raise ValueError("COMPLETION_NATIVE_OWNER")
        aperture = dict(kind="bundled-setup-hold-v1", launch="plan_request", transaction="plan_data",
                        data_valid="register_data", capture="capture_event", captured="captured",
                        setup_fs="100000", hold_fs="100000")
        if any(timing["capture_aperture"].get(k) != v for k, v in aperture.items()):
            raise ValueError("COMPLETION_APERTURE")
        for name in ("plan_phase", "memory_phase", "telemetry_phase", "housekeeping_phase", "payload"):
            cell(name, "EventRegister", WIDTH=33 if name == "payload" else 1, DELAY_FS=1000000, RESET_VALUE=0)
        for name in ("plan_pending", "response_occupied"):
            cell(name, "Xor", DELAY_FS=1000000)
        gate("request_guard", delay=11000000)
        for name in ("memory", "telemetry", "housekeeping"):
            and_gate(name+"_available")
        gate("request_delay", width=3, delay=11000000)
        and_gate("runnable"); gate("data_delay", width=37, delay=10000000)
        # Phase + twenty serial control maxima + skew and low/hold margin.
        gate("acknowledge_guard", width=4, delay=210200001)
        gate("output_guard", delay=210200001)
    else:
        if (len(node["children"]) != 1 or node["children"][0]["id"] != "reply" or
                not re.fullmatch(r"FourPhaseStage(?:_[0-9]+)?", node["children"][0]["contract"]["module"])):
            raise ValueError("COMPLETION_REPLY_OWNER")
        gate("request_guard", delay=11000000)
        for name in ("memory_ack", "telemetry_ack", "housekeeping_ack"):
            and_gate(name)
        asym("rendezvous", 1, 3, 3); asym("plan_ack", 1, 0, 3)
    # Timing-marker primitives are checked separately by the unchanged library.
    markers = {"completion_mux_marker", "capture_aperture_marker"} if click else {"completion_mux_marker"}
    if (len(cells) != len(node["primitives"]) or set(cells) != set(expected_cells) | markers or
            any(cells[n]["model"] != "ChiselAsyncTimingMarker_v1" for n in markers)):
        raise ValueError("COMPLETION_PRIMITIVE_INVENTORY")
    for name, (model, params) in expected_cells.items():
        actual = cells.get(name, {})
        if actual.get("model") != model or any(actual.get("parameters", {}).get(k) != v for k, v in params.items()):
            raise ValueError("COMPLETION_CELL_POLICY:"+name)


def completion_bindings(node):
    e = {x["id"]: x["rtl_path"] for x in node["endpoints"]}
    c = {x["id"]: x["rtl_path"] for x in node["primitives"]}
    if node["module"].startswith("Click"):
        pairs = [(e["register_data"], c["data_delay"]+".q"),
                 (e["register_data"]+"[32:0]", c["payload"]+".d"),
                 (e["register_data"]+"[33]", c["plan_phase"]+".d"),
                 (e["capture_event"], c["payload"]+".trigger"),
                 (e["response_data"], c["payload"]+".q"),
                 (e["response_request"], c["output_guard"]+".q"),
                 (c["plan_phase"]+".q", c["output_guard"]+".a")]
        for i, name in enumerate(("plan", "memory", "telemetry", "housekeeping")):
            pairs += [(e["register_data"]+f"[{33+i}]", c[name+"_phase"]+".d"),
                      (e["captured"]+f"[{33+i}]", c[name+"_phase"]+".q"),
                      (e["capture_event"], c[name+"_phase"]+".trigger"),
                      (c[name+"_phase"]+".q", c["acknowledge_guard"]+f".a[{i}]"),
                      (e[name+"_acknowledge"], c["acknowledge_guard"]+f".q[{i}]")]
        pairs += [(e["captured"]+"[32:0]", c["payload"]+".q")]
        prefixes = ("runnable", "memory_available", "telemetry_available", "housekeeping_available")
    else:
        reply = node["children"][0]["contract"]
        child_endpoints = {x["id"]: x["rtl_path"] for x in reply["endpoints"]}
        data = next(x["rtl_path"] for x in reply["primitives"] if x["id"] == "data_delay")
        pairs = [(e["result"], child_endpoints["in_data"]), (e["result"], data+".a"),
                 (c["rendezvous"]+".q", child_endpoints["in_request"]),
                 (e["plan_acknowledge"], c["plan_ack"]+".q"),
                 (c["plan_ack"]+".common", child_endpoints["in_acknowledge"])]
        for name in ("memory", "telemetry", "housekeeping"):
            pairs += [(e[name+"_acknowledge"], c[name+"_ack"]+".q")]
        pairs += [(c["plan_ack"]+".falling", "{"+",".join(e[n+"_acknowledge"] for n in ("memory","telemetry","housekeeping"))+"}")]
        pairs += [(e["response_data"], child_endpoints["out_data"]),
                  (e["response_request"], child_endpoints["out_request"]),
                  (e["creditReturn_acknowledge"], child_endpoints["out_acknowledge"])]
        prefixes = ("memory_ack", "telemetry_ack", "housekeeping_ack")
    # Compare full selection and feedback equations, not just downstream aliases.
    cat = lambda xs: "{"+",".join(xs)+"}"
    selected = {name: e["plan_data"]+f"[{2-i}]" for i, name in enumerate(("memory", "telemetry", "housekeeping"))}
    result = f"({selected['memory']} ? {e['memory_data']} : {e['plan_data']}[35:3])"
    pairs += [(e["plan_request"], c["request_guard"]+".a")]
    if node["module"].startswith("Click"):
        feedback = [f"({selected[n]} ? {e[n+'_request']} : {c[n+'_phase']}.q)"
                    for n in ("housekeeping", "telemetry", "memory")]
        pairs += [(c["data_delay"]+".a", cat(feedback+[e["plan_request"], result])),
                  (e["result_sources"], cat([e["plan_data"], e["memory_data"], e["plan_request"],
                   e["memory_request"], e["telemetry_request"], e["housekeeping_request"],
                   c["memory_phase"]+".q", c["telemetry_phase"]+".q", c["housekeeping_phase"]+".q"])),
                  (c["plan_pending"]+".a", c["request_guard"]+".q"),
                  (c["plan_pending"]+".b", c["plan_phase"]+".q"),
                  (c["response_occupied"]+".a", c["plan_phase"]+".q"),
                  (c["response_occupied"]+".b", e["creditReturn_acknowledge"]),
                  (c["runnable_na"]+".a", c["plan_pending"]+".q"),
                  (c["runnable_nb"]+".a", "!"+c["response_occupied"]+".q"),
                  (e["capture_event"], c["housekeeping_available"]+".q")]
        readiness = [f"(!{selected[n]} || ({e[n+'_request']} != {c[n+'_phase']}.q))"
                     for n in ("housekeeping", "telemetry", "memory")]
        pairs.append((c["request_delay"]+".a", cat(readiness)))
        previous = "runnable"
        for i, n in enumerate(("memory", "telemetry", "housekeeping")):
            pairs += [(c[n+"_available_na"]+".a", c[previous]+".q"),
                      (c[n+"_available_nb"]+".a", c["request_delay"]+f".q[{i}]")]
            previous = n+"_available"
    else:
        pairs += [(e["result"], result), (e["result_sources"], cat([e["plan_data"],e["memory_data"]])),
                  (c["rendezvous"]+".common", c["request_guard"]+".q"),
                  (c["rendezvous"]+".rising", cat([f"(!{selected[n]} || {e[n+'_request']})"
                   for n in ("memory","telemetry","housekeeping")])),
                  (c["rendezvous"]+".falling", cat([f"({selected[n]} && {e[n+'_request']})"
                   for n in ("memory","telemetry","housekeeping")]))]
        for n in ("memory", "telemetry", "housekeeping"):
            pairs += [(c[n+"_ack_na"]+".a", child_endpoints["in_acknowledge"]),
                      (c[n+"_ack_nb"]+".a", selected[n])]
    for prefix in prefixes:
        pairs += [(c[prefix+"_na"]+".q", c[prefix+"_or"]+".a"),
                  (c[prefix+"_nb"]+".q", c[prefix+"_or"]+".b"),
                  (c[prefix+"_or"]+".q", c[prefix]+".a")]
    return pairs + [(e["creditReturn_request"], e["response_acknowledge"]),
                    (e["creditReturn_data"], "1'b0")]

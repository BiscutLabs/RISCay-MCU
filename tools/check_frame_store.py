# SPDX-License-Identifier: Apache-2.0
"""Closed structural policy for the native four-bank frame payload owners.

This is a structural attestation, not a functional or timing proof. The exact
emitted owner and BD buffer bodies are pinned after independent source review.
Only comments, whitespace and the emitter's numeric module-clone suffixes are
normalized. The complete declared port ABI is preserved, including availability;
no statements, writers, expressions or ports are erased.
Runtime capture/fault controls independently qualify the reviewed implementation.
"""
import hashlib
import re
from pathlib import Path

from check_frame_receipt import FIELDS


MODEL = r"(?:FourPhase|Click)FrameStore(?:_[0-9]+)?"
RTL_FINGERPRINTS = {
    "bd": {
        "9a41aab3d945799d3ba183289dbbdbfc3f7b198b707972a4a7d9e4e604e7d71d",  # embedded aliases
        "b925ac81ae6b336b39146d00a6366350e2c2abfeaba6aa8273650ac4041e32a6",  # standalone aliases
    },
    "click": {
        "704590623294de4831450f9d2f2f4df00c9f07bd950cebf56145c610a7bf3d2c",
        "3bb3442d6497c7b8b5b2e484733c1314b886f82bfe200ef2485688db9b73206d",
    },
}
BD_BUFFER_FINGERPRINT = "d776db42fe7986486ecefa402db6f48b0f594e6f4dd40d1735116842380d2f45"


def require(value, detail):
    if not value:
        raise ValueError("FRAME_STORE_" + detail)


def canonical_rtl(text):
    # Numeric clone names are only normalized for these three exact module
    # families. Their actual instance targets are separately resolved and read.
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    text = re.sub(r"\b(LongHoldBuffer|FourPhaseFrameStore|ClickFrameStore)(?:_\d+)?\b", r"\1", text)
    return re.sub(r"\s+", "", text)


def rtl_fingerprint(text):
    return hashlib.sha256(canonical_rtl(text).encode("utf-8")).hexdigest()


def primitive_spec(click):
    gate = lambda width, delay: ("ChiselAsyncControlGate_v1", dict(WIDTH=str(width), OP="0", RESET_VALUE="0", DELAY_FS=str(delay)))
    register = lambda width: ("ChiselAsyncEventRegister_v1", dict(WIDTH=str(width), RESET_VALUE="0", DELAY_FS="1000000"))
    atomic = ("ChiselAsyncAnd_v1", dict(INPUTS="2", INVERT="0", DELAY_FS="1000000"))
    if click:
        result = {"payload"+str(i): register(337) for i in range(4)}
        result.update({"phase"+str(i): register(1) for i in range(4)})
        result.update(accepted_phase=("ChiselAsyncPhaseRegister_v1", dict(RESET_VALUE="0", DELAY_FS="1000000")),
                      pending=("ChiselAsyncXor_v1", dict(DELAY_FS="1000000")), capture=atomic,
                      request_delay=gate(1,11000000), data_delay=gate(1352,10000000),
                      acknowledge_guard=gate(1,32000000), output_guard=gate(4,110000000))
    else:
        result = dict(route=register(2), data_delay=gate(2,10000000), request_delay=gate(1,11000000),
                      route_decode=gate(4,1000000), request_guard=gate(1,32000000), return_guard=gate(4,32000000))
        result.update({"route"+str(i): atomic for i in range(4)})
    return result


def timing_spec(click):
    path, aperture = ("bank_transform","bank_aperture") if click else ("route_path","route_aperture")
    source, sink, capture, captured = ("sources","register_data","capture_event","captured") if click else (
        "slot","route_data","route_capture","route_value")
    logic = ("full selected source/unselected retained data and phase muxes, including every feedback bit" if click else
             "temporary slot to retained native route; 10 ns complete data budget")
    return [dict(id=path,kind="bundled-data-path-v1",marker=path+"_marker",source=source,sink=sink,logic=logic,
                 logic_model_fs="0",budget=dict(min_fs="10000000",max_fs="10000000",model_fs="10000000"),
                 delay_owner=[],delay_cell="data_delay",accounting="included-in-delay-cell; replace-model-with-mapped-path; not-additive"),
            dict(id=aperture,kind="bundled-setup-hold-v1",marker=aperture+"_marker",launch="in_request",transaction=source,
                 data_valid=sink,capture=capture,captured=captured,setup_fs="100000",hold_fs="100000",mode="digital-model",
                 provenance="explicit fixture contract",pulse_policy="one outstanding launch; identity travels with data; capture on rising edge")]


def validate_frame_store_metadata(node, resolved=False):
    model = node.get("module", "")
    require(re.fullmatch(MODEL, model), "OWNER")
    click = model.startswith("Click")
    require(type(node.get("capacity")) is int and node["capacity"] == 4, "CAPACITY")
    require(node.get("reset_domain") == "root", "POR_DOMAIN")
    channels = node.get("channels", [])
    require(len(channels) == 5 and [c.get("id") for c in channels] == ["in","bank0","bank1","bank2","bank3"], "CHANNEL_INVENTORY")
    protocol = "two-phase-bundled-v1" if click else "four-phase-bundled-v1"
    for c in channels:
        name = c["id"]; port = "in" if name == "in" else "banks_"+name[-1]
        expected_layout = [dict(field="bits."+field, lsb=lsb, width=width, signed=False,
                               source=f"~|{model}>{port}.bits.{field}") for field,lsb,width in FIELDS]
        require(c.get("protocol") == protocol and c.get("role") == ("input" if name == "in" else "output") and
                c.get("reset_domain") == "root" and c.get("token_contract") == "ordered-lossless-reset-abort-v1" and
                c.get("request") == name+"_request" and c.get("data") == name+"_data" and
                c.get("acknowledge") == name+"_acknowledge" and c.get("layout") == expected_layout,
                "CHANNEL:"+name)
        require(all(type(f.get("lsb")) is int and type(f.get("width")) is int and f.get("signed") is False
                    for f in c["layout"]), "CHANNEL_TYPES:"+name)
        environment = ("binary inputs; coordinated reset to 00; every ack edge delivers; data held while req != ack" if click else
                       "binary inputs; coordinated reset; data held through return to idle")
        require(c.get("phases") == ["00","10","11","01","00"] and c.get("environment") == environment,
                "CHANNEL_ENVIRONMENT:"+name)
    spec = primitive_spec(click)
    actual = [p for p in node.get("primitives", []) if p.get("model") != "ChiselAsyncTimingMarker_v1"]
    require(len(actual) == len(spec) and {p.get("id") for p in actual} == set(spec), "PRIMITIVE_INVENTORY")
    for p in actual:
        require((p.get("model"),p.get("parameters")) == spec[p["id"]], "PRIMITIVE_PARAMETERS:"+p["id"])
    timing = timing_spec(click)
    require(node.get("timing") == timing, "TIMING")
    markers = [p for p in node.get("primitives", []) if p.get("model") == "ChiselAsyncTimingMarker_v1"]
    require(len(markers) == 2 and [p.get("id") for p in markers] == [t["marker"] for t in timing], "MARKER_INVENTORY")
    for index,marker in enumerate(markers):
        params = {kind+"_"+bound+"_FS":"0" for kind in ("ACKNOWLEDGE","A","B","DATA","LATCH","LONG_HOLD")
                  for bound in ("MIN","MAX","MODEL")}
        params.update(HOLD_FS="0",SETUP_FS="0",MATCHED_FS="0",OUTPUT_FS="0")
        if index == 0:
            params.update(KIND="3",WIDTH="3043" if click else "4",DATA_MIN_FS="10000000",DATA_MAX_FS="10000000",DATA_MODEL_FS="10000000")
        else:
            params.update(KIND="1",WIDTH="4397" if click else "8",HOLD_FS="100000",SETUP_FS="100000")
        require(marker.get("parameters") == params, "MARKER_PARAMETERS:"+marker["id"])
    endpoints = {c["id"]+"_"+kind:width for c in channels for kind,width in (("request",1),("data",337),("acknowledge",1))}
    endpoints.update(reset=1,slot=2,available=4,busy=1)
    endpoints.update(dict(sources=1691,register_data=1352,captured=1352,capture_event=1) if click else
                     dict(route_data=2,route_capture=1,route_value=2))
    actual_endpoints = node.get("endpoints", [])
    require(len(actual_endpoints) == len(endpoints) and {e.get("id") for e in actual_endpoints} == set(endpoints) and
            all(type(e.get("width")) is int and e["width"] == endpoints[e["id"]] for e in actual_endpoints), "ENDPOINT_INVENTORY")
    sources = {c["id"]+"_"+kind: re.escape("~|"+model+">"+(
        "in" if c["id"] == "in" else "banks_"+c["id"][-1])+"."+member)
        for c in channels for kind,member in (("request","req"),("data","bits"),("acknowledge","ack"))}
    sources.update({name:re.escape("~|"+model+">"+name) for name in ("reset","slot","available","busy")})
    if click:
        sources.update(sources=re.escape("~|"+model+">sourceBits"), captured=re.escape("~|"+model+">capturedBits"),
                       capture_event=re.escape("~|"+model+">captureEvent"),
                       register_data=re.escape("~|"+model+">registerDataProbe"))
    else:
        sources.update(route_capture=re.escape("~|"+model+">tagCapture"),
                       route_data=re.escape("~|"+model+">routeDataProbe"),
                       route_value=re.escape("~|"+model+">routeValueProbe"))
    for e in actual_endpoints:
        # The strict library first validates this semantic path, then resolves
        # it through its hash-bound probe ABI and checks the actual net width.
        # The subsequent pin comparisons must use that resolved path verbatim.
        path_ok = (e.get("rtl_path", "").startswith(node["rtl_path"]+".") if resolved else
                   e.get("rtl_path") == node["rtl_path"]+f'.ca_p_{len(e["id"])}_'+e["id"])
        require(re.fullmatch(sources[e["id"]],e.get("source", "")) and
                path_ok, "ENDPOINT_SOURCE:"+e["id"])
    children = node.get("children", [])
    require(len(children) == (0 if click else 4) and
            [c.get("id") for c in children] == ([] if click else ["storage"+str(i) for i in range(4)]), "CHILD_INVENTORY")
    if not click:
        for child in children:
            c = child["contract"]
            require(re.fullmatch(r"LongHoldBuffer(?:_[0-9]+)?", c.get("module", "")) and
                    c.get("reset_domain") == "root" and type(c.get("capacity")) is int and c["capacity"] == 1,
                    "BD_BUFFER_OWNER")
            require(len(c.get("channels", [])) == 2 and
                    all(x.get("protocol") == "four-phase-bundled-v1" and
                        sum(f["width"] for f in x.get("layout", [])) == 337 for x in c["channels"]), "BD_BUFFER_SCHEMA")
    return click


def validate_frame_store(node, directory, resolved=False):
    """Close all custom owner RTL and actual BD buffer implementations."""
    directory = Path(directory)
    click = validate_frame_store_metadata(node,resolved=resolved); variant = "click" if click else "bd"
    path = directory / (node["module"]+".sv")
    require(path.is_file(), "OWNER_FILE")
    text = path.read_text(encoding="utf-8")
    fingerprint = rtl_fingerprint(text)
    require(fingerprint in RTL_FINGERPRINTS[variant], "RTL_FINGERPRINT:"+variant)
    files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()}
    if not click:
        plain = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
        for child in node["children"]:
            name = child["contract"]["rtl_path"].rsplit(".",1)[-1]
            models = re.findall(r"\b(LongHoldBuffer(?:_[0-9]+)?)\s+"+re.escape(name)+r"\s*\(", plain)
            require(len(models) == 1, "BD_BUFFER_INSTANCE:"+name)
            body = directory / (models[0]+".sv")
            require(body.is_file(), "BD_BUFFER_FILE:"+name)
            require(rtl_fingerprint(body.read_text(encoding="utf-8")) == BD_BUFFER_FINGERPRINT, "BD_BUFFER_RTL:"+name)
            files[body.name] = hashlib.sha256(body.read_bytes()).hexdigest()
    return dict(variant=variant, node=node["rtl_path"], fingerprint=fingerprint, files_sha256=files)


def validate_frame_stores(manifest, directory, resolved=False):
    results = []
    def visit(node):
        if node.get("module", "").startswith(("FourPhaseFrameStore","ClickFrameStore")):
            results.append(validate_frame_store(node,directory,resolved=resolved))
        for child in node.get("children", []): visit(child["contract"])
    visit(manifest["design"])
    return results

# SPDX-License-Identifier: Apache-2.0
"""Closed policy for the payload-free, POR-owned I2C frame receipts.

Only comments and whitespace are ignored in emitted RTL. The complete firtool
module, including ports, packed probes, initializer guards and all writers, is
pinned; an emitter change requires review. This does not qualify the external
publisher-to-mailbox timing path or the work-clock acceptance connection.
"""
from pathlib import Path
import re


MODEL = r"(?:FourPhase|Click)FrameReceipt(?:_[0-9]+)?"
REGISTERS = ("localReset_release_0", "localReset_release_1", "requestMeta",
             "requestSync", "acknowledge")
# Low-to-high packing, independently fixed by I2cFrame/ControlIngress/HostFrame.
FIELDS = (("resetEpoch", 0, 64), ("ingress.programBusy", 64, 1),
          ("ingress.resetActive", 65, 1)) + tuple(
    (f"ingress.frame.bytes[{i}]", 66 + i * 8, 8) for i in range(33)) + (
    ("ingress.frame.overflow", 330, 1), ("ingress.frame.length", 331, 6))
ENDPOINTS = {
    "request_meta": (1, "requestMeta"), "request_sync": (1, "requestSync"),
    "acknowledge": (1, "acknowledge"), "in_request": (1, "in.req"),
    "in_data": (337, "in.bits"), "in_acknowledge": (1, "in.ack"),
    "out_valid": (1, "out.valid"), "out_data": (337, "out.bits"),
    "out_ready": (1, "out.ready"), "out_clock": (1, "clock"),
    "local_reset": (1, "localReset"), "reset": (1, "reset"),
}


def validate_frame_receipt(node):
    """Validate exact channels, all 38 fields, and all twelve endpoint sources."""
    module = node.get("module", "")
    if not re.fullmatch(MODEL, module):
        raise ValueError("FRAME_RECEIPT_OWNER")
    click = module.startswith("Click")
    domain = node.get("reset_domain")
    if not isinstance(domain, str) or not domain:
        raise ValueError("FRAME_RECEIPT_RESET_DOMAIN")
    expected = []
    for name in ("in", "out"):
        channel = dict(id=name, role="input" if name == "in" else "output",
                       reset_domain=domain, token_contract="ordered-lossless-reset-abort-v1",
                       layout=[dict(field="bits." + field, lsb=lsb, width=width, signed=False,
                                    source=f"~|{module}>{name}.bits.{field}")
                               for field, lsb, width in FIELDS])
        if name == "in":
            channel.update(protocol="two-phase-bundled-v1" if click else "four-phase-bundled-v1",
                           request="in_request", data="in_data", acknowledge="in_acknowledge",
                           phases=["00", "10", "11", "01", "00"], environment=(
                               "binary inputs; coordinated reset to 00; every ack edge delivers; data held while req != ack"
                               if click else "binary inputs; coordinated reset; data held through return to idle"))
        else:
            channel.update(protocol="decoupled-v1", valid="out_valid", data="out_data",
                           ready="out_ready", clock="out_clock", phases=["rising-edge-fire"],
                           environment="transfer only at rising clock with ready and valid; no input irrevocability assumed; coordinated reset")
        expected.append(channel)
    if (type(node.get("capacity")) is not int or node["capacity"] != 1 or
            node.get("channels") != expected or
            any(type(field.get("lsb")) is not int or type(field.get("width")) is not int or
                field.get("signed") is not False
                for channel in node["channels"] for field in channel["layout"])):
        raise ValueError("FRAME_RECEIPT_SCHEMA")
    endpoints = node.get("endpoints", [])
    if (len(endpoints) != len(ENDPOINTS) or
            {e.get("id") for e in endpoints} != set(ENDPOINTS) or
            any(type(e.get("width")) is not int or
                (e["width"], e.get("source")) !=
                (ENDPOINTS[e["id"]][0], f"~|{module}>{ENDPOINTS[e['id']][1]}")
                for e in endpoints) or
            any(node.get(k) != [] for k in ("children", "primitives", "timing"))):
        raise ValueError("FRAME_RECEIPT_INVENTORY")
    return click


def frame_receipt_bindings(node, scopes):
    """Return mapping comparisons against real registers, ports, and bus leaves."""
    click = validate_frame_receipt(node)
    path = node["rtl_path"]
    scope = scopes.get(path, {})
    if (scope.get("registers") != {name: 1 for name in REGISTERS} or
            any(type(width) is not int for width in scope["registers"].values()) or
            scope.get("memories", {})):
        raise ValueError("FRAME_RECEIPT_REGISTER_INVENTORY")
    e = {x["id"]: x["rtl_path"] for x in node["endpoints"]}
    active = f"({e['request_sync']} != {e['acknowledge']})" if click else (
        f"({e['request_sync']} && !{e['acknowledge']})")
    concat = lambda port: "{" + ",".join(path + "." + port + "_bits_" + _leaf(field)
                                         for field, _, _ in reversed(FIELDS)) + "}"
    return [(e["request_meta"], path + ".requestMeta"),
            (e["request_sync"], path + ".requestSync"),
            (e["acknowledge"], path + ".acknowledge"),
            (e["local_reset"], path + ".localReset_release_1"),
            (e["reset"], path + ".reset"), (e["out_clock"], path + ".clock"),
            (e["in_request"], path + ".in_req"), (e["out_ready"], path + ".out_ready"),
            (e["in_acknowledge"], path + ".in_ack"),
            (e["in_acknowledge"], e["acknowledge"]),
            (e["out_valid"], path + ".out_valid"),
            (e["out_valid"], f"({active} && !{e['local_reset']})"),
            (e["in_data"], concat("in")), (e["out_data"], concat("out")),
            (e["out_data"], e["in_data"])]


def _leaf(field):
    return field.replace(".", "_").replace("[", "_").replace("]", "")


def _compact(source):
    # No alias folding, Boolean rewriting, dead-code removal, or numeric coercion.
    return re.sub(r"\s+", "", re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.S))


_HEADER = """
`ifndef RANDOMIZE
  `ifdef RANDOMIZE_REG_INIT
    `define RANDOMIZE
  `endif
`endif
`ifndef SYNTHESIS
  `ifndef ENABLE_INITIAL_REG_
    `define ENABLE_INITIAL_REG_
  `endif
`endif
`ifndef RANDOM
  `define RANDOM $random
`endif
`ifndef INIT_RANDOM
  `define INIT_RANDOM
`endif
`ifndef RANDOMIZE_DELAY
  `define RANDOMIZE_DELAY 0.002
`endif
`ifndef INIT_RANDOM_PROLOG_
  `ifdef RANDOMIZE
    `ifdef VERILATOR
      `define INIT_RANDOM_PROLOG_ `INIT_RANDOM
    `else
      `define INIT_RANDOM_PROLOG_ `INIT_RANDOM #`RANDOMIZE_DELAY begin end
    `endif
  `else
    `define INIT_RANDOM_PROLOG_
  `endif
`endif
"""
_RELEASE = """
always @(posedge clock or posedge reset) begin
  if (reset) begin localReset_release_0 <= 1'h1; localReset_release_1 <= 1'h1; end
  else begin localReset_release_0 <= 1'h0; localReset_release_1 <= localReset_release_0; end
end
"""
_INITIAL = """
`ifdef ENABLE_INITIAL_REG_
  `ifdef FIRRTL_BEFORE_INITIAL
    `FIRRTL_BEFORE_INITIAL
  `endif
  logic [31:0] _RANDOM[0:0];
  initial begin
    `ifdef INIT_RANDOM_PROLOG_
      `INIT_RANDOM_PROLOG_
    `endif
    `ifdef RANDOMIZE_REG_INIT
      _RANDOM[1'b0] = `RANDOM;
      localReset_release_0 = _RANDOM[1'b0][0];
      localReset_release_1 = _RANDOM[1'b0][1];
      requestMeta = _RANDOM[1'b0][2]; requestSync = _RANDOM[1'b0][3];
      acknowledge = _RANDOM[1'b0][4];
    `endif
    if(reset) begin localReset_release_0 = 1'h1; localReset_release_1 = 1'h1; end
    if(localReset) begin requestMeta = 1'h0; requestSync = 1'h0; acknowledge = 1'h0; end
  end
  `ifdef FIRRTL_AFTER_INITIAL
    `FIRRTL_AFTER_INITIAL
  `endif
`endif
"""


def validate_frame_receipt_rtl(node, rtl):
    """Pin all emitted logic, including both full-width packed metadata probes."""
    click = validate_frame_receipt(node)
    module = node["module"]
    source = _compact(rtl)
    # Source port order is declaration order, unlike Vec packing order.
    leaves = [("ingress_frame_length", 6), ("ingress_frame_overflow", 1)] + [
        (f"ingress_frame_bytes_{i}", 8) for i in range(33)] + [
        ("ingress_resetActive", 1), ("ingress_programBusy", 1), ("resetEpoch", 64)]
    port = lambda direction, name, width=1: direction + (
        f"[{width - 1}:0]" if width > 1 else "") + name
    ports = [port("input", name) for name in ("reset", "clock", "in_req")]
    ports += [port("input", "in_bits_" + field, width) for field, width in leaves]
    ports += [port("output", "in_ack"), port("input", "out_ready"), port("output", "out_valid")]
    ports += [port("output", "out_bits_" + field, width) for field, width in leaves]
    prefix = _compact(_HEADER) + "module" + module + "(" + ",".join(ports) + ");"
    if not source.startswith(prefix) or not source.endswith("endmodule"):
        raise ValueError("FRAME_RECEIPT_PORTS_OR_PREAMBLE")
    body = source[len(prefix):-len("endmodule")]
    valid = "requestSync!=acknowledge&~packed_10_probe" if click else (
        "requestSync&~acknowledge&~packed_10_probe")
    packed = "{" + ",".join("in_bits_" + _leaf(field) for field, _, _ in reversed(FIELDS)) + "}"
    declarations = _compact("""
wire packed_9_probe = clock; wire packed_11_probe = reset;
reg localReset_release_0; reg localReset_release_1;
wire localReset = localReset_release_1; wire packed_10_probe = localReset;
reg requestMeta; reg requestSync; reg acknowledge; wire in_ack_0 = acknowledge;
""") + f"wirepacked_6={valid};wire[336:0]packed_4_probe={packed};wire[336:0]packed_7_probe={packed};"
    if not body.startswith(declarations):
        raise ValueError("FRAME_RECEIPT_REGISTERS_OR_PROBES")
    body = body[len(declarations):]
    ack = "if(out_ready&packed_6)acknowledge<=requestSync;" if click else (
        "acknowledge<=out_ready&packed_6|requestSync&acknowledge;")
    receipt = ("always@(posedgeclockorposedgelocalReset)beginif(localReset)begin"
               "requestMeta<=1'h0;requestSync<=1'h0;acknowledge<=1'h0;endelsebegin"
               "requestMeta<=in_req;requestSync<=requestMeta;" + ack + "endend")
    sequential = _compact(_RELEASE) + receipt
    if not body.startswith(sequential):
        raise ValueError("FRAME_RECEIPT_SEQUENTIAL_LOGIC")
    body = body[len(sequential):]
    initializer = _compact(_INITIAL)
    if not body.startswith(initializer):
        raise ValueError("FRAME_RECEIPT_INITIALIZERS")
    body = body[len(initializer):]
    assigns = "assignin_ack=in_ack_0;assignout_valid=packed_6;" + "".join(
        f"assignout_bits_{field}=in_bits_{field};" for field, _ in leaves)
    # Exact remainder closes duplicate writers, extra always/initial/force/task/
    # function/generate/instance constructs and second module definitions too.
    if body != assigns:
        raise ValueError("FRAME_RECEIPT_COMBINATIONAL_LOGIC")
    # Unlike ordinary Verilog spacing, a preprocessor newline is semantic.
    # Do not let whitespace normalization hide a directive swallowed by a macro.
    def directives(text):
        text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
        return [_compact(line) for line in text.splitlines() if line.lstrip().startswith("`")]
    if directives(rtl) != directives(_HEADER + _INITIAL):
        raise ValueError("FRAME_RECEIPT_PREPROCESSOR_LINES")


def validate_frame_receipts(manifest, directory):
    """Validate every receipt and require its presence under every I2cTarget."""
    directory = Path(directory)

    def visit(node):
        module = node.get("module", "")
        if module.startswith(("FourPhaseFrameReceipt", "ClickFrameReceipt")):
            validate_frame_receipt(node)
            validate_frame_receipt_rtl(node, (directory / (module + ".sv")).read_text(encoding="utf-8"))
        if re.fullmatch(r"I2cTarget(?:_[0-9]+)?", module):
            children = node.get("children", [])
            native = [c["contract"] for c in children if c.get("id") == "native"]
            receipts = [c["contract"] for c in children if c.get("id") == "frame_bridge"]
            if (len(native) != 1 or len(receipts) != 1 or not re.fullmatch(
                    r"(?:FourPhase|Click)I2c(?:_[0-9]+)?", native[0].get("module", ""))):
                raise ValueError("FRAME_RECEIPT_TARGET_INVENTORY")
            required = ("Click" if native[0]["module"].startswith("Click") else "FourPhase") + "FrameReceipt"
            if not re.fullmatch(required + r"(?:_[0-9]+)?", receipts[0].get("module", "")):
                raise ValueError("FRAME_RECEIPT_TARGET_OWNER")
        for child in node.get("children", []):
            visit(child["contract"])

    visit(manifest["design"])

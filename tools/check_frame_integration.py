# SPDX-License-Identifier: Apache-2.0
"""Strict frame receipt wiring and original mailbox capture policy.

This audits emitted production wiring and returns the validated inlined data/
load expressions for independent capture monitors. It does not measure timing.
"""
from pathlib import Path
from collections import Counter
from functools import lru_cache
import re

from check_frame_receipt import FIELDS, validate_frame_receipt, frame_receipt_bindings


def require(condition, diagnostic):
    if not condition:
        raise ValueError("FRAME_INTEGRATION_" + diagnostic)


@lru_cache(maxsize=12)
def clean(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


def compact(text):
    return re.sub(r"\s+", "", text)


def leaf(field):
    return field.replace(".", "_").replace("[", "_").replace("]", "")


def child(node, name):
    found = [c["contract"] for c in node.get("children", []) if c.get("id") == name]
    require(len(found) == 1, "CHILD:" + name)
    return found[0]


def pins(rtl, instance, model):
    """Resolve named pins with balanced expressions; reject duplicates/extra syntax."""
    matches = list(re.finditer(r"\b(\w+)\s+" + re.escape(instance) +
                              r"\s*\((.*?)\);", clean(rtl), re.S))
    require(len(matches) == 1 and matches[0][1] == model, "INSTANCE:" + instance)
    fragment = matches[0][2]; result = {}; at = 0
    while fragment[at:].strip():
        match = re.match(r"\s*\.(\w+)\s*\(", fragment[at:])
        require(match is not None and match[1] not in result, "PIN_SYNTAX:" + instance)
        begin = at + match.end(); end = begin; depth = 1
        while end < len(fragment) and depth:
            depth += (fragment[end] == "(") - (fragment[end] == ")"); end += 1
        require(depth == 0, "PIN_END:" + instance)
        result[match[1]] = compact(fragment[begin:end - 1]); at = end
        rest = fragment[at:].lstrip()
        if not rest: break
        require(rest.startswith(","), "PIN_SEPARATOR:" + instance)
        at = len(fragment) - len(rest) + 1
    return result


def driver(rtl, name, expected):
    un = clean(rtl)
    matches = re.findall(r"\b(?:wire\s+(?:\[\d+:0\]\s*)?|assign\s+)" +
                         re.escape(name) + r"\s*=\s*([^;]+);", un)
    require(len(matches) == 1 and compact(matches[0]) == compact(expected), "DRIVER:" + name)
    no_other_writers(un, name, 1)
    return name


def no_other_writers(rtl, name, scalar=0):
    """An alias or child output cannot acquire a second/procedural/partial driver."""
    forbidden, counts, partial = writer_inventory(rtl)
    require(not forbidden, "ALIAS_WRITER_CONSTRUCT")
    require(counts[name] == scalar, "ALIAS_WRITERS:" + name)
    require(name not in partial, "ALIAS_PARTIAL_WRITER:" + name)


@lru_cache(maxsize=12)
def writer_inventory(rtl):
    un = clean(rtl)
    counts = Counter(re.findall(r"\b(\w+)\s*(?:<=|=(?!=))", un))
    partial = set()
    # Scan balanced lvalues backwards from each assignment/update operator.
    # A flat brace regex misses {{q}} and concatenated indexed destinations.
    for match in re.finditer(r"(?<![=!<>])=(?!=)|<=|(?:<<<|>>>|<<|>>|[+\-*/%&|^])=|\+\+|--", un):
        end = match.start(); pos = end - 1
        while pos >= 0 and un[pos].isspace(): pos -= 1
        compound = match[0] not in ("=", "<=")
        if pos >= 0 and un[pos] in "}]":
            close = un[pos]; opening = "{" if close == "}" else "["; depth = 1; pos -= 1
            while pos >= 0 and depth:
                depth += (un[pos] == close) - (un[pos] == opening); pos -= 1
            require(depth == 0, "WRITER_LVALUE_BALANCE")
            if close == "]":
                while pos >= 0 and (un[pos].isalnum() or un[pos] in "_.$[]: '"): pos -= 1
            partial.update(re.findall(r"\b\w+\b", un[pos + 1:end]))
        elif compound:
            while pos >= 0 and (un[pos].isalnum() or un[pos] in "_$"): pos -= 1
            partial.update(re.findall(r"\b\w+\b", un[pos + 1:end]))
        if match[0] in ("++", "--"):
            following = re.match(r"\s*(\w+)", un[match.end():])
            if following: partial.add(following[1])
    return bool(re.search(r"\b(?:force|release|alias|bind)\b", un)), counts, partial


def always_blocks(rtl):
    # The pinned emitter marks the outer end; nested ends cannot be mistaken for it.
    return [clean(block) for block in re.findall(
        r"\balways\s*@\(.*?^\s*end\s*//\s*always[^\n]*", rtl, re.S | re.M)]


def statement_tree(text):
    """Parse the emitted if/begin/assignment subset, preserving every condition."""
    text = clean(text); at = 0

    def ws():
        nonlocal at
        while at < len(text) and text[at].isspace(): at += 1

    def word(value):
        ws()
        return re.match(re.escape(value) + r"\b", text[at:]) is not None

    def statement():
        nonlocal at
        ws()
        if word("begin"):
            at += 5; items = []
            while not word("end"):
                require(at < len(text), "STATEMENT_END")
                items.append(statement())
            at += 3
            return ("sequence", *items)
        if word("if"):
            at += 2; ws(); require(at < len(text) and text[at] == "(", "IF_SYNTAX")
            at += 1; start = at; depth = 1
            while at < len(text) and depth:
                depth += (text[at] == "(") - (text[at] == ")"); at += 1
            require(depth == 0, "IF_END")
            condition = compact(text[start:at - 1]); yes = statement(); no = ("sequence",)
            if word("else"): at += 4; no = statement()
            return ("if", condition, yes, no)
        end = text.find(";", at); require(end >= at, "ASSIGNMENT_END")
        raw = compact(text[at:end]); at = end + 1
        assignment = re.fullmatch(r"(\w+)<=([^;]+)", raw)
        require(assignment is not None, "STATEMENT_SYNTAX:" + raw[:80])
        return ("assign", assignment[1], assignment[2])

    tree = statement(); ws(); require(at == len(text), "STATEMENT_TRAILING")
    return tree


def projected_tree(tree, names):
    if tree[0] == "assign": return tree if tree[1] in names else None
    if tree[0] == "sequence":
        kept = [value for item in tree[1:] if (value := projected_tree(item, names)) is not None]
        if not kept: return None
        return kept[0] if len(kept) == 1 else ("sequence", *kept)
    yes, no = projected_tree(tree[2], names), projected_tree(tree[3], names)
    return None if yes is None and no is None else ("if", tree[1], yes, no)


def initial_policy(rtl, values, reset):
    """Close initializer guards, not just the number of scalar assignments."""
    un = clean(rtl)
    require(len(re.findall(r"\binitial\b", un)) == 1, "INITIAL_BLOCK_COUNT")
    blocks = re.findall(r"\binitial\s+(begin\b.*?^\s*end)\s*//\s*initial", rtl, re.S | re.M)
    require(len(blocks) == 1, "INITIAL_BLOCK_SHAPE")
    body = clean(blocks[0])
    directives = re.findall(r"^\s*(`[^\n]*)", body, re.M)
    require([compact(x) for x in directives] == ["`ifdefINIT_RANDOM_PROLOG_", "`INIT_RANDOM_PROLOG_",
            "`endif", "`ifdefRANDOMIZE_REG_INIT", "`endif"], "INITIAL_DIRECTIVES")
    body = re.sub(r"^\s*`[^\n]*", "", body, flags=re.M)
    body, loops = re.subn(r"for\s*\(logic\s*\[\d+:0\]\s+i\s*=\s*\d+'h0;\s*i\s*<\s*\d+'h[0-9A-Fa-f]+;\s*i\s*\+=\s*\d+'h1\)\s*begin\s*_RANDOM\[i\]\s*=\s*`RANDOM;\s*end", "", body)
    require(loops == 1, "INITIAL_RANDOM_LOOP")
    body = re.sub(r"\b(\w+)\s*=(?!=)", r"\1 <=", body)
    tree = statement_tree(body); assignments = {name: [] for name in values}

    def visit(tree, guards=()):
        if tree[0] == "assign":
            if tree[1] in assignments: assignments[tree[1]].append((guards, tree[2]))
        elif tree[0] == "sequence":
            for sub in tree[1:]: visit(sub, guards)
        else:
            visit(tree[2], guards + ((tree[1], True),))
            visit(tree[3], guards + ((tree[1], False),))

    visit(tree)
    atom = r"_RANDOM\[\d+'h[0-9a-fA-F]+\](?:\[\d+(?::\d+)?\])?"
    for name, value in values.items():
        got = assignments[name]
        require(len(got) == 2 and got[0][0] == () and
                re.fullmatch(atom + r"|\{" + atom + r"(?:," + atom + r")+\}", got[0][1]) is not None and
                got[1] == (((reset, True),), value), "INITIAL_GUARDS:" + name)


def state_policy(rtl, values, sensitivity, expected, reset="reset"):
    names = set(values)
    blocks = [b for b in always_blocks(rtl) if any(re.search(r"\b" + re.escape(n) + r"\s*<=", b) for n in names)]
    require(len(blocks) == 1, "STATE_CLOCK_OWNERS:" + sorted(names)[0])
    head = re.match(r"always\s*@\((.*?)\)\s*(.*)", blocks[0], re.S)
    require(head and compact(head[1]) == compact(sensitivity), "STATE_CLOCK_RESET:" + sorted(names)[0])
    require(projected_tree(statement_tree(head[2]), names) == projected_tree(statement_tree(expected), names),
            "STATE_TRANSITIONS:" + sorted(names)[0])
    un = clean(rtl)
    require(not re.search(r"\b(?:force|release|final|task|function|alias|bind)\b", un), "UNEXPECTED_WRITER_CONSTRUCT")
    for name in names:
        width = int(values[name].split("'")[0])
        declaration = r"\breg\s+" + (r"\[" + str(width - 1) + r":0\]\s*" if width > 1 else "") + name + r"\s*;"
        require(len(re.findall(declaration, un)) == 1, "STATE_REGISTER:" + name)
        require(len(re.findall(r"\b" + name + r"\s*<=", un)) == len(re.findall(r"\b" + name + r"\s*<=", expected)),
                "STATE_WRITERS:" + name)
        require(len(re.findall(r"\b" + name + r"\s*=(?!=)", un)) == 2, "STATE_INITIAL_WRITERS:" + name)
    require(not (names & writer_inventory(rtl)[2]), "STATE_PARTIAL_WRITER")
    initial_policy(rtl, values, reset)


def epoch_assertion_policy(directory, model, rising, ready_reset):
    path = Path(directory) / "verification" / "assert" / (model + "_Verification_Assert.sv")
    require(path.is_file(), "EPOCH_ASSERTION_FILE")
    raw = path.read_text(encoding="utf-8"); un = clean(raw); prefix = model + "."
    blocks = re.findall(r"`ifndef\s+SYNTHESIS[^\n]*\n\s*(always\s*@\(.*?^\s*end)\s*//\s*always[^\n]*\n\s*`endif", raw, re.M | re.S)
    require(len(blocks) == 1, "EPOCH_ASSERTION_GUARD")
    expected = ("always @(posedge " + prefix + "clock) begin if(" + prefix + rising + "&~" + prefix + ready_reset +
                "&(&" + prefix + "resetEpoch_epoch))begin if(`ASSERT_VERBOSE_COND_)$error(\"Assertion failed: I2C_RESET_EPOCH_WRAP\\n\");if(`STOP_COND_)$fatal;end ")
    # Pin the complete block so an extra ancestor condition or disabled assertion
    # cannot coexist with an apparently intact substring.
    expected += ("if(" + prefix + "event_layerCapture&~" + prefix + ready_reset + "&" + prefix +
                 "tailGray==(headGray^4'hC))begin if(`ASSERT_VERBOSE_COND_)$error(\"Assertion failed: I2C_EDGE_RING_OVERFLOW\\n\");if(`STOP_COND_)$fatal;end end")
    require(compact(clean(blocks[0])) == compact(expected), "EPOCH_ASSERTION_LOGIC")
    binding = Path(directory) / "verification" / "assert" / ("layers-" + model + "-Verification-Assert.sv")
    require(binding.is_file(), "EPOCH_ASSERTION_BIND_FILE")
    bind_text = compact(clean(binding.read_text(encoding="utf-8")))
    guard = "layers_" + model + "_Verification_Assert"
    expected_bind = f'`ifndef {guard}\n`define {guard}\n`include "layers-{model}-Verification.sv"\nbind {model} {model}_Verification_Assert verification_assert ();\n`endif'
    require(un.count("I2C_RESET_EPOCH_WRAP") == 1 and bind_text == compact(expected_bind), "EPOCH_ASSERTION_BIND")
    for macro in ("STOP_COND", "ASSERT_VERBOSE_COND"):
        expected_macro = f"`ifndef {macro}_\n`ifdef {macro}\n`define {macro}_ (`{macro})\n`else\n`define {macro}_ 1\n`endif\n`endif"
        require(compact(expected_macro) in compact(un) and len(re.findall(r"`define\s+" + macro + r"_\b", un)) == 2,
                "EPOCH_ASSERTION_MACRO")


def _mailbox_policy(rtl, clock, source):
    """Close every original slot/count transition including its ancestor guards."""
    fields = [("frame_length", 6), ("frame_overflow", 1)] + [
        (f"frame_bytes_{i}", 8) for i in range(33)] + [("resetActive", 1), ("programBusy", 1)]
    names = {f"fabric_hostFrames_{slot}_{name}" for slot in ("first", "second") for name, _ in fields}
    names.add("fabric_hostFrames_count")
    reset = "".join(f"fabric_hostFrames_{slot}_{name}<={width}'h0;"
                    for slot in ("first", "second") for name, width in fields) + "fabric_hostFrames_count<=2'h0;"
    incoming = lambda slot: "".join(f"fabric_hostFrames_{slot}_{name}<={source[name]};" for name, _ in fields)
    shift = "".join(f"fabric_hostFrames_first_{name}<=fabric_hostFrames_second_{name};" for name, _ in fields)
    branch = ("if(fabric_hostFrames__1)begin " + incoming("first") + "end "
              "else if(fabric_hostFrames_)begin if(fabric_hostFrames__2)begin " + incoming("first") +
              "end fabric_hostFrames_count<=fabric_hostFrames_count+2'h1;end "
              "else if(fabric_hostFrames__0)begin " + shift + "fabric_hostFrames_count<=fabric_hostFrames_count-2'h1;end "
              "if(fabric_hostFrames__1|~fabric_hostFrames_|fabric_hostFrames__2)begin end else begin " + incoming("second") + "end ")
    expected = projected_tree(statement_tree("begin if(reset)begin " + reset + "end else begin " + branch + "end end"), names)
    blocks = [block for block in always_blocks(rtl) if any(
        re.search(r"\b" + re.escape(name) + r"\s*<=", block) for name in names)]
    require(len(blocks) == 1, "MAILBOX_CLOCK_OWNERS")
    head = re.match(r"always\s*@\((.*?)\)\s*(.*)", blocks[0], re.S)
    require(head is not None and compact(head[1]) == "posedge" + clock + "orposedgereset", "MAILBOX_CLOCK_RESET")
    actual = projected_tree(statement_tree(head[2]), names)
    require(actual == expected, "MAILBOX_TRANSITIONS")
    un = clean(rtl)
    require(not re.search(r"\b(?:force|release|final|task|function|alias|bind)\b", un), "UNEXPECTED_WRITER_CONSTRUCT")
    # Indexed/concatenated lvalues are not legal substitutes for the pinned scalar writers.
    require(not (names & writer_inventory(rtl)[2]), "MAILBOX_PARTIAL_WRITER")
    for name in names:
        width = 2 if name == "fabric_hostFrames_count" else next(w for f, w in fields if name.endswith("_" + f))
        declaration = r"\breg\s+" + (r"\[" + str(width - 1) + r":0\]\s*" if width > 1 else "") + re.escape(name) + r"\s*;"
        require(len(re.findall(declaration, un)) == 1, "MAILBOX_REGISTER:" + name)
        expected_writers = 3 if name == "fabric_hostFrames_count" else 4 if "_first_" in name else 2
        require(len(re.findall(r"\b" + re.escape(name) + r"\s*<=", un)) == expected_writers, "MAILBOX_WRITERS:" + name)
        initial = re.findall(r"\b" + re.escape(name) + r"\s*=(?!=)\s*([^;]+);", un)
        require(len(initial) == 2 and compact(initial[-1]) == f"{width}'h0" and
                re.fullmatch(r"(?:_RANDOM\[\d+'h[0-9a-fA-F]+\](?:\[\d+(?::\d+)?\])?|\{_RANDOM\[\d+'h[0-9a-fA-F]+\](?:\[\d+(?::\d+)?\])?(?:,_RANDOM\[\d+'h[0-9a-fA-F]+\](?:\[\d+(?::\d+)?\])?)+\})", compact(initial[0])) is not None,
                "MAILBOX_INITIALIZERS:" + name)
    initial_policy(rtl, {name: ("2'h0" if name.endswith("_count") else
                   str(next(w for f, w in fields if name.endswith("_" + f))) + "'h0") for name in names}, "reset")
    return fields


def validate_frame_integration(manifest, scopes, directory):
    """Return validated production source/capture paths, or None without I2cTarget."""
    directory = Path(directory); root = manifest["design"]; top = manifest["top"]
    targets = [c["contract"] for c in root.get("children", []) if c.get("id") == "i2c"]
    if not targets:
        require(top not in ("FourPhaseSoc", "ClickSoc"), "MISSING_I2C")
        return None
    require(len(targets) == 1, "TARGET_COUNT"); target = targets[0]
    require(re.fullmatch(r"I2cTarget(?:_[0-9]+)?", target["module"]), "TARGET_MODEL")
    native = child(target, "native"); receipt = child(target, "frame_bridge")
    publication = child(native, "publication"); snapshot = child(target, "snapshot_bridge")
    click = validate_frame_receipt(receipt); prefix = "Click" if click else "FourPhase"
    require(re.fullmatch(prefix + r"I2c(?:_[0-9]+)?", native["module"]) and
            re.fullmatch(r"I2cPublication(?:_[0-9]+)?", publication["module"]), "NATIVE_OWNERS")
    require(re.fullmatch(prefix + r"ToDecoupled(?:_[0-9]+)?", snapshot["module"]), "SNAPSHOT_OWNER")
    for node in (target, native, receipt, publication, snapshot): require(node["reset_domain"] == "root", "POR_OWNER")
    te = {e["id"]: e for e in target["endpoints"]}
    require(len(te) == len(target["endpoints"]) and type(te.get("frame_accept_enable", {}).get("width")) is int and
            te["frame_accept_enable"]["width"] == 1 and
            te["frame_accept_enable"].get("source") == f"~|{target['module']}>frameAcceptEnable", "ENABLE_ENDPOINT")
    tr = (directory / (target["module"] + ".sv")).read_text(encoding="utf-8")
    nr = (directory / (native["module"] + ".sv")).read_text(encoding="utf-8")
    sr = (directory / (root["module"] + ".sv")).read_text(encoding="utf-8")
    rp = pins(tr, receipt["rtl_path"].rsplit(".", 1)[1], receipt["module"])
    np = pins(tr, native["rtl_path"].rsplit(".", 1)[1], native["module"])
    pp = pins(nr, publication["rtl_path"].rsplit(".", 1)[1], publication["module"])
    tp = pins(sr, target["rtl_path"].rsplit(".", 1)[1], target["module"])
    pairs = []; r = receipt["rtl_path"]; t = target["rtl_path"]; n = native["rtl_path"]; p = publication["rtl_path"]
    for node in (native, receipt, publication): pairs.append((node["rtl_path"] + ".reset", top + ".reset"))
    require(rp.get("clock") == "clock" and rp.get("reset") == "reset" and np.get("reset") == "reset" and
            pp.get("reset") == "reset" and tp.get("reset") == "reset" and tp.get("clock") == "serviceClock", "CLOCK_RESET_PINS")
    for suffix in ("req", "ack") + tuple("bits_" + leaf(f) for f, _, _ in FIELDS):
        require(rp.get("in_" + suffix) == np.get("frame_" + suffix) and
                re.fullmatch(r"\w+", rp.get("in_" + suffix, "")) is not None, "NATIVE_RECEIPT_PIN:" + suffix)
        no_other_writers(tr, rp["in_" + suffix])
        alias = "packed_0" if suffix == "req" else "frame_ack" if suffix == "ack" else "_ca_child_publication_frame_" + suffix
        require(pp.get("frame_" + suffix) == alias, "PUBLICATION_PIN:" + suffix)
        no_other_writers(nr, alias)
        if suffix != "ack": driver(nr, "frame_" + suffix, alias)
        pairs += [(r + ".in_" + suffix, n + ".frame_" + suffix),
                  (n + ".frame_" + suffix, p + ".frame_" + suffix)]
    for field, _, _ in FIELDS:
        f = leaf(field)
        output = "_ca_child_frame_bridge_out_bits_" + f if field in ("resetEpoch", "ingress.resetActive") else (
            "host_frame_bits_" + f.removeprefix("ingress_"))
        require(rp.get("out_bits_" + f) == output, "FRAME_OUTPUT_PIN:" + f)
        no_other_writers(tr, output)
    require(rp.get("out_ready") == "ca_child_frame_bridge_out_ready" and
            rp.get("out_valid") == "_ca_child_frame_bridge_out_valid", "RECEIPT_CONTROL_PINS")
    observed = "localReset_layerCapture" in clean(tr)
    local_reset = "localReset_layerCapture" if observed else "localReset_release_1"
    ready_reset = "_resetEpoch_T_2_layerCapture" if observed else local_reset
    rising = "resetEpoch_rising_layerCapture" if observed else "resetEpoch_rising"
    if observed:
        driver(tr, local_reset, "localReset_release_1")
        driver(tr, ready_reset, local_reset)
    for name, value in dict(ca_child_frame_bridge_out_ready="~" + ready_reset + "&frameAcceptEnable",
                           **{rising: "host_resetActive&~resetEpoch_previous"},
                           resetEpoch=rising + "?resetEpoch_epoch+64'h1:resetEpoch_epoch",
                           host_frame_valid="ca_child_frame_bridge_out_ready&_ca_child_frame_bridge_out_valid",
                           host_frame_bits_resetActive="_ca_child_frame_bridge_out_bits_ingress_resetActive|host_resetActive|_ca_child_frame_bridge_out_bits_resetEpoch!=resetEpoch",
                           host_busy="active_stages_1|start|stop|effects_stages_1|_ca_child_frame_bridge_out_valid|_ca_child_snapshot_bridge_out_valid").items(): driver(tr, name, value)
    state_policy(tr, {"localReset_release_0": "1'h1", "localReset_release_1": "1'h1"},
                 "posedge clock or posedge reset", "begin if(reset)begin localReset_release_0<=1'h1;localReset_release_1<=1'h1;end else begin localReset_release_0<=1'h0;localReset_release_1<=localReset_release_0;end end")
    state_policy(tr, {"resetEpoch_epoch": "64'h0", "resetEpoch_previous": "1'h0"},
                 "posedge clock or posedge " + local_reset,
                 "begin if(" + local_reset + ")begin resetEpoch_epoch<=64'h0;resetEpoch_previous<=1'h0;end else begin if(" + rising + ")resetEpoch_epoch<=resetEpoch_epoch+64'h1;resetEpoch_previous<=host_resetActive;end end", local_reset)
    epoch_assertion_policy(directory, target["module"], rising, ready_reset)
    pairs += [(r + ".clock", top + ".serviceClock"),
              (r + ".out_ready", f"(!{t}.localReset_release_1 && {t}.frameAcceptEnable)"),
              (t + ".host_frame_valid", f"({r}.out_valid && {r}.out_ready)"),
              (t + ".host_frame_bits_resetActive", f"({r}.out_bits_ingress_resetActive | {t}.host_resetActive | ({r}.out_bits_resetEpoch != {t}.resetEpoch))"),
              (te["frame_accept_enable"]["rtl_path"], t + ".frameAcceptEnable")]
    gate = tp.get("frameAcceptEnable"); require(gate in ("gate_enabled", "1'h1"), "WORK_ENABLE_BINDING")
    if gate == "gate_enabled":
        driver(sr, "gate__enabled_T_3", "~serviceClock")
        expected = "always@(posedgegate__enabled_T_3orposedgereset)beginif(reset)gate_enabled<=1'h1;elsegate_enabled<=(|{gate_needClock,gate_grace})|reset;end"
        blocks = [compact(b) for b in always_blocks(sr) if re.search(r"\bgate_enabled\s*<=", b)]
        require(blocks == [expected], "WORK_GATE_STATE")
        demand = "cpuResetActive|~(fabric_parkedForSleep&~fabric_io_programSource_draining&~fabric_io_ramSource_draining&~fabric_scalingBusy&~fabric_tick&~fabric_telemetryWork&~fabric_boardWork)|(|{fabric_io_programSource_draining|fabric_io_ramSource_draining|fabric_scalingBusy|_ca_child_i2c_host_busy,fabric__gpioActivity_T})|fabric_memoryBusy|fabric_controlBusy|fabric_telemetryWork|fabric_boardWork|gate_second!=gate_io_consumedGray"
        drain = "cpuResetActive|(|{~fabric_parkedForSleep|_ca_child_i2c_host_busy,fabric__gpioActivity_T})"
        gate_values = {n: "1'h1" for n in ("gate_demandFirst", "gate_needClock", "gate_drainFirst", "gate_drain")}
        gate_values["gate_grace"] = "3'h7"
        state_policy(sr, gate_values, "posedge serviceClock or posedge reset",
                     "begin if(reset)begin " + "".join(n + "<=" + v + ";" for n, v in gate_values.items()) +
                     "end else begin gate_demandFirst<=" + demand + ";gate_needClock<=gate_demandFirst;gate_drainFirst<=" + drain +
                     ";gate_drain<=gate_drainFirst;if(gate_drain)gate_grace<=3'h7;else if(|gate_grace)gate_grace<=gate_grace-3'h1;end end")
        state_policy(sr, {"gate_enabled": "1'h1"}, "posedge gate__enabled_T_3 or posedge reset",
                     "begin if(reset)gate_enabled<=1'h1;else gate_enabled<=(|{gate_needClock,gate_grace})|reset;end")
        driver(sr, "fabric_clock", "serviceClock&gate_enabled")
        gate_path = top + ".gate_enabled"
    else:
        driver(sr, "fabric_clock", "serviceClock")
        gate_path = "1'b1"
    pairs += [(t + ".frameAcceptEnable", gate_path), (top + ".fabric_clock", f"({top}.serviceClock & {gate_path})")]
    # Explicitly pin the old pre-edge admission context. Alias names are compiler
    # spelling, not substitute observations or new producer inputs.
    expected_top = dict(
        fabric_loaderPending="fabric_controlState_loaderPending",
        fabric__5="fabric_io_controlReply_ready&_ca_child_control_reply_bridge_out_valid",
        fabric__6="_ca_child_control_command_bridge_in_ready&fabric_io_controlCommand_valid",
        fabric__loaderControlPending_T="fabric_io_controlCommand_bits_kind==3'h0",
        fabric__loaderControlPending_T_1="|fabric_io_controlCommand_bits_frame_bytes_0",
        fabric__loaderControlPending_T_3="fabric_io_controlCommand_bits_frame_bytes_0<8'h7",
        fabric_hostFrames_io_enq_bits_resetActive="cpuResetActive|_ca_child_i2c_host_frame_bits_resetActive",
        fabric_hostFrames_io_enq_bits_programBusy="_ca_child_i2c_host_frame_bits_programBusy|_ca_child_program_access_io_busy|fabric_loaderPending|fabric_loaderControlPending|fabric__6&fabric__loaderControlPending_T&fabric__loaderControlPending_T_1&fabric__loaderControlPending_T_3",
        fabric_hostFrames_io_enq_ready="fabric_hostFrames_count!=2'h2",
        fabric_hostFrames_io_deq_valid="|fabric_hostFrames_count",
        fabric_hostFrames_io_deq_ready="fabric__6&fabric__loaderControlPending_T",
        fabric_hostFrames_="fabric_hostFrames_io_enq_ready&fabric_io_i2c_frame_valid",
        fabric_hostFrames__0="fabric_hostFrames_io_deq_ready&fabric_hostFrames_io_deq_valid",
        fabric_hostFrames__1="fabric_hostFrames_&fabric_hostFrames__0",
        fabric_hostFrames__2="fabric_hostFrames_count==2'h0")
    for name, value in expected_top.items(): driver(sr, name, value)
    qualify = lambda expression: re.sub(r"(?<![\w'])\b[A-Za-z_]\w*\b", lambda match: top + "." + match[0], expression)
    pairs += [(top + "." + name, "(" + qualify(value) + ")") for name, value in expected_top.items()]
    host_busy = "_ca_child_program_access_io_busy|fabric_loaderPending|fabric_loaderControlPending|fabric__6&fabric__loaderControlPending_T&fabric__loaderControlPending_T_1&fabric__loaderControlPending_T_3"
    require(tp.get("host_frame_valid") == "fabric_io_i2c_frame_valid" and tp.get("host_resetActive") == "cpuResetActive" and
            tp.get("host_programBusy") == host_busy and tp.get("host_busy") == "_ca_child_i2c_host_busy", "TOP_ADMISSION_PINS")
    state_policy(sr, {"fabric_loaderControlPending": "1'h0"}, "posedge fabric_clock or posedge reset",
                 "begin if(reset)fabric_loaderControlPending<=1'h0;else fabric_loaderControlPending<=~fabric__5&(fabric__6?fabric__loaderControlPending_T&fabric__loaderControlPending_T_1&fabric__loaderControlPending_T_3:fabric_loaderControlPending);end")
    source = {}
    for field, _, _ in FIELDS:
        if not field.startswith("ingress."): continue
        f = leaf(field.removeprefix("ingress."))
        net = "_ca_child_i2c_host_frame_bits_" + f
        require(tp.get("host_frame_bits_" + f) == net, "TOP_FRAME_PIN:" + f)
        no_other_writers(sr, net)
        source[f] = "fabric_hostFrames_io_enq_bits_" + f if f in ("resetActive", "programBusy") else net
        pairs.append((top + "." + net, t + ".host_frame_bits_" + f))
    fields = _mailbox_policy(sr, "fabric_clock", source)
    cells = [cell for cell in publication["primitives"] if cell["id"] == "frame_payload"]
    require(len(cells) == 1 and cells[0]["model"] == "ChiselAsyncEventRegister_v1" and
            cells[0]["parameters"].get("WIDTH") == "337", "PUBLISHER_PAYLOAD")
    q = cells[0]["rtl_path"] + ".q"
    pairs.append((q, "{" + ",".join(r + ".in_bits_" + leaf(f) for f, _, _ in reversed(FIELDS)) + "}"))
    enq = top + ".fabric_hostFrames_"; deq = top + ".fabric_hostFrames__0"; empty = top + ".fabric_hostFrames__2"
    slots = {}
    for slot in ("first", "second"):
        load = f"(({enq} && ({deq} || {empty})) || (!{enq} && {deq}))" if slot == "first" else f"({enq} && !{deq} && !{empty})"
        slots[slot] = [dict(field=f, width=w, q=f"{top}.fabric_hostFrames_{slot}_{f}",
                            incoming=top + "." + source[f], load=load,
                            d=f"({enq} ? {top}.{source[f]} : {top}.fabric_hostFrames_second_{f})" if slot == "first" else top + "." + source[f])
                       for f, w in fields]
    return dict(top=top, target=t, receipt=r, publication=p, frame_payload=q, source_epoch=r + ".in_bits_resetEpoch",
                current_epoch=t + ".resetEpoch", clock=top + ".fabric_clock", reset=top + ".reset", gate=gate_path,
                enq=enq, deq=deq, count=top + ".fabric_hostFrames_count", slots=slots, pairs=pairs,
                reset_context=top + ".fabric_hostFrames_io_enq_bits_resetActive",
                busy_context=top + ".fabric_hostFrames_io_enq_bits_programBusy",
                literal_enable_endpoint=te["frame_accept_enable"]["rtl_path"] if gate == "1'h1" else None)


def frame_receipt_probe(source, manifest, scopes, directory):
    pairs = []

    def visit(node):
        if re.fullmatch(r"(?:FourPhase|Click)FrameReceipt(?:_[0-9]+)?", node["module"]):
            pairs.extend(frame_receipt_bindings(node, scopes))
        for item in node.get("children", []): visit(item["contract"])

    visit(manifest["design"])
    record = validate_frame_integration(manifest, scopes, directory)
    if record:
        pairs.extend(record["pairs"])
        endpoint = record["literal_enable_endpoint"]
        if endpoint:
            pattern = r'^if \(ones_(\d+) !== 1\'h1 \|\| zeros_\1 !== 1\'h1\) \$fatal\(1, "INACTIVE_ENDPOINT:' + re.escape(endpoint) + r'"\);$'
            matches = list(re.finditer(pattern, source, re.M)); require(len(matches) == 1, "ENABLE_LITERAL_COVERAGE")
            match = matches[0]
            source = source[:match.start()] + match[0].replace("zeros_" + match[1] + " !== 1'h1", "zeros_" + match[1] + " !== 1'h0") + source[match.end():]
            pairs += [(endpoint, "1'b1"), (record["target"] + ".frameAcceptEnable", "1'b1")]
    if not pairs: return source
    anchor = "task check; begin"; require(source.count(anchor) == 1, "PROBE_SHAPE")
    comparisons = [f'if ({a} !== {b}) $fatal(1,"FRAME_RECEIPT_BINDING:{a}");' for a, b in pairs]
    return source.replace(anchor, anchor + "\n" + "\n".join(comparisons))

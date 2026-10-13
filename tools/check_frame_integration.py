# SPDX-License-Identifier: Apache-2.0
"""Strict native frame storage, receipt wiring and descriptor capture policy.

This audits emitted production wiring and returns the validated inlined data/
load expressions for independent capture monitors. It does not measure timing.
"""
from pathlib import Path
from collections import Counter
from functools import lru_cache
import re

from check_frame_receipt import FIELDS, validate_frame_receipt, frame_receipt_bindings, actual_receipt_rtl, _HEADER


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
    matches = re.findall(r"\b(?:wire\s+(?:\[\d+:0\]\s*)*|assign\s+)" +
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


@lru_cache(maxsize=12)
def always_blocks(rtl):
    # The pinned emitter marks the outer end; nested ends cannot be mistaken for it.
    return [clean(block) for block in re.findall(
        r"\balways\s*@\(.*?^\s*end\s*//\s*always[^\n]*", rtl, re.S | re.M)]


@lru_cache(maxsize=12)
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
    return _state_policy(rtl, tuple(values.items()), sensitivity, expected, reset)


@lru_cache(maxsize=24)
def _state_policy(rtl, value_pairs, sensitivity, expected, reset):
    values = dict(value_pairs)
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


def assertion_wrapper_policy(directory, model, raw, label, diagnostic):
    """Close preprocessing and binding around the actual executable assertion."""
    un = clean(raw)
    module = re.search(r"\bmodule\s+" + re.escape(model) + r"_Verification_Assert\s*\(\s*\)\s*;", un)
    require(module is not None, diagnostic + "_MODULE")
    header = "".join(f"`ifndef {m}_\n`ifdef {m}\n`define {m}_ (`{m})\n`else\n`define {m}_ 1\n`endif\n`endif\n"
                     for m in ("STOP_COND", "ASSERT_VERBOSE_COND")) + _HEADER
    prefix = un[:module.start()]
    directives = lambda value: [compact(line) for line in value.splitlines() if line.strip().startswith("`")]
    require(compact(prefix) == compact(header) and directives(prefix) == directives(header), diagnostic + "_HEADER")
    body = un[module.end():]
    position = body.find(label)
    require(position >= 0, diagnostic + "_COUNT")
    # The assertion must execute under the sole non-synthesis guard. Any extra
    # wrapper, redefinition, or early closing directive changes its meaning.
    tokens = list(re.finditer(r"`(?:ifndef|ifdef|elsif|else|endif|define|undef|include)\b[^\n]*", body))
    before = [m for m in tokens if m.start() < position]
    after = [m for m in tokens if m.start() > position]
    require(len(before) == 1 and compact(before[0][0]) == "`ifndefSYNTHESIS" and
            after and compact(after[0][0]) == "`endif", diagnostic + "_WRAPPER")
    assertion_execution_policy(raw, body, before[0].start(), before[0].end(), after[0].start(),
                               3 if model in ("FourPhaseSoc", "ClickSoc") else 1, diagnostic)
    binding = Path(directory) / "verification" / "assert" / ("layers-" + model + "-Verification-Assert.sv")
    require(binding.is_file(), diagnostic + "_BIND_FILE")
    raw_bind = clean(binding.read_text(encoding="utf-8"))
    guard = "layers_" + model + "_Verification_Assert"
    child_include = '`include "layers-I2cTarget-Verification-Assert.sv"\n' if model in ("FourPhaseSoc", "ClickSoc") else ""
    expected = f'`ifndef {guard}\n`define {guard}\n`include "layers-{model}-Verification.sv"\n' + child_include + f'bind {model} {model}_Verification_Assert verification_assert ();\n`endif'
    require(compact(raw_bind) == compact(expected) and directives(raw_bind) == directives(expected), diagnostic + "_BIND")


def assertion_execution_policy(raw, body, guard_start, block_start, block_end, count, diagnostic):
    """Close lexical execution ownership, including implicit generate scopes."""
    un = clean(raw)
    require(len(re.findall(r"\bmodule\b", un)) == 1 and len(re.findall(r"\bendmodule\b", un)) == 1 and
            not re.search(r"\b(?:generate|endgenerate|function|endfunction|task|endtask|class|package|program|interface)\b", body) and
            not re.search(r"\b(?:always|always_comb|always_ff|always_latch|initial|begin|end)\b", body[:guard_start]),
            diagnostic + "_OWNERSHIP")
    fragment = body[block_start:block_end]
    blocks = [block for block in always_blocks(raw) if block in fragment]
    require(len(blocks) == count, diagnostic + "_OWNERSHIP")
    for block in blocks:
        require(fragment.count(block) == 1, diagnostic + "_OWNERSHIP")
        fragment = fragment.replace(block, "", 1)
        head = re.match(r"always\s*@\((.*?)\)\s*(.*)", block, re.S)
        parsed = re.sub(r'\$error\("[^"\n]*"\);|\$fatal;', "assertion_action<=1;", head[2])
        try:
            statement_tree(parsed)
        except ValueError as error:
            raise ValueError("FRAME_INTEGRATION_" + diagnostic + "_OWNERSHIP") from error
    require(re.fullmatch(r"\s*(?:wire\s+(?:\[\d+:0\]\s*)*\w+\s*=\s*[^;]+;\s*)*", fragment) is not None,
            diagnostic + "_OWNERSHIP")


def inline_assertion_wrapper_policy(model, raw, label, diagnostic):
    """Accept only the pinned executable inline form, with its full macro shell.

    This does not manufacture an extracted verification module or remove any
    source. The original module, clock, condition AST and both failure actions
    are checked separately against the same assertion contract.
    """
    un = clean(raw)
    module = re.search(r"\bmodule\s+" + re.escape(model) + r"\s*\(", un)
    require(module is not None, diagnostic + "_MODULE")
    header = "".join(f"`ifndef {m}_\n`ifdef {m}\n`define {m}_ (`{m})\n`else\n`define {m}_ 1\n`endif\n`endif\n"
                     for m in ("STOP_COND", "ASSERT_VERBOSE_COND")) + _HEADER
    directives = lambda value: [compact(line) for line in value.splitlines() if line.strip().startswith("`")]
    require(compact(un[:module.start()]) == compact(header) and
            directives(un[:module.start()]) == directives(header), diagnostic + "_HEADER")
    body = un[module.end():]
    require(body.count(label) == 1, diagnostic + "_COUNT")
    expected = ["`ifndefSYNTHESIS", "`endif", "`ifdefENABLE_INITIAL_REG_",
                "`ifdefFIRRTL_BEFORE_INITIAL", "`FIRRTL_BEFORE_INITIAL", "`endif",
                "`ifdefINIT_RANDOM_PROLOG_", "`INIT_RANDOM_PROLOG_", "`endif",
                "`ifdefRANDOMIZE_REG_INIT", "`endif", "`ifdefFIRRTL_AFTER_INITIAL",
                "`FIRRTL_AFTER_INITIAL", "`endif", "`endif"]
    require(directives(body) == expected, diagnostic + "_WRAPPER")
    # Directives cannot be hidden after ordinary source on the same line.
    for directive in re.finditer(r"`(?:ifndef|ifdef|elsif|else|endif|define|undef|include)\b", body):
        require(not body[body.rfind("\n", 0, directive.start()) + 1:directive.start()].strip(),
                diagnostic + "_WRAPPER")
    blocks = list(re.finditer(r"`ifndef\s+SYNTHESIS\s*\n(.*?)`endif", body, re.S))
    require(len(blocks) == 1 and label in blocks[0][1], diagnostic + "_WRAPPER")
    assertion_execution_policy(raw, body, blocks[0].start(), blocks[0].start(1), blocks[0].end(1), 1, diagnostic)


def assertion_source(directory, model, inline, diagnostic):
    extracted = Path(directory) / "verification" / "assert" / (model + "_Verification_Assert.sv")
    if inline:
        require(not extracted.exists(), diagnostic + "_MIXED_FORM")
        path = Path(directory) / (model + ".sv")
    else:
        path = extracted
    require(path.is_file(), diagnostic + "_FILE")
    return path.read_text(encoding="utf-8")


def top_spelling(inline):
    """Translate expected identifiers only; never rewrite the observed RTL.

    These five compiler spellings change when verification layers are inlined.
    Every translated driver, use and procedural writer still goes through the
    existing exact source policies. No expression is inferred from a name.
    """
    names = dict(fabric_clock="gate_io_clockOut", fabric_io_i2c_frame_valid="_ca_child_i2c_host_frame_valid",
                 fabric__5="fabric__7", fabric__6="fabric__10", fabric__27="fabric__33") if inline else {}
    return lambda text: re.sub(r"\b[A-Za-z_]\w*\b", lambda m: names.get(m[0], m[0]), text)


def validated_service_clock(root, directory):
    """Resolve the work clock independently of an access endpoint's own pin.

    Both compiler forms must retain their exact gate equation and I2C work-edge
    qualification. An ambiguous alias or an added writer fails closed.
    """
    target = child(root, "i2c")
    directory = Path(directory)
    rtl = (directory / (root["module"] + ".sv")).read_text(encoding="utf-8")
    names = [name for name in ("fabric_clock", "gate_io_clockOut") if re.search(r"\b" + name + r"\b", clean(rtl))]
    require(len(names) == 1, "SERVICE_CLOCK_ALIAS")
    # A vector or signed wire is not the emitted scalar clock ABI. Inventory
    # every declaration of this name, including a second bare declaration;
    # checking just its continuous driver does not establish that shape.
    declarations = []
    for declaration in re.finditer(r"\b(?:wire|reg|logic)\b([^;]*);", clean(rtl)):
        # Split declaration lists only at top-level commas; commas within an
        # initializer's concatenation or function call are expression reads.
        parts = []; start = 0; depth = 0
        for index, char in enumerate(declaration[1]):
            depth += (char in "([{") - (char in ")]}")
            if char == "," and depth == 0:
                parts.append(declaration[1][start:index]); start = index + 1
        parts.append(declaration[1][start:])
        for part in parts:
            if re.search(r"\b" + names[0] + r"\b", part.split("=", 1)[0]):
                declarations.append(declaration[0])
    require(len(declarations) == 1 and re.fullmatch(
        r"wire\s+" + names[0] + r"\s*(?:;|=\s*[^;]+;)", declarations[0]) is not None,
        "SERVICE_CLOCK_DECLARATION")
    extracted = directory / "verification" / "assert" / (target["module"] + "_Verification_Assert.sv")
    require(names[0] == top_spelling(not extracted.is_file())("fabric_clock"), "SERVICE_CLOCK_FORM")
    connection = pins(rtl, target["rtl_path"].rsplit(".", 1)[1], target["module"])
    enable = connection.get("frameAcceptEnable")
    require(enable in ("gate_enabled", "1'h1"), "WORK_ENABLE_BINDING")
    driver(rtl, names[0], "serviceClock&gate_enabled" if enable == "gate_enabled" else "serviceClock")
    return root["rtl_path"] + "." + names[0]


def epoch_assertion_policy(directory, model, rising, ready_reset, inline=False):
    raw = assertion_source(directory, model, inline, "EPOCH_ASSERTION")
    un = clean(raw); prefix = "" if inline else model + "."
    blocks = re.findall(r"`ifndef\s+SYNTHESIS[^\n]*\n(.*?)`endif\s*//\s*not def SYNTHESIS", raw, re.S)
    require(len(blocks) == 2 and compact(clean(blocks[0])) == "`ifndefENABLE_INITIAL_REG_`defineENABLE_INITIAL_REG_`endif", "EPOCH_ASSERTION_GUARD")
    def packed(path):
        return "{" + ",".join(prefix + ("_" if inline else "") + path + leaf(f) +
                              ("" if inline else "_layerCapture") for f, _, _ in reversed(FIELDS)) + "}"
    banks = "{" + ",".join("{" + packed(f"ca_child_frame_store_banks_{i}_bits_") + "}" for i in reversed(range(4))) + "}"
    expected = "wire _GEN=" + prefix + ("host_frame_valid_0&~localReset_release_1;" if inline else "_host_frame_valid_T_layerCapture&~" + prefix + "localReset_layerCapture;")
    expected += "wire[3:0][336:0]_GEN_0=" + banks + ";always@(posedge " + prefix + "clock)begin "
    checks = [
        ("_GEN&" + ("_ca_child_frame_store_in_ack!=_ca_child_native_frame_req" if inline else prefix + "ca_child_frame_store_in_ack_layerCapture!=" + prefix + "ca_child_native_frame_req_layerCapture"), "FRAME_STORE_COPY_NOT_READY_AT_A"),
        ("_GEN&_GEN_0[" + prefix + "frameSlot]!=" + packed("ca_child_native_frame_bits_"), "FRAME_STORE_COPY_IDENTITY_AT_A"),
        (prefix + rising + "&~" + prefix + ready_reset + "&(&" + prefix + "resetEpoch_epoch)", "I2C_RESET_EPOCH_WRAP"),
        (prefix + ("event_0" if inline else "event_layerCapture") + "&~" + prefix + ready_reset + "&" + prefix + "tailGray==(headGray^4'hC)", "I2C_EDGE_RING_OVERFLOW")]
    for condition, label in checks:
        expected += 'if(' + condition + ')begin if(`ASSERT_VERBOSE_COND_)$error("Assertion failed: ' + label + '\\n");if(`STOP_COND_)$fatal;end '
    expected += "end"
    require(compact(clean(blocks[1])) == compact(expected), "EPOCH_ASSERTION_LOGIC")
    if inline:
        inline_assertion_wrapper_policy(model, raw, "I2C_RESET_EPOCH_WRAP", "EPOCH_ASSERTION")
        return
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
    assertion_wrapper_policy(directory, model, raw, "I2C_RESET_EPOCH_WRAP", "EPOCH_ASSERTION")


def overflow_assertion_policy(directory, model, inline=False):
    """Check the overflow assertion's actual clock, ancestors and both actions."""
    raw = assertion_source(directory, model, inline, "OVERFLOW_ASSERTION")
    if inline:
        inline_assertion_wrapper_policy(model, raw, "CONTROL_HOST_MAILBOX_OVERFLOW", "OVERFLOW_ASSERTION")
    else:
        assertion_wrapper_policy(directory, model, raw, "CONTROL_HOST_MAILBOX_OVERFLOW", "OVERFLOW_ASSERTION")
    blocks = [b for b in always_blocks(raw) if "CONTROL_HOST_MAILBOX_OVERFLOW" in b]
    require(len(blocks) == 1 and clean(raw).count("CONTROL_HOST_MAILBOX_OVERFLOW") == 1, "OVERFLOW_ASSERTION_COUNT")
    head = re.match(r"always\s*@\((.*?)\)\s*(.*)", blocks[0], re.S)
    prefix = "" if inline else model + "."
    require(head and compact(head[1]) == "posedge" + prefix + top_spelling(inline)("fabric_clock"), "OVERFLOW_ASSERTION_CLOCK")
    calls = []
    def replace(match):
        calls.append(match[0])
        return f"check_call_{len(calls)-1}<=1;"
    body = re.sub(r'\$error\("[^"\n]*"\);|\$fatal;', replace, head[2])
    tree = statement_tree(body)
    index = [i for i, call in enumerate(calls) if "CONTROL_HOST_MAILBOX_OVERFLOW" in call]
    require(len(index) == 1 and index[0] + 1 < len(calls) and calls[index[0] + 1] == "$fatal;", "OVERFLOW_ASSERTION_ACTIONS")
    guards = {}
    def visit(node, path=()):
        if node[0] == "assign": guards.setdefault(node[1], []).append((path, node[2]))
        elif node[0] == "sequence":
            for item in node[1:]: visit(item, path)
        else:
            visit(node[2], path + ((node[1], True),)); visit(node[3], path + ((node[1], False),))
    visit(tree)
    pred = top_spelling(inline)("~" + prefix + "reset&~(~" + prefix + "fabric_io_i2c_frame_valid|" + prefix + "fabric_hostFrames_io_enq_ready)")
    for number, macro in ((index[0], "`ASSERT_VERBOSE_COND_"), (index[0] + 1, "`STOP_COND_")):
        require(guards.get(f"check_call_{number}") == [(((pred, True), (macro, True)), "1")], "OVERFLOW_ASSERTION_LOGIC")
    for macro in ("STOP_COND", "ASSERT_VERBOSE_COND"):
        expected = f"`ifndef {macro}_\n`ifdef {macro}\n`define {macro}_ (`{macro})\n`else\n`define {macro}_ 1\n`endif\n`endif"
        require(compact(expected) in compact(clean(raw)) and len(re.findall(r"`define\s+" + macro + r"_\b", clean(raw))) == 2, "OVERFLOW_ASSERTION_MACRO")


def _mailbox_policy(rtl, clock, source):
    """Close every original slot/count transition including its ancestor guards."""
    fields = [("bank", 2), ("resetActive", 1), ("programBusy", 1)]
    names = {f"fabric_hostFrames_{slot}_{name}" for slot in ("first", "second") for name, _ in fields}
    names.add("fabric_hostFrames_count")
    inventory = re.findall(r"\breg\s+(?:\[[^;]+?\]\s*)?(fabric_hostFrames_\w+)\b", clean(rtl))
    require(len(inventory) == len(names) and set(inventory) == names, "MAILBOX_REGISTER_INVENTORY")
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


def native_bank_integration(directory, root, target, store, heads, tr, sr, sp, rp, tp, gate, pairs, inline=False):
    """Close borrowed input, physical bank heads and selected D command routing."""
    top = root["rtl_path"]; t = target["rtl_path"]; st = store["rtl_path"]
    spell = top_spelling(inline)
    copy_ack = "_ca_child_frame_store_in_ack" if inline else "ca_child_frame_store_in_ack_layerCapture"
    qualify = lambda expression: re.sub(r"(?<![\w'])\b[A-Za-z_]\w*\b", lambda match: top + "." + match[0], expression)
    require(sp.get("reset") == "reset" and sp.get("slot") == "frameSlot" and
            sp.get("in_ack") == copy_ack and
            sp.get("busy") == "_ca_child_frame_store_busy", "STORE_CONTROL_PINS")
    for i in range(4):
        require(sp.get(f"available_{i}") == "", "STORE_AVAILABILITY_PIN:" + str(i))
    pairs += [(st + ".reset", top + ".reset"), (st + ".slot", t + ".frameSlot"),
              (t + "." + copy_ack, st + ".in_ack"),
              (t + "._ca_child_frame_store_busy", st + ".busy")]
    for net in (sp["in_ack"], sp["busy"]): no_other_writers(tr, net)
    for suffix in ["req"] + ["bits_" + leaf(f) for f, _, _ in FIELDS]:
        require(sp.get("in_" + suffix) == rp["in_" + suffix], "BORROWED_SOURCE:" + suffix)
        pairs.append((st + ".in_" + suffix, target["rtl_path"] + "." + rp["in_" + suffix]))
    command = child(root, "control_command_bridge")
    click = store["module"].startswith("Click")
    expected_command = "DecoupledToClick" if click else "DecoupledToFourPhase"
    require(re.fullmatch(expected_command + r"(?:_[0-9]+)?", command["module"]) and
            command["reset_domain"] == "root", "COMMAND_OWNER")
    cp = pins(sr, command["rtl_path"].rsplit(".", 1)[1], command["module"])
    require(cp.get("clock") == spell("fabric_clock") and cp.get("reset") == "reset" and
            cp.get("in_valid") == "fabric_io_controlCommand_valid" and
            cp.get("in_ready") == "_ca_child_control_command_bridge_in_ready" and
            cp.get("in_bits_kind") == "fabric_io_controlCommand_bits_kind", "COMMAND_CONTROL_PINS")
    expected = {
        "fabric_mmioLaunch": "fabric__mmioLaunch_T&fabric_cpuAvailable&~fabric_hostFrames_io_deq_valid",
        "fabric_hostHeadValid": "fabric_hostFrames_io_deq_valid&_GEN_12[fabric_hostFrames_first_bank]",
        "fabric__io_i2c_heads_0_ready_T": gate + "&fabric_hostFrames_io_deq_ready" if gate != "1'h1" else "fabric_hostFrames_io_deq_ready",
        "fabric_controlBusy": "fabric_controlOutstanding|_ca_child_program_stored_bridge_out_valid|fabric_mmioCommitPending|fabric_resetPending|fabric_haltPending|fabric_hostFrames_io_deq_valid",
        "fabric_io_controlCommand_valid": "~fabric_controlOutstanding&(_ca_child_program_stored_bridge_out_valid|fabric_mmioCommitPending|fabric_resetPending|fabric_haltPending|fabric_hostHeadValid|fabric_mmioLaunch)",
        "fabric__27": "fabric_mmioCommitPending&~_ca_child_program_stored_bridge_out_valid",
        "_GEN_50": "fabric__27|~fabric_hostFrames_io_deq_valid",
        "fabric_io_controlCommand_bits_kind": "fabric__27?3'h5:_ca_child_program_stored_bridge_out_valid?3'h1:fabric_mmioCommitPending?3'h5:fabric_resetPending?3'h2:fabric_haltPending?3'h3:{~fabric_hostHeadValid,2'h0}",
    }
    for name, expression in expected.items():
        driver(sr, spell(name), spell(expression))
        pairs.append((top + "." + name, "(" + qualify(expression) + ")"))
    banks = []
    for i, head in enumerate(heads):
        actual, _ = actual_receipt_rtl(head, directory, tr)
        hp = pins(tr, head["rtl_path"].rsplit(".", 1)[1], actual)
        require(hp.get("clock") == "clock" and hp.get("reset") == "reset", "HEAD_CLOCK_RESET:" + str(i))
        pairs += [(head["rtl_path"] + ".clock", top + ".serviceClock"), (head["rtl_path"] + ".reset", top + ".reset")]
        for suffix in ["req", "ack"] + ["bits_" + leaf(f) for f, _, _ in FIELDS]:
            require(hp.get("in_" + suffix) == sp.get(f"banks_{i}_" + suffix) and
                    re.fullmatch(r"\w+", hp.get("in_" + suffix, "")), "BANK_HEAD_PIN:" + str(i) + ":" + suffix)
            no_other_writers(tr, hp["in_" + suffix])
            pairs.append((head["rtl_path"] + ".in_" + suffix, st + f".banks_{i}_" + suffix))
        for suffix in ["ready", "valid"] + ["bits_" + leaf(f) for f, _, _ in FIELDS]:
            out_net = f"host_heads_{i}_" + suffix
            require(hp.get("out_" + suffix) == out_net, "HEAD_OUTPUT_PIN:" + str(i) + ":" + suffix)
            if suffix != "ready": no_other_writers(tr, out_net)
            if suffix == "ready":
                selected = f"fabric_hostFrames_first_bank==2'h{i}" if i < 3 else "(&fabric_hostFrames_first_bank)"
                expression = "fabric__io_i2c_heads_0_ready_T&fabric_hostFrames_io_deq_valid&" + selected
            elif suffix in ("bits_ingress_resetActive", "bits_ingress_programBusy"):
                # Context comes from the A descriptor, but the full receipt ABI
                # remains present and directly bound through the target port.
                expression = ""
                pairs.append((t + "." + out_net, head["rtl_path"] + ".out_" + suffix))
            else:
                expression = f"_ca_child_i2c_host_heads_{i}_" + suffix
            require(tp.get(f"host_heads_{i}_" + suffix) == expression, "TOP_HEAD_PIN:" + str(i) + ":" + suffix)
            if suffix == "ready": pairs.append((head["rtl_path"] + ".out_ready", "(" + qualify(expression) + ")"))
            if expression and suffix != "ready":
                no_other_writers(sr, expression)
                pairs.append((top + "." + expression, head["rtl_path"] + ".out_" + suffix))
        fields = [f"{st}.banks_{i}_bits_" + leaf(f) for f, _, _ in reversed(FIELDS)]
        owner = store if click else child(store, f"storage{i}")
        cells = [c for c in owner.get("primitives", []) if c["id"] == (f"payload{i}" if click else "payload")]
        require(len(cells) == 1 and cells[0]["model"] == ("ChiselAsyncEventRegister_v1" if click else "ChiselAsyncClosingLatch_v1") and
                cells[0]["parameters"].get("WIDTH") == "337", "BANK_PAYLOAD_OWNER:" + str(i))
        payload = cells[0]["rtl_path"]
        pairs.append((payload + ".q", "{" + ",".join(fields) + "}"))
        banks.append(dict(index=i, receipt=head["rtl_path"], request=f"{st}.banks_{i}_req", acknowledge=f"{st}.banks_{i}_ack",
                          data="{" + ",".join(fields) + "}", payload=payload, d=payload + ".d", q=payload + ".q",
                          capture=payload + (".trigger" if click else ".closed"), copy_ack=st + ".in_ack"))
    # Exact packed arrays feed one selected head; no byte/epoch truncation or permutation.
    selected_fields = [("valid", 12)] + [("bits_ingress_frame_length", 13), ("bits_ingress_frame_overflow", 14)] + [
        (f"bits_ingress_frame_bytes_{i}", 15 + i) for i in range(33)] + [("bits_resetEpoch", 48)]
    for field, number in selected_fields:
        expression = "{" + ",".join("{" + f"_ca_child_i2c_host_heads_{i}_" + field + "}" for i in reversed(range(4))) + "}"
        driver(sr, f"_GEN_{number}", expression)
        pairs.append((top + f"._GEN_{number}", qualify(expression)))
    driver(sr, "fabric_io_controlCommand_bits_frame_bytes_0", "_GEN_50?8'h0:_GEN_15[fabric_hostFrames_first_bank]")
    command_fields = [("length", 6, 13), ("overflow", 1, 14)] + [(f"bytes_{i}", 8, 15 + i) for i in range(33)]
    for field, width, number in command_fields:
        select = f"_GEN_{number}[fabric_hostFrames_first_bank]"
        expression = ("fabric_io_controlCommand_bits_frame_bytes_0" if field == "bytes_0" else
                      "~fabric__27&fabric_hostFrames_io_deq_valid&" + select if field == "overflow" else
                      f"_GEN_50?{width}'h0:" + select)
        require(cp.get("in_bits_frame_" + field) == spell(expression), "COMMAND_FRAME_PIN:" + field)
        pairs.append((command["rtl_path"] + ".in_bits_frame_" + field, "(" + qualify(expression) + ")"))
    for field, expression in {
        "cpuResetActive": "~fabric__27&(cpuResetActive|fabric_hostFrames_io_deq_valid&(fabric_hostFrames_first_resetActive|_GEN_48[fabric_hostFrames_first_bank]!=_ca_child_i2c_host_currentEpoch))",
        "programBusy": "~fabric__27&(_ca_child_program_access_io_busy|fabric_hostFrames_io_deq_valid&fabric_hostFrames_first_programBusy)"}.items():
        require(cp.get("in_bits_" + field) == spell(expression), "COMMAND_CONTEXT_PIN:" + field)
        pairs.append((command["rtl_path"] + ".in_bits_" + field, "(" + qualify(expression) + ")"))
    return banks, dict(path=command["rtl_path"], clock=command["rtl_path"] + ".clock", reset=command["rtl_path"] + ".reset",
                       valid=command["rtl_path"] + ".in_valid", ready=command["rtl_path"] + ".in_ready",
                       kind=command["rtl_path"] + ".in_bits_kind", selected_bank=top + ".fabric_hostFrames_first_bank")


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
    store = child(target, "frame_store")
    heads = [child(target, f"frame_head{i}_bridge") for i in range(4)]
    ids = [c["id"] for c in target["children"]]
    require(len(ids) == 8 and set(ids) == {"native", "frame_bridge", "frame_store", "snapshot_bridge"} |
            {f"frame_head{i}_bridge" for i in range(4)}, "TARGET_INVENTORY")
    publication = child(native, "publication"); snapshot = child(target, "snapshot_bridge")
    click = validate_frame_receipt(receipt); prefix = "Click" if click else "FourPhase"
    require(re.fullmatch(prefix + r"I2c(?:_[0-9]+)?", native["module"]) and
            re.fullmatch(r"I2cPublication(?:_[0-9]+)?", publication["module"]), "NATIVE_OWNERS")
    require(re.fullmatch(prefix + r"ToDecoupled(?:_[0-9]+)?", snapshot["module"]), "SNAPSHOT_OWNER")
    require(re.fullmatch(prefix + r"FrameStore(?:_[0-9]+)?", store["module"]) and
            type(store.get("capacity")) is int and store["capacity"] == 4, "STORE_OWNER")
    for h in heads: require(validate_frame_receipt(h) == click, "HEAD_OWNER")
    for node in (target, native, receipt, publication, snapshot, store, *heads):
        require(node["reset_domain"] == "root", "POR_OWNER")
    te = {e["id"]: e for e in target["endpoints"]}
    require(len(te) == len(target["endpoints"]) and type(te.get("frame_accept_enable", {}).get("width")) is int and
            te["frame_accept_enable"]["width"] == 1 and
            te["frame_accept_enable"].get("source") == f"~|{target['module']}>frameAcceptEnable", "ENABLE_ENDPOINT")
    tr = (directory / (target["module"] + ".sv")).read_text(encoding="utf-8")
    nr = (directory / (native["module"] + ".sv")).read_text(encoding="utf-8")
    sr = (directory / (root["module"] + ".sv")).read_text(encoding="utf-8")
    receipt_model, _ = actual_receipt_rtl(receipt, directory, tr)
    rp = pins(tr, receipt["rtl_path"].rsplit(".", 1)[1], receipt_model)
    sp = pins(tr, store["rtl_path"].rsplit(".", 1)[1], store["module"])
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
        output = ("_ca_child_frame_bridge_out_bits_" + f if field in ("resetEpoch", "ingress.resetActive") else
                  "host_frame_bits_programBusy" if field == "ingress.programBusy" else
                  "host_frame_bits_" + f.removeprefix("ingress_"))
        require(rp.get("out_bits_" + f) == output, "FRAME_OUTPUT_PIN:" + f)
        no_other_writers(tr, output)
        if field.startswith("ingress.frame."):
            # No clocked client consumes the old payload port. Preserve its
            # declared ABI and exact source, and require the explicit unused
            # parent connection instead of accepting a pruned/missing pin.
            require(tp.get(output) == "", "TOP_UNUSED_FRAME_PIN:" + f)
            pairs.append((t + "." + output, r + ".out_bits_" + f))
    require(rp.get("out_ready") == "ca_child_frame_bridge_out_ready" and
            rp.get("out_valid") == "_ca_child_frame_bridge_out_valid", "RECEIPT_CONTROL_PINS")
    observed = "localReset_layerCapture" in clean(tr)
    inline = not observed
    spell = top_spelling(inline)
    valid = "_host_frame_valid_T_layerCapture" if observed else "host_frame_valid_0"
    local_reset = "localReset_layerCapture" if observed else "localReset_release_1"
    ready_reset = "_resetEpoch_T_2_layerCapture" if observed else local_reset
    rising = "resetEpoch_rising_layerCapture" if observed else "resetEpoch_rising"
    if observed:
        driver(tr, local_reset, "localReset_release_1")
        driver(tr, ready_reset, local_reset)
    for name, value in dict(ca_child_frame_bridge_out_ready="~" + ready_reset + "&frameAcceptEnable",
                           **{rising: "host_resetActive&~resetEpoch_previous"},
                           resetEpoch=rising + "?resetEpoch_epoch+64'h1:resetEpoch_epoch",
                           **{valid: "ca_child_frame_bridge_out_ready&_ca_child_frame_bridge_out_valid"},
                           host_frame_valid=valid,
                           host_frameSlot="frameSlot", host_currentEpoch="resetEpoch",
                           host_frame_bits_resetActive="_ca_child_frame_bridge_out_bits_ingress_resetActive|host_resetActive|_ca_child_frame_bridge_out_bits_resetEpoch!=resetEpoch",
                           host_busy="active_stages_1|start|stop|effects_stages_1|_ca_child_frame_bridge_out_valid|_ca_child_snapshot_bridge_out_valid|frameStoreBusy_stages_1").items(): driver(tr, name, value)
    state_policy(tr, {"localReset_release_0": "1'h1", "localReset_release_1": "1'h1"},
                 "posedge clock or posedge reset", "begin if(reset)begin localReset_release_0<=1'h1;localReset_release_1<=1'h1;end else begin localReset_release_0<=1'h0;localReset_release_1<=localReset_release_0;end end")
    state_policy(tr, {"resetEpoch_epoch": "64'h0", "resetEpoch_previous": "1'h0"},
                 "posedge clock or posedge " + local_reset,
                 "begin if(" + local_reset + ")begin resetEpoch_epoch<=64'h0;resetEpoch_previous<=1'h0;end else begin if(" + rising + ")resetEpoch_epoch<=resetEpoch_epoch+64'h1;resetEpoch_previous<=host_resetActive;end end", local_reset)
    state_policy(tr, {"frameSlot": "2'h0"}, "posedge clock or posedge " + local_reset,
                 "begin if(" + local_reset + ")frameSlot<=2'h0;else if(" + valid + ")frameSlot<=frameSlot+2'h1;end", local_reset)
    state_policy(tr, {"frameStoreBusy_stages_0": "1'h0", "frameStoreBusy_stages_1": "1'h0"},
                 "posedge clock or posedge " + local_reset,
                 "begin if(" + local_reset + ")begin frameStoreBusy_stages_0<=1'h0;frameStoreBusy_stages_1<=1'h0;end else begin frameStoreBusy_stages_0<=_ca_child_frame_store_busy;frameStoreBusy_stages_1<=frameStoreBusy_stages_0;end end", local_reset)
    epoch_assertion_policy(directory, target["module"], rising, ready_reset, inline)
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
                     spell("begin if(reset)begin " + "".join(n + "<=" + v + ";" for n, v in gate_values.items()) +
                     "end else begin gate_demandFirst<=" + demand + ";gate_needClock<=gate_demandFirst;gate_drainFirst<=" + drain +
                     ";gate_drain<=gate_drainFirst;if(gate_drain)gate_grace<=3'h7;else if(|gate_grace)gate_grace<=gate_grace-3'h1;end end"))
        state_policy(sr, {"gate_enabled": "1'h1"}, "posedge gate__enabled_T_3 or posedge reset",
                     "begin if(reset)gate_enabled<=1'h1;else gate_enabled<=(|{gate_needClock,gate_grace})|reset;end")
        driver(sr, spell("fabric_clock"), "serviceClock&gate_enabled")
        gate_path = top + ".gate_enabled"
    else:
        driver(sr, spell("fabric_clock"), "serviceClock")
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
    for name, value in expected_top.items(): driver(sr, spell(name), spell(value))
    qualify = lambda expression: re.sub(r"(?<![\w'])\b[A-Za-z_]\w*\b", lambda match: top + "." + match[0], expression)
    pairs += [(top + "." + name, "(" + qualify(value) + ")") for name, value in expected_top.items()]
    host_busy = "_ca_child_program_access_io_busy|fabric_loaderPending|fabric_loaderControlPending|fabric__6&fabric__loaderControlPending_T&fabric__loaderControlPending_T_1&fabric__loaderControlPending_T_3"
    require(tp.get("host_frame_valid") == spell("fabric_io_i2c_frame_valid") and tp.get("host_resetActive") == "cpuResetActive" and
            tp.get("host_programBusy") == spell(host_busy) and tp.get("host_busy") == "_ca_child_i2c_host_busy", "TOP_ADMISSION_PINS")
    state_policy(sr, {"fabric_loaderControlPending": "1'h0"}, spell("posedge fabric_clock or posedge reset"),
                 spell("begin if(reset)fabric_loaderControlPending<=1'h0;else fabric_loaderControlPending<=~fabric__5&(fabric__6?fabric__loaderControlPending_T&fabric__loaderControlPending_T_1&fabric__loaderControlPending_T_3:fabric_loaderControlPending);end"))
    source = {"bank": "_ca_child_i2c_host_frameSlot"}
    for f in ("resetActive", "programBusy"):
        net = "_ca_child_i2c_host_frame_bits_" + f
        require(tp.get("host_frame_bits_" + f) == net, "TOP_FRAME_PIN:" + f)
        no_other_writers(sr, net)
        source[f] = "fabric_hostFrames_io_enq_bits_" + f
        pairs.append((top + "." + net, t + ".host_frame_bits_" + f))
    require(tp.get("host_frameSlot") == source["bank"] and
            tp.get("host_currentEpoch") == "_ca_child_i2c_host_currentEpoch", "TOP_STORE_PINS")
    for net in (source["bank"], "_ca_child_i2c_host_currentEpoch"): no_other_writers(sr, net)
    pairs += [(top + "." + source["bank"], t + ".frameSlot"),
              (top + "._ca_child_i2c_host_currentEpoch", t + ".resetEpoch")]
    require(not re.search(r"\breg\s+(?:\[[^;]+\]\s*)?(?:fabric_hostResetDebt|fabric_hostFrames_(?:first|second)_frame_\w+)\b", clean(sr)), "OLD_CLOCKED_PAYLOAD_OR_DEBT")
    bank_records, command_record = native_bank_integration(directory, root, target, store, heads, tr, sr,
                                                           sp, rp, tp, gate, pairs, inline)
    fields = _mailbox_policy(sr, spell("fabric_clock"), source)
    overflow_assertion_policy(directory, root["module"], inline)
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
                store=store["rtl_path"], frame_slot=t + ".frameSlot", banks=bank_records, command=command_record,
                current_epoch=t + ".resetEpoch", clock=spell(top + ".fabric_clock"), reset=top + ".reset", gate=gate_path,
                enq=enq, deq=deq, count=top + ".fabric_hostFrames_count", slots=slots,
                pairs=[(spell(a), spell(b)) for a, b in pairs],
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

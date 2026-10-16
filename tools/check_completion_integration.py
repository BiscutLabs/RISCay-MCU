# SPDX-License-Identifier: Apache-2.0
"""Strict mapping obligations at the clocked/native completion boundary."""
import re
from check_application_reset import coordinated_reset
from check_service_reply_receipt import native_reply_source, pack_reply, control_widths
from check_quiescing_receipt import native_request_source, pack_request


def native_return_cell(manifest, scopes, header, bank, identity, suffix, model, parameters, width=1):
    """Resolve one exact return-owner cell; never infer a source from a net name."""
    top=manifest['top'];root=top+'.ca_child_'+bank+'_return'
    owners=[c['contract'] for c in manifest['design']['children'] if c['id']==bank+'_return']
    prefix='Click' if top=='ClickSoc' else 'FourPhase'
    if (bank not in ('ram','program') or len(owners)!=1 or owners[0].get('rtl_path')!=root or
            not re.fullmatch(prefix+bank.title()+r'Return(?:_[0-9]+)?',owners[0].get('module',''))):
        raise ValueError('COMPLETION_NATIVE_RETURN_OWNER:'+bank)
    cells=[p for p in owners[0].get('primitives',[]) if p['id']==identity]
    path=root+'.'+suffix;q=dict(name='q',width=width,direction='output')
    if (len(cells)!=1 or cells[0].get('rtl_path')!=path or cells[0].get('model')!=model or
            cells[0].get('parameters')!=parameters or cells[0].get('reset')!='reset' or
            cells[0].get('reset_domain')!='root' or
            [p for p in cells[0].get('ports',[]) if p.get('name')=='q']!=[q] or
            scopes.get(path,{}).get('model')!=model or scopes[path].get('ports',{}).get('q')!=q or
            scopes[path].get('parameters')!=parameters or f"force {path}.q = {width}'h0;" not in header):
        raise ValueError('COMPLETION_NATIVE_RETURN_CELL:'+bank+'.'+identity)
    return path+'.q'


def program_permission_sources(manifest,scopes,header):
    """Only retained native state may supply the CPU/loader permit truth table."""
    top=manifest['top'];click=top=='ClickSoc';prefix='Click' if click else 'FourPhase'
    path=top+'.ca_child_program_source'
    owners=[c['contract'] for c in manifest['design']['children'] if c['id']=='program_source']
    if (len(owners)!=1 or owners[0].get('rtl_path')!=path or
            not re.fullmatch(prefix+r'ProgramSource(?:_[0-9]+)?',owners[0].get('module',''))):
        raise ValueError('COMPLETION_PROGRAM_PERMISSION_OWNER')
    owner=owners[0];buffers=[c['contract'] for c in owner.get('children',[]) if c['id']=='reservation']
    if (len(buffers)!=1 or buffers[0].get('rtl_path')!=path+'.ca_child_reservation' or
            not re.fullmatch(('ClickBuffer' if click else 'LongHoldBuffer')+r'(?:_[0-9]+)?',buffers[0].get('module',''))):
        raise ValueError('COMPLETION_PROGRAM_PERMISSION_RESERVATION')
    reservation=buffers[0]
    def cell(node,name,model,parameters,width=1,reset='reset',suffix=None):
        cells=[p for p in node.get('primitives',[]) if p['id']==name]
        base=node['rtl_path']+'.'+(suffix or 'ca_primitive_'+name);q=dict(name='q',width=width,direction='output')
        if (len(cells)!=1 or cells[0].get('rtl_path')!=base or cells[0].get('model')!=model or
                cells[0].get('parameters')!=parameters or cells[0].get('reset')!=reset or cells[0].get('reset_domain')!='root' or
                [p for p in cells[0].get('ports',[]) if p.get('name')=='q']!=[q] or
                scopes.get(base,{}).get('model')!=model or scopes[base].get('parameters')!=parameters or
                scopes[base].get('ports',{}).get('q')!=q or f"force {base}.q = {width}'h0;" not in header):
            raise ValueError('COMPLETION_PROGRAM_PERMISSION_CELL:'+name)
        return base+'.q'
    event=lambda width:dict(WIDTH=str(width),DELAY_FS='1000000',RESET_VALUE='0')
    result=dict(eligibility=cell(owner,'eligibility','ChiselAsyncEventRegister_v1',event(1),reset='eligibility_reset'))
    result['loader']=cell(reservation,'payload','ChiselAsyncEventRegister_v1' if click else 'ChiselAsyncClosingLatch_v1',
        event(1) if click else dict(WIDTH='1',DELAY_FS='1000000'))
    if click:
        result.update(reserved=cell(reservation,'input_phase','ChiselAsyncPhaseRegister_v1',dict(DELAY_FS='1000000',RESET_VALUE='0')),
            armed=cell(owner,'armed_phase','ChiselAsyncEventRegister_v1',event(2),2),
            retired=cell(owner,'retired_phase','ChiselAsyncEventRegister_v1',event(1)),
            owned=cell(owner,'owned','ChiselAsyncXor_v1',dict(DELAY_FS='1000000'),suffix='owned_ca_primitive_owned'),
            reserved_guard=cell(reservation,'acknowledge_guard','ChiselAsyncControlGate_v1',dict(DELAY_FS='32000000',OP='0',RESET_VALUE='0',WIDTH='1')))
    else:
        result['reserved']=cell(reservation,'acknowledge','ChiselAsyncAsymmetricC_v1',
            dict(COMMON='1',COMMON_INVERT='1',DELAY_FS='1000000',FALLING='1',FALLING_INVERT='0',RESET_VALUE='0',RISING='1',RISING_INVERT='0'))
    return result


def completion_bridges(manifest):
    top = manifest.get("top")
    if top not in ("FourPhaseSoc", "ClickSoc"):
        return {}
    children = {c["id"]: c["contract"] for c in manifest["design"].get("children", [])}
    names = {"completion_"+n+"_bridge" for n in ("plan", "telemetry", "housekeeping")}
    if 'completion_memory_bridge' in children:
        raise ValueError("COMPLETION_OBSOLETE_MEMORY_BRIDGE")
    found = names & children.keys()
    if not found:
        return {}
    if found != names:
        raise ValueError("COMPLETION_BRIDGE_INVENTORY")
    prefix = "DecoupledToClick" if top == "ClickSoc" else "DecoupledToFourPhase"
    if any(e['id']=='native_application_reset' for e in manifest['design'].get('endpoints',[])):
        prefix += 'Quiescing'
    protocol = "two-phase-bundled-v1" if top == "ClickSoc" else "four-phase-bundled-v1"
    for name in names:
        node = children[name]
        if (not re.fullmatch(prefix+r"(?:_[0-9]+)?", node["module"]) or
                node["rtl_path"] != top+".ca_child_"+name or
                {c["id"]: (c["protocol"], c["role"]) for c in node["channels"]} !=
                {"in": ("decoupled-v1", "input"), "out": (protocol, "output")}):
            raise ValueError("COMPLETION_BRIDGE_OWNER")
    return {name: children[name] for name in names}


def completion_constants_probe(source, manifest, scopes, top_rtl):
    """Replace impossible polarity coverage ONLY for two literal effect leaves.

    Require their exact values on every check. All dynamic bits keep both-polarity
    coverage; storage outputs, native inputs, comparisons and drivers are untouched.
    The public schema and elaborated scalar leaf must agree before applying a mask.
    """
    bridges = completion_bridges(manifest)
    if not bridges:
        return source
    comparisons = []
    for name, width, pin, value, layout in (
            ("telemetry", 1, "in_bits", 1, [("bits", 0, 1)]),
            ("housekeeping", 1, "in_bits", 1, [("bits", 0, 1)])):
        node = bridges["completion_"+name+"_bridge"]
        channel = next(c for c in node["channels"] if c["id"] == "in")
        fields = [(f["field"], f["lsb"], f["width"]) for f in channel["layout"]]
        endpoints = {e["id"]: e for e in node["endpoints"]}
        path = node["rtl_path"]
        if (channel.get("data") != "in_data" or fields != layout or
                any(f["signed"] for f in channel["layout"]) or
                endpoints.get("in_data", {}).get("width") != width or
                scopes.get(path, {}).get("ports", {}).get(pin) !=
                dict(name=pin, width=1, direction="input")):
            raise ValueError("COMPLETION_CONSTANT_SCHEMA")
        # The pinned emitter emits one named instance per line and a closing
        # `);` on its own line. Reject changed syntax instead of inferring a
        # constant from finite simulation samples of a potentially dynamic net.
        clean = re.sub(r"/\*.*?\*/|//[^\n]*", "", top_rtl, flags=re.S)
        instance = path.rsplit(".", 1)[1]
        blocks = list(re.finditer(r"^\s*(\w+)\s+"+re.escape(instance)+r"\s*\((.*?)^\s*\);", clean, re.M | re.S))
        if (len(blocks) != 1 or blocks[0][1] != scopes[path]["model"]):
            raise ValueError("COMPLETION_CONSTANT_INSTANCE")
        bindings = re.findall(r"\."+pin+r"\s*\(([^()]*)\)", blocks[0][2])
        if bindings != [f"1'h{value}"]:
            raise ValueError("COMPLETION_CONSTANT_LITERAL:"+name)
        endpoint = endpoints["in_data"]["rtl_path"]
        comparisons.append(f'if ({path}.{pin} !== 1\'h{value}) $fatal(1,"COMPLETION_CONSTANT_BINDING:{name}");')
        # Also assert the corresponding packed endpoint bit, independent of aliases.
        bit = endpoint+"[0]" if width > 1 else endpoint
        comparisons.append(f'if ({bit} !== {path}.{pin}) $fatal(1,"COMPLETION_CONSTANT_ENDPOINT:{name}");')
        full = (1 << width)-1
        pattern = (r"^if \(ones_(\d+) !== "+str(width)+"'h"+f"{full:x}"+
                   r" \|\| zeros_\1 !== "+str(width)+"'h"+f"{full:x}"+
                   r'\) \$fatal\(1, "INACTIVE_ENDPOINT:'+re.escape(endpoint)+r'"\);$')
        matches = list(re.finditer(pattern, source, re.M))
        if len(matches) != 1:
            raise ValueError("COMPLETION_CONSTANT_COVERAGE_SHAPE")
        match = matches[0]; index = match[1]
        ones, zeros = (full if value else full ^ 1), (full ^ 1 if value else full)
        replacement = (f"if (ones_{index} !== {width}'h{ones:x} || zeros_{index} !== {width}'h{zeros:x}) "
                       f'$fatal(1, "INACTIVE_ENDPOINT:{endpoint}");')
        source = source[:match.start()] + replacement + source[match.end():]
    anchor = "task check; begin"
    if source.count(anchor) != 1:
        raise ValueError("COMPLETION_CONSTANT_PROBE_SHAPE")
    return source.replace(anchor, anchor+"\n"+"\n".join(comparisons))


def completion_background(source, manifest, scopes, checks, program_bytes=None):
    """Add joint acceptance/publication scenarios using catalogued state.

    Each scenario starts at the original all-zero source header. No derived port,
    endpoint, activity counter, native combinational signal or constant is forced.
    The short drain prelude releases Click's generic forced ownership XOR while
    driving its actual phase registers, then restores the complete source header.
    """
    if not completion_bridges(manifest):
        return source, checks
    top = manifest["top"]
    anchor = f"initial begin\nforce {top}.reset = 1'b1; #1;\n"
    if source.count(anchor) != 1:
        raise ValueError("COMPLETION_BACKGROUND_SHAPE")
    start = source.index(anchor)+len(anchor)
    end = source.index("\n#1;\n", start)+len("\n#1;\n")
    header = source[start:end]
    coverage = list(re.finditer(r"^if \(ones_\d+ !==.*INACTIVE_ENDPOINT:.*$", source, re.M))
    marker = f"CONTRACT_PROBES_PASS:{checks}"
    if not coverage or source.count(marker) != 1:
        raise ValueError("COMPLETION_BACKGROUND_SHAPE")
    extra, steps = [], 0

    def force(path, width, value, primitive=False):
        node, field = path.rsplit(".", 1)
        source_valid = (scopes.get(node, {}).get("ports", {}).get(field) == dict(name=field,width=width,direction="output")) if primitive else (
            scopes.get(node, {}).get("registers", {}).get(field) == width)
        if (not source_valid or
                f"force {path} = {width}'h0;" not in header):
            raise ValueError("COMPLETION_BACKGROUND_DRIVER")
        if not 0 <= value < 1 << width:
            raise ValueError("COMPLETION_BACKGROUND_RANGE")
        extra.append(f"force {path} = {width}'h{value:x};\n")

    def check(delay=1):
        nonlocal steps
        extra.append(f"#{delay}; check;\n"); steps += 1

    def walk(width):
        return [0, (1 << width)-1] + [v for bit in range(width)
            for v in (1 << bit, ((1 << width)-1) ^ (1 << bit))]

    # Native return occupancy and presentation are independent of effects
    # drainage. Put their two distinguishing combinations before the expensive
    # generic sweep so wiring controls fail promptly at the original assertions.
    for bank in ('ram','program'):
        extra.append(header)
        def native_cell(identity,suffix,model,parameters,width=1):
            return native_return_cell(manifest,scopes,header,bank,identity,suffix,model,parameters,width)
        if top=='ClickSoc':
            owned=native_cell('owned','pending_ca_primitive_owned','ChiselAsyncXor_v1',dict(DELAY_FS='1000000'))
            guard=native_cell('acknowledge_guard','completedDelayed_ca_primitive_acknowledge_guard',
                'ChiselAsyncControlGate_v1',dict(DELAY_FS='200000000',OP='0',RESET_VALUE='0',WIDTH='1'))
            phases=[native_cell(n,'ca_primitive_'+n,'ChiselAsyncEventRegister_v1',
                dict(WIDTH='1',DELAY_FS='1000000',RESET_VALUE='0')) for n in ('received_phase','completed_phase')]
            extra.append(f'release {guard};\nrelease {owned};\n')
            force(phases[0],1,1,primitive=True);force(phases[1],1,0,primitive=True)
        else:
            pending=native_cell('pending','ca_primitive_pending','ChiselAsyncAsymmetricC_v1',
                dict(COMMON='1',COMMON_INVERT='1',DELAY_FS='1000000',FALLING='0',FALLING_INVERT='0',
                     RESET_VALUE='0',RISING='2',RISING_INVERT='0'))
            force(pending,1,1,primitive=True)
        access=top+'.ca_child_'+bank+'_access'
        force(top+'.gate_enabled',1,1)
        for group in ('returned_stages','bytesReturned_stages','bytesReturned_stages_1',
                      'bytesReturned_stages_2','bytesReturned_stages_3','ownerReturned_stages'):
            for stage in (0,1):force(access+f'.{group}_{stage}',1,1)
        settle=201000001 if top=='ClickSoc' else 1
        check(settle)
        force(phases[0] if top=='ClickSoc' else pending,1,0,primitive=True)
        for stage in (0,1):force(access+f'.ownerReturned_stages_{stage}',1,0)
        check(settle)
    prelude=''.join(extra)+header
    extra.clear()

    if top == "ClickSoc":
        # Generic one-hot/one-cold walks of a two-bit register never produce
        # 11. Exercise the real reset-release source, including its AND-reduced
        # startup state; never force Admission.start or relax its coverage.
        extra.append(header)
        for value in (0, 1, 2, 3):
            force(top+".ca_child_admission_start_stages", 2, value); check()

    request = top+".ca_child_request_bridge"
    request_native = native_request_source(manifest, scopes, header)
    control = top+".ca_child_control_reply_bridge"
    retained = {name: native_reply_source(manifest, scopes, header, name, program_bytes)
                for name in ("control", "telemetry", "housekeeping")}
    reply_values = {}
    def held(owner, field, value):
        values = reply_values.setdefault(owner, {})
        values[field] = value
        native = retained[owner]
        force(native["path"], native["width"], pack_reply(native, values), primitive=True)

    def plan(operation, address, mmio=False):
        extra.append(header)
        reply_values.clear()
        force(top+".gate_enabled", 1, 1)
        # The coordinated boundary's second synchronizer register has an
        # explicit synchronous cancellation mux, proved by the graph audit.
        force(top+(".second" if coordinated_reset(manifest) else ".fabric_io_completionIdle_REG"), 1, 1)
        force(top+".ca_child_admission_grant_bridge.state", 2, 2)
        for bank in ("program", "ram"):
            for group in ("returned_stages", "bytesReturned_stages", "bytesReturned_stages_1",
                          "bytesReturned_stages_2", "bytesReturned_stages_3"):
                for stage in (0, 1):
                    force(top+f".ca_child_{bank}_access.{group}_{stage}", 1, 1)
        for bank in ("program","ram"):
            for stage in (0,1):force(top+f".ca_child_{bank}_access.ownerReturned_stages_{stage}",1,1)
        force(request+".state", 2, 2)
        force(request_native['path'],70,pack_request(operation=operation,address=address,mask=15),primitive=True)
        if address == 0x20000000:
            force(top+".ca_child_ram_grant_bridge.state", 2, 2)
        elif address == 0x10000000:
            # RAM now selects its independent native return. Exercise the
            # remaining program selector through a permitted CPU-read request
            # and a retained program grant, not a forced plan endpoint.
            force(top+".fabric_controlState_programmed", 1, 1)
            force(top+".fabric_controlState_imageLength", control_widths(program_bytes)[0], 4)
            force(top+".ca_child_program_grant_bridge.state", 2, 2)
        if mmio:
            force(top+".fabric_controlOutstanding", 1, 1)
            force(top+".fabric_mmioCurrent", 1, 1)
            force(control+".state", 2, 2)
            held("control", "kind", 4)
            if operation==2 and address==0x30000008:
                for owner in ("telemetry","housekeeping"):
                    force(top+f".ca_child_{owner}_grant_bridge.state",2,2)
        check()

    plan(1, 0x30000004, True)
    for value in walk(32):
        held("control", "memory.data", value); check()
    held("control", "memory.error", 1); check()
    plan(1, 0x10000000)
    plan(1, 0x20000000)
    plan(2, 0x30000008, True)
    # CPU permission is immutable reservation role plus native ownership and
    # application eligibility. Exercise every source combination, including
    # Click's arm identity, without forcing the permit or ownership XOR.
    permission=program_permission_sources(manifest,scopes,header)
    extra.append(header)
    if top=='ClickSoc':
        extra.append(f"release {permission['reserved_guard']};\nrelease {permission['owned']};\n")
    for reserved in (0,1):
        for loader in (0,1):
            for eligible in (0,1):
                force(permission['reserved'],1,reserved,primitive=True)
                force(permission['loader'],1,loader,primitive=True)
                force(permission['eligibility'],1,eligible,primitive=True)
                if top=='ClickSoc':
                    for retired in (0,1):
                        for armed in range(4):
                            force(permission['retired'],1,retired,primitive=True)
                            force(permission['armed'],2,armed,primitive=True);check(33000001)
                else:check()
    # The capture receipt accepts only a pending synchronized request while
    # the access owns a word. Generic independent bit walks cannot combine
    # those source states with released reset. Exercise the complete three-bit
    # truth table, including both Click phase directions and BD return-to-zero.
    # Coherent return stages also expose effectsDrained/full busy/admission;
    # none of those derived signals, or the receipt acceptance, is forced.
    for bank in ('ram','program'):
        access=top+'.ca_child_'+bank+'_access';receipt=access+'.ca_child_capture_receipt'
        extra.append(header);force(top+'.gate_enabled',1,1)
        for group in ('returned_stages','bytesReturned_stages','bytesReturned_stages_1',
                      'bytesReturned_stages_2','bytesReturned_stages_3','ownerReturned_stages'):
            for stage in (0,1):force(access+f'.{group}_{stage}',1,1)
        for active in (0,1):
            for request_sync in (0,1):
                for phase in (0,1):
                    force(access+'.active',1,active);force(receipt+'.requestSync',1,request_sync)
                    force(receipt+'.phase',1,phase);check()
        # Native retained payload drives publication and the independent memory
        # input. No clocked reply or derived response endpoint is forced.
        extra.append(header)
        payload=native_return_cell(manifest,scopes,header,bank,'payload','ca_primitive_payload',
            'ChiselAsyncEventRegister_v1',dict(WIDTH='32',DELAY_FS='1000000',RESET_VALUE='0'),32)
        for value in walk(32):force(payload,32,value,primitive=True);check()
    for name, field in (("telemetry", "kind"), ("housekeeping", "cpuCompletion")):
        extra.append(header)
        force(top+f".fabric_{name}Outstanding", 1, 1)
        owner=next(c["contract"] for c in manifest["design"]["children"] if c["id"]==name+"_source")
        cell=next(p for p in owner["primitives"] if p["id"]=="eligibility")
        if cell["model"]!="ChiselAsyncEventRegister_v1" or cell["parameters"].get("WIDTH")!="1":
            raise ValueError("COMPLETION_PUBLICATION_ELIGIBILITY_OWNER")
        force(cell["rtl_path"]+".q",1,1,primitive=True)
        force(top+f".ca_child_{name}_reply_bridge.state", 2, 2)
        reply_values.clear()
        held(name, field, 1); check()
        if coordinated_reset(manifest):
            # Services now consumes the POR reservation mirror, not native
            # eligibility. Preserve the preceding native-owner scenario and
            # exercise every mirror/cancellation combination from actual
            # catalogued registers with the same retained CPU reply. Neither
            # the derived eligibility nor the completion endpoint is forced.
            inputs = [top+f".{name}Boundary_{n}" for n in
                      ("active", "revoked", "role", "pending")]
            inputs += [top+".resetBoundary_stopped", top+".cpuResetActive"]
            for value in range(1 << len(inputs)):
                for bit, path in enumerate(inputs):
                    force(path, 1, (value >> bit) & 1)
                check()
                # The fixture owns a CPU completion: it is deliverable only
                # while active, unrevoked, non-recovery and uncancelled.
                # This expectation comes from the driven source state, never
                # from DUT permission/role/valid or the native eligibility q.
                extra.append(f"if ({top}.ca_child_completion_{name}_bridge.in_valid !== 1'h{int(value == 1)}) "
                             f'$fatal(1,"COMPLETION_PUBLICATION_MIRROR:{name}:{value}");\n')
    count = checks+steps*len(coverage)
    position = coverage[0].start()
    result = source[:end]+prelude+source[end:position]+"".join(extra)+source[position:]
    return result.replace(marker, f"CONTRACT_PROBES_PASS:{count}"), count

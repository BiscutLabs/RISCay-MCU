# SPDX-License-Identifier: Apache-2.0
"""Elaborated raw-reset/native-status paths to periodic-clocked state.

Uses the pinned sv2v/Yosys frontend, before ABC or technology mapping. Native
storage remains typed, with taint propagated through every input/output. This is structural containment, not
metastability, bundled-data aperture, or physical reset qualification.
"""
from __future__ import annotations
from collections import defaultdict, deque
from itertools import product
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from gf180_estimate import ROOT, linux, sha, verify_hash
from reset_bridge_proof import Cone, prove_receiver, prove_phase_pair, prove_completion_idle, prove_sram_capture, sram_capacities
from reset_coordinator_proof import prove_coordinator, work_clock
from quiescing_receipt_proof import prove_masked_request
from quiescing_request_hold_proof import prove_request_hold

NATIVE_STATE = frozenset({
    "ChiselAsyncAsymmetricC_v1", "ChiselAsyncClosingLatch_v1",
    "ChiselAsyncEventRegister_v1", "ChiselAsyncPhaseRegister_v1",
    "ChiselAsyncCElement_v1", "ChiselAsyncLatch_v1",
})
NATIVE_COMB = frozenset({
    "ChiselAsyncControlGate_v1", "ChiselAsyncAnd_v1", "ChiselAsyncXor_v1",
})
NATIVE_PINS = {
    'ChiselAsyncAsymmetricC_v1': ('reset','common','rising','falling'),
    'ChiselAsyncClosingLatch_v1': ('reset','closed','d'),
    'ChiselAsyncEventRegister_v1': ('reset','trigger','d'),
    'ChiselAsyncPhaseRegister_v1': ('reset','trigger'),
    'ChiselAsyncCElement_v1': ('reset','a','b'),
    'ChiselAsyncLatch_v1': ('reset','enable','d'),
    'ChiselAsyncControlGate_v1': ('reset','a','b'),
    'ChiselAsyncAnd_v1': ('reset','d'),
    'ChiselAsyncXor_v1': ('reset','a','b'),
}
COMB = frozenset("$mux $pmux $and $or $not $xor $xnor $add $sub $mul $div $mod "
    "$eq $ne $eqx $nex $lt $le $gt $ge $logic_not $logic_and $logic_or "
    "$shiftx $shift $shl $shr $sshl $sshr $reduce_and $reduce_or $reduce_xor "
    "$reduce_xnor $reduce_bool $concat $slice $neg $pos".split())
SRAM = "gf180mcu_ocd_ip_sram__sram1024x8m8wm1"
STATUS = ("recoveryDebt", "eligible", "ownerRecovery", "recoveryReturning",
          "ownerLoader", "cpuPresentationPermit")
FIXTURE_TOPS = ('BdResetBoundarySocFixture', 'ClickResetBoundarySocFixture')
SOC_TOPS = ('FourPhaseSoc', 'ClickSoc') + FIXTURE_TOPS
CLICK_TOPS = ('ClickSoc', 'ClickResetBoundarySocFixture')


def propagation_graph(cells, model, held_data_inputs=()):
    """Rebuild by cell/input arc, preserving parallel unapproved paths.

Only the caller's successfully proved request-mask B ports may be handed off.
No native cell, output net, select pin or periodic destination is exempted.
"""
    omitted = set()
    for item in held_data_inputs:
        name=item['cell'];cell=cells.get(name,{});pins=cell.get('connections',{})
        if (item.get('input_pin')!='B' or item.get('output_pin')!='Y' or
            cell.get('type')!='$mux' or set(pins)!={'A','B','S','Y'} or
            pins['A']!=['0']*len(item['input_bits']) or pins['B']!=item['input_bits'] or
            pins['Y']!=item['output_bits'] or pins['S']!=item['select_bits'] or
            len(pins['B'])!=len(pins['Y']) or len(pins['S'])!=1 or name in omitted):
            raise ValueError('RDC_HELD_DATA_HANDOFF_SHAPE')
        omitted.add(name)
    graph=defaultdict(set)
    for name,cell in cells.items():
        if cell['type'] in ('$adff','$dff') or model(cell)==SRAM: continue
        outputs={b for p,v in cell['connections'].items()
                 if cell['port_directions'][p]=='output' for b in v if isinstance(b,int)}
        for pin,vector in cell['connections'].items():
            if cell['port_directions'][pin]!='input' or (name in omitted and pin=='B'): continue
            for bit in vector:
                if isinstance(bit,int): graph[bit].update(outputs)
    return graph


def reachable(graph, start):
    found=set(start);queue=deque(start)
    while queue:
        bit=queue.popleft()
        for target in graph.get(bit,set())-found:
            found.add(target);queue.append(target)
    return found


def prove_handoff_destinations(cells, model, held_data_inputs, clocks=(), por_reset=None):
    """A held combinational bus may end only at periodic data inputs.

The source/receipt proofs do not establish a downstream native owner's hold
contract, a clock/reset waveform, or a macro access contract. Reject such
routes before applying any B-port handoff, even if their outputs later reach D.
"""
    users=defaultdict(set)
    for name,cell in cells.items():
        for pin,vector in cell['connections'].items():
            if cell['port_directions'][pin]=='input':
                for bit in vector:
                    if isinstance(bit,int): users[bit].add((name,pin))
    queue=deque(b for item in held_data_inputs for b in item['output_bits'])
    seen=set(queue);sinks=set()
    while queue:
        bit=queue.popleft()
        for name,pin in sorted(users[bit]):
            cell=cells[name];kind=model(cell)
            if cell['type'] in ('$adff','$dff'):
                if pin!='D': raise ValueError('RDC_HELD_DATA_DESTINATION_'+name+'_'+pin)
                sinks.add((name,pin));continue
            if cell['type'] not in COMB and kind not in NATIVE_COMB:
                raise ValueError('RDC_HELD_DATA_DESTINATION_'+name+'_'+pin)
            for output,vector in cell['connections'].items():
                if cell['port_directions'][output]=='output':
                    for target in vector:
                        if isinstance(target,int) and target not in seen:
                            seen.add(target);queue.append(target)
    resetless=[]
    for name,_ in sorted(sinks):
        cell=cells[name];pins=cell['connections'];parameters=cell.get('parameters',{})
        if pins.get('CLK') not in clocks or parameters.get('CLK_POLARITY')!='1':
            raise ValueError('RDC_HELD_DATA_CLOCK_'+name)
        if cell['type']=='$dff' and set(pins)=={'D','Q','CLK'}:
            # Existing payload storage can intentionally have no reset. Its
            # data handoff does not waive a reset/control pin: none exists.
            resetless.append(name)
        elif (cell['type']!='$adff' or set(pins)!={'D','Q','CLK','ARST'} or
              parameters.get('ARST_POLARITY')!='1' or por_reset is None or
              not por_reset(pins.get('ARST',[]),pins['CLK'])):
            raise ValueError('RDC_HELD_DATA_RESET_'+name)
    return dict(status='pass',periodic_data_sinks=[list(s) for s in sorted(sinks)],
                traversed_bits=len(seen),positive_clocks=list(clocks),resetless_data_sinks=resetless,
                contract='combinational paths to service/work positive-edge D; POR or explicit resetless data storage')


def destination_cone(pin, uncut, handed_off, fixed_macro=False):
    """No held-data discharge at clocks, resets, controls or any macro pin."""
    return handed_off if pin=='D' and not fixed_macro else uncut


def fixture_ports(module, top):
    """Only the exact existing reset-boundary fixture ABI gets full SoC proof."""
    if top not in FIXTURE_TOPS:
        raise ValueError('RDC_FIXTURE_IDENTITY')
    inputs = {n: 1 for n in ('reset','serviceClock','watchdogClock','scl','sda','adcMiso',
                             'applicationReset','stopWorkClock','holdRamDecision')}
    inputs['gpioIn'] = 32
    outputs = {n: 1 for n in ('sdaLow','adcCsN','adcSclk','programmed','locked','systemReset',
        'resetReason','sleeping','serviceClockEnable','traceEvent','commit_valid','receivingClock',
        'boundaryClosed','boundaryRebased','boundaryRebaseIdle','ingressRebased','rebasing','coreResetHeld',
        'wakeDemand','cutoff','islandReset','ingressClosed','serviceClosed','rawRequest','rawAck','offered',
        'accepted','wordAccepted','ramBusy','ramGrantWaiting','nativeTraceEvent')}
    outputs.update(gpioOut=32,gpioOe=32,sleepEntries=32,mode=3,workClosedAcks=4,workRebaseAcks=4)
    for prefix in ('trace_', 'nativeTrace_'):
        outputs.update({prefix+n:w for n,w in dict(valid=1,pc=32,instruction=32,rd=4,data=32,
                                                   writeRegister=1,trap=1,cause=4).items()})
    for prefix in ('commit_bits_', 'rawPayload_', 'captured_'):
        outputs.update({prefix+n:w for n,w in dict(operation=2,address=32,data=32,mask=4).items()})
    expected={n:('input',w) for n,w in inputs.items()} | {n:('output',w) for n,w in outputs.items()}
    actual={n:(p['direction'],len(p['bits'])) for n,p in module['ports'].items()}
    if actual != expected:
        raise ValueError('RDC_FIXTURE_EXACT_PORTS')
    for name,port in module['ports'].items():
        if module['netnames'].get(name,{}).get('bits') != port['bits']:
            raise ValueError('RDC_FIXTURE_PORT_ALIAS_'+name)


def prove_reset_origin(cone, origin, fixture=False):
    """Preserve production POR|watchdog; add only the fixture's actual input."""
    for por, expired, requested in product(range(2), range(2), range(2) if fixture else (0,)):
        env={};cone.bind(env,cone.bits('reset'),por);cone.bind(env,cone.bits('watchdog_'),expired)
        if fixture: cone.bind(env,cone.bits('applicationReset'),requested)
        if cone.evaluate(origin,env) != bool(por or expired or requested):
            raise ValueError('RDC_RAW_RESET_ORIGIN')


def prepare_graph(export: Path, output: Path, manifest: dict) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / "tools/gf180-estimate-inputs.json").read_text())
    runtime = ROOT / ".tools/physical"
    tools = {"sv2v": runtime / "sv2v", "yosys": runtime / "root/usr/bin/yosys"}
    for name, path in tools.items():
        verify_hash(path, lock["tools"][name]["sha256"])
    sram_lock = json.loads((ROOT / "soc/sram-lock.json").read_text())
    sram = ROOT / "soc/src/main/resources/riscay/sram" / (SRAM + ".blackbox.v")
    verify_hash(sram, sram_lock["assets"][sram.name]["sha256"])
    inputs = {}
    files = []
    names = set()
    for name in (export / "filelist.f").read_text().splitlines():
        if not name.strip():
            continue
        source = (export / name.strip()).resolve()
        if not source.is_relative_to(export.resolve()) or source.name in names:
            raise ValueError("RDC_SOURCE_INVENTORY")
        names.add(source.name)
        text = source.read_text()
        inputs[name] = sha(source)
        if source.name.startswith("ChiselAsync"):
            start = text.index("module ")
            end = text.index(");", start) + 2
            text = "(* blackbox *)\n" + text[start:end] + "\nendmodule\n"
            text = text.replace("parameter time", "parameter [63:0]")
            text = text.replace("parameter longint unsigned", "parameter [63:0]")
            text = text.replace("parameter bit", "parameter")
        elif source.name == SRAM + ".sv":
            text = sram.read_text()
        target = output / source.name
        target.write_text(text)
        files.append(target)
    commands = [["wsl", "-e", linux(tools["sv2v"]), "-DSYNTHESIS", *map(linux, files)]]
    with (output / "converted.v").open("w") as out, (output / "sv2v.log").open("w") as err:
        subprocess.run(commands[0], stdout=out, stderr=err, check=True, timeout=120)
    top = manifest["top"]
    script = (f'read_verilog -sv {linux(output / "converted.v")}\n'
              f'hierarchy -check -top {top}\nproc\nflatten\nopt_clean\n'
              f'write_json {linux(output / "netlist.json")}\n')
    (output / "graph.ys").write_text(script)
    commands.append(["wsl", "-e", linux(tools["yosys"]), "-s", linux(output / "graph.ys")])
    result = subprocess.run(commands[1], capture_output=True, text=True, timeout=120)
    (output / "yosys.log").write_text(result.stdout + result.stderr)
    result.check_returncode()
    return dict(top=top, sources=inputs, filelist_sha256=sha(export / "filelist.f"),
        contract_sha256=sha(export / "contract.json"), sram_blackbox_sha256=sha(sram),
        tools={k: dict(path=str(v), sha256=sha(v), version=lock["tools"][k]["version"]) for k, v in tools.items()},
        commands=commands, script_sha256=sha(output / "graph.ys"),
        converted_sha256=sha(output / "converted.v"), netlist_sha256=sha(output / "netlist.json"))


def audit_graph(database: dict, top: str, capacities: dict | None = None) -> dict:
    modules = database["modules"]
    module = modules[top]
    if top in FIXTURE_TOPS: fixture_ports(module, top)
    cells, nets = module["cells"], module["netnames"]
    def model(cell):
        kind = cell["type"]
        return modules.get(kind, {}).get("attributes", {}).get("hdlname", kind).split()[0]
    def bits(name):
        if name not in nets:
            raise ValueError("RDC_MISSING_NET_" + name)
        return nets[name]["bits"]
    sequential = {n: c for n, c in cells.items() if c["type"] in ("$adff", "$dff")}
    fanout = defaultdict(set)
    for name, port in module.get("ports", {}).items():
        if port["direction"] == "output":
            for bit in port["bits"]:
                fanout[bit].add(("$top-output", name))
    for name, cell in cells.items():
        if set(cell["connections"]) != set(cell["port_directions"]):
            raise ValueError("RDC_UNCLASSIFIED_PIN_" + name)
        for pin, vector in cell["connections"].items():
            if cell["port_directions"][pin] == "input":
                for bit in vector:
                    if isinstance(bit, int):
                        fanout[bit].add((name, pin))
        kind = model(cell)
        if any(d not in ('input','output') for d in cell['port_directions'].values()):
            raise ValueError('RDC_UNCLASSIFIED_PIN_DIRECTION_'+name)
        if kind in NATIVE_STATE | NATIVE_COMB:
            expected={p:'input' for p in NATIVE_PINS.get(kind,())};expected['q']='output'
            if cell['port_directions'] != expected:
                raise ValueError('RDC_NATIVE_PIN_SCHEMA_'+name)
        if name in sequential or kind == SRAM:
            continue
        if cell["type"] not in COMB and kind not in NATIVE_COMB | NATIVE_STATE:
            raise ValueError("RDC_UNCLASSIFIED_CELL_" + kind)
    graph=propagation_graph(cells,model)
    def reach(start):
        return reachable(graph,start)
    por = set(bits("reset"))
    q_drivers = defaultdict(list)
    for name, cell in sequential.items():
        for bit in cell["connections"]["Q"]:
            q_drivers[bit].append((name, cell))
    def por_reset(vector, clock):
        if set(vector) == por:
            return True
        # Exact library two-edge POR release chain, both flops asynchronously
        # set by external POR. No reset generated from arbitrary POR state.
        for index in range(2):
            if len(vector) != 1 or len(q_drivers[vector[0]]) != 1:
                return False
            _, cell = q_drivers[vector[0]][0]
            pins = cell["connections"]
            if (cell["type"] != "$adff" or set(pins["ARST"]) != por or pins["CLK"] != clock or
                int(cell["parameters"]["ARST_VALUE"], 2) != 1 or
                int(cell["parameters"]["ARST_POLARITY"], 2) != 1 or
                int(cell["parameters"]["CLK_POLARITY"], 2) != 1):
                return False
            vector = pins["D"]
        return vector == ["0"]
    if top in SOC_TOPS:
        cone=Cone(module)
        _,hold=cone.flop('release_0');pins=hold['connections']
        if (pins['CLK'] != bits('serviceClock') or len(pins['Q']) != 8 or
            pins['D'] != ['0']+pins['Q'][:-1] or
            hold['parameters']['CLK_POLARITY'] != '1' or hold['parameters']['ARST_POLARITY'] != '1' or
            int(hold['parameters']['ARST_VALUE'],2) != 255):
            raise ValueError('RDC_RAW_RESET_HOLD')
        prove_reset_origin(cone, pins['ARST'], top in FIXTURE_TOPS)
        for requested in (0,1):
            for held in range(256):
                env={};cone.bind(env,pins['ARST'],requested);cone.bind(env,pins['Q'],held)
                if cone.evaluate(bits('systemReset'),env) != bool(requested or held):
                    raise ValueError('RDC_RAW_RESET_QUALIFICATION')
        raw_origins=pins['ARST']+bits('systemReset')
        raw=reach(raw_origins)
        # Retained producers are POR-owned down to their actual primitive pins.
        # The two presentation islands have distinct coordinated lifetimes.
        reset_checks=set()
        for name,cell in cells.items():
            if model(cell) not in NATIVE_STATE | NATIVE_COMB: continue
            expected=None
            if name.startswith('ca_child_core.'): expected='core'
            elif name.startswith(('ca_child_transactions.','ca_child_admission.','ca_child_completion.')): expected='native'
            elif name.startswith(('ca_child_program_access.ca_child_native.','ca_child_ram_access.ca_child_native.')): expected='por'
            elif name.startswith(tuple('ca_child_'+owner+'_source.' for owner in ('program','ram','telemetry','housekeeping'))):
                expected='por'
                if name in {'ca_child_'+owner+'_source.ca_primitive_eligibility'
                            for owner in ('program','ram','telemetry','housekeeping')}:
                    expected='native'
                elif name in {'ca_child_'+owner+'_source.ca_primitive_debt_storage'
                              for owner in ('telemetry','housekeeping')}:
                    expected='debt'
            if expected is None: continue
            key=(tuple(cell['connections']['reset']),expected)
            if key in reset_checks: continue
            native_hold=bits('resetBoundary_nativeHeld')
            core_hold=bits('resetBoundary_coreHeld')
            for values in range(32):
                p,n,c,r,cut=[(values>>i)&1 for i in range(5)]
                env={}
                for vector,value in ((bits('reset'),p),(native_hold,n),(core_hold,c),
                                     (bits('systemReset'),r),(bits('ca_child_request_bridge.close'),cut)):
                    cone.bind(env,vector,value)
                want={'por':p,'native':p or n,'core':p or c,'debt':p or r or cut}[expected]
                if cone.evaluate(cell['connections']['reset'],env) != want:
                    raise ValueError('RDC_NATIVE_RESET_OWNER_'+name)
            reset_checks.add(key)
    else:
        raw_origins=bits("applicationResetRequest") + bits("systemReset")
        raw = reach(raw_origins)
    # Keep the uncut closure for reset ownership. Final crossing traversal must
    # start from the original roots, not resume beyond a proved data handoff.
    seeds = {"raw-reset": set(raw_origins)}
    reset_owner_violations=[]
    for name, cell in sequential.items():
        if raw.intersection(cell["connections"].get("ARST", [])):
            seeds["raw-Q:" + name] = set(cell["connections"]["Q"])
            if top in SOC_TOPS and cell['connections']['Q'] != bits('release_0'):
                reset_owner_violations.append(dict(source='raw-reset',sink=name,pin='ARST',kind='unexpected raw-reset register'))
    for name, cell in cells.items():
        if model(cell) in NATIVE_STATE and raw.intersection(cell["connections"].get("reset", [])):
            seeds["raw-native-Q:" + name] = {b for p, v in cell["connections"].items() if cell["port_directions"][p] == "output" for b in v}
            allowed={'ca_child_'+owner+'_source.ca_primitive_debt_storage' for owner in ('telemetry','housekeeping')}
            if top in SOC_TOPS and name not in allowed:
                reset_owner_violations.append(dict(source='raw-reset',sink=name,pin='reset',kind='unexpected raw-reset native storage'))
    for name, net in nets.items():
        if not name.startswith("$") and name.endswith(tuple("." + s for s in STATUS)):
            seeds["native:" + name] = set(net["bits"])
    if top in SOC_TOPS:
        # Required production aliases. ownerRecovery is optimized into the
        # reservation/grant payload; a suffix-only search silently missed it.
        for owner in ('telemetry','housekeeping'):
            for status in ('recoveryDebt','grant_bits_recovery','recoveryReturning'):
                name='ca_child_'+owner+'_source.'+status
                seeds['native:'+name]=set(bits(name))
            name='ca_child_'+owner+'_source.ca_primitive_eligibility'
            cell=cells.get(name)
            if not cell or model(cell) != 'ChiselAsyncEventRegister_v1':
                raise ValueError('RDC_REQUIRED_ELIGIBILITY_SOURCE_'+name)
            seeds['native:'+name+'.q']=set(cell['connections']['q'])
        for owner in ('ram','program'):
            for boundary in ('source','return'):
                name='ca_child_'+owner+'_'+boundary+'.eligible'
                seeds['native:'+name]=set(bits(name))
        for status in ('ownerLoader','cpuPresentationPermit'):
            name='ca_child_program_source.'+status
            seeds['native:'+name]=set(bits(name))
    synchronizers = {}
    for name, cell in sequential.items():
        pins = cell["connections"]
        q = pins["Q"]
        if len(q) != 1 or cell["type"] != "$adff" or not por_reset(pins['ARST'],pins['CLK']):
            continue
        users = fanout[q[0]]
        if len(users) != 1:
            continue
        second, pin = next(iter(users))
        after = sequential.get(second)
        if not after or pin != "D" or after["type"] != "$adff":
            continue
        pins2 = after["connections"]
        if (pins2["CLK"] == pins["CLK"] and pins2["ARST"] == pins['ARST'] and pins2["D"] == q and
            cell["parameters"]["CLK_POLARITY"] == after["parameters"]["CLK_POLARITY"] == "1" and
            cell["parameters"]["ARST_POLARITY"] == after["parameters"]["ARST_POLARITY"] == "1"):
            synchronizers[name] = second
    receiver_proofs=[]
    payload_exemptions={}
    held_data_inputs=[]
    if top in SOC_TOPS:
        receiver_proofs.append(prove_coordinator(module,por_reset))
        # These are the documented native held-bus boundaries reached by the
        # raw/status cones. No control, reset, clock or other register is waived.
        receivers=['ca_child_'+n+'_grant_bridge' for n in ('program','telemetry','housekeeping')]
        receivers += ['ca_child_'+n+'_access.ca_child_byte_request_'+str(i)
                      for n in ('program','ram') for i in range(4)]
        quiescing=['ca_child_request_bridge','ca_child_admission_grant_bridge']
        receivers += quiescing
        for prefix in receivers:
            proof=prove_receiver(module,prefix,top in CLICK_TOPS,prefix in quiescing,por_reset,fanout)
            if prefix == 'ca_child_request_bridge':
                receiver_proofs.append(prove_request_hold(database,top,capacities))
                masked=prove_masked_request(database,top,proof)
                receiver_proofs.append(masked)
                held_data_inputs.extend(masked['held_data_inputs'])
                proof['payload_fields']=masked['payload_fields']
                producer='ca_child_transactions.serviceRequest'
            elif prefix == 'ca_child_admission_grant_bridge': producer='ca_child_admission.grant'
            elif '.ca_child_byte_request_' in prefix:
                access,index=prefix.split('.ca_child_byte_request_')
                producer=access+'.ca_child_native.byteRequest_'+index
            else:
                producer=prefix.removesuffix('_grant_bridge')+'_source.grant'
            for field in ['_req','_ack']+['_bits'+s for s in proof['payload_fields']]:
                if bits(prefix+'.in'+field) != bits(producer+field):
                    raise ValueError('RDC_HELD_SOURCE_BINDING_'+prefix+field)
            proof['producer']=producer
            receiver_proofs.append(proof)
            payload_exemptions.update({sink:proof for sink in proof['payload']})
            synchronizers[proof['first']]=proof['second']
        if capacities is None or set(capacities) != {'program', 'ram'}:
            raise ValueError('RDC_SRAM_MISSING_CAPACITIES')
        for bank in ('program', 'ram'):
            proof = prove_sram_capture(module, bank, por_reset, capacities[bank])
            receiver_proofs.append(proof)
            payload_exemptions.update({sink: proof for sink in proof['payload']})
        for part in ('plan','telemetry','housekeeping'):
            proof=prove_phase_pair(module,'ca_child_completion_'+part+'_bridge',por_reset,fanout)
            receiver_proofs.append(proof)
            synchronizers[proof['first']]=proof['second']
        proof=prove_completion_idle(module,top in CLICK_TOPS,por_reset,fanout)
        receiver_proofs.append(proof)
        synchronizers[proof['first']]=proof['second']
    crossing_graph=propagation_graph(cells,model,held_data_inputs)
    handoff_clocks=[bits('serviceClock'),work_clock(Cone(module))] if held_data_inputs else []
    handoff_destinations=prove_handoff_destinations(cells,model,held_data_inputs,handoff_clocks,por_reset)
    crossings, violations, exemptions, discharged = [], reset_owner_violations, [], []
    for source, start in seeds.items():
        uncut=reach(start)
        cone = reachable(crossing_graph,start)
        for name, cell in sequential.items():
            pins = cell["connections"]
            for pin, vector in pins.items():
                pin_cone=destination_cone(pin,uncut,cone)
                if (pin=='D' and uncut.intersection(vector) and not pin_cone.intersection(vector)
                    and name not in synchronizers and name not in payload_exemptions
                    and not raw.intersection(pins.get('ARST',[]))):
                    discharged.append(dict(source=source,sink=name,pin=pin,
                        contract='proved retained CPU request mask data handoff'))
                if pin == "Q" or not pin_cone.intersection(vector):
                    continue
                if pin == "D" and name in synchronizers:
                    crossings.append(dict(source=source, first=name, second=synchronizers[name]))
                    continue
                # These registers are raw-reset sources, not POR destinations.
                # Their Q is independently seeded above; it is never waived.
                if raw.intersection(pins.get("ARST", [])):
                    continue
                if pin == 'D' and name in payload_exemptions:
                    exemptions.append(dict(source=source, sink=name, pin=pin,
                        contract=payload_exemptions[name]['contract'],
                        proof=payload_exemptions[name]['prefix']))
                    continue
                violations.append(dict(source=source, sink=name, pin=pin))
        for name,cell in cells.items():
            if model(cell)!=SRAM: continue
            for pin,vector in cell['connections'].items():
                if (cell['port_directions'][pin]=='input' and
                    destination_cone(pin,uncut,cone,fixed_macro=True).intersection(vector)):
                    violations.append(dict(source=source,sink=name,pin=pin,kind='fixed SRAM macro input'))
    report = dict(status="fail" if violations else "pass", scope="structural containment only",
        seeds=sorted(seeds), synchronizers=synchronizers, crossings=crossings,
        exemptions=exemptions, receiver_proofs=receiver_proofs, violations=violations,
        held_data_handoffs=held_data_inputs, held_data_discharged=discharged,
        held_data_destinations=handoff_destinations)
    return report


def check_reset_crossings(export: Path, manifest: dict) -> dict:
    output = export / "reset-crossings"
    inputs = prepare_graph(export, output, manifest)
    inventory_path = export / "sram.json"
    capacities = sram_capacities(json.loads(inventory_path.read_text()), manifest["top"])
    inputs["sram_inventory_sha256"] = sha(inventory_path)
    inputs["sram_capacities"] = capacities
    result = audit_graph(json.loads((output / "netlist.json").read_text()), manifest["top"], capacities)
    result["inputs"] = inputs
    (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    if result["violations"]:
        raise ValueError("UNSYNCHRONIZED_RESET_CROSSING: " + json.dumps(result["violations"][:5]))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.export / "contract.json").read_text())["manifest"]
    print(json.dumps(check_reset_crossings(args.export, manifest), indent=2))

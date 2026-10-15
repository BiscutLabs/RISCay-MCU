# SPDX-License-Identifier: Apache-2.0
"""Elaborated raw-reset/native-status paths to periodic-clocked state.

Uses the pinned sv2v/Yosys frontend, before ABC or technology mapping. Native
storage remains typed, with taint propagated through every input/output. This is structural containment, not
metastability, bundled-data aperture, or physical reset qualification.
"""
from __future__ import annotations
from collections import defaultdict, deque
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from gf180_estimate import ROOT, linux, sha, verify_hash
from reset_bridge_proof import Cone, prove_receiver, prove_phase_pair, prove_completion_idle, prove_sram_capture, sram_capacities
from reset_coordinator_proof import prove_coordinator

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
    cells, nets = module["cells"], module["netnames"]
    def model(cell):
        kind = cell["type"]
        return modules.get(kind, {}).get("attributes", {}).get("hdlname", kind).split()[0]
    def bits(name):
        if name not in nets:
            raise ValueError("RDC_MISSING_NET_" + name)
        return nets[name]["bits"]
    sequential = {n: c for n, c in cells.items() if c["type"] in ("$adff", "$dff")}
    fanout, graph = defaultdict(set), defaultdict(set)
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
        inputs = {b for p, v in cell["connections"].items() if cell["port_directions"][p] == "input" for b in v if isinstance(b, int)}
        outputs = {b for p, v in cell["connections"].items() if cell["port_directions"][p] == "output" for b in v if isinstance(b, int)}
        for bit in inputs:
            graph[bit].update(outputs)
    def reach(start):
        found = set(start)
        queue = deque(start)
        while queue:
            bit = queue.popleft()
            for target in graph[bit] - found:
                found.add(target)
                queue.append(target)
        return found
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
    if top in ('FourPhaseSoc','ClickSoc'):
        cone=Cone(module)
        _,hold=cone.flop('release_0');pins=hold['connections']
        if (pins['CLK'] != bits('serviceClock') or len(pins['Q']) != 8 or
            pins['D'] != ['0']+pins['Q'][:-1] or
            hold['parameters']['CLK_POLARITY'] != '1' or hold['parameters']['ARST_POLARITY'] != '1' or
            int(hold['parameters']['ARST_VALUE'],2) != 255):
            raise ValueError('RDC_RAW_RESET_HOLD')
        for por_value in (0,1):
            for expired in (0,1):
                env={};cone.bind(env,bits('reset'),por_value);cone.bind(env,bits('watchdog_'),expired)
                if cone.evaluate(pins['ARST'],env) != (por_value or expired):
                    raise ValueError('RDC_RAW_RESET_ORIGIN')
        for requested in (0,1):
            for held in range(256):
                env={};cone.bind(env,pins['ARST'],requested);cone.bind(env,pins['Q'],held)
                if cone.evaluate(bits('systemReset'),env) != bool(requested or held):
                    raise ValueError('RDC_RAW_RESET_QUALIFICATION')
        raw=reach(pins['ARST']+bits('systemReset'))
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
        raw = reach(bits("applicationResetRequest") + bits("systemReset"))
    seeds = {"raw-reset": raw}
    reset_owner_violations=[]
    for name, cell in sequential.items():
        if raw.intersection(cell["connections"].get("ARST", [])):
            seeds["raw-Q:" + name] = set(cell["connections"]["Q"])
            if top in ('FourPhaseSoc','ClickSoc') and cell['connections']['Q'] != bits('release_0'):
                reset_owner_violations.append(dict(source='raw-reset',sink=name,pin='ARST',kind='unexpected raw-reset register'))
    for name, cell in cells.items():
        if model(cell) in NATIVE_STATE and raw.intersection(cell["connections"].get("reset", [])):
            seeds["raw-native-Q:" + name] = {b for p, v in cell["connections"].items() if cell["port_directions"][p] == "output" for b in v}
            allowed={'ca_child_'+owner+'_source.ca_primitive_debt_storage' for owner in ('telemetry','housekeeping')}
            if top in ('FourPhaseSoc','ClickSoc') and name not in allowed:
                reset_owner_violations.append(dict(source='raw-reset',sink=name,pin='reset',kind='unexpected raw-reset native storage'))
    for name, net in nets.items():
        if not name.startswith("$") and name.endswith(tuple("." + s for s in STATUS)):
            seeds["native:" + name] = set(net["bits"])
    if top in ('FourPhaseSoc','ClickSoc'):
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
    if top in ('FourPhaseSoc','ClickSoc'):
        receiver_proofs.append(prove_coordinator(module,por_reset))
        # These are the documented native held-bus boundaries reached by the
        # raw/status cones. No control, reset, clock or other register is waived.
        receivers=['ca_child_'+n+'_grant_bridge' for n in ('program','telemetry','housekeeping')]
        receivers += ['ca_child_'+n+'_access.ca_child_byte_request_'+str(i)
                      for n in ('program','ram') for i in range(4)]
        quiescing=['ca_child_request_bridge','ca_child_admission_grant_bridge']
        receivers += quiescing
        for prefix in receivers:
            proof=prove_receiver(module,prefix,top=='ClickSoc',prefix in quiescing,por_reset,fanout)
            if prefix == 'ca_child_request_bridge': producer='ca_child_transactions.serviceRequest'
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
        proof=prove_completion_idle(module,top=='ClickSoc',por_reset,fanout)
        receiver_proofs.append(proof)
        synchronizers[proof['first']]=proof['second']
    crossings, violations, exemptions = [], reset_owner_violations, []
    for source, start in seeds.items():
        cone = reach(start)
        for name, cell in sequential.items():
            pins = cell["connections"]
            for pin, vector in pins.items():
                if pin == "Q" or not cone.intersection(vector):
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
                if cell['port_directions'][pin]=='input' and cone.intersection(vector):
                    violations.append(dict(source=source,sink=name,pin=pin,kind='fixed SRAM macro input'))
    report = dict(status="fail" if violations else "pass", scope="structural containment only",
        seeds=sorted(seeds), synchronizers=synchronizers, crossings=crossings,
        exemptions=exemptions, receiver_proofs=receiver_proofs, violations=violations)
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

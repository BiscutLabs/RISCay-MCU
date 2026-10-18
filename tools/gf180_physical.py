# SPDX-License-Identifier: Apache-2.0
"""Experimental physical binding. No behavioral delays enter implementation RTL.

The library ASIC exporter currently rejects the registered SRAM source and its
timing exporter rejects Click. This adapter inventories the SAME contract, checks
exact parameter tuples, and explicitly admits the pinned SRAM view. It never
reports timing closure: qualification requires the separate evidence checker.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from gf180_control_roles import CATALOGUE, CONTROL, DATA, resolve_roles

ROOT = Path(__file__).resolve().parents[1]
SC = "gf180mcu_fd_sc_mcu7t5v0__"
SRAM = "gf180mcu_ocd_ip_sram__sram1024x8m8wm1"
ATTR = '(* keep = 1, dont_touch = "yes" *) '

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def write_json(path, value):
    path.write_text(json.dumps(value,indent=2)+"\n")

def nodes(n):
    yield n
    for child in n["children"]:
        yield from nodes(child["contract"])

def key(p):
    return p["model"], tuple(sorted((k,int(v)) for k,v in p["parameters"].items()))

def passive(p):
    return p["view"] == "constraint-marker" or p["model"] == "ChiselAsyncProtocolGuard_v1"


def audit_alias_binding(binding, body):
    """Prove the complete physical view of the only supported cell-free model."""
    model=binding['model']
    if model!='ChiselAsyncPassiveDataAllowance_v1':
        if binding.get('aliases'): raise ValueError('UNSUPPORTED_PASSIVE_ALIAS_MODEL')
        return
    params=binding['parameters']
    if set(params)!={'WIDTH','DELAY_FS'} or params['WIDTH']<1 or params['DELAY_FS']<=0:
        raise ValueError('PASSIVE_ALIAS_PARAMETERS')
    width=params['WIDTH']
    if binding.get('cells')!=[] or body.get('cells',{}):
        raise ValueError('PASSIVE_ALIAS_HAS_CELLS')
    if binding.get('aliases')!=[[f'q[{i}]',f'a[{i}]'] for i in range(width)]:
        raise ValueError('PASSIVE_ALIAS_LAYOUT')
    ports=body['ports']
    if (set(ports)!={'a','q'} or ports['a']['direction']!='input' or
            ports['q']['direction']!='output' or len(ports['a']['bits'])!=width or
            len(ports['q']['bits'])!=width):
        raise ValueError('PASSIVE_ALIAS_PORTS')
    if ports['q']['bits']!=ports['a']['bits']:
        raise ValueError('PASSIVE_ALIAS_CONNECTION')

def legacy_inventory(export):
    """Read old comparison-baseline exports only; never the current design."""
    manifest = json.loads((export/"contract.json").read_text())["manifest"]
    ns = list(nodes(manifest["design"]))
    primitives = [p for n in ns for p in n["primitives"]]
    sources = [export/x.strip() for x in (export/"filelist.f").read_text().splitlines() if x.strip()]
    allowed = {n["module"]+".sv" for n in ns} | {p["model"]+".sv" for p in primitives} | {SRAM+".sv"}
    if any(p.name not in allowed or p.parent.resolve()!=export.resolve() for p in sources):
        raise ValueError("UNREGISTERED_SOURCE")
    # Detect an unregistered use of a registered primitive, including a reused module.
    models = {p["model"] for p in primitives}
    actual_modules={manifest["top"]:manifest["top"]}
    for n in ns:
        rtl = (export/(actual_modules[n["rtl_path"]]+".sv")).read_text()
        # firtool can deduplicate equal modules; follow the emitted instance,
        # rather than assuming the pre-deduplication metadata module exists.
        for child in n["children"]:
            path=child["contract"]["rtl_path"]
            match=re.search(r'\b(\w+)\s+'+re.escape(path.split('.')[-1])+r'\s*\(',rtl)
            if not match: raise ValueError("MISSING_ASYNC_CHILD_"+path)
            actual_modules[path]=match[1]
        observed = {(m,x) for m in models for x in re.findall(
            r'\b'+re.escape(m)+r'\s*(?:#\s*\(.*?\)\s*)?([\w$]+)\s*\(',rtl,re.S)}
        declared = {(p["model"],p["rtl_path"].split('.')[-1]) for p in n["primitives"]}
        if observed != declared: raise ValueError("UNREGISTERED_PRIMITIVE")
    groups = defaultdict(list)
    for p in primitives: groups[key(p)].append(p)
    for ps in groups.values():
        if any(p["ports"] != ps[0]["ports"] for p in ps): raise ValueError("INCONSISTENT_PORTS")
    return manifest, sources, groups


def inventory(export, *, comparison_baseline=False):
    if comparison_baseline:
        return legacy_inventory(export)
    from export_structure import validate, inside
    validate(export)  # Generation owns structural rules, including deduplication.
    manifest=json.loads((export/'contract.json').read_text())['manifest']
    sources=[inside(export,s.strip()) for s in (export/'filelist.f').read_text().splitlines() if s.strip()]
    groups=defaultdict(list)
    for node in nodes(manifest['design']):
        for primitive in node['primitives']:
            groups[key(primitive)].append(primitive)
    for group in groups.values():
        if any(p['ports'] != group[0]['ports'] for p in group):
            raise ValueError('INCONSISTENT_PORTS')
    return manifest,sources,groups

class Circuit:
    """Explicit standard-cell graph, also used to generate SPICE test circuits."""
    def __init__(self):
        self.cells = []
        self.aliases = []
        self.serial = 0
    def cell(self, kind, **pins):
        name = "u"+str(self.serial); self.serial += 1
        self.cells.append(dict(name=name,cell=SC+kind,pins=pins))
    def gate(self, kind, pins, output="Z"):
        net = "n"+str(self.serial)
        self.cell(kind,**pins,**{output:net})
        return net
    def inv(self, a): return self.gate("inv_1",dict(I=a),"ZN")
    def reduce(self, kind, values):
        if not values: return "1'b1" if kind=="and" else "1'b0"
        value = values[0]
        for other in values[1:]: value = self.gate(kind+"2_1",dict(A1=value,A2=other))
        return value
    def chain(self, a, count, q="q",kind="buf_1"):
        for i in range(count):
            out = q if i == count-1 else "n"+str(self.serial)
            self.cell(kind,I=a,Z=out); a=out
    def verilog(self, module, ports):
        declarations = [f'{p["direction"]} wire [{p["width"]-1}:0] {p["name"]}' for p in ports]
        nets = sorted({v for c in self.cells for v in c["pins"].values() if re.fullmatch(r'n\d+',v)})
        body = [f'(* keep_hierarchy = "yes" *) module {module} ('+", ".join(declarations)+");"]
        if nets: body.append(ATTR+"wire "+", ".join(nets)+";")
        body += [f'assign {sink} = {source};' for sink,source in self.aliases]
        body += [ATTR+c["cell"]+" "+c["name"]+" ("+", ".join(f'.{p}({v})' for p,v in c["pins"].items())+");" for c in self.cells]
        return "\n".join(body)+"\nendmodule\n"


def distribution_parents(circuit, roots, groups, fanout=16, trunk_kinds=None):
    """Equal-depth, bounded-fanout parents for interleaved final leaf buffers.

    Small trees retain their exact existing recipe and cell numbering. Wider
    trees add matching trunk levels to every branch; partial groups still need
    loaded skew, capture/ACK and reset characterization.
    """
    if not roots or groups<1 or fanout<2:raise ValueError('INVALID_DISTRIBUTION_TREE')
    trunk_kinds=tuple(trunk_kinds or ('buf_8',)*len(roots))
    if len(trunk_kinds)!=len(roots) or any(k not in ('buf_8','buf_12') for k in trunk_kinds):
        raise ValueError('INVALID_DISTRIBUTION_DRIVER')
    depth=0;capacity=fanout
    while groups>capacity:depth+=1;capacity*=fanout
    def descend(parents,count,level):
        if level==0:return [parents]*count
        branches=math.ceil(count/(fanout**level))
        sizes=[count//branches+(i<count%branches) for i in range(branches)]
        result=[]
        for size in sizes:
            child=tuple(circuit.gate(k,dict(I=p)) for p,k in zip(parents,trunk_kinds))
            result.extend(descend(child,size,level-1))
        return result
    return descend(tuple(roots),groups,depth),depth+1


def distribution_profile(cells, *, capture_root=None, data_reset=False, fanout=16):
    """Audit every input load and equal-depth capture/reset trees independently."""
    drivers={};loads=defaultdict(int)
    for cell in cells:
        for pin,net in cell['pins'].items():
            if pin in ('Z','ZN','Q'):
                if net in drivers:raise ValueError('DISTRIBUTION_MULTIPLE_DRIVERS')
                drivers[net]=cell
            else:loads[net]+=1
    if max(loads.values(),default=0)>fanout:raise ValueError('DISTRIBUTION_FANOUT')
    def depth(net,root,seen=()):
        if net==root:return (0,0)
        if net in seen or net not in drivers:raise ValueError('DISTRIBUTION_ROOT')
        cell=drivers[net]
        if not re.fullmatch(re.escape(SC)+r'(?:buf|inv)_\d+',cell['cell']):raise ValueError('DISTRIBUTION_NONBUFFER')
        levels,parity=depth(cell['pins']['I'],root,(*seen,net))
        return (1+levels,parity ^ int(cell['cell'].startswith(SC+'inv_')))
    captures=[c['pins'][p] for c in cells for p in ('CLK','E') if p in c['pins']]
    resets=([c['pins']['A2'] for c in cells if c['cell']==SC+'and2_1'] if data_reset else
            [c['pins'][p] for c in cells for p in ('RN','SETN') if p in c['pins']])
    depths={}
    for name,nets,root in (('capture',captures,capture_root),('reset',resets,'reset')):
        if not nets:continue
        paths={depth(n,root) for n in nets}
        expected_inversion=int(name=='reset' or capture_root=='closed')
        if any(parity!=expected_inversion for _,parity in paths):raise ValueError('DISTRIBUTION_POLARITY_'+name.upper())
        ds={levels for levels,_ in paths}
        if len(ds)!=1:raise ValueError('DISTRIBUTION_UNBALANCED_'+name.upper())
        depths[name+'_depth']=ds.pop()
    return dict(maximum_input_fanout=max(loads.values(),default=0),**depths)


def adapter(p, guard_min_ns, *, role=None, guard_stages=None):
    k=dict(key(p)[1]); model=p["model"].removeprefix("ChiselAsync").removesuffix("_v1")
    c=Circuit(); requirement={"control_max_ns":10}
    if guard_stages is not None and (model!='ControlGate' or role!=CONTROL or
            k.get('WIDTH')!=1 or k.get('OP')!=0 or k.get('RESET_VALUE')!=0 or
            k.get('DELAY_FS',0)<=1000000 or type(guard_stages) is not int or guard_stages<1):
        raise ValueError('INVALID_ORDERING_GUARD_OVERRIDE')
    # Long guards use GF180's DLYD cell (less area per guaranteed delay than
    # repeated BUFs). Counts derive from all pinned corners with extra stages.
    # Post-route slew/load and delay checks remain
    # mandatory; this is a conservative candidate, NOT a wire-delay model.
    def stages(ns): return max(1,math.ceil(1.2*ns/guard_min_ns))
    def normalize(port,count,mask):
        if count<0 or mask<0 or mask>=(1<<count): raise ValueError("INVALID_INPUT_BUBBLE_MASK")
        return [c.inv(f'{port}[{i}]') if (mask>>i)&1 else f'{port}[{i}]' for i in range(count)]
    if model=="AsymmetricC":
        if k["RESET_VALUE"]!=0 or k["COMMON"]<1: raise ValueError("UNSUPPORTED_C_RESET_OR_INPUTS")
        common=normalize("common",k["COMMON"],k["COMMON_INVERT"])
        rising=normalize("rising",k["RISING"],k["RISING_INVERT"])
        falling=normalize("falling",k["FALLING"],k["FALLING_INVERT"])
        set_net=c.reduce("and",common+rising)
        hold_net=c.reduce("or",common+falling)
        # Entire asymmetric equation in ONE preserved state keeper. Do not
        # replace it with a chain of binary C-elements (different protocol).
        c.cell("aoi21_1",A1="state",A2=hold_net,B=set_net,ZN="next_n")
        c.cell("nor2_1",A1="next_n",A2="reset",ZN="state")
        c.chain("state",9)
        requirement.update(feedback="aoi21/nor2 static keeper",feedback_max_ns=10,control_min_ns=1)
    elif model in ("And","Xor"):
        if model=="And": value=c.reduce("and",normalize("d",k["INPUTS"],k["INVERT"]))
        else: value=c.gate("xor2_1",dict(A1="a",A2="b"))
        value=c.gate("and2_1",dict(A1=value,A2=c.inv("reset")))
        c.chain(value,9); requirement["control_min_ns"]=1
    elif model=="PassiveDataAllowance":
        if set(k)!={"WIDTH","DELAY_FS"} or k["WIDTH"]<1 or k["DELAY_FS"]<=0:
            raise ValueError("INVALID_PASSIVE_ALLOWANCE_PARAMETERS")
        if role!=DATA: raise ValueError("PASSIVE_ALLOWANCE_REQUIRES_DATA_ROLE")
        ports={port["name"]:(port["direction"],port["width"]) for port in p["ports"]}
        if len(p["ports"])!=2 or ports!={"a":("input",k["WIDTH"]),"q":("output",k["WIDTH"])}:
            raise ValueError("INVALID_PASSIVE_ALLOWANCE_PORTS")
        c.aliases=[(f'q[{i}]',f'a[{i}]') for i in range(k["WIDTH"])]
        requirement=dict(role=DATA,implementation="passive-alias",invalid_data="unmasked",
                         model_allowance_fs=k["DELAY_FS"],
                         physical_obligation="real-source-to-capture-max-min-and-valid-qualified-fanout")
    elif model=="ControlGate":
        width=k["WIDTH"]; op=k["OP"]
        if role not in (DATA,CONTROL): raise ValueError("EXPLICIT_CONTROL_ROLE_REQUIRED")
        if width<1 or not 0<=k["RESET_VALUE"]<(1<<width) or k["DELAY_FS"]<=0:
            raise ValueError("INVALID_CONTROL_PARAMETERS")
        if not math.isfinite(guard_min_ns) or guard_min_ns<=0:
            raise ValueError("INVALID_GUARD_FLOOR")
        if op not in (0,1,2): raise ValueError("UNKNOWN_CONTROL_OPERATION")
        data=role==DATA
        if data and (op!=0 or k["RESET_VALUE"]!=0): raise ValueError("UNKNOWN_DATA_ALLOWANCE")
        requirement={"role":role,
                     "data_max_ns" if data else "control_min_ns":k["DELAY_FS"]/1e6}
        if guard_stages is not None:
            requirement=dict(role=role,model_delay_fs=k['DELAY_FS'],physical_stages=guard_stages,
                physical_obligation='same-corner-relative-ordering',engineering_derate=.2,residual_ns=2.)
        nr=c.inv("reset")
        reset_groups={}
        if data:
            reset_root=c.gate("buf_8",dict(I=nr))
            parents,levels=distribution_parents(c,(reset_root,),math.ceil(width/16))
            reset_groups={g:c.gate("buf_4",dict(I=parent[0])) for g,parent in enumerate(parents)}
            requirement.update(distribution_fanout_limit=16,reset_branch_levels=levels)
        for i in range(width):
            value=f'a[{i}]'
            if op==1: value=c.inv(value)
            if op==2: value=c.gate("or2_1",dict(A1=value,A2=f'b[{i}]'))
            value=c.gate("or2_1" if (k["RESET_VALUE"]>>i)&1 else "and2_1",
                dict(A1=value,A2="reset" if (k["RESET_VALUE"]>>i)&1 else reset_groups.get(i//16,nr)))
            long_guard=not data and k["DELAY_FS"]>1000000
            c.chain(value,guard_stages if guard_stages is not None else stages(k["DELAY_FS"]/1e6) if long_guard else 1 if data else 9,
                f'q[{i}]',kind="dlyd_1" if long_guard else "buf_1")
        if not data and k["DELAY_FS"]<=1000000: requirement["control_max_ns"]=10
    elif model in ("EventRegister","ClosingLatch","PhaseRegister"):
        width=k.get("WIDTH",1); nr=c.inv("reset")
        enable=c.inv("closed") if model=="ClosingLatch" else "trigger"
        # Small balanced local tree, including reset, avoids a single cell
        # driving hundreds of clock/reset pins. Bound every leaf after routing.
        # Wide event trees need more drive ahead of the unchanged final leaves.
        # Reset, ClosingLatch and PhaseRegister recipes retain their drivers.
        capture_driver='buf_12' if model=='EventRegister' and width>256 else 'buf_8'
        root=c.gate(capture_driver,dict(I=enable)); reset_root=c.gate("buf_8",dict(I=nr))
        clocks={}; resets={}
        parents,levels=distribution_parents(c,(root,reset_root),math.ceil(width/16),
                                           trunk_kinds=(capture_driver,'buf_8'))
        for group,(clock_parent,reset_parent) in enumerate(parents):
            clocks[group]=c.gate("buf_4",dict(I=clock_parent))
            resets[group]=c.gate("buf_4",dict(I=reset_parent))
        for i in range(width):
            q="state" if model=="PhaseRegister" else f'q[{i}]'
            d=c.inv("state") if model=="PhaseRegister" else f'd[{i}]'
            if model=="ClosingLatch": c.cell("latrnq_1",D=d,E=clocks[i//16],RN=resets[i//16],Q=q)
            elif (k.get("RESET_VALUE",0)>>i)&1: c.cell("dffsnq_1",D=d,CLK=clocks[i//16],SETN=resets[i//16],Q=q)
            else: c.cell("dffrnq_1",D=d,CLK=clocks[i//16],RN=resets[i//16],Q=q)
        requirement.update(storage_bits=width,clock_distribution_max_ns=4 if model=="ClosingLatch" else 2.5,
                           distribution_fanout_limit=16,capture_branch_levels=levels,reset_branch_levels=levels,
                           capture_leaf_spread='must-measure-both-edges-per-corner; not-qualified-by-fanout')
        if model=="PhaseRegister":
            c.chain("state",9); requirement["control_min_ns"]=1
    else: raise ValueError("UNSUPPORTED_ACTIVE_MODEL_"+model)
    if 'distribution_fanout_limit' in requirement:
        requirement['distribution_structure']=distribution_profile(c.cells,
            capture_root='closed' if model=='ClosingLatch' else 'trigger',data_reset=model=='ControlGate')
    return c,requirement

def pdk_verify(pdk):
    lock=json.loads((ROOT/"physical/gf180/pdk-lock.json").read_text())
    for name,digest in lock["files"].items():
        if sha(pdk/name)!=digest: raise ValueError("PDK_HASH_MISMATCH_"+name)
    return lock

def guard_floor(pdk):
    from gf180_estimate import groups
    minima=[]
    for lib in sorted(pdk.glob("*.lib")):
        body=dict(groups(lib.read_text(),"cell"))[SC+"dlyd_1"]
        for kind in ("cell_rise","cell_fall"):
            for _,table in groups(body,kind):
                slews=[float(x) for x in re.search(r'index_1\("([^"]+)"\)',table)[1].split(',')]
                values=re.search(r'values\s*\((.*?)\)\s*;',table,re.S)
                rows=re.findall(r'"([^"]+)"',values[1])
                # Include the next grid row above our 2 ns slew limit. Slow
                # unconstrained ramps have negative 50%-crossing delay and
                # cannot be used to infer a positive buffer-chain minimum.
                last=next(i for i,x in enumerate(slews) if x>=2.0)
                minima += [float(x) for row in rows[:last+1] for x in row.split(',')]
    value=min(minima)
    if value<=0: raise ValueError("INVALID_BUFFER_FLOOR")
    return value * 0.8 # additional headroom for the sub-20 ps input-slew boundary

def physical_policy(export, manifest, *, comparison_baseline=False):
    policy=json.loads((export/"physical-policy.json").read_text())
    if comparison_baseline:
        if (policy.get("schema") != "riscay-comparison-baseline-v1" or
            policy.get("source_commit") != "8637099bb603543b4d8e1d76de2bf165bbaa171a" or
            policy.get("application_reset") != "historical-raw-reset-without-R1-R2"):
            raise ValueError("UNSUPPORTED_COMPARISON_BASELINE")
    elif policy.get("schema") not in {"riscay-physical-policy-v3", "riscay-physical-policy-v4"}:
        raise ValueError("PHYSICAL_POLICY_REEXPORT_REQUIRED")
    if policy.get("schema") == "riscay-physical-policy-v4":
        if (policy.get("architecture") != "generic-mcu" or policy.get("profile_behavior") is not False
                or policy.get("spi_boot") is not True or policy.get("rom_bytes",0) <= 12
                or "policy_enabled" in policy):
            raise ValueError("INVALID_GENERIC_MCU_POLICY")
    elif policy.get("policy_enabled") is not True:
        raise ValueError("DISABLED_ESTIMATE_POLICY") # Historical comparison exports only.
    if (policy.get("timing_policy")!="current-supported-digital" or
        policy.get("qualification")!="unqualified" or policy.get("verification_layers")!="inline" or
        policy.get("timing_intent")!="contract.json"):
        raise ValueError("UNSUPPORTED_PHYSICAL_EXPORT_POLICY")
    if {"bd":"FourPhaseSoc","click":"ClickSoc"}.get(policy.get("variant"))!=manifest["top"]:
        raise ValueError("PHYSICAL_POLICY_TOP_MISMATCH")
    if policy.get("contract_sha256")!=sha(export/"contract.json") or policy.get("ports_sha256")!=sha(export/"ports.json"):
        raise ValueError("STALE_PHYSICAL_EXPORT_POLICY")
    expected_reset=dict(qualifier_edges=8, native_hold_edges=64, native_release_edges=64,
        digital_delay_limit_fs="250000000", measured_local_guard_reset_max_fs="1550000000",
        minimum_native_hold_fs="3150000000", minimum_native_release_fs="3150000000",
        qualification="unqualified", scope="local-guard-margin-only")
    if policy.get("service_max_hz") != 20000000 or (not comparison_baseline and policy.get("application_reset") != expected_reset):
        raise ValueError("UNSUPPORTED_APPLICATION_RESET_POLICY")
    if "native_reset_settlement_fs" in policy:
        raise ValueError("AMBIGUOUS_APPLICATION_RESET_POLICY")
    return policy

def prepare(export,out,pdk, *, comparison_baseline=False,candidate_guards=False):
    if out.exists(): raise ValueError("OUTPUT_ALREADY_EXISTS")
    pdk_verify(pdk)
    from sram_assets import verify
    # Public asset tool also checks the vendored RTL. No memory contents model
    # is copied into the ASIC inventory.
    lock=json.loads((ROOT/"soc/sram-lock.json").read_text())
    for name,asset in lock["assets"].items():
        verify((ROOT/".tools/gf180-sram"/name).read_bytes(),asset["sha256"])
    manifest,sources,groups=inventory(export,comparison_baseline=comparison_baseline)
    roles=resolve_roles(manifest["design"])
    policy=physical_policy(export,manifest,comparison_baseline=comparison_baseline)
    floor=guard_floor(pdk)
    guard_policy_path=ROOT/'physical/gf180/ordering-guards.json'
    wrappers={}; rewrites={}; guard_evidence={}; guard_policy=None
    primitive_files={k[0]+".sv" for k in groups}
    if guard_policy_path.exists() and not comparison_baseline:
        from ordering_guard_mapping import specialize
        guard_policy=json.loads(guard_policy_path.read_text())
        groups,wrappers,rewrites,guard_evidence=specialize(export,manifest,groups,
            guard_policy,policy['variant'],floor,candidate=candidate_guards)
    allowance_audit = None
    if any(k[0] == 'ChiselAsyncPassiveDataAllowance_v1' for k in groups):
        from check_reset_crossings import check_reset_crossings
        check_reset_crossings(export, manifest)
        allowance_audit = export/'reset-crossings/allowance-audit.json'
    out.mkdir(parents=True)
    if allowance_audit:
        shutil.copyfile(allowance_audit, out/'passive-allowance-audit.json')
    bindings=[]; circuits=[]; filelist=[]
    for source in sources:
        if source.name in primitive_files: continue
        if source.name==SRAM+".sv":
            shutil.copyfile(ROOT/".tools/gf180-sram"/(SRAM+".blackbox.v"),out/source.name)
        elif source.name in rewrites:
            from ordering_guard_mapping import rewrite_owner
            (out/source.name).write_text(rewrite_owner(source.read_text(),rewrites[source.name]))
        else: shutil.copyfile(source,out/source.name)
        filelist.append(source.name)
    bymodel=defaultdict(list)
    for index,(k,ps) in enumerate(sorted(groups.items())):
        p=ps[0]
        if passive(p): bymodel[k[0]].append((k,None)); continue
        role=roles[p["rtl_path"]]["role"] if p["rtl_path"] in roles else None
        circuit,requirements=adapter(p,floor,role=role,guard_stages=wrappers.get(k[0],{}).get('stages'))
        module=f'riscay_gf180_cell_{index}'
        text=circuit.verilog(module,p["ports"])
        # Internal keeper nets are explicitly declared, never implicit wires.
        extra=[n for n in ("state","next_n") if any(n in c["pins"].values() for c in circuit.cells)]
        if extra: text=text.replace(");\n", ");\n"+ATTR+"wire "+", ".join(extra)+";\n",1)
        circuits.append(text)
        binding=dict(model=p['model'],parameters=dict(k[1]),module=module,ports=p["ports"],
            instances=[x["rtl_path"] for x in ps],requirements=requirements,cells=circuit.cells)
        if k[0] in wrappers:
            binding['guard_policy']={x['rtl_path']:guard_evidence[x['rtl_path']] for x in ps}
        if circuit.aliases: binding["aliases"]=circuit.aliases
        if role is not None:
            binding["role_evidence"]={x["rtl_path"]:roles[x["rtl_path"]] for x in ps}
        bindings.append(binding); bymodel[k[0]].append((k,binding))
    for model,variants in sorted(bymodel.items()):
        original_model=wrappers.get(model,{}).get('model',model)
        source=(export/(original_model+".sv")).read_text(); start=source.index("module "+original_model)
        header=source[start:source.index(");",start)+2]
        if original_model!=model:header=header.replace('module '+original_model,'module '+model,1)
        header=header.replace("parameter time", "parameter [63:0]")
        header=header.replace("parameter longint unsigned", "parameter [63:0]")
        body=[]
        if variants[0][1] is not None:
            for i,(k,b) in enumerate(variants):
                b["variant"]=i
                conditions=" && ".join(f'({n} == {max(64,v.bit_length())}\'d{v})' for n,v in k[1])
                body.append(f'{"if" if i==0 else "else if"} ({conditions}) begin : variant_{i}')
                body.append('(* keep_hierarchy = "yes", dont_touch = "yes" *) '+b["module"]+
                    " mapped ("+", ".join(f'.{p["name"]}({p["name"]})' for p in b["ports"])+");\nend")
            body.append("else begin : unmapped\n  RISCAY_UNMAPPED_ASYNC_PARAMETERIZATION reject();\nend")
        (out/(model+".sv")).write_text("// Exact physical binding; no simulation delay body.\n"+header+"\n"+"\n".join(body)+"\nendmodule\n")
        filelist.append(model+".sv")
    (out/"riscay_gf180_cells.v").write_text("// SPDX-License-Identifier: Apache-2.0\n"+"\n".join(circuits))
    filelist.append("riscay_gf180_cells.v")
    physical_top(export,out,manifest,policy)
    filelist += ["RiscayMcuDigital.sv","riscay_reset_hold.sv"]
    (out/"filelist.f").write_text("\n".join(filelist)+"\n")
    shutil.copyfile(export/"contract.json",out/"timing-intent.json")
    shutil.copyfile(export/"physical-policy.json",out/"physical-policy.json")
    if guard_policy:shutil.copyfile(guard_policy_path,out/'ordering-guards.json')
    timing_contract(out,manifest,bindings)
    write_json(out/"mapping.json",dict(schema="riscay-gf180-mapping-v1",status="mapped-unqualified",
        comparison_baseline=comparison_baseline, physical_policy_sha256=sha(export/"physical-policy.json"),
        top="RiscayMcuDigital",variant=policy["variant"],matched_delay_cell="dlyd_1",matched_delay_floor_ns=floor,
        bindings=bindings,inputs={p.name:sha(p) for p in sources},
        passive_allowance_audit_sha256=sha(allowance_audit) if allowance_audit else None,
        ordering_guard_policy_sha256=sha(guard_policy_path) if guard_policy else None,
        ordering_guard_status=guard_policy['status'] if guard_policy else 'unchanged-baseline',
        control_roles_sha256=sha(CATALOGUE),
        files_sha256={f:sha(out/f) for f in filelist},
        qualification="PVT, extracted relative timing, pulse/aperture, reset and C-element checks required"))
    return len(bindings)

def gpio_pad_binding(count, spi_boot):
    if spi_boot and count < 7: raise ValueError('SPI_BOOT_GPIO_COUNT')
    indices=[i for i in range(count) if not spi_boot or i not in (3,6)]
    lines=[]
    for pad,logical in enumerate(indices):
        lines += [f"  assign gpio[{pad}] = gpioOe[{logical}] ? gpioOut[{logical}] : 1'bz;",
                  f"  assign gpioSense[{logical}] = gpio[{pad}];"]
    if spi_boot:
        lines += ['  assign gpioSense[3] = adcSclk;', '  assign gpioSense[6] = adcMiso;']
    return indices,'\n'.join(lines)


def physical_top(export,out,manifest,policy):
    ports=json.loads((export/"ports.json").read_text())["nodes"][0]["ports"]
    names=[p["source"].split('>')[-1].replace('.','_').replace('[','_').replace(']','') for p in ports]
    # I2C and GPIO use separate sense/drive ports at the digital boundary; the
    # chip shell exposes bidirectional package nets. No diagnostic pad bundle.
    external={"scl","sda","sdaLow","gpioIn","gpioOut","gpioOe","adcMiso","adcCsN","adcSclk"}
    n=policy["gpio_count"]
    declarations=["input wire serviceClock, watchdogClock, powerGood, reset",
        "output wire serviceClockEnable, porReleased", "input wire scl, sda, adcMiso",
        "output wire sdaLow, adcCsN, adcSclk",f"input wire [{n-1}:0] gpioIn",
        f"output wire [{n-1}:0] gpioOut, gpioOe"]
    connections=[]
    for name,p in zip(names,ports):
        if name=="reset": value="~porReleased"
        elif name=="gpioIn": value=f"{{{32-n}'b0,gpioIn}}"
        elif name in ("gpioOut","gpioOe"): value=name+"Full"
        elif name in external or name in ("serviceClock","watchdogClock","serviceClockEnable"): value=name
        elif p["direction"]=="output": value=""
        else: raise ValueError("UNBOUND_TOP_INPUT_"+name)
        connections.append(f'.{name}({value})')
    text="// SPDX-License-Identifier: Apache-2.0\nmodule RiscayMcuDigital ("+",\n".join(declarations)+");\n"
    text+="wire [31:0] gpioOutFull, gpioOeFull;\n"
    text+=f"assign gpioOut=gpioOutFull[{n-1}:0];\nassign gpioOe=gpioOeFull[{n-1}:0];\n"
    text+="riscay_reset_hold #(.HOLD_CYCLES(100000)) resetHold (.clk(serviceClock), .power_good(powerGood), .reset(reset), .released(porReleased));\n"
    text+=manifest["top"]+" soc ("+",\n".join(connections)+");\nendmodule\n"
    (out/"RiscayMcuDigital.sv").write_text(text)
    shutil.copyfile(export/"chip/riscay_reset_hold.sv",out/"riscay_reset_hold.sv")
    indices,pad_binding=gpio_pad_binding(n,policy.get('spi_boot',False))
    shell=(ROOT/"physical/gf180/RiscayMcuChip.sv").read_text().replace("@GPIO_COUNT@",str(n))
    shell=shell.replace('@GPIO_PAD_COUNT@',str(len(indices))).replace('@GPIO_PAD_BINDINGS@',pad_binding)
    (out/"RiscayMcuChip.sv").write_text(shell)
    for f in ("riscay_supply_monitor.v","riscay_lf_osc.v","riscay_service_osc.v"):
        shutil.copyfile(export/"chip"/f,out/f)
    shutil.copyfile(ROOT/"physical/gf180/power.tcl",out/"power.tcl")
    shutil.copyfile(ROOT/"physical/gf180/base.sdc",out/"base.sdc")
    write_json(out/"pins.json",dict(gpio_count=n,gpio_pad_logical_indices=indices,
        package_signals=["reset","scl","sda","adcMiso","adcCsN","adcSclk"]+
        [f"gpio[{i}]" for i in range(len(indices))],supplies=["VDD","VSS"],
        internal_analog_boundary=["serviceClock","watchdogClock","powerGood","serviceClockEnable","porReleased"],
        pad_status="logical shell only; GF180 I/O cells, ESD and padframe still required"))

def timing_contract(out,manifest,bindings):
    # This inventory is deliberately unbound. gf180_constraints.py uses the
    # synthesized instance tree, including generate-block spelling and names.
    checks=[]
    for b in bindings:
        for instance in b["instances"]:
            checks.append(dict(id=instance,module=b["module"],requirements=b["requirements"],
                relative_leaf_pins=[c["name"]+"/"+p for c in b["cells"] for p in c["pins"]]))
    timings=[dict(path=n["rtl_path"],timing=t,endpoints=n["endpoints"]) for n in nodes(manifest["design"]) for t in n["timing"]]
    write_json(out/"async-checks.json",dict(schema="riscay-relative-timing-v1",status="unqualified",
        cells=checks,stages=timings,required_evidence=["cell_pvt","whole_data_paths","relative_ordering",
        "pulse_high_low","setup_hold","reset_recovery_removal","clock_distribution","sram_half_cycle",
        "cdc_first_stage_only","keeper_feedback","postroute_parasitics"]))

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export",type=Path); parser.add_argument("output",type=Path)
    parser.add_argument("--pdk",type=Path,default=ROOT/".tools/physical/pdk")
    parser.add_argument('--candidate-guards',action='store_true',help='Explicit exploratory mapping of a not-yet-accepted guard policy')
    args=parser.parse_args()
    print(f"Mapped {prepare(args.export,args.output,args.pdk,candidate_guards=args.candidate_guards)} exact specializations; qualification pending")

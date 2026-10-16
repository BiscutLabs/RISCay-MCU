# SPDX-License-Identifier: Apache-2.0
"""First digital-block P&R experiment. Completion never implies async signoff."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
from gf180_physical import ROOT, SC, SRAM, pdk_verify, sha, write_json
from gf180_constraints import brace
from gf180_estimate import linux
from gf180_implement import audit

OPENROAD = "/nix/store/c4zxmi7w55jnz305yqc4407n4426zj7s-openroad-2026-02-17/bin/openroad"
PDK_SOURCE = "/home/nixos/work/gf180mcu-project-template/gf180mcu/gf180mcuD"
STAGES = ["floorplan", "place", "clock", "global", "route", "extract"]
ASSETS = {
    "technology.tlef": "libs.ref/gf180mcu_fd_sc_mcu7t5v0/techlef/gf180mcu_fd_sc_mcu7t5v0__nom.tlef",
    "tracks.info": "libs.tech/librelane/gf180mcu_fd_sc_mcu7t5v0/tracks.info",
    "rcx.nom": "libs.tech/librelane/rules.openrcx.gf180mcuD.nom",
    "rcx.min": "libs.tech/librelane/rules.openrcx.gf180mcuD.min",
    "rcx.max": "libs.tech/librelane/rules.openrcx.gf180mcuD.max",
}
PROVENANCE_SCHEMA = "riscay-pnr-inputs-v2"
MAPPING_INPUTS = ("mapping.json", "netlist.v", "netlist.json", "base.sdc", "clocked.sdc",
                  "feedback-cuts.tcl", "async.sdc", "preserve-mapped.tcl", "constraints-bound.json",
                  "electrical-repair/receipt.json")
FLOW_INPUTS = ("pnr.tcl", "pnr-pdn.tcl", "power.tcl")
GENERATED_INPUTS = ("config.tcl", "async-pnr.sdc", "protected.tcl")
RC_CORNERS = ("nom", "min", "max")


def geometry(side):
    if not math.isfinite(side) or side < 1440:
        raise ValueError("INVALID_COMMON_OUTLINE")
    return dict(die_um=[0,0,side,side], core_um=[30,30,side-30,side-30],
        placement_density=0.50,
        macro_locations=[["soc/fabric_"+name, x, side-576]
            for name,x in zip(("program_macros_0","program_macros_1","ram_macros_0"),
                             (100, (side-301.3)/2, side-400))])


def mapping_hashes(mapping):
    return {name: sha(mapping/name) for name in MAPPING_INPUTS}


def flow_key(hashes):
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()


def snapshot_flow(out, files):
    hashes={file.name:sha(file) for file in files}
    snapshot=out/"flow-snapshots"/flow_key(hashes)
    if snapshot.exists():
        if any(not (snapshot/name).is_file() or sha(snapshot/name)!=digest for name,digest in hashes.items()):
            raise ValueError("PNR_FLOW_SNAPSHOT_CHANGED")
    else:
        snapshot.mkdir(parents=True)
        for file in files: shutil.copyfile(file,snapshot/file.name)
    return snapshot,hashes


def validate_provenance(mapping,out,stage,flow_sources=None):
    """Fail before any output write; legacy runs remain historical evidence."""
    meta=json.loads((out/"run.json").read_text())
    if meta.get("provenance_schema")!=PROVENANCE_SCHEMA:
        raise ValueError("PNR_FRESH_RUN_REQUIRED")
    # Reading a checkpoint or its extracted RC is an acceptance path too.
    # Revalidate the complete repair evidence, then bind the exact receipt used
    # for this P&R run so a newly accepted repair cannot relabel an old ODB.
    from repair_gf180_design import validate_receipt
    validate_receipt(mapping)
    if meta.get("mapping_inputs_sha256")!=mapping_hashes(mapping):
        raise ValueError("PNR_MAPPING_INPUT_CHANGED")
    hashes=meta.get("flow_sources",{})
    if set(hashes)!=set(FLOW_INPUTS) or (flow_sources is not None and hashes!=flow_sources):
        raise ValueError("PNR_FLOW_INPUT_CHANGED")
    snapshot=out/"flow-snapshots"/flow_key(hashes)
    if any(not (snapshot/name).is_file() or sha(snapshot/name)!=digest for name,digest in hashes.items()):
        raise ValueError("PNR_FLOW_SNAPSHOT_CHANGED")
    for name,digest in meta.get("generated_inputs_sha256",{}).items():
        if not (out/name).is_file() or sha(out/name)!=digest:
            raise ValueError("PNR_GENERATED_INPUT_CHANGED")
    if set(meta.get("generated_inputs_sha256",{}))!=set(GENERATED_INPUTS):
        raise ValueError("PNR_GENERATED_INPUTS_MISSING")
    checkpoint=meta.get("checkpoints",{}).get(stage,{})
    if not checkpoint or checkpoint.get("odb_sha256")!=sha(out/(stage+".odb")):
        raise ValueError("PNR_CHECKPOINT_CHANGED")
    if checkpoint.get("protected_baseline_sha256")!=sha(out/"protected-baseline.tcl"):
        raise ValueError("PNR_PROTECTED_BASELINE_CHANGED")
    if stage=="extract" and checkpoint.get("spef_sha256")!=sha(out/"routed.spef"):
        raise ValueError("PNR_SPEF_CHANGED")
    if stage=="extract" and meta.get("wire_corners"):
        corners=checkpoint.get("rc_corners",{})
        if set(corners)!=set(RC_CORNERS): raise ValueError("PNR_RC_CORNERS_MISSING")
        for rc,receipt in corners.items():
            odb=out/('extract'+('' if rc=='nom' else '-'+rc)+'.odb')
            if receipt.get('odb_sha256')!=sha(odb) or receipt.get('spef_sha256')!=sha(out/('routed-'+rc+'.spef')):
                raise ValueError("PNR_RC_INPUT_CHANGED_"+rc)
    return meta


def rc_inputs(mapping,out,corner):
    meta=validate_provenance(mapping,out,"extract")
    if corner not in RC_CORNERS or set(meta.get('wire_corners',[]))!=set(RC_CORNERS):
        raise ValueError("PNR_RC_CORNERS_MISSING")
    return (out/('extract'+('' if corner=='nom' else '-'+corner)+'.odb'),
            out/('routed-'+corner+'.spef'))

def assets():
    dest=ROOT/".tools/physical/routing"; dest.mkdir(exist_ok=True)
    lockfile=ROOT/"physical/gf180/routing-lock.json"
    for name,source in ASSETS.items():
        if not (dest/name).exists():
            subprocess.run(["wsl","-d","nixos-librelane","-e","/run/current-system/sw/bin/cp",
                            PDK_SOURCE+"/"+source,linux(dest/name)],check=True)
    observed={name:sha(dest/name) for name in ASSETS}
    if lockfile.exists():
        if json.loads(lockfile.read_text())["files"]!=observed: raise ValueError("ROUTING_ASSET_CHANGED")
    else:
        write_json(lockfile,dict(source="same installed open_pdks snapshot as pdk-lock.json",
                                source_files=ASSETS,files=observed))
    return dest

def configuration(mapping,out,routing,threads,side=1440):
    pdk=ROOT/".tools/physical/pdk"; pdk_verify(pdk); audit(mapping)
    lines=[]
    for name,path in dict(mapping=mapping,out=out,pdk=pdk,routing=routing,
                          sram=ROOT/".tools/gf180-sram",source=ROOT/"physical/gf180").items():
        lines.append(f'set {name} {brace(linux(path))}')
    lines.extend([f'set threads {threads}',f'set sc {SC}',f'set sram_cell {SRAM}'])
    g=geometry(side)
    lines += ['set die_area {'+' '.join(map(str,g['die_um']))+'}',
              'set core_area {'+' '.join(map(str,g['core_um']))+'}',
              'set placement_density '+str(g['placement_density']),
              'set macro_locations {'+' '.join('{'+name+' '+str(x)+' '+str(y)+'}'
                  for name,x,y in g['macro_locations'])+'}']
    (out/"config.tcl").write_text("\n".join(lines)+"\n")
    # Compare every protected signal-pin connection at each checkpoint. Capture
    # after constant tie-cell insertion; power/well connections are separate.
    a=json.loads((mapping/"netlist-audit.json").read_text())
    m=json.loads((mapping/"mapping.json").read_text())
    protected=[]
    for b in m["bindings"]:
        for instance in b["instances"]:
            root=a["adapter_instances"][instance]
            for cell in b["cells"]:
                protected.append((root+"/"+cell["name"],cell["cell"],sorted(cell["pins"])))
    text="set protected_cells {\n"
    for name,master,pins in protected:
        text+="  {"+brace(name)+" "+brace(master)+" {"+" ".join(pins)+"}}\n"
    (out/"protected.tcl").write_text(text+"}\n")
    modules=json.loads((mapping/"netlist.json").read_text())["modules"]
    (out/"async-pnr.sdc").write_text(bind_flat_interfaces(modules,(mapping/"async.sdc").read_text()))

def bind_flat_interfaces(modules,sdc):
    # OpenDB flattens hierarchical interface pins. Resolve their connected leaf
    # drivers from the same Yosys graph instead of silently dropping constraints.
    boundaries={}; drivers={}; parents={}
    def find(n):
        p=parents.setdefault(n,n)
        if p!=n: parents[n]=find(p)
        return parents[n]
    def union(a,b):
        a,b=find(a),find(b)
        if a!=b:
            if a[0]==b[0]=="constant": raise ValueError("CONFLICTING_BOUNDARY_CONSTANTS")
            if a[0]=="constant": parents[b]=a
            else: parents[a]=b
    def walk(kind,path,portmap):
        mod=modules[kind]
        def net(bit): return ("constant",bit) if isinstance(bit,str) else (path,bit)
        for name,port in mod["ports"].items():
            for i,bit in enumerate(port["bits"]):
                if portmap.get(name):
                    if len(portmap[name])!=len(port["bits"]): raise ValueError("PARTIAL_BOUNDARY_"+path+name)
                    union(net(bit),portmap[name][i])
        for name,port in {**mod.get('netnames',{}),**mod['ports']}.items(): boundaries[path+name]=[net(b) for b in port["bits"]]
        for name,cell in mod.get("cells",{}).items():
            instance=path+name
            connections={p:[net(b) for b in bits] for p,bits in cell["connections"].items()}
            if cell["type"].startswith(SC) or cell["type"]==SRAM:
                for p,nets in connections.items():
                    if cell["port_directions"][p]!="output": continue
                    for i,n in enumerate(nets):
                        drivers.setdefault(n,[]).append(instance+"/"+p+(f'[{i}]' if len(nets)>1 else ""))
            else: walk(cell["type"],instance+"/",connections)
    walk("RiscayMcuDigital","",{})
    resolved={}
    for n,pins in drivers.items(): resolved.setdefault(find(n),[]).extend(pins)
    drivers=resolved
    def bind(match):
        name,width=match[1],int(match[2]); nets=[find(n) for n in boundaries[name]]
        if len(nets)!=width: raise ValueError("BOUNDARY_WIDTH_CHANGED_"+name)
        selected=[]
        for n in nets:
            if n[0]=="constant": continue
            if n not in drivers: raise ValueError("UNDRIVEN_BOUNDARY_"+name)
            selected.extend(drivers[n])
        if not selected: raise ValueError("EMPTY_BOUNDARY_"+name)
        return '[concat '+" ".join('[rp '+brace(p)+']' for p in sorted(set(selected)))+']'
    return re.sub(r'\[rbus \{([^}]+)\} (\d+)\]',bind,sdc)

def run(mapping,out,from_stage,to_stage,threads,side=1440):
    mapping=mapping.resolve(); out=out.resolve()
    from repair_gf180_design import validate_receipt
    validate_receipt(mapping)
    begin,end=STAGES.index(from_stage),STAGES.index(to_stage)
    g=geometry(side)
    if begin>end: raise ValueError("STAGE_ORDER")
    files=[ROOT/"physical/gf180"/n for n in FLOW_INPUTS]
    hashes={file.name:sha(file) for file in files}
    if begin:
        # Never regenerate constraints or relabel an old ODB with new inputs.
        meta=validate_provenance(mapping,out,STAGES[begin-1],hashes)
        if meta.get("openroad")!=OPENROAD or meta.get("threads")!=threads or meta.get("routing_lock_sha256")!=sha(ROOT/"physical/gf180/routing-lock.json"):
            raise ValueError("PNR_RUN_CONFIGURATION_CHANGED")
        if meta.get("mapping_directory")!=str(mapping) or meta.get("output_directory")!=str(out):
            raise ValueError("PNR_RESUME_DIRECTORY_CHANGED")
        if meta.get("geometry",geometry(1440))!=g:
            raise ValueError("PNR_GEOMETRY_CHANGED")
        pdk_verify(ROOT/".tools/physical/pdk")
    if from_stage=="floorplan": out.mkdir(parents=True,exist_ok=False)
    elif not out.is_dir(): raise ValueError("MISSING_RESUME_DIRECTORY")
    routing=assets()
    snapshot,hashes=snapshot_flow(out,files)
    if not begin:
        configuration(mapping,out,routing,threads,side)
        with (out/"config.tcl").open("a") as config: config.write('set source '+brace(linux(snapshot))+'\n')
        meta=dict(status="running-unqualified",source_commit=subprocess.check_output(
        ["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),mapping_sha256=sha(mapping/"mapping.json"),
        netlist_sha256=sha(mapping/"netlist.v"),openroad=OPENROAD,
        flow_sha256=sha(files[0]),flow_sources=hashes,provenance_schema=PROVENANCE_SCHEMA,
        mapping_inputs_sha256=mapping_hashes(mapping),checkpoints={},
        mapping_directory=str(mapping),output_directory=str(out),
        generated_inputs_sha256={name:sha(out/name) for name in GENERATED_INPUTS},
        routing_lock_sha256=sha(ROOT/"physical/gf180/routing-lock.json"),
        wire_corners=list(RC_CORNERS),
        die_um=g['die_um'],core_um=g['core_um'],geometry=g,threads=threads,
        limits=["digital block only; no pads/analog", "no async timing closure",
                "initial placement and routing, no density/antenna/LVS signoff"])
    else:
        # OpenROAD rewrites logs, metrics, ODBs and route products in place.
        # Copy every existing top-level artifact before allowing any retry;
        # hard links would not preserve files subsequently opened for writing.
        attempts=out/"resume-history"; attempts.mkdir(exist_ok=True)
        number=0
        while (attempts/str(number)).exists(): number+=1
        archive=attempts/str(number); archive.mkdir()
        for artifact in out.iterdir():
            if artifact.is_file(): shutil.copy2(artifact,archive/artifact.name)
        meta["status"]="running-unqualified"
    for stale in STAGES[begin:]: meta["checkpoints"].pop(stale,None)
    write_json(out/"run.json",meta)
    for i in range(begin,end+1):
        stage=STAGES[i]
        driver=out/(stage+".tcl")
        driver.write_text(f'source {brace(linux(out/"config.tcl"))}\nset stage {stage}\nset checkpoint {stage}\nset rc_corner nom\n'
            +f'set previous {STAGES[i-1] if i else "none"}\n'
            +f'source {brace(linux(snapshot/"pnr.tcl"))}\n')
        print("START",stage,flush=True)
        with (out/(stage+".log")).open("w") as log:
            result=subprocess.run(["wsl","-d","nixos-librelane","-e",OPENROAD,"-exit",
                "-metrics",linux(out/(stage+"-metrics.json")),linux(driver)],stdout=log,stderr=subprocess.STDOUT)
        log=(out/(stage+".log")).read_text()
        if result.returncode or f'PNR_STAGE_COMPLETE {stage}' not in log:
            meta.update(status="stopped-unqualified",failed_stage=stage,returncode=result.returncode)
            write_json(out/"run.json",meta)
            raise RuntimeError("PNR_STAGE_FAILED_"+stage+"\n"+log[-4000:])
        # A regenerated checkpoint invalidates all downstream saved stages.
        for later in STAGES[i+1:]: meta["checkpoints"].pop(later,None)
        meta["checkpoints"][stage]=dict(odb_sha256=sha(out/(stage+".odb")),
            protected_baseline_sha256=sha(out/"protected-baseline.tcl"))
        if stage=="extract":
            meta["checkpoints"][stage]["spef_sha256"]=sha(out/"routed.spef")
            # Independent fresh OpenROAD processes read the identical routed
            # checkpoint; never rescale nominal SPEF to invent min/max RC.
            rc_evidence={"nom":dict(spef_sha256=sha(out/"routed-nom.spef"),
                                   odb_sha256=sha(out/"extract.odb"))}
            for rc in ("min","max"):
                checkpoint="extract-"+rc; rc_driver=out/(checkpoint+".tcl")
                rc_driver.write_text(f'source {brace(linux(out/"config.tcl"))}\nset stage extract\n'
                    +f'set checkpoint {checkpoint}\nset previous route\nset rc_corner {rc}\n'
                    +f'source {brace(linux(snapshot/"pnr.tcl"))}\n')
                with (out/(checkpoint+".log")).open("w") as log:
                    r=subprocess.run(["wsl","-d","nixos-librelane","-e",OPENROAD,"-exit",linux(rc_driver)],stdout=log,stderr=subprocess.STDOUT)
                if r.returncode or 'PNR_STAGE_COMPLETE extract' not in (out/(checkpoint+".log")).read_text():
                    meta.update(status="stopped-unqualified",failed_stage=checkpoint,returncode=r.returncode)
                    write_json(out/"run.json",meta)
                    raise RuntimeError("PNR_RC_EXTRACTION_FAILED_"+rc)
                rc_evidence[rc]=dict(spef_sha256=sha(out/("routed-"+rc+".spef")),odb_sha256=sha(out/(checkpoint+".odb")))
            meta["checkpoints"][stage]["rc_corners"]=rc_evidence
        meta.update(last_completed_stage=stage); write_json(out/"run.json",meta)
        print("COMPLETE",stage,flush=True)
    meta["status"]="experiment-complete-timing-unqualified" if to_stage=="extract" else "checkpoint-unqualified"
    write_json(out/"run.json",meta)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mapping",type=Path); p.add_argument("output",type=Path)
    p.add_argument("--from-stage",choices=STAGES,default="floorplan")
    p.add_argument("--to-stage",choices=STAGES,default="extract")
    p.add_argument("--threads",type=int,default=8)
    p.add_argument("--die-side-um",type=float,default=1440)
    a=p.parse_args(); run(a.mapping,a.output,a.from_stage,a.to_stage,a.threads,a.die_side_um)

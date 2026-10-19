# SPDX-License-Identifier: Apache-2.0
"""Contract-selected canonical stage instances using shared controller templates.

No numeric controller result is shared between instances: physical load, capture
width, guards, corner and input slew remain part of each measurement. Custom
owners, FIFOs and Joins are deliberately not relabeled as canonical stages.
"""
from run_receipt import RunReceipt
import argparse
from copy import deepcopy
import hashlib
from itertools import product
import json
from pathlib import Path
import re
import subprocess

import control_relative_timing as relative
from characterize_gf180_control_native import OWNERS, expected_binding
from gf180_physical import ROOT, nodes, sha, write_json, pdk_verify
from repair_gf180_control import require, connectivity
from physical_tools import tool


def receipt_original(mapping, receipt):
    data=(mapping/'electrical-repair/reference/netlist.json').read_bytes()
    expected=receipt['inputs_sha256'][str((mapping/'netlist.json').resolve())]
    require(hashlib.sha256(data).hexdigest()==expected,'STAGE_REPAIR_REFERENCE_CHANGED')
    return json.loads(data)


def receipt_proof(mapping, receipt):
    data=(mapping/'electrical-repair/proof.json').read_bytes()
    require(hashlib.sha256(data).hexdigest()==receipt['evidence_sha256']['proof.json'],
            'STAGE_REPAIR_PROOF_CHANGED')
    return json.loads(data)


def receipt_buffers(mapping, receipt):
    return receipt_proof(mapping,receipt)['added_buffers']


def repaired_bindings(record, netlist, original, audit, buffers=()):
    """Bind live cloned modules by the receipt's exact original instance paths.

    Callers validate the complete repair receipt before using this metadata.
    Original definitions left behind by a hierarchical writer are not evidence
    for a live clone: audit_bindings still checks its actual recipe and pins.
    """
    from gf180_implement import instances
    live=dict(instances(netlist['modules'],'RiscayMcuDigital'))
    prior=dict(instances(original['modules'],'RiscayMcuDigital'))
    result=deepcopy(record)
    result['repair_buffers']=list(buffers)
    result['original_modules']={path:kind for path,kind in prior.items() if path in live}
    expected={i for b in result['bindings'] for i in b['instances']}
    require(set(audit['adapter_instances'])==expected,'STAGE_REPAIRED_ADAPTER_INVENTORY')
    for b in result['bindings']:
        modules=set()
        for instance in b['instances']:
            path=audit['adapter_instances'][instance]
            require(path.startswith('soc/'+'/'.join(instance.split('.')[1:])+'/') and
                    prior.get(path)==b['module'] and path in live,'STAGE_REPAIRED_ADAPTER_PATH')
            modules.add(live[path])
        b['physical_modules']=sorted(modules)
    return result


def descriptor(manifest, netlist, record, path, variant, *, storage=False):
    require(variant in ("bd","click"),"STAGE_VARIANT")
    matches=[n for n in nodes(manifest["design"]) if n["rtl_path"]==path]
    require(len(matches)==1,"STAGE_CONTRACT_PATH")
    node=matches[0]
    family=(("LongHoldBuffer" if variant=="bd" else "ClickBuffer") if storage else
            ("FourPhaseStage" if variant=="bd" else "ClickStage"))
    require(re.fullmatch(family+r"(?:_\d+)?",node["module"]) is not None,"STAGE_UNSUPPORTED_CONTROLLER")
    require(path.split(".")[0]==manifest["top"],"STAGE_TOP_BINDING")
    kind="RiscayMcuDigital"
    for part in ["soc",*path.split(".")[1:]]:
        body=netlist["modules"][kind]
        require(part in body["cells"],"STAGE_INSTANCE_BINDING")
        kind=body["cells"][part]["type"]
    original=record.get('original_modules',{}).get('soc/'+'/'.join(path.split('.')[1:]),kind)
    require(kind in netlist["modules"] and re.fullmatch(family+r"(?:_\d+)?",original) is not None,"STAGE_MAPPED_FAMILY")
    endpoints={e["id"]:e for e in node["endpoints"]}
    require(len(endpoints)==len(node["endpoints"]),"STAGE_DUPLICATE_ENDPOINT")
    iw,ow=[endpoints[k]["width"] for k in ("in_data","out_data")]
    require(type(iw)==type(ow)==int and 0<iw<=4096 and 0<ow<=1024,"STAGE_RESOURCE_BOUND")
    require(not storage or iw==ow,"STAGE_STORAGE_WIDTH")
    storage_endpoint="latch_data" if variant=="bd" else "register_data"
    require(endpoints[storage_endpoint]["width"]==ow,"STAGE_CAPTURE_WIDTH")
    endpoint_sources=dict(in_request="in.req",in_data="in.bits",in_acknowledge="in.ack",
        out_request="out.req",out_data="out.bits",out_acknowledge="out.ack",reset="reset")
    endpoint_sources.update(dict(latch_data="latchData",latch_closed="latchClosed",state_a="stateA") if variant=="bd" else
                            dict(register_data="registerData",capture="capture"))
    require(set(endpoints)==set(endpoint_sources),"STAGE_ENDPOINT_INVENTORY")
    for name,source in endpoint_sources.items():
        e=endpoints[name]
        require(e["source"]=="~|"+node["module"]+">"+source and
                e["rtl_path"]==path+".ca_p_"+str(len(name))+"_"+name and
                (name in ("in_data","out_data",storage_endpoint) or e["width"]==1),"STAGE_ENDPOINT_BINDING")
    selected={p["id"]:p for p in node["primitives"] if p["view"]!="constraint-marker"}
    require(len(selected)==sum(p["view"]!="constraint-marker" for p in node["primitives"]) and
            set(selected)==OWNERS[variant]|{"data_delay"},"STAGE_PRIMITIVE_INVENTORY")
    expected={}
    for name,p in selected.items():
        require(p["rtl_path"]==path+".ca_primitive_"+name and p["version"]==1,"STAGE_PRIMITIVE_PATH")
        params={k:int(v) for k,v in p["parameters"].items()}
        if name=="data_delay":
            model=p["model"]
            require(model in ("ChiselAsyncControlGate_v1","ChiselAsyncPassiveDataAllowance_v1"),
                    "STAGE_DATA_ALLOWANCE_MODEL")
            shape=(dict(WIDTH=ow,DELAY_FS=1) if model=="ChiselAsyncPassiveDataAllowance_v1" else
                   dict(OP=0,RESET_VALUE=0,WIDTH=ow,DELAY_FS=1))
        else:
            model,shape=expected_binding(variant,name)
            if name=="payload":shape["WIDTH"]=ow
        require(p["model"]==model and set(params)==set(shape) and params["DELAY_FS"]>0 and
                {k:v for k,v in params.items() if k!="DELAY_FS"}=={k:v for k,v in shape.items() if k!="DELAY_FS"},"STAGE_PRIMITIVE_SPECIALIZATION")
        bindings=[b for b in record["bindings"] if p["rtl_path"] in b["instances"]]
        require(len(bindings)==1 and bindings[0]["model"]==model and bindings[0]["parameters"]==params,"STAGE_MAPPING_METADATA")
        expected["ca_primitive_"+name]=(model,params)
    body=netlist["modules"][kind]
    data_connections=body["cells"]["ca_primitive_data_delay"]["connections"]
    if selected["data_delay"]["model"]=="ChiselAsyncPassiveDataAllowance_v1":
        require(set(data_connections)=={"a","q"} and
                len(data_connections["a"])==len(data_connections["q"])==ow,
                "STAGE_PASSIVE_DATA_PORTS")
    else:
        require(data_connections["reset"]==body["ports"]["reset"]["bits"],"STAGE_DATA_RESET")
    require(set(p for p,v in body["ports"].items() if v["direction"]=="input" and not (p=="in_bits" or p.startswith("in_bits_")))=={"reset","in_req","out_ack"},"STAGE_UNDECLARED_INPUT")
    timing=[t for t in node["timing"] if t["kind"]==("long-hold-bundling-v2" if variant=="bd" else "click-bundling-v1")]
    require(len(timing)==1,"STAGE_TIMING_KIND")
    t=timing[0]
    actual=lambda name:expected["ca_primitive_"+name][1]["DELAY_FS"]
    if variant=="bd":
        require(t["request"]=="in_request" and t["input_data"]=="in_data" and t["latch_data"]=="latch_data" and
                all(t[k]==v for k,v in dict(latch_closed="latch_closed",acknowledge="in_acknowledge",output_request="out_request",output_data="out_data").items()) and
                int(t["matched_delay_fs"])==actual("request_delay") and int(t["output_delay_fs"])==actual("output_delay") and
                int(t["data_delay"]["model_fs"])==actual("data_delay") and int(t["latch_delay"]["model_fs"])==actual("payload") and
                all(int(t["control_delays"][k]["model_fs"])==actual(k) for k in ("a","b","acknowledge","long_hold")),"STAGE_TIMING_BINDING")
        transforms=[t for t in node["timing"] if t["kind"]=="bundled-data-path-v1"]
        require(len(transforms)==1 and all(transforms[0][k]==v for k,v in
            dict(source="in_data",sink="latch_data",delay_cell="data_delay",delay_owner=[]).items()) and
            int(transforms[0]["budget"]["model_fs"])==actual("data_delay"),"STAGE_TRANSFORM_BINDING")
    else:
        require(t["variant"]=="standard" and t["initial_token"] is False and
                t["endpoints"]==["in_request","in_data","in_acknowledge","out_request","out_data","out_acknowledge","capture","register_data"] and
                all(int(t["times"][field])==actual(name) for field,name in (("REQUEST_FS","request_delay"),("ACKNOWLEDGE_FS","acknowledge_guard"),("OUTPUT_FS","output_guard"))) and
                all(int(t["cells"][name]["model_fs"])==actual(name) for name in ("data_delay","fire","input_compare","input_phase","output_compare","payload")),"STAGE_TIMING_BINDING")
    return dict(instance=path,logical_module=node["module"],module=kind,input_width=iw,payload_width=ow,
                expected_bindings=expected,controller_template="bd-empty-capture-v1" if variant=="bd" else "click-standard-capture-v1")


def numerical_status(summary):
    """A negative allowance requires input data lead; it is not a setup pass."""
    fields=("minimum_input_data_lag_ns","minimum_zero_reuse_hold_ns","minimum_ack_after_capture_ns")
    negative=[k for k in fields if summary[k] is not None and summary[k]<0]
    return dict(status="NEGATIVE_LOCAL_MARGIN" if negative else "NONNEGATIVE_LOCAL_MARGINS",
                negative_metrics=negative, physical_qualification=False)


def bd_wire_envelope(measurements,plan):
    """Compare fastest control/ACK with slowest data/capture across wire views.

    Cell PVT and injected source slew must match at the caller. This conservative
    wire envelope does not supply source launch composition or mismatch derates.
    """
    require(plan['variant']=='bd' and {'min','max'}<=measurements.keys(),'STAGE_WIRE_ENVELOPE_INPUTS')
    contexts={c['id']:c for c in plan['contexts']}
    require(all(set(results)==set(contexts) for results in measurements.values()),'STAGE_WIRE_ENVELOPE_CONTEXTS')
    merged={}
    for name,context in contexts.items():
        modes={q['id']:q['mode'] for q in context['queries']}
        require(all(set(results[name]['rows'])==set(modes) for results in measurements.values()),'STAGE_WIRE_ENVELOPE_ROWS')
        rows={}
        for key,mode in modes.items():
            require(mode in ('min','max'),'STAGE_WIRE_ENVELOPE_MODE')
            rc,row=(min if mode=='min' else max)(
                ((rc,r[name]['rows'][key]) for rc,r in measurements.items()),key=lambda pair:pair[1]['delay_ns'])
            rows[key]=dict(row,wire_corner=rc)
        merged[name]=dict(rows=rows,event_slew_ns=[
            min(r[name]['event_slew_ns'][0] for r in measurements.values()),
            max(r[name]['event_slew_ns'][1] for r in measurements.values())])
    return merged


def wire_envelope_coverage(cases,envelopes,enabled):
    expected={(c['instance'],c['key']) for c in cases if c['wire_corner']=='min'} if enabled else set()
    actual=[(e['instance'],e['key']) for e in envelopes]
    require(len(actual)==len(set(actual)) and set(actual)==expected,'STAGE_WIRE_ENVELOPE_COVERAGE')
    require(all(e['status'] in ('UNRESOLVED','CONDITIONAL_LOCAL_MEASUREMENTS') for e in envelopes),
            'STAGE_WIRE_ENVELOPE_STATUS')
    unresolved=sum(e['status']=='UNRESOLVED' for e in envelopes)
    return dict(status='requested' if enabled else 'not-requested',
        reason=None if enabled else 'Requires routed BD measurements with both min and max RC',
        expected=len(expected),completed=len(envelopes)-unresolved,unresolved=unresolved)


def roundtrip(mapping, output, netlist, yosys, pdk):
    """Prove the queried Verilog has exactly the graph used to bind queries."""
    write_json(output/"blackboxes.json",dict(modules={n:b for n,b in netlist["modules"].items()
        if not n.startswith(relative.SC) and int(b.get("attributes",{}).get("blackbox","0"),2)}))
    # Quoted filenames are understood by Yosys, not a shell.
    def filename(p):
        value=yosys.path(p)
        require(not any(c in value for c in '\r\n"\\'),"STAGE_YOSYS_FILENAME")
        return '"'+value+'"'
    script=output/"roundtrip.ys"
    script.write_text('read_liberty -lib '+filename(pdk/(relative.SC+"tt_025C_3v30.lib"))+'\n'+
        'read_json '+filename(output/"blackboxes.json")+'\n'+
        'read_verilog '+filename(mapping/"netlist.v")+'\nhierarchy -check -top RiscayMcuDigital\n'+
        'write_json '+filename(output/"roundtrip.json")+'\n',newline="\n")
    with (output/"roundtrip.log").open("w") as stream:
        subprocess.run(yosys.command(["-s",yosys.path(script)],timeout=110),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
    actual=json.loads((output/"roundtrip.json").read_text())
    require(connectivity(actual)==connectivity(netlist),"STAGE_VERILOG_GRAPH_MISMATCH")


def inventory(manifest):
    return [dict(instance=n["rtl_path"],module=n["module"],
                 supported=bool(re.fullmatch(r"(?:FourPhaseStage|ClickStage)(?:_\d+)?",n["module"])))
            for n in nodes(manifest["design"]) if n["primitives"]]


def run(mapping, output, variant, paths, campaign=False, *, routed=None, wire_corners=('min','max')):
    require(not output.exists(),"STAGE_OUTPUT_EXISTS")
    from repair_gf180_design import validate_receipt
    import native_leaf_timing as leaf
    receipt=validate_receipt(mapping)
    record=json.loads((mapping/"mapping.json").read_text())
    audit=json.loads((mapping/"netlist-audit.json").read_text())
    require(audit["status"]=="pass" and audit["netlist_sha256"]==sha(mapping/"netlist.v") and audit["mapping_sha256"]==sha(mapping/"mapping.json"),"STAGE_STALE_AUDIT")
    require(record["variant"]==variant,"STAGE_VARIANT")
    policy=json.loads((mapping/"physical-policy.json").read_text())
    require(record["physical_policy_sha256"]==sha(mapping/"physical-policy.json") and
            policy["contract_sha256"]==sha(mapping/"timing-intent.json"),"STAGE_STALE_CONTRACT")
    manifest=json.loads((mapping/"timing-intent.json").read_text())["manifest"]
    netlist=json.loads((mapping/"netlist.json").read_text())
    original=receipt_original(mapping,receipt)
    proof=receipt_proof(mapping,receipt)
    leaf_index=leaf.LeafIndex(original,netlist,proof['added_buffers'],proof['added_ties'])
    cuts=leaf.keeper_cuts(leaf_index,audit)
    require(paths and len(paths)<=16 and len(set(paths))==len(paths),"STAGE_SELECTION_BOUND")
    # Original hierarchy supplies logical identity, never timing. Every query
    # runs on the complete repaired graph with its parent buffers and loads.
    descriptors=[descriptor(manifest,original,record,p,variant) for p in paths]
    plans=[leaf.bind_plan(relative.make_plan(original,record,variant,d),leaf_index,d,original,cuts)
           for d in descriptors]
    sta=tool("sta");yosys=tool("yosys");pdk=ROOT/".tools/physical/pdk";pdk_verify(pdk)
    rc_views={None:(None,None)}; routed_files=[]; routed_netlists={}; routed_drivers={}
    if routed is not None:
        from gf180_pnr import validate_provenance,rc_inputs,pnr_tool
        routed=routed.resolve()
        meta=validate_provenance(mapping,routed,'extract')
        require(wire_corners and len(set(wire_corners))==len(wire_corners),'STAGE_RC_SELECTION')
        rc_views={rc:rc_inputs(mapping,routed,rc) for rc in wire_corners}
        odb_tool=pnr_tool(meta)
        routed_files=[routed/'run.json',routed/'global-repair-after.tsv',routed/'global-repair-proof.json',
                      *[p for pair in rc_views.values() for p in pair],*odb_tool.input_files()]
        # The P&R graph proof binds the complete repaired graph; source identities
        # and protected leaf pins above still come from the original contract.
        # Register the actual post-placement cell masters for path validation.
        physical_cells={}
        from routed_annotation import flat_export_name
        for line in (routed/'global-repair-after.tsv').read_text().splitlines():
            row=line.split('\t')
            if row[0]=='C':
                require(len(row)==3,'STAGE_ROUTED_CELL_INVENTORY')
                name=flat_export_name(row[1])
                require(name not in physical_cells,'STAGE_ROUTED_CELL_INVENTORY')
                physical_cells[name]=dict(type=row[2])
        require(physical_cells,'STAGE_ROUTED_CELL_INVENTORY')
        leaf_index.after['cells']=physical_cells
    source_names=("native_stage_timing.py","native_leaf_timing.py","routed_annotation.py","physical_tools.py","control_relative_timing.py","characterize_gf180_control_native.py",
                  "screen_gf180_control_repair.py","gf180_physical.py","gf180_estimate.py","gf180_implement.py","repair_gf180_control.py","characterize_gf180_liberty.py")
    files=[mapping/f for f in ("mapping.json","netlist.v","netlist.json","netlist-audit.json","timing-intent.json","physical-policy.json")]
    files += [mapping/'electrical-repair/receipt.json',mapping/'electrical-repair/reference/netlist.json',
              mapping/'electrical-repair/proof.json',ROOT/'tools/repair_gf180_design.py']
    files += [ROOT/"tools"/f for f in source_names]+[relative.PROBE]+sta.input_files()+yosys.input_files()
    files += [pdk/(relative.SC+c+".lib") for c in relative.CORNERS]
    files += [ROOT/'.tools/gf180-sram'/(leaf.SRAM+'__'+c+'.lib') for c in relative.CORNERS]
    files += routed_files
    run_receipt=RunReceipt(output/"receipt.json",inputs=files,tools=[ROOT/"tools/run_receipt.py"])
    status='fail'
    try:
        output.mkdir(parents=True);write_json(output/"inventory.json",inventory(manifest))
        if routed is None:roundtrip(mapping,output,netlist,yosys,pdk)
        else:
            from routed_annotation import run as audit_annotation, flat_driver_report
            ports={name+(f'[{i}]' if len(port['bits'])>1 else '')
                   for name,port in leaf_index.after['ports'].items() for i in range(len(port['bits']))}
            for rc,(odb,spef) in rc_views.items():
                annotation_dir=output/('annotation-'+rc)
                routed_netlists[rc]=annotation_dir/'actual.v'
                audit_annotation(odb,spef,odb_tool,annotation_dir,export_netlist=routed_netlists[rc])
                annotation_log=(annotation_dir/'annotation.log').read_text()
                routed_drivers[rc]=flat_driver_report(annotation_log,ports)
            exported_hashes={rc:sha(path) for rc,path in routed_netlists.items()}
            write_json(output/'analysis-backend.json',dict(backend='standalone-STA',
                netlists={rc:dict(path=str(path),sha256=exported_hashes[rc],source_odb=str(rc_views[rc][0]),
                                 source_odb_sha256=sha(rc_views[rc][0])) for rc,path in routed_netlists.items()},
                scope='Fresh full-netlist exports from accepted ODBs; exact SPEF and complete loaded-driver coverage in each STA context'))
        cases=[]
        for (index,plan), (wire_corner,(odb,spef)) in product(enumerate(plans),rc_views.items()):
            sub=output/(str(index)+('-rc-'+wire_corner if wire_corner else ''));sub.mkdir();write_json(sub/"plan.json",plan)
            for corner in (relative.CORNERS if campaign else relative.CORNERS[:1]):
                cell=relative.aperture(relative.library(pdk/(relative.SC+corner+".lib")),variant)
                for slew in ([0.02,2.0] if campaign else [0.2]):
                    key=f"{corner}-s{slew}";results={};failure=None
                    for ctx in plan["contexts"]:
                        if ctx['kind'] in ('common','sequential_ack'):
                            prior=[r['event_slew_ns'] for name,r in results.items() if name.startswith(('request-','release-'))]
                            require(prior,'LEAF_COMMON_SLEW_REQUIRED')
                            ctx['root_slew_ns']=dict(min=min(r[0] for r in prior),max=max(r[1] for r in prior))
                        tcl=sub/(key+"-"+ctx["id"]+".tcl");log=tcl.with_suffix(".log")
                        tcl.write_text(leaf.script(mapping/"netlist.v",corner,slew,plan,ctx,sta=sta,
                                                  routed_netlist=routed_netlists.get(wire_corner),spef=spef),newline="\n")
                        with log.open("w") as stream:
                            arguments=["-no_init","-exit",sta.path(tcl)]
                            subprocess.run(sta.command(arguments,timeout=110 if routed else 55),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120 if routed else 65)
                        try:results[ctx["id"]]=leaf.parse(log.read_text(),plan,ctx,slew,leaf_index,
                                                        routed_drivers=routed_drivers.get(wire_corner))
                        except ValueError as e:
                            failure=dict(context=ctx["id"],diagnostic=str(e));break
                    if failure is None:
                        try:summary=relative.margins(results,plan,cell)
                        except ValueError as e:failure=dict(context="relative-composition",diagnostic=str(e))
                    case=dict(instance=plan["descriptor"]["instance"],key=key,wire_corner=wire_corner,status="UNRESOLVED" if failure else "CONDITIONAL_LOCAL_MEASUREMENTS",failure=failure,
                              numerical=None if failure else numerical_status(summary),
                              summary=None if failure else {k:v for k,v in summary.items() if k!="lanes"})
                    write_json(sub/(key+".json"),dict(case=case,results=results,aperture=cell,summary=None if failure else summary))
                    cases.append(case);print(json.dumps(case),flush=True)
        cross_rc=[]
        envelope_enabled=routed is not None and variant=='bd' and {'min','max'}<=rc_views.keys()
        if routed is not None:
            require(all(sha(path)==exported_hashes[rc] for rc,path in routed_netlists.items()),'STAGE_ROUTED_EXPORT_CHANGED')
            validate_provenance(mapping,routed,'extract')
            if envelope_enabled:
                for index,plan in enumerate(plans):
                    envelope_dir=output/(str(index)+'-rc-envelope');envelope_dir.mkdir()
                    for case in [c for c in cases if c['instance']==plan['descriptor']['instance'] and c['wire_corner']=='min']:
                        records={rc:json.loads((output/(str(index)+'-rc-'+rc)/(case['key']+'.json')).read_text()) for rc in rc_views}
                        failures={rc:r['case']['failure'] for rc,r in records.items() if r['case']['status']=='UNRESOLVED'}
                        merged=summary=None
                        if not failures:
                            try:
                                merged=bd_wire_envelope({rc:r['results'] for rc,r in records.items()},plan)
                                summary=relative.margins(merged,plan,records['min']['aperture'])
                            except ValueError as error:failures={'composition':str(error)}
                        entry=dict(instance=case['instance'],key=case['key'],
                            status='UNRESOLVED' if failures else 'CONDITIONAL_LOCAL_MEASUREMENTS',failure=failures or None,
                            numerical=None if failures else numerical_status(summary),
                            summary=None if failures else {k:v for k,v in summary.items() if k!='lanes'})
                        write_json(envelope_dir/(case['key']+'.json'),dict(case=entry,results=merged,summary=summary))
                        cross_rc.append(entry)
        write_json(output/"results.json",dict(physical_qualification=False,routed_directory=str(routed) if routed else None,
            scope='Conditional local stage bounds; source launch, actual upstream slew, mismatch, noise and reset closure remain separate obligations',
            cases=cases,cross_rc_envelopes=cross_rc,
            cross_rc_coverage=wire_envelope_coverage(cases,cross_rc,envelope_enabled)))
        if any(c["status"]=="UNRESOLVED" for c in cases+cross_rc):raise ValueError("STAGE_CAMPAIGN_UNRESOLVED")
        status='pass'
    finally:
        run_receipt.finish(outputs=[p for p in output.rglob('*') if p.is_file()],status=status)



if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mapping",type=Path);p.add_argument("output",type=Path)
    p.add_argument("--variant",choices=("bd","click"),required=True)
    p.add_argument("--stage",action="append",required=True)
    p.add_argument("--campaign",action="store_true")
    p.add_argument('--routed',type=Path,help='Accepted zero-DRC P&R run; export its actual ODB for STA with extracted SPEF')
    p.add_argument('--wire-corner',action='append',choices=('min','nom','max'),help='Extracted corners; defaults to min and max')
    a=p.parse_args();run(a.mapping,a.output,a.variant,a.stage,a.campaign,routed=a.routed,wire_corners=a.wire_corner or ('min','max'))

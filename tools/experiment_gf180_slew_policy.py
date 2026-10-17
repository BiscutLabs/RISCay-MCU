# SPDX-License-Identifier: Apache-2.0
"""Isolated corner-slew repair experiment; never overwrites an accepted mapping."""
import argparse
import copy
from dataclasses import replace
import json
from pathlib import Path
import re
import subprocess

from characterize_gf180_liberty import CORNERS
from gf180_constraints import brace
from gf180_estimate import library
from gf180_physical import ROOT, SC, SRAM, sha, write_json
from gf180_slew_policy import write_views, seed_pins, classify, compose_reports, report_rows
from check_pnr_repair import read_graph
from physical_tools import tool
from repair_gf180_control import require
from repair_gf180_design import (validate_receipt, protected_cells, read_verilog_json,
                                correct_scalar_port_escaping, graph_proof, flat,
                                prune_added_orphan_ties)


def pack_database_graph(database,reference):
    """Only coalesce scalar OpenDB bus names using the original exact schema."""
    result=copy.deepcopy(database);body=result['modules']['RiscayMcuDigital']
    schema=flat(reference,'RiscayMcuDigital')
    def pack(actual,expected):
        expanded={p if len(v['bits'])==1 else f'{p}[{i}]'
                  for p,v in expected.items() for i in range(len(v['bits']))}
        require(set(actual)==expanded,'SLEW_DATABASE_PIN_SCHEMA')
        packed={}
        for p,v in expected.items():
            names=[p] if len(v['bits'])==1 else [f'{p}[{i}]' for i in range(len(v['bits']))]
            require(all(actual[n]['direction']==v['direction'] and len(actual[n]['bits'])==1 for n in names),
                    'SLEW_DATABASE_PIN_DIRECTION')
            packed[p]=dict(direction=v['direction'],bits=[actual[n]['bits'][0] for n in names])
        return packed
    body['ports']=pack(body['ports'],schema['ports'])
    for name,c in body['cells'].items():
        if name not in schema['cells']:continue  # Added scalar buffers/ties are proved separately.
        expected=schema['cells'][name]
        actual={p:dict(bits=bs,direction=c['port_directions'][p]) for p,bs in c['connections'].items()}
        wanted={p:dict(bits=bs,direction=expected['directions'][p]) for p,bs in expected['connections'].items()}
        packed=pack(actual,wanted)
        c['connections']={p:v['bits'] for p,v in packed.items()}
        c['port_directions']={p:v['direction'] for p,v in packed.items()}
    return result


def leaf_graph(netlist):
    """Remove hierarchy only for the independent writer-to-OpenDB comparison.

    The original-to-writer proof separately retains every native interface.
    """
    g=flat(netlist,'RiscayMcuDigital');nets={}
    def bit(n):
        if n[0]=='constant':return n[1]
        if n not in nets:nets[n]=len(nets)+1
        return nets[n]
    ports={p:dict(direction=v['direction'],bits=list(map(bit,v['bits']))) for p,v in g['ports'].items()}
    cells={n:dict(type=c['type'],port_directions=c['directions'],
                 connections={p:list(map(bit,bs)) for p,bs in c['connections'].items()}) for n,c in g['cells'].items()}
    return dict(modules=dict(RiscayMcuDigital=dict(ports=ports,cells=cells)))


def fresh_reports(out,runtime,library_lines,helper):
    """Two identical fresh processes per policy; never reuse optimizer state."""
    b=lambda p:brace(runtime.path(p))
    generated={};context_changes={}
    for label,limit in (('ordinary',1000),('native',2)):
        script=out/('report-'+label+'.tcl')
        lines=library_lines+['read_db '+b(out/'candidate.odb'),
            'set_wire_rc -resistance 0 -capacitance 0','set_input_transition 2 [all_inputs]',
            'set_load 0.05 [all_outputs]',f'set_max_transition {limit} [current_design]',
            'source '+b(helper),'slew_raw_reports '+b(out/('fresh-'+label)),
            'puts SLEW_REPORT_COMPLETE','exit']
        script.write_text('\n'.join(lines)+'\n',newline='\n')
        generated[str(script.resolve())]=sha(script)
        original={}
        for repeat in (False,True):
            logfile=out/('report-'+('repeat-' if repeat else '')+label+'.log')
            with logfile.open('w') as log:
                subprocess.run(runtime.command(['-exit',runtime.path(script)],timeout=180),
                               stdout=log,stderr=subprocess.STDOUT,check=True,timeout=195)
            require('SLEW_REPORT_COMPLETE' in logfile.read_text(),'SLEW_REPORT_INCOMPLETE')
            for c in CORNERS:
                data=(out/f'fresh-{label}-{c}.rpt').read_bytes()
                if repeat:require(data==original[c],'SLEW_FRESH_REPORT_NOT_REPRODUCIBLE')
                else:
                    original[c]=data
                    (out/f'fresh-first-{label}-{c}.rpt').write_bytes(data)
        for corner in CORNERS:
            resident={(r['kind'],r['pin']):r for r in report_rows((out/f'after-{label}-{corner}.rpt').read_text())}
            reloaded={(r['kind'],r['pin']):r for r in report_rows((out/f'fresh-{label}-{corner}.rpt').read_text())}
            context_changes[label+'-'+corner]=[dict(resident=resident.get(k),reloaded=reloaded.get(k))
                for k in sorted(resident.keys()|reloaded.keys()) if resident.get(k)!=reloaded.get(k)]
    write_json(out/'resident-vs-reloaded.json',context_changes)
    return generated


def run(mapping, out, executable=None, blanket=False):
    mapping=mapping.resolve(); out=out.resolve()
    validate_receipt(mapping)
    require(not out.exists(), 'SLEW_EXPERIMENT_EXISTS')
    pdk=ROOT/'.tools/physical/pdk'
    runtime=tool('openroad')
    if executable:runtime=replace(runtime,executable=executable)
    yosys=tool('yosys')
    source=mapping/'electrical-repair'
    metadata=json.loads((mapping/'mapping.json').read_text())
    audit=json.loads((source/'reference/netlist-audit.json').read_text())
    before=json.loads((source/'reference/netlist.json').read_text())
    protected=protected_cells(mapping)
    helper=ROOT/'physical/gf180/slew-policy.tcl'
    graph_helper=ROOT/'physical/gf180/pnr-repair.tcl'
    inputs=[source/'receipt.json',source/'prepared.v',source/'prepared.json',mapping/'mapping.json',
            source/'reference/netlist-audit.json',source/'reference/netlist.json',helper,graph_helper,
            *[ROOT/'tools'/n for n in ('experiment_gf180_slew_policy.py','gf180_slew_policy.py',
                                     'repair_gf180_design.py','gf180_physical.py','gf180_control_roles.py',
                                     'gf180_estimate.py','gf180_constraints.py','repair_gf180_control.py',
                                     'characterize_gf180_liberty.py','check_pnr_repair.py')],
            *runtime.input_files(),*yosys.input_files()]
    wrapped=runtime.host_path().with_name('.'+runtime.host_path().name+'-wrapped')
    if wrapped.exists():inputs.append(wrapped)
    inputs += [pdk/(SC+c+'.lib') for c in CORNERS]
    inputs += [ROOT/'.tools/gf180-sram'/(SRAM+'__'+c+'.lib') for c in CORNERS]
    inputs += [ROOT/'.tools/physical/routing/technology.tlef',pdk/'gf180mcu_fd_sc_mcu7t5v0.lef',
               ROOT/'.tools/gf180-sram'/(SRAM+'.lef')]
    frozen={str(p.resolve()):sha(p) for p in inputs}
    out.mkdir()
    write_json(out/'inputs.json', frozen)
    write_views(pdk,out/'slew-views',CORNERS)
    seeds=seed_pins(metadata,audit['adapter_instances'])
    write_json(out/'native-seeds.json',seeds)
    b=lambda p:brace(runtime.path(p))
    lines=['set sc '+SC,'set pvt_corners {'+' '.join(CORNERS)+'}',
           'define_corners {*}$pvt_corners']
    for c in CORNERS:
        libdir=pdk if blanket else out/'slew-views'
        lines += ['read_liberty -corner '+c+' '+b(libdir/(SC+c+'.lib')),
                  'read_liberty -corner '+c+' '+b(ROOT/'.tools/gf180-sram'/(SRAM+'__'+c+'.lib'))]
    # Compare both candidates under the SAME final corner-specific policy.
    # Only the baseline optimizer uses original libraries and blanket 2 ns.
    report_libraries=lines[:3]
    for c in CORNERS:
        report_libraries += ['read_liberty -corner '+c+' '+b(out/'slew-views'/(SC+c+'.lib')),
                             'read_liberty -corner '+c+' '+b(ROOT/'.tools/gf180-sram'/(SRAM+'__'+c+'.lib'))]
    lines += ['read_lef '+b(ROOT/'.tools/physical/routing/technology.tlef'),
              'read_lef '+b(pdk/'gf180mcu_fd_sc_mcu7t5v0.lef'),
              'read_lef '+b(ROOT/'.tools/gf180-sram'/(SRAM+'.lef')),
              'read_verilog '+b(source/'prepared.v'),'link_design -hier RiscayMcuDigital',
              'initialize_floorplan -die_area {0 0 5000 5000} -core_area {30 30 4970 4970} -site GF018hv5v_mcu_sc7',
              'set_wire_rc -resistance 0 -capacitance 0',
              'set_input_transition 2 [all_inputs]','set_load 0.05 [all_outputs]',
              'set_max_transition '+('2' if blanket else '1000')+' [current_design]',
              'set slew_native_seeds {'+' '.join(brace(p) for p in seeds)+'}',
              'set protected [dict create]',
              'foreach name {'+' '.join(brace(p) for p in sorted(protected))+'} {dict set protected $name 1}',
              'foreach inst [[ord::get_db_block] getInsts] {',
              'if {[dict exists $protected [$inst getName]] || [[$inst getMaster] getName] eq "'+SRAM+'"} {$inst setDoNotTouch true}',
              '}', 'set_dont_use [get_lib_cells */*dff*]', 'set_dont_use [get_lib_cells */*lat*]',
              'source '+b(helper), 'slew_raw_reports '+b(out/'before-ordinary'),
              'repair_design -pre_placement -max_wire_length 0 -verbose',
              'write_verilog '+b(out/'ordinary.v')]
    # Two bounded strict rounds reclassify every newly inserted segment. An
    # unresolved row is retained; iteration count is not a convergence claim.
    if not blanket:
        for i in range(2): lines += ['slew_strict_repair '+b(out/f'strict-round-{i}')]
    lines += ['set_max_transition 1000 [current_design]', 'slew_raw_reports '+b(out/'after-ordinary'),
              'set_max_transition 2 [current_design]', 'slew_raw_reports '+b(out/'after-native'),
              'write_db '+b(out/'candidate.odb'),'source '+b(graph_helper),
              'repair_graph '+b(out/'candidate-raw.tsv'),
              'write_verilog '+b(out/'repaired-raw.v'), 'puts SLEW_EXPERIMENT_COMPLETE', 'exit']
    script=out/'repair.tcl';script.write_text('\n'.join(lines)+'\n',newline='\n')
    generated={str(p.resolve()):sha(p) for p in [script,out/'native-seeds.json',*sorted((out/'slew-views').iterdir())]}
    with (out/'repair.log').open('w') as log:
        subprocess.run(runtime.command(['-exit',runtime.path(script)],timeout=1200),
                       stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1215)
    require('SLEW_EXPERIMENT_COMPLETE' in (out/'repair.log').read_text(),'SLEW_INCOMPLETE')
    require(all(sha(Path(p))==h for p,h in generated.items()),'SLEW_GENERATED_INPUT_CHANGED')
    generated[str((out/'candidate.odb').resolve())]=sha(out/'candidate.odb')
    generated.update(fresh_reports(out,runtime,report_libraries,helper))
    corrected,edits=correct_scalar_port_escaping((out/'repaired-raw.v').read_text())
    (out/'repaired.v').write_text(corrected,newline='\n')
    write_json(out/'serializer-corrections.json',edits)
    after=read_verilog_json(out/'repaired.v',out/'repaired.json','RiscayMcuDigital',yosys,pdk,before)
    libs=[library(pdk/(SC+c+'.lib')) for c in CORNERS]
    removed=prune_added_orphan_ties(before,after,'RiscayMcuDigital',protected,libs)
    write_json(out/'orphan-ties.json',removed)
    write_json(out/'candidate.json',after)
    db=pack_database_graph(read_graph(out/'candidate-raw.tsv'),before)
    physical_db=copy.deepcopy(db)
    db_orphans=prune_added_orphan_ties(before,db,'RiscayMcuDigital',protected,libs)
    write_json(out/'database-orphan-ties.json',db_orphans)
    proof=graph_proof(before,after,'RiscayMcuDigital',protected,libs)
    writer_flat=leaf_graph(after)
    # A hierarchy-only constant port can keep a tie in the writer even when
    # no physical leaf consumes it. Remove only the existing oracle's proven
    # orphan ties from BOTH flat proof views; retain every raw physical cell.
    writer_orphans=prune_added_orphan_ties(leaf_graph(before),writer_flat,'RiscayMcuDigital',protected,libs)
    write_json(out/'writer-flat-orphan-ties.json',writer_orphans)
    writer_proof=graph_proof(writer_flat,db,'RiscayMcuDigital',protected,libs)
    require(not writer_proof['added_buffers'] and not writer_proof['added_ties'] and
            not writer_proof['resized'],'SLEW_WRITER_GRAPH_CHANGED')
    write_json(out/'writer-proof.json',writer_proof)
    write_json(out/'proof.json',proof)
    inventory=classify(flat(physical_db,'RiscayMcuDigital'),seeds)
    write_json(out/'pin-classes.json',{k:v for k,v in inventory.items() if k!='native_nets'})
    combined={corner:compose_reports((out/f'fresh-ordinary-{corner}.rpt').read_text(),
        (out/f'fresh-native-{corner}.rpt').read_text(),inventory) for corner in CORNERS}
    write_json(out/'classified-electrical.json',combined)
    # Fresh candidate evidence remains isolated from default-flow receipts.
    require(all(sha(Path(p))==h for p,h in frozen.items()),'SLEW_INPUT_CHANGED')
    require(all(sha(Path(p))==h for p,h in generated.items()),'SLEW_GENERATED_INPUT_CHANGED')
    write_json(out/'result.json',dict(status='graph-proved-experiment-electrically-unqualified',
        physical_qualification=False, default_flow_changed=False,
        blanket_2ns_baseline=blanket,
        inputs_sha256=frozen,generated_inputs_sha256=generated,
        evidence_sha256={str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file()},
        proof_sha256=sha(out/'proof.json'),
        native_pins=len(inventory['native_pins']), ordinary_pins=len(inventory['ordinary_pins'])))
    print('SLEW_GRAPH_PROVED',out,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mapping',type=Path);parser.add_argument('out',type=Path)
    parser.add_argument('--openroad')
    parser.add_argument('--blanket-baseline',action='store_true')
    args=parser.parse_args();run(args.mapping,args.out,args.openroad,args.blanket_baseline)

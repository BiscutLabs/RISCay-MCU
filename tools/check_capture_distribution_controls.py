# SPDX-License-Identifier: Apache-2.0
"""Actual-arc sensitivity and period invariance of loaded capture-tree reports."""
import argparse
import json
from pathlib import Path
import subprocess

import measure_capture_distribution as measure
from gf180_physical import SC, sha, write_json
from native_leaf_timing import LeafIndex, keeper_cuts
from native_stage_timing import receipt_original, receipt_proof
from physical_tools import tool
from repair_gf180_control import require
from repair_gf180_design import validate_receipt


def values(log):
    return {x[1]:list(map(float,x[2:7])) for line in log.splitlines() if (x:=line.split('\t'))[0]=='CONTROL_PATH'}


def require_baseline_inputs(evidence,files):
    recorded=evidence['inputs_sha256']
    for path in files:
        require(recorded.get(str(path.resolve()))==sha(path),'DISTRIBUTION_CONTROL_BASELINE_BINDING')


def compare(base,changed,affected):
    require(base.keys()==changed.keys(),'DISTRIBUTION_CONTROL_COVERAGE')
    moved=[]
    for key,a in base.items():
        b=changed[key]
        if key in affected:
            require(b[3]-a[3]>90,'DISTRIBUTION_CONTROL_NO_DELAY');moved.append(key)
        else:require(all(abs(x-y)<1e-5 for x,y in zip(a,b)),'DISTRIBUTION_CONTROL_UNEXPECTED_CHANGE')
    require(set(moved)==affected,'DISTRIBUTION_CONTROL_OMITTED_BRANCH')
    return len(moved)


def run(mapping,baseline,out):
    require(not out.exists(),'DISTRIBUTION_CONTROL_OUTPUT_EXISTS')
    receipt=validate_receipt(mapping);evidence=json.loads((baseline/'results.json').read_text())
    require(all(sha(Path(p))==h for p,h in evidence['inputs_sha256'].items()),'DISTRIBUTION_CONTROL_STALE_INPUT')
    require(all(sha(baseline/p)==h for p,h in evidence['evidence_sha256'].items()),'DISTRIBUTION_CONTROL_STALE_BASELINE')
    sta=tool('sta')
    require_baseline_inputs(evidence,[*[mapping/n for n in ('netlist.v','mapping.json','netlist-audit.json','electrical-repair/receipt.json')],
        *sta.input_files()])
    plan=json.loads((baseline/'plan.json').read_text());audit=json.loads((mapping/'netlist-audit.json').read_text())
    proof=receipt_proof(mapping,receipt);live=json.loads((mapping/'netlist.json').read_text())
    index=LeafIndex(receipt_original(mapping,receipt),live,proof['added_buffers'],proof['added_ties'])
    cuts=keeper_cuts(index,audit);key='tt_025C_3v30-s0.02'
    base_log=(baseline/(key+'.log')).read_text();measure.parse(base_log,plan,.02);base=values(base_log)
    # Select one real final branch of bank0; derive all downstream capture pins
    # from the live graph rather than assuming a contiguous 16-bit group.
    selected=[(i,p) for i,p in enumerate(plan) if '.ca_child_frame_store.' in p['instance']]
    require(selected,'DISTRIBUTION_CONTROL_NO_FRAME_BANK');i,p=selected[0]
    target=p['targets'][0];cell,pin=target.rsplit('/',1);net=index.after['cells'][cell]['connections'][pin]
    drivers=[(n,c) for n,c in index.after['cells'].items() if c['connections'].get('Z')==net]
    require(len(drivers)==1 and drivers[0][1]['type']==SC+'buf_4','DISTRIBUTION_CONTROL_BRANCH_DRIVER')
    driver=drivers[0][0];affected=set()
    for n,pp in enumerate(plan):
        for j,t in enumerate(pp['targets']):
            c,pin=t.rsplit('/',1)
            if index.after['cells'][c]['connections'][pin]==net:
                affected.update(f'{n}:{e}:{m}:{j}' for e in ('rise','fall') for m in ('min','max'))
    require(len(affected)==64,'DISTRIBUTION_CONTROL_EXPECTED_16_LEAVES')
    files=[Path(__file__),baseline/'results.json',*sta.input_files()]
    frozen={**evidence['inputs_sha256'],**{str(f.resolve()):sha(f) for f in files}}
    out.mkdir(parents=True);sdf=out/'late-branch.sdf'
    sdf_instance=driver.replace('.',r'\.')
    sdf.write_text('(DELAYFILE (SDFVERSION "3.0") (DESIGN "RiscayMcuDigital") (DIVIDER /) (TIMESCALE 1ns)\n'
        f'(CELL (CELLTYPE "{SC}buf_4") (INSTANCE {sdf_instance}) (DELAY (ABSOLUTE (IOPATH I Z (100:100:100) (100:100:100))))))\n')
    results=[]
    for name,period,annotation in (('period',2000,None),('late-branch',1000,sdf)):
        tcl=out/(name+'.tcl');log=out/(name+'.log')
        tcl.write_text(measure.script(mapping,plan,cuts,'tt_025C_3v30',.02,sta,period=period,sdf=annotation),newline='\n')
        with log.open('w') as stream:subprocess.run(sta.command(['-no_init','-exit',sta.path(tcl)],timeout=180),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=190)
        text=log.read_text();summary=measure.parse(text,plan,.02)
        changed=compare(base,values(text),affected if annotation else set())
        if annotation:
            require(all(not r['within_budget'] for r in summary if r['instance']==p['instance']),'DISTRIBUTION_CONTROL_BUDGET_NOT_FAILED')
        results.append(dict(control=name,status='pass',changed_rows=changed));print(results[-1],flush=True)
    require(all(sha(Path(p))==h for p,h in frozen.items()),'DISTRIBUTION_CONTROL_INPUT_CHANGED');validate_receipt(mapping)
    write_json(out/'results.json',dict(status='pass',physical_qualification=False,controls=results,
        mutated_driver=driver,affected_capture_leaves=16,inputs_sha256=frozen,
        evidence_sha256={p.name:sha(p) for p in out.iterdir() if p.is_file()}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('mapping','baseline','output'):p.add_argument(name,type=Path)
    a=p.parse_args();run(a.mapping,a.baseline,a.output)

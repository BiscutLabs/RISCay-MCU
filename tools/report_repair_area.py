# SPDX-License-Identifier: Apache-2.0
"""Account for every cell before/after accepted repair; no power or timing claim."""
import argparse
import json
import math
import re
from pathlib import Path

from gf180_estimate import groups, scalar
from gf180_physical import ROOT, SC, SRAM, sha, write_json
from repair_gf180_control import require
from repair_gf180_design import flat, validate_receipt


def lef_areas(paths):
    result={}
    for path in paths:
        for name,body in re.findall(r'^\s*MACRO\s+(\S+)\s*\n(.*?)^\s*END\s+\1\s*$',path.read_text(),re.M|re.S):
            sizes=re.findall(r'^\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;',body,re.M)
            require(len(sizes)==1 and name not in result,'REPAIR_AREA_LEF_MACRO')
            result[name]=math.prod(map(float,sizes[0]))
    require(result and all(math.isfinite(a) and a>0 for a in result.values()),'REPAIR_AREA_LEF_SIZE')
    return result


def summarize(a,b,proof,prep,liberty,areas):
    require(a.keys()<=b.keys(),'REPAIR_AREA_ORIGINAL_CELL_REMOVED')
    require(all(c['type'] in areas and c['type'] in liberty for c in [*a.values(),*b.values()]),'REPAIR_AREA_MISSING_CELL')
    added=set(b)-set(a);buffers=set(proof['added_buffers']);ties=set(proof['added_ties'])
    require(not buffers&ties and added==buffers|ties,'REPAIR_AREA_ADDITION_INVENTORY')
    reset={x['buffer'] for x in prep['reset_buffers']}
    sram={x['buffer'] for x in prep.get('sram_clock_buffers',[])}
    feedback={x for x in buffers if '/riscay_output_feedback_' in x}
    require(reset|sram<=buffers and not reset&feedback and not sram&(reset|feedback),'REPAIR_AREA_PREPARATION_INVENTORY')
    categories=dict(native_reset=reset,sram_clock=sram,writer_feedback=feedback,openroad_other=buffers-reset-sram-feedback)
    def area(cells,metric=areas):return math.fsum(metric[c['type']] for c in cells)
    before,after=area(a.values()),area(b.values())
    macro_before=area(c for c in a.values() if c['type']==SRAM)
    macros=area(c for c in b.values() if c['type']==SRAM)
    require(macro_before==macros,'REPAIR_AREA_MACRO_CHANGED')
    added_area=area(b[n] for n in added)
    resized=math.fsum(areas[b[n]['type']]-areas[a[n]['type']] for n in a)
    require(math.isclose(after-before,added_area+resized,abs_tol=1e-5),'REPAIR_AREA_RECONCILIATION')
    return dict(lef_total_before_mm2=before/1e6,lef_total_after_mm2=after/1e6,
        liberty_total_before_mm2=area(a.values(),liberty)/1e6,liberty_total_after_mm2=area(b.values(),liberty)/1e6,
        macro_lef_area_mm2=macros/1e6,macro_liberty_area_mm2=area((c for c in b.values() if c['type']==SRAM),liberty)/1e6,
        original_cells=len(a),repaired_cells=len(b),
        logic_before_mm2=(before-macros)/1e6,logic_after_mm2=(after-macros)/1e6,
        logic_delta_mm2=(after-before)/1e6,new_cell_area_mm2=added_area/1e6,resize_delta_mm2=resized/1e6,
        buffers={name:dict(count=len(ns),area_mm2=area(b[n] for n in ns)/1e6) for name,ns in categories.items()},
        new_ties=dict(count=len(ties),area_mm2=area(b[n] for n in ties)/1e6))


def report(mapping, output):
    mapping=mapping.resolve();require(not output.exists(),'REPAIR_AREA_OUTPUT_EXISTS')
    validate_receipt(mapping)
    libpaths=[ROOT/'.tools/physical/pdk'/(SC+'tt_025C_3v30.lib'),
              ROOT/'.tools/gf180-sram'/(SRAM+'__tt_025C_3v30.lib')]
    lefpaths=[ROOT/'.tools/physical/pdk/gf180mcu_fd_sc_mcu7t5v0.lef',ROOT/'.tools/gf180-sram'/(SRAM+'.lef')]
    files=[mapping/'netlist.json',mapping/'electrical-repair/reference/netlist.json',
           mapping/'electrical-repair/receipt.json',mapping/'electrical-repair/proof.json',
           mapping/'electrical-repair/preparation.json',Path(__file__),*libpaths,*lefpaths]
    frozen={str(p.resolve()):sha(p) for p in files}
    # This report reads geometry only; SRAM and standard cells use different
    # Liberty power units, so the energy estimator's unit checks do not apply.
    liberty={k:scalar(body,'area') for p in libpaths for k,body in groups(p.read_text(),'cell')}
    require(liberty and all(math.isfinite(a) and a>0 for a in liberty.values()),'REPAIR_AREA_LIBRARY')
    a=flat(json.loads(files[1].read_text()),'RiscayMcuDigital')['cells']
    b=flat(json.loads(files[0].read_text()),'RiscayMcuDigital')['cells']
    proof=json.loads(files[3].read_text());prep=json.loads(files[4].read_text())
    result=dict(scope='LEF footprints and separate Liberty area totals; pre-placement; timing-unqualified',
        variant=json.loads((mapping/'mapping.json').read_text())['variant'],
        **summarize(a,b,proof,prep,liberty,lef_areas(lefpaths)),inputs_sha256=frozen)
    require(all(sha(Path(p))==h for p,h in frozen.items()),'REPAIR_AREA_INPUT_CHANGED')
    validate_receipt(mapping)
    write_json(output,result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mapping',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();print(json.dumps(report(a.mapping,a.output),indent=2))

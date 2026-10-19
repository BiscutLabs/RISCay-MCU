# SPDX-License-Identifier: Apache-2.0
"""A failing corner search, unchanged in-bounds search, and full-site rejection."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
from gf180_pnr import pnr_tool
from run_receipt import RunReceipt


def main():
    p=argparse.ArgumentParser()
    for n in ('old','new','source','output'):p.add_argument(n)
    a=p.parse_args();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=False)
    tools={k:pnr_tool(executable=getattr(a,k)) for k in ('old','new')}
    source=tools['new'].host_path(a.source)
    fixture=Path(__file__).with_name('dpl-search-control.tcl')
    binaries=[]
    for t in tools.values():
        binaries.extend(t.input_files())
        wrapped=t.host_path().with_name('.'+t.host_path().name+'-wrapped')
        if wrapped.is_file():binaries.append(wrapped)
    receipt=RunReceipt(out/'receipt.json',inputs=[fixture,source/'src/dpl/test/simple01.def',
        source/'test/Nangate45/Nangate45.lef'],tools=[Path(__file__),*binaries])
    results={};status='fail'
    try:
        for label,t in tools.items():
            for scenario in ('corner','inside','full'):
                key=label+'-'+scenario;driver=out/(key+'.tcl');log=out/(key+'.log')
                expect_pass=scenario=='inside' or (label=='new' and scenario=='corner')
                diagnostic='' if expect_pass else ('DPL-0017' if scenario=='corner' else 'DPL-0016')
                driver.write_text(f'set fixture_source {{{a.source}}}\nset scenario {scenario}\nset expected_rejection {{{diagnostic}}}\nsource {{{t.path(fixture)}}}\n')
                code=receipt.command(t.command(['-exit',t.path(driver)]),cwd=ROOT,log=log)
                text=log.read_text();match=re.search(r'DPL_CONTROL_PASS ([^\n]+)',text)
                rejected=re.search(r'DPL_CONTROL_REJECTED ([^\n]+)',text)
                results[key]=dict(code=code,placement=match[1] if match else None,rejection=rejected[1] if rejected else None)
                if expect_pass:
                    assert code==0 and match and rejected is None,'DPL_CONTROL_UNEXPECTED_FAILURE_'+key
                else:
                    assert code==0 and match is None and rejected and diagnostic in rejected[1],'DPL_CONTROL_REJECTION_MISSING_'+key
        assert results['old-inside']['placement']==results['new-inside']['placement'],'DPL_CONTROL_IN_BOUNDS_CHANGED'
        status='pass'
    finally:
        (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        receipt.finish(outputs=[f for f in out.iterdir() if f.is_file()],status=status)


if __name__=='__main__':main()

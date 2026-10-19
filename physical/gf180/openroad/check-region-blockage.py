# SPDX-License-Identifier: Apache-2.0
"""Run an unchanged tiny upstream design through old/new regional accounting."""
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
    fixture=Path(__file__).with_name('region-blockage-control.tcl')
    inputs=[fixture,*[source/'src/gpl/test'/n for n in ('nangate45.lef','simple01.def')]]
    binaries=[]
    for t in tools.values():
        binaries.extend(t.input_files())
        wrapped=t.host_path().with_name('.'+t.host_path().name+'-wrapped')
        if wrapped.is_file():binaries.append(wrapped)
    receipt=RunReceipt(out/'receipt.json',inputs=inputs,tools=[Path(__file__),*binaries])
    results={};status='fail'
    try:
        for label,t in tools.items():
            results[label]={}
            for scenario in ('base','far','partial','fixed-partial','fixed-overlap','top-far','power-domain'):
                key=label+'-'+scenario;driver=out/(key+'.tcl');log=out/(key+'.log')
                driver.write_text(f'set fixture_source {{{a.source}}}\nset scenario {scenario}\nsource {{{t.path(fixture)}}}\n')
                if receipt.command(t.command(['-exit',t.path(driver)]),cwd=ROOT,log=log):
                    raise ValueError('REGION_CONTROL_TOOL_FAILED_'+key)
                text=log.read_text()
                if 'REGION_ACCOUNTING_CONTROL_COMPLETE' not in text:raise ValueError('REGION_CONTROL_INCOMPLETE')
                if label=='new':
                    expected=scenario not in ('top-far','power-domain')
                    assert ('MODULE_REGION_ACCOUNTING corrected-uniform-physical' in text)==expected,'REGION_CONTROL_MODE'
                regional={}
                for name,body in re.findall(r'Initialize Region: ([^\n]+)\n(.*?)(?=Initialize Region:|\Z)',text,re.S):
                    m=re.search(r'Fixed instances area:\s+([\d.]+)',body)
                    if m:regional[name]=float(m[1])
                results[label][scenario]=dict(regions=regional,fixed_cell_um2=float(re.search(r'CONTROL_FIXED_AREA ([\d.]+)',text)[1]))
        def area(label,case):return results[label][case]['regions']['test_group']
        expected=results['new']['base']['fixed_cell_um2']
        assert abs(area('new','base')-expected)<.002,'REGION_FIXED_CELL_MISSING'
        assert abs(area('new','far')-area('new','base'))<.002,'REGION_OUTSIDE_BLOCKAGE_COUNTED'
        assert abs(area('new','partial')-area('new','base')-1.14*2.8)<.002,'REGION_PARTIAL_BLOCKAGE_NOT_CLIPPED'
        assert abs(area('new','fixed-partial')-.38*1.4)<.002,'REGION_PARTIAL_FIXED_CELL_NOT_CLIPPED'
        assert abs(area('new','fixed-overlap')-expected)<.002,'REGION_FIXED_BLOCKAGE_DOUBLE_COUNTED'
        assert area('old','far')>area('old','base')+1,'REGION_NEGATIVE_CONTROL_NOT_DETECTED'
        assert results['new']['top-far']['regions']==results['old']['top-far']['regions'],'REGION_TOP_ACCOUNTING_CHANGED'
        assert results['new']['power-domain']['regions']==results['old']['power-domain']['regions'],'REGION_POWER_DOMAIN_ACCOUNTING_CHANGED'
        status='pass'
    finally:
        (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        receipt.finish(outputs=[f for f in out.iterdir() if f.is_file()],status=status)


if __name__=='__main__':main()

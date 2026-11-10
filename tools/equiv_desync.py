# SPDX-License-Identifier: Apache-2.0
"""Sequential equivalence with external ideal clocks, before physical mapping.

Inputs must already expose the same ideal clock ports. No regex rewriting,
unmatched-point waiver, reset removal, or output exclusion is supported.
Generator/wake behavior is checked separately in the physical variant tests.
"""
import argparse
import json
import re
from pathlib import Path
from gf180_physical import ROOT
from physical_tools import tool
from run_receipt import RunReceipt


def script(gold, gate, top, yosys, gate_top=None):
    gate_top=gate_top or top
    if not top.replace('_','').isalnum(): raise ValueError('EQUIV_TOP_NAME')
    if not gate_top.replace('_','').isalnum(): raise ValueError('EQUIV_TOP_NAME')
    q = lambda p: '"' + yosys.path(p) + '"'
    # clk2fflogic preserves edge detection and asynchronous reset in one formal
    # timestep model; async2sync would instead assume synchronous reset sampling.
    return (f'read_verilog -sv {q(gold)}\nprep -top {top} -flatten\nmemory_map\nclk2fflogic\nopt_clean\n'
        f'rename {top} gold\ndesign -stash gold\n'
        f'read_verilog -sv {q(gate)}\nprep -top {gate_top} -flatten\nmemory_map\nclk2fflogic\nopt_clean\n'
        f'rename {gate_top} gate\ndesign -stash gate\n'
        'design -copy-from gold =A:blackbox\n'
        'design -copy-from gold -as gold gold\ndesign -copy-from gate -as gate gate\n'
        'equiv_make gold gate equiv\nhierarchy -check -top equiv\nopt_merge\nequiv_struct\nequiv_simple\n'
        'equiv_induct -seq 8\nequiv_status -assert\n')


def export_inputs(path):
    if not path.is_dir(): return [path],None
    metadata=[p for p in (path/'clocked.json',path/'desync.json') if p.is_file()]
    if len(metadata)!=1:raise ValueError('EQUIV_EXPORT_METADATA')
    data=json.loads(metadata[0].read_text())
    files=[path/s.strip() for s in (path/'filelist.f').read_text().splitlines() if s.strip()]
    if not files or any(not f.resolve().is_relative_to(path.resolve()) for f in files):
        raise ValueError('EQUIV_EXPORT_SOURCE')
    return files+[metadata[0],path/'filelist.f'],data['top']


def run(gold, gate, out, top='RiscayMcuDigital'):
    out.mkdir(parents=True,exist_ok=False)
    yosys=tool('yosys')
    gold_files,gold_top=export_inputs(gold); gate_files,gate_top=export_inputs(gate)
    converter=tool('sv2v') if gold_top or gate_top else None
    receipt=RunReceipt(out/'receipt.json',inputs=gold_files+gate_files,
        tools=[Path(__file__),*yosys.input_files(),*(converter.input_files() if converter else [])])
    for side,files,name in [('gold',gold_files,gold_top),('gate',gate_files,gate_top)]:
        if name:
            converted=out/(side+'.v')
            code=receipt.command(converter.command(['-DSYNTHESIS',*[converter.path(p) for p in files if p.suffix in ('.sv','.v')]],timeout=180),cwd=ROOT,log=converted)
            if code:
                receipt.finish(outputs=[converted],status='fail')
                raise ValueError('DESYNC_EQUIVALENCE_CONVERSION')
            if side=='gold':gold=converted
            else:gate=converted
    ys=out/'equiv.ys'; ys.write_text(script(gold,gate,gold_top or top,yosys,gate_top or top))
    code=receipt.command(yosys.command(['-s',yosys.path(ys)],timeout=1200),cwd=ROOT,log=out/'equiv.log')
    text=(out/'equiv.log').read_text()
    if not re.search(r'Found [1-9][0-9]* \$equiv cells in equiv:',text) or 'Equivalence successfully proven!' not in text:code=1
    receipt.finish(outputs=[ys,out/'equiv.log',gold,gate],status='fail' if code else 'pass')
    if code: raise ValueError('DESYNC_EQUIVALENCE_FAILED')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('gold',type=Path);p.add_argument('gate',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--top',default='RiscayMcuDigital')
    a=p.parse_args();run(a.gold.resolve(),a.gate.resolve(),a.output.resolve(),a.top)

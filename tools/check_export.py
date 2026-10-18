# SPDX-License-Identifier: Apache-2.0
"""Validate a generated native structural audit and record one run receipt.

No generated Verilog or testbench is rewritten. Dynamic chip simulations, RDC
and mapped physical proofs are separate gates; this command claims only the
checks it actually runs. Old probe/attestation switches are intentionally gone.
"""
import argparse
import json
from pathlib import Path
from export_structure import validate, inside
from run_receipt import RunReceipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=args.export.resolve();args.output.mkdir(parents=True,exist_ok=False)
    inputs=[root/n for n in ('contract.json','structure.json','design.hw.mlir','ports.json','filelist.f')]
    inputs += [inside(root,s.strip()) for s in (root/'filelist.f').read_text().splitlines() if s.strip()]
    repository=Path(__file__).resolve().parents[1]
    inputs += [repository/'soc/sram-lock.json',*repository.glob('soc/src/main/resources/riscay/sram/*.v')]
    run=RunReceipt(args.output/'receipt.json',inputs=inputs,
                   tools=[Path(__file__),Path(__file__).with_name('export_structure.py'),
                          Path(__file__).with_name('run_receipt.py'),Path(__file__).with_name('sram_assets.py')])
    result=args.output/'structure.json'
    try:
        report=validate(root)
    except Exception as error:
        result.write_text(json.dumps(dict(status='fail',diagnostic=str(error)),indent=2)+'\n')
        run.finish(outputs=[result],status='fail')
        raise
    result.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    run.finish(outputs=[result],coverage=dict(scope=report['scope'],top=report['top']))
    print(f"STRUCTURE_PASS: {report['top']}; {report['scope']}")


if __name__=='__main__':main()

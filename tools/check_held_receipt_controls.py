# SPDX-License-Identifier: Apache-2.0
"""Negative controls against actual compiled C1b receivers and SRAM capture cones."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from check_held_receipts import catalog, validate_held_receipts
from reset_bridge_proof import Cone, prove_sram_capture, sram_capacities, saved_sram_address_width


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export',type=Path);parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    sys.path.insert(0,str(args.library/'tools'))
    spec=importlib.util.spec_from_file_location('library_checker',args.library/'tools/check_export.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    manifest=json.loads((args.export/'contract.json').read_text())['manifest']
    scopes=module.read_vvp((args.export/'contract_probe.vvp').read_text())
    bindings=validate_held_receipts(manifest,args.export,scopes)
    records=[]
    def reject(name,run,expected):
        try: run()
        except ValueError as error:
            if not str(error).startswith(expected): raise
            records.append(dict(fault=name,rejected=str(error)))
        else: raise ValueError('HELD_CONTROL_SURVIVED:'+name)
    with tempfile.TemporaryDirectory() as tmp:
        directory=Path(tmp)
        for p in args.export.glob('*ServiceReplyReceipt*.sv'):
            (directory/p.name).write_bytes(p.read_bytes())
        for item in catalog(manifest):
            node=item['node'];path=node['rtl_path'];source,reg=item['storage'].rsplit('.',1)
            for fault in ('payload-bank','source-width','source-kind'):
                mutant=copy.deepcopy(scopes)
                if fault=='payload-bank':mutant[path]['registers']['data']=item['width']
                elif fault=='source-width':
                    mutant[source]['parameters']['WIDTH']=str(item['width']+1)
                else:mutant[source]['model']='UnretainedCombinationalSource'
                reject(path+':'+fault,lambda:validate_held_receipts(manifest,directory,mutant),'HELD_RECEIPT_')
            rtl=directory/(scopes[path]['model']+'.sv');original=rtl.read_text()
            # Modify the actual payload assignment, preserving module/control shape.
            mutant,count=re.subn(r'(assign out_bits\w*\s*=\s*)(in_bits\w*)(;)',r'\1~\2\3',original,count=1)
            if count!=1:raise ValueError('HELD_CONTROL_ASSIGNMENT_ANCHOR')
            rtl.write_text(mutant)
            reject(path+':inverted-payload',lambda:validate_held_receipts(manifest,directory,scopes),'SERVICE_REPLY_RTL_PAYLOAD_')
            rtl.write_text(original)
        validate_held_receipts(manifest,directory,scopes)
    graph_path=args.export/'reset-crossings/netlist.json'
    graph=json.loads(graph_path.read_text())['modules'][manifest['top']]
    inventory_path=args.export/'sram.json'
    capacities=sram_capacities(json.loads(inventory_path.read_text()),manifest['top'])
    for bank in ('program','ram'):
        prefix='fabric_'+bank+'_';access='ca_child_'+bank+'_access'
        cone=Cone(graph);state=cone.flop(prefix+'state')[1]['connections'];clock=state['CLK'];reset=state['ARST']
        por=lambda r,c:r==reset and c==clock
        prove_sram_capture(graph,bank,por,capacities[bank])
        for fault in ('saved-address-too-short','saved-address-upper-source'):
            mutant=copy.deepcopy(graph);c=Cone(mutant);name=prefix+'saved_address'
            reg=c.drivers[c.bits(name)[0]][0];pins=mutant['cells'][reg]['connections']
            if fault=='saved-address-too-short':
                mutant['netnames'][name]['bits']=list(c.bits(name)[:-1])
                pins['Q']=list(pins['Q'][:-1]);pins['D']=list(pins['D'][:-1])
            else:
                pins['D'][-1]=c.bits(access+'.ca_child_byte_request_0.in_bits_address')[31]
            reject(bank+':'+fault,lambda:prove_sram_capture(mutant,bank,por,capacities[bank]),'RDC_SRAM_')
        for fault in ('receipt-clock','saved-clock','saved-edge','wrong-ready','wrong-select','wrong-tag','capture-unconditionally'):
            mutant=copy.deepcopy(graph);c=Cone(mutant)
            if fault=='receipt-clock':mutant['netnames'][access+'.ca_child_byte_request_0.clock']['bits']=['0']
            elif fault=='wrong-ready':mutant['netnames'][access+'.ca_child_byte_request_0.out_ready']['bits']=['1']
            elif fault=='wrong-select':mutant['netnames'][prefix+'selected']['bits']=['1','1']
            else:
                name=prefix+('tag' if fault=='wrong-tag' else 'saved_address')
                reg=c.drivers[c.bits(name)[0]][0];cell=mutant['cells'][reg]
                if fault=='saved-clock':cell['connections']['CLK']=['0']
                elif fault=='saved-edge':cell['parameters']['CLK_POLARITY']='0'
                elif fault=='wrong-tag':cell['connections']['D']=['0','0']
                else:cell['connections']['D']=c.bits(access+'.ca_child_byte_request_0.in_bits_address')
            reject(bank+':'+fault,lambda:prove_sram_capture(mutant,bank,por,capacities[bank]),'RDC_SRAM_')
        for lane in range(4):
            for field,width in dict(address=32,write=1,data=8,enable=1).items():
                for fault in ('source-alias','capture-bit'):
                    mutant=copy.deepcopy(graph);c=Cone(mutant)
                    if fault=='source-alias':
                        name=access+f'.ca_child_byte_request_{lane}.in_bits_{field}'
                        mutant['netnames'][name]['bits']=c.bits(access+f'.ca_child_native.byteRequest_{(lane+1)%4}_bits_{field}')
                    else:
                        reg=c.drivers[c.bits(prefix+'saved_'+field)[0]][0]
                        mutant['cells'][reg]['connections']['D'][lane%(saved_sram_address_width(capacities[bank]) if field=='address' else width)]='0'
                    reject(f'{bank}:{lane}:{field}:{fault}',lambda:prove_sram_capture(mutant,bank,por,capacities[bank]),'RDC_SRAM_')
    result=dict(status='PASS',scope='structural faults; not physical setup/hold qualification',
        bindings=len(bindings),negative_controls=len(records),records=records,
        inputs={str(p):sha(p) for p in [args.export/'contract.json',args.export/'contract_probe.vvp',graph_path,inventory_path,
                Path(__file__),Path(__file__).with_name('check_held_receipts.py'),Path(__file__).with_name('reset_bridge_proof.py')]})
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','bindings','negative_controls')}))


if __name__=='__main__':main()

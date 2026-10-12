# SPDX-License-Identifier: Apache-2.0
"""Structural-policy sensitivity tests; behavioral/pin controls are separate.

Without arguments, run portable unit tests. With --export DIR (repeatable),
test actual exported metadata and every named owner port/parameter connection,
plus hidden writers and the resolved BD buffer body. No simulation PASS is
inferred from these deliberately structural controls.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

from check_frame_store import canonical_rtl, rtl_fingerprint, validate_frame_store, validate_frame_store_metadata


class FrameStorePolicyTests(unittest.TestCase):
    def test_only_format_and_exact_module_clone_families_are_normalized(self):
        a = 'module ClickFrameStore; LongHoldBuffer_7 b(.q(q)); endmodule'
        b = '/* header */ module ClickFrameStore_19; // clone\n LongHoldBuffer b ( .q(q) ); endmodule'
        self.assertEqual(canonical_rtl(a), canonical_rtl(b))
        self.assertNotEqual(canonical_rtl(a), canonical_rtl(a.replace('b(', 'b_7(')))
        self.assertNotEqual(canonical_rtl(a), canonical_rtl(a.replace('LongHoldBuffer_7', 'LongHoldBufferOther_7')))

    def test_writers_pins_expressions_and_widths_are_never_erased(self):
        a = "module FourPhaseFrameStore(input reset); Gate #(.WIDTH(337)) g(.a(x),.q(q)); endmodule"
        for old, new in [('reset','applicationReset'), ('337','336'), ('.a(x)', '.a(~x)'),
                         ('.q(q)', '.q(other)'), ('endmodule','assign q=0; endmodule')]:
            self.assertNotEqual(rtl_fingerprint(a),rtl_fingerprint(a.replace(old,new)))

    def test_model_identity_is_closed(self):
        for name in ('FrameStore','ClickFrameStoreRTZ','FourPhaseFrameStore_','ClickFrameStore_1Hidden'):
            with self.assertRaisesRegex(ValueError,'^FRAME_STORE_OWNER$'):
                validate_frame_store_metadata(dict(module=name))

    def test_capacity_is_exact_integer(self):
        for capacity in (True,4.0,'4',2,None):
            with self.assertRaisesRegex(ValueError,'^FRAME_STORE_CAPACITY$'):
                validate_frame_store_metadata(dict(module='ClickFrameStore',capacity=capacity))

    def test_no_application_reset_owner_is_accepted(self):
        with self.assertRaisesRegex(ValueError,'^FRAME_STORE_POR_DOMAIN$'):
            validate_frame_store_metadata(dict(module='FourPhaseFrameStore',capacity=4,reset_domain='application'))


def nodes(node):
    if node['module'].startswith(('FourPhaseFrameStore','ClickFrameStore')):
        yield node
    for child in node.get('children',[]):
        yield from nodes(child['contract'])


def reject(function, expected):
    try:
        function()
    except ValueError as error:
        if not str(error).startswith('FRAME_STORE_'+expected):
            raise AssertionError(('UNRELATED_POLICY_FAILURE',expected,str(error))) from error
        return str(error)
    raise AssertionError('POLICY_MUTANT_ACCEPTED:'+expected)


def set_at(root,path,value):
    for key in path[:-1]:root=root[key]
    root[path[-1]]=value


def metadata_mutants(node):
    yield ('capacity',),3,'CAPACITY'
    yield ('reset_domain',),'application','POR_DOMAIN'
    yield ('children',),node['children']+[{}],'CHILD_INVENTORY'
    for i,c in enumerate(node['channels']):
        for key,value in [('protocol','rtz-adapter'),('role','wrong'),('reset_domain','application'),
                          ('request','wrong'),('data','wrong'),('acknowledge','wrong'),('token_contract','lossy')]:
            yield ('channels',i,key),value,'CHANNEL:'
        yield ('channels',i,'phases'),[],'CHANNEL_ENVIRONMENT:'
        yield ('channels',i,'environment'),'unconstrained','CHANNEL_ENVIRONMENT:'
        for j,f in enumerate(c['layout']):
            for key,value in [('lsb',f['lsb']+1),('width',f['width']+1),('source','~|Wrong>payload'),
                              ('field','bits.wrong'),('signed',True)]:
                yield ('channels',i,'layout',j,key),value,'CHANNEL:'
    for i,e in enumerate(node['endpoints']):
        for key,value,reason in [('width',True,'ENDPOINT_INVENTORY'),('width',e['width']+1,'ENDPOINT_INVENTORY'),
                                 ('source','~|Wrong>signal','ENDPOINT_SOURCE:'),('rtl_path','Wrong.probe','ENDPOINT_SOURCE:')]:
            yield ('endpoints',i,key),value,reason
    for i,p in enumerate(node['primitives']):
        reason='MARKER_PARAMETERS:' if p['model']=='ChiselAsyncTimingMarker_v1' else 'PRIMITIVE_PARAMETERS:'
        for key,value in p['parameters'].items():
            yield ('primitives',i,'parameters',key),str(int(value)+1),reason
    for i,t in enumerate(node['timing']):
        for key in t:
            yield ('timing',i,key),None,'TIMING'


def actual_controls(directory):
    directory=directory.resolve()
    manifest=json.loads((directory/'contract.json').read_text(encoding='utf-8'))['manifest']
    found=list(nodes(manifest['design']))
    assert len(found)==1,('OWNER_INVENTORY',directory,len(found))
    node=found[0]
    evidence=validate_frame_store(node,directory)
    checks=[]
    for path,value,reason in metadata_mutants(node):
        mutant=copy.deepcopy(node);set_at(mutant,path,value)
        error=reject(lambda:validate_frame_store(mutant,directory),reason)
        checks.append(dict(kind='metadata',path=list(path),value=value,error=error))
    original=Path.read_text
    for filename in evidence['files_sha256']:
        path=directory/filename
        body=original(path,encoding='utf-8')
        mutations=[('hidden-writer',body.replace('endmodule','assign unexpected_writer = 1\'b0; endmodule',1))]
        # Mutate the connection name, preserving the rest of the actual source.
        # Whole-body closure must reject every changed pin/parameter connection.
        for match in re.finditer(r'\.(\w+)\s*\(',body):
            start,end=match.span(1)
            mutations.append((f'connection-{start}-{match[1]}',body[:start]+'FAULT_'+body[start:end]+body[end:]))
        expected='RTL_FINGERPRINT:' if filename==node['module']+'.sv' else 'BD_BUFFER_RTL:'
        for name,mutant in mutations:
            assert mutant!=body
            def read(p,*args,**kwargs):
                return mutant if p.resolve()==path else original(p,*args,**kwargs)
            with patch.object(Path,'read_text',read):
                error=reject(lambda:validate_frame_store(node,directory),expected)
            checks.append(dict(kind='actual-rtl',file=filename,mutation=name,error=error,
                               mutant_sha256=hashlib.sha256(mutant.encode('utf-8')).hexdigest()))
    assert evidence==validate_frame_store(node,directory),'BASELINE_CHANGED'
    return dict(export=str(directory),baseline=evidence,rejected=len(checks),controls=checks)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export',type=Path,action='append',default=[])
    parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    if not args.export:
        unittest.main(argv=[sys.argv[0]])
        return
    assert args.out and not args.out.exists(),'NEW_OUTPUT_REQUIRED'
    result=dict(status='PASS',qualification='structural sensitivity only',exports=[actual_controls(d) for d in args.export])
    result['tool_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                          (Path(__file__),Path(__file__).with_name('check_frame_store.py'),Path(__file__).with_name('check_frame_receipt.py'))}
    args.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print('FRAME_STORE_POLICY_CONTROLS_PASS',sum(e['rejected'] for e in result['exports']))


if __name__=='__main__':main()

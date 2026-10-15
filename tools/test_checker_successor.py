"""Pure synthetic custody/binder controls; no simulator or compiler is invoked."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import checker_successor as successor
import check_quiescing_receipt_controls as controls

class CheckerSuccessorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.block = patch('subprocess.Popen', side_effect=AssertionError('NO_CHILD_PROCESS'))
        self.block.start(); self.addCleanup(self.block.stop)
        self.names = {'tools/check_reset_crossings.py', 'tools/quiescing_gate_control.py',
            'tools/check_quiescing_receipt_controls.py', 'verification/Scope.scala',
            'tools/fixtures/quiescing_receipt/required-suites.json'}
        for name in self.names:
            self.put(name, 'original '+name)
        original = self.snapshot()
        classes = {}
        for name in controls.REQUIRED_CLASSES:
            p = self.put('verification/target/scala-unit/classes/'+name, 'original class '+name)
            classes[p.relative_to(self.root).as_posix()] = successor.sha(p)
        self.iv = self.put('runtime/bin/iverilog.exe', 'original compiler')
        self.vvp = self.put('runtime/bin/vvp.exe', 'original simulator')
        self.ivl = self.put('runtime/lib/ivl/vvp.conf', 'original runtime')
        runtime = {str(p):successor.sha(p) for p in (self.iv,self.vvp,self.ivl)}
        self.base = self.root/'build/async-quiescing-receipt-production-r2'
        self.base.mkdir(parents=True)
        records = {}
        for field,name in [('before_sha256','regression-before.json'),
                           ('command_sha256','regression-command.json'),
                           ('preparation_sha256','preparation.json'),('log_sha256','regression.log')]:
            p = self.put(str((self.base/name).relative_to(self.root)), '{}')
            records[field] = successor.sha(p)
        self.execution = dict(sources_sha256=original, compiled_class_sha256=classes,
            tool_inputs_sha256=runtime, exports_sha256={'portable-r1/bd/top.sv':'a'*64}, **records)
        self.execution_path = self.base/'execution.json'
        self.write(self.execution_path,self.execution)
        self.manifest = self.root/'build/successor/checker-successor.json'
        delta = {}
        for name in sorted(successor.ADDITIONS | {'tools/check_reset_crossings.py'}):
            before = original.get(name)
            archive = None
            if before is not None:
                p = self.put('build/successor/original-sources/'+name, (self.root/name).read_text())
                archive = dict(path=str(p),sha256=before)
            self.put(name, 'current '+name); self.names.add(name)
            delta[name] = dict(before_sha256=before,after_sha256=successor.sha(self.root/name),original_archive=archive)
        copy_path = self.root/'build/copied/copy-receipt.json'
        self.write(copy_path,dict(status='BYTE_IDENTICAL_EXPORTED_INPUT_COPIES_ONLY',
            original_execution=str(self.execution_path), original_execution_sha256=successor.sha(self.execution_path),
            exports_sha256=self.execution['exports_sha256'], retained_failed_strict_sha256={'failed':'b'*64}))
        review = self.put('build/review.txt','synthetic review input, not approval')
        self.spec = dict(schema='riscay-c1e-checker-successor-v1',
            status='BOUND_CHECKER_ONLY_DELTA_REQUIRES_DOWNSTREAM_REVIEW',
            original_execution=dict(path=str(self.execution_path),sha256=successor.sha(self.execution_path)),
            copied_exports_receipt=dict(path=str(copy_path),sha256=successor.sha(copy_path)),
            delta=delta,current_sources_sha256=self.snapshot(),review_inputs_sha256={str(review):successor.sha(review)})
        self.write(self.manifest,self.spec)
        self.inv = patch.object(successor,'inventory',side_effect=lambda root:self.snapshot())
        self.inv.start();self.addCleanup(self.inv.stop)

    def put(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8');return p

    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')

    def snapshot(self):
        return {name:successor.sha(self.root/name) for name in self.names}

    def bind(self):
        self.write(self.manifest,self.spec)
        return successor.bind_sources(self.execution,self.root,self.manifest)

    def full_bind(self):
        self.write(self.manifest,self.spec)
        with patch.object(controls,'execution_header',return_value={'synthetic':'header boundary'}), \
             patch.object(controls,'required_inventory',return_value={'source_lf_sha256':{}}), \
             patch.object(controls,'REQUIRED_INVENTORY',self.root/'tools/fixtures/quiescing_receipt/required-suites.json'), \
             patch.object(controls,'helper_closure',return_value=[self.root/'tools/check_quiescing_receipt_controls.py']), \
             patch.object(controls.shutil,'which',side_effect=lambda n:str(self.iv if n=='iverilog' else self.vvp)):
            return controls.bind_execution(self.execution_path,self.root,self.manifest)

    def test_exact_delta_and_original_execution_unchanged(self):
        original=copy.deepcopy(self.execution);bound=self.bind()
        self.assertEqual(self.execution,original)
        self.assertEqual(bound['current_sources_sha256'],self.snapshot())
        self.assertIn(str(self.manifest),bound['records'])

    def test_original_four_tuple_is_preserved(self):
        old=copy.deepcopy(self.execution);result=self.full_bind()
        self.assertEqual(len(result),4);self.assertEqual(result[0],old)
        self.assertEqual(self.execution,old)
        self.assertEqual(controls.current_sources(old,self.root,self.manifest),self.snapshot())

    def test_changed_class_rejected_by_original_binder(self):
        name=next(iter(self.execution['compiled_class_sha256']));self.put(name,'changed class')
        with self.assertRaisesRegex(ValueError,'CLASS_INVENTORY'):self.full_bind()

    def test_changed_runtime_rejected_by_original_binder(self):
        self.ivl.write_text('changed runtime')
        with self.assertRaises(ValueError):self.full_bind()

    def test_default_does_not_allow_checker_delta(self):
        with self.assertRaisesRegex(ValueError,'ORIGINAL_COMPLETE_SOURCE_INVENTORY'):
            successor.bind_sources(self.execution,self.root)

    def test_undeclared_source_added(self):
        self.put('tools/unreviewed.py','extra');self.names.add('tools/unreviewed.py')
        with self.assertRaisesRegex(ValueError,'COMPLETE_CURRENT_SOURCE_INVENTORY'):self.bind()

    def test_unchanged_scala_modified(self):
        self.put('verification/Scope.scala','changed RTL source')
        with self.assertRaisesRegex(ValueError,'COMPLETE_CURRENT_SOURCE_INVENTORY'):self.bind()

    def test_functional_helper_forbidden_even_with_hashes(self):
        name='tools/check_frame_store_controls.py'
        self.spec['delta'][name]=copy.deepcopy(self.spec['delta']['tools/check_reset_crossings.py'])
        with self.assertRaisesRegex(ValueError,'EXACT_CHECKER_ALLOWLIST'):self.bind()

    def test_gate_scope_enforced_by_full_source_binder_with_matching_hashes(self):
        name='tools/quiescing_gate_control.py'
        old='import re\nFATAL = "capture"\ndef prove_graph(module): return 0\ndef mutate(texts, manifest, variant): return texts\n'
        archived=self.put('build/successor/original-sources/'+name,old)
        self.execution['sources_sha256'][name]=successor.sha(archived)
        self.write(self.execution_path,self.execution)
        self.spec['original_execution']['sha256']=successor.sha(self.execution_path)
        copy_path=Path(self.spec['copied_exports_receipt']['path']);copies=successor.read(copy_path)
        copies['original_execution_sha256']=successor.sha(self.execution_path);self.write(copy_path,copies)
        self.spec['copied_exports_receipt']['sha256']=successor.sha(copy_path)
        for text,allowed in ((old.replace('return 0','return 1'),True),
                             (old.replace('return texts','return {}'),False)):
            self.put(name,text)
            self.spec['delta'][name]=dict(before_sha256=successor.sha(archived),after_sha256=successor.sha(self.root/name),
                original_archive=dict(path=str(archived),sha256=successor.sha(archived)))
            self.spec['current_sources_sha256']=self.snapshot()
            if allowed:self.bind()
            else:
                with self.assertRaisesRegex(ValueError,'SOURCE_SCOPE_PROTECTED_AST'):self.bind()

    def test_scala_delta_forbidden(self):
        self.spec['delta']['verification/Scope.scala']=copy.deepcopy(self.spec['delta']['tools/check_reset_crossings.py'])
        with self.assertRaisesRegex(ValueError,'EXACT_CHECKER_ALLOWLIST'):self.bind()

    def test_wrong_original_digest(self):
        self.spec['delta']['tools/check_reset_crossings.py']['before_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'EXACT_OLD_NEW_HASH'):self.bind()

    def test_wrong_current_digest(self):
        self.spec['delta']['tools/check_reset_crossings.py']['after_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'CURRENT_CHECKER_HASH'):self.bind()

    def test_old_archive_corrupted(self):
        p=self.spec['delta']['tools/check_reset_crossings.py']['original_archive']['path'];Path(p).write_text('bad old bytes')
        with self.assertRaisesRegex(ValueError,'FILE_HASH'):self.bind()

    def test_added_helper_omitted(self):
        del self.spec['delta']['tools/checker_successor.py']
        with self.assertRaisesRegex(ValueError,'EXPLICIT_NEW_HELPER_AND_TEST'):self.bind()

    def test_current_inventory_forged(self):
        self.spec['current_sources_sha256']['verification/Scope.scala']='0'*64
        with self.assertRaisesRegex(ValueError,'COMPLETE_CURRENT_SOURCE_INVENTORY'):self.bind()

    def test_original_execution_changed(self):
        self.execution_path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'FILE_HASH'):self.bind()

    def test_copied_export_manifest_wrong_original(self):
        p=Path(self.spec['copied_exports_receipt']['path']);j=successor.read(p)
        j['original_execution_sha256']='0'*64;self.write(p,j)
        self.spec['copied_exports_receipt']['sha256']=successor.sha(p)
        with self.assertRaisesRegex(ValueError,'COPIED_EXPORT_ANCESTRY'):self.bind()

    def test_review_input_changed(self):
        p=Path(next(iter(self.spec['review_inputs_sha256'])));p.write_text('changed')
        with self.assertRaisesRegex(ValueError,'FILE_HASH'):self.bind()

    def test_duplicate_manifest_key(self):
        self.manifest.write_text('{"schema":1,"schema":2}')
        with self.assertRaisesRegex(ValueError,'DUPLICATE_JSON_KEY'):
            successor.bind_sources(self.execution,self.root,self.manifest)

class ExactSourceScopeTests(unittest.TestCase):
    def check(self,name,old,new):
        with tempfile.TemporaryDirectory() as folder:
            before=Path(folder)/'before.py';after=Path(folder)/'after.py'
            before.write_text(old,encoding='utf-8');after.write_text(new,encoding='utf-8')
            successor.source_scope(name,before,after)

    def gate(self):
        return ('import re\nFATAL = "capture"\ndef prove_graph(module): return 0\n'
                'def validate_testbench(text): return text\ndef mutate(texts, manifest, variant): return texts\n')

    def test_gate_exact_scope_accepts_comments_and_proof_body_only(self):
        old=self.gate();self.check('tools/quiescing_gate_control.py',old,'# position is irrelevant\n\n'+old.replace('return 0','return 1'))

    def test_gate_fixture_mutation_import_constant_extra_and_duplicate_reject(self):
        old=self.gate()
        mutants=[old.replace('return text\n','return None\n'),old.replace('return texts\n','return {}\n'),
                 old.replace('import re','import os'),old.replace('"capture"','"waived"'),
                 old+'def unrelated(): return 1\n',old+'def prove_graph(module): return 2\n',
                 old.replace('def prove_graph','async def prove_graph'),old.replace('def prove_graph','def renamed')]
        for text in mutants:
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'SOURCE_SCOPE_'):
                self.check('tools/quiescing_gate_control.py',old,text)

    def frame(self):
        old='import re\nPOLICY = "exact"\ndef assertion_wrapper_policy(x): return 0\ndef assertion_execution_policy(x): return x\n'
        new=old.replace('return 0','return 1')+'def coordinated_request_assertion_model(directory, model, diagnostic): return True\n'
        return old,new

    def test_frame_exact_existing_and_single_added_function_scope(self):
        old,new=self.frame();self.check('tools/check_frame_integration.py',old,'\n# comment\n'+new)

    def test_frame_execution_policy_constant_import_missing_duplicate_reject(self):
        old,new=self.frame()
        mutants=[new.replace('return x','return None'),new.replace('"exact"','"waived"'),new.replace('import re','import os'),
                 old,new+'def coordinated_request_assertion_model(directory, model, diagnostic): return False\n',
                 new.replace('def assertion_wrapper_policy','def renamed')]
        for text in mutants:
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'SOURCE_SCOPE_'):
                self.check('tools/check_frame_integration.py',old,text)


if __name__=='__main__':
    unittest.main()

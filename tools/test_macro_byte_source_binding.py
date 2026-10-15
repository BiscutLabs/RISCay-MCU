# SPDX-License-Identifier: Apache-2.0
"""Independent failure controls for source/runtime capture binding; no hardware claims."""
from pathlib import Path
import json
import os
import tempfile
import unittest
import copy

import macro_byte_source_binding as binding
import check_macro_byte_owner as campaign


class SourceBindingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.export = self.root/'exports'
        self.export.mkdir()
        sources = {}
        for name in binding.SOURCE_FILES:
            p = self.root/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('fixture:' + name)
            os.utime(p, ns=(1000000000, 1000000000))
            sources[name] = dict(sha256=binding.sha(p), modified_ms=1000)
        classes = []
        for name, source in binding.CLASS_SOURCES.items():
            p = self.root/'target/classes'/(name.replace('.', '/')+'.class')
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(('class-fixture:' + name).encode())
            os.utime(p, ns=(2000000000, 2000000000))
            classes.append(dict(name=name, source=source, path=str(p), sha256=binding.sha(p), modified_ms=2000))
        jar = self.root/'library.jar'
        jar.write_bytes(b'test capture only; not a simulator model')
        self.record = dict(schema='riscay-experimental-macro-byte-cohort-v1', status='COMPLETE',
            started_ms=3000, finished_ms=4000, sources=sources, runtime_classes=classes,
            library_jar=dict(path=str(jar), sha256=binding.sha(jar)), exports=dict(bd='bd', click='click'))
        self.save()

    def save(self):
        (self.export/'source-manifest.json').write_text(json.dumps(self.record))

    def check(self):
        return binding.verify_capture(self.export, self.root)

    def test_complete_capture(self):
        record, hashes = self.check()
        self.assertEqual(record, self.record)
        self.assertGreater(len(hashes), len(binding.SOURCE_FILES))

    def test_incomplete_emission(self):
        self.record['status'] = 'CAPTURED'; self.save()
        with self.assertRaisesRegex(ValueError, 'INCOMPLETE_EMISSION'): self.check()

    def test_changed_source(self):
        (self.root/binding.SOURCE_FILES[1]).write_text('changed owner')
        with self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED'): self.check()

    def test_touched_source(self):
        p = self.root/binding.SOURCE_FILES[1]
        os.utime(p, ns=(1500000000, 1500000000))
        with self.assertRaisesRegex(ValueError, 'SOURCE_TIMESTAMP_CHANGED'): self.check()

    def test_source_after_generation_start(self):
        name = binding.SOURCE_FILES[1]; p = self.root/name
        os.utime(p, ns=(5000000000, 5000000000))
        self.record['sources'][name]['modified_ms'] = 5000; self.save()
        with self.assertRaisesRegex(ValueError, 'SOURCE_AFTER_EMISSION_START'): self.check()

    def test_old_compiled_class(self):
        c = self.record['runtime_classes'][0]
        os.utime(c['path'], ns=(500000000, 500000000))
        c['modified_ms'] = 500; self.save()
        with self.assertRaisesRegex(ValueError, 'CLASS_SOURCE_ORDER'): self.check()

    def test_changed_compiled_class(self):
        Path(self.record['runtime_classes'][0]['path']).write_bytes(b'new class')
        with self.assertRaisesRegex(ValueError, 'COMPILED_CLASS_CHANGED'): self.check()

    def test_missing_class(self):
        self.record['runtime_classes'].pop(); self.save()
        with self.assertRaisesRegex(ValueError, 'CLASS_INVENTORY'): self.check()

    def test_changed_library(self):
        Path(self.record['library_jar']['path']).write_bytes(b'other library')
        with self.assertRaisesRegex(ValueError, 'LIBRARY_JAR_CHANGED'): self.check()

    def test_missing_source(self):
        self.record['sources'].pop(binding.SOURCE_FILES[0]); self.save()
        with self.assertRaisesRegex(ValueError, 'SOURCE_INVENTORY'): self.check()

    def test_unrecorded_sram_family_member(self):
        c = next(c for c in self.record['runtime_classes'] if c['name'] == 'riscay.soc.SramByteRequest')
        (Path(c['path']).parent/'SramByteRequest$$anon$unexpected.class').write_bytes(b'unrecorded family member')
        with self.assertRaisesRegex(ValueError, 'SRAM_CLASS_FAMILY_INVENTORY:SramByteRequest'): self.check()


def sram_class_control(name, fault):
    def test(self):
        c = next(c for c in self.record['runtime_classes'] if c['name'] == name)
        if fault == 'omitted':
            self.record['runtime_classes'].remove(c); expected = 'CLASS_INVENTORY'
        elif fault == 'missing':
            Path(c['path']).unlink(); expected = 'COMPILED_CLASS_CHANGED'
        elif fault == 'changed':
            Path(c['path']).write_bytes(b'changed used SRAM bytecode'); expected = 'COMPILED_CLASS_CHANGED'
        else:
            os.utime(c['path'], ns=(500000000, 500000000))
            c['modified_ms'] = 500; expected = 'CLASS_SOURCE_ORDER'
        self.save()
        with self.assertRaisesRegex(ValueError, expected): self.check()
    return test


for class_name in binding.CLASS_SOURCES:
    if class_name.startswith('riscay.soc.') and binding.CLASS_SOURCES[class_name] == binding.SOURCE_FILES[4]:
        for fault_name in ('omitted', 'missing', 'changed', 'stale'):
            setattr(SourceBindingTest, 'test_sram_'+class_name.rsplit('.', 1)[1]+'_'+fault_name,
                    sram_class_control(class_name, fault_name))


class RootGraphTest(unittest.TestCase):
    """Synthetic syntax controls, not a library model or hardware qualification.

    Exercise the same inventory entry point used before compiling each campaign.
    Real emitted roots must also pass after every fresh Scala emission.
    """
    def fixture(self, variant):
        stem = 'Click' if variant == 'click' else 'FourPhase'
        top, owner = stem+'MacroByteFixture', stem+'MacroByteOwner'
        root = top+'.ca_child_byte_owner'
        primitives = [dict(id=key, rtl_path=root+'.inst_'+key, model=model,
            resource='chiselasync/sv/'+model+'.sv',
            parameters={'WIDTH': '42' if key == 'pin_payload' else '8'})
            for key, model in campaign.EXPECTED_PRIMITIVES[variant].items()]
        design = dict(module=top, rtl_path=top, primitives=[], children=[dict(id='byte_owner',
            contract=dict(module=owner, rtl_path=root, primitives=primitives, children=[]))])
        contract = dict(manifest=dict(top=top, design=design,
            resources={p['resource']:'synthetic-structural-control' for p in primitives}))
        sources = {model+'.sv':'module '+model+'(); endmodule\n'
                   for model in set(campaign.EXPECTED_PRIMITIVES[variant].values())}
        sources[binding.MACRO+'.sv'] = ('module '+binding.MACRO+'(); endmodule\n')*2
        sources[owner+'.sv'] = 'module '+owner+'(input reset);\n' + '\n'.join(
            p['model']+' #(.WIDTH(1)) '+p['rtl_path'].split('.')[-1]+' (.reset(reset));'
            for p in primitives) + '\nendmodule\n'
        sources[top+'.sv'] = ('module '+top+'(input reset);\n'+owner+' ca_child_byte_owner (.reset(reset));\n'
                             +binding.MACRO+' fixed_macro (.CLK(reset));\nendmodule\n')
        return contract, sources, '\n'.join(sources)+'\n', top, owner

    def check(self, variant, contract, sources, filelist):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder/'contract.json').write_text(json.dumps(contract))
            (folder/'filelist.f').write_text(filelist)
            for name, text in sources.items(): (folder/name).write_text(text)
            return campaign.inventory(folder, variant)

    def test_complete_native_roots(self):
        for v in ('bd', 'click'):
            with self.subTest(variant=v): self.check(v, *self.fixture(v)[:3])


def graph_control(fault):
    def test(self):
        for variant in ('bd', 'click'):
            with self.subTest(variant=variant):
                contract, sources, filelist, top, owner = self.fixture(variant)
                primitives = contract['manifest']['design']['children'][0]['contract']['primitives']
                if fault in ('extra_owner_child', 'extra_fixture_child'):
                    target = owner if fault == 'extra_owner_child' else top
                    # Reuse an allowed public type: no extra file is needed to
                    # expose an omitted instance, so this tests graph equality.
                    sources[target+'.sv'] = sources[target+'.sv'].replace('endmodule',
                        'ChiselAsyncEventRegister_v1 unregistered_state (.reset(reset));\nendmodule')
                    expected = 'EXACT_OWNER_INSTANCE_GRAPH' if target == owner else 'EXACT_FIXTURE_INSTANCE_GRAPH'
                elif fault in ('owner_storage', 'fixture_storage'):
                    target = owner if fault == 'owner_storage' else top
                    sources[target+'.sv'] = sources[target+'.sv'].replace('endmodule',
                        'reg state; always @(posedge reset) state <= ~state;\nendmodule')
                    expected = 'ORDINARY_STORAGE_IN_ROOT'
                elif fault == 'wrong_instance_type':
                    first = primitives[0]
                    sources[owner+'.sv'] = sources[owner+'.sv'].replace(first['model']+' #',
                        'ChiselAsyncEventRegister_v1 #', 1)
                    expected = 'EXACT_OWNER_INSTANCE_GRAPH'
                elif fault == 'metadata_omission':
                    primitives.pop(); expected = 'EXACT_NATIVE_PRIMITIVE_INVENTORY'
                elif fault == 'metadata_extra_id':
                    extra = copy.deepcopy(primitives[0]); extra['id'] = 'unreviewed_id'; primitives.append(extra)
                    expected = 'EXACT_NATIVE_PRIMITIVE_INVENTORY'
                elif fault == 'extra_module_file':
                    sources['Hidden.sv'] = 'module Hidden(); endmodule\n'
                    filelist += 'Hidden.sv\n'; expected = 'EXACT_COMPILED_MODULE_FILES'
                elif fault == 'extra_module_in_root':
                    sources[owner+'.sv'] += 'module Hidden(); endmodule\n'; expected = 'RTL_ROOT_MODULE_SET'
                elif fault == 'extra_filelist_entry':
                    filelist += 'Hidden.v\n'; expected = 'EXACT_COMPILED_FILELIST'
                elif fault == 'resource_wrong_type':
                    name = primitives[0]['model']
                    sources[name+'.sv'] = 'module Wrong(); endmodule\n'; expected = 'PUBLIC_RESOURCE_MODULE_TYPE'
                elif fault == 'missing_owner_instance':
                    name = primitives[0]['rtl_path'].split('.')[-1]
                    sources[owner+'.sv'] = '\n'.join(line for line in sources[owner+'.sv'].splitlines() if name not in line)
                    expected = 'EXACT_OWNER_INSTANCE_GRAPH'
                elif fault == 'duplicate_owner_instance':
                    line = sources[owner+'.sv'].splitlines()[1]
                    sources[owner+'.sv'] = sources[owner+'.sv'].replace('endmodule', line+'\nendmodule')
                    expected = 'RTL_DUPLICATE_INSTANCE'
                elif fault == 'wrong_fixture_owner_type':
                    sources[top+'.sv'] = sources[top+'.sv'].replace(owner+' ca_child', 'ChiselAsyncEventRegister_v1 ca_child')
                    expected = 'EXACT_FIXTURE_INSTANCE_GRAPH'
                elif fault == 'generate_child':
                    sources[owner+'.sv'] = sources[owner+'.sv'].replace('endmodule',
                        'generate if (1) begin ChiselAsyncEventRegister_v1 hidden (.reset(reset)); end endgenerate\nendmodule')
                    expected = 'RTL_STATEMENT_END'
                else:
                    raise AssertionError(fault)
                with self.assertRaisesRegex((ValueError, AssertionError), expected):
                    self.check(variant, contract, sources, filelist)
    return test


for fault in ('extra_owner_child', 'extra_fixture_child', 'owner_storage', 'fixture_storage',
              'wrong_instance_type', 'metadata_omission', 'metadata_extra_id', 'extra_module_file',
              'extra_module_in_root', 'extra_filelist_entry', 'resource_wrong_type',
              'missing_owner_instance', 'duplicate_owner_instance', 'wrong_fixture_owner_type', 'generate_child'):
    setattr(RootGraphTest, 'test_'+fault, graph_control(fault))


if __name__ == '__main__':
    unittest.main()

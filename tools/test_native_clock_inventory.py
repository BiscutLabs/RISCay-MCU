# SPDX-License-Identifier: Apache-2.0
import copy
import unittest
from check_native_clock_inventory import native_clock_inventory


class NativeClockInventoryTest(unittest.TestCase):
    def fixture(self):
        native=dict(module='ClickSram',rtl_path='Top.native',children=[],
                    primitives=[dict(rtl_path='Top.native.payload',model='ChiselAsyncEventRegister_v1')])
        manifest=dict(design=dict(module='Top',rtl_path='Top',children=[dict(contract=native)]))
        scopes={'Top':dict(registers=dict(service=1)), 'Top.native':dict(registers={}),
                'Top.native.payload':dict(model='ChiselAsyncEventRegister_v1',registers=dict(q=42)),
                'Top.native.unregistered_child':dict(registers={})}
        return manifest,scopes

    def test_native_primitives_and_explicit_service_shell_are_separate(self):
        m,s=self.fixture()
        self.assertEqual(native_clock_inventory(m,s)['checked'],['Top.native','Top.native.unregistered_child'])

    def test_clocked_state_cannot_hide_in_an_unregistered_descendant(self):
        m,s=self.fixture()
        for path in ('Top.native','Top.native.unregistered_child'):
            for bad in (dict(registers=dict(accidental=1)),dict(memories=dict(accidental=32)),dict(ports=dict(clock={}))):
                mutant=copy.deepcopy(s);mutant[path].update(bad)
                with self.assertRaisesRegex(ValueError,'NATIVE_CLOCKED_STATE'):
                    native_clock_inventory(m,mutant)

    def test_missing_compiled_inventory_is_not_a_pass(self):
        m,_=self.fixture()
        with self.assertRaisesRegex(ValueError,'NATIVE_CLOCK_INVENTORY_MISSING_ROOT'):
            native_clock_inventory(m,{})

    def test_clocked_primitive_cannot_use_a_native_looking_name(self):
        m,s=self.fixture()
        m['design']['children'][0]['contract']['primitives'][0]['model']='ChiselAsyncClockedHelper_v1'
        s['Top.native.payload']['model']='ChiselAsyncClockedHelper_v1'
        with self.assertRaisesRegex(ValueError,'NATIVE_CLOCK_PRIMITIVE_KIND'):
            native_clock_inventory(m,s)

    def test_primitive_binding_and_descendants_are_closed(self):
        m,s=self.fixture();s['Top.native.payload']['model']='ClockedHelper'
        with self.assertRaisesRegex(ValueError,'NATIVE_CLOCK_PRIMITIVE_BINDING'):
            native_clock_inventory(m,s)
        m,s=self.fixture();s['Top.native.payload.hidden']=dict(registers=dict(q=32))
        with self.assertRaisesRegex(ValueError,'NATIVE_CLOCK_PRIMITIVE_DESCENDANT'):
            native_clock_inventory(m,s)

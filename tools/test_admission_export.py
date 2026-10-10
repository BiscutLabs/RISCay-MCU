# SPDX-License-Identifier: Apache-2.0
"""Constant credit payloads require an exact elaborated driver, not inactivity."""
import copy
import unittest
from check_admission_export import literal_nets, admission_probe
from check_export import validate_native_click


class AdmissionExportTest(unittest.TestCase):
    def fixture(self):
        scopes={'ClickCompletion':{'model':'ClickCompletion'}}
        text='''S_a .scope module, "ClickCompletion" "ClickCompletion" 1 1;
L_a .functor BUFT 1, C4<0>, C4<0>, C4<0>, C4<0>;
v_a .net "creditReturn_bits", 0 0, L_a;  1 drivers
'''
        manifest={'top':'ClickCompletion','design':{'module':'ClickCompletion','children':[],
            'endpoints':[{'id':'creditReturn_data','width':1,'rtl_path':'ClickCompletion.creditReturn_bits'}]}}
        probe='''task check; begin
end endtask
if (ones_7 !== 1'h1 || zeros_7 !== 1'h1) $fatal(1, "INACTIVE_ENDPOINT:ClickCompletion.creditReturn_bits");
if (ones_8 !== 1'h1 || zeros_8 !== 1'h1) $fatal(1, "INACTIVE_ENDPOINT:ClickCompletion.dynamic");
'''
        return text,scopes,manifest,probe

    def test_only_exact_single_scalar_zero_driver_is_classified(self):
        text,scopes,m,p=self.fixture()
        result=admission_probe(p,m,literal_nets(text,scopes))
        self.assertIn("ones_7 !== 1'h0 || zeros_7 !== 1'h1",result)
        self.assertIn("ones_8 !== 1'h1 || zeros_8 !== 1'h1",result)
        self.assertIn('ADMISSION_LITERAL_VALUE',result)
        self.assertNotIn('force ',result)
        alias=literal_nets(text.replace('1 drivers','alias, 1 drivers'),{'ClickCompletion':{}})
        self.assertEqual(admission_probe(p,m,alias),result)
        for changed in (text.replace('C4<0>, C4<0>, C4<0>, C4<0>','C4<1>, C4<0>, C4<0>, C4<0>'),
                        text.replace('C4<0>, C4<0>, C4<0>, C4<0>','C4<x>, C4<0>, C4<0>, C4<0>'),
                        text.replace('1 drivers','2 drivers'),text.replace('L_a;','L_dynamic;'),
                        text.replace('0 0, L_a','1 0, L_a'),text.replace('BUFT','BUF')):
            with self.assertRaisesRegex(ValueError,'ADMISSION_LITERAL_DRIVER'):
                admission_probe(p,m,literal_nets(changed,{'ClickCompletion':{}}))

    def test_width_and_original_coverage_are_required(self):
        text,scopes,m,p=self.fixture(); literal_nets(text,scopes)
        bad=copy.deepcopy(m);bad['design']['endpoints'][0]['width']=2
        with self.assertRaisesRegex(ValueError,'ADMISSION_LITERAL_DRIVER'):
            admission_probe(p,bad,scopes)
        with self.assertRaisesRegex(ValueError,'ADMISSION_LITERAL_COVERAGE'):
            admission_probe(p.replace("ones_7 !== 1'h1","ones_7 !== 1'h0"),m,scopes)

    def test_production_owner_cannot_disappear_and_click_cannot_hide_rtz(self):
        for top in ('FourPhaseSoc','ClickSoc'):
            manifest=dict(top=top,design=dict(module=top,children=[]))
            with self.assertRaisesRegex(ValueError,'ADMISSION_SOC_INVENTORY'):
                admission_probe('task check; begin',manifest,{})
        manifest=dict(top='ClickAdmission',design=dict(module='ClickAdmission',channels=[],primitives=[],
            children=[dict(id='hidden',contract=dict(module='FourPhaseStage',channels=[],primitives=[],children=[]))]))
        with self.assertRaises(ValueError): validate_native_click(manifest)


if __name__=='__main__': unittest.main()

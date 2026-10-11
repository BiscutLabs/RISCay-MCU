# SPDX-License-Identifier: Apache-2.0
import copy
import unittest
from check_export import validate_native_click
from check_application_reset import persistent_reset_children
from check_publication_source_export import validate_publication_source,CHANNELS


class PublicationSourceExportTests(unittest.TestCase):
    def test_unknown_owners_are_rejected(self):
        for name in ('ClockedPublicationSource','ClickPublicationSourceRTZ','FourPhasePublicationSourceAdapter'):
            with self.assertRaisesRegex(ValueError,'PUBLICATION_SOURCE_OWNER'):
                validate_publication_source(dict(module=name))

    def test_native_click_owner_cannot_hide_rtz(self):
        node=dict(module='ClickPublicationSource',channels=[],primitives=[],children=[])
        validate_native_click(dict(top='ClickPublicationSource',design=node))
        for hidden in (dict(module='FourPhaseStage',channels=[],primitives=[],children=[]),
                       dict(module='Boundary',channels=[dict(protocol='four-phase-bundled-v1')],primitives=[],children=[]),
                       dict(module='Storage',channels=[],primitives=[dict(model='ChiselAsyncClosingLatch_v1')],children=[])):
            bad=copy.deepcopy(node);bad['children'].append(dict(id='hidden',contract=hidden))
            with self.assertRaisesRegex(ValueError,'MCU_CLICK_HAS_RTZ_IMPLEMENTATION'):
                validate_native_click(dict(top='ClickPublicationSource',design=bad))

    def test_every_publication_crossing_requires_por_ownership_and_complete_inventory(self):
        for click in (False,True):
            prefix='Click' if click else 'FourPhase'
            for owner in ('telemetry','housekeeping'):
                expected={owner+'_source':prefix+'PublicationSource'}
                for name in CHANNELS:
                    expected[owner+'_'+name+'_bridge']=(prefix+'ToDecoupled' if name in ('grant','drain') else 'DecoupledTo'+prefix)
                children=[dict(id=n,contract=dict(module=m)) for n,m in expected.items()]
                manifest=dict(top=prefix+'Soc',design=dict(children=children))
                classified=persistent_reset_children(manifest)
                self.assertTrue(all(classified[n]==m for n,m in expected.items()))
                for i in range(len(children)):
                    missing=copy.deepcopy(manifest);missing['design']['children'].pop(i)
                    with self.assertRaisesRegex(ValueError,'SOC_PUBLICATION_SOURCE_RESET_INVENTORY'):
                        persistent_reset_children(missing)
                    wrong=copy.deepcopy(manifest);wrong['design']['children'][i]['contract']['module']='ClockedAdapter'
                    with self.assertRaisesRegex(ValueError,'SOC_PERSISTENT_RESET_OWNER'):
                        persistent_reset_children(wrong)


if __name__=='__main__':unittest.main()

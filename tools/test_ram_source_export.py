# SPDX-License-Identifier: Apache-2.0
import copy
import unittest
from check_ram_source_export import ram_source_probe, validate_ram_source
from check_export import validate_native_click


class RamSourceExportTest(unittest.TestCase):
    def test_required_production_reservation_cannot_disappear(self):
        for top in ("FourPhaseSoc","ClickSoc"):
            m=dict(top=top,design=dict(module=top,children=[]))
            with self.assertRaisesRegex(ValueError,"RAM_SOURCE_SOC_INVENTORY"):
                ram_source_probe("task check; begin",m,{})

    def test_native_click_audit_includes_standalone_ram_owner(self):
        n=dict(module="ClickRamSource",channels=[],primitives=[],children=[])
        validate_native_click(dict(top="ClickRamSource",design=n))
        for hidden in (dict(module="FourPhaseStage",channels=[],primitives=[],children=[]),
                       dict(module="Boundary",channels=[dict(protocol="four-phase-bundled-v1")],primitives=[],children=[]),
                       dict(module="Storage",channels=[],primitives=[dict(model="ChiselAsyncClosingLatch_v1")],children=[])):
            bad=copy.deepcopy(n);bad["children"].append(dict(id="hidden",contract=hidden))
            with self.assertRaisesRegex(ValueError,"MCU_CLICK_HAS_RTZ_IMPLEMENTATION"):
                validate_native_click(dict(top="ClickRamSource",design=bad))

    def test_unknown_owner_fails_before_inspecting_optional_metadata(self):
        for module in ("FourPhaseRamSourceAdapter","ClockedRamSource","ClickRamSourceRTZ"):
            with self.assertRaisesRegex(ValueError,"RAM_SOURCE_OWNER"):
                validate_ram_source(dict(module=module))

if __name__=="__main__": unittest.main()

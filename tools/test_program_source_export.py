# SPDX-License-Identifier: Apache-2.0
import copy
import unittest
from check_export import validate_native_click
from check_program_source_export import validate_program_source,validate_stored_receipt,stored_receipt_bindings,validate_stored_receipt_rtl


class ProgramSourceExportTests(unittest.TestCase):
    def test_stored_receipt_closes_all_sequential_writers(self):
        # The schema is checked independently above; this test pins the emitted
        # clock/reset and state transition shape, including unauthorized writers.
        from unittest.mock import patch
        for click in (False,True):
            rtl="""wire packed_9_probe = clock;
wire packed_11_probe = reset;
wire localReset = localReset_release_1;
wire packed_10_probe = localReset;
wire packed_6 = VALID;
wire in_ack_0 = acknowledge;
always @(posedge clock or posedge reset) begin
 if(reset) begin localReset_release_0 <= 1'h1; localReset_release_1 <= 1'h1; end
 else begin localReset_release_0 <= 1'h0; localReset_release_1 <= localReset_release_0; end
end // always
always @(posedge clock or posedge localReset) begin
 if(localReset) begin requestMeta <= 1'h0; requestSync <= 1'h0; acknowledge <= 1'h0; end
 else begin requestMeta <= in_req; requestSync <= requestMeta; ACK end
end // always
initial begin
 `ifdef INIT_RANDOM_PROLOG_
  `INIT_RANDOM_PROLOG_
 `endif
 `ifdef RANDOMIZE_REG_INIT
  _RANDOM[1'b0] = `RANDOM;
  localReset_release_0 = _RANDOM[1'b0][0];
  localReset_release_1 = _RANDOM[1'b0][1];
  requestMeta = _RANDOM[1'b0][2];
  requestSync = _RANDOM[1'b0][3];
  acknowledge = _RANDOM[1'b0][4];
 `endif
 if(reset) begin localReset_release_0 = 1'h1; localReset_release_1 = 1'h1; end
 if(localReset) begin requestMeta = 1'h0; requestSync = 1'h0; acknowledge = 1'h0; end
end // initial
assign in_ack = in_ack_0;
assign out_valid = packed_6;
assign out_bits = in_bits;
""".replace('VALID','requestSync != acknowledge & ~packed_10_probe' if click else
            'requestSync & ~acknowledge & ~packed_10_probe').replace('ACK',
            'if(out_ready & packed_6) acknowledge <= requestSync;' if click else
            'acknowledge <= out_ready & packed_6 | requestSync & acknowledge;')
            with patch('check_program_source_export.validate_stored_receipt',return_value=click):
                validate_stored_receipt_rtl({},rtl)
                for old,new in [('requestSync <= requestMeta','requestSync <= in_req'),
                    ('requestMeta <= in_req','requestMeta <= requestSync'),
                    ('out_ready & packed_6','packed_6'),('acknowledge <= 1\'h0','acknowledge <= 1\'h1'),
                    ('posedge clock','posedge other_clock'),('or posedge reset',''),
                    ('localReset_release_1 <= localReset_release_0','localReset_release_1 <= 1\'h0'),
                    ('wire localReset = localReset_release_1','wire localReset = reset'),
                    ('assign out_bits = in_bits','assign out_bits = !in_bits')]:
                    with self.assertRaisesRegex(ValueError,'STORED_RECEIPT_'):
                        validate_stored_receipt_rtl({},rtl.replace(old,new))
                for extra in ["always @(posedge clock) acknowledge <= 1'b1;",
                              "always_comb acknowledge = in_req;",
                              "initial requestSync <= 1'b1;",
                              "initial begin #100 acknowledge = 1'b1; end",
                              "initial begin #100 force requestSync = 1'b1; end",
                              "assign out_bits = 1'b0;", "assign localReset = reset;"]:
                    with self.assertRaisesRegex(ValueError,'STORED_RECEIPT_'):
                        validate_stored_receipt_rtl({},rtl+extra)

    def test_stored_receipt_schema_and_register_inventory_are_closed(self):
        for click in (False,True):
            module=('Click' if click else 'FourPhase')+'StoredReceipt';path='Top.receipt'
            ids=('in_request','in_data','in_acknowledge','out_valid','out_data','out_ready','out_clock',
                 'reset','local_reset','request_meta','request_sync','acknowledge')
            node=dict(module=module,rtl_path=path,capacity=1,children=[],primitives=[],timing=[],
                endpoints=[dict(id=x,width=1,rtl_path=path+'.'+x) for x in ids],
                channels=[dict(id=n,protocol=p,role=r,layout=[dict(field='bits',lsb=0,width=1,signed=False,
                    source=f'~|{module}>{n}.bits')]) for n,p,r in
                    [('in','two-phase-bundled-v1' if click else 'four-phase-bundled-v1','input'),('out','decoupled-v1','output')]])
            self.assertEqual(validate_stored_receipt(node),click)
            regs={n:1 for n in ('localReset_release_0','localReset_release_1','requestMeta','requestSync','acknowledge')}
            self.assertEqual(len(stored_receipt_bindings(node,{path:dict(registers=regs)})),8)
            for field,value in [('capacity',2),('children',[dict(id='hidden')]),('timing',[dict(id='unknown')])]:
                bad=copy.deepcopy(node);bad[field]=value
                with self.assertRaises(ValueError):validate_stored_receipt(bad)
            for name in ids:
                bad=copy.deepcopy(node);next(e for e in bad['endpoints'] if e['id']==name)['width']=2
                with self.assertRaisesRegex(ValueError,'STORED_RECEIPT_INVENTORY'):validate_stored_receipt(bad)
            for name in regs:
                bad=regs.copy();bad.pop(name)
                with self.assertRaisesRegex(ValueError,'STORED_RECEIPT_REGISTER_INVENTORY'):
                    stored_receipt_bindings(node,{path:dict(registers=bad)})

    def test_unknown_owner_is_rejected(self):
        for module in ("FourPhaseProgramSourceAdapter","ClockedProgramSource","ClickProgramSourceRTZ"):
            with self.assertRaisesRegex(ValueError,"PROGRAM_SOURCE_OWNER"):
                validate_program_source(dict(module=module))

    def test_native_program_owner_cannot_hide_rtz(self):
        node=dict(module="ClickProgramSource",channels=[],primitives=[],children=[])
        validate_native_click(dict(top="ClickProgramSource",design=node))
        for hidden in (dict(module="FourPhaseStage",channels=[],primitives=[],children=[]),
                       dict(module="Boundary",channels=[dict(protocol="four-phase-bundled-v1")],primitives=[],children=[]),
                       dict(module="Storage",channels=[],primitives=[dict(model="ChiselAsyncClosingLatch_v1")],children=[])):
            bad=copy.deepcopy(node);bad["children"].append(dict(id="hidden",contract=hidden))
            with self.assertRaisesRegex(ValueError,"MCU_CLICK_HAS_RTZ_IMPLEMENTATION"):
                validate_native_click(dict(top="ClickProgramSource",design=bad))


if __name__ == "__main__": unittest.main()

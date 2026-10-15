"""Independent tests of common scratch mutation coverage and scope."""
import copy,importlib.util,json,re,sys,tempfile,unittest
from pathlib import Path
import check_i2c_wiring_controls as controls
from check_export import i2c_path_bindings
from test_i2c_export import fixture

class CommonRunnerTest(unittest.TestCase):
    def test_every_address_and_bit_is_selected_once_without_replacing_old_cases(self):
        for click in (False,True):
            primitives={p['id']:p for p in fixture(click)['primitives']}
            cases=controls.common_byte_cases(primitives)
            self.assertEqual(len(cases),42)
            lanes=[lane for _,_,_,lane in cases if lane is not None]
            self.assertEqual(set(lanes),set(range(0,264,8))|set(range(1,8)))
            self.assertEqual(len(lanes),len(set(lanes)))
            self.assertEqual({pin for _,primitive,pin,lane in cases if primitive=='receive_all'},{'d','trigger'})
            pairs=i2c_path_bindings(fixture(click))
            with tempfile.TemporaryDirectory() as directory:
                probe=Path(directory)/'contract_probe.sv'
                probe.write_text('module ContractProbe;\ntask check; begin\n'+''.join(f'if ({a} !== {b}) $fatal(1,"DATA_PATH_BINDING_MISMATCH");\n' for a,b in pairs)+'end endtask\nendmodule\n')
                for _,primitive,pin,_ in cases:
                    expected=controls.fault_site(probe,'Top.'+primitive+'.'+pin,pairs)
                    self.assertEqual(expected['scope'],'ContractProbe.check')

    def test_unknown_or_selective_storage_fails_closed(self):
        good={p['id']:p for p in fixture(False)['primitives']}
        for kind in ('missing','selective','storage-width','data-width','model'):
            changed=copy.deepcopy(good)
            if kind=='missing':del changed['receive_all']
            elif kind=='selective':changed['receive_0']=copy.deepcopy(changed['receive_all'])
            elif kind=='storage-width':changed['receive_all']['parameters']['WIDTH']='263'
            elif kind=='data-width':changed['byte_data_delay']['parameters']['WIDTH']='263'
            else:changed['receive_all']['model']='ChiselAsyncClosingLatch_v1'
            with self.assertRaises(AssertionError):controls.common_byte_cases(changed)

    def test_exact_balanced_actual_input_mutation_and_scope(self):
        source='''module I2cPublication;
Primitive byte_data_delay (
  .a ({upper, (valid ? data : (old_data))}),
  .b (264'h0),
  .reset (reset),
  .q (target)
  );
endmodule
'''
        for lane in range(264):
            mutated=controls.mutate_byte_lane(source,'byte_data_delay',lane)
            mask=re.search(r"\^ 264'h([0-9a-f]+)",mutated)
            self.assertIsNotNone(mask)
            self.assertEqual(int(mask[1],16),2**lane)
            self.assertIn('.b (264\'h0)',mutated)
            self.assertIn('.reset (reset)',mutated)
            restored=mutated.replace("({upper, (valid ? data : (old_data))}) ^ 264'h"+mask[1],'{upper, (valid ? data : (old_data))}')
            self.assertEqual(restored,source)
        for lane in (-1,264):
            with self.assertRaises(AssertionError):controls.mutate_byte_lane(source,'byte_data_delay',lane)
        for malformed in (source.replace('byte_data_delay','other'),source+source,source.replace('.a (','.c (')):
            with self.assertRaises(AssertionError):controls.mutate_byte_lane(malformed,'byte_data_delay',0)

    def test_real_lane_fault_is_at_exact_compiled_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            for lane in (None,0,127,263):
                folder=Path(directory)/str(lane);folder.mkdir()
                rtl=folder/'I2cPublication.sv'
                rtl.write_text('''module Pin(input [263:0] a,output [263:0] q);assign q=a;endmodule
module I2cPublication;
reg [263:0] raw=0;wire [263:0] q;
Pin byte_data_delay (
  .a (raw),
  .q (q)
  );
endmodule
''')
                probe=folder/'contract_probe.sv'
                probe.write_text('''module ContractProbe;
task check;begin
if (I2cPublication.raw !== I2cPublication.byte_data_delay.a) $fatal(1,"DATA_PATH_BINDING_MISMATCH");
end endtask
initial begin #1;check;$display("CONTRACT_PROBES_PASS:1");$finish;end
endmodule
''')
                (folder/'filelist.f').write_text('I2cPublication.sv\n');(folder/'contract.json').write_text('{}\n')
                expected=None
                if lane is not None:
                    rtl.write_text(controls.mutate_byte_lane(rtl.read_text(),'byte_data_delay',lane))
                    expected=controls.fault_site(probe,'I2cPublication.byte_data_delay.a',[('I2cPublication.raw','I2cPublication.byte_data_delay.a')])
                record={}
                controls.execute_case(folder,1,expected,controls.digest(probe),[],record)
                self.assertEqual(record['status'],'PASS')
                if lane is not None:self.assertEqual(record['fatal_site']['line'],3)

if __name__=='__main__':unittest.main()

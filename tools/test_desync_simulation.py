# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from desync_simulation import bounds, controller_bounds, flow_monitor, flow_coverage
from primitives import candidate_recipe, simulation_equations
from test_desync_network import fixture as graph_fixture


class SimulationTests(unittest.TestCase):
    def test_transfer_checks_detect_partial_x_corruption_duplicate_reset_and_gate_faults(self):
        for fault,diagnostic in [('none','TRANSFER_PASS'),('partial','DESYNC_REGISTER_FLOW'),
                                 ('duplicate','DESYNC_DUPLICATE_CAPTURE'),('reset','DESYNC_RESET_VALUE'),
                                 ('gate','DESYNC_GATE_CHANGED_OPEN'),('order','DESYNC_GRAPH_ORDER'),
                                 ('reset_token','TRANSFER_PASS'),('held_reset_token','TRANSFER_PASS'),
                                 ('bad_reset_token','DESYNC_REGISTER_FLOW')]:
            with self.subTest(fault=fault):
                top=dict(cells={'master':dict(connections={'EN':[7],'ARST':[9]},parameters=dict(ARST_VALUE='00',ARST_POLARITY='1')),'slave':dict(connections={'EN':[8]})},
                    netnames={'resetHold/unsafe_supply':dict(bits=[2]),'qualifier':dict(bits=[11]),'desync_fabric_s':dict(bits=[10])})
                initial=(1<<2)|(1<<9)
                for i,label in enumerate(('cpu.m','fabric.m','fabric.s','power.m','power.s')):
                    pin='acknowledgeOut' if label=='cpu.m' else 'enable'
                    top['netnames']['desync_control/'+label+'/'+pin]=dict(bits=[20+i])
                    if label.endswith('.m') and label!='cpu.m':initial|=1<<(20+i)
                if fault=='order':initial|=1<<22
                part=graph_fixture();part.update(gated_domains={'work':'qualifier'},falling_gate_conditions={})
                row=dict(path='q',bank='fabric',domain='work',bits=2,falling=False,kind='latch-pair',
                    storage=['master','slave'],original_type='$adff',master_reset=fault.endswith('reset_token'),
                    original_parameters=dict(ARST_POLARITY='1',ARST_VALUE='00',CLK_POLARITY='1'),
                    original_connections=dict(D=[3,4],Q=[5,6],ARST=[9],CLK=[12]))
                monitor=flow_monitor(top,dict(state=[row],partition=part))
                declarations=[]
                for name,value in top['netnames'].items():
                    if not name.startswith('desync_') or '/' in name:continue
                    bits=value['bits'];expression='{'+','.join(f'v[{b}]' for b in reversed(bits))+'}'
                    declarations.append(f'wire [{len(bits)-1}:0] {name}={expression};')
                stimulus="dut.v[4:3]=2'b10;"
                if fault=='partial':stimulus="dut.v[4:3]=2'bx1;"
                stimulus+=" dut.v[7]=1;#1;dut.v[7]=0;dut.v[8]=1;#1;dut.v[6:5]=dut.v[4:3];"
                if fault=='partial':stimulus+="dut.v[5]=0;"
                if fault.endswith('reset_token'):
                    stimulus+="dut.v[9]=1;dut.v[6:5]=0;#1;"
                    if fault=='held_reset_token':stimulus+="dut.v[8]=0;#1;dut.v[7]=1;#1;dut.v[7]=0;dut.v[8]=1;#1;dut.v[8]=0;#1;dut.v[8]=1;#1;"
                    stimulus+="dut.v[9]=0;#1;"
                    if fault=='bad_reset_token':stimulus+="dut.v[6:5]=2'b10;"
                stimulus+='dut.v[8]=0;#1;'
                stimulus+=dict(none='',partial='',reset_token='',held_reset_token='',bad_reset_token='',duplicate='dut.v[8]=1;#1;dut.v[8]=0;',
                    reset="dut.v[6:5]=2'b11;dut.v[9]=1;",gate='dut.v[10]=1;dut.v[11]=1;',order='dut.v[22]=0;')[fault]
                source=f'''module Dummy; reg [31:0] v=32'h{initial:x};
{chr(10).join(declarations)}
DesyncFlowChecks checks(); endmodule
module Testbench; timeunit 1ns; timeprecision 1ps; reg clockEnabled=1; Dummy dut();
initial begin #2;dut.v[2]=0;dut.v[9]=0;#1;{stimulus}#1;$display("TRANSFER_PASS");$finish;end endmodule
{monitor}'''
                self.simulate(source,diagnostic,fails=fault not in ('none','reset_token','held_reset_token'))

    def test_sta_bounds_fail_closed_and_enable_is_incremental(self):
        common=dict(instance='bank',corner='slow',context='Aplus',source='requestIn',
                    source_rise=True,sense='max',input_slew_ns=2)
        rows=[dict(common,target='acknowledgeOut',delay_ns=8),dict(common,target='enable',delay_ns=8.4)]
        self.assertEqual(bounds(rows,'bank','enable','slow'),(8.4,8.4))
        for value in controller_bounds(rows,'bank','enable','slow'):
            self.assertAlmostEqual(value,.4)
        with self.assertRaisesRegex(ValueError,'MISSING_STA_BOUND'):bounds(rows,'other','enable','slow')
        with self.assertRaisesRegex(ValueError,'ENABLE_INCREMENT'):controller_bounds(rows[:1],'bank','enable','slow')

    def test_flow_report_requires_live_inventory_and_exposes_unexercised_state(self):
        transform=dict(state=[dict(path='used',bank='a',bits=3),dict(path='unused',bank='b',bits=2)])
        text='DESYNC_FLOW_COVERAGE,0,a,3,7\nDESYNC_FLOW_COVERAGE,1,b,2,0\nDESYNC_FLOW_TOTAL,defined_bits=21,undefined_bits=14\n'
        self.assertEqual(flow_coverage(text,transform)['unexercised'],['unused'])
        for changed in (text.replace('DESYNC_FLOW_COVERAGE,1,b,2,0\n',''),
                        text.replace(',1,b,2,0',',0,a,3,0'),text.replace(',0,a,3,7',',0,a,4,7'),
                        text.replace('defined_bits=21','defined_bits=0'),text+text):
            with self.subTest(changed=changed),self.assertRaisesRegex(ValueError,'DESYNC_SIM_FLOW_'):
                flow_coverage(changed,transform)

    def test_registered_stimuli_run_against_behavioral_models(self):
        cases=[('RiscayDesyncController',False),('RiscayDesyncController',True),
               ('RiscayDesyncJoin',False),('RiscayDesyncJoin',True),('RiscayDesyncCaptureJoin',False)]
        modules=['module Testbench; initial begin #400; $display("MODELS_PASS"); $finish; end']
        for i,(name,initial) in enumerate(cases):modules.append(f'ModelTest{i} t{i}();')
        modules.append('endmodule')
        for i,(name,initial) in enumerate(cases):
            recipe=candidate_recipe(name,initial_open=initial)
            delays={p:.1 for p,d in recipe['ports'].items() if d=='output'}
            code=[f'module ModelTest{i}; timeunit 1ns; timeprecision 1ps;']
            code += [f'{"reg" if d=="input" else "wire"} {p};' for p,d in recipe['ports'].items()]
            code.append(simulation_equations(name,dict(initial_open=initial),delays))
            for pin,edges in recipe['stimulus'].items():
                last=0;line='initial begin '
                for at,value in edges:line+=f'#{at-last} {pin}={value}; ';last=at
                code.append(line+'end')
            last=0;line='initial begin '
            for row in recipe['samples']:
                line+=f'#{row["at_ns"]-last}; ';last=row['at_ns']
                for p,value in row['values'].items():line+=f'if({p} !== 1\'b{value}) $fatal(1,"MODEL:{name}:{initial}:{p}"); '
            code.append(line+'end\nendmodule');modules+=code
        self.simulate('\n'.join(modules),'MODELS_PASS')

    def test_master_reset_keeps_the_actual_causal_return(self):
        model=simulation_equations('RiscayDesyncController',dict(initial_open=True),
            dict(acknowledgeOut=.3,enable=.1,requestOut=.2))
        tb='''module Testbench; timeunit 1ns; timeprecision 1ps;
reg reset=1,requestIn=0,acknowledgeIn=1; wire acknowledgeOut,enable,requestOut;
MODEL
initial begin #2;reset=0;#2;requestIn=1;#2;acknowledgeIn=0;#2;
if(!requestOut) $fatal(1,"RESET_PRECONDITION"); reset=1;#0.31;
if(!requestOut) $fatal(1,"EARLY_MASTER_RESET_RETURN");#2;
if(requestOut) $fatal(1,"RESET_DID_NOT_DRAIN");$display("RESET_PASS");$finish;end endmodule'''
        self.simulate(tb.replace('MODEL',model),'RESET_PASS')
        mutation=model.replace('requestOut = (!enable', "requestOut = reset ? 1'b0 : (!enable")
        self.simulate(tb.replace('MODEL',mutation),'EARLY_MASTER_RESET_RETURN',fails=True)

    def simulate(self,source,expected,fails=False):
        with TemporaryDirectory() as folder:
            p=Path(folder);(p/'test.sv').write_text(source)
            c=subprocess.run(['iverilog','-g2012','-s','Testbench','-o',str(p/'sim'),str(p/'test.sv')],capture_output=True,text=True,timeout=30)
            self.assertEqual(c.returncode,0,c.stdout+c.stderr)
            r=subprocess.run(['vvp',str(p/'sim')],capture_output=True,text=True,timeout=30)
            self.assertEqual(r.returncode!=0,fails,r.stdout+r.stderr)
            self.assertIn(expected,r.stdout+r.stderr)


if __name__=='__main__':unittest.main()

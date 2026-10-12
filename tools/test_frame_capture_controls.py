# SPDX-License-Identifier: Apache-2.0
"""Fail-closed checks for emitted frame-capture qualification evidence."""
import copy
import re
import tempfile
import unittest
from pathlib import Path

from check_frame_capture_controls import (LEAVES, PREFIX, assertion_sites,
    classify, classify_wrap, instrument, monitors, packed, qualify, skew, supplemental)


def fake_binding():
    path = 'Testbench.dut.ca_child_i2c'
    return dict(variant='bd', source_q=path+'.ca_child_native.ca_child_publication.ca_primitive_frame_payload.q',
                clock='Testbench.dut.workClock', target_path=path,
                publisher_path=path+'.ca_child_native.ca_child_publication', receipt_path=path+'.ca_child_frame_bridge',
                frame_d={name: 'incoming_'+name for name, _ in LEAVES},
                publisher={'primitives': [dict(id=n,rtl_path='Top.publisher.'+n,parameters={'DELAY_FS':delay})
                    for n,delay in [('frame_payload','1000000'),('frame_phase','1000000'),
                                    ('pending','1000000'),('data_delay','10000000'),('output_guard','110000000')]]})


BENCH='''module Testbench;
timeunit 1ns; timeprecision 1ps;
initial begin
  #25;
  if(original_bad) $fatal(1,"ORIGINAL_ASSERTION");
  $display("RISCAY_SOC_PASS");
end
endmodule
'''


class FrameCaptureControlTests(unittest.TestCase):
    def test_original_functional_oracle_is_byte_for_byte_preserved(self):
        instrumented=instrument(BENCH,fake_binding())
        head=instrumented.split('\nmodule FrameCaptureChecks;',1)[0]
        head=head.replace('FrameCaptureChecks frame_capture_checks();\n','').replace('frame_capture_checks.finish_checks();\n','')
        self.assertEqual(head,BENCH)
        self.assertIn('timeunit 1fs; timeprecision 1fs;',instrumented)
        for bad in (BENCH.replace('1ns','1ps'),BENCH+BENCH,BENCH.replace('RISCAY_SOC_PASS','FAKE_PASS')):
            with self.subTest(bad=bad),self.assertRaises(ValueError):instrument(bad,fake_binding())

    def test_actual_mailbox_and_independent_context_are_monitored(self):
        text=monitors(fake_binding())
        self.assertIn('posedge Testbench.dut.workClock',text)
        self.assertIn('fabric_hostFrames_first_frame_bytes_32',text)
        self.assertIn('fabric_hostFrames_second_frame_bytes_32',text)
        self.assertIn('ca_primitive_frame_payload.q',text)
        self.assertIn('native_payload[63:0]',text)
        self.assertIn('resetEpoch_epoch',text)
        self.assertIn('resetEpoch_previous',text)
        self.assertIn('in_bits_frame_bytes_0>=1',text)
        self.assertIn('in_bits_frame_bytes_0<=6',text)
        self.assertIn('mailbox_d !== independently_expected',text)
        self.assertIn('if(occupancy==0 || deq)',text)
        self.assertIn('expected_first=second_q',text)
        self.assertIn('first_q !== expected_first',text)
        self.assertIn('second_q !== expected_second',text)
        self.assertEqual(sum(w for _,w in LEAVES),273)

    def test_apertures_do_not_exempt_application_reset(self):
        text=monitors(fake_binding())
        self.assertIn('always @(native_payload) if(!Testbench.reset)',text)
        self.assertIn('$time-admission_time<=100000',text)
        self.assertIn('$time-source_change<=100000',text)
        self.assertIn('$time-data_change<=100000',text)
        self.assertIn('always @(mailbox_d[272:2])',text)
        self.assertNotIn('if(!Testbench.applicationReset)',text)
        self.assertNotIn('force ',text)
        self.assertIn('.frame_req || Testbench.dut.ca_child_i2c.ca_child_native.ca_child_publication.frame_ack',text)
        click=fake_binding();click['variant']='click'
        self.assertIn('.frame_req!=Testbench.dut.ca_child_i2c.ca_child_native.ca_child_publication.frame_ack',monitors(click))
        self.assertNotIn('source_held',text)

    def test_exact_fatal_site_rejects_display_copy_other_location_and_extra_failure(self):
        test=instrument(BENCH,fake_binding());expected=PREFIX+'_DESTINATION_HOLD'
        sites=assertion_sites(test,expected);self.assertEqual(len(sites),1);site=sites[0]
        self.assertIn(expected,test.splitlines()[site['line']-1])
        self.assertEqual(site['scope'],'Testbench.frame_capture_checks')
        log=f"FATAL: testbench.sv:{site['line']}: {expected}\n       Time: 7  Scope: {site['scope']}\n"
        self.assertEqual(len(classify({'exit_code':0},{'exit_code':1},log,sites)),1)
        bads=[expected,log.replace('testbench.sv','unrelated.sv'),log.replace(str(site['line'])+':','1:'),
              log.replace(site['scope'],'Testbench'),log+'RISCAY_SOC_PASS\n',log+'SOC_DEADLINE\n',
              log+log.replace(expected,'ANOTHER_FAULT')]
        for bad in bads:
            with self.subTest(log=bad),self.assertRaises(ValueError):classify({'exit_code':0},{'exit_code':1},bad,sites)

    def test_original_oracle_fault_site_is_also_exact(self):
        test=instrument(BENCH,fake_binding());sites=assertion_sites(test,'ORIGINAL_ASSERTION')
        self.assertEqual(sites,[dict(source='testbench.sv',line=6,message='ORIGINAL_ASSERTION',scope='Testbench')])

    def test_positive_requires_success_activity_marker_and_no_failure(self):
        self.assertEqual(classify({'exit_code':0},{'exit_code':0},'RISCAY_SOC_PASS\n'),[])
        for compiled, simulated, log in [({'exit_code':1},{'exit_code':0},'RISCAY_SOC_PASS\n'),
            ({'exit_code':0},{'exit_code':1},'RISCAY_SOC_PASS\n'),
            ({'exit_code':0},{'exit_code':0,'timed_out':True},'RISCAY_SOC_PASS\n'),
            ({'exit_code':0},{'exit_code':0},''),
            ({'exit_code':0},{'exit_code':0},'RISCAY_SOC_PASS\nRISCAY_SOC_PASS\n'),
            ({'exit_code':0},{'exit_code':0},'RISCAY_SOC_PASS\nFATAL: a:1: bad\n')]:
            with self.subTest(log=log),self.assertRaises(ValueError):classify(compiled,simulated,log)

    def test_opposing_delay_profiles_keep_fixed_data_and_guards(self):
        b=fake_binding()
        original=BENCH.replace('initial begin','defparam dut.publisher.data_delay.DELAY_FS=10000000;\n'
            'defparam dut.publisher.output_guard.DELAY_FS=110000000;\ninitial begin')
        for profile, payload, control in [('data-slow-control-fast','10000000','1000000'),
                                         ('data-fast-control-slow','1000000','10000000')]:
            result,changes=skew(original,b,profile)
            self.assertEqual(changes['dut.publisher.frame_payload.DELAY_FS']['after'],payload)
            self.assertEqual(changes['dut.publisher.pending.DELAY_FS']['after'],control)
            self.assertNotIn('dut.publisher.data_delay.DELAY_FS',changes)
            self.assertIn('defparam dut.publisher.output_guard.DELAY_FS=110000000;',result)
        with self.assertRaises(ValueError):skew(BENCH,b,'arbitrary-slower')
        duplicate=BENCH.replace('initial begin','defparam dut.publisher.pending.DELAY_FS=1;\n'*2+'initial begin')
        with self.assertRaises(ValueError):skew(duplicate,b,'data-slow-control-fast')
        minimum,changes=skew(original,b,'minimum')
        self.assertTrue(all(change['after']=='1000000' for change in changes.values()))
        self.assertIn('defparam dut.publisher.output_guard.DELAY_FS=110000000;',minimum)

    def test_wrap_requires_original_error_fatal_lines_scope_and_same_time(self):
        site=dict(source=r'P:\case\I2cTarget.sv',error_line=332,fatal_line=334,scope='Testbench.dut.ca_child_i2c')
        log=(f"ERROR: {site['source']}:332: Assertion failed: I2C_RESET_EPOCH_WRAP\n\n"
             f"       Time: 3825  Scope: {site['scope']}\n"
             f"FATAL: {site['source']}:334: \n       Time: 3825  Scope: {site['scope']}\n")
        self.assertEqual(classify_wrap({'exit_code':0},{'exit_code':1},log,site),[site])
        for bad in (log.replace(':334:',':333:'),log.replace('I2C_RESET_EPOCH_WRAP','OTHER'),
                    log.replace('Time: 3825','Time: 3826',1),log+'FRAME_INPUT_WRAP_MISSING\n',
                    log+log,log.replace('Testbench.dut.ca_child_i2c','Testbench')):
            with self.subTest(log=bad),self.assertRaises(ValueError):classify_wrap({'exit_code':0},{'exit_code':1},bad,site)

    def test_supplemental_driver_forces_only_upstream_input_not_downstream_ack(self):
        b=fake_binding()
        ports=['reset','holdFrame','holdHostCommands','stopWorkClock','applicationReset','scl','sda','response_ready']
        header='module Testbench;\ntimeunit 1ns; timeprecision 1ps;\n'+''.join('reg [0:0] '+p+';\n' for p in ports)
        original=header+'reg clockEnabled=1;\ninitial begin serviceClock=0; forever begin #25; if(clockEnabled) serviceClock=~serviceClock; end end\n'
        original+='initial begin watchdogClock=0; forever begin #163; if(referenceEnabled) watchdogClock=~watchdogClock; end end\nendmodule\n'
        names=['reset','in_req','in_bits_frameValid','in_bits_snapshotValid','frame_ack','snapshot_ack',
               'in_bits_frame_ingress_frame_length','in_bits_frame_ingress_frame_overflow',
               'in_bits_frame_ingress_resetActive','in_bits_frame_ingress_programBusy','in_bits_frame_resetEpoch']
        names+=['in_bits_frame_ingress_frame_bytes_'+str(i) for i in range(33)]
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'I2cPublication.sv').write_text('module I2cPublication(\n'+''.join('input '+n+',\n' for n in names)+');\nendmodule\n',encoding='utf-8')
            text=supplemental(original,b,folder)
        forced=re.findall(r'\bforce\s+([\w.]+)\s*=',text)
        self.assertEqual(len(forced),len([n for n in names if n.startswith('in_')]))
        self.assertTrue(all('.ca_child_publication.in_' in x for x in forced))
        self.assertFalse(any(x.endswith(('frame_ack','snapshot_ack')) or '.q' in x for x in forced))
        self.assertIn('reset=1;scl=1;',text)
        self.assertIn('bit_index<337',text)
        self.assertIn('bit_index<64',text)
        self.assertIn('first_writes!=405',text)
        self.assertIn('second_writes!=403',text)
        self.assertIn('FRAME_INPUT_SAME_EDGE_BUSY_RESULT',text)
        self.assertIn('FRAME_INPUT_337_POLARITY',text)
        self.assertIn('FRAME_INPUT_273_POLARITY',text)
        self.assertIn('FRAME_INPUT_EPOCH_BIT',text)
        self.assertNotRegex(text,r'force\s+[^;]*=pub_data\[')


if __name__=='__main__':
    unittest.main()

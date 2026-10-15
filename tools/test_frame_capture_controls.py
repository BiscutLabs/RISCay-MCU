# SPDX-License-Identifier: Apache-2.0
"""Fail-closed checks for emitted frame-capture qualification evidence."""
import copy
import re
import tempfile
import unittest
from pathlib import Path

from check_frame_capture_controls import (LEAVES, PREFIX, assertion_sites,
    classify, classify_wrap, copy_order_metrics, command_capture_policy, fixture_masks_policy, instrument, monitors, omit_same_edge_busy, packed, qualify, ring_budget_ns, service_period, skew, supplemental)


def fake_binding():
    path = 'Testbench.dut.ca_child_i2c'
    store={'primitives':[dict(id=id,rtl_path='Top.store.'+id,parameters={'DELAY_FS':'1000000'}) for id in ('payload0','route','accepted_phase')], 'children':[]}
    return dict(variant='bd', source_q=path+'.ca_child_native.ca_child_publication.ca_primitive_frame_payload.q',
                clock='Testbench.dut.workClock', target_path=path,
                publisher_path=path+'.ca_child_native.ca_child_publication', receipt_path=path+'.ca_child_frame_bridge',
                route_q=path+'.route.q',route_d=path+'.route.d',route_capture=path+'.route.trigger',
                store_path=path+'.ca_child_frame_store',store=store,command_path='Testbench.dut.ca_child_control_command_bridge',
                banks=[dict(q=path+f'.bank{i}.q',d=path+f'.bank{i}.d',capture=path+f'.bank{i}.closed',
                            phase=path+f'.phase{i}.q',req=path+f'.bank{i}.req',ack=path+f'.bank{i}.ack',available=path+f'.bank{i}.available') for i in range(4)],
                frame_d={name:'incoming_'+name for name in ('bank','resetActive','programBusy')},
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
    def test_same_edge_busy_fault_preserves_direct_admission_context(self):
        terms=['_ca_child_i2c_host_frame_bits_programBusy','_ca_child_program_access_io_busy',
               'fabric_loaderPending','fabric_loaderControlPending',
               'fabric__9 & ~_GEN_14 & fabric__loaderControlPending_T_1 & fabric__loaderControlPending_T_3']
        context=' | '.join(terms)
        source=f'wire fabric_hostFrames_io_enq_bits_programBusy={context};'
        changed=omit_same_edge_busy(source,context)
        self.assertIn('fabric_hostFrames_io_enq_bits_programBusy='+' | '.join(terms[:4])+';',changed)
        self.assertNotIn(terms[-1],changed)
        for text,c in ((source,' | '.join(terms[:4])),(source.replace(terms[-1],'wrong'),context),
                       (source,context.replace(terms[0],'unrelated'))):
            with self.subTest(text=text),self.assertRaises(ValueError):omit_same_edge_busy(text,c)

    def test_original_functional_oracle_is_byte_for_byte_preserved(self):
        instrumented=instrument(BENCH,fake_binding())
        head=instrumented.split('\nmodule FrameCaptureChecks;',1)[0]
        head=head.replace('FrameCaptureChecks frame_capture_checks();\n','').replace('frame_capture_checks.finish_checks();\n','')
        self.assertEqual(head,BENCH)
        self.assertIn('timeunit 1fs; timeprecision 1fs;',instrumented)
        for bad in (BENCH.replace('1ns','1ps'),BENCH+BENCH,BENCH.replace('RISCAY_SOC_PASS','FAKE_PASS')):
            with self.subTest(bad=bad),self.assertRaises(ValueError):instrument(bad,fake_binding())

    def test_actual_banks_descriptors_command_capture_and_independent_context_are_monitored(self):
        text=monitors(fake_binding())
        for expected in ('posedge Testbench.dut.workClock','fabric_hostFrames_first_bank',
                         'fabric_hostFrames_second_programBusy','ca_primitive_frame_payload.q',
                         'native_payload[63:0]','resetEpoch_epoch','resetEpoch_previous',
                         'in_bits_frame_bytes_0>=1','in_bits_frame_bytes_0<=6',
                         'descriptor_d!=={slot,expected_reset,expected_busy}',
                         'if(occupancy==0 || deq)','expected_first=second_q',
                         'first_q!==expected_first','second_q!==expected_second',
                         'data_frame_bytes_32','COMMAND_D_IDENTITY','COMMAND_Q_CAPTURE',
                         'BANK_UNAVAILABLE_AT_O','COPY_COMPLETION_IDENTITY','DISPATCH_BEFORE_COPY_COMPLETION','next_offer=(next_offer+1)%4'):
            self.assertIn(expected,text)
        for index in range(4):
            for suffix in ('SETUP','HOLD','CAPTURE','IDENTITY','RETAIN','PULSE'):
                self.assertIn(f'BANK{index}_{suffix}',text)
        self.assertEqual(sum(w for _,w in LEAVES),273)

    def test_native_offer_capture_and_admission_counters_are_independent(self):
        for variant in ('bd','click'):
            b=fake_binding();b['variant']=variant;text=monitors(b)
            for expected in ('native_next_bank!==next_offer','offered_generation[slot]!=lifetime_accepts',
                             'captured_generation[pending_bank]!=pending_generation','copied_generation[first_q[3:2]]!=offered_generation[first_q[3:2]]',
                             'NATIVE_ROUTE_SETUP','NATIVE_ROUTE_HOLD','NATIVE_ROUTE_Q','NATIVE_ROUTE_RESET','NATIVE_ROUTE_PULSE',
                             'accept_before_copy=accept_before_copy+1','copy_before_accept=copy_before_accept+1'):
                self.assertIn(expected,text)
            self.assertNotIn('BANK_COPY_AT_A',text)
            self.assertNotIn('host_frameOffered',text)
            self.assertNotIn('frameCopyReady',text)
            self.assertNotIn('observed_reset_history',text)
            self.assertNotIn('store.slot',text)
            if variant=='click':self.assertIn('COPY_PHASE_IDENTITY',text)

    def test_copy_order_metrics_require_real_completions_and_early_admission(self):
        self.assertEqual(copy_order_metrics('FRAME_CAPTURE_COPY_ORDER:8:0:8\n',True)['accept_before_copy'],8)
        self.assertEqual(copy_order_metrics('FRAME_CAPTURE_COPY_ORDER:4:4:0\n')['copy_before_accept'],4)
        for text in ('','FRAME_CAPTURE_COPY_ORDER:0:0:0\n','FRAME_CAPTURE_COPY_ORDER:3:2:2\n',
                     'FRAME_CAPTURE_COPY_ORDER:1:1:0\nFRAME_CAPTURE_COPY_ORDER:1:1:0\n'):
            with self.subTest(text=text),self.assertRaises(ValueError):copy_order_metrics(text)
        with self.assertRaisesRegex(ValueError,'A_BEFORE_COPY_COVERAGE'):
            copy_order_metrics('FRAME_CAPTURE_COPY_ORDER:4:4:0\n',True)

    def test_bank_corruption_group_is_exact_and_keeps_observation_points_distinct(self):
        text=instrument(BENCH,fake_binding())
        sites=assertion_sites(text,('FRAME_CAPTURE_BANK0_IDENTITY','FRAME_CAPTURE_BANK0_COPY_COMPLETION_IDENTITY'))
        self.assertEqual(len(sites),2)
        for site in sites:
            log=f'FATAL: testbench.sv:{site["line"]}: {site["message"]}\n       Time: 21 Scope: {site["scope"]}\n'
            self.assertEqual(len(classify({'exit_code':0},{'exit_code':1},log,sites)),1)
            with self.assertRaises(ValueError):classify({'exit_code':0},{'exit_code':1},log.replace('BANK0','BANK1'),sites)
        for messages in (('FRAME_CAPTURE_BANK0_IDENTITY','FRAME_CAPTURE_COPY_COMPLETION_IDENTITY'),
                         ('FRAME_CAPTURE_BANK0_IDENTITY','FRAME_CAPTURE_BANK1_COPY_COMPLETION_IDENTITY')):
            with self.assertRaises(ValueError):assertion_sites(text,messages)

    def test_opposing_route_and_accepted_delays_preserve_fixed_budgets(self):
        for profile,slow in (('route-slow-accepted-fast','route'),('route-fast-accepted-slow','accepted_phase')):
            b=fake_binding();text,changes=skew(BENCH,b,profile)
            self.assertEqual(changes['dut.store.route.DELAY_FS']['after'],'10000000' if slow=='route' else '1000000')
            self.assertEqual(changes['dut.store.accepted_phase.DELAY_FS']['after'],'10000000' if slow=='accepted_phase' else '1000000')
            self.assertNotIn('data_delay.DELAY_FS',text)
            self.assertNotIn('output_guard.DELAY_FS',text)

    def test_apertures_do_not_exempt_application_reset(self):
        text=monitors(fake_binding())
        self.assertIn('always @(native_payload) if(!Testbench.reset)',text)
        self.assertIn('$time-admission_time<=100000',text)
        self.assertIn('$time-source_change<=100000',text)
        self.assertIn('$time-receipt_change<=100000',text)
        self.assertIn('always @(receipt_payload[336:66])',text)
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

    def test_publisher_and_bank_skew_are_independent_and_fixed_guards_unchanged(self):
        b=fake_binding()
        for profile,publisher,bank in [('publisher-fast-banks-slow','1000000','10000000'),
                                       ('publisher-slow-banks-fast','10000000','1000000')]:
            text,changes=skew(BENCH,b,profile)
            self.assertEqual(changes['dut.publisher.frame_payload.DELAY_FS']['after'],publisher)
            self.assertEqual(changes['dut.store.payload0.DELAY_FS']['after'],bank)
            self.assertNotIn('dut.publisher.output_guard.DELAY_FS',changes)
            self.assertNotIn('dut.publisher.data_delay.DELAY_FS',changes)

    def test_command_capture_rejects_wrong_clock_missing_bit_extra_writer_or_wrong_source(self):
        fields=[(n if n!='resetActive' else 'cpuResetActive',w) for n,w in LEAVES]
        rtl='module Command(input clock,input localReset_release_1);\n'
        rtl+='\n'.join('reg '+(f'[{w-1}:0] ' if w>1 else '')+'data_'+n+';' for n,w in fields)
        rtl+='\nalways @(posedge clock or posedge localReset_release_1) begin\nif(localReset_release_1) begin\n'
        rtl+='\n'.join(f"data_{n} <= {w}'h0;" for n,w in fields)
        rtl+='\nend else begin\nif (_in_ready_T & _GEN) begin\n'
        rtl+='\n'.join(f'data_{n} <= in_bits_{n};' for n,w in fields)
        rtl+='\nend\nend\nend // always\nendmodule\n'
        self.assertEqual(command_capture_policy(rtl,False),fields)
        changes=[rtl.replace('posedge clock','posedge unrelatedClock'),
                 rtl.replace('data_frame_bytes_32 <= in_bits_frame_bytes_32;',''),
                 rtl.replace('endmodule','always @(posedge clock) data_frame_bytes_0 <= 0;\nendmodule'),
                 rtl.replace('data_programBusy <= in_bits_programBusy;','data_programBusy <= 0;'),
                 rtl.replace('if (_in_ready_T & _GEN)','if (_in_ready_T)'),
                 rtl.replace('if(localReset_release_1)', 'if(unrelated_reset)'),
                 rtl.replace('endmodule', 'always @(posedge clock) data_frame_bytes_0[0] <= 0;\nendmodule')]
        for changed in changes:
            with self.subTest(changed=changed),self.assertRaises(ValueError):command_capture_policy(changed,False)

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
        names+=['in_bits_byteWrite_valid','in_bits_byteWrite_index','in_bits_byteWrite_data']
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'I2cPublication.sv').write_text('module I2cPublication(\n'+''.join('input '+n+',\n' for n in names)+');\nendmodule\n',encoding='utf-8')
            text=supplemental(original,b,folder)
            continuous=supplemental(original,b,folder,continuous=True)
            boundary=supplemental(original,b,folder,continuous=True,boundary=True)
            ring=supplemental(original,b,folder,ring=True)
        forced=re.findall(r'\bforce\s+([\w.]+)\s*=',text)
        self.assertEqual(len(forced),len([n for n in names if n.startswith('in_')]))
        self.assertTrue(all('.ca_child_publication.in_' in x for x in forced))
        self.assertFalse(any(x.endswith(('frame_ack','snapshot_ack')) or '.q' in x for x in forced))
        self.assertIn('task preload_frame_bytes(input [336:0] data);',text)
        self.assertIn('byte_index<33',text)
        self.assertEqual(text.count('#300;#0;$fatal(1,"FRAME_INPUT_BYTE_DEADLINE");'),1)
        self.assertIn('join_any\n      disable bounded_byte;',text)
        self.assertIn('pub_byte_data=data[66+byte_index*8+:8]',text)
        self.assertIn('pub_frame_valid=0;',text)
        self.assertIn('pub_byte_valid=0;pub_frame_valid=1;',text)
        self.assertEqual(text.count('preload_frame_bytes(pub_data);'),4)
        self.assertIn('preload_frame_bytes(pub_data);#0.001;',ring)
        self.assertIn('reset=1;scl=1;',text)
        self.assertIn('bit_index<337',text)
        self.assertIn('bit_index<64',text)
        self.assertIn('first_writes!=405',text)
        self.assertIn('second_writes!=403',text)
        self.assertIn('FRAME_INPUT_SAME_EDGE_BUSY_RESULT',text)
        self.assertNotIn('frameCopyReady',text)
        self.assertIn('if(!hostDispatched || !injectedAccepted)',text)
        self.assertIn('FRAME_INPUT_337_POLARITY',text)
        self.assertIn('FRAME_INPUT_273_POLARITY',text)
        self.assertIn('while(!controlIdle || dut.ca_child_i2c.host_resetActive)',text)
        self.assertIn('currentReset || currentBusy || dut.ca_child_i2c.host_resetActive',text)
        self.assertIn('FRAME_INPUT_EPOCH_BIT',text)
        self.assertNotRegex(text,r'force\s+[^;]*=pub_data\[')
        continuous_body=continuous[continuous.index('  new_pair();\n  // Do not reset'):]
        self.assertEqual(continuous_body.count('new_pair();'),1)
        self.assertNotIn('reset=1',continuous_body)
        self.assertIn('bank_index<8',continuous_body)
        self.assertIn('bank_accepts[bank_index]!=674',continuous_body)
        self.assertIn('FRAME_INPUT_D_EPOCH_MASKED',continuous_body)
        self.assertIn('epoch_driver=64\'b1<<bit_index',continuous_body)
        forced_continuous=re.findall(r'\bforce\s+([\w.]+)\s*=',continuous)
        extra=set(forced_continuous)-set(forced)
        self.assertEqual(extra,{'dut.ca_child_i2c.resetEpoch_epoch'})
        self.assertIn('FRAME_INPUT_CONTINUOUS:4:4:8:0:32',boundary)
        self.assertEqual(set(re.findall(r'\bforce\s+([\w.]+)\s*=',boundary)),set(forced))
        ring_body=ring[ring.index('  new_pair();ring_active=1;'):]
        self.assertNotIn('offer_frame(',ring_body)
        self.assertNotIn('repeat(',ring_body)
        self.assertIn('ring_late_dispatches!=30 || ring_exact_frontiers!=30',ring_body)
        self.assertIn('FRAME_INPUT_RING_LAST_LEGAL_D',ring)
        self.assertIn('receiptValid && !ring_offer_pending',ring)
        self.assertIn('hostDispatched || ring_now-ring_last_D!=ring_period',ring)
        self.assertIn('ring_offers!=32 || ring_accepts!=32 || ring_offer_pending',ring)
        self.assertIn('FRAME_INPUT_RING_ADMISSION_WITHOUT_OFFER',ring)
        self.assertIn('ring_offers!=ring_accepts+1',ring)
        self.assertIn('FRAME_INPUT_RING_PERIOD',ring)
        self.assertIn('in_ready && !dut.fabric_controlOutstanding)',ring_body)
        self.assertIn('FRAME_CAPTURE_READY_BY_THIRD_NEXT_A',monitors(b))

    def test_period_boundaries_are_exactly_representable_and_independently_checked(self):
        bench='initial begin serviceClock=0; forever begin #25.0; if(clockEnabled) serviceClock=~serviceClock; end end\nlocalparam time RING_EXPECTED_PERIOD_FS=50000000;\ninitial begin #100000000; $fatal(1,"FRAME_INPUT_DEADLINE"); end'
        bench+='\nfor(byte_index=0;byte_index<33;byte_index=byte_index+1) begin\n'
        bench+='#300;#0;$fatal(1,"FRAME_INPUT_BYTE_DEADLINE");\njoin_any\n      disable bounded_byte;\nend'
        for period in (50,55.498,55.5,55.502,114,312.5,1000,1000000):
            changed=service_period(bench,period)
            self.assertIn('#'+str(period/2),changed)
            self.assertIn('RING_EXPECTED_PERIOD_FS='+str(round(period*1000000)),changed)
            self.assertEqual(ring_budget_ns(period),round(period*1152+1000)+32*33*300)
            self.assertIn(f'initial begin #{ring_budget_ns(period)}; $fatal(1,"FRAME_INPUT_DEADLINE"); end',changed)
        self.assertEqual(ring_budget_ns(50),375400)
        for malformed in (bench.replace('#100000000;', '#100000001;'),
                          bench.replace('"FRAME_INPUT_DEADLINE"', '"OTHER_DEADLINE"'),
                          bench+'\ninitial begin #100000000; $fatal(1,"FRAME_INPUT_DEADLINE"); end'):
            with self.subTest(malformed=malformed),self.assertRaisesRegex(ValueError,'RING_DEADLINE_BINDING'):
                service_period(malformed,50)
        for malformed in (bench.replace('#300;#0;', '#301;#0;'),
                          bench.replace('byte_index<33', 'byte_index<32'),
                          bench.replace('disable bounded_byte;', 'disable wrong_scope;')):
            with self.subTest(malformed=malformed),self.assertRaisesRegex(ValueError,'RING_BYTE_BOUND_BINDING'):
                service_period(malformed,50)
        wire='initial begin serviceClock=0; forever begin #25.0; if(clockEnabled) serviceClock=~serviceClock; end end\ninitial begin #12345; $fatal(1,"ORIGINAL_WIRE_DEADLINE"); end'
        self.assertEqual(service_period(wire,50),wire)
        self.assertIn('#12345; $fatal(1,"ORIGINAL_WIRE_DEADLINE");',service_period(wire,312.5))
        for period in (49.998,1000000.002,55.499):
            with self.subTest(period=period),self.assertRaises(ValueError):service_period(bench,period)

    def test_fixture_stall_masks_must_remain_symmetric_and_have_no_extra_uses(self):
        rtl='input holdFrame; input holdHostCommands; input holdSelectedHead;\nwire frame_enable=enabled & ~holdFrame;\n'
        rtl+='assign fabric_io_controlCommand_ready=_ca_child_control_command_bridge_in_ready & ~holdHostCommands;\n'
        rtl+='wire fabric__io_i2c_heads_0_ready_T=enabled & fabric_hostFrames_io_deq_ready;\n'
        rtl+='Command command(.in_valid(fabric_io_controlCommand_valid & ~holdHostCommands));\n'
        target={'frameAcceptEnable':'enabled&~holdFrame'};command={'in_valid':'fabric_io_controlCommand_valid&~holdHostCommands'}
        for i in range(4):
            target[f'host_heads_{i}_ready']=f'ca_child_i2c_host_heads_{i}_ready'
            select=f"fabric_hostFrames_first_bank == 2'h{i}" if i<3 else '(&fabric_hostFrames_first_bank)'
            rtl+=f'assign fabric_io_i2c_heads_{i}_valid=_ca_child_i2c_host_heads_{i}_valid & ~holdSelectedHead;\n'
            rtl+=f'wire ca_child_i2c_host_heads_{i}_ready=fabric__io_i2c_heads_0_ready_T & fabric_hostFrames_io_deq_valid & {select} & ~holdSelectedHead;\n'
        fixture_masks_policy(rtl,target,command)
        for changed in (rtl.replace('& ~holdSelectedHead','',1),rtl+'wire unrelated=holdSelectedHead;',rtl.replace('& ~holdHostCommands','',1)):
            with self.subTest(changed=changed),self.assertRaises(ValueError):fixture_masks_policy(changed,target,command)



if __name__=='__main__':
    unittest.main()

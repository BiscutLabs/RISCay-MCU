# SPDX-License-Identifier: Apache-2.0
import unittest
from unittest.mock import patch
from check_frame_wake_controls import PROFILES,FIXED,child,instrument,sources_policy,metrics,profile
from check_program_return_fatals import fatal_sites,classify_fatal


class FrameWakeControlsTest(unittest.TestCase):
    def test_inventory_is_explicit(self):
        for bad in ({},{'bd':{}},{'bd':{},'click':{}}):
            with self.assertRaises(ValueError):sources_policy(bad)
        self.assertEqual(len(PROFILES),4)
        self.assertTrue({'request_delay','return_guard','acknowledge_guard','output_guard'}<=FIXED)

    def test_child_inventory_is_unambiguous(self):
        for nodes in ([],[{'id':'x','contract':{}},{'id':'x','contract':{}}]):
            with self.assertRaises(ValueError):child({'children':nodes},'x')

    def test_missing_or_duplicate_finish_is_rejected(self):
        for body in ('', 'reg clockEnabled=1;', 'reg clockEnabled=1;'+2*'$display("RISCAY_SOC_PASS"); $finish;'):
            with self.assertRaises(ValueError):instrument(body,{})

    def test_negative_requires_the_compiled_fatal_location(self):
        text='module Testbench;initial begin : fw_stop $fatal(1,"EXPECTED");end endmodule'
        sites=fatal_sites(text,['EXPECTED'])
        good='FATAL: testbench.sv:1: EXPECTED\n       Time: 21 Scope: Testbench.fw_stop\n'
        self.assertEqual(len(classify_fatal({'exit_code':0},{'exit_code':1},good,sites)),1)
        for bad in ('EXPECTED',good.replace(':1:',':2:'),good.replace('fw_stop','other')):
            with self.assertRaises(ValueError):classify_fatal({'exit_code':0},{'exit_code':1},bad,sites)

    def test_original_deadline_and_oracles_remain_verbatim(self):
        body='reg clockEnabled=1;\nlocalparam CHECK_SOURCE_STOP=1;\ninitial begin #5000000; $fatal(1,"SOC_DEADLINE"); end\ninitial begin if(bad) $fatal(1,"ORIGINAL");$display("RISCAY_SOC_PASS"); $finish;end'
        with patch('check_frame_wake_controls.monitor',return_value='// extra monitors'):
            result=instrument(body,{})
        self.assertIn('initial begin #5000000; $fatal(1,"SOC_DEADLINE"); end',result)
        self.assertIn('if(bad) $fatal(1,"ORIGINAL");',result)
        self.assertEqual(result.count('command(9);'),1)
        self.assertIn('fw_ring_index<12',result)

    def test_metric_parser_requires_all_banks_and_an_independent_positive(self):
        banks='\n'.join(f'FRAME_WAKE_CONTROL_BANK {i} offers={4 if i<2 else 3} dispatches={4 if i<2 else 3} return_edges=4' for i in range(4))
        counts='FRAME_WAKE_CONTROL_METRICS offers=14 accepts=14 dispatches=14 stops=5 stopped_checks=3 front_edges=300 work_edges=200 last_state_margin_ns=100.001 quiet_margin_ns=50.001'
        good=banks+'\n'+counts+'\nFRAME_WAKE_CONTROL_PASS\n'
        self.assertEqual(metrics(good,True)['counts']['offers'],14)
        for bad in (good.replace('FRAME_WAKE_CONTROL_PASS',''),good.replace('accepts=14','accepts=13'),good.replace('BANK 3','BANK 2'),good.replace('quiet_margin_ns=50.001','quiet_margin_ns=0.000')):
            with self.assertRaises(ValueError):metrics(bad,True)

    def test_skew_preserves_fixed_guards_and_noncell_data_budget(self):
        node={'module':'Store','children':[],'primitives':[
            {'id':name,'rtl_path':'Top.store.'+name,'model':'Gate','parameters':{'DELAY_FS':str(value)}}
            for name,value in [('request_delay',11000000),('data_delay',10000000),('return_guard',32000000),('output_guard',110000000),('payload',1000000)]]}
        publisher={'module':'Pub','children':[],'primitives':[]}
        body,overrides=profile('reg clockEnabled=1;',{'store':node,'publication':publisher},'publisher-fast-banks-slow')
        self.assertEqual(overrides,{'dut.soc.store.payload':{'before':1000000,'after':10000000}})
        self.assertNotIn('data_delay.DELAY_FS',body)


if __name__=='__main__':unittest.main()

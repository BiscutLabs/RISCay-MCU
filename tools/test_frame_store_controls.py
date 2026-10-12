# SPDX-License-Identifier: Apache-2.0
import unittest
import tempfile
from pathlib import Path

from check_frame_store_controls import (CAMPAIGNS,PROFILES,closing,masked,mutation_jobs,
    pin_value,port_span,profile,replace_pin,replace_one,source_oracles,parse_metrics,extra_rtl,helper_closure)
from check_program_return_fatals import fatal_sites,classify_fatal


class FrameStoreControlsTest(unittest.TestCase):
    def test_named_port_parser_preserves_nested_expressions_and_comments(self):
        original='module M; Gate cell( .a ({f(x), y[2:0]}), /* .a(ignored) */ .q (z) ); endmodule'
        self.assertEqual(pin_value(original,'cell','a'),'{f(x), y[2:0]}')
        result=replace_pin(original,'cell','a',"4'h1")
        self.assertEqual(result,original.replace('{f(x), y[2:0]}',"4'h1"))

    def test_named_port_parser_fails_closed_for_missing_duplicate_or_unnamed_ports(self):
        for text in ('Gate cell(a,b);','Gate cell(.a(x),.a(y));','Gate cell(.q(z));',
                     'Gate cell(.a(x)); Gate cell(.a(y));','Gate cell(.a(x),);'):
            with self.assertRaises(ValueError):port_span(text,'cell','a')

    def test_mutation_anchor_requires_exactly_one_site(self):
        for text in ('absent','hit hit'):
            with self.assertRaisesRegex(ValueError,'MUTATION_ANCHOR'):replace_one(text,'hit','changed')

    def test_delimiter_and_comment_handling(self):
        text='/* ( */ f({a[0],g(b)}) // )'
        code=masked(text)
        self.assertEqual(code[closing(code,code.index('('))],')')
        with self.assertRaisesRegex(ValueError,'PORT_DELIMITER'):closing('([)]',0)

    def test_all_nine_click_pins_have_independent_pulse_and_distribution_controls(self):
        jobs=mutation_jobs(True);names={j['name'] for j in jobs}
        self.assertEqual(len(names),len(jobs))
        for register in [f'{kind}{i}' for i in range(4) for kind in ('payload','phase')]+['accepted_phase']:
            for prefix in ('disconnect-trigger','short-high','short-low','late-trigger'):
                self.assertIn(prefix+'-'+register,names)
        self.assertNotIn('setup-accepted_phase',names)

    def test_source_inventory_requires_both_variants_and_every_campaign(self):
        with self.assertRaisesRegex(ValueError,'VARIANT_INVENTORY'):source_oracles({'bd':{}})
        with self.assertRaisesRegex(ValueError,'SOURCE_INVENTORY'):source_oracles({'bd':{},'click':{}})
        self.assertEqual(len(CAMPAIGNS),6)
        self.assertEqual(len(PROFILES),3)

    def test_profile_rejects_fixed_guard_or_unknown_cell_overrides(self):
        node={'primitives':[{'id':'request_guard','rtl_path':'M.guard','parameters':{'DELAY_FS':'32000000'},'model':'Gate'}],
              'module':'M','children':[]}
        with self.assertRaisesRegex(ValueError,'FIXED_GUARD_OVERRIDDEN'):
            profile('defparam dut.guard.DELAY_FS=32000000;',node,'minimum')
        with self.assertRaisesRegex(ValueError,'UNKNOWN_DELAY_CELL'):
            profile('defparam dut.unknown.DELAY_FS=1000000;',node,'minimum')

    def test_added_rtl_declares_mutation_nets_before_their_instance_uses(self):
        body='module Owner(input a, output q); Gate g(.a(late),.q(q)); endmodule'
        result=extra_rtl(body,'wire late;','assign #100000 late=a;')
        self.assertLess(result.index('wire late;'),result.index('Gate g'))
        self.assertIn('Gate g(.a(late),.q(q));',result)
        self.assertEqual(result.count('assign #100000 late=a;'),1)

    def test_low_pulse_controls_bind_both_independent_monitors_at_all_nine_pins(self):
        low=[j for j in mutation_jobs(True) if j['name'].startswith('short-low-')]
        self.assertEqual(len(low),9)
        self.assertTrue(all(j['expected']==['FRAME_STORE_PULSE_LOW_'+j['name'][10:],
            'FRAME_STORE_PIN_PULSE_LOW_'+j['name'][10:]] for j in low))
        route=next(j for j in mutation_jobs(False) if j['name']=='short-low-route')
        self.assertEqual(route['expected'],['FRAME_STORE_PULSE_LOW_route','FRAME_STORE_PIN_PULSE_LOW_route'])

    def test_minimum_profile_preserves_the_complete_data_budget(self):
        node={'module':'M','children':[],'primitives':[
            {'id':'data_delay','rtl_path':'M.data','model':'Gate','parameters':{'DELAY_FS':'10000000'}},
            {'id':'payload','rtl_path':'M.payload','model':'ChiselAsyncEventRegister_v1','parameters':{'DELAY_FS':'1000000'}}]}
        body='defparam dut.data.DELAY_FS=10000000;\ndefparam dut.payload.DELAY_FS=10000000;'
        result,changed=profile(body,node,'minimum')
        self.assertIn('dut.data.DELAY_FS=10000000;',result)
        self.assertEqual(changed,{'dut.payload':{'before':10000000,'after':1000000}})

    def test_empty_pin_activity_is_never_a_positive(self):
        node={'module':'M','children':[],'primitives':[{'id':'phase','rtl_path':'M.p','model':'ChiselAsyncPhaseRegister_v1','parameters':{}}]}
        for log in ('','FRAME_STORE_PIN phase captures=0 setups=0 holds=0 setup_fs=0 hold_fs=0 high_fs=0 low_fs=0'):
            with self.assertRaisesRegex(ValueError,'CAPTURE_ACTIVITY'):parse_metrics(log,node)

    def test_helper_binding_follows_transitive_local_imports_and_breaks_cycles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            (root/'a.py').write_text('from b import value\nimport os\n',encoding='utf-8')
            (root/'b.py').write_text('import c\nvalue=1\n',encoding='utf-8')
            (root/'c.py').write_text('from a import value\n',encoding='utf-8')
            self.assertEqual(set(helper_closure([root/'a.py'])),{(root/(name+'.py')).resolve() for name in 'abc'})

    def test_formatted_or_displayed_text_cannot_substitute_for_exact_fatal(self):
        body='module Testbench;initial begin : check $fatal(1,"EXPECTED");end endmodule'
        sites=fatal_sites(body,['EXPECTED'])
        good='FATAL: testbench.sv:1: EXPECTED\n       Time: 12 Scope: Testbench.check\n'
        result=classify_fatal({'exit_code':0},{'exit_code':1},good,sites)
        self.assertEqual(len(result),1)
        for bad in ('EXPECTED\n',good.replace(':1:',':2:'),good.replace('Testbench.check','Testbench.other'),
                    good+'CA_TEST_PASS seed=1\n'):
            with self.assertRaises(ValueError):classify_fatal({'exit_code':0},{'exit_code':1},bad,sites)


if __name__=='__main__':unittest.main()

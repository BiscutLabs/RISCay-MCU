# SPDX-License-Identifier: Apache-2.0
from itertools import product
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from desync_transform import flatten_input, latch_techmap, storage_scaffold
from desync_partition import partition
from test_desync_partition import fixture


class StorageTransformTests(unittest.TestCase):
    def test_owner_aliases_survive_renaming_and_reject_cross_bank_merging(self):
        n, p = fixture(); normalized = flatten_input(n, p)
        top = normalized['modules']['chip']
        top['cells']['optimized_slice'] = top['cells'].pop('fabric')
        row = next(r for r in partition(normalized, p)['registers'] if r['path']=='optimized_slice')
        self.assertEqual(row['bank'], 'fabric')
        self.assertTrue(all(not w['attributes'] for w in top['netnames'].values()))
        top['netnames']['desync_owner/cpu/invalid_merge'] = dict(bits=top['cells']['optimized_slice']['connections']['Q'], attributes={})
        with self.assertRaisesRegex(ValueError, 'OPTIMIZED_BANK_AMBIGUITY'):
            partition(normalized, p)

    def test_generated_latch_adapter_polarities_and_hold(self):
        models = '''
module gf180mcu_fd_sc_mcu7t5v0__latq_1(input D,E,output reg Q); always @* if(E) Q=D; endmodule
module gf180mcu_fd_sc_mcu7t5v0__latrnq_1(input D,E,RN,output reg Q); always @* if(!RN) Q=0; else if(E) Q=D; endmodule
module gf180mcu_fd_sc_mcu7t5v0__latsnq_1(input D,E,SETN,output reg Q); always @* if(!SETN) Q=1; else if(E) Q=D; endmodule
'''
        fixtures = []
        for ep, rp, value in product(('P', 'N'), ('P', 'N'), (0, 1)):
            fixtures.append(f'''module test_{ep}{rp}{value}; reg d,e,r; wire q;
\\$_DLATCH_{ep}{rp}{value}_ dut(d,e,r,q);
initial begin #1; d=0; e={int(ep=='N')}; r={int(rp=='P')};
#1; if(q!==1'b{value}) $fatal(1,"RESET"); r=~r; e=~e; d=1;
#1; if(q!==1'b1) $fatal(1,"OPEN"); e=~e; #1; d=0;
#1; if(q!==1'b1) $fatal(1,"HOLD"); r=~r;
#1; if(q!==1'b{value}) $fatal(1,"ASYNC_RESET"); end endmodule''')
        for ep in ('P', 'N'):
            fixtures.append(f'''module test_{ep}; reg d,e; wire q;
\\$_DLATCH_{ep}_ dut(d,e,q);
initial begin #1; d=0; e={int(ep=='P')};
#1; if(q!==1'b0) $fatal(1,"PLAIN_OPEN"); e=~e; #1; d=1;
#1; if(q!==1'b0) $fatal(1,"PLAIN_HOLD"); e=~e;
#1; if(q!==1'b1) $fatal(1,"PLAIN_REOPEN"); end endmodule''')
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw); src = folder/'test.v'; binary = folder/'test.vvp'
            for text, should_pass in [(latch_techmap(), True), (latch_techmap().replace('.RN(~R)', '.RN(R)'), False)]:
                src.write_text(text + models + '\n'.join(fixtures))
                compile_result = subprocess.run([shutil.which('iverilog'), '-g2012', '-o', str(binary), str(src)], capture_output=True, text=True)
                self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
                result = subprocess.run([shutil.which('vvp'), str(binary)], capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, should_pass, result.stdout + result.stderr)

    def test_combinational_logic_and_retained_state_are_unchanged(self):
        n, p = fixture()
        p['retained_domains'] = ['service']
        n['modules']['chip']['cells']['logic'] = dict(type='$not', parameters=dict(A_WIDTH='1', Y_WIDTH='1', A_SIGNED='0'),
            connections=dict(A=[3], Y=[10]), port_directions=dict(A='input', Y='output'), attributes={})
        result, report = storage_scaffold(n, p)
        m = result['modules']['chip']
        self.assertEqual(m['cells']['logic']['type'], '$not')
        self.assertEqual(m['cells']['power']['type'], '$dff')
        self.assertEqual(next(r for r in report['state'] if r['path'] == 'power')['kind'], 'retained')
        self.assertFalse(any(c.get('attributes', {}).get('keep') for c in m['cells'].values()))
        self.assertEqual(report['status'], 'storage-scaffold-only')
        self.assertEqual(report['architectural_bits_before_optimization'], sum(r['bits'] for r in report['state']))

    def test_enable_and_synchronous_reset_priority_exhaustive(self):
        for kind in ('$dff', '$dffe', '$sdff', '$sdffe', '$sdffce'):
            for ep, rp, rv in product((0, 1), repeat=3):
                n, p = fixture(); m = n['modules']['chip']; c = m['cells']['fabric']
                c['type'] = kind
                for port, bit in [('EN', 11), ('SRST', 12)]:
                    needed = (port == 'EN' and kind in ('$dffe', '$sdffe', '$sdffce')) or (port == 'SRST' and kind.startswith('$sdff'))
                    if needed:
                        m['ports'][port] = dict(direction='input', bits=[bit]); m['netnames'][port] = dict(bits=[bit])
                        c['connections'][port] = [bit]; c['port_directions'][port] = 'input'
                        c['parameters'][port+'_POLARITY'] = str(ep if port == 'EN' else rp)
                if kind.startswith('$sdff'):
                    c['parameters']['SRST_VALUE'] = str(rv)
                out, _ = storage_scaffold(n, p); t = out['modules']['chip']
                def wire(name): return t['netnames'][name]['bits'][0]
                for d, q, en, reset in product((0, 1), repeat=4):
                    values = {'0': 0, '1': 1, wire('cpuQ'): d, wire('fabricQ'): q}
                    if 'EN' in t['netnames']: values[wire('EN')] = en
                    if 'SRST' in t['netnames']: values[wire('SRST')] = reset
                    for name, cell in t['cells'].items():
                        if name.startswith('fabric/') and cell['type'] == '$mux':
                            ports = cell['connections']; s = values[ports['S'][0]]
                            values[ports['Y'][0]] = values[ports['B' if s else 'A'][0]]
                    observed = values[t['cells']['fabric/master']['connections']['D'][0]]
                    expected = d
                    enabled = en == ep
                    reset_active = reset == rp
                    if 'EN' in c['connections'] and not enabled: expected = q
                    if 'SRST' in c['connections'] and reset_active: expected = rv
                    if kind == '$sdffce' and not enabled: expected = q
                    with self.subTest(kind=kind, ep=ep, rp=rp, rv=rv, d=d, q=q, en=en, reset=reset):
                        self.assertEqual(observed, expected)

    def test_resettable_falling_master_is_defined_but_positive_master_is_plain(self):
        n, p = fixture()
        for name in ('fabric', 'power'):
            c = n['modules']['chip']['cells'][name]; c['type'] = '$adff'
            c['connections']['ARST'] = [3]; c['port_directions']['ARST'] = 'input'
            c['parameters'].update(ARST_POLARITY='0', ARST_VALUE='1')
        result, _ = storage_scaffold(n, p); cells = result['modules']['chip']['cells']
        self.assertEqual(cells['fabric/master']['type'], '$dlatch')
        for name in ('fabric/slave', 'power/master', 'power/slave'):
            self.assertEqual(cells[name]['type'], '$adlatch')
            self.assertEqual(cells[name]['parameters']['ARST_VALUE'], '1')
            self.assertEqual(cells[name]['parameters']['ARST_POLARITY'], '0')

    def test_independent_async_reset_defines_master_and_bad_binding_fails(self):
        n, p = fixture(); c = n['modules']['chip']['cells']['fabric']
        c['type'] = '$adff'; c['connections']['ARST'] = [3]; c['port_directions']['ARST'] = 'input'
        c['parameters'].update(ARST_POLARITY='1', ARST_VALUE='1')
        p['defined_master_reset_aliases'] = ['fabricQ']
        out, report = storage_scaffold(n, p)
        cells = out['modules']['chip']['cells']
        for label in ('master', 'slave'):
            self.assertEqual(cells['fabric/'+label]['type'], '$adlatch')
            self.assertEqual(cells['fabric/'+label]['parameters']['ARST_VALUE'], '1')
        self.assertEqual(next(r for r in report['state'] if r['path']=='fabric')['master_reset_aliases'], ['fabricQ'])
        p['defined_master_reset_aliases'] = ['not_a_register']
        with self.assertRaisesRegex(ValueError, 'MASTER_RESET_ALIAS_MISSING'):
            storage_scaffold(n, p)
        p['defined_master_reset_aliases'] = ['cpuQ']
        with self.assertRaisesRegex(ValueError, 'MASTER_RESET_BINDING'):
            storage_scaffold(n, p)

    def test_short_wake_reset_survives_release_while_slave_is_open(self):
        # Replay the review's counterexample. The old plain master retains zero;
        # releasing reset then overwrites the freshly set wake slave with zero.
        models = '''
module lat(input D,E,R,output reg Q); always @* if(R) Q=1; else if(E) Q=D; endmodule
module tb;
reg d,em,es,r; wire qm,qs;
lat master(d,em,MASTER_RESET,qm); lat slave(qm,es,r,qs);
initial begin
  d=0; em=0; es=0; r=0;
  #1; em=1; #1; em=0; #1; es=1;
  #1; r=1; #1; if(qs!==1'b1) $fatal(1,"WAKE_ASSERT");
  r=0; #1; if(qs!==1'b1) $fatal(1,"WAKE_LOST_AT_RELEASE");
  es=0; #1; em=1; #1; em=0; #1; es=1;
  #1; if(qs!==1'b0) $fatal(1,"NEXT_CAPTURE");
end
endmodule
'''
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw); src = folder/'test.v'; binary = folder/'test.vvp'
            for reset, success in [('r', True), ("1'b0", False)]:
                src.write_text(models.replace('MASTER_RESET', reset))
                c = subprocess.run([shutil.which('iverilog'), '-g2012', '-o', str(binary), str(src)], capture_output=True, text=True)
                self.assertEqual(c.returncode, 0, c.stderr)
                r = subprocess.run([shutil.which('vvp'), str(binary)], capture_output=True, text=True)
                self.assertEqual(r.returncode == 0, success, r.stdout + r.stderr)
                if not success: self.assertIn('WAKE_LOST_AT_RELEASE', r.stdout)

    def test_slave_is_gated_and_master_tracks(self):
        n, p = fixture(); result, _ = storage_scaffold(n, p); m = result['modules']['chip']
        self.assertEqual(m['cells']['fabric/master']['connections']['EN'], m['ports']['desync_fabric_m']['bits'])
        self.assertNotEqual(m['cells']['fabric/slave']['connections']['EN'], m['ports']['desync_fabric_s']['bits'])
        self.assertEqual(m['cells']['desync/fabric/s/gate_work']['connections']['B'], m['netnames']['enable']['bits'])
        with self.assertRaisesRegex(ValueError, 'FALLING_FLOP_EXCEPTION'):
            storage_scaffold(n, p, ('power',))


if __name__ == '__main__':
    unittest.main()

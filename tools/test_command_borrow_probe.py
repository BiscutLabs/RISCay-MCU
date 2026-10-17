# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from check_command_borrow import telemetry_borrow_background


def fixture(top, channels=0):
    prefix = top[:-3]
    sender = dict(module='DecoupledTo' + prefix, rtl_path=top + '.sender')
    native = dict(module=prefix + 'Telemetry', rtl_path=top + '.native')
    base = channels * 100
    command = [('appIndex', 0, 6), ('data', 6, 32), ('offset', 38, 7), ('elapsedUpper', 45, 32),
               ('clear', 77, 6), ('events', 83, 6), ('kind', 89, 2), ('recovery', 91, 1)]
    header = [('elapsedUpper', 0, 32), ('events', 32, 6), ('kind', 38, 2), ('recovery', 40, 1)]
    capture = [('tailAge', 0, 32), ('value', 32, 32), ('calibrated', 64, 1), ('valid', 65, 1),
               ('hadValid', 66, 1), ('count', 67, 32), ('seen', 99, 1)]
    def layout(module, channel, fields):
        all_fields = [(f'captures[{i}].{name}', i * 100 + bit, width) for i in range(channels)
                      for name, bit, width in capture] + [(name, base + bit, width) for name, bit, width in fields]
        return [dict(field='bits.' + name, lsb=bit, width=width, signed=False,
                     source='~|' + module + '>' + channel + '.bits.' + name) for name, bit, width in all_fields]
    sender['channels'] = [dict(id=side, layout=layout(sender['module'], side, header)) for side in ('in', 'out')]
    native['channels'] = [dict(id='command', layout=layout(native['module'], 'command', command))]
    fields = [('clear', 6), ('offset', 7), ('data', 32), ('appIndex', 6)]
    regs = {'fabric_telemetryCommit_' + name: width for name, width in fields}
    regs['live_data'] = 32
    scopes = {top: dict(registers=regs), sender['rtl_path']: dict(registers={'data_kind': 2},
              ports={'out_bits_kind': dict(width=2, direction='output')}),
              native['rtl_path']: dict(ports={'command_bits_' + name: dict(width=width, direction='input')
                                             for name, width in [('kind', 2)] + fields})}
    manifest = dict(top=top, design=dict(children=[dict(id='telemetry', contract=native),
                                                  dict(id='telemetry_command_bridge', contract=sender)]))
    rtl = '''module Sender(output [1:0] out_bits_kind); reg [1:0] data_kind;
assign out_bits_kind=data_kind; endmodule
module Native(input [1:0] command_bits_kind, input [5:0] command_bits_clear,
input [6:0] command_bits_offset, input [31:0] command_bits_data, input [5:0] command_bits_appIndex);
wire [50:0] observed={command_bits_clear,command_bits_offset,command_bits_data,command_bits_appIndex}; endmodule
'''
    rtl += f'module {top}; reg reset;\n' + ''.join(f'reg [{w-1}:0] {n};\n' for n, w in regs.items())
    rtl += "wire [1:0] kind; Sender sender(kind); wire selected=kind==2'h1;\n"
    rtl += 'Native native(.command_bits_kind(kind),' + ','.join(
        f".command_bits_{name}(selected ? fabric_telemetryCommit_{name} : {width}'h0)" for name, width in fields) + ');\nendmodule\n'
    header_text = f"force {top}.reset = 1'b0;\n" + ''.join(
        f"force {top}.{name} = {width}'h0;\n" for name, width in regs.items())
    header_text += f"force {top}.sender.data_kind = 2'h0;\n#1;\n"
    source = f'''module ContractProbe; timeunit 1ns; timeprecision 1ps;
reg [50:0] ones_0=0, zeros_0=0;
task check; begin
ones_0=ones_0 | {top}.native.observed; zeros_0=zeros_0 | ~{top}.native.observed;
end endtask
initial begin
force {top}.reset = 1'b1; #1;
{header_text}check;
if (ones_0 !== 51'h7ffffffffffff || zeros_0 !== 51'h7ffffffffffff) $fatal(1,"INACTIVE_ENDPOINT:borrowed");
$display("CONTRACT_PROBES_PASS:1"); $finish;
end endmodule
'''
    return source, manifest, scopes, rtl


class BorrowProbeTest(unittest.TestCase):
    def test_actual_sources_toggle_all_bits_and_reject_mask_selector_and_live_source_faults(self):
        for top in ('FourPhaseSoc', 'ClickSoc'):
            source, manifest, scopes, rtl = fixture(top)
            extended, checks = telemetry_borrow_background(source, manifest, scopes, 1)
            self.assertEqual(checks, 441)
            self.assertIn('if (ones_0 !==', extended)
            self.assertIn('zeros_0 !==', extended)
            self.assertEqual(set(re.findall(r'force (\S+) =', extended)), set(re.findall(r'force (\S+) =', source)))
            cases = [(source, rtl, 'INACTIVE_ENDPOINT:borrowed'), (extended, rtl, None)]
            cases += [(extended, rtl.replace("selected=kind==2'h1", "selected=kind==2'h2"), 'TELEMETRY_BORROW_BINDING:' + top + '.native.command_bits_clear'),
                      (extended, rtl.replace("selected=kind==2'h1", "selected=1'b1"), 'TELEMETRY_BORROW_BINDING:' + top + '.native.command_bits_clear'),
                      (extended, rtl.replace('selected ? fabric_telemetryCommit_data', 'selected ? live_data'), 'TELEMETRY_BORROW_BINDING:' + top + '.native.command_bits_data'),
                      (extended, rtl.replace('out_bits_kind=data_kind', "out_bits_kind=data_kind ^ 2'h1"), 'TELEMETRY_BORROW_BINDING:' + top + '.sender.out_bits_kind')]
            with tempfile.TemporaryDirectory(prefix='riscay-borrow-probe-') as tmp:
                folder = Path(tmp)
                for stimulus, model, failure in cases:
                    (folder / 'test.sv').write_text(model + stimulus)
                    built = subprocess.run(['iverilog', '-g2012', '-s', top, '-s', 'ContractProbe', '-o', 'sim.vvp', 'test.sv'],
                                           cwd=folder, capture_output=True, text=True, timeout=30)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    run = subprocess.run(['vvp', 'sim.vvp'], cwd=folder, capture_output=True, text=True, timeout=30)
                    if failure is None:
                        self.assertEqual(run.returncode, 0, run.stdout)
                        self.assertIn('CONTRACT_PROBES_PASS:441', run.stdout)
                    else:
                        self.assertNotEqual(run.returncode, 0)
                        fatal = re.findall(r'^FATAL: test\.sv:(\d+): (.*)$', run.stdout, re.M)
                        self.assertEqual(len(fatal), 1, run.stdout)
                        sites = [i for i, line in enumerate((model + stimulus).splitlines(), 1)
                                 if '$fatal' in line and '"' + failure + '"' in line]
                        self.assertEqual(sites, [int(fatal[0][0])], run.stdout)
                        self.assertEqual(fatal[0][1], failure, run.stdout)

    def test_zero_one_and_two_capture_layouts(self):
        for top in ('FourPhaseSoc', 'ClickSoc'):
            for channels in (0, 1, 2):
                source, manifest, scopes, _ = fixture(top, channels)
                self.assertEqual(telemetry_borrow_background(source, manifest, scopes, 1)[1], 441)

    def test_exact_layout_fields_offsets_widths_signedness_and_sources(self):
        for top in ('FourPhaseSoc', 'ClickSoc'):
            for child in range(2):
                for channel in range(1 if child == 0 else 2):
                    for key, value in (('field', 'bits.wrong'), ('lsb', 1), ('width', 999), ('signed', True), ('source', 'wrong')):
                        source, manifest, scopes, _ = fixture(top)
                        manifest['design']['children'][child]['contract']['channels'][channel]['layout'][0][key] = value
                        with self.assertRaisesRegex(ValueError, 'TELEMETRY_BORROW_LAYOUT'):
                            telemetry_borrow_background(source, manifest, scopes, 1)

    def test_missing_or_wrong_actual_source_and_pin_fail_closed(self):
        for top in ('FourPhaseSoc', 'ClickSoc'):
            for target, group, key, value, diagnostic in (
                    (top, 'registers', 'fabric_telemetryCommit_data', 31, 'SOURCE'),
                    (top + '.sender', 'registers', 'data_kind', None, 'SOURCE'),
                    (top + '.native', 'ports', 'command_bits_clear', dict(width=6, direction='output'), 'PIN'),
                    (top + '.sender', 'ports', 'out_bits_kind', dict(width=1, direction='output'), 'PIN')):
                source, manifest, scopes, _ = fixture(top)
                scopes[target][group][key] = value
                with self.assertRaisesRegex(ValueError, 'TELEMETRY_BORROW_' + diagnostic):
                    telemetry_borrow_background(source, manifest, scopes, 1)
            source, manifest, scopes, _ = fixture(top)
            with self.assertRaisesRegex(ValueError, 'TELEMETRY_BORROW_DRIVER'):
                telemetry_borrow_background(source.replace(f"force {top}.sender.data_kind = 2'h0;\n", ''), manifest, scopes, 1)


if __name__ == '__main__':
    unittest.main()

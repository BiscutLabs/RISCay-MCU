# SPDX-License-Identifier: Apache-2.0
"""RAM receipt policy checks and explicit actual-emitted-RTL negative controls.

Run --bd-export DIR --click-export DIR for the real integration campaign. Those
arguments require complete existing functional exports, including sim.vvp. This
script does not elaborate, simulate or modify the input evidence. With no export
arguments only the parser/policy unit tests run; no RTL campaign is claimed.
"""
import argparse
import copy
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from check_ram_capture_receipt import (ACCESS_REGISTERS, RECEIPT_REGISTERS, HEADER_POLICY, ClosedModule,
    compact, load_export, receipt_ports, validate_ram_access, validate_receipt_rtl)


class CapturePolicyTests(unittest.TestCase):
    def test_state_budget_is_exact_and_names_are_distinct(self):
        self.assertEqual(len(RECEIPT_REGISTERS), 5)
        self.assertEqual(len(ACCESS_REGISTERS), 15)
        self.assertEqual(len(set(RECEIPT_REGISTERS)), 5)
        self.assertEqual(len(set(ACCESS_REGISTERS)), 15)
        self.assertEqual(set(RECEIPT_REGISTERS), {'localReset_release_0', 'localReset_release_1', 'requestMeta', 'requestSync', 'phase'})

    def test_unknown_abi_and_hidden_prefix_cannot_be_consumed(self):
        ports = ','.join(d + ' ' + n for n, (d, _) in receipt_ports().items())
        source = HEADER_POLICY + '\nmodule Receipt(' + ports + ');endmodule'
        ClosedModule(source, 'Receipt', receipt_ports()).close()
        for bad in (source.replace('input request', 'output request'), source.replace('request,', 'request,input surprise,'),
                    source.replace('module Receipt', '`define request phase\nmodule Receipt')):
            with self.assertRaisesRegex(ValueError, 'RAM_CAPTURE_(PORTS|PREFIX)'):
                ClosedModule(bad, 'Receipt', receipt_ports())

    def test_remaining_writers_and_extra_state_are_rejected(self):
        ports = ','.join(d + ' ' + n for n, (d, _) in receipt_ports().items())
        for extra in ('reg state;', 'assign accepted=request;', 'initial phase=1;', 'always @(posedge clock) phase<=1;',
                      'force phase=1;', 'logic phase;', '`define phase request'):
            module = ClosedModule(HEADER_POLICY + '\nmodule Receipt(' + ports + ');' + extra + 'endmodule',
                                  'Receipt', receipt_ports())
            with self.assertRaisesRegex(ValueError, 'RAM_CAPTURE_UNCONSUMED_RTL'):
                module.close()


def actual_campaign(directories, library):
    """Return evidence only after every positive and negative control passes."""
    results = {}
    for variant, directory in directories.items():
        directory = directory.resolve()
        access, scopes = load_export(directory, library)
        baseline = validate_ram_access(access, directory, scopes)
        if baseline['variant'] != variant:
            raise AssertionError('RAM_CAPTURE_TEST_VARIANT')
        children = {c['id']: c['contract'] for c in access['children']}
        receipt = children['capture_receipt']
        models = {n: scopes[c['rtl_path']]['model'] for n, c in children.items()}
        model = scopes[access['rtl_path']]['model']
        originals = {m: (directory / (m + '.sv')).read_text(encoding='utf-8') for m in {model, *models.values()}}
        before = {m: hashlib.sha256(s.encode()).hexdigest() for m, s in originals.items()}
        before_files = {m: hashlib.sha256((directory / (m + '.sv')).read_bytes()).hexdigest() for m in originals}
        passed = []
        with tempfile.TemporaryDirectory(prefix='riscay-ram-capture-controls-') as temporary:
            out = Path(temporary)
            for m, source in originals.items():
                (out / (m + '.sv')).write_text(source, encoding='utf-8')

            def check(name, mutate, diagnostic='RAM_CAPTURE_'):
                bad_node, bad_scopes = copy.deepcopy(access), copy.deepcopy(scopes)
                for m, source in originals.items():
                    (out / (m + '.sv')).write_text(source, encoding='utf-8')
                mutate(bad_node, bad_scopes, out)
                try:
                    validate_ram_access(bad_node, out, bad_scopes)
                except ValueError as error:
                    if not re.search(diagnostic, str(error)):
                        raise AssertionError(name + ': wrong diagnostic ' + str(error)) from error
                    passed.append(dict(name=name, diagnostic=str(error)))
                else:
                    raise AssertionError('RAM_CAPTURE_NEGATIVE_PASSED:' + name)

            def rtl(name, target, old, new, diagnostic='RAM_CAPTURE_', count=1):
                def mutate(_node, _scopes, folder):
                    p = folder / (target + '.sv')
                    s = p.read_text(encoding='utf-8')
                    # Match whitespace-insensitively so comments/locations never
                    # become the mutation's target or the rejection evidence.
                    s = re.sub(r'/\*.*?\*/|//[^\n]*', '', s, flags=re.S)
                    pattern = r'\s*'.join(re.escape(ch) for ch in compact(old))
                    matches = list(re.finditer(pattern, s))
                    if len(matches) != count:
                        raise AssertionError(f'RAM_CAPTURE_MUTATION_SHAPE:{name}:{len(matches)}')
                    p.write_text(re.sub(pattern, lambda _: new, s), encoding='utf-8')
                check(name, mutate, diagnostic)

            rm = models['capture_receipt']
            rtl('receipt-bypass-second-sync', rm, 'requestSync<=requestMeta;', 'requestSync<=request;', 'RECEIPT_ACCEPTANCE')
            rtl('receipt-bypass-first-sync', rm, 'requestMeta<=request;', 'requestMeta<=phase;', 'RECEIPT_ACCEPTANCE')
            rtl('receipt-wrong-reset-pin', rm, 'posedge reset)', 'posedge accept)', 'RECEIPT_RESET_RELEASE')
            rtl('receipt-wrong-clock-edge', rm, 'posedge clock', 'negedge clock', 'RECEIPT_RESET_RELEASE', count=2)
            rtl('receipt-release-shortened', rm, "localReset_release_1<=localReset_release_0;", "localReset_release_1<=1'h0;", 'RECEIPT_RESET_RELEASE')
            rtl('receipt-ack-speculative', rm, 'assign acknowledge=phase;', 'assign acknowledge=requestSync;', 'RECEIPT_OUTPUT')
            rtl('receipt-accept-requires-idle-cycle', rm, 'accept &', 'accept & idle &', 'RECEIPT_WIRE')
            rtl('receipt-accept-ignores-active', rm, 'accept &', "1'h1 &", 'RECEIPT_WIRE')
            rtl('receipt-accept-ignores-local-reset', rm, '& ~packed_8_probe;', ';', 'RECEIPT_WIRE')
            rtl('receipt-stale-reset-phase', rm, "phase<=1'h0;", "phase<=1'h1;", 'RECEIPT_ACCEPTANCE')
            rtl('receipt-initial-stale-phase', rm, "phase=1'h0;", "phase=1'h1;", 'RECEIPT_INITIALIZATION')
            rtl('receipt-extra-register', rm, 'reg phase;', 'reg phase;reg hidden;', 'UNCONSUMED_RTL')
            rtl('receipt-declaration-writer', rm, 'reg phase;', "reg phase=1'b1;", 'RECEIPT_REGISTER')
            rtl('receipt-extra-procedural-writer', rm, 'endmodule', "always@(posedge clock)phase<=1'b0;endmodule", 'UNCONSUMED_RTL')
            rtl('receipt-extra-continuous-writer', rm, 'endmodule', "assign acknowledge=1'b0;endmodule", 'UNCONSUMED_RTL')
            rtl('receipt-macro-pin-rewrite', rm, 'module ' + rm, '`define accept idle\nmodule ' + rm, 'PREFIX')
            if variant == 'click':
                rtl('receipt-click-compares-as-rtz', rm, 'requestSync != phase', 'requestSync & ~phase', 'RECEIPT_WIRE')
                rtl('receipt-click-phase-not-retained', rm, 'if(_accepted_output)phase<=requestSync;', 'phase<=requestSync;', 'RECEIPT_ACCEPTANCE')
            else:
                rtl('receipt-bd-ack-does-not-return', rm, 'phase<=_accepted_output|requestSync&phase;', 'phase<=_accepted_output|phase;', 'RECEIPT_ACCEPTANCE')

            rtl('access-active-clears-from-idle', model, '~_ca_child_capture_receipt_accepted &', '~_ca_child_capture_receipt_idle &', 'ACCESS_ACTIVE_AND_OBSERVATION')
            rtl('access-owner-idle-blocks-effects', model, 'wire drained=', 'wire drained=ownerReturned_stages_1 &', 'ACCESS_WIRE:drained')
            rtl('access-receipt-omitted-from-drain', model, '&_ca_child_capture_receipt_idle;', ';', 'ACCESS_WIRE:drained')
            rtl('access-omits-command-return', model, '&_ca_child_command_bridge_in_ready', '', 'ACCESS_WIRE:drained')
            rtl('access-owner-idle-omitted-from-busy', model, 'assign io_busy=active|~drained|~ownerReturned_stages_1|localReset_release_1;',
                'assign io_busy=active|~drained|localReset_release_1;', 'ACCESS_OUTPUT:io_busy')
            rtl('access-admits-while-active', model, 'io_request_valid & ~active & drained', 'io_request_valid & drained', 'ACCESS_WIRE:ca_child_command_bridge_in_valid')
            rtl('access-readiness-ignores-return-owner', model, 'assign io_request_ready=~active&drained&ownerReturned_stages_1;',
                'assign io_request_ready=~active&drained;', 'ACCESS_OUTPUT:io_request_ready')
            rtl('access-active-wrong-local-reset', model, 'posedge localReset_release_1)', 'posedge reset)', 'ACCESS_ACTIVE_AND_OBSERVATION')
            rtl('access-return-idle-bypasses-second-sync', model, 'ownerReturned_stages_1<=ownerReturned_stages_0;',
                'ownerReturned_stages_1<=returnIdle;', 'ACCESS_ACTIVE_AND_OBSERVATION')
            rtl('access-word-return-bypasses-first-sync', model, 'returned_stages_1<=returned_stages_0;',
                'returned_stages_1<=word_ack;', 'ACCESS_ACTIVE_AND_OBSERVATION')
            if variant == 'bd':
                rtl('access-native-ack-omitted-from-sync', model, 'returned_stages_0<=~packed_0&~word_ack;',
                    'returned_stages_0<=~packed_0;', 'ACCESS_ACTIVE_AND_OBSERVATION')
                rtl('access-native-ack-enters-admission', model, 'wire drained=',
                    'wire drained=~word_ack&', 'ACCESS_WIRE:drained')
            rtl('access-extra-register', model, 'reg active;', 'reg active;reg shadow;', 'UNCONSUMED_RTL')
            rtl('access-declaration-writer', model, 'reg active;', "reg active=1'b0;", 'ACCESS_REGISTER')
            rtl('access-extra-active-writer', model, 'endmodule', "always@(posedge clock)active<=1'b0;endmodule", 'UNCONSUMED_RTL')
            rtl('access-initial-active', model, "active=1'h0;", "active=1'h1;", 'ACCESS_INITIALIZATION')
            for i in range(4):
                rtl(f'access-byte-{i}-reply-return-omitted', model, f'&_ca_child_byte_reply_{i}_in_ready', '', 'ACCESS_WIRE:drained')
                first = 'bytesReturned_stages_0' if i == 0 else f'bytesReturned_stages_{i}_0'
                second = 'bytesReturned_stages_1' if i == 0 else f'bytesReturned_stages_{i}_1'
                rtl(f'access-byte-{i}-second-sync-bypass', model, second + '<=' + first + ';', second + '<=word_ack;', 'ACCESS_ACTIVE_AND_OBSERVATION')
            for label, child, pin, old, new in (
                ('receipt-active-idle-cycle', 'capture_receipt', 'accept', 'active', 'ownerReturned_stages_1'),
                ('receipt-wrong-request', 'capture_receipt', 'request', 'captureRequest', 'word_ack'),
                ('receipt-clear-speculative', 'capture_receipt', 'accepted', '_ca_child_capture_receipt_accepted', '_ca_child_capture_receipt_idle'),
                ('native-word-ack-cycle', 'native', 'response_ack', 'word_ack', 'captureAcknowledge'),
                ('native-word-payload-loss', 'native', 'response_bits', 'packed_1', 'io_request_bits_data'),
                ('command-payload-alias', 'command_bridge', 'in_bits_data', 'io_request_bits_data', 'io_request_bits_address')):
                def mutate(_node, _scopes, folder, child=child, pin=pin, old=old, new=new):
                    p = folder / (model + '.sv'); s = p.read_text(encoding='utf-8')
                    pattern = (r'(' + re.escape(models[child]) + r'\s+ca_child_' + child + r'\s*\(.*?\.' + pin +
                               r'\s*\()' + re.escape(old) + r'(\))')
                    s, count = re.subn(pattern, lambda m: m[1] + new + m[2], s, flags=re.S)
                    if count != 1:
                        raise AssertionError('RAM_CAPTURE_PIN_MUTATION_SHAPE:' + label)
                    p.write_text(s, encoding='utf-8')
                check('actual-' + label, mutate, 'ACCESS_PINS:' + child)
            # Mutate each actual child clock/reset pin in its instance only.
            for name, child_model in models.items():
                for pin in ('reset', 'clock'):
                    if pin == 'clock' and name == 'native':
                        continue
                    def mutate(_node, _scopes, folder, name=name, child_model=child_model, pin=pin):
                        p = folder / (model + '.sv'); s = p.read_text(encoding='utf-8')
                        pattern = r'(' + re.escape(child_model) + r'\s+ca_child_' + name + r'\s*\(.*?\.' + pin + r'\s*\()' + pin + r'(\))'
                        s, count = re.subn(pattern, lambda m: m[1] + ('clock' if pin == 'reset' else 'reset') + m[2], s, flags=re.S)
                        if count != 1:
                            raise AssertionError('RAM_CAPTURE_PIN_MUTATION_SHAPE')
                        p.write_text(s, encoding='utf-8')
                    check('actual-child-' + name + '-' + pin, mutate, 'ACCESS_PINS:' + name)
            for target, registers in ((access, ACCESS_REGISTERS), (receipt, RECEIPT_REGISTERS)):
                for name in registers:
                    def mutate(_node, bad_scopes, _folder, target=target, name=name):
                        del bad_scopes[target['rtl_path']]['registers'][name]
                    check('scope-missing-' + target['module'] + '-' + name, mutate, 'REGISTER_INVENTORY')
                for label, name, width in (('extra', 'untracked', 1), ('wide', registers[-1], 2)):
                    def mutate(_node, bad_scopes, _folder, target=target, name=name, width=width):
                        bad_scopes[target['rtl_path']]['registers'][name] = width
                    check('scope-' + label + '-' + target['module'], mutate, 'REGISTER_INVENTORY')
                check('scope-hidden-memory-' + target['module'],
                    lambda n, s, p, target=target: s[target['rtl_path']]['memories'].update(hidden=(32, 1)), 'MEMORY_INVENTORY')
                check('scope-hidden-port-' + target['module'],
                    lambda n, s, p, target=target: s[target['rtl_path']]['ports'].update(hidden=dict(name='hidden', direction='input', width=1)), 'SCOPE_PORTS')
            for name in children:
                def mutate(node, _scopes, _folder, name=name):
                    next(c['contract'] for c in node['children'] if c['id'] == name)['reset_domain'] = 'application'
                check('metadata-child-domain-' + name, mutate, 'CHILD_DOMAIN_OR_PATH')
            check('metadata-extra-child', lambda n, s, p: n['children'].append(dict(id='hidden', contract={})), 'ACCESS_CHILD_INVENTORY')
            check('metadata-extra-endpoint', lambda n, s, p: n['endpoints'].append(dict(id='hidden', width=1)), 'ENDPOINT_INVENTORY')
            check('metadata-rtz-protocol-substitution', lambda n, s, p: n['channels'][0].update(protocol='four-phase-bundled-v1' if variant == 'click' else 'two-phase-bundled-v1'), 'ACCESS_CHANNEL_SCHEMA')
            check('scope-foreign-receipt-model', lambda n, s, p: s[receipt['rtl_path']].update(model='OtherReceipt'), 'RESOLVED_OWNER')
            check('scope-hidden-child', lambda n, s, p: s.update({access['rtl_path'] + '.hidden': dict(model='Other')}), 'SCOPE_CHILD_INVENTORY')
            check('scope-hidden-receipt-child', lambda n, s, p: s.update({receipt['rtl_path'] + '.hidden': dict(model='Other')}), 'RECEIPT_SCOPE_CHILDREN')
        after = {m: hashlib.sha256((directory / (m + '.sv')).read_bytes()).hexdigest() for m in originals}
        if before_files != after:
            raise AssertionError('RAM_CAPTURE_SOURCE_CHANGED')
        results[variant] = dict(directory=str(directory), positive=True, negative_controls=len(passed), controls=passed,
            source_text_sha256=before, source_file_sha256=after, originals_preserved=True,
            receipt_clocked_bits=baseline['receipt_clocked_bits'], access_clocked_bits=baseline['access_clocked_bits'])
    return dict(schema='riscay-ram-capture-static-controls-v1', passed=True, variants=results,
                negative_controls=sum(r['negative_controls'] for r in results.values()),
                scope='actual emitted RTL static controls; not dynamic simulation or physical qualification')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bd-export', type=Path)
    parser.add_argument('--click-export', type=Path)
    parser.add_argument('--library', type=Path, default=Path('P:/Personal/chisel-async'))
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if bool(args.bd_export) != bool(args.click_export):
        parser.error('both --bd-export and --click-export are required for the actual RTL campaign')
    run = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CapturePolicyTests))
    if not run.wasSuccessful():
        sys.exit(1)
    if args.bd_export:
        result = actual_campaign(dict(bd=args.bd_export, click=args.click_export), args.library)
        if args.out:
            args.out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print('PASS: both actual RTL exports; ' + str(result['negative_controls']) + ' rejected controls')

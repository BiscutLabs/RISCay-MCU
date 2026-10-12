# SPDX-License-Identifier: Apache-2.0
"""Parser/evidence policy controls; these do not claim RTL simulation coverage."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from check_program_return_wiring_controls import (bind_diagnostics, classify_simulation,
    copy_inputs, read_baseline, sha256, cases_for)


EXPECTED_ENDPOINTS = {
    'word-request': ('program_return', 'word_request'),
    'word-data': ('program_return', 'word_data'),
    'word-acknowledge': ('program_return', 'word_acknowledge'),
    'publication-request': ('program_return', 'publication_request'),
    'publication-data': ('program_return', 'publication_data'),
    'publication-acknowledge': ('program_return', 'publication_acknowledge'),
    'capture-request': ('program_return', 'capture_request'),
    'capture-acknowledge': ('program_return', 'capture_acknowledge'),
    'response-request': ('program_return', 'response_request'),
    'response-data': ('program_return', 'response_data'),
    'response-acknowledge': ('program_return', 'response_acknowledge'),
    'eligibility': ('program_return', 'eligible'),
    'cpu-role-bypassed': ('program_return', 'eligible'),
    'presentation-reset-to-por': ('program_return', 'application_reset'),
    'retained-owner-reset-to-application': ('program_return', 'reset'),
    'access-reset-to-application': ('program_access', 'reset'),
    'access-clock': ('program_access', 'clock'),
    'return-idle': ('program_return', 'idle'),
    'effects-drain-omitted': ('program_source', 'word_drained'),
    'presentation-drain-omitted': ('program_source', 'word_drained'),
    'full-busy-drain-cycle': ('program_source', 'word_drained'),
}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def fixture(root, variant='bd'):
    """Small, explicitly synthetic files exercise the real baseline reader."""
    top = 'ClickSoc' if variant == 'click' else 'FourPhaseSoc'
    prefix = 'Click' if variant == 'click' else 'FourPhase'
    owners = dict(program_return=prefix + 'ProgramReturn', program_source=prefix + 'ProgramSource',
                  program_access='ProgramAccess', completion=prefix + 'Completion')
    endpoint_ids = {field for _, field in EXPECTED_ENDPOINTS.values()} | {
        'publication_request', 'publication_data', 'publication_acknowledge', 'cpu_presentation_permit'}
    children = []
    paths = {}
    for owner, module in owners.items():
        endpoints = [dict(id=field, probe=owner + '_' + field,
                          rtl_path=top + '.ca_child_' + owner + '.unresolved_' + field)
                     for field in sorted(endpoint_ids)]
        children.append(dict(id=owner, contract=dict(module=module, rtl_path=top + '.ca_child_' + owner,
                                                     endpoints=endpoints)))
        paths.update({e['probe']: top + '.ca_child_' + owner + '.' + e['id'] for e in endpoints})
    pins = {
        'program_return': dict(word_req='word_request', word_bits='word_bits', publication_ack='publication_ack',
            captureAcknowledge='capture_ack', response_ack='response_ack', eligible='cpu_permit', reset='reset',
            applicationReset='application_reset', presentationSettled='presentation_settled'),
        'program_source': dict(publication_req='publication_request', publication_bits='publication_bits',
            wordDrained='effects_drained & presentation_settled', eligible='eligible', cpuPresentationPermit='cpu_permit'),
        'program_access': dict(word_ack='word_ack', captureRequest='capture_req', reset='reset', clock='work_clock',
            returnIdle='return_idle', effectsDrained='effects_drained', io_busy='access_busy'),
        'completion': dict(memory_req='response_request', memory_bits_data='response_bits'),
    }
    rtl = 'module ' + top + ';\n' + '\n'.join(owners[o] + ' ca_child_' + o + '(' +
        ','.join('.' + p + '(' + v + ')' for p, v in ports.items()) + ');' for o, ports in pins.items()) + '\nendmodule\n'
    (root / (top + '.sv')).write_text(rtl, encoding='utf-8')
    abi_file = 'ref_' + top + '.sv'
    abi_text = '// Synthetic probe ABI for policy tests only.\n'
    (root / abi_file).write_text(abi_text, encoding='utf-8')
    manifest = dict(top=top, design=dict(children=children),
                    probe_abi=dict(file=abi_file, sha256=hashlib.sha256(abi_text.encode()).hexdigest()))
    semantic = hashlib.sha256(json.dumps(manifest, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    write_json(root / 'contract.json', dict(manifest=manifest, semantic_sha256=semantic))
    receipt = dict(status='PASS', semantic_sha256=semantic, mapping_checks=42,
                   source_sha256={top + '.sv': sha256(root / (top + '.sv'))},
                   probe_abi_sha256=manifest['probe_abi']['sha256'], probe_paths=paths)
    write_json(root / 'resolved.json', receipt)
    (root / 'filelist.f').write_text(top + '.sv\n', encoding='utf-8')
    write_json(root / 'program-return-reset-boundary.json', dict(integration=dict(top=top),
        capture_receipt=dict(receipt_clocked_bits=5, access_clocked_bits=15)))
    permit = paths['program_source_cpu_presentation_permit']
    eligible = paths['program_return_eligible']
    conditions = {'PROGRAM_RETURN_BOUNDARY:' + eligible: eligible + ' !== ' + permit,
                  'PROGRAM_SOURCE_BINDING:' + permit: permit + ' !== ' + eligible}
    probe = 'module ContractProbe;\ntask check; begin\n' + '\n'.join(
        'if (' + conditions.get(kind + ':' + path, 'a !== b') + ') $fatal(1,"' + kind + ':' + path + '");'
        for kind in ('PROGRAM_RETURN_BOUNDARY', 'PROGRAM_SOURCE_BINDING') for path in sorted(set(paths.values())))
    # The production probe has an earlier internal role equation bearing the
    # same message. It must not be admitted as a top-level wiring assertion.
    probe += '\nif (' + permit + ' !== (owned && eligible)) $fatal(1,"PROGRAM_SOURCE_BINDING:' + permit + '");'
    probe += '\nend endtask\nendmodule\n'
    (root / 'contract_probe.sv').write_text(probe, encoding='utf-8')
    (root / 'contract_probe.vvp').write_bytes(b'SYNTHETIC policy-test executable placeholder; never executed\n')
    (root / 'contract_simulation.log').write_text('CONTRACT_PROBES_PASS:42\n', encoding='utf-8')
    attestation = dict(schema='riscay-mapping-probe-attestation-v1', status='PASS',
        probe_sha256=sha256(root / 'contract_probe.sv'), compiled_vvp_sha256=sha256(root / 'contract_probe.vvp'),
        simulation_log_sha256=sha256(root / 'contract_simulation.log'), mapping_checks=42,
        source_sha256=receipt['source_sha256'], semantic_sha256=semantic)
    write_json(root / 'mapping-probe-attestation.json', attestation)
    return read_baseline(variant, root)


def fatal_log(site, message=None, line=None, source=None, scope=None):
    return (f"FATAL: {source or site['source']}:{line if line is not None else site['line']}: "
            f"{message or site['message']}\n       Time: 123  Scope: {scope or site['scope']}\n")


class BaselineEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.baseline = fixture(self.root)

    def test_both_catalogues_bind_only_their_expected_boundary(self):
        click = self.root / 'click'
        click.mkdir()
        for baseline in (self.baseline, fixture(click, 'click')):
            top = baseline['manifest']['top']
            self.assertEqual({c['name'] for c in baseline['cases']}, set(EXPECTED_ENDPOINTS))
            for case in baseline['cases']:
                owner, endpoint = EXPECTED_ENDPOINTS[case['name']]
                expected = {'PROGRAM_RETURN_BOUNDARY:' + top + '.ca_child_' + owner + '.' + endpoint}
                if case['name'].startswith('publication-'):
                    expected.add('PROGRAM_SOURCE_BINDING:' + top + '.ca_child_program_source.' + endpoint)
                if endpoint == 'word_drained':
                    expected.add('PROGRAM_SOURCE_BINDING:' + top + '.ca_child_program_source.word_drained')
                if case['name'] in ('eligibility', 'cpu-role-bypassed'):
                    expected.add('PROGRAM_SOURCE_BINDING:' + top + '.ca_child_program_source.cpu_presentation_permit')
                self.assertEqual({f['message'] for f in case['allowed_fatals']}, expected)

    def test_permission_cases_accept_only_exact_cross_owner_assertion_sites(self):
        click = self.root / 'click'
        click.mkdir()
        for baseline in (self.baseline, fixture(click, 'click')):
            for case in (c for c in baseline['cases'] if c['name'] in ('eligibility', 'cpu-role-bypassed')):
                with self.subTest(top=baseline['manifest']['top'], case=case['name']):
                    self.assertEqual(len(case['allowed_fatals']), 2)
                    for site in case['allowed_fatals']:
                        self.assertEqual(classify_simulation(dict(exit_code=0), dict(exit_code=1),
                            fatal_log(site), case['allowed_fatals']), [dict(site, time=123)])
                    site = next(f for f in case['allowed_fatals'] if f['message'].startswith('PROGRAM_SOURCE_BINDING:'))
                    internal_line = next(n for n, line in enumerate(baseline['probe'].decode().splitlines(), 1)
                                         if 'owned && eligible' in line)
                    for change in (dict(line=internal_line), dict(line=site['line'] + 1),
                                   dict(message=site['message'].replace('cpu_presentation_permit', 'eligible'))):
                        with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'UNEXPECTED_FATAL'):
                            classify_simulation(dict(exit_code=0), dict(exit_code=1),
                                fatal_log(site, **change), case['allowed_fatals'])

    def test_permission_binding_cannot_use_same_message_on_another_equation(self):
        for case in ('eligibility', 'cpu-role-bypassed'):
            permit = 'FourPhaseSoc.ca_child_program_source.cpu_presentation_permit'
            eligible = 'FourPhaseSoc.ca_child_program_return.eligible'
            for before, after in ((permit + ' !== ' + eligible, permit + ' !== raw_eligible'),
                                  (eligible + ' !== ' + permit, eligible + ' !== raw_eligible')):
                with self.subTest(case=case, equation=before), self.assertRaisesRegex(ValueError, 'DIAGNOSTIC_NOT_IN_PROBE'):
                    bind_diagnostics([dict(name=case)], self.baseline['manifest'], self.baseline['receipt'],
                                     self.baseline['probe'].replace(before.encode(), after.encode()))

    def test_role_bypass_control_requires_a_distinct_qualified_baseline(self):
        rtl = (self.root/'FourPhaseSoc.sv').read_text()
        case = next(c for c in self.baseline['cases'] if c['name']=='cpu-role-bypassed')
        self.assertEqual((case['before'],case['after']),('cpu_permit','eligible'))
        for bad in (rtl.replace('.eligible(cpu_permit)', '.eligible(eligible)'),
                    rtl.replace('.cpuPresentationPermit(cpu_permit)', '.cpuPresentationPermit(eligible)'),
                    rtl.replace('.cpuPresentationPermit(cpu_permit)', ".cpuPresentationPermit(1'b1)")):
            with self.subTest(rtl=bad), self.assertRaisesRegex(ValueError,'ROLE_QUALIFIED_PERMISSION_BINDING'):
                cases_for(bad,self.baseline['manifest'])

    def test_stale_probe_executable_and_log_are_rejected(self):
        for file, field in (('contract_probe.sv', 'probe_sha256'), ('contract_probe.vvp', 'compiled_vvp_sha256'),
                            ('contract_simulation.log', 'simulation_log_sha256')):
            with self.subTest(file=file):
                path = self.root / file
                original = path.read_bytes()
                path.write_bytes(original + b'\n// changed after PASS\n')
                with self.assertRaisesRegex(ValueError, 'ATTESTATION_MISMATCH:' + field):
                    read_baseline('bd', self.root)
                path.write_bytes(original)

    def test_each_attestation_field_is_required_and_checked(self):
        path = self.root / 'mapping-probe-attestation.json'
        original = json.loads(path.read_text())
        for field in original:
            for replacement in ('wrong', None):
                with self.subTest(field=field, replacement=replacement):
                    changed = copy.deepcopy(original)
                    if replacement is None:
                        del changed[field]
                    else:
                        changed[field] = replacement
                    write_json(path, changed)
                    with self.assertRaisesRegex(ValueError, 'ATTESTATION_(STATUS|MISMATCH)'):
                        read_baseline('bd', self.root)
        write_json(path, original)

    def test_missing_attestation_or_executable_is_rejected(self):
        for name in ('mapping-probe-attestation.json', 'contract_probe.vvp'):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(ValueError, 'STRICT_BASELINE_FILES'):
                    read_baseline('bd', self.root)
                path.write_bytes(original)

    def test_updated_source_receipt_cannot_reuse_old_attestation(self):
        path = self.root / 'FourPhaseSoc.sv'
        path.write_bytes(path.read_bytes() + b'\n// substituted RTL\n')
        receipt = copy.deepcopy(self.baseline['receipt'])
        receipt['source_sha256']['FourPhaseSoc.sv'] = sha256(path)
        write_json(self.root / 'resolved.json', receipt)
        with self.assertRaisesRegex(ValueError, 'ATTESTATION_MISMATCH:source_sha256'):
            read_baseline('bd', self.root)

    def test_copy_rejects_rtl_or_oracle_changed_after_baseline_read(self):
        for name, diagnostic in (('FourPhaseSoc.sv', 'COPIED_RTL_CHANGED'),
                                 ('contract_probe.sv', 'COPIED_ORACLE_CHANGED')):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b'\n// changed after baseline read\n')
                with self.assertRaisesRegex(ValueError, diagnostic):
                    copy_inputs(self.baseline, self.root / ('copied-' + name))
                path.write_bytes(original)

    def test_receipt_source_and_semantic_checks_still_apply(self):
        receipt_path = self.root / 'resolved.json'
        for field in ('source_sha256', 'semantic_sha256'):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.baseline['receipt'])
                changed[field] = 'changed'
                write_json(receipt_path, changed)
                with self.assertRaisesRegex(ValueError, 'RTL_CHANGED|STRICT_SEMANTIC_HASH'):
                    read_baseline('bd', self.root)
        write_json(receipt_path, self.baseline['receipt'])

    def test_wrong_mapping_count_or_pending_baseline_is_rejected(self):
        receipt_path = self.root / 'resolved.json'
        for field, value in (('mapping_checks', 43), ('mapping_checks', True), ('status', 'PENDING')):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(self.baseline['receipt'])
                changed[field] = value
                write_json(receipt_path, changed)
                with self.assertRaisesRegex(ValueError, 'STRICT_POSITIVE_LOG|MAPPING_COUNT|STRICT_BASELINE_NOT_COMPLETE'):
                    read_baseline('bd', self.root)

    def test_declared_endpoint_must_resolve_to_its_owner(self):
        receipt = copy.deepcopy(self.baseline['receipt'])
        receipt['probe_paths']['program_return_word_request'] = 'FourPhaseSoc.other.word_request'
        with self.assertRaisesRegex(ValueError, 'DIAGNOSTIC_RESOLUTION'):
            bind_diagnostics([dict(name='word-request')], self.baseline['manifest'], receipt, self.baseline['probe'])

    def test_display_and_commented_assertions_are_not_allowed_sites(self):
        for form in ('if (a !== b) $display(1,"{message}");', '// if (a !== b) $fatal(1,"{message}");',
                     '/*\nif (a !== b) $fatal(1,"{message}");\n*/'):
            with self.subTest(form=form):
                message = self.baseline['cases'][0]['allowed_fatals'][0]['message']
                probe = form.format(message=message).encode()
                with self.assertRaisesRegex(ValueError, 'DIAGNOSTIC_NOT_IN_PROBE'):
                    bind_diagnostics([dict(name='word-request')], self.baseline['manifest'], self.baseline['receipt'], probe)


class FatalClassificationTests(unittest.TestCase):
    def setUp(self):
        self.site = dict(source='contract_probe.sv', line=42,
                         message='PROGRAM_RETURN_BOUNDARY:FourPhaseSoc.ca_child_program_return.word_req',
                         scope='ContractProbe.check')
        self.compiled = dict(exit_code=0)
        self.simulated = dict(exit_code=1)

    def classify(self, log, compiled=None, simulated=None, allowed=None):
        return classify_simulation(compiled if compiled is not None else self.compiled,
            simulated if simulated is not None else self.simulated, log,
            [self.site] if allowed is None else allowed)

    def test_actual_fatal_with_matching_line_scope_and_endpoint_passes(self):
        records = self.classify(fatal_log(self.site))
        self.assertEqual(records, [dict(self.site, time=123)])

    def test_display_only_and_display_plus_unrelated_fatal_fail(self):
        display = self.site['message'] + '\n'
        for log in (display, display + fatal_log(self.site, message='UNRELATED_FAILURE'),
                    display + fatal_log(self.site, message='PROGRAM_SOURCE_BINDING:source')):
            with self.subTest(log=log), self.assertRaisesRegex(ValueError, 'NO_TARGET_FATAL|UNEXPECTED_FATAL'):
                self.classify(log)

    def test_mixed_targeted_and_unrelated_fatal_fail_in_either_order(self):
        target = fatal_log(self.site)
        unrelated = fatal_log(self.site, message='UNRELATED_FAILURE')
        for log in (target + unrelated, unrelated + target):
            with self.subTest(log=log), self.assertRaisesRegex(ValueError, 'UNEXPECTED_FATAL'):
                self.classify(log)

    def test_wrong_case_endpoint_line_scope_and_source_fail(self):
        for replacement in (dict(message=self.site['message'].replace('word_req', 'word_bits')),
                            dict(message='PROGRAM_SOURCE_BINDING:wrong_source'), dict(line=43),
                            dict(scope='OtherTask.check'), dict(source='mutant.sv')):
            with self.subTest(replacement=replacement), self.assertRaisesRegex(ValueError, 'UNEXPECTED_FATAL'):
                self.classify(fatal_log(self.site, **replacement))

    def test_timeout_deadline_success_error_and_compile_failure_fail(self):
        target = fatal_log(self.site)
        for extra in ('WALL_TIMEOUT_NOT_A_PASS', 'SOC_DEADLINE', 'CONTRACT_PROBES_PASS:42',
                      'ERROR: unrelated error', 'syntax error'):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, 'FORBIDDEN_SIMULATION_RESULT'):
                self.classify(target + extra + '\n')
        for compiled in (dict(exit_code=1), dict(exit_code=None), dict(exit_code=0, timed_out=True)):
            with self.subTest(compiled=compiled), self.assertRaisesRegex(ValueError, 'COMPILE_FAILED'):
                self.classify(target, compiled=compiled)
        for simulated in (dict(exit_code=0), dict(exit_code=2), dict(exit_code=-9),
                          dict(exit_code=None, timed_out=True), dict(exit_code=1, timed_out=True)):
            with self.subTest(simulated=simulated), self.assertRaisesRegex(ValueError, 'SIMULATION_EXIT'):
                self.classify(target, simulated=simulated)

    def test_malformed_fatal_and_missing_context_fail(self):
        for log in ('FATAL: ' + self.site['message'] + '\n', fatal_log(self.site).splitlines()[0],
                    fatal_log(self.site).replace('       Time:', 'missing Time:'),
                    'prefix ' + fatal_log(self.site)):
            with self.subTest(log=log), self.assertRaisesRegex(ValueError, 'MALFORMED_FATAL|FATAL_CONTEXT'):
                self.classify(log)

    def test_multiple_appropriate_fatals_pass_but_no_allowlist_fails(self):
        other = dict(self.site, line=43, message='PROGRAM_SOURCE_BINDING:FourPhaseSoc.ca_child_program_source.publication_req')
        self.assertEqual(len(self.classify(fatal_log(self.site) + fatal_log(other), allowed=[self.site, other])), 2)
        with self.assertRaisesRegex(ValueError, 'NO_ALLOWED_FATAL'):
            self.classify(fatal_log(self.site), allowed=[])


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""Replay native RAM-return functional oracles against isolated RTL mutations.

The original functional oracles are preserved. The issue-history case changes
only two control-cell delays to the documented 10 ns maximum; its matching
unmutated baseline must also pass. Compile errors, global deadlines and simulator
timeouts never qualify a negative control. This checks digital protocol behavior,
not physical timing or the complete SoC integration.
"""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

from check_ram_return_capture_controls import source_oracles
from check_admission_controls import replace_pin
from check_i2c_wiring_controls import hashes, run
from check_recovery_capture_controls import pin_expression


def primitive(node, name):
    matches = [p for p in node['primitives'] if p['id'] == name]
    if len(matches) != 1:
        raise ValueError('RAM_RETURN_CONTROL_PRIMITIVE:' + name)
    return matches[0]['rtl_path'].rsplit('.', 1)[1]


def pin(text, node, name, port, value):
    return replace_pin(text, primitive(node, name), port, value)


def expression(text, node, name, port='q'):
    return pin_expression(text, primitive(node, name), port)


def assignment(text, name, value):
    pattern = r'(\bassign\s+' + re.escape(name) + r'\s*=\s*)([^;]+)(;)'
    changed, count = re.subn(pattern, lambda m: m[1] + value + m[3], text)
    if count != 1 or changed == text:
        raise ValueError('RAM_RETURN_CONTROL_ASSIGNMENT:' + name)
    return changed


def transform_assignment(text, name, transform):
    match = re.search(r'\bassign\s+' + re.escape(name) + r'\s*=\s*([^;]+);', text)
    if not match:
        raise ValueError('RAM_RETURN_CONTROL_ASSIGNMENT:' + name)
    return assignment(text, name, transform(match[1]))


def replace_expression(text, node, name, port, old, new):
    original = expression(text, node, name, port)
    if original.count(old) != 1:
        raise ValueError('RAM_RETURN_CONTROL_EXPRESSION:' + name + ':' + port)
    return pin(text, node, name, port, original.replace(old, new))


SKEW_PROFILES = {'issue-history': ('permission', 'issue_pending')}
RESET_STAGES = ('held', 'arm', 'issue', 'offered', 'ack', 'cleanup', 'repeated',
                'release_arm', 'release_issue', 'receipt_hold')


def fixture_inventory(variant):
    expected = {'stalls', 'cancel', 'offer-bound'}
    expected.update('reset-' + stage + '-' + str(prior)
                    for stage in RESET_STAGES
                    for prior in ((1, 2) if variant == 'click' else (1,)))
    if variant == 'bd':
        expected.update('full-return-' + branch
                        for branch in ('input', 'publication', 'receipt', 'application'))
    return expected


def directed_skew(test, node, profile):
    paths = []
    for name in SKEW_PROFILES[profile]:
        path = 'dut.' + next(p['rtl_path'].split('.', 1)[1]
                             for p in node['primitives'] if p['id'] == name)
        old = 'defparam ' + path + '.DELAY_FS=1000000;'
        if test.count(old) != 1:
            raise ValueError('RAM_RETURN_CONTROL_SKEW_SHAPE:' + name)
        test = test.replace(old, 'defparam ' + path + '.DELAY_FS=10000000;')
        paths.append(path)
    return test, paths


def controls(variant):
    """Each entry names the exact broken obligation and independent diagnostic."""
    cases = []

    def add(name, fixture, mutate, *expected, profile=None):
        cases.append((name, fixture, mutate, expected, profile))

    add('retained-response-live-input', 'stalls',
        lambda t, n: assignment(t, 'response_bits_data', 'word_bits'),
        'RAM_RESPONSE_PAYLOAD', 'RAM_APP_DATA_HOLD')
    add('publication-live-input', 'stalls',
        lambda t, n: assignment(t, 'publication_bits', 'word_bits[0]'),
        'RAM_PUBLICATION_IDENTITY', 'DATA_HOLD publication')
    add('response-error-high', 'stalls',
        lambda t, n: assignment(t, 'response_bits_error', "1'b1"),
        'RAM_RESPONSE_PAYLOAD')
    add('payload-application-reset', 'reset-offered-1',
        lambda t, n: pin(t, n, 'payload', 'reset', 'presentationReset'),
        'RAM_RESET_RETAINED_WORD', 'RAM_PUBLICATION_IDENTITY', 'DATA_HOLD publication')
    if variant == 'bd':
        add('permission-por-only', 'reset-issue-1',
            lambda t, n: pin(t, n, 'permission', 'reset', 'reset'),
            'RAM_RESET_STALE_PRESENTATION', 'RAM_RETURN_CLEANUP_BOUND')
    else:
        # Click's independently reset target also collapses to the canceled
        # application phase. Bypassing permission reset alone is therefore
        # functionally masked; the closed reset validator checks that pin.
        add('permission-and-target-por-only', 'reset-arm-2',
            lambda t, n: pin(pin(t, n, 'permission', 'reset', 'reset'), n,
                            'application_target', 'reset', 'reset'),
            'RAM_RESET_STALE_PRESENTATION', 'RAM_RETURN_CLEANUP_BOUND')
    add('permission-always-live', 'cancel',
        lambda t, n: pin(t, n, 'permission', 'd', "1'b1"),
        'RAM_CANCEL_COUNTS_OR_STALE_PHASE', 'RAM_CANCEL_REVIVED_PRESENTATION')

    if variant == 'bd':
        add('input-return-before-withdrawal', 'full-return-input',
            lambda t, n: pin(t, n, 'input_returned', 'rising', "2'b11"),
            'HANDSHAKE_ORDER word', 'RAM_PUBLICATION_IDENTITY')
        add('input-withdrawal-from-live-request', 'full-return-publication',
            lambda t, n: pin(t, n, 'input_offer_nb', 'a', 'word_req'),
            'HANDSHAKE_ORDER word', 'RAM_FULL_RETURN_EARLY_REUSE', 'RAM_RETURN_CLEANUP_BOUND')
        add('shutdown-history-truncated', 'stalls',
            lambda t, n: pin(t, n, 'history_common', 'b', "1'b0"),
            'HANDSHAKE_ORDER publication', 'RAM_CAPTURE_REQ_ORDER',
            'RAM_APP_REQ_ORDER', 'RAM_APP_ACK_ORDER', 'RAM_RETURN_COUNTS', 'RAM_RETURN_CLEANUP_BOUND')
        for branch, fixture, ack, diagnostic in (
                ('publication', 'full-return-publication', 'publication_ack', 'HANDSHAKE_ORDER publication'),
                ('receipt', 'full-return-receipt', 'captureAcknowledge', 'RAM_CAPTURE_REQ_ORDER')):
            add(branch + '-seen-without-ack', 'offer-bound',
                lambda t, n, branch=branch: pin(t, n, branch + '_seen', 'rising', "2'b11"),
                diagnostic, 'RAM_CAPTURE_REQ_RETURN', 'RAM_CAPTURE_ACK_ORDER', 'RAM_NATIVE_OFFER_BOUND')
            # Return proof and ingress capacity deliberately repeat the ACK-low
            # obligation. Name both bypasses: the isolated proof mutant is
            # masked by the independent capacity check and is not a control pass.
            def bypass_return_and_capacity(t, n, branch=branch, ack=ack):
                t = replace_expression(t, n, branch + '_returned', 'rising', '~' + ack, "1'b1")
                return transform_assignment(t, 'capacity', lambda e: e.replace('~' + ack, "1'b1"))
            add(branch + '-proof-and-capacity-full-return-bypass', fixture,
                bypass_return_and_capacity, 'RAM_FULL_RETURN_EARLY_REUSE', diagnostic,
                'RAM_RETURN_CLEANUP_BOUND', 'DATA_HOLD publication', 'RAM_APP_DATA_HOLD',
                'RAM_CAPTURE_ACK_RETURN')
        def application_return_bypass(t, n):
            original = expression(t, n, 'terminal', 'rising')
            if original.count('~response_ack') != 2:
                raise ValueError('RAM_RETURN_CONTROL_APPLICATION_RETURN_SHAPE')
            t = pin(t, n, 'terminal', 'rising', original.replace('~response_ack', "1'b1"))
            return transform_assignment(t, 'capacity', lambda e: e.replace('~response_ack', "1'b1"))
        add('application-proof-and-capacity-full-return-bypass', 'full-return-application',
            application_return_bypass, 'RAM_FULL_RETURN_EARLY_REUSE', 'RAM_APP_DATA_HOLD',
            'RAM_APP_REQ_ORDER', 'RAM_APP_ACK_RETURN')
        add('publication-ack-bound-to-receipt', 'stalls',
            lambda t, n: replace_expression(t, n, 'publication_seen', 'rising',
                                           'publication_ack', 'captureAcknowledge'),
            'HANDSHAKE_ORDER publication')
        add('receipt-ack-bound-to-publication', 'stalls',
            lambda t, n: replace_expression(t, n, 'receipt_seen', 'rising',
                                           'captureAcknowledge', 'publication_ack'),
            'RAM_CAPTURE_REQ_RETURN', 'RAM_CAPTURE_REQ_ORDER', 'RAM_CAPTURE_ACK_ORDER')
        add('application-reset-disconnected', 'reset-offered-1',
            lambda t, n: t.replace('packed_6_probe | packed_10_probe', 'packed_6_probe'),
            'RAM_RESET_SETTLEMENT')
    else:
        add('application-phase-por-only', 'reset-offered-2',
            lambda t, n: pin(t, n, 'application_phase', 'reset', 'reset'),
            'RAM_RESET_SETTLEMENT', 'RAM_RESET_STALE_PRESENTATION')
        add('received-phase-application-reset', 'reset-held-2',
            lambda t, n: pin(t, n, 'received_phase', 'reset', 'presentationReset'),
            'HANDSHAKE_ORDER word', 'ACK_WITHOUT_REQUEST word',
            'RAM_POR_PROGRESS_DURING_RESET', 'RAM_CAPTURE_PHASE_ORDER')
        add('issued-phase-application-reset', 'reset-held-1',
            lambda t, n: pin(t, n, 'issued_phase', 'reset', 'presentationReset'),
            'RAM_POR_PROGRESS_DURING_RESET', 'RAM_RETURN_CLEANUP_BOUND')
        add('completed-phase-application-reset', 'reset-held-1',
            lambda t, n: pin(t, n, 'completed_phase', 'reset', 'presentationReset'),
            'RAM_POR_PROGRESS_DURING_RESET', 'RAM_RETURN_CLEANUP_BOUND')
        add('target-bound-to-por-phase', 'offer-bound',
            lambda t, n: pin(t, n, 'target_data_delay', 'a', 'word_req'),
            'RAM_CANCEL_COUNTS_OR_STALE_PHASE', 'RAM_APPLICATION_OFFER_BOUND')
        add('issue-bypasses-permission', 'cancel',
            lambda t, n: pin(t, n, 'application_data_delay', 'a',
                            expression(t, n, 'application_target')),
            'RAM_CANCEL_COUNTS_OR_STALE_PHASE', 'RAM_CANCEL_REVIVED_PRESENTATION')
        add('issued-identity-from-completed', 'offer-bound',
            lambda t, n: pin(t, n, 'issue_data_delay', 'a',
                            expression(t, n, 'completed_phase')),
            'RAM_RETURN_CLEANUP_BOUND')
        add('completion-identity-from-application', 'cancel',
            lambda t, n: pin(t, n, 'finish_data_delay', 'a',
                            expression(t, n, 'application_phase')),
            'RAM_RETURN_CLEANUP_BOUND')
        add('publication-phase-from-application', 'offer-bound',
            lambda t, n: assignment(t, 'publication_req', expression(t, n, 'application_phase')),
            'RAM_PUBLICATION_IDENTITY', 'REQUEST_WHILE_PENDING publication',
            'RAM_NATIVE_OFFER_BOUND')
        add('receipt-phase-from-application', 'offer-bound',
            lambda t, n: assignment(t, 'captureRequest', expression(t, n, 'application_phase')),
            'RAM_CAPTURE_PHASE_ORDER', 'RAM_CAPTURE_ACK_ORDER', 'RAM_NATIVE_OFFER_BOUND')
        add('receipt-ack-bound-to-publication', 'stalls',
            lambda t, n: t.replace('& captureAcknowledge == _ca_primitive_received_phase_q',
                                    '& publication_ack == _ca_primitive_received_phase_q'),
            'RAM_RECEIPT_RESET_DRAIN_BYPASS', 'RAM_CAPTURE_PHASE_ORDER')
        add('application-request-four-phase-adapter', 'stalls',
            lambda t, n: assignment(t, 'response_req',
                                    '(' + expression(t, n, 'application_phase') + ' ^ response_ack)'),
            'RAM_APP_PHASE_ORDER', 'RAM_APP_ACK_ORDER')
        add('terminal-before-actual-issue-history', 'offer-bound',
            lambda t, n: replace_expression(t, n, 'terminal', 'rising',
                                            expression(t, n, 'issue_seen'), "1'b1"),
            'RAM_PRESENTATION_SETTLEMENT_IDENTITY', profile='issue-history')
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--keep-going', action='store_true')
    parser.add_argument('--case', help='Restrict development replay by case-name regex; summary is partial')
    args = parser.parse_args()
    sources = json.loads(args.sources.read_text())
    _, closed_records, closed_cohort = source_oracles(sources)
    if set(sources) != {'bd', 'click'}:
        raise ValueError('RAM_RETURN_CONTROL_VARIANTS')
    out = args.out.resolve()
    originals = {}
    rtl_cohort = {}
    for variant, fixtures in sources.items():
        if set(fixtures) != fixture_inventory(variant):
            raise ValueError('RAM_RETURN_CONTROL_FIXTURE_INVENTORY:' + variant)
        for name, path in fixtures.items():
            source = Path(path).resolve()
            if out.is_relative_to(source) or source.is_relative_to(out):
                raise ValueError('RAM_RETURN_CONTROL_SOURCE_OVERLAP')
            results = list(source.glob('seed-*/result.json'))
            if {p.parent.name for p in results} != {'seed-' + str(i) for i in range(1, 25)}:
                raise ValueError('RAM_RETURN_CONTROL_SEED_INVENTORY:' + variant + ':' + name)
            if any(json.loads(p.read_text()).get('status') != 'PASS' or
                   str(json.loads(p.read_text()).get('seed')) != p.parent.name.removeprefix('seed-')
                   for p in results):
                raise ValueError('RAM_RETURN_CONTROL_FAILED_SOURCE:' + variant + ':' + name)
            module = 'ClickRamReturn' if variant == 'click' else 'FourPhaseRamReturn'
            rtl_sha = hashlib.sha256((source / 'export' / (module + '.sv')).read_bytes()).hexdigest()
            if variant in rtl_cohort and rtl_cohort[variant] != rtl_sha:
                raise ValueError('RAM_RETURN_CONTROL_MIXED_RTL_COHORT:' + variant)
            rtl_cohort[variant] = rtl_sha
            originals[str(source)] = hashes(source)
    out.mkdir(parents=True, exist_ok=False)
    results = {}
    commands = []
    failures = []

    def record():
        (out / 'results.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n', encoding='utf-8')

    def simulate(label, variant, fixture, mutation=None, expected=(), profile=None):
        source = Path(sources[variant][fixture]).resolve()
        case = out / label
        shutil.copytree(source / 'export', case)
        oracle = source / 'seed-1/testbench.sv'
        oracle_sha = hashlib.sha256(oracle.read_bytes()).hexdigest()
        shutil.copyfile(oracle, case / 'testbench.sv')
        node = json.loads((case / 'contract.json').read_text())['manifest']['design']
        if node['module'] != ('ClickRamReturn' if variant == 'click' else 'FourPhaseRamReturn') or node['children']:
            raise ValueError('RAM_RETURN_CONTROL_NATIVE_OWNER')
        paths = []
        if profile:
            test = (case / 'testbench.sv').read_text()
            if 'RAM_PRESENTATION_SETTLEMENT_IDENTITY' not in test:
                raise ValueError('RAM_RETURN_CONTROL_MISSING_PRESENTATION_ORACLE')
            test, paths = directed_skew(test, node, profile)
            (case / 'testbench.sv').write_text(test, encoding='utf-8')
        replay_sha = hashlib.sha256((case / 'testbench.sv').read_bytes()).hexdigest()
        rtl = case / (node['module'] + '.sv')
        if mutation:
            original = rtl.read_text()
            changed = mutation(original, node)
            if original == changed:
                raise ValueError('RAM_RETURN_CONTROL_UNCHANGED_MUTANT:' + label)
            rtl.write_text(changed, encoding='utf-8')
        files = [str((case / line.strip()).resolve())
                 for line in (case / 'filelist.f').read_text().splitlines() if line.strip()]
        compiled, log = run(['iverilog', '-g2012', '-s', 'Testbench', '-o', 'sim.vvp',
                             *files, 'testbench.sv'], case, 'compile.log', commands)
        results[label] = dict(source=str(source), oracle_sha256=oracle_sha,
                              replay_sha256=replay_sha, directed_skew=paths,
                              functional_oracles_preserved=True,
                              mutated=mutation is not None, expected=list(expected), compile=compiled,
                              rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest())
        record()
        if compiled['exit_code'] != 0:
            raise AssertionError('RAM_RETURN_CONTROL_COMPILE_FAILED:' + log[-4000:])
        simulated, log = run(['vvp', 'sim.vvp'], case, 'simulation.log', commands)
        results[label]['simulation'] = simulated
        record()
        if mutation:
            if not (simulated['exit_code'] != 0 and any(marker in log for marker in expected)
                    and 'DEADLINE' not in log and 'TIMEOUT' not in log):
                raise AssertionError('RAM_RETURN_CONTROL_NOT_DETECTED:' + log[-4000:])
        elif simulated['exit_code'] != 0 or 'CA_TEST_PASS' not in log:
            raise AssertionError('RAM_RETURN_CONTROL_BASELINE_FAILED:' + log[-4000:])
        if hashlib.sha256((case / 'testbench.sv').read_bytes()).hexdigest() != replay_sha:
            raise AssertionError('RAM_RETURN_CONTROL_ORACLE_CHANGED')
        results[label]['passed'] = True
        record()
        print(label, 'PASS', flush=True)

    # Baselines precede every mutation, so a broken source cohort cannot be
    # misrepresented as a useful negative control.
    fatal = None
    try:
        for variant, fixtures in sources.items():
            for fixture in fixtures:
                simulate(variant + '-' + fixture + '-baseline', variant, fixture)
        for variant in sources:
            for name, fixture, mutation, expected, profile in controls(variant):
                label = variant + '-' + name
                if args.case and not re.search(args.case, label):
                    continue
                try:
                    if profile:
                        simulate(label + '-skew-baseline', variant, fixture, profile=profile)
                    simulate(label, variant, fixture, mutation, expected, profile)
                except (ValueError, AssertionError) as error:
                    failures.append(label)
                    results.setdefault(label, {})['failure'] = str(error)
                    record()
                    print(label, 'FAILED', str(error)[-1000:], flush=True)
                    if not args.keep_going:
                        break
            if failures and not args.keep_going:
                break
    except Exception as error:
        fatal = error
    finally:
        preserved = all(hashes(Path(source)) == before for source, before in originals.items())
        results['summary'] = dict(closed_export_cohort=closed_cohort, source_manifest_sha256=hashlib.sha256(args.sources.read_bytes()).hexdigest(),

            positive_replays=sum(r.get('passed', False) and not r.get('mutated', False) for r in results.values()),
            functional_mutations=sum(r.get('passed', False) and r.get('mutated', False) for r in results.values()),
            failed_controls=failures, originals_preserved=preserved, source_cohort_sha256=originals,
            rtl_cohort_sha256=rtl_cohort, partial=args.case is not None,
            fatal=None if fatal is None else str(fatal))
        record()
    if not preserved:
        raise AssertionError('RAM_RETURN_CONTROL_SOURCE_CHANGED')
    if fatal is not None:
        raise fatal
    if failures:
        raise AssertionError('RAM_RETURN_CONTROLS_FAILED:' + ','.join(failures))
    print('PARTIAL_RAM_RETURN_CONTROLS_PASS' if args.case else 'ALL_RAM_RETURN_CONTROLS_PASS', flush=True)


if __name__ == '__main__':
    main()

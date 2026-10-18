# SPDX-License-Identifier: Apache-2.0
"""Seal complete local guard evidence; does not change or approve the policy."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path

from control_relative_timing import CORNERS
from gf180_physical import ROOT, sha, write_json
from repair_gf180_control import require


def validate_cases(records, cases, residual):
    """Require each actual owner/corner/slew and every changed guard metric."""
    owners = {r['owner'] for r in records}
    expected = {(owner, f'{corner}-s{slew}') for owner in owners
                for corner in CORNERS for slew in (.02, 2.)}
    counts = Counter((c['instance'], c['key']) for c in cases)
    require(set(counts) == expected and all(n == 1 for n in counts.values()),
            'GUARD_SEAL_CASE_COVERAGE')
    requirements = {}
    for record in records:
        kind = record['primitive_id']
        metrics = {'output_delay': ('publication-rise', 'publication-fall'),
                   'request_delay': ('setup',),
                   'acknowledge_guard': ('hold', 'pulse-high', 'ack-after-rearm')}[kind]
        requirements.setdefault(record['owner'], set()).update(metrics)
    minima = {}
    by_owner = {}
    for case in cases:
        required = requirements[case['instance']]
        require(required <= case['minima'].keys(), 'GUARD_SEAL_METRIC_MISSING')
        require(all(isinstance(v, (int, float)) and math.isfinite(v)
                    for v in case['minima'].values()), 'GUARD_SEAL_NONFINITE')
        require(all(case['minima'][m] >= residual for m in required),
                'GUARD_SEAL_NEGATIVE_MARGIN')
        # Full elapsed cases also retain their existing local hold measurement.
        # It is reported separately: the 2 ns adoption floor applies to the
        # changed request/publication guards, not invented source-release credit.
        if 'setup' in required:
            require(case['minima'].get('hold', -1) >= 0, 'GUARD_SEAL_ELAPSED_HOLD')
        target = by_owner.setdefault(case['instance'], {})
        for metric, value in case['minima'].items():
            minima[metric] = min(minima.get(metric, math.inf), value)
            target[metric] = min(target.get(metric, math.inf), value)
    return dict(case_count=len(cases), owner_count=len(owners), minima_ns=minima,
                owner_minima_ns=by_owner)


def validate_inputs(frozen, campaign, source_root=ROOT/'tools'):
    custody = {}
    for filename, digest in frozen.items():
        path = Path(filename)
        if path.is_file() and sha(path) == digest:
            custody[filename] = str(path)
            continue
        snapshot = campaign/'source-snapshot'/path.name
        require(path.parent.resolve() == source_root.resolve() and snapshot.is_file()
                and sha(snapshot) == digest, 'GUARD_SEAL_INPUT_CHANGED')
        custody[filename] = str(snapshot)
    return custody


def load_campaign(policy, mapping, campaign):
    report_path = campaign/'results.json'
    report = json.loads(report_path.read_text())
    require(report['engineering_derate'] == policy['engineering_derate'] == .2
            and report['residual_ns'] == policy['residual_ns'] == 2,
            'GUARD_SEAL_POLICY_CHANGED')
    require(report['focused'] and not report['candidate'], 'GUARD_SEAL_GRAPH_MODE')
    for relative, digest in report['files_sha256'].items():
        path = (campaign/relative).resolve()
        require(path.is_relative_to(campaign.resolve()) and path.is_file()
                and sha(path) == digest, 'GUARD_SEAL_ARTIFACT_CHANGED')
    custody = validate_inputs(report['input_sha256'], campaign)
    repair = json.loads((mapping/'electrical-repair/receipt.json').read_text())
    saved_repair = dict(report['post_run_receipt'])
    saved_repair.pop('historical_helpers', None)
    require(saved_repair == repair, 'GUARD_SEAL_REPAIR_RECEIPT_CHANGED')
    for relative, digest in repair['evidence_sha256'].items():
        directory = (mapping/'electrical-repair').resolve()
        path = (directory/relative).resolve()
        require(path.is_relative_to(directory) and path.is_file() and sha(path) == digest,
                'GUARD_SEAL_REPAIR_EVIDENCE_CHANGED')
    for name in ('mapping.json', 'netlist.v', 'netlist.json'):
        require(report['input_sha256'][str((mapping/name).resolve())] == sha(mapping/name),
                'GUARD_SEAL_MAPPING_CHANGED')
    return report, custody


CRPR_PREFIX = 'sta::set_crpr_enabled false\n'
SCRIPT_LINE = '        text = leaf.script(netlist, corner, slew, context_plan, context, sta=sta)\n'
CRPR_LINE = '        text = "sta::set_crpr_enabled false\\n" + text\n'


def validate_retry_source(original, retry):
    require(original.count(SCRIPT_LINE) == 1 and
            retry == original.replace(SCRIPT_LINE, SCRIPT_LINE+CRPR_LINE),
            'GUARD_SEAL_RETRY_SOURCE_SCOPE')


def replace_retry(policy, variant, original_dir, original, retry_dir, retry):
    """Replace complete affected-owner cohorts, retaining every failed attempt."""
    require(retry['status'] == 'COMPLETE_MEASURED' and not retry['failures'],
            'GUARD_SEAL_RETRY_INCOMPLETE')
    old_inputs = dict(original['input_sha256']); new_inputs = dict(retry['input_sha256'])
    old_helpers = [p for p in old_inputs if Path(p).name == 'size_ordering_guards.py']
    new_helpers = [p for p in new_inputs if Path(p).name == 'size_ordering_guards.py']
    require(len(old_helpers) == len(new_helpers) == 1, 'GUARD_SEAL_RETRY_HELPER')
    old_helper = Path(validate_inputs(old_inputs, original_dir)[old_helpers[0]])
    new_helper = Path(validate_inputs(new_inputs, retry_dir)[new_helpers[0]])
    del old_inputs[old_helpers[0]]; del new_inputs[new_helpers[0]]
    require(old_inputs == new_inputs, 'GUARD_SEAL_RETRY_INPUTS_CHANGED')
    validate_retry_source(old_helper.read_text(), new_helper.read_text())
    owners = {c['instance'] for c in retry['cases']}
    records = [r for r in policy['variants'][variant] if r['owner'] in owners]
    validate_cases(records, retry['cases'], policy['residual_ns'])
    def directories(folder):
        found = {}
        for path in folder.glob('*/plan.json'):
            plan = json.loads(path.read_text()); owner = plan['descriptor']['instance']
            require(owner not in found, 'GUARD_SEAL_DUPLICATE_PLAN')
            found[owner] = path.parent
        return found
    old_dirs, new_dirs = directories(original_dir), directories(retry_dir)
    overlap = 0; tcl_checks = 0
    for owner in owners:
        require(owner in old_dirs and owner in new_dirs, 'GUARD_SEAL_RETRY_OWNER')
        left, right = old_dirs[owner], new_dirs[owner]
        require(json.loads((left/'plan.json').read_text()) == json.loads((right/'plan.json').read_text()),
                'GUARD_SEAL_RETRY_PLAN_CHANGED')
        for case in (c for c in retry['cases'] if c['instance'] == owner):
            old_case, new_case = left/(case['key']+'.json'), right/(case['key']+'.json')
            if old_case.exists():
                require(json.loads(old_case.read_text()) == json.loads(new_case.read_text()),
                        'GUARD_SEAL_RETRY_RAW_ROWS_CHANGED')
                overlap += 1
            for script in right.glob(case['key']+'-*.tcl'):
                text = script.read_text()
                require(text.startswith(CRPR_PREFIX), 'GUARD_SEAL_RETRY_CRPR_REQUIRED')
                prior = left/script.name
                if prior.exists():
                    require(text == CRPR_PREFIX+prior.read_text(), 'GUARD_SEAL_RETRY_TCL_CHANGED')
                    tcl_checks += 1
    require(overlap and tcl_checks, 'GUARD_SEAL_RETRY_NO_OVERLAP')
    cases = [c for c in original['cases'] if c['instance'] not in owners]+retry['cases']
    evidence = dict(report_sha256=sha(retry_dir/'results.json'), original_failures=original['failures'],
                    owners=sorted(owners), case_count=len(retry['cases']), raw_overlap_count=overlap,
                    exact_tcl_delta_checks=tcl_checks, setting='sta::set_crpr_enabled false',
                    retry_source_sha256=sha(new_helper))
    return cases, evidence


def seal_variant(policy, variant, mapping, campaign, retry_dirs=()):
    report, custody = load_campaign(policy, mapping, campaign)
    require(report['status'] in ('COMPLETE_MEASURED', 'INCOMPLETE_FAILURES'), 'GUARD_SEAL_INCOMPLETE')
    if report['failures']:
        require(retry_dirs and all(f['type'] == 'CalledProcessError' and
                any('exit status '+str(code) in f['message'] for code in (11, 124)) for f in report['failures']),
                'GUARD_SEAL_UNRESOLVED_FAILURE')
    cases = report['cases']; retries = []; replaced = set()
    for retry_dir in retry_dirs:
        retry_dir = retry_dir.resolve()
        retry, retry_custody = load_campaign(policy, mapping, retry_dir)
        owners = {c['instance'] for c in retry['cases']}
        require(not owners & replaced, 'GUARD_SEAL_DUPLICATE_RETRY_OWNER')
        replaced |= owners
        merged, evidence = replace_retry(policy, variant, campaign, report, retry_dir, retry)
        cases = [c for c in cases if c['instance'] not in owners]+[c for c in merged if c['instance'] in owners]
        evidence['input_sha256'] = retry['input_sha256']; evidence['input_custody'] = retry_custody
        retries.append(evidence)
    data = json.loads((mapping/'mapping.json').read_text())
    applied = {}
    for binding in data['bindings']:
        for instance, selection in binding.get('guard_policy', {}).items():
            require(instance not in applied, 'GUARD_SEAL_DUPLICATE_BINDING')
            applied[instance] = selection
    records = policy['variants'][variant]
    require(set(applied) == {r['instance'] for r in records}, 'GUARD_SEAL_BINDING_COVERAGE')
    for record in records:
        selected = applied[record['instance']]
        require(selected['requested'] == record and selected['stages'] == record['stages'],
                'GUARD_SEAL_BINDING_CHANGED')
    mapping_files = {name: sha(mapping/name) for name in
                     ('mapping.json', 'netlist.v', 'netlist.json', 'electrical-repair/receipt.json')}
    summary = validate_cases(records, cases, policy['residual_ns'])
    summary.update(report_sha256=sha(campaign/'results.json'), mapping_sha256=mapping_files,
                   input_sha256=report['input_sha256'], input_custody=custody,
                   retries=retries,
                   source_launch_composition='UNMEASURED_BY_GUARD_RECEIPT',
                   data_setup='ELAPSED_ONLY; OTHER_UNCHANGED_CONES_UNMEASURED')
    return summary


def run(policy_path, bd_mapping, bd_campaign, click_mapping, click_campaign, output, bd_retries=(), click_retries=()):
    require(not output.exists(), 'GUARD_SEAL_OUTPUT_EXISTS')
    policy = json.loads(policy_path.read_text())
    result = {variant: seal_variant(policy, variant, mapping.resolve(), campaign.resolve(), retries)
              for variant, mapping, campaign, retries in [('bd', bd_mapping, bd_campaign, bd_retries),
                                                          ('click', click_mapping, click_campaign, click_retries)]}
    write_json(output, dict(status='LOCAL_GUARD_CHECKS_PASS', policy_sha256=sha(policy_path),
                           statistical_qualification=False, routed_qualification=False,
                           independent_review_required=True, variants=result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('policy', 'bd_mapping', 'bd_campaign', 'click_mapping', 'click_campaign', 'output'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--bd-retry', type=Path, action='append', default=[])
    parser.add_argument('--click-retry', type=Path, action='append', default=[])
    args = parser.parse_args()
    run(args.policy, args.bd_mapping, args.bd_campaign, args.click_mapping, args.click_campaign,
        args.output, args.bd_retry, args.click_retry)

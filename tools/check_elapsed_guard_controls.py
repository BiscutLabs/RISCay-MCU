# SPDX-License-Identifier: Apache-2.0
"""A7b exact-arc fault controls on the isolated shortened elapsed guard."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import control_relative_timing as relative
import native_leaf_timing as leaf
import native_stage_timing as stage
from check_control_relative_controls import fault_sdf, verify_runtime
from check_native_stage_controls import capture_fault_pin, verdict
from experiment_elapsed_guard import verify_files
from gf180_physical import sha, write_json
from physical_tools import tool
from repair_gf180_control import require
from repair_gf180_design import validate_receipt


def run(mapping, candidate, output):
    require(not output.exists(), 'A7_CONTROL_OUTPUT_EXISTS')
    receipt = json.loads((candidate / 'results.json').read_text())
    require(receipt['status'] == 'EXPERIMENTAL_LOCAL_ONLY' and receipt['production_enabled'] is False and
            receipt['all_local_sizing_checks_nonnegative'], 'A7_CONTROL_BASE_STATUS')
    verify_files(receipt, candidate)
    repair = validate_receipt(mapping); proof = stage.receipt_proof(mapping, repair)
    index = leaf.LeafIndex(stage.receipt_original(mapping, repair),
                           json.loads((candidate / 'netlist.json').read_text()),
                           proof['added_buffers'], proof['added_ties'])
    sta = tool('sta'); runtime = verify_runtime(sta, receipt['inputs_sha256'])
    paths = [Path(__file__), Path(__file__).with_name('check_native_stage_controls.py'),
             Path(__file__).with_name('check_control_relative_controls.py')]
    frozen = {str(p.resolve()): sha(p) for p in paths}
    plan = json.loads((candidate / 'plan.json').read_text())
    key = 'tt_025C_3v30-s0.02'; saved = json.loads((candidate / (key + '.json')).read_text())
    output.mkdir(parents=True); verdicts = []
    for fault in ('period', 'short_request', 'early_ack', 'late_capture'):
        results = deepcopy(saved['results']); arcs = []
        if fault != 'period':
            sdf, arcs = fault_sdf(plan, fault, capture_fault_pin(plan) if fault == 'late_capture' else None)
            (output / (fault + '.sdf')).write_text(sdf, newline='\n')
        for context in plan['contexts']:
            relevant = (True if fault == 'period' else context['kind'] == 'request' if fault == 'short_request'
                        else context['kind'] == 'common')
            if not relevant:
                continue
            ctx = deepcopy(context)
            if ctx['kind'] == 'common':
                bounds = results['request-0']['event_slew_ns']
                ctx['root_slew_ns'] = dict(min=bounds[0], max=bounds[1])
            tcl = output / (fault + '-' + ctx['id'] + '.tcl'); log = tcl.with_suffix('.log')
            text = leaf.script(candidate / 'netlist.v', relative.CORNERS[0], .02, plan, ctx,
                               sta=sta, period=2000 if fault == 'period' else 1000)
            if fault != 'period':
                text = text.replace('row RELATIVE_BEGIN',
                    'read_sdf ' + relative.brace(sta.path(output / (fault + '.sdf'))) + '\nrow RELATIVE_BEGIN')
            tcl.write_text(text, newline='\n')
            with log.open('w') as stream:
                subprocess.run(sta.command(['-no_init', '-exit', sta.path(tcl)], timeout=55),
                               stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=65)
            results[ctx['id']] = leaf.parse(log.read_text(), plan, ctx, .02, index)
        summary = relative.margins(results, plan, saved['aperture'])
        if fault == 'period':
            require(results == saved['results'] and summary == saved['summary'], 'A7_PERIOD_DEPENDENCE')
            checked = dict(fault=fault, status='IDENTICAL')
        else:
            checked = verdict(saved['summary'], summary, plan, fault, arcs)
        write_json(output / (fault + '.json'), dict(verdict=checked, summary=summary, results=results, arcs=arcs))
        verdicts.append(checked)
        print(json.dumps({k: len(v) if isinstance(v, list) else v for k, v in checked.items()}), flush=True)
    verify_files(receipt, candidate)
    require(all(sha(Path(p)) == h for p, h in frozen.items()), 'A7_CONTROL_SOURCE_CHANGED')
    write_json(output / 'results.json', dict(status='PASS_EXACT_FAULT_CONTROLS', physical_qualification=False,
        candidate_sha256=sha(candidate / 'results.json'), runtime_sha256=runtime, inputs_sha256=frozen,
        verdicts=verdicts, files_sha256={p.name: sha(p) for p in output.iterdir() if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mapping', 'candidate', 'output'):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    run(args.mapping, args.candidate, args.output)

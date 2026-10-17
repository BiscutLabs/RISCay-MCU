# SPDX-License-Identifier: Apache-2.0
"""A7b: one isolated BD elapsed request-chain candidate, never a production map.

Reuse the contract/leaf stage queries on the complete repaired chip. The only
graph edit removes interior DLYD cells from the elapsed request chain. Reset
masking, endpoint driver, capture trees, feedback, ACK and output guards stay.
Local sizing does not qualify FIFO launch, pending/return, reset or routed RC.
"""
import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import subprocess

import control_relative_timing as relative
import native_leaf_timing as leaf
import native_stage_timing as stage
from gf180_implement import instances, leaves
from gf180_physical import ROOT, SC, sha, write_json
from physical_tools import tool
from repair_gf180_control import require, connectivity
from repair_gf180_design import read_verilog_json, validate_receipt

OWNER = 'FourPhaseSoc.ca_child_elapsed_scaler.ca_child_native.ca_child_step'
GUARD = OWNER + '.ca_primitive_request_delay'


def narrow_chain(body, count):
    """Keep the reset gate and terminal DLYD; reject branches or other logic."""
    result = deepcopy(body)
    cells = result['cells']
    delays = {n: c for n, c in cells.items() if c['type'] == SC + 'dlyd_1'}
    other = {n: c for n, c in cells.items() if n not in delays}
    require(type(count) is int and 1 <= count <= len(delays), 'A7_CHAIN_COUNT')
    require(len(other) == 2 and sorted(c['type'] for c in other.values()) ==
            sorted(SC + c for c in ('inv_1', 'and2_1')), 'A7_CHAIN_RECIPE')
    inv = next(c for c in other.values() if c['type'] == SC + 'inv_1')
    gate = next(c for c in other.values() if c['type'] == SC + 'and2_1')
    require(inv['connections']['I'] == body['ports']['reset']['bits'] and
            gate['connections']['A1'] == body['ports']['a']['bits'] and
            gate['connections']['A2'] == inv['connections']['ZN'], 'A7_RESET_AND_ENDPOINT')
    node = gate['connections']['Z']; ordered = []
    while len(ordered) < len(delays):
        found = [n for n, c in delays.items() if c['connections']['I'] == node]
        require(len(found) == 1 and found[0] not in ordered, 'A7_CHAIN_BRANCH_OR_CYCLE')
        ordered.append(found[0]); node = delays[found[0]]['connections']['Z']
    terminal = cells[ordered[-1]]
    require(terminal['connections']['Z'] == body['ports']['q']['bits'], 'A7_CHAIN_TERMINUS')
    removed = ordered[count - 1:-1]
    for name in removed:
        del cells[name]
    terminal['connections']['I'] = (gate if count == 1 else cells[ordered[count - 2]])['connections']['Z'][:]
    # Every retained cell except this one terminal input must be byte-identical.
    for name, cell in cells.items():
        old = deepcopy(body['cells'][name])
        if cell is terminal:
            old['connections']['I'] = cell['connections']['I']
        require(old == cell, 'A7_UNEXPECTED_CELL_CHANGE')
    return result, ordered, removed


def module_verilog(name, body):
    """Emit this scalar standard-cell module, not a replacement whole-chip flow."""
    require(re.fullmatch(r'\w+', name) is not None and
            all(len(p['bits']) == 1 for p in body['ports'].values()), 'A7_SCALAR_MODULE')
    names = {p['bits'][0]: n for n, p in body['ports'].items()}
    used = {b for c in body['cells'].values() for bits in c['connections'].values() for b in bits}
    require(all(type(b) is int for b in used), 'A7_NONSCALAR_NET')
    names.update({b: 'a7_n' + str(b) for b in used - set(names)})
    lines = ['module ' + name + '(' + ', '.join(body['ports']) + ');']
    lines += [p['direction'] + ' ' + n + ';' for n, p in body['ports'].items()]
    lines += ['wire ' + names[b] + ';' for b in sorted(used - {p['bits'][0] for p in body['ports'].values()})]
    for n, c in body['cells'].items():
        require(re.fullmatch(r'\w+', n) is not None and c['type'].startswith(SC), 'A7_CELL_NAME')
        lines.append(c['type'] + ' ' + n + '(' + ', '.join('.' + p + '(' + names[bits[0]] + ')'
                     for p, bits in c['connections'].items()) + ');')
    return '\n'.join(lines) + '\nendmodule'


def sensitivity(saved, derate):
    require(math.isfinite(derate) and 0 <= derate < 1, 'A7_DERATE')
    data = saved['results']['data']['rows']; request = saved['results']['request-0']['rows']
    values = []
    for row in saved['summary']['lanes']:
        if row['maximum_input_data_lag_ns'] is None:
            continue
        lane = row['lane']
        dmax = max(data[f'data:{lane}:max:{edge}']['delay_ns'] for edge in ('rise', 'fall'))
        capture = request[f'capture:{lane}:min:rise']['delay_ns']
        setup = saved['aperture']['setup_ns']
        values.append(dict(lane=lane, capture_min_ns=capture, data_max_ns=dmax, setup_ns=setup,
                           slack_ns=(1 - derate) * capture - (1 + derate) * dmax - setup))
    require(values, 'A7_NO_DYNAMIC_LANES')
    return min(values, key=lambda x: x['slack_ns'])


def propose_count(cases, original, derate):
    """Same-corner proposal only; actual shortened-netlist measurement must pass.

    Scale the entire measured request path for the initial count estimate. It
    includes non-chain delay, so this is not a calibrated chain model. Loaded
    candidate measurements, not this estimate, decide the local result.
    """
    rows = []
    for key, saved in cases.items():
        for row in saved['summary']['lanes']:
            if row['maximum_input_data_lag_ns'] is None:
                continue
            lane = row['lane']; data = saved['results']['data']['rows']
            dmax = max(data[f'data:{lane}:max:{e}']['delay_ns'] for e in ('rise', 'fall'))
            request = saved['results']['request-0']['rows'][f'capture:{lane}:min:rise']['delay_ns']
            count = math.ceil(original * ((1 + derate) * dmax + saved['aperture']['setup_ns']) /
                              ((1 - derate) * request))
            rows.append(dict(key=key, lane=lane, count=count))
    require(rows and 0 <= derate < 1, 'A7_COUNT_INPUT')
    return min(original, max(r['count'] for r in rows)), rows


def verify_files(receipt, directory):
    for path, digest in receipt['inputs_sha256'].items():
        require(sha(Path(path)) == digest, 'A7_BASE_INPUT_CHANGED')
    for path, digest in receipt['files_sha256'].items():
        require(sha(directory / path) == digest, 'A7_BASE_EVIDENCE_CHANGED')


def run(mapping, baseline, output, count=None, derate=.15):
    require(not output.exists(), 'A7_OUTPUT_EXISTS')
    baseline_receipt = json.loads((baseline / 'results.json').read_text())
    verify_files(baseline_receipt, baseline)
    require(len(baseline_receipt['cases']) == 10 and all(c['instance'] == OWNER and c['failure'] is None
            for c in baseline_receipt['cases']), 'A7_BASE_COHORT')
    repair = validate_receipt(mapping)
    sta, yosys = tool('sta'), tool('yosys')
    require(all(baseline_receipt['inputs_sha256'].get(str(p.resolve())) == sha(p)
                for p in sta.input_files() + yosys.input_files()), 'A7_RUNTIME_CHANGED')
    live = json.loads((mapping / 'netlist.json').read_text())
    original = stage.receipt_original(mapping, repair); proof = stage.receipt_proof(mapping, repair)
    record = json.loads((mapping / 'mapping.json').read_text())
    binding, = [b for b in record['bindings'] if GUARD in b['instances']]
    require(binding['instances'] == [GUARD] and binding['requirements']['role'] == 'matched-control-delay',
            'A7_SINGLE_GUARD')
    audit = json.loads((mapping / 'netlist-audit.json').read_text())
    path = audit['adapter_instances'][GUARD]
    physical_module = dict(instances(live['modules'], 'RiscayMcuDigital'))[path]
    require(physical_module == binding['module'], 'A7_GUARD_MODULE')
    count_live = sum(k == physical_module for _, k in instances(live['modules'], 'RiscayMcuDigital'))
    require(count_live == 1, 'A7_SHARED_GUARD')
    body = live['modules'][physical_module]
    chain_count = sum(c['type'] == SC + 'dlyd_1' for c in body['cells'].values())
    cases = {c['key']: json.loads((baseline / '0' / (c['key'] + '.json')).read_text())
             for c in baseline_receipt['cases']}
    proposed, proposal = propose_count(cases, chain_count, derate)
    count = proposed if count is None else count
    candidate_body, ordered, removed = narrow_chain(body, count)
    require(removed, 'A7_NOT_SHORTER')
    candidate = deepcopy(live); candidate['modules'][physical_module] = candidate_body
    old_text = (mapping / 'netlist.v').read_text()
    pattern = r'(?m)^module ' + re.escape(physical_module) + r'\s*\(.*?^endmodule'
    candidate_text, replacements = re.subn(pattern, lambda _: module_verilog(physical_module, candidate_body),
                                           old_text, flags=re.S | re.M)
    require(replacements == 1, 'A7_MODULE_TEXT')
    output.mkdir(parents=True); (output / 'netlist.v').write_text(candidate_text, newline='\n')
    readback = read_verilog_json(output / 'netlist.v', output / 'netlist.json', 'RiscayMcuDigital',
                                yosys, ROOT / '.tools/physical/pdk', candidate)
    # Fresh parser must recover exactly the intended graph, including every
    # unchanged parent load. Do not forge a normal mapper/repair receipt.
    require(connectivity(candidate) == connectivity(readback), 'A7_CANDIDATE_READBACK')
    flat_old = dict(leaves(live['modules'], 'RiscayMcuDigital'))
    flat_new = dict(leaves(readback['modules'], 'RiscayMcuDigital'))
    removed_paths = {path + '/' + n for n in removed}
    require(set(flat_old) - set(flat_new) == removed_paths and not set(flat_new) - set(flat_old), 'A7_LEAF_DELTA')
    require(all(flat_old[p]['type'] == flat_new[p]['type'] for p in flat_new), 'A7_LEAF_MASTER_CHANGE')
    index = leaf.LeafIndex(original, readback, proof['added_buffers'], proof['added_ties'])
    plan = json.loads((baseline / '0/plan.json').read_text())
    plan['native']['cells'] = [c for c in plan['native']['cells'] if c['path'] not in removed_paths]
    write_json(output / 'plan.json', plan)
    files = [Path(__file__), baseline / 'results.json', output / 'netlist.v', output / 'netlist.json',
             output / 'plan.json', ROOT / '.tools/physical/pdk/gf180mcu_fd_sc_mcu7t5v0.lef']
    frozen = {str(p.resolve()): sha(p) for p in files}
    summaries = []
    for key, old in cases.items():
        corner, slew_text = key.rsplit('-s', 1); slew = float(slew_text)
        results = {}
        for context in plan['contexts']:
            ctx = deepcopy(context)
            if ctx['kind'] == 'common':
                bounds = results['request-0']['event_slew_ns']
                ctx['root_slew_ns'] = dict(min=bounds[0], max=bounds[1])
            tcl = output / (key + '-' + ctx['id'] + '.tcl'); log = tcl.with_suffix('.log')
            tcl.write_text(leaf.script(output / 'netlist.v', corner, slew, plan, ctx, sta=sta), newline='\n')
            with log.open('w') as stream:
                subprocess.run(sta.command(['-no_init', '-exit', sta.path(tcl)], timeout=55),
                               stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=65)
            results[ctx['id']] = leaf.parse(log.read_text(), plan, ctx, slew, index)
        saved = dict(results=results, aperture=old['aperture'],
                     summary=relative.margins(results, plan, old['aperture']))
        # Only the request-chain cone changed. No data, source-release or
        # capture-versus-ACK improvement may be credited to another edit.
        require(results['data'] == old['results']['data'], 'A7_DATA_CONE_CHANGED')
        for metric in ('minimum_zero_reuse_hold_ns', 'minimum_ack_after_capture_ns'):
            require(abs(saved['summary'][metric] - old['summary'][metric]) < 1e-6, 'A7_HOLD_OR_ACK_CHANGED')
        saved['sensitivity'] = {str(d): sensitivity(saved, d) for d in (0., .05, .10, .15, .20)}
        write_json(output / (key + '.json'), saved)
        row = dict(key=key, **{k: v for k, v in saved['summary'].items() if k != 'lanes'},
                   sensitivity=saved['sensitivity'], electrical_violation_rows={k: len(v['electrical_violations'])
                                                                               for k, v in results.items()})
        summaries.append(row); print(json.dumps(row), flush=True)
    lef = (ROOT / '.tools/physical/pdk/gf180mcu_fd_sc_mcu7t5v0.lef').read_text()
    area_match, = re.findall(r'MACRO\s+' + re.escape(SC + 'dlyd_1') + r'\s.*?SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)', lef, re.S)
    area_delta = len(removed) * float(area_match[0]) * float(area_match[1]) / 1e6
    verify_files(baseline_receipt, baseline); validate_receipt(mapping)
    require(all(sha(Path(p)) == h for p, h in frozen.items()), 'A7_INPUT_CHANGED')
    result = dict(status='EXPERIMENTAL_LOCAL_ONLY', physical_qualification=False, production_enabled=False,
                  owner=OWNER, adapter=GUARD, chain_before=chain_count, chain_after=count,
                  removed_dlyd=len(removed), leaf_area_reduction_mm2=area_delta,
                  sizing_derate_sensitivity=derate, proposed_count=proposed, proposal=proposal,
                  all_local_sizing_checks_nonnegative=all(s['sensitivity'][str(derate)]['slack_ns'] >= 0 for s in summaries),
                  baseline_sha256=sha(baseline / 'results.json'), cases=summaries,
                  inputs_sha256={**baseline_receipt['inputs_sha256'], **frozen},
                  files_sha256={str(p.relative_to(output)).replace('\\', '/'): sha(p) for p in output.rglob('*') if p.is_file()})
    write_json(output / 'results.json', result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('mapping', 'baseline', 'output'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--count', type=int)
    args = parser.parse_args()
    run(args.mapping, args.baseline, args.output, args.count)

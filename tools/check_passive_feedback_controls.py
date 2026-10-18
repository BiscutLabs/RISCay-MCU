# SPDX-License-Identifier: Apache-2.0
"""Real Liberty hold fault controls for the same-event passive FrameStore cone.

This deliberately bounds a small D-pin subset while retaining the complete
eligible source-Q set. It supplements, and never replaces, the full cohort.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import passive_feedback_hold as f


def paths(text):
    pins = {}; result = {}
    for line in text.splitlines():
        parts = line.split('\t')
        if parts[0] == 'PIN':
            f.require(parts[1] not in pins, 'FEEDBACK_CONTROL_DUPLICATE_PIN')
            pins[parts[1]] = parts[2]
        elif parts[0] in ('PATH', 'CLOCK'):
            key = parts[0], parts[1], pins[parts[2]], parts[3]
            f.require(key not in result, 'FEEDBACK_CONTROL_DUPLICATE_PATH')
            result[key] = [pins[p] for p in parts[4:]]
    return result


def run(mapping, export, output):
    f.require(not output.exists(), 'FEEDBACK_CONTROL_OUTPUT_EXISTS')
    receipt = f.validate_receipt(mapping)
    record = json.loads((mapping/'mapping.json').read_text())
    audit = json.loads((mapping/'netlist-audit.json').read_text())
    f.require(audit['status'] == 'pass' and audit['netlist_sha256'] == f.sha(mapping/'netlist.v'),
              'FEEDBACK_CONTROL_STALE_AUDIT')
    f.require(f.sha(export/'contract.json') == f.sha(mapping/'timing-intent.json'),
              'FEEDBACK_CONTROL_EXPORT_IDENTITY')
    manifest = json.loads((export/'contract.json').read_text())['manifest']
    f.require(manifest['top'] == 'ClickSoc', 'FEEDBACK_CONTROL_VARIANT')
    inventory = f.sources.inventory(export, manifest['top'])
    original = f.stages.receipt_original(mapping, receipt)
    proof = f.stages.receipt_proof(mapping, receipt)
    index = f.leaf.LeafIndex(original, json.loads((mapping/'netlist.json').read_text()),
                           proof['added_buffers'], proof['added_ties'])
    groups = f.bind(inventory, record, audit, index)
    prefix = 'ClickSoc.ca_child_i2c.ca_child_frame_store.'
    selected = [p for p in groups if prefix+'ca_primitive_route' in p['banks']]
    f.require(len(selected) == 1, 'FEEDBACK_CONTROL_FRAMESTORE_GROUP')
    full = selected[0]
    # Payload lane 0 is the capture-skew victim. Route lane 0 is independently
    # clocked by another leaf and gives an off-path control in the same group.
    targets = {}
    for bank in ('ca_primitive_payload0', 'ca_primitive_route'):
        matches = [(d, v) for d, v in full['targets'].items()
                   if v['bank'] == prefix+bank and v['lane'] == 0]
        f.require(len(matches) == 1, 'FEEDBACK_CONTROL_EXACT_TARGET')
        targets.update(matches)
    plan = deepcopy(full); plan['targets'] = targets
    corner = 'tt_025C_3v30'
    libpath = f.ROOT/'.tools/physical/pdk'/(f.SC+corner+'.lib')
    lib = f.library(libpath)
    f.bind_cone(plan, record, audit, index, lib)
    f.require(set(plan['targets']) == set(targets) and plan['sources'] == full['sources'],
              'FEEDBACK_CONTROL_COMPLETE_SOURCE_SET')
    victim = next(d for d, v in targets.items() if v['bank'].endswith('ca_primitive_payload0'))
    unaffected = next(d for d in targets if d != victim)
    clock = targets[victim]['CLK']
    net = index.live_net('pin', clock)
    drivers = [(path, c, pin) for path, c in index.after['cells'].items()
               for pin, bits in c['connections'].items()
               if c['directions'][pin] == 'output' and len(bits) == 1 and bits[0] == net]
    f.require(len(drivers) == 1, 'FEEDBACK_CONTROL_CAPTURE_DRIVER')
    driver, cell, pin = drivers[0]
    f.require(cell['type'].startswith(f.SC+'buf_') and pin == 'Z' and
              index.live_net('pin', targets[unaffected]['CLK']) != net,
              'FEEDBACK_CONTROL_CAPTURE_BRANCH')
    arc = dict(cell=driver, master=cell['type'], source='I', sink='Z', delay_ns=1000)
    cuts = f.leaf.keeper_cuts(index, audit)
    envelope = f.slew_envelope(index, lib, plan['root'])
    aperture = f.hold_aperture(lib)
    sta = f.tool('sta')
    files = [mapping/name for name in ('mapping.json', 'netlist.json', 'netlist.v',
        'netlist-audit.json', 'timing-intent.json', 'electrical-repair/receipt.json',
        'electrical-repair/proof.json', 'electrical-repair/reference/netlist.json')]
    files += [f.ROOT/'tools'/name for name in ('check_passive_feedback_controls.py',
        'passive_feedback_hold.py', 'passive_source_inventory.py', 'passive_constant_proof.py',
        'native_allowance_audit.py', 'check_reset_crossings.py', 'gf180_physical.py',
        'gf180_estimate.py', 'native_stage_timing.py', 'native_leaf_timing.py',
        'physical_tools.py', 'repair_gf180_design.py', 'control_relative_timing.py',
        'screen_gf180_control_repair.py', 'repair_gf180_control.py')]
    files += [libpath, f.ROOT/'.tools/gf180-sram'/(f.SRAM+'__tt_025C_3v30.lib')]+sta.input_files()
    frozen = {str(p.resolve()): f.sha(p) for p in files}
    frozen.update(inventory['inputs_sha256'])
    output.mkdir(parents=True)
    f.write_json(output/'plan.json', plan)
    f.write_json(output/'binding.json', dict(full_group_source_count=len(full['sources']),
        full_group_target_count=len(full['targets']), victim=victim, unaffected=unaffected,
        envelope=envelope, arc=arc, input_files_sha256=frozen))
    baseline = None; verdicts = []
    for case in ('baseline', 'period', 'late_capture'):
        text, samples = f.script(mapping, corner, plan, envelope, cuts, sta,
                                 period=5000 if case == 'period' else 1000)
        if case == 'late_capture':
            instance = driver.replace('.', r'\.')
            sdf = output/'late_capture.sdf'
            sdf.write_text('(DELAYFILE (SDFVERSION "3.0") (DESIGN "RiscayMcuDigital") '
                '(DIVIDER /) (TIMESCALE 1ns)\n'
                f'(CELL (CELLTYPE "{cell["type"]}") (INSTANCE {instance}) '
                '(DELAY (ABSOLUTE (IOPATH I Z (1000:1000:1000) (1000:1000:1000)))))\n)\n',
                newline='\n')
            anchor = 'link_design RiscayMcuDigital\n'
            f.require(text.count(anchor) == 1, 'FEEDBACK_CONTROL_SCRIPT_SHAPE')
            text = text.replace(anchor, anchor+'read_sdf '+f.brace(sta.path(sdf))+'\n')
        tcl = output/(case+'.tcl'); log = tcl.with_suffix('.log')
        tcl.write_text(text, newline='\n')
        with log.open('w') as stream:
            subprocess.run(sta.command(['-no_init', '-exit', sta.path(tcl)], timeout=300),
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=310)
        evidence = log.read_text()
        rows, slews = f.parse(evidence, plan, samples, aperture)
        traces = paths(evidence)
        ranges = f.table_ranges(rows, slews, index, lib, plan)
        f.require(not ranges['range_errors'], 'FEEDBACK_CONTROL_EXTRAPOLATED')
        rowmap = {(r['sample'], r['target'], r['edge']): r for r in rows}
        if case == 'baseline':
            f.require(all(r['slack_ns'] >= 0 for r in rows), 'FEEDBACK_CONTROL_BASELINE_HOLD')
            baseline = dict(rows=rowmap, paths=traces, slews=slews)
        elif case == 'period':
            f.require(rowmap == baseline['rows'] and traces == baseline['paths'] and
                      slews == baseline['slews'], 'FEEDBACK_CONTROL_PERIOD_DEPENDENCE')
        else:
            changed = 0
            for key, row in rowmap.items():
                if row['target'] == victim:
                    clkpath = traces[('CLOCK', *key)]
                    datapath = traces[('PATH', *key)]
                    f.require(driver+'/I' in clkpath and driver+'/Z' in clkpath and
                              driver+'/Z' not in datapath, 'FEEDBACK_CONTROL_FAULT_PATH')
                    f.require(row['slack_ns'] < 0 and
                              baseline['rows'][key]['slack_ns']-row['slack_ns'] > 900,
                              'FEEDBACK_CONTROL_LATE_CAPTURE_ACCEPTED')
                    changed += 1
                else:
                    f.require(row == baseline['rows'][key] and all(
                        traces[(kind, *key)] == baseline['paths'][(kind, *key)]
                        for kind in ('PATH', 'CLOCK')), 'FEEDBACK_CONTROL_OFF_PATH_CHANGE')
            f.require(changed == 2*len(samples), 'FEEDBACK_CONTROL_CHANGED_COVERAGE')
        result = dict(case=case, status='PASS', period_ns=5000 if case == 'period' else 1000,
                      minimum_hold_ns=min(r['slack_ns'] for r in rows), rows=rows,
                      table_ranges=ranges, samples=samples)
        f.write_json(output/(case+'.json'), result)
        verdicts.append({k: result[k] for k in ('case', 'status', 'minimum_hold_ns')})
        print(json.dumps(verdicts[-1]), flush=True)
    f.require(all(f.sha(Path(p)) == h for p, h in frozen.items()), 'FEEDBACK_CONTROL_INPUT_CHANGED')
    f.validate_receipt(mapping)
    f.write_json(output/'controls.json', dict(status='PASS', physical_qualification=False,
        scope=__doc__, complete_source_count=len(plan['sources']), selected_target_count=len(targets),
        measured_rows_per_case=len(baseline['rows']), verdicts=verdicts, inputs_sha256=frozen,
        files_sha256={p.name: f.sha(p) for p in output.iterdir() if p.is_file()}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('mapping', 'export', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    run(a.mapping.resolve(), a.export.resolve(), a.output.resolve())

# SPDX-License-Identifier: Apache-2.0
"""Small transistor Monte Carlo screen; not a routed OCV/yield qualification."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from run_receipt import RunReceipt

PREFIX = 'gf180mcu_fd_sc_mcu7t5v0__'
CONTEXTS = [('tt', 'typical', 25, 3.3), ('ff_cold', 'ff', -40, 3.6),
            ('ff_hot', 'ff', 125, 3.6), ('ss_cold', 'ss', -40, 3.0),
            ('ss_hot', 'ss', 125, 3.0), ('global_tt', 'statistical', 25, 3.3)]


def deck(pdk, context, seed, variation, step_ps):
    name, model, temperature, voltage = context
    lines = [f'GF180 guard/logic variation {name} seed {seed}',
             f'.include "{pdk.as_posix()}/design.ngspice"',
             f'.lib "{pdk.as_posix()}/sm141064.ngspice" {model}',
             f'.param sw_stat_global={int(variation and model == "statistical")} sw_stat_mismatch={int(variation)}',
             f'.include "{pdk.as_posix()}/gf180mcu_fd_sc_mcu7t5v0.spice"',
             f'.temp {temperature}', f'Vdd vdd 0 {voltage}',
             f'Vin in 0 PULSE(0 {voltage} 10n 1n 1n 80n 180n)']
    # Both paths see the same source edge, supply and process draw. Each transistor
    # retains its own PDK local mismatch sample. No user-invented sigma is added.
    previous = 'in'
    for i in range(4):
        node = f'd{i}'
        lines.append(f'Xd{i} {previous} {node} vdd vdd 0 0 {PREFIX}dlyd_1')
        previous = node
    previous = 'in'
    for i in range(12):
        node = f'l{i}'
        cell, pins = [('nand2_1', f'{previous} vdd'), ('nor2_1', f'{previous} 0'),
                      ('aoi21_1', f'{previous} vdd 0'), ('inv_1', previous)][i % 4]
        lines.append(f'Xl{i} {pins} {node} vdd vdd 0 0 {PREFIX}{cell}')
        # A small, explicit local wire/side-load on every logic stage.
        lines.append(f'Cl{i} {node} 0 5f')
        previous = node
    lines += ['Cdout d3 0 20f', 'Clout l11 0 20f', '.control',
              f'setseed {seed}', 'reset', f'tran {step_ps}p 180n 0 {step_ps}p']
    for path, node in [('delay', 'd3'), ('logic', 'l11')]:
        for edge in ('rise', 'fall'):
            lines.append(f'meas tran {path}_{edge} TRIG v(in) VAL={voltage/2} {edge}=1 '
                         f'TARG v({node}) VAL={voltage/2} {edge}=1')
    return '\n'.join([*lines, 'quit', '.endc', '.end', ''])


def measurements(log):
    result = {}
    for name in ('delay_rise', 'delay_fall', 'logic_rise', 'logic_fall'):
        values = re.findall(r'^' + name + r'\s*=\s*([^\s]+)', log, re.M)
        if len(values) != 1:
            raise ValueError('MISSING_MEASUREMENT:' + name)
        value = float(values[0])
        if not math.isfinite(value) or value <= 0:
            raise ValueError('INVALID_MEASUREMENT:' + name)
        result[name] = value
    return result


def envelope(ratios):
    if not ratios or any(not math.isfinite(r) or r <= 0 for r in ratios):
        raise ValueError('INVALID_RATIO')
    low, high = min(ratios), max(ratios)
    worst = max(high, 1/low)
    return dict(minimum_ratio=low, maximum_ratio=high, worst_ratio=worst,
                required_symmetric_derate=max(0, (worst-1)/(worst+1)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdk', type=Path, default=ROOT/'.tools/physical/pdk')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ngspice', default='ngspice')
    parser.add_argument('--samples', type=int, default=32)
    args = parser.parse_args()
    if args.samples < 2: parser.error('At least two independent seeds are required')
    simulator = Path(shutil.which(args.ngspice) or args.ngspice).resolve()
    if not simulator.is_file(): parser.error('ngspice is required')
    pdk = args.pdk.resolve(); out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    lockfile = ROOT/'physical/gf180/pdk-lock.json'
    lock = json.loads(lockfile.read_text())
    models = [pdk/name for name in ('design.ngspice', 'sm141064.ngspice', PREFIX[:-2]+'.spice')]
    for path in models:
        if hashlib.sha256(path.read_bytes()).hexdigest() != lock['files'][path.name]:
            raise ValueError('PDK_HASH:' + path.name)
    run = RunReceipt(out/'receipt.json', inputs=[lockfile, *models], tools=[Path(__file__), simulator])

    def simulate(context, seed, variation, step=20, suffix=''):
        name = f'{context[0]}-{seed}-{int(variation)}-{step}{suffix}'
        source = out/(name+'.spice'); log = out/(name+'.log')
        source.write_text(deck(pdk, context, seed, variation, step), encoding='utf-8')
        with log.open('w') as stream:
            subprocess.run([str(simulator), '-b', str(source)], cwd=pdk, stdout=stream,
                           stderr=subprocess.STDOUT, timeout=60, check=True)
        return dict(context=context[0], seed=seed, variation=variation, step_ps=step,
                    **measurements(log.read_text(errors='replace')))

    try:
        nominal = {c[0]: simulate(c, 1, False) for c in CONTEXTS}
        jobs = [(c, seed) for c in CONTEXTS for seed in range(1, args.samples+1)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            samples = list(pool.map(lambda pair: simulate(*pair, True), jobs))
        # Disabled variation must ignore seed; enabled variation must actually vary.
        control = simulate(CONTEXTS[0], 2, False)
        repeat = simulate(CONTEXTS[0], 1, True, suffix='-repeat')
        fine = [simulate(c, 1, True, step=10) for c in CONTEXTS]
        summary = {}
        for c in CONTEXTS:
            rows = [s for s in samples if s['context'] == c[0]]
            if len({r['delay_rise'] for r in rows}) < 2 or len({r['logic_rise'] for r in rows}) < 2:
                raise ValueError('VARIATION_INACTIVE:' + c[0])
            ratios = [r['logic_'+e]/r['delay_'+e] /
                      (nominal[c[0]]['logic_'+e]/nominal[c[0]]['delay_'+e])
                      for r in rows for e in ('rise', 'fall')]
            summary[c[0]] = dict(samples=len(rows), **envelope(ratios))
        for name in ('delay_rise', 'delay_fall', 'logic_rise', 'logic_fall'):
            if control[name] != nominal['tt'][name] or repeat[name] != samples[0][name]:
                raise ValueError('SEED_CONTROL:' + name)
            for row in fine:
                original = next(r for r in samples if r['context'] == row['context'] and r['seed'] == 1)
                if abs(row[name]/original[name]-1) > 0.01:
                    raise ValueError('TIMESTEP_NOT_CONVERGED:' + row['context'] + ':' + name)
        report = dict(scope='schematic screening; no layout gradients, wire RC or yield claim',
                      two_sided_derate=0.20, ratio_limit=1.2/0.8, contexts=summary,
                      nominal=list(nominal.values()), samples=samples, controls=[control, repeat, *fine])
        report['within_screened_envelope'] = all(s['worst_ratio'] <= report['ratio_limit'] for s in summary.values())
        (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        run.finish(outputs=sorted(out.glob('*')), status='pass' if report['within_screened_envelope'] else 'fail', coverage=summary)
        print(json.dumps(summary, indent=2))
        return 0 if report['within_screened_envelope'] else 1
    except Exception:
        if not run.finished: run.finish(outputs=sorted(out.glob('*')), status='fail')
        raise


if __name__ == '__main__': sys.exit(main())

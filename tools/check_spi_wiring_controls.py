# SPDX-License-Identifier: Apache-2.0
"""Bind isolated SPI player/native faults to fresh RTL and unchanged oracles.

The wire fixture is SpiAdcSpec's original half-period-two waveform test. Strict
exports retain every mandatory generic campaign and native recipe check. Shape
drift is an error: a new emitted binding needs review, not a broader mutation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from check_spi_replay_controls import (bind_sites, execute, require, sha,
                                      tree_hashes, validate_coverage)


NATIVE_FIELDS = (('initialCsN', 1, 0, 'recipe-initial-cs'),
                 ('initialSclk', 1, 0, 'recipe-initial-sclk'),
                 ('occupied', 32, 0xffffffff, 'recipe-occupied'),
                 ('csN', 32, 0x80000000, 'recipe-cs'),
                 ('sclk', 32, 0x55555555, 'recipe-sclk'))


def exact(source, pattern, label):
    matches = list(re.finditer(pattern, source))
    require(len(matches) == 1, 'EMITTED_BINDING:' + label)
    return matches[0].group()


def case(root, label, family, file, old, new, message, scope='Testbench'):
    require(old != new and (root / file).read_text().count(old) == 1,
            'EMITTED_BINDING:' + label)
    return dict(label=label, family=family, file=file, source_sha256=sha(root / file),
                old=old, new=new, fatal_sites=[dict(format=message, scope=scope)])


def wire_cases(root):
    file = 'SpiAdc.sv'
    source = (root / file).read_text()
    # Require the actual immutable-program bindings and slot-dependent pin
    # selects. Mutations below break these uses, not a disconnected test copy.
    for field, _, _, _ in NATIVE_FIELDS:
        exact(source, rf'\.program_{field}\s*\(recipe_{field}\)', field)
    exact(source, r'wire\s+\[31:0\]\s+_GEN = \{27\x27h0, slot\};', 'slot-extend')
    exact(source, r'playing <= ~_GEN_3 & \(_GEN_0 \? \(\|recipe_occupied\) : playing\);', 'play-load')
    exact(source, r'cs <= _cs_T\[0\];', 'pin-cs')
    exact(source, r'clockLevel <= _clockLevel_T\[0\];', 'pin-sclk')
    slot_load = exact(source, r'if \(_GEN_0\)[^\n]*\n\s+slot <= 5\x27h0;', 'slot-load')
    terminal = "recipe_occupied >> _GEN == 32'h1;"
    cases = []
    def add(label, family, old, new, message, scope='Testbench'):
        cases.append(case(root, label, family, file, old, new, message, scope))
    # The former 96-bit player registers no longer exist. Retain each original
    # recipe/load fault at the actual indexed use; strict cases independently
    # corrupt each immutable native constant at its producer output.
    add('occupied-truncated', 'recipe-occupied', terminal,
        "32'h7fffffff >> _GEN == 32'h1;", 'SPI_FRAME_TOO_LONG')
    add('cs-sequence', 'recipe-cs', 'recipe_csN >> _GEN;',
        "32'h20000000 >> _GEN;", 'SPI_FRAME_LENGTH edges=%d duration=%f')
    add('sclk-sequence', 'recipe-sclk', 'recipe_sclk >> _GEN;',
        "32'h55555554 >> _GEN;", 'SPI_HALF_PHASE edges=%d elapsed=%f')
    add('initial-cs-load', 'recipe-initial-cs', 'cs <= recipe_initialCsN;',
        "cs <= 1'h1;", 'SPI_FRAME_START')
    add('initial-sclk-load', 'recipe-initial-sclk', 'clockLevel <= recipe_initialSclk;',
        "clockLevel <= 1'h1;", 'SPI_FRAME_START')
    add('slot-load', 'slot-load', slot_load,
        slot_load.replace("slot <= 5'h0;", "slot <= 5'h1;"),
        'SPI_HALF_PHASE edges=%d elapsed=%f')
    add('slot-advance', 'slot-advance', "slot <= slot + 5'h1;",
        "slot <= slot + 5'h2;", 'SPI_FRAME_TOO_LONG')
    add('occupancy-terminal', 'occupancy-terminal', terminal,
        "recipe_occupied >> _GEN == 32'h3;", 'SPI_FRAME_TOO_LONG')
    add('divider-enable', 'divider-enable', 'wire        _GEN_1 = playing & divider;',
        'wire        _GEN_1 = playing & ~divider;', 'SPI_HALF_PHASE edges=%d elapsed=%f')
    add('miso-capture', 'miso-capture', 'samples <= {miso, samples[31:1]};',
        'samples <= {~miso, samples[31:1]};',
        'SPI_WIRE_RESULT word=%h value=%h valid=%b', 'Testbench.retire')
    return cases


def strict_cases(root, variant):
    file = ('FourPhaseSpiAdc' if variant == 'bd' else 'ClickSpiAdc') + '.sv'
    source = (root / file).read_text()
    cases = []
    for field, width, value, family in NATIVE_FIELDS:
        old = exact(source, rf'assign\s+program_{field}\s*=\s*{width}\x27h{value:X}\s*;', field)
        new = re.sub(rf'{width}\x27h{value:X}', f"{width}'h{value ^ 1:X}", old)
        cases.append(case(root, 'native-' + field, family, file, old, new,
                          'MCU_SPI_PROGRAM_VALUE:' + field, 'ContractProbe.check'))
    return cases


def group(root, variant, mode):
    root = root.resolve()
    require(root.is_dir(), 'EXPORT_MISSING')
    cases = wire_cases(root) if mode == 'wire' else strict_cases(root, variant)
    oracle = root / ('testbench.sv' if mode == 'wire' else 'contract_probe.sv')
    for fault in cases:
        bind_sites(oracle.read_text(), fault['fatal_sites'])
    hashes = tree_hashes(root)
    return dict(name=variant + '-' + mode, variant=variant, mode=mode, export=str(root),
                # Host execution allowance only: no testbench time/deadline changes.
                timeout_seconds=3600 if mode == 'strict' else 900,
                export_tree_sha256=hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(),
                source_hashes={f: sha(root / f) for f in sorted({c['file'] for c in cases})},
                oracle_sha256=sha(oracle), cases=cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bd', 'click', 'bd-strict', 'click-strict', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    runner = Path(__file__).with_name('check_spi_replay_controls.py')
    runner_sha, binder_sha = sha(runner), sha(Path(__file__))
    roots = [getattr(args, key).resolve() for key in ('bd', 'click', 'bd_strict', 'click_strict')]
    require(all(not out.is_relative_to(r) and not r.is_relative_to(out) for r in roots), 'OVERLAP')
    plan = dict(status='BOUND_TO_FRESH_EMITTED_RTL', binder_sha256=binder_sha, runner_sha256=runner_sha,
                groups=[group(getattr(args, variant + ('_strict' if mode == 'strict' else '')),
                              variant, mode)
                        for variant in ('bd', 'click') for mode in ('wire', 'strict')])
    validate_coverage(plan)
    out.mkdir(parents=True, exist_ok=False)
    plan_file = out / 'bound-plan.json'
    plan_file.write_text(json.dumps(plan, indent=2) + '\n')
    plan_sha = sha(plan_file)
    results = []
    for entry in plan['groups']:
        target = out / entry['name']
        target.mkdir()
        results.append(execute(entry, target))
        (out / 'results.json').write_text(json.dumps(dict(status='PARTIAL', groups=results), indent=2) + '\n')
    require(sha(runner) == runner_sha and sha(Path(__file__)) == binder_sha
            and sha(plan_file) == plan_sha, 'RUNNER_OR_PLAN_CHANGED')
    receipt = dict(status='PASS', scope='actual emitted isolated faults; physical timing remains open',
                   plan_sha256=plan_sha, binder_sha256=binder_sha,
                   runner_sha256=runner_sha, groups=results)
    (out / 'results.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('ALL_ACTUAL_SPI_WIRING_CONTROLS_PASS', flush=True)


if __name__ == '__main__':
    main()

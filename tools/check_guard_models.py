# SPDX-License-Identifier: Apache-2.0
"""Exercise exported native controllers with deliberately fast ordering guards.

The 8 ns model setting is a stress value, not eight physical cells or a timing
qualification. Physical per-corner bounds are measured separately. The source
reuses its data immediately after acknowledgement; the independent payload
oracle, stalls, phase/RTZ history and reset checks are unchanged.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from experiment_passive_stage import digital_bench, bind_export, classify_digital
from gf180_physical import ROOT, nodes, sha, write_json
from repair_gf180_control import require


def bench_source(module, variant, setting):
    text = digital_bench(module, variant, False, 'none')
    # The existing fixture waits for output offer before observing source ACK.
    # Watch ACK concurrently, so the shortened Click ACK really releases the
    # source before its unchanged output publication guard completes.
    begin = text.index(';\n wait(', text.index('#1000000; in_req=')) + 2
    end = text.index('\nend endtask', begin)
    offer = 'out_req != out_ack' if variant == 'click' else 'out_req'
    release = ('capture_expected=0; address=~a; data=~d; mask=~m;' if variant == 'click' else
               'in_req=0; wait(!in_ack); capture_expected=0; address=~a; data=~d; mask=~m;')
    complete = ('#100000000;' if variant == 'click' else
                'wait(!out_req); #1000000; out_ack=0; #100000000;')
    text = text[:begin] + f''' fork
 begin
  wait(in_ack == in_req); {release}
 end
 begin
  wait({offer}); #1000;
  if (output_word !== expected) $fatal(1,"PASSIVE_STAGE_OUTPUT_IDENTITY");
  offers=offers+1;
  repeat(stall) begin #1000000; if (output_word !== expected) $fatal(1,"PASSIVE_STAGE_STALLED_OUTPUT"); end
  out_ack={'out_req' if variant == 'click' else '1'};
  {complete}
 end
 join''' + text[end:]
    if variant == 'bd':
        guard = 'output_delay'
        monitor = '''always @(posedge out_req) if (!reset && !dut.ca_primitive_payload.closed)
  $fatal(1,"GUARD_OFFER_BEFORE_CAPTURE");'''
        diagnostic = 'GUARD_OFFER_BEFORE_CAPTURE'
    else:
        guard = 'acknowledge_guard'
        monitor = '''always @(in_ack) if (!reset && dut.ca_primitive_fire.q)
  $fatal(1,"GUARD_ACK_BEFORE_REARM");'''
        diagnostic = 'GUARD_ACK_BEFORE_REARM'
    assert text.count('endmodule') == 1
    delay = {'fast': 8_000_000, 'too-short': 1_000}.get(setting)
    override = '' if delay is None else f'defparam dut.ca_primitive_{guard}.DELAY_FS={delay};'
    text = text.replace('endmodule', monitor + '\n' + override + '\nendmodule')
    return text, diagnostic if setting == 'too-short' else None


def run(mapping, export, output, variant):
    require(not output.exists(), 'GUARD_MODEL_OUTPUT_EXISTS')
    record = json.loads((mapping/'mapping.json').read_text())
    manifest = json.loads((mapping/'timing-intent.json').read_text())['manifest']
    path = manifest['top'] + '.ca_child_ram_access.ca_child_native.ca_child_prepare'
    owner, = [n for n in nodes(manifest['design']) if n['rtl_path'] == path]
    # Metadata preserves logical owner identity; firtool may deduplicate the
    # emitted module into another instance's definition.
    module = manifest['top']
    for local in path.split('.')[1:]:
        module, = re.findall(r'\b(\w+)\s+' + re.escape(local) + r'\s*\(',
                             (export/(module+'.sv')).read_text())
    source = export/(module+'.sv')
    original = source.read_text()
    cells = [export/(name+'.sv') for name in sorted(set(re.findall(r'\b(ChiselAsync\w+_v1)\s*#\s*\(', original)))]
    bind_export(record, [source, *cells])
    compiler = Path(shutil.which('iverilog') or ROOT/'.tools/iverilog/bin/iverilog.exe')
    runtime = Path(shutil.which('vvp') or compiler.with_name('vvp.exe'))
    require(compiler.is_file() and runtime.is_file(), 'GUARD_MODEL_ICARUS_MISSING')
    backend = compiler.parent.parent/'lib/ivl'
    files = [Path(__file__), ROOT/'tools/experiment_passive_stage.py', source, *cells, compiler, runtime,
             *(p for p in backend.iterdir() if p.is_file())]
    frozen = {str(p.resolve()): sha(p) for p in files}
    results = []
    for setting in ('nominal', 'fast', 'too-short'):
        case = output/setting
        case.mkdir(parents=True)
        bench, expected = bench_source(module, variant, setting)
        (case/'testbench.sv').write_text(bench, newline='\n')
        command = [str(compiler), '-g2012', '-s', 'Testbench', '-o', 'test.vvp', str(source),
                   *map(str, cells), str(case/'testbench.sv')]
        result = subprocess.run(command, cwd=case, capture_output=True, text=True, timeout=30)
        (case/'compile.log').write_text(result.stdout+result.stderr)
        require(result.returncode == 0, 'GUARD_MODEL_COMPILE_FAILED')
        result = subprocess.run([str(runtime), 'test.vvp'], cwd=case, capture_output=True, text=True, timeout=30)
        log = result.stdout+result.stderr
        (case/'simulation.log').write_text(log)
        classify_digital(log, result.returncode, bench, case/'testbench.sv', expected)
        results.append(dict(setting=setting, status='PASS', expected_diagnostic=expected,
                            command=command, log_sha256=sha(case/'simulation.log'),
                            testbench_sha256=sha(case/'testbench.sv'), binary_sha256=sha(case/'test.vvp'),
                            compile_log_sha256=sha(case/'compile.log')))
    require(all(sha(Path(p)) == h for p, h in frozen.items()), 'GUARD_MODEL_INPUT_CHANGED')
    write_json(output/'results.json', dict(status='PASS', variant=variant, instance=path,
        scope='Actual exported standard-stage controller; deliberately accelerated digital guard models',
        physical_qualification=False, model_guard_fs=8_000_000, cases=results, inputs_sha256=frozen))
    print(json.dumps(dict(status='PASS', variant=variant, cases=len(results))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mapping', type=Path)
    parser.add_argument('export', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--variant', choices=('bd','click'), required=True)
    args = parser.parse_args()
    run(args.mapping.resolve(), args.export.resolve(), args.output.resolve(), args.variant)

# SPDX-License-Identifier: Apache-2.0
"""Portable fast gate used locally and on every main push. One sbt process."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
import xml.etree.ElementTree as ET
from run_receipt import RunReceipt
from ordering_guard_mapping import validate_dependencies
from area_ratio import check_budget_history

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAST_SUITES = (
    'DesyncClockSpec', 'DesyncChipSpec', 'DesyncCoreSpec', 'DesyncSocSpec', 'DesyncFabricSpec', 'DesyncSleepSpec', 'DesyncDeepSleepSpec', 'DesyncBoundarySpec',
    'ClockedCoreSpec', 'ClockedSocSpec', 'ClockedFabricSpec', 'ClockedSleepSpec', 'ClockedBoundarySpec',
    'TimestampMathSpec', 'AppRegistersSpec', 'AppSnapshotRecoverySpec', 'EventReferenceSpec', 'ClockedEventsSpec', 'CoreSpec', 'SocSpec', 'HostSchemaSpec', 'AsyncFabricSpec', 'AsyncControlSpec',
    'AsyncCrcSpec', 'AsyncHousekeepingSpec', 'AsyncFrameStoreSpec',
    'BootIngressSpec', 'I2cSpec', 'SramSpec', 'QuiescingReceiptSpec', 'QuiescingBridgeSpec', 'SleepSpec',
)


def reports(directory, required, started, *, contains=None):
    """A successful testOnly selector is insufficient: require fresh execution."""
    executed = {}
    for name in required:
        path = directory / ('TEST-' + name + '.xml')
        if not path.is_file() or path.stat().st_mtime < started:
            raise ValueError('CI_MISSING_FRESH_SUITE:' + name)
        suite = ET.parse(path).getroot()
        cases = suite.findall('testcase')
        if (suite.get('name') != name or not cases or
                any(int(suite.get(k, '0')) for k in ('errors', 'failures', 'skipped')) or
                any(c.find(k) is not None for c in cases for k in ('failure', 'error', 'skipped'))):
            raise ValueError('CI_SUITE_NOT_PASSED:' + name)
        if contains and any(contains not in c.get('name', '') for c in cases):
            raise ValueError('CI_FILTER_NOT_EXECUTED:' + name)
        executed[name] = [c.get('name') for c in cases]
    return executed


def accepted_skips(skipped):
    return all(os.name != 'nt' and test.id() ==
               'test_physical_tools.RuntimeTests.test_mounted_drive_hashes_original_windows_file' and
               reason == 'Windows mounted-drive host path' for test, reason in skipped)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--python-only', action='store_true')
    parser.add_argument('--area-mapping', type=Path, help='mapped candidate netlist JSON; paired with --area-reference')
    parser.add_argument('--area-reference', type=Path)
    parser.add_argument('--physical-mapping', type=Path, help='CTS candidate JSON; paired with --physical-reference')
    parser.add_argument('--physical-reference', type=Path)
    args = parser.parse_args()
    comparisons=[]
    for candidate,reference,physical in ((args.area_mapping,args.area_reference,False),
                                       (args.physical_mapping,args.physical_reference,True)):
        if bool(candidate)!=bool(reference):parser.error('Area comparisons require both candidate and reference')
        if candidate:comparisons.append((candidate.resolve(),reference.resolve(),physical))
    args.output.mkdir(parents=True, exist_ok=False)
    # Include firmware, fixed models, policies and resources as well as Scala.
    tracked = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
    inputs = [ROOT/p for p in tracked if p and (ROOT/p).is_file() and
              Path(p).suffix.lower() in {'.scala','.sbt','.json','.py','.tcl','.v','.sv','.hex','.c','.h','.s','.ld','.properties','.yml'}]
    inputs += [path for candidate,reference,_ in comparisons for path in (candidate,reference)]
    tools = [Path(sys.executable), *ROOT.glob('tools/*.py')]
    simulator_dirs = []
    for variable in ('CA_IVERILOG', 'CA_VVP'):
        value = os.environ.get(variable) or shutil.which(variable.removeprefix('CA_').lower())
        if value:
            executable = Path(value).resolve()
            tools.append(executable); simulator_dirs.append(str(executable.parent))
    # Python pin/model tests invoke the ordinary command names; Scala honors CA_*.
    # Both must use the same selected installation.
    os.environ['PATH'] = os.pathsep.join(dict.fromkeys([*simulator_dirs, os.environ.get('PATH','')]))
    if os.environ.get('JAVA_HOME'):
        tools.append(Path(os.environ['JAVA_HOME'])/'bin'/('java.exe' if os.name == 'nt' else 'java'))
    run = RunReceipt(args.output/'receipt.json', inputs=inputs, tools=tools)
    check_budget_history(ROOT/'physical/gf180/desync-budget.json')
    # Policy-only changes must not silently shorten a chain used by a different
    # controller. Full physical STA remains a separate, PDK-dependent campaign.
    dependency_log = args.output/'guard-dependencies.json'
    try:
        dependencies = validate_dependencies(json.loads(
            (ROOT/'physical/gf180/ordering-guards.json').read_text(encoding='utf-8')))
        dependency_log.write_text(json.dumps(dict(status='pass', dependencies=dependencies), indent=2)+'\n')
    except (ValueError, KeyError, TypeError) as error:
        dependency_log.write_text(json.dumps(dict(status='fail', diagnostic=str(error)), indent=2)+'\n')
        run.finish(outputs=[dependency_log], status='fail')
        return 1
    suite = unittest.defaultTestLoader.discover(str(ROOT/'tools'))
    if unittest.defaultTestLoader.errors or not suite.countTestCases():
        log=args.output/'python.log'
        log.write_text('CI_TEST_DISCOVERY_FAILED\n'+'\n'.join(unittest.defaultTestLoader.errors))
        run.finish(outputs=[log],status='fail')
        return 1
    with (args.output/'python.log').open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    status = 'pass' if result.wasSuccessful() and accepted_skips(result.skipped) else 'fail'
    outputs = [dependency_log, args.output/'python.log']
    for candidate,reference,physical in comparisons:
        from gf180_physical import SC,SRAM
        label='physical-area' if physical else 'mapped-area'
        log=args.output/(label+'.jsonl')
        command=[sys.executable,str(ROOT/'tools/area_ratio.py'),str(candidate),str(reference),
            '--liberty',str(ROOT/'.tools/physical/pdk'/(SC+'tt_025C_3v30.lib')),
            '--liberty',str(ROOT/'.tools/gf180-sram'/(SRAM+'__tt_025C_3v30.lib'))]
        if physical:command.append('--physical')
        if run.command(command,cwd=ROOT,log=log):status='fail'
        outputs.append(log)
    fast_suites = ['riscay.'+s for s in FAST_SUITES]
    boot_suites = ['riscay.GenericBootSpec','riscay.ClockedGenericBootSpec','riscay.DesyncGenericBootSpec']
    physical_suites = ['riscay.physical.PhysicalExportSpec','riscay.physical.PhysicalTimingSpec']
    requested = [] if args.python_only else fast_suites + boot_suites + physical_suites
    executed = {}; diagnostic = None
    if status == 'pass' and not args.python_only:
        reference_export=args.output.resolve()/'clocked-export'
        candidate_export=args.output.resolve()/'desync-export'
        commands = ['libraryRuntime', 'verification/testOnly '+ ' '.join('riscay.'+s for s in FAST_SUITES),
                    'verification/testOnly '+ ' '.join(boot_suites)+' -- -z "generic SPI boot"', 'physical/test']
        commands.append('clocked/runMain riscay.clocked.EmitClockedSoc '+reference_export.as_posix())
        commands.append('desync/runMain riscay.desync.EmitDesyncSoc '+candidate_export.as_posix())
        started = time.time()
        code = run.command([sys.executable, str(ROOT/'tools/sbt.py'), '--bootstrap', *commands],
                           cwd=ROOT, log=args.output/'scala.log')
        outputs.append(args.output/'scala.log')
        if code:
            status = 'fail'
        if status=='pass':
            # The clock source is explicitly abstracted. This proves copied
            # region behavior, not analog mutex or matched-delay timing.
            formal_log=args.output/'equivalence.log'
            code=run.command([sys.executable,str(ROOT/'tools/equiv_desync.py'),
                str(reference_export),str(candidate_export),str(args.output.resolve()/'equivalence')],
                cwd=ROOT,log=formal_log)
            outputs += [formal_log,args.output/'equivalence/receipt.json']
            if code:status='fail'
        try:
            runtime = ROOT/'build/library-runtime.txt'
            if not runtime.is_file() or runtime.stat().st_mtime < started:
                raise ValueError('CI_MISSING_FRESH_LIBRARY_RUNTIME')
            # This tool is compiled during the run, so hash its resulting JAR
            # alongside the run's outputs rather than an unrelated Ivy cache.
            run.tools += run.capture([Path(runtime.read_text(encoding='utf-8').strip())])
            outputs.append(runtime)
            executed.update(reports(ROOT/'verification/target/test-reports', fast_suites, started))
            executed.update(reports(ROOT/'verification/target/test-reports', boot_suites,
                                    started, contains='generic SPI boot'))
            executed.update(reports(ROOT/'physical/target/test-reports', physical_suites, started))
            outputs += [ROOT/('physical' if '.physical.' in name else 'verification')/
                        'target/test-reports'/('TEST-'+name+'.xml') for name in executed]
        except (ValueError, ET.ParseError) as error:
            diagnostic = str(error); status = 'fail'
    coverage = dict(python_tests=result.testsRun, failures=len(result.failures),
                    errors=len(result.errors), skipped=[dict(test=t.id(), reason=r) for t,r in result.skipped],
                    requested_scala_suites=requested, executed_scala_tests=executed, diagnostic=diagnostic)
    run.finish(outputs=outputs, status=status, coverage=coverage)
    print(f'{status.upper()}: {result.testsRun} Python tests; receipt: {args.output / "receipt.json"}')
    return 0 if status == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())

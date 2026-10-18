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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FAST_SUITES = (
    'CoreSpec', 'HostSchemaSpec', 'AsyncFabricSpec', 'AsyncControlSpec',
    'AsyncCrcSpec', 'AsyncHousekeepingSpec', 'AsyncFrameStoreSpec',
    'BootIngressSpec', 'QuiescingReceiptSpec', 'QuiescingBridgeSpec', 'SleepSpec',
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
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    # Include firmware, fixed models, policies and resources as well as Scala.
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    inputs = [ROOT/p for p in tracked if p and (ROOT/p).is_file() and
              Path(p).suffix.lower() in {'.scala','.sbt','.json','.py','.v','.sv','.hex','.c','.h','.s','.ld','.properties','.yml'}]
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
    suite = unittest.defaultTestLoader.discover(str(ROOT/'tools'))
    if unittest.defaultTestLoader.errors or not suite.countTestCases():
        log=args.output/'python.log'
        log.write_text('CI_TEST_DISCOVERY_FAILED\n'+'\n'.join(unittest.defaultTestLoader.errors))
        run.finish(outputs=[log],status='fail')
        return 1
    with (args.output/'python.log').open('w', encoding='utf-8') as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    status = 'pass' if result.wasSuccessful() and accepted_skips(result.skipped) else 'fail'
    outputs = [args.output/'python.log']
    requested = [] if args.python_only else ['riscay.'+s for s in FAST_SUITES]+[
        'riscay.GenericBootSpec', 'riscay.physical.PhysicalExportSpec', 'riscay.physical.PhysicalTimingSpec']
    executed = {}; diagnostic = None
    if status == 'pass' and not args.python_only:
        commands = ['libraryRuntime', 'verification/testOnly '+ ' '.join('riscay.'+s for s in FAST_SUITES),
                    'verification/testOnly riscay.GenericBootSpec -- -z "generic SPI boot"', 'physical/test']
        started = time.time()
        code = run.command([sys.executable, str(ROOT/'tools/sbt.py'), '--bootstrap', *commands],
                           cwd=ROOT, log=args.output/'scala.log')
        outputs.append(args.output/'scala.log')
        if code:
            status = 'fail'
        try:
            runtime = ROOT/'build/library-runtime.txt'
            if not runtime.is_file() or runtime.stat().st_mtime < started:
                raise ValueError('CI_MISSING_FRESH_LIBRARY_RUNTIME')
            # This tool is compiled during the run, so hash its resulting JAR
            # alongside the run's outputs rather than an unrelated Ivy cache.
            run.tools += run.capture([Path(runtime.read_text(encoding='utf-8').strip())])
            outputs.append(runtime)
            executed.update(reports(ROOT/'verification/target/test-reports', requested[:-3], started))
            executed.update(reports(ROOT/'verification/target/test-reports', ['riscay.GenericBootSpec'],
                                    started, contains='generic SPI boot'))
            executed.update(reports(ROOT/'physical/target/test-reports', requested[-2:], started))
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

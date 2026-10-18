# SPDX-License-Identifier: Apache-2.0
"""One receipt per command run; explicit files, no successor/attestation chain."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


class RunReceipt:
    def __init__(self, destination, *, inputs=(), tools=()):
        self.destination = Path(destination)
        if self.destination.exists():
            raise ValueError('RUN_RECEIPT_EXISTS')
        self.started = time.time()
        self.files = {}
        self.before = {}
        self.commands = []
        self.inputs = self.capture(inputs, initial=True)
        self.tools = self.capture(tools, initial=True)
        self.finished = False

    def capture(self, paths, *, initial=False):
        result = []
        for raw in paths:
            path = Path(raw).resolve()
            key = str(path)
            if key not in self.files:
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                self.files[key] = digest.hexdigest()
            if initial:
                stat = path.stat()
                self.before[key] = (stat.st_size, stat.st_mtime_ns)
            result.append(key)
        return sorted(set(result))

    def command(self, argv, *, cwd, log):
        start = time.time()
        with Path(log).open('w', encoding='utf-8') as stream:
            try:
                code = subprocess.run(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT).returncode
            except OSError as error:
                stream.write(str(error)+'\n'); code = 127
        self.commands.append(dict(argv=list(argv), cwd=str(Path(cwd).resolve()),
                                  log=str(Path(log).resolve()), returncode=code,
                                  seconds=time.time()-start))
        return code

    def finish(self, *, outputs=(), status='pass', coverage=None):
        if self.finished:
            raise ValueError('RUN_RECEIPT_ALREADY_FINISHED')
        changed = []
        for name, before in self.before.items():
            path = Path(name)
            if not path.exists() or (path.stat().st_size, path.stat().st_mtime_ns) != before:
                changed.append(name)
        # Inputs/tools are immutable for a run. A changed stat rejects the run
        # without a second hash or a chain of successor approvals.
        outputs = list(map(Path, outputs))
        missing = [str(p.resolve()) for p in outputs if not p.is_file()]
        outputs = self.capture(p for p in outputs if p.is_file())
        failed = changed or missing or any(c['returncode'] for c in self.commands)
        report = dict(schema='riscay-run-v1', status='fail' if failed else status,
                      started=self.started, seconds=time.time()-self.started,
                      inputs=self.inputs, tools=self.tools, outputs=outputs,
                      sha256=self.files, commands=self.commands, changed_inputs=changed, missing_outputs=missing,
                      coverage=coverage or {})
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        with self.destination.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2); stream.write('\n')
        self.finished = True
        if failed:
            raise ValueError('RUN_FAILED')
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', type=Path, help='JSON: inputs, tools, outputs and commands {argv,cwd,log}')
    parser.add_argument('receipt', type=Path)
    args = parser.parse_args()
    recipe = json.loads(args.recipe.read_text(encoding='utf-8'))
    run = RunReceipt(args.receipt, inputs=[args.recipe, *recipe['inputs']], tools=recipe['tools'])
    for command in recipe['commands']:
        if run.command(**command):
            break
    run.finish(outputs=[*recipe['outputs'], *(c['log'] for c in run.commands)])


if __name__ == '__main__':
    main()

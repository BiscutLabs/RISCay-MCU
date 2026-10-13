# SPDX-License-Identifier: Apache-2.0
"""Reproducible harness-only preparation for the service-architecture comparison.

Historical RTL is deliberately not certified by the current reset policy.
No production Scala implementation is modified by this tool.
"""
import argparse
import json
from pathlib import Path
import subprocess
from gf180_physical import ROOT, prepare, sha, write_json

BASELINE = "8637099bb603543b4d8e1d76de2bf165bbaa171a"
CANDIDATE = "2e4169c2f1befd1e8c5dfc704d9e936fe70e1a90"
EMITTER = "physical/src/main/scala/riscay/physical/EmitPhysical.scala"
HARNESS = "verification/src/test/scala/riscay/ClockedSimulation.scala"


def original(revision, name):
    return subprocess.check_output(["git", "show", revision+":"+name], cwd=ROOT).decode()


def setup_baseline(worktree, evidence):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=worktree, text=True).strip()
    if head != BASELINE:
        raise ValueError("WRONG_COMPARISON_BASELINE")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=worktree, text=True).strip():
        raise ValueError("BASELINE_NOT_CLEAN")
    # Use the same supported defaults and inlined assertions as the current
    # emitter. Only the historical board class and honest policy receipt differ.
    source = original(CANDIDATE, EMITTER).replace("GroundlarkBoard", "GroundlarkSupervisor")
    source = source.replace('"riscay-physical-policy-v3"', '"riscay-comparison-baseline-v1"')
    source = source.replace('"service_max_hz" -> ApplicationResetContract.maximumServiceHz',
                            '"service_max_hz" -> 20000000')
    start = source.index('        "application_reset" -> ujson.Obj(')
    end = source.index(',indent=2)', start)
    source = source[:start] + ('        "source_commit" -> "'+BASELINE+'",\n'
        '        "application_reset" -> "historical-raw-reset-without-R1-R2")') + source[end:]
    (worktree/EMITTER).write_text(source)
    harness = original(BASELINE, HARNESS)
    before = 'ExportDesign.emit({ design=gen; design }, base)'
    if harness.count(before) != 1:
        raise ValueError("BASELINE_HARNESS_SHAPE_CHANGED")
    (worktree/HARNESS).write_text(harness.replace(before,
        'ExportDesign.emit(chisel3.layer.elideBlocks { design=gen; design }, base)'))
    evidence.mkdir(parents=True, exist_ok=False)
    diff = subprocess.check_output(["git", "diff", "--no-ext-diff"], cwd=worktree)
    (evidence/"baseline-harness.patch").write_bytes(diff)
    write_json(evidence/"setup.json", dict(baseline=BASELINE, candidate=CANDIDATE,
        changes={n:sha(worktree/n) for n in (EMITTER,HARNESS)},
        patch_sha256=sha(evidence/"baseline-harness.patch"),
        limitations=["Historical reset defects retained", "Native-model workload is not energy",
                     "Groundlark OFF/restart qualification workload, not RUN/SHUTDOWN"]))


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="command",required=True)
    setup=sub.add_parser("setup-baseline")
    setup.add_argument("worktree",type=Path); setup.add_argument("evidence",type=Path)
    mapping=sub.add_parser("map-inputs")
    mapping.add_argument("export",type=Path); mapping.add_argument("output",type=Path)
    mapping.add_argument("--baseline",action="store_true")
    a=p.parse_args()
    if a.command=="setup-baseline": setup_baseline(a.worktree,a.evidence)
    else: print(prepare(a.export,a.output,ROOT/".tools/physical/pdk",comparison_baseline=a.baseline))

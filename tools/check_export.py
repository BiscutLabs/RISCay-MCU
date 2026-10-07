# SPDX-License-Identifier: Apache-2.0
"""Run the unchanged chisel-async export checks with a larger MCU probe timeout.

The library defaults to 60 seconds, which its small component probes fit. This
adapter changes only the contract_probe.vvp wall-clock limit; checks and coverage
are unmodified. The library checkout is an explicit development dependency.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--probe-timeout", type=int, default=600)
    args = parser.parse_args()
    if args.probe_timeout <= 0:
        parser.error("--probe-timeout must be positive")
    source = args.library.resolve() / "tools" / "check_export.py"
    sys.path.insert(0, str(source.parent))
    spec = importlib.util.spec_from_file_location("riscay_library_export_checker", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_run = subprocess.run

    def run(command, *pargs, **kwargs):
        if isinstance(command, (list, tuple)) and len(command) > 1 and command[1] == "contract_probe.vvp":
            kwargs["timeout"] = args.probe_timeout
        return original_run(command, *pargs, **kwargs)

    subprocess.run = run
    try:
        result = module.validate_export(args.directory.resolve())
    finally:
        subprocess.run = original_run
    import json
    print(json.dumps({"status": result["status"], "semantic_sha256": result["semantic_sha256"],
                      "endpoints": len(result["endpoints"]), "mapping_checks": result["mapping_checks"],
                      "probe_timeout_seconds": args.probe_timeout}, indent=2))


if __name__ == "__main__":
    main()

# SPDX-License-Identifier: Apache-2.0
"""Fetch and verify the exact GF180 SRAM physical views selected by the RTL."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def verify(data, expected):
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("SRAM_ASSET_HASH_MISMATCH")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".tools/gf180-sram")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    lock = json.loads((ROOT / "soc/sram-lock.json").read_text())
    args.output.mkdir(parents=True, exist_ok=True)
    base = lock["repository"].replace("https://github.com/", "https://raw.githubusercontent.com/")
    for name, asset in lock["assets"].items():
        path = args.output / name
        if not path.exists() and not args.verify_only:
            with urllib.request.urlopen(f'{base}/{lock["revision"]}/{asset["path"]}', timeout=60) as reply:
                data = reply.read()
            verify(data, asset["sha256"])
            path.write_bytes(data)
        verify(path.read_bytes(), asset["sha256"])
        vendored = ROOT / "soc/src/main/resources/riscay/sram" / name
        if vendored.exists():
            verify(vendored.read_bytes(), asset["sha256"])
    print(f'Verified {len(lock["assets"])} pinned SRAM assets: {args.output}')


if __name__ == "__main__":
    main()

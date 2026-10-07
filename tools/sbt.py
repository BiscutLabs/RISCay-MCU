# SPDX-License-Identifier: Apache-2.0
# Adapted from BiscutLabs/chisel-async tools/sbt.py (Apache-2.0).
"""Portable pinned sbt launcher. Requires JDK 21 and the chisel-async RC1 JAR."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.12.4"
SHA256 = "45eb459f46b234ccdfe4a16c6863dc5a793ac5f71acc2412a2b2b5b176461104"


def main() -> int:
    args = sys.argv[1:]
    bootstrap = "--bootstrap" in args
    args = [arg for arg in args if arg != "--bootstrap"]
    launcher = ROOT / ".tools" / f"sbt-launch-{VERSION}.jar"
    if not launcher.exists():
        if not bootstrap:
            raise RuntimeError("Run tools/sbt.py --bootstrap <tasks> to install the pinned launcher.")
        url = f"https://repo.maven.apache.org/maven2/org/scala-sbt/sbt-launch/{VERSION}/{launcher.name}"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise RuntimeError("Downloaded launcher checksum mismatch")
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_bytes(data)
    if hashlib.sha256(launcher.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Cached launcher checksum mismatch")
    java_home = os.environ.get("JAVA_HOME")
    java = str(Path(java_home) / "bin" / ("java.exe" if os.name == "nt" else "java")) if java_home else shutil.which("java")
    if not java:
        raise RuntimeError("Install JDK 21 and set JAVA_HOME.")
    command = [java, "-Xmx2G", "-XX:ActiveProcessorCount=4", "-Dsbt.supershell=false",
               "-Dsbt.color=false", "-Dsbt.override.build.repos=true",
               f"-Dsbt.repository.config={ROOT / 'project' / 'repositories'}",
               "-jar", str(launcher), *args]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError) as error:
        print(f"sbt: {error}", file=sys.stderr)
        sys.exit(2)

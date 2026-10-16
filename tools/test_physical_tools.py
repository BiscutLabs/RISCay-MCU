# SPDX-License-Identifier: Apache-2.0
"""Native and WSL command construction; no installed physical tools required."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import physical_tools as p
from check_control_relative_controls import verify_runtime
from gf180_physical import sha


class RuntimeTests(unittest.TestCase):
    def configured(self,entry):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        path=Path(temp.name)/"tools.json"
        path.write_text(json.dumps(dict(schema=1,tools=dict(sta=entry))))
        env=patch.dict(os.environ,RISCAY_PHYSICAL_TOOLS=str(path));env.start();self.addCleanup(env.stop)
        return p.tool("sta")

    def test_native_argv_preserves_spaces(self):
        tool=self.configured(dict(executable="/custom path/sta"))
        self.assertEqual(tool.command(["-exit","a b.tcl"]),["/custom path/sta","-exit","a b.tcl"])

    def test_wsl_argv_and_bounded_timeout(self):
        tool=self.configured(dict(executable="/nix/sta",distribution="test-distro",timeout_executable="/nix/coreutils",timeout_arguments=["--coreutils-prog=timeout"]))
        self.assertEqual(tool.command(["-exit","a b.tcl"],timeout=55),[
            "wsl","-d","test-distro","-e","/nix/coreutils","--coreutils-prog=timeout",
            "--signal=TERM","--kill-after=5s","55s","/nix/sta","-exit","a b.tcl"])
        self.assertEqual(str(tool.host_path()).replace("\\","/"),"//wsl.localhost/test-distro/nix/sta")

    def test_config_and_executables_are_evidence_inputs(self):
        tool=self.configured(dict(executable="/nix/sta",distribution="test",timeout_executable="/bin/timeout"))
        files=tool.input_files()
        self.assertEqual(files[0],tool.config_path)
        self.assertIn("physical_tools.py",str(files[-1]))
        self.assertEqual(len(files),4)

    @unittest.skipUnless(os.name=="nt","Windows mounted-drive host path")
    def test_mounted_drive_hashes_original_windows_file(self):
        tool=self.configured(dict(executable="/mnt/p/tools/yosys",distribution="Ubuntu"))
        self.assertEqual(tool.host_path(),Path("P:/tools/yosys"))

    def test_native_executable_resolved_before_hashing(self):
        tool=self.configured(dict(executable="sta"))
        with patch.object(p.shutil,"which",return_value=__file__):
            self.assertEqual(tool.host_path(),Path(__file__).resolve())

    def test_bad_arguments_rejected(self):
        for entry in (dict(executable="sta",timeout_arguments="--bad"),dict(executable=None),
                      dict(executable="sta\nexit"),dict(executable="sta",distribution="../bad"),
                      dict(executable="sta",unexpected=True)):
            with self.subTest(entry=entry),self.assertRaises(ValueError):self.configured(entry)

    def test_relative_wsl_executable_rejected(self):
        tool=self.configured(dict(executable="sta",distribution="test"))
        with self.assertRaisesRegex(ValueError,"PHYSICAL_WSL_EXECUTABLE_ABSOLUTE"):tool.host_path()

    def test_timeout_bound(self):
        tool=self.configured(dict(executable="sta"))
        for value in (0,-1,True,1.5):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,"PHYSICAL_TOOL_TIMEOUT"):
                tool.command([],timeout=value)

    def test_fault_campaign_rejects_different_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            original=Path(directory)/"original";other=Path(directory)/"other"
            original.write_text("same bytes");other.write_text("same bytes")
            frozen={str(original.resolve()):sha(original)}
            self.assertEqual(verify_runtime(SimpleNamespace(input_files=lambda:[original]),frozen),frozen)
            with self.assertRaisesRegex(ValueError,"RELATIVE_CONTROL_RUNTIME_CHANGED"):
                verify_runtime(SimpleNamespace(input_files=lambda:[other]),frozen)


if __name__=="__main__":unittest.main()

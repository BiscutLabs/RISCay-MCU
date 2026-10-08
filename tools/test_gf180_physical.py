# SPDX-License-Identifier: Apache-2.0
"""Controls for mapping safety, area accounting and independent event monitors."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from gf180_physical import adapter, sha
from gf180_constraints import monitors, brace
from check_gf180_envelopes import strict, run as envelopes

def primitive(model,**parameters):
    return dict(model="ChiselAsync"+model+"_v1",parameters={k:str(v) for k,v in parameters.items()})

class PhysicalControls(unittest.TestCase):
    def test_relative_guard_requires_finite_positive_margin(self):
        self.assertEqual(strict(31,30,"writeback")["margin_ns"],1)
        for available,required in ((30,30),(29,30),(float("nan"),30),(31,float("nan")),
                                   (float("inf"),30),(31,float("inf")),(-1,-2)):
            with self.assertRaisesRegex(ValueError,"RELATIVE_ENVELOPE_FAILED"):
                strict(available,required,"writeback")

    def test_envelope_evidence_must_match_current_mapping_and_netlist(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            for name in ("mapped","cells","stages"): (folder/name).mkdir()
            mapped,cells,stages=(folder/name for name in ("mapped","cells","stages"))
            (mapped/"mapping.json").write_text('{}')
            (mapped/"netlist.v").write_text('module top; endmodule\n')
            (cells/"results.json").write_text(json.dumps(dict(status="bounds-pass",mapping_sha256="stale")))
            (stages/"results.json").write_text(json.dumps(dict(status="pass",netlist_sha256="stale")))
            with self.assertRaisesRegex(ValueError,"STALE_CELL_ENVELOPES"):
                envelopes(mapped,cells,stages,folder/"result.json")
            (cells/"results.json").write_text(json.dumps(dict(status="bounds-pass",mapping_sha256=sha(mapped/"mapping.json"))))
            with self.assertRaisesRegex(ValueError,"STALE_DATA_PATHS"):
                envelopes(mapped,cells,stages,folder/"result.json")
            self.assertFalse((folder/"result.json").exists())

    def test_data_allowance_is_not_a_bank_of_delay_lines(self):
        c,r=adapter(primitive("ControlGate",WIDTH=278,OP=0,DELAY_FS=20000000,RESET_VALUE=0),0.1)
        self.assertEqual(sum(x["cell"].endswith("buf_1") for x in c.cells),278)
        self.assertEqual(r["role"],"whole-transform-allowance")

    def test_long_guard_has_real_preserved_cells(self):
        c,r=adapter(primitive("ControlGate",WIDTH=1,OP=0,DELAY_FS=31000000,RESET_VALUE=0),1.4)
        self.assertEqual(sum(x["cell"].endswith("dlyd_1") for x in c.cells),27)
        text=c.verilog("candidate",[])
        self.assertNotIn("#",text); self.assertIn('dont_touch = "yes"',text)
        self.assertEqual(r["control_min_ns"],31)

    def test_unsupported_cells_and_reset_are_rejected(self):
        for p in (primitive("Mutex",DELAY_FS=1000000),primitive("AsymmetricC",COMMON=1,RESET_VALUE=1)):
            with self.assertRaises(ValueError): adapter(p,0.1)

    def test_c_element_is_one_static_keeper(self):
        c,_=adapter(primitive("AsymmetricC",COMMON=1,RISING=2,FALLING=1,COMMON_INVERT=1,
            RISING_INVERT=2,FALLING_INVERT=1,RESET_VALUE=0,DELAY_FS=1000000),0.1)
        a=[x for x in c.cells if x["cell"].endswith("aoi21_1")]
        n=[x for x in c.cells if x["cell"].endswith("nor2_1")]
        self.assertEqual(len(a),1); self.assertEqual(len(n),1)
        self.assertEqual(a[0]["pins"]["A1"],n[0]["pins"]["ZN"])
        self.assertEqual(a[0]["pins"]["ZN"],n[0]["pins"]["A1"])

    def test_storage_has_exact_bit_count_and_bounded_fanout_tree(self):
        c,r=adapter(primitive("EventRegister",WIDTH=278,RESET_VALUE=0,DELAY_FS=1000000),0.1)
        self.assertEqual(sum("dffrnq" in x["cell"] for x in c.cells),278)
        fanout={}
        for x in c.cells:
            if "CLK" in x["pins"]: fanout[x["pins"]["CLK"]]=fanout.get(x["pins"]["CLK"],0)+1
        self.assertLessEqual(max(fanout.values()),16)

    def test_tcl_injection_is_rejected(self):
        for name in ("x}\nexit", "{x", "x\ry"):
            with self.assertRaises(ValueError): brace(name)

    def test_pulse_and_aperture_monitors_reject_real_violations(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder); monitors(folder,[])
            source=(folder/"event-monitors.sv").read_text().split("module riscay_physical_monitors;")[0]
            stimuli={
                "pass":"#10; d=1; #10; clk=1; #10; clk=0; #10;",
                "setup":"#10; d=1; #1; clk=1; #10;",
                "hold":"#10; clk=1; #0.1; d=1; #10;",
                "high":"#10; clk=1; #0.1; clk=0; #10;",
                "low":"#10; clk=1; #10; clk=0; #0.1; clk=1; #10;"}
            stimuli["recovery"]="#0.1; clk=1; #10;"
            for name,stimulus in stimuli.items():
                tb=source+'\nmodule tb; timeunit 1ns; timeprecision 1ps; reg clk=0,d=0,rn=0;\n'
                tb+='riscay_capture_check m(clk,d,rn); initial begin #5; rn=1; '+stimulus+' $display("DONE"); $finish; end endmodule\n'
                path=folder/(name+".sv"); path.write_text(tb)
                binary=folder/(name+".vvp")
                subprocess.run(["iverilog","-g2012","-s","tb","-o",str(binary),str(path)],check=True,capture_output=True)
                result=subprocess.run(["vvp",str(binary)],capture_output=True,text=True,timeout=10)
                if name=="pass": self.assertEqual(result.returncode,0,result.stdout)
                else:
                    self.assertNotEqual(result.returncode,0,name)
                    self.assertIn("ASYNC_"+name.upper(),result.stdout)

if __name__=="__main__": unittest.main()

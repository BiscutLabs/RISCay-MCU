# SPDX-License-Identifier: Apache-2.0
"""Independent negative controls for native I2C publication contracts."""
import copy
import unittest
from pathlib import Path
import subprocess
import tempfile
import re
from check_export import (I2C_PROJECTION_PATH, validate_i2c_publication,
                          validate_fabric_inventory, validate_native_click, i2c_path_bindings,
                          i2c_background)


def fixture(click):
    protocol = "two-phase-bundled-v1" if click else "four-phase-bundled-v1"
    width = 687 if click else 685
    n = dict(module="I2cPublication", children=[], channels=[dict(id=i,role=r,protocol=protocol)
             for i,r in (("in","input"),("frame","output"),("snapshot","output"))],primitives=[],
             endpoints=[dict(id=i,width=w,rtl_path="Top."+i) for i,w in
               dict(in_data=687,frame_data=337,snapshot_data=8,observed=340,capture=1,
                    sources=1034 if click else 1032,register_data=width,captured=width,
                    in_request=1,in_acknowledge=1,frame_request=1,snapshot_request=1,frame_acknowledge=1,snapshot_acknowledge=1).items()],
             timing=[dict(id="projection",kind="bundled-data-path-v1",logic=I2C_PROJECTION_PATH,
                          delay_owner=[],delay_cell="data_delay",source="sources",sink="register_data"),
                     dict(id="projection_aperture",kind="bundled-setup-hold-v1",launch="in_request",
                          transaction="in_data",data_valid="register_data",capture="capture",captured="captured",
                          setup_fs="100000",hold_fs="100000")])
    def cell(i,model,width=None,delay=1000000,**p):
        p.update(DELAY_FS=str(delay))
        if width is not None: p["WIDTH"]=str(width)
        n["primitives"].append(dict(id=i,rtl_path="Top."+i,model="ChiselAsync"+model+"_v1",
                                    parameters={k:str(v) for k,v in p.items()}))
    for i,w in (("observation",340),("frame_payload",337),("snapshot_payload",8)):
        cell(i,"EventRegister",w,RESET_VALUE=0)
    for i,d,w in (("request_delay",11000000,1),("data_delay",10000000,width),
                  ("acknowledge_guard",110000000,1),("output_guard",110000000,1),("return_guard",110000000,1)):
        cell(i,"ControlGate",w,d,OP=0,RESET_VALUE=0)
    if click:
        cell("accepted_phase","PhaseRegister",RESET_VALUE=0)
        cell("frame_phase","EventRegister",1,RESET_VALUE=0); cell("snapshot_phase","EventRegister",1,RESET_VALUE=0)
        cell("pending","Xor"); prefixes=["capture_gate"]
    else:
        for i in ("admission","frame_pending","snapshot_pending"):
            cell(i,"AsymmetricC",COMMON=1,RISING=1,FALLING=0,COMMON_INVERT=0,RISING_INVERT=0,FALLING_INVERT=0,RESET_VALUE=0)
        prefixes=["frame_publish","snapshot_publish"]
    for prefix in prefixes:
        for suffix,op,initial in (("_na",1,1),("_nb",1,1),("_or",2,1),("",1,0)):
            cell(prefix+suffix,"ControlGate",1,OP=op,RESET_VALUE=initial)
    return n


class I2cExportTest(unittest.TestCase):
    def test_decode_background_preserves_checks_and_rejects_bad_mapping(self):
        fields = {"head": (336,4), "mode": (328,4), "active": (327,1),
                  "addressByte": (325,1), "selectedWrite": (324,1),
                  "receive": (316,8), "bit": (313,3), "length": (303,6)}
        state = dict(primitives=[dict(id="payload", model="ChiselAsyncEventRegister_v1",
                    rtl_path="Top.i2c.native.state.payload",
                    ports=[dict(name="q",width=340,direction="output")])],
                    channels=[dict(id="out",layout=[dict(field="bits."+n,lsb=b,width=w)
                              for n,(b,w) in fields.items()])])
        owner = dict(module="I2cTarget",rtl_path="Top.i2c",children=[dict(id="native",contract=dict(
            module="ClickI2c",children=[dict(id="state",contract=state)]))])
        manifest = dict(top="Top",design=dict(children=[dict(id="i2c",contract=owner)]))
        regs = {"slots_0_"+n:1 for n in ("rise","sda","stop","start","timeout")}
        scopes = {"Top.i2c":dict(registers=regs)}
        header = "force Top.reset = 1'h0;\nforce Top.i2c.native.state.payload.q = 340'h0;\n"
        header += "".join(f"force Top.i2c.{n} = 1'h0;\n" for n in regs)+"#1;\n"
        rtl = """module Payload; reg [339:0] q; endmodule
module State; Payload payload(); endmodule
module Native; State state(); endmodule
module I2c; Native native();
""" + "\n".join("reg "+n+";" for n in regs) + """
wire [339:0] s = native.state.payload.q;
wire frame = !slots_0_timeout && (slots_0_start || slots_0_stop) && s[324] && s[308:303]!=0;
wire snapshot = !slots_0_timeout && s[331:328]==1 && slots_0_rise && s[315:313]==7 &&
  s[325] && s[322:316]==7'h35 && slots_0_sda;
wire [1:0] expected = {frame,snapshot};
wire [1:0] observed = expected;
endmodule
module Top; reg reset; I2c i2c(); endmodule
"""
        source = """module ContractProbe; timeunit 1ns; timeprecision 1ps;
reg [1:0] ones_0=0,zeros_0=0;
task check; begin
if (Top.i2c.observed !== Top.i2c.expected) $fatal(1,"BINDING_MISMATCH");
ones_0=ones_0|Top.i2c.observed; zeros_0=zeros_0|~Top.i2c.observed;
end endtask
initial begin
force Top.reset = 1'b1; #1;
""" + header + """check;
if (ones_0 !== 2'h3 || zeros_0 !== 2'h3) $fatal(1,"INACTIVE_ENDPOINT:observed");
$display("CONTRACT_PROBES_PASS:1"); $finish; end endmodule
"""
        extended,count=i2c_background(source,manifest,scopes,1)
        self.assertEqual(count,131)
        self.assertTrue(extended.startswith(source[:source.index('if (ones_0 !==')]))
        self.assertIn('if (ones_0 !==',extended)
        self.assertEqual(set(re.findall(r"force (\S+) =",extended)),set(re.findall(r"force (\S+) =",source)))
        with tempfile.TemporaryDirectory(prefix="riscay-i2c-decode-") as folder:
            path=Path(folder)
            for stimulus,model,expected in ((source,rtl,"INACTIVE_ENDPOINT"),
                    (extended,rtl,"CONTRACT_PROBES_PASS"),
                    (extended,rtl.replace("7'h35","7'h2a"),"CONTRACT_PROBES_PASS"),
                    (extended,rtl.replace("observed = expected;","observed = expected ^ 1'b1;"),"BINDING_MISMATCH")):
                (path/"test.sv").write_text(model+stimulus,encoding="utf-8")
                build=subprocess.run(["iverilog","-g2012","-s","Top","-s","ContractProbe","-o","sim.vvp","test.sv"],
                                     cwd=path,capture_output=True,text=True,timeout=30)
                self.assertEqual(build.returncode,0,build.stderr)
                run=subprocess.run(["vvp","sim.vvp"],cwd=path,capture_output=True,text=True,timeout=30)
                self.assertEqual(run.returncode==0,expected=="CONTRACT_PROBES_PASS",run.stdout)
                self.assertIn(expected,run.stdout)
        for mutate in (lambda: state["primitives"][0]["ports"][0].update(width=339),
                       lambda: state["channels"][0]["layout"][0].update(lsb=335),
                       lambda: scopes["Top.i2c"]["registers"].update(slots_0_rise=2)):
            saved_state=copy.deepcopy(state); saved_scopes=copy.deepcopy(scopes)
            mutate()
            with self.assertRaisesRegex(ValueError,"I2C_PROBE_.*MISMATCH"):
                i2c_background(source,manifest,scopes,1)
            state.clear(); state.update(saved_state); scopes.clear(); scopes.update(saved_scopes)
        with self.assertRaisesRegex(ValueError,"I2C_PROBE_DRIVER_MISMATCH"):
            i2c_background(source.replace("force Top.i2c.slots_0_stop = 1'h0;\n",""),manifest,scopes,1)

    def test_obligations_aperture_width_and_native_protocol_fail_closed(self):
        for click in (False,True):
            n=fixture(click); self.assertEqual(validate_i2c_publication(n),click)
            validate_fabric_inventory(dict(design=n))
            mutations=[lambda x:x["timing"].pop(), lambda x:x["timing"][0].update(delay_cell="missing"),
                       lambda x:x["timing"][1].update(hold_fs="0"),lambda x:x["endpoints"][0].update(width=686),
                       lambda x:x["channels"].pop(),lambda x:x["children"].append(dict(contract={}))]
            for change in mutations:
                bad=copy.deepcopy(n);change(bad)
                with self.assertRaisesRegex(ValueError,"MCU_I2C_"): validate_fabric_inventory(dict(design=bad))

    def test_every_cell_and_guard_is_required_with_its_declared_policy(self):
        for click in (False,True):
            n=fixture(click)
            for i in range(len(n["primitives"])):
                for kind in ("remove","model","delay"):
                    bad=copy.deepcopy(n)
                    if kind=="remove":bad["primitives"].pop(i)
                    elif kind=="model":bad["primitives"][i]["model"]="Unrelated"
                    else:bad["primitives"][i]["parameters"]["DELAY_FS"]="1"
                    with self.assertRaisesRegex(ValueError,"MCU_I2C_"):validate_i2c_publication(bad)

    def test_actual_storage_and_all_phase_pins_are_bound(self):
        for click in (False,True):
            pairs=i2c_path_bindings(fixture(click)); text=str(pairs)
            for name in ["observation","frame_payload","snapshot_payload"]+(["frame_phase","snapshot_phase"] if click else []):
                for pin in ("d","q","trigger"):self.assertIn("Top."+name+"."+pin,text)
            for guard in ("acknowledge_guard","output_guard","return_guard"):
                self.assertIn("Top."+guard+".a",text); self.assertIn("Top."+guard+".q",text)
            self.assertIn("Top.data_delay.a",text)
            for prefix in (("capture_gate",) if click else ("frame_publish","snapshot_publish")):
                for suffix,pin in (("_na","a"),("_nb","b")):
                    self.assertIn(("Top."+prefix+suffix+".q","Top."+prefix+"_or."+pin),pairs)
                self.assertIn(("Top."+prefix+"_or.q","Top."+prefix+".a"),pairs)
            self.assertEqual(len(pairs),29 if click else 35)

    def test_comparison_mechanism_rejects_each_unequal_observation(self):
        # Treat each side as an independent observation. The real export test
        # binds these comparisons to RTL; these controls prove each can reject.
        for click in (False,True):
            pairs=i2c_path_bindings(fixture(click))
            signals=sorted({x for pair in pairs for x in pair})
            names={x:"pin_"+str(i) for i,x in enumerate(signals)}
            for broken in [None]+list(dict.fromkeys(b for _,b in pairs)):
                declarations="\n".join("reg [1033:0] "+names[x]+";" for x in signals)
                checks="\n".join(f'if ({names[a]} !== {names[b]}) $fatal(1,"I2C_PIN_BINDING");' for a,b in pairs)
                initial="\n".join(names[x]+"=0;" for x in signals)
                changed="\n".join(names[x]+("=0;" if x==broken else "={1034{1'b1}};") for x in signals)
                rtl="module Testbench;\n"+declarations+"\ninitial begin\n"+initial+"\n#1;\n"+checks+"\n"+changed+"\n#1;\n"+checks+'\n$display("I2C_PINS_PASS"); $finish; end endmodule'
                with tempfile.TemporaryDirectory(prefix="riscay-i2c-export-") as folder:
                    root=Path(folder);(root/"test.sv").write_text(rtl)
                    built=subprocess.run(["iverilog","-g2012","-s","Testbench","-o","sim.vvp","test.sv"],cwd=root,capture_output=True,text=True,timeout=30)
                    self.assertEqual(built.returncode,0,built.stderr)
                    run=subprocess.run(["vvp","sim.vvp"],cwd=root,capture_output=True,text=True,timeout=30)
                    self.assertEqual(run.returncode==0,broken is None,run.stdout)
                    self.assertIn("I2C_PINS_PASS" if broken is None else "I2C_PIN_BINDING",run.stdout)

    def test_standalone_native_click_rejects_hidden_rtz(self):
        root=dict(module="ClickI2c",channels=[],primitives=[],children=[dict(contract=fixture(True))])
        validate_native_click(dict(top="ClickI2c",design=root))
        root["children"][0]["contract"]["channels"][0]["protocol"]="four-phase-bundled-v1"
        with self.assertRaisesRegex(ValueError,"RTZ"):validate_native_click(dict(top="ClickI2c",design=root))

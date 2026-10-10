# SPDX-License-Identifier: Apache-2.0
"""Independent constant-port and wiring controls for the native SPI recipe."""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from check_export import SPI_PROGRAM, spi_program_probe, validate_native_click


class SpiProgramTest(unittest.TestCase):
    def fixture(self, click):
        model = "ClickSpiAdc" if click else "FourPhaseSpiAdc"
        protocol = "two-phase-bundled-v1" if click else "four-phase-bundled-v1"
        node = dict(module=model, rtl_path="SpiAdc.ca_child_native", children=[],
                    channels=[dict(id=c, protocol=protocol, role=r) for c,r in (
                        ("command","input"),("reply","output"),("wave","output"),("capture","input"))])
        parent = dict(module="SpiAdc", rtl_path="SpiAdc", children=[dict(id="native",contract=node)] + [
            dict(id=c+"_bridge",contract=dict(module="Bridge",rtl_path="SpiAdc."+c,children=[]))
            for c in ("command","reply","wave","capture")])
        ports = {"program_"+f: dict(name="program_"+f,width=w,direction="output") for f,(w,v) in SPI_PROGRAM.items()}
        scopes = {node["rtl_path"]:dict(ports=ports), "SpiAdc":dict(nets={"recipe_"+f:w for f,(w,v) in SPI_PROGRAM.items()})}
        return dict(top="SpiAdc",design=parent),scopes

    def test_exact_constant_recipe_and_recipe_boundary_binding(self):
        for click in (False,True):
            manifest,scopes = self.fixture(click)
            source = '''module ContractProbe; task check; begin
if (SpiAdc.reset !== 0) $fatal(1,"EXISTING_RESET_CHECK");
end endtask
initial begin #1; check; $display("SPI_PROGRAM_PASS"); $finish; end endmodule
'''
            probe=spi_program_probe(source,manifest,scopes)
            self.assertIn('if (SpiAdc.reset !== 0)',probe)
            self.assertNotIn('force ',probe)
            ports=",".join(f"output [{w-1}:0] program_{f}" for f,(w,v) in SPI_PROGRAM.items())
            constants="\n".join(f"assign program_{f}={w}'h{v:x};" for f,(w,v) in SPI_PROGRAM.items())
            nets="\n".join(f"wire [{w-1}:0] recipe_{f};" for f,(w,v) in SPI_PROGRAM.items())
            bindings=",".join(f".program_{f}(recipe_{f})" for f in SPI_PROGRAM)
            original=f"module Native({ports}); {constants} endmodule\nmodule SpiAdc; wire reset=0; {nets}\nNative ca_child_native({bindings}); endmodule\n"
            cases=[("baseline",original,"SPI_PROGRAM_PASS")]
            for field,(width,value) in SPI_PROGRAM.items():
                cases.append(("value-"+field,original.replace(f"assign program_{field}={width}'h{value:x};",
                    f"assign program_{field}={width}'h{value^1:x};"),"MCU_SPI_PROGRAM_VALUE"))
                cases.append(("disconnected-"+field,original.replace(f".program_{field}(recipe_{field})",
                    f".program_{field}()"),"MCU_SPI_PLAYER_BINDING"))
            with tempfile.TemporaryDirectory(prefix="riscay-spi-recipe-") as folder:
                path=Path(folder)
                for label,rtl,expected in cases:
                    (path/"test.sv").write_text(rtl+probe,encoding="utf-8")
                    built=subprocess.run(["iverilog","-g2012","-s","SpiAdc","-s","ContractProbe","-o","sim.vvp","test.sv"],cwd=path,capture_output=True,text=True,timeout=30)
                    self.assertEqual(built.returncode,0,built.stderr)
                    result=subprocess.run(["vvp","sim.vvp"],cwd=path,capture_output=True,text=True,timeout=30)
                    self.assertEqual(result.returncode==0,label=="baseline",result.stdout)
                    self.assertIn(expected,result.stdout)

    def test_recipe_inventory_width_direction_owner_and_probe_drift_fail_closed(self):
        manifest,scopes=self.fixture(True)
        for change in ("missing","width","direction","extra","recipe","owner","protocol"):
            m,s=copy.deepcopy(manifest),copy.deepcopy(scopes)
            ports=s["SpiAdc.ca_child_native"]["ports"]
            if change=="missing": del ports["program_sclk"]
            if change=="width": ports["program_sclk"]["width"]=31
            if change=="direction": ports["program_sclk"]["direction"]="input"
            if change=="extra": ports["program_extra"]=dict(name="program_extra",width=1,direction="output")
            if change=="recipe": s["SpiAdc"]["nets"]["recipe_sclk"]=31
            if change=="owner": m["design"]["children"].pop()
            if change=="protocol": m["design"]["children"][0]["contract"]["channels"][0]["protocol"]="four-phase-bundled-v1"
            with self.assertRaisesRegex(ValueError,"MCU_SPI_"):
                spi_program_probe("task check; begin",m,s)
        with self.assertRaisesRegex(ValueError,"MCU_SPI_PROBE_SHAPE"):
            spi_program_probe("",manifest,scopes)

    def test_standalone_click_spi_rejects_hidden_four_phase_implementation(self):
        manifest,_=self.fixture(True)
        node=manifest["design"]["children"][0]["contract"]
        node["primitives"]=[]
        manifest=dict(top="ClickSpiAdc",design=node)
        validate_native_click(manifest)
        node["channels"][0]["protocol"]="four-phase-bundled-v1"
        with self.assertRaisesRegex(ValueError,"MCU_CLICK_HAS_RTZ"):
            validate_native_click(manifest)


if __name__ == "__main__": unittest.main()

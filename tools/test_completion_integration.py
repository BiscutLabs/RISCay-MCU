# SPDX-License-Identifier: Apache-2.0
"""Independent constant-boundary and source-campaign negative controls."""
import copy
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from check_completion_integration import completion_background, completion_constants_probe


def fixture(top):
    click = top == "ClickSoc"
    module = "DecoupledToClick" if click else "DecoupledToFourPhase"
    protocol = "two-phase-bundled-v1" if click else "four-phase-bundled-v1"
    children, scopes, instances, declarations, comparisons, coverage = [], {}, [], [], [], []
    for i, name in enumerate(("plan", "memory", "telemetry", "housekeeping")):
        path = top+".ca_child_completion_"+name+"_bridge"
        width = 37 if name == "plan" else 33 if name == "memory" else 1
        layout = [("bits.error", 0, 1), ("bits.data", 1, 32)] if name == "memory" else [("bits", 0, width)]
        node = dict(module=module, rtl_path=path, channels=[
            dict(id="in", protocol="decoupled-v1", role="input", data="in_data",
                 layout=[dict(field=f, lsb=l, width=w, signed=False) for f,l,w in layout]),
            dict(id="out", protocol=protocol, role="output")],
            endpoints=[dict(id="in_data", width=width, rtl_path=path+".payload")])
        children.append(dict(id="completion_"+name+"_bridge", contract=node))
        if name == "plan": continue
        pin = "in_bits_error" if name == "memory" else "in_bits"
        actual_module = "MemoryBoundary" if name == "memory" else "EffectBoundary"
        scopes[path] = dict(model=actual_module, ports={pin:dict(name=pin,width=1,direction="input")})
        instances.append(f"{actual_module} ca_child_completion_{name}_bridge (\n"
                         +(f".data(data),\n" if name == "memory" else "")
                         +f".{pin}(1'h{0 if name == 'memory' else 1})\n);\n")
        declarations.append(f"reg [{width-1}:0] ones_{i}=0, zeros_{i}=0;")
        for bit in range(width):
            value = path+".payload"+(f"[{bit}]" if width > 1 else "")
            comparisons.extend((f"if ({value} === 1'b1) ones_{i}[{bit}]=1;",
                                f"if ({value} === 1'b0) zeros_{i}[{bit}]=1;"))
        coverage.append(f"if (ones_{i} !== {width}'h{(1<<width)-1:x} || zeros_{i} !== {width}'h{(1<<width)-1:x}) "
                        +f'$fatal(1, "INACTIVE_ENDPOINT:{path}.payload");')
    manifest = dict(top=top, design=dict(children=children))
    rtl = ("module MemoryBoundary(input [31:0] data,input in_bits_error); wire [32:0] payload={data,in_bits_error}; endmodule\n"
           "module EffectBoundary(input in_bits); wire payload=in_bits; endmodule\n"
           +f"module {top}; reg [31:0] data=0;\n"+"".join(instances)+"endmodule\n")
    probe = ("module ContractProbe;\n"+"\n".join(declarations)+"\ntask check; begin\n"+
             "\n".join(comparisons)+"\nend endtask\ninitial begin\n"+
             f"{top}.data=0; #1; check; {top}.data=32'hffffffff; #1; check;\n"+
             "\n".join(coverage)+'\n$display("PASS"); $finish; end endmodule\n')
    return manifest,scopes,rtl,probe


class CompletionIntegrationTest(unittest.TestCase):
    def test_exact_constant_binding_and_every_dynamic_bit(self):
        for top in ("FourPhaseSoc", "ClickSoc"):
            manifest,scopes,rtl,source = fixture(top)
            probe=completion_constants_probe(source,manifest,scopes,rtl)
            self.assertNotIn("force ",probe)
            self.assertEqual(source.count("INACTIVE_ENDPOINT:"),probe.count("INACTIVE_ENDPOINT:"))
            self.assertIn("ones_1 !== 33'h1fffffffe || zeros_1 !== 33'h1ffffffff",probe)
            self.assertIn("ones_2 !== 1'h1 || zeros_2 !== 1'h0",probe)
            cases=[(rtl,probe,"PASS",True), (rtl,source,"INACTIVE_ENDPOINT",False),
                   (rtl.replace("{data,in_bits_error}","{data & 32'h7fffffff,in_bits_error}"),probe,"INACTIVE_ENDPOINT",False),
                   (rtl.replace(".in_bits_error(1'h0)",".in_bits_error(1'h1)"),probe,"COMPLETION_CONSTANT_BINDING",False),
                   (rtl.replace(".in_bits(1'h1)",".in_bits(1'h0)",1),probe,"COMPLETION_CONSTANT_BINDING",False)]
            with tempfile.TemporaryDirectory(prefix="completion-constant-") as folder:
                path=Path(folder)
                for model,test,expected,passed in cases:
                    (path/"test.sv").write_text(model+test)
                    result=subprocess.run(["iverilog","-g2012","-s",top,"-s","ContractProbe","-o","sim.vvp","test.sv"],cwd=path,capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,result.stderr)
                    result=subprocess.run(["vvp","sim.vvp"],cwd=path,capture_output=True,text=True)
                    self.assertEqual(result.returncode==0,passed,result.stdout)
                    self.assertIn(expected,result.stdout)

    def test_literal_classification_and_schema_fail_closed(self):
        for top in ("FourPhaseSoc", "ClickSoc"):
            m,s,rtl,p=fixture(top)
            for expression in ("data[0]", "1'h1", "1'bx", "(data[0] & 1'b0)"):
                with self.assertRaisesRegex(ValueError,"COMPLETION_CONSTANT_LITERAL"):
                    completion_constants_probe(p,m,s,rtl.replace(".in_bits_error(1'h0)",".in_bits_error("+expression+")"))
            bad=copy.deepcopy(m);bad['design']['children'].pop()
            with self.assertRaisesRegex(ValueError,"COMPLETION_BRIDGE_INVENTORY"):
                completion_constants_probe(p,bad,s,rtl)
            for key,value in (("lsb",1),("width",2),("signed",True)):
                bad=copy.deepcopy(m);bad['design']['children'][1]['contract']['channels'][0]['layout'][0][key]=value
                with self.assertRaisesRegex(ValueError,"COMPLETION_CONSTANT_SCHEMA"):
                    completion_constants_probe(p,bad,s,rtl)
            with self.assertRaisesRegex(ValueError,"COMPLETION_CONSTANT_COVERAGE_SHAPE"):
                completion_constants_probe(p.replace("zeros_1 !== 33'h1ffffffff","zeros_1 !== 33'h1fffffffe"),m,s,rtl)

    def test_background_only_catalogued_registers_original_campaign_preserved(self):
        for top in ("FourPhaseSoc", "ClickSoc"):
            manifest,scopes,_,_=fixture(top)
            regs={top:{n:1 for n in ("gate_enabled","fabric_io_completionIdle_REG","fabric_controlOutstanding",
                                    "fabric_mmioCurrent","fabric_telemetryOutstanding",
                                    "fabric_housekeepingOutstanding","fabric_controlState_programmed")}}
            regs[top]["fabric_controlState_imageLength"]=32
            regs[top+".ca_child_request_bridge"] = dict(state=2,data_mask=4,data_operation=2,data_address=32)
            if top == "ClickSoc":
                regs[top]["ca_child_admission_start_stages"] = 2
            regs[top+".ca_child_admission_grant_bridge"] = dict(state=2)
            regs[top+".ca_child_ram_grant_bridge"] = dict(state=2)
            regs[top+".ca_child_program_grant_bridge"] = dict(state=2)
            path=top+".ca_child_program_source.ca_primitive_eligibility"
            regs[path]=dict(q=1)
            scopes[path]=dict(ports={"q":dict(name="q",width=1,direction="output")})
            manifest["design"]["children"].append(dict(id="program_source",contract=dict(primitives=[
                dict(id="eligibility",rtl_path=path,model="ChiselAsyncEventRegister_v1",parameters=dict(WIDTH="1"))])))
            for owner in ("telemetry","housekeeping"):
                regs[top+f".ca_child_{owner}_grant_bridge"]=dict(state=2)
                path=top+f".ca_child_{owner}_source.ca_primitive_eligibility"
                regs[path]=dict(q=1)
                scopes[path]=dict(ports={"q":dict(name="q",width=1,direction="output")})
                manifest["design"]["children"].append(dict(id=owner+"_source",contract=dict(primitives=[
                    dict(id="eligibility",rtl_path=path,model="ChiselAsyncEventRegister_v1",parameters=dict(WIDTH="1"))])))
            regs[top+".ca_child_control_reply_bridge"] = dict(state=2,data_kind=3,data_memory_data=32,data_memory_error=1)
            for bank in ("program","ram"):
                regs[top+f".ca_child_{bank}_access"]={f"{group}_{stage}":1 for group in (
                    "returned_stages","bytesReturned_stages","bytesReturned_stages_1","bytesReturned_stages_2","bytesReturned_stages_3") for stage in (0,1)}
            regs[top+".ca_child_program_access"]["active"]=1
            regs[top+".ca_child_ram_access"]["active"]=1
            regs[top+".ca_child_ram_access"].update({f"ownerReturned_stages_{i}":1 for i in (0,1)})
            regs[top+".ca_child_ram_access.ca_child_capture_receipt"]=dict(requestSync=1,phase=1)
            root=top+".ca_child_ram_return"
            native=[]
            if top=="ClickSoc":
                native.append(("owned","pending_ca_primitive_owned","ChiselAsyncXor_v1",dict(DELAY_FS="1000000")))
                native.append(("acknowledge_guard","completedDelayed_ca_primitive_acknowledge_guard","ChiselAsyncControlGate_v1",
                               dict(DELAY_FS="200000000",OP="0",RESET_VALUE="0",WIDTH="1")))
                native.extend((n,"ca_primitive_"+n,"ChiselAsyncEventRegister_v1",
                               dict(WIDTH="1",DELAY_FS="1000000",RESET_VALUE="0"))
                              for n in ("received_phase","completed_phase"))
            else:
                native.append(("pending","ca_primitive_pending","ChiselAsyncAsymmetricC_v1",
                               dict(COMMON="1",COMMON_INVERT="1",DELAY_FS="1000000",FALLING="0",FALLING_INVERT="0",
                                    RESET_VALUE="0",RISING="2",RISING_INVERT="0")))
            cells=[]
            for identity,suffix,model,parameters in native:
                path=root+"."+suffix
                q=dict(name="q",width=1,direction="output")
                cells.append(dict(id=identity,rtl_path=path,model=model,parameters=parameters,
                                  reset="reset",reset_domain="root",ports=[q]))
                regs[path]=dict(q=1)
                scopes[path]=dict(model=model,parameters=parameters,ports=dict(q=q))
            manifest["design"]["children"].append(dict(id="ram_return",contract=dict(rtl_path=root,
                module="ClickRamReturn" if top=="ClickSoc" else "FourPhaseRamReturn",primitives=cells)))
            regs[top+".ca_child_program_access.ca_child_reply_bridge"]=dict(state=2,data=32)
            regs[top+".ca_child_telemetry_reply_bridge"]=dict(state=2,data_kind=2)
            regs[top+".ca_child_housekeeping_reply_bridge"]=dict(state=2,data_cpuCompletion=1)
            for path,rs in regs.items():scopes.setdefault(path,{})['registers']=rs
            header="".join(f"force {path}.{name} = {width}'h0;\n" for path,rs in regs.items() for name,width in rs.items())+"#1;\n"
            coverage='if (ones_0 !== 1\'h1 || zeros_0 !== 1\'h1) $fatal(1, "INACTIVE_ENDPOINT:test");\n'
            generic="// Original generic campaign sentinel\n#1; check;\n"
            original=f"initial begin\nforce {top}.reset = 1'b1; #1;\n"+header+generic+coverage+'$display("CONTRACT_PROBES_PASS:1");'
            augmented,count=completion_background(original,manifest,scopes,1)
            self.assertGreater(count,130)
            first_end=original.index(generic)
            self.assertTrue(augmented.startswith(original[:first_end]))
            self.assertEqual(augmented.count(generic),1)
            prelude=augmented[first_end:augmented.index(generic)]
            self.assertEqual(len(re.findall(r"#\d+; check;",prelude)),2)
            self.assertTrue(prelude.endswith(header))
            if top=="ClickSoc":
                owned=root+".pending_ca_primitive_owned.q"
                self.assertIn(f"release {owned};",prelude)
                guard=root+".completedDelayed_ca_primitive_acknowledge_guard.q"
                self.assertIn(f"release {guard};",prelude)
                self.assertEqual(prelude.count("#201000001; check;"),2)
                # The only owned-Q force is in the restored original header.
                self.assertNotIn(f"force {owned}",prelude[:-len(header)])
                self.assertNotIn(f"force {guard}",prelude[:-len(header)])
                for n,value in (("received_phase",1),("completed_phase",0)):
                    self.assertIn(f"force {root}.ca_primitive_{n}.q = 1'h{value};",prelude)
            else:
                self.assertIn(f"force {root}.ca_primitive_pending.q = 1'h1;",prelude)
            self.assertIn(coverage,augmented)
            # Both memory selections must be reached from the real source
            # state. The old RAM-only scenario can no longer cover program.
            for path,width,value in ((top+".fabric_controlState_programmed",1,1),
                                     (top+".fabric_controlState_imageLength",32,4),
                                     (top+".ca_child_program_grant_bridge.state",2,2),
                                     (top+".ca_child_request_bridge.data_address",32,0x10000000),
                                     (top+".ca_child_request_bridge.data_address",32,0x20000000)):
                self.assertIn(f"force {path} = {width}'h{value:x};",augmented)
            ram=top+".ca_child_ram_access"
            receipt=ram+".ca_child_capture_receipt"
            for active in (0,1):
                for request_sync in (0,1):
                    for phase in (0,1):
                        scenario=(f"force {ram}.active = 1'h{active};\n"
                                  f"force {receipt}.requestSync = 1'h{request_sync};\n"
                                  f"force {receipt}.phase = 1'h{phase};\n#1; check;\n")
                        self.assertEqual(augmented.count(scenario),1)
            if top == "ClickSoc":
                for value in range(4):
                    self.assertIn(f"force {top}.ca_child_admission_start_stages = 2'h{value:x};\n#1; check;",augmented)
            allowed={path+'.'+n for path,rs in regs.items() for n in rs}|{top+'.reset'}
            self.assertLessEqual(set(re.findall(r"force (\S+) =",augmented)),allowed)
            for path,rs in regs.items():
                for name in rs:
                    bad=copy.deepcopy(scopes)
                    if 'ports' in bad[path] and name in bad[path]['ports']: del bad[path]['ports'][name]
                    else: del bad[path]['registers'][name]
                    with self.assertRaisesRegex(ValueError,"COMPLETION_BACKGROUND_DRIVER|COMPLETION_RAM_DRAIN_CELL"):
                        completion_background(original,manifest,bad,1)
            owner=manifest["design"]["children"][-1]["contract"]
            for key,value in (("module","WrongOwner"),("rtl_path",root+"_alias")):
                bad=copy.deepcopy(manifest);bad["design"]["children"][-1]["contract"][key]=value
                with self.assertRaisesRegex(ValueError,"COMPLETION_RAM_DRAIN_OWNER"):
                    completion_background(original,bad,scopes,1)
            for index,cell in enumerate(owner["primitives"]):
                for key,value in (("id","alias"),("rtl_path",cell["rtl_path"]+"_alias"),
                                  ("model","WrongPrimitive"),("reset","application_reset"),
                                  ("reset_domain","application"),("parameters",{}),
                                  ("ports",[dict(name="q",width=2,direction="output")]),
                                  ("ports",[dict(name="q",width=1,direction="input")])):
                    bad=copy.deepcopy(manifest);bad["design"]["children"][-1]["contract"]["primitives"][index][key]=value
                    with self.assertRaisesRegex(ValueError,"COMPLETION_RAM_DRAIN_CELL"):
                        completion_background(original,bad,scopes,1)
                for key,value in (("model","WrongPrimitive"),("parameters",{}),
                                  ("ports",dict(q=dict(name="q",width=2,direction="output")))):
                    bad=copy.deepcopy(scopes);bad[cell["rtl_path"]][key]=value
                    with self.assertRaisesRegex(ValueError,"COMPLETION_RAM_DRAIN_CELL"):
                        completion_background(original,manifest,bad,1)
                bad=copy.deepcopy(manifest);bad["design"]["children"][-1]["contract"]["primitives"].append(copy.deepcopy(cell))
                with self.assertRaisesRegex(ValueError,"COMPLETION_RAM_DRAIN_CELL"):
                    completion_background(original,bad,scopes,1)


if __name__ == '__main__':unittest.main()

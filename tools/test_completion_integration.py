# SPDX-License-Identifier: Apache-2.0
"""Independent constant-boundary and source-campaign negative controls."""
import copy
from itertools import product
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
    for i, name in enumerate(("plan", "telemetry", "housekeeping")):
        path = top+".ca_child_completion_"+name+"_bridge"
        width = 37 if name == "plan" else 1
        layout = [("bits", 0, width)]
        node = dict(module=module, rtl_path=path, channels=[
            dict(id="in", protocol="decoupled-v1", role="input", data="in_data",
                 layout=[dict(field=f, lsb=l, width=w, signed=False) for f,l,w in layout]),
            dict(id="out", protocol=protocol, role="output")],
            endpoints=[dict(id="in_data", width=width, rtl_path=path+".payload")])
        children.append(dict(id="completion_"+name+"_bridge", contract=node))
        if name == "plan": continue
        pin = "in_bits"
        actual_module = "EffectBoundary"
        scopes[path] = dict(model=actual_module, ports={pin:dict(name=pin,width=1,direction="input")})
        instances.append(f"{actual_module} ca_child_completion_{name}_bridge (\n"
                         +f".{pin}(1'h1)\n);\n")
        declarations.append(f"reg [{width-1}:0] ones_{i}=0, zeros_{i}=0;")
        for bit in range(width):
            value = path+".payload"+(f"[{bit}]" if width > 1 else "")
            comparisons.extend((f"if ({value} === 1'b1) ones_{i}[{bit}]=1;",
                                f"if ({value} === 1'b0) zeros_{i}[{bit}]=1;"))
        coverage.append(f"if (ones_{i} !== {width}'h{(1<<width)-1:x} || zeros_{i} !== {width}'h{(1<<width)-1:x}) "
                        +f'$fatal(1, "INACTIVE_ENDPOINT:{path}.payload");')
    # Independent dynamic payload remains fully covered; only the obsolete
    # bridge error bit moves to native return alias tests.
    declarations.append('reg [31:0] ones_3=0, zeros_3=0;')
    comparisons.extend((f'ones_3 = ones_3 | {top}.observed;',f'zeros_3 = zeros_3 | ~{top}.observed;'))
    coverage.append(f'if (ones_3 !== 32\'hffffffff || zeros_3 !== 32\'hffffffff) $fatal(1,"INACTIVE_ENDPOINT:{top}.observed");')
    manifest = dict(top=top, design=dict(children=children))
    rtl = ("module MemoryBoundary(input [31:0] data,input in_bits_error); wire [32:0] payload={data,in_bits_error}; endmodule\n"
           "module EffectBoundary(input in_bits); wire payload=in_bits; endmodule\n"
           +f"module {top}; reg [31:0] data=0; wire [31:0] observed=data;\n"+"".join(instances)+"endmodule\n")
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
            self.assertIn("ones_1 !== 1'h1 || zeros_1 !== 1'h0",probe)
            self.assertIn("ones_2 !== 1'h1 || zeros_2 !== 1'h0",probe)
            cases=[(rtl,probe,"PASS",True), (rtl,source,"INACTIVE_ENDPOINT",False),
                   (rtl.replace("observed=data","observed=data & 32'h7fffffff"),probe,"INACTIVE_ENDPOINT",False),
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
            for expression in ("data[0]", "1'h0", "1'bx", "(data[0] | 1'b1)"):
                with self.assertRaisesRegex(ValueError,"COMPLETION_CONSTANT_LITERAL"):
                    completion_constants_probe(p,m,s,rtl.replace(".in_bits(1'h1)",".in_bits("+expression+")"))
            obsolete=copy.deepcopy(m);obsolete['design']['children'].append(dict(id='completion_memory_bridge',contract={}))
            with self.assertRaisesRegex(ValueError,'COMPLETION_OBSOLETE_MEMORY_BRIDGE'):
                completion_constants_probe(p,obsolete,s,rtl)
            bad=copy.deepcopy(m);bad['design']['children'].pop()
            with self.assertRaisesRegex(ValueError,"COMPLETION_BRIDGE_INVENTORY"):
                completion_constants_probe(p,bad,s,rtl)
            for key,value in (("lsb",1),("width",2),("signed",True)):
                bad=copy.deepcopy(m);bad['design']['children'][1]['contract']['channels'][0]['layout'][0][key]=value
                with self.assertRaisesRegex(ValueError,"COMPLETION_CONSTANT_SCHEMA"):
                    completion_constants_probe(p,bad,s,rtl)
            with self.assertRaisesRegex(ValueError,"COMPLETION_CONSTANT_COVERAGE_SHAPE"):
                completion_constants_probe(p.replace("zeros_1 !== 1'h1","zeros_1 !== 1'h0"),m,s,rtl)

    def test_background_only_catalogued_registers_original_campaign_preserved(self):
        for top,coordinated in product(("FourPhaseSoc", "ClickSoc"), (False, True)):
            manifest,scopes,_,_=fixture(top)
            regs={top:{n:1 for n in ("gate_enabled","fabric_io_completionIdle_REG","fabric_controlOutstanding",
                                    "fabric_mmioCurrent","fabric_telemetryOutstanding",
                                    "fabric_housekeepingOutstanding","fabric_controlState_programmed")}}
            regs[top]["fabric_controlState_imageLength"]=32
            if coordinated:
                manifest['design']['endpoints']=[dict(id='native_application_reset')]
                for child in manifest['design']['children']:
                    child['contract']['module'] += 'Quiescing'
                del regs[top]['fabric_io_completionIdle_REG']
                regs[top].update(second=1,resetBoundary_stopped=1,cpuResetActive=1)
                for owner in ('telemetry','housekeeping'):
                    regs[top].update({owner+'Boundary_'+field:1 for field in ('active','revoked','role','pending')})
            regs[top+".ca_child_request_bridge"] = dict(state=2,data_mask=4,data_operation=2,data_address=32)
            if top == "ClickSoc":
                regs[top]["ca_child_admission_start_stages"] = 2
            regs[top+".ca_child_admission_grant_bridge"] = dict(state=2)
            regs[top+".ca_child_ram_grant_bridge"] = dict(state=2)
            regs[top+".ca_child_program_grant_bridge"] = dict(state=2)
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
            def cell(node,identity,suffix,model,parameters,width=1,reset='reset'):
                path=node['rtl_path']+'.'+suffix;q=dict(name='q',width=width,direction='output')
                node['primitives'].append(dict(id=identity,rtl_path=path,model=model,parameters=parameters,
                    reset=reset,reset_domain='root',ports=[q]))
                regs[path]=dict(q=width);scopes[path]=dict(model=model,parameters=parameters,ports=dict(q=q))
            for bank in ('ram','program'):
                access=top+'.ca_child_'+bank+'_access';regs[access]['active']=1
                regs[access].update({f'ownerReturned_stages_{i}':1 for i in (0,1)})
                regs[access+'.ca_child_capture_receipt']=dict(requestSync=1,phase=1)
                root=top+'.ca_child_'+bank+'_return'
                node=dict(rtl_path=root,module=('Click' if top=='ClickSoc' else 'FourPhase')+bank.title()+'Return',primitives=[])
                cell(node,'payload','ca_primitive_payload','ChiselAsyncEventRegister_v1',dict(WIDTH='32',DELAY_FS='1000000',RESET_VALUE='0'),32)
                if top=='ClickSoc':
                    cell(node,'owned','pending_ca_primitive_owned','ChiselAsyncXor_v1',dict(DELAY_FS='1000000'))
                    cell(node,'acknowledge_guard','completedDelayed_ca_primitive_acknowledge_guard','ChiselAsyncControlGate_v1',
                        dict(DELAY_FS='200000000',OP='0',RESET_VALUE='0',WIDTH='1'))
                    for n in ('received_phase','completed_phase'):
                        cell(node,n,'ca_primitive_'+n,'ChiselAsyncEventRegister_v1',dict(WIDTH='1',DELAY_FS='1000000',RESET_VALUE='0'))
                else:
                    cell(node,'pending','ca_primitive_pending','ChiselAsyncAsymmetricC_v1',
                        dict(COMMON='1',COMMON_INVERT='1',DELAY_FS='1000000',FALLING='0',FALLING_INVERT='0',RESET_VALUE='0',RISING='2',RISING_INVERT='0'))
                manifest['design']['children'].append(dict(id=bank+'_return',contract=node))
            owner=dict(rtl_path=top+'.ca_child_program_source',module=('Click' if top=='ClickSoc' else 'FourPhase')+'ProgramSource',primitives=[],children=[])
            reservation=dict(rtl_path=owner['rtl_path']+'.ca_child_reservation',module='ClickBuffer' if top=='ClickSoc' else 'LongHoldBuffer',primitives=[])
            owner['children'].append(dict(id='reservation',contract=reservation))
            event=lambda width:dict(WIDTH=str(width),DELAY_FS='1000000',RESET_VALUE='0')
            cell(owner,'eligibility','ca_primitive_eligibility','ChiselAsyncEventRegister_v1',event(1),reset='eligibility_reset')
            cell(reservation,'payload','ca_primitive_payload','ChiselAsyncEventRegister_v1' if top=='ClickSoc' else 'ChiselAsyncClosingLatch_v1',
                 event(1) if top=='ClickSoc' else dict(WIDTH='1',DELAY_FS='1000000'))
            if top=='ClickSoc':
                cell(reservation,'input_phase','ca_primitive_input_phase','ChiselAsyncPhaseRegister_v1',dict(DELAY_FS='1000000',RESET_VALUE='0'))
                cell(reservation,'acknowledge_guard','ca_primitive_acknowledge_guard','ChiselAsyncControlGate_v1',dict(DELAY_FS='32000000',OP='0',RESET_VALUE='0',WIDTH='1'))
                for n,width in (('armed_phase',2),('retired_phase',1)):
                    cell(owner,n,'ca_primitive_'+n,'ChiselAsyncEventRegister_v1',event(width),width)
                cell(owner,'owned','owned_ca_primitive_owned','ChiselAsyncXor_v1',dict(DELAY_FS='1000000'))
            else:
                cell(reservation,'acknowledge','ca_primitive_acknowledge','ChiselAsyncAsymmetricC_v1',
                     dict(COMMON='1',COMMON_INVERT='1',DELAY_FS='1000000',FALLING='1',FALLING_INVERT='0',RESET_VALUE='0',RISING='1',RISING_INVERT='0'))
            manifest['design']['children'].append(dict(id='program_source',contract=owner))
            regs[top+".ca_child_telemetry_reply_bridge"]=dict(state=2,data_kind=2)
            regs[top+".ca_child_housekeeping_reply_bridge"]=dict(state=2,data_cpuCompletion=1)
            for path,rs in regs.items():scopes.setdefault(path,{})['registers']=rs
            header="".join(f"force {path}.{name} = {width}'h0;\n" for path,rs in regs.items() for name,width in rs.items())+"#1;\n"
            coverage='if (ones_0 !== 1\'h1 || zeros_0 !== 1\'h1) $fatal(1, "INACTIVE_ENDPOINT:test");\n'
            generic="// Original generic campaign sentinel\n#1; check;\n"
            original=f"initial begin\nforce {top}.reset = 1'b1; #1;\n"+header+generic+coverage+'$display("CONTRACT_PROBES_PASS:1");'
            augmented,count=completion_background(original,manifest,scopes,1)
            self.assertGreater(count,130)
            self.assertEqual(count,len(re.findall(r"#\d+; check;",augmented)))
            second_coverage=coverage.replace('ones_0','ones_1').replace('zeros_0','zeros_1').replace(':test',':second')
            doubled=original.replace(coverage,coverage+second_coverage).replace('CONTRACT_PROBES_PASS:1','CONTRACT_PROBES_PASS:2')
            twice,twice_count=completion_background(doubled,manifest,scopes,2)
            self.assertEqual(twice_count,2*count)
            self.assertEqual(twice_count,2*len(re.findall(r"#\d+; check;",twice)))
            first_end=original.index(generic)
            self.assertTrue(augmented.startswith(original[:first_end]))
            self.assertEqual(augmented.count(generic),1)
            prelude=augmented[first_end:augmented.index(generic)]
            self.assertEqual(len(re.findall(r"#\d+; check;",prelude)),4)
            self.assertTrue(prelude.endswith(header))
            if top=="ClickSoc":
                owned=root+".pending_ca_primitive_owned.q"
                self.assertIn(f"release {owned};",prelude)
                guard=root+".completedDelayed_ca_primitive_acknowledge_guard.q"
                self.assertIn(f"release {guard};",prelude)
                self.assertEqual(prelude.count("#201000001; check;"),4)
                # The only owned-Q force is in the restored original header.
                self.assertNotIn(f"force {owned}",prelude.replace(header,""))
                self.assertNotIn(f"force {guard}",prelude.replace(header,""))
                for n,value in (("received_phase",1),("completed_phase",0)):
                    self.assertIn(f"force {root}.ca_primitive_{n}.q = 1'h{value};",prelude)
            else:
                self.assertIn(f"force {root}.ca_primitive_pending.q = 1'h1;",prelude)
            self.assertIn(coverage,augmented)
            if coordinated:
                self.assertEqual(augmented.count('COMPLETION_PUBLICATION_MIRROR:'),128)
                for owner in ('telemetry','housekeeping'):
                    inputs=[top+'.'+owner+'Boundary_'+n for n in ('active','revoked','role','pending')]
                    inputs += [top+'.resetBoundary_stopped',top+'.cpuResetActive']
                    for value in range(64):
                        scenario=''.join(f"force {path} = 1'h{(value>>bit)&1};\n" for bit,path in enumerate(inputs))
                        scenario += (f"#1; check;\nif ({top}.ca_child_completion_{owner}_bridge.in_valid !== 1'h{int(value==1)}) "
                                     f'$fatal(1,"COMPLETION_PUBLICATION_MIRROR:{owner}:{value}");\n')
                        self.assertEqual(augmented.count(scenario),1)
                    # The old native-owner case remains ahead of the mirror
                    # truth table; all dynamic polarity assertions survive.
                    previous=(f"force {top}.ca_child_{owner}_reply_bridge."+
                              ('data_kind = 2' if owner=='telemetry' else 'data_cpuCompletion = 1')+"'h1;\n#1; check;\n")
                    self.assertIn(previous,augmented)
            else:
                self.assertNotIn('COMPLETION_PUBLICATION_MIRROR:',augmented)
            # Both memory selections must be reached from the real source
            # state. The old RAM-only scenario can no longer cover program.
            for path,width,value in ((top+".fabric_controlState_programmed",1,1),
                                     (top+".fabric_controlState_imageLength",32,4),
                                     (top+".ca_child_program_grant_bridge.state",2,2),
                                     (top+".ca_child_request_bridge.data_address",32,0x10000000),
                                     (top+".ca_child_request_bridge.data_address",32,0x20000000)):
                self.assertIn(f"force {path} = {width}'h{value:x};",augmented)
            for bank in ('ram','program'):
                access=top+'.ca_child_'+bank+'_access';receipt=access+'.ca_child_capture_receipt'
                for active in (0,1):
                    for request_sync in (0,1):
                        for phase in (0,1):
                            scenario=(f"force {access}.active = 1'h{active};\n"
                                      f"force {receipt}.requestSync = 1'h{request_sync};\n"
                                      f"force {receipt}.phase = 1'h{phase};\n#1; check;\n")
                            self.assertEqual(augmented.count(scenario),1)
            if top=='ClickSoc':
                self.assertEqual(augmented.count('#33000001; check;'),64)
                permission_root=top+'.ca_child_program_source'
                self.assertIn('release '+permission_root+'.owned_ca_primitive_owned.q;',augmented)
                self.assertIn('release '+permission_root+'.ca_child_reservation.ca_primitive_acknowledge_guard.q;',augmented)
                for derived in ('.owned_ca_primitive_owned.q','.ca_child_reservation.ca_primitive_acknowledge_guard.q'):
                    self.assertNotIn('force '+permission_root+derived,augmented.replace(header,''))
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
                    with self.assertRaisesRegex(ValueError,"COMPLETION_BACKGROUND_DRIVER|COMPLETION_NATIVE_RETURN_CELL|COMPLETION_PROGRAM_PERMISSION_CELL"):
                        completion_background(original,manifest,bad,1)
            for bank in ('ram','program'):
                root=top+'.ca_child_'+bank+'_return'
                owner_index=next(i for i,c in enumerate(manifest["design"]["children"]) if c["id"]==bank+"_return")
                owner=manifest["design"]["children"][owner_index]["contract"]
                for key,value in (("module","WrongOwner"),("rtl_path",root+"_alias")):
                    bad=copy.deepcopy(manifest);bad["design"]["children"][owner_index]["contract"][key]=value
                    with self.assertRaisesRegex(ValueError,"COMPLETION_NATIVE_RETURN_OWNER"):
                        completion_background(original,bad,scopes,1)
                for index,cell in enumerate(owner["primitives"]):
                    for key,value in (("id","alias"),("rtl_path",cell["rtl_path"]+"_alias"),
                                      ("model","WrongPrimitive"),("reset","application_reset"),
                                      ("reset_domain","application"),("parameters",{}),
                                      ("ports",[dict(name="q",width=2,direction="output")]),
                                      ("ports",[dict(name="q",width=1,direction="input")])):
                        bad=copy.deepcopy(manifest);bad["design"]["children"][owner_index]["contract"]["primitives"][index][key]=value
                        with self.assertRaisesRegex(ValueError,"COMPLETION_NATIVE_RETURN_CELL"):
                            completion_background(original,bad,scopes,1)
                    for key,value in (("model","WrongPrimitive"),("parameters",{}),
                                      ("ports",dict(q=dict(name="q",width=2,direction="output")))):
                        bad=copy.deepcopy(scopes);bad[cell["rtl_path"]][key]=value
                        with self.assertRaisesRegex(ValueError,"COMPLETION_NATIVE_RETURN_CELL"):
                            completion_background(original,manifest,bad,1)
                    bad=copy.deepcopy(manifest);bad["design"]["children"][owner_index]["contract"]["primitives"].append(copy.deepcopy(cell))
                    with self.assertRaisesRegex(ValueError,"COMPLETION_NATIVE_RETURN_CELL"):
                        completion_background(original,bad,scopes,1)

            source_index=next(i for i,c in enumerate(manifest['design']['children']) if c['id']=='program_source')
            owner=manifest['design']['children'][source_index]['contract']
            for parent_path,node in (((),owner),(('children',0,'contract'),owner['children'][0]['contract'])):
                for index,primitive in enumerate(node['primitives']):
                    for key,value in (('id','alias'),('rtl_path',primitive['rtl_path']+'_alias'),
                        ('model','WrongPrimitive'),('reset','wrong_reset'),('reset_domain','application'),
                        ('parameters',{}),('ports',[dict(name='q',width=99,direction='output')])):
                        bad=copy.deepcopy(manifest);target=bad['design']['children'][source_index]['contract']
                        for part in parent_path:target=target[part]
                        target['primitives'][index][key]=value
                        with self.assertRaisesRegex(ValueError,'COMPLETION_PROGRAM_PERMISSION_CELL'):
                            completion_background(original,bad,scopes,1)



if __name__ == '__main__':unittest.main()

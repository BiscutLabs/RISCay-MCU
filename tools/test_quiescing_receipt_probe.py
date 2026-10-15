# SPDX-License-Identifier: Apache-2.0
"""Independent schemas and executable native-request probe controls."""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from check_quiescing_receipt import native_request_source,pack_request,request_receipt_probe

def add_native_request_fixture(manifest,scopes,inventories):
    top=manifest['top'];click=top=='ClickSoc';prefix='Click' if click else 'FourPhase'
    protocol='two-phase-bundled-v1' if click else 'four-phase-bundled-v1'
    fields=[('mask',0,4),('data',4,32),('address',36,32),('operation',68,2)]
    def node(kind,path):
        return dict(module=prefix+kind,rtl_path=path,reset_domain='root',channels=[],endpoints=[],children=[],primitives=[],timing=[])
    def channel(n,identity,signal,role,p):
        n['channels'].append(dict(id=identity,protocol=p,role=role,reset_domain='root',data=identity+'_data',
            layout=[dict(field='bits.'+f,lsb=l,width=w,signed=False,source=f"~|{n['module']}>{signal}.bits.{f}") for f,l,w in fields]))
        n['endpoints'].append(dict(id=identity+'_data',width=70,source=f"~|{n['module']}>{signal}.bits"))
        phases=({'valid':signal+'.valid','ready':signal+'.ready','clock':'clock'} if p=='decoupled-v1'
                else {'request':signal+'.req','acknowledge':signal+'.ack'})
        for key,value in phases.items():
            n['channels'][-1][key]=identity+'_'+key
            n['endpoints'].append(dict(id=identity+'_'+key,width=1,source=f"~|{n['module']}>{value}"))
        s=scopes.setdefault(n['rtl_path'],dict(model=n['module'],ports={}))
        for field,_,width in fields:
            name=signal+'_bits_'+field
            s['ports'][name]=dict(name=name,width=width,direction='input' if role=='input' else 'output')
        if p!='decoupled-v1':
            for suffix,d in [('req','input' if role=='input' else 'output'),('ack','output' if role=='input' else 'input')]:
                name=signal+'_'+suffix;s['ports'][name]=dict(name=name,width=1,direction=d)
    core=node('Core',top+'.ca_child_core');address=node('Stage',core['rtl_path']+'.ca_child_address')
    fabric=node('Fabric',top+'.ca_child_transactions');receipt=node('QuiescingReceipt',top+'.ca_child_request_bridge')
    core['children'].append(dict(id='address',contract=address))
    for n in (core,address,fabric,receipt):scopes[n['rtl_path']]=dict(model=n['module'],ports={})
    for n,identity,signal,role,p in [(address,'out','out','output',protocol),(core,'request','request','output',protocol),
        (fabric,'request','request','input',protocol),(fabric,'service_request','serviceRequest','output',protocol),
        (receipt,'in','in','input',protocol),(receipt,'out','out','output','decoupled-v1')]:channel(n,identity,signal,role,p)
    receipt['capacity']=1
    receipt['endpoints'] += [dict(id=name,width=1,source=f"~|{receipt['module']}>{name}")
                            for name in ('close','closed','rebase','rebased','reset')]
    regs=dict(localReset_release_0=1,localReset_release_1=1,stopped=1,rebased_REG=1,
        request_first=1,request=1,state=2,acknowledge=1)
    scope=scopes[receipt['rtl_path']];scope['registers']=regs;scope['memories']={}
    inventories[receipt['rtl_path']]=dict(regs)
    for name,direction in [('clock','input'),('reset','input'),('close','input'),('rebase','input'),
        ('closed','output'),('rebased','output'),('in_req','input'),('in_ack','output'),('out_ready','input'),('out_valid','output')]:
        scope['ports'][name]=dict(name=name,width=1,direction=direction)
    q=dict(name='q',width=70,direction='output');parameters=dict(WIDTH='70',DELAY_FS='1000000')
    if click:parameters['RESET_VALUE']='0'
    model='ChiselAsyncEventRegister_v1' if click else 'ChiselAsyncClosingLatch_v1'
    target=address['rtl_path']+'.ca_primitive_payload'
    address['primitives'].append(dict(id='payload',model=model,rtl_path=target,parameters=parameters,
        ports=[q],reset='reset',reset_domain='root'))
    scopes[target]=dict(model=model,parameters=parameters,ports=dict(q=q))
    inventories[target]=dict(q=70)
    manifest['design']['children'] += [dict(id=i,contract=n) for i,n in [('core',core),('transactions',fabric),('request_bridge',receipt)]]
    return target+'.q'

def request_fixture_rtl():
    # data_* are only aliases for old independent consumer expressions, not
    # stored inputs or permitted force targets.
    return '''
module NativeRequestPayload; reg [69:0] q=0; endmodule
module NativeAddress;
NativeRequestPayload ca_primitive_payload();
wire out_req=0,out_ack=0;
wire [3:0] out_bits_mask=ca_primitive_payload.q[3:0];
wire [31:0] out_bits_data=ca_primitive_payload.q[35:4];
wire [31:0] out_bits_address=ca_primitive_payload.q[67:36];
wire [1:0] out_bits_operation=ca_primitive_payload.q[69:68];
endmodule
module NativeCore;
NativeAddress ca_child_address();
wire request_req=0,request_ack=0;
wire [3:0] request_bits_mask=ca_child_address.out_bits_mask;
wire [31:0] request_bits_data=ca_child_address.out_bits_data;
wire [31:0] request_bits_address=ca_child_address.out_bits_address;
wire [1:0] request_bits_operation=ca_child_address.out_bits_operation;
endmodule
module Request(input [69:0] native_bits);
reg [1:0] state=0;
reg close=0,localReset_release_0=0,localReset_release_1=0,stopped=0,rebased_REG=0;
reg request_first=0,request=0,acknowledge=0;
wire out_valid=state==2 && !close && !localReset_release_1;
wire in_ack=acknowledge;
wire in_req=0;
wire [3:0] in_bits_mask=native_bits[3:0];
wire [31:0] in_bits_data=native_bits[35:4];
wire [31:0] in_bits_address=native_bits[67:36];
wire [1:0] in_bits_operation=native_bits[69:68];
wire [3:0] out_bits_mask=out_valid ? in_bits_mask : 4'b0;
wire [31:0] out_bits_data=out_valid ? in_bits_data : 32'b0;
wire [31:0] out_bits_address=out_valid ? in_bits_address : 32'b0;
wire [1:0] out_bits_operation=out_valid ? in_bits_operation : 2'b0;
wire [3:0] data_mask=out_bits_mask;
wire [31:0] data_data=out_bits_data;
wire [31:0] data_address=out_bits_address;
wire [1:0] data_operation=out_bits_operation;
endmodule
'''

class QuiescingRequestProbeTest(unittest.TestCase):
    def fixture(self,click):
        top='ClickSoc' if click else 'FourPhaseSoc';m=dict(top=top,design=dict(children=[]));s={};i={}
        path=add_native_request_fixture(m,s,i)
        header=''.join(f"force {p}.{n} = {w}'h0;\n" for p,regs in i.items() for n,w in regs.items())
        return m,s,i,path,header

    def test_exact_source_and_packing(self):
        for click in (False,True):
            m,s,_,path,h=self.fixture(click)
            self.assertEqual(native_request_source(m,s,h)['path'],path)
            for width,shift,name in [(2,68,'operation'),(32,36,'address'),(32,4,'data'),(4,0,'mask')]:
                for bit in range(width):self.assertEqual(pack_request(**{name:1<<bit}),1<<(shift+bit))
                for value in [-1,1<<width,True,1.0]:
                    with self.assertRaisesRegex(ValueError,'QUIESCING_REQUEST_PACK_RANGE_'+name):pack_request(**{name:value})
            with self.assertRaisesRegex(ValueError,'QUIESCING_REQUEST_PACK_FIELD'):pack_request(unknown=0)

    def test_only_cpu_request_changes_reset_receiver_kind(self):
        from check_application_reset import persistent_reset_children
        for click in (False,True):
            m,_,_,_,_=self.fixture(click);prefix='Click' if click else 'FourPhase'
            m['design']['endpoints']=[dict(id='native_application_reset')]
            children=m['design']['children']
            children.append(dict(id='admission_grant_bridge',contract=dict(module=prefix+'QuiescingToDecoupled')))
            children.extend(dict(id='completion_'+n+'_bridge',contract=dict(module='DecoupledTo'+prefix+'Quiescing'))
                            for n in ('plan','telemetry','housekeeping'))
            result=persistent_reset_children(m)
            self.assertEqual(result['request_bridge'],prefix+'QuiescingReceipt')
            self.assertEqual(result['admission_grant_bridge'],prefix+'QuiescingToDecoupled')
            for identity,replacement in [('request_bridge',prefix+'QuiescingToDecoupled'),
                ('admission_grant_bridge',prefix+'QuiescingReceipt')]:
                node=next(c['contract'] for c in children if c['id']==identity);before=node['module'];node['module']=replacement
                with self.assertRaisesRegex(ValueError,'SOC_PERSISTENT_RESET_OWNER'):persistent_reset_children(m)
                node['module']=before

    def test_every_schema_field_scope_and_source_is_checked(self):
        for click in (False,True):
            m,s,_,path,h=self.fixture(click)
            nodes=[m['design']['children'][0]['contract'],m['design']['children'][0]['contract']['children'][0]['contract'],
                   m['design']['children'][1]['contract'],m['design']['children'][2]['contract']]
            # Independent exact diagnostics, one mutation at a time.
            for node in nodes:
                for channel in node['channels']:
                    for field in channel['layout']:
                        for key,value in [('lsb',field['lsb']+1),('width',field['width']+1),('signed',True),('source','~|Wrong>bits')]:
                            before=field[key];field[key]=value
                            with self.assertRaisesRegex(ValueError,'QUIESCING_REQUEST_LAYOUT_'+channel['id']):native_request_source(m,s,h)
                            field[key]=before
                    for key,value in [('protocol','wrong'),('role','wrong'),('reset_domain','wrong')]:
                        before=channel[key];channel[key]=value
                        with self.assertRaisesRegex(ValueError,'QUIESCING_REQUEST_CHANNEL_CONTRACT_'+channel['id']):native_request_source(m,s,h)
                        channel[key]=before
                    for key in ('request','acknowledge','valid','ready','clock'):
                        if key not in channel:continue
                        before=channel[key];channel[key]='wrong_endpoint'
                        with self.assertRaisesRegex(ValueError,'QUIESCING_REQUEST_PHASE_ENDPOINT_'+channel['id']+'_'+key):native_request_source(m,s,h)
                        channel[key]=before
                for key,value in [('module','Wrong'),('rtl_path','Wrong'),('reset_domain','Wrong')]:
                    before=node[key];node[key]=value
                    with self.assertRaisesRegex(ValueError,'QUIESCING_REQUEST_OWNER_'):native_request_source(m,s,h)
                    node[key]=before
            for node in nodes:
                scope=s[node['rtl_path']]
                original=scope['model'];scope['model']='Wrong'
                with self.assertRaisesRegex(ValueError,'QUIESCING_REQUEST_SCOPE_'):native_request_source(m,s,h)
                scope['model']=original
                for name,p in scope['ports'].items():
                    for key,value in [('width',p['width']+1),('direction','wrong')]:
                        before=p[key];p[key]=value
                        with self.assertRaisesRegex(ValueError,'QUIESCING_REQUEST_PORT_|QUIESCING_REQUEST_PHASE_PORT_|QUIESCING_REQUEST_RECEIPT_PORTS'):native_request_source(m,s,h)
                        p[key]=before
            payload=nodes[1]['primitives'][0]
            for key,value in [('model','Wrong'),('rtl_path','Wrong'),('reset','wrong'),('reset_domain','wrong'),('parameters',dict(WIDTH='69'))]:
                before=payload[key];payload[key]=value
                with self.assertRaisesRegex(ValueError,'QUIESCING_REQUEST_NATIVE_STORAGE'):native_request_source(m,s,h)
                payload[key]=before
            compiled=s[path.rsplit('.',1)[0]]
            for key,value in [('model','Wrong'),('parameters',dict(WIDTH='69')),('ports',{})]:
                before=compiled[key];compiled[key]=value
                with self.assertRaisesRegex(ValueError,'QUIESCING_REQUEST_NATIVE_STORAGE'):native_request_source(m,s,h)
                compiled[key]=before
            for replacement in ['',h+h]:
                with self.assertRaisesRegex(ValueError,'QUIESCING_REQUEST_CATALOGUED_FORCE'):native_request_source(m,s,replacement)
            receipt=nodes[3];scope=s[receipt['rtl_path']]
            scope['registers']['data_address']=32
            with self.assertRaisesRegex(ValueError,'QUIESCING_REQUEST_RECEIPT_STORAGE'):native_request_source(m,s,h)

    def test_executed_alias_checks_reject_wire_and_invalid_mask_faults(self):
        for click in (False,True):
            m,s,i,path,h=self.fixture(click);top=m['top']
            fields=[('mask',3,0,4),('data',35,4,32),('address',67,36,32),('operation',69,68,2)]
            fabric='module Fabric(input [69:0] bits);\nwire request_req=0,request_ack=0,serviceRequest_req=0,serviceRequest_ack=0;\n'
            for pin in ['request','serviceRequest']:
                fabric+='\n'.join(f'wire [{w-1}:0] {pin}_bits_{f}=bits[{hi}:{lo}];' for f,hi,lo,w in fields)+'\n'
            fabric+='endmodule\n'
            rtl=request_fixture_rtl()+fabric+f'''module {top};
NativeCore ca_child_core();
Request ca_child_request_bridge(ca_child_core.ca_child_address.ca_primitive_payload.q);
Fabric ca_child_transactions(ca_child_core.ca_child_address.ca_primitive_payload.q);
endmodule
'''
            source=f'''module ContractProbe; timeunit 1ns; timeprecision 1ps;
integer bitIndex,validState;
task check; begin end endtask
initial begin
{h}
for(validState=0;validState<4;validState=validState+1) begin
  force {top}.ca_child_request_bridge.state=validState;
  for(bitIndex=0;bitIndex<70;bitIndex=bitIndex+1) begin
    force {path}=70'b1<<bitIndex; #1; check;
    force {path}=~(70'b1<<bitIndex); #1; check;
  end
end
$display("REQUEST_PROBE_PASS"); $finish;
end endmodule
'''
            probe=request_receipt_probe(source,m,s)
            self.assertEqual(probe.count('QUIESCING_REQUEST_BINDING:'),32)
            for before,after,diagnostic in [(None,None,'REQUEST_PROBE_PASS'),
                ('out_valid ? in_bits_data : 32\'b0','in_bits_data','QUIESCING_REQUEST_BINDING:'+top+'.ca_child_request_bridge.out_bits_data'),
                ('out_bits_address=ca_primitive_payload.q[67:36]','out_bits_address=ca_primitive_payload.q[66:35]',
                 'QUIESCING_REQUEST_BINDING:'+top+'.ca_child_core.ca_child_address.out_bits_address'),
                ('wire out_req=0,out_ack=0;','wire out_req=1,out_ack=0;',
                 'QUIESCING_REQUEST_BINDING:'+top+'.ca_child_core.ca_child_address.out_req')]:
                model=rtl if before is None else rtl.replace(before,after)
                with tempfile.TemporaryDirectory(prefix='c1e-native-request-') as folder:
                    p=Path(folder);(p/'test.sv').write_text(model+probe)
                    compile=subprocess.run(['iverilog','-g2012','-s',top,'-s','ContractProbe','-o','sim.vvp','test.sv'],cwd=p,capture_output=True,text=True,timeout=30)
                    self.assertEqual(compile.returncode,0,compile.stderr)
                    run=subprocess.run(['vvp','sim.vvp'],cwd=p,capture_output=True,text=True,timeout=30)
                    self.assertEqual(run.returncode==0,before is None,run.stdout+run.stderr)
                    self.assertIn(diagnostic,run.stdout)

if __name__=='__main__':unittest.main()

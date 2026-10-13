# SPDX-License-Identifier: Apache-2.0
"""Independent packing, source-identity and no-payload-register controls."""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from check_service_reply_receipt import native_reply_source, pack_reply, receipt_bindings, service_reply_probe


# Schema order is specified independently here, from low bit to high bit.
FIELDS = {
    'control': [('memory.error',1),('memory.data',32),('hostWake',1),('period',32),
        ('periodUpdate',1),('programWrite',1),('state.appIndex',6),('state.sampleValue',32),
        ('state.sampleIndex',4),('state.selector',24),('state.loaderWord',32),('state.loaderPending',1),
        ('state.crc',32),('state.expectedCrc',32),('state.imageId',32),('state.received',32),
        ('state.entry',32),('state.imageLength',32),('state.lastError',8),('state.started',1),
        ('state.locked',1),('state.programmed',1),('state.mode',3),('kind',3)],
    'housekeeping': [('cpuCompletion',1),('resetApplication',1),('kick',1),('startAdc',1),
        ('leaseExpired',1),('due',1),('elapsed[0]',32),('elapsed[1]',32),('elapsed[2]',32),
        ('single',1),('tick',1),('timeValid',1),('state.requested',1),('state.countdown',32),
        ('state.periodPending',1),('state.nextPeriod',32),('state.period',32),('state.wakeMask',32),
        ('state.lease',32),('state.armed',1),('state.deadline',32),('state.consumed',32),
        ('state.boardNow',32),('state.now',32),('recovery',1)],
    'telemetry': [('state.samples[0].fault',1),('state.samples[0].never',1),
        ('state.samples[0].sequence',32),('state.samples[0].age',32),('state.samples[0].calibrated',1),
        ('state.samples[0].valid',1),('state.samples[0].value',32),('state.pending',6),
        ('state.enable',32),('state.output',32),('kind',2),('recovery',1)],
    'supervisor': [('sample.fault',1),('sample.never',1),('sample.sequence',32),('sample.age',32),
        ('sample.calibrated',1),('sample.valid',1),('sample.value',32),
        ('observed[0]',1),('observed[1]',1),('observed[2]',1),('observed[3]',1),
        ('counts[0]',32),('counts[1]',32),('counts[2]',32),('counts[3]',32),
        ('waitShutdown',1),('waitOff',1),('waitRun',1),('qualified',1),('shutdownAt',32),
        ('offAt',32),('timeouts',2),('fault',3),('mode',2),('sensingFault',1)]}


def add_native_reply_fixture(manifest, scopes, inventories, owner):
    top=manifest['top'];click=top=='ClickSoc';prefix='Click' if click else 'FourPhase'
    path=top+'.ca_child_'+owner;module=prefix+owner.title()
    offset=0;fields=[]
    for field,width in FIELDS[owner]:
        fields.append(dict(field='bits.'+field,lsb=offset,width=width,signed=False,
                           source=f'~|{module}>reply.bits.{field}'))
        offset+=width
    q=dict(name='q',width=offset,direction='output')
    model='ChiselAsyncEventRegister_v1' if click else 'ChiselAsyncClosingLatch_v1'
    params=dict(WIDTH=str(offset),DELAY_FS='1000000')
    if click:params['RESET_VALUE']='0'
    target=path+'.ca_child_update.ca_primitive_payload'
    primitive=dict(id='payload',rtl_path=target,model=model,parameters=params,ports=[q],reset='reset',reset_domain='root')
    update=dict(module='ClickStage' if click else 'FourPhaseStage',rtl_path=path+'.ca_child_update',reset_domain='root',primitives=[primitive])
    native=dict(module=module,rtl_path=path,reset_domain='root',channels=[dict(id='reply',role='output',
        protocol='two-phase-bundled-v1' if click else 'four-phase-bundled-v1',layout=fields)],
        children=[dict(id='update',contract=update)])
    manifest['design']['children'].append(dict(id=owner,contract=native))
    scopes[target]=dict(model=model,parameters=params,ports=dict(q=q))
    inventories[target]=dict(q=offset)
    return native


def fixture(top,owner):
    manifest=dict(top=top,design=dict(children=[]));scopes={};inventories={}
    native=add_native_reply_fixture(manifest,scopes,inventories,owner)
    click=top=='ClickSoc';ack='ack' if click else 'acknowledge'
    path=top+'.ca_child_'+owner+'_reply_bridge';module=('Click' if click else 'FourPhase')+'ServiceReplyReceipt'
    width=sum(w for _,w in FIELDS[owner])
    channels=[]
    for name in ('in','out'):
        fields=copy.deepcopy(native['channels'][0]['layout'])
        for field in fields:field['source']=f"~|{module}>{name}.{field['field']}"
        channels.append(dict(id=name,layout=fields,protocol='decoupled-v1' if name=='out' else
            ('two-phase-bundled-v1' if click else 'four-phase-bundled-v1'),role='input' if name=='in' else 'output'))
    endpoints=dict(local_reset=(1,'localReset'),request_sync=(1,'request_stages[1]'),state=(2,'state'),
        acknowledge=(1,ack),reset=(1,'reset'),in_request=(1,'in.req'),in_data=(width,'in.bits'),
        in_acknowledge=(1,'in.ack'),out_valid=(1,'out.valid'),out_data=(width,'out.bits'),
        out_ready=(1,'out.ready'),out_clock=(1,'clock'))
    receipt=dict(module=module,rtl_path=path,reset_domain='root',capacity=1,primitives=[],children=[],timing=[],channels=channels,
        endpoints=[dict(id=n,width=w,source=f'~|{module}>{signal}',rtl_path=path+'.ep_'+n) for n,(w,signal) in endpoints.items()])
    manifest['design']['children'].append(dict(id=owner+'_reply_bridge',contract=receipt))
    scopes[path]=dict(registers=dict(localReset_release_0=1,localReset_release_1=1,
        request_stages_0=1,request_stages_1=1,state=2,**{ack:1}),memories={})
    ports={n:dict(name=n,width=1,direction=d) for n,d in [('reset','input'),('clock','input'),('in_req','input'),('in_ack','output'),('out_ready','input'),('out_valid','output')]}
    for field,width in FIELDS[owner]:
        field=field.replace('.', '_').replace('[', '_').replace(']', '')
        for side,direction in [('in','input'),('out','output')]:
            name=side+'_bits_'+field;ports[name]=dict(name=name,width=width,direction=direction)
    scopes[path].update(model=module,ports=ports)
    header=''.join(f"force {p}.{n} = {w}'h0;\n" for p,rs in inventories.items() for n,w in rs.items())
    return manifest,scopes,header


class ServiceReplyReceiptTest(unittest.TestCase):
    def test_executed_alias_probe_rejects_wrong_live_native_data(self):
        for top in ('FourPhaseSoc','ClickSoc'):
            manifest,scopes,_=fixture(top,'control')
            ack='ack' if top=='ClickSoc' else 'acknowledge'
            # No payload register in Receipt. The sole q belongs to Native.Update.
            native=[];receipt=[];offset=0
            for field,width in FIELDS['control']:
                name=field.replace('.','_').replace('[','_').replace(']','')
                part=f'[{offset+width-1}:{offset}]'
                native.append(f'wire [{width-1}:0] reply_bits_{name}=ca_child_update.ca_primitive_payload.q{part};')
                receipt.extend([f'wire [{width-1}:0] in_bits_{name}=payload{part};',
                                f'wire [{width-1}:0] out_bits_{name}=in_bits_{name};'])
                offset+=width
            rtl='module Payload; reg [375:0] q=0; endmodule\nmodule Update; Payload ca_primitive_payload(); endmodule\n'
            rtl+='module Native; Update ca_child_update();\n'+'\n'.join(native)+'\nendmodule\n'
            rtl+=f'''module Receipt(input [375:0] payload);
reg localReset_release_1=0, request_stages_1=0, {ack}=0;
reg [1:0] state=2;
wire reset=0, ep_reset=reset, ep_local_reset=localReset_release_1;
wire ep_request_sync=request_stages_1, ep_acknowledge={ack};
wire [1:0] ep_state=state;
wire in_ack={ack}, out_valid=(state==2 && !localReset_release_1);
'''+ '\n'.join(receipt)+'\nendmodule\n'
            rtl+=f'module {top}; Native ca_child_control(); Receipt ca_child_control_reply_bridge(.payload(ca_child_control.ca_child_update.ca_primitive_payload.q)); endmodule\n'
            stimulus=f'''module ContractProbe;
task check; begin end endtask
integer i;
initial begin
for(i=0;i<376;i=i+1) begin
  {top}.ca_child_control.ca_child_update.ca_primitive_payload.q=376'b1<<i; #1;check;
  {top}.ca_child_control.ca_child_update.ca_primitive_payload.q=~(376'b1<<i); #1;check;
end
$display("SERVICE_REPLY_ALIAS_PASS");$finish;
end endmodule
'''
            probe=service_reply_probe(stimulus,manifest,scopes)
            self.assertEqual(probe.count('SERVICE_REPLY_BINDING:'),3*len(FIELDS['control'])+7)
            with tempfile.TemporaryDirectory(prefix='service-reply-alias-') as folder:
                path=Path(folder)
                for broken in (False,True):
                    model=rtl.replace('out_bits_memory_data=in_bits_memory_data;',
                                      'out_bits_memory_data=in_bits_memory_data ^ 32\'h1;') if broken else rtl
                    (path/'test.sv').write_text(model+probe)
                    built=subprocess.run(['iverilog','-g2012','-s',top,'-s','ContractProbe','-o','sim.vvp','test.sv'],
                                         cwd=path,capture_output=True,text=True,timeout=30)
                    self.assertEqual(built.returncode,0,built.stderr)
                    ran=subprocess.run(['vvp','sim.vvp'],cwd=path,capture_output=True,text=True,timeout=30)
                    self.assertEqual(ran.returncode==0,not broken,ran.stdout)
                    self.assertIn('SERVICE_REPLY_BINDING:' if broken else 'SERVICE_REPLY_ALIAS_PASS',ran.stdout)

    def test_actual_storage_and_independent_known_bit_positions(self):
        for top in ('FourPhaseSoc','ClickSoc'):
            for owner in FIELDS:
                m,s,h=fixture(top,owner)
                native=native_reply_source(m,s,h,owner)
                self.assertEqual(native['width'],dict(control=376,housekeeping=397,telemetry=173,supervisor=308)[owner])
                self.assertTrue(receipt_bindings(m,s))
                if owner=='control':
                    self.assertEqual(pack_reply(native,{'kind':4,'programWrite':1,'state.received':0x89abcdef,
                        'state.loaderWord':0x12345678,'memory.data':0xf00dd00d,'memory.error':1}),
                        (4<<373)|(1<<67)|(0x89abcdef<<263)|(0x12345678<<134)|(0xf00dd00d<<1)|1)
                if owner=='telemetry':self.assertEqual(pack_reply(native,{'kind':1}),1<<170)
                if owner=='housekeeping':self.assertEqual(pack_reply(native,{'cpuCompletion':1}),1)

    def test_wrong_storage_origin_layout_model_reset_or_header_rejected(self):
        for top in ('FourPhaseSoc','ClickSoc'):
            m,s,h=fixture(top,'control')
            for mutate in (
                lambda n:n.update(reset_domain='application'),
                lambda n:n['channels'][0]['layout'][0].update(lsb=1),
                lambda n:n['channels'][0]['layout'][1].update(width=31),
                lambda n:n['channels'][0]['layout'][0].update(signed=True),
                lambda n:n['children'][0]['contract'].update(module='FourPhaseToDecoupled'),
                lambda n:n['children'][0]['contract']['primitives'][0].update(model='ChiselAsyncControlGate_v1'),
                lambda n:n['children'][0]['contract']['primitives'][0].update(reset_domain='application'),
                lambda n:n['children'][0]['contract']['primitives'][0]['parameters'].update(DELAY_FS='2000000')):
                bad=copy.deepcopy(m);mutate(bad['design']['children'][0]['contract'])
                with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_'):native_reply_source(bad,s,h,'control')
            with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_STORAGE_FORCE'):native_reply_source(m,s,'','control')
            native=native_reply_source(m,s,h,'control')
            for values in ({'kind':8},{'kind':-1},{'unknown':1}):
                with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_PACK'):pack_reply(native,values)

    def test_receiver_payload_storage_and_domain_protocol_mutations_rejected(self):
        for top in ('FourPhaseSoc','ClickSoc'):
            for owner in FIELDS:
                m,s,h=fixture(top,owner)
                for mutate in (
                    lambda n:n.update(reset_domain='application'),
                    lambda n:n.update(module='ClickToDecoupled'),
                    lambda n:n['channels'][0].update(protocol='four-phase-bundled-v1' if top=='ClickSoc' else 'two-phase-bundled-v1'),
                    lambda n:n['channels'][1]['layout'][0].update(lsb=1),
                    lambda n:n['endpoints'][0].update(source='~|bad>reset')):
                    bad=copy.deepcopy(m);mutate(bad['design']['children'][1]['contract'])
                    with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_'):receipt_bindings(bad,s)
                bad=copy.deepcopy(s);bad[top+'.ca_child_'+owner+'_reply_bridge']['registers']['data']=sum(w for _,w in FIELDS[owner])
                with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_REGISTER_INVENTORY'):receipt_bindings(m,bad)


if __name__=='__main__':unittest.main()

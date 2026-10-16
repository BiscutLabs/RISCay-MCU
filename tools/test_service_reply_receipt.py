# SPDX-License-Identifier: Apache-2.0
"""Independent packing, source-identity and no-payload-register controls."""
import copy
from pathlib import Path
import subprocess
import tempfile
import unittest
from check_service_reply_receipt import (native_reply_source, pack_reply, receipt_bindings, service_reply_probe,
    control_widths, control_layout, validate_control_token)


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


# Independently enumerated (count, entry, state, token, reply) widths.
CAPACITIES = {4:(3,2,217,249,288), 12:(4,4,221,253,292), 16:(5,4,223,255,294),
              1024:(11,10,241,273,312), 1028:(11,11,242,274,313),
              2048:(12,11,244,276,315), 3072:(12,12,245,277,316)}


def fixture_fields(owner, program_bytes=2048):
    if owner != 'control': return FIELDS[owner]
    count, entry, _, _, _ = CAPACITIES[program_bytes]
    widths = {'state.received':count, 'state.imageLength':count, 'state.entry':entry}
    return [(name, widths.get(name, width)) for name, width in FIELDS[owner]]


def add_control_token_fixture(node, program_bytes=2048):
    state = [(name, width) for name, width in fixture_fields('control',program_bytes) if name.startswith('state.')]
    node['module'] = 'TokenStorage'
    node['channels'] = []
    for identity in ('in','out'):
        offset = 0; fields = []
        for name,width in [('pendingCrc',32)] + state:
            fields.append(dict(field='bits.'+name,lsb=offset,width=width,signed=False,
                source=f"~|TokenStorage>{identity}.bits.{name}"))
            offset += width
        assert offset == CAPACITIES[program_bytes][3]
        node['channels'].append(dict(id=identity,layout=fields))


def add_native_reply_fixture(manifest, scopes, inventories, owner, program_bytes=2048):
    top=manifest['top'];click=top=='ClickSoc';prefix='Click' if click else 'FourPhase'
    path=top+'.ca_child_'+owner;module=prefix+owner.title()
    offset=0;fields=[]
    for field,width in fixture_fields(owner,program_bytes):
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


def fixture(top,owner,program_bytes=2048):
    manifest=dict(top=top,design=dict(children=[]));scopes={};inventories={}
    native=add_native_reply_fixture(manifest,scopes,inventories,owner,program_bytes)
    click=top=='ClickSoc';ack='ack' if click else 'acknowledge'
    path=top+'.ca_child_'+owner+'_reply_bridge';module=('Click' if click else 'FourPhase')+'ServiceReplyReceipt'
    width=sum(w for _,w in fixture_fields(owner,program_bytes))
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
    for field,width in fixture_fields(owner,program_bytes):
        field=field.replace('.', '_').replace('[', '_').replace(']', '')
        for side,direction in [('in','input'),('out','output')]:
            name=side+'_bits_'+field;ports[name]=dict(name=name,width=width,direction=direction)
    scopes[path].update(model=module,ports=ports)
    header=''.join(f"force {p}.{n} = {w}'h0;\n" for p,rs in inventories.items() for n,w in rs.items())
    return manifest,scopes,header


class ServiceReplyReceiptTest(unittest.TestCase):
    def test_capacity_bound_layout_offsets_and_all_internal_lanes(self):
        # Literal reply offsets: received, entry, imageLength, lastError, kind.
        offsets={4:(263,266,268,271,285),12:(263,267,271,275,289),16:(263,268,272,277,291),
                 1024:(263,274,284,295,309),1028:(263,274,285,296,310),
                 2048:(263,275,286,298,312),3072:(263,275,287,299,313)}
        for top in ('FourPhaseSoc','ClickSoc'):
            for capacity,(count,entry,_,token,reply) in CAPACITIES.items():
                with self.subTest(top=top,capacity=capacity):
                    m,s,h=fixture(top,'control',capacity)
                    source=native_reply_source(m,s,h,'control',capacity)
                    self.assertEqual(source['width'],reply)
                    self.assertEqual(control_widths(capacity),(count,entry))
                    fields=('state.received','state.entry','state.imageLength','state.lastError','kind')
                    self.assertEqual(tuple(source['fields'][f][0] for f in fields),offsets[capacity])
                    self.assertTrue(receipt_bindings(m,s,capacity))
                    token_node={};add_control_token_fixture(token_node,capacity)
                    self.assertEqual(validate_control_token(token_node,capacity),token)
                    for field,width in (('state.received',count),('state.imageLength',count),('state.entry',entry)):
                        offset=source['fields'][field][0]
                        for bit in range(width):
                            self.assertEqual(pack_reply(source,{field:1<<bit}),1<<(offset+bit))
                        for invalid in (-1,1<<width):
                            with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_PACK_RANGE_'):
                                pack_reply(source,{field:invalid})
                    self.assertEqual(pack_reply(source,{'state.received':capacity}),capacity<<263)

    def test_control_capacity_and_changed_schema_fail_closed(self):
        for capacity in (None,True,0,-4,3,4.0,'4',0x80000000):
            with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_CONTROL_CAPACITY'):
                control_layout(capacity)
        for top in ('FourPhaseSoc','ClickSoc'):
            m,s,h=fixture(top,'control',2048)
            with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_CONTROL_CAPACITY'):
                native_reply_source(m,s,h,'control')
            with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_SCHEMA_control'):
                native_reply_source(m,s,h,'control',1024)
            for field in ('state.received','state.entry','state.imageLength'):
                for key,delta in (('width',-1),('lsb',1)):
                    bad=copy.deepcopy(m)
                    item=next(f for f in bad['design']['children'][0]['contract']['channels'][0]['layout']
                              if f['field']=='bits.'+field)
                    item[key]+=delta
                    with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_SCHEMA_control'):
                        native_reply_source(bad,s,h,'control',2048)
            node={};add_control_token_fixture(node,2048)
            for channel in (0,1):
                for field in ('bits.state.received','bits.state.entry','bits.state.imageLength'):
                    bad=copy.deepcopy(node)
                    next(f for f in bad['channels'][channel]['layout'] if f['field']==field)['width']-=1
                    with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_CONTROL_TOKEN_SCHEMA'):
                        validate_control_token(bad,2048)

    def test_executed_alias_probe_rejects_wrong_live_native_data(self):
        for top in ('FourPhaseSoc','ClickSoc'):
            manifest,scopes,_=fixture(top,'control')
            ack='ack' if top=='ClickSoc' else 'acknowledge'
            # No payload register in Receipt. The sole q belongs to Native.Update.
            native=[];receipt=[];offset=0
            for field,width in fixture_fields('control'):
                name=field.replace('.','_').replace('[','_').replace(']','')
                part=f'[{offset+width-1}:{offset}]'
                native.append(f'wire [{width-1}:0] reply_bits_{name}=ca_child_update.ca_primitive_payload.q{part};')
                receipt.extend([f'wire [{width-1}:0] in_bits_{name}=payload{part};',
                                f'wire [{width-1}:0] out_bits_{name}=in_bits_{name};'])
                offset+=width
            rtl='module Payload; reg [314:0] q=0; endmodule\nmodule Update; Payload ca_primitive_payload(); endmodule\n'
            rtl+='module Native; Update ca_child_update();\n'+'\n'.join(native)+'\nendmodule\n'
            rtl+=f'''module Receipt(input [314:0] payload);
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
for(i=0;i<315;i=i+1) begin
  {top}.ca_child_control.ca_child_update.ca_primitive_payload.q=315'b1<<i; #1;check;
  {top}.ca_child_control.ca_child_update.ca_primitive_payload.q=~(315'b1<<i); #1;check;
end
$display("SERVICE_REPLY_ALIAS_PASS");$finish;
end endmodule
'''
            probe=service_reply_probe(stimulus,manifest,scopes,2048)
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
                native=native_reply_source(m,s,h,owner,2048)
                self.assertEqual(native['width'],dict(control=315,housekeeping=397,telemetry=173,supervisor=308)[owner])
                self.assertTrue(receipt_bindings(m,s,2048))
                if owner=='control':
                    self.assertEqual(pack_reply(native,{'kind':4,'programWrite':1,'state.received':0xabc,
                        'state.loaderWord':0x12345678,'memory.data':0xf00dd00d,'memory.error':1}),
                        (4<<312)|(1<<67)|(0xabc<<263)|(0x12345678<<134)|(0xf00dd00d<<1)|1)
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
                with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_'):native_reply_source(bad,s,h,'control',2048)
            with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_STORAGE_FORCE'):native_reply_source(m,s,'','control',2048)
            native=native_reply_source(m,s,h,'control',2048)
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
                    with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_'):receipt_bindings(bad,s,2048)
                bad=copy.deepcopy(s);bad[top+'.ca_child_'+owner+'_reply_bridge']['registers']['data']=sum(w for _,w in FIELDS[owner])
                with self.assertRaisesRegex(ValueError,'SERVICE_REPLY_REGISTER_INVENTORY'):receipt_bindings(m,bad,2048)


if __name__=='__main__':unittest.main()

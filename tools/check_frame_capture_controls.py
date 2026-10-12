# SPDX-License-Identifier: Apache-2.0
"""Qualify native I2C frame delivery through retained banks and command capture.

Original composed testbenches keep their assertions. A separate supplemental
campaign drives the native publication input, never its retained output, to
exercise every source bit, four physical banks and two logical descriptors.
Checks use 1 fs time, actual capture pins, A/D identity and captured command Q.
The synthetic D-epoch campaign separately drives the actual epoch source register.
Clocked descriptor/context selection uses ideal zero-delay flops: physical hold
at that synchronous mux/capture boundary is not claimed by this campaign.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from check_i2c_wiring_controls import hashes
from check_program_return_fatals import fatal_sites, classify_fatal
from check_admission_controls import replace_pin
from check_frame_integration import (_mailbox_policy, child, pins, always_blocks, driver,
    statement_tree, projected_tree, writer_inventory, initial_policy)
from check_frame_receipt import actual_receipt_rtl
from check_frame_store import validate_frame_store

PREFIX = 'FRAME_CAPTURE'
PROFILES = ('original', 'minimum', 'data-slow-control-fast', 'data-fast-control-slow',
            'publisher-fast-banks-slow', 'publisher-slow-banks-fast')
FIXTURES = {'reset3200000','reset20000000','slots3200000','slots20000000','stored20000000',
            'reuse20000000','queuedepoch20000000','priority20000000'}
LEAVES = [('frame_length', 6), ('frame_overflow', 1)] + [
    ('frame_bytes_' + str(i), 8) for i in range(33)] + [('resetActive', 1), ('programBusy', 1)]
DESCRIPTOR = [('bank', 2), ('resetActive', 1), ('programBusy', 1)]
PERIODS_NS = tuple(sorted({50,312.5,1000,1000000} | {
    round(edge+epsilon,3) for edge in (55.5,57,57.5,60,111,114,115,120,125)
    for epsilon in (-.002,0,.002)}))


def require(value, message):
    if not value:
        raise ValueError(PREFIX + '_' + message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean(text):
    return re.sub(r'//[^\n]*|/\*.*?\*/', '', text, flags=re.S)


def nodes(node):
    yield node
    for child in node.get('children', []):
        yield from nodes(child['contract'])


def packed(prefix):
    # Chisel Vec.asUInt has byte zero at the low end; the two context bits
    # follow the frame. This ordering is independent of SV declaration order.
    ordered = ['frame_length', 'frame_overflow'] + [
        'frame_bytes_' + str(i) for i in reversed(range(33))] + ['resetActive', 'programBusy']
    return '{' + ','.join(prefix + name for name in ordered) + '}'


def qualify(expression, scope='Testbench.dut'):
    # Expressions are captured from emitted RTL, not executable Python.
    return re.sub(r"(?<![\w'])\b[A-Za-z_][A-Za-z_0-9]*\b", lambda m: scope + '.' + m[0], expression)


def actual_model(source, parent, node):
    """Resolve deduplicated emitted models from the actual parent instance."""
    instance=node['rtl_path'].rsplit('.',1)[1]
    found=re.findall(r'\b(\w+)\s+'+re.escape(instance)+r'\s*\(',clean(parent))
    require(len(found)==1,'INSTANCE_MODEL:'+instance)
    require(re.sub(r'_\d+$','',found[0])==re.sub(r'_\d+$','',node['module']),'DEDUP_MODEL:'+instance)
    rtl=(source/(found[0]+'.sv')).read_text(encoding='utf-8')
    return found[0],rtl,pins(parent,instance,found[0])


def command_capture_policy(rtl, click):
    """Close every final frame/context register's reset and sole dynamic load."""
    text=clean(rtl)
    fields=[(name if name!='resetActive' else 'cpuResetActive',width) for name,width in LEAVES]
    # The complete enabled load block must capture all command fields together.
    load=r'if\s*\(_in_ready_T\s*&\s*_GEN\)\s*begin'
    loads=list(re.finditer(load+r'(.*?)\bend\b',text,re.S))
    require(len(loads)==1,'COMMAND_CAPTURE_ENABLE')
    owners=[block for block in always_blocks(rtl) if re.search(r'\bdata_frame_length\s*<=',block)]
    require(len(owners)==1 and re.match(r'always\s*@\(posedge\s+clock\s+or\s+posedge\s+localReset_release_1\)',owners[0]),
            'COMMAND_CAPTURE_CLOCK_RESET')
    owner=owners[0]
    names={'data_'+name for name,_ in fields}
    expected='begin if(localReset_release_1) begin '+''.join(f"data_{name}<={width}'h0;" for name,width in fields)
    expected+='end else begin if(_in_ready_T & _GEN) begin '+''.join('data_'+name+'<=in_bits_'+name+';' for name,_ in fields)+'end end end'
    body=re.match(r'always\s*@\([^)]*\)\s*(.*)',owner,re.S)[1]
    require(projected_tree(statement_tree(body),names)==projected_tree(statement_tree(expected),names),'COMMAND_CAPTURE_RESET_LOAD_BRANCH')
    forbidden,_,partial=writer_inventory(rtl)
    require(not forbidden and not names.intersection(partial),'COMMAND_CAPTURE_EXTRA_WRITER')
    for name,width in fields:
        q='data_'+name
        declarations=re.findall(r'\breg\s+(\[\d+:0\]\s+)?'+q+r'\s*;',text)
        require(len(declarations)==1 and (declarations[0].strip() or '[0:0]')==f'[{width-1}:0]','COMMAND_REGISTER:'+q)
        assignments=re.findall(r'\b'+q+r'\s*<=\s*([^;]+);',text)
        require([re.sub(r'\s+','',s) for s in assignments]==[f"{width}'h0",'in_bits_'+name],'COMMAND_WRITERS:'+q)
        require(len(re.findall(r'\b'+q+r'\s*<=',owner))==2,'COMMAND_COMMON_CLOCK_RESET:'+q)
        require(len(re.findall(r'\b'+q+r'\s*<=\s*in_bits_'+name+r'\s*;',loads[0][1]))==1,'COMMAND_CAPTURE:'+q)
    blocks=re.findall(r'always\s*@\(posedge\s+clock\s+or\s+posedge\s+(\w+)\)\s*begin',text)
    require('localReset_release_1' in blocks,'COMMAND_POR_CLOCK')
    return fields


def fixture_masks_policy(rtl, target_pins, command_pins):
    """Only these symmetric test stalls may modify production handshake wiring."""
    text=clean(rtl)
    require(target_pins['frameAcceptEnable']=='enabled&~holdFrame','FIXTURE_A_ENABLE')
    require(command_pins['in_valid']=='fabric_io_controlCommand_valid&~holdHostCommands','FIXTURE_COMMAND_VALID')
    driver(rtl,'fabric_io_controlCommand_ready','_ca_child_control_command_bridge_in_ready & ~holdHostCommands')
    driver(rtl,'fabric__io_i2c_heads_0_ready_T','enabled & fabric_hostFrames_io_deq_ready')
    for index in range(4):
        ready=f'ca_child_i2c_host_heads_{index}_ready'
        require(target_pins[f'host_heads_{index}_ready']==ready,'FIXTURE_HEAD_READY_PIN')
        driver(rtl,f'fabric_io_i2c_heads_{index}_valid',f'_ca_child_i2c_host_heads_{index}_valid & ~holdSelectedHead')
        select=f"fabric_hostFrames_first_bank == 2'h{index}" if index<3 else '(&fabric_hostFrames_first_bank)'
        driver(rtl,ready,'fabric__io_i2c_heads_0_ready_T & fabric_hostFrames_io_deq_valid & '+select+' & ~holdSelectedHead')
    require(len(re.findall(r'\bholdFrame\b',text))==2,'FIXTURE_A_EXTRA_MASK')
    require(len(re.findall(r'\bholdSelectedHead\b',text))==9,'FIXTURE_HEAD_EXTRA_MASK')
    require(len(re.findall(r'\bholdHostCommands\b',text))==3,'FIXTURE_COMMAND_EXTRA_MASK')


def bindings(source):
    """Bind controls to the emitted instance and actual inlined register RHS."""
    source = Path(source)
    manifest = json.loads((source / 'contract.json').read_text(encoding='utf-8'))['manifest']
    top = manifest['top']
    require(top in ('BdFrameAdmissionFixture', 'ClickFrameAdmissionFixture'), 'TOP')
    variant = 'click' if top.startswith('Click') else 'bd'
    target=child(manifest['design'],'i2c'); native=child(target,'native')
    publisher=child(native,'publication'); receipt=child(target,'frame_bridge')
    store=child(target,'frame_store'); command=child(manifest['design'],'control_command_bridge')
    heads=[child(target,f'frame_head{i}_bridge') for i in range(4)]
    primitive = [p for p in publisher['primitives'] if p['id'] == 'frame_payload']
    require(len(primitive) == 1 and primitive[0]['parameters']['WIDTH'] == '337', 'SOURCE_WIDTH')
    path = lambda p: 'Testbench.dut.' + p.split('.', 1)[1]
    rtl = clean((source / (top + '.sv')).read_text(encoding='utf-8'))
    assignments = {}
    for slot in ('first', 'second'):
        for leaf, width in DESCRIPTOR:
            name = 'fabric_hostFrames_' + slot + '_' + leaf
            declaration = re.findall(r'\breg\s+(\[\d+:0\]\s+)?' + name + r'\s*;', rtl)
            require(len(declaration) == 1, 'REGISTER:' + name)
            require((declaration[0].strip() or '[0:0]') == '[' + str(width - 1) + ':0]', 'REGISTER_WIDTH:' + name)
            rhs = [re.sub(r'\s+', '', s) for s in re.findall(r'\b' + name + r'\s*<=\s*([^;]+);', rtl)]
            data = [s for s in rhs if not re.fullmatch(r"\d+'h0", s) and not s.startswith('fabric_hostFrames_second_')]
            require(len(data) == (2 if slot == 'first' else 1) and len(set(data)) == 1, 'D_BINDING:' + name)
            assignments[name] = data[0]
    # Each register must occur in the same POR-owned work-clock block. All
    # branch/load semantics are also checked dynamically against count/A/D.
    starts = list(re.finditer(r'always\s*@\(posedge\s+(\w+)\s+or\s+posedge\s+(\w+)\)\s+begin', rtl))
    clocks = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(rtl)
        body = rtl[match.end():end]
        if re.search(r'fabric_hostFrames_first_bank\s*<=', body):
            clocks.append((match[1], match[2]))
    require(len(clocks) == 1 and clocks[0][1] == 'reset', 'MAILBOX_CLOCK_RESET')
    # Export references and ABI are evidence, not optional conveniences.
    for key in ('probe_abi', 'port_abi'):
        abi = manifest[key]
        require(abi['sha256'] == sha(source / abi['file']), 'ABI_HASH:' + key)
    require(sum(w for _, w in LEAVES) == 273, 'DESTINATION_WIDTH')
    frame_d = {leaf: assignments['fabric_hostFrames_first_' + leaf] for leaf, _ in DESCRIPTOR}
    require(all(assignments['fabric_hostFrames_second_' + leaf] == rhs for leaf, rhs in frame_d.items()), 'SLOT_D_IDENTITY')
    _mailbox_policy((source / (top + '.sv')).read_text(encoding='utf-8'), clocks[0][0], frame_d)
    target_model,tr,tp=actual_model(source,rtl,target)
    receipt_model,rr,rp=actual_model(source,tr,receipt)
    for node in [receipt]+heads:
        model,body,ports=actual_model(source,tr,node)
        actual_receipt_rtl(node,source,tr)
        require(ports['clock']=='clock' and ports['reset']=='reset','RECEIPT_CLOCK_RESET')
    store_model,sr,sp=actual_model(source,tr,store)
    validate_frame_store(store,source)
    command_model,cr,cp=actual_model(source,rtl,command)
    require(cp['clock']==clocks[0][0] and cp['reset']=='reset','COMMAND_ACTUAL_CLOCK_RESET')
    require(tp['clock']=='serviceClock' and tp['reset']=='reset','ORIGINAL_RECEIPT_ACTUAL_CLOCK_RESET')
    command_fields=command_capture_policy(cr,variant=='click')
    initial_policy(cr,{'data_'+name:f"{width}'h0" for name,width in command_fields},'localReset_release_1')
    fixture_masks_policy(rtl,tp,cp)
    # Resolve physical bank payload primitives independently of fixture outputs.
    banks=[]
    available_endpoints=[e for e in store['endpoints'] if e['id']=='available' and e['width']==4]
    require(len(available_endpoints)==1,'BANK_AVAILABILITY_ENDPOINT')
    for i,node in enumerate(heads):
        hm,hr,hp=actual_model(source,tr,node)
        owner=store if variant=='click' else child(store,f'storage{i}')
        owner_model=store_model if variant=='click' else actual_model(source,sr,owner)[0]
        found=[p for p in owner['primitives'] if p['id']==(f'payload{i}' if variant=='click' else 'payload')]
        require(len(found)==1 and found[0]['parameters']['WIDTH']=='337','BANK_PAYLOAD:'+str(i))
        cell=found[0]; expected='ChiselAsyncEventRegister_v1' if variant=='click' else 'ChiselAsyncClosingLatch_v1'
        require(cell['model']==expected,'BANK_MODEL:'+str(i))
        for leaf in ('req','ack'):
            require(hp['in_'+leaf]==sp[f'banks_{i}_{leaf}'],'BANK_HEAD_PIN:'+str(i)+':'+leaf)
        banks.append(dict(index=i,node=owner,owner_model=owner_model,cell=cell,path=path(cell['rtl_path']),
                          q=path(cell['rtl_path'])+'.q',d=path(cell['rtl_path'])+'.d',
                          capture=path(cell['rtl_path'])+('.trigger' if variant=='click' else '.closed'),
                          receipt_path=path(node['rtl_path']),receipt_model=hm,
                          req=path(store['rtl_path'])+f'.banks_{i}_req',ack=path(store['rtl_path'])+f'.banks_{i}_ack',
                          # Whole-store policy closes this actual probe alias;
                          # contract ca_p paths exist only after strict export instrumentation.
                          available=path(store['rtl_path'])+f'.packed_17_probe[{i}]'))
    for resource, digest in manifest['resources'].items():
        require(sha(source / Path(resource).name) == digest, 'MODEL_HASH:' + resource)
    busy = re.search(r'wire\s+fabric_hostFrames_io_enq_bits_programBusy\s*=\s*([^;]+);', rtl)
    reset = re.search(r'wire\s+fabric_hostFrames_io_enq_bits_resetActive\s*=\s*([^;]+);', rtl)
    require(busy and reset, 'CONTEXT_BINDING')
    return dict(variant=variant, manifest=manifest, top=top, publisher=publisher,
                receipt=receipt, receipt_model=receipt_model, source_cell=primitive[0], source_q=path(primitive[0]['rtl_path']) + '.q',
                publisher_path=path(publisher['rtl_path']), receipt_path=path(receipt['rtl_path']),
                target_path=path(receipt['rtl_path']).rsplit('.', 1)[0], clock=qualify(clocks[0][0]),
                frame_d=frame_d, register_assignments=assignments,
                context_busy=busy[1].strip(), context_reset=reset[1].strip(),
                store=store,store_model=store_model,store_path=path(store['rtl_path']),banks=banks,
                command=command,command_model=command_model,command_path=path(command['rtl_path']),command_fields=command_fields)


def monitors(b):
    receipt,pub,target=b['receipt_path'],b['publisher_path'],b['target_path']
    store,command=b['store_path'],b['command_path']
    descriptor=lambda slot:'{'+','.join('Testbench.dut.fabric_hostFrames_'+slot+'_'+name for name,_ in DESCRIPTOR)+'}'
    incoming='{'+','.join(qualify(b['frame_d'][name]) for name,_ in DESCRIPTOR)+'}'
    command_data=lambda prefix:'{'+','.join(command+'.'+prefix+(name if name!='resetActive' else 'cpuResetActive') for name in
        ['frame_length','frame_overflow']+['frame_bytes_'+str(i) for i in reversed(range(33))]+['resetActive','programBusy'])+'}'
    bank_wires='\n'.join(f"wire [336:0] bank_q_{i}={v['q']};wire [336:0] bank_d_{i}={v['d']};" for i,v in enumerate(b['banks']))
    bank_select=lambda leaf:'{'+','.join(v[leaf] for v in reversed(b['banks']))+'}'
    result=bank_wires+f'''\nwire [336:0] native_payload={b['source_q']};
wire [336:0] receipt_payload={{{packed(receipt+'.out_bits_ingress_')},{receipt}.out_bits_resetEpoch}};
wire [3:0] first_q={descriptor('first')},second_q={descriptor('second')};
wire [3:0] descriptor_d={incoming};
wire enq=Testbench.dut.fabric_hostFrames_;
wire deq=Testbench.dut.fabric_hostFrames__0;
wire [1:0] occupancy=Testbench.dut.fabric_hostFrames_count;
wire work_clock={b['clock']};
wire receipt_fire={receipt}.out_valid && {receipt}.out_ready;
wire [1:0] slot={store}.slot;
wire [3:0] bank_available={bank_select('available')};
wire [3:0] bank_request={bank_select('req')},bank_acknowledge={bank_select('ack')};
wire [336:0] bank_q[0:3];
assign bank_q[0]=bank_q_0;assign bank_q[1]=bank_q_1;assign bank_q[2]=bank_q_2;assign bank_q[3]=bank_q_3;
wire expected_reset=native_payload[65] || {target}.host_resetActive ||
  (native_payload[63:0] != ({target}.resetEpoch_epoch + ({target}.host_resetActive && !{target}.resetEpoch_previous))) ||
  Testbench.dut.cpuResetActive;
wire expected_busy=native_payload[64] || Testbench.dut.ca_child_program_access.io_busy ||
  Testbench.dut.fabric_loaderPending || Testbench.dut.fabric_loaderControlPending ||
  ({command}.in_valid && {command}.in_ready && {command}.in_bits_kind==0 &&
   {command}.in_bits_frame_bytes_0>=1 && {command}.in_bits_frame_bytes_0<=6);
wire [272:0] independently_expected={{native_payload[336:66],expected_reset,expected_busy}};
wire [272:0] command_d={command_data('in_bits_')},command_q={command_data('data_')};
wire command_fire={command}.in_valid && {command}.in_ready && {command}.in_bits_kind==0;
wire [63:0] epoch_now={target}.resetEpoch_epoch + ({target}.host_resetActive && !{target}.resetEpoch_previous);
reg [336:0] expected_native[0:3];reg [272:0] expected_context[0:3];
reg [3:0] live=0;
reg [3:0] expected_first,expected_second;
reg [1:0] expected_count;
reg [272:0] expected_command;
reg expected_ack,had_enq,had_deq,expected_meta,expected_sync;
integer accepts=0,dispatches=0,offers=0,first_writes=0,second_writes=0,shifts=0,simultaneous=0,stopped_edges=0;
integer context_post_edge_changes=0,next_offer=0,next_accept=0,lifetime_accepts=0,lifetime_offers=0,third_next_checks=0,reuse_offer_checks=0,i;
integer bank_accepts[0:3];integer bank_dispatches[0:3];
reg [336:0] bank_ones[0:3],bank_zeroes[0:3];
reg [336:0] seen_one=0,seen_zero=0;
reg [272:0] seen_destination_one=0,seen_destination_zero=0;
time source_change=0,data_change=0,admission_time=0,actual_work_edge=0;
time receipt_change=0;time bank_retired_at[0:3],bank_ready_at[0:3];reg [3:0] bank_retired=0;
time minimum_source_setup=64'hffffffffffffffff,minimum_destination_setup=64'hffffffffffffffff;
time minimum_source_hold=64'hffffffffffffffff,minimum_payload_hold=64'hffffffffffffffff;
time minimum_third_next_margin=64'hffffffffffffffff,minimum_reuse_offer_margin=64'hffffffffffffffff;
reg source_seen=0,admission_seen=0,previous_ack=0;
always @(posedge Testbench.reset) begin
 admission_seen=0;source_seen=0;previous_ack=0;live=0;bank_retired=0;next_offer=0;next_accept=0;lifetime_accepts=0;lifetime_offers=0;
end
initial for(i=0;i<4;i=i+1) begin bank_accepts[i]=0;bank_dispatches[i]=0;bank_ready_at[i]=0;bank_ones[i]=0;bank_zeroes[i]=0;end
always @({pub}.frame_req) if(!Testbench.reset && ({"1'b1" if b['variant']=='click' else pub+'.frame_req'})) begin
 if(slot!==next_offer || bank_available[slot]!==1'b1) $fatal(1,"{PREFIX}_BANK_UNAVAILABLE_AT_O");
 if(lifetime_offers>=4) begin
  reuse_offer_checks=reuse_offer_checks+1;
  if($time-bank_ready_at[slot]<minimum_reuse_offer_margin) minimum_reuse_offer_margin=$time-bank_ready_at[slot];
 end
 lifetime_offers=lifetime_offers+1;next_offer=(next_offer+1)%4;offers=offers+1;
end
always @(native_payload) if(!Testbench.reset) begin
 if({pub}.frame_req{('!='+pub+'.frame_ack') if b['variant']=='click' else (' || '+pub+'.frame_ack')}) $fatal(1,"{PREFIX}_SOURCE_OVERWRITE");
 if(admission_seen && $time-admission_time<=100000) $fatal(1,"{PREFIX}_SOURCE_HOLD");
 if(admission_seen && $time-admission_time<minimum_source_hold) minimum_source_hold=$time-admission_time;
 source_change=$time;source_seen=1;
end
always @(descriptor_d) if(!Testbench.reset) begin
 data_change=$time;if(admission_seen && $time==admission_time) context_post_edge_changes=context_post_edge_changes+1;
end
always @(receipt_payload[336:66]) if(!Testbench.reset) begin
 if(admission_seen && $time-admission_time<=100000) $fatal(1,"{PREFIX}_DESTINATION_HOLD");
 receipt_change=$time;
end
always @(posedge {b['clock']}) actual_work_edge=$time;
always @(posedge {receipt}.clock) if(!Testbench.reset && !{receipt}.localReset) begin
 expected_meta={receipt}.in_req;expected_sync={receipt}.requestMeta;
 if(receipt_fire) begin #1;if(actual_work_edge!=$time-1) $fatal(1,"{PREFIX}_ACK_WITHOUT_WORK_EDGE");end
 if(!Testbench.workRunning) begin stopped_edges=stopped_edges+1;if(receipt_fire) $fatal(1,"{PREFIX}_STOPPED_ACCEPTANCE");end
 #1;
 if(!Testbench.reset && !{receipt}.localReset) begin
  if({receipt}.requestMeta!==expected_meta) $fatal(1,"{PREFIX}_REQUEST_META_CAPTURE");
  if({receipt}.requestSync!==expected_sync) $fatal(1,"{PREFIX}_REQUEST_SYNC_CAPTURE");
 end
end
always @(posedge {b['clock']}) if(!Testbench.reset) begin
 had_enq=enq;had_deq=deq;expected_first=first_q;expected_second=second_q;expected_count=occupancy;
 expected_ack={'~'+receipt+'.acknowledge' if b['variant']=='click' else "1'b1"};
 if(receipt_fire!==enq) $fatal(1,"{PREFIX}_ADMISSION_IDENTITY");
 if(command_fire!==deq) $fatal(1,"{PREFIX}_DISPATCH_IDENTITY");
 if(deq) begin
  if(!live[first_q[3:2]]) $fatal(1,"{PREFIX}_DISPATCH_WITHOUT_LIVE_BANK");
  expected_command=expected_context[first_q[3:2]];
  expected_command[1]=expected_command[1] || Testbench.dut.cpuResetActive || expected_native[first_q[3:2]][63:0]!=epoch_now;
  expected_command[0]=expected_command[0] || Testbench.dut.ca_child_program_access.io_busy;
  if(command_d!==expected_command || bank_q[first_q[3:2]]!==expected_native[first_q[3:2]]) $fatal(1,"{PREFIX}_COMMAND_D_IDENTITY");
  live[first_q[3:2]]=0;bank_retired[first_q[3:2]]=1;bank_retired_at[first_q[3:2]]=$time;
  dispatches=dispatches+1;bank_dispatches[first_q[3:2]]=bank_dispatches[first_q[3:2]]+1;
 end
 if(enq) begin
  if(lifetime_accepts>=3) begin
   if(bank_available[(slot+1)%4]!==1'b1) $fatal(1,"{PREFIX}_READY_BY_THIRD_NEXT_A");
   third_next_checks=third_next_checks+1;
   if($time-bank_ready_at[(slot+1)%4]<minimum_third_next_margin) minimum_third_next_margin=$time-bank_ready_at[(slot+1)%4];
  end
  lifetime_accepts=lifetime_accepts+1;
  if((^native_payload)===1'bx || $time-source_change<=100000) $fatal(1,"{PREFIX}_SOURCE_SETUP");
  if($time-receipt_change<=100000) $fatal(1,"{PREFIX}_DESTINATION_SETUP");
  if($time-source_change<minimum_source_setup) minimum_source_setup=$time-source_change;
  if(descriptor_d!=={{slot,expected_reset,expected_busy}} || receipt_payload!==native_payload) $fatal(1,"{PREFIX}_CONTEXT_OR_DATA");
  if(occupancy==2) $fatal(1,"{PREFIX}_IMPOSSIBLE_ACCEPTANCE");
  if(slot!==next_accept || live[slot]) $fatal(1,"{PREFIX}_LIVE_BANK_OVERWRITE");
  if({store}.in_ack!=={pub}.frame_req || bank_q[slot]!==native_payload) $fatal(1,"{PREFIX}_BANK_COPY_AT_A");
  next_accept=(next_accept+1)%4;live[slot]=1;expected_native[slot]=native_payload;expected_context[slot]=independently_expected;
  bank_accepts[slot]=bank_accepts[slot]+1;bank_ones[slot]=bank_ones[slot]|native_payload;bank_zeroes[slot]=bank_zeroes[slot]|~native_payload;
  admission_seen=1;admission_time=$time;accepts=accepts+1;
  seen_one=seen_one|native_payload;seen_zero=seen_zero|~native_payload;
  seen_destination_one=seen_destination_one|independently_expected;seen_destination_zero=seen_destination_zero|~independently_expected;
  if(occupancy==0 || deq) begin expected_first=descriptor_d;first_writes=first_writes+1;end
  else begin expected_second=descriptor_d;second_writes=second_writes+1;end
  if(deq) simultaneous=simultaneous+1;else expected_count=occupancy+1;
 end else if(deq) begin expected_first=second_q;expected_count=occupancy-1;shifts=shifts+1;end
 #1;
 if(!Testbench.reset) begin
  if(first_q!==expected_first) $fatal(1,"{PREFIX}_FIRST_CAPTURE");
  if(second_q!==expected_second) $fatal(1,"{PREFIX}_SECOND_CAPTURE");
  if(occupancy!==expected_count) $fatal(1,"{PREFIX}_COUNT_CAPTURE");
  if(had_deq && command_q!==expected_command) $fatal(1,"{PREFIX}_COMMAND_Q_CAPTURE");
  if(had_enq && {receipt}.acknowledge!==expected_ack) $fatal(1,"{PREFIX}_ACK_CAPTURE");
 end
end
always @({receipt}.acknowledge) if(!Testbench.reset && !{receipt}.localReset) begin
 #1;
 if({receipt}.acknowledge!==previous_ack) begin
  if({'1\'b1' if b['variant']=='click' else receipt+'.acknowledge'}) begin
   if(!admission_seen || $time!=admission_time+1) $fatal(1,"{PREFIX}_ACK_WITHOUT_ADMISSION");
  end else if({receipt}.requestSync) $fatal(1,"{PREFIX}_EARLY_BD_ACK_RETURN");
 end
 previous_ack={receipt}.acknowledge;
end
'''
    for i,bank in enumerate(b['banks']):
        owned=f"({bank['req']} != {bank['ack']})" if b['variant']=='click' else f"({bank['req']} || {bank['ack']})"
        result+=f'''
always @(posedge {bank['available']}) bank_ready_at[{i}]=$time;
time bank_data_change_{i}=0,bank_capture_time_{i}=0;reg bank_captured_{i}=0;
reg [336:0] bank_expected_d_{i},bank_expected_identity_{i};
always @({bank['d']}) if(!Testbench.reset) begin
 if(bank_captured_{i} && $time-bank_capture_time_{i}<=100000) $fatal(1,"{PREFIX}_BANK{i}_HOLD");
 bank_data_change_{i}=$time;
end
always @(posedge {bank['capture']}) if(!Testbench.reset) begin
 if($time-bank_data_change_{i}<=100000) $fatal(1,"{PREFIX}_BANK{i}_SETUP");
 if($time-bank_data_change_{i}<minimum_destination_setup) minimum_destination_setup=$time-bank_data_change_{i};
 bank_expected_d_{i}={bank['d']};bank_expected_identity_{i}=(slot=={i} ? native_payload : {bank['q']});
 bank_capture_time_{i}=$time;bank_captured_{i}=1;
 #10000001;if({bank['q']}!==bank_expected_d_{i}) $fatal(1,"{PREFIX}_BANK{i}_CAPTURE");
 if({bank['q']}!==bank_expected_identity_{i}) $fatal(1,"{PREFIX}_BANK{i}_IDENTITY");
end
always @(negedge {bank['capture']}) if(!Testbench.reset && bank_captured_{i} && $time-bank_capture_time_{i}<=100000)
 $fatal(1,"{PREFIX}_BANK{i}_PULSE");
always @({bank['q']}) if(!Testbench.reset) begin
 if(live[{i}] || {owned}) $fatal(1,"{PREFIX}_BANK{i}_RETAIN");
 if(bank_retired[{i}] && $time-bank_retired_at[{i}]<minimum_payload_hold) minimum_payload_hold=$time-bank_retired_at[{i}];
end
always @(posedge Testbench.reset) bank_captured_{i}=0;
'''
    result+=f'''
task finish_checks;
integer k;
begin
 if(!accepts || !first_writes) $fatal(1,"{PREFIX}_NO_ACTIVITY");
 $display("{PREFIX}_ACTIVITY:%0d:%0d:%0d:%0d:%0d:%0d:%0d",accepts,first_writes,second_writes,shifts,simultaneous,stopped_edges,context_post_edge_changes);
 $display("{PREFIX}_SOURCE_ONES:%h",seen_one);$display("{PREFIX}_SOURCE_ZEROES:%h",seen_zero);
 $display("{PREFIX}_DEST_ONES:%h",seen_destination_one);$display("{PREFIX}_DEST_ZEROES:%h",seen_destination_zero);
 for(k=0;k<4;k=k+1) $display("{PREFIX}_BANK:%0d:%0d:%0d:%h:%h",k,bank_accepts[k],bank_dispatches[k],bank_ones[k],bank_zeroes[k]);
 $display("{PREFIX}_MIN_FS:%0d:%0d:%0d:%0d",minimum_source_setup,minimum_destination_setup,minimum_source_hold,minimum_payload_hold);
 $display("{PREFIX}_READY_FS:%0d:%0d:%0d:%0d",third_next_checks,reuse_offer_checks,minimum_third_next_margin,minimum_reuse_offer_margin);
end
endtask
'''
    return result

def instrument(original, b):
    anchor = 'timeunit 1ns; timeprecision 1ps;'
    marker = '$display("RISCAY_SOC_PASS");'
    require(original.count(anchor) == original.count(marker) == original.count('endmodule') == 1, 'ORACLE_SHAPE')
    result = original.replace(anchor, anchor + '\nFrameCaptureChecks frame_capture_checks();', 1)
    result = result.replace(marker, 'frame_capture_checks.finish_checks();\n' + marker, 1)
    require(result.replace('FrameCaptureChecks frame_capture_checks();\n', '', 1).replace(
        'frame_capture_checks.finish_checks();\n', '', 1) == original, 'ORACLE_CHANGED')
    return result + '\nmodule FrameCaptureChecks;\ntimeunit 1fs; timeprecision 1fs;\n' + monitors(b) + '\nendmodule\n'


def assertion_sites(test, expected):
    start = test.index('module FrameCaptureChecks;')
    if not expected.startswith(PREFIX + '_'):
        return fatal_sites(test[:start], [expected])
    sites = fatal_sites(test[start:], [expected])
    for site in sites:
        site['line'] += test.count('\n', 0, start)
        site['scope'] = site['scope'].replace('Testbench', 'Testbench.frame_capture_checks', 1)
    return sites


def classify(compiled, simulated, log, sites=()):
    if sites:
        require('RISCAY_SOC_PASS' not in log, 'MIXED_PASS_FAULT')
        return classify_fatal(compiled, simulated, log, sites)
    require(compiled.get('exit_code') == simulated.get('exit_code') == 0 and
            not compiled.get('timed_out') and not simulated.get('timed_out'), 'POSITIVE_EXIT')
    require(log.splitlines().count('RISCAY_SOC_PASS') == 1 and
            not re.search(r'FATAL:|TIMEOUT|DEADLINE|\bERROR\b', log, re.I), 'POSITIVE_LOG')
    return []


def wrap_sites(case,b):
    path=(Path(case)/'I2cTarget.sv').resolve();text=path.read_text(encoding='utf-8')
    errors=list(re.finditer(r'\$error\("Assertion failed: I2C_RESET_EPOCH_WRAP\\n"\);',text))
    require(len(errors)==1,'WRAP_ASSERTION_INVENTORY');error=errors[0]
    stop=re.match(r'(?:(?!\bend\b).)*?\$fatal;',text[error.end():],re.S)
    require(stop is not None,'WRAP_FATAL_BINDING')
    fatal_at=error.end()+stop[0].rindex('$fatal;')
    return dict(source=str(path),error_line=text.count('\n',0,error.start())+1,
                fatal_line=text.count('\n',0,fatal_at)+1,scope=b['target_path'])


def classify_wrap(compiled,simulated,log,site):
    require(compiled.get('exit_code')==0 and simulated.get('exit_code')==1 and
            not compiled.get('timed_out') and not simulated.get('timed_out'),'WRAP_EXIT')
    require(not re.search(r'RISCAY_SOC_PASS|TIMEOUT|DEADLINE|FRAME_INPUT_WRAP_MISSING',log),'WRAP_OTHER_RESULT')
    pattern=(r'ERROR: '+re.escape(site['source'])+':'+str(site['error_line'])+
        r': Assertion failed: I2C_RESET_EPOCH_WRAP\s*\n\s*Time: (\d+)\s+Scope: '+re.escape(site['scope'])+
        r'\s*\nFATAL: '+re.escape(site['source'])+':'+str(site['fatal_line'])+
        r':\s*\n\s*Time: \1\s+Scope: '+re.escape(site['scope'])+r'\s*')
    require(re.fullmatch(pattern,log) is not None,'WRAP_EXACT_ASSERTION')
    return [site]


def skew(test, b, profile):
    require(profile in PROFILES, 'PROFILE')
    if profile == 'original':
        return test, {}
    changes = {}
    # Never change fixed request/output guards or the explicit 10 ns data
    # budget. Oppose variable storage propagation against control feedback.
    family=[('publisher',b['publisher'])]+[('bank',n) for n in nodes(b['store'])]
    for owner,p in [(owner,p) for owner,n in family for p in n['primitives']]:
        if p['parameters'].get('DELAY_FS') != '1000000':
            continue
        is_data=p['id'] in ('frame_payload','frame_phase','payload') or bool(re.fullmatch(r'(payload|phase)\d',p['id']))
        if profile=='publisher-fast-banks-slow': slow=owner=='bank'
        elif profile=='publisher-slow-banks-fast': slow=owner=='publisher'
        else: slow=profile!='minimum' and (is_data == (profile=='data-slow-control-fast'))
        name = 'dut.' + p['rtl_path'].split('.', 1)[1] + '.DELAY_FS'
        pattern = r'\bdefparam\s+' + re.escape(name) + r'\s*=\s*(\d+)\s*;'
        old = re.findall(pattern, test)
        require(len(old) <= 1, 'DUPLICATE_DELAY')
        value = '10000000' if slow else '1000000'
        statement = 'defparam ' + name + '=' + value + ';'
        if old:
            test = re.sub(pattern, statement, test)
        else:
            test = test.replace('timeunit 1ns; timeprecision 1ps;', 'timeunit 1ns; timeprecision 1ps;\n' + statement, 1)
        changes[name] = dict(before=old[0] if old else '1000000', after=value)
    require(changes, 'EMPTY_SKEW')
    return test, changes


def supplemental(original, b, source, wrap=False, continuous=False, boundary=False, ring=False):
    """New input-boundary experiment, separate from the unmodified wire oracle.

    Normal stimulus forces declared I2cPublication input pins only. The separate
    D-epoch and wrap cases explicitly force the actual epoch source register.
    Native payload, descriptor and command destination registers are never forced.
    """
    prefix = original.split('reg clockEnabled=1;', 1)
    require(len(prefix) == 2 and prefix[0].count('module Testbench;') == 1, 'SUPPLEMENTAL_HEADER')
    header = prefix[0]
    require('force ' not in header and 'initial ' not in header, 'SUPPLEMENTAL_HEADER_STIMULUS')
    clocks = re.findall(r'initial begin (?:serviceClock|watchdogClock)=0; forever begin [^\n]+', original)
    require(len(clocks) == 2, 'SUPPLEMENTAL_CLOCKS')
    declarations = re.findall(r'^reg\s+\[\d+:0\]\s+(\w+)\s*;', header, re.M)
    require({'reset', 'holdFrame', 'holdHostCommands', 'stopWorkClock', 'applicationReset'} <= set(declarations), 'SUPPLEMENTAL_PORTS')
    rtl = clean((Path(source) / 'I2cPublication.sv').read_text(encoding='utf-8'))
    inputs = re.findall(r'^\s*input\s+(?:\[\d+:0\]\s+)?(\w+)\s*,', rtl, re.M)
    require(inputs and set(inputs) >= {'reset', 'in_req', 'in_bits_frameValid', 'in_bits_snapshotValid'}, 'PUBLICATION_INPUTS')
    force = []; driver_wires = []
    slices = {'in_bits_frame_ingress_frame_length': 'pub_data[336:331]',
              'in_bits_frame_ingress_frame_overflow': 'pub_data[330]',
              'in_bits_frame_ingress_resetActive': 'pub_data[65]',
              'in_bits_frame_ingress_programBusy': 'pub_data[64]',
              'in_bits_frame_resetEpoch': 'pub_data[63:0]'}
    slices.update({'in_bits_frame_ingress_frame_bytes_' + str(i): f'pub_data[{66 + i * 8}+:8]' for i in range(33)})
    require(set(slices) <= set(inputs), 'PUBLICATION_FRAME_PORTS')
    pub = b['publisher_path'].replace('Testbench.', '')
    for name in inputs:
        if not name.startswith('in_'):
            continue
        value = 'pub_phase' if name == 'in_req' else "1'b1" if name == 'in_bits_frameValid' else slices.get(name, "'0")
        if name in slices:
            width = 64 if name.endswith('resetEpoch') else 6 if name.endswith('length') else 8 if 'bytes_' in name else 1
            driver_wires.append(f'wire [{width-1}:0] drive_{name}={value};')
            value='drive_'+name
        force.append('force ' + pub + '.' + name + '=' + value + ';')
    native_return = (f'wait({pub}.frame_req=={pub}.frame_ack);' if b['variant'] == 'click'
                     else f'wait(!{pub}.frame_req && !{pub}.frame_ack);')
    request = 'pub_phase=~pub_phase;' if b['variant'] == 'click' else "pub_phase=1;"
    input_return = '' if b['variant'] == 'click' else f'#2;pub_phase=0;wait(!{pub}.in_ack);'
    result=header + '\nreg clockEnabled=1;reg referenceEnabled=1;\n' + '\n'.join(clocks) + f'''
reg [336:0] pub_data=0,expectedSourcePayload=0,pattern,queued_second_data;
{' '.join(driver_wires)}
reg pub_phase=0,queued_second_pending=0;
integer bit_index,old_accepts,epoch_checks=0;
initial begin #100000000; $fatal(1,"FRAME_INPUT_DEADLINE"); end
always @(posedge observedWorkClock) if(!reset && injectedAccepted) begin
  if(observedNativeFrame !== expectedSourcePayload) $fatal(1,"FRAME_INPUT_SOURCE_IDENTITY");
  if(queued_second_pending) begin expectedSourcePayload=queued_second_data;queued_second_pending=0;end
end
task new_pair;
begin
  @(negedge serviceClock);#2;reset=1;pub_phase=0;pub_data=0;
  holdFrame=0;holdHostCommands=0;stopWorkClock=0;applicationReset=0;
  repeat(8) @(negedge serviceClock);
  #2;reset=0;
  repeat(64) @(negedge serviceClock);
  while(!controlIdle) @(negedge serviceClock);
  #2;holdHostCommands=1;
  if(dut.fabric_hostFrames_count!=0 || currentReset || currentBusy) $fatal(1,"FRAME_INPUT_PAIR_PRECONDITION");
end
endtask
task offer_frame(input [336:0] data);
begin
  @(negedge serviceClock);#2;expectedSourcePayload=data;pub_data=data;
  old_accepts=frame_capture_checks.accepts;
  #30;{request}
  wait({pub}.in_ack==pub_phase);
  {input_return}
  wait(frame_capture_checks.accepts==old_accepts+1);
  {native_return}
  repeat(4) @(negedge serviceClock);
end
endtask
initial begin
  {' '.join(name+'=0;' for name in declarations if name not in ('serviceClock','watchdogClock','sda'))}
  reset=1;scl=1;hostLow=0;response_ready=1;
  {' '.join(force)}
  // Walking one and walking zero are captured in different actual slots.
  // Start with a second publication already waiting while the first output
  // is held. Releasing only frame acceptance measures earliest source reuse.
  new_pair();holdFrame=1;pattern=0;pattern[63:0]=currentEpoch;
  expectedSourcePayload=pattern;pub_data=pattern;old_accepts=frame_capture_checks.accepts;
  #30;{request}wait({pub}.in_ack==pub_phase);{input_return}
  wait(receiptValid);
  @(negedge serviceClock);#2;queued_second_data=~pattern;pub_data=queued_second_data;
  queued_second_pending=1;#30;{request}
  repeat(8) @(negedge serviceClock);
  if(observedNativeFrame !== pattern || frame_capture_checks.accepts!=old_accepts) $fatal(1,"FRAME_INPUT_QUEUED_RETENTION");
  #2;holdFrame=0;
  wait({pub}.in_ack==pub_phase);{input_return}
  wait(frame_capture_checks.accepts==old_accepts+2);{native_return}
  if(queued_second_pending || dut.fabric_hostFrames_count!=2) $fatal(1,"FRAME_INPUT_QUEUED_REUSE");
  // Source context is tested with an equal epoch so the comparator cannot mask
  // a disconnected source reset bit; current synchronous context is clear.
  new_pair();pattern=0;pattern[63:0]=currentEpoch;pattern[65]=1;
  offer_frame(pattern);pattern[65]=0;pattern[64]=1;offer_frame(pattern);
  if(!dut.fabric_hostFrames_first_resetActive || !dut.fabric_hostFrames_second_programBusy ||
     dut.fabric_hostFrames_second_resetActive) $fatal(1,"FRAME_INPUT_SOURCE_CONTEXT");
  // Only the same-edge Host VERIFY dispatch may contribute busy at this A.
  // Its own invalid-state result is followed by START, which must report Busy
  // from the retained admission context even after VERIFY has completed.
  new_pair();pattern=0;pattern[63:0]=currentEpoch;pattern[336:331]=1;pattern[73:66]=3;
  offer_frame(pattern);holdFrame=1;pattern[73:66]=5;
  expectedSourcePayload=pattern;pub_data=pattern;old_accepts=frame_capture_checks.accepts;
  #30;{request}wait({pub}.in_ack==pub_phase);{input_return}wait(receiptValid);
  @(negedge serviceClock);#2;
  if(currentBusy || currentReset || dut.fabric_loaderPending || dut.fabric_loaderControlPending ||
     observedNativeFrame[65:64]!=0 || observedNativeFrame[63:0]!=currentEpoch)
    $fatal(1,"FRAME_INPUT_SAME_EDGE_PRECONDITION");
  holdHostCommands=0;holdFrame=0;
  @(posedge observedWorkClock);
  if(!hostDispatched || !injectedAccepted) $fatal(1,"FRAME_INPUT_SAME_EDGE_MISSING");
  #1;
  if(!dut.fabric_hostFrames_first_programBusy) $fatal(1,"FRAME_INPUT_SAME_EDGE_BUSY_CAPTURE");
  {native_return}
  @(negedge serviceClock);while(!controlIdle) @(negedge serviceClock);
  if(lastError!=3 || programmed || mode!=0 || frame_capture_checks.accepts!=old_accepts+1)
    $fatal(1,"FRAME_INPUT_SAME_EDGE_BUSY_RESULT");
  for(bit_index=0;bit_index<337;bit_index=bit_index+1) begin
    new_pair();pattern=337'b1<<bit_index;
    offer_frame(pattern);offer_frame(~pattern);
    if(dut.fabric_hostFrames_count!=2) $fatal(1,"FRAME_INPUT_SLOT_COVERAGE");
  end
  // Every epoch comparator input independently changes the admission reset bit.
  // These are additional frames with source reset history clear, so another
  // source/context bit cannot mask a missing epoch input.
  for(bit_index=0;bit_index<64;bit_index=bit_index+1) begin
    new_pair();pattern=0;pattern[63:0]=currentEpoch;
    offer_frame(pattern);
    if(dut.fabric_hostFrames_first_resetActive) $fatal(1,"FRAME_INPUT_EQUAL_EPOCH");
    pattern[bit_index]=~pattern[bit_index];offer_frame(pattern);
    if(!dut.fabric_hostFrames_second_resetActive) $fatal(1,"FRAME_INPUT_EPOCH_BIT");
    epoch_checks=epoch_checks+1;
  end
  if(frame_capture_checks.seen_one !== {{337{{1'b1}}}} || frame_capture_checks.seen_zero !== {{337{{1'b1}}}})
    $fatal(1,"FRAME_INPUT_337_POLARITY");
  if(frame_capture_checks.seen_destination_one !== {{273{{1'b1}}}} || frame_capture_checks.seen_destination_zero !== {{273{{1'b1}}}})
    $fatal(1,"FRAME_INPUT_273_POLARITY");
  if(epoch_checks!=64 || frame_capture_checks.first_writes!=405 || frame_capture_checks.second_writes!=403 || frame_capture_checks.simultaneous!=1)
    $fatal(1,"FRAME_INPUT_FULL_COVERAGE");
  $display("FRAME_INPUT_COVERAGE:337:273:%0d:808",epoch_checks);
  $display("RISCAY_SOC_PASS");$finish;
end
endmodule
'''
    if continuous:
        walk_bits=4 if boundary else 337;epoch_bits=0 if boundary else 64
        frame_count=walk_bits*8+epoch_bits*4
        start=result.index('  // Walking one')
        result=result[:start]+f'''  new_pair();
  // Do not reset between pairs: all four physical banks see both polarities of
  // every source bit through repeated independent native phase generations.
  for(bit_index=0;bit_index<{walk_bits};bit_index=bit_index+1) begin
    for(bank_index=0;bank_index<8;bank_index=bank_index+1) begin
      pattern=337'b1<<bit_index;if(bank_index>=4) pattern=~pattern;
      offer_frame(pattern);
      if(bank_index%2==1) begin
        if(dut.fabric_hostFrames_count!=2) $fatal(1,"FRAME_INPUT_CONTINUOUS_TWO_CREDITS");
        @(negedge serviceClock);#2;holdHostCommands=0;
        @(negedge serviceClock);while(!controlIdle) @(negedge serviceClock);
        #2;holdHostCommands=1;
      end
    end
  end
  for(bank_index=0;bank_index<4;bank_index=bank_index+1) begin
    if(frame_capture_checks.bank_ones[bank_index]!=={{337{{1'b1}}}} ||
       frame_capture_checks.bank_zeroes[bank_index]!=={{337{{1'b1}}}} ||
       frame_capture_checks.bank_accepts[bank_index]!={walk_bits*2} || frame_capture_checks.bank_dispatches[bank_index]!={walk_bits*2})
      $fatal(1,"FRAME_INPUT_CONTINUOUS_BANK_POLARITY");
  end
  // Isolate D's comparator from A's captured reset flag. The actual epoch source
  // register is the only additional forced node in this synthetic campaign;
  // descriptors, native banks and command destinations are never forced.
  force {b['target_path'].replace('Testbench.','')}.resetEpoch_epoch=epoch_driver;
  for(bit_index=0;bit_index<{epoch_bits};bit_index=bit_index+1) begin
    for(bank_index=0;bank_index<4;bank_index=bank_index+1) begin
      epoch_driver=0;pattern=0;
      offer_frame(pattern);
      if(dut.fabric_hostFrames_first_resetActive || currentReset)
        $fatal(1,"FRAME_INPUT_D_EPOCH_MASKED");
      @(negedge serviceClock);#2;epoch_driver=64'b1<<bit_index;
      @(negedge serviceClock);#2;holdHostCommands=0;
      @(negedge serviceClock);while(!controlIdle) @(negedge serviceClock);
      #2;holdHostCommands=1;epoch_checks=epoch_checks+1;
    end
  end
  release {b['target_path'].replace('Testbench.','')}.resetEpoch_epoch;
  if(frame_capture_checks.accepts!={frame_count} || frame_capture_checks.dispatches!={frame_count} || epoch_checks!={epoch_bits*4})
    $fatal(1,"FRAME_INPUT_CONTINUOUS_COUNTS");
  $display("FRAME_INPUT_CONTINUOUS:{walk_bits}:4:{walk_bits*2}:{epoch_bits*4}:{frame_count}");
  $display("RISCAY_SOC_PASS");$finish;
end
endmodule
'''
        if boundary:
            begin=result.index('  // Isolate D\'s comparator')
            end=result.index('  if(frame_capture_checks.accepts!=',begin)
            result=result[:begin]+result[end:]
        result=result.replace('integer bit_index,old_accepts,epoch_checks=0;','reg [63:0] epoch_driver=0;integer bit_index,bank_index,old_accepts,epoch_checks=0;')
    if ring:
        receipt=b['receipt_path'].replace('Testbench.','')
        pre_second=(f'{receipt}.requestMeta != {receipt}.acknowledge && {receipt}.requestSync == {receipt}.acknowledge'
                    if b['variant']=='click' else f'{receipt}.requestMeta && !{receipt}.requestSync && !{receipt}.acknowledge')
        start=result.index('  // Walking one')
        result=result[:start]+f'''  new_pair();ring_active=1;
  // The next input is offered immediately after the publisher input handshake.
  // After the initial two-credit fill, original A and actual command-input
  // readiness pace legal traffic; the single outstanding Control bridge can be
  // slower than publication. No native-bank return or extra service edge is awaited.
  for(bit_index=0;bit_index<32;bit_index=bit_index+1) begin
    if(bit_index>=3) begin
      wait(frame_capture_checks.accepts==bit_index);
      wait({b['command_path'].replace('Testbench.','')}.in_ready && !dut.fabric_controlOutstanding);
    end
    pattern=0;pattern[81:74]=bit_index;pub_data=pattern;
    #0.001;{request}
    wait({pub}.in_ack==pub_phase);expectedSourcePayload=pattern;
    {input_return}
  end
  wait(frame_capture_checks.accepts==32);ring_draining=1;holdHostCommands=0;
  wait(frame_capture_checks.dispatches==32);{native_return}
  wait(frame_capture_checks.bank_available==4'b1111);
  #2;
  if(ring_late_dispatches!=30 || ring_exact_frontiers!=30)
    $fatal(1,"FRAME_INPUT_RING_FRONTIER_COUNT");
  for(bit_index=0;bit_index<4;bit_index=bit_index+1)
    if(frame_capture_checks.bank_accepts[bit_index]!=8 || frame_capture_checks.bank_dispatches[bit_index]!=8)
      $fatal(1,"FRAME_INPUT_RING_ROTATIONS");
  $display("FRAME_INPUT_RING:32:4:8:%0d:%0d",ring_late_dispatches,ring_exact_frontiers);
  $display("RISCAY_SOC_PASS");$finish;
end
endmodule
'''
        driver=f'''
reg ring_active=0,ring_draining=0;
integer ring_late_dispatches=0,ring_exact_frontiers=0,ring_accepts=0;
localparam time RING_EXPECTED_PERIOD_FS={round(float(re.findall(r'#([0-9.]+)',clocks[0])[0])*2000000)};
time ring_last_D=0,ring_last_edge=0,ring_period=0,ring_now=0;
always @(negedge serviceClock) if(ring_active && !ring_draining) begin
  // Meta has observed original O; the next edge updates Sync. D on that edge
  // is the final legal dequeue before A on the following actual work edge.
  holdHostCommands=!(dut.fabric_hostFrames_count==2 && ({pre_second}));
end
always @(posedge observedWorkClock) if(ring_active) begin
  ring_now=time'($realtime*1000000);ring_period=ring_now-ring_last_edge;
  if(ring_last_edge!=0 && ring_period!=RING_EXPECTED_PERIOD_FS) $fatal(1,"FRAME_INPUT_RING_PERIOD");
  ring_last_edge=ring_now;
  if(hostDispatched) begin
    ring_last_D=ring_now;
    if(!ring_draining) ring_late_dispatches=ring_late_dispatches+1;
  end
  if(injectedAccepted) begin
    if(ring_accepts>=2) begin
    if(hostDispatched || ring_now-ring_last_D!=ring_period)
      $fatal(1,"FRAME_INPUT_RING_LAST_LEGAL_D");
    ring_exact_frontiers=ring_exact_frontiers+1;
    end
    ring_accepts=ring_accepts+1;
  end
end
'''
        result=result.replace('reg [336:0] pub_data=0,',driver+'reg [336:0] pub_data=0,')
    if wrap:
        start=result.index('  // Walking one')
        result=result[:start]+f'''  new_pair();
  @(negedge serviceClock);#2;
  force {b['target_path'].replace('Testbench.', '')}.resetEpoch_epoch=64'hffffffffffffffff;
  applicationReset=1;
  repeat(32) @(negedge serviceClock);
  $fatal(1,"FRAME_INPUT_WRAP_MISSING");
  $display("RISCAY_SOC_PASS");$finish;
end
endmodule
'''
    return result


def mutate(case, b, fault):
    """An isolated real RTL defect; monitors and original oracles are unchanged."""
    top = case / (b['top'] + '.sv')
    receipt = case / (b['receipt_model'] + '.sv')
    bank_fault=re.fullmatch(r'bank([0-3])-(data|setup|hold)',fault)
    if bank_fault:
        index=int(bank_fault[1]);kind=bank_fault[2];bank=b['banks'][index]
        owner_file=case/(bank['owner_model']+'.sv');body=owner_file.read_text(encoding='utf-8')
        instance=bank['cell']['rtl_path'].rsplit('.',1)[1]
        block=re.search(r'\b'+re.escape(instance)+r'\s*\((.*?)\);',clean(body),re.S)
        require(block is not None,'MUTATION_BANK_INSTANCE')
        data=re.findall(r'\.d\s*\(([^()]*)\)',block[1]);capture_name='trigger' if b['variant']=='click' else 'closed'
        trigger=re.findall(r'\.'+capture_name+r'\s*\(([^()]*)\)',block[1])
        require(len(data)==len(trigger)==1,'MUTATION_BANK_PINS')
        if kind=='data':
            body=replace_pin(body,instance,'d',f"({data[0]} ^ 337'h1)")
            expected=f'{PREFIX}_BANK{index}_IDENTITY'
        else:
            delayed='frame_fault_delayed';declaration='\nwire '+delayed+';\n'
            body,count=re.subn(r'(\bmodule\s+\w+\s*\(.*?\);)',r'\1'+declaration,body,count=1,flags=re.S)
            require(count==1,'MUTATION_BANK_MODULE')
            body='`timescale 1fs/1fs\n'+body.replace('endmodule',f'assign #50000 {delayed}={trigger[0]};\nendmodule')
            signal=delayed if kind=='hold' else trigger[0]
            body=replace_pin(body,instance,'d',f'({data[0]} ^ {{337{{{signal}}}}})')
            if kind=='setup':body=replace_pin(body,instance,capture_name,delayed)
            expected=f'{PREFIX}_BANK{index}_'+kind.upper()
        if b['variant']=='bd':
            # The emitter shares one buffer model between four instances. Clone
            # precisely the targeted instance so a sibling fault cannot qualify it.
            clone=bank['owner_model']+'_FaultBank'+str(index)
            body,count=re.subn(r'\bmodule\s+'+re.escape(bank['owner_model'])+r'\s*\(', 'module '+clone+' (',body,count=1)
            require(count==1,'MUTATION_BANK_CLONE')
            store_file=case/(b['store_model']+'.sv');store_text=store_file.read_text(encoding='utf-8')
            child_instance=bank['node']['rtl_path'].rsplit('.',1)[1]
            store_text,count=re.subn(r'\b'+re.escape(bank['owner_model'])+r'(\s+'+re.escape(child_instance)+r'\s*\()',clone+r'\1',store_text,count=1)
            require(count==1,'MUTATION_BANK_CLONE_INSTANCE');store_file.write_text(store_text+'\n'+body,encoding='utf-8')
        else:owner_file.write_text(body,encoding='utf-8')
        return expected
    if fault in ('bank-return-stuck','bank-unavailable-at-o'):
        bench=case/'testbench.sv';text=bench.read_text(encoding='utf-8')
        marker='endmodule';position=text.rfind(marker)
        acknowledge=b['banks'][0]['receipt_path']+'.acknowledge'
        value="1'b0" if b['variant']=='click' else "1'b1"
        wait_for="bank_dispatches[0]==1" if fault=="bank-return-stuck" else "lifetime_accepts==4"
        injected=f"initial begin wait({wait_for});#1;force {acknowledge}={value};end\n"
        bench.write_text(text[:position]+injected+text[position:],encoding='utf-8')
        return PREFIX+('_READY_BY_THIRD_NEXT_A' if fault=='bank-return-stuck' else '_BANK_UNAVAILABLE_AT_O')
    if fault in ('first-data', 'second-data'):
        slot = fault.split('-')[0]
        text = top.read_text(encoding='utf-8')
        lhs = 'fabric_hostFrames_' + slot + '_bank'
        rhs = b['register_assignments'][lhs]
        pattern = r'(\b' + lhs + r'\s*<=\s*)' + re.escape(rhs) + r'(\s*;)'
        text, count = re.subn(pattern, lambda m: m[1] + "("+rhs+" ^ 2'h1)" + m[2], text)
        require(count == (2 if slot == 'first' else 1), 'MUTATION_BINDING')
        top.write_text(text, encoding='utf-8')
        return PREFIX + '_' + slot.upper() + '_CAPTURE'
    if fault == 'ack-without-admission':
        text = receipt.read_text(encoding='utf-8')
        if b['variant'] == 'click':
            text, count = re.subn(r'if\s*\(out_ready\s*&\s*packed_6\)', 'if (requestSync != acknowledge)', text)
        else:
            text, count = re.subn(r'acknowledge\s*<=\s*out_ready\s*&\s*packed_6\s*\|\s*requestSync\s*&\s*acknowledge;', 'acknowledge <= requestSync;', text)
        require(count == 1, 'MUTATION_ACK_BINDING')
        receipt.write_text(text, encoding='utf-8')
        return PREFIX + '_ACK_WITHOUT_ADMISSION'
    if fault in ('receipt-data', 'data-hold','data-setup'):
        text = receipt.read_text(encoding='utf-8')
        old = 'assign out_bits_ingress_frame_bytes_0 = in_bits_ingress_frame_bytes_0;'
        require(text.count(old) == 1, 'MUTATION_RECEIPT_DATA')
        if fault == 'receipt-data':
            new = "assign out_bits_ingress_frame_bytes_0 = 8'hff;"
            expected = PREFIX + '_CONTEXT_OR_DATA'
        else:
            text,count=re.subn(r'(\bmodule\s+\w+\s*\(.*?\);)',r'\1\nwire injected_late_ack;\n',text,count=1,flags=re.S)
            require(count==1,'MUTATION_MODULE_HEADER')
            if fault=='data-hold':
                assignment='assign #50000 injected_late_ack=acknowledge;'
            else:
                half=re.findall(r'initial begin serviceClock=0; forever begin #([0-9.]+)',(case/'testbench.sv').read_text(encoding='utf-8'))
                require(len(half)==1,'MUTATION_CLOCK_PERIOD')
                assignment=f'assign #{int(float(half[0])*1000000)-50000} injected_late_ack=~clock;'
            text = '`timescale 1fs/1fs\n' + text.replace('endmodule',assignment+'\nendmodule')
            new = 'assign out_bits_ingress_frame_bytes_0 = in_bits_ingress_frame_bytes_0 ^ {8{injected_late_ack}};'
            expected = PREFIX + ('_DESTINATION_HOLD' if fault=='data-hold' else '_DESTINATION_SETUP')
        receipt.write_text(text.replace(old, new), encoding='utf-8')
        return expected
    if fault == 'epoch-bit63':
        target = case / 'I2cTarget.sv'; text = target.read_text(encoding='utf-8')
        old = '_ca_child_frame_bridge_out_bits_resetEpoch != resetEpoch'
        require(text.count(old) == 1, 'MUTATION_EPOCH_BINDING')
        target.write_text(text.replace(old, '_ca_child_frame_bridge_out_bits_resetEpoch[62:0] != resetEpoch[62:0]'), encoding='utf-8')
        return PREFIX + '_CONTEXT_OR_DATA'
    if fault in ('sync-bypass','meta-disconnect','wrong-phase'):
        text=receipt.read_text(encoding='utf-8')
        if fault=='sync-bypass':
            old='requestSync <= requestMeta;';new='requestSync <= in_req;';expected=PREFIX+'_REQUEST_SYNC_CAPTURE'
        elif fault=='meta-disconnect':
            old='requestMeta <= in_req;';new="requestMeta <= 1'b0;";expected=PREFIX+'_REQUEST_META_CAPTURE'
        elif b['variant']=='click':
            old='acknowledge <= requestSync;';new='acknowledge <= ~requestSync;';expected=PREFIX+'_ACK_CAPTURE'
        else:
            old='acknowledge <= out_ready & packed_6 | requestSync & acknowledge;'
            new='acknowledge <= out_ready & packed_6;';expected=PREFIX+'_EARLY_BD_ACK_RETURN'
        require(text.count(old)==1,'MUTATION_PHASE_BINDING')
        receipt.write_text(text.replace(old,new),encoding='utf-8');return expected
    if fault=='work-enable-bypass':
        text=top.read_text(encoding='utf-8')
        text=replace_pin(text,b['target_path'].rsplit('.',1)[1],'frameAcceptEnable','~holdFrame')
        top.write_text(text,encoding='utf-8')
        return 'FRAME_ADMISSION_STOPPED_WORK_ACK'
    if fault=='publication-overwrite':
        publication=case/'I2cPublication.sv';text=publication.read_text(encoding='utf-8')
        identifier='capture_gate_nb' if b['variant']=='click' else 'admission'
        cells=[p for p in b['publisher']['primitives'] if p['id']==identifier]
        require(len(cells)==1,'MUTATION_PUBLISHER_PRIMITIVE')
        text=replace_pin(text,cells[0]['rtl_path'].rsplit('.',1)[1],'a' if b['variant']=='click' else 'rising',"1'b1")
        publication.write_text(text,encoding='utf-8')
        return PREFIX+'_SOURCE_OVERWRITE'
    if fault in ('source-reset','source-busy'):
        text=receipt.read_text(encoding='utf-8');leaf='resetActive' if fault=='source-reset' else 'programBusy'
        old=f'assign out_bits_ingress_{leaf} = in_bits_ingress_{leaf};'
        require(text.count(old)==1,'MUTATION_SOURCE_CONTEXT')
        receipt.write_text(text.replace(old,f"assign out_bits_ingress_{leaf} = 1'b0;"),encoding='utf-8')
        return PREFIX+'_CONTEXT_OR_DATA'
    if fault=='same-edge-busy':
        text=top.read_text(encoding='utf-8')
        parts=b['context_busy'].split('|');require(len(parts)==5,'MUTATION_BUSY_CLAUSES')
        text,count=re.subn(r'(wire\s+fabric_hostFrames_io_enq_bits_programBusy\s*=\s*)[^;]+;',
                          lambda m:m[1]+' | '.join(parts[:4])+';',text)
        require(count==1,'MUTATION_BUSY_BINDING');top.write_text(text,encoding='utf-8')
        return PREFIX+'_CONTEXT_OR_DATA'
    if fault=='command-capture':
        path=case/(b['command_model']+'.sv');text=path.read_text(encoding='utf-8')
        old='data_frame_bytes_0 <= in_bits_frame_bytes_0;'
        require(text.count(old)==1,'MUTATION_COMMAND_CAPTURE')
        path.write_text(text.replace(old,"data_frame_bytes_0 <= in_bits_frame_bytes_0 ^ 8'h1;"),encoding='utf-8')
        return PREFIX+'_COMMAND_Q_CAPTURE'
    if fault=='dispatch-epoch-bit63':
        text=top.read_text(encoding='utf-8')
        pattern=r'(_GEN_\d+\[fabric_hostFrames_first_bank\])\s*!=\s*(_ca_child_i2c_host_currentEpoch)'
        matches=list(re.finditer(pattern,text));require(len(matches)==1,'MUTATION_DISPATCH_EPOCH')
        # A shift avoids introducing invalid syntax on an indexed array element.
        text,count=re.subn(pattern,lambda m:'(('+m[1]+" << 1) != ("+m[2]+' << 1))',text)
        require(count==1,'MUTATION_DISPATCH_EPOCH_COUNT');top.write_text(text,encoding='utf-8')
        return PREFIX+'_COMMAND_D_IDENTITY'
    raise ValueError(PREFIX + '_MUTATION_KIND:' + fault)


def service_period(test, period_ns):
    """Set an exactly representable service period and its independent observer."""
    require(50<=period_ns<=1000000 and (float(period_ns)*500).is_integer(),'PERIOD_SUPPORTED_PRECISION')
    clocks=re.findall(r'initial begin serviceClock=0; forever begin [^\n]+',test)
    require(len(clocks)==1 and len(re.findall(r'#[0-9.]+',clocks[0]))==1,'PERIOD_CLOCK_BINDING')
    changed=re.sub(r'#[0-9.]+','#'+str(period_ns/2),clocks[0])
    test=test.replace(clocks[0],changed)
    test,count=re.subn(r'RING_EXPECTED_PERIOD_FS=\d+', 'RING_EXPECTED_PERIOD_FS='+str(round(period_ns*1000000)),test)
    require(count in (0,1),'PERIOD_OBSERVER_BINDING')
    if count:
        # This newly generated synthetic scenario has 128 startup/drain cycles
        # and 32 frames at a conservative 32-edge command/publication bound.
        # Original real-wire testbench deadlines never enter this helper.
        budget=round(period_ns*(128+32*32)+1000)
        test,deadlines=re.subn(r'initial begin #\d+; \$fatal\(1,"FRAME_INPUT_DEADLINE"\); end',
                              f'initial begin #{budget}; $fatal(1,"FRAME_INPUT_DEADLINE"); end',test)
        require(deadlines==1,'RING_DEADLINE_BINDING')
    return test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    sources = json.loads(args.sources.read_text(encoding='utf-8'))
    require(set(sources) == {'bd', 'click'} and all(isinstance(x, dict) and set(x)==FIXTURES for x in sources.values()), 'SOURCES')
    loaded = {}
    for variant, group in sources.items():
        loaded[variant] = {}
        for label, name in group.items():
            path = Path(name).resolve(); b = bindings(path)
            require(b['variant'] == variant, 'VARIANT')
            original = (path / 'testbench.sv').read_text(encoding='utf-8')
            half=re.findall(r'initial begin serviceClock=0; forever begin #([0-9.]+)',original)
            require(len(half)==1 and round(5e8/float(half[0]))==int(re.search(r'\d+$',label)[0]),'FIXTURE_FREQUENCY')
            classify({'exit_code': 0}, {'exit_code': 0}, (path / 'simulation.log').read_text(encoding='utf-8'))
            files = [s.strip() for s in (path / 'filelist.f').read_text(encoding='utf-8').splitlines() if s.strip()]
            require(len(files) == len(set(files)) and all((path / f).resolve().is_relative_to(path) and (path / f).is_file() for f in files), 'FILELIST')
            loaded[variant][label] = dict(path=path, bindings=b, original=original, files=files)
    paths = [x['path'] for group in loaded.values() for x in group.values()]
    require(len(paths) == len(set(paths)), 'DUPLICATE_SOURCE')
    out = args.out.resolve()
    require(all(not out.is_relative_to(p) and not p.is_relative_to(out) for p in paths), 'OUTPUT_OVERLAP')
    out.mkdir(parents=True, exist_ok=False)
    originals = {str(p): hashes(p) for p in paths}
    tool_directory=Path(__file__).resolve().parent
    helpers={Path(__file__).resolve(),tool_directory/'test_frame_capture_controls.py'}
    helpers.update(Path(module.__file__).resolve() for module in list(sys.modules.values())
                   if getattr(module,'__file__',None) and Path(module.__file__).resolve().parent==tool_directory)
    helper_hashes={str(path):sha(path) for path in sorted(helpers)}
    executables={name:Path(shutil.which(name) or '').resolve() for name in ('iverilog','vvp')}
    require(all(path.is_file() for path in executables.values()),'EXECUTABLE_MISSING')
    compiler_inputs=set(executables.values())
    backend=executables['iverilog'].parent.parent/'lib'/'ivl'
    if backend.is_dir():compiler_inputs.update(path.resolve() for path in backend.iterdir() if path.is_file())
    compiler_hashes={str(path):sha(path) for path in sorted(compiler_inputs)}
    records = dict(status='RUNNING', source_index_sha256=sha(args.sources), source_sha256=originals,
                   tool_sha256=helper_hashes,compiler_sha256=compiler_hashes,cases={},
                   bindings={v:{label:{'publisher':f['bindings']['publisher_path'],'receipt':f['bindings']['receipt_path'],
                       'store':f['bindings']['store_path'],'command':f['bindings']['command_path'],
                       'descriptor_d':f['bindings']['frame_d'],'clock':f['bindings']['clock'],
                       'banks':[{k:bank[k] for k in ('index','path','q','d','capture','receipt_path','req','ack','available')}
                                for bank in f['bindings']['banks']]} for label,f in group.items()} for v,group in loaded.items()},
                   limit='Digital native retained-source and bank 100 ps aperture, descriptor A and actual ControlCommand D/Q; synchronous selector/context physical hold not qualified')
    commands = []
    def save():
        (out / 'results.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n', encoding='utf-8')
    def run(argv, case, logname):
        commands.append(dict(cwd=str(case), argv=argv, log=logname)); start = time.monotonic()
        try:
            result = subprocess.run(argv, cwd=case, text=True, capture_output=True, timeout=60)
            log = result.stdout + result.stderr
            record = dict(exit_code=result.returncode, timed_out=False)
        except subprocess.TimeoutExpired as error:
            log = 'PROCESS_TIMEOUT\n' + str(error.stdout or '') + str(error.stderr or '')
            record = dict(exit_code=None, timed_out=True)
        (case / logname).write_text(log, encoding='utf-8')
        record.update(seconds=round(time.monotonic() - start, 3), sha256=sha(case / logname), log=str(case / logname))
        return record, log
    def simulate(variant, label, profile, fault=None, walk=False,wrap=False,continuous=False,period_ns=None,ring=False):
        fixture = loaded[variant][label]; b = fixture['bindings']
        campaign=(['ring32']+(['period'+str(period_ns).replace('.','p')] if period_ns else [])) if ring else ['epoch-wrap'] if wrap else ['continuous337'] if continuous and period_ns is None else ['period'+str(period_ns).replace('.','p')] if period_ns else ['full337'] if walk else []
        name = '-'.join([variant, label, profile] + campaign + ([fault] if fault else [])); case = out / name
        shutil.copytree(fixture['path'], case)
        original = supplemental(fixture['original'], b, fixture['path'],wrap=wrap,continuous=continuous,boundary=period_ns is not None,ring=ring) if walk or wrap or continuous or ring else fixture['original']
        if period_ns is not None:
            original=service_period(original,period_ns)
        test, delays = skew(original, b, profile)
        test = instrument(test, b); (case / 'testbench.sv').write_text(test, encoding='utf-8')
        expected = 'I2C_RESET_EPOCH_WRAP' if wrap else mutate(case, b, fault) if fault else None
        test=(case/'testbench.sv').read_text(encoding='utf-8')
        entry = dict(source=str(fixture['path']), profile=profile, delay_changes=delays, fault=fault,
                     original_oracle_sha256=sha(fixture['path'] / 'testbench.sv'), oracle_sha256=sha(case / 'testbench.sv'),
                     original_assertions_preserved=not (walk or wrap or continuous or ring), supplemental_input_campaign=walk or continuous or ring,
                     continuous_native_banks=continuous,ring_last_legal_D=ring,period_ns=period_ns,
                     synthetic_ring_budget_ns=round(period_ns*1152+1000) if ring and period_ns is not None else None,
                     forced_epoch_source=(b['target_path']+'.resetEpoch_epoch') if continuous and period_ns is None else None,
                     forced_return_receipt=(b['banks'][0]['receipt_path']+'.acknowledge') if fault in ('bank-return-stuck','bank-unavailable-at-o') else None,
                     actual_epoch_wrap_control=wrap, expected=expected,
                     source_sha256={f: sha(case / f) for f in fixture['files']},
                     exact_fatal_sites=[wrap_sites(case,b)] if wrap else assertion_sites(test, expected) if expected else [])
        records['cases'][name] = entry; save()
        entry['compile'], log = run([str(executables['iverilog']), '-g2012', '-s', 'Testbench', '-o', 'frame-capture.vvp',
                                    *[str((case / f).resolve()) for f in fixture['files']], 'testbench.sv'], case, 'capture-compile.log')
        save(); require(entry['compile']['exit_code'] == 0, 'COMPILE:' + name + ':' + log[-2500:])
        entry['binary_sha256'] = sha(case / 'frame-capture.vvp')
        entry['simulation'], log = run([str(executables['vvp']), 'frame-capture.vvp'], case, 'capture-simulation.log'); save()
        entry['actual_fatals'] = (classify_wrap(entry['compile'],entry['simulation'],log,entry['exact_fatal_sites'][0])
                                 if wrap else classify(entry['compile'], entry['simulation'], log, entry['exact_fatal_sites']))
        entry['activity'] = [s for s in log.splitlines() if s.startswith(PREFIX + '_')]
        require(entry['binary_sha256'] == sha(case / 'frame-capture.vvp') and entry['oracle_sha256'] == sha(case / 'testbench.sv'), 'EXECUTED_ARTIFACT_CHANGED')
        require(all(sha(case / f)==digest for f,digest in entry['source_sha256'].items()),'COMPILED_INPUT_CHANGED')
        entry['status'] = 'PASS'; save(); print(name, 'PASS', flush=True)
    try:
        save()
        records['compiler_versions']={name:run([str(path),'-V'],out,name+'-version.log')[0] for name,path in executables.items()}
        require(all(r['exit_code']==0 for r in records['compiler_versions'].values()),'COMPILER_VERSION')
        save()
        for variant, group in loaded.items():
            for label in group:
                for profile in PROFILES:
                    simulate(variant, label, profile)
            for label in [key for key in group if key.startswith('slots')]:
                for profile in PROFILES[:4]:
                    simulate(variant, label, profile, walk=True)
                for profile in PROFILES:
                    simulate(variant, label, profile, continuous=True)
            for period_ns in PERIODS_NS:
                for profile in ('publisher-fast-banks-slow','publisher-slow-banks-fast'):
                    simulate(variant,'slots20000000',profile,ring=True,period_ns=period_ns)
            slot_label=next(key for key in group if key.startswith('slots'))
            for fault in ('first-data','second-data','receipt-data','data-hold','data-setup','publication-overwrite','epoch-bit63',
                          'source-reset','source-busy','same-edge-busy','sync-bypass','meta-disconnect','wrong-phase'):
                simulate(variant,slot_label,'original',fault,walk=True)
            reset_labels=[key for key in group if key.startswith('reset')]
            if reset_labels:
                simulate(variant,reset_labels[0],'original','ack-without-admission')
                simulate(variant,reset_labels[0],'original','work-enable-bypass')
            simulate(variant,slot_label,'original',wrap=True)
            simulate(variant,'slots20000000','original','command-capture',continuous=True)
            simulate(variant,'slots20000000','original','dispatch-epoch-bit63',continuous=True)
            for fault in ('bank-return-stuck','bank-unavailable-at-o'):
                simulate(variant,'slots20000000','original',fault,ring=True)
            for fault in [f'bank{i}-data' for i in range(4)]+['bank0-setup','bank0-hold']:
                simulate(variant,'slots20000000','original',fault,continuous=True,period_ns=50)
        require(sha(args.sources)==records['source_index_sha256'],'SOURCE_INDEX_CHANGED')
        require(all(hashes(Path(p)) == h for p, h in originals.items()), 'ORIGINAL_CHANGED')
        require(all(sha(p)==value for p,value in helper_hashes.items()),'HELPER_CHANGED')
        require(all(sha(p)==value for p,value in compiler_hashes.items()),'COMPILER_CHANGED')
        require(len(records['cases'])==312 and all(e.get('status')=='PASS' for e in records['cases'].values()),'COMPLETE_CASE_CATALOGUE')
        records.update(status='PASS', positives=sum(not e['expected'] for e in records['cases'].values()),
                       negatives=sum(bool(e['expected']) for e in records['cases'].values()), originals_preserved=True)
    except BaseException as error:
        records.update(status='FAILED', error=repr(error)); save(); raise
    save(); print('FRAME_CAPTURE_CONTROLS_PASS', flush=True)


if __name__ == '__main__':
    main()

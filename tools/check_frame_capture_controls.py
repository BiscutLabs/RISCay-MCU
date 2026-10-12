# SPDX-License-Identifier: Apache-2.0
"""Qualify native I2C frame delivery using real exported mailbox registers.

Original composed testbenches keep their assertions. A separate supplemental
campaign drives the native publication input, never its retained output, to
exercise every source bit and both actual mailbox slots. Checks use 1 fs time,
the actual work clock, native source retention, pre-edge context and captured Q.
The synchronous context cone uses ideal zero-delay flops: its physical hold
aperture is deliberately not claimed by this digital campaign.
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
from check_frame_integration import _mailbox_policy
from check_frame_receipt import validate_frame_receipts

PREFIX = 'FRAME_CAPTURE'
PROFILES = ('original', 'minimum', 'data-slow-control-fast', 'data-fast-control-slow')
FIXTURES = {'reset3200000','reset20000000','slots3200000','slots20000000','stored20000000'}
LEAVES = [('frame_length', 6), ('frame_overflow', 1)] + [
    ('frame_bytes_' + str(i), 8) for i in range(33)] + [('resetActive', 1), ('programBusy', 1)]


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


def bindings(source):
    """Bind controls to the emitted instance and actual inlined register RHS."""
    source = Path(source)
    manifest = json.loads((source / 'contract.json').read_text(encoding='utf-8'))['manifest']
    top = manifest['top']
    require(top in ('BdFrameAdmissionFixture', 'ClickFrameAdmissionFixture'), 'TOP')
    variant = 'click' if top.startswith('Click') else 'bd'
    tree = list(nodes(manifest['design']))
    publisher = [n for n in tree if n['module'] == 'I2cPublication']
    receipts = [n for n in tree if n['module'] in ('ClickFrameReceipt', 'FourPhaseFrameReceipt')]
    require(len(publisher) == len(receipts) == 1, 'OWNER_INVENTORY')
    publisher, receipt = publisher[0], receipts[0]
    primitive = [p for p in publisher['primitives'] if p['id'] == 'frame_payload']
    require(len(primitive) == 1 and primitive[0]['parameters']['WIDTH'] == '337', 'SOURCE_WIDTH')
    path = lambda p: 'Testbench.dut.' + p.split('.', 1)[1]
    rtl = clean((source / (top + '.sv')).read_text(encoding='utf-8'))
    assignments = {}
    for slot in ('first', 'second'):
        for leaf, width in LEAVES:
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
        if re.search(r'fabric_hostFrames_first_frame_length\s*<=', body):
            clocks.append((match[1], match[2]))
    require(len(clocks) == 1 and clocks[0][1] == 'reset', 'MAILBOX_CLOCK_RESET')
    # Export references and ABI are evidence, not optional conveniences.
    for key in ('probe_abi', 'port_abi'):
        abi = manifest[key]
        require(abi['sha256'] == sha(source / abi['file']), 'ABI_HASH:' + key)
    require(sum(w for _, w in LEAVES) == 273, 'DESTINATION_WIDTH')
    frame_d = {leaf: assignments['fabric_hostFrames_first_' + leaf] for leaf, _ in LEAVES}
    require(all(assignments['fabric_hostFrames_second_' + leaf] == rhs for leaf, rhs in frame_d.items()), 'SLOT_D_IDENTITY')
    _mailbox_policy((source / (top + '.sv')).read_text(encoding='utf-8'), clocks[0][0], frame_d)
    validate_frame_receipts(manifest, source)
    for resource, digest in manifest['resources'].items():
        require(sha(source / Path(resource).name) == digest, 'MODEL_HASH:' + resource)
    busy = re.search(r'wire\s+fabric_hostFrames_io_enq_bits_programBusy\s*=\s*([^;]+);', rtl)
    reset = re.search(r'wire\s+fabric_hostFrames_io_enq_bits_resetActive\s*=\s*([^;]+);', rtl)
    require(busy and reset, 'CONTEXT_BINDING')
    return dict(variant=variant, manifest=manifest, top=top, publisher=publisher,
                receipt=receipt, source_cell=primitive[0], source_q=path(primitive[0]['rtl_path']) + '.q',
                publisher_path=path(publisher['rtl_path']), receipt_path=path(receipt['rtl_path']),
                target_path=path(receipt['rtl_path']).rsplit('.', 1)[0], clock=qualify(clocks[0][0]),
                frame_d=frame_d, register_assignments=assignments,
                context_busy=busy[1].strip(), context_reset=reset[1].strip())


def monitors(b):
    receipt, pub, target = b['receipt_path'], b['publisher_path'], b['target_path']
    source = b['source_q']
    d = packed('FC_D_')
    wires = '\n'.join('wire [' + str(width - 1) + ':0] FC_D_' + leaf + ' = ' +
                      qualify(b['frame_d'][leaf]) + ';' for leaf, width in LEAVES)
    # The actual target reset-context OR and Services context changes are
    # compared with independently named pre-edge state, not copied D wires.
    return wires + f'''
wire [336:0] native_payload={source};
wire [272:0] mailbox_d={d};
wire [272:0] first_q={packed('Testbench.dut.fabric_hostFrames_first_')};
wire [272:0] second_q={packed('Testbench.dut.fabric_hostFrames_second_')};
wire enq=Testbench.dut.fabric_hostFrames_;
wire deq=Testbench.dut.fabric_hostFrames__0;
wire [1:0] occupancy=Testbench.dut.fabric_hostFrames_count;
wire work_clock={b['clock']};
wire receipt_fire={receipt}.out_valid && {receipt}.out_ready;
wire expected_reset=native_payload[65] || {target}.host_resetActive ||
  (native_payload[63:0] != ({target}.resetEpoch_epoch + ({target}.host_resetActive && !{target}.resetEpoch_previous))) ||
  Testbench.dut.cpuResetActive;
wire expected_busy=native_payload[64] || Testbench.dut.ca_child_program_access.io_busy ||
  Testbench.dut.fabric_loaderPending || Testbench.dut.fabric_loaderControlPending ||
  (Testbench.dut.ca_child_control_command_bridge.in_valid && Testbench.dut.ca_child_control_command_bridge.in_ready &&
   Testbench.dut.ca_child_control_command_bridge.in_bits_kind==0 &&
   Testbench.dut.ca_child_control_command_bridge.in_bits_frame_bytes_0>=1 &&
   Testbench.dut.ca_child_control_command_bridge.in_bits_frame_bytes_0<=6);
wire [272:0] independently_expected={{native_payload[336:66],expected_reset,expected_busy}};
time source_change=0, data_change=0, admission_time=0, actual_work_edge=0;
time minimum_source_setup=64'hffffffffffffffff, minimum_destination_setup=64'hffffffffffffffff;
time minimum_source_hold=64'hffffffffffffffff, minimum_payload_hold=64'hffffffffffffffff;
reg source_seen=0, admission_seen=0;
reg [272:0] expected_first,expected_second;
reg [1:0] expected_count;
reg expected_ack, had_enq, had_deq;
integer accepts=0, first_writes=0, second_writes=0, shifts=0, simultaneous=0, stopped_edges=0;
integer context_post_edge_changes=0;
reg [336:0] seen_one=0,seen_zero=0;
reg [272:0] seen_destination_one=0,seen_destination_zero=0;
reg previous_ack=0;
reg expected_meta,expected_sync;
always @(native_payload) if(!Testbench.reset) begin
  if({pub}.frame_req{('!='+pub+'.frame_ack') if b['variant']=='click' else (' || '+pub+'.frame_ack')}) $fatal(1,"{PREFIX}_SOURCE_OVERWRITE");
  if(admission_seen && $time-admission_time<=100000) $fatal(1,"{PREFIX}_SOURCE_HOLD");
  if(admission_seen && $time-admission_time<minimum_source_hold) minimum_source_hold=$time-admission_time;
  source_change=$time; source_seen=1;
end
always @(mailbox_d) if(!Testbench.reset) begin
  data_change=$time;
  if(admission_seen && $time==admission_time) context_post_edge_changes=context_post_edge_changes+1;
end
always @(mailbox_d[272:2]) if(!Testbench.reset && admission_seen) begin
  if($time-admission_time<=100000) $fatal(1,"{PREFIX}_DESTINATION_HOLD");
  if($time-admission_time<minimum_payload_hold) minimum_payload_hold=$time-admission_time;
end
always @(posedge Testbench.reset) begin
  admission_seen=0;source_seen=0;previous_ack=0;
end
always @(posedge {b['clock']}) actual_work_edge=$time;
always @(posedge {receipt}.clock) if(!Testbench.reset && !{receipt}.localReset) begin
  expected_meta={receipt}.in_req;expected_sync={receipt}.requestMeta;
  if(receipt_fire) begin
    #1;
    if(actual_work_edge!=$time-1) $fatal(1,"{PREFIX}_ACK_WITHOUT_WORK_EDGE");
  end
  if(!Testbench.workRunning) begin
    stopped_edges=stopped_edges+1;
    if(receipt_fire) $fatal(1,"{PREFIX}_STOPPED_ACCEPTANCE");
  end
  #1;
  if(!Testbench.reset && !{receipt}.localReset) begin
    if({receipt}.requestMeta !== expected_meta) $fatal(1,"{PREFIX}_REQUEST_META_CAPTURE");
    if({receipt}.requestSync !== expected_sync) $fatal(1,"{PREFIX}_REQUEST_SYNC_CAPTURE");
  end
end
always @(posedge {b['clock']}) if(!Testbench.reset) begin
  had_enq=enq;had_deq=deq;
  expected_first=first_q;expected_second=second_q;expected_count=occupancy;
  expected_ack={'~'+receipt+'.acknowledge' if b['variant']=='click' else "1'b1"};
  if(receipt_fire !== enq) $fatal(1,"{PREFIX}_ADMISSION_IDENTITY");
  if(enq) begin
    if((^native_payload)===1'bx || $time-source_change<=100000) $fatal(1,"{PREFIX}_SOURCE_SETUP");
    if($time-data_change<=100000) $fatal(1,"{PREFIX}_DESTINATION_SETUP");
    if($time-source_change<minimum_source_setup) minimum_source_setup=$time-source_change;
    if($time-data_change<minimum_destination_setup) minimum_destination_setup=$time-data_change;
    if(mailbox_d !== independently_expected) $fatal(1,"{PREFIX}_CONTEXT_OR_DATA");
    if(occupancy==2) $fatal(1,"{PREFIX}_IMPOSSIBLE_ACCEPTANCE");
    admission_seen=1;admission_time=$time;accepts=accepts+1;
    seen_one=seen_one|native_payload;seen_zero=seen_zero|~native_payload;
    seen_destination_one=seen_destination_one|mailbox_d;
    seen_destination_zero=seen_destination_zero|~mailbox_d;
    if(occupancy==0 || deq) begin expected_first=independently_expected; first_writes=first_writes+1; end
    else begin expected_second=independently_expected; second_writes=second_writes+1; end
    if(deq) simultaneous=simultaneous+1;else expected_count=occupancy+1;
  end else if(deq) begin
    expected_first=second_q;expected_count=occupancy-1;shifts=shifts+1;
  end
  #1;
  if(!Testbench.reset) begin
    if(first_q !== expected_first) $fatal(1,"{PREFIX}_FIRST_CAPTURE");
    if(second_q !== expected_second) $fatal(1,"{PREFIX}_SECOND_CAPTURE");
    if(occupancy !== expected_count) $fatal(1,"{PREFIX}_COUNT_CAPTURE");
    if(had_enq && {receipt}.acknowledge !== expected_ack) $fatal(1,"{PREFIX}_ACK_CAPTURE");
  end
end
always @({receipt}.acknowledge) if(!Testbench.reset && !{receipt}.localReset) begin
  #1;
  if({receipt}.acknowledge !== previous_ack) begin
    if({'1\'b1' if b['variant']=='click' else receipt+'.acknowledge'}) begin
      if(!admission_seen || $time!=admission_time+1) $fatal(1,"{PREFIX}_ACK_WITHOUT_ADMISSION");
    end else if({receipt}.requestSync) $fatal(1,"{PREFIX}_EARLY_BD_ACK_RETURN");
  end
  previous_ack={receipt}.acknowledge;
end
task finish_checks;
begin
  if(!accepts || !first_writes) $fatal(1,"{PREFIX}_NO_ACTIVITY");
  $display("{PREFIX}_ACTIVITY:%0d:%0d:%0d:%0d:%0d:%0d:%0d",accepts,first_writes,second_writes,shifts,simultaneous,stopped_edges,context_post_edge_changes);
  $display("{PREFIX}_SOURCE_ONES:%h",seen_one);$display("{PREFIX}_SOURCE_ZEROES:%h",seen_zero);
  $display("{PREFIX}_DEST_ONES:%h",seen_destination_one);$display("{PREFIX}_DEST_ZEROES:%h",seen_destination_zero);
  $display("{PREFIX}_MIN_FS:%0d:%0d:%0d:%0d",minimum_source_setup,minimum_destination_setup,minimum_source_hold,minimum_payload_hold);
end
endtask
'''


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
    for p in b['publisher']['primitives']:
        if p['parameters'].get('DELAY_FS') != '1000000':
            continue
        slow = profile!='minimum' and ((p['id'] in ('frame_payload', 'frame_phase')) == (profile == 'data-slow-control-fast'))
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


def supplemental(original, b, source, wrap=False):
    """New input-boundary experiment, separate from the unmodified wire oracle.

    All forced nodes are declared I2cPublication input pins. The source register,
    output request/ACK, receipt and destination registers are never forced.
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
    receipt = case / (b['receipt']['module'] + '.sv')
    if fault in ('first-data', 'second-data'):
        slot = fault.split('-')[0]
        text = top.read_text(encoding='utf-8')
        lhs = 'fabric_hostFrames_' + slot + '_frame_bytes_0'
        rhs = b['register_assignments'][lhs]
        pattern = r'(\b' + lhs + r'\s*<=\s*)' + re.escape(rhs) + r'(\s*;)'
        text, count = re.subn(pattern, lambda m: m[1] + "8'hff" + m[2], text)
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
    raise ValueError(PREFIX + '_MUTATION_KIND:' + fault)


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
    records = dict(status='RUNNING', source_index_sha256=sha(args.sources), source_sha256=originals,
                   tool_sha256=helper_hashes, cases={},
                   limit='Digital retained-source 100 ps aperture and actual mailbox capture; synchronous context physical hold not qualified')
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
    def simulate(variant, label, profile, fault=None, walk=False,wrap=False):
        fixture = loaded[variant][label]; b = fixture['bindings']
        name = '-'.join([variant, label, profile] + (['epoch-wrap'] if wrap else ['full337'] if walk else []) + ([fault] if fault else [])); case = out / name
        shutil.copytree(fixture['path'], case)
        original = supplemental(fixture['original'], b, fixture['path'],wrap=wrap) if walk or wrap else fixture['original']
        test, delays = skew(original, b, profile)
        test = instrument(test, b); (case / 'testbench.sv').write_text(test, encoding='utf-8')
        expected = 'I2C_RESET_EPOCH_WRAP' if wrap else mutate(case, b, fault) if fault else None
        entry = dict(source=str(fixture['path']), profile=profile, delay_changes=delays, fault=fault,
                     original_oracle_sha256=sha(fixture['path'] / 'testbench.sv'), oracle_sha256=sha(case / 'testbench.sv'),
                     original_assertions_preserved=not (walk or wrap), supplemental_input_campaign=walk,
                     actual_epoch_wrap_control=wrap, expected=expected,
                     source_sha256={f: sha(case / f) for f in fixture['files']},
                     exact_fatal_sites=[wrap_sites(case,b)] if wrap else assertion_sites(test, expected) if expected else [])
        records['cases'][name] = entry; save()
        entry['compile'], log = run(['iverilog', '-g2012', '-s', 'Testbench', '-o', 'frame-capture.vvp',
                                    *[str((case / f).resolve()) for f in fixture['files']], 'testbench.sv'], case, 'capture-compile.log')
        save(); require(entry['compile']['exit_code'] == 0, 'COMPILE:' + name + ':' + log[-2500:])
        entry['binary_sha256'] = sha(case / 'frame-capture.vvp')
        entry['simulation'], log = run(['vvp', 'frame-capture.vvp'], case, 'capture-simulation.log'); save()
        entry['actual_fatals'] = (classify_wrap(entry['compile'],entry['simulation'],log,entry['exact_fatal_sites'][0])
                                 if wrap else classify(entry['compile'], entry['simulation'], log, entry['exact_fatal_sites']))
        entry['activity'] = [s for s in log.splitlines() if s.startswith(PREFIX + '_')]
        require(entry['binary_sha256'] == sha(case / 'frame-capture.vvp') and entry['oracle_sha256'] == sha(case / 'testbench.sv'), 'EXECUTED_ARTIFACT_CHANGED')
        require(all(sha(case / f)==digest for f,digest in entry['source_sha256'].items()),'COMPILED_INPUT_CHANGED')
        entry['status'] = 'PASS'; save(); print(name, 'PASS', flush=True)
    try:
        save()
        for variant, group in loaded.items():
            for label in group:
                for profile in PROFILES:
                    simulate(variant, label, profile)
            for label in [key for key in group if key.startswith('slots')]:
                for profile in PROFILES:
                    simulate(variant, label, profile, walk=True)
            slot_label=next(key for key in group if key.startswith('slots'))
            for fault in ('first-data','second-data','receipt-data','data-hold','data-setup','publication-overwrite','epoch-bit63',
                          'source-reset','source-busy','same-edge-busy','sync-bypass','meta-disconnect','wrong-phase'):
                simulate(variant,slot_label,'original',fault,walk=True)
            reset_labels=[key for key in group if key.startswith('reset')]
            if reset_labels:
                simulate(variant,reset_labels[0],'original','ack-without-admission')
                simulate(variant,reset_labels[0],'original','work-enable-bypass')
            simulate(variant,slot_label,'original',wrap=True)
        require(all(hashes(Path(p)) == h for p, h in originals.items()), 'ORIGINAL_CHANGED')
        require(all(sha(p)==value for p,value in helper_hashes.items()),'HELPER_CHANGED')
        records.update(status='PASS', positives=sum(not e['expected'] for e in records['cases'].values()),
                       negatives=sum(bool(e['expected']) for e in records['cases'].values()), originals_preserved=True)
    except BaseException as error:
        records.update(status='FAILED', error=repr(error)); save(); raise
    save(); print('FRAME_CAPTURE_CONTROLS_PASS', flush=True)


if __name__ == '__main__':
    main()

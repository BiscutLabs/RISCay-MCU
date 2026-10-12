# SPDX-License-Identifier: Apache-2.0
"""Replay standalone frame receipt contracts and reject isolated actual RTL faults."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from check_frame_receipt import validate_frame_receipt_rtl
from check_i2c_wiring_controls import hashes
from check_program_return_fatals import fatal_sites, classify_fatal


def require(value, name):
    if not value:
        raise ValueError('FRAME_RECEIPT_CONTROL_' + name)


def change(text, pattern, replacement):
    updated, count = re.subn(pattern, lambda _: replacement, text)
    require(count == 1, 'MUTATION_ANCHOR')
    return updated


def mutate(text, fault, click):
    if fault == 'meta-disconnected':
        return change(text, r'requestMeta <= in_req;', "requestMeta <= 1'b0;")
    if fault == 'sync-bypassed':
        return change(text, r'requestSync <= requestMeta;', 'requestSync <= in_req;')
    if fault == 'ack-without-ready':
        return change(text, r'out_ready & (packed_6(?:_probe)?)', 'packed_6')
    if fault == 'return-or-phase':
        return (change(text, r'acknowledge <= requestSync;', 'acknowledge <= ~requestSync;') if click else
                change(text, r'requestSync & acknowledge;', 'in_req & acknowledge;'))
    if fault == 'por-ack-set':
        return change(text, r"acknowledge <= 1'h0;", "acknowledge <= 1'h1;")
    if fault == 'por-release-bypassed':
        return change(text, r'localReset_release_1 <= localReset_release_0;', "localReset_release_1 <= 1'h0;")
    raise ValueError('FRAME_RECEIPT_CONTROL_UNKNOWN_FAULT')


def instrument(test, path):
    """Add a reset-release witness without changing any existing assertion."""
    require(test.count('\nendmodule') == 1, 'TESTBENCH_SHAPE')
    monitor = f'''
integer receipt_release_edges=0;
always @(posedge {path}.clock or posedge {path}.reset) begin
  if({path}.reset) receipt_release_edges=0;
  else if(receipt_release_edges<2) receipt_release_edges=receipt_release_edges+1;
  #0.001;
  if({path}.localReset_release_1 !== (receipt_release_edges<2))
    $fatal(1,"FRAME_RECEIPT_POR_RELEASE_STAGES");
end
'''
    return test.replace('\nendmodule', monitor + '\nendmodule')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args=parser.parse_args()
    sources=json.loads(args.sources.read_text(encoding='utf-8'))
    require(set(sources)=={'bd','click'} and all(set(g)=={'bits','gate','por'} for g in sources.values()), 'SOURCE_INVENTORY')
    out=args.out.resolve(); require(not out.exists(), 'OUTPUT_EXISTS')
    for group in sources.values():
        for path in group.values():
            p=Path(path).resolve()
            require(not out.is_relative_to(p) and not p.is_relative_to(out), 'SOURCE_OVERLAP')
    out.mkdir(parents=True)
    sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    helpers=(Path(__file__),Path(__file__).with_name('check_frame_receipt.py'),
             Path(__file__).with_name('check_i2c_wiring_controls.py'),Path(__file__).with_name('check_program_return_fatals.py'))
    result=dict(status='RUNNING', source_index_sha256=sha(args.sources),
        tools_sha256={str(p.resolve()):sha(p) for p in helpers}, cases={})
    def save():
        (out/'results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    def run(command, directory, label):
        completed=subprocess.run(command,cwd=directory,text=True,capture_output=True,timeout=60)
        log=completed.stdout+completed.stderr
        p=directory/(label+'.log');p.write_text(log,encoding='utf-8')
        return dict(command=command,exit_code=completed.returncode,timed_out=False,log_sha256=sha(p)),log
    try:
        for variant, group in sources.items():
            click=variant=='click'
            jobs=[(k,None,None) for k in group]+[
                ('bits','meta-disconnected','FRAME_RECEIPT_OFFER'),
                ('bits','sync-bypassed','FRAME_RECEIPT_SYNC_BYPASS'),
                ('gate','ack-without-ready','FRAME_RECEIPT_ACK_WITHOUT_WORK_EDGE'),
                ('bits','return-or-phase','FRAME_RECEIPT_DESTINATION_CAPTURE' if click else 'FRAME_RECEIPT_UNSYNCHRONIZED_RETURN'),
                ('por','por-ack-set','FRAME_RECEIPT_POR_PRECONDITION' if click else 'FRAME_RECEIPT_POR_ASSERTION'),
                ('por','por-release-bypassed','FRAME_RECEIPT_POR_RELEASE_STAGES')]
            for label,fault,expected in jobs:
                source=Path(group[label]).resolve(); original=hashes(source)
                manifest=json.loads((source/'contract.json').read_text(encoding='utf-8'))['manifest']
                require(manifest['top']=='FrameReceiptFixture', 'TOP')
                node=next(c['contract'] for c in manifest['design']['children'] if c['id']=='receipt')
                require(node['module']==('ClickFrameReceipt' if click else 'FourPhaseFrameReceipt'), 'VARIANT')
                rtl=node['module']+'.sv'
                before=(source/rtl).read_text(encoding='utf-8');validate_frame_receipt_rtl(node,before)
                baseline_log=(source/'simulation.log').read_text(encoding='utf-8')
                require(baseline_log.count('RISCAY_SOC_PASS')==1 and not re.search(r'FATAL|TIMEOUT|DEADLINE',baseline_log), 'SOURCE_NOT_PASS')
                name=variant+'-'+label+'-'+(fault or 'positive');case=out/name;shutil.copytree(source,case)
                tb=(source/'testbench.sv').read_text(encoding='utf-8')
                path='dut.'+node['rtl_path'].split('.',1)[1]
                augmented=instrument(tb,path);(case/'testbench.sv').write_text(augmented,encoding='utf-8')
                if fault:(case/rtl).write_text(mutate(before,fault,click),encoding='utf-8')
                files=[line.strip() for line in (case/'filelist.f').read_text(encoding='utf-8').splitlines() if line.strip()]
                require(files and len(files)==len(set(files)) and all((case/f).resolve().is_relative_to(case) and (case/f).is_file() for f in files), 'FILELIST')
                record=dict(source=str(source),source_sha256=original,expected=expected,
                    original_assertions_preserved=True,testbench_sha256=sha(case/'testbench.sv'),
                    rtl_sha256={f:sha(case/f) for f in files},fatal_sites=fatal_sites(augmented,[expected]) if expected else [])
                result['cases'][name]=record;save()
                record['compile'],log=run(['iverilog','-g2012','-s','Testbench','-o','receipt.vvp',
                    *[str((case/f).resolve()) for f in files],'testbench.sv'],case,'compile')
                require(record['compile']['exit_code']==0,'COMPILE:'+name+':'+log[-1200:])
                record['binary_sha256']=sha(case/'receipt.vvp')
                record['simulation'],log=run(['vvp','receipt.vvp'],case,'run');save()
                if expected:record['fatal_records']=classify_fatal(record['compile'],record['simulation'],log,record['fatal_sites'])
                else:require(record['simulation']['exit_code']==0 and log.count('RISCAY_SOC_PASS')==1 and
                    not re.search(r'FATAL|TIMEOUT|DEADLINE',log),'POSITIVE:'+name)
                require(original==hashes(source) and record['binary_sha256']==sha(case/'receipt.vvp') and
                    record['testbench_sha256']==sha(case/'testbench.sv') and record['rtl_sha256']=={f:sha(case/f) for f in files},'ARTIFACT_CHANGED')
                record['status']='PASS';save();print(name,'PASS',flush=True)
        require(result['tools_sha256']=={str(p.resolve()):sha(p) for p in helpers},'TOOLS_CHANGED')
        result.update(status='PASS',positives=6,faults=12);save()
    except BaseException as error:
        result.update(status='FAILED',error=repr(error));save();raise
    print('FRAME_RECEIPT_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()

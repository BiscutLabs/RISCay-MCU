# SPDX-License-Identifier: Apache-2.0
"""Mutate actual program ownership RTL while preserving independent test oracles."""
import argparse,copy,hashlib,json,re,shutil
from pathlib import Path
from check_i2c_wiring_controls import hashes,run
from check_admission_controls import replace_pin
from check_program_source_export import validate_program_source


def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError("PROGRAM_CONTROL_MUTATION_SHAPE:"+old)
    return text.replace(old,new)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--sources",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args();sources=json.loads(args.sources.read_text())
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False);results={};commands=[]
    def record():
        (out/"results.json").write_text(json.dumps(results,indent=2)+"\n")
        (out/"commands.json").write_text(json.dumps(commands,indent=2)+"\n")
    def simulate(label,source,native,mutation=None,oracle_path='seed-1/testbench.sv',child=None):
        source=Path(source).resolve()
        if out.is_relative_to(source):raise ValueError("PROGRAM_CONTROLS_OVERLAP_SOURCE")
        before=hashes(source);case=out/label
        shutil.copytree(source/"export" if native else source,case)
        if native:shutil.copy2(source/oracle_path,case/'testbench.sv')
        manifest=json.loads((case/'contract.json').read_text())['manifest']
        model=manifest['top'] if child is None else next(c['contract']['module'] for c in manifest['design']['children'] if c['id']==child)
        rtl=case/(model+'.sv')
        oracle=hashlib.sha256((case/'testbench.sv').read_bytes()).hexdigest()
        if mutation:rtl.write_text(mutation(rtl.read_text(),manifest),encoding='utf-8')
        files=[str((case/x.strip()).resolve()) for x in (case/'filelist.f').read_text().splitlines() if x.strip()]
        compiled,log=run(['iverilog','-g2012','-s','Testbench','-o','control.vvp',*files,'testbench.sv'],case,'control-compile.log',commands)
        assert compiled['exit_code']==0,log[-4000:]
        simulated,log=run(['vvp','control.vvp'],case,'control-simulation.log',commands)
        results[label]=dict(compile=compiled,simulation=simulated,oracle_sha256=oracle,
            rtl_sha256=hashlib.sha256(rtl.read_bytes()).hexdigest(),source=str(source),mutated=mutation is not None)
        record()
        assert (simulated['exit_code']==0)==(mutation is None),log[-4000:]
        if mutation:
            assert any(x in log for x in ('PROGRAM_SOURCE_','HANDSHAKE_ORDER','PROTOCOL_',
                'TIMING_LONG_HOLD_FORK','DATA_HOLD','STORED_RECEIPT_')),log[-4000:]
            assert 'DEADLINE' not in log and 'TIMEOUT' not in log,log[-4000:]
        else:assert ('CA_TEST_PASS' in log if native else 'RISCAY_SOC_PASS' in log),log[-4000:]
        assert hashlib.sha256((case/'testbench.sv').read_bytes()).hexdigest()==oracle,'PROGRAM_ORACLE_CHANGED'
        assert hashes(source)==before,'ORIGINAL_PROGRAM_EVIDENCE_CHANGED'
        results[label]['original_preserved']=True;record();print(label,'PASS',flush=True)
    for variant in ('bd','click'):
        s=sources[variant]
        node=json.loads((Path(s['native'])/'export/contract.json').read_text())['manifest']['design']
        validate_program_source(node);bad_nodes=[]
        for field,value in (('module','ClockedOwner'),('capacity',2)):
            bad=copy.deepcopy(node);bad[field]=value;bad_nodes.append(bad)
        for i in range(5):
            for field,value in (('signed',True),('width',2),('lsb',1),('source','wrong')):
                bad=copy.deepcopy(node);bad['channels'][i]['layout'][0][field]=value;bad_nodes.append(bad)
        for i,p in enumerate(node['primitives']):
            bad=copy.deepcopy(node);bad['primitives'][i]['reset']='reset' if p['reset']!='reset' else 'eligibility_reset';bad_nodes.append(bad)
            if 'DELAY_FS' in p['parameters']:
                bad=copy.deepcopy(node);bad['primitives'][i]['parameters']['DELAY_FS']='0';bad_nodes.append(bad)
        for i in range(len(node['timing'])):
            bad=copy.deepcopy(node);bad['timing'].pop(i);bad_nodes.append(bad)
        for i in range(2):
            bad=copy.deepcopy(node);bad['children'][i]['contract']['module']='FourPhaseAdapter';bad_nodes.append(bad)
        for bad in bad_nodes:
            try:validate_program_source(bad)
            except ValueError:pass
            else:raise AssertionError('PROGRAM_METADATA_MUTATION_ACCEPTED')
        results[variant+'-metadata']=dict(rejected=len(bad_nodes));record()
        def primitive(m,id):return next(p['rtl_path'].rsplit('.',1)[1] for p in m['design']['primitives'] if p['id']==id)
        def pin(text,m,id,port,value):return replace_pin(text,primitive(m,id),port,value)
        def child_reset(text,m,id):
            child=next(c['contract'] for c in m['design']['children'] if c['id']==id)
            return replace_pin(text,child['rtl_path'].rsplit('.',1)[1],'reset','reset | applicationReset')
        simulate(variant+'-native-baseline',s['native'],True)
        simulate(variant+'-reservation-reset',s['native'],True,lambda t,m:child_reset(t,m,'reservation'))
        simulate(variant+'-eligibility-reset-bypass',s['native'],True,lambda t,m:pin(t,m,'eligibility','reset','reset'))
        simulate(variant+'-late-arm',s['native'],True,lambda t,m:pin(t,m,'eligibility','trigger','grant_ack'))
        if variant=='click':
            def grant_guard_bypass(t,m):
                pattern=r'(ChiselAsyncControlGate_v1\s+#\(\s*\.DELAY_FS\()241200001(\),(?:\s*\.\w+\([^)]*\),?)+\s*\)\s+'+re.escape(primitive(m,'output_guard'))+r'\s*\()'
                changed,count=re.subn(pattern,lambda x:x[1]+'1'+x[2],t)
                if count!=1:raise ValueError('PROGRAM_GRANT_GUARD_MUTATION_SHAPE')
                return changed
            simulate('click-grant-guard-bypass',s['native'],True,grant_guard_bypass)
            oracle='selected-skew-publication/testbench.sv'
            simulate('click-selection-baseline',s['publication_native'],True,oracle_path=oracle)
            simulate('click-selection-guard-bypass',s['publication_native'],True,
                lambda t,m:pin(t,m,'decision_pending','a','decision_req'),oracle_path=oracle)
        simulate(variant+'-mixed-baseline',s['mixed'],True)
        def flip_tag(t,m):
            changed,count=re.subn(r'(assign ownerLoader\s*=\s*)([^;]+);',lambda x:x[1]+'~('+x[2]+');',t)
            if count!=1:raise ValueError('PROGRAM_TAG_MUTATION_SHAPE:'+str(count))
            return changed
        simulate(variant+'-owner-tag-flipped',s['mixed'],True,flip_tag)
        def selected_without(t,m,publication=True):
            if variant=='bd':
                return pin(t,m,'stored_offer_nb' if publication else 'stored_selected_nb','a',
                    primitive(m,'request_guard')+'.q' if publication else 'decision_bits')
            selected='decision_bits & ca_child_reservation.out_bits' if publication else 'decision_bits & '+primitive(m,'publication_pending')+'.q'
            expr='{'+primitive(m,'owned')+'.q,('+primitive(m,'armed_phase')+'.q[0] == reserved),'+primitive(m,'decision_pending')+'.q,('+selected+'),'+primitive(m,'stored_pending')+'.q}'
            return pin(t,m,'stored_request_delay','a',expr)
        simulate(variant+'-stored-before-publication',s['mixed'],True,lambda t,m:selected_without(t,m,True))
        simulate(variant+'-cpu-issues-stored',s['mixed'],True,lambda t,m:selected_without(t,m,False))
        simulate(variant+'-stored-baseline',s['stored_native'],True)
        def bypass_stored(t,m):
            if variant=='click':return pin(t,m,'stored_retired_nb','a',"1'b1")
            expr='{reserved,'+primitive(m,'request_guard')+".q,(!decision_bits | publication_req),wordDrained,(!grant_req & !grant_ack),1'b1}"
            return pin(t,m,'retirement','rising',expr)
        simulate(variant+'-stored-receipt-bypass',s['stored_native'],True,bypass_stored)
        if variant=='bd':
            simulate('bd-return-baseline',s['return'],True)
            simulate('bd-stored-return-bypass',s['return'],True,
                lambda t,m:pin(t,m,'reservation_return','falling',"{decision_ack,publication_ack,reserved,4'b0}"))
        else:
            simulate('click-stored-phase-reset',s['mixed'],True,lambda t,m:pin(t,m,'stored_phase','reset','reset | applicationReset'))
        simulate(variant+'-effects-baseline',s['effects'],False)
        simulate(variant+'-premature-publication',s['effects'],False,
            lambda t,m:replace_pin(t,'ca_child_program_publication_bridge','in_valid','wordAccepted'))
        simulate(variant+'-late-baseline',s['late'],False)
        simulate(variant+'-stored-ack-bypass',s['late'],False,
            lambda t,m:replace_pin(t,'ca_child_program_stored_bridge','out_ready',"1'b1"))
        simulate(variant+'-publication-baseline',s['publication'],False)
        simulate(variant+'-reset-debt-bypass',s['publication'],False,
            lambda t,m:replace_once(t,"programResetDebt <= 1'h1;","programResetDebt <= 1'h0;"))
        simulate(variant+'-busy-baseline',s['busy'],False)
        def busy_bypass(t,m):
            pattern=r'(fabric_hostFrames_first_programBusy\s*<=\s*)fabric_hostFrames_io_enq_bits_programBusy;'
            changed,count=re.subn(pattern,lambda x:x[1]+"1'h0;",t)
            if count!=2:raise ValueError('PROGRAM_BUSY_MUTATION_SHAPE:'+str(count))
            return changed
        simulate(variant+'-admission-busy-history-bypass',s['busy'],False,busy_bypass)
        simulate(variant+'-receipt-baseline',s['receipt'],False)
        simulate(variant+'-receipt-sync-bypass',s['receipt'],False,
            lambda t,m:replace_once(t,'requestSync <= requestMeta;','requestSync <= in_req;'),child='receipt')
        simulate(variant+'-receipt-ready-bypass',s['receipt'],False,
            lambda t,m:replace_pin(t,'ca_child_receipt','out_ready',"1'b1"))
        simulate(variant+'-receipt-payload-inverted',s['receipt'],False,
            lambda t,m:replace_pin(t,'ca_child_receipt','in_bits','!data'))
        simulate(variant+'-receipt-application-reset',s['receipt'],False,
            lambda t,m:replace_pin(t,'ca_child_receipt','reset','reset | applicationReset'))
    print('ALL_PROGRAM_SOURCE_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()

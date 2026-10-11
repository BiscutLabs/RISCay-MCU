# SPDX-License-Identifier: Apache-2.0
"""Mutate actual publication receipt ownership RTL while preserving independent test oracles."""
import argparse,copy,hashlib,json,re,shutil
from pathlib import Path
from check_i2c_wiring_controls import hashes,run
from check_admission_controls import replace_pin
from check_publication_source_export import validate_publication_source


def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError("PUBLICATION_CONTROL_MUTATION_SHAPE:"+old)
    return text.replace(old,new)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--sources",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--native-only",action="store_true",help="Diagnostic native preflight; not full integration qualification")
    args=parser.parse_args();sources=json.loads(args.sources.read_text())
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False);results={'scope':dict(native_only=args.native_only)};commands=[]
    def record():
        (out/"results.json").write_text(json.dumps(results,indent=2)+"\n")
        (out/"commands.json").write_text(json.dumps(commands,indent=2)+"\n")
    def simulate(label,source,native,mutation=None,oracle_path='seed-1/testbench.sv',child=None):
        source=Path(source).resolve()
        if out.is_relative_to(source):raise ValueError("PUBLICATION_CONTROLS_OVERLAP_SOURCE")
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
            assert any(x in log for x in ('PUBLICATION_','RECOVERY_','HANDSHAKE_ORDER','PROTOCOL_',
                'TIMING_LONG_HOLD_FORK','DATA_HOLD')),log[-4000:]
            assert 'DEADLINE' not in log and 'TIMEOUT' not in log,log[-4000:]
        else:assert ('CA_TEST_PASS' in log if native else 'RISCAY_SOC_PASS' in log),log[-4000:]
        assert hashlib.sha256((case/'testbench.sv').read_bytes()).hexdigest()==oracle,'PUBLICATION_ORACLE_CHANGED'
        assert hashes(source)==before,'ORIGINAL_PUBLICATION_EVIDENCE_CHANGED'
        results[label]['original_preserved']=True;record();print(label,'PASS',flush=True)
    for variant in ('bd','click'):
        s=sources[variant]
        node=json.loads((Path(s['mixed'])/'export/contract.json').read_text())['manifest']['design']
        validate_publication_source(node);bad_nodes=[]
        for field,value in (('module','ClockedOwner'),('capacity',2)):
            bad=copy.deepcopy(node);bad[field]=value;bad_nodes.append(bad)
        for i in range(5):
            for j,entry in enumerate(node['channels'][i]['layout']):
                for field,value in (('signed',True),('width',2),('lsb',entry['lsb']+1),('source','wrong'),('field','wrong')):
                    bad=copy.deepcopy(node);bad['channels'][i]['layout'][j][field]=value;bad_nodes.append(bad)
            for field,value in (('protocol','four-phase-bundled-v1' if variant=='click' else 'two-phase-bundled-v1'),('role','invalid')):
                bad=copy.deepcopy(node);bad['channels'][i][field]=value;bad_nodes.append(bad)
        for i,p in enumerate(node['primitives']):
            bad=copy.deepcopy(node);bad['primitives'][i]['reset']='reset' if p['reset']!='reset' else 'eligibility_reset';bad_nodes.append(bad)
            for field in p['parameters']:
                bad=copy.deepcopy(node);bad['primitives'][i]['parameters'][field]=str(int(p['parameters'][field])+1);bad_nodes.append(bad)
        for i in range(len(node['timing'])):
            bad=copy.deepcopy(node);bad['timing'].pop(i);bad_nodes.append(bad)
            timing=node['timing'][i]
            fields=('source','sink','delay_cell','logic') if timing['kind']=='bundled-data-path-v1' else (
                'launch','transaction','data_valid','capture','captured')
            for field in fields:
                bad=copy.deepcopy(node);bad['timing'][i][field]='wrong';bad_nodes.append(bad)
            if timing['kind']=='bundled-data-path-v1':
                for field in ('min_fs','max_fs','model_fs'):
                    bad=copy.deepcopy(node);bad['timing'][i]['budget'][field]='1';bad_nodes.append(bad)
            else:
                for field in ('setup_fs','hold_fs'):
                    bad=copy.deepcopy(node);bad['timing'][i][field]='1';bad_nodes.append(bad)
        for i in range(len(node['endpoints'])):
            bad=copy.deepcopy(node);bad['endpoints'][i]['width']+=1;bad_nodes.append(bad)
        bad=copy.deepcopy(node);bad['children'][0]['contract']['module']='FourPhaseAdapter';bad_nodes.append(bad)
        for i,channel in enumerate(node['children'][0]['contract']['channels']):
            for j in range(len(channel['layout'])):
                bad=copy.deepcopy(node);bad['children'][0]['contract']['channels'][i]['layout'].pop(j);bad_nodes.append(bad)
        for bad in bad_nodes:
            try:validate_publication_source(bad)
            except ValueError:pass
            else:raise AssertionError('PUBLICATION_METADATA_MUTATION_ACCEPTED')
        results[variant+'-metadata']=dict(rejected=len(bad_nodes));record()
        def primitive(m,id):return next(p['rtl_path'].rsplit('.',1)[1] for p in m['design']['primitives'] if p['id']==id)
        def pin(text,m,id,port,value):return replace_pin(text,primitive(m,id),port,value)
        def reservation_reset(text,m):
            child=m['design']['children'][0]['contract']
            return replace_pin(text,child['rtl_path'].rsplit('.',1)[1],'reset','reset | applicationReset')
        simulate(variant+'-mixed-baseline',s['mixed'],True)
        simulate(variant+'-reservation-reset',s['mixed'],True,reservation_reset)
        simulate(variant+'-eligibility-reset-bypass',s['mixed'],True,lambda t,m:pin(t,m,'eligibility','reset','reset'))
        simulate(variant+'-late-arm',s['mixed'],True,lambda t,m:pin(t,m,'eligibility','trigger','grant_ack'))
        def flip_grant(t,m):
            changed,count=re.subn(r'(assign grant_bits_tag\s*=\s*)([^;]+);',lambda x:x[1]+'~('+x[2]+');',t)
            if count!=1:raise ValueError('PUBLICATION_TAG_MUTATION_SHAPE')
            return changed
        simulate(variant+'-grant-payload-flipped',s['mixed'],True,flip_grant)
        def retirement(t,m,omit):
            if variant=='click':
                name={'publication':'retire_effect_nb','drain':'retire_decision_na','decision':'retire_decision_nb'}[omit]
                return pin(t,m,name,'a',"1'b1")
            values=['reserved',primitive(m,'request_guard')+'.q',
                '(!decision_bits | ('+primitive(m,'drain_issue')+'.q & drain_ack))',
                '(!decision_bits | '+primitive(m,'receipt_seen')+'.q | !eligible)',
                '(!publication_req & !publication_ack)','(!grant_req & !grant_ack)']
            values[{'publication':3,'drain':2,'decision':1}[omit]]="1'b1"
            return pin(t,m,'retirement','rising','{'+','.join(values)+'}')
        simulate(variant+'-required-baseline',s['required'],True)
        simulate(variant+'-missing-publication-accepted',s['required'],True,lambda t,m:retirement(t,m,'publication'))
        simulate(variant+'-missing-drain-accepted',s['mixed'],True,lambda t,m:retirement(t,m,'drain'))
        simulate(variant+'-missing-decision-accepted',s['mixed'],True,lambda t,m:retirement(t,m,'decision'))
        if variant=='bd':
            simulate('bd-return-baseline',s['return'],True)
            simulate('bd-drain-return-bypass',s['return'],True,lambda t,m:pin(t,m,'reservation_return','falling',
                '{decision_ack,publication_req,publication_ack,reserved,'+primitive(m,'receipt_seen')+
                ".q,drain_req,1'b0,"+primitive(m,'recovery_clear')+'.q}'))
        else:
            for phase in ('publication_phase','drain_phase'):
                simulate('click-'+phase+'-application-reset',s['mixed'],True,
                    lambda t,m,phase=phase:pin(t,m,phase,'reset','reset | applicationReset'))
        if args.native_only:continue
        for case in ('atomic','cancel','staged','held','drain','housekeeping_held','housekeeping_drain','recovery_return'):
            simulate(variant+'-'+case+'-baseline',s[case],False)
        for owner in ('telemetry','housekeeping'):
            # Wrong grant payload violates the production atomic-commit assertion.
            def grant_bit(t,m,owner=owner):
                block=re.search(r'\bca_child_'+owner+r'_grant_bridge\s*\((.*?)\n\s*\);',t,re.S)
                if not block:raise ValueError('PUBLICATION_GRANT_INSTANCE')
                values=re.findall(r'\.in_bits_tag\s*\(([^()]*)\)',block[1]);assert len(values)==1
                return replace_pin(t,'ca_child_'+owner+'_grant_bridge','in_bits_tag','!'+values[0].strip())
            simulate(variant+'-'+owner+'-grant-payload',s['atomic'],False,grant_bit)
            def debt_reset(t,m,owner=owner):
                return replace_once(t,owner+"ReturnFence <= 1'h1;",owner+"ReturnFence <= 1'h0;")
            # Native sticky debt now independently remembers raw reset. The
            # retained fence has a distinct job after debt clears; use that
            # unchanged return-window oracle to detect its reset corruption.
            simulate(variant+'-'+owner+'-return-fence',s['recovery_return'],False,debt_reset)
        for owner in ('telemetry','housekeeping'):
            key='' if owner=='telemetry' else 'housekeeping_'
            simulate(variant+'-'+owner+'-drain-acceptance-bypass',s[key+'drain'],False,
                lambda t,m,owner=owner:replace_pin(t,'ca_child_'+owner+'_drain_bridge','out_ready',"1'b1"))
            simulate(variant+'-'+owner+'-publication-acceptance-bypass',s[key+'held'],False,
                lambda t,m,owner=owner:replace_pin(t,'ca_child_'+owner+'_publication_bridge','in_valid',"1'b0"))
    print('NATIVE_PUBLICATION_SOURCE_PREFLIGHT_PASS' if args.native_only else 'ALL_PUBLICATION_SOURCE_CONTROLS_PASS',flush=True)


if __name__=='__main__':main()

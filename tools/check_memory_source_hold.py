# SPDX-License-Identifier: Apache-2.0
"""Check publication-ACK inhibition before the existing decision bridge can reuse data.

The pinned DecoupledToFourPhase bridge captures data only in idle. ACK falling
passes meta E0, sync E1, return-to-idle E2, then earliest acceptance E3. Services
also admits each decision only with a new grant. Credit only ONE existing work
period; the other two periods, source CQ and new-grant latency receive no credit.
This is a composed internal-port contract, not an arbitrary four-phase source.
"""
import argparse,json,sys
from pathlib import Path
import check_memory_owner_timing as t


def run(mapping,export,out):
    policy=json.loads((mapping/'physical-policy.json').read_text(encoding='utf-8'))
    t.require(policy['service_max_hz']==20_000_000,'SOURCE_HOLD_MAX_CLOCK')
    period_ns=1e9/policy['service_max_hz']
    bridges=sorted(export.glob('DecoupledToFourPhase*.sv'))
    t.require(bridges,'SOURCE_HOLD_BRIDGE_EVIDENCE')
    inputs=[*t.input_files(mapping),mapping/'timing-intent.json',mapping/'physical-policy.json',
        mapping/'electrical-repair/receipt.json',mapping/'electrical-repair/proof.json',
        mapping/'electrical-repair/reference/netlist.json',*bridges,
        t.ROOT/'designs/four-phase-bd/src/main/scala/riscay/bd/FourPhasePlatform.scala',
        t.ROOT/'designs/four-phase-bd/src/main/scala/riscay/bd/FourPhaseServices.scala']
    sources=[Path(__file__),Path(t.__file__),t.relative.PROBE,*[Path(m.__file__) for m in list(sys.modules.values())
        if getattr(m,'__file__',None) and Path(m.__file__).parent==t.ROOT/'tools'],*t.tool('sta').input_files()]
    receipt=t.RunReceipt(out/'receipt.json',inputs=inputs,tools=sources);status='fail';cases=[]
    try:
        out.mkdir(parents=True,exist_ok=False);b=t.bind_source(mapping);sta=t.tool('sta')
        for name,o in b['owners'].items():
            p=o['prefix'];pr=o['primitives'];index=b['index']
            root=o['ports']['decision_ack'][0]['source']
            path=pr['publication_ack_ca_primitive_publication_ack_or']['path']
            targets=sorted({pin for row in index.boundary(path,'a') for pin in row['complete_fanout'] if pin.startswith(path+'/')})
            t.require(targets,'SOURCE_ACK_INHIBIT_LEAVES')
            ctx=t.context('ack-guard',[root],t.query(targets,'inhibit','fall',('rise',)),
                [('port','reset',0),('pin',o['ports']['applicationReset'][0]['source'],0)],b['cuts'])
            plan=dict(native=o['native'])
            for corner in t.relative.CORNERS:
                lib=t.library(t.ROOT/'.tools/physical/pdk'/(t.SC+corner+'.lib'))
                for slew in (.02,2.):
                    d=out/name/corner/str(slew);d.mkdir(parents=True)
                    result=t.audit_paths(t.leaf_case(mapping,d,plan,index,ctx,corner,slew,sta,1000,lib),d,index,lib)
                    latest=max(v['delay_ns'] for k,v in result['rows'].items() if ':max:' in k)
                    case=dict(owner=name,corner=corner,slew=slew,inhibit_max_ns=latest,
                        hold_credit_ns=period_ns,margin_ns=.8*period_ns-1.2*latest-2,result=result)
                    cases.append(case);t.write_json(out/'measurements.json',dict(cases=cases))
                    t.require(not result['table_ranges']['range_errors'] and not result['pin_electrical_errors'],'SOURCE_ACK_INHIBIT_ELECTRICAL')
                    print(name,corner,slew,'inhibit',round(latest,6),'margin',round(case['margin_ns'],6),flush=True)
        expected={(o,c,s) for o in b['owners'] for c in t.relative.CORNERS for s in (.02,2.)}
        actual=[(c['owner'],c['corner'],c['slew']) for c in cases]
        t.require(len(actual)==len(set(actual)) and set(actual)==expected,'SOURCE_ACK_INHIBIT_COVERAGE')
        t.require(all(c['margin_ns']>=0 for c in cases),'SOURCE_ACK_INHIBIT_HOLD')
        t.write_json(out/'summary.json',dict(scope='Local zero-wire-RC hold from existing retained work-clock decision bridge; no new clock or timing waiver',
            credited_period_ns=period_ns,minimum_margin_ns=min(c['margin_ns'] for c in cases)))
        status='pass'
    finally:receipt.finish(outputs=sorted(p for p in out.rglob('*') if p.is_file()),status=status)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('mapping','export','output'):parser.add_argument('--'+name,type=Path,required=True)
    a=parser.parse_args();run(a.mapping,a.export,a.output)

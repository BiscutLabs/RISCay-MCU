# SPDX-License-Identifier: Apache-2.0
"""Paired native-model ACK activity and explicit representative guard-cell energy."""
import argparse
import json
import math
from pathlib import Path
import re
import statistics

from gf180_estimate import cell_metrics, direct_groups, library, scalar, table_value
from gf180_physical import ROOT, SC, sha, write_json
from repair_gf180_control import require


def read_wakes(path, guard_ns=None):
    text=path.read_text()
    require(text.count('ESTIMATE_ACTIVITY_COMPLETE')==1 and text.count('RISCAY_SOC_PASS')==1
            and not re.search(r'FATAL|ERROR',text),'ACK_ACTIVITY_INCOMPLETE')
    wakes=[];acks=[]
    for line in text.splitlines():
        x=line.split(',')
        if x[0]=='WAKE':
            require(len(x)==7,'ACK_ACTIVITY_WAKE_SHAPE')
            w=dict(zip(('phase','fast','work','retired','adc'),map(int,x[1:6])),ns=float(x[6]))
            require(0<w['work']<=w['fast'] and math.isfinite(w['ns']) and w['ns']>0,'ACK_ACTIVITY_WAKE')
            wakes.append(w)
        if x[0]=='ACK_GUARD':
            require(len(x)==5 and guard_ns is not None,'ACK_ACTIVITY_GUARD_SHAPE')
            rises,falls=map(int,x[1:3]);wait,delay=map(float,x[3:])
            require(rises==falls and rises>=0 and delay==guard_ns and
                math.isclose(wait,(rises+falls)*delay,abs_tol=.001),'ACK_ACTIVITY_EDGE_ACCOUNTING')
            acks.append(dict(rises=rises,falls=falls,sum_wait_ns=wait))
    require(wakes and (len(acks)==len(wakes) if guard_ns is not None else not acks),'ACK_ACTIVITY_ROW_COUNT')
    for w,a in zip(wakes,acks):w.update(a)
    result={}
    for kind,predicate in (('maintenance',lambda w:not w['adc'] and not w['retired']),
                           ('sample',lambda w:w['adc'] and not w['retired']),
                           ('firmware',lambda w:w['retired']>0)):
        rows=[w for w in wakes if predicate(w)]
        require(len(rows)>=2,'ACK_ACTIVITY_INSUFFICIENT_'+kind.upper())
        require(kind!='firmware' or all(w['retired']==43 for w in rows),'ACK_ACTIVITY_WORKLOAD_CHANGED')
        result[kind]=dict(observations=len(rows),**{k:statistics.mean(w[k] for w in rows) for k in rows[0] if k!='phase'})
    return wakes,result


def compare(normal,bypass):
    require(len(normal)==len(bypass),'ACK_ACTIVITY_UNMATCHED_WAKE_COUNT')
    for a,b in zip(normal,bypass):
        require(all(a[k]==b[k] for k in ('phase','retired','adc','rises','falls')),'ACK_ACTIVITY_UNMATCHED_WORKLOAD')
    return [{k:a[k]-b[k] for k in ('fast','work','ns')} for a,b in zip(normal,bypass)]


def matched_exports(normal,bypass):
    def sources(folder):return {p.relative_to(folder).as_posix():p for p in folder.rglob('*')
        if p.is_file() and p.suffix in ('.sv','.v','.json','.f')}
    a,b=sources(normal),sources(bypass)
    require(a.keys()==b.keys() and {'testbench.sv','maximum-delays.json','contract.json','filelist.f','FourPhaseSoc.sv'}<=a.keys(),
            'ACK_ACTIVITY_EXPORT_INVENTORY')
    require(json.loads(a['maximum-delays.json'].read_text())=={} and
        json.loads(b['maximum-delays.json'].read_text())=={'FourPhaseSoc.ca_child_control.ca_primitive_acknowledge_guard':'1000'},
        'ACK_ACTIVITY_OVERRIDE_BINDING')
    tb=b['testbench.sv'].read_text()
    changes=[('defparam dut.soc.ca_child_control.ca_primitive_acknowledge_guard.DELAY_FS=1000;','')]
    changes += [(f'$realtime-{edge} {op} 0.001{sign}0.0005',f'$realtime-{edge} {op} 32.0{sign}0.0005')
        for edge in ('ackRiseAt','ackFallAt') for op,sign in (('<','-'),('>','+'))]
    changes += [('ackRiseEdges,ackFallEdges,ackWaitNs,0.001);','ackRiseEdges,ackFallEdges,ackWaitNs,32.0);')]
    for old,new in changes:
        require(tb.count(old)==1,'ACK_ACTIVITY_OVERRIDE_SHAPE');tb=tb.replace(old,new)
    require(tb==a['testbench.sv'].read_text(),'ACK_ACTIVITY_HARNESS_CHANGED')
    for name in a.keys()-{'testbench.sv','maximum-delays.json'}:
        require(sha(a[name])==sha(b[name]),'ACK_ACTIVITY_EXPORT_CHANGED_'+name)
    return {str(p.resolve()):sha(p) for p in [*a.values(),*b.values()]}


def guard_energy(mapping):
    m=json.loads((mapping/'mapping.json').read_text())
    matches=[b for b in m['bindings'] if any(x.endswith('ca_child_control.ca_primitive_acknowledge_guard') for x in b['instances'])]
    require(len(matches)==1,'ACK_ACTIVITY_GUARD_BINDING')
    cells=matches[0]['cells']
    require(sum(c['cell']==SC+'and2_1' for c in cells)==1 and sum(c['cell']==SC+'inv_1' for c in cells)==1
        and all(c['cell'] in (SC+'and2_1',SC+'inv_1',SC+'dlyd_1') for c in cells),'ACK_ACTIVITY_GUARD_RECIPE')
    libpath=ROOT/'.tools/physical/pdk'/(SC+'tt_025C_3v30.lib');lib=library(libpath)
    voltage=3.3;slew=.1;load=.01;dynamic=0
    for c in cells:
        if c['cell']==SC+'inv_1':continue # reset is static during the measured wakes
        body=lib[c['cell']];pins=dict(direct_groups(body,'pin'))
        input_pin='A1' if c['cell']==SC+'and2_1' else 'I'
        powers=[p for _,p in direct_groups(pins['Z'],'internal_power')
                if re.search(r'related_pin\s*:\s*"'+input_pin+r'"',p)]
        require(powers,'ACK_ACTIVITY_MISSING_POWER_ARC')
        # mW*ns=pJ. Representative conditional table average, not a measured
        # waveform or routed-net load. External output-wire energy is excluded.
        dynamic+=scalar(pins[input_pin],'capacitance')*voltage**2
        pairs=[]
        for power in powers:
            pair=0
            for edge in ('rise_power','fall_power'):
                tables=list(direct_groups(power,edge));require(len(tables)==1,'ACK_ACTIVITY_POWER_TABLE')
                pair+=max(0,table_value(tables[0][1],slew,load))
            pairs.append(pair)
        dynamic+=statistics.mean(pairs)
    metrics=[cell_metrics(lib[c['cell']]) for c in cells]
    return dict(scope='representative TT cell-internal plus active-input capacitance; excludes wires and upstream driver internal energy',
        voltage_v=voltage,input_slew_ns=slew,table_output_load_pf=load,
        dlyd_cells=sum(c['cell']==SC+'dlyd_1' for c in cells),
        dynamic_pj_per_rise_fall_pair=dynamic,
        leakage_min_uw=sum(x['leak_min_uw'] for x in metrics),leakage_max_uw=sum(x['leak_max_uw'] for x in metrics),
        liberty_sha256=sha(libpath))


def report(normal,bypass,click,mapping,output):
    require(not output.exists(),'ACK_ACTIVITY_OUTPUT_EXISTS')
    files=[normal,bypass,click,mapping/'mapping.json',Path(__file__)]
    frozen={str(p.resolve()):sha(p) for p in files}
    frozen.update(matched_exports(normal.parent,bypass.parent))
    nw,ns=read_wakes(normal,32.0);bw,bs=read_wakes(bypass,.001);cw,cs=read_wakes(click)
    diffs=compare(nw,bw);energy=guard_energy(mapping)
    for kind in ns:ns[kind]['guard_dynamic_pj']=ns[kind]['rises']*energy['dynamic_pj_per_rise_fall_pair']
    result=dict(scope='native digital model workload; not mapped timing or whole-chip power',
        normal_bd=ns,diagnostic_bypass_bd=bs,click=cs,guard_energy=energy,
        paired_delta_range={k:[min(d[k] for d in diffs),max(d[k] for d in diffs)] for k in ('fast','work','ns')},
        inputs_sha256=frozen)
    require(all(sha(Path(p))==h for p,h in frozen.items()),'ACK_ACTIVITY_INPUT_CHANGED')
    write_json(output,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('normal','bypass','click','mapping','output'):p.add_argument(name,type=Path)
    a=p.parse_args();print(json.dumps(report(a.normal,a.bypass,a.click,a.mapping,a.output),indent=2))

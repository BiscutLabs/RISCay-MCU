# SPDX-License-Identifier: Apache-2.0
"""Group retained P&R slew violations by their actual net and repair obstacle."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from gf180_physical import sha,write_json
from gf180_slew_policy import report_rows
from repair_gf180_control import require
from characterize_gf180_liberty import CORNERS
from gf180_pnr import validate_provenance


def classify(graph_text,locked_text,log,reports):
    pins={};drivers=defaultdict(list);masters={}
    for line in graph_text.splitlines():
        row=line.split('\t')
        if row[0]=='C':masters[row[1]]=row[2]
        elif row[0]=='P':
            name,pin,direction,net=row[1:];full=name+'/'+pin
            require(full not in pins,'ELECTRICAL_DUPLICATE_PIN');pins[full]=net
            if direction=='output':drivers[net].append(full)
        elif row[0]=='T':
            name,direction,net=row[1:]
            require(name not in pins,'ELECTRICAL_DUPLICATE_PIN');pins[name]=net
            if direction=='input':drivers[net].append(name)
        else:raise ValueError('ELECTRICAL_GRAPH_ROW')
    locked=set(locked_text.splitlines())
    # STA report formatting removes escaped hierarchy separators in flat CTS
    # names. Resolve that exact spelling, rejecting any ambiguous alias.
    report_pins={}
    for pin in pins:
        printed=pin.replace('\\/','/')
        require(printed not in report_pins,'ELECTRICAL_AMBIGUOUS_REPORT_PIN')
        report_pins[printed]=pin
    report_nets={}
    for net in set(pins.values()):
        printed=net.replace('\\/','/')
        require(printed not in report_nets,'ELECTRICAL_AMBIGUOUS_REPORT_NET')
        report_nets[printed]=net
    abandoned=set()
    stale_warnings=[]
    for line in log.splitlines():
        if 'Cannot repair slew on net ' not in line:continue
        match=re.search(r'Cannot repair slew on net (\S+) driven by (\S+): driver resistance ',line)
        require(match is not None,'ELECTRICAL_REPAIR_WARNING_SHAPE')
        net=report_nets.get(match[1].replace('\\/','/'))
        driver=report_pins.get(match[2].replace('\\/','/'))
        if net is not None and driver is not None and pins[driver]==net:
            abandoned.add((net,driver))
        else:stale_warnings.append(line)  # Repair subsequently changed this segment.
    result={}
    for corner,text in reports.items():
        nets={};caps=[]
        for row in report_rows(text):
            require(row['pin'] in report_pins,'ELECTRICAL_UNKNOWN_REPORTED_PIN')
            database_pin=report_pins[row['pin']]
            if row['kind']=='max capacitance':caps.append(row);continue
            net=pins[database_pin]
            require(len(drivers[net])==1,'ELECTRICAL_DRIVER_COUNT')
            driver=drivers[net][0]
            category=('locked-native-net' if net in locked else
                      'resizer-no-progress' if (net,driver) in abandoned else 'ordinary-or-clock')
            item=nets.setdefault(net,dict(net=net,driver=driver,
                master=masters.get(driver.rsplit('/',1)[0],'TOP_PORT'),category=category,rows=[]))
            item['rows'].append(dict(row,database_pin=database_pin))
        ordered=sorted(nets.values(),key=lambda n:max(r['value'] for r in n['rows']),reverse=True)
        result[corner]=dict(slew_rows=sum(len(n['rows']) for n in ordered),unique_nets=len(ordered),
            nets_by_category=dict(Counter(n['category'] for n in ordered)),
            worst_slew_ns=max((r['value'] for n in ordered for r in n['rows']),default=0),
            nets=ordered,capacitance_rows=caps,unmatched_intermediate_warnings=stale_warnings)
    return result


def run(mapping,pnr,output,stage='global'):
    validate_provenance(mapping,pnr,stage)
    require(not output.exists(),'ELECTRICAL_REPORT_EXISTS')
    graph=pnr/(stage+'-repair-after.tsv');locked=pnr/(stage+'-native-protected-nets.txt');log=pnr/(stage+'.log')
    reports={c:pnr/(stage+'-'+c+'-electrical.rpt') for c in CORNERS}
    files=[graph,locked,log,*reports.values(),Path(__file__),Path(__file__).with_name('gf180_slew_policy.py')]
    frozen={str(p.resolve()):sha(p) for p in files}
    result=classify(graph.read_text(),locked.read_text(),log.read_text(),{c:p.read_text() for c,p in reports.items()})
    require(all(sha(Path(p))==h for p,h in frozen.items()),'ELECTRICAL_REPORT_INPUT_CHANGED')
    validate_provenance(mapping,pnr,stage)
    write_json(output,dict(status='diagnostic-not-electrical-closure',inputs_sha256=frozen,corners=result))
    print(json.dumps({c:{k:v for k,v in r.items() if k not in
        ('nets','capacitance_rows','unmatched_intermediate_warnings')} for c,r in result.items()},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mapping',type=Path);p.add_argument('pnr',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--stage',choices=('place','global'),default='global')
    a=p.parse_args();run(a.mapping.resolve(),a.pnr.resolve(),a.output.resolve(),a.stage)

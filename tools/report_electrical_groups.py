# SPDX-License-Identifier: Apache-2.0
"""Group retained P&R slew violations by their actual net and repair obstacle."""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re
from gf180_physical import sha,write_json
from gf180_slew_policy import report_rows
from repair_gf180_control import require
from characterize_gf180_liberty import CORNERS
from gf180_pnr import validate_provenance


CAPTURE_CAPS = r'''
rename set_max_capacitance audit_set_max_capacitance
set adapter_limits [dict create]
proc set_max_capacitance {cap objects} {
  global adapter_limits
  foreach pin $objects {
    if {[$pin is_hierarchical] || ![$pin is_driver]} {error ADAPTER_CAP_NOT_LEAF_DRIVER}
    set name [get_full_name $pin]
    set pf [expr {1e12*[sta::capacitance_ui_sta $cap]}]
    if {![dict exists $adapter_limits $name] || $pf<[dict get $adapter_limits $name]} {
      dict set adapter_limits $name $pf
    }
  }
  audit_set_max_capacitance $cap $objects
}
'''

QUERY_CAPS = r'''
if {abs([sta::capacitance_sta_ui 1e-12]-1)>1e-6} {error ADAPTER_CAP_EXPECTED_PF_UNITS}
puts ADAPTER_CAP_LIMITS_BEGIN
dict for {name limit} $adapter_limits {puts "ADAPTER_CAP_LIMIT\t$name\t$limit"}
puts ADAPTER_CAP_LIMITS_END
set driver_count 0
foreach inst [[ord::get_db_block] getInsts] {
  foreach term [$inst getITerms] {
    if {[[$term getMTerm] getIoType] in {OUTPUT INOUT}} {incr driver_count}
  }
}
incr driver_count [llength [[ord::get_db_block] getBTerms]]
foreach corner $audit_corners {
  set scene [sta::find_scene $corner]
  if {$scene eq "NULL"} {error ADAPTER_CAP_CORNER_MISSING}
  puts "ADAPTER_CAP_REPORT_BEGIN\t$corner"
  report_check_types -corner $corner -max_capacitance -max_count $driver_count -digits 12 -no_line_splits
  puts "ADAPTER_CAP_REPORT_END\t$corner"
  dict for {name limit} $adapter_limits {
    set pin [get_pins -quiet $name]
    if {[llength $pin]!=1} {error "ADAPTER_CAP_PIN_MISSING $name"}
    set net [$pin net]
    if {$net eq "NULL"} {error "ADAPTER_CAP_NET_MISSING $name"}
    set drivers 0
    set iterator [$net connected_pin_iterator]
    while {[$iterator has_next]} {
      set p [$iterator next]
      if {![$p is_hierarchical] && [$p is_driver]} {incr drivers}
    }
    $iterator finish
    if {$drivers!=1} {error "ADAPTER_CAP_DRIVER_COUNT $name $drivers"}
    puts "ADAPTER_CAP_LOAD\t$corner\t$name\t[expr {1e12*[$net pin_capacitance $scene min]}]\t[expr {1e12*[$net wire_capacitance $scene min]}]\t[expr {1e12*[$net pin_capacitance $scene max]}]\t[expr {1e12*[$net wire_capacitance $scene max]}]"
  }
}
puts ADAPTER_CAP_COMPLETE
'''


def cap_audit_rows(log, corners, reference_pins=None):
    """Keep coherent STA loads separate from independently maximal bounds."""
    expected={}; loads={c:{} for c in corners}; reports={c:{} for c in corners}
    active=None; limits=False; seen=[]; ended=[]; complete=0
    pattern=re.compile(r'^(\S+)\s+([-+.\deE]+)\s+([-+.\deE]+)\s+([-+.\deE]+)\s+\((MET|VIOLATED)\)$')
    def number(value):
        value=float(value);require(math.isfinite(value),'ADAPTER_CAP_NONFINITE');return value
    def name(value):return value.replace('\\/','/')
    for raw in log.splitlines():
        row=raw.split('\t')
        if raw=='ADAPTER_CAP_LIMITS_BEGIN':
            require(not limits and not expected,'ADAPTER_CAP_LIMIT_MARKERS');limits=True
        elif raw=='ADAPTER_CAP_LIMITS_END':
            require(limits and expected,'ADAPTER_CAP_LIMIT_MARKERS');limits=False
        elif row[0]=='ADAPTER_CAP_LIMIT':
            require(limits and len(row)==3 and name(row[1]) not in expected,'ADAPTER_CAP_LIMIT_ROW')
            cap=number(row[2]);require(cap>0,'ADAPTER_CAP_LIMIT_ROW');expected[name(row[1])]=cap
        elif row[0]=='ADAPTER_CAP_REPORT_BEGIN':
            require(len(row)==2 and row[1] in reports and active is None and row[1] not in seen,'ADAPTER_CAP_REPORT_MARKERS')
            active=row[1];seen.append(active)
        elif row[0]=='ADAPTER_CAP_REPORT_END':
            require(len(row)==2 and row[1]==active,'ADAPTER_CAP_REPORT_MARKERS');ended.append(active);active=None
        elif row[0]=='ADAPTER_CAP_LOAD':
            require(len(row)==7 and row[1] in loads and name(row[2]) not in loads[row[1]],'ADAPTER_CAP_LOAD_ROW')
            values=list(map(number,row[3:]));require(min(values)>=0,'ADAPTER_CAP_NEGATIVE_LOAD')
            loads[row[1]][name(row[2])]=values
        elif raw=='ADAPTER_CAP_COMPLETE':complete+=1
        elif active is not None:
            text=raw.strip();match=pattern.fullmatch(text)
            if match:
                pin=name(match[1]);require(pin not in reports[active],'ADAPTER_CAP_DUPLICATE_REPORT_PIN')
                limit,value,slack=map(number,match.groups()[1:4]);require(limit>0 and value>=0,'ADAPTER_CAP_REPORT_VALUE')
                reports[active][pin]=dict(limit_pf=limit,load_pf=value,slack_pf=slack)
            else:
                require(not text or text=='max capacitance' or text.startswith('Pin ') or set(text)=={'-'},'ADAPTER_CAP_REPORT_SHAPE')
    require(not limits and active is None and seen==ended and set(seen)==set(corners) and complete==1 and expected,
            'ADAPTER_CAP_INCOMPLETE')
    result={}
    for corner in corners:
        missing=sorted(set(expected)-set(loads[corner]));extra=sorted(set(loads[corner])-set(expected));rows=[]
        require(not extra,'ADAPTER_CAP_UNEXPECTED_PIN')
        for pin,values in loads[corner].items():
            pmin,wmin,pmax,wmax=values;upper=pmax+wmax;lower=max(pmax,wmax);coherent=reports[corner].get(pin)
            if coherent:
                value=coherent['load_pf']
                tolerance=max(1e-8,1e-6*upper)  # STA stores capacitance and unit scales as floats.
                require(lower-tolerance<=value<=upper+tolerance,'ADAPTER_CAP_COMPONENT_MISMATCH')
                lower=upper=value
            limit=expected[pin]
            status=('definite-violation' if lower>limit else 'bound-only-candidate' if upper>limit else 'within-bound')
            rows.append(dict(pin=pin,intended_limit_pf=limit,pin_min_pf=pmin,wire_min_pf=wmin,pin_max_pf=pmax,wire_max_pf=wmax,
                             coherent_load_pf=coherent['load_pf'] if coherent else None,
                             lower_load_bound_pf=lower,upper_load_bound_pf=upper,status=status))
        result[corner]=dict(expected_pins=len(expected),measured_pins=len(loads[corner]),missing_pins=missing,
            reference_loads_pf={p:reports[corner].get(name(p),{}).get('load_pf')
                               for p in (reference_pins or {}).get(corner,[])},
            coherent_report_missing_pins=sorted(set(expected)-set(reports[corner])),
            definite_violations=sum(r['status']=='definite-violation' for r in rows),
            bound_only_candidates=sum(r['status']=='bound-only-candidate' for r in rows),
            liberty_reported_violations=[dict(pin=p,**r) for p,r in reports[corner].items() if r['slack_pf']<0],rows=rows)
    return result


def require_bound_files(paths, expected, label, relative_to=None):
    """Validate only the immutable inputs consumed by this diagnostic."""
    for path in paths:
        key=path.relative_to(relative_to).as_posix() if relative_to else str(path.resolve())
        require(key in expected and path.is_file() and sha(path)==expected[key],label)


def audit_capacitance(mapping,pnr,output,stage='global',wire_corner='nom'):
    """Read a completed checkpoint while another P&R stage may still be active."""
    from gf180_constraints import brace
    from gf180_physical import ROOT,SC,SRAM
    from gf180_pnr import pnr_tool
    from run_receipt import RunReceipt
    from routed_annotation import SPEF_WARNING, run as annotation_audit
    require(stage in ('global','extract') and not output.exists(),'ADAPTER_CAP_AUDIT_ARGUMENTS')
    meta=json.loads((pnr/'run.json').read_text());checkpoint=meta['checkpoints'][stage]
    selected=pnr_tool(meta)
    odb=pnr/('global.odb' if stage=='global' else 'extract'+('' if wire_corner=='nom' else '-'+wire_corner)+'.odb')
    spef=pnr/('routed-'+wire_corner+'.spef') if stage=='extract' else None
    evidence=checkpoint if stage=='global' else checkpoint['rc_corners'][wire_corner]
    require(sha(odb)==evidence['odb_sha256'] and (spef is None or sha(spef)==evidence['spef_sha256']), 'ADAPTER_CAP_CHECKPOINT_CHANGED')
    libs=[ROOT/'.tools/physical/pdk'/(SC+c+'.lib') for c in CORNERS]
    srams=[ROOT/'.tools/gf180-sram'/(SRAM+'__'+c+'.lib') for c in CORNERS]
    sdcs=[mapping/n for n in ('base.sdc','clocked.sdc','feedback-cuts.tcl')]
    cap_sdc=pnr/'async-electrical.sdc'
    require_bound_files(sdcs,meta.get('mapping_inputs_sha256',{}),'ADAPTER_CAP_MAPPING_INPUT_CHANGED',mapping)
    require_bound_files([cap_sdc],meta.get('generated_inputs_sha256',{}),'ADAPTER_CAP_CONSTRAINT_CHANGED',pnr)
    require_bound_files([*libs,*srams],meta.get('physical_inputs_sha256',{}),'ADAPTER_CAP_LIBRARY_CHANGED')
    runtime=[p for p in selected.input_files() if p!=selected.config_path.resolve()]
    executable=selected.host_path();wrapped=executable.with_name('.'+executable.name+'-wrapped')
    if wrapped.is_file() or str(wrapped.resolve()) in meta.get('openroad_runtime_sha256',{}):runtime.append(wrapped)
    require_bound_files(runtime,meta.get('openroad_runtime_sha256',{}),'ADAPTER_CAP_RUNTIME_CHANGED')
    references={c:pnr/('global-'+c+'-electrical.rpt') for c in CORNERS} if stage=='global' else {}
    require_bound_files(references.values(),checkpoint.get('electrical_reports_sha256',{}),'ADAPTER_CAP_REFERENCE_CHANGED',pnr)
    inputs=[odb,*libs,*srams,*sdcs,cap_sdc,*references.values(),*([spef] if spef else [])]
    receipt=RunReceipt(output/'receipt.json',inputs=inputs,tools=[Path(__file__),Path(__file__).with_name('routed_annotation.py'),selected.config_path,*runtime])
    output.mkdir(parents=True);status='fail'
    try:
        t='set_thread_count 2\nset audit_corners {'+' '.join(CORNERS)+'}\ndefine_corners {*}$audit_corners\n'
        for corner,lib,sram in zip(CORNERS,libs,srams):
            for path in (lib,sram):t+='read_liberty -corner '+corner+' '+brace(selected.path(path))+'\n'
        t+='read_db '+brace(selected.path(odb))+'\n'
        for path in sdcs:t+='source '+brace(selected.path(path))+'\n'
        t+=CAPTURE_CAPS+'source '+brace(selected.path(cap_sdc))+'\nset_propagated_clock [get_clocks {service work lf}]\n'
        if spef:
            annotation_audit(odb,spef,selected,output/'annotation')
            for corner in CORNERS:t+='read_spef -corner '+corner+' '+brace(selected.path(spef))+'\n'
        else:
            t+='set_wire_rc -signal -layer Metal3\nset_wire_rc -clock -layer Metal4\nset_routing_layers -signal Metal2-Metal5 -clock Metal2-Metal5\nestimate_parasitics -global_routing\n'
        t+=QUERY_CAPS+'exit\n'
        script=output/'audit.tcl';script.write_text(t)
        code=receipt.command(selected.command(['-no_init','-exit',selected.path(script)]),cwd=output,log=output/'audit.log')
        log=(output/'audit.log').read_text();require(code==0 and not re.search(SPEF_WARNING,log),'ADAPTER_CAP_TOOL_FAILED')
        reference_rows={c:[r for r in report_rows(p.read_text()) if r['kind']=='max capacitance']
                        for c,p in references.items()}
        result=cap_audit_rows(log,CORNERS,{c:[r['pin'] for r in rows] for c,rows in reference_rows.items()})
        calibration=[]
        for corner,rows in reference_rows.items():
            for row in rows:
                current=result[corner]['reference_loads_pf'][row['pin']]
                calibration.append(dict(corner=corner,pin=row['pin'],retained_report_load_pf=row['value'],
                    reloaded_load_pf=current,within_report_rounding=current is not None and abs(current-row['value'])<=5.1e-7))
        missing=sum(len(r['missing_pins']) for r in result.values());violations=sum(r['definite_violations'] for r in result.values());candidates=sum(r['bound_only_candidates'] for r in result.values())
        write_json(output/'report.json',dict(status='adapter-capacitance-failures' if violations else 'adapter-capacitance-unresolved' if missing or candidates else 'adapter-capacitance-within-bounds',
            physical_qualification=False,geometry_checkpoint=stage,wire_corner=wire_corner if spef else None,corners=result,
            retained_report_load_comparison=calibration,
            limits=['Per-pin SDC limits are enumerated independently of the pinned STA limit checker.',
                    'Coherent report loads use the same STA loadCap calculation as Liberty checks.',
                    'Where the report omits a driver, independently maximal pin/wire components form an upper bound; their maximum forms a lower bound.',
                    'Min/max components are separate STA analysis views, not paired rise/fall samples.',
                    'Global checkpoint reload estimates from saved database guides; accepted extracted SPEF min/max remain definitive.',
                    'The active run.json is read for checkpoint identity, never hashed or treated as immutable.']))
        status='pass' if not missing else 'fail'
    finally:receipt.finish(outputs=[p for p in output.rglob('*') if p.is_file()],status=status)
    return result


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
    p.add_argument('--stage',choices=('place','global','extract'),default='global')
    p.add_argument('--adapter-caps',action='store_true',help='Read-only per-pin capacitance audit; output is a fresh directory')
    p.add_argument('--wire-corner',choices=('nom','min','max'),default='nom')
    a=p.parse_args()
    if a.adapter_caps:audit_capacitance(a.mapping.resolve(),a.pnr.resolve(),a.output.resolve(),a.stage,a.wire_corner)
    else:
        require(a.stage!='extract','ELECTRICAL_GROUP_STAGE')
        run(a.mapping.resolve(),a.pnr.resolve(),a.output.resolve(),a.stage)

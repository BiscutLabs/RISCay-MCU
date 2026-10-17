# SPDX-License-Identifier: Apache-2.0
"""Exact periodic clock identity and per-sink CTS construction coverage."""
from pathlib import Path
import re
from gf180_physical import ROOT, SC, SRAM, sha, write_json
from characterize_gf180_liberty import CORNERS
from gf180_estimate import library, direct_groups
from repair_gf180_control import require
from repair_gf180_design import flat, graph_proof, protected_cells, validate_sram_clock_drivers
from check_pnr_repair import read_graph


def inventory(text):
    roots={};pins=set();macros=set();generated=[];waveforms={}
    for line in text.splitlines():
        row=line.split('\t')
        if len(row)==3 and row[0]=='R':
            require(row[1] not in roots,'CTS_DUPLICATE_ROOT');roots[row[1]]=row[2]
        elif len(row)==4 and row[0] in ('P','M'):
            require(row[1] in ('service','work','lf','i2c_start') and row[2] in ('rise','fall'),
                    'CTS_SINK_SHAPE')
            item=tuple(row[1:]); target=macros if row[0]=='M' else pins
            require(item not in target,'CTS_DUPLICATE_SINK');target.add(item)
        elif len(row)==2 and row[0]=='G':generated.append(row[1])
        elif len(row)==4 and row[0]=='W':
            require(row[1] not in waveforms,'CTS_DUPLICATE_WAVEFORM')
            waveforms[row[1]]=(float(row[2]),tuple(map(float,row[3].split(','))))
        else:raise ValueError('CTS_INVENTORY_ROW')
    require(set(roots)=={'service','work','lf','i2c_start'},'CTS_ROOT_INVENTORY')
    require(len(macros)==3 and all(c=='work' and e=='rise' for c,e,p in macros),'CTS_MACRO_INVENTORY')
    require(all(any(c==clock for c,e,p in pins) for clock in roots),'CTS_EMPTY_CLOCK')
    require(generated==['create_generated_clock -name work -source [get_ports {serviceClock}] '
                       '-divide_by 1 [get_pins {'+roots['work']+'}]'],'CTS_WORK_RELATION_CHANGED')
    require(set(waveforms)==set(roots),'CTS_WAVEFORM_INVENTORY')
    require(waveforms['service']==waveforms['work'],'CTS_WORK_WAVEFORM_CHANGED')
    for name,period in dict(service=50e-9,work=50e-9,lf=1/12,i2c_start=2500e-9).items():
        actual,waveform=waveforms[name]
        require(abs(actual/period-1)<1e-6 and len(waveform)==2 and
                waveform[0]==0 and abs(waveform[1]/(period/2)-1)<1e-6,'CTS_WAVEFORM_CHANGED')
    return roots,pins|macros


def graph_index(graph):
    drivers={};pin_nets={}
    for name,cell in graph['cells'].items():
        for pin,ns in cell['connections'].items():
            if len(ns)!=1:continue
            pin_nets[name+'/'+pin]=ns[0]
            if cell['directions'][pin]=='output':
                require(ns[0] not in drivers,'CTS_MULTIPLE_DRIVERS');drivers[ns[0]]=name
    for name,port in graph['ports'].items():
        if len(port['bits'])==1:pin_nets[name]=port['bits'][0]
    return drivers,pin_nets


def sequential_pins(libs):
    """Clock pins and active edges from every corner, independent of STA discovery."""
    results=[]
    for lib in libs:
        result={}
        for name,body in lib.items():
            states=[(kind,value) for kind in ('ff','latch') for _,value in direct_groups(body,kind)]
            marked={pin for pin,value in direct_groups(body,'pin') if re.search(r'\bclock\s*:\s*true\s*;',value)}
            if not states:
                if marked:result[name]=None  # Fail if instantiated (e.g. an unreviewed ICG).
                continue
            require(len(states)==1,'CTS_UNKNOWN_SEQUENTIAL_CELL')
            kind,state=states[0];key='clocked_on' if kind=='ff' else 'enable'
            value=re.search(r'\b'+key+r'\s*:\s*"([^"]+)"\s*;',state)
            require(value is not None,'CTS_MISSING_CLOCK_EXPRESSION')
            expression=value[1].replace('(','').replace(')','')
            match=re.fullmatch(r'(!?)(\w+)',expression)
            require(match is not None and marked=={match[2]},'CTS_UNKNOWN_CLOCK_EXPRESSION')
            result[name]=(match[2],'fall' if match[1] else 'rise')
        results.append(result)
    require(results and all(r==results[0] for r in results),'CTS_CORNER_CLOCK_PINS_CHANGED')
    return results[0]


def expected_sinks(graph,roots,seq,protected):
    drivers,pins=graph_index(graph)
    require(set(roots.values())<=set(pins),'CTS_MISSING_ROOT')
    root_nets={pins[p]:clock for clock,p in roots.items()}
    require(len(root_nets)==len(roots),'CTS_ALIASED_ROOTS')
    expected=set();native_checked=set()
    # This is a clock-wiring check, not a general CDC proof. Native triggers may
    # depend on registered observations, but no combinational periodic root may
    # drive them. Stop at real storage outputs; never exempt a gate by its name.
    def native_root_reachable(net):
        pending=[net];seen=set()
        while pending:
            n=pending.pop()
            if n in root_nets:return True
            if n in seen:continue
            seen.add(n)
            if n not in drivers:continue
            cell=graph['cells'][drivers[n]]
            if cell['type'] in seq or cell['type']==SRAM:continue
            pending.extend(v for p,ns in cell['connections'].items() if cell['directions'][p]=='input' for v in ns)
        return False
    for name,cell in graph['cells'].items():
        if cell['type']==SRAM:pin,edge='CLK','rise'
        elif cell['type'] in seq:
            require(seq[cell['type']] is not None,'CTS_UNKNOWN_CLOCK_CELL_'+cell['type'])
            pin,edge=seq[cell['type']]
        else:continue
        full=name+'/'+pin;require(full in pins,'CTS_MISSING_SEQUENTIAL_PIN')
        net=pins[full]
        if name in protected:
            if net not in native_checked:
                require(not native_root_reachable(net),'CTS_PERIODIC_NATIVE_STORAGE');native_checked.add(net)
            continue
        parity=0;seen=set()
        while net not in root_nets:
            require(net not in seen and net in drivers,'CTS_UNROOTED_SEQUENTIAL_PIN_'+full);seen.add(net)
            c=graph['cells'][drivers[net]]
            require(re.fullmatch(re.escape(SC)+r'(?:buf|clkbuf|inv)_\d+',c['type']),
                    'CTS_UNREVIEWED_CLOCK_LOGIC_'+full)
            parity ^= int(c['type'].startswith(SC+'inv_'));net=c['connections']['I'][0]
        relative='fall' if (edge=='fall')^bool(parity) else 'rise'
        expected.add((root_nets[net],relative,full))
    require(expected,'CTS_EMPTY_EXPECTED_INVENTORY')
    return expected


def reconcile_sinks(expected,reported):
    # OpenSTA includes generated-clock descendants in the master clock's list.
    # Keep the nearest physical root, but accept only this proved 1:1 relation.
    allowed=expected|{('service',e,p) for c,e,p in expected if c=='work'}
    require(expected<=reported and reported<=allowed,'CTS_STA_GRAPH_INVENTORY_MISMATCH')
    return expected


def paths(graph,roots,sinks,created):
    drivers,pin_nets=graph_index(graph)
    result={}
    for clock,edge,pin in sorted(sinks):
        require(pin in pin_nets and roots[clock] in pin_nets,'CTS_MISSING_PIN')
        root=pin_nets[roots[clock]];net=pin_nets[pin];seen=set();path=[];parity=0
        while net!=root:
            require(net not in seen and net in drivers,'CTS_DISCONNECTED_OR_CYCLIC');seen.add(net)
            name=drivers[net];cell=graph['cells'][name]
            require(re.fullmatch(re.escape(SC)+r'(?:buf|clkbuf|inv)_\d+',cell['type']),
                    'CTS_UNREVIEWED_CLOCK_LOGIC')
            parity ^= int(cell['type'].startswith(SC+'inv_'))
            path.append(name);net=cell['connections']['I'][0]
        result[(clock,edge,pin)]=dict(parity=parity,created_buffers=sorted(set(path)&created),depth=len(path))
    return result


def verify_paths(before,after):
    require(set(before)==set(after),'CTS_SINK_OR_ROOT_CHANGED')
    for pin,row in after.items():
        require(row['parity']==before[pin]['parity'],'CTS_CLOCK_POLARITY_CHANGED')
        if pin[0]=='i2c_start':require(not row['created_buffers'],'CTS_SDA_WAS_BUFFERED')
        else:require(row['created_buffers'],'CTS_PERIODIC_SINK_NOT_CONSTRUCTED_'+pin[2])


def check(mapping,out):
    files=[out/(name+'.tsv') for name in ('clock-repair-before','clock-repair-after','clock-sinks-before','clock-sinks-after')]
    frozen={str(p.resolve()):sha(p) for p in files}
    a,b=map(read_graph,files[:2]);left,right=map(lambda p:inventory(p.read_text()),files[2:])
    require(left==right,'CTS_SINK_OR_ROOT_CHANGED')
    libs=[library(ROOT/'.tools/physical/pdk'/(SC+c+'.lib')) for c in CORNERS]
    proof=graph_proof(a,b,'RiscayMcuDigital',protected_cells(mapping),libs)
    created=set(proof['added_buffers'])
    seq=sequential_pins(libs);protected=protected_cells(mapping)
    ag,bg=flat(a,'RiscayMcuDigital'),flat(b,'RiscayMcuDigital')
    expected_a=expected_sinks(ag,left[0],seq,protected)
    expected_b=expected_sinks(bg,right[0],seq,protected)
    before=paths(ag,left[0],reconcile_sinks(expected_a,left[1]),set())
    after=paths(bg,right[0],reconcile_sinks(expected_b,right[1]),created)
    verify_paths(before,after)
    proof['sram_clock_drivers']=validate_sram_clock_drivers(b,'RiscayMcuDigital')
    proof['periodic_sinks']=sum(c!='i2c_start' for c,e,p in after)
    proof['sink_paths']=[dict(clock=c,edge=e,pin=p,**row) for (c,e,p),row in after.items()]
    proof['physical_qualification']=False
    require(all(sha(Path(p))==h for p,h in frozen.items()),'CTS_INPUT_CHANGED')
    proof['inputs_sha256']=frozen
    write_json(out/'clock-coverage-proof.json',proof)
    return dict(proof_sha256=sha(out/'clock-coverage-proof.json'),inputs_sha256=frozen)

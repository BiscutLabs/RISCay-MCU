# SPDX-License-Identifier: Apache-2.0
"""Inventory extracted native coupling and run bounded distributed-RC screens.

This is not receiver-noise, keeper-stability or crosstalk timing qualification.
The RC sensitivity decks omit transistor drivers, receiver input capacitance,
receiver thresholds, supply noise and arbitrary aggressor timing combinations.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from gf180_estimate import linux
from gf180_physical import sha, write_json
from native_routing import read_report


def require(value, message):
    if not value:
        raise ValueError(message)


def number(text):
    value = float(text)
    require(math.isfinite(value) and value >= 0, 'COUPLING_INVALID_NUMBER')
    return value


def unescape(text):
    return re.sub(r'\\(.)', r'\1', text)


def read_spef(path, selected):
    """Stream all node ownership; retain RC networks only for selected victims.

    Reciprocal SPEF coupling rows belong to each endpoint's D_NET block. Each
    victim reads only its own block, so its coupling is counted once, including
    physically parallel capacitors with identical endpoints and values.
    """
    names, ownership, nets, retained = {}, {}, {}, {}
    # OpenRCX escapes generated Verilog identifiers differently from OpenDB.
    # Match a normalized spelling only when the complete selected set is unique.
    selected_aliases = {unescape(n): n for n in selected}
    require(len(selected_aliases)==len(selected), 'COUPLING_AMBIGUOUS_SELECTED_NAME')
    section = None; current = None; cap_scale = None; res_scale = None
    pin_cap = None; current_data = None

    def name(token):
        match = re.fullmatch(r'(\*\d+)(.*)', token)
        if match:
            require(match[1] in names, 'COUPLING_NAME_MAP_MISSING')
            return names[match[1]] + unescape(match[2])
        return unescape(token)

    def own(node):
        require(current is not None, 'COUPLING_NODE_OUTSIDE_NET')
        require(node not in ownership or ownership[node] == current, 'COUPLING_NODE_MULTIPLE_NETS')
        ownership[node] = current

    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            row = line.split()
            if not row: continue
            marker = row[0]
            if marker == '*C_UNIT':
                require(len(row)==3 and row[2].upper() in ('F','PF','FF'), 'COUPLING_CAP_UNIT')
                cap_scale = number(row[1]) * {'F':1e12,'PF':1.,'FF':1e-3}[row[2].upper()]
                require(cap_scale>0,'COUPLING_CAP_UNIT'); continue
            if marker == '*R_UNIT':
                require(len(row)==3 and row[2].upper() in ('OHM','KOHM'), 'COUPLING_RES_UNIT')
                res_scale = number(row[1]) * {'OHM':1.,'KOHM':1e3}[row[2].upper()]
                require(res_scale>0,'COUPLING_RES_UNIT'); continue
            if marker == '*DESIGN_FLOW':
                match = re.search(r'"PIN_CAP (NONE|INPUT_OUTPUT|INPUT)"',line)
                if match: pin_cap = match[1]
            if marker in ('*NAME_MAP','*PORTS','*CONN','*CAP','*RES'):
                section = marker; continue
            if marker == '*D_NET':
                require(cap_scale is not None and res_scale is not None and len(row)==3, 'COUPLING_NET_HEADER')
                current = row[1]
                require(current not in nets, 'COUPLING_DUPLICATE_NET')
                decoded = name(current)
                nets[current] = selected_aliases.get(decoded, decoded)
                current_data = None
                if nets[current] in selected:
                    current_data = dict(name=nets[current], spef_name=decoded,total_header_pf=number(row[2])*cap_scale,
                                        ground={}, coupling=[], resistors=[], connections=[])
                    retained[current] = current_data
                section = None; continue
            if marker == '*END':
                current = None; current_data = None; section = None; continue
            if section == '*NAME_MAP':
                require(len(row)==2 and re.fullmatch(r'\*\d+',marker) and marker not in names, 'COUPLING_NAME_MAP')
                names[marker] = unescape(row[1]); continue
            if section == '*CONN' and marker in ('*I','*P'):
                require(len(row)>=3 and row[2] in ('I','O','B'), 'COUPLING_CONNECTION')
                own(row[1])
                if current_data is not None:
                    current_data['connections'].append(dict(node=row[1], kind=marker, direction=row[2], pin=name(row[1])))
                continue
            if section == '*CAP':
                require(len(row) in (3,4) and marker.isdigit(), 'COUPLING_CAP_ROW')
                cap = number(row[-1])*cap_scale
                if len(row)==3:
                    own(row[1])
                    if current_data is not None:
                        current_data['ground'][row[1]] = current_data['ground'].get(row[1],0.) + cap
                elif current_data is not None:
                    current_data['coupling'].append((row[1],row[2],cap))
                continue
            if section == '*RES':
                require(len(row)==4 and marker.isdigit(), 'COUPLING_RES_ROW')
                own(row[1]); own(row[2]); resistance=number(row[3])*res_scale
                if current_data is not None: current_data['resistors'].append((row[1],row[2],resistance))
    require(nets and pin_cap == 'NONE', 'COUPLING_EXPECTED_WIRE_ONLY_SPEF')
    found = {v['name'] for v in retained.values()}
    require(len(found)==len(retained), 'COUPLING_DUPLICATE_EXPANDED_NET')
    for token, data in retained.items():
        resolved=[]
        for a,b,cap in data['coupling']:
            if cap==0: continue
            require(a in ownership and b in ownership, 'COUPLING_UNRESOLVED_NODE')
            require((ownership[a]==token) != (ownership[b]==token), 'COUPLING_NONLOCAL_OR_INTERNAL_CAP')
            if ownership[b]==token: a,b=b,a
            resolved.append((a,b,cap,nets[ownership[b]]))
        data['coupling']=resolved
    return dict(networks={v['name']:v for v in retained.values()},
                missing=sorted(set(selected)-found), pin_cap=pin_cap,
                extracted_net_count=len(nets), cap_unit_pf=cap_scale,res_unit_ohm=res_scale)


def rank(network, voltage):
    ground=sum(network['ground'].values()); coupled=sum(c[2] for c in network['coupling'])
    aggressors=defaultdict(float); local=defaultdict(float)
    for node,_,cap,aggressor in network['coupling']:
        aggressors[aggressor]+=cap;local[node]+=cap
    ratios=[c/(c+network['ground'].get(node,0.)) for node,c in local.items() if c>0]
    return dict(net=network['name'], ground_pf=ground,coupling_pf=coupled,
                total_wire_cap_pf=ground+coupled, header_total_pf=network['total_header_pf'],
                lumped_floating_rail_charge_share_v=voltage*coupled/(ground+coupled) if ground+coupled else 0.,
                simultaneous_edge_node_upper_bound_v=voltage*max(ratios,default=0.),
                independent_single_transition_upper_bound_v=voltage*sum(ratios),
                resistor_count=len(network['resistors']),receiver_count=sum(
                    c['direction']=='I' and c['kind']=='*I' for c in network['connections']),
                receiver_pins=[c['pin'] for c in network['connections'] if c['kind']=='*I' and c['direction']=='I'],
                aggressors=[dict(net=n,coupling_pf=c) for n,c in sorted(aggressors.items(),key=lambda r:(-r[1],r[0]))])


def unextracted_rows(log, expected):
    rows={}
    for line in log.splitlines():
        if not line.startswith('UNEXTRACTED_SPEF_NET\t'):continue
        row=line.split('\t')
        require(len(row)==6 and row[1] not in rows,'COUPLING_UNEXTRACTED_ROW')
        values=[int(x) for x in row[2:]]
        require(all(x>=0 for x in values),'COUPLING_UNEXTRACTED_ROW')
        rows[row[1]]=values
    require(set(rows)==set(expected),'COUPLING_UNEXTRACTED_COVERAGE')
    return dict(excluded=sorted(n for n,v in rows.items() if v==[0,1,0,0]),
                unexplained=sorted(n for n,v in rows.items() if v!=[0,1,0,0]),
                counts_by_net=rows)


def check_extraction_pair(metadata, odb_digest, spef_digest, mapping_digest,
                          routing_digest=None, inventory_digest=None, historical_diagnostic=False):
    records=metadata['checkpoints']['extract']['rc_corners']
    matches=[corner for corner,row in records.items()
             if row['odb_sha256']==odb_digest and row['spef_sha256']==spef_digest]
    require(len(matches)==1 and metadata['mapping_sha256']==mapping_digest,'COUPLING_EXTRACTION_INPUT_MISMATCH')
    if metadata.get('provenance_schema')=='riscay-pnr-inputs-v5':
        require(routing_digest is not None and inventory_digest is not None and
                metadata['checkpoints']['route'].get('native_routing_sha256')==routing_digest and
                metadata.get('generated_inputs_sha256',{}).get('native-routing.json')==inventory_digest,
                'COUPLING_NATIVE_ROUTING_RUN_MISMATCH')
    else:
        require(historical_diagnostic,'COUPLING_HISTORICAL_DIAGNOSTIC_REQUIRED')
    return matches[0]


def classify_unextracted(odb, missing, out):
    """Only a proved single terminal without routed wire can leave wire SI."""
    from gf180_constraints import brace
    from gf180_pnr import pnr_tool
    metadata=json.loads((odb.parent/'run.json').read_text())
    runtime=pnr_tool(metadata)
    text='read_db '+brace(runtime.path(odb))+'\nset block [ord::get_db_block]\n'
    text+='foreach name [list '+' '.join(brace(n) for n in missing)+'] {\n'
    text+='  set n [$block findNet $name]\n  if {$n eq "NULL"} {error "COUPLING_NET_MISSING $name"}\n'
    text+='  puts "UNEXTRACTED_SPEF_NET\\t$name\\t[expr {[$n getWire] ne \"NULL\"}]\\t[llength [$n getITerms]]\\t[llength [$n getBTerms]]\\t[$n isConnectedByAbutment]"\n}\n'
    text+='puts COUPLING_UNEXTRACTED_COMPLETE\nexit\n'
    script=out/'unextracted-check.tcl';script.write_text(text)
    result=subprocess.run(runtime.command(['-no_init','-exit',runtime.path(script)]),capture_output=True,text=True,timeout=45)
    log=result.stdout+result.stderr;(out/'unextracted-check.log').write_text(log)
    require(result.returncode==0 and 'COUPLING_UNEXTRACTED_COMPLETE' in log,'COUPLING_UNEXTRACTED_FAILED')
    record=unextracted_rows(log,missing)
    record.update(odb_sha256=sha(odb),run_receipt_sha256=sha(odb.parent/'run.json'),
                  script_sha256=sha(script),log_sha256=sha(out/'unextracted-check.log'))
    return record


def deck(network, voltage, quiet, rising, slew, driver_ohms, offset, max_nodes=400, timestep_factor=1.):
    nodes = set(network['ground'])
    for a,b,_ in network['resistors']: nodes.update((a,b))
    nodes.update(c['node'] for c in network['connections'])
    nodes.update(c[0] for c in network['coupling'])
    require(nodes and len(nodes)<=max_nodes, 'COUPLING_SPICE_NODE_LIMIT')
    drivers=[c['node'] for c in network['connections'] if
             (c['kind'],c['direction']) in (('*I','O'),('*P','I'))]
    require(len(drivers)==1,'COUPLING_SPICE_DRIVER_COUNT')
    require(all(r>0 for _,_,r in network['resistors']), 'COUPLING_SPICE_NONPOSITIVE_R')
    require(all(math.isfinite(x) and x>0 for x in (voltage,slew,driver_ohms)) and offset>=0,
            'COUPLING_SPICE_PARAMETERS')
    labels={n:'n'+str(i) for i,n in enumerate(sorted(nodes))}
    aggs=rank(network,voltage)['aggressors'];sources={a['net']:'a'+str(i) for i,a in enumerate(aggs)}
    total=sum(network['ground'].values())+sum(c[2] for c in network['coupling'])
    end=max(12.,6.+offset+slew+10*driver_ohms*total*1e-3)
    text='Extracted victim RC sensitivity; no receiver-noise qualification\n'
    text+=f'VQUIET quiet 0 {quiet}\nRDRIVER quiet {labels[drivers[0]]} {driver_ohms}\n'
    first,last=(0.,voltage) if rising else (voltage,0.)
    for i,a in enumerate(aggs):
        start=5.+(offset if i==0 else 0.)
        text+=f'VAG{i} {sources[a["net"]]} 0 PWL(0 {first} {start}n {first} {start+slew}n {last})\n'
    for i,(node,cap) in enumerate(network['ground'].items()):
        if cap: text+=f'CG{i} {labels[node]} 0 {cap}p\n'
    for i,(a,b,res) in enumerate(network['resistors']):text+=f'R{i} {labels[a]} {labels[b]} {res}\n'
    for i,(a,_,cap,aggressor) in enumerate(network['coupling']):
        text+=f'CC{i} {labels[a]} {sources[aggressor]} {cap}p\n'
    step=min(.02,slew/20)*timestep_factor
    require(0<timestep_factor<=1,'COUPLING_SPICE_TIMESTEP')
    text+=f'.options reltol=1e-5 abstol=1e-12\n.tran {step}n {end}n 0 {step}n\n'
    # Observe every victim node, including receiver pins and internal RC peaks.
    for label in labels.values():
        text+=f'.meas tran {label}_min MIN v({label}) FROM=4n TO={end}n\n'
        text+=f'.meas tran {label}_max MAX v({label}) FROM=4n TO={end}n\n'
    text+='.end\n'
    return text,labels


def simulator():
    executable=shutil.which('ngspice')
    command=[executable] if executable else ['wsl','--exec','ngspice']
    try:
        probe=subprocess.run(command+['--version'],capture_output=True,text=True,timeout=15)
        if probe.returncode==0 and 'ngspice' in probe.stdout.lower():
            if executable:
                digest=sha(Path(executable));resolved=executable
            else:
                location=subprocess.run(['wsl','--exec','which','ngspice'],capture_output=True,text=True,timeout=15)
                require(location.returncode==0,'COUPLING_SIMULATOR_LOCATION')
                resolved=location.stdout.strip()
                hashed=subprocess.run(['wsl','--exec','sha256sum',resolved],capture_output=True,text=True,timeout=15)
                require(hashed.returncode==0 and re.fullmatch(r'[0-9a-f]{64}',hashed.stdout.split()[0]),'COUPLING_SIMULATOR_HASH')
                digest=hashed.stdout.split()[0]
            return command,dict(version=probe.stdout,executable=resolved,sha256=digest)
    except (OSError,subprocess.TimeoutExpired):pass
    return None,None


def screen(networks, ranking, out, count, voltage, driver_values, slews, offsets):
    command,tool=simulator()
    if command is None:return dict(status='unavailable',cases=[],limitation='ngspice not available')
    (out/'ngspice-version.log').write_text(tool['version'])
    cases=[];skipped=[];convergence=[]
    for ni,row in enumerate(ranking[:count]):
        network=networks[row['net']]
        for resistance in driver_values:
            for slew in slews:
                for offset in offsets:
                    for quiet in (0.,voltage):
                        for rising in (False,True):
                            key=f'v{ni}-r{resistance}-s{slew}-o{offset}-q{quiet}-e{int(rising)}'
                            try:text,labels=deck(network,voltage,quiet,rising,slew,resistance,offset)
                            except ValueError as e:
                                skipped.append(dict(net=row['net'],case=key,reason=str(e)));continue
                            path=out/(key+'.spice');path.write_text(text)
                            args=command+['-n','-b',linux(path) if command[0]=='wsl' else str(path)]
                            try:p=subprocess.run(args,capture_output=True,text=True,timeout=60)
                            except subprocess.TimeoutExpired:
                                skipped.append(dict(net=row['net'],case=key,reason='timeout'));continue
                            log=p.stdout+p.stderr;(out/(key+'.log')).write_text(log)
                            values={k:float(v) for k,v in re.findall(r'^(n\d+_(?:min|max))\s*=\s*([-+.0-9eE]+)',log,re.M)}
                            expected={label+'_'+edge for label in labels.values() for edge in ('min','max')}
                            if p.returncode or set(values)!=expected or not all(math.isfinite(v) for v in values.values()):
                                skipped.append(dict(net=row['net'],case=key,reason='incomplete-measurements'));continue
                            worst=max(labels,key=lambda n:max(abs(values[labels[n]+'_min']-quiet),abs(values[labels[n]+'_max']-quiet)))
                            cases.append(dict(net=row['net'],case=key,driver_ohms=resistance,slew_ns=slew,
                                largest_aggressor_offset_ns=offset,quiet_v=quiet,aggressor_edge='rise' if rising else 'fall',
                                minimum_v=min(values[k] for k in values if k.endswith('_min')),
                                maximum_v=max(values[k] for k in values if k.endswith('_max')),
                                worst_node=worst,worst_pin=next((c['pin'] for c in network['connections'] if c['node']==worst),None),
                                maximum_excursion_v=max(abs(values[labels[worst]+'_min']-quiet),abs(values[labels[worst]+'_max']-quiet)),
                                deck_sha256=sha(path),log_sha256=sha(out/(key+'.log'))))
        completed=[case for case in cases if case['net']==row['net']]
        if completed:
            worst=max(completed,key=lambda case:case['maximum_excursion_v'])
            text,labels=deck(network,voltage,worst['quiet_v'],worst['aggressor_edge']=='rise',worst['slew_ns'],
                             worst['driver_ohms'],worst['largest_aggressor_offset_ns'],timestep_factor=.5)
            path=out/(worst['case']+'-halfstep.spice');path.write_text(text)
            try:
                process=subprocess.run(command+['-n','-b',linux(path) if command[0]=='wsl' else str(path)],
                                       capture_output=True,text=True,timeout=60)
                log=process.stdout+process.stderr;(out/(worst['case']+'-halfstep.log')).write_text(log)
                values={k:float(v) for k,v in re.findall(r'^(n\d+_(?:min|max))\s*=\s*([-+.0-9eE]+)',log,re.M)}
                expected={label+'_'+edge for label in labels.values() for edge in ('min','max')}
                require(process.returncode==0 and set(values)==expected and all(math.isfinite(v) for v in values.values()),
                        'COUPLING_CONVERGENCE_INCOMPLETE')
                refined=max(abs(v-worst['quiet_v']) for v in values.values())
                change=abs(refined-worst['maximum_excursion_v'])/max(refined,worst['maximum_excursion_v'],1e-12)
                convergence.append(dict(net=row['net'],case=worst['case'],relative_change=change,
                                        tolerance=.01,within_tolerance=change<=.01,deck_sha256=sha(path),
                                        log_sha256=sha(out/(worst['case']+'-halfstep.log'))))
            except (ValueError,subprocess.TimeoutExpired) as e:
                skipped.append(dict(net=row['net'],case=worst['case']+'-halfstep',reason=str(e)))
    if any(not c['within_tolerance'] for c in convergence):
        skipped.append(dict(reason='timestep-convergence-exceeds-one-percent'))
    return dict(status='rc-sensitivity-only' if not skipped else 'rc-sensitivity-incomplete',cases=cases,skipped=skipped,
                simulator=tool,convergence=convergence,
                limitations=['Driver resistance values are sensitivity inputs, not characterized cell bounds',
                             'Ideal equipotential aggressors, wire-only victim RC; no receiver pin capacitors or transistor receivers',
                             'No receiver thresholds, glitch rejection, keeper history, or event immunity qualification',
                             'Finite slew/offset samples do not cover arbitrary asynchronous switching'])


def select_victims(ranking, count, victims=None):
    if victims is None:return ranking[:count]
    require(victims and len(victims)<=16 and len(victims)==len(set(victims)), 'COUPLING_VICTIM_SELECTION')
    bynet={row['net']:row for row in ranking}
    require(set(victims)<=set(bynet),'COUPLING_VICTIM_NOT_EXTRACTED_NATIVE_NET')
    return [bynet[net] for net in victims]


def run(spef,routing,inventory,out,voltage=3.3,spice_victims=2,driver_values=(100.,10000.),slews=(.02,2.),offsets=(0.,.2),odb=None,victims=None,historical_diagnostic=False):
    require(math.isfinite(voltage) and voltage>0,'COUPLING_VOLTAGE')
    require(odb is not None or historical_diagnostic,'COUPLING_MATCHING_ODB_REQUIRED')
    out.mkdir(parents=True,exist_ok=False)
    manifest=json.loads(inventory.read_text())
    selected=read_report(routing,[r['pin'] for r in manifest['anchors']])['nets']
    parsed=read_spef(spef,set(selected))
    extraction_corner=None
    if odb is not None:
        extraction_corner=check_extraction_pair(json.loads((odb.parent/'run.json').read_text()),
                                                sha(odb),sha(spef),manifest['mapping_sha256'],
                                                sha(routing),sha(inventory),historical_diagnostic)
    unextracted=None
    if odb is not None and parsed['missing']:
        unextracted=classify_unextracted(odb,parsed['missing'],out)
        parsed['missing']=unextracted['unexplained']
    ranking=sorted((rank(n,voltage) for n in parsed['networks'].values()),
                   key=lambda r:(-r['lumped_floating_rail_charge_share_v'],-r['coupling_pf'],r['net']))
    pin_nets={row[1]:row[2] for line in routing.read_text().splitlines() if (row:=line.split('\t'))[0]=='P'}
    owners=defaultdict(set)
    for anchor in manifest['anchors']:owners[pin_nets[anchor['pin']]].add(anchor['owner'])
    for row in ranking:row['direct_primitive_owners']=sorted(owners[row['net']])
    spice_ranking=select_victims(ranking,spice_victims,victims)
    result=dict(status='coupling-inventory-unqualified' if not parsed['missing'] else 'coupling-inventory-incomplete',
        physical_qualification=False,historical_diagnostic=historical_diagnostic,
        voltage_v=voltage,wire_corner=extraction_corner,selected_nets=len(selected),covered_nets=len(ranking),missing_nets=parsed['missing'],
        extracted_net_count=parsed['extracted_net_count'],hotspots=ranking,
        unextracted_single_terminal_audit=unextracted,
        spice_selection=dict(mode='explicit-native-nets' if victims is not None else 'largest-lumped-charge-ratio',
                             nets=[row['net'] for row in spice_ranking],complete_native_inventory_retained=True),
        assumptions=['Capacitance excludes cell pin capacitance (SPEF PIN_CAP NONE)',
          'Lumped floating-victim charge sharing is conservative within its lumped model, not at every distributed node',
          'Simultaneous-edge node bound assumes all aggressors make one monotonic full-rail transition together',
          'Independent-single-transition bound sums nodal injections; it permits arbitrary alignment but only one full-rail transition per coupling source',
          'Neither voltage bound establishes receiver immunity; repetitive switching, receiver regeneration, supply noise and transistor effects remain open'],
        inputs=dict(spef_sha256=sha(spef),routing_report_sha256=sha(routing),inventory_sha256=sha(inventory),
                    checker_sha256=sha(Path(__file__)),
                    native_routing_reader_sha256=sha(Path(__file__).with_name('native_routing.py'))))
    if historical_diagnostic:
        result['status']='historical-coupling-incomplete' if parsed['missing'] else 'historical-coupling-diagnostic'
        result['assumptions'].append('Historical diagnostic: native routing report/manifest may not belong to the extraction run receipt')
    if odb is not None:
        result['inputs'].update(odb_sha256=sha(odb),run_receipt_sha256=sha(odb.parent/'run.json'))
    write_json(out/'coupling.json',result)
    if spice_ranking:
        result['spice']=screen(parsed['networks'],spice_ranking,out,len(spice_ranking),voltage,driver_values,slews,offsets)
        write_json(out/'coupling.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('hotspots','spice','missing_nets','assumptions','unextracted_single_terminal_audit')},indent=2))
    print('Missing native SPEF nets:',len(parsed['missing']))
    if 'spice' in result:print('SPICE:',result['spice']['status'],len(result['spice']['cases']),'cases')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('spef',type=Path);p.add_argument('routing_report',type=Path)
    p.add_argument('inventory',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--voltage',type=float,default=3.3)
    p.add_argument('--spice-victims',type=int,default=2,help='Default number of ranked victims; --victim overrides selection')
    p.add_argument('--victim',action='append',help='Exact extracted native net to screen; repeat for up to 16 nets')
    p.add_argument('--driver-ohms',type=float,nargs='+',default=[100.,10000.])
    p.add_argument('--slew-ns',type=float,nargs='+',default=[.02,2.])
    p.add_argument('--offset-ns',type=float,nargs='+',default=[0.,.2])
    p.add_argument('--odb',type=Path,help='Matching extracted ODB; audit missing SPEF nets as single-terminal/no-wire only')
    p.add_argument('--historical-diagnostic',action='store_true',help='Explicitly allow old receipts without native-routing bindings; never current-run qualification')
    a=p.parse_args();require(a.spice_victims>=0,'COUPLING_VICTIM_COUNT')
    run(a.spef.resolve(),a.routing_report.resolve(),a.inventory.resolve(),a.output.resolve(),a.voltage,a.spice_victims,a.driver_ohms,a.slew_ns,a.offset_ns,a.odb.resolve() if a.odb else None,a.victim,a.historical_diagnostic)

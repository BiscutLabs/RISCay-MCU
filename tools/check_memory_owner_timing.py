# SPDX-License-Identifier: Apache-2.0
"""Loaded BD memory-owner guard review; no signoff claim.

Example: python tools/check_memory_owner_timing.py --group source --mapping build/.../map-r2 --output build/.../source-check
Uses the repaired live graph and actual pin loads, with reviewed keeper cuts only.
Decision composition charges the real sender CQ and credits zero work-cycle lead.
"""
from pathlib import Path
import argparse,json,math,os,re,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import native_leaf_timing as leaf
import native_stage_timing as stages
import control_relative_timing as relative
import passive_feedback_hold as feedback
import size_ordering_guards as guards
from gf180_physical import SC,write_json
from gf180_estimate import library,direct_groups,numbers,table_value
from repair_gf180_design import validate_receipt,input_files
from repair_gf180_control import require
from physical_tools import tool
from run_receipt import RunReceipt
def query(pins,role,source_edge='any',sink_edges=('rise','fall')):
    return [dict(id=f'{role}:{i}:{mode}:{edge}',role='data',mode=mode,source_edge=source_edge,
                 sink_edge=edge,sink_kind='pin',sink=pin)
            for i,pin in enumerate(sorted(set(pins))) for mode in ('min','max') for edge in sink_edges]

def context(name,sources,queries,cases,cuts):
    require(sources and queries,'CONTROL_EMPTY_CONTEXT:'+name)
    return dict(id=name,kind='data' if name.endswith('data') else 'composition',source_kind='clock',
                sources=sorted(set(sources)),queries=queries,state=dict(cases=cases,keeper_cuts=cuts))
def storage_envelope(index,lib,sources):
    """Loaded CLK/Q or latch D/G/Q bounds; no nominal period/lead credited."""
    rows=[];errors=[]
    def one(q):
        path,pin=q.rsplit('/',1);cell=index.after['cells'][path]
        require(pin=='Q' and cell['type'].startswith((SC+'dff',SC+'lat')),'CONTROL_LAUNCH_STORAGE:'+q)
        load=feedback.pin_load(index,lib,q);body=dict(direct_groups(lib[cell['type']],'pin'))[pin]
        delays=[];slews=[];arcs=[]
        for _,arc in direct_groups(body,'timing'):
            related=re.search(r'related_pin\s*:\s*"([^"]+)"',arc)
            if not related:continue
            require(related[1] in ('CLK','D','G','E','RN','SN','RESET'),'MEMORY_UNKNOWN_STORAGE_ARC')
            if related[1] in ('RN','SN','RESET'):continue
            for table,dest in (('cell_rise',delays),('cell_fall',delays),('rise_transition',slews),('fall_transition',slews)):
                for _,values in direct_groups(arc,table):
                    xs,ys=numbers(values,'index_1'),numbers(values,'index_2')
                    require(ys[0]<=load<=ys[-1],'CONTROL_LAUNCH_LOAD_EXTRAPOLATION:'+q)
                    dest.extend(table_value(values,x,load) for x in xs)
            arcs.append(related[1])
        require(delays and slews and all(math.isfinite(x) and x>=0 for x in delays+slews),'CONTROL_LAUNCH_TABLES:'+q)
        return dict(q=q,cell=cell['type'],load_pf=load,related_pins=sorted(set(arcs)),
            minimum_ns=min(delays),maximum_ns=max(delays),slew_min_ns=min(slews),slew_max_ns=max(slews))
    for q in sources:
        try:rows.append(one(q))
        except ValueError as e:errors.append(dict(q=q,error=str(e),load_pf=feedback.pin_load(index,lib,q)))
    require(rows,'CONTROL_LAUNCH_EMPTY')
    return dict(rows=rows,errors=errors,maximum_launch_ns=max(r['maximum_ns'] for r in rows),
        slew=dict(min=min(r['slew_min_ns'] for r in rows),max=max(r['slew_max_ns'] for r in rows)))
def execute(sta,tcl,text,timeout=180):
    tcl.write_text(text,encoding='utf-8',newline='\n');log=tcl.with_suffix('.log')
    with log.open('w',encoding='utf-8') as stream:
        subprocess.run(sta.command(['-no_init','-exit',sta.path(tcl)],timeout=timeout),stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=timeout+10)
    return log.read_text(encoding='utf-8')
GRAPH_OBSERVATION = r"""
proc control_graph_observe {id mode se edge roots target} {
  get_property [exact_object pin $target] arrival_${mode}_${edge}
  set best {}; set visits 0
  foreach vertex [[exact_object pin $target] vertices] {
    set it [$vertex path_iterator $edge $mode]
    while {[$it has_next]} {
      incr visits; if {$visits>20000} {error CONTROL_GRAPH_PATH_LIMIT}
      set path [$it next];set start [$path start_path]
      set name [get_full_name [$start pin]]
      set source_edge [string map {^ rise v fall} [$start edge]]
      if {[lsearch -exact $roots $name]<0 || ($se ne "any" && $se ne $source_edge)} {continue}
      set origin [sta::time_sta_ui [$start arrival]];set arrival [sta::time_sta_ui [$path arrival]]
      set delay [expr {$arrival-$origin}];set names {};set worst 0.0
      foreach p [$path pins] {
        lappend names [get_full_name $p]
        foreach e {rise fall} {set value [get_property $p slew_max_$e];if {$value>$worst} {set worst $value}}
      }
      set names [lreverse $names]
      if {[lindex $names 0] ne $name || [lindex $names end] ne $target} {error CONTROL_GRAPH_ENDPOINT}
      if {![llength $best] || ($mode eq "min" && $delay<[lindex $best 0]) || ($mode eq "max" && $delay>[lindex $best 0])} {
        set best [list $delay $origin $arrival $worst $name $source_edge $names]
      }
    }
    $it finish
  }
  if {![llength $best]} {error CONTROL_GRAPH_MISSING}
  lassign $best delay origin arrival worst name source_edge names
  row CONTROL_PATH $id $origin $arrival $delay $delay $worst $name $target $source_edge $edge
  row CONTROL_POINTS $id {*}$names
}
"""
def leaf_case(mapping,out,plan,index,ctx,corner,slew,sta,period,lib):
    p=dict(plan['native'],event=ctx['sources'][0]);text=leaf.script(mapping/'netlist.v',corner,slew,p,ctx,sta=sta,period=period)
    text=text.replace('[$arc to_string]','[get_full_name [$arc from_pin]]->[get_full_name [$arc to_pin]]')
    if ctx['id'] in ('ack-guard','reply-data'):
        text=text.replace('row RELATIVE_BEGIN\n',GRAPH_OBSERVATION+'\nrow RELATIVE_BEGIN\n')
        text='\n'.join(line for line in text.split('\n') if not line.startswith('control_batch ') and not line.startswith('if {[llength $targets]}'))
        rows=[]
        for q in ctx['queries']:
            rows.append('control_graph_observe '+' '.join(map(relative.brace,(q['id'],q['mode'],q['source_edge'],q['sink_edge'])))+' [list '+' '.join(map(relative.brace,ctx['sources']))+'] '+relative.brace(q['sink']))
        text=text.replace('set event_pin [exact_object pin ', '\n'.join(rows)+'\nset event_pin [exact_object pin ')

    # Audit automatic loop cuts across all alternatives; electrical audits below
    # cover the explicitly reported extremal paths in each legal context.
    extra='set audit_targets [list '+ ' '.join('[exact_object pin '+relative.brace(q)+']' for q in sorted({q['sink'] for q in ctx['queries']}))+']\n'
    extra+='sta::find_delays\nleaf_check_loop_cuts $roots $audit_targets {} {}\n'
    require(text.count('row RELATIVE_COMPLETE\n')==1,'CONTROL_COMPLETION_MARKER')
    text=text.replace('row RELATIVE_COMPLETE\n',extra+'row RELATIVE_COMPLETE\n')
    log=execute(sta,out/(corner+'-s'+str(slew)+'-'+ctx['id']+'.tcl'),text)
    result=leaf.parse(log,p,ctx,slew,index)
    return result
def bind_source(mapping):
    receipt=validate_receipt(mapping);proof=stages.receipt_proof(mapping,receipt)
    original=stages.receipt_original(mapping,receipt)
    live=json.loads((mapping/'netlist.json').read_text(encoding='utf-8'))
    record=json.loads((mapping/'mapping.json').read_text(encoding='utf-8'));audit=json.loads((mapping/'netlist-audit.json').read_text(encoding='utf-8'))
    manifest=json.loads((mapping/'timing-intent.json').read_text(encoding='utf-8'))['manifest']
    index=leaf.LeafIndex(original,live,proof['added_buffers'],proof['added_ties'])
    cuts=leaf.keeper_cuts(index,audit)
    owners={}
    for name in ('ram','program'):
        owner='FourPhaseSoc.ca_child_'+name+'_source';prefix='soc/ca_child_'+name+'_source'
        desc=stages.descriptor(manifest,original,record,owner+'.ca_child_reservation','bd',storage=True)
        native=guards.extend_plan(leaf.bind_plan(relative.make_plan(original,record,'bd',desc),index,desc,original,cuts),index)
        ports={}
        for b,values in index.before['boundaries'].items():
            if b.startswith(prefix+'/') and '/' not in b[len(prefix)+1:]:
                port=b[len(prefix)+1:]
                ports[port]=index.boundary(prefix,port)
        prim={}
        for binding in record['bindings']:
            for instance in binding['instances']:
                if instance.startswith(owner+'.') and '.' not in instance[len(owner)+1:]:
                    physical=audit['adapter_instances'][instance]
                    prim[instance.split('.')[-1]]=dict(path=physical,model=binding['model'],parameters=binding['parameters'],
                        cells=[dict(c,path=physical+'/'+c['name']) for c in binding['cells']])
        owners[name]=dict(owner=owner,prefix=prefix,ports=ports,primitives=prim,native=native)
    return dict(mapping=mapping,index=index,record=record,audit=audit,cuts=cuts,owners=owners)
GRAPH_OBSERVATION=GRAPH_OBSERVATION.replace('row CONTROL_POINTS $id {*}$names',"""row CONTROL_POINTS $id {*}$names
  foreach pn $names {set pp [exact_object pin $pn];row SOURCE_PIN_SLEW $pn [leaf_slew $pp rise min] [leaf_slew $pp fall min] [leaf_slew $pp rise max] [leaf_slew $pp fall max]}""")

def audit_paths(result,d,index,lib):
 result.pop('electrical_violations',None);paths=result['paths'];arcs=set()
 for path in paths.values():
  for x,y in zip(path,path[1:]):
   if x.rsplit('/',1)[0]==y.rsplit('/',1)[0]:arcs.add((x,y))
 result['loads']={q:feedback.pin_load(index,lib,q) for _,q in arcs}
 result['arc_count']=len(arcs)
 log=next(d.glob('*.log')).read_text(encoding='utf-8');sv={}
 for line in log.splitlines():
  f=line.split('\t')
  if f[0]=='SOURCE_PIN_SLEW':sv[('case',f[1])]=list(map(float,f[2:]))
 result['table_ranges']=feedback.table_ranges([dict(sample='case')],sv,index,lib,dict(cone_arcs=sorted(arcs),targets={}))
 ee=[]
 for (_,pin),vals in sv.items():
  cp,pn=pin.rsplit('/',1);body=dict(direct_groups(lib[index.after['cells'][cp]['type']],'pin'))[pn]
  mt=re.search(r'max_transition\s*:\s*([\d.eE+-]+)',body)
  mc=re.search(r'max_capacitance\s*:\s*([\d.eE+-]+)',body)
  if index.after['cells'][cp]['directions'][pn]=='output':require(mt is not None and mc is not None,'MEMORY_PIN_LIMIT_MISSING:'+pin)
  if mt and max(vals)>float(mt[1])+1e-6:ee.append(dict(pin=pin,kind='slew',actual=max(vals),limit=float(mt[1])))
  if ('/ca_primitive_' in pin or '_ca_primitive_' in pin) and max(vals)>2+1e-6:ee.append(dict(pin=pin,kind='native_slew',actual=max(vals),limit=2))
  if mc:
   load=feedback.pin_load(index,lib,pin)
   if load>float(mc[1])+1e-6:ee.append(dict(pin=pin,kind='capacitance',actual=load,limit=float(mc[1])))
 result['pin_electrical_errors']=ee
 return result

def run_sources(mapping,out,owners=('ram','program'),kinds=()):
 b=bind_source(mapping);idx=b['index'];out.mkdir(parents=True,exist_ok=False);sta=tool('sta');cases=[]
 for name in owners:
  o=b['owners'][name];p=o['prefix'];n=o['native'];pr=o['primitives'];ctxs=[]
  def source(port):return o['ports'][port][0]['source']
  def targets(primitive,port):return [r['source'] for r in idx.boundary(pr[primitive]['path'],port) if r['kind']=='pin']
  # Native publication root, true capture leaf and offer output. Eligibility launch comes from reservation input ACK.
  a=relative.driver(n['native'],'a');cap=n['lane_map'][0]['capture'];elig=pr['ca_primitive_eligibility']['path']+'/u5/CLK'
  gpath=pr.get('grant_req_ca_primitive_output_guard',{}).get('path')
  offer=idx.scalar(p+'/ca_child_reservation','out_req')[1]
  rows=[('close',cap),('eligibility_clock',elig),('offer',offer)]
  if gpath:rows += [('guarded_grant',source('grant_req'))]
  pubcases=next(c for c in n['contexts'] if c['id']=='publication')['state']['cases']
  ctxs.append(('publication',a,rows,pubcases,'rise'))
  # Decision bit propagation terminates at the real retirement rising ports and Stored input request gate.
  dp=pr['decisionReady_ca_primitive_request_guard']['path'];dreq=source('decision_req');dbits=source('decision_bits')
  # Measure guard only with real loading on its output, both polarities. Request's sender launch is charged separately.
  ctxs.append(('decision_chain',dreq,[('decision_ready',idx.scalar(dp,'q')[1])],[('port','reset',0)],'any'))
  # Actual mapped parent Boolean cones, not a borrowed owner's allowance.
  rpath=pr['ca_primitive_retirement']['path'];dataTargets=[]
  for port in ('rising','falling'):
   for row in idx.boundary(rpath,port):
    for sink in row['complete_fanout']:
     if sink.startswith(rpath+'/'):dataTargets.append(sink)
  # Only include reachable targets; walk forward through parent combinational cells before native storage/keepers.
  bynet={}
  for cp,c in idx.after['cells'].items():
   for pin,nets in c['connections'].items():
    if c['directions'][pin]=='input':
     for net in nets:bynet.setdefault(net,[]).append((cp,pin))
  seen=set();reachable=set();stack=[idx.live_net('pin',dbits)]
  while stack:
   net=stack.pop()
   if net in seen:continue
   seen.add(net)
   for cp,pin in bynet.get(net,[]):
    label=cp+'/'+pin
    if label in dataTargets:reachable.add(label);continue
    if not cp.startswith(p+'/') or cp.startswith(rpath+'/'):continue
    c=idx.after['cells'][cp]
    if c['type'].startswith((SC+'dff',SC+'lat')) or c['type']==SC+'aoi21_1':continue
    for op,nets in c['connections'].items():
     if c['directions'][op]=='output':stack.extend(nets)
  
  bitcases=[('port','reset',0),('pin',source('decision_req'),0),('pin',source('decision_ack'),0),('pin',source('reserve_req'),1),('pin',source('grant_ack'),0)]
  bitcases += [('pin',c['path']+'/A1',0) for key,prim in pr.items() for c in prim['cells'] if c['cell']==SC+'aoi21_1']
  
  if name=='program':
   storedSelected=idx.scalar(pr['ca_child_stored_buffer_in_req_ca_primitive_stored_selected']['path'],'q')[1]
   reachable.add(storedSelected)
   bitcases += [('pin',idx.scalar(p+'/ca_child_reservation','in_ack')[1],1),('pin',source('grant_bits'),1)]
  bitrows=[('decode',x) for x in sorted(reachable)]
  if name=='program':
   selectedNa=idx.scalar(pr['ca_child_stored_buffer_in_req_na_ca_primitive_stored_offer_na']['path'],'q')[1]
   readyNb=idx.scalar(pr['ca_child_stored_buffer_in_req_nb_ca_primitive_stored_offer_nb']['path'],'q')[1]
   bitrows.append(('selected_na',selectedNa))
   rolecases=[c for c in bitcases if c[1]!=source('grant_bits')]+[('pin',source('decision_bits'),1)]
   ctxs.append(('stored_role_reuse',source('grant_bits'),[('selected_na',selectedNa)],rolecases,'any'))
   ctxs.append(('stored_return',idx.scalar(dp,'q')[1],[('ready_inhibit',readyNb)],
     [('port','reset',0),('pin',source('publication_req'),1)],'fall'))
  ctxs.append(('decision_bits',dbits,bitrows,bitcases,'any'))
  # Normal-operation timing; reset assertion/recovery has separate RDC and reset-envelope obligations.
  ctxs=[(label,root,rows,conds+[('pin',source('applicationReset'),0)],se) for label,root,rows,conds,se in ctxs]
  required=set(source(port) for port in ('decision_ack','publication_ack'))|{idx.scalar(p+'/ca_child_reservation','in_ack')[1]}
  if name=='program':required|={idx.scalar(p+'/ca_child_stored_buffer','in_ack')[1],source('stored_req'),source('stored_ack'),idx.scalar(pr['ca_primitive_stored_accepted']['path'],'q')[1]}
  held=set(row['source'] for row in idx.boundary(pr['ca_primitive_reservation_return']['path'],'falling'))
  readiness=idx.scalar(dp,'q')[1] in {row['source'] for row in idx.boundary(rpath,'falling')}
  return_complete=required<=held and readiness and idx.scalar(pr['ca_primitive_reservation_return']['path'],'common')[1]==source('decision_ack')
  if kinds:ctxs=[c for c in ctxs if c[0] in kinds]
  for corner in relative.CORNERS:
   lib=library(ROOT/'.tools/physical/pdk'/(SC+corner+'.lib'))
   launch=storage_envelope(idx,lib,[dbits,dreq]);require(not launch['errors'],'SOURCE_LAUNCH_EXTRAPOLATION')
   forcing=forcing_slew_envelope(idx,lib,p);(out/name).mkdir(exist_ok=True)
   write_json(out/name/(corner+'-forcing.json'),forcing);require(not forcing['errors'],'MEMORY_FORCING_ENVELOPE')
   publication_launch=storage_envelope(idx,lib,[source('grant_bits'),source('eligible')]);require(not publication_launch['errors'],'SOURCE_PUBLICATION_LAUNCH')
   for slew in (.02,2.):
    for label,root,rows,conds,se in ctxs:
     queries=[]
     for i,(role,target) in enumerate(rows):
      for mode in ('min','max'):
       for edge in (('rise',) if label=='stored_return' or label=='publication' and role!='close' else ('fall',) if label=='publication' and role=='close' else ('rise','fall')):
        queries.append(dict(id=f'{role}:{i}:{mode}:{edge}',role='data',mode=mode,source_edge=se,sink_edge=edge,sink_kind='pin',sink=target))
     ctx=context('reply-data',[root],queries,conds,b['cuts']);pl=dict(native=n)
     d=out/name/corner/str(slew)/label;d.mkdir(parents=True)
     try:
      result=leaf_case(b['mapping'],d,pl,idx,ctx,corner,slew,sta,1000,lib)
      result=audit_paths(result,d,idx,lib)
      cases.append(dict(owner=name,corner=corner,slew=slew,kind=label,status='measured',result=result,launch=launch,publication_launch=publication_launch,return_complete=return_complete))
      print(name,corner,slew,label,[(k,round(v['delay_ns'],4)) for k,v in result['rows'].items()],flush=True)
     except Exception as e:
      cases.append(dict(owner=name,corner=corner,slew=slew,kind=label,status='error',error=str(e)));print('ERROR',name,corner,slew,label,str(e),flush=True)
     write_json(out/'measurements.json',dict(cases=cases))
 return cases

def bind_return(mapping,owner,extended=False):
    receipt=validate_receipt(mapping);proof=stages.receipt_proof(mapping,receipt)
    original=stages.receipt_original(mapping,receipt);live=json.loads((mapping/'netlist.json').read_text(encoding='utf-8'))
    record=json.loads((mapping/'mapping.json').read_text(encoding='utf-8'));audit=json.loads((mapping/'netlist-audit.json').read_text(encoding='utf-8'))
    manifest=json.loads((mapping/'timing-intent.json').read_text(encoding='utf-8'))['manifest']
    node=next(n for n in guards.nodes(manifest['design']) if n['rtl_path']==owner)
    index=leaf.LeafIndex(original,live,proof['added_buffers'],proof['added_ties']);cuts=leaf.keeper_cuts(index,audit)
    primitives={p['id']:p for p in node['primitives']};prefix='soc/'+'/'.join(owner.split('.')[1:])
    primitives={name:dict(p,path=audit['adapter_instances'][p['rtl_path']],binding=next(b for b in record['bindings'] if p['rtl_path'] in b['instances']))
                for name,p in primitives.items() if p['rtl_path'] in audit['adapter_instances']}
    def pin(ident,port):return index.scalar(primitives[ident]['path'],port)[1]
    def cells(ident,kind):
        p=primitives[ident]
        return [p['path']+'/'+c['name'] for c in p['binding']['cells'] if c['cell']==SC+kind]
    def input_pins(ident,port,lane=None):
        p=primitives[ident]
        target=port+f'[{lane}]'
        result=[p['path']+'/'+c['name']+'/'+pin for c in p['binding']['cells'] for pin,n in c['pins'].items()
                if n==port or (lane is None and n.startswith(port+'[')) or n==target]
        require(result,'RETURN_INPUT_PIN:'+ident+':'+port)
        return result
    reset=[('pin',index.scalar(prefix,p)[1],0) for p in ('reset','applicationReset')]
    banks={name:feedback.storage(record,audit,index,primitives[name]['rtl_path']) for name in ('payload','permission')}
    clocks=[b['CLK'] for _,lanes in banks.values() for b in lanes.values()]
    cqs=[b['Q'] for _,lanes in banks.values() for b in lanes.values()]
    state={name:pin(name,'q') for name,p in primitives.items() if p['model']=='ChiselAsyncAsymmetricC_v1'}
    keepers={name:cells(name,'aoi21_1')[0] for name in state}
    pending=pin('pending','q');issued=pin('issued','q');armed=pin('output_guard','q');history=pin('history_common','q')
    offers={name:pin(name,'q') for name in ('input_offer','application_offer','application_request','publication_offer','receipt_offer','output_delay')}
    contexts=[]
    for direction in ('rise','fall'):
        value=int(direction=='fall')
        cases=reset+[("pin",path+'/A1',value) for name,path in keepers.items() if name!='pending']
        # Other state is retained zero during capture, one during return. Issue
        # itself remains driven; it is the changed path under measurement.
        cases += [('pin',q,value) for n,q in state.items() if n not in ('pending','issued','released')]
        cases += [('pin',pin('permission','q'),1)]
        if direction=='rise':
            cases += [('pin',p,1) for p in input_pins('issued','common')]
        else:
            cases += [('pin',p,1) for p in input_pins('issued','rising')]
            cases += [('pin',p,0) for p in input_pins('history_common','a')]
            # Independent P launch: Rq=0 biases only upstream feedback. R is not
        # physically assumed low during retirement; measured downstream paths
        # start at P and do not traverse that biased branch.
        cases += [('pin',state['released'],0)]
        sinks=({**offers,'armed':armed,'issued':issued,'history':history} if direction=='rise' else
               {'armed':armed,'issued':issued,'history':history})
        qs=[]
        for label,target in sinks.items():
            if direction=='rise' and label=='input_offer':continue
            qs += query([target],label,direction,(direction,))
        if direction=='rise':qs += query(clocks,'capture','rise',('rise',))
        else:
            qs += query(clocks,'capture','fall',('fall',))
            for ident in ('input_offer_na','application_offer_na','application_request_na','publication_offer_na','receipt_offer_na'):
                qs += query([pin(ident,'q')],ident,'fall',('rise',))
            # These P-owned return proofs must also be low before the H tail
            # clears released; otherwise a still-high set term could reassert R.
            # Use a separate falling context below so every proof's set input
            # can remain asserted until its own common input falls.
        ctx=context('pending-'+direction,[pending],qs,cases,cuts);ctx['id']='ack-guard'
        contexts.append(dict(label='pending-'+direction,context=ctx))
    if extended:
        for name in ('pending','released','issued'):
            source=cells(name,'nor2_1')[0]+'/ZN'
            ctx=context('keeper-output-'+name,[source],query([state[name]],'keeper_output','any'),reset,cuts);ctx['id']='ack-guard'
            contexts.append(dict(label='keeper-output-'+name,context=ctx))
        # R's output may clear P as soon as R becomes visible. All P-owned
        # completion proofs then clear; measure the actual last AND input to
        # the R keeper, so regeneration need not rely on an arbitrary timer.
        cases=reset+[("pin",path+'/A1',1) for name,path in keepers.items() if name!='released']
        for name in ('pending','issued','terminal','input_returned','publication_returned','receipt_returned'):
            cases += [('pin',p,0) for p in input_pins(name,'rising')]
        qs=query([pending],'pending_clear','rise',('fall',))
        ctx=context('release-cutoff',[state['released']],qs,cases,cuts);ctx['id']='ack-guard'
        contexts.append(dict(label='release-cutoff',context=ctx))
        cases=reset+[("pin",path+'/A1',1) for name,path in keepers.items() if name not in ('pending','released')]
        # Independent P launch: Rq=0 biases only upstream feedback. R is not
        # physically assumed low during retirement; measured downstream paths
        # start at P and do not traverse that biased branch.
        cases += [('pin',state['released'],0)]
        cases += [('pin',p,1) for p in input_pins('released','common')]
        for name in ('terminal','input_returned','publication_returned','receipt_returned'):
            cases += [('pin',p,0) for p in input_pins(name,'rising')]
        ctx=context('proof-withdraw',[pending],query([keepers['released']+'/B'],'release_set_withdraw','fall',('fall',)),cases,cuts);ctx['id']='ack-guard'
        contexts.append(dict(label='proof-withdraw',context=ctx))
        cases=reset+[("pin",path+'/A1',1) for name,path in keepers.items() if name not in ('pending','released')]
        # Independent P launch: Rq=0 biases only upstream feedback. R is not
        # physically assumed low during retirement; measured downstream paths
        # start at P and do not traverse that biased branch.
        cases += [('pin',state['released'],0)]
        for name in ('terminal','input_returned','publication_returned','receipt_returned'):
            cases += [('pin',p,1) for p in input_pins(name,'rising')]
        qs=query([state[n] for n in ('terminal','input_returned','publication_returned','receipt_returned')],'proofs_clear','fall',('fall',))
        ctx=context('proofs-clear',[pending],qs,cases,cuts);ctx['id']='ack-guard'
        contexts.append(dict(label='proofs-clear',context=ctx))
        for name in ('terminal','input_returned','publication_returned','receipt_returned'):
            cases=reset+[('pin',keepers['released']+'/A1',0)]
            cases += [('pin',p,1) for p in input_pins('released','common')]
            cases += [('pin',state[n],1) for n in ('terminal','input_returned','publication_returned','receipt_returned') if n!=name]
            source=cells(name,'nor2_1')[0]+'/ZN'
            ctx=context('proof-commit-'+name,[source],query([state['released']],'proof_commit','rise',('rise',)),cases,cuts);ctx['id']='ack-guard'
            contexts.append(dict(label='proof-commit-'+name,context=ctx))
        cases=reset+[('pin',keepers['released']+'/A1',1)]
        cases += [('pin',p,0) for p in input_pins('released','rising')]
        ctx=context('history-return',[history],query([state['released']],'released_clear','fall',('fall',)),cases,cuts);ctx['id']='ack-guard'
        contexts.append(dict(label='history-return',context=ctx))
    return dict(owner=owner,primitive_paths={k:v['path'] for k,v in primitives.items()},
        clocks=clocks,cqs=cqs,state=state,keepers=keepers,contexts=contexts,
        native=dict(variant='bd',event=pending,phase={},native={},payload_width=33,leaf_anchored=True)),index

def values(case,label,mode,edge=None):
 rows=[v['delay_ns'] for key,v in case['result']['rows'].items() if key.startswith(label+':') and ':'+mode+':' in key and (edge is None or key.endswith(':'+edge))]
 require(rows,'MEMORY_MARGIN_ROWS:'+label);return (min if mode=='min' else max)(rows)

def source_margins(cases):
 result=[]
 for owner,corner in sorted({(c['owner'],c['corner']) for c in cases}):
  group=[c for c in cases if c['owner']==owner and c['corner']==corner]
  def bound(kind,label,mode,edge=None):return (min if mode=='min' else max)(values(c,label,mode,edge) for c in group if c['kind']==kind)
  launch=max(c['launch']['maximum_launch_ns'] for c in group)
  pub=next(c for c in group if c['kind']=='publication')['publication_launch']['rows']
  offer=bound('publication','offer','min','rise')
  rows=dict(role_publication=.8*offer-1.2*(bound('publication','close','max','fall')+pub[0]['maximum_ns'])-2,
   eligibility_publication=.8*offer-1.2*(bound('publication','eligibility_clock','max','rise')+pub[1]['maximum_ns'])-2,
   decision_setup=.8*bound('decision_chain','decision_ready','min')-1.2*(launch+bound('decision_bits','decode','max'))-2)
  if owner=='program':
   inhibition=bound('stored_return','ready_inhibit','max','rise')
   # New role/decision data is permitted at ready falling, earlier than either ACK falling.
   # Left na falling must follow right nb rising at the actual OR input drivers.
   for kind in ('decision_bits','stored_role_reuse'):
    rows['stored_return_'+kind]=.8*bound(kind,'selected_na','min','fall')-1.2*inhibition-2
  require(all(c['return_complete'] for c in group),'SOURCE_RETURN_OBLIGATION')
  result.append(dict(owner=owner,corner=corner,margins_ns=rows))
 return result

def forcing_slew_envelope(index,lib,prefix):
    prefix=prefix.rstrip('/');allcells=index.after['cells'];drivers={}
    for path,c in allcells.items():
        for pin,nets in c['connections'].items():
            if c['directions'][pin]=='output':
                for net in nets:drivers[net]=(path,pin)
    boundary={}
    for label in index.before['boundaries']:
        if not label.startswith(prefix+'/') or '/' in label[len(prefix)+1:]:continue
        for row in index.boundary(prefix,label[len(prefix)+1:]):
            if row['kind']=='pin' and not row['source'].startswith(prefix+'/'):
                boundary[index.live_net('pin',row['source'])]=dict(port=label,source=row['source'],slew_ns=[.02,2.])
    cells={p:c for p,c in allcells.items() if p.startswith(prefix+'/')};added=[];pending=list(cells)
    while pending:
        path=pending.pop()
        for pin,nets in allcells[path]['connections'].items():
            if allcells[path]['directions'][pin]!='input':continue
            for net in nets:
                if net in boundary or index.normalized(net)[0]=='constant':continue
                require(net in drivers,'MEMORY_SLEW_UNDRIVEN')
                dp,op=drivers[net]
                if dp in cells:continue
                require(re.fullmatch(re.escape(SC)+r'(?:clk)?(?:buf|inv)_\d+',allcells[dp]['type']) is not None,'MEMORY_SLEW_UNDECLARED_SOURCE:'+dp)
                cells[dp]=allcells[dp];pending.append(dp);added.append(dp)
    outputs=[];excluded=[];errors=[];cache={}
    for path,c in cells.items():
        for out,body in direct_groups(lib[c['type']],'pin'):
            if c['directions'].get(out)!='output':continue
            q=path+'/'+out
            try:load=feedback.pin_load(index,lib,q)
            except ValueError as e:
                if str(e)=='FEEDBACK_EMPTY_LOAD':continue
                raise
            values=[];sources=[]
            for _,arc in direct_groups(body,'timing'):
                m=re.search(r'related_pin\s*:\s*"([^"]+)"',arc)
                if not m:continue
                inp=m[1]
                if c['type'].startswith((SC+'dff',SC+'lat')) and inp in ('RN','SN','RESET'):
                    excluded.append(q+':'+inp);continue
                if c['type'].startswith((SC+'dff',SC+'lat')):require(inp in ('D','E','G','CLK'),'MEMORY_UNKNOWN_STORAGE_ARC:'+inp)
                if index.normalized(c['connections'][inp][0])[0]=='constant':continue
                sources.append(inp)
                for table in ('rise_transition','fall_transition'):
                    for _,tbl in direct_groups(arc,table):
                        key=c['type'],out,inp,table,load,tbl
                        if key not in cache:
                            xs,ys=numbers(tbl,'index_1'),numbers(tbl,'index_2')
                            require(ys[0]<=load<=ys[-1] and xs[0]<=.02<=2.<=xs[-1],'MEMORY_FORCING_TABLE_RANGE:'+q)
                            cache[key]=[table_value(tbl,x,load) for x in sorted({.02,2.,*(x for x in xs if .02<x<2.)})]
                        values.extend(cache[key])
            if not values:continue
            require(all(math.isfinite(v) for v in values),'MEMORY_FORCING_NONFINITE')
            cap=re.search(r'max_capacitance\s*:\s*([\d.eE+-]+)',body);slew=re.search(r'max_transition\s*:\s*([\d.eE+-]+)',body)
            require(cap is not None and slew is not None,'MEMORY_FORCING_PIN_LIMIT_MISSING:'+q)
            row=dict(pin=q,load_pf=load,related_inputs=sorted(set(sources)),minimum_ns=min(values),maximum_ns=max(values),max_capacitance_pf=float(cap[1]),max_transition_ns=float(slew[1]));outputs.append(row)
            if min(values)<.02-1e-6 or max(values)>min(2.,float(slew[1]))+1e-6 or load>float(cap[1])+1e-6:errors.append(row)
    require(outputs,'MEMORY_FORCING_EMPTY')
    return dict(scope='Normal-operation all-cell closed .02--2ns forcing envelope; no wire or reset-transition qualification',
        boundary=list(boundary.values()),included_parent_buffers=sorted(added),excluded_storage_reset_arcs=sorted(set(excluded)),
        outputs=outputs,errors=errors)

def keeper_envelopes(plan,index,lib):
    """Bound regeneration in a closed 0.02--2ns actual-load slew envelope."""
    result={}
    for name in ('pending','released','issued','terminal','input_returned','publication_returned','receipt_returned'):
        prefix=plan['primitive_paths'][name]+'/'
        cells=[(path,c) for path,c in index.after['cells'].items() if path.startswith(prefix)]
        rows=[];interval=(.02,2.)
        for kind in ('aoi21_1','nor2_1'):
            selected=[(p,c) for p,c in cells if c['type']==SC+kind]
            require(len(selected)==1,'RETURN_KEEPER_BINDING:'+name)
            path,cell=selected[0];load=feedback.pin_load(index,lib,path+'/ZN')
            body=dict(direct_groups(lib[cell['type']],'pin'))['ZN'];values=[];slews=[]
            for _,arc in direct_groups(body,'timing'):
                related=re.search(r'related_pin\s*:\s*"([^"]+)"',arc)
                if not related:continue
                for table,destination in (('cell_rise',values),('cell_fall',values),('rise_transition',slews),('fall_transition',slews)):
                    if destination is values and related[1]!='A1': continue
                    # Include set/common arcs in the AOI transition envelope,
                    # so entry to the keeper has the same slew bound as feedback.
                    # POR A2 is constant here; reset distribution is a separate gate.
                    if destination is slews and kind=='nor2_1' and related[1]!='A1': continue
                    for _,tbl in direct_groups(arc,table):
                        xs,ys=numbers(tbl,'index_1'),numbers(tbl,'index_2')
                        require(ys[0]<=load<=ys[-1],'RETURN_KEEPER_LOAD_EXTRAPOLATION')
                        require(xs[0]<=interval[0]<=interval[1]<=xs[-1],'RETURN_KEEPER_SLEW_EXTRAPOLATION')
                        probes=sorted({*interval,*(x for x in xs if interval[0]<x<interval[1])})
                        destination.extend(table_value(tbl,x,load) for x in probes)
            require(values and slews and all(math.isfinite(v) for v in values+slews),'RETURN_KEEPER_TABLES')
            rows.append(dict(path=path,load_pf=load,input_slew_ns=interval,maximum_ns=max(values),output_slew_ns=[min(slews),max(slews)]))
            interval=(min(slews),max(slews))
        require(.02<=interval[0]<=interval[1]<=2.,'RETURN_KEEPER_SLEW_NOT_CLOSED')
        result[name]=dict(arcs=rows,maximum_ns=sum(r['maximum_ns'] for r in rows))
    return result

def evaluate_return_cases(cases):
    groups={}
    for case in cases:
        groups.setdefault((case['owner'],case['corner']),{}).setdefault(case['kind'],[]).append(case)
    answer=[]
    for key,group in groups.items():
        def bound(kind,role,mode,edge=None):
            values=[v['delay_ns'] for case in group[kind] for k,v in case['result']['rows'].items() if k.startswith(role+':') and ':'+mode+':' in k and (edge is None or k.endswith(':'+edge))]
            require(values,'RETURN_MISSING_BOUND:'+kind+':'+role+':'+mode)
            return (min if mode=='min' else max)(values)
        rise=group['pending-rise'][0];keepers=rise['keepers'];pulse=rise['pulse_ns']
        launch=rise['launch'];require(not launch['errors'],'RETURN_CAPTURE_CQ')
        margins={};hi=bound('pending-rise','capture','max');lo=bound('pending-fall','capture','max')
        for offer in ('application_offer','application_request','publication_offer','receipt_offer'):
            margins[offer+'_after_data']=.8*bound('pending-rise',offer,'min')-1.2*(hi+launch['maximum_launch_ns'])-2
        history=bound('pending-fall','history','min')
        inhibits=max(bound('pending-fall',n,'max') for n in ('input_offer_na','application_offer_na','application_request_na','publication_offer_na','receipt_offer_na'))
        margins['history_after_inhibits']=.8*history-1.2*inhibits-2
        margins['history_after_proofs']=.8*history-1.2*bound('proofs-clear','proofs_clear','max')-2
        for direction,latest in (('rise',hi),('fall',lo)):
            margins['capture_'+direction+'_pulse']=.8*bound('pending-'+direction,'armed','min')-1.2*latest-pulse-2
        margins['return_keeper_lifetime']=.8*bound('pending-fall','armed','min')-1.2*max(keepers[n]['maximum_ns'] for n in ('pending','released','issued'))-2
        pclear=bound('release-cutoff','pending_clear','min')
        lifetime=bound('keeper-output-released','keeper_output','min','rise')+pclear+bound('proof-withdraw','release_set_withdraw','min')
        margins['released_retained_before_set_withdraw']=.8*lifetime-1.2*keepers['released']['maximum_ns']-2
        margins['pending_retained_before_input_withdraw']=.8*bound('pending-rise','output_delay','min')-1.2*keepers['pending']['maximum_ns']-2
        for name in ('terminal','input_returned','publication_returned','receipt_returned'):
            margins[name+'_retained_before_clear']=.8*(bound('proof-commit-'+name,'proof_commit','min')+pclear)-1.2*keepers[name]['maximum_ns']-2
        require(bound('history-return','released_clear','min')>=0,'RETURN_HISTORY_ACKNOWLEDGEMENT')
        answer.append(dict(owner=key[0],corner=key[1],margins_ns=margins))
    return answer

def run_returns(mapping,out,owners,corners,labels=()):
 out.mkdir(parents=True,exist_ok=False);sta=tool('sta');cases=[]
 for owner in owners:
  plan,index=bind_return(mapping,'FourPhaseSoc.ca_child_'+owner+'_return',extended=True)
  for corner in corners:
   lib=library(ROOT/'.tools/physical/pdk'/(SC+corner+'.lib'))
   launch=storage_envelope(index,lib,plan['cqs']);require(not launch['errors'],'SOURCE_LAUNCH_EXTRAPOLATION')
   forcing=forcing_slew_envelope(index,lib,'soc/ca_child_'+owner+'_return');(out/owner).mkdir(exist_ok=True)
   write_json(out/owner/(corner+'-forcing.json'),forcing);require(not forcing['errors'],'MEMORY_FORCING_ENVELOPE')
   keepers=keeper_envelopes(plan,index,lib)
   pulse=max(guards.scalar_table_max(lib[SC+n],'min_pulse_width',('rise_constraint','fall_constraint')) for n in ('dffrnq_1','dffsnq_1'))
   for slew in (.02,2.):
    for item in plan['contexts']:
     if labels and item['label'] not in labels:continue
     d=out/owner/corner/str(slew)/item['label'];d.mkdir(parents=True)
     record=dict(owner=owner,corner=corner,slew=slew,kind=item['label'],status='measured',launch=launch,pulse_ns=pulse,keepers=keepers)
     try:record['result']=audit_paths(leaf_case(mapping,d,plan,index,item['context'],corner,slew,sta,1000,lib),d,index,lib)
     except Exception as e:record.update(status='error',error=str(e))
     cases.append(record);write_json(out/'measurements.json',dict(cases=cases))
     print(owner,corner,slew,item['label'],record['status'],record.get('error',''),flush=True)
 return cases

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--mapping',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--group',choices=('source','return'),required=True)
 parser.add_argument('--owner',action='append',choices=('ram','program'));parser.add_argument('--kind',action='append')
 args=parser.parse_args();owners=args.owner or ('ram','program');status='fail'
 inputs=[args.mapping/n for n in ('mapping.json','netlist.json','netlist.v','netlist-audit.json','timing-intent.json','electrical-repair/receipt.json','electrical-repair/proof.json','electrical-repair/reference/netlist.json')]
 inputs+=input_files(args.mapping)
 inputs+=list((ROOT/'.tools/physical/pdk').glob(SC+'*.lib'))+list((ROOT/'.tools/gf180-sram').glob('*.lib'))
 sources=[Path(__file__),relative.PROBE,*[Path(m.__file__) for m in list(sys.modules.values()) if getattr(m,'__file__',None) and Path(m.__file__).parent==ROOT/'tools'],*tool('sta').input_files()]
 receipt=RunReceipt(args.output/'receipt.json',inputs=inputs,tools=sources)
 try:
  kinds={owner:({'publication','decision_chain','decision_bits'}|({'stored_return','stored_role_reuse'} if owner=='program' else set())) if args.group=='source' else {r['label'] for r in bind_return(args.mapping,'FourPhaseSoc.ca_child_'+owner+'_return',True)[0]['contexts']} for owner in owners}
  require(not args.kind or set(args.kind)<=set.union(*kinds.values()),'MEMORY_UNKNOWN_CONTEXT')
  expected={(o,c,s,k) for o in owners for c in relative.CORNERS for s in (.02,2.) for k in kinds[o] if not args.kind or k in args.kind}
  cases=run_sources(args.mapping,args.output,owners,args.kind or ()) if args.group=='source' else run_returns(args.mapping,args.output,owners,relative.CORNERS,args.kind or ())
  actual=[(c['owner'],c['corner'],c['slew'],c['kind']) for c in cases]
  require(len(actual)==len(set(actual)) and set(actual)==expected,'MEMORY_CONTEXT_COVERAGE')
  require(all(c['status']=='measured' and not c['result']['table_ranges']['range_errors'] and not c['result']['pin_electrical_errors'] for c in cases),'MEMORY_OWNER_TIMING_INCOMPLETE')
  margins=[] if args.kind else source_margins(cases) if args.group=='source' else evaluate_return_cases(cases)
  write_json(args.output/'summary.json',dict(scope='selected measurements only' if args.kind else 'complete local memory-owner obligations; zero wire RC, not signoff',margins=margins))
  require(all(v>=0 for r in margins for v in r['margins_ns'].values()),'MEMORY_OWNER_MARGIN')
  status='pass'
 finally:
  receipt.finish(outputs=sorted(p for p in args.output.rglob('*') if p.is_file()),status=status,coverage=dict(group=args.group,owners=list(owners),selected_contexts=args.kind))

# SPDX-License-Identifier: Apache-2.0
"""Enumerate local adapter source/sink polarities and literal constant proofs.

Feedback keeper arcs are cut exactly as in feedback-cuts.tcl. These are local
forward-path probes, never keeper stability or whole-controller qualification.
"""
from collections import defaultdict
import re
from gf180_physical import SC


def gates(cells):
    edges=[]
    for c in cells:
        kind=c['cell'].removeprefix(SC); p=c['pins']; name=c['name']
        outputs=[x for x in ('Z','ZN') if x in p]
        if not outputs:continue
        out=outputs[0]
        if kind.startswith(('dff','lat')):continue
        if kind.startswith(('buf_','clkbuf_','dlyd_','and','or')): signs=[0]
        elif kind.startswith(('inv_','clkinv_','nand','nor','aoi','oai')): signs=[1]
        elif kind.startswith('xor'): signs=[0,1]
        else:raise ValueError('UNKNOWN_PROBE_ARC_'+kind)
        for pin in p:
            if pin==out:continue
            # The physical C-element's retained keeper feedback is a separate
            # obligation. Never traverse it cyclically to invent a short path.
            if kind=='aoi21_1' and pin=='A1' and p[pin]=='state':continue
            for inv in signs:edges.append((name+'/'+pin,name+'/'+out,inv))
    return edges


def constant_outputs(cells, input_values):
    values=dict(input_values)
    def conjunction(xs):return 0 if 0 in xs else 1 if all(x==1 for x in xs) else None
    def disjunction(xs):return 1 if 1 in xs else 0 if all(x==0 for x in xs) else None
    def invert(x):return None if x is None else 1-x
    changed=True
    while changed:
        changed=False
        for c in cells:
            kind=c['cell'].removeprefix(SC); p=c['pins']
            out=next((x for x in ('Z','ZN') if x in p),None)
            if out is None:continue
            xs=[values.get(n) for k,n in p.items() if k!=out]
            value=None
            if kind.startswith(('buf_','clkbuf_','dlyd_')):value=xs[0]
            elif kind.startswith(('inv_','clkinv_')):value=invert(xs[0])
            elif kind.startswith('and'):value=conjunction(xs)
            elif kind.startswith('or'):value=disjunction(xs)
            elif kind.startswith('nand'):value=invert(conjunction(xs))
            elif kind.startswith('nor'):value=invert(disjunction(xs))
            elif kind.startswith('xor') and all(x is not None for x in xs):value=sum(xs)%2
            elif kind=='aoi21_1':
                value=invert(disjunction([conjunction([values.get(p['A1']),values.get(p['A2'])]),values.get(p['B'])]))
            if value is not None:
                n=p[out]
                if n in values and values[n]!=value:raise ValueError('CONFLICTING_CONSTANT_PROOF')
                if n not in values:values[n]=value;changed=True
    return values


def plan(row,binding,root,flat_cells):
    cells=binding['cells']; roots=root+'/'
    consumers=defaultdict(list); producers=defaultdict(list)
    input_values={"1'b0":0,"1'b1":1}
    for c in cells:
        for pin,net in c['pins'].items():
            ref=c['name']+'/'+pin
            (producers if pin in ('Z','ZN','Q') else consumers)[net].append(ref)
            bit=flat_cells[roots+c['name']]['connections'][pin][0]
            if bit[0]=='constant' and bit[1] in ('0','1'):
                value=int(bit[1])
                if net in input_values and input_values[net]!=value:raise ValueError('CONFLICTING_CONSTANT_PROOF')
                input_values[net]=value
    values=constant_outputs(cells,input_values)
    pin_values={c['name']+'/'+pin:values[net] for c in cells for pin,net in c['pins'].items() if net in values}
    arcs=defaultdict(list)
    for a,b,sign in gates(cells):arcs[a].append((b,sign))
    for net,ps in producers.items():
        for a in ps:
            for b in consumers[net]:arcs[a].append((b,0))
    sources=[p.removeprefix(roots) for p in sorted(set(row['from_pins']))]
    sinks=[p.removeprefix(roots) for p in sorted(set(row['to_pins']))]
    if any(not p.startswith(roots) for p in row['from_pins']+row['to_pins']):raise ValueError('PROBE_OUTSIDE_ADAPTER')
    pairs=[]
    reset_sources=[c['name']+'/'+pin for c in cells for pin,net in c['pins'].items() if net=='reset' and pin not in ('Z','ZN','Q')]
    for source in sources+reset_sources:
        if source in pin_values:continue
        seen={(source,0)};pending=list(seen)
        while pending:
            pin,sign=pending.pop()
            for dest,inv in arcs[pin]:
                state=(dest,sign^inv)
                if state not in seen:seen.add(state);pending.append(state)
        for sink in sinks:
            if sink in pin_values:continue
            # A literal-one data input can leave only reset able to change q.
            # Keep that reset measurement separate from the data timing bound.
            if source in reset_sources and any(p['sink']==roots+sink for p in pairs):continue
            pairs += [dict(source=roots+source,sink=roots+sink,inverted=bool(inv),reset_only=source in reset_sources)
                      for inv in (0,1) if (sink,inv) in seen]
    dynamic_sinks=set(sinks)-pin_values.keys()
    covered={p['sink'].removeprefix(roots) for p in pairs}
    if dynamic_sinks!=covered:raise ValueError('LOCAL_PROBE_GRAPH_UNCOVERED_'+row['id'])
    return dict(root=root,pairs=pairs,
        constant_sources={roots+p:pin_values[p] for p in sources if p in pin_values},
        constant_sinks={roots+p:pin_values[p] for p in sinks if p in pin_values},
        constant_evidence=input_values,
        scope='local forward paths; keeper feedback stability, reset and full-controller timing remain open')

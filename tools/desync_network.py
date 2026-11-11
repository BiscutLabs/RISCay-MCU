# SPDX-License-Identifier: Apache-2.0
"""Generate the controller graph from witnessed data/phase/gate dependencies.

The event-equation model is an untimed ordering screen, not a physical model.
It follows the actual enable inverter in the request keeper. Matched-delay and
leaf-enable timing remain separate obligations; no guessed waits appear here.
"""
from collections import defaultdict
from desync_graph import compose


def connections(partition, flop_bank='cpu'):
    rows = {b+'.'+p: dict(request=[], ack=[], same=[], closed=[], rise=[])
            for b in sorted(partition['banks']) for p in 'ms'}
    def link(a,b):
        rows[b]['request'].append(a+'.B'); rows[a]['ack'].append(b+'.A')
    for bank in partition['banks']:
        phases=('s','m') if partition['bank_phases'][bank]=='fall' else ('m','s')
        link(bank+'.'+phases[0],bank+'.'+phases[1])
    for edge in partition['phase_edges']:
        if edge['source'].startswith('@'): continue
        if not edge.get('witnesses'): raise ValueError('DESYNC_UNWITNESSED_DEPENDENCY')
        source=edge['source']+('.m' if edge['source_phase']=='fall' else '.s')
        if edge['role']=='data' and edge['source']==edge['target']==flop_bank: continue
        if edge['role'] in ('gate','falling_gate'):
            if edge['role']=='gate' and edge['target_phase']=='fall': continue
            target=edge['target']+('.m' if edge['target_phase']=='fall' else '.s')
            if target==flop_bank+'.s':
                rows[flop_bank+'.m']['rise'].append(source+'.A')
                rows[source]['closed'].append(flop_bank+'.m.N')
                rows[source]['request'].append(flop_bank+'.s.B')
            else:
                rows[target]['closed'].append(source+'.A')
                rows[source]['closed'].append(target+'.A')
                link(source,target); link(target,source)
        else:
            target=edge['target']+('.s' if edge['target_phase'] in ('fall','macro') else '.m')
            if source[-1]!=target[-1]: link(source,target)
            elif source!=target:
                rows[target]['same'].append(source+'.A')
                rows[source]['request'].append(target+'.N')
    for macro in partition.get('macros',[]):
        bank=macro['bank']; rows[bank+'.s']['closed'].append(bank+'.m.A')
    for label,row in rows.items():
        for field in row: row[field]=sorted(set(row[field]))
        if not row['request']:row['request']=list(row['same'])
        if not row['request'] or not row['ack']: raise ValueError('DESYNC_CONTROLLER_DISCONNECTED:'+label)
    return rows


class EventModel:
    """Atomic keeper/inverter equations; no cell-delay or pulse-width claim."""
    def __init__(self,partition,*,stop=True):
        self.plan=connections(partition); self.state={}; self.func={}; self.trace=[]
        self.graph=compose(partition,['cpu'],phase_aware=True)
        self.mark=[r['tokens'] for r in self.graph['arcs']]
        self.incoming=defaultdict(list);self.outgoing=defaultdict(list)
        for i,r in enumerate(self.graph['arcs']):
            self.incoming[r['target']].append(i);self.outgoing[r['source']].append(i)
        for label in self.plan:
            self.state.update({label+'.A':int(label.endswith('.s')),label+'.B':0,
                               label+'.N':int(label.endswith('.m'))})
        downstream=self.join('cpu.downstream',self.plan['cpu.s']['ack'],0)
        for label,row in self.plan.items():
            request=self.join(label+'.R',row['request'],0)
            ack=(self.join('cpu.publicationReady',[downstream,'cpu.m.A'],0) if label=='cpu.s' else
                 self.join(label+'.O',row['ack'],int(label.endswith('.m'))))
            if label=='power.m' and stop:
                power_request=request;request='grant0'
            if label=='cpu.m':
                self.state['cpu.captureReady']=0
                self.func['cpu.captureReady']=lambda s,r=request,d=downstream:int(s[r] and
                    (s['cpu.captureReady'] or (s[d] and s['cpu.s.B'])))
                request='cpu.captureReady'
            a,b,n=label+'.A',label+'.B',label+'.N'
            def update(s,r=request,o=ack,a=a,b=b,row=row):
                setting=s[r] and not s[b] and all(s[q] for q in row['same']+row['rise'])
                holding=s[r] or not s[b] or not s[o] or any(s[q] for q in row['same']) or not all(s[q] for q in row['closed'])
                return int(setting or (s[a] and holding))
            self.func[a]=update
            # Actual request keeper reads enable, not A before its inverter.
            self.func[b]=lambda s,b=b,n=n,o=ack:int(not s[n] and (s[b] or not s[o]))
            self.func[n]=lambda s,a=a:1-s[a]
        if stop:
            self.state.update(run=1,stopPending=0,grant0=0,grant1=0)
            self.func['stopPending']=lambda s:1-s['run'] if s['run']==s['grant1'] else s['stopPending']
            # Atomic exclusion screen only; silicon uses the filtered Mutex.
            self.func['grant0']=lambda s,r=power_request:int(s[r] and (s['grant0'] or not s['grant1']))
            self.func['grant1']=lambda s:int(s['stopPending'] and (s['grant1'] or not s['grant0']))

    def join(self,name,inputs,initial):
        if len(inputs)==1:return inputs[0]
        self.state[name]=initial
        self.func[name]=lambda s,ns=inputs,n=name:s[ns[0]] if len({s[i] for i in ns})==1 else s[n]
        return name

    def step(self,rng):
        enabled=[n for n,f in self.func.items() if f(self.state)!=self.state[n]]
        if not enabled:return False
        name=rng.choice(enabled);value=self.func[name](self.state)
        if name.endswith('.A') and name!='cpu.s.A':
            transition=('cpu.rise' if value else 'cpu.fall') if name=='cpu.m.A' else name[:-2]+('+' if value==0 else '-')
            if any(not self.mark[i] for i in self.incoming[transition]):
                raise ValueError('DESYNC_CONTROLLER_ORDER:'+transition)
            for i in self.incoming[transition]:self.mark[i]=0
            if any(self.mark[i] for i in self.outgoing[transition]):
                raise ValueError('DESYNC_CONTROLLER_UNSAFE:'+transition)
            for i in self.outgoing[transition]:self.mark[i]=1
            self.trace.append(transition)
        self.state[name]=value
        return True

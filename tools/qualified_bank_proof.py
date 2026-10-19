"""Conservative mapped-bank independence under an inactive reader qualifier.

Every state output and unrelated input is free. A Liberty truth-table enclosure
propagates constants and possible bank dependence, overapproximating correlations.
Only reviewed keeper *input arcs* are state boundaries; no output net is cut.
"""
import ast
from functools import lru_cache
from itertools import product
from repair_gf180_design import logic_signature
from collections import defaultdict, deque


class StorageFrontier:
    """Enumerate every first storage sink; never silently drop an unknown domain."""
    def __init__(self, cells, periodic, native, sc, sram):
        self.cells,self.periodic,self.native=cells,set(periodic),set(native)
        self.sc,self.sram=sc,sram
        self.consumers=defaultdict(list);self.excluded=set()
        for path,c in cells.items():
            for pin,nets in c['connections'].items():
                if c['directions'][pin]=='input':
                    for n in nets:self.consumers[n].append((path,pin))

    def classify(self,path):
        if path in self.periodic:return 'periodic'
        if path in self.native:return 'native'
        raise ValueError('BANK_UNKNOWN_STORAGE_DOMAIN:'+path)

    def endpoints(self,sources):
        todo=deque(n for p in sources for n in self.cells[p.rsplit('/',1)[0]]['connections'][p.rsplit('/',1)[1]])
        seen=set();ends=set()
        while todo:
            n=todo.popleft()
            if n in seen:continue
            seen.add(n)
            for path,pin in self.consumers[n]:
                c=self.cells[path]
                if c['type'].startswith((self.sc+'dff',self.sc+'lat')):
                    if pin!='D':raise ValueError('BANK_NON_DATA_STORAGE_FANOUT:'+path+'/'+pin)
                    self.classify(path);ends.add(path+'/D')
                elif c['type']==self.sram:
                    raise ValueError('BANK_UNEXPECTED_MACRO_FANOUT:'+path+'/'+pin)
                else:
                    todo.extend(n for p,ns in c['connections'].items() if c['directions'][p]=='output' for n in ns)
        return sorted(ends)

    def periodic_targets(self,sources):
        ends=self.endpoints(sources)
        self.excluded.update(p for p in ends if self.classify(p.rsplit('/',1)[0])=='native')
        return [p for p in ends if self.classify(p.rsplit('/',1)[0])=='periodic']


@lru_cache(maxsize=256)
def expression(text):
    node=ast.parse(text.replace('!', '~'),mode='eval').body
    def check(n):
        if isinstance(n,ast.Name):return
        if isinstance(n,ast.Constant) and type(n.value) is int and n.value in (0,1):return
        if isinstance(n,ast.UnaryOp) and isinstance(n.op,ast.Invert):check(n.operand);return
        if isinstance(n,ast.BinOp) and isinstance(n.op,(ast.BitAnd,ast.BitOr,ast.BitXor)):
            check(n.left);check(n.right);return
        raise ValueError('BANK_QUALIFIER_UNSUPPORTED_FUNCTION')
    check(node)
    return node


def evaluate(node,values):
    if isinstance(node,ast.Name):return values[node.id]
    if isinstance(node,ast.Constant):return node.value
    if isinstance(node,ast.UnaryOp):return 1 ^ evaluate(node.operand,values)
    a,b=evaluate(node.left,values),evaluate(node.right,values)
    if isinstance(node.op,ast.BitAnd):return a & b
    if isinstance(node.op,ast.BitOr):return a | b
    return a ^ b


@lru_cache(maxsize=4096)
def enclose(function,inputs):
    node=expression(function)
    known={p:v for p,v,d in inputs if v is not None}
    unknown=[(p,d) for p,v,d in inputs if v is None]
    outputs=set();groups={}
    for bits in product((0,1),repeat=len(unknown)):
        values=dict(known);values.update((p,b) for (p,d),b in zip(unknown,bits))
        result=evaluate(node,values);outputs.add(result)
        external=tuple(b for (p,d),b in zip(unknown,bits) if not d)
        groups.setdefault(external,set()).add(result)
    return (next(iter(outputs)) if len(outputs)==1 else None,
            any(len(values)>1 for values in groups.values()))


class BankIndependence:
    def __init__(self,cells,library,bank_nets,assumptions,keeper_cuts):
        self.cells,self.library=cells,library
        self.bank=set(bank_nets);self.assumptions=dict(assumptions)
        if self.bank & self.assumptions.keys() or any(v not in (0,1) for v in self.assumptions.values()):
            raise ValueError('BANK_QUALIFIER_INVALID_ASSUMPTION')
        self.cuts=set(keeper_cuts);self.cache={};self.active=set();self.drivers={}
        for path,c in cells.items():
            for pin,nets in c['connections'].items():
                if c['directions'][pin]=='output':
                    for n in nets:
                        if n in self.drivers:raise ValueError('BANK_QUALIFIER_MULTIPLE_DRIVERS')
                        self.drivers[n]=(path,pin)

    def value(self,net):
        if net in self.assumptions:return self.assumptions[net],False
        if net in self.bank:return None,True
        if net in self.cache:return self.cache[net]
        if net in self.active:raise ValueError('BANK_QUALIFIER_UNREVIEWED_LOOP')
        if net not in self.drivers:
            if isinstance(net,tuple) and len(net)==2 and net[0]=='constant':
                if net[1] not in ('0','1'):raise ValueError('BANK_QUALIFIER_UNKNOWN_CONSTANT')
                return int(net[1]),False
            return None,False
        path,pin=self.drivers[net];c=self.cells[path]
        if c['type'].split('__')[-1].startswith(('dff','lat','sram')):
            return None,False
        self.active.add(net)
        sig=logic_signature(self.library,c['type'])
        if sig[pin][2] is not None:raise ValueError('BANK_QUALIFIER_TRISTATE')
        inputs=[]
        for p,ns in c['connections'].items():
            if c['directions'][p]=='input':
                if len(ns)!=1:raise ValueError('BANK_QUALIFIER_VECTOR_CELL')
                v,d=(None,False) if (path,p) in self.cuts else self.value(ns[0])
                inputs.append((p,v,d))
        result=enclose(sig[pin][1],tuple(sorted(inputs)))
        self.active.remove(net);self.cache[net]=result
        return result

    def failures(self,targets):
        failures=[]
        for pin in targets:
            path,port=pin.rsplit('/',1)
            nets=self.cells[path]['connections'][port]
            if any(self.value(n)[1] for n in nets):failures.append(pin)
        return failures

    def require_independent(self,targets,partition_nets=()):
        # Preserve decoder reconvergence by splitting only independent storage
        # outputs, never decoded predicates. Both values of every split are
        # visited; a branch closes only when the conservative enclosure proves it.
        nets=list(dict.fromkeys(partition_nets));leaves=[]
        for net in nets:
            if net in self.bank or net in self.assumptions or net not in self.drivers:
                raise ValueError('BANK_QUALIFIER_INVALID_PARTITION')
            path,pin=self.drivers[net]
            if pin not in ('Q','QN') or not self.cells[path]['type'].split('__')[-1].startswith(('dff','lat')):
                raise ValueError('BANK_QUALIFIER_INVALID_PARTITION')
        def visit(checker,remaining,depth,case):
            failures=checker.failures(remaining)
            if not failures:
                leaves.append(case);return
            if depth==len(nets):raise ValueError('BANK_UNQUALIFIED_READER: '+repr(failures))
            for value in (0,1):
                child=BankIndependence(self.cells,self.library,self.bank,
                    dict(checker.assumptions)|{nets[depth]:value},self.cuts)
                visit(child,failures,depth+1,case+[value])
        visit(self,targets,0,[])
        return dict(readers=len(targets),evaluated_nets=len(self.cache),
                    partition_nets=nets,exhaustive_partition_leaves=leaves,
                    proof='Liberty truth-table enclosure; exhaustive cofactoring of independent storage outputs; all other inputs and state free')

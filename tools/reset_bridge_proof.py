# SPDX-License-Identifier: Apache-2.0
"""Finite local proof of clocked bridge equations, separate from physical CDC.

Every payload exemption needs exact capture/self muxes, reset ownership and
request/return equations. Producer hold/reset contracts need a separate audit.
"""
from itertools import product


class Cone:
    def __init__(self, module):
        self.module = module
        self.drivers = {}
        for name, cell in module['cells'].items():
            for port, direction in cell['port_directions'].items():
                if direction == 'output':
                    for index, bit in enumerate(cell['connections'][port]):
                        if isinstance(bit, int):
                            if bit in self.drivers: raise ValueError('RDC_MULTIPLE_DRIVERS')
                            self.drivers[bit] = (name, cell, port, index)

    def bits(self, name):
        try: return self.module['netnames'][name]['bits']
        except KeyError as error: raise ValueError('RDC_BRIDGE_MISSING_NET_' + name) from error

    def flop(self, name):
        vector = self.bits(name)
        drivers = {self.drivers[b][0] for b in vector if b in self.drivers}
        if len(drivers) != 1: raise ValueError('RDC_BRIDGE_REGISTER_' + name)
        driver = drivers.pop(); cell = self.module['cells'][driver]
        if cell['type'] != '$adff' or cell['connections']['Q'] != vector:
            raise ValueError('RDC_BRIDGE_REGISTER_' + name)
        return driver, cell

    @staticmethod
    def bind(env, vector, value):
        for index, bit in enumerate(vector):
            v = (value >> index) & 1
            if isinstance(bit, int):
                if bit in env and env[bit] != v: raise ValueError('RDC_BRIDGE_ALIASED_INPUTS')
                env[bit] = v
            elif bit not in ('0', '1') or int(bit) != v: raise ValueError('RDC_BRIDGE_CONSTANT_INPUT')

    def evaluate(self, vector, env, cache=None):
        cache = {} if cache is None else cache
        def bit_value(bit):
            if bit in ('0', '1'): return int(bit)
            if bit in env: return env[bit]
            if bit in cache: return cache[bit]
            if bit not in self.drivers: raise ValueError('RDC_BRIDGE_UNPROVEN_INPUT_' + str(bit))
            _, cell, port, index = self.drivers[bit]
            kind = cell['type']; pins = cell['connections']
            def get(pin): return self.evaluate(pins[pin], env, cache)
            def signed(pin):
                return int(cell.get('parameters',{}).get(pin+'_SIGNED','0'),2)==1
            def operand(pin, extend_signed):
                value=get(pin); width=len(pins[pin])
                return value-(1<<width) if extend_signed and value & (1<<(width-1)) else value
            both_signed=signed('A') and signed('B')
            if kind == '$mux': value = get('B') if get('S') else get('A')
            elif kind == '$pmux':
                s = get('S'); width = len(pins['Y'])
                if s and s & (s - 1): raise ValueError('RDC_BRIDGE_NONEXCLUSIVE_PMUX')
                value = get('A') if not s else (get('B') >> ((s.bit_length()-1)*width))
            elif kind in ('$eq', '$ne'):
                value = int((operand('A',both_signed) == operand('B',both_signed)) == (kind == '$eq'))
            elif kind in ('$and', '$or', '$xor'):
                a,b=operand('A',both_signed),operand('B',both_signed)
                value={'$and':a & b,'$or':a | b,'$xor':a ^ b}[kind]
            elif kind == '$not': value = ~operand('A',signed('A'))
            elif kind in ('$logic_not', '$reduce_bool', '$reduce_or'):
                value = int(bool(get('A')) != (kind == '$logic_not'))
            elif kind == '$reduce_and': value = int(get('A') == (1 << len(pins['A']))-1)
            elif kind in ('$logic_and', '$logic_or'):
                a,b=bool(get('A')),bool(get('B')); value=int(a and b if kind == '$logic_and' else a or b)
            elif kind in ('$add','$sub','$mul'):
                a,b=operand('A',both_signed),operand('B',both_signed)
                value={'$add':a+b,'$sub':a-b,'$mul':a*b}[kind]
            elif kind == '$shl': value=operand('A',signed('A')) << get('B')
            elif kind in ('$shiftx', '$shr'):
                shift=operand('B',signed('B')) if kind=='$shiftx' else get('B')
                if kind == '$shiftx' and (shift < 0 or shift+len(pins['Y']) > len(pins['A'])):
                    raise ValueError('RDC_BRIDGE_UNDEFINED_SHIFT')
                value=get('A') >> shift
            else: raise ValueError('RDC_BRIDGE_UNPROVEN_OPERATOR_' + kind)
            for i, out in enumerate(pins[port]):
                if isinstance(out, int): cache[out] = (value >> i) & 1
            return (value >> index) & 1
        return sum(bit_value(bit) << i for i,bit in enumerate(vector))

    def payload_leaf(self, bit, env, leaves):
        if bit in leaves or bit in ('0', '1'): return bit
        if bit not in self.drivers: raise ValueError('RDC_BRIDGE_PAYLOAD_DRIVER')
        _, cell, _, index = self.drivers[bit]
        if cell['type'] != '$mux': raise ValueError('RDC_BRIDGE_PAYLOAD_LOGIC')
        pins=cell['connections']
        selected=pins['B'] if self.evaluate(pins['S'],env) else pins['A']
        return self.payload_leaf(selected[index],env,leaves)


def check_flop_reset(cell, clock, reset):
    if (cell['connections']['CLK'] != clock or cell['connections']['ARST'] != reset or
        cell['parameters']['CLK_POLARITY'] != '1' or cell['parameters']['ARST_POLARITY'] != '1' or
        int(cell['parameters']['ARST_VALUE'],2) != 0):
        raise ValueError('RDC_BRIDGE_CONTROL_RESET')


def prove_sram_capture(module, bank, por_reset):
    """Exact held-source -> unreset macro input storage, never a bank-wide waiver.

    Enumerate even illegal multi-valid masks: the functional native one-hot
    assertion is additional protection, not an assumption in this proof.
    """
    cone = Cone(module)
    prefix = 'fabric_' + bank + '_'
    access = 'ca_child_' + bank + '_access'
    state = cone.flop(prefix + 'state')[1]
    # Inline physical exports may eliminate the clock alias. Use the actual
    # state-flop clock and require every receipt/capture flop to share it.
    clock = state['connections']['CLK']
    reset = state['connections']['ARST']
    if not por_reset(reset, clock): raise ValueError('RDC_SRAM_NOT_POR')
    check_flop_reset(state, clock, reset)
    fields = dict(address=32, write=1, data=8, enable=1)
    inputs = {}
    for lane in range(4):
        receipt = access + '.ca_child_byte_request_' + str(lane)
        if cone.bits(receipt + '.clock') != clock:
            raise ValueError('RDC_SRAM_RECEIPT_CLOCK')
        for field, width in fields.items():
            bits = cone.bits(receipt + '.in_bits_' + field)
            if len(bits) != width or bits != cone.bits(receipt + '.out_bits_' + field):
                raise ValueError('RDC_SRAM_HELD_ALIAS')
            if bits != cone.bits(access + '.ca_child_native.byteRequest_' + str(lane) + '_bits_' + field):
                raise ValueError('RDC_SRAM_NATIVE_ALIAS')
            inputs[lane, field] = bits
    registers = {}
    for field, width in {**fields, 'tag': 2}.items():
        name = prefix + ('tag' if field == 'tag' else 'saved_' + field)
        q = cone.bits(name)
        drivers = {cone.drivers[b][0] for b in q}
        if len(drivers) != 1: raise ValueError('RDC_SRAM_CAPTURE_REGISTER')
        reg = drivers.pop(); cell = module['cells'][reg]; pins = cell['connections']
        if (cell['type'] != '$dff' or pins['Q'] != q or len(q) != width or
                pins['CLK'] != clock or cell['parameters']['CLK_POLARITY'] != '1'):
            raise ValueError('RDC_SRAM_CAPTURE_CLOCK')
        registers[field] = reg, pins

    def leaf(bit, env, leaves):
        if bit in leaves or bit in ('0', '1'): return bit
        _, cell, _, index = cone.drivers[bit]
        pins = cell['connections']; kind = cell['type']
        if kind == '$mux':
            branch = pins['B'] if cone.evaluate(pins['S'], env) else pins['A']
        elif kind == '$pmux':
            select = cone.evaluate(pins['S'], env); width = len(pins['Y'])
            if select and select & (select - 1): raise ValueError('RDC_SRAM_CAPTURE_PMUX')
            branch = pins['A'] if not select else pins['B'][(select.bit_length()-1)*width:select.bit_length()*width]
        elif kind == '$shiftx':
            shift = cone.evaluate(pins['B'], env)
            branch = pins['A'][shift:shift+len(pins['Y'])]
        else: raise ValueError('RDC_SRAM_CAPTURE_LOGIC_' + kind)
        return leaf(branch[index], env, leaves)

    for value, mask, rst in product(range(4), range(16), range(2)):
        env = {}; cone.bind(env, state['connections']['Q'], value); cone.bind(env, reset, rst)
        # Chisel PriorityEncoder's no-valid default is the last lane. No
        # payload/tag capture may occur in that case, even though ready is high.
        selected = (mask & -mask).bit_length()-1 if mask else 3
        for lane in range(4):
            cone.bind(env, cone.bits(access + '.ca_child_byte_request_' + str(lane) + '.out_valid'), (mask >> lane) & 1)
        if cone.evaluate(cone.bits(prefix + 'selected'), env) != selected:
            raise ValueError('RDC_SRAM_SELECTED')
        for lane in range(4):
            ready = cone.bits(access + '.ca_child_byte_request_' + str(lane) + '.out_ready')
            if cone.evaluate(ready, env) != (value == 0 and not rst and selected == lane):
                raise ValueError('RDC_SRAM_READY')
        capture = value == 0 and bool(mask) and not rst
        for field in fields:
            _, pins = registers[field]
            leaves = set(pins['Q'] + sum([inputs[i, field] for i in range(4)], []))
            expected = inputs[selected, field] if capture else pins['Q']
            if [leaf(b, env, leaves) for b in pins['D']] != expected:
                raise ValueError('RDC_SRAM_CAPTURE_' + field)
        _, tag = registers['tag']
        for old in range(4):
            tag_env = dict(env); cone.bind(tag_env, tag['Q'], old)
            if cone.evaluate(tag['D'], tag_env) != (selected if capture else old):
                raise ValueError('RDC_SRAM_TAG')
    return dict(prefix=prefix, rows=128, payload=[registers[f][0] for f in fields],
                contract='retained native byte bus, receipt ACK on exact macro-controller capture')


def prove_first_fanout(module, first_q, permitted, fanout):
    queue=[first_q];seen={first_q}
    while queue:
        bit=queue.pop()
        for user,pin in fanout[bit]:
            cell=module['cells'].get(user)
            if not cell or (cell['type'] == '$adff' and (user not in permitted or pin != 'D')):
                raise ValueError('RDC_BRIDGE_FIRST_STAGE_FANOUT')
            if cell['type'] == '$adff': continue
            if cell['type'] not in ('$mux','$and','$not'):
                raise ValueError('RDC_BRIDGE_FIRST_STAGE_LOGIC_'+cell['type'])
            for out in cell['connections']['Y']:
                if out not in seen: seen.add(out);queue.append(out)


def prove_phase_pair(module, prefix, por_reset, fanout):
    cone=Cone(module)
    first=cone.flop(prefix+'.acknowledge_first');second=cone.flop(prefix+'.acknowledge')
    clock=cone.bits(prefix+'.clock');reset=cone.bits(prefix+'.localReset_release_1')
    if not por_reset(reset,clock): raise ValueError('RDC_BRIDGE_NOT_POR')
    for _,cell in (first,second): check_flop_reset(cell,clock,reset)
    for a,b,raw,close,rebase in product(range(2),repeat=5):
        env={}
        for bits,value in ((first[1]['connections']['Q'],a),(second[1]['connections']['Q'],b),
                (cone.bits(prefix+'.out_ack'),raw),(cone.bits(prefix+'.close'),close),
                (cone.bits(prefix+'.rebase'),rebase)):
            cone.bind(env,bits,value)
        if (cone.evaluate(first[1]['connections']['D'],env) != (0 if rebase else a if close else raw) or
            cone.evaluate(second[1]['connections']['D'],env) != (0 if rebase else b if close else a)):
            raise ValueError('RDC_PHASE_PAIR_EQUATIONS')
    prove_first_fanout(module,first[1]['connections']['Q'][0],{first[0],second[0]},fanout)
    return dict(prefix=prefix,rows=32,first=first[0],second=second[0])


def prove_completion_idle(module, click, por_reset, fanout):
    cone=Cone(module)
    first=cone.flop('completionReturnedFirst');second=cone.flop('second')
    clock=cone.bits('ca_child_completion_plan_bridge.clock');reset=cone.bits('reset')
    for _,cell in (first,second): check_flop_reset(cell,clock,reset)
    cutoff=cone.bits('ca_child_request_bridge.close')
    for a,b,request,ack,cancel in product(range(2),repeat=5):
        env={}
        for bits,value in ((first[1]['connections']['Q'],a),(second[1]['connections']['Q'],b),
                (cone.bits('ca_child_completion.response_req'),request),
                (cone.bits('ca_child_completion.response_ack'),ack),(cutoff,cancel)):
            cone.bind(env,bits,value)
        idle=(request==ack) if click else not (request or ack)
        if (cone.evaluate(first[1]['connections']['D'],env) != (idle and not cancel) or
            cone.evaluate(second[1]['connections']['D'],env) != (a and not cancel)):
            raise ValueError('RDC_IDLE_PAIR_EQUATIONS')
    prove_first_fanout(module,first[1]['connections']['Q'][0],{second[0]},fanout)
    return dict(prefix='completionIdle',rows=32,first=first[0],second=second[0])


def prove_receiver(module, prefix, click, quiescing, por_reset, fanout):
    cone=Cone(module)
    names = dict(state='state', ack='ack' if click and not quiescing else 'acknowledge',
        first='request_first' if quiescing else 'request_stages_0',
        second='request' if quiescing else 'request_stages_1')
    regs={k:cone.flop(prefix+'.'+v) for k,v in names.items()}
    clock=cone.bits(prefix+'.clock'); reset=cone.bits(prefix+'.localReset_release_1')
    if not por_reset(reset,clock): raise ValueError('RDC_BRIDGE_NOT_POR')
    for _, cell in regs.values(): check_flop_reset(cell,clock,reset)
    payload=[]
    for name, net in module['netnames'].items():
        local=name.removeprefix(prefix+'.')
        if not name.startswith(prefix+'.') or not (local == 'data' or local.startswith('data_')) or '.' in local:
            continue
        # Constant/unused fields have no receiving FF and receive no exemption.
        if all(b in ('0','1') for b in net['bits']): continue
        if all(b not in cone.drivers and not fanout[b] for b in net['bits']): continue
        input_bits=cone.bits(prefix+'.in_bits'+local[4:])
        output_bits=cone.bits(prefix+'.out_bits'+local[4:])
        reg,cell=cone.flop(name); pins=cell['connections']
        check_flop_reset(cell,clock,reset)
        if pins['Q'] != output_bits or len(input_bits) != len(output_bits):
            raise ValueError('RDC_BRIDGE_PAYLOAD_BINDING')
        payload.append((reg,cell,input_bits))
    controls=dict(req=cone.bits(prefix+'.in_req'),ready=cone.bits(prefix+'.out_ready'),reset=reset)
    if quiescing: controls.update(close=cone.bits(prefix+'.close'),rebase=cone.bits(prefix+'.rebase'))
    rows=0
    for state, ack, first, second, req, ready, rst, close, rebase in product(
            range(4),*[range(2)]*6, range(2) if quiescing else [0],range(2) if quiescing else [0]):
        env={}
        for key,value in dict(state=state,ack=ack,first=first,second=second).items():
            cone.bind(env,regs[key][1]['connections']['Q'],value)
        for key,value in dict(req=req,ready=ready,reset=rst,close=close,rebase=rebase).items():
            if key in controls: cone.bind(env,controls[key],value)
        valid=state==2 and not close and not rst
        next_state=state;next_ack=ack
        if rebase: next_state=0;next_ack=0
        elif not close:
            if state==0 and (second != ack if click else second): next_state=1
            elif state==1: next_state=2
            elif state==2 and ready and valid:
                next_state=0 if click else 3;next_ack=second if click else 1
            elif not click and state==3 and not second: next_state=0;next_ack=0
        expected=dict(state=next_state,ack=next_ack,
            first=0 if rebase else first if close else req,
            second=0 if rebase else second if close else first)
        for key,value in expected.items():
            if cone.evaluate(regs[key][1]['connections']['D'],env) != value:
                raise ValueError('RDC_BRIDGE_TRANSITION_'+prefix+'_'+key)
        if cone.evaluate(cone.bits(prefix+'.out_valid'),env) != valid or cone.evaluate(cone.bits(prefix+'.in_ack'),env) != ack:
            raise ValueError('RDC_BRIDGE_OUTPUT_'+prefix)
        capture=state==1 and not close and not rebase
        for reg,cell,inputs in payload:
            pins=cell['connections'];leaves=set(inputs+pins['Q'])
            for i,bit in enumerate(pins['D']):
                if cone.payload_leaf(bit,env,leaves) != (inputs[i] if capture else pins['Q'][i]):
                    raise ValueError('RDC_BRIDGE_CAPTURE_'+prefix)
        rows+=1
    prove_first_fanout(module,regs['first'][1]['connections']['Q'][0],{regs[k][0] for k in ('first','second')},fanout)
    return dict(prefix=prefix,rows=rows,payload=[r for r,_,_ in payload],
        payload_fields=[next(n.removeprefix(prefix+'.data') for n,v in module['netnames'].items()
            if n.startswith(prefix+'.data') and v['bits']==cell['connections']['Q']) for _,cell,_ in payload],
        first=regs['first'][0],second=regs['second'][0],
        contract='held native bus, two-stage request, complete settle/capture/return FSM')

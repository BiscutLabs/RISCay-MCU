"""Exact C1e masked-bus proof. No blanket register/sink exemptions.

The caller must separately prove the native source lifetime, receiver FSM and
complete reset coordinator before using its exact mask B-port handoffs.
"""
from collections import defaultdict, deque
from reset_bridge_proof import Cone

FIELDS = {'mask': (0, 4), 'data': (4, 32), 'address': (36, 32), 'operation': (68, 2)}
NATIVE_STATE = {'ChiselAsyncAsymmetricC_v1', 'ChiselAsyncClosingLatch_v1',
    'ChiselAsyncEventRegister_v1', 'ChiselAsyncPhaseRegister_v1',
    'ChiselAsyncCElement_v1', 'ChiselAsyncLatch_v1'}


def require(value, reason):
    if not value:
        raise ValueError('RDC_QUIESCING_RECEIPT_' + reason)


def prove_masked_request(database, top, control_proof):
    require(top in ('FourPhaseSoc','ClickSoc','BdResetBoundarySocFixture','ClickResetBoundarySocFixture'), 'EXACT_SOC_TOP')
    module = database['modules'][top]
    cone = Cone(module)
    prefix = 'ca_child_request_bridge'
    require(control_proof['prefix'] == prefix and not control_proof['payload'], 'CONTROL_PROOF')
    valid = cone.bits(prefix + '.out_valid')
    source_name = 'ca_child_core.ca_child_address.ca_primitive_payload'
    source = module['cells'][source_name]
    model = lambda c: database['modules'].get(c['type'], {}).get('attributes', {}).get('hdlname', c['type']).split()[0]
    expected = 'ChiselAsyncEventRegister_v1' if top in ('ClickSoc','ClickResetBoundarySocFixture') else 'ChiselAsyncClosingLatch_v1'
    require(model(source) == expected and len(source['connections']['q']) == 70, 'NATIVE_OWNER')
    require(cone.bits(prefix+'.clock') == cone.bits('serviceClock'), 'SERVICE_CLOCK')
    require(cone.bits(prefix+'.out_ready') == cone.bits('fabric_io_request_ready'), 'READY_ALIAS')
    mask_cells = set(); handoffs = []
    output_bits = []
    for field, (offset, width) in FIELDS.items():
        source_bits = source['connections']['q'][offset:offset+width]
        native = cone.bits('ca_child_transactions.serviceRequest_bits_'+field)
        incoming = cone.bits(prefix+'.in_bits_'+field)
        outgoing = cone.bits(prefix+'.out_bits_'+field)
        require(incoming == native == source_bits and len(outgoing) == width, 'SOURCE_PACKING_'+field)
        for i, bit in enumerate(outgoing):
            require(bit in cone.drivers, 'MISSING_MASK_'+field)
            name, cell, port, index = cone.drivers[bit]
            pins = cell['connections']
            # Current Chisel Mux lowers to one $mux per field. Fail closed on
            # changed lowering rather than treating an arbitrary cone as a mask.
            require(cell['type'] == '$mux' and port == 'Y' and pins['S'] == valid and
                pins['A'] == ['0']*width and pins['B'] == incoming and
                pins['Y'] == outgoing and index == i, 'EXACT_MASK_'+field)
            mask_cells.add(name)
        output_bits += outgoing
        handoffs.append(dict(field=field, cell=name, input_pin='B', output_pin='Y',
                             input_bits=incoming, output_bits=outgoing, select_bits=valid))
    # Prove no retained data register or shadow payload survives in this owner.
    allowed = {'state', 'acknowledge', 'request_first', 'request', 'stopped',
               'closed_REG', 'rebased_REG', 'localReset_release_0', 'localReset_release_1'}
    for name, cell in module['cells'].items():
        if cell['type'] not in ('$adff', '$dff'): continue
        q = cell['connections']['Q']
        aliases = [n[len(prefix)+1:] for n,v in module['netnames'].items()
            if n.startswith(prefix+'.') and v['bits'] == q]
        if aliases and not set(aliases) <= {'close','rebase','clock','reset'}:
            require(any(n in allowed for n in aliases), 'UNEXPECTED_STORAGE_' + aliases[0])
            require(not any(n == 'data' or n.startswith('data_') for n in aliases), 'PAYLOAD_COPY')

    # Full combinational fanout walk from the actual native payload. Remove only
    # exact proved mask cells, then require all paths to periodic registers to
    # end at the existing request synchronizer's first D. Native retained state
    # terminates a path because it starts a distinct native hold contract.
    users = defaultdict(list)
    for name, cell in module['cells'].items():
        for pin, direction in cell['port_directions'].items():
            if direction == 'input':
                for bit in cell['connections'][pin]: users[bit].append((name,pin))
    queue = deque(source['connections']['q']); seen = set(queue); sinks = []
    while queue:
        bit = queue.popleft()
        for name, pin in users[bit]:
            cell = module['cells'][name]
            if name in mask_cells or model(cell) in NATIVE_STATE: continue
            if cell['type'] in ('$adff','$dff'):
                require(name == control_proof['first'] and pin == 'D', 'UNMASKED_PERIODIC_SINK_'+name+'_'+pin)
                sinks.append([name,pin]); continue
            require(cell['type'].startswith('$') or model(cell) in
                {'ChiselAsyncControlGate_v1','ChiselAsyncAnd_v1','ChiselAsyncXor_v1',
                 'ChiselAsyncPassiveDataAllowance_v1'}, 'UNCLASSIFIED_FANOUT')
            for output, direction in cell['port_directions'].items():
                if direction == 'output':
                    for target in cell['connections'][output]:
                        if isinstance(target,int) and target not in seen:
                            seen.add(target); queue.append(target)

    # The actual service receipt may ACK only on an edge also present at the
    # consumer. Existing exact coordinator proof establishes workClock =
    # serviceClock && gate_enabled; prove ready collapses to zero when disabled.
    cache = {}
    def known(bit):
        if bit in ('0','1'): return int(bit)
        if bit in cone.bits('gate_enabled'): return 0
        if bit in cache: return cache[bit]
        if bit not in cone.drivers: return None
        _,cell,port,index = cone.drivers[bit]; pins=cell['connections']; kind=cell['type']
        if kind in ('$adff','$dff') or model(cell) in NATIVE_STATE: return None
        def vector(pin): return [known(b) for b in pins[pin]]
        result = None
        if kind in ('$and','$logic_and'):
            a,b=vector('A'),vector('B')
            if kind == '$logic_and':
                a=[int(any(a))] if all(x is not None for x in a) else [None]
                b=[int(any(b))] if all(x is not None for x in b) else [None]
            av=a[min(index,len(a)-1)];bv=b[min(index,len(b)-1)]
            result=0 if av==0 or bv==0 else 1 if av==bv==1 else None
        elif kind == '$not':
            value=vector('A')[index]; result=None if value is None else 1-value
        elif kind == '$logic_not':
            value=vector('A'); result=int(not any(value)) if all(x is not None for x in value) else None
        elif kind == '$mux':
            select=known(pins['S'][0]);a,b=known(pins['A'][index]),known(pins['B'][index])
            result=(b if select else a) if select is not None else a if a==b else None
        cache[bit]=result
        return result
    require([known(b) for b in cone.bits(prefix+'.out_ready')] == [0], 'READY_WITHOUT_WORK_CLOCK')
    return dict(prefix=prefix, status='pass', payload=[], payload_fields=['_'+f for f in FIELDS],
        source=source_name, source_width=70, mask_cells=sorted(mask_cells),
        held_data_inputs=handoffs,
        masked_bits=len(output_bits), traversed_unmasked_bits=len(seen), allowed_request_sinks=sorted(sinks),
        contract='retained native request; invalid zero mask; exact clock/close/rebase proofs required separately')

# SPDX-License-Identifier: Apache-2.0
"""Reviewed native Stage/Fabric lifetime binding for the CPU held-data handoff.

These topology fingerprints bind the complete existing native controllers, data
transforms, fixed primitive parameters and return histories. They are independent
of Yosys numbering, export paths and wire aliases. They are not timing proofs.
The digital protocol argument is in docs/application-reset-boundary.md; changing
an owner requires a new review, not automatic acceptance of a new fingerprint.
"""
import hashlib
import json

from reset_bridge_proof import Cone


FIELDS = {'mask': (0, 4), 'data': (4, 32), 'address': (36, 32), 'operation': (68, 2)}
NATIVE = frozenset(('ChiselAsyncAsymmetricC_v1', 'ChiselAsyncClosingLatch_v1',
    'ChiselAsyncEventRegister_v1', 'ChiselAsyncPhaseRegister_v1',
    'ChiselAsyncCElement_v1', 'ChiselAsyncLatch_v1', 'ChiselAsyncControlGate_v1',
    'ChiselAsyncAnd_v1', 'ChiselAsyncXor_v1', 'ChiselAsyncPassiveDataAllowance_v1'))
# Reviewed C1f -> C1e1 topology is identical in portable and physical exports.
# These are maintained constants, never learned from the graph being audited.
EXPECTED = {
    'bd': {'address': '020facf6d63804e11412bf76aab0cc15559018dd4542c9338a32189234aaae43',
           'fabric': '4c32d7fc17f3af226f8cbcb15e7c641fb19f91358d6e5047ec4c85fafe0cf0f3'},
    'click': {'address': '583df44b8dea3d25c009c2d10d131da9c1b7e26e6d2d67497c0bc48f6d511d8d',
              'fabric': '5927432ca7205e12ec272cff525a1036c9ce11f7dca11d9f9e7ef4e5040d740e'},
}
# A8b review compares every canonical native pin record and all boundary
# expressions against the above graph. Only the named data allowance changes
# to passive a/q; controller, storage, ACK and reset records are identical.
PASSIVE_EXPECTED = {
    'bd': {'address': '902b7aa6e503c5fa0fd45a4ed5b2c3bf36e3c199de7d5f15e8b8a347d09c13fd',
           'fabric': '1ec507f4dc3c9400038fa49cd0c461f6428dddc77aac3011f46bd2a44fc1cbcd'},
    'click': {'address': 'cd4378a12a92fa8e50d05249010bd1575da80e9ea9b5d961e589f90ac23e680a',
              'fabric': '4ec6f3aeba5b9f75808f7d68abeb96ed059dabc41ecc30c948a5adf42a01b3d2'},
}
FIXTURE_FABRIC = {
    'bd': 'aaa0c271ed06a37f09de4c70e90d5365d6210aec94dc3b791fc5d826a030137b',
    'click': 'd48d3ce84c6f5bbe1e62e7b38a3d6d1c9f91de7d72ece46b39de1a43556d41ef',
}


def need(value, reason):
    if not value:
        raise ValueError('RDC_QUIESCING_HOLD_' + reason)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def owner_signature(database, top, prefix, inputs, outputs):
    """Canonical actual pin graph; native Q breaks cycles, never hides its D.

Every native cell beneath the owner is included with all input cones. Native Q
is an identity leaf only during recursion; its own complete pin record is still
hashed. Unbound external inputs and periodic cells fail closed. Ordinary logic
is recursively canonicalized by type, parameters, pins and lane position.
"""
    module = database['modules'][top]; cone = Cone(module)
    def model(cell):
        return database['modules'].get(cell['type'], {}).get('attributes', {}).get('hdlname', cell['type']).split()[0]
    boundary = {}
    schema = {}
    for name in inputs:
        vector = cone.bits(prefix + '.' + name); schema[name] = len(vector)
        for index, bit in enumerate(vector):
            if not isinstance(bit, int): continue
            token = (name, index)
            need(bit not in boundary, 'ALIASED_OWNER_INPUT_' + prefix)
            boundary[bit] = token
    owned = {name: cell for name, cell in module['cells'].items()
             if name.startswith(prefix + '.') and model(cell) in NATIVE}
    need(bool(owned), 'EMPTY_OWNER_' + prefix)
    cache = {}; active = set(); ordinary = set()
    def expression(bit):
        if bit in ('0', '1'): return canonical(['literal', bit])
        if bit in boundary: return canonical(['input', *boundary[bit]])
        if bit in cache: return cache[bit]
        need(bit not in active and bit in cone.drivers, 'UNBOUND_OR_CYCLIC_OWNER_' + prefix)
        name, cell, pin, index = cone.drivers[bit]
        if name in owned:
            result = canonical(['native-output', name[len(prefix)+1:], pin, index])
        else:
            need(cell['type'].startswith('$') and cell['type'] not in ('$adff', '$dff'),
                 'FOREIGN_OR_CLOCKED_OWNER_' + prefix)
            active.add(bit); ordinary.add(name)
            result = canonical(['logic', cell['type'], cell.get('parameters', {}), pin, index,
                {p: [expression(b) for b in bits] for p, bits in cell['connections'].items()
                 if cell['port_directions'][p] == 'input'}])
            active.remove(bit)
        cache[bit] = result
        return result
    records = {}
    for name, cell in sorted(owned.items()):
        records[name[len(prefix)+1:]] = dict(model=model(cell), parameters=cell.get('parameters', {}),
            directions=cell['port_directions'], pins={p: ([expression(b) for b in bits]
                if cell['port_directions'][p] == 'input' else len(bits))
                for p, bits in cell['connections'].items()})
    result = dict(inputs=schema, native=records,
                  outputs={n: [expression(b) for b in cone.bits(prefix+'.'+n)] for n in outputs})
    return dict(sha256=canonical(result), native_cells=len(owned), combinational_cells=len(ordinary),
                input_widths=schema, output_widths={n: len(v) for n, v in result['outputs'].items()})


def source_signatures(database, top):
    cone = Cone(database['modules'][top]); address='ca_child_core.ca_child_address'; fabric='ca_child_transactions'
    inputs = sorted(n[len(address)+1:] for n in cone.module['netnames']
                    if n.startswith(address+'.in_bits_') and '.' not in n[len(address)+1:])
    address_inputs = ['reset', 'in_req', 'out_ack'] + inputs
    address_outputs = ['in_ack', 'out_req'] + ['out_bits_'+f for f in FIELDS]
    fabric_inputs = ['reset','request_req','response_ack','serviceRequest_ack','serviceResponse_req']
    fabric_inputs += ['request_bits_'+f for f in FIELDS] + ['serviceResponse_bits_data','serviceResponse_bits_error']
    fabric_outputs = ['request_ack','response_req','response_bits_data','response_bits_error',
                      'serviceRequest_req','serviceResponse_ack'] + ['serviceRequest_bits_'+f for f in FIELDS]
    return {name: owner_signature(database, top, prefix, incoming, outgoing)
            for name,prefix,incoming,outgoing in [('address',address,address_inputs,address_outputs),
                                                ('fabric',fabric,fabric_inputs,fabric_outputs)]}


def prove_request_hold(database, top, capacities):
    need(top in ('FourPhaseSoc','ClickSoc','BdResetBoundarySocFixture','ClickResetBoundarySocFixture'), 'TOP')
    click = top in ('ClickSoc','ClickResetBoundarySocFixture'); protocol='click' if click else 'bd'
    fixture=top in ('BdResetBoundarySocFixture','ClickResetBoundarySocFixture')
    expected_capacities={'program':64,'ram':32} if fixture else {'program':2048,'ram':1024}
    need(capacities==expected_capacities and all(type(v) is int for v in capacities.values()), 'REVIEWED_CAPACITIES')
    module=database['modules'][top]; cone=Cone(module)
    address='ca_child_core.ca_child_address'; fabric='ca_child_transactions'; receipt='ca_child_request_bridge'
    # Actual links, not matching owner names. The address ACK must be Fabric's
    # retained completion ACK; the receipt ACK cannot directly release it.
    aliases=[(address+'.out_req','ca_child_core.request_req'),(address+'.out_ack','ca_child_core.request_ack'),
             ('ca_child_core.request_req',fabric+'.request_req'),('ca_child_core.request_ack',fabric+'.request_ack'),
             (fabric+'.serviceRequest_req',receipt+'.in_req'),(fabric+'.serviceRequest_ack',receipt+'.in_ack')]
    for a,b in aliases: need(cone.bits(a)==cone.bits(b), 'PHASE_ALIAS_'+a)
    need(cone.bits(address+'.out_ack') != cone.bits(receipt+'.in_ack'), 'EARLY_RECEIPT_ACK')
    source=module['cells'][address+'.ca_primitive_payload']['connections']['q']
    need(len(source)==70, 'SOURCE_WIDTH')
    for field,(offset,width) in FIELDS.items():
        want=source[offset:offset+width]
        for owner,pin in ((address,'out'),('ca_child_core','request'),(fabric,'request'),(fabric,'serviceRequest'),(receipt,'in')):
            need(cone.bits(owner+'.'+pin+'_bits_'+field)==want, 'PAYLOAD_ALIAS_'+owner+'_'+field)
    # The global uncut native-reset-owner proof checks these expressions against
    # POR/coordinator state. Also bind the actual owner boundary pins here.
    for owner,reset_name in ((address,'nativeCoreReset'),('ca_child_core','nativeCoreReset'),(fabric,'nativeApplicationReset')):
        need(cone.bits(owner+'.reset')==cone.bits(reset_name), 'RESET_ALIAS_'+owner)
    signatures=source_signatures(database,top)
    for owner,signature in signatures.items():
        expected=({FIXTURE_FABRIC[protocol]} if fixture and owner=='fabric' else
                  {EXPECTED[protocol][owner], PASSIVE_EXPECTED[protocol][owner]})
        need(signature['sha256'] in expected, 'OWNER_TOPOLOGY_'+owner)
    return dict(prefix=address, consumer_prefix=receipt, status='pass', protocol=protocol, source=address+'.ca_primitive_payload',
        source_width=70, signatures=signatures, capacities=capacities, phase_aliases=aliases,
        contract='reviewed complete native Stage and Fabric hold/ACK/return topology; coordinated reset required')

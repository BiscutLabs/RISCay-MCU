# SPDX-License-Identifier: Apache-2.0
"""Conservative constants with every state output and runtime input free.

This is deliberately a small proof engine, not a simulator. Unsupported cells
and X/Z bits stay unknown. Only pure bitwise logic, muxes, wiring and passive
allowances can prove a capture D constant; reset/valid are never assumptions.
"""
from passive_allowance_policy import PASSIVE


def parameter(cell, name, default=0):
    value = cell.get('parameters', {}).get(name)
    return default if value is None else int(value, 2)


def extend(bits, width, signed=False):
    return (bits + [(bits[-1] if bits and signed else 0)] * width)[:width]


class ConstantProof:
    def __init__(self, cells, model):
        self.cells, self.model = cells, model
        self.drivers, self.cache, self.active = {}, {}, set()
        for name, cell in cells.items():
            for pin, bits in cell['connections'].items():
                if cell['port_directions'][pin] != 'output':
                    continue
                for lane, bit in enumerate(bits):
                    if isinstance(bit, int):
                        if bit in self.drivers:
                            raise ValueError('ALLOWANCE_CONSTANT_MULTIPLE_DRIVERS')
                        self.drivers[bit] = (name, pin, lane)

    def bit(self, bit):
        if not isinstance(bit, int):
            return int(bit) if bit in ('0', '1') else None
        if bit in self.cache:
            return self.cache[bit]
        if bit in self.active or bit not in self.drivers:
            return None
        self.active.add(bit)
        name, pin, lane = self.drivers[bit]
        values = self.evaluate(self.cells[name], pin)
        value = values[lane]
        self.active.remove(bit)
        self.cache[bit] = value
        return value

    def evaluate(self, cell, pin):
        c = cell['connections']; width = len(c[pin]); kind = self.model(cell)
        # Native state/control and periodic storage are free boundaries. In
        # particular no reset value or controller state is used in this proof.
        if kind != PASSIVE and cell['type'] not in {
                '$mux', '$and', '$or', '$xor', '$xnor', '$not', '$pos',
                '$concat', '$slice', '$reduce_and', '$reduce_or', '$reduce_bool',
                '$reduce_xor', '$reduce_xnor', '$logic_not'}:
            return [None] * width
        values = lambda port: [self.bit(b) for b in c[port]]
        if kind == PASSIVE:
            return values('a')
        kind = cell['type']
        a = values('A')
        if kind == '$mux':
            b, select = values('B'), values('S')[0]
            return [x if select == 0 else y if select == 1 else x if x == y else None
                    for x, y in zip(a, b)]
        if kind == '$concat':
            return a + values('B')
        if kind == '$slice':
            offset = parameter(cell, 'OFFSET')
            return a[offset:offset + width]
        if kind in ('$reduce_and', '$reduce_or', '$reduce_bool', '$logic_not',
                    '$reduce_xor', '$reduce_xnor'):
            if kind == '$reduce_and':
                result = 0 if 0 in a else 1 if all(x == 1 for x in a) else None
            elif kind in ('$reduce_or', '$reduce_bool', '$logic_not'):
                result = 1 if 1 in a else 0 if all(x == 0 for x in a) else None
                if kind == '$logic_not' and result is not None: result ^= 1
            else:
                result = None if None in a else sum(a) % 2
                if kind == '$reduce_xnor' and result is not None: result ^= 1
            return [result] + [0] * (width - 1)
        signed = bool(parameter(cell, 'A_SIGNED'))
        if 'B' in c:
            signed = signed and bool(parameter(cell, 'B_SIGNED'))
        a = extend(a, width, signed)
        if kind == '$pos': return a
        if kind == '$not': return [None if x is None else x ^ 1 for x in a]
        b = extend(values('B'), width, signed)
        result = []
        for x, y in zip(a, b):
            if kind == '$and': z = 0 if x == 0 or y == 0 else 1 if x == y == 1 else None
            elif kind == '$or': z = 1 if x == 1 or y == 1 else 0 if x == y == 0 else None
            else:
                z = None if x is None or y is None else x ^ y
                if kind == '$xnor' and z is not None: z ^= 1
            result.append(z)
        return result

# SPDX-License-Identifier: Apache-2.0
"""Add source-level Telemetry borrow coverage; retain every generic obligation."""
import re

FIELDS = {'clear': 6, 'offset': 7, 'data': 32, 'appIndex': 6}


def telemetry_borrow_background(source, manifest, scopes, checks):
    top = manifest.get('top')
    if top not in ('FourPhaseSoc', 'ClickSoc'):
        return source, checks
    prefix = 'Click' if top == 'ClickSoc' else 'FourPhase'

    def require(ok, diagnostic):
        if not ok:
            raise ValueError('TELEMETRY_BORROW_' + diagnostic)

    def child(name, module):
        found = [c['contract'] for c in manifest['design'].get('children', []) if c['id'] == name]
        require(len(found) == 1 and re.fullmatch(module + r'(?:_\d+)?', found[0]['module']), 'OWNER')
        return found[0]

    def layout(node, channel):
        found = [c['layout'] for c in node.get('channels', []) if c['id'] == channel]
        require(len(found) == 1, 'LAYOUT')
        fields = {f['field']: f for f in found[0]}
        require(len(fields) == len(found[0]), 'LAYOUT')
        return fields

    native = child('telemetry', prefix + 'Telemetry')
    sender = child('telemetry_command_bridge', 'DecoupledTo' + prefix)
    command = layout(native, 'command')
    header = layout(sender, 'out')
    incoming = layout(sender, 'in')
    indices = {int(m[1]) for f in command if (m := re.fullmatch(r'bits\.captures\[(\d+)\]\.\w+', f))}
    require(indices == set(range(len(indices))), 'LAYOUT')
    captures = [(f'captures[{i}].{name}', width) for i in range(len(indices))
                for name, width in (('tailAge', 32), ('value', 32), ('calibrated', 1),
                                    ('valid', 1), ('hadValid', 1), ('count', 32), ('seen', 1))]
    def expected(node, channel, fields):
        result, lsb = {}, 0
        for name, width in captures + fields:
            field = 'bits.' + name
            result[field] = dict(field=field, lsb=lsb, width=width, signed=False,
                                 source='~|' + node['module'] + '>' + channel + '.' + field)
            lsb += width
        return result
    suffix = [('elapsedUpper', 32), ('events', 6), ('kind', 2), ('recovery', 1)]
    require(header == expected(sender, 'out', suffix) and incoming == expected(sender, 'in', suffix)
            and command == expected(native, 'command', [('appIndex', 6), ('data', 32), ('offset', 7),
                    ('elapsedUpper', 32), ('clear', 6), ('events', 6), ('kind', 2), ('recovery', 1)]), 'LAYOUT')

    def register(path, width):
        owner, name = path.rsplit('.', 1)
        require(scopes.get(owner, {}).get('registers', {}).get(name) == width, 'SOURCE')
        return path

    def pin(path, width, direction):
        owner, name = path.rsplit('.', 1)
        actual = scopes.get(owner, {}).get('ports', {}).get(name, {})
        require(actual.get('width') == width and actual.get('direction') == direction, 'PIN')
        return path

    kind = register(sender['rtl_path'] + '.data_kind', 2)
    kind_out = pin(sender['rtl_path'] + '.out_bits_kind', 2, 'output')
    kind_in = pin(native['rtl_path'] + '.command_bits_kind', 2, 'input')
    bindings = [(kind_out, kind), (kind_in, kind)]
    banks = {}
    for field, width in FIELDS.items():
        banks[field] = register(top + '.fabric_telemetryCommit_' + field, width)
        actual = pin(native['rtl_path'] + '.command_bits_' + field, width, 'input')
        bindings.append((actual, f"({kind} == 2'h1 ? {banks[field]} : {width}'h0)"))

    anchor = f"initial begin\nforce {top}.reset = 1'b1; #1;\n"
    require(source.count(anchor) == 1 and source.count('task check; begin\n') == 1, 'PROBE_SHAPE')
    start = source.index(anchor) + len(anchor)
    end = source.find('\n#1;\n', start)
    require(end >= start, 'PROBE_SHAPE')
    reset_sources = source[start:end + len('\n#1;\n')]
    coverage = list(re.finditer(r'^if \(ones_\d+ !==.*INACTIVE_ENDPOINT:.*$', source, re.M))
    completion = f'CONTRACT_PROBES_PASS:{checks}'
    require(coverage and source.count(completion) == 1, 'PROBE_SHAPE')
    extra, steps = [reset_sources], 0

    def force(path, width, value):
        require(f"force {path} = {width}'h0;" in reset_sources, 'DRIVER')
        extra.append(f"force {path} = {width}'h{value:x};\n")

    # Select the actual retained header, then walk the existing bank. Never
    # force a native command pin, packed endpoint, mask or derived valid signal.
    for selected in range(4):
        force(kind, 2, selected)
        for field, width in FIELDS.items():
            mask = (1 << width) - 1
            for value in [0, mask] + [v for bit in range(width) for v in (1 << bit, mask ^ (1 << bit))]:
                force(banks[field], width, value)
                extra.append('#1; check;\n')
                steps += 1
            force(banks[field], width, 0)
    extra.append(reset_sources)
    position = coverage[0].start()
    result = source[:position] + ''.join(extra) + source[position:]
    assertions = ''.join(f'if ({actual} !== {expected}) $fatal(1,"TELEMETRY_BORROW_BINDING:{actual}");\n'
                         for actual, expected in bindings)
    result = result.replace('task check; begin\n', 'task check; begin\n' + assertions, 1)
    count = checks + steps * len(coverage)
    return result.replace(completion, f'CONTRACT_PROBES_PASS:{count}'), count

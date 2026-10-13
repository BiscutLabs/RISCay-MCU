# SPDX-License-Identifier: Apache-2.0
"""Closed schemas and actual native storage for the four service reply receipts.

These checks prove source identity, packing and zero additional payload storage.
They do not qualify the physical held-bus setup/hold path. Every mapping check
compares the real producer storage with both sides of the clocked receiver;
dynamic bits retain their original activity obligations.
"""
import hashlib
import re
from pathlib import Path


OWNERS = ('control', 'housekeeping', 'telemetry', 'supervisor')

# The complete control and initialization body, after independently checked
# schema-only port/payload aliases are removed. No Boolean rewriting is used.
CONTROL_FINGERPRINTS = {
    'bd': 'a7c14c967bf9a81267ee332ffa0439e4f548d554623a1613d69c37c5d679f6fa',
    'click': '24eeeef0a409b31f2409612d063a3afde504514c38ba5edadb150081a36ebc3c',
}


def require(value, detail):
    if not value:
        raise ValueError('SERVICE_REPLY_' + detail)


def _fields(items):
    result = []
    offset = 0
    for name, width in items:
        result.append((name, offset, width))
        offset += width
    return result


SAMPLE = [('fault', 1), ('never', 1), ('sequence', 32), ('age', 32),
          ('calibrated', 1), ('valid', 1), ('value', 32)]
CONTROL = _fields([
    ('memory.error', 1), ('memory.data', 32), ('hostWake', 1), ('period', 32),
    ('periodUpdate', 1), ('programWrite', 1), ('state.appIndex', 6),
    ('state.sampleValue', 32), ('state.sampleIndex', 4), ('state.selector', 24),
    ('state.loaderWord', 32), ('state.loaderPending', 1), ('state.crc', 32),
    ('state.expectedCrc', 32), ('state.imageId', 32), ('state.received', 32),
    ('state.entry', 32), ('state.imageLength', 32), ('state.lastError', 8),
    ('state.started', 1), ('state.locked', 1), ('state.programmed', 1),
    ('state.mode', 3), ('kind', 3)])
HOUSEKEEPING = _fields([
    ('cpuCompletion', 1), ('resetApplication', 1), ('kick', 1), ('startAdc', 1),
    ('leaseExpired', 1), ('due', 1), *[(f'elapsed[{i}]', 32) for i in range(3)],
    ('single', 1), ('tick', 1), ('timeValid', 1), ('state.requested', 1),
    ('state.countdown', 32), ('state.periodPending', 1), ('state.nextPeriod', 32),
    ('state.period', 32), ('state.wakeMask', 32), ('state.lease', 32),
    ('state.armed', 1), ('state.deadline', 32), ('state.consumed', 32),
    ('state.boardNow', 32), ('state.now', 32), ('recovery', 1)])
SUPERVISOR = _fields([
    *[('sample.' + field, width) for field, width in SAMPLE],
    *[(f'observed[{i}]', 1) for i in range(4)],
    *[(f'counts[{i}]', 32) for i in range(4)],
    ('waitShutdown', 1), ('waitOff', 1), ('waitRun', 1), ('qualified', 1),
    ('shutdownAt', 32), ('offAt', 32), ('timeouts', 2), ('fault', 3),
    ('mode', 2), ('sensingFault', 1)])


def layout(owner, declared):
    require(owner in OWNERS, 'OWNER')
    if owner == 'telemetry':
        names = [f.get('field', '') for f in declared]
        def size(pattern):
            indices = {int(m[1]) for field in names if (m := re.fullmatch(pattern, field))}
            require(indices == set(range(len(indices))), 'TELEMETRY_INDICES')
            return len(indices)
        channels = size(r'bits\.state\.samples\[(\d+)\]\.fault')
        words = size(r'bits\.state\.application\[(\d+)\]')
        expected = _fields([
            *[(f'state.samples[{i}].{field}', width) for i in range(channels) for field, width in SAMPLE],
            *[(f'state.application[{i}]', 32) for i in range(words)],
            ('state.pending', 6), ('state.enable', 32), ('state.output', 32),
            ('kind', 2), ('recovery', 1)])
    else:
        expected = dict(control=CONTROL, housekeeping=HOUSEKEEPING, supervisor=SUPERVISOR)[owner]
    require([(f.get('field'), f.get('lsb'), f.get('width'), f.get('signed')) for f in declared] ==
            [('bits.' + name, offset, width, False) for name, offset, width in expected], 'SCHEMA_' + owner)
    require(all(type(f.get('lsb')) is int and type(f.get('width')) is int and f.get('signed') is False
                for f in declared), 'SCHEMA_TYPES_' + owner)
    return expected


def leaf(field):
    return field.replace('.', '_').replace('[', '_').replace(']', '')


def _child(node, identity):
    found = [c['contract'] for c in node.get('children', []) if c.get('id') == identity]
    require(len(found) == 1, 'CHILD_' + identity)
    return found[0]


def native_reply_source(manifest, scopes, header, owner):
    """Return only the registered transform output and independently packed fields."""
    top = manifest['top']
    require(top in ('FourPhaseSoc', 'ClickSoc') and owner in OWNERS, 'OWNER')
    click = top == 'ClickSoc'
    prefix = 'Click' if click else 'FourPhase'
    node = _child(manifest['design'], owner)
    path = top + '.ca_child_' + owner
    require(node.get('rtl_path') == path and node.get('reset_domain') == 'root' and
            re.fullmatch(prefix + owner.title() + r'(?:_\d+)?', node.get('module', '')), 'PRODUCER_' + owner)
    replies = [c for c in node.get('channels', []) if c.get('id') == 'reply']
    require(len(replies) == 1 and replies[0].get('role') == 'output' and
            replies[0].get('protocol') == ('two-phase-bundled-v1' if click else 'four-phase-bundled-v1'),
            'CHANNEL_' + owner)
    fields = layout(owner, replies[0].get('layout', []))
    require(all(f.get('source') == f"~|{node['module']}>reply.{f['field']}" for f in replies[0]['layout']),
            'FIELD_SOURCE_' + owner)
    width = sum(f[2] for f in fields)
    update = _child(node, 'update')
    require(update.get('rtl_path') == path + '.ca_child_update' and update.get('reset_domain') == 'root' and
            re.fullmatch(('ClickStage' if click else 'FourPhaseStage') + r'(?:_\d+)?', update.get('module', '')),
            'UPDATE_' + owner)
    storage = [p for p in update.get('primitives', []) if p.get('id') == 'payload']
    target = update['rtl_path'] + '.ca_primitive_payload'
    model = 'ChiselAsyncEventRegister_v1' if click else 'ChiselAsyncClosingLatch_v1'
    parameters = dict(DELAY_FS='1000000', WIDTH=str(width))
    if click:
        parameters['RESET_VALUE'] = '0'
    port = dict(name='q', width=width, direction='output')
    require(len(storage) == 1 and storage[0].get('rtl_path') == target and
            storage[0].get('model') == model and storage[0].get('parameters') == parameters and
            storage[0].get('reset') == 'reset' and storage[0].get('reset_domain') == 'root' and
            [p for p in storage[0].get('ports', []) if p.get('name') == 'q'] == [port] and
            scopes.get(target, {}).get('model') == model and scopes[target].get('parameters') == parameters and
            scopes[target].get('ports', {}).get('q') == port, 'STORAGE_' + owner)
    if header is not None:
        require(f"force {target}.q = {width}'h0;" in header, 'STORAGE_FORCE_' + owner)
    return dict(path=target + '.q', width=width, fields={name: (offset, size) for name, offset, size in fields})


def pack_reply(source, values):
    require(set(values) <= source['fields'].keys(), 'PACK_FIELD')
    packed = 0
    for name, value in values.items():
        offset, width = source['fields'][name]
        require(type(value) is int and 0 <= value < (1 << width), 'PACK_RANGE_' + name)
        packed |= value << offset
    return packed


def receipt_bindings(manifest, scopes):
    """Validate exact storage-free receivers and produce independent alias checks."""
    if manifest.get('top') not in ('FourPhaseSoc', 'ClickSoc'):
        return []
    top = manifest['top']; click = top == 'ClickSoc'
    children = {c['id']: c['contract'] for c in manifest['design'].get('children', [])}
    result = []
    for owner in OWNERS:
        if owner not in children:
            require(owner + '_reply_bridge' not in children, 'ORPHAN_RECEIPT_' + owner)
            continue
        node = _child(manifest['design'], owner + '_reply_bridge')
        model = ('Click' if click else 'FourPhase') + 'ServiceReplyReceipt'
        path = top + '.ca_child_' + owner + '_reply_bridge'
        require(re.fullmatch(model + r'(?:_\d+)?', node.get('module', '')) and
                node.get('rtl_path') == path and node.get('reset_domain') == 'root' and
                node.get('capacity') == 1 and all(node.get(k) == [] for k in ('children', 'primitives', 'timing')),
                'RECEIPT_OWNER_' + owner)
        source = native_reply_source(manifest, scopes, None, owner)
        channels = node.get('channels', [])
        require([c.get('id') for c in channels] == ['in', 'out'], 'RECEIPT_CHANNELS_' + owner)
        for channel in channels:
            expected = 'decoupled-v1' if channel['id'] == 'out' else ('two-phase-bundled-v1' if click else 'four-phase-bundled-v1')
            require(channel.get('protocol') == expected and channel.get('role') == ('input' if channel['id'] == 'in' else 'output'),
                    'RECEIPT_PROTOCOL_' + owner)
            fields = layout(owner, channel.get('layout', []))
            require({name: (offset, width) for name, offset, width in fields} == source['fields'], 'RECEIPT_LAYOUT_' + owner)
        ack = 'ack' if click else 'acknowledge'
        expected_regs = dict(localReset_release_0=1, localReset_release_1=1,
                             request_stages_0=1, request_stages_1=1, state=2, **{ack: 1})
        scope = scopes.get(path, {})
        require(scope.get('registers') == expected_regs and not scope.get('memories'), 'REGISTER_INVENTORY_' + owner)
        ports = {name: dict(name=name, width=1, direction=direction) for name, direction in (
            ('reset','input'), ('clock','input'), ('in_req','input'), ('in_ack','output'),
            ('out_ready','input'), ('out_valid','output'))}
        for field, (_, width) in source['fields'].items():
            for side, direction in (('in','input'), ('out','output')):
                name = side + '_bits_' + leaf(field)
                ports[name] = dict(name=name, width=width, direction=direction)
        require(scope.get('model') == node['module'] and scope.get('ports') == ports, 'PORT_INVENTORY_' + owner)
        e = {v['id']: v for v in node.get('endpoints', [])}
        expected_endpoints = dict(local_reset=(1, 'localReset'), request_sync=(1, 'request_stages[1]'),
            state=(2, 'state'), acknowledge=(1, ack), reset=(1, 'reset'),
            in_request=(1, 'in.req'), in_data=(source['width'], 'in.bits'), in_acknowledge=(1, 'in.ack'),
            out_valid=(1, 'out.valid'), out_data=(source['width'], 'out.bits'), out_ready=(1, 'out.ready'), out_clock=(1, 'clock'))
        require(len(e) == len(node.get('endpoints', [])) and e.keys() == expected_endpoints.keys() and
                all((e[name].get('width'), e[name].get('source')) == (width, f"~|{node['module']}>{signal}")
                    for name, (width, signal) in expected_endpoints.items()), 'ENDPOINTS_' + owner)
        for name, signal in [('local_reset', 'localReset_release_1'), ('request_sync', 'request_stages_1'),
                             ('state', 'state'), ('acknowledge', ack), ('reset', 'reset')]:
            result.append((e[name]['rtl_path'], path + '.' + signal))
        result += [(path + '.in_ack', path + '.' + ack),
                   (path + '.out_valid', f"(({path}.state == 2'h2) && !{path}.localReset_release_1)")]
        for field, (offset, width) in source['fields'].items():
            selected = source['path'] + (f'[{offset}]' if width == 1 else f'[{offset + width - 1}:{offset}]')
            for port in ('in', 'out'):
                result.append((path + '.' + port + '_bits_' + leaf(field), selected))
            result.append((top + '.ca_child_' + owner + '.reply_bits_' + leaf(field), selected))
    return result


def receipt_control_fingerprint(text, fields):
    clean = re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)
    match = re.search(r'\bmodule\s+(?:FourPhase|Click)ServiceReplyReceipt(?:_\d+)?\s*\([^;]*\);(.*?)\bendmodule\s*$',
                      clean, re.S)
    require(match is not None and len(re.findall(r'\bmodule\b', clean)) == 1, 'RTL_MODULE')
    body = match[1]
    for field, _, _ in fields:
        suffix = '_' + leaf(field) if field else ''
        assignment = 'assign out_bits' + suffix + ' = in_bits' + suffix + ';'
        expression = r'\s*'.join(map(re.escape, assignment.split()))
        body, count = re.subn(expression, '', body)
        require(count == 1, 'RTL_PAYLOAD_' + field)
    width = sum(w for _, _, w in fields)
    if fields == [('', 0, width)]:
        # Scalar channels alias the payload directly; FIRRTL emits no packed
        # aggregate metadata wires. The remaining control body is identical.
        return hashlib.sha256(re.sub(r'\s+', '', body).encode()).hexdigest()
    expected = '{' + ','.join('in_bits_' + leaf(field) for field, _, _ in reversed(fields)) + '}'
    for name in ('packed_3_probe', 'packed_6_probe'):
        expression = r'wire\s*\[' + str(width - 1) + r':0\]\s*' + name + r'\s*=\s*([^;]+);'
        found = re.findall(expression, body)
        require(len(found) == 1 and re.sub(r'\s+', '', found[0]) == expected, 'RTL_PACKING_' + name)
        body = re.sub(expression, '', body)
    return hashlib.sha256(re.sub(r'\s+', '', body).encode()).hexdigest()


def validate_service_reply_rtl(manifest, directory):
    if manifest.get('top') not in ('FourPhaseSoc', 'ClickSoc'):
        return
    click = manifest['top'] == 'ClickSoc'
    children = {c['id']: c['contract'] for c in manifest['design'].get('children', [])}
    for owner in OWNERS:
        if owner not in children:
            continue
        node = _child(manifest['design'], owner + '_reply_bridge')
        channels = [c for c in node.get('channels', []) if c.get('id') == 'in']
        require(len(channels) == 1, 'RTL_CHANNEL_' + owner)
        fields = layout(owner, channels[0].get('layout', []))
        source = (Path(directory) / (node['module'] + '.sv')).read_text()
        require(receipt_control_fingerprint(source, fields) == CONTROL_FINGERPRINTS['click' if click else 'bd'],
                'RTL_CONTROL_' + owner)


def service_reply_probe(source, manifest, scopes):
    bindings = receipt_bindings(manifest, scopes)
    if not bindings:
        return source
    matches = list(re.finditer(r'\btask(?:\s+automatic)?\s+check\s*;\s*begin', source))
    require(len(matches) == 1, 'CHECK_SHAPE')
    statements = ''.join(f'\nif ({left} !== {right}) $fatal(1,"SERVICE_REPLY_BINDING:{left}");'
                         for left, right in bindings)
    point = matches[0].end()
    return source[:point] + statements + source[point:]

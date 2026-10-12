# SPDX-License-Identifier: Apache-2.0
"""Closed standalone native program-return RTL/reset contract (digital models only).

The raw application port deliberately has a different reset lifetime from the
retained word. This checker resolves that boundary from *validated RTL*, rather
than pretending that it is an ordinary same-reset library channel. Every cell,
pin, endpoint, port, writer and passive timing marker is checked. This is not a
whole-SoC integration check, a physical timing proof, or a generic Verilog parser.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

CAPTURES = {
    'bd': {'payload': 'pending', 'permission': 'pending'},
    'click': {'received_phase': 'request_guard', 'payload': 'request_guard',
              'permission': 'request_guard', 'application_target': 'request_guard',
              'issued_phase': 'request_delay', 'application_phase': 'request_delay',
              'completed_phase': 'return_guard'},
}
PORTS = {n: ('input', 1) for n in ('reset', 'word_req', 'publication_ack',
         'captureAcknowledge', 'response_ack', 'applicationReset', 'eligible')}
PORTS.update({n: ('output', 1) for n in ('word_ack', 'publication_req', 'publication_bits',
              'captureRequest', 'response_req', 'response_bits_error', 'presentationSettled', 'idle')})
PORTS.update(word_bits=('input', 32), response_bits_data=('output', 32))
APPLICATION_RESET = 'reset|applicationReset'
FIXED_GUARDS = {'request_delay', 'output_delay', 'request_guard', 'return_guard', 'acknowledge_guard', 'output_guard'}
MODEL_HASHES = {
    'ChiselAsyncAsymmetricC_v1': '5a0e057bc58d9dea359e58fdc2135bdecad1af6ea99d549c20784bcacc2dab49',
    'ChiselAsyncControlGate_v1': '739e5993bba245e8a9c58ab2ac90746944684cf0e865f13089ad68eb08241f9e',
    'ChiselAsyncEventRegister_v1': '6973d29216ce233cba02d039d3258833f6caaed7fa368eb6e2608bb0d002926d',
    'ChiselAsyncTimingMarker_v1': 'a744279bf6446b1a46cada6e37b9efaab246aef6c7e2cbd45ce1b50cf1862575',
    'ChiselAsyncXor_v1': 'ccc145705a8d60627803bd30dad6bab58ece655368fa43eaebcb03e00aa137c4',
}
EXPORTED_MODEL_HASHES = dict(zip(MODEL_HASHES, (
    '25a48179101f3d7ce2d49c2ce9efa67f59853e686b7c946ce3c30d92e4615f18',
    '45b8e16fdb1888ae4636eb8038a030390c09f65a8d52e52d537495640b9ae4c2',
    'da2f055a2fabb4d5fb42d631d2d6ccec400465d1d37dd54ee1a65f8f546c104e',
    '18a250359ad29ec8997c94bd7b3f56415b42497fad0fd09ea904cbd4b6c69b13',
    '0f07e7fd8d20f1e0456e304c42c83b0bd2a85709385dfb1c8fc07af57e66fe28')))


def require(condition, diagnostic):
    if not condition:
        raise ValueError('PROGRAM_RETURN_' + diagnostic)


def clean(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)


def unique(pairs, diagnostic):
    result = dict(pairs)
    require(len(result) == len(pairs), diagnostic)
    return result


def cat(*parts):
    return '{' + ','.join(parts) + '}'


def policy(variant):
    """Independent expected native netlist in semantic cell names."""
    require(variant in CAPTURES, 'VARIANT')
    click = variant == 'click'
    cells, endpoints, widths, timings = {}, {}, {}, []
    q = lambda name: 'Q_' + name

    def endpoint(name, expression, width=1):
        endpoints[name] = expression
        widths[name] = width

    def cell(name, model, pins, application=False, **parameters):
        cells[name] = dict(model='ChiselAsync' + model + '_v1',
                           parameters={k: str(v) for k, v in parameters.items()},
                           reset='presentation_reset' if application else 'reset',
                           pins=dict(reset=APPLICATION_RESET if application else 'reset', **pins))

    def gate(name, a, b=None, op=0, width=1, delay=1000000, initial=0, application=False):
        cell(name, 'ControlGate', dict(a=a, b=b if b is not None else f"{width}'h0"),
             application, WIDTH=width, OP=op, DELAY_FS=delay, RESET_VALUE=initial)
        return q(name)

    def and_gate(name, a, b, application=False):
        na = gate(name + '_na', a, op=1, initial=1, application=application)
        nb = gate(name + '_nb', b, op=1, initial=1, application=application)
        o = gate(name + '_or', na, nb, op=2, initial=1, application=application)
        return gate(name, o, op=1, application=application)

    def state(name, common, rising, count, invert=0, application=False):
        cell(name, 'AsymmetricC', dict(common=common, rising=rising, falling="1'h0"), application,
             COMMON=1, RISING=count, FALLING=0, DELAY_FS=1000000, RESET_VALUE=0,
             COMMON_INVERT=invert, RISING_INVERT=0, FALLING_INVERT=0)
        return q(name)

    def register(name, trigger, data, width=1, application=False):
        cell(name, 'EventRegister', dict(trigger=trigger, d=data), application,
             WIDTH=width, DELAY_FS=1000000, RESET_VALUE=0)
        return q(name)

    def xor(name, a, b):
        cell(name, 'Xor', dict(a=a, b=b), DELAY_FS=1000000)
        return q(name)

    for name, port in (('word_request', 'word_req'), ('word_data', 'word_bits'),
                       ('word_acknowledge', 'word_ack'), ('publication_request', 'publication_req'),
                       ('publication_data', 'publication_bits'), ('publication_acknowledge', 'publication_ack'),
                       ('reset', 'reset'), ('application_reset', 'applicationReset'), ('eligible', 'eligible'),
                       ('capture_request', 'captureRequest'), ('capture_acknowledge', 'captureAcknowledge'),
                       ('response_request', 'response_req'), ('response_acknowledge', 'response_ack'),
                       ('presentation_settled', 'presentationSettled'), ('idle', 'idle')):
        endpoint(name, port, 32 if name == 'word_data' else 1)
    endpoint('presentation_reset', APPLICATION_RESET)
    endpoint('response_data', cat(q('payload'), "1'h0"), 33)
    endpoint('retained_word', q('payload'), 32)
    endpoint('word_permission', q('permission'))
    endpoint('permission_data', q('permission_data_delay'))
    endpoint('terminal_proof', q('terminal'))
    endpoint('cleanup', q('acknowledge_guard'))
    gate('permission_data_delay', 'eligible', delay=10000000)
    payload = q('payload')
    permission = q('permission')
    if click:
        incoming = xor('incoming', 'word_req', q('received_phase'))
        arm = gate('request_guard', and_gate('arm_selected', incoming, 'CAPACITY'), delay=11000000)
        gate('data_delay', cat('word_req', 'word_bits'), width=33, delay=10000000)
        gate('target_data_delay', '~' + q('application_phase'), delay=10000000)
        register('received_phase', arm, q('data_delay') + '[32]')
        register('payload', arm, q('data_delay') + '[31:0]', 32)
        register('permission', arm, q('permission_data_delay'), application=True)
        register('application_target', arm, q('target_data_delay'), application=True)
        issue_pending = xor('issue_pending', q('received_phase'), q('issued_phase'))
        issue = gate('request_delay', issue_pending, delay=200000000)
        gate('issue_data_delay', q('received_phase'), delay=10000000)
        application_source = permission + '?' + q('application_target') + ':' + q('application_phase')
        gate('application_data_delay', application_source, delay=10000000)
        register('issued_phase', issue, q('issue_data_delay'))
        register('application_phase', issue, q('application_data_delay'), application=True)
        request = q('application_phase')
        gate('acknowledge_guard', q('completed_phase'), delay=200000000)
        pending = xor('owned', q('received_phase'), q('acknowledge_guard'))
        state('issue_seen', pending, issue, 1)
        accepted = permission + '&' + request + '==' + q('application_target') + '&response_ack==' + q('application_target')
        cancelled = '~' + permission + '&' + request + '==response_ack'
        state('terminal', pending, cat(q('issue_seen') + '&~' + issue_pending, '~' + issue, accepted + '|' + cancelled), 3)
        published = gate('output_guard', q('received_phase'), delay=200000000)
        publication_returned = published + '==' + q('received_phase') + '&publication_ack==' + q('received_phase')
        receipt_returned = published + '==' + q('received_phase') + '&captureAcknowledge==' + q('received_phase')
        finish = gate('return_guard', and_gate('finish_selected', q('terminal'),
                      and_gate('branches_returned', publication_returned, receipt_returned)), delay=11000000)
        gate('finish_data_delay', q('received_phase'), delay=10000000)
        register('completed_phase', finish, q('finish_data_delay'))
        ack = gate('output_delay', q('received_phase'), delay=32000000)
        capacity = ('~' + pending + '&' + q('received_phase') + '==' + q('issued_phase') + '&' +
                    q('issued_phase') + '==' + q('completed_phase') + '&' + q('completed_phase') + '==' +
                    q('acknowledge_guard') + '&~' + q('terminal') + '&~' + q('issue_seen') + '&~' + arm +
                    '&~' + issue + '&~' + finish + '&(' + publication_returned + ')&(' + receipt_returned +
                    ')&' + ack + '==' + q('received_phase'))
        idle = '(' + capacity + ')&word_req==' + ack
        capture_request = published
        for name, expression, width in (
            ('input_sources', cat('word_req', 'word_bits'), 33), ('input_data', q('data_delay'), 33),
            ('captured', cat(q('received_phase'), payload), 33), ('target_source', '~' + request, 1),
            ('target_data', q('target_data_delay'), 1), ('target', q('application_target'), 1),
            ('received', q('received_phase'), 1), ('issue_event', issue, 1), ('issue_data', q('issue_data_delay'), 1),
            ('issued_identity', q('issued_phase'), 1), ('application_source', application_source, 1),
            ('application_data', q('application_data_delay'), 1), ('finish_event', finish, 1),
            ('finish_data', q('finish_data_delay'), 1), ('completed', q('completed_phase'), 1),
            ('publication_returned', publication_returned, 1), ('receipt_returned', receipt_returned, 1)):
            endpoint(name, expression, width)
        paths = [('word', 'input_sources', 'input_data', 'arm_event', 'captured', 'data_delay'),
                 ('permission', 'eligible', 'permission_data', 'arm_event', 'word_permission', 'permission_data_delay'),
                 ('target', 'target_source', 'target_data', 'arm_event', 'target', 'target_data_delay'),
                 ('issue', 'received', 'issue_data', 'issue_event', 'issued_identity', 'issue_data_delay'),
                 ('application', 'application_source', 'application_data', 'issue_event', 'response_request', 'application_data_delay'),
                 ('finish', 'received', 'finish_data', 'finish_event', 'completed', 'finish_data_delay')]
    else:
        pending = state('pending', q('acknowledge_guard'), cat(q('request_guard'), 'CAPACITY'), 2, invert=1)
        arm = pending
        gate('request_guard', 'word_req', delay=11000000)
        gate('data_delay', 'word_bits', width=32, delay=10000000)
        register('payload', pending, q('data_delay'), 32)
        register('permission', pending, q('permission_data_delay'), application=True)
        armed = gate('output_guard', pending, delay=200000000)
        history = gate('history_common', pending, armed, op=2)
        issued = state('issued', pending, armed, 1)
        state('input_seen', history, q('output_delay'), 1)
        state('input_withdrawn', history, cat(q('input_seen'), '~word_req'), 2)
        state('input_returned', pending, cat(q('input_withdrawn'), '~' + q('output_delay')), 2)
        offer = and_gate('input_offer', pending, '~' + q('input_withdrawn'))
        ack = gate('output_delay', offer, delay=32000000)
        application_offer = and_gate('application_offer', issued, permission, application=True)
        request = and_gate('application_request', application_offer, '~' + q('application_seen'), application=True)
        state('application_seen', history, cat(request, 'response_ack'), 2, application=True)
        normal = permission + '&' + q('application_seen') + '&~' + request + '&~response_ack'
        cancelled = '~' + permission + '&~' + request + '&~response_ack'
        state('terminal', pending, cat(issued, normal + '|' + cancelled), 2)
        for name, ack_input in (('publication', 'publication_ack'), ('receipt', 'captureAcknowledge')):
            branch = and_gate(name + '_offer', issued, '~' + q(name + '_seen'))
            state(name + '_seen', history, cat(branch, ack_input), 2)
            state(name + '_returned', pending, cat(q(name + '_seen'), '~' + branch, '~' + ack_input), 3)
        state('released', pending, cat(q('terminal'), q('input_returned'), q('publication_returned'), q('receipt_returned')), 4)
        gate('acknowledge_guard', q('released'), delay=200000000)
        published, capture_request = q('publication_offer'), q('receipt_offer')
        quiet = [pending, q('released'), q('acknowledge_guard'), armed, history, issued, q('terminal'),
                 q('input_seen'), q('input_withdrawn'), q('input_returned'), ack, offer, q('publication_seen'),
                 q('publication_returned'), published, 'publication_ack', q('receipt_seen'), q('receipt_returned'),
                 capture_request, 'captureAcknowledge', q('application_seen'), request, 'response_ack', application_offer]
        capacity = '&'.join('~' + n for n in quiet)
        idle = '(' + capacity + ')&~word_req'
        endpoint('input_data', q('data_delay'), 32)
        endpoint('history_hold', history)
        endpoint('issued_identity', issued)
        paths = [('word', 'word_data', 'input_data', 'arm_event', 'retained_word', 'data_delay'),
                 ('permission', 'eligible', 'permission_data', 'arm_event', 'word_permission', 'permission_data_delay')]
    outputs = dict(word_ack=ack, publication_req=published, publication_bits=payload + '[0]',
                   captureRequest=capture_request, response_req=request, response_bits_data=payload,
                   response_bits_error="1'h0", presentationSettled='~' + pending + '|' + q('terminal'), idle=idle)
    endpoint('capacity', capacity)
    endpoint('arm_event', arm)
    for c in cells.values():
        c['pins'] = {k: v.replace('CAPACITY', '(' + capacity + ')') for k, v in c['pins'].items()}
    for name, source, data, event, captured, delay in paths:
        for kind in ('path', 'aperture'):
            marker = name + '_' + kind + '_marker'
            if kind == 'path':
                values = cat(endpoints[data], endpoints[source])
                width = widths[data] + widths[source]
                timing = dict(id=name + '_path', kind='bundled-data-path-v1', marker=marker,
                              source=source, sink=data, logic='native program return ' + name + ' capture',
                              logic_model_fs='0', budget={k: '10000000' for k in ('min_fs', 'max_fs', 'model_fs')},
                              delay_owner=[], delay_cell=delay,
                              accounting='included-in-delay-cell; replace-model-with-mapped-path; not-additive')
            else:
                values = cat(endpoints[captured], endpoints[event], endpoints[data], '{2{' + endpoints[source] + '}}')
                width = widths[captured] + widths[event] + widths[data] + 2 * widths[source]
                timing = dict(id=name + '_aperture', kind='bundled-setup-hold-v1', marker=marker,
                              launch=source, transaction=source, data_valid=data, capture=event, captured=captured,
                              setup_fs='100000', hold_fs='100000', mode='digital-model', provenance='explicit fixture contract',
                              pulse_policy='one outstanding launch; identity travels with data; capture on rising edge')
            parameters = {k: 0 for k in ('ACKNOWLEDGE_MAX_FS ACKNOWLEDGE_MIN_FS ACKNOWLEDGE_MODEL_FS '
                'A_MAX_FS A_MIN_FS A_MODEL_FS B_MAX_FS B_MIN_FS B_MODEL_FS DATA_MAX_FS DATA_MIN_FS DATA_MODEL_FS '
                'HOLD_FS KIND LATCH_MAX_FS LATCH_MIN_FS LATCH_MODEL_FS LONG_HOLD_MAX_FS LONG_HOLD_MIN_FS '
                'LONG_HOLD_MODEL_FS MATCHED_FS OUTPUT_FS SETUP_FS WIDTH').split()}
            parameters.update(WIDTH=width, KIND=3 if kind == 'path' else 1)
            if kind == 'path':
                parameters.update(DATA_MIN_FS=10000000, DATA_MAX_FS=10000000, DATA_MODEL_FS=10000000)
            else:
                parameters.update(SETUP_FS=100000, HOLD_FS=100000)
            cell(marker, 'TimingMarker', dict(values=values), **parameters)
            timings.append(timing)
    return dict(cells=cells, endpoints=endpoints, widths=widths, outputs=outputs, timings=timings)


def local_probe_name(endpoint):
    """Module-local probe identifier, distinct from the forwarded top ABI name."""
    return 'ca_p_' + str(len(endpoint)) + '_' + endpoint


def global_probe_name(node, endpoint):
    """DesignContract.child emits ca_child_<id> and forwards encoded id paths."""
    hierarchy = node['rtl_path'].split('.')[1:]
    require(all(re.fullmatch(r'ca_child_[A-Za-z_]\w*', part) for part in hierarchy), 'CHILD_PATH')
    logical = [part.removeprefix('ca_child_') for part in hierarchy] + [endpoint]
    return 'ca_p_' + '_'.join(str(len(part)) + '_' + part for part in logical)


def validate_program_return(node, resolved=False):
    require(re.fullmatch(r'(?:FourPhase|Click)ProgramReturn(?:_[0-9]+)?', node.get('module', '')), 'OWNER')
    variant = 'click' if node['module'].startswith('Click') else 'bd'
    expected = policy(variant)
    require(re.fullmatch(r'\w+(?:\.\w+)*', node.get('rtl_path', '')) and
            isinstance(node.get('reset_domain'), str) and bool(node['reset_domain']) and
            node.get('capacity') == 1 and node.get('children') == [], 'INVENTORY')
    endpoints = unique([(e['id'], e) for e in node['endpoints']], 'ENDPOINT_DUPLICATE')
    require({n: e['width'] for n, e in endpoints.items()} == expected['widths'], 'ENDPOINTS')
    for n, e in endpoints.items():
        path = e['rtl_path']
        physical = path.startswith(node['rtl_path'] + '.') and re.fullmatch(r'\w+', path[len(node['rtl_path']) + 1:])
        require((bool(physical) if resolved else path == node['rtl_path'] + '.' + local_probe_name(n)) and
                e['probe'] == global_probe_name(node, n), 'ENDPOINT_PATH:' + n)
    channels = unique([(c['id'], c) for c in node['channels']], 'CHANNEL_DUPLICATE')
    require(set(channels) == {'word', 'publication'}, 'CHANNELS')
    for name, role, width in (('word', 'input', 32), ('publication', 'output', 1)):
        c = channels[name]
        require(c['protocol'] == ('two-phase-bundled-v1' if variant == 'click' else 'four-phase-bundled-v1') and
                c['role'] == role and c['reset_domain'] == node['reset_domain'] and
                all(c[k] == name + '_' + k for k in ('request', 'data', 'acknowledge')) and
                c['layout'] == [dict(field='bits', lsb=0, width=width, signed=False,
                                     source='~|' + node['module'] + '>' + name + '.bits')], 'CHANNEL_SCHEMA:' + name)
    require(node['timing'] == expected['timings'], 'TIMING')
    cells = unique([(c['id'], c) for c in node['primitives']], 'CELL_DUPLICATE')
    require(set(cells) == set(expected['cells']), 'CELLS')
    paths = []
    for name, c in cells.items():
        spec = expected['cells'][name]
        require(c['model'] == spec['model'] and c['parameters'] == spec['parameters'], 'CELL_POLICY:' + name)
        require(c['reset'] == spec['reset'] and c['reset_domain'] == node['reset_domain'], 'RESET:' + name)
        require(c['rtl_path'].startswith(node['rtl_path'] + '.') and c['rtl_path'].count('.') == node['rtl_path'].count('.') + 1,
                'CELL_PATH:' + name)
        require(c['resource'] == 'chiselasync/sv/' + c['model'] + '.sv' and c['version'] == 1 and
                c['view'] == ('constraint-marker' if c['model'].endswith('TimingMarker_v1') else 'behavioral'), 'CELL_MODEL:' + name)
        paths.append(c['rtl_path'])
    require(len(set(paths)) == len(paths), 'CELL_PATH_DUPLICATE')
    return variant


def program_return_bindings(node, resolved=False):
    """Closed equations for the strict hierarchical probe; no activity masks.

    The parent integration checker must separately validate every raw boundary
    peer and POR/application reset source. The standalone structural checker
    additionally rejects extra RTL writers and checks model hashes.
    """
    spec = policy(validate_program_return(node, resolved=resolved))
    cells = {p['id']: p['rtl_path'] for p in node['primitives']}
    endpoints = {e['id']: e['rtl_path'] for e in node['endpoints']}

    def resolved(text):
        def name(match):
            value = match[0]
            if value.startswith('Q_'):
                return cells[value[2:]] + '.q'
            if value in PORTS:
                return node['rtl_path'] + '.' + value
            return value
        return re.sub(r'\b[A-Za-z_]\w*\b', name, text)

    pairs = [(cells[n] + '.' + pin, '(' + resolved(value) + ')')
             for n, cell in spec['cells'].items() for pin, value in cell['pins'].items()]
    pairs += [(node['rtl_path'] + '.' + n, '(' + resolved(value) + ')') for n, value in spec['outputs'].items()]
    pairs += [(endpoints[n], '(' + resolved(value) + ')') for n, value in spec['endpoints'].items()]
    return pairs


# Whole data-path logic labels consumed by the strict export adapter. The
# validator still checks their variant-specific source/sink/delay-cell tuples.
PATHS = tuple('native program return ' + name + ' capture'
              for name in ('word', 'permission', 'target', 'issue', 'application', 'finish'))
PROGRAM_RETURN_PATHS = PATHS


TOKEN = re.compile(r"\d+'[hbd][0-9a-fA-F]+|\d+|[A-Za-z_]\w*|==|[~&|?:{},\[\]()]" )


def expression(text, resolve=lambda n: ('name', n)):
    """Small expression grammar; preserving precedence is essential to closure."""
    compact = re.sub(r'\s+', '', text)
    tokens = TOKEN.findall(compact)
    require(''.join(tokens) == compact, 'EXPRESSION_SYNTAX:' + compact)
    at = 0

    def take(value=None):
        nonlocal at
        require(at < len(tokens), 'EXPRESSION_END')
        result = tokens[at]
        require(value is None or result == value, 'EXPRESSION_TOKEN:' + str(value))
        at += 1
        return result

    def parse(minimum=0):
        token = take()
        if token == '~':
            left = ('~', parse(5))
        elif token == '(':
            left = parse(); take(')')
        elif token == '{':
            if at + 1 < len(tokens) and tokens[at].isdigit() and tokens[at + 1] == '{':
                count = int(take()); take('{'); item = parse(); take('}'); take('}')
                left = ('repeat', count, item)
            else:
                parts = [parse()]
                while at < len(tokens) and tokens[at] == ',':
                    take(','); parts.append(parse())
                take('}'); left = ('cat', *parts)
        elif "'" in token:
            width, base, value = re.fullmatch(r"(\d+)'([hbd])([0-9a-fA-F]+)", token).groups()
            left = ('literal', int(width), int(value, {'h': 16, 'b': 2, 'd': 10}[base]))
        else:
            require(not token.isdigit(), 'UNSIZED_EXPRESSION')
            left = resolve(token)
        while at < len(tokens):
            op = tokens[at]
            if op == '[':
                take('['); high = int(take()); low = high
                if tokens[at] == ':':
                    take(':'); low = int(take())
                take(']'); left = ('slice', left, high, low)
                continue
            precedence = {'?': 1, '|': 2, '&': 3, '==': 4}.get(op, -1)
            if precedence < minimum:
                break
            take()
            if op == '?':
                yes = parse(); take(':'); left = ('mux', left, yes, parse(precedence))
            else:
                right = parse(precedence + 1)
                # Associative operations may acquire parentheses while expanding
                # a named wire. Flatten only the identical associative operator.
                parts = list(left[1:]) if left[0] == op and op in ('&', '|') else [left]
                parts.extend(right[1:] if right[0] == op and op in ('&', '|') else [right])
                left = (op, *parts)
        return left

    result = parse()
    require(at == len(tokens), 'EXPRESSION_TRAILING')
    return result


def parse_rtl(node, rtl):
    """Consume the entire restricted standalone module, refusing other writers."""
    rtl = clean(rtl)
    head = re.match(r'\s*module\s+(\w+)\s*\((.*?)\);', rtl, re.S)
    require(head is not None and head[1] == node['module'], 'RTL_MODULE')
    ports = []
    for item in head[2].split(','):
        m = re.fullmatch(r'\s*(input|output)\s*(?:\[(\d+):0\])?\s*(\w+)\s*', item)
        require(m is not None, 'RTL_PORT_SYNTAX')
        ports.append((m[3], (m[1], int(m[2]) + 1 if m[2] else 1)))
    require(unique(ports, 'RTL_PORT_DUPLICATE') == PORTS, 'RTL_PORTS')
    body = rtl[head.end():]
    instances, wires, assignments = {}, {}, {}

    def driver(name, value):
        require(name not in assignments, 'RTL_MULTIPLE_WRITERS:' + name)
        assignments[name] = value

    while body.strip() != 'endmodule':
        body = body.lstrip()
        wire = re.match(r'wire\s+(?:\[(\d+):0\]\s*)?(\w+)\s*(?:=\s*([^;]+))?;', body)
        assign = re.match(r'assign\s+(\w+)\s*=\s*([^;]+);', body)
        instance = re.match(r'(\w+)\s*#\((.*?)\)\s+(\w+)\s*\((.*?)\);', body, re.S)
        if wire:
            require(wire[2] not in wires and wire[2] not in PORTS, 'RTL_WIRE_DUPLICATE')
            wires[wire[2]] = int(wire[1]) + 1 if wire[1] else 1
            if wire[3] is not None:
                driver(wire[2], wire[3])
            body = body[wire.end():]
        elif assign:
            driver(assign[1], assign[2]); body = body[assign.end():]
        elif instance:
            def named(block):
                pairs, pos = [], 0
                while pos < len(block):
                    m = re.match(r'\s*\.(\w+)\s*\(', block[pos:])
                    require(m is not None, 'RTL_PIN_SYNTAX')
                    start = pos + m.end(); end = start; depth = 1
                    while end < len(block) and depth:
                        depth += (block[end] == '(') - (block[end] == ')'); end += 1
                    require(depth == 0, 'RTL_PIN_END')
                    pairs.append((m[1], block[start:end - 1].strip()))
                    pos = end
                    rest = block[pos:].lstrip()
                    if rest:
                        require(rest.startswith(','), 'RTL_PIN_SEPARATOR')
                        pos = len(block) - len(rest) + 1
                    else:
                        pos = len(block)
                return unique(pairs, 'RTL_PIN_DUPLICATE')
            require(instance[3] not in instances, 'RTL_CELL_DUPLICATE')
            instances[instance[3]] = dict(model=instance[1], parameters=named(instance[2]), pins=named(instance[4]))
            body = body[instance.end():]
        else:
            raise ValueError('PROGRAM_RETURN_RTL_UNEXPECTED:' + body[:100])
    return instances, wires, assignments


def validate_program_return_rtl(node, rtl, references, resolved=False):
    variant = validate_program_return(node, resolved=resolved)
    expected = policy(variant)
    instances, wires, assignments = parse_rtl(node, rtl)
    cells = {p['id']: p for p in node['primitives']}
    require(set(instances) == {p['rtl_path'].rsplit('.', 1)[1] for p in cells.values()}, 'RTL_CELLS')
    leaves = {n: ('name', n) for n, (direction, _) in PORTS.items() if direction == 'input'}
    leaf_widths = {n: width for n, (direction, width) in PORTS.items() if direction == 'input'}
    used, visiting = set(), set()
    for name, c in cells.items():
        instance = instances[c['rtl_path'].rsplit('.', 1)[1]]
        spec = expected['cells'][name]
        require(instance['model'] == spec['model'] and instance['parameters'] == spec['parameters'], 'RTL_CELL_POLICY:' + name)
        pin_names = set(spec['pins']) | ({'q'} if not name.endswith('_marker') else set())
        require(set(instance['pins']) == pin_names, 'RTL_PINS:' + name)
        ports = {p['name']: (p['direction'], p['width']) for p in c['ports']}
        width = int(spec['parameters'].get('WIDTH', 1))
        port_widths = {n: 1 for n in pin_names}
        if spec['model'].endswith('ControlGate_v1'):
            port_widths.update(a=width, b=width, q=width)
        elif spec['model'].endswith('EventRegister_v1'):
            port_widths.update(d=width, q=width)
        elif spec['model'].endswith('TimingMarker_v1'):
            port_widths['values'] = width
        elif spec['model'].endswith('AsymmetricC_v1'):
            port_widths.update(common=int(spec['parameters']['COMMON']), rising=max(1, int(spec['parameters']['RISING'])), falling=1)
        require(len(c['ports']) == len(pin_names) and ports == {p: ('output' if p == 'q' else 'input', w)
                for p, w in port_widths.items()}, 'CELL_PORTS:' + name)
        if 'q' in pin_names:
            net = instance['pins']['q']
            require(re.fullmatch(r'\w+', net) and net in wires and wires[net] == width and
                    net not in leaves and net not in assignments, 'RTL_Q_DRIVER:' + name)
            leaves[net] = ('name', 'Q_' + name)
            leaf_widths['Q_' + name] = width

    def resolve(name):
        used.add(name)
        if name in leaves:
            return leaves[name]
        require(name in assignments and (name in wires or PORTS.get(name, ('',))[0] == 'output'), 'RTL_UNDRIVEN:' + name)
        require(name not in visiting, 'RTL_COMBINATIONAL_CYCLE:' + name)
        visiting.add(name)
        result = expression(assignments[name], resolve)
        visiting.remove(name)
        return result

    def desired(text):
        return expression(text, lambda n: desired(expected['outputs'][n]) if n in expected['outputs'] else ('name', n))

    def expression_width(tree):
        op = tree[0]
        if op == 'name':
            return leaf_widths[tree[1]]
        if op == 'literal':
            require(0 <= tree[2] < 2 ** tree[1], 'LITERAL_WIDTH')
            return tree[1]
        if op == 'slice':
            require(0 <= tree[3] <= tree[2] < expression_width(tree[1]), 'SLICE_WIDTH')
            return tree[2] - tree[3] + 1
        if op == 'cat':
            return sum(map(expression_width, tree[1:]))
        if op == 'repeat':
            return tree[1] * expression_width(tree[2])
        if op == '~':
            return expression_width(tree[1])
        if op == 'mux':
            require(expression_width(tree[1]) == 1, 'MUX_SELECTOR_WIDTH')
            require(expression_width(tree[2]) == expression_width(tree[3]), 'MUX_BRANCH_WIDTH')
            return expression_width(tree[2])
        sizes = [expression_width(x) for x in tree[1:]]
        require(len(set(sizes)) == 1, 'OPERAND_WIDTH')
        return 1 if op == '==' else sizes[0]

    bindings = {}
    for name, c in cells.items():
        instance = instances[c['rtl_path'].rsplit('.', 1)[1]]
        for pin, wanted in expected['cells'][name]['pins'].items():
            got = expression(instance['pins'][pin], resolve)
            require(got == desired(wanted), 'RTL_BINDING:' + name + '.' + pin)
            bindings[c['rtl_path'] + '.' + pin] = wanted
    for name, wanted in expected['outputs'].items():
        require(resolve(name) == desired(wanted), 'RTL_OUTPUT:' + name)
        require(expression_width(resolve(name)) == PORTS[name][1], 'RTL_OUTPUT_WIDTH:' + name)
    require(re.sub(r'\s+', '', assignments['response_bits_error']) == "1'h0", 'ERROR_LITERAL')
    definitions = []
    for line in clean(references).splitlines():
        if not line.strip():
            continue
        m = re.fullmatch(r'\s*`define\s+(\w+)\s+(\w+)\s*', line)
        require(m is not None, 'PROBE_SYNTAX')
        definitions.append((m[1], m[2]))
    refs = unique(definitions, 'PROBE_DUPLICATE')
    # Standalone ref_<module>.sv contains local probes. For an embedded owner,
    # callers convert the already verified top ABI's resolved paths to this
    # local form. Forwarded global e.probe names must never stand in for local
    # RTL anchors, nor may the conversion mutate the original top-level node.
    require(set(refs) == {'ref_' + node['module'] + '_' + local_probe_name(e['id']) for e in node['endpoints']}, 'PROBES')
    endpoint_bindings = {}
    for e in node['endpoints']:
        wire = refs['ref_' + node['module'] + '_' + local_probe_name(e['id'])]
        require(wires.get(wire, PORTS.get(wire, (None, None))[1]) == e['width'], 'PROBE_WIDTH:' + e['id'])
        require(resolve(wire) == desired(expected['endpoints'][e['id']]), 'PROBE_BINDING:' + e['id'])
        endpoint_bindings[e['id']] = node['rtl_path'] + '.' + wire
        if resolved:
            require(e['rtl_path'] == endpoint_bindings[e['id']], 'RESOLVED_PROBE_BINDING:' + e['id'])
    require(set(wires) <= used and set(assignments) <= used, 'RTL_EXTRA_LOGIC')
    require(set(assignments).isdisjoint(n for n, (d, _) in PORTS.items() if d == 'input'), 'RTL_INPUT_WRITER')
    for name, width in wires.items():
        require(expression_width(resolve(name)) == width, 'RTL_WIRE_WIDTH:' + name)
    return reset_record(node, variant, bindings, endpoint_bindings)


def reset_record(node, variant, bindings, endpoints):
    """Resolved supplemental record; all listed expressions were checked in RTL."""
    cells = {p['id']: p for p in node['primitives']}
    state = []
    for name, cell in cells.items():
        if cell['model'].endswith('TimingMarker_v1'):
            continue
        state.append(dict(id=name, model=cell['model'], path=cell['rtl_path'], reset_pin=cell['rtl_path'] + '.reset',
                          reset_expression=bindings[cell['rtl_path'] + '.reset'],
                          lifetime='application' if cell['reset'] == 'presentation_reset' else 'power-on',
                          width=int(cell['parameters'].get('WIDTH', 1))))
    owner = node['rtl_path']
    return dict(schema='riscay-reset-boundary-v1', owner=owner,
                scope='standalone digital native program return; no integration or physical qualification',
                protocol='two-phase-bundled-v1' if variant == 'click' else 'four-phase-bundled-v1',
                por=owner + '.reset', application_reset=owner + '.applicationReset',
                presentation_reset=endpoints['presentation_reset'], presentation_reset_expression=APPLICATION_RESET,
                state=state, endpoints=endpoints, checked_bindings=bindings,
                application_port=dict(request=owner + '.response_req', acknowledge=owner + '.response_ack',
                    data=owner + '.response_bits_data', error=owner + '.response_bits_error',
                    error_literal=False, payload_owner=cells['payload']['rtl_path'],
                    permission_owner=cells['permission']['rtl_path'], request_ack_lifetime='application', payload_lifetime='power-on',
                    cancellation='qualified application reset irrevocably clears captured permission; POR word and proof transport drain independently',
                    data_hold='retained POR payload remains stable until all word/publication/capture/presentation branches return'),
                publication=dict(reset_lifetime='power-on', payload='retained_word[0]', dynamic=True),
                capture_receipt=dict(reset_lifetime='power-on', control_only=True,
                    request=owner + '.captureRequest', acknowledge=owner + '.captureAcknowledge'),
                captures={n: dict(trigger=cells[n]['rtl_path'] + '.trigger', data=cells[n]['rtl_path'] + '.d',
                    origin=cells[origin]['rtl_path'] + '.q', setup_fs=100000, hold_fs=100000,
                    pulse_high_fs=100000, pulse_low_fs=100000, distribution_max_fs=100000)
                    for n, origin in CAPTURES[variant].items()},
                delay_policy={c['rtl_path']: dict(fixed_fs=int(c['parameters']['DELAY_FS']) if n.endswith('_data_delay') or n == 'data_delay' else None,
                    minimum_fs=1000000, maximum_fs=10000000) for n, c in cells.items()
                    if not c['model'].endswith('TimingMarker_v1') and n not in FIXED_GUARDS},
                assumptions=dict(qualified_reset_hold_min_fs=350000000, digital_reset_settlement_max_fs=250000000,
                    control_delay_range_fs=[1000000, 10000000], cleanup_guards_fs=200000000,
                    physical_cells_and_complete_path_closure_required=True))


def validate_export(directory):
    directory = Path(directory)
    document = json.loads((directory / 'contract.json').read_text())
    manifest = document['manifest']; node = manifest['design']
    validate_program_return(node)
    require(manifest['top'] == node['module'] == node['rtl_path'] and node['reset_domain'] == 'root' and
            node['module'] in ('FourPhaseProgramReturn', 'ClickProgramReturn'), 'TOP')
    require(manifest['schema'] == 'chisel-async-contract-v3' and manifest['time_unit'] == 'fs', 'SCHEMA')
    models = {c['model'] for c in node['primitives']}
    require(set(manifest['resources']) == {'chiselasync/sv/' + m + '.sv' for m in models}, 'RESOURCES')
    for model in models:
        actual = hashlib.sha256((directory / (model + '.sv')).read_bytes()).hexdigest()
        require(model in MODEL_HASHES and actual == EXPORTED_MODEL_HASHES[model] and
                manifest['resources']['chiselasync/sv/' + model + '.sv'] == MODEL_HASHES[model], 'MODEL_HASH:' + model)
    files = [line.strip().replace('\\', '/').removeprefix('./')
             for line in (directory / 'filelist.f').read_text().splitlines() if line.strip()]
    require(len(files) == len(models) + 1 and set(files) == {m + '.sv' for m in models} | {node['module'] + '.sv'}, 'FILELIST')
    for kind, filename in (('port_abi', 'ports.json'), ('probe_abi', 'ref_' + node['module'] + '.sv')):
        require(manifest[kind] == dict(file=filename, sha256=hashlib.sha256((directory / filename).read_bytes()).hexdigest()),
                'ABI_HASH:' + kind)
    abi = json.loads((directory / 'ports.json').read_text())
    require(abi['schema'] == 'chisel-async-port-abi-v2' and abi['top'] == node['module'] and
            len(abi['nodes']) == 1 and abi['nodes'][0]['rtl_path'] == node['module'] and
            abi['nodes'][0]['module'] == node['module'], 'PORT_ABI')
    port_names = {n: n for n in PORTS}
    port_names.update({n: n.replace('_', '.', 1) for n in PORTS if n.startswith(('word_', 'publication_', 'response_'))})
    port_names.update(response_bits_data='response.bits.data', response_bits_error='response.bits.error')
    require(len(abi['nodes'][0]['ports']) == len(PORTS) and
            {p['source']: (p['direction'], p['width'], p['signed'], p['clock']) for p in abi['nodes'][0]['ports']} ==
            {'~|' + node['module'] + '>' + port_names[n]: (d, w, False, False) for n, (d, w) in PORTS.items()}, 'PORT_ABI_SCHEMA')
    record = validate_program_return_rtl(node, (directory / (node['module'] + '.sv')).read_text(),
                                     (directory / ('ref_' + node['module'] + '.sv')).read_text())
    record['export_sha256'] = {f: hashlib.sha256((directory / f).read_bytes()).hexdigest()
                               for f in sorted(set(files) | {'contract.json', 'ports.json', 'ref_' + node['module'] + '.sv', 'filelist.f'})}
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    record = validate_export(args.export)
    args.out.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print('PROGRAM_RETURN_CONTRACT_PASS', record['owner'])


if __name__ == '__main__':
    main()

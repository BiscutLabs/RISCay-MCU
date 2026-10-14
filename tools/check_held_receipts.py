# SPDX-License-Identifier: Apache-2.0
"""Closed inventory of retained peripheral/SRAM payload receivers (C1b).

No payload register, native guard or settling cycle is added. The mapping probe
checks the actual source storage on every step; it never forces a derived bus.
This does not qualify the longer producer-to-consumer physical capture path.
"""
import re
from pathlib import Path
from check_service_reply_receipt import _child, _fields, leaf, receipt_control_fingerprint, CONTROL_FINGERPRINTS


def require(ok, message):
    if not ok: raise ValueError('HELD_RECEIPT_' + message)


def elapsed_source_fields(lanes, click):
    """Independent low-to-high owner schema, separate from reply field packing."""
    fields = _fields([('mode', 1 if click else 2), ('replyPhase',1),
        ('commandPhase',1), ('single',1), ('index',3)] +
        [(f'remainder[{i}]',10) for i in range(lanes)] +
        [(f'quotient[{i}]',32) for i in range(lanes)] +
        [(f'fraction[{i}]',10) for i in range(lanes)] + [('delta',32), ('target',32)])
    return fields


def catalog(manifest):
    root = manifest['design']; result = []
    children = {c['id'] for c in root['children']}
    def add(owner, receiver, fields, storage, model, width=None):
        if owner not in children: return
        parent = _child(root, owner); node = _child(parent, receiver)
        result.append(dict(owner=owner, node=node, fields=_fields(fields),
                           storage=parent['rtl_path'] + '.' + storage, model=model,
                           width=width or sum(w for _, w in fields)))
    native_model = 'ChiselAsyncEventRegister_v1' if manifest['top'] == 'ClickSoc' else 'ChiselAsyncClosingLatch_v1'
    for bank in ('ram', 'program'):
        for lane in range(4):
            add(bank+'_access', 'byte_request_'+str(lane), [('enable',1),('data',8),('write',1),('address',32)],
                f'ca_child_native.ca_child_lane_{lane}_issue.ca_primitive_payload.q', native_model)
    if 'elapsed_scaler' in children:
        parent = _child(root, 'elapsed_scaler')
        node = _child(parent, 'reply_bridge')
        layout = node['channels'][0]['layout']
        lanes = len([f for f in layout if re.fullmatch(r'bits.elapsed\[\d+\]', f['field'])])
        require(lanes > 0, 'ELAPSED_LANES')
        click = manifest['top'] == 'ClickSoc'
        native = _child(parent, 'native'); owner = _child(native, 'owner')
        source_fields = elapsed_source_fields(lanes, click)
        require(re.fullmatch(('Click' if click else 'FourPhase')+r'Elapsed(?:_\d+)?',native['module']) and
                native['reset_domain'] == owner['reset_domain'] == 'root', 'ELAPSED_OWNER')
        require(re.fullmatch(('PhaseDecoupledClickBuffer' if click else 'FourPhaseFifo')+r'(?:_\d+)?',
                owner['module']), 'ELAPSED_STORAGE_OWNER')
        channels = [c for c in owner['channels'] if c['id'] == 'out']
        require(len(channels) == 1, 'ELAPSED_SOURCE_CHANNEL')
        expected = [dict(field='bits.'+f, lsb=o, width=w, signed=False,
                         source=f'~|{owner["module"]}>out.bits.{f}') for f,o,w in source_fields]
        require(channels[0]['layout'] == expected, 'ELAPSED_SOURCE_LAYOUT')
        offsets = {f:(o,w) for f,o,w in source_fields}
        storage = 'ca_child_native.ca_child_owner.' + ('' if click else 'head_ca_child_stage0.ca_child_storage.')
        add('elapsed_scaler', 'reply_bridge', [(f'elapsed[{i}]',32) for i in range(lanes)]+[('single',1)]+
            [(f'state.fraction[{i}]',10) for i in range(lanes)]+[('state.consumed',32)],
            storage+'ca_primitive_payload.q', native_model, sum(w for _,_,w in source_fields))
        result[-1]['source_fields'] = {
            **{f'elapsed[{i}]':offsets[f'quotient[{i}]'] for i in range(lanes)},
            **{f'state.fraction[{i}]':offsets[f'fraction[{i}]'] for i in range(lanes)},
            'single':offsets['single'], 'state.consumed':offsets['target']}
    add('spi_adc', 'reply_bridge', [('value',32),('publish',1),('nextPrimed',1)],
        'ca_child_native.ca_child_finish.ca_primitive_payload.q', native_model)
    # Each Join retains its command operand in a native input buffer. Never
    # compare the already retired clocked command sender with that token.
    right = 'right_storage' if manifest['top'] == 'ClickSoc' else 'right'
    add('spi_adc', 'wave_bridge', [('',1)],
        'ca_child_native.ca_child_owner.ca_child_'+right+'.ca_primitive_payload.q',native_model)
    add('i2c', 'snapshot_bridge', [('',8)], 'ca_child_native.ca_child_publication.ca_primitive_snapshot_payload.q',
        'ChiselAsyncEventRegister_v1')
    return result


def validate_held_receipts(manifest, directory, scopes):
    if manifest.get('top') not in ('FourPhaseSoc', 'ClickSoc'): return []
    click = manifest['top'] == 'ClickSoc'; pairs = []
    for item in catalog(manifest):
        node = item['node']; path = node['rtl_path']; model = node['module']; fields = item['fields']
        require(re.fullmatch(('Click' if click else 'FourPhase')+r'ServiceReplyReceipt(?:_\d+)?', model), 'OWNER:'+path)
        require(node['reset_domain'] == 'root' and node['capacity'] == 1 and
                all(node[k] == [] for k in ('children','primitives','timing')), 'OWNERSHIP:'+path)
        require([c['id'] for c in node['channels']] == ['in','out'], 'CHANNELS:'+path)
        for channel in node['channels']:
            side = channel['id']
            expected = [('bits'+('.'+f if f else ''),o,w,False) for f,o,w in fields]
            require([(v['field'],v['lsb'],v['width'],v['signed']) for v in channel['layout']] == expected, 'LAYOUT:'+path)
            require(channel['protocol'] == ('decoupled-v1' if side == 'out' else
                    'two-phase-bundled-v1' if click else 'four-phase-bundled-v1') and
                    channel['role'] == ('output' if side == 'out' else 'input'), 'PROTOCOL:'+path)
            require(all(v['source'] == f'~|{model}>{side}.{v["field"]}' for v in channel['layout']), 'FIELD_SOURCE:'+path)
        scope = scopes[path]; ack = 'ack' if click else 'acknowledge'
        require(scope['registers'] == dict(localReset_release_0=1,localReset_release_1=1,
                request_stages_0=1,request_stages_1=1,state=2,**{ack:1}) and not scope.get('memories'), 'STORAGE:'+path)
        ports = {n:dict(name=n,width=1,direction=d) for n,d in [('reset','input'),('clock','input'),
                 ('in_req','input'),('in_ack','output'),('out_ready','input'),('out_valid','output')]}
        for f,_,w in fields:
            for side,direction in [('in','input'),('out','output')]:
                name=side+'_bits'+('_'+leaf(f) if f else '')
                ports[name]=dict(name=name,width=w,direction=direction)
        # FIRRTL deduplicates the eight identical byte receivers. Resolve the
        # actual compiled module while retaining exact per-instance ports.
        require(re.fullmatch(('Click' if click else 'FourPhase')+r'ServiceReplyReceipt(?:_\d+)?',scope['model']) and
                scope['ports'] == ports, 'PORTS:'+path)
        rtl=(Path(directory)/(scope['model']+'.sv')).read_text()
        require(receipt_control_fingerprint(rtl,fields) == CONTROL_FINGERPRINTS['click' if click else 'bd'], 'CONTROL:'+path)
        source,reg=item['storage'].rsplit('.',1); storage=scopes[source]
        require(storage['model'] == item['model'] and storage['parameters'].get('WIDTH') == str(item['width']) and
                storage['ports'].get('q') == dict(name='q',width=item['width'],direction='output'), 'NATIVE_STORAGE:'+path)
        for f,offset,width in fields:
            if 'source_fields' in item:
                offset, source_width = item['source_fields'][f]
                require(source_width == width, 'SOURCE_FIELD_WIDTH:'+path+'.'+f)
            selected=item['storage']+(f'[{offset}]' if width == 1 and item['width'] > 1 else
                     f'[{offset+width-1}:{offset}]' if width < item['width'] else '')
            for side in ('in','out'):
                pairs.append((path+'.'+side+'_bits'+('_'+leaf(f) if f else ''),selected))
    return pairs


def held_receipt_probe(source, pairs):
    anchor='task check; begin'
    require(source.count(anchor) == 1, 'CHECK_SHAPE')
    checks=''.join(f'\nif ({a} !== {b}) $fatal(1,"HELD_RECEIPT_BINDING:{a}");' for a,b in pairs)
    return source.replace(anchor,anchor+checks)

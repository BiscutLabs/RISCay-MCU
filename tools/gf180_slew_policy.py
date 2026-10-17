# SPDX-License-Identifier: Apache-2.0
"""Corner-specific ordinary slew views; native control remains limited to 2 ns.

Views change electrical limits only, never characterization tables. Native
membership comes from validated primitive recipes and actual connectivity,
not hierarchical name substrings or payload widths.
"""
from collections import defaultdict, deque
from decimal import Decimal
import re

from gf180_physical import SC, sha, write_json
from gf180_control_roles import DATA, CONTROL
from repair_gf180_control import require

FRACTION = Decimal('0.8')
NATIVE_NS = 2.0
LIMIT = re.compile(rb'\b(?:default_max_transition|max_transition)\s*:\s*([0-9]+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?)\s*;')
BUFFER = re.compile(re.escape(SC) + r'(?:buf|clkbuf|inv)_\d+')
NONCODE = re.compile(rb'//[^\r\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"', re.S)


def limit_view(source, fraction=FRACTION):
    require(Decimal(0) < fraction < Decimal(1), 'SLEW_FRACTION')
    masked = NONCODE.sub(lambda m:re.sub(rb'[^\r\n]',b' ',m[0]),source)
    require(b'/*' not in masked and b'"' not in masked, 'SLEW_LIBRARY_SYNTAX')
    require(len(re.findall(rb'\btime_unit\s*:\s*1ns\s*;',masked))==1,
            'SLEW_LIBRARY_TIME_UNIT')
    matches = list(LIMIT.finditer(masked))
    require(matches and len(matches)==len(re.findall(rb'\b(?:default_max_transition|max_transition)\s*:',masked)),
            'SLEW_LIBRARY_LIMITS_MISSING')
    parts = []; cursor = 0; edits = []
    for match in matches:
        old = match[1]; value = Decimal(old.decode())
        require(value > 0, 'SLEW_LIBRARY_LIMIT_INVALID')
        new = format(value * fraction, 'f').encode()
        parts += [source[cursor:match.start(1)], new]
        cursor = match.end(1)
        edits.append(dict(offset=match.start(1), before=old.decode(), after=new.decode()))
    parts.append(source[cursor:])
    return b''.join(parts), edits


def verify_view(source, candidate, fraction=FRACTION):
    expected, edits = limit_view(source, fraction)
    require(candidate == expected, 'SLEW_VIEW_CHANGED_CHARACTERIZATION')
    return edits


def write_views(pdk, out, corners):
    out.mkdir(parents=True, exist_ok=False)
    records = {}
    for corner in corners:
        original = pdk / (SC + corner + '.lib')
        destination = out / original.name
        data = original.read_bytes(); changed, edits = limit_view(data)
        destination.write_bytes(changed)
        verify_view(data, destination.read_bytes())
        records[corner] = dict(source_sha256=sha(original), view_sha256=sha(destination),
                               edits=edits)
    record = dict(schema='riscay-slew-views-v1', fraction=str(FRACTION), native_limit_ns=NATIVE_NS,
                  characterization_changed=False, corners=records)
    write_json(out / 'manifest.json', record)
    return record


def native_recipe_pins(binding):
    """Select native control nets within one exact adapter recipe.

    Payload D/Q and data-allowance lanes retain ordinary electrical limits.
    Their reset/capture trees retain strict limits. If a payload net also
    serves control elsewhere, graph union promotes the whole net to strict.
    """
    model = binding['model'].removeprefix('ChiselAsync').removesuffix('_v1')
    cells = binding['cells']; nets = {n for c in cells for n in c['pins'].values()}
    if model in ('And', 'Xor', 'AsymmetricC', 'PhaseRegister'):
        strict = nets
    elif model == 'ControlGate' and binding['requirements'].get('role') == CONTROL:
        strict = nets
    elif model in ('EventRegister', 'ClosingLatch') or (
            model == 'ControlGate' and binding['requirements'].get('role') == DATA):
        strict = {'reset'}
        if model != 'ControlGate':
            strict.add('closed' if model == 'ClosingLatch' else 'trigger')
        # Recipe buffers/inverters carry control to reset and capture pins.
        changed = True
        while changed:
            changed = False
            for c in cells:
                if BUFFER.fullmatch(c['cell']) and c['pins'].get('I') in strict:
                    outputs = [n for p,n in c['pins'].items() if p in ('Z','ZN')]
                    for n in outputs:
                        if n not in strict: strict.add(n); changed = True
        for c in cells:
            for p,n in c['pins'].items():
                if p in ('E','CLK','RN','SETN'):
                    require(n in strict, 'SLEW_UNCLASSIFIED_CAPTURE_RESET')
    else:
        raise ValueError('SLEW_UNKNOWN_NATIVE_RECIPE_' + model)
    return sorted(c['name'] + '/' + p for c in cells for p,n in c['pins'].items()
                  if n in strict and n not in ("1'b0", "1'b1"))


def seed_pins(mapping, adapter_instances):
    expected = {i for b in mapping['bindings'] for i in b['instances']}
    require(set(adapter_instances) == expected, 'SLEW_ADAPTER_INVENTORY')
    result = set()
    for binding in mapping['bindings']:
        local = native_recipe_pins(binding)
        require(local, 'SLEW_EMPTY_NATIVE_RECIPE')
        for instance in binding['instances']:
            result.update(adapter_instances[instance] + '/' + p for p in local)
    return sorted(result)


def classify(graph, seeds):
    """graph is the actual flat leaf graph, including newly inserted buffers."""
    pins = {}; adjacent = defaultdict(set)
    for name,cell in graph['cells'].items():
        for pin, bits in cell['connections'].items():
            require(bits, 'SLEW_EMPTY_LEAF_CONNECTION')
            require(len(bits)==1 or cell['type'].startswith('gf180mcu_ocd_ip_sram__'),
                    'SLEW_UNKNOWN_VECTOR_LEAF')
            for i,n in enumerate(bits):
                pins[name + '/' + pin + (f'[{i}]' if len(bits)>1 else '')] = n
        if BUFFER.fullmatch(cell['type']):
            con = cell['connections']
            output = 'ZN' if cell['type'].startswith(SC + 'inv_') else 'Z'
            require(set(con) == {'I', output} and all(len(v)==1 for v in con.values()), 'SLEW_BUFFER_SHAPE')
            a,b = con['I'][0],con[output][0]
            adjacent[a].add(b); adjacent[b].add(a)
    require(seeds and set(seeds) <= set(pins), 'SLEW_NATIVE_PIN_MISSING')
    strict = {pins[p] for p in seeds}
    # Keep the existing explicit top-level electrical envelope. In particular,
    # an observation payload driving SDA is also a physical pin driver.
    for name, port in graph.get('ports', {}).items():
        for i,n in enumerate(port['bits']):
            pins[name if len(port['bits']) == 1 else f'{name}[{i}]'] = n
            strict.add(n)
    pending = deque(strict)
    while pending:
        for n in adjacent[pending.popleft()] - strict:
            strict.add(n); pending.append(n)
    return dict(native_pins=sorted(p for p,n in pins.items() if n in strict),
                ordinary_pins=sorted(p for p,n in pins.items() if n not in strict),
                native_nets=strict)


def report_rows(text):
    """Fail closed on unknown report output, including malformed violations."""
    section=None; rows=[]; seen=set()
    for line in text.splitlines():
        line=line.strip()
        if not line or set(line)=={'-'}:continue
        if line in ('max slew','max capacitance'):section=line;continue
        if re.fullmatch(r'Pin\s+Limit\s+(?:Slew|Cap|Capacitance)\s+Slack',line):continue
        match=re.fullmatch(r'(\S+)\s+([-+.0-9eE]+)\s+([-+.0-9eE]+)\s+([-+.0-9eE]+)\s+\(VIOLATED\)',line)
        require(section is not None and match is not None,'SLEW_REPORT_SHAPE')
        pin=match[1]; key=(section,pin)
        require(key not in seen,'SLEW_DUPLICATE_REPORT_PIN');seen.add(key)
        limit,value,slack=map(float,match.groups()[1:])
        require(all(__import__('math').isfinite(v) for v in (limit,value,slack)) and
                limit>0 and value>=0 and slack<=0 and abs(limit-value-slack)<0.000003,
                'SLEW_REPORT_NUMBERS')
        rows.append(dict(kind=section,pin=pin,limit=limit,value=value,slack=slack,
                         unit='ns' if section=='max slew' else 'pF'))
    return rows


def compose_reports(ordinary,native,inventory):
    strict=set(inventory['native_pins']); normal=set(inventory['ordinary_pins'])
    require(strict and not strict&normal,'SLEW_PIN_CLASS_OVERLAP')
    a,b=report_rows(ordinary),report_rows(native)
    for row in a+b:require(row['pin'] in strict|normal,'SLEW_REPORT_UNCLASSIFIED_PIN')
    # Capacitance has the same constraint and graph in both contexts.
    caps=lambda rows:sorted((r for r in rows if r['kind']=='max capacitance'),key=lambda r:r['pin'])
    require(caps(a)==caps(b),'SLEW_CAPACITANCE_CONTEXT_CHANGED')
    strict_rows={r['pin']:r for r in b if r['kind']=='max slew'}
    for row in a:
        if row['kind']!='max slew':continue
        other=strict_rows.get(row['pin'])
        require(other is not None and other['value']==row['value'] and other['limit']<=row['limit'],
                'SLEW_REPORT_CONTEXT_CHANGED')
    result=caps(a)
    for rows,selected,label in ((a,normal,'ordinary'),(b,strict,'native-or-boundary')):
        for row in rows:
            if row['kind']=='max slew' and row['pin'] in selected:
                if label=='native-or-boundary':require(row['limit']<=NATIVE_NS+1e-6,'SLEW_NATIVE_LIMIT_RELAXED')
                result.append(dict(row,policy=label))
    return result

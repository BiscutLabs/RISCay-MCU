# SPDX-License-Identifier: Apache-2.0
"""Same-corner guard campaign on complete, electrically repaired chip graphs.

This is a reversible physical recipe change, not statistical or routed signoff.
Each instance keeps its actual data cone, load and capture tree. Counts may be
shared by a mapper parameter group; measured results never are.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import hashlib
import math
from pathlib import Path
import re
import shutil
import subprocess

import control_relative_timing as relative
import native_leaf_timing as leaf
import native_stage_timing as stage
from experiment_elapsed_guard import narrow_chain
from experiment_passive_stage import write_verilog, partition
from gf180_physical import ROOT, SC, nodes, sha, write_json
from gf180_implement import instances
from gf180_estimate import direct_groups
from physical_tools import tool
from repair_gf180_control import require
from repair_gf180_design import validate_receipt, flat

DERATE = .20
RESIDUAL_NS = 2.0
PURE_BD = {
    ('FourPhaseCore','request_guard'),('FourPhaseControl','acknowledge_guard'),
    ('FourPhaseFrameStore','request_delay'),('FourPhaseFrameStore','request_guard'),('FourPhaseFrameStore','return_guard'),
    ('I2cPublication','output_guard'),('I2cPublication','return_guard'),
    ('FourPhaseProgramReturn','request_guard'),('FourPhaseProgramReturn','output_delay'),
    ('FourPhaseRamReturn','request_guard'),('FourPhaseRamReturn','output_delay'),
    ('FourPhasePublicationSource','request_delay'),('FourPhaseCompletion','request_guard'),('FourPhaseFabric','request_guard')}


def validate_historical_receipt(mapping, revision='2f5aa54'):
    """Validate old graph evidence while mapper helpers evolve in this batch.

    Only repository helper files may use their hash-exact recorded Git blob.
    Netlists, PDK, executables, tool configuration and every evidence file must
    still match the original receipt at their actual paths.
    """
    from repair_gf180_design import EVIDENCE, input_files
    mapping = Path(mapping).resolve()
    require(re.fullmatch(r'[0-9a-f]{7,40}', revision) is not None, 'GUARD_REVISION')
    receipt = json.loads((mapping/'electrical-repair/receipt.json').read_text())
    out = mapping/'electrical-repair'
    require(receipt.get('schema') == 'riscay-electrical-repair-v1' and
            receipt['status'] == 'structurally-accepted-electrically-unqualified' and
            receipt['physical_qualification'] is False, 'GUARD_REPAIR_RECEIPT_STATUS')
    require(set(receipt['evidence_sha256']) == set(EVIDENCE) and
            set(receipt['inputs_sha256']) == {str(p.resolve()) for p in input_files(mapping)},
            'GUARD_REPAIR_INVENTORY')
    for name,key in (('netlist.v','repaired_verilog_sha256'), ('netlist.json','repaired_json_sha256')):
        require(sha(mapping/name) == receipt[key], 'GUARD_REPAIRED_GRAPH_CHANGED')
    require(sha(mapping/'netlist-audit.json') == receipt['evidence_sha256']['candidate/netlist-audit.json'],
            'GUARD_REPAIRED_AUDIT_CHANGED')
    for name,digest in receipt['evidence_sha256'].items():
        path = (out/name).resolve()
        require(path.is_relative_to(out) and sha(path) == digest, 'GUARD_REPAIR_EVIDENCE_CHANGED')
    history = []
    for name,digest in receipt['inputs_sha256'].items():
        path = Path(name)
        if path.parent == mapping and path.name in ('netlist.v', 'netlist.json', 'netlist-audit.json'):
            path = out/'reference'/path.name
        if sha(path) == digest:
            continue
        require(path.parent == ROOT/'tools', 'GUARD_NONHELPER_INPUT_CHANGED')
        relative_path = path.relative_to(ROOT).as_posix()
        blob = subprocess.run(['git', 'show', revision+':'+relative_path], cwd=ROOT,
                              capture_output=True, check=True).stdout
        # Repository checkout uses CRLF; the recorded receipt hashes those bytes.
        forms = (blob, blob.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        require(any(hashlib.sha256(value).hexdigest() == digest for value in forms),
                'GUARD_HISTORICAL_HELPER_MISMATCH')
        history.append(dict(path=str(path), measured_hash=digest, current_hash=sha(path),
                            source_commit=revision))
    receipt['historical_helpers'] = history
    return receipt


def family(name):
    return re.sub(r'_\d+$', '', name)


def inventory(mapping):
    record = json.loads((mapping/'mapping.json').read_text())
    manifest = json.loads((mapping/'timing-intent.json').read_text())['manifest']
    owners = {p['rtl_path']:(n, p) for n in nodes(manifest['design']) for p in n['primitives']}
    rows = []
    for b in record['bindings']:
        if b['requirements'].get('role') != 'matched-control-delay':
            continue
        for path in b['instances']:
            owner, p = owners[path]
            name, ident = family(owner['module']), p['id']
            count = sum(c['cell'] == SC+'dlyd_1' for c in b['cells'])
            if b['parameters']['DELAY_FS'] <= 1000000:
                purpose, disposition = 'functional-feedback', 'retain-functional-primitive'
                classification='functional-not-a-removable-wait'
            elif name in ('FourPhaseStage', 'LongHoldBuffer'):
                purpose = 'ordering-'+('bundling' if ident == 'request_delay' else 'publication')
                disposition = 'measure-canonical-stage'
                classification='ordering'
            elif name in ('ClickStage', 'ClickBuffer'):
                purpose = 'ordering-and-pulse-'+ident
                disposition = 'measure-canonical-stage' if ident == 'acknowledge_guard' else 'retain-pulse-path'
                classification='mixed-ordering-and-pulse/reset'
            else:
                # Custom owners keep their exact recipe. The inventory is an
                # explicit scope disposition, never a fabricated timing pass.
                purpose = 'custom-ordering-and-reset' if name != 'InitialTokens' else 'seed-reset-admission'
                disposition = 'retain-custom-obligation'
                pure=((name,ident) in PURE_BD if record['variant']=='bd' else
                      (name,ident) in {('ClickCore','request_guard'),('I2cPublication','output_guard'),('I2cPublication','return_guard')})
                classification='ordering' if pure else 'mixed-ordering-and-pulse/reset'
            rows.append(dict(instance=path, owner=owner['rtl_path'], owner_module=name,
                             owner_metadata_module=owner['module'],
                             primitive_id=ident, original_parameters=b['parameters'],
                             stages=count, purpose=purpose, classification=classification, disposition=disposition))
    return rows, manifest, record


def conservative_margin(early, late, aperture=0, derate=DERATE):
    require(all(math.isfinite(x) and x >= 0 for x in (early, late, aperture)), 'GUARD_MARGIN_INPUT')
    require(.20 <= derate < 1, 'GUARD_DERATE_FLOOR')
    return (1-derate)*early-(1+derate)*late-aperture


def phase_slews(log):
    values = {}
    for line in log.splitlines():
        fields = line.split('\t')
        if fields[0] != 'GUARD_PHASE_Q_SLEW':continue
        require(len(fields)==4 and tuple(fields[1:3]) not in values, 'GUARD_PHASE_SLEW_ROW')
        mode,edge=fields[1:3];value=float(fields[3])
        require(mode in ('min','max') and edge in ('rise','fall') and math.isfinite(value) and value>=0,
                'GUARD_PHASE_SLEW_VALUE')
        values[mode,edge]=value
    require(set(values)=={(m,e) for m in ('min','max') for e in ('rise','fall')},
            'GUARD_PHASE_SLEW_COVERAGE')
    require(all(values['min',e]<=values['max',e] for e in ('rise','fall')), 'GUARD_PHASE_SLEW_ORDER')
    return {e:{m:values[m,e] for m in ('min','max')} for e in ('rise','fall')}


def scalar_table_max(body, timing_prefix, table_names):
    values = []
    for _, pin in direct_groups(body, 'pin'):
        for _, arc in direct_groups(pin, 'timing'):
            if timing_prefix and not re.search(r'timing_type\s*:\s*'+timing_prefix, arc):
                continue
            for name in table_names:
                for _, table in direct_groups(arc, name):
                    field = re.search(r'values\s*\((.*?)\)\s*;', table, re.S)
                    require(field is not None, 'GUARD_LIBERTY_VALUES')
                    values.extend(float(v) for v in re.findall(r'[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?', field[1]))
    require(values and all(math.isfinite(x) for x in values), 'GUARD_LIBERTY_COVERAGE')
    return max(0., max(values))


def extend_plan(plan, index):
    """Add BD A-to-capture and publication paths in both directions.

    Publication follows the latest closure plus a conservative latch D-to-Q
    bound. This gives no transparent-latch or source-age timing credit.
    """
    result = deepcopy(plan)
    if plan['variant'] == 'click':
        for phase in (0, 1):
            edge = 'rise' if phase == 0 else 'fall'
            request = next(c for c in result['contexts'] if c['id'] == f'request-{phase}')
            ctx = deepcopy(request)
            ctx.update(id=f'rearm-{phase}', kind='rearm', sources=[result['phase']['Q']['pin']], queries=[])
            # Reset and downstream ACK retain their real state; phase inputs
            # are now driven by the actual phase Q, and pending request is held.
            cases = request['state']['cases']
            ctx['state']['cases'] = [cases[0], cases[-1],
                                    ('pin', relative.driver(result['native'], 'request_delay'), 1-phase)]
            for lane in result['lane_map']:
                for mode in ('min', 'max'):
                    ctx['queries'].append(dict(id=f'rearm:{lane["lane"]}:{mode}', role='ack',
                        lane=lane['lane'], mode=mode, source_edge=edge, sink_edge='fall',
                        sink_kind='pin', sink=lane['capture'], receiver_role='rearm-clock'))
            result['contexts'].append(ctx)
        return result
    root = relative.driver(result['native'], 'a')
    prefix = result['native']['physical_prefix']
    offer_net = index.before['boundaries'][prefix+'out_req'][0]
    targets = sorted(p for k,p in index.consumers[offer_net] if k == 'pin')
    require(targets, 'GUARD_PUBLICATION_RECEIVERS')
    ctx = deepcopy(next(c for c in result['contexts'] if c['id'] == 'request-0'))
    ctx.update(id='publication', kind='publication', sources=[root], queries=[])
    # The already-bound request context fixes downstream ACK low, permitting
    # both A transitions through the long-hold OR and the output guard.
    for edge in ('rise', 'fall'):
        for lane in result['lane_map']:
            for mode in ('min', 'max'):
                ctx['queries'].append(dict(id=f'close:{lane["lane"]}:{mode}:{edge}', role='capture',
                    lane=lane['lane'], mode=mode, source_edge=edge,
                    sink_edge='fall' if edge == 'rise' else 'rise', sink_kind='pin', sink=lane['capture']))
        for i,pin in enumerate(targets):
            for mode in ('min', 'max'):
                # Reuse the graph-arrival reader also used for ACK receivers:
                # ordinary combinational input pins are not STA PathEnds.
                ctx['queries'].append(dict(id=f'offer:{i}:{mode}:{edge}', role='ack',
                    mode=mode, source_edge=edge, sink_edge=edge, sink_kind='pin', sink=pin,
                    receiver_role='publication-receiver'))
    release=deepcopy(ctx)
    release.update(id='a-return',kind='a-return',sources=[index.scalar(prefix[:-1],'out_ack')[1]],queries=[])
    b=relative.driver(result['native'],'b')
    release['state']['cases']=[(kind,pin,1 if pin==b or '/ca_primitive_a/' in pin and pin.endswith('/A1') else value)
                              for kind,pin,value in ctx['state']['cases'] if pin!=release['sources'][0]]
    release['state']['cases'].append(('pin',relative.driver(result['native'],'request_delay'),1))
    for mode in ('min','max'):
        release['queries'].append(dict(id='a-return:'+mode,role='ack',mode=mode,source_edge='rise',sink_edge='fall',
            sink_kind='pin',sink=root,receiver_role='source-return'))
    result['contexts'].extend([release,ctx])
    result['publication_targets'] = targets
    return result


def focus_guard_plan(plan):
    """Keep all changed guard obligations without remeasuring unrelated data.

    Elapsed changes a request guard and therefore retains the complete data,
    setup and hold survey. Other cases retain actual loaded launch slews and
    every capture/ACK/rearm branch; omitted data setup is explicitly unmeasured.
    """
    if plan['descriptor']['instance'].endswith('.ca_child_elapsed_scaler.ca_child_native.ca_child_step'):
        return plan
    result=deepcopy(plan);result['guard_only']=True
    if result['variant']=='bd':
        launch=deepcopy(next(c for c in result['contexts'] if c['id']=='request-0'))
        launch.update(id='a-launch',kind='a-launch',queries=[dict(id='a-launch:'+mode,role='ack',
            mode=mode,source_edge='rise',sink_edge='rise',sink_kind='pin',
            sink=relative.driver(result['native'],'a'),receiver_role='actual-a-launch') for mode in ('min','max')])
        result['contexts']=[launch]+[c for c in result['contexts'] if c['id'] in ('a-return','publication')]
    else:
        result['contexts']=[c for c in result['contexts'] if c['id']!='data']
        for ctx in result['contexts']:
            if ctx['id'].startswith(('request-','release-')):
                edge=ctx['queries'][0]['source_edge']
                ctx['kind']='launch'
                ctx['queries']=[dict(id='fire-launch:'+mode,role='ack',mode=mode,source_edge=edge,
                    sink_edge='rise',sink_kind='pin',sink=result['event'],receiver_role='actual-fire-launch')
                    for mode in ('min','max')]
    return result


def candidate_counts(rows):
    changes = []
    for row in rows:
        count = row['stages']
        if row['disposition'] == 'measure-canonical-stage':
            if row['primitive_id'] in ('output_delay', 'acknowledge_guard'):
                count = min(count, 8)
            elif row['owner'].endswith('.ca_child_elapsed_scaler.ca_child_native.ca_child_step'):
                count = min(count, 28)
        if count < row['stages']:
            changes.append(dict(row, stages=count, previous_stages=row['stages']))
    return changes


def rewrite_graph(live, audit, changes):
    """Clone shared hierarchy only along changed paths; keep original leaf IDs."""
    result = deepcopy(live)
    cloned = {}
    removals = []
    for change in changes:
        path = audit['adapter_instances'][change['instance']]
        parts = path.split('/')
        body = result['modules']['RiscayMcuDigital']
        for depth, part in enumerate(parts):
            prefix = '/'.join(parts[:depth+1])
            require(part in body['cells'], 'GUARD_INSTANCE_MISSING')
            cell = body['cells'][part]
            if prefix not in cloned:
                name = 'GuardCampaign_'+str(len(cloned))+'_'+cell['type']
                require(name not in result['modules'], 'GUARD_CLONE_COLLISION')
                result['modules'][name] = deepcopy(result['modules'][cell['type']])
                cell['type'] = name
                cloned[prefix] = name
            require(cell['type'] == cloned[prefix], 'GUARD_CLONE_BINDING')
            body = result['modules'][cell['type']]
        replacement, ordered, removed = narrow_chain(body, change['stages'])
        require(len(ordered) == change['previous_stages'], 'GUARD_ORIGINAL_COUNT')
        result['modules'][cloned[path]] = replacement
        removals.extend(path+'/'+name for name in removed)
    before,after=flat(live,'RiscayMcuDigital'),flat(result,'RiscayMcuDigital')
    removed=set(removals)
    require(set(before['cells'])-removed==set(after['cells']), 'GUARD_LEAF_SCOPE')
    aliases={}
    for path in removed:
        cell=before['cells'][path]
        require(cell['type']==SC+'dlyd_1' and set(cell['connections'])=={'I','Z'}, 'GUARD_REMOVED_CELL')
        aliases[cell['connections']['Z'][0]]=cell['connections']['I'][0]
    for path,cell in after['cells'].items():
        prior=before['cells'][path]
        require((cell['type'],cell['directions'])==(prior['type'],prior['directions']), 'GUARD_OTHER_LEAF_CHANGED')
    require(partition(before,aliases,removed)==partition(after), 'GUARD_PIN_PARTITION_CHANGED')
    return result, removals


def margins(results, plan, aperture, liberty):
    summary = dict(scope='changed guard paths only',data_setup='UNMEASURED',source_launch_composition='UNMEASURED') if plan.get('guard_only') else relative.margins({k:v for k,v in results.items()
                               if k not in ('publication', 'a-return', 'rearm-0', 'rearm-1')}, plan, aperture)
    rows = []
    data = results.get('data',{}).get('rows',{})
    common = results.get('common',{}).get('rows',{})
    phases=[] if plan.get('guard_only') and plan['variant']=='bd' else ([0] if plan['variant']=='bd' else [0,1])
    for phase in phases:
        edge = 'rise' if phase == 0 else 'fall'
        request = results[f'request-{phase}']['rows']
        ackrows = common if plan['variant'] == 'bd' else results['ack']['rows']
        ack = min(v['delay_ns'] for k,v in ackrows.items() if k.startswith('ack:') and k.endswith(':min:'+edge))
        for lane in range(plan['payload_width']):
            close = common[f'capture:{lane}:max']['delay_ns']
            rows.append(dict(kind='hold', lane=lane, phase=phase,
                slack_ns=conservative_margin(ack, close, aperture['hold_ns'])))
            if plan.get('guard_only') or str(lane) in plan.get('constant_lanes', {}):
                continue
            late = max(data[f'data:{lane}:max:{e}']['delay_ns'] for e in ('rise', 'fall'))
            early = request[f'capture:{lane}:min:{edge}']['delay_ns']
            rows.append(dict(kind='setup', lane=lane, phase=phase,
                slack_ns=conservative_margin(early, late, aperture['setup_ns'])))
    if plan['variant'] == 'bd':
        storage = liberty[SC+'latrnq_1']
        # Maximum complete cell-rise/fall table is conservative even when
        # latch D was already stable before closure.
        dq = scalar_table_max(storage, None, ('cell_rise', 'cell_fall'))
        pubs = results['publication']['rows']
        for edge in ('rise', 'fall'):
            early = min(v['delay_ns'] for k,v in pubs.items() if k.startswith('offer:') and k.endswith(':min:'+edge))
            late = max(v['delay_ns'] for k,v in pubs.items() if k.startswith('close:') and k.endswith(':max:'+edge))
            rows.append(dict(kind='publication-'+edge, slack_ns=conservative_margin(early, late+dq)))
    else:
        pulse = scalar_table_max(liberty[SC+'dffrnq_1'], 'min_pulse_width',
                                 ('rise_constraint', 'fall_constraint'))
        ackrows = results['ack']['rows']
        for phase in (0, 1):
            edge = 'rise' if phase == 0 else 'fall'
            acks = [r for k,r in ackrows.items() if k.endswith(':min:'+edge)]
            ack = min(r['delay_ns'] for r in acks)
            latest_phase = common['phase_clock:max']['delay_ns']
            earliest_phase = common['phase_clock:min']['delay_ns']
            late_cq = max(r['clk_q_ns'] for k,r in ackrows.items() if k.endswith(':max:'+edge))
            early_cq = min(r['clk_q_ns'] for k,r in ackrows.items() if k.endswith(':min:'+edge))
            rearm = results[f'rearm-{phase}']['rows']
            last_fall = latest_phase+late_cq+max(r['delay_ns'] for k,r in rearm.items() if k.endswith(':max'))
            rows.append(dict(kind='ack-after-rearm', phase=phase,
                             slack_ns=conservative_margin(ack, last_fall, pulse)))
            for lane in range(plan['payload_width']):
                first_fall = earliest_phase+early_cq+rearm[f'rearm:{lane}:min']['delay_ns']
                last_rise = common[f'capture:{lane}:max']['delay_ns']
                rows.append(dict(kind='pulse-high', phase=phase, lane=lane,
                                 slack_ns=conservative_margin(first_fall, last_rise, pulse)))
    return dict(summary=summary, rows=rows,
                minima={k:min(r['slack_ns'] for r in rows if r['kind'] == k) for k in {r['kind'] for r in rows}})


def measure_case(netlist, plan, index, directory, corner, slew, sta):
    key = f'{corner}-s{slew}'
    liberty = relative.library(ROOT/'.tools/physical/pdk'/(SC+corner+'.lib'))
    aperture = relative.aperture(liberty, plan['variant'])
    results = {}
    for context in deepcopy(plan['contexts']):
        if context['kind'] in ('common', 'sequential_ack'):
            bounds = [r['event_slew_ns'] for k,r in results.items() if k.startswith(('request-', 'release-'))]
            context['root_slew_ns'] = dict(min=min(x[0] for x in bounds), max=max(x[1] for x in bounds))
        if context['kind'] == 'rearm':
            edge=context['queries'][0]['source_edge']
            require('phase_q_slew_ns' in results['ack'], 'GUARD_REARM_SLEW_REQUIRED')
            context['root_slew_ns']=results['ack']['phase_q_slew_ns'][edge]
        if context['kind']=='publication':
            launch='a-launch' if plan.get('guard_only') else 'request-0'
            require('a_slew_ns' in results[launch] and 'a_slew_ns' in results['a-return'],
                    'GUARD_PUBLICATION_SLEW_REQUIRED')
            bounds=[results[launch]['a_slew_ns']['rise'],results['a-return']['a_slew_ns']['fall']]
            context['root_slew_ns']=dict(min=min(v['min'] for v in bounds),max=max(v['max'] for v in bounds))
        script = directory/(key+'-'+context['id']+'.tcl')
        log = script.with_suffix('.log')
        context_plan = dict(plan, event=context['sources'][0]) if context['kind'] in ('publication','rearm','a-return','a-launch','launch') else plan
        text = leaf.script(netlist, corner, slew, context_plan, context, sta=sta)
        if context['kind'] in ('publication','rearm','launch'):
            before = 'elseif {$pin ne $root || $start_edge ne "rise"}'
            require(text.count(before) == 1, 'GUARD_EVENT_READER_SHAPE')
            source_edge = '$edge' if context['kind']=='publication' else '"'+context['queries'][0]['source_edge']+'"'
            text = text.replace(before, 'elseif {$pin ne $root || $start_edge ne '+source_edge+'}')
        if context['kind']=='launch':
            # Path-reader root is the request/release source; the downstream
            # common/ACK contexts need the loaded fire output's measured slew.
            marker='set event_pin [exact_object pin '+relative.brace(context_plan['event'])+']'
            require(text.count(marker)==1,'GUARD_LAUNCH_EVENT_BINDING')
            text=text.replace(marker,'set event_pin [exact_object pin '+relative.brace(plan['event'])+']')
        if context['kind'] == 'rearm':
            # Split the actual sequential launch at Q. Its measured CLK-to-Q
            # arc is added from the separate ACK context in margins(); without
            # this one cut STA suppresses the self-clock return path. No keeper
            # or combinational feedback arc is waived by this split.
            marker = 'set roots {};'
            require(text.count(marker) == 1, 'GUARD_REARM_CLOCK_SHAPE')
            phase = plan['phase']['Q']['pin'].rsplit('/', 1)[0]
            text = text.replace(marker, 'set_disable_timing -from CLK -to Q [get_cells {'+phase+'}]\n'+marker)
        measure_phase=context['kind']=='sequential_ack'
        measure_a=plan['variant']=='bd' and context['id'] in ('request-0','a-return','a-launch')
        if measure_phase or measure_a:
            marker='row RELATIVE_COMPLETE\n'
            require(text.count(marker)==1, 'GUARD_PHASE_SLEW_INSERT')
            measured_pin=plan['phase']['Q']['pin'] if measure_phase else relative.driver(plan['native'],'a')
            query='set phase_q_pin [exact_object pin {'+measured_pin+'}]\n'
            for mode in ('min','max'):
                for edge in ('rise','fall'):
                    query+=f'row GUARD_PHASE_Q_SLEW {mode} {edge} [leaf_slew $phase_q_pin {edge} {mode}]\n'
            text=text.replace(marker,query+marker)
        script.write_text(text, newline='\n')
        with log.open('w') as stream:
            subprocess.run(sta.command(['-no_init', '-exit', sta.path(script)], timeout=55),
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=65)
        results[context['id']] = leaf.parse(log.read_text(), context_plan, context, slew, index)
        if measure_phase:
            results[context['id']]['phase_q_slew_ns']=phase_slews(log.read_text())
        if measure_a:
            results[context['id']]['a_slew_ns']=phase_slews(log.read_text())
    checked = margins(results, plan, aperture, liberty)
    result = dict(instance=plan['descriptor']['instance'], key=key,
                  minima=checked['minima'], electrical_rows=max(len(r['electrical_violations']) for r in results.values()))
    write_json(directory/(key+'.json'), dict(result=result, results=results, aperture=aperture, **checked))
    return result


def run(mapping, output, variant, *, candidate=False, paths=(), workers=2, focused=False):
    require(not output.exists(), 'GUARD_OUTPUT_EXISTS')
    mapping = mapping.resolve()
    receipt = validate_historical_receipt(mapping)
    rows, manifest, record = inventory(mapping)
    audit = json.loads((mapping/'netlist-audit.json').read_text())
    original = stage.receipt_original(mapping, receipt)
    live = json.loads((mapping/'netlist.json').read_text())
    proof = stage.receipt_proof(mapping, receipt)
    source_index = leaf.LeafIndex(original, live, proof['added_buffers'], proof['added_ties'])
    cuts = leaf.keeper_cuts(source_index, audit)
    selected = sorted({r['owner'] for r in rows if r['disposition'] == 'measure-canonical-stage'})
    if paths:
        require(set(paths) <= set(selected), 'GUARD_UNKNOWN_STAGE')
        selected = list(paths)
    changes = candidate_counts(rows) if candidate else []
    output.mkdir(parents=True)
    write_json(output/'inventory.json', dict(rows=rows, purpose_counts=dict(Counter(r['purpose'] for r in rows))))
    write_json(output/'retained-receipt.json', receipt)
    write_json(output/'changes.json', changes)
    plans = []
    for path in selected:
        node = next(n for n in nodes(manifest['design']) if n['rtl_path'] == path)
        desc = stage.descriptor(manifest, original, record, path, variant,
                                storage=family(node['module']) in ('LongHoldBuffer', 'ClickBuffer'))
        plan = leaf.bind_plan(relative.make_plan(original, record, variant, desc), source_index, desc, original, cuts)
        extended=extend_plan(plan,source_index)
        plans.append(focus_guard_plan(extended) if focused else extended)
    sta, yosys = tool('sta'), tool('yosys')
    if candidate:
        graph, removed = rewrite_graph(live, audit, changes)
        physical = output/'physical'; physical.mkdir()
        write_verilog(graph, physical, yosys)
        netlist = physical/'netlist.v'
        index = leaf.LeafIndex(original, graph, proof['added_buffers'], proof['added_ties'])
        for plan in plans:
            plan['native']['cells'] = [c for c in plan['native']['cells'] if c['path'] not in removed]
    else:
        netlist = mapping/'netlist.v'; index = source_index
    files = [mapping/f for f in ('netlist.v', 'netlist.json', 'mapping.json', 'netlist-audit.json', 'timing-intent.json')]
    files += [Path(__file__), ROOT/'tools/native_stage_timing.py', ROOT/'tools/native_leaf_timing.py',
              ROOT/'tools/control_relative_timing.py', ROOT/'tools/experiment_elapsed_guard.py',
              ROOT/'tools/experiment_passive_stage.py', relative.PROBE, *sta.input_files(), *yosys.input_files()]
    files += [ROOT/'.tools/physical/pdk'/(SC+c+'.lib') for c in relative.CORNERS]
    files += [ROOT/'.tools/gf180-sram'/(leaf.SRAM+'__tt_025C_3v30.lib')]
    frozen = {str(p.resolve()):sha(p) for p in files}
    # Preserve the exact executed helpers even if this long campaign is later
    # interrupted or a subsequent implementation changes the working tree.
    snapshot=output/'source-snapshot';snapshot.mkdir()
    for path in files:
        if path.parent.resolve()==(ROOT/'tools').resolve():
            shutil.copyfile(path,snapshot/path.name)
            require(sha(snapshot/path.name)==frozen[str(path.resolve())],'GUARD_SNAPSHOT_CHANGED')
    write_json(output/'inputs.json',frozen)
    tasks = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i,plan in enumerate(plans):
            directory = output/str(i); directory.mkdir()
            write_json(directory/'plan.json', plan)
            for corner in relative.CORNERS:
                for slew in (.02, 2.):
                    tasks.append(pool.submit(measure_case, netlist, plan, index, directory, corner, slew, sta))
        results = []; failures=[]
        for future in as_completed(tasks):
            try:result=future.result()
            except Exception as error:
                failures.append(dict(type=type(error).__name__,message=str(error)))
                print(json.dumps(dict(failure=failures[-1])),flush=True);continue
            results.append(result)
            print(json.dumps(result), flush=True)
    require(all(sha(Path(p)) == digest for p,digest in frozen.items()), 'GUARD_INPUT_CHANGED')
    final_receipt=validate_historical_receipt(mapping)
    write_json(output/'results.json', dict(engineering_derate=DERATE, residual_ns=RESIDUAL_NS,
        statistical_qualification=False, routed_qualification=False, candidate=candidate,
        status='COMPLETE_MEASURED' if not failures else 'INCOMPLETE_FAILURES',focused=focused,
        cases=results, failures=failures, changes=changes, input_sha256=frozen, post_run_receipt=final_receipt,
        files_sha256={str(p.relative_to(output)).replace('\\','/'):sha(p)
                      for p in output.rglob('*') if p.is_file()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mapping', type=Path); parser.add_argument('output', type=Path)
    parser.add_argument('--variant', choices=('bd', 'click'), required=True)
    parser.add_argument('--candidate', action='store_true')
    parser.add_argument('--stage', action='append', default=[])
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--focused',action='store_true')
    args = parser.parse_args()
    run(args.mapping, args.output, args.variant, candidate=args.candidate, paths=args.stage, workers=args.workers,focused=args.focused)

# SPDX-License-Identifier: Apache-2.0
"""Exact native credit topology, bindings, and literal payload obligations."""
import re
from check_completion_export import validate_completion


def children(node):
    return {c['id']: c['contract'] for c in node['children']}


def endpoints(node):
    return {e['id']: e['rtl_path'] for e in node['endpoints']}


def validate_admission(node):
    if not re.fullmatch(r'(?:FourPhase|Click)Admission(?:_[0-9]+)?',node['module']):
        raise ValueError('ADMISSION_OWNER')
    click = node['module'].startswith('Click')
    protocol = 'two-phase-bundled-v1' if click else 'four-phase-bundled-v1'
    if (node['capacity'] != 2 or node['timing'] or len(node['channels']) != 2 or
        {c['id']:(c['protocol'],c['role']) for c in node['channels']} !=
        {'returned':(protocol,'input'),'grant':(protocol,'output')} or
        any(e['width'] != 1 for e in node['endpoints']) or
        any(c['layout'] != [dict(field='bits',lsb=0,width=1,signed=False,
            source=f"~|{node['module']}>{c['id']}.bits")] for c in node['channels'])):
        raise ValueError('ADMISSION_SCHEMA')
    cs=children(node)
    if set(cs) != {'pending','credit'} or len(node['children']) != 2:
        raise ValueError('ADMISSION_OWNER')
    expected=('ClickBuffer','PhaseDecoupledClickBuffer') if click else ('LongHoldBuffer','FourPhaseFifo')
    for n,m in zip(('pending','credit'),expected):
        if not re.fullmatch(m+r'(?:_[0-9]+)?',cs[n]['module']) or cs[n]['capacity'] != 1:
            raise ValueError('ADMISSION_STORAGE')
    if click:
        if node['primitives'] or cs['pending']['children'] or cs['credit']['children']:
            raise ValueError('ADMISSION_CLICK_OWNER')
        for n,seed in (('pending','0'),('credit','1')):
            cells={p['id']:p for p in cs[n]['primitives']}
            if (cells['click_marker']['parameters']['SEEDED'] != seed or
                cells['input_phase']['parameters']['RESET_VALUE'] != '0' or
                cells['output_phase' if n=='credit' else 'input_phase']['parameters']['RESET_VALUE'] != seed or
                cells['output_guard']['parameters']['RESET_VALUE'] != seed):
                raise ValueError('ADMISSION_SEED_COUNT')
    else:
        cells={p['id']:p for p in node['primitives']}
        expected_params=dict(COMMON='1',RISING='1',FALLING='0',DELAY_FS='1000000',RESET_VALUE='0',
                             COMMON_INVERT='0',RISING_INVERT='0',FALLING_INVERT='0')
        if (set(cells) != {'return_barrier'} or len(node['primitives']) != 1 or
            cells['return_barrier']['model'] != 'ChiselAsyncAsymmetricC_v1' or
            cells['return_barrier']['parameters'] != expected_params):
            raise ValueError('ADMISSION_RETURN_BARRIER')
        cc=children(cs['credit'])
        if (set(cc) != {'initial','stage0'} or cc['initial']['capacity'] != 1 or
            not re.fullmatch(r'InitialTokens(?:_[0-9]+)?',cc['initial']['module']) or
            not re.fullmatch(r'FourPhaseMerge(?:_[0-9]+)?',cc['stage0']['module'])):
            raise ValueError('ADMISSION_SEED_COUNT')
        if {p['id'] for p in cc['initial']['primitives']} != {
                'accepted0','active0','finished0','data','request_delay','initial_mux_marker'}:
            raise ValueError('ADMISSION_SEED_COUNT')


def admission_pairs(node):
    e=endpoints(node); cs=children(node); p=endpoints(cs['pending']); c=endpoints(cs['credit'])
    pairs=[(e['returned_'+s],p['in_'+s]) for s in ('request','data','acknowledge')]
    pairs += [(e['grant_'+s],c['out_'+s]) for s in ('request','data','acknowledge')]
    pairs += [(p['out_'+s],c['in_'+s]) for s in ('data','acknowledge')]
    if node['module'].startswith('Click'):
        pairs += [(p['out_request'],c['in_request']),(e['start'],c['start'])]
    else:
        b=node['primitives'][0]['rtl_path']
        pairs += [(p['out_request'],b+'.common'),(e['response_idle'],b+'.rising'),
                  (c['in_request'],b+'.q')]
    return pairs


def literal_nets(contents, scopes):
    """Record only a single elaborated scalar constant driver, never sampled values."""
    constants=dict(re.findall(r'^(L_\w+) \.functor BUFT 1, C4<([01])>, C4<0>, C4<0>, C4<0>;$',contents,re.M))
    paths={}; current=None
    for line in contents.splitlines():
        scope=re.match(r'(S_\w+) \.scope (\w+), "([^"\\]+)" "([^"\\]+)" (.*);$',line)
        if scope:
            key,kind,name,model,tail=scope.groups(); parent=re.search(r', (S_\w+)$',tail)
            current=(paths[parent[1]]+'.' if parent else '')+name; paths[key]=current
        net=re.match(r'v\w+ \.net(?:/\w+)? "(\w+)", 0 0, (L_\w+);\s+(?:alias, )?1 drivers$',line)
        if net and current in scopes and net[2] in constants:
            scopes[current].setdefault('literal_scalars',{})[net[1]]=int(constants[net[2]])
    return scopes


def admission_probe(source,manifest,scopes):
    pairs=[]; constants=[]
    def visit(node):
        if re.fullmatch(r'(?:FourPhase|Click)Admission(?:_[0-9]+)?',node['module']):
            validate_admission(node); pairs.extend(admission_pairs(node))
        if re.fullmatch(r'(?:FourPhase|Click)Completion(?:_[0-9]+)?',node['module']):
            constants.append((node,'creditReturn_data'))
        for c in node['children']: visit(c['contract'])
    visit(manifest['design'])
    if manifest['top'] in ('FourPhaseSoc','ClickSoc'):
        cs=children(manifest['design'])
        if not {'admission','completion','admission_grant_bridge'} <= cs.keys():
            raise ValueError('ADMISSION_SOC_INVENTORY')
        if 'admission' in cs:
            click=manifest['top']=='ClickSoc'
            prefix='Click' if click else 'FourPhase'
            if any(not re.fullmatch(prefix+suffix+r'(?:_[0-9]+)?',cs[name]['module'])
                   for name,suffix in (('admission','Admission'),('completion','Completion'))):
                raise ValueError('ADMISSION_SOC_OWNER')
            validate_admission(cs['admission']);validate_completion(cs['completion'])
            bridge=cs['admission_grant_bridge']
            model='ClickToDecoupled' if click else 'FourPhaseToDecoupled'
            protocol='two-phase-bundled-v1' if click else 'four-phase-bundled-v1'
            if (not re.fullmatch(model+r'(?:_[0-9]+)?',bridge['module']) or
                {c['id']:(c['protocol'],c['role']) for c in bridge['channels']} !=
                {'in':(protocol,'input'),'out':('decoupled-v1','output')} or
                any(c['layout'] != [dict(field='bits',lsb=0,width=1,signed=False,
                    source=f"~|{bridge['module']}>{c['id']}.bits")] for c in bridge['channels'])):
                raise ValueError('ADMISSION_GRANT_BRIDGE_SCHEMA')
            a=endpoints(cs['admission']); c=endpoints(cs['completion']); g=endpoints(cs['admission_grant_bridge'])
            pairs += [(a['returned_'+s],c['creditReturn_'+s]) for s in ('request','data','acknowledge')]
            pairs += [(a['grant_'+s],g['in_'+s]) for s in ('request','data','acknowledge')]
            if manifest['top']=='FourPhaseSoc':
                pairs.append((a['response_idle'],f"(!{c['response_request']} && !{c['response_acknowledge']})"))
            constants += [(cs['admission'],'returned_data'),(children(cs['admission'])['pending'],'in_data')]
    comparisons=[f'if ({a} !== {b}) $fatal(1,"ADMISSION_BINDING:{a}");' for a,b in pairs]
    for node,name in constants:
        ep=next(e for e in node['endpoints'] if e['id']==name); path=ep['rtl_path']; owner,net=path.rsplit('.',1)
        if ep['width'] != 1 or scopes.get(owner,{}).get('literal_scalars',{}).get(net) != 0:
            raise ValueError('ADMISSION_LITERAL_DRIVER:'+path)
        pattern=r'^if \(ones_(\d+) !== 1\'h1 \|\| zeros_\1 !== 1\'h1\) \$fatal\(1, "INACTIVE_ENDPOINT:'+re.escape(path)+r'"\);$'
        matches=list(re.finditer(pattern,source,re.M))
        if len(matches) != 1: raise ValueError('ADMISSION_LITERAL_COVERAGE:'+path)
        m=matches[0]
        source=source[:m.start()]+m[0].replace(f"ones_{m[1]} !== 1'h1",f"ones_{m[1]} !== 1'h0")+source[m.end():]
        comparisons.append(f'if ({path} !== 1\'b0) $fatal(1,"ADMISSION_LITERAL_VALUE:{path}");')
    anchor='task check; begin'
    if source.count(anchor)!=1: raise ValueError('ADMISSION_PROBE_SHAPE')
    return source.replace(anchor,anchor+'\n'+'\n'.join(comparisons))

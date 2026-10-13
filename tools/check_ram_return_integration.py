# SPDX-License-Identifier: Apache-2.0
"""Native retained RAM return bindings and narrowly proven constant coverage."""
import json,re
from check_application_reset import presentation_reset
from pathlib import Path
from check_ram_return_contract import validate_ram_return,validate_ram_return_rtl,require,expression
from check_ram_capture_receipt import validate_ram_access
from check_frame_integration import validated_service_clock


def mask_literal_zero(source,endpoint,width,bit):
    return apply_return_literal_obligations(source,[(endpoint,width,bit)])


def apply_return_literal_obligations(source,obligations):
    """Apply exact, independently proved zero bits once per packed endpoint.

    Begin only from untouched all-polarity requirements. Two return owners may
    prove different bits of Completion.result_sources; neither may inherit a
    partially relaxed mask as evidence that the other's aliases were checked.
    """
    grouped={}
    for endpoint,width,bit in obligations:
        require(type(width) is int and width>0 and type(bit) is int and 0<=bit<width,'CONSTANT_MASK_RANGE')
        old_width,bits=grouped.setdefault(endpoint,(width,set()))
        require(old_width==width and bit not in bits,'CONSTANT_MASK_DUPLICATE_OR_WIDTH:'+endpoint)
        bits.add(bit)
    for endpoint,(width,bits) in grouped.items():
        source=_mask_literal_zeros(source,endpoint,width,bits)
    return source


def _mask_literal_zeros(source,endpoint,width,bits):
    full=(1<<width)-1
    pattern=(r"^if \(ones_(\d+) !== "+str(width)+"'h"+f"{full:x}"+
        r" \|\| zeros_\1 !== "+str(width)+"'h"+f"{full:x}"+
        r'\) \$fatal\(1, "INACTIVE_ENDPOINT:'+re.escape(endpoint)+r'"\);$')
    matches=list(re.finditer(pattern,source,re.M));require(len(matches)==1,'CONSTANT_COVERAGE_SHAPE:'+endpoint)
    m=matches[0]
    replacement=(f"if (ones_{m[1]} !== {width}'h{full^sum(1<<bit for bit in bits):x} || zeros_{m[1]} !== {width}'h{full:x}) "
        f'$fatal(1, "INACTIVE_ENDPOINT:{endpoint}");')
    return source[:m.start()]+replacement+source[m.end():]


def close_error_aliases(node,completion,top,scopes,directory):
    """Close every alias occurrence before allowing any zero polarity mask.

    The top wire has exactly one declaration and two scalar pin connections.
    In Completion, consume only the scalar input declaration, the two exact
    packing writers, pure expression reads, and known child input-pin reads.
    Reject every remaining occurrence. A writer blacklist cannot safely cover
    concatenated lvalues, parameterized child outputs, force or other syntax.
    """
    directory=Path(directory)
    clean=lambda text:re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    compact=lambda text:re.sub(r'\s+','',text)
    rtl=clean((directory/(top+'.sv')).read_text())
    def pins(text,instance):
        blocks=list(re.finditer(r'^\s*(\w+)\s+(?:#\(.*?\)\s*)?'+re.escape(instance)+r'\s*\((.*?)^\s*\);',text,re.M|re.S))
        require(len(blocks)==1,'ERROR_ALIAS_INSTANCE:'+instance)
        block=blocks[0];fragment=block[2];result={};at=0
        while at<len(fragment):
            match=re.match(r'\s*\.(\w+)\s*\(',fragment[at:])
            require(match is not None,'ERROR_ALIAS_PIN_SYNTAX:'+instance)
            begin=at+match.end();end=begin;depth=1
            while end<len(fragment) and depth:
                depth+=(fragment[end]=='(')-(fragment[end]==')');end+=1
            require(depth==0 and match[1] not in result,'ERROR_ALIAS_PIN_DUPLICATE_OR_END')
            result[match[1]]=(fragment[begin:end-1].strip(),block.start(2)+at,block.start(2)+end)
            at=end
            rest=fragment[at:].lstrip()
            if not rest:break
            require(rest.startswith(','),'ERROR_ALIAS_PIN_SEPARATOR')
            at=len(fragment)-len(rest)+1
        return result
    def erase(text,spans):
        for begin,end in sorted(spans,reverse=True):
            text=text[:begin]+' '*(end-begin)+text[end:]
        return text
    def has(text,name):return re.search(r'\b'+re.escape(name)+r'\b',text) is not None
    producer=node['rtl_path'].rsplit('.',1)[1];consumer=completion['rtl_path'].rsplit('.',1)[1]
    produced=pins(rtl,producer).get('response_bits_error',('',0,0))
    consumed=pins(rtl,consumer).get('ram_bits_error',('',0,0))
    net=produced[0]
    require(re.fullmatch(r'\w+',net),'ERROR_ALIAS_SOURCE')
    require(consumed[0]==net,'ERROR_ALIAS_CONSUMER')
    for path,pin,direction in ((node['rtl_path'],'response_bits_error','output'),
                               (completion['rtl_path'],'ram_bits_error','input')):
        port=scopes.get(path,{}).get('ports',{}).get(pin,{})
        require(port.get('direction')==direction and port.get('width')==1,'ERROR_ALIAS_SCALAR_PORT')
    declarations=list(re.finditer(r'\bwire\s+'+re.escape(net)+r'\s*;',rtl))
    require(len(declarations)==1,'ERROR_ALIAS_DECLARATION')
    residue=erase(rtl,[produced[1:],consumed[1:],declarations[0].span()])
    require(not has(residue,net),'ERROR_ALIAS_UNCONSUMED_TOP_REFERENCE')
    body=clean((directory/(completion['module']+'.sv')).read_text())
    e={x['id']:x for x in completion['endpoints']}
    leaves=['plan_bits_response_data','plan_bits_response_error','plan_bits_memory','plan_bits_ram',
        'plan_bits_telemetry','plan_bits_housekeeping','memory_bits_data','memory_bits_error','ram_bits_data','ram_bits_error']
    if completion['module'].startswith('Click'):
        leaves+=['plan_req','memory_req','ram_req','telemetry_req','housekeeping_req']
        for name in ('memory_phase','ram_phase','telemetry_phase','housekeeping_phase'):
            cell=next(p for p in completion['primitives'] if p['id']==name)
            instance=cell['rtl_path'].rsplit('.',1)[1]
            q=pins(body,instance).get('q',('',0,0))[0]
            require(re.fullmatch(r'\w+',q),'ERROR_ALIAS_PHASE_Q')
            leaves.append(q)
    wanted={'ram_data':'{ram_bits_data,ram_bits_error}','result_sources':'{'+','.join(leaves)+'}'}
    packed={e[n]['rtl_path'].rsplit('.',1)[1]:n for n in wanted}
    require(len(packed)==2,'ERROR_ALIAS_PACKED_ENDPOINT_DUPLICATE')
    protected={'ram_bits_error',*packed}
    spans=[]
    header=re.search(r'\bmodule\s+'+re.escape(completion['module'])+r'\s*\((.*?)\);',body,re.S)
    require(header is not None,'ERROR_ALIAS_COMPLETION_HEADER')
    scalar=[part.strip() for part in header[1].split(',') if has(part,'ram_bits_error')]
    require(scalar==['input ram_bits_error'] or len(scalar)==1 and compact(scalar[0])=='inputram_bits_error',
            'ERROR_ALIAS_INPUT_DECLARATION')
    require(not any(has(header[1],n) for n in packed),'ERROR_ALIAS_PACKED_PORT')
    spans.append(header.span())
    found={n:0 for n in packed}
    # Only entire module-level pure continuous assignments may consume reads.
    # Anchoring rejects procedural assignments and concatenated lvalues.
    for match in re.finditer(r'^\s*(wire\s+(?:\[\d+:0\]\s*)?|assign\s+)(\w+)\s*=\s*([^;]+);',body,re.M):
        lhs,rhs=match[2],match[3]
        if lhs not in protected and not any(has(rhs,n) for n in protected):continue
        require(lhs!='ram_bits_error','ERROR_ALIAS_INPUT_WRITER')
        if lhs in packed:
            require(match[1].lstrip().startswith('wire') and compact(rhs)==wanted[packed[lhs]],
                    'ERROR_ALIAS_PACKING:'+packed[lhs])
            found[lhs]+=1
        expression(rhs)
        spans.append(match.span())
    require(all(n==1 for n in found.values()),'ERROR_ALIAS_PACKING_INVENTORY')
    # Consume only reads at enumerated physical input ports. Parameterized cell
    # output writers, including concatenated/sliced outputs, remain forbidden.
    children={p['rtl_path'] for p in completion.get('primitives',[])} | {
        c['contract']['rtl_path'] for c in completion.get('children',[])}
    for path,scope in scopes.items():
        if not path.startswith(completion['rtl_path']+'.'):continue
        instance=path[len(completion['rtl_path'])+1:]
        if '.' in instance:continue
        for pin,(value,begin,end) in pins(body,instance).items():
            if not any(has(value,n) for n in protected):continue
            require(path in children and scope.get('ports',{}).get(pin,{}).get('direction')=='input',
                    'ERROR_ALIAS_CHILD_OUTPUT_WRITER')
            expression(value)
            spans.append((begin,end))
    residue=erase(body,spans)
    require(not any(has(residue,n) for n in protected),'ERROR_ALIAS_UNCONSUMED_COMPLETION_REFERENCE')
    return dict(source=node['rtl_path']+'.response_bits_error',wire=top+'.'+net,
        consumer=completion['rtl_path']+'.ram_bits_error',packing_checked=['ram_data','result_sources'])


def ram_return_probe(source,manifest,scopes,directory,literal_obligations=None):
    root=manifest['design'];top=manifest['top'];directory=Path(directory)
    children={c['id']:c['contract'] for c in root.get('children',[])}
    standalone=re.fullmatch(r'(?:FourPhase|Click)RamReturn(?:_[0-9]+)?',root['module'])
    node=root if standalone else children.get('ram_return')
    if node is None:
        require(top not in ('FourPhaseSoc','ClickSoc'),'SOC_RETURN_MISSING')
        return source
    variant=validate_ram_return(node,resolved=True);click=variant=='click'
    # The library already resolved and verified the hashed top-level probe ABI.
    # Convert this owner's local definitions for the closed RTL-expression audit.
    refs=''.join('`define ref_'+node['module']+'_ca_p_'+str(len(e['id']))+'_'+e['id']+' '+e['rtl_path'].rsplit('.',1)[1]+'\n'
        for e in node['endpoints'])
    record=validate_ram_return_rtl(node,(directory/(node['module']+'.sv')).read_text(),refs,resolved=True)
    e={x['id']:x['rtl_path'] for x in node['endpoints']}
    # Replace the library's flat-domain assumption only for the closed list
    # of application-lifetime cells, with the exact qualified-reset equation.
    for cell in node['primitives']:
        if cell['reset']!='presentation_reset':continue
        pin=cell['rtl_path']+'.reset';app=e['presentation_reset']
        old=f'if ({pin} !== {app} || {app} !== {node["rtl_path"]}.reset) $fatal(1, "RESET_BINDING_MISMATCH");'
        new=f'if ({pin} !== {app} || {app} !== ({e["reset"]} | {e["application_reset"]})) $fatal(1, "RESET_BINDING_MISMATCH");'
        require(source.count(old)==1,'RESET_PROBE_SHAPE:'+cell['id'])
        source=source.replace(old,new)
    pairs=[(e['response_data']+"[0]","1'b0")]
    constants=[(e['response_data'],33,0)]
    if not standalone:
        require(top in ('FourPhaseSoc','ClickSoc'),'SOC_TOP')
        require({'ram_access','ram_source','completion'}<=children.keys() and 'ram_publication_bridge' not in children,
            'SOC_INVENTORY')
        access=children['ram_access'];owner=children['ram_source'];completion=children['completion']
        require(re.fullmatch(r'RamAccess(?:_[0-9]+)?',access['module']),'ACCESS_OWNER')
        subs={c['id']:c['contract'] for c in access['children']}
        require(set(subs)=={'native','command_bridge','capture_receipt'} |
            {f'byte_{kind}_{n}' for kind in ('request','reply') for n in range(4)},'ACCESS_CHILDREN')
        cap=subs['capture_receipt'];require(re.fullmatch(('Click' if click else 'FourPhase')+r'RamCaptureReceipt(?:_[0-9]+)?',cap['module']),'RECEIPT_OWNER')
        endpoints=lambda n:{x['id']:x['rtl_path'] for x in n['endpoints']}
        a,o,c,r=endpoints(access),endpoints(owner),endpoints(completion),endpoints(cap)
        record['capture_receipt']=validate_ram_access(access,directory,scopes)
        pairs += record['capture_receipt']['bindings']
        pairs += [(e['reset'],top+'.reset'),(e['application_reset'],presentation_reset(manifest)),
            (a['reset'],top+'.reset'),(access['rtl_path']+'.clock',validated_service_clock(root,directory)),
            (e['eligible'],o['eligible']),(e['idle'],a['return_idle']),
            (o['word_drained'],'('+a['effects_drained']+' && '+e['presentation_settled']+')'),
            (e['capture_request'],a['capture_request']),(e['capture_acknowledge'],a['capture_acknowledge']),
            (a['capture_request'],r['request']),(a['capture_acknowledge'],r['acknowledge']),
            (a['active'],r['accept'])]
        for field in ('request','data','acknowledge'):
            pairs += [(e['word_'+field],a['word_'+field]),(e['publication_'+field],o['publication_'+field]),
                (e['response_'+field],c['ram_'+field])]
        record['error_alias_closure']=close_error_aliases(node,completion,top,scopes,directory)
        constants += [(c['ram_data'],33,0),(c['result_sources'],112 if click else 103,9 if click else 0)]
        # These are literal aliases of the validated constant error leaf, never
        # generic storage masks. Dynamic RAM bits and every other bit stay active.
        pairs += [(c['ram_data']+'[0]',e['response_data']+'[0]'),
            (c['result_sources']+('[9]' if click else '[0]'),e['response_data']+'[0]')]
        record['integration']=dict(top=top,access=access['rtl_path'],completion=completion['rtl_path'],
            source=owner['rtl_path'],receipt=cap['rtl_path'],bindings=pairs)
    require(source.count('task check; begin')==1,'PROBE_SHAPE')
    checks='\n'.join(f'if ({a} !== {b}) $fatal(1,"RAM_RETURN_BOUNDARY:{a}");' for a,b in pairs)
    for endpoint,width,bit in constants:
        require(any(x['rtl_path']==endpoint and x['width']==width for n in (node,children.get('completion',{}))
            for x in n.get('endpoints',[])),'CONSTANT_SCHEMA')
    if literal_obligations is None:
        source=apply_return_literal_obligations(source,constants)
    else:
        literal_obligations.extend(constants)
    (directory/'ram-return-reset-boundary.json').write_text(json.dumps(record,indent=2)+'\n')
    return source.replace('task check; begin','task check; begin\n'+checks)

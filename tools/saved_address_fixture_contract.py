# SPDX-License-Identifier: Apache-2.0
"""Closed saved-address fixture oracle and metadata contract; no execution.

The readable golden templates must be reviewed independently of the Scala generator.
They preserve the entire testbench, including stimulus, task bodies, guards,
fatal statements, initialization, clocks and final pass. Whitespace alone may
change; comments, strings and every non-whitespace token remain bound.
This narrow binding is not a replacement for the full async export checker.
"""
import hashlib
import json
from pathlib import Path
import re

TOP = 'SramSavedAddressFixture'
ASSETS = Path(__file__).resolve().parent / 'fixtures/sram_saved_address'
ASSET_NAMES = ('testbench.sv.in', 'macro-monitor.sv.in', 'root-contract.json')
MACRO = 'gf180mcu_ocd_ip_sram__sram1024x8m8wm1.sv'


def need(ok, why):
    if not ok:
        raise ValueError('SAVED_ADDRESS_CONTRACT_' + why)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(), object_pairs_hook=unique_json)


def shape(value, keys):
    need(type(value) is dict and set(value) == set(keys.split()), 'SCHEMA_FIELDS')


def tokens(text):
    # Preserve strings/comments as whole tokens so whitespace in strings and
    # moving code into a comment cannot masquerade as formatting.
    return re.findall(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/|[A-Za-z_$][\w$]*|\d+|[^\s]', text)


def testbench(capacity):
    need(type(capacity) is int and capacity in (4,12,1024,1028,2048,3072), 'CAPACITY')
    banks = range((capacity + 1023) // 1024)
    kinds = (('macroAddress',9), ('macroData',7), ('macroCen',0), ('macroGwen',0))
    replacements = {
        '@CAPACITY@': str(capacity),
        '@MACRO_DECLARATIONS@': '\n'.join(f'wire [{width}:0] {kind}_{bank};' for kind,width in kinds for bank in banks),
        '@MACRO_CONNECTIONS@': ','.join(f'.{kind}_{bank}({kind}_{bank})' for kind,_ in kinds for bank in banks),
        '@MACRO_MONITORS@': '\n'.join((ASSETS/'macro-monitor.sv.in').read_text().replace('@BANK@',str(bank)) for bank in banks),
        '@MACRO_STOP_CHECKS@': '\n'.join(
            f'if(macroCen_{bank} !== !((phase==1 || phase==2) && {bank}=={(capacity-1)//1024})) '
            f'$fatal(1,"SAVED_ADDRESS_STOP_CEN_{bank}");' for bank in banks),
    }
    result = (ASSETS/'testbench.sv.in').read_text()
    for marker, replacement in replacements.items():
        need(marker in result, 'MISSING_TEMPLATE_MARKER')
        result = result.replace(marker,replacement)
    need(re.search(r'@[A-Z_]+@',result) is None, 'UNRESOLVED_TEMPLATE_MARKER')
    return result


def validate_testbench(text, capacity):
    need(tokens(text) == tokens(testbench(capacity)), 'COMPLETE_TESTBENCH_ORACLE')


def expected_top_ports(capacity):
    declaration = testbench(capacity).split('reg hostLow=',1)[0]
    result = {}
    for kind,high,name in re.findall(r'\b(reg|wire) \[(\d+):0\] (\w+);',declaration):
        result[name] = ('input' if kind=='reg' else 'output', int(high)+1,
                        False, name in ('serviceClock','watchdogClock'))
    need(len(result) == 58 + 4*((capacity+1023)//1024), 'TEMPLATE_PORT_INVENTORY')
    return result


def validate_compile_log(text):
    # The original pinned Icarus run produces only these ten macro typ notices.
    # Empty output is also a clean compile; every other diagnostic fails closed.
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return
    parsed = []
    for line in lines:
        match = re.fullmatch(r'(.+[\\/]' + re.escape(MACRO) + r'):(\d+): warning: Choosing typ expression\.',line)
        need(match is not None, 'BASELINE_COMPILE_DIAGNOSTIC')
        parsed.append((match[1],int(match[2])))
    need(len({path for path,_ in parsed})==1 and [line for _,line in parsed] ==
         [263,264,265,267,268,269,270,271,273,274], 'BASELINE_COMPILE_DIAGNOSTIC_INVENTORY')


def flatten(source, module):
    prefix = '~|' + module + '>'
    need(type(source) is str and source.startswith(prefix), 'PORT_SOURCE')
    return re.sub(r'[.\[]','_',source[len(prefix):]).replace(']','')


def walk(node):
    shape(node, 'rtl_path module reset_domain capacity endpoints channels primitives timing children' +
          (' memories' if 'memories' in node else ''))
    for key in ('endpoints','channels','primitives','timing','children'):
        need(type(node[key]) is list, 'NODE_LIST')
    need(type(node['module']) is str and type(node['rtl_path']) is str and
         type(node['reset_domain']) is str, 'NODE_IDENTITY')
    yield node
    for child in node['children']:
        shape(child,'id contract')
        yield from walk(child['contract'])


def validate_metadata(root, capacity, source):
    document = read_json(root/'contract.json')
    shape(document,'semantic_sha256 manifest')
    manifest = document['manifest']
    shape(manifest,'schema time_unit time_range top toolchain resources rtl_semantic_sha256 probe_abi port_abi design')
    digest = hashlib.sha256(json.dumps(manifest,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    need(document['semantic_sha256']==digest, 'MANIFEST_HASH')
    need(manifest['schema']=='chisel-async-contract-v3' and manifest['time_unit']=='fs' and
         manifest['time_range']=='0..9223372036854775807' and manifest['top']==TOP, 'MANIFEST_SCHEMA_TOP')
    need(manifest['toolchain']==dict(chisel='7.16.0',scala='2.13.18',firtool='1.160.0',options=[
        '-O=release','--strip-fir-debug-info','--lowering-options=disallowPortDeclSharing,disallowLocalVariables']), 'TOOLCHAIN')
    design = manifest['design']
    nodes = list(walk(design))
    root_expected = read_json(ASSETS/'root-contract.json')
    root_actual = {key:design[key] for key in root_expected if key!='child_ids'}
    root_actual['child_ids'] = [child['id'] for child in design['children']]
    need(root_actual==root_expected, 'ROOT_DESIGN_INVENTORY')
    paths = [node['rtl_path'] for node in nodes]
    need(len(paths)==len(set(paths)) and paths[0]==TOP, 'DESIGN_PATH_INVENTORY')
    for key,name in (('port_abi','ports.json'),('probe_abi','ref_'+TOP+'.sv')):
        need(manifest[key]==dict(file=name,sha256=sha(root/name)), 'ABI_HASH_'+key)
    files = [(root/line.strip()).resolve() for line in (root/'filelist.f').read_text().splitlines() if line.strip()]
    need(files and len(files)==len(set(files)) and all(path.is_file() and path.is_relative_to(root) for path in files), 'FILELIST')
    hashes = {}
    resource_names = {Path(name).name for name in manifest['resources']}
    for path in files:
        normalized = '\n'.join(line.split('\t//',1)[0].rstrip() for line in path.read_text().splitlines()).rstrip()+'\n'
        # ClockedSimulation restores the exact library resource after emission.
        # Its only difference is removal of this fixed generated banner. Both
        # the original resource hash and reconstructed emitted hash must match.
        if path.name in resource_names and not normalized.startswith('// Generated by CIRCT firtool-1.160.0\n'):
            normalized = '// Generated by CIRCT firtool-1.160.0\n' + normalized
        need(path.name not in hashes, 'DUPLICATE_RTL_BASENAME')
        hashes[path.name] = hashlib.sha256(normalized.encode()).hexdigest()
    need(manifest['rtl_semantic_sha256']==hashes, 'RTL_SEMANTIC_HASHES')
    resources = {primitive['resource'] for node in nodes for primitive in node['primitives']}
    need(resources and set(manifest['resources'])==resources, 'RESOURCE_INVENTORY')
    for name,digest in manifest['resources'].items():
        path = root/Path(name).name
        text = re.sub(r'^// Generated by CIRCT[^\n]*\n','',path.read_text()).rstrip()+'\n'
        need(path.resolve() in files and hashlib.sha256(text.encode()).hexdigest()==digest, 'RESOURCE_HASH')
    abi = read_json(root/'ports.json')
    shape(abi,'schema top nodes')
    need(abi['schema']=='chisel-async-port-abi-v2' and abi['top']==TOP and type(abi['nodes']) is list, 'PORT_SCHEMA_TOP')
    abi_paths = [node['rtl_path'] for node in abi['nodes']]
    need(len(abi_paths)==len(set(abi_paths)) and set(abi_paths)==set(paths), 'PORT_NODE_INVENTORY')
    design_by_path = {node['rtl_path']:node for node in nodes}
    for node in abi['nodes']:
        shape(node,'rtl_path module ports channels')
        need(node['module']==design_by_path[node['rtl_path']]['module'] and type(node['ports']) is list and
             type(node['channels']) is list, 'PORT_NODE')
        ports = {}
        for port in node['ports']:
            shape(port,'source width signed direction clock')
            need(type(port['width']) is int and port['width']>0 and type(port['signed']) is bool and
                 type(port['clock']) is bool and port['direction'] in ('input','output'), 'PORT_SHAPE')
            name = flatten(port['source'],node['module'])
            need(name not in ports, 'DUPLICATE_PORT')
            ports[name] = (port['direction'],port['width'],port['signed'],port['clock'])
        for channel in node['channels']:
            shape(channel,'source protocol')
            flatten(channel['source'],node['module'])
            need(channel['protocol'] in ('four-phase-bundled-v1','two-phase-bundled-v1','decoupled-v1'), 'PORT_CHANNEL')
        if node['rtl_path']==TOP:
            need(ports==expected_top_ports(capacity), 'TOP_PORT_INVENTORY')
            need(node['channels']==[dict(source='~|'+TOP+'>'+name,protocol='decoupled-v1')
                                    for name in ('request','response')], 'TOP_PORT_CHANNELS')
    head = re.sub(r'//[^\n]*','',source.split(');',1)[0]+');')
    actual = re.findall(r'\b(input|output)\s+(?:wire\s+)?(?:\[(\d+):0\]\s*)?(\w+)\s*[,\)]',head)
    actual_ports = {name:(direction,int(high)+1 if high else 1) for direction,high,name in actual}
    need(len(actual)==len(actual_ports) and actual_ports==
         {name:attributes[:2] for name,attributes in expected_top_ports(capacity).items()}, 'ACTUAL_TOP_PORT_INVENTORY')
    return dict(contract_semantic_sha256=digest, nodes=len(nodes), top_ports=len(actual_ports))

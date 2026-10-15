# SPDX-License-Identifier: Apache-2.0
"""Fail-closed source, runtime-class, export and fixed-model binding for the experiment."""
from pathlib import Path
import hashlib
import json
import re
import zipfile

MACRO = 'gf180mcu_ocd_ip_sram__sram1024x8m8wm1'
SOURCE_FILES = (
    'build.sbt',
    'designs/four-phase-bd/src/main/scala/riscay/bd/experimental/FourPhaseMacroByteOwner.scala',
    'designs/two-phase-click/src/main/scala/riscay/click/experimental/ClickMacroByteOwner.scala',
    'soc/src/main/scala/riscay/soc/experimental/MacroByteSchema.scala',
    'soc/src/main/scala/riscay/soc/Sram.scala',
    'soc/sram-lock.json',
    f'soc/src/main/resources/riscay/sram/{MACRO}.v',
    f'soc/src/main/resources/riscay/sram/{MACRO}.blackbox.v',
    'verification/src/test/scala/riscay/MacroByteFixtures.scala',
    'verification/src/test/scala/riscay/AsyncMacroByteOwnerSpec.scala',
    'verification/src/test/resources/riscay/macro-byte/ByteOwnerBench.sv.in',
    'verification/src/test/resources/riscay/macro-byte/PinAperture.sv',
    'tools/check_macro_byte_owner.py',
    'tools/macro_byte_source_binding.py',
)
CLASS_SOURCES = {
    'riscay.bd.experimental.FourPhaseMacroByteOwner': SOURCE_FILES[1],
    'riscay.click.experimental.ClickMacroByteOwner': SOURCE_FILES[2],
    'riscay.soc.experimental.MacroBytePins': SOURCE_FILES[3],
    'riscay.soc.experimental.MacroByteObservations': SOURCE_FILES[3],
    'riscay.soc.experimental.ByteModelTiming': SOURCE_FILES[3],
    'riscay.soc.Gf180Sram1KiB': SOURCE_FILES[4],
    'riscay.soc.Gf180Sram1KiB$$anon$1': SOURCE_FILES[4],
    'riscay.soc.SramByteRequest': SOURCE_FILES[4],
    'riscay.soc.SramInventory': SOURCE_FILES[4],
    'riscay.soc.SramInventory$': SOURCE_FILES[4],
    'riscay.FourPhaseMacroByteFixture': SOURCE_FILES[8],
    'riscay.ClickMacroByteFixture': SOURCE_FILES[8],
    'riscay.MacroByteCohort$': SOURCE_FILES[8],
    'riscay.EmitMacroByteFixtures$': SOURCE_FILES[8],
    'riscay.AsyncMacroByteOwnerSpec': SOURCE_FILES[9],
}
# Explicitly used project families from Sram.scala, including the macro's FlatIO
# anonymous Bundle and the inventory object's Scala module/forwarder pair.
SRAM_CLASS_FAMILIES = ('Gf180Sram1KiB', 'SramByteRequest', 'SramInventory')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def require(condition, reason):
    if not condition:
        raise ValueError('MACRO_BYTE_BINDING:' + reason)


def strip_comments(text):
    # Preserve strings so comment-looking text cannot erase executable tokens.
    return re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/',
                  lambda m: m[0] if m[0].startswith('"') else ' ', text)


def close_paren(text, start):
    require(start < len(text) and text[start] == '(', 'RTL_EXPECTED_PAREN')
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i
    require(False, 'RTL_UNCLOSED_PAREN')


def root_instances(text, module):
    """Parse the deliberately small firtool wire/assign/direct-instance dialect.

    Unknown syntax fails closed. This is not a general SystemVerilog parser;
    generated procedural logic, generate blocks, escaped names, compiler
    directives, extra modules and instance arrays require explicit review.
    """
    text = strip_comments(text).strip()
    require(not re.search(r'\b(?:always\w*|initial|final|reg|logic|event)\b', text),
            'ORDINARY_STORAGE_IN_ROOT:' + module)
    require(not any(x in text for x in ('`', '\\', '"', '(*')), 'RTL_UNSUPPORTED_SYNTAX:' + module)
    header = re.match(r'module\s+' + re.escape(module) + r'\s*\(', text)
    require(header is not None, 'RTL_ROOT_MODULE:' + module)
    end = close_paren(text, header.end()-1)
    require(text[end+1:].lstrip().startswith(';'), 'RTL_ROOT_HEADER:' + module)
    body = text[end+1:].lstrip()[1:].strip()
    require(body.endswith('endmodule') and len(re.findall(r'\bendmodule\b', body)) == 1,
            'RTL_ROOT_MODULE_SET:' + module)
    body = body[:-len('endmodule')].strip()
    require(not re.search(r'\bmodule\b', body), 'RTL_ROOT_MODULE_SET:' + module)
    require(not body or body.endswith(';'), 'RTL_STATEMENT_END:' + module)
    instances = {}
    for statement in body.split(';'):
        s = statement.strip()
        if not s:
            continue
        if re.match(r'(?:wire|assign)\s', s):
            # A continuous net declaration/assignment has no nested statements.
            # Disallow procedural and hierarchy syntax even if put after wire.
            require(not re.search(r'\b(?:begin|end|generate|endgenerate|function|task|module)\b', s),
                    'RTL_UNSUPPORTED_STATEMENT:' + module)
            continue
        model = re.match(r'([A-Za-z_][A-Za-z_0-9$]*)\s+', s)
        require(model is not None, 'RTL_UNSUPPORTED_STATEMENT:' + module)
        rest = s[model.end():].lstrip()
        if rest.startswith('#'):
            rest = rest[1:].lstrip()
            end = close_paren(rest, 0)
            rest = rest[end+1:].lstrip()
        instance = re.match(r'([A-Za-z_][A-Za-z_0-9$]*)\s*\(', rest)
        require(instance is not None, 'RTL_UNSUPPORTED_INSTANCE:' + module)
        end = close_paren(rest, instance.end()-1)
        require(not rest[end+1:].strip(), 'RTL_UNSUPPORTED_INSTANCE_TAIL:' + module)
        name = instance[1]
        require(name not in instances, 'RTL_DUPLICATE_INSTANCE:' + module + '.' + name)
        instances[name] = model[1]
    return instances


def verify_rtl_inventory(contract, sources, filelist):
    """Bind actual compiled roots to the contract and fixed public resources.

    verify_cohort separately checks every resource against its resolved library
    JAR and the fixed macro against the pinned assets. No metadata exemption is
    granted to an extra actual module/instance or ordinary storage in either root.
    """
    meta = contract['manifest']; top = meta['top']; design = meta['design']
    require(design['module'] == top and design['rtl_path'] == top and not design['primitives'],
            'FIXTURE_CONTRACT_ROOT')
    require(len(design['children']) == 1 and design['children'][0]['id'] == 'byte_owner',
            'FIXTURE_CONTRACT_CHILDREN')
    owner = design['children'][0]['contract']; owner_name = owner['module']
    owner_path = top + '.ca_child_byte_owner'
    require(owner['rtl_path'] == owner_path and not owner['children'], 'OWNER_CONTRACT_PATH')
    expected = {}
    resources = {}
    for primitive in owner['primitives']:
        path = primitive['rtl_path'].split('.')
        require('.'.join(path[:-1]) == owner_path, 'PRIMITIVE_NOT_DIRECT_CHILD:' + primitive['id'])
        require(path[-1] not in expected, 'DUPLICATE_PRIMITIVE_PATH')
        expected[path[-1]] = primitive['model']
        resource = 'chiselasync/sv/' + primitive['model'] + '.sv'
        require(primitive['resource'] == resource, 'PRIMITIVE_RESOURCE_TYPE:' + primitive['id'])
        resources[resource] = primitive['model']
    require(set(resources) == set(meta['resources']), 'EXACT_PUBLIC_RESOURCE_SET')
    expected_files = {top+'.sv', owner_name+'.sv', MACRO+'.sv'} | {Path(x).name for x in resources}
    require(set(sources) == expected_files, 'EXACT_COMPILED_MODULE_FILES')
    listed = [x.strip().replace('\\', '/') for x in filelist.splitlines() if x.strip()]
    require(len(listed) == len(expected_files) and len({Path(x).name for x in listed}) == len(listed)
            and set(listed) <= expected_files | {'./'+x for x in expected_files}
            and {Path(x).name for x in listed} == expected_files, 'EXACT_COMPILED_FILELIST')
    for resource, model in resources.items():
        modules = re.findall(r'\bmodule\s+([A-Za-z_][A-Za-z_0-9$]*)', strip_comments(sources[Path(resource).name]))
        require(modules == [model], 'PUBLIC_RESOURCE_MODULE_TYPE:' + model)
    # Both fixed branches exist in the exact export, selected by SYNTHESIS.
    # Their bytes are validated by verify_cohort; no other module is permitted.
    macros = re.findall(r'\bmodule\s+([A-Za-z_][A-Za-z_0-9$]*)', strip_comments(sources[MACRO+'.sv']))
    require(macros == [MACRO, MACRO], 'FIXED_MACRO_MODULE_SET')
    actual_owner = root_instances(sources[owner_name+'.sv'], owner_name)
    require(actual_owner == expected, 'EXACT_OWNER_INSTANCE_GRAPH')
    actual_fixture = root_instances(sources[top+'.sv'], top)
    fixture_expected = {'ca_child_byte_owner': owner_name, 'fixed_macro': MACRO}
    require(actual_fixture == fixture_expected, 'EXACT_FIXTURE_INSTANCE_GRAPH')
    return {'owner': actual_owner, 'fixture': actual_fixture, 'compiled_files': sorted(expected_files)}


def verify_capture(export, root):
    export, root = Path(export).resolve(), Path(root).resolve()
    manifest_path = export/'source-manifest.json'
    require(manifest_path.is_file(), 'MISSING_SOURCE_MANIFEST')
    m = json.loads(manifest_path.read_text())
    require(m['schema'] == 'riscay-experimental-macro-byte-cohort-v1', 'SCHEMA')
    require(m['status'] == 'COMPLETE', 'INCOMPLETE_EMISSION')
    require(m['started_ms'] <= m['finished_ms'], 'EMISSION_ORDER')
    require(set(m['sources']) == set(SOURCE_FILES), 'SOURCE_INVENTORY')
    bound = {str(manifest_path): sha(manifest_path)}
    for relative, value in m['sources'].items():
        p = root/relative
        require(p.is_file() and sha(p) == value['sha256'], 'SOURCE_CHANGED:' + relative)
        require(p.stat().st_mtime_ns//1000000 == value['modified_ms'], 'SOURCE_TIMESTAMP_CHANGED:' + relative)
        require(value['modified_ms'] <= m['started_ms'], 'SOURCE_AFTER_EMISSION_START:' + relative)
        bound[str(p)] = sha(p)
    classes = m['runtime_classes']
    names = [x['name'] for x in classes]
    require(len(names) == len(set(names)) and set(CLASS_SOURCES) <= set(names), 'CLASS_INVENTORY')
    for c in classes:
        name = c['name']; canonical = name if name in CLASS_SOURCES else name.removesuffix('$')
        require(canonical in CLASS_SOURCES and c['source'] == CLASS_SOURCES[canonical], 'CLASS_SOURCE:' + name)
        p = Path(c['path']).resolve()
        require(p.is_relative_to(root), 'CLASS_OUTSIDE_REPOSITORY:' + name)
        require(p.as_posix().endswith('/' + name.replace('.', '/') + '.class'), 'CLASS_PATH:' + name)
        require(p.is_file() and sha(p) == c['sha256'], 'COMPILED_CLASS_CHANGED:' + name)
        require(p.stat().st_mtime_ns//1000000 == c['modified_ms'], 'CLASS_TIMESTAMP_CHANGED:' + name)
        require(m['sources'][c['source']]['modified_ms'] <= c['modified_ms'] <= m['started_ms'],
                'CLASS_SOURCE_ORDER:' + name)
        bound[str(p)] = sha(p)
    for family in SRAM_CLASS_FAMILIES:
        primary = next(c for c in classes if c['name'] == 'riscay.soc.'+family)
        folder = Path(primary['path']).resolve().parent
        actual = {p.stem for p in folder.glob(family+'*.class')
                  if p.stem == family or p.stem.startswith(family+'$')}
        recorded = {c['name'].rsplit('.', 1)[1] for c in classes
                    if c['name'] == 'riscay.soc.'+family or c['name'].startswith('riscay.soc.'+family+'$')}
        require(all(Path(c['path']).resolve().parent == folder for c in classes
                    if c['name'].rsplit('.', 1)[1] in recorded), 'SRAM_CLASS_FAMILY_LOCATION:' + family)
        require(actual == recorded, 'SRAM_CLASS_FAMILY_INVENTORY:' + family)
    jar = Path(m['library_jar']['path']).resolve()
    require(jar.is_file() and sha(jar) == m['library_jar']['sha256'], 'LIBRARY_JAR_CHANGED')
    require(set(m['exports']) == {'bd', 'click'}, 'EXPORT_INVENTORY')
    bound[str(jar)] = sha(jar)
    return m, bound


def verify_cohort(export, root):
    export, root = Path(export).resolve(), Path(root).resolve()
    m, bound = verify_capture(export, root)
    lock = json.loads((root/'soc/sram-lock.json').read_text())
    require(lock['macro'] == MACRO, 'FIXED_MACRO_NAME')
    resources = root/'soc/src/main/resources/riscay/sram'
    for suffix in ('.v', '.blackbox.v'):
        require(sha(resources/(MACRO+suffix)) == lock['assets'][MACRO+suffix]['sha256'], 'FIXED_MACRO_LOCK:' + suffix)
    with zipfile.ZipFile(m['library_jar']['path']) as archive:
        for variant in ('bd', 'click'):
            folder = export/variant
            c = json.loads((folder/'contract.json').read_text()); meta = c['manifest']
            require(c['semantic_sha256'] == m['exports'][variant], 'EXPORT_CAPTURE:' + variant)
            require(digest(json.dumps(meta, separators=(',', ':'), ensure_ascii=False)) == c['semantic_sha256'], 'MANIFEST_DIGEST')
            files = [x.strip().replace('\\', '/') for x in (folder/'filelist.f').read_text().splitlines() if x.strip()]
            require(len(files) == len(set(files)), 'DUPLICATE_FILELIST')
            verify_rtl_inventory(c, {p.name:p.read_text() for p in folder.glob('*.sv')
                                     if p.name != 'ref_'+meta['top']+'.sv'}, (folder/'filelist.f').read_text())
            require({Path(x).name for x in files} == set(meta['rtl_semantic_sha256']), 'RTL_FILELIST')
            for name in files:
                p = (folder/name).resolve()
                require(p.is_relative_to(folder), 'RTL_OUTSIDE_EXPORT')
                normalized = '\n'.join(line.split('\t//', 1)[0].rstrip() for line in p.read_text().splitlines()).rstrip()+'\n'
                require(digest(normalized) == meta['rtl_semantic_sha256'][p.name], 'RTL_CHANGED:' + p.name)
            for name, expected in meta['resources'].items():
                normalized = archive.read(name).decode().replace('\r\n', '\n').rstrip()+'\n'
                require(digest(normalized) == expected, 'RESOURCE_DIGEST:' + name)
                header, emitted = (folder/Path(name).name).read_text().split('\n', 1)
                require(header == '// Generated by CIRCT firtool-'+meta['toolchain']['firtool'], 'RESOURCE_HEADER')
                require(emitted.rstrip()+'\n' == normalized, 'RESOURCE_BYTES:' + name)
            require(sha(folder/'ports.json') == meta['port_abi']['sha256'], 'PORT_ABI')
            require(sha(folder/meta['probe_abi']['file']) == meta['probe_abi']['sha256'], 'PROBE_ABI')
            original = (resources/(MACRO+'.v')).read_text()
            require(original.count("mem[i] = 8'd0;") == 1, 'FIXED_INITIALIZER')
            expected = '`ifdef SYNTHESIS\n'+(resources/(MACRO+'.blackbox.v')).read_text()+'\n`else\n'+original.replace("mem[i] = 8'd0;", "mem[i] = 8'bx;")+'\n`endif\n\n'
            header, emitted = (folder/(MACRO+'.sv')).read_text().split('\n', 1)
            require(header == '// Generated by CIRCT firtool-'+meta['toolchain']['firtool'] and emitted == expected,
                    'FIXED_MACRO_EXPORT')
            for p in folder.rglob('*'):
                if p.is_file():
                    bound[str(p)] = sha(p)
    return m, bound

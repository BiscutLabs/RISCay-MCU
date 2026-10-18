# SPDX-License-Identifier: Apache-2.0
"""Consume the library's generation audit; no MCU Verilog/probe rewriting.

Structural acceptance is distinct from the library's dynamic export checker.
Mapped graph preservation, keeper cuts and unused added cells are checked by
the physical flow; this file never labels unperformed physical checks as passes.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path


def require(ok, reason):
    if not ok:
        raise ValueError('EXPORT_STRUCTURE_' + reason)


def nodes(node):
    yield node
    for child in node['children']:
        yield from nodes(child['contract'])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inside(root, name):
    path = (root / name.replace('\\', '/')).resolve()
    require(path.is_relative_to(root.resolve()), 'FILE_OUTSIDE_EXPORT')
    return path


def validate(directory):
    root = Path(directory)
    document = json.loads((root/'contract.json').read_text(encoding='utf-8'))
    manifest = document['manifest']
    semantic = digest(json.dumps(manifest, separators=(',', ':'), ensure_ascii=False).encode())
    require(semantic == document['semantic_sha256'], 'CONTRACT_CHANGED')
    report = json.loads((root/'structure.json').read_text(encoding='utf-8'))
    require(report['schema'] == 'chisel-async-structure-v1' and report['status'] == 'pass', 'GENERATION_AUDIT')
    require(report['top'] == manifest['top'] and report['contract_semantic_sha256'] == semantic, 'AUDIT_BINDING')
    require(report['hw_sha256'] == digest((root/'design.hw.mlir').read_bytes()), 'HW_CHANGED')
    inventory = [p['rtl_path'] for n in nodes(manifest['design']) for p in n['primitives']]
    require(len(inventory) == len(set(inventory)) and set(report['primitive_paths']) == set(inventory), 'PRIMITIVE_INVENTORY')
    require(set(report['owner_modules']) == {n['rtl_path'] for n in nodes(manifest['design'])}, 'OWNER_INVENTORY')
    files = [inside(root, line.strip()) for line in (root/'filelist.f').read_text().splitlines() if line.strip()]
    require(len({p.name for p in files}) == len(files) and {p.name for p in files} == set(manifest['rtl_semantic_sha256']), 'RTL_INVENTORY')
    for path in files:
        lines = path.read_text(encoding='utf-8').splitlines()
        normalized = '\n'.join(line.split('\t//', 1)[0].rstrip() for line in lines).rstrip()+'\n'
        require(digest(normalized.encode()) == manifest['rtl_semantic_sha256'][path.name], 'RTL_CHANGED:'+path.name)
    abi = manifest['port_abi']
    require(digest(inside(root, abi['file']).read_bytes()) == abi['sha256'], 'PORT_ABI_CHANGED')
    if 'gf180mcu_ocd_ip_sram__sram1024x8m8wm1' in report.get('opaque_external_models',[]):
        from sram_assets import validate_export
        validate_export(root,manifest['toolchain']['firtool'])
    return dict(schema='riscay-export-structure-v1', status='pass', top=manifest['top'],
                primitive_paths=sorted(inventory), owner_modules=report['owner_modules'],
                generation_audit=report,
                scope='generation structure only; chip simulations and mapped timing remain separate',
                physical_checks='pending mapping: full graph/protected primitives, keeper arcs, unused added cells')

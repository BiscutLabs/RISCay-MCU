"""Exact C1e checker-only source succession; never creates a regression receipt.

The maintained bind_execution still validates the original execution/header,
classes, runtime and fixture cohort. This helper validates the separate current
source inventory and old-byte custody; it does not approve any checker run.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ALLOWED = frozenset({
    'tools/check_reset_crossings.py', 'tools/quiescing_receipt_proof.py',
    'tools/gf180_constraints.py',
    'tools/check_quiescing_receipt_controls.py', 'tools/check_quiescing_graph_controls.py',
    'tools/checker_successor.py', 'tools/test_checker_successor.py',
    'tools/quiescing_request_hold_proof.py', 'tools/test_quiescing_request_hold.py',
    'tools/test_quiescing_handoff.py',
    'tools/check_quiescing_handoff_controls.py',
    'tools/quiescing_gate_control.py', 'tools/test_quiescing_gate_control.py',
    'tools/check_frame_integration.py', 'tools/test_frame_assertion_bind.py',
})
ADDITIONS = frozenset({'tools/checker_successor.py', 'tools/test_checker_successor.py',
    'tools/quiescing_request_hold_proof.py', 'tools/test_quiescing_request_hold.py',
    'tools/test_quiescing_handoff.py', 'tools/check_quiescing_handoff_controls.py',
    'tools/test_frame_assertion_bind.py'})

def need(ok, why):
    if not ok:
        raise ValueError('CHECKER_SUCCESSOR_' + why)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def read(path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            need(key not in out, 'DUPLICATE_JSON_KEY')
            out[key] = value
        return out
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique)

def inventory(root):
    listing = subprocess.check_output(['git', 'ls-files', '--cached', '--others',
        '--exclude-standard', '-z'], cwd=root, text=True, timeout=30)
    return {name:sha(root/name) for name in listing.split('\0') if name and (root/name).is_file()}


def source_scope(name, archived, current):
    """Preserve functional code outside the two exact checker repair scopes."""
    if name == 'tools/quiescing_gate_control.py':
        changed, added = {'prove_graph'}, set()
    elif name == 'tools/check_frame_integration.py':
        changed, added = {'assertion_wrapper_policy'}, {'coordinated_request_assertion_model'}
    else:
        return
    old = ast.parse(Path(archived).read_text(encoding='utf-8'))
    new = ast.parse(Path(current).read_text(encoding='utf-8'))
    def count(tree, function):
        return sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function
                   for node in tree.body)
    for function in changed:
        need(count(old, function) == count(new, function) == 1, 'SOURCE_SCOPE_REQUIRED_FUNCTION:'+name)
    for function in added:
        need(count(old, function) == 0 and count(new, function) == 1, 'SOURCE_SCOPE_EXACT_ADDITION:'+name)
    allowed = changed | added
    def protected(tree):
        # Only ordinary top-level definitions are omitted. Async/class aliases,
        # assignments, imports, constants and all other complete bodies stay exact.
        tree.body = [node for node in tree.body if not (type(node) is ast.FunctionDef and node.name in allowed)]
        return ast.dump(tree, include_attributes=False)
    need(protected(old) == protected(new), 'SOURCE_SCOPE_PROTECTED_AST:'+name)

def bind_sources(execution, root, checker_successor=None):
    """Return current sources, separate records and copy-root metadata.

    Original execution is read/compared, never edited or substituted. Old changed
    bytes are rehashed in explicit archives; all other original bytes stay live.
    Copied-export manifest identity is checked here; strict and graph binders
    additionally rehash the complete emitted files and failed strict evidence.
    """
    root = Path(root).resolve()
    original = execution['sources_sha256']
    if checker_successor is None:
        need(inventory(root) == original, 'ORIGINAL_COMPLETE_SOURCE_INVENTORY')
        return dict(current_sources_sha256=dict(original), records={}, exports_root=None,
                    checker_successor=None)
    path = Path(checker_successor).resolve()
    need(path.is_relative_to(root/'build'), 'MANIFEST_LOCATION')
    spec = read(path)
    need(set(spec) == {'schema','status','original_execution','copied_exports_receipt',
         'delta','current_sources_sha256','review_inputs_sha256'}, 'MANIFEST_FIELDS')
    need(spec['schema'] == 'riscay-c1e-checker-successor-v1' and
         spec['status'] == 'BOUND_CHECKER_ONLY_DELTA_REQUIRES_DOWNSTREAM_REVIEW', 'SCHEMA_STATUS')
    records = {str(path):sha(path)}
    def bind(record):
        need(type(record) is dict and set(record) == {'path','sha256'}, 'FILE_RECORD')
        p = Path(record['path'])
        need(p.is_absolute() and str(p.resolve()) == str(p), 'CANONICAL_FILE')
        need(re.fullmatch('[0-9a-f]{64}', record['sha256']) is not None and
             sha(p) == record['sha256'], 'FILE_HASH:'+str(p))
        need(str(p) not in records or records[str(p)] == record['sha256'], 'RECORD_CONFLICT')
        records[str(p)] = record['sha256']
        return p
    old_path = bind(spec['original_execution'])
    need(old_path == root/'build/async-quiescing-receipt-production-r2/execution.json' and
         read(old_path) == execution, 'ORIGINAL_EXECUTION_IDENTITY')
    copy_path = bind(spec['copied_exports_receipt'])
    copies = read(copy_path)
    need(copy_path.name == 'copy-receipt.json' and copy_path.parent.is_relative_to(root/'build')
         and copy_path.parent != old_path.parent, 'COPIED_EXPORT_ROOT')
    need(copies['status'] == 'BYTE_IDENTICAL_EXPORTED_INPUT_COPIES_ONLY' and
         copies['original_execution'] == str(old_path) and
         copies['original_execution_sha256'] == spec['original_execution']['sha256'] and
         copies['exports_sha256'] == execution['exports_sha256'] and
         copies['retained_failed_strict_sha256'], 'COPIED_EXPORT_ANCESTRY')
    delta = spec['delta']
    need(type(delta) is dict and delta and set(delta) <= ALLOWED, 'EXACT_CHECKER_ALLOWLIST')
    need(ADDITIONS <= set(delta), 'EXPLICIT_NEW_HELPER_AND_TEST')
    current = dict(original)
    archives = set()
    runtime = {Path(p).resolve() for p in execution['tool_inputs_sha256']}
    for name, change in delta.items():
        need(set(change) == {'before_sha256','after_sha256','original_archive'}, 'DELTA_FIELDS')
        before, after = change['before_sha256'], change['after_sha256']
        need(before == original.get(name) and before != after and
             type(after) is str and re.fullmatch('[0-9a-f]{64}', after), 'EXACT_OLD_NEW_HASH:'+name)
        need((root/name).resolve() not in runtime, 'FUNCTIONAL_RUNTIME_MUST_NOT_CHANGE')
        if before is None:
            need(name in ADDITIONS and change['original_archive'] is None, 'EXPLICIT_ADDITION')
        else:
            archived = bind(change['original_archive'])
            need(archived.is_relative_to(root/'build') and archived not in archives and
                 archived != (root/name).resolve() and records[str(archived)] == before,
                 'ORIGINAL_SOURCE_ARCHIVE:'+name)
            archives.add(archived)
        need(sha(root/name) == after, 'CURRENT_CHECKER_HASH:'+name)
        if before is not None:
            source_scope(name, archived, root/name)
        records[str((root/name).resolve())] = after
        current[name] = after
    need(spec['current_sources_sha256'] == current and inventory(root) == current,
         'COMPLETE_CURRENT_SOURCE_INVENTORY')
    reviews = spec['review_inputs_sha256']
    need(type(reviews) is dict and reviews, 'EXPLICIT_REVIEW_INPUTS')
    for name, digest in reviews.items():
        bind(dict(path=name, sha256=digest))
    return dict(current_sources_sha256=current, records=records,
        exports_root=str(copy_path.parent), checker_successor=dict(path=str(path),sha256=sha(path)),
        copied_exports_receipt=dict(path=str(copy_path),sha256=sha(copy_path)))

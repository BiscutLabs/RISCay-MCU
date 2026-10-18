# SPDX-License-Identifier: Apache-2.0
"""Pure resource controls using the existing library source, without imports.

CHISEL_ASYNC_ROOT selects the same development checkout required by check_export;
the default is the sibling chisel-async repository. No external Python package,
HDL compiler, simulator, sbt, mapper or STA process is used.
"""
import ast
import copy
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest import mock

import check_probe_budget as budget


LIBRARY = Path(os.environ.get('CHISEL_ASYNC_ROOT', str(Path(__file__).resolve().parents[2] / 'chisel-async')))
SOURCE = (LIBRARY / 'tools/check_export.py').read_text(encoding='utf-8')


def existing_functions():
    selected = {'nodes', 'source_path', 'paired_probe_values', 'probe_source'}
    body = [node for node in ast.parse(SOURCE).body
            if isinstance(node, ast.FunctionDef) and node.name in selected]
    if len(body) != len(selected):
        raise AssertionError('MISSING_ACTUAL_LIBRARY_FUNCTION')
    def require(value, diagnostic):
        if not value:
            raise ValueError(diagnostic)
    namespace = dict(require=require, re=re, IDENT=r'[A-Za-z_][A-Za-z0-9_$]*',
                     export_extensions=SimpleNamespace(equality_statements=lambda _: []))
    exec(compile(ast.Module(body=body, type_ignores=[]), str(LIBRARY/'tools/check_export.py'), 'exec'), namespace)
    return namespace


REFERENCE = existing_functions()


def fixture(widths):
    node = dict(rtl_path='Toy', module='Toy', children=[], channels=[], timing=[], primitives=[],
                endpoints=[dict(id='reset', rtl_path='Toy.reset', source='~|Toy>reset', width=1)])
    scope = dict(ports={f'i{index}': dict(direction='input', width=width)
                       for index, width in enumerate(widths)}, registers={}, nets={'reset': 1})
    return dict(top='Toy', design=node), {'Toy': scope}


class ProbeBudgetTest(unittest.TestCase):
    def test_known_source_accepts_comments_and_docstring_only_changes(self):
        budget.require_known_algorithm(SOURCE)
        tree = ast.parse(SOURCE)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in budget.ALGORITHM_SHA256:
                if isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
                    node.body[0].value.value = 'Documentation only'
        budget.require_known_algorithm(ast.unparse(tree) + '\n# comment\n')

    def test_unknown_pairing_or_driver_algorithm_rejected(self):
        for name in budget.ALGORITHM_SHA256:
            for fault in ('body', 'duplicate', 'missing'):
                with self.subTest(name=name, fault=fault):
                    tree = ast.parse(SOURCE)
                    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
                    if fault == 'body':
                        node.body.append(ast.Pass())
                    elif fault == 'duplicate':
                        tree.body.append(copy.deepcopy(node))
                    else:
                        tree.body.remove(node)
                    with self.assertRaisesRegex(ValueError, 'PAIRED_PROBE_UNSUPPORTED_LIBRARY_ALGORITHM'):
                        budget.require_known_algorithm(ast.unparse(ast.fix_missing_locations(tree)))
        for source in ('invalid Python???', None):
            with self.assertRaisesRegex(ValueError, 'PAIRED_PROBE_UNSUPPORTED_LIBRARY_ALGORITHM'):
                budget.require_known_algorithm(source)

    def test_small_overlap_cardinalities_match_actual_generator(self):
        paired = REFERENCE['paired_probe_values']
        for a in (1, 2, 3, 4, 8, 17):
            for b in (1, 2, 3, 4, 8, 17):
                ca, ea = budget.value_counts(a)
                cb, eb = budget.value_counts(b)
                self.assertEqual(ea * cb + ca * eb - ca * cb, len(paired(a, b)), (a, b))

    def test_aggregate_count_and_byte_bound_match_actual_source(self):
        generate = REFERENCE['probe_source']
        for widths in ([], [1], [1, 1], [1, 2, 3], [2, 2, 3, 8], [17, 17, 33]):
            with self.subTest(widths=widths):
                manifest, scopes = fixture(widths)
                estimate = budget.require_paired_probe_budget(manifest, scopes, SOURCE)
                ordinary, base_checks = generate(manifest, scopes)
                paired, all_checks = generate(manifest, scopes, paired=True)
                self.assertEqual(all_checks - base_checks, estimate['extra_mapping_checks'])
                self.assertEqual(len(paired.splitlines()) - len(ordinary.splitlines()), estimate['extra_lines'])
                self.assertLessEqual(len(paired.encode()) - len(ordinary.encode()), estimate['extra_source_bytes_upper_bound'])

    def test_inventory_includes_children_registers_outputs_and_duplicates(self):
        manifest, scopes = fixture([2])
        scopes['Toy']['registers']['i0'] = 2  # Preserve repeated force entries.
        child = dict(rtl_path='Toy.child', module='Child', children=[], channels=[], timing=[],
                     endpoints=[dict(id='reset', rtl_path='Toy.child.reset', source='~|Child>reset', width=1)],
                     primitives=[dict(rtl_path='Toy.child.cell', reset='reset', model='ChiselAsyncEventRegister_v1', ports=[
                         dict(name='d', direction='input', width=3), dict(name='q', direction='output', width=3)])])
        manifest['design']['children'] = [dict(contract=child)]
        scopes['Toy.child'] = dict(ports={'ignored_child_input': dict(direction='input', width=17)},
                                   registers={'state': 1}, nets={'reset': 1})
        expected = [('Toy.i0', 2), ('Toy.i0', 2), ('Toy.child.state', 1), ('Toy.child.cell.q', 3)]
        self.assertEqual(budget.driver_inventory(manifest, scopes), (expected, 2))
        ordinary, count = REFERENCE['probe_source'](manifest, scopes)
        paired, all_count = REFERENCE['probe_source'](manifest, scopes, paired=True)
        estimate = budget.paired_probe_budget(manifest, scopes)
        self.assertEqual(all_count - count, estimate['extra_mapping_checks'])
        self.assertEqual(len(paired.splitlines()) - len(ordinary.splitlines()), estimate['extra_lines'])

    def test_passive_reset_binding_keeps_every_driver_and_paired_sample(self):
        manifest, scopes = fixture([2])
        manifest['design']['primitives'] = [dict(rtl_path='Toy.allowance', reset='reset',
            model='ChiselAsyncPassiveDataAllowance_v1', ports=[
                dict(name='a', direction='input', width=3), dict(name='q', direction='output', width=3)])]
        ordinary, count = REFERENCE['probe_source'](manifest, scopes)
        paired, all_count = REFERENCE['probe_source'](manifest, scopes, paired=True)
        estimate = budget.require_paired_probe_budget(manifest, scopes, SOURCE)
        self.assertEqual(budget.driver_inventory(manifest, scopes)[0], [('Toy.i0',2),('Toy.allowance.q',3)])
        self.assertNotIn('Toy.allowance.reset', ordinary)
        self.assertIn('RESET_BINDING_MISMATCH', ordinary)
        self.assertEqual(all_count-count, estimate['extra_mapping_checks'])
        self.assertEqual(len(paired.splitlines())-len(ordinary.splitlines()),estimate['extra_lines'])
        self.assertLessEqual(len(paired.encode())-len(ordinary.encode()),estimate['extra_source_bytes_upper_bound'])

    def test_huge_width_and_soc_driver_count_fail_without_pair_allocation(self):
        # Fail before testing giant widths if a future implementation starts
        # materializing a width-sized mask or enumerating its individual bits.
        source = ast.parse(Path(budget.__file__).read_text())
        self.assertFalse(any(isinstance(node, (ast.LShift, ast.RShift, ast.Pow))
                             for node in ast.walk(source)))
        for widths in ([10**12, 10**12], [1]*2400, [337]*2400):
            fail = mock.Mock(side_effect=AssertionError('MUST_NOT_ALLOCATE'))
            with mock.patch.dict(REFERENCE, paired_probe_values=fail), mock.patch.object(budget, 'range', fail, create=True):
                manifest, scopes = fixture(widths)
                with self.assertRaisesRegex(ValueError, 'PAIRED_PROBE_RESOURCE_BUDGET_EXCEEDED:') as caught:
                    budget.require_paired_probe_budget(manifest, scopes, SOURCE)
            record = json.loads(str(caught.exception).split(':', 1)[1])
            self.assertEqual(record['driver_count'], len(widths))
            self.assertTrue(record['exceeded'])
            self.assertEqual(record['limits'], budget.LIMITS)

    def test_each_budget_is_enforced_and_exact_limit_is_allowed(self):
        manifest, scopes = fixture([3, 8, 17])
        measured = budget.paired_probe_budget(manifest, scopes)
        for field in budget.LIMITS:
            limits = {key: measured[key] for key in budget.LIMITS}
            with mock.patch.object(budget, 'LIMITS', limits):
                self.assertFalse(budget.require_paired_probe_budget(manifest, scopes, SOURCE)['exceeded'])
            limits[field] -= 1
            with mock.patch.object(budget, 'LIMITS', limits):
                with self.assertRaisesRegex(ValueError, 'PAIRED_PROBE_RESOURCE_BUDGET_EXCEEDED:') as caught:
                    budget.require_paired_probe_budget(manifest, scopes, SOURCE)
                self.assertEqual(json.loads(str(caught.exception).split(':', 1)[1])['exceeded'], [field])

    def test_bad_inventory_is_not_a_zero_work_pass(self):
        for width in (0, -1, True, '8', None):
            with self.assertRaisesRegex(ValueError, 'PAIRED_PROBE_INVALID_INVENTORY:WIDTH'):
                budget.paired_probe_budget(*fixture([width]))
        manifest, scopes = fixture([1])
        manifest['design']['children'].append(dict(contract=manifest['design']))
        with self.assertRaisesRegex(ValueError, 'PAIRED_PROBE_INVALID_INVENTORY:NODE_IDENTITY'):
            budget.paired_probe_budget(manifest, scopes)


if __name__ == '__main__':
    unittest.main()

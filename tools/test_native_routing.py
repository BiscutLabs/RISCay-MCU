# SPDX-License-Identifier: Apache-2.0
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gf180_control_roles import CONTROL, DATA, PASSIVE_MODEL
from gf180_physical import adapter
from native_routing import anchors, generate, read_report


def fixture():
    bindings = []
    for model, params, role in [
        ('ChiselAsyncControlGate_v1', dict(WIDTH=1, OP=0, RESET_VALUE=0, DELAY_FS=10000000), CONTROL),
        ('ChiselAsyncClosingLatch_v1', dict(WIDTH=4, RESET_VALUE=0), None)]:
        cells, requirements = adapter(dict(model=model, parameters=params), 1.404, role=role)
        bindings.append(dict(model=model, cells=cells.cells, requirements=requirements,
                             instances=[model]))
    bindings.append(dict(model=PASSIVE_MODEL, cells=[], requirements=dict(role=DATA), instances=['passive']))
    mapping = dict(bindings=bindings)
    audit = dict(adapter_instances={i: 'soc/'+i for b in bindings for i in b['instances']})
    return mapping, audit


class NativeRouting(unittest.TestCase):
    def test_typed_control_and_capture_includes_internal_delay_excludes_payload(self):
        mapping, audit = fixture()
        rows, passive = anchors(mapping, audit)
        self.assertEqual(passive, ['passive'])
        control = [r for r in rows if 'ControlGate' in r['model']]
        self.assertTrue(any('dlyd' in r['master'] for r in control))
        storage = [r for r in rows if 'ClosingLatch' in r['model']]
        self.assertTrue(any(r['pin'].endswith('/E') for r in storage))
        self.assertFalse(any(r['pin'].endswith(('/D','/Q')) for r in storage))

    def test_missing_duplicate_and_changed_passive_fail(self):
        mapping, audit = fixture()
        del audit['adapter_instances']['passive']
        with self.assertRaisesRegex(ValueError, 'ADAPTER_INVENTORY'): anchors(mapping, audit)
        mapping, audit = fixture()
        mapping['bindings'][0]['instances'] *= 2
        with self.assertRaisesRegex(ValueError, 'ADAPTER_INVENTORY'): anchors(mapping, audit)
        mapping, audit = fixture()
        mapping['bindings'][-1]['cells'] = [dict(name='unexpected')]
        with self.assertRaisesRegex(ValueError, 'PASSIVE_RECIPE'): anchors(mapping, audit)

    def test_generation_and_report_coverage_are_explicitly_unqualified(self):
        mapping, audit = fixture()
        with TemporaryDirectory() as d:
            root = Path(d)
            (root/'mapping.json').write_text(json.dumps(mapping))
            (root/'netlist-audit.json').write_text(json.dumps(audit))
            result = generate(root, root)
            self.assertEqual(result['status'], 'constraints-only')
            self.assertIn('set native_routing_seeds', (root/'native-routing.tcl').read_text())
            pins = [r['pin'] for r in result['anchors']]
            report = ''.join(f'P\t{p}\tnative\n' for p in pins)
            report += 'N\tnative\triscay_native_2s\nL\tMetal2\t560\t1120\nSTATUS\tassigned-unqualified\n'
            (root/'report.tsv').write_text(report)
            self.assertFalse(read_report(root/'report.tsv',pins)['geometric_spacing_qualified'])
            for bad in (report.replace('N\tnative\triscay_native_2s\n',''),
                        report.replace('assigned-unqualified','PASS'),
                        report.replace('560\t1120','560\t0')):
                (root/'report.tsv').write_text(bad)
                with self.assertRaises(ValueError): read_report(root/'report.tsv',pins)


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""Independent negative controls for actual same-event feedback hold evidence."""
from copy import deepcopy
import unittest

import passive_feedback_hold as h


class FeedbackParserTests(unittest.TestCase):
    def setUp(self):
        self.plan = dict(root='root/Z', sources=['src/Q'],
                         targets={'dst/D': {'CLK': 'dst/CLK'}})
        self.pins = ['root/Z', 'src/CLK', 'src/Q', 'dst/D', 'dst/CLK', 'wrong/Q', 'wrong/CLK']
        self.lines = ['PIN\t'+str(i)+'\t'+pin for i, pin in enumerate(self.pins)]
        for edge in ('rise', 'fall'):
            self.lines += [f'HOLD\ts\t3\t{edge}\t2\t0.5\t0.1\t1.2\t0.7',
                           f'PATH\ts\t3\t{edge}\t0\t1\t2\t3',
                           f'CLOCK\ts\t3\t{edge}\t0\t4']
        self.lines += ['FEEDBACK_COMPLETE']

    def parse(self, lines=None):
        return h.parse('\n'.join(self.lines if lines is None else lines), self.plan, ['s'], .2)

    def test_actual_hold_and_named_diagnostic_preserved(self):
        rows, _ = self.parse()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['slack_ns'], .5)
        self.assertAlmostEqual(rows[0]['selected_path_maximum_aperture_diagnostic_ns'], .4)
        self.assertNotIn('conservative_aperture_slack_ns', rows[0])

    def test_each_endpoint_polarity_is_required(self):
        for kind in ('HOLD', 'PATH', 'CLOCK'):
            rows = [r for r in self.lines if not r.startswith(kind+'\ts\t3\tfall')]
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, '^FEEDBACK_PATH_COVERAGE$'):
                self.parse(rows)

    def test_duplicate_rows_rejected(self):
        for kind, code in [('HOLD', 'ROW_BINDING'), ('PATH', 'DUPLICATE_PATH'), ('CLOCK', 'DUPLICATE_CLOCK')]:
            rows = self.lines[:-1]+[next(r for r in self.lines if r.startswith(kind+'\t'))]+self.lines[-1:]
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, '^FEEDBACK_'+code+'$'):
                self.parse(rows)

    def test_wrong_source_or_polarity_rejected(self):
        for old, new in [('\trise\t2\t0.5', '\trise\t5\t0.5'),
                         ('HOLD\ts\t3\trise', 'HOLD\ts\t3\tfall')]:
            with self.subTest(new=new), self.assertRaisesRegex(ValueError, '^FEEDBACK_ROW_BINDING$'):
                self.parse([r.replace(old, new) for r in self.lines])

    def test_capture_and_launch_clock_identities_rejected(self):
        changes = [('CLOCK\ts\t3\trise\t0\t4', 'CLOCK\ts\t3\trise\t0\t6', 'CLOCK_IDENTITY'),
                   ('PATH\ts\t3\trise\t0\t1\t2\t3', 'PATH\ts\t3\trise\t0\t6\t2\t3', 'LAUNCH_CLOCK_IDENTITY'),
                   ('PATH\ts\t3\trise\t0\t1\t2\t3', 'PATH\ts\t3\trise\t6\t1\t2\t3', 'CLOCK_IDENTITY')]
        for old, new, code in changes:
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, '^FEEDBACK_'+code+'$'):
                self.parse([r.replace(old, new) for r in self.lines])

    def test_nonfinite_evidence_rejected(self):
        for value in ('nan', 'inf', '-inf'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '^FEEDBACK_NONFINITE$'):
                self.parse([r.replace('\t0.5\t', '\t'+value+'\t') for r in self.lines])

    def test_negative_hold_is_evidence_not_clipped(self):
        rows, _ = self.parse([r.replace('\t0.5\t', '\t-0.5\t') for r in self.lines])
        self.assertLess(min(r['slack_ns'] for r in rows), 0)

    def test_global_aperture_can_change_the_critical_path(self):
        # A is the genuine minimum-standard-slack winner. Its diagnostic cannot
        # bound unreported B after both paths receive a maximum-table aperture.
        native = [.1, .2]; holds = [.4, -.4]; maximum = .4
        corrected = [slack+hold-maximum for slack, hold in zip(native, holds)]
        self.assertEqual(native.index(min(native)), 0)
        self.assertEqual(corrected.index(min(corrected)), 1)
        self.assertAlmostEqual(corrected[1], -.6)
        lines = [r.replace('\t0.5\t0.1\t', '\t0.1\t0.4\t') for r in self.lines]
        rows, _ = h.parse('\n'.join(lines), self.plan, ['s'], maximum)
        self.assertEqual(rows[0]['slack_ns'], .1)
        self.assertNotIn('conservative_aperture_slack_ns', rows[0])

    def test_tool_error_and_missing_completion_rejected(self):
        for rows in (self.lines[:-1], self.lines+['Error: unrelated STA failure']):
            with self.assertRaisesRegex(ValueError, '^FEEDBACK_INCOMPLETE$'):
                self.parse(rows)


class Index:
    def __init__(self, cells):
        self.after = {'cells': cells, 'ports': {}}
        self.before = {'boundaries': {path+'/q': cell['connections']['Q'] for path, cell in cells.items()
                                      if 'Q' in cell['connections']}}
        self.drivers = {}
        for path, item in cells.items():
            for pin, bits in item['connections'].items():
                if item['directions'][pin] == 'output':
                    for bit in bits:
                        self.drivers.setdefault(bit, []).append(('pin', path+'/'+pin))

    def live_net(self, kind, label):
        assert kind == 'pin'
        cell, pin = label.rsplit('/', 1)
        return self.after['cells'][cell]['connections'][pin][0]

    def boundary(self, path, port):
        return [dict(kind='pin', source=path+'/Q')]

    def scalar(self, path, port):
        assert port == 'trigger'
        return 'pin', 'root/Z'


class FeedbackStorageTests(unittest.TestCase):
    def fixture(self, reset):
        rows = [dict(name=f'bit{i}', cell=h.SC+('dffsnq_1' if reset & (1 << i) else 'dffrnq_1'),
                     pins=dict(D=f'd[{i}]', Q=f'q[{i}]', CLK='trigger')) for i in range(2)]
        record = dict(bindings=[dict(instances=['bank'], model='ChiselAsyncEventRegister_v1',
                                    parameters=dict(RESET_VALUE=reset), cells=rows)])
        live = {'bank/'+r['name']: cell(r['cell'], {'CLK': 10, 'D': i}, {'Q': i+20})
                for i, r in enumerate(rows)}
        return record, dict(adapter_instances={'bank': 'bank'}), Index(live)

    def test_each_reset_bit_selects_the_exact_physical_cell(self):
        for reset in range(4):
            with self.subTest(reset=reset):
                record, audit, index = self.fixture(reset)
                root, lanes = h.storage(record, audit, index, 'bank')
                self.assertEqual(root, 'root/Z')
                self.assertEqual(set(lanes), {0, 1})

    def test_wrong_reset_polarity_cell_is_rejected(self):
        for reset in range(4):
            for lane in range(2):
                record, audit, index = self.fixture(reset)
                row = record['bindings'][0]['cells'][lane]
                row['cell'] = h.SC+('dffrnq_1' if reset & (1 << lane) else 'dffsnq_1')
                with self.subTest(reset=reset, lane=lane), self.assertRaisesRegex(ValueError, '^FEEDBACK_STORAGE_RECIPE$'):
                    h.storage(record, audit, index, 'bank')


def cell(kind, inputs, outputs):
    return dict(type=kind, connections={k: [v] for k, v in (inputs | outputs).items()},
                directions={k: 'input' for k in inputs} | {k: 'output' for k in outputs})


class FeedbackConeTests(unittest.TestCase):
    def setUp(self):
        self.cells = {'src': cell('ff', {'CLK': 10, 'D': 0}, {'Q': 1}),
                      'left': cell('buffer', {'I': 1}, {'Z': 2}),
                      'right': cell('buffer', {'I': 1}, {'Z': 3}),
                      'merge': cell('merge', {'A': 2, 'B': 3}, {'Z': 4}),
                      'dst': cell('ff', {'CLK': 10, 'D': 4}, {'Q': 5}),
                      'root': cell('buffer', {'I': 11}, {'Z': 10})}
        self.lib = {'ff': 'ff (IQ,IQN) { clocked_on : "CLK"; next_state : "D"; }',
                    'buffer': 'pin(Z) { timing() { related_pin : "I"; } }',
                    'merge': 'pin(Z) { timing() { related_pin : "A"; } timing() { related_pin : "B"; } }'}
        self.record = {'bindings': [dict(model='ChiselAsyncEventRegister_v1', instances=[name],
                                        ports=[dict(name='q', direction='output')]) for name in ('src', 'dst')]}
        self.audit = {'adapter_instances': {'src': 'src', 'dst': 'dst'}}
        self.plan = dict(root='root/Z', sources=['src/Q'], targets={'dst/D': dict(CLK='dst/CLK')})

    def bind(self):
        h.bind_cone(self.plan, self.record, self.audit, Index(self.cells), self.lib)

    def test_every_alternative_combination_path_is_bound(self):
        self.bind()
        self.assertEqual(set(map(tuple, self.plan['cone_arcs'])),
                         {('left/I', 'left/Z'), ('right/I', 'right/Z'),
                          ('merge/A', 'merge/Z'), ('merge/B', 'merge/Z'), ('src/CLK', 'src/Q')})

    def test_missing_one_connected_alternative_arc_fails(self):
        self.lib['merge'] = 'pin(Z) { timing() { related_pin : "A"; } }'
        with self.assertRaisesRegex(ValueError, '^FEEDBACK_REACHABLE_ARC_MISSING$'):
            self.bind()

    def test_multiple_driver_and_combinational_cycle_rejected(self):
        self.cells['rogue'] = cell('buffer', {'I': 1}, {'Z': 2})
        with self.assertRaisesRegex(ValueError, '^FEEDBACK_MULTIPLE_DRIVERS$'):
            self.bind()
        del self.cells['rogue']
        self.cells['left']['connections']['I'] = [4]
        with self.assertRaisesRegex(ValueError, '^FEEDBACK_COMBINATIONAL_CYCLE$'):
            self.bind()

    def test_wrong_clock_driver_rejected(self):
        self.cells['src']['connections']['CLK'] = [2]
        with self.assertRaisesRegex(ValueError, '^FEEDBACK_CLOCK_TREE$'):
            self.bind()


class FeedbackTableTests(unittest.TestCase):
    def setUp(self):
        table = 'index_1("0.1, 1.0"); index_2("0.1, 1.0"); values("0.2, 0.3", "0.4, 0.5");'
        delay = 'related_pin : "I"; '+''.join(name+'(t) {'+table+'}' for name in
                                              ('cell_rise', 'cell_fall', 'rise_transition', 'fall_transition'))
        hold = 'timing_type : hold_rising; related_pin : "CLK"; '+''.join(name+'(t) {'+table+'}'
                                                                 for name in ('rise_constraint', 'fall_constraint'))
        self.lib = {'buffer': 'pin(I) { capacitance : 0.2; } pin(Z) { timing() {'+delay+'} }',
                    'ff': 'pin(D) { capacitance : 0.2; timing() {'+hold+'} } pin(CLK) { capacitance : 0.2; }'}
        self.index = Index({'buffer': cell('buffer', {'I': 1}, {'Z': 2}),
                            'dst': cell('ff', {'D': 2, 'CLK': 3}, {'Q': 4})})
        self.plan = dict(cone_arcs=[('buffer/I', 'buffer/Z')], targets={'dst/D': dict(CLK='dst/CLK')})
        self.rows = [dict(sample='s')]
        self.slews = {('s', pin): [.4]*4 for pin in ('buffer/I', 'dst/D', 'dst/CLK')}

    def ranges(self):
        return h.table_ranges(self.rows, self.slews, self.index, self.lib, self.plan)

    def test_actual_arc_and_hold_tables_in_range(self):
        report = self.ranges()
        self.assertEqual(report['checked_cell_arcs'], 1)
        self.assertFalse(report['range_errors'])

    def test_out_of_table_or_nonfinite_slew_is_rejected_by_ranges(self):
        for pin in ('buffer/I', 'dst/D', 'dst/CLK'):
            for value in (2., float('nan')):
                with self.subTest(pin=pin, value=value):
                    self.slews[('s', pin)] = [value]*4
                    self.assertTrue(self.ranges()['range_errors'])
                    self.slews[('s', pin)] = [.4]*4

    def test_missing_slew_or_arc_table_is_not_zero_delay(self):
        del self.slews['s', 'buffer/I']
        with self.assertRaisesRegex(ValueError, '^FEEDBACK_SLEW_MISSING$'):
            self.ranges()
        self.slews['s', 'buffer/I'] = [.4]*4
        self.lib['buffer'] = 'pin(I) { capacitance : 0.2; } pin(Z) { timing() { related_pin : "I"; } }'
        with self.assertRaisesRegex(ValueError, '^FEEDBACK_ARC_TABLE_MISSING$'):
            self.ranges()

    def test_load_extrapolation_is_visible(self):
        self.lib['ff'] = self.lib['ff'].replace('capacitance : 0.2;', 'capacitance : 2.0;')
        self.assertTrue(self.ranges()['range_errors'])

    def test_missing_hold_table_is_unresolved(self):
        self.lib['ff'] = 'pin(D) { capacitance : 0.2; } pin(CLK) { capacitance : 0.2; }'
        with self.assertRaisesRegex(ValueError, '^FEEDBACK_HOLD_TABLE_MISSING$'):
            self.ranges()

    def test_top_output_and_unknown_load_are_rejected(self):
        self.index.after['ports']['out'] = dict(direction='output', bits=[2])
        with self.assertRaisesRegex(ValueError, '^FEEDBACK_TOP_OUTPUT_LOAD$'):
            self.ranges()
        self.index.after['ports'] = {}
        self.index = Index(self.index.after['cells'] | {'unknown': cell('unknown', {'I': 2}, {'Z': 5})})
        with self.assertRaisesRegex(ValueError, '^FEEDBACK_UNKNOWN_LOAD$'):
            self.ranges()


if __name__ == '__main__':
    unittest.main()

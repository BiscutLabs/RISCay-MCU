# SPDX-License-Identifier: Apache-2.0
import unittest

from routed_annotation import (BEGIN, END, DRIVERS_BEGIN, DRIVERS_END,
                               check_paths, parse_annotation, check_loaded_drivers, flat_driver_report)


def report(unannotated='', partial='', unannotated_count=0, partial_count=0):
    return (f'{BEGIN}\nFound {unannotated_count} unannotated drivers.\n'
            f'{unannotated}Found {partial_count} partially unannotated drivers.\n'
            f'{partial}{END}\n')


class RoutedAnnotationTests(unittest.TestCase):
    def drivers(self, rows):
        return (DRIVERS_BEGIN+'\n'+''.join(f'DRIVER\t{p}\t{n}\n' for p, n in rows)+
                f'COUNT\t{len(rows)}\n'+DRIVERS_END+'\n')

    def test_unloaded_exclusions_are_from_live_connectivity(self):
        log = report(' unused/Q\n', unannotated_count=1)+self.drivers([('used/Q', 3), ('unused/Q', 0)])
        summary = check_loaded_drivers(log)
        self.assertEqual(summary['no_load_exclusions'], ['unused/Q'])
        self.assertEqual(summary['loaded_driver_count'], 1)
        with self.assertRaisesRegex(ValueError, 'ROUTED_LOADED_DRIVER_UNANNOTATED'):
            check_loaded_drivers(log.replace('DRIVER\tunused/Q\t0', 'DRIVER\tunused/Q\t1'))

    def test_flat_report_names_bind_exact_live_driver_identity(self):
        live=self.drivers([('soc/used/Q',3),('soc/unused/Q',0),('in',2)])
        encoded=flat_driver_report(live,{'in'})
        good=report(' soc\\/unused/Q\n',unannotated_count=1)+encoded
        self.assertEqual(check_loaded_drivers(good)['loaded_driver_count'],2)
        with self.assertRaisesRegex(ValueError,'ROUTED_LOADED_DRIVER_UNANNOTATED'):
            check_loaded_drivers(good.replace(' soc\\/unused/Q',' soc\\/used/Q'))
        with self.assertRaisesRegex(ValueError,'ROUTED_ANNOTATION_UNKNOWN_DRIVER'):
            check_loaded_drivers(good.replace(' soc\\/unused/Q',' unknown/Q'))
        escaped=flat_driver_report(self.drivers([('soc\\/literal/Q',1)]),set())
        self.assertIn('DRIVER\tsoc\\/literal/Q\t1',escaped)
        with self.assertRaisesRegex(ValueError,'ROUTED_FLAT_DRIVER_COLLISION'):
            flat_driver_report(self.drivers([('soc\\/literal/Q',1),('soc/literal/Q',1)]),set())

    def test_partial_unknown_warning_and_driver_inventory_fail(self):
        live = self.drivers([('used/Q', 3), ('unused/Q', 0)])
        failures = [report(partial=' unused/Q\n', partial_count=1)+live,
                    report(' unknown/Q\n', unannotated_count=1)+live,
                    '[WARNING STA-1652] pin absent\n'+report()+live,
                    report()+live.replace('COUNT\t2', 'COUNT\t3'),
                    report()+live.replace('unused/Q', 'used/Q')]
        for log in failures:
            with self.subTest(log=log):
                with self.assertRaises(ValueError): check_loaded_drivers(log)
        for code in range(1640,1658):
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, 'ROUTED_SPEF_ANNOTATION_INCOMPLETE'):
                check_loaded_drivers(f'[WARNING STA-{code}] invalid SPEF\n'+report()+live)

    def test_inventory_retains_unrelated_drivers_and_partial_loads(self):
        inventory = parse_annotation(report(' unused/Q\n', ' branch/Z\n  load/D\n', 1, 1))
        self.assertEqual(inventory, {'unannotated': ['unused/Q'],
                                    'partial': {'branch/Z': ['load/D']}})
        coverage = check_paths(inventory, {'data': ['source/Q', 'sink/D']})
        self.assertEqual(coverage['checked_path_pins'], 2)
        self.assertEqual(coverage['unrelated_unannotated_drivers'], 1)

    def test_source_interior_and_endpoint_all_fail(self):
        for pin in ('source/Q', 'buffer/Z', 'endpoint/Z'):
            for partial in (False, True):
                with self.subTest(pin=pin, partial=partial):
                    inventory = parse_annotation(report(partial=f' {pin}\n', partial_count=1)
                        if partial else report(f' {pin}\n', unannotated_count=1))
                    with self.assertRaisesRegex(ValueError, 'ROUTED_PATH_UNANNOTATED'):
                        check_paths(inventory, {'path': ['source/Q', 'buffer/Z', 'endpoint/Z']})

    def test_empty_context_and_fully_annotated_paths(self):
        inventory = parse_annotation(report())
        self.assertEqual(check_paths(inventory, {})['checked_path_pins'], 0)
        self.assertEqual(check_paths(inventory, {'path': ['a/Q', 'b/D']})['checked_path_pins'], 2)

    def test_bad_counts_sections_duplicates_and_unknown_lines_fail(self):
        good = report(' a/Q\n', ' b/Z\n  c/D\n', 1, 1)
        bad = [good.replace('Found 1 unannotated', 'Found 2 unannotated'),
               good.replace(' a/Q\n', ' a/Q\n a/Q\n'),
               good.replace(' b/Z\n', ' a/Q\n'),
               good.replace('  c/D\n', '  c/D\n  c/D\n'),
               good.replace(' a/Q\n', '  a/Q\n'),
               good.replace(' b/Z\n', ''),
               good.replace('Found 1 partially unannotated drivers.\n', ''),
               good.replace('Found 1 unannotated drivers.\n', ''),
               good.replace(' a/Q\n', '[WARNING] unexpected\n'),
               good.replace(END, ''), good+good, END+'\n'+BEGIN+'\n']
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_annotation(value)


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
import unittest

from check_admission_controls import replace_pin


class AdmissionPinMutationTests(unittest.TestCase):
    def test_flat_expression_preserves_exact_surrounding_text(self):
        source='Cell target (\n  .a (old_signal), // keep this\n  .b (other_signal)\n);\n'
        self.assertEqual(replace_pin(source,'target','a',"1'b0"),
            source.replace('.a (old_signal)',".a (1'b0)"))

    def test_nested_expression_is_replaced_in_full(self):
        old='enabled & ~(hold[0] | select ? f(a, (b + c)) : {x[3:0], y})'
        source='Cell target (\n  .in_valid ('+old+'),\n  .in_bits ({a, b})\n);\n'
        self.assertEqual(replace_pin(source,'target','in_valid',"1'b0"),
            source.replace(old,"1'b0"))

    def test_multiline_nested_expression_preserves_other_pins_and_instances(self):
        old='\n    live && (first ||\n      (second && third))\n  '
        source=('Cell other (.in_valid (other));\n'
                'Cell target_suffix (.in_valid (suffix));\n'
                'Cell prefix_target (.in_valid (prefix));\n'
                'Cell target$extra (.in_valid (dollar));\n'
                'Cell target (\n  .in_valid ('+old+'), .in_valid_extra (keep),\n'
                '  .data ({f(x, y), z[3:0]})\n);\n')
        self.assertEqual(replace_pin(source,'target','in_valid','replacement'),
            source.replace(old,'replacement'))

    def test_comments_and_strings_cannot_select_targets_or_close_expressions(self):
        old='f("escaped \\\" ) target (.a (fake))", a /* ))] } .a (fake) */)'
        source=('// target (.a (fake));\n'
                '/* target (.a (fake)); */\n'
                'Cell target (\n  .a ('+old+'), // .a (fake)\n  .b (keep)\n);\n')
        self.assertEqual(replace_pin(source,'target','a','new_data'),source.replace(old,'new_data'))

    def test_empty_port_connection_can_be_replaced(self):
        self.assertEqual(replace_pin('Cell target (.a (), .b (keep));','target','a','signal'),
            'Cell target (.a (signal), .b (keep));')

    def test_missing_or_duplicate_instance_fails_closed(self):
        for source in ('Cell other (.a (x));',
                       'Cell target (.a (x)); Cell target (.a (y));'):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError,'ADMISSION_MUTATION_INSTANCE'):
                replace_pin(source,'target','a','new_data')

    def test_missing_or_duplicate_pin_fails_closed(self):
        for source in ('Cell target (.b (x));','Cell target (.a (x), .a (y));',
                       'Cell target (.a (x), .b (y), .b (z));'):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError,'ADMISSION_MUTATION_PIN'):
                replace_pin(source,'target','a','new_data')

    def test_malformed_instance_delimiters_fail_closed(self):
        for source in ('Cell target (.a ((x)), .b (y);',
                       'Cell target (.a (x)));',
                       'Cell target (.a (x))',
                       'Cell target (.a (x[3:0)));',
                       'Cell target (.a ({x, y)));',
                       'Cell target (.a ("unterminated));',
                       'Cell target (.a (x /* unterminated));'):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError,'ADMISSION_MUTATION_INSTANCE'):
                replace_pin(source,'target','a','new_data')

    def test_malformed_port_lists_fail_closed(self):
        for source in ('Cell target (x, .a (y));','Cell target (.a x);',
                       'Cell target (.a (x) .b (y));','Cell target (.a (x),);'):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError,'ADMISSION_MUTATION_PIN'):
                replace_pin(source,'target','a','new_data')


if __name__=='__main__': unittest.main()

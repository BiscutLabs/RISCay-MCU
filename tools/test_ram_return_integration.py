# SPDX-License-Identifier: Apache-2.0
"""Static native RAM error-alias closure controls.

The default tests use small independent netlists. Optional --bd-export and
--click-export replay the same mutations against real production exports. The
original exports are read only; every changed RTL copy lives in a temporary
directory. These tests do not compile, simulate, or claim complete SoC closure.
"""
import argparse
import copy
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from check_ram_return_integration import close_error_aliases, mask_literal_zero


def clean(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S)


def replace_pin(text, instance, pin, value):
    block = re.compile(r'(^\s*\w+\s+' + re.escape(instance) + r'\s*\()(.*?)(^\s*\);)', re.M | re.S)
    matches = list(block.finditer(text))
    if len(matches) != 1:
        raise AssertionError('INTEGRATION_TEST_INSTANCE:' + instance)
    match = matches[0]
    changed, count = re.subn(r'(\.' + re.escape(pin) + r'\s*\()([^()]*)\)',
                              lambda m: m[1] + value + ')', match[2])
    if count != 1:
        raise AssertionError('INTEGRATION_TEST_PIN:' + pin)
    return text[:match.start(2)] + changed + text[match.end(2):]


def append_rtl(text, fragment):
    if text.count('endmodule') != 1:
        raise AssertionError('INTEGRATION_TEST_MODULE_SHAPE')
    return text.replace('endmodule', fragment + '\nendmodule')


def synthetic(click):
    top = 'ClickSoc' if click else 'FourPhaseSoc'
    model = 'ClickCompletion' if click else 'FourPhaseCompletion'
    producer, consumer = 'ca_child_ram_return', 'ca_child_completion'
    node = dict(rtl_path=top + '.' + producer)
    completion = dict(module=model, rtl_path=top + '.' + consumer,
        endpoints=[dict(id=n, rtl_path=top + '.' + consumer + '.' + wire)
                   for n, wire in (('ram_data', 'ram_packed'), ('result_sources', 'result_packed'))], primitives=[])
    scopes = {node['rtl_path']: dict(ports={'response_bits_error': dict(direction='output', width=1)}),
              completion['rtl_path']: dict(ports={'ram_bits_error': dict(direction='input', width=1)})}
    # Explicit production ABI ordering, independent of the checker helper.
    fields = ['plan_bits_response_data', 'plan_bits_response_error', 'plan_bits_memory', 'plan_bits_ram',
              'plan_bits_telemetry', 'plan_bits_housekeeping', 'memory_bits_data', 'memory_bits_error',
              'ram_bits_data', 'ram_bits_error']
    cells = ''
    if click:
        fields += ['plan_req', 'memory_req', 'ram_req', 'telemetry_req', 'housekeeping_req']
        for owner in ('memory_phase', 'ram_phase', 'telemetry_phase', 'housekeeping_phase'):
            instance = 'ca_primitive_' + owner
            path = completion['rtl_path'] + '.' + instance
            completion['primitives'].append(dict(id=owner, rtl_path=path))
            fields.append(owner + '_q')
            cells += 'EventRegister #(.WIDTH(1)) ' + instance + ' (\n.q (' + owner + '_q)\n);\n'
            scopes[path] = dict(ports={'q': dict(direction='output', width=1)})
    sources = {top + '.sv': ('module ' + top + '();\nwire ram_error;\n'
        'RamReturn ' + producer + ' (\n.response_bits_error (ram_error)\n);\n' +
        model + ' ' + consumer + ' (\n.ram_bits_error (ram_error)\n);\nendmodule\n'),
        model + '.sv': ('module ' + model + '(input ram_bits_error);\n' +
            'wire [32:0] ram_packed = {ram_bits_data, ram_bits_error};\n' +
            'wire [' + ('111' if click else '102') + ':0] result_packed = {' + ', '.join(fields) + '};\n' +
            cells + 'endmodule\n')}
    return dict(top=top, node=node, completion=completion, scopes=scopes, sources=sources)


def actual(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'contract.json').read_text())['manifest']
    top = manifest['top']
    definitions = dict(re.findall(r'^`define\s+(\w+)\s+(\S+)\s*$',
                                 (directory / ('ref_' + top + '.sv')).read_text(), re.M))
    root = manifest['design']
    children = {c['id']: c['contract'] for c in root['children']}
    node, completion = copy.deepcopy(children['ram_return']), copy.deepcopy(children['completion'])
    for endpoint in completion['endpoints']:
        endpoint['rtl_path'] = top + '.' + definitions['ref_' + top + '_' + endpoint['probe']]
    scopes = {}

    def ports(path, model):
        # Derive direction from the actual emitted declaration, not endpoint
        # metadata. Only direction and scalar width are needed by alias closure.
        source = clean((directory / (model + '.sv')).read_text())
        header = re.search(r'\bmodule\b.*?;', source, re.S)
        if header is None:
            raise AssertionError('INTEGRATION_TEST_MODULE_HEADER:' + model)
        declarations = re.findall(r'\b(input|output|inout)\s+(?:(?:wire|logic|reg)\s+)?'
                                  r'(?:\[([^]]+)\]\s*)?(\w+)', header[0])
        scopes[path] = dict(ports={n: dict(direction=d, width=1 if not w else None) for d, w, n in declarations})

    # Firtool may deduplicate modules and leave a different metadata spelling;
    # use actual instance models for this independent port-direction inventory.
    for path, model in ((top, top), (completion['rtl_path'], completion['module'])):
        ports(path, model)
        text = clean((directory / (model + '.sv')).read_text())
        for match in re.finditer(r'^\s*(\w+)\s+(?:#\(.*?\)\s*)?(\w+)\s*\((.*?)^\s*\);', text, re.M | re.S):
            if (directory / (match[1] + '.sv')).is_file():
                ports(path + '.' + match[2], match[1])
    sources = {name: clean((directory / name).read_text()) for name in (top + '.sv', completion['module'] + '.sv')}
    return dict(top=top, node=node, completion=completion, scopes=scopes, sources=sources)


class AliasControls:
    def fixtures(self):
        raise NotImplementedError

    def check(self, fixture, mutate=None, expected=None):
        value = copy.deepcopy(fixture)
        if mutate:
            mutate(value)
        with tempfile.TemporaryDirectory(prefix='riscay-ram-error-alias-') as temporary:
            folder = Path(temporary)
            for name, source in value['sources'].items():
                (folder / name).write_text(source, encoding='utf-8')
            operation = lambda: close_error_aliases(value['node'], value['completion'], value['top'], value['scopes'], folder)
            if expected:
                with self.assertRaisesRegex(ValueError, expected):
                    operation()
            else:
                record = operation()
                self.assertEqual(record['packing_checked'], ['ram_data', 'result_sources'])
        return value

    @staticmethod
    def net(fixture):
        top = fixture['sources'][fixture['top'] + '.sv']
        producer = fixture['node']['rtl_path'].rsplit('.', 1)[1]
        block = re.search(r'\b' + producer + r'\s*\((.*?)^\s*\);', top, re.M | re.S)[1]
        return re.search(r'\.response_bits_error\s*\((\w+)\)', block)[1]

    @staticmethod
    def append(fixture, owner, fragment):
        filename = fixture['top'] + '.sv' if owner == 'top' else fixture['completion']['module'] + '.sv'
        fixture['sources'][filename] = append_rtl(fixture['sources'][filename], fragment)

    def test_valid_literal_alias_baseline(self):
        for fixture in self.fixtures():
            with self.subTest(top=fixture['top']):
                self.check(fixture)

    def test_ordinary_pure_expression_reads_remain_allowed(self):
        for fixture in self.fixtures():
            self.check(fixture, lambda f: self.append(f, 'completion',
                'wire diagnostic_copy = ram_bits_error;\nassign diagnostic_output = ram_bits_error;'))

    def test_scalar_port_direction_and_width_are_closed(self):
        for fixture in self.fixtures():
            for owner, pin in (('node', 'response_bits_error'), ('completion', 'ram_bits_error')):
                for field, value in (('direction', 'inout'), ('width', 2), ('width', None)):
                    def mutate(f, owner=owner, pin=pin, field=field, value=value):
                        f['scopes'][f[owner]['rtl_path']]['ports'][pin][field] = value
                    with self.subTest(top=fixture['top'], owner=owner, field=field, value=value):
                        self.check(fixture, mutate, 'RAM_RETURN_ERROR_ALIAS_SCALAR_PORT')

    def test_scalar_input_declaration_must_match_the_compiled_input(self):
        for fixture in self.fixtures():
            for declaration in ('output ram_bits_error', 'input [1:0] ram_bits_error'):
                def mutate(f, declaration=declaration):
                    name = f['completion']['module'] + '.sv'
                    f['sources'][name], count = re.subn(r'\binput\s+ram_bits_error\b', declaration, f['sources'][name])
                    self.assertEqual(count, 1)
                with self.subTest(top=fixture['top'], declaration=declaration):
                    self.check(fixture, mutate, 'RAM_RETURN_ERROR_ALIAS_INPUT_DECLARATION')

    def test_unknown_child_input_cannot_consume_an_alias_reference(self):
        for fixture in self.fixtures():
            def mutate(f):
                f['scopes'][f['completion']['rtl_path'] + '.unknown_reader'] = dict(ports={'in': dict(direction='input', width=1)})
                self.append(f, 'completion', 'UnknownReader #(.WIDTH(1)) unknown_reader (\n.in(ram_bits_error)\n);')
            self.check(fixture, mutate, 'RAM_RETURN_ERROR_ALIAS_CHILD_OUTPUT_WRITER')

    def test_duplicate_packed_endpoint_aliases_are_rejected(self):
        for fixture in self.fixtures():
            def mutate(f):
                endpoints = {e['id']: e for e in f['completion']['endpoints']}
                endpoints['ram_data']['rtl_path'] = endpoints['result_sources']['rtl_path']
            self.check(fixture, mutate, 'RAM_RETURN_ERROR_ALIAS_PACKED_ENDPOINT_DUPLICATE')

    def test_macro_or_unsupported_reference_cannot_hide_a_writer(self):
        for fixture in self.fixtures():
            for owner, fragment in (('top', '`define RAM_ALIAS ' + self.net(fixture)),
                                    ('completion', '`define RAM_INPUT ram_bits_error'),
                                    ('completion', 'tran hidden_writer(ram_bits_error,other_error);')):
                with self.subTest(top=fixture['top'], owner=owner, fragment=fragment):
                    self.check(fixture, lambda f, owner=owner, fragment=fragment: self.append(f, owner, fragment),
                               'RAM_RETURN_ERROR_ALIAS_UNCONSUMED')

    def test_consumer_xor_mux_substitution_and_literal_are_rejected(self):
        for fixture in self.fixtures():
            net = self.net(fixture)
            for expression in (net + ' ^ reset', 'reset ? ' + net + " : 1'b0", 'other_error', "1'b0", '(' + net + ')'):
                def mutate(f, expression=expression):
                    name = f['top'] + '.sv'
                    f['sources'][name] = replace_pin(f['sources'][name], f['completion']['rtl_path'].rsplit('.', 1)[1],
                                                    'ram_bits_error', expression)
                with self.subTest(top=fixture['top'], expression=expression):
                    self.check(fixture, mutate, 'RAM_RETURN_ERROR_ALIAS_CONSUMER')

    def test_top_scalar_and_concatenation_writers_are_rejected(self):
        for fixture in self.fixtures():
            net = self.net(fixture)
            for fragment in ('assign ' + net + '=reset;', 'always @(posedge reset) ' + net + '<=1;',
                             'initial force ' + net + '=reset;', 'assign {' + net + ',unused}=2\'b00;'):
                with self.subTest(top=fixture['top'], fragment=fragment):
                    self.check(fixture, lambda f, fragment=fragment: self.append(f, 'top', fragment), 'RAM_RETURN_ERROR_ALIAS_')

    def test_scalar_input_writers_are_rejected(self):
        for fixture in self.fixtures():
            for fragment in ('assign ram_bits_error=1\'b0;', 'always @(posedge reset) ram_bits_error<=1;',
                             'initial force ram_bits_error=1\'b0;', 'assign {ram_bits_error,unused}=2\'b00;'):
                with self.subTest(top=fixture['top'], fragment=fragment):
                    self.check(fixture, lambda f, fragment=fragment: self.append(f, 'completion', fragment), 'RAM_RETURN_ERROR_ALIAS_')

    def test_extra_output_drivers_are_rejected_in_both_modules(self):
        for fixture in self.fixtures():
            for owner in ('top', 'completion'):
                for parameterized in (False, True):
                    def mutate(f, owner=owner, parameterized=parameterized):
                        net = self.net(f) if owner == 'top' else 'ram_bits_error'
                        path = f['top'] if owner == 'top' else f['completion']['rtl_path']
                        f['scopes'][path + '.extra_writer'] = dict(ports={'q': dict(direction='output', width=1)})
                        self.append(f, owner, 'ExtraWriter ' + ('#(.WIDTH(1)) ' if parameterized else '') +
                                    'extra_writer (\n.q (' + net + ')\n);')
                    with self.subTest(top=fixture['top'], owner=owner, parameterized=parameterized):
                        self.check(fixture, mutate, 'RAM_RETURN_ERROR_ALIAS_')

    def test_error_packing_xor_mux_constant_and_wrong_leaf_are_rejected(self):
        for fixture in self.fixtures():
            for endpoint in ('ram_data', 'result_sources'):
                for expression in ('ram_bits_error ^ reset', "reset ? ram_bits_error : 1'b0", "1'b0", 'memory_bits_error'):
                    def mutate(f, endpoint=endpoint, expression=expression):
                        wire = next(e['rtl_path'].rsplit('.', 1)[1] for e in f['completion']['endpoints'] if e['id'] == endpoint)
                        name = f['completion']['module'] + '.sv'
                        pattern = r'(\b' + re.escape(wire) + r'\s*=)([^;]+)(;)'
                        def change(m):
                            if m[2].count('ram_bits_error') != 1:
                                raise AssertionError('INTEGRATION_TEST_PACKING_SHAPE')
                            return m[1] + m[2].replace('ram_bits_error', expression) + m[3]
                        f['sources'][name], count = re.subn(pattern, change, f['sources'][name])
                        self.assertEqual(count, 1)
                    with self.subTest(top=fixture['top'], endpoint=endpoint, expression=expression):
                        self.check(fixture, mutate, 'RAM_RETURN_ERROR_ALIAS_PACKING')

    def test_packed_extra_scalar_and_concatenation_writers_are_rejected(self):
        for fixture in self.fixtures():
            for endpoint in ('ram_data', 'result_sources'):
                wire = next(e['rtl_path'].rsplit('.', 1)[1] for e in fixture['completion']['endpoints'] if e['id'] == endpoint)
                for fragment in ('assign ' + wire + "[0]=1'b0;", 'assign {' + wire + ",unused}=1'b0;"):
                    with self.subTest(top=fixture['top'], endpoint=endpoint, fragment=fragment):
                        self.check(fixture, lambda f, fragment=fragment: self.append(f, 'completion', fragment), 'RAM_RETURN_ERROR_ALIAS_')

    def test_packed_extra_cell_outputs_are_rejected(self):
        for fixture in self.fixtures():
            for endpoint in ('ram_data', 'result_sources'):
                for parameterized in (False, True):
                    def mutate(f, endpoint=endpoint, parameterized=parameterized):
                        wire = next(e['rtl_path'].rsplit('.', 1)[1] for e in f['completion']['endpoints'] if e['id'] == endpoint)
                        f['scopes'][f['completion']['rtl_path'] + '.extra_writer'] = dict(ports={'q': dict(direction='output', width=1)})
                        self.append(f, 'completion', 'ExtraWriter ' + ('#(.WIDTH(1)) ' if parameterized else '') +
                                    'extra_writer (\n.q (' + wire + '[0])\n);')
                    with self.subTest(top=fixture['top'], endpoint=endpoint, parameterized=parameterized):
                        self.check(fixture, mutate, 'RAM_RETURN_ERROR_ALIAS_')


class RamErrorAliasUnitTests(AliasControls, unittest.TestCase):
    def fixtures(self):
        return [synthetic(False), synthetic(True)]


class ConstantMaskTests(unittest.TestCase):
    def test_only_impossible_one_polarity_is_removed(self):
        for width, bit in ((33, 0), (103, 0), (112, 9)):
            full = (1 << width) - 1
            source = f'if (ones_7 !== {width}\'h{full:x} || zeros_7 !== {width}\'h{full:x}) $fatal(1, "INACTIVE_ENDPOINT:Soc.alias");'
            result = mask_literal_zero(source, 'Soc.alias', width, bit)
            self.assertIn(f"ones_7 !== {width}'h{full ^ (1 << bit):x}", result)
            self.assertIn(f"zeros_7 !== {width}'h{full:x}", result)
            self.assertEqual(result.count('$fatal'), 1)

    def test_missing_or_duplicated_coverage_check_fails_closed(self):
        source = 'if (ones_1 !== 1\'h1 || zeros_1 !== 1\'h1) $fatal(1, "INACTIVE_ENDPOINT:Soc.alias");'
        for changed in ('', source + '\n' + source, source.replace('1\'h1', '1\'h0')):
            with self.assertRaisesRegex(ValueError, 'RAM_RETURN_CONSTANT_COVERAGE_SHAPE'):
                mask_literal_zero(changed, 'Soc.alias', 1, 0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bd-export', type=Path)
    parser.add_argument('--click-export', type=Path)
    args = parser.parse_args()
    if bool(args.bd_export) != bool(args.click_export):
        parser.error('Supply both production exports or neither.')
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    original_hashes = {}
    if args.bd_export:
        directories = [args.bd_export.resolve(), args.click_export.resolve()]
        original_hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for d in directories for p in d.glob('*.sv')}
        fixtures = [actual(d) for d in directories]
        class ActualRamErrorAliasTests(AliasControls, unittest.TestCase):
            def fixtures(self):
                return fixtures
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ActualRamErrorAliasTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if any(hashlib.sha256(p.read_bytes()).hexdigest() != digest for p, digest in original_hashes.items()):
        raise AssertionError('INTEGRATION_TEST_ORIGINAL_CHANGED')
    raise SystemExit(not result.wasSuccessful())

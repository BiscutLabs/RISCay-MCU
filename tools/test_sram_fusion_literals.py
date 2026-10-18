# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest

import check_sram_fusion_literals as f


def fixture(click=False):
    top = 'ClickSoc' if click else 'FourPhaseSoc'; style = 'Click' if click else 'FourPhase'
    protocol = ('two' if click else 'four')+'-phase-bundled-v1'
    graph = {'modules': {top: {'netnames': {}}}}
    root = dict(module=top, rtl_path=top, children=[])
    for owner in ('ram', 'program'):
        path = top+'.ca_child_'+owner+'_access.ca_child_native'
        bits = ['0']*32+list(range(1000 if owner == 'ram' else 2000,
                                (1000 if owner == 'ram' else 2000)+69))
        def node(name, ids):
            n = dict(module=name, rtl_path=path+'.'+name, channels=[], endpoints=[], children=[])
            for cid in ids:
                ep = n['rtl_path']+'.'+cid+'_bits'
                n['endpoints'].append(dict(id=cid+'_data', width=101, rtl_path=ep))
                n['channels'].append(dict(id=cid, data=cid+'_data', protocol=protocol,
                    layout=[dict(field=k, lsb=i, width=w, signed=False) for k, i, w in f.LAYOUT]))
                graph['modules'][top]['netnames'][ep[len(top)+1:]] = dict(bits=list(bits))
            return n
        fork = node('fork', ('in', 'left', 'right') if click else ('in', 'out0', 'out1'))
        issue = node('issue', ('in',)); join = node('join', ('left',) if click else ('left_input',))
        join['children'] = [dict(id='left_storage' if click else 'left', contract=node('store', ('in',)))]
        native = dict(module=style+'Sram', rtl_path=path, children=[dict(id=k, contract=v)
            for k, v in [('lane_0_fork', fork), ('lane_0_issue', issue), ('lane_0_join', join)]])
        root['children'].append(dict(id=owner+'_access', contract=dict(children=[dict(id='native', contract=native)])))
    return dict(top=top, design=root), graph


def probe(records):
    full = (1 << 101)-1
    return 'task check; begin\nend endtask\n'+'\n'.join(
        f'if (ones_{i} !== 101\'h{full:x} || zeros_{i} !== 101\'h{full:x}) '
        f'$fatal(1, "INACTIVE_ENDPOINT:{r["endpoint"]}");' for i, r in enumerate(records))


class SramFusionLiteralSpec(unittest.TestCase):
    def test_both_native_protocols_preserve_request_polarity_and_add_value_checks(self):
        for click in (False, True):
            m, g = fixture(click); records = f.obligations(m, g); self.assertEqual(len(records), 12)
            result = f.apply(probe(records), records)
            self.assertEqual(result.count('SRAM_FUSION_LITERAL_VALUE:'), 12)
            self.assertEqual(result.count("!== 101'h1fffffffffffffffff00000000"), 12)
            self.assertEqual(result.count("!== 101'h1fffffffffffffffffffffffff"), 12)

    def test_result_must_be_literal_zero_not_dynamic_one_unknown_or_reset_state(self):
        for bad in (45678, '1', 'x', 'z'):
            m, g = fixture(); next(iter(g['modules'][m['top']]['netnames'].values()))['bits'][7] = bad
            with self.subTest(value=bad), self.assertRaisesRegex(ValueError, 'NOT_LITERAL_ZERO'):
                f.obligations(m, g)

    def test_request_alias_cannot_be_changed(self):
        m, g = fixture(); list(g['modules'][m['top']]['netnames'].values())[1]['bits'][64] += 1
        with self.assertRaisesRegex(ValueError, 'PROJECTION_ALIAS'): f.obligations(m, g)

    def test_no_constant_request_lane_is_covered_by_this_proof(self):
        for bad in ('0', '1', 'x'):
            m, g = fixture(); next(iter(g['modules'][m['top']]['netnames'].values()))['bits'][32] = bad
            with self.subTest(value=bad), self.assertRaisesRegex(ValueError, 'REQUEST_IS_NOT_DYNAMIC'):
                f.obligations(m, g)

    def test_schema_order_and_signedness_are_exact(self):
        for change in ('order', 'signed', 'width'):
            m, g = fixture(); native=m['design']['children'][0]['contract']['children'][0]['contract']
            layout=native['children'][0]['contract']['channels'][0]['layout']
            if change == 'order': layout[0], layout[1] = layout[1], layout[0]
            elif change == 'signed': layout[0]['signed'] = True
            else: layout[0]['width'] = 31
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'CHANNEL_SCHEMA'):
                f.obligations(m, g)

    def test_endpoint_missing_or_duplicate_is_rejected(self):
        for duplicate in (False, True):
            m, g = fixture(); native=m['design']['children'][0]['contract']['children'][0]['contract']
            es=native['children'][0]['contract']['endpoints']
            if duplicate: es.append(deepcopy(es[0]))
            else: es.pop(0)
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(ValueError, 'ENDPOINT_SCHEMA'):
                f.obligations(m, g)

    def test_missing_elaborated_net_and_unfused_stage_are_rejected(self):
        m, g = fixture(); g['modules'][m['top']]['netnames'].pop(next(iter(g['modules'][m['top']]['netnames'])))
        with self.assertRaisesRegex(ValueError, 'ELABORATED_ENDPOINT'): f.obligations(m, g)
        m, g = fixture(); m['design']['children'][0]['contract']['children'][0]['contract']['children'].append(
            dict(id='prepare', contract={}))
        with self.assertRaisesRegex(ValueError, 'FUSED_TOPOLOGY'): f.obligations(m, g)

    def test_existing_relaxed_or_malformed_mask_is_rejected(self):
        m, g = fixture(); records = f.obligations(m, g)
        already = f.apply(probe(records), records)
        with self.assertRaisesRegex(ValueError, 'CONSTANT_COVERAGE_SHAPE'): f.apply(already, records)
        malformed = probe(records).replace('zeros_0', 'zeros_999')
        with self.assertRaisesRegex(ValueError, 'CONSTANT_COVERAGE_SHAPE'): f.apply(malformed, records)


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from check_gf180_coupling import check_extraction_pair,deck,rank,read_spef,select_victims,unextracted_rows


SPEF='''*SPEF "ieee 1481-1999"
*DESIGN_FLOW "PIN_CAP NONE"
*C_UNIT 1 PF
*R_UNIT 1 OHM
*NAME_MAP
*1 victim
*2 aggressor
*3 driver
*4 receiver
*5 other
*D_NET *1 3
*CONN
*I *3:Z O
*I *4:I I
*CAP
1 *3:Z 1
2 *4:I 1
3 *4:I *5:Z 1
*RES
1 *3:Z *4:I 100
*END
*D_NET *2 2
*CONN
*I *5:Z O
*CAP
1 *5:Z 1
2 *5:Z *4:I 1
*RES
*END
'''


class Coupling(unittest.TestCase):
    def read(self,text,selected=('victim','aggressor')):
        with TemporaryDirectory() as d:
            p=Path(d)/'test.spef';p.write_text(text)
            return read_spef(p,set(selected))

    def test_reciprocal_rows_are_counted_once_per_victim(self):
        parsed=self.read(SPEF);self.assertEqual(parsed['missing'],[])
        row=rank(parsed['networks']['victim'],3.)
        self.assertEqual(row['coupling_pf'],1.)
        self.assertEqual(row['lumped_floating_rail_charge_share_v'],1.)
        self.assertEqual(row['simultaneous_edge_node_upper_bound_v'],1.5)
        self.assertEqual(row['aggressors'],[dict(net='aggressor',coupling_pf=1.)])
        # Equal parallel physical capacitors must not be deduplicated away.
        more=SPEF.replace('3 *4:I *5:Z 1','3 *4:I *5:Z 1\n4 *4:I *5:Z 1')
        self.assertEqual(rank(self.read(more)['networks']['victim'],3.)['coupling_pf'],2.)

    def test_missing_ownership_invalid_numbers_and_pin_caps_fail(self):
        self.assertEqual(self.read(SPEF,('missing',))['missing'],['missing'])
        for text in (SPEF.replace('*5:Z 1','*unknown:Z 1',1),
                     SPEF.replace('3 *4:I *5:Z 1','3 *4:I *5:Z nan'),
                     SPEF.replace('PIN_CAP NONE','PIN_CAP INPUT')):
            with self.assertRaises(ValueError):self.read(text)

    def test_unit_conversion_and_distributed_deck(self):
        parsed=self.read(SPEF.replace('*C_UNIT 1 PF','*C_UNIT 1000 FF'))
        net=parsed['networks']['victim']
        text,labels=deck(net,3.3,0.,True,.02,100.,.2)
        self.assertEqual(len(labels),2)
        self.assertIn('CC0 ',text);self.assertIn('R0 ',text)
        self.assertIn('.meas tran n0_max',text)
        self.assertIn('5.2n 0.0',text)
        with self.assertRaisesRegex(ValueError,'NODE_LIMIT'):deck(net,3.3,0.,True,.02,100.,.2,max_nodes=1)

    def test_escaped_identifiers_resolve_uniquely(self):
        text=SPEF.replace('*1 victim',r'*1 victim\/wire')
        parsed=self.read(text,(r'victim\/wire',))
        self.assertEqual(parsed['missing'],[])
        self.assertIn(r'victim\/wire',parsed['networks'])
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS_SELECTED_NAME'):
            self.read(text,(r'victim\/wire','victim/wire'))

    def test_unextracted_requires_single_terminal_and_no_wire(self):
        log='UNEXTRACTED_SPEF_NET\tstub\t0\t1\t0\t0\nUNEXTRACTED_SPEF_NET\tmissing\t1\t2\t0\t0\n'
        result=unextracted_rows(log,['stub','missing'])
        self.assertEqual(result['excluded'],['stub'])
        self.assertEqual(result['unexplained'],['missing'])
        with self.assertRaisesRegex(ValueError,'COVERAGE'):unextracted_rows(log,['stub','missing','absent'])

    def test_rc_pair_and_mapping_must_match_existing_run_receipt(self):
        receipt=dict(provenance_schema='riscay-pnr-inputs-v5',mapping_sha256='mapping',
            generated_inputs_sha256={'native-routing.json':'inventory'},
            checkpoints=dict(route=dict(native_routing_sha256='routing'),extract=dict(rc_corners={
            'min':dict(odb_sha256='odb-min',spef_sha256='spef-min'),
            'max':dict(odb_sha256='odb-max',spef_sha256='spef-max')})))
        self.assertEqual(check_extraction_pair(receipt,'odb-min','spef-min','mapping','routing','inventory'),'min')
        for odb,spef,mapping in [('odb-min','spef-max','mapping'),('odb-min','spef-min','other')]:
            with self.assertRaisesRegex(ValueError,'INPUT_MISMATCH'):check_extraction_pair(receipt,odb,spef,mapping)
        for routing,inventory in [('other-run-routing','inventory'),('routing','other-run-inventory')]:
            for historical in (False,True):
                with self.assertRaisesRegex(ValueError,'NATIVE_ROUTING_RUN_MISMATCH'):
                    check_extraction_pair(receipt,'odb-min','spef-min','mapping',routing,inventory,historical)
        receipt['provenance_schema']='riscay-pnr-inputs-v4'
        with self.assertRaisesRegex(ValueError,'HISTORICAL_DIAGNOSTIC_REQUIRED'):
            check_extraction_pair(receipt,'odb-min','spef-min','mapping','routing','inventory')
        self.assertEqual(check_extraction_pair(receipt,'odb-min','spef-min','mapping',historical_diagnostic=True),'min')

    def test_explicit_victims_keep_order_and_reject_duplicates_or_unknown_nets(self):
        ranking=[dict(net='ratio-first'),dict(net='request'),dict(net='ack')]
        self.assertEqual([r['net'] for r in select_victims(ranking,1,['ack','request'])],['ack','request'])
        self.assertEqual(select_victims(ranking,1),ranking[:1])
        for victims in ([],['request','request'],['unknown']):
            with self.assertRaises(ValueError):select_victims(ranking,1,victims)


if __name__=='__main__':unittest.main()

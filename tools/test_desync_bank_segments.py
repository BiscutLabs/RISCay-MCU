# SPDX-License-Identifier: Apache-2.0
import unittest
from measure_desync_banks import parse_segments


class BankSegmentTests(unittest.TestCase):
    def test_inventory_distinguishes_missing_and_disconnected_pairs(self):
        rows=['STORAGE 4 4','SEGMENTS_DONE']
        for source in ('a','b'):
            for target in ('a','b'):
                for mode in ('min','max'):
                    present=int(source==target)
                    rows.append(f'PAIR_COVERAGE {source} {target} {mode} {present}')
                    if present:rows.append(f'PAIR {source} {target} {mode} 1 2 q/Q d/D 997')
        text='\n'.join(rows)
        report=parse_segments(text,'fixture')
        self.assertTrue(all(r['source']==r['target'] for r in report['rows']))
        self.assertTrue(all(r['source']!=r['target'] for r in report['empty_pairs']))
        mutations=(text.replace('SEGMENTS_DONE',''),
                   text.replace('PAIR a a min 1 2 q/Q d/D',''),
                   text.replace('PAIR_COVERAGE a b min 0',''),
                   text+'\nError: failed query',
                   text.replace('PAIR a a min 1 2','PAIR a a min 1 nan'))
        for broken in mutations:
            with self.subTest(broken=broken),self.assertRaises(ValueError):
                parse_segments(broken,'fixture')


if __name__=='__main__':unittest.main()

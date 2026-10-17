# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from check_pnr_repair import read_graph
from repair_gf180_design import graph_proof
from gf180_physical import SC
from test_global_repair import LIB


class PnrRepairTest(unittest.TestCase):
    def read(self,text):
        with TemporaryDirectory() as folder:
            p=Path(folder)/'graph.tsv';p.write_text(text)
            return read_graph(p)

    def graph(self,buffered=False):
        return ('C\towner/gate\t'+SC+'buf_1\nP\towner/gate\tI\tinput\tin\nP\towner/gate\tZ\toutput\tmid\n'
                'C\tsink\t'+SC+'inv_1\nP\tsink\tI\tinput\t'+('branch' if buffered else 'mid')+'\nP\tsink\tZ\toutput\tout\n'
                +('C\tadded\t'+SC+'buf_2\nP\tadded\tI\tinput\tmid\nP\tadded\tZ\toutput\tbranch\n' if buffered else '')+
                'T\tinput\tinput\tin\nT\toutput\toutput\tout\n')

    def test_flat_odbdump_preserves_native_pins_and_full_graph(self):
        a=self.read(self.graph());b=self.read(self.graph(True))
        p=graph_proof(a,b,'RiscayMcuDigital',{'owner/gate':'owner'},[LIB]*5)
        self.assertEqual(p['added_buffers'],['added'])
        bad=self.read(self.graph(True).replace('P\tadded\tI\tinput\tmid','P\tadded\tI\tinput\tin'))
        with self.assertRaisesRegex(ValueError,'REPAIR_GRAPH_CHANGED'):
            graph_proof(a,bad,'RiscayMcuDigital',{'owner/gate':'owner'},[LIB]*5)

    def test_bad_or_missing_pins_fail_closed(self):
        for text in ('','unknown','P\tabsent\tA\tinput\tx','C\tu\tx\nP\tu\tA\tinput\tNULL',
                     'C\tu\tx\nP\tu\tA\tinout\tx','C\tu\tx\nC\tu\tx'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):self.read(text)


if __name__=='__main__':unittest.main()

# SPDX-License-Identifier: Apache-2.0
import unittest
from report_electrical_groups import classify


class ElectricalGroups(unittest.TestCase):
    def test_shared_rows_are_one_net_and_locked_has_precedence(self):
        graph='C\tdriver\tcell\nP\tdriver\tZ\toutput\tn\nC\tsink\tcell\nP\tsink\tA\tinput\tn\nT\tpad\toutput\tn\n'
        log='[WARNING RSZ-0170] Cannot repair slew on net n driven by driver/Z: driver resistance x repeater pin capacitance exceeded\n'
        report='max slew\ndriver/Z 2 12 -10 (VIOLATED)\nsink/A 2 12 -10 (VIOLATED)\npad 2 12 -10 (VIOLATED)\n'
        for locked,warning,expected in [('n\n',log,'locked-native-net'),('',log,'resizer-no-progress'),('','','ordinary-or-clock')]:
            row=classify(graph,locked,warning,{'corner':report})['corner']
            self.assertEqual(row['unique_nets'],1);self.assertEqual(row['slew_rows'],3)
            self.assertEqual(row['nets_by_category'],{expected:1})
        with self.assertRaisesRegex(ValueError,'UNKNOWN_REPORTED_PIN'):
            classify(graph,'',log,{'corner':report.replace('sink/A','unknown/A')})
        with self.assertRaisesRegex(ValueError,'DRIVER_COUNT'):
            classify(graph+'C\textra\tcell\nP\textra\tZ\toutput\tn\n','',log,{'corner':report})
        escaped=graph.replace('driver','parent\\/driver')
        rows=classify(escaped,'',log.replace('driver/Z','parent/driver/Z'),{'corner':report.replace('driver','parent/driver')})
        self.assertEqual(rows['corner']['nets'][0]['driver'],'parent\\/driver/Z')
        self.assertEqual(rows['corner']['nets'][0]['category'],'resizer-no-progress')
        escaped=escaped.replace('\tn\n','\tparent\\/net\n')
        rows=classify(escaped,'',log.replace('net n ','net parent/net ').replace('driver/Z','parent/driver/Z'),
                      {'corner':report.replace('driver','parent/driver')})
        self.assertEqual(rows['corner']['nets'][0]['category'],'resizer-no-progress')
        with self.assertRaisesRegex(ValueError,'AMBIGUOUS_REPORT_PIN'):
            classify(escaped+'C\tparent/driver\tcell\nP\tparent/driver\tZ\toutput\tx\n','','',{})


if __name__=='__main__':unittest.main()

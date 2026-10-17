# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import json
from report_ack_activity import read_wakes, compare, matched_exports


def fixture(guard=32):
    lines=[]
    for retired,adc in ((0,0),(0,1),(43,0))*2:
        cycles=11 if retired else 0
        lines.extend((f'WAKE,2,100,90,{retired},{adc},123.0',
            f'ACK_GUARD,{cycles},{cycles},{cycles*2*guard:.3f},{guard:.3f}'))
    return '\n'.join([*lines,'ESTIMATE_ACTIVITY_COMPLETE','RISCAY_SOC_PASS'])


class AckActivityTest(unittest.TestCase):
    def parse(self,text,guard=32):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'simulation.log';path.write_text(text)
            return read_wakes(path,guard)

    def test_two_edges_and_zero_marginal_clock_cost(self):
        normal,summary=self.parse(fixture())
        bypass,_=self.parse(fixture(.001),.001)
        self.assertEqual(summary['firmware']['sum_wait_ns'],704)
        self.assertEqual(compare(normal,bypass),[dict(fast=0,work=0,ns=0)]*6)

    def test_missing_failed_and_unmatched_evidence(self):
        for old,new,error in (('RISCAY_SOC_PASS','','INCOMPLETE'),
                             ('RISCAY_SOC_PASS','FATAL: bad\nRISCAY_SOC_PASS','INCOMPLETE'),
                             ('ACK_GUARD,0,0,0.000,32.000\n','','ROW_COUNT'),
                             ('ACK_GUARD,11,11','ACK_GUARD,11,10','EDGE_ACCOUNTING'),
                             ('704.000','352.000','EDGE_ACCOUNTING'),
                             ('704.000','nan','EDGE_ACCOUNTING'),
                             ('32.000','31.000','EDGE_ACCOUNTING'),
                             ('90,43,0','90,42,0','WORKLOAD_CHANGED')):
            with self.subTest(error=error):
                with self.assertRaisesRegex(ValueError,'ACK_ACTIVITY_'+error):self.parse(fixture().replace(old,new,1))

    def test_comparison_requires_same_workload_in_same_order(self):
        a,_=self.parse(fixture());b=deepcopy(a);b[2]['rises']+=1
        with self.assertRaisesRegex(ValueError,'UNMATCHED_WORKLOAD'):compare(a,b)
        with self.assertRaisesRegex(ValueError,'UNMATCHED_WAKE_COUNT'):compare(a,b[:-1])

    def test_matched_export_check_allows_only_the_reviewed_override(self):
        with TemporaryDirectory() as folder:
            a,b=Path(folder)/'normal',Path(folder)/'bypass';a.mkdir();b.mkdir()
            for root in (a,b):
                for name in ('FourPhaseSoc.sv','contract.json','filelist.f'):(root/name).write_text(name)
            monitor='\n'.join(f'$realtime-{edge} {op} 32.0{sign}0.0005'
                for edge in ('ackRiseAt','ackFallAt') for op,sign in (('<','-'),('>','+')))
            monitor+='\nackRiseEdges,ackFallEdges,ackWaitNs,32.0);'
            (a/'testbench.sv').write_text('\n'+monitor)
            (b/'testbench.sv').write_text('defparam dut.soc.ca_child_control.ca_primitive_acknowledge_guard.DELAY_FS=1000;\n'+monitor.replace('32.0','0.001'))
            (a/'maximum-delays.json').write_text('{}')
            (b/'maximum-delays.json').write_text(json.dumps({'FourPhaseSoc.ca_child_control.ca_primitive_acknowledge_guard':'1000'}))
            self.assertEqual(len(matched_exports(a,b)),10)
            for file,error in (('FourPhaseSoc.sv','EXPORT_CHANGED'),('testbench.sv','HARNESS_CHANGED'),('filelist.f','EXPORT_CHANGED')):
                original=(b/file).read_text();(b/file).write_text(original+'changed')
                with self.assertRaisesRegex(ValueError,error):matched_exports(a,b)
                (b/file).write_text(original)
            (b/'maximum-delays.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'OVERRIDE_BINDING'):matched_exports(a,b)


if __name__=='__main__':unittest.main()

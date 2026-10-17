# SPDX-License-Identifier: Apache-2.0
import copy
import unittest
from check_pnr_clock import inventory,paths,verify_paths,expected_sinks,reconcile_sinks,sequential_pins
from gf180_physical import SC


def graph():
    def cell(kind,connection):
        return dict(type=SC+kind,connections={k:[v] for k,v in connection.items()},
                    directions={k:'output' if k in ('Z','ZN','Q') else 'input' for k in connection})
    return dict(ports={'work':dict(direction='input',bits=[0])},cells={
        'repair':cell('buf_4',dict(I=0,Z=1)),
        'cts':cell('clkbuf_8',dict(I=1,Z=2)),
        'sink':cell('dffrnq_1',dict(CLK=2,D=3,RN=4,Q=5))})


class ClockCoverage(unittest.TestCase):
    def test_generated_source_and_waveform_controls(self):
        text='\n'.join(['R\tservice\tserviceClock','R\twork\tgate/Z','R\tlf\twatchdogClock','R\ti2c_start\tsda',
            'G\tcreate_generated_clock -name work -source [get_ports {serviceClock}] -divide_by 1 [get_pins {gate/Z}]',
            'W\tservice\t5e-8\t0,2.5e-8','W\twork\t5e-8\t0,2.5e-8',
            'W\tlf\t0.08333333333333333\t0,0.041666666666666664','W\ti2c_start\t2.5e-6\t0,1.25e-6',
            *['P\t'+c+'\trise\t'+c+'/CLK' for c in ('service','work','lf','i2c_start')],
            *['M\twork\trise\tsram'+str(i)+'/CLK' for i in range(3)]])
        inventory(text)
        mutants=[text.replace('[get_ports {serviceClock}]','[get_ports {watchdogClock}]'),
                 text.replace('-divide_by 1','-divide_by 2'),text.replace('-divide_by 1','-divide_by 1 -invert'),
                 text.replace('W\twork\t5e-8','W\twork\t6e-8'),text.replace('0,2.5e-8','0,2e-8'),
                 '\n'.join(l for l in text.splitlines() if not l.startswith('G\t')),
                 '\n'.join(l for l in text.splitlines() if not l.startswith('W\twork\t'))]
        for bad in mutants:
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'CTS_'):inventory(bad)

    def test_sink_missing_from_both_sta_lists_is_rejected(self):
        g=graph();g['cells']['sink2']=copy.deepcopy(g['cells']['sink'])
        g['cells']['sink2']['connections']['Q']=[6]
        expected=expected_sinks(g,{'work':'work'},{SC+'dffrnq_1':('CLK','rise')},set())
        reported={('work','rise','sink/CLK')}
        # Equal before/after lists cannot hide an independently enumerated pin.
        for stage in ('before','after'):
            with self.subTest(stage=stage),self.assertRaisesRegex(ValueError,'STA_GRAPH_INVENTORY_MISMATCH'):
                reconcile_sinks(expected,reported)
        with self.assertRaisesRegex(ValueError,'STA_GRAPH_INVENTORY_MISMATCH'):
            reconcile_sinks(expected,expected|{('work','rise','not-a-clock/D')})

    def test_master_membership_does_not_reassign_generated_sinks(self):
        g=graph();g['ports']['service']=dict(direction='input',bits=[9])
        roots={'work':'work','service':'service'}
        expected=expected_sinks(g,roots,{SC+'dffrnq_1':('CLK','rise')},set())
        self.assertEqual(expected,{('work','rise','sink/CLK')})
        self.assertEqual(reconcile_sinks(expected,expected|{('service','rise','sink/CLK')}),expected)

    def test_native_exemption_never_hides_periodic_storage(self):
        with self.assertRaisesRegex(ValueError,'PERIODIC_NATIVE_STORAGE'):
            expected_sinks(graph(),{'work':'work'},{SC+'dffrnq_1':('CLK','rise')},{'sink'})
        g=graph();g['cells']['cts']['type']=SC+'and2_1'
        with self.assertRaisesRegex(ValueError,'PERIODIC_NATIVE_STORAGE'):
            expected_sinks(g,{'work':'work'},{SC+'dffrnq_1':('CLK','rise')},{'sink'})

    def test_liberty_edge_and_actual_inversion_compose(self):
        body='ff (IQ,IQN) {clocked_on : "(!CLKN)";} pin (CLKN) {clock : true;}'
        seq=sequential_pins([{SC+'dffnq_1':body}]*5)
        self.assertEqual(seq,{SC+'dffnq_1':('CLKN','fall')})
        g=graph();c=g['cells']['sink'];c['type']=SC+'dffnq_1'
        c['connections']['CLKN']=c['connections'].pop('CLK');c['directions']['CLKN']=c['directions'].pop('CLK')
        self.assertEqual(expected_sinks(g,{'work':'work'},seq,set()),{('work','fall','sink/CLKN')})
        g['cells']['cts']['type']=SC+'inv_4'
        self.assertEqual(expected_sinks(g,{'work':'work'},seq,set()),{('work','rise','sink/CLKN')})
        with self.assertRaisesRegex(ValueError,'CORNER_CLOCK_PINS_CHANGED'):
            sequential_pins([{SC+'dffnq_1':body},{SC+'dffnq_1':body.replace('!CLKN','CLKN')}])

    def test_existing_repair_buffer_cannot_hide_a_missing_cts_tree(self):
        g=graph();roots={'work':'work'};sinks={('work','rise','sink/CLK')}
        before=paths(g,roots,sinks,set())
        after=paths(g,roots,sinks,{'cts'})
        verify_paths(before,after)
        self.assertEqual(after[('work','rise','sink/CLK')]['created_buffers'],['cts'])
        with self.assertRaisesRegex(ValueError,'PERIODIC_SINK_NOT_CONSTRUCTED'):
            verify_paths(before,paths(g,roots,sinks,set()))

    def test_native_capture_or_sda_cannot_be_counted_as_periodic_cts(self):
        g=graph();roots={'i2c_start':'work'};sinks={('i2c_start','fall','sink/CLK')}
        before=paths(g,roots,sinks,set())
        verify_paths(before,before)
        with self.assertRaisesRegex(ValueError,'SDA_WAS_BUFFERED'):
            verify_paths(before,paths(g,roots,sinks,{'cts'}))

    def test_falling_launch_polarity_is_preserved(self):
        g=graph();roots={'work':'work'};sinks={('work','fall','sink/CLK')}
        before=paths(g,roots,sinks,set());g['cells']['cts']['type']=SC+'inv_4'
        g['cells']['cts']['connections']['ZN']=g['cells']['cts']['connections'].pop('Z')
        g['cells']['cts']['directions']['ZN']=g['cells']['cts']['directions'].pop('Z')
        with self.assertRaisesRegex(ValueError,'CLOCK_POLARITY_CHANGED'):
            verify_paths(before,paths(g,roots,sinks,{'cts'}))

    def test_missing_disconnected_multidriver_and_logic_paths_fail(self):
        base=graph();roots={'work':'work'};sinks={('work','rise','sink/CLK')}
        bad=copy.deepcopy(base);bad['cells']['cts']['connections']['I']=[99]
        with self.assertRaisesRegex(ValueError,'DISCONNECTED_OR_CYCLIC'):paths(bad,roots,sinks,{'cts'})
        bad=copy.deepcopy(base);bad['cells']['copy']=copy.deepcopy(bad['cells']['cts'])
        with self.assertRaisesRegex(ValueError,'MULTIPLE_DRIVERS'):paths(bad,roots,sinks,{'cts'})
        bad=copy.deepcopy(base);bad['cells']['cts']['type']=SC+'and2_1'
        with self.assertRaisesRegex(ValueError,'UNREVIEWED_CLOCK_LOGIC'):paths(bad,roots,sinks,{'cts'})
        with self.assertRaisesRegex(ValueError,'MISSING_PIN'):paths(base,roots,{('work','rise','missing/CLK')},{'cts'})


if __name__=='__main__':unittest.main()

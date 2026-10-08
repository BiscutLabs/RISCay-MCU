# SPDX-License-Identifier: Apache-2.0
"""Synthetic negative controls independent of the SPICE circuits."""
import importlib.util
from pathlib import Path
import sys
import unittest

BASE=Path(__file__).resolve().parents[1]/'analog/gf180-clock-reset'
sys.path.insert(0,str(BASE))
spec=importlib.util.spec_from_file_location('clock_reset_characterize',BASE/'characterize.py')
c=importlib.util.module_from_spec(spec); sys.modules[spec.name]=c; spec.loader.exec_module(c)


def clock(period=100):
    rows=[]
    for ns in range(10001):
        active=(2100<=ns<5000 or 7100<=ns)
        high=active and (ns-2100)%period<period//2
        rows.append((ns*1e-9,3.3 if high else 0,0,0,3.3,-1e-6))
    return rows


class ClockResetMeasurementTest(unittest.TestCase):
    def test_independent_clock(self):
        self.assertAlmostEqual(c.check_clock(clock(),c.Case('test','clock'))['hz'],1e7,delta=1)

    def test_inactive_and_incomplete_waveforms_are_rejected(self):
        for rows,reason in ((clock()[:10],'INCOMPLETE_WAVEFORM'),
                            ([(r[0],0,*r[2:]) for r in clock()],'NO_SUSTAINED_CLOCK')):
            with self.assertRaisesRegex(ValueError,reason): c.check_clock(rows,c.Case('test','clock'))

    def test_frequency_and_runt_pulse_controls(self):
        with self.assertRaisesRegex(ValueError,'FREQUENCY_CONTRACT'):
            c.check_clock(clock(25),c.Case('test','clock'))
        rows=clock()
        for ns in range(200,210): rows[ns]=(rows[ns][0],3.3,*rows[ns][2:])
        with self.assertRaisesRegex(ValueError,'RUNT_HIGH_PULSE'):
            c.check_clock(rows,c.Case('test','clock'))

    def test_unsafe_low_supply_pulse_cannot_hide_in_startup(self):
        case=c.Case('test','monitor',profile='plateau',voltage=2.7)
        rows=[(0,0,1.17,0,2.7,0),(.0001,2.7,1.17,0,2.7,0),
              (.0022,2.7,1.17,0,2.7,0),(.0025,0,1.17,0,2.7,0),(.012,0,1.17,0,2.7,0)]
        with self.assertRaisesRegex(ValueError,'UNSAFE_STARTUP_PULSE'): c.check_monitor(rows,case)

    def test_brownout_must_be_observed(self):
        rows=[(i*.0001,3.3,1.17,0,3.3,0) for i in range(122)]
        with self.assertRaisesRegex(ValueError,'BROWNOUT_RESPONSE'):
            c.check_monitor(rows,c.Case('test','monitor',profile='dip'))


if __name__=='__main__': unittest.main()

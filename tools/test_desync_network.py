# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import random
import unittest
from unittest.mock import patch
from desync_network import EventModel, connections
from primitives import resolve_candidate, classified_cells
from gf180_netgraph import graph
from desync_assemble import assemble
from audit_desync_protection import audit


def fixture():
    banks=('cpu','fabric','power')
    return dict(banks=dict.fromkeys(banks),bank_phases=dict.fromkeys(banks,'rise'),
        registers=[dict(bank=b,transformed=True,falling=False) for b in banks],macros=[],
        phase_edges=[dict(source=a,target=b,source_phase='rise',target_phase='rise',role='data',witnesses=['q->d'])
                     for a in banks for b in banks])


class NetworkTests(unittest.TestCase):
    def test_assembly_connects_registered_controls_but_cannot_bypass_missing_delays(self):
        part=fixture();top=dict(ports={},netnames={},cells={})
        for i,n in enumerate(('serviceClock','serviceClockEnable','resetHold/unsafe_supply',
                             'desync_cpu_capture','desync_fabric_m','desync_fabric_s','desync_power_m','desync_power_s')):
            top['netnames'][n]=dict(bits=[i+2],attributes={})
            if '/' not in n:top['ports'][n]=dict(direction='input',bits=[i+2])
        storage=dict(modules={'RiscayMcuDigital':top})
        original=deepcopy(storage)
        transform=dict(status='storage-scaffold-only',partition=part)
        with self.assertRaisesRegex(ValueError,'MEASURED_BANK_DELAYS_REQUIRED'):
            assemble(storage,transform)
        result,report=assemble(storage,transform,timing_preparation=True)
        self.assertFalse(report['complete_chip_area'])
        self.assertFalse(report['physical_qualification'])
        self.assertEqual({r['bank'] for r in report['delays']},set(part['banks']))
        self.assertEqual(report['storage_roots']['cpu']['capture'],top['ports']['desync_cpu_capture']['bits'])
        self.assertNotEqual(report['storage_roots']['cpu']['capture'],report['controller_roots']['cpu']['m'])
        mapped=result['modules']['RiscayMcuDigital']
        self.assertFalse(set(mapped['cells'])&set(mapped['netnames']))
        self.assertFalse(set(top['ports'])&set(mapped['ports'])-{'serviceClock','serviceClockEnable'})
        self.assertEqual(audit(result,report['bindings'],experimental=True)['status'],'pass')
        self.assertEqual(storage,original)
        # A damaged actual leaf must fail; binding declarations alone are not
        # accepted as evidence that the generator connected the recipe.
        bad=deepcopy(result)
        cell=next(c for c in bad['modules']['RiscayMcuDigital']['cells'].values()
                  if 'I' in c['connections'])
        cell['connections']['I']=['0']
        with self.assertRaisesRegex(ValueError,'PRIMITIVE_CONNECTIVITY'):
            audit(bad,report['bindings'],experimental=True)
        # Recipe constants are literal bits, never fresh undriven aliases.
        def with_constant(name,parameters):
            r=resolve_candidate(name,parameters)
            if name=='RiscayDesyncCaptureJoin':r['cells'][0]['pins']['A1']='0'
            return r
        with patch('desync_assemble.resolve_candidate',side_effect=with_constant):
            literal,_=assemble(storage,transform,timing_preparation=True)
        self.assertEqual(literal['modules']['RiscayMcuDigital']['cells'][
            'desync_control/cpu.capture/ready__cell']['connections']['A1'],['0'])

    def test_running_stop_and_early_wake_respect_the_independent_graph(self):
        for seed in range(8):
            m=EventModel(fixture());rng=random.Random(seed)
            for _ in range(1000):self.assertTrue(m.step(rng))
            m.state['run']=0
            for _ in range(1000):
                if not m.step(rng):break
            else:self.fail('stop did not drain')
            self.assertEqual(m.state['grant1'],1)
            m.state['run']=1
            for _ in range(1000):self.assertTrue(m.step(rng))
        m=EventModel(fixture());m.state.update(run=0,stopPending=0,grant1=0)
        self.assertEqual(m.func['stopPending'](m.state),1)
        m.state.update(run=1,stopPending=1)
        self.assertEqual(m.func['stopPending'](m.state),1)
        m.state['grant1']=1
        self.assertEqual(m.func['stopPending'](m.state),0)

    def test_request_waits_for_actual_enable_return_and_missing_join_is_detected(self):
        m=EventModel(fixture());m.state.update({'fabric.m.A':1,'fabric.m.N':1,'fabric.m.B':0})
        self.assertEqual(m.func['fabric.m.B'](m.state),0)
        # Destroy an actual handshake cause; the independent marked graph
        # catches the illicit capture, rather than merely checking a count.
        m.func['fabric.m.A']=lambda s:1-s['fabric.m.A']
        rng=random.Random(7)
        with self.assertRaisesRegex(ValueError,'CONTROLLER_ORDER'):
            for _ in range(10000):m.step(rng)

    def test_registry_owns_parameterized_ports_and_leaf_identity(self):
        recipe=resolve_candidate('RiscayDesyncQualifiedController',dict(initial_open=True,same_count=2,closed_count=1))
        b=dict(instance='dut',primitive=recipe['primitive'],parameters=dict(initial_open=True,same_count=2,closed_count=1),
               ports=dict.fromkeys(recipe['ports']),cells=recipe['cells'])
        self.assertTrue(classified_cells([b],experimental=True))
        with self.assertRaisesRegex(ValueError,'RECIPE_UNAVAILABLE'):classified_cells([b])
        bad=deepcopy(b);bad['cells'][0]['pins']['I']='wrong'
        with self.assertRaisesRegex(ValueError,'RECIPE_CHANGED'):classified_cells([bad],experimental=True)

    def test_external_cell_is_a_leaf_without_a_second_primitive_catalogue(self):
        modules={'RiscayMcuDigital':dict(ports={},netnames={},cells={
            'dut':dict(type='external',connections=dict(A=[2],Q=[3]))}),
            'external':dict(attributes={'blackbox':'1'},ports=dict(A=dict(bits=[2]),Q=dict(bits=[3])),netnames={},cells={})}
        cells,_=graph(modules)
        self.assertEqual(cells['dut']['type'],'external')


if __name__=='__main__':unittest.main()

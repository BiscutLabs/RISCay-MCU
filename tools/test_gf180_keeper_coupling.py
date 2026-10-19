# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import check_gf180_keeper_coupling as k


def fixture():
    binding = dict(model='ChiselAsyncAsymmetricC_v1',instances=['owner'],parameters=dict(
        COMMON=1,COMMON_INVERT=0,RISING=1,RISING_INVERT=0,FALLING=0,FALLING_INVERT=0,RESET_VALUE=0),
        ports=[dict(name=p,width=1,direction='input') for p in ('common','rising','falling','reset')]+[
            dict(name='q',width=1,direction='output')],
        cells=[dict(name='u0',cell='and',pins=dict(A='common[0]',B='rising[0]',Z='n0')),
               dict(name='u1',cell='aoi',pins=dict(A='state',B='common[0]',C='n0',ZN='next_n')),
               dict(name='u2',cell='nor',pins=dict(A='next_n',B='reset',ZN='state')),
               dict(name='u3',cell='buf',pins=dict(I='state',Z='q'))])
    cells={}; nets={}
    for c in binding['cells']:
        name='root/'+c['name']; cells[name]=dict(master=c['cell'],pins=c['pins'],directions={})
        for pin,net in c['pins'].items():
            direction='output' if pin in ('Z','ZN') else 'input'
            cells[name]['directions'][pin]=direction
            nets.setdefault(net,[]).append(dict(pin=name+':'+pin,direction=direction,master=c['cell'],port=pin))
    for p in ('common[0]','rising[0]','reset'):
        nets[p].append(dict(pin='boundary:'+p,direction='output',master='buf',port='Z'))
    nets['q'].append(dict(pin='sink:I',direction='input',master='buf',port='I'))
    return dict(bindings=[binding]),dict(adapter_instances=dict(owner='root')),cells,nets


def measurements(values=None):
    result={key+'_'+suffix:0. for key in ('q','state','victim0') for suffix in ('before','after','min','max')}
    result.update(values or {})
    return '\n'.join(f'{key} = {v}' for key,v in result.items())


def cluster_fixture():
    plan=k.bind_owner(*fixture(),'owner','state'); networks={}
    for i,(net,terms) in enumerate(plan['terminals'].items()):
        connections=[dict(node=f'{i}:{j}',pin=t['pin'],kind='*I',direction='O' if t['direction']=='output' else 'I') for j,t in enumerate(terms)]
        driver=next(c['node'] for c in connections if c['direction']=='O')
        networks[net]=dict(name=net,connections=connections,ground={driver:.01},
            resistors=[(driver,c['node'],10.) for c in connections if c['direction']=='I'],coupling=[])
    a=networks['state']['connections'][0]['node']; b=networks['next_n']['connections'][0]['node']
    networks['state']['coupling']=[(a,b,.002,'next_n'),(a,'external:1',.003,'aggressor')]
    networks['next_n']['coupling']=[(b,a,.002,'state')]
    return plan,k.bind_networks(plan,dict(networks=networks,missing=[]))


class KeeperCouplingTests(unittest.TestCase):
    def test_history_is_reached_through_gray_walk_both_states(self):
        b=fixture()[0]['bindings'][0]; histories=k.holding_sequences(b)
        self.assertEqual(set(histories['sequences']),{'0','1'})
        for q,events in histories['sequences'].items():
            self.assertEqual(events[0][0]['reset'],1)
            self.assertEqual(events[-1],(histories['inputs'],int(q)))

    def test_actual_owner_and_internal_victim_required(self):
        values=fixture(); plan=k.bind_owner(*values,'owner','state')
        self.assertEqual(len(plan['cells']),4)
        with self.assertRaisesRegex(ValueError,'KEEPER_VICTIM_NOT_INTERNAL'):
            k.bind_owner(*values,'owner','q')
        broken=deepcopy(values); broken[2]['root/u1']['master']='other'
        with self.assertRaisesRegex(ValueError,'KEEPER_ACTUAL_CELL_MISMATCH'):
            k.bind_owner(*broken,'owner','state')

    def test_hotspot_selection_uses_measured_external_coupling(self):
        values=fixture()
        rows=[dict(net=n,ground_pf=.01,coupling_pf=c,aggressors=[dict(net=a,coupling_pf=c)])
              for n,c,a in [('state',.8,'next_n'),('next_n',.03,'outside'),('n0',.02,'outside'),('q',5.,'outside')]]
        chosen=k.eligible_hotspots(*values,rows)
        self.assertEqual([r['net'] for r in chosen['ranked']],['next_n','n0'])
        broken=deepcopy(values); broken[3]['next_n'].append(dict(pin='outside:I',direction='input',master='buf',port='I'))
        with self.assertRaisesRegex(ValueError,'KEEPER_EXTERNAL_INTERNAL_NET'):
            k.bind_owner(*broken,'owner','state')

    def test_spurious_output_and_retained_change_fail_analog_does_not(self):
        observed=dict(q='n0',state='n1',victim0='n2')
        analog=k.evaluate(measurements(dict(victim0_max=2.,state_max=2.)),observed,0,3.3)
        self.assertEqual(analog['verdict'],'analog-excursion-only')
        self.assertTrue(analog['internal_state_marker_crossed'])
        for values in (dict(q_max=2.),dict(state_max=3.3,state_after=3.3)):
            row=k.evaluate(measurements(values),observed,0,3.3)
            self.assertEqual(row['verdict'],'observed-spurious-owner-transition')
        with self.assertRaisesRegex(ValueError,'KEEPER_INITIAL_HISTORY_UNSETTLED'):
            k.evaluate(measurements(dict(q_before=1.)),observed,0,3.3)
        with self.assertRaisesRegex(ValueError,'KEEPER_MEASUREMENTS_INCOMPLETE'):
            k.evaluate(measurements().replace('q_max = 0.0',''),observed,0,3.3)
        unsettled=k.evaluate(measurements(dict(q_max=1.,q_after=1.)),observed,0,3.3)
        self.assertEqual(unsettled['verdict'],'unresolved-final-state')
        self.assertFalse(unsettled['final_state_settled'])
        crossed=k.evaluate(measurements(dict(q_max=2.,q_after=1.)),observed,0,3.3)
        self.assertEqual(crossed['verdict'],'observed-spurious-owner-transition')
        self.assertFalse(crossed['final_state_settled'])

    def test_external_loads_use_exact_pvt_pin_capacitance(self):
        cluster=dict(external_loads=dict(n1=dict(master='buf',port='I')))
        self.assertEqual(k.external_caps(cluster,dict(buf='pin(I) { capacitance : 0.003; }')),dict(n1=.003))
        with self.assertRaisesRegex(ValueError,'KEEPER_EXTERNAL_MASTER_NOT_LOADED'):
            k.external_caps(cluster,{})

    def test_spice_binding_missing_terminal_is_not_waived(self):
        plan=k.bind_owner(*fixture(),'owner','state')
        parsed=dict(networks={n:dict(connections=[],resistors=[],coupling=[]) for n in plan['logical'].values()},missing=[])
        with self.assertRaisesRegex(ValueError,'KEEPER_SPEF_TERMINAL_MISMATCH'):
            k.bind_networks(plan,parsed)

    def test_internal_coupling_reciprocity_and_multiplicity_required(self):
        plan,cluster=cluster_fixture(); parsed=dict(networks=deepcopy(cluster['networks']),missing=[])
        parsed['networks']['state']['coupling'].append(parsed['networks']['state']['coupling'][0])
        with self.assertRaisesRegex(ValueError,'KEEPER_NONRECIPROCAL_INTERNAL_COUPLING'):
            k.bind_networks(plan,parsed)
        parsed['networks']['next_n']['coupling'].append(parsed['networks']['next_n']['coupling'][0])
        self.assertTrue(k.bind_networks(plan,parsed))

    def test_deck_keeps_transistors_feedback_and_one_physical_coupler(self):
        plan,cluster=cluster_fixture()
        with TemporaryDirectory() as tmp:
            pdk=Path(tmp)
            (pdk/'gf180mcu_fd_sc_mcu7t5v0.spice').write_text('\n'.join(
                '.SUBCKT '+master+' '+pins+' VDD VNW VPW VSS\n.ENDS'
                for master,pins in [('and','A B Z'),('aoi','A B C ZN'),('nor','A B ZN'),('buf','I Z')]))
            text,observed=k.deck(plan,cluster,pdk,k.CORNERS[0],dict.fromkeys(cluster['external_loads'],.003),0,.02,'rise')
        self.assertEqual(sum(line.startswith('X') for line in text.splitlines()),4)
        # Two reciprocal SPEF rows are one physical capacitor, including feedback coupling.
        self.assertEqual(sum(line.startswith('C') and line.endswith(' 0.002p') for line in text.splitlines()),1)
        self.assertIn('PWL(0 0.0',text)
        self.assertEqual(set(observed),{'q','state','victim0','victim1','victim2'})
        self.assertNotIn('.ic ',text)

    def test_named_connectivity_rejects_normalization_collision(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'inventory.tsv'
            path.write_text('C\ta\\/b\tbuf\nC\ta/b\tbuf\n')
            with self.assertRaisesRegex(ValueError,'KEEPER_CELL_INVENTORY'):
                k.connectivity(path)


if __name__ == '__main__':
    unittest.main()

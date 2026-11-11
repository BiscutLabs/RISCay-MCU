# SPDX-License-Identifier: Apache-2.0
from copy import deepcopy
import unittest
from measure_desync_feedback import prepare, check_wave, check_measurements, run
from primitives import resolve_candidate
from test_desync_handoff import cell


class FeedbackTests(unittest.TestCase):
    def fixture(self):
        parameters=dict(initial_open=True,same_count=0,closed_count=0,rise_qualified=False)
        source=dict(instance='desync_control/x.m',primitive='RiscayDesyncQualifiedController',parameters=parameters,
                    ports={'acknowledgeIn':'x.s.A'})
        target=dict(instance='desync_control/x.s',ports={'acknowledgeOut':'x.s.A'})
        nets={};cells={}
        def bit(n):return nets.setdefault(n,len(nets)+10)
        for c in resolve_candidate(source['primitive'],parameters)['cells']:
            cells[source['instance']+'/'+c['name']]=cell(c['cell'].split('__')[1],
                {p:bit(n) for p,n in c['pins'].items() if p not in ('Z','ZN')},
                {p:bit(n) for p,n in c['pins'].items() if p in ('Z','ZN')})
        root=nets['acknowledgeIn'];se=bit('slaveEnable')
        cells[target['instance']+'/enable_invert__cell']=cell('inv_1',{'I':root},{'ZN':se})
        # Source D aliases the slave output, as in a real synchronizer chain.
        cells['m']=cell('latq_1',{'D':101,'E':nets['enable']},{'Q':100})
        cells['s']=cell('latq_1',{'D':100,'E':se},{'Q':101})
        roots={source['instance']+'/enable':'mr',target['instance']+'/enable':'sr'}
        routes={'m/E':dict(root='mr',arcs=[]),'s/E':dict(root='sr',arcs=[])}
        return dict(cells=cells),[source,target],roots,routes,'x'

    def test_actual_feedback_preserved_and_data_cut_load_restored(self):
        args=self.fixture();f=prepare(*args)
        self.assertEqual(f['pairs'],[('m/Q','s/D')])
        self.assertEqual(f['cells']['m']['connections']['D'],['data'])
        self.assertEqual(f['loads'][101],[dict(cell='m',type=f['cells']['m']['type'],pin='D')])
        for n,c in f['cells'].items():
            if n.startswith('desync_control/'):
                self.assertEqual(c,args[0]['cells'][n])
        del args[3]['m/E']
        with self.assertRaisesRegex(ValueError,'TREE_INVENTORY'):prepare(*args)

    def test_cannot_silently_substitute_cut_feedback_or_another_controller(self):
        args=self.fixture()
        args[0]['cells']['desync_control/x.m/ack_keeper__cell']['connections']['A1']=[999]
        with self.assertRaisesRegex(ValueError,'NATIVE_WIRING'):prepare(*args)
        args=self.fixture();args[1][0]['parameters']['same_count']=1
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_CONTROLLER'):prepare(*args)

    def test_ack_must_come_from_receiver_not_sender_feedback(self):
        args=self.fixture();cells=args[0]['cells'];prefix='desync_control/x.m/'
        bit=cells[prefix+'reset_state__cell']['connections']['ZN'][0]
        cells[prefix+'request_hold__cell']['connections']['A3']=[bit]
        cells[prefix+'request_keeper__cell']['connections']['A1']=[bit]
        with self.assertRaisesRegex(ValueError,'ACK_FRONTIER'):prepare(*args)

    def measured(self,old):
        return '\n'.join([f'{p}0_{bound} = {old}' for p in ('m','s') for bound in ('min','max')]+
                         [f'm0_end = {1-old}',f's0_end = {old}','q0_time = 1.7e-7'])

    def test_every_bit_retains_old_and_source_really_reuses(self):
        for old in (0,1):
            good=self.measured(old);self.assertEqual(check_measurements(good,1,old,1),[170])
            for broken in (good.replace(f's0_max = {old}',f's0_max = {1-old}'),
                           good.replace(f'm0_end = {1-old}',f'm0_end = {old}'),
                           good.replace('q0_time = 1.7e-7','q0_time = 1.5e-7'),
                           good+'\ns0_end = 0',good+'\nWarning: ignored annotation'):
                with self.assertRaises(ValueError):check_measurements(broken,1,old,1)
            with self.assertRaisesRegex(ValueError,'COVERAGE'):check_measurements(good,2,old,1)

    def wave(self):
        f=dict(source_nets=dict(acknowledgeOut=1,requestOut=2,enable=3),ends={4:True,5:False})
        rows=[]
        for i in range(2101):
            t=i/10
            rows.append([t*1e-9,int(41<=t<162),int(82<=t<162.5),int(t<41.2 or t>=163),
                         int(t<42 or t>=164),int(81<=t<162)])
        return rows,[1,2,3,4,5],f,1,.1

    def test_legal_history_and_complete_retained_edges(self):
        args=self.wave();self.assertEqual(set(check_wave(*args)),{1,2,3,4,5})
        for mutation in ('recross','early','history','missing','keeper'):
            args=deepcopy(self.wave())
            if mutation=='recross':args[0][1700][4]=0
            elif mutation=='early':args[0][1250][4]=1
            elif mutation=='history':args[0][700][1]=0
            elif mutation=='keeper':args[0][1250][1]=0
            else:del args[0][1700]
            with self.assertRaises(ValueError):check_wave(*args)

    def test_invalid_or_empty_campaign_fails_before_work(self):
        for step,late,corners in ((.3,0,[]),(.2,float('nan'),[]),(.2,0,[])):
            with self.assertRaisesRegex(ValueError,'POLICY|INVENTORY'):
                run(None,None,None,None,None,'i2c',step,late,corners,[.02],[0])


if __name__=='__main__':unittest.main()

# SPDX-License-Identifier: Apache-2.0
import unittest
from copy import deepcopy

from native_allowance_audit import FanoutIndex, audit_elaborated
from passive_allowance_policy import PASSIVE, data_specs, return_policy

SC='gf180mcu_fd_sc_mcu7t5v0__'

def fixture():
    bit=lambda n: ('top/',n)
    graph=dict(cells={
        'top/data/u0':dict(type=SC+'buf_1',directions=dict(I='input',Z='output'),connections=dict(I=[bit(1)],Z=[bit(2)])),
        'top/store/u0':dict(type=SC+'dffrnq_1',directions=dict(D='input',CLK='input',RN='input',Q='output'),
            connections=dict(D=[bit(2)],CLK=[bit(3)],RN=[bit(4)],Q=[bit(5)]))},
        ports={},boundaries={'top/data/a':[bit(1)],'top/data/q':[bit(2)],'top/data/reset':[bit(4)],
         'top/store/d':[bit(2)],'top/store/trigger':[bit(3)],'top/store/reset':[bit(4)],'top/store/q':[bit(5)]})
    def port(n,d,w=1):return dict(name=n,direction=d,width=w)
    mapping=dict(bindings=[
        dict(model='ChiselAsyncControlGate_v1',parameters=dict(WIDTH='1',DELAY_FS='10000000',OP='0',RESET_VALUE='0'),
             requirements=dict(role='whole-transform-allowance'),instances=['Top.data'],cells=[dict(name='u0',pins=dict(I='a',Z='q'))],
             ports=[port('a','input'),port('reset','input'),port('q','output')]),
        dict(model='ChiselAsyncEventRegister_v1',parameters=dict(WIDTH='1'),requirements={},instances=['Top.store'],
             cells=[dict(name='u0',pins=dict(D='d',CLK='trigger',RN='reset',Q='q'))],
             ports=[port('d','input'),port('trigger','input'),port('reset','input'),port('q','output')])])
    audit=dict(adapter_instances={'Top.data':'top/data','Top.store':'top/store'})
    return graph,mapping,audit


class AllowanceAuditSpec(unittest.TestCase):
    def test_data_terminates_at_real_native_storage(self):
        result=FanoutIndex(*fixture()).trace_sinks('Top.data')
        self.assertEqual(result['storage_data_sinks'][0]['leaf_pins'],['top/store/u0/D'])
        self.assertEqual(result['maximum_output_leaf_fanout'],1)
        self.assertFalse(result['escapes'])

    def test_real_control_pin_escape_rejected(self):
        g,m,a=fixture();g['boundaries']['top/store/trigger']=[('top/',2)]
        with self.assertRaisesRegex(ValueError,'ALLOWANCE_AUDIT_INVALID_DATA_ESCAPE:Top.data'):
            FanoutIndex(g,m,a).trace_sinks('Top.data')

    def test_periodic_storage_is_not_an_exemption(self):
        g,m,a=fixture();g['cells']['periodic']=dict(type=SC+'dffrnq_1',directions=dict(D='input',CLK='input',Q='output'),
            connections=dict(D=[('top/',2)],CLK=[('top/',20)],Q=[('top/',21)]))
        with self.assertRaisesRegex(ValueError,'ALLOWANCE_AUDIT_INVALID_DATA_ESCAPE:Top.data'):
            FanoutIndex(g,m,a).trace_sinks('Top.data')

    def test_functional_top_output_escape_rejected(self):
        g,m,a=fixture();g['ports']['sdaLow']=dict(direction='output',bits=[('top/',2)])
        with self.assertRaisesRegex(ValueError,'ALLOWANCE_AUDIT_INVALID_DATA_ESCAPE:Top.data'):
            FanoutIndex(g,m,a).trace_sinks('Top.data')

    def test_combinational_path_to_storage_is_audited(self):
        g,m,a=fixture();g['cells']['mux']=dict(type=SC+'mux2_1',directions=dict(I='input',Z='output'),
            connections=dict(I=[('top/',2)],Z=[('top/',22)]))
        g['boundaries']['top/store/d']=[('top/',22)];g['cells']['top/store/u0']['connections']['D']=[('top/',22)]
        result=FanoutIndex(g,m,a).trace_sinks('Top.data')
        self.assertEqual(result['combinational_cells'],['mux'])
        self.assertEqual(len(result['storage_data_sinks']),1)

    def test_missing_capture_reset_rejected(self):
        g,m,a=fixture();del g['boundaries']['top/store/reset']
        with self.assertRaisesRegex(ValueError,'ALLOWANCE_AUDIT_MISSING_LIVE_PORT'):
            FanoutIndex(g,m,a)

    def test_alias_source_fanout_is_reported_not_silently_approved(self):
        g,m,a=fixture();g['boundaries']['top/store/trigger']=[('top/',2)]
        result=FanoutIndex(g,m,a).trace_sinks('Top.data',require_capture_only=False)
        self.assertEqual(result['disposition'],'source-alias-fanout-or-escape')
        self.assertTrue(result['escapes'])

    def test_passive_policy_changes_only_named_data_model(self):
        expected={'data_delay':('ChiselAsyncControlGate_v1',dict(WIDTH='8',OP='0',RESET_VALUE='0',DELAY_FS='10000000')),
            'request_delay':('ChiselAsyncControlGate_v1',dict(WIDTH='1',OP='0',RESET_VALUE='0',DELAY_FS='11000000'))}
        node={'primitives':[dict(id='data_delay',model=PASSIVE),dict(id='request_delay',model=PASSIVE)]}
        result=data_specs(node,expected)
        self.assertEqual(result['data_delay'],(PASSIVE,dict(WIDTH='8',DELAY_FS='10000000')))
        self.assertEqual(result['request_delay'],expected['request_delay'])
        self.assertEqual(expected['data_delay'][0],'ChiselAsyncControlGate_v1')

    def test_nonbuffer_data_model_rejected(self):
        node={'primitives':[dict(id='data_delay',model=PASSIVE)]}
        with self.assertRaisesRegex(ValueError,'PASSIVE_NOT_DATA_BUFFER'):
            data_specs(node,{'data_delay':('ChiselAsyncControlGate_v1',dict(WIDTH='1',OP='1',RESET_VALUE='1',DELAY_FS='10000000'))})


class ElaboratedAllowanceSpec(unittest.TestCase):
    def fixture(self):
        def cell(kind, connections, directions):
            return dict(type=kind, connections=connections, port_directions=directions)
        cells={'data':cell(PASSIVE,{'a':[1],'q':[2]},{'a':'input','q':'output'}),
            'store':cell('ChiselAsyncEventRegister_v1',{'d':[2],'trigger':[3],'reset':[4],'q':[5]},
                         {'d':'input','trigger':'input','reset':'input','q':'output'})}
        manifest={'top':'Top','design':{'children':[], 'primitives':[
            dict(rtl_path='Top.data',model=PASSIVE,parameters={'WIDTH':'1'}),
            dict(rtl_path='Top.store',model='ChiselAsyncEventRegister_v1')]}}
        return {'modules':{'Top':{'cells':cells,'ports':{}}}},manifest

    def test_actual_primitive_d_and_capture_identity(self):
        db,m=self.fixture();r=audit_elaborated(db,m)
        self.assertEqual(r['instance_count'],1)
        self.assertEqual(r['instances'][0]['capture_sinks'][0]['event_pin'],'Top.store.trigger')
        self.assertEqual(r['instances'][0]['capture_sinks'][0]['source_lanes'],[0])
        self.assertIsNone(r['instances'][0]['capture_sinks'][0]['constant_value'])

    def test_constant_and_dynamic_lanes_have_separate_provenance(self):
        db,m=self.fixture();cells=db['modules']['Top']['cells']
        cells['data']['connections'].update(a=['1',1],q=[2,6])
        cells['store']['connections'].update(d=[2,6],q=[5,7])
        m['design']['primitives'][0]['parameters']['WIDTH']='2'
        sinks=audit_elaborated(db,m)['instances'][0]['capture_sinks']
        self.assertEqual([(s['lane'],s['source_lanes'],s['constant_value']) for s in sinks],
                         [(0,[0],1),(1,[1],None)])

    def test_literal_through_mux_is_proved_without_select_assumptions(self):
        db,m=self.fixture();cells=db['modules']['Top']['cells']
        cells['data']['connections']['a']=['1']
        cells['store']['connections']['d']=[8]
        cells['mux']=dict(type='$mux',connections={'A':[2],'B':['1'],'S':[9],'Y':[8]},
                          port_directions={'A':'input','B':'input','S':'input','Y':'output'})
        sink=audit_elaborated(db,m)['instances'][0]['capture_sinks'][0]
        self.assertEqual(sink['constant_value'],1)
        cells['mux']['connections']['B']=['0']
        sink=audit_elaborated(db,m)['instances'][0]['capture_sinks'][0]
        self.assertIsNone(sink['constant_value'])

    def test_sign_extension_cannot_escape_to_control_or_output(self):
        for encoded in ('1','00000000000000000000000000000001'):
            for destination in ('control','output'):
                with self.subTest(encoded=encoded,destination=destination):
                    db,m=self.fixture();body=db['modules']['Top'];cells=body['cells']
                    cells['sign']=dict(type='$pos',connections={'A':[2],'Y':[10,11]},
                        port_directions={'A':'input','Y':'output'},parameters={'A_SIGNED':encoded})
                    if destination=='control': cells['store']['connections']['trigger']=[11]
                    else: body['ports']['escape']=dict(direction='output',bits=[11])
                    with self.assertRaisesRegex(ValueError,'ELABORATED_INVALID_DATA_ESCAPE:data'):
                        audit_elaborated(db,m)

    def test_signed_binary_dependencies_remain_conservative(self):
        db,m=self.fixture();cells=db['modules']['Top']['cells']
        cells['binary']=dict(type='$or',connections={'A':[2],'B':['0','0'],'Y':[10,11]},
            port_directions={'A':'input','B':'input','Y':'output'},
            parameters={'A_SIGNED':'0001','B_SIGNED':'0000'})
        db['modules']['Top']['ports']['escape']=dict(direction='output',bits=[11])
        with self.assertRaisesRegex(ValueError,'ELABORATED_INVALID_DATA_ESCAPE:data'):
            audit_elaborated(db,m)

    def test_actual_source_reset_pin_fault_is_rejected(self):
        db,m=self.fixture();db['modules']['Top']['cells']['store']['connections']['reset']=[2]
        with self.assertRaisesRegex(ValueError,'ELABORATED_INVALID_DATA_ESCAPE:data'):
            audit_elaborated(db,m)

    def test_actual_periodic_consumer_is_rejected(self):
        db,m=self.fixture();db['modules']['Top']['cells']['ff']={
            'type':'$dff','connections':{'D':[2],'CLK':[7],'Q':[8]},
            'port_directions':{'D':'input','CLK':'input','Q':'output'}}
        with self.assertRaisesRegex(ValueError,'ELABORATED_INVALID_DATA_ESCAPE:data'):
            audit_elaborated(db,m)

    def test_actual_unknown_comb_cell_is_rejected(self):
        db,m=self.fixture();db['modules']['Top']['cells']['unknown']={
            'type':'unreviewed','connections':{'a':[2],'q':[9]},'port_directions':{'a':'input','q':'output'}}
        with self.assertRaisesRegex(ValueError,'ELABORATED_INVALID_DATA_ESCAPE:data'):
            audit_elaborated(db,m)


if __name__=='__main__':unittest.main()

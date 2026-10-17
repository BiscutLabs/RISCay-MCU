# SPDX-License-Identifier: Apache-2.0
"""Reject collateral wiring/recipe changes in the bounded A8b experiment."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import experiment_passive_stage as e


def fixture():
    ports=dict(reset=dict(direction='input',bits=[2]),
               a=dict(direction='input',bits=list(range(3,104))),
               b=dict(direction='input',bits=['0']*101),
               q=dict(direction='output',bits=list(range(205,306))))
    directions={p:v['direction'] for p,v in ports.items()}
    connection={p:list(v['bits']) for p,v in ports.items()}
    def child(kind):return dict(type=kind,connections=deepcopy(connection),port_directions=directions)
    adapter=dict(ports=deepcopy(ports),cells={
        f'bit{i}':dict(type=e.SC+'buf_1',connections=dict(I=[3+i],Z=[205+i]),port_directions=dict(I='input',Z='output'))
        for i in range(101)})
    body=dict(ports=deepcopy(ports),cells=dict(ca_primitive_data_delay=child('Allowance'),
        control=dict(type=e.SC+'inv_1',connections=dict(I=[2],ZN=[500]),port_directions=dict(I='input',ZN='output'))))
    return dict(modules=dict(RiscayMcuDigital=dict(ports=deepcopy(ports),cells=dict(soc=child('Soc'))),
                            Soc=dict(ports=deepcopy(ports),cells=dict(stage=child('Stage'),other=child('Stage'))),
                            Stage=body,Allowance=adapter))


class PassiveExperimentTests(unittest.TestCase):
    def test_exact_fatal_file_and_line(self):
        path=Path('testbench.sv').resolve();bench='$fatal(1,"EXPECTED");'
        e.classify_digital(f'FATAL: {path}:1: EXPECTED',1,bench,path,'EXPECTED')
        for log in (f'FATAL: {path.with_name("primitive.sv")}:1: EXPECTED',
                    f'FATAL: {path}:2: EXPECTED',f'FATAL: {path}:1: UNRELATED'):
            with self.assertRaisesRegex(ValueError,'PASSIVE_WRONG_FATAL'):
                e.classify_digital(log,1,bench,path,'EXPECTED')

    def test_simulation_source_is_bound_to_mapper_input(self):
        with TemporaryDirectory() as directory:
            source=Path(directory)/'Stage.sv';source.write_text('module Stage; endmodule')
            record=dict(inputs={source.name:e.sha(source)})
            e.bind_export(record,[source])
            source.write_text('module Stage; wire silently_changed; endmodule')
            with self.assertRaisesRegex(ValueError,'PASSIVE_EXPORT_SOURCE_MISMATCH'):
                e.bind_export(record,[source])

    def test_one_instance_and_unchanged_sibling(self):
        original=fixture();snapshot=deepcopy(original)
        graph,proof=e.passive_graph(original,'Soc.stage')
        self.assertEqual(original,snapshot)
        self.assertEqual(proof['removed_cell_counts'],{e.SC+'buf_1':101})
        after=e.flat(graph,'RiscayMcuDigital')
        self.assertIn('soc/other/ca_primitive_data_delay/bit0',after['cells'])
        self.assertIn('soc/stage/control',after['cells'])

    def test_wrong_width_is_rejected(self):
        original=fixture();original['modules']['Allowance']['ports']['a']['bits'].pop()
        with self.assertRaisesRegex(ValueError,'PASSIVE_PREPARE_WIDTH'):e.passive_graph(original,'Soc.stage')

    def test_other_cell_resize_is_rejected(self):
        original=fixture();graph,_=e.passive_graph(original,'Soc.stage')
        module=graph['modules']['A8bExperiment_1_Stage']
        module['cells']['control']['type']=e.SC+'inv_2'
        with self.assertRaisesRegex(ValueError,'PASSIVE_OTHER_CELL_CHANGED'):
            e.prove_passive_graph(original,graph,'Soc.stage',['soc','stage','ca_primitive_data_delay'])

    def test_other_pin_rewire_is_rejected(self):
        original=fixture();graph,_=e.passive_graph(original,'Soc.stage')
        graph['modules']['A8bExperiment_1_Stage']['cells']['control']['connections']['I']=[3]
        with self.assertRaisesRegex(ValueError,'PASSIVE_GRAPH_CHANGED'):
            e.prove_passive_graph(original,graph,'Soc.stage',['soc','stage','ca_primitive_data_delay'])

    def test_passive_alias_swap_is_rejected(self):
        original=fixture();graph,_=e.passive_graph(original,'Soc.stage')
        bits=graph['modules']['A8bExperiment_2_Allowance']['ports']['q']['bits']
        bits[0],bits[1]=bits[1],bits[0]
        with self.assertRaisesRegex(ValueError,'PASSIVE_GRAPH_CHANGED'):
            e.prove_passive_graph(original,graph,'Soc.stage',['soc','stage','ca_primitive_data_delay'])

    def test_deleted_control_is_rejected(self):
        original=fixture();graph,_=e.passive_graph(original,'Soc.stage')
        del graph['modules']['A8bExperiment_1_Stage']['cells']['control']
        with self.assertRaisesRegex(ValueError,'PASSIVE_CELL_SCOPE'):
            e.prove_passive_graph(original,graph,'Soc.stage',['soc','stage','ca_primitive_data_delay'])

    def test_model_replacement_is_explicit_and_one_instance(self):
        text='ChiselAsyncControlGate_v1 #(.WIDTH(1)) request ();\nChiselAsyncControlGate_v1 #(.WIDTH(101)) ca_primitive_data_delay (.reset(reset));'
        changed=e.passive_source(text)
        self.assertEqual(changed.count('ChiselAsyncControlGate_v1'),1)
        self.assertEqual(changed.count(e.MODEL),1)
        self.assertTrue(changed.startswith(text.split('\n')[0]))
        with self.assertRaisesRegex(ValueError,'PASSIVE_MODEL_INSTANCE'):e.passive_source(text+'\n'+text)


if __name__=='__main__':unittest.main()

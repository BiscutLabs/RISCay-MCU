# SPDX-License-Identifier: Apache-2.0
import unittest
from copy import deepcopy
from measure_desync_banks import parse_segments, cut_storage, data_reachability, data_queries, audit_data_view, validate_data_report
from gf180_physical import SC,SRAM
from test_global_repair import cell


class BankSegmentTests(unittest.TestCase):
    def test_storage_frontiers_preserve_logic_and_all_macro_endpoints(self):
        cells={'ff':cell('dffq_1',D=2,CLK=40,Q=3),
               'latch':cell('latq_1',D=4,E=42,Q=5),
               'wire':cell('buf_1',I=3,Z=4),
               'macro':dict(type=SRAM,port_directions={'Q':'output',**{p:'input' for p in ('A','D','CEN','GWEN','WEN','CLK')}},
                   connections={'A':[5,5],'D':[3,4],'CEN':[1],'GWEN':[1],'WEN':[1,1],'CLK':[42],'Q':[10,11]})}
        original=dict(modules={'RiscayMcuDigital':dict(cells=cells,
            ports={'watchdogClock':dict(direction='input',bits=[40]),'sda':dict(direction='input',bits=[41])},
            netnames={'watchdogClock':dict(bits=[40]),'sda':dict(bits=[41])})})
        analysis=deepcopy(original)
        library={SC+'dffq_1':'ff(IQ,IQN){}',SC+'latq_1':'latch(IQ,IQN){}',SC+'buf_1':'',SRAM:''}
        removed,ports=cut_storage(analysis,original,
            {'latch/E':dict(root='a'),'macro/CLK':dict(root='a')},{'desync_control/cpu.m/enable':'a'},library)
        self.assertEqual(removed,{'ff','latch','macro'})
        self.assertEqual(analysis['modules']['RiscayMcuDigital']['cells'],{'wire':cells['wire']})
        expected={(n,p,i) for n,c in cells.items() if n!='wire' for p,bs in c['connections'].items()
                  if p=='Q' or p in (('A','D','CEN','GWEN','WEN') if n=='macro' else ('D',)) for i in range(len(bs))}
        self.assertEqual({(p['cell'],p['pin'],p['lane']) for p in ports},expected)
        self.assertEqual(data_reachability(analysis['modules']['RiscayMcuDigital'],ports),{('lf','cpu_m'),('cpu_m','cpu_m')})
        text='\n'.join(data_queries(ports,1000))
        self.assertIn('set_input_delay 0',text)
        self.assertIn('set_output_delay 0',text)
        self.assertNotIn('set_propagated_clock',text)
        self.assertIn('set_max_delay 0',text)
        self.assertEqual(text.replace('period 1000','period 700'), '\n'.join(data_queries(ports,700)))

    def test_each_mode_and_pin_inventory_must_be_complete(self):
        ports=[dict(port='q',kind='q',domain='a',cell='source',pin='Q',lane=0),
               dict(port='d',kind='d',domain='b',cell='target',pin='D',lane=0)]
        report=dict(storage_q_and_d_pins=[1,1],rows=[dict(source='a',target='b',mode=m,
            selected_q_arrival_ns=0,selected_d_arrival_ns=1,q='q',d='d') for m in ('min','max')])
        validate_data_report(report,ports,{('a','b')})
        for mutate in (lambda r:r['rows'].pop(),lambda r:r.update(storage_q_and_d_pins=[2,1]),
                       lambda r:r['rows'][0].update(q='alias'),lambda r:r['rows'][0].update(selected_q_arrival_ns=.01)):
            bad=deepcopy(report);mutate(bad)
            with self.assertRaises(ValueError):validate_data_report(bad,ports,{('a','b')})

    def test_view_audit_rejects_missing_endpoint_load_and_ordinary_logic_change(self):
        register=cell('dffq_1',D=2,CLK=4,Q=3)
        wire=cell('buf_1',I=1,Z=2)
        before=dict(modules={'RiscayMcuDigital':dict(cells={'r':register,'b':wire})})
        ports=[dict(port='q',kind='q',cell='r',pin='Q',lane=0,bit=3),
               dict(port='d',kind='d',cell='r',pin='D',lane=0,bit=2)]
        loads=[dict(instance='load',cell='Load',pins=[(SC+'dffq_1','D')],bit=2)]
        after=dict(modules={'RiscayMcuDigital':dict(cells={'b':wire,'load':dict(type='Load',connections={'I':[2]})},
            ports={'in':dict(direction='input',bits=[1]),'q':dict(direction='input',bits=[3]),'d':dict(direction='output',bits=[2])})})
        library={SC+'dffq_1':'ff(IQ,IQN){}',SC+'buf_1':''}
        audit_data_view(before,after,ports,{'r'},library,loads)
        for which in ('endpoint','load','logic','kind','removed'):
            bad=deepcopy(after);ps=deepcopy(ports);ls=deepcopy(loads)
            removed={'r'}
            if which=='endpoint':bad['modules']['RiscayMcuDigital']['ports'].pop('d')
            if which=='load':ls[0]['pins']=[]
            if which=='logic':bad['modules']['RiscayMcuDigital']['cells']['b']['connections']['I']=[3]
            if which=='kind':ps[0]['kind']='d'
            if which=='removed':removed.add('b');bad['modules']['RiscayMcuDigital']['cells'].pop('b')
            with self.subTest(which=which),self.assertRaises(ValueError):audit_data_view(before,bad,ps,removed,library,ls)

    def test_inventory_distinguishes_missing_and_disconnected_pairs(self):
        rows=['STORAGE 4 4','SEGMENTS_DONE']
        for source in ('a','b'):
            for target in ('a','b'):
                for mode in ('min','max'):
                    present=int(source==target)
                    rows.append(f'PAIR_COVERAGE {source} {target} {mode} {present}')
                    if present:rows.append(f'PAIR {source} {target} {mode} 1 2 q/Q d/D 997')
        text='\n'.join(rows)
        report=parse_segments(text,'fixture')
        self.assertTrue(all(r['source']==r['target'] for r in report['rows']))
        self.assertTrue(all(r['source']!=r['target'] for r in report['empty_pairs']))
        mutations=(text.replace('SEGMENTS_DONE',''),
                   text.replace('PAIR a a min 1 2 q/Q d/D',''),
                   text.replace('PAIR_COVERAGE a b min 0',''),
                   text+'\nError: failed query',
                   text.replace('PAIR a a min 1 2','PAIR a a min 1 nan'))
        for broken in mutations:
            with self.subTest(broken=broken),self.assertRaises(ValueError):
                parse_segments(broken,'fixture')


if __name__=='__main__':unittest.main()

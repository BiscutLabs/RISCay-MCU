import copy, itertools, unittest
from qualified_bank_proof import BankIndependence, StorageFrontier, enclose, expression


class QualifiedBankProofSpec(unittest.TestCase):
    def test_launch_latency_changes_winner_and_keeps_polarity(self):
        from telemetry_bank_timing import composed_launch_bounds
        launches={p:{(m,e):v for m in ('min','max') for e,v in edges.items()}
                  for p,edges in {'a':{'rise':7.,'fall':1.},'b':{'rise':1.,'fall':2.}}.items()}
        paths={m:[('a/Q','rise',4.),('a/Q','fall',8.),('b/Q','rise',9.),('b/Q','fall',3.)]
               for m in ('min','max')}
        bounds=composed_launch_bounds(paths,launches)
        # b/rise has the longest cone, but a/rise wins after launch is included.
        # a/fall must not inherit a/rise's slower launch (which invents 18 ns).
        self.assertAlmostEqual(bounds['max'],1.2*11)
        self.assertAlmostEqual(bounds['min'],.8*5)
        self.assertLess(bounds['max'],14)
        launches['b']['max','rise']=6.
        self.assertGreater(composed_launch_bounds(paths,launches)['max'],14)

    def test_truth_table_enclosure_never_hides_bank_dependence(self):
        functions=[('(A&B)',lambda x:x['A'] and x['B']),
                   ('((A&(!S))|(B&S))',lambda x:x['B'] if x['S'] else x['A']),
                   ('(!(A^B))',lambda x:x['A']==x['B']),
                   ('((A|B)&C)',lambda x:(x['A'] or x['B']) and x['C']),
                   ('((!A)&(!B))',lambda x:not x['A'] and not x['B'])]
        for function,oracle in functions:
            pins=sorted(set(__import__('re').findall(r'[A-Z]+',function)))
            for states in itertools.product([(0,False),(1,False),(None,False),(None,True)],repeat=len(pins)):
                inputs=tuple((p,v,d) for p,(v,d) in zip(pins,states))
                constant,depends=enclose(function,inputs)
                rows=[]
                for values in itertools.product((0,1),repeat=len(pins)):
                    row=dict(zip(pins,values))
                    if all(v is None or row[p]==v for p,v,d in inputs):rows.append((row,int(oracle(row))))
                outputs={value for row,value in rows}
                dependent=any(a!=b and all(x[p]==y[p] for p,v,d in inputs if not d)
                              for x,a in rows for y,b in rows)
                self.assertEqual(depends,dependent)
                self.assertEqual(constant,next(iter(outputs)) if len(outputs)==1 else None)
        with self.assertRaises(ValueError):expression('__import__("os")')

    def test_inactive_gate_and_negative_bypass(self):
        lib={'and': 'pin(A) { direction: input; } pin(B) { direction: input; } pin(Z) { direction: output; function: "(A&B)"; }'}
        cells={'g':dict(type='and',connections={'A':['bank'],'B':['ready'],'Z':['y']},directions={'A':'input','B':'input','Z':'output'}),
               'sink':dict(type='test__dffrnq_1',connections={'D':['y'],'CLK':['clk'],'Q':['q']},directions={'D':'input','CLK':'input','Q':'output'})}
        BankIndependence(cells,lib,['bank'],{'ready':0},[]).require_independent(['sink/D'])
        bad=copy.deepcopy(cells);bad['g']['connections']['B']=[('constant','1')]
        with self.assertRaisesRegex(ValueError,'BANK_UNQUALIFIED_READER'):
            BankIndependence(bad,lib,['bank'],{'ready':0},[]).require_independent(['sink/D'])
        with self.assertRaisesRegex(ValueError,'INVALID_ASSUMPTION'):
            BankIndependence(cells,lib,['bank'],{'bank':0},[])

    def test_frontier_rejects_unclassified_storage_and_macro_pins(self):
        def cell(kind,**pins):
            return dict(type=kind,connections={p:[n] for p,n in pins.items()},
                directions={p:'output' if p=='Q' else 'input' for p in pins})
        cells={'source':cell('sc_dff',Q='bank',D='input',CLK='capture'),
               'reader':cell('sc_dff',D='bank',Q='read',CLK='work'),
               'native':cell('sc_lat',D='bank',Q='copy',E='native_capture')}
        frontier=StorageFrontier(cells,{'reader'},{'source','native'},'sc_','macro')
        self.assertEqual(frontier.periodic_targets(['source/Q']),['reader/D'])
        self.assertEqual(frontier.excluded,{'native/D'})
        with self.assertRaisesRegex(ValueError,'BANK_UNKNOWN_STORAGE_DOMAIN'):
            StorageFrontier(cells,{'reader'},{'source'},'sc_','macro').endpoints(['source/Q'])
        for pin in ('CLK','CEN','D'):
            with self.subTest(pin=pin):
                bad=dict(cells,ram=cell('macro',**{pin:'bank'}))
                with self.assertRaisesRegex(ValueError,'BANK_UNEXPECTED_MACRO_FANOUT'):
                    StorageFrontier(bad,{'reader'},{'source','native'},'sc_','macro').endpoints(['source/Q'])

    def test_correlated_decode_requires_both_partition_branches(self):
        lib={'and': 'pin(A) { direction: input; } pin(B) { direction: input; } pin(Z) { direction: output; function: "(A&B)"; }',
             'inv': 'pin(A) { direction: input; } pin(Z) { direction: output; function: "(!A)"; }'}
        def cell(kind,**pins):
            return dict(type=kind,connections={p:[n] for p,n in pins.items()},
                directions={p:'output' if p in ('Q','Z') else 'input' for p in pins})
        cells={'selector':cell('test__dff',Q='select',D='unrelated'),
            'decode':cell('and',A='bank',B='select',Z='data'),
            'inverse':cell('inv',A='select',Z='enable'),
            'gate':cell('and',A='data',B='enable',Z='out'),
            'sink':cell('test__dff',D='out',Q='held')}
        proof=BankIndependence(cells,lib,['bank'],{},[])
        with self.assertRaisesRegex(ValueError,'BANK_UNQUALIFIED_READER'):
            proof.require_independent(['sink/D'])
        self.assertEqual(proof.require_independent(['sink/D'],['select'])['exhaustive_partition_leaves'],[[0],[1]])
        for bad_case in (0,1):
            bad=copy.deepcopy(cells)
            bad['gate']['connections']['B']=['select' if bad_case else 'enable']
            bad['decode']['connections']['B']=['select' if bad_case else 'enable']
            with self.assertRaisesRegex(ValueError,'BANK_UNQUALIFIED_READER'):
                BankIndependence(bad,lib,['bank'],{},[]).require_independent(['sink/D'],['select'])
        with self.assertRaisesRegex(ValueError,'INVALID_PARTITION'):
            proof.require_independent(['sink/D'],['data'])


if __name__=='__main__':unittest.main()

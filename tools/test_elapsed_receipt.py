# SPDX-License-Identifier: Apache-2.0
"""Independent owner/reply packing for the bounded elapsed feedback loop."""
import copy
import unittest
from check_held_receipts import catalog, elapsed_source_fields


# Literal three-lane positions, specified independently from the checker.
BD = [('mode',0,2),('replyPhase',2,1),('commandPhase',3,1),('single',4,1),
      ('index',5,3),('remainder[0]',8,10),('remainder[1]',18,10),('remainder[2]',28,10),
      ('quotient[0]',38,32),('quotient[1]',70,32),('quotient[2]',102,32),
      ('fraction[0]',134,10),('fraction[1]',144,10),('fraction[2]',154,10),
      ('delta',164,32),('target',196,32)]
CLICK = [('mode',0,1),('replyPhase',1,1),('commandPhase',2,1),('single',3,1),
         ('index',4,3),('remainder[0]',7,10),('remainder[1]',17,10),('remainder[2]',27,10),
         ('quotient[0]',37,32),('quotient[1]',69,32),('quotient[2]',101,32),
         ('fraction[0]',133,10),('fraction[1]',143,10),('fraction[2]',153,10),
         ('delta',163,32),('target',195,32)]


def fixture(click):
    prefix='Click' if click else 'FourPhase'; top=prefix+'Soc'
    model='PhaseDecoupledClickBuffer_8' if click else 'FourPhaseFifo_8'
    owner=dict(module=model,reset_domain='root',channels=[dict(id='out',layout=[
        dict(field='bits.'+f,lsb=o,width=w,signed=False,source=f'~|{model}>out.bits.{f}')
        for f,o,w in (CLICK if click else BD)])])
    native=dict(module=prefix+'Elapsed',reset_domain='root',children=[dict(id='owner',contract=owner)])
    receipt=dict(channels=[dict(layout=[dict(field=f'bits.elapsed[{i}]') for i in range(3)])])
    parent=dict(rtl_path=top+'.ca_child_elapsed_scaler',children=[
        dict(id='native',contract=native),dict(id='reply_bridge',contract=receipt)])
    return dict(top=top,design=dict(children=[dict(id='elapsed_scaler',contract=parent)])),owner,native


class ElapsedReceiptTest(unittest.TestCase):
    def test_literal_owner_offsets_and_reply_slices(self):
        for click,expected in ((False,BD),(True,CLICK)):
            self.assertEqual(elapsed_source_fields(3,click),expected)
            manifest,_,_=fixture(click); item,=catalog(manifest)
            self.assertEqual(item['width'],227 if click else 228)
            shift=1 if click else 0
            self.assertEqual(item['source_fields'],{
                'elapsed[0]':(38-shift,32),'elapsed[1]':(70-shift,32),'elapsed[2]':(102-shift,32),
                'single':(4-shift,1),'state.fraction[0]':(134-shift,10),
                'state.fraction[1]':(144-shift,10),'state.fraction[2]':(154-shift,10),
                'state.consumed':(196-shift,32)})
            self.assertEqual(item['fields'],[('elapsed[0]',0,32),('elapsed[1]',32,32),
                ('elapsed[2]',64,32),('single',96,1),('state.fraction[0]',97,10),
                ('state.fraction[1]',107,10),('state.fraction[2]',117,10),('state.consumed',127,32)])
            self.assertTrue(item['storage'].endswith(('ca_child_owner.' if click else
                'ca_child_owner.head_ca_child_stage0.ca_child_storage.')+'ca_primitive_payload.q'))

    def test_rejects_wrong_source_packing_and_owner(self):
        for click in (False,True):
            for fault in ('offset','width','field','source','signed','owner','reset','native'):
                manifest,owner,native=fixture(click)
                field=owner['channels'][0]['layout'][8]
                if fault=='offset':field['lsb']+=1
                elif fault=='width':field['width']-=1
                elif fault=='field':field['field']='bits.delta'
                elif fault=='source':field['source']='~|Wrong>out.bits.quotient[0]'
                elif fault=='signed':field['signed']=True
                elif fault=='owner':owner['module']='ClockedCopy'
                elif fault=='reset':owner['reset_domain']='application'
                else:native['module']='OtherElapsed'
                with self.subTest(click=click,fault=fault), self.assertRaisesRegex(ValueError,'HELD_RECEIPT_ELAPSED_'):
                    catalog(manifest)


if __name__=='__main__':unittest.main()

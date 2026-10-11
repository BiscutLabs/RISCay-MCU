# SPDX-License-Identifier: Apache-2.0
import copy
import re
import unittest
from check_publication_source_export import channel_layout,publication_recovery_background


def fixture(click=False):
    top='ClickSoc' if click else 'FourPhaseSoc';children=[];scopes={};forces=[]
    for name in ('telemetry','housekeeping'):
        path=top+'.ca_child_'+name+'_source';cells=[]
        for identity,initial in (('eligibility','0'),('debt_storage','1')):
            primitive=path+'.ca_primitive_'+identity
            cells.append(dict(id=identity,rtl_path=primitive,model='ChiselAsyncEventRegister_v1',
                parameters=dict(WIDTH='1',RESET_VALUE=initial)))
            scopes[primitive]=dict(model='ChiselAsyncEventRegister_v1',ports=dict(q=dict(name='q',width=1,direction='output')))
            forces.append(f"force {primitive}.q = 1'h0;\n")
        module='ClickBuffer' if click else 'LongHoldBuffer';model='ChiselAsyncEventRegister_v1' if click else 'ChiselAsyncClosingLatch_v1'
        payload=path+'.ca_child_reservation.ca_primitive_payload'
        scopes[payload]=dict(model=model,ports=dict(q=dict(name='q',width=2,direction='output')))
        forces.append(f"force {payload}.q = 2'h0;\n")
        storage=dict(module=module,channels=[dict(id='out',layout=channel_layout(module,'out',True))],
            primitives=[dict(id='payload',rtl_path=payload,model=model,parameters=dict(WIDTH='2'))])
        children.append(dict(id=name+'_source',contract=dict(module=('Click' if click else 'FourPhase')+'PublicationSource',
            primitives=cells,children=[dict(id='reservation',contract=storage)])))
        grant=top+'.ca_child_'+name+'_grant_bridge';scopes[grant]=dict(registers=dict(state=2,data_recovery=1))
        forces.extend((f"force {grant}.state = 2'h0;\n",f"force {grant}.data_recovery = 1'h0;\n"))
    coverage='if (ones_0 !== 212\'hfffffffffffffffffffffffffffffffffffffffffffffffffffff || zeros_0 !== 212\'hfffffffffffffffffffffffffffffffffffffffffffffffffffff) $fatal(1,"INACTIVE_ENDPOINT:command");\n'
    source=f"initial begin\nforce {top}.reset = 1'b1; #1;\n"+''.join(forces)+'#1;\n// retained original campaign\n#1; check;\n'+coverage+'$display("CONTRACT_PROBES_PASS:1");'
    return dict(top=top,design=dict(children=children)),scopes,source,coverage


class RecoveryBackgroundTests(unittest.TestCase):
    def test_joint_sources_preserve_original_campaign_and_every_dynamic_check(self):
        for click in (False,True):
            manifest,scopes,source,coverage=fixture(click)
            result,count=publication_recovery_background(source,manifest,scopes,1)
            self.assertEqual(count,33)
            self.assertTrue(result.startswith(source[:source.index(coverage)]))
            self.assertEqual(result.count(coverage),1)
            self.assertEqual(result.count('#1; check;'),33)
            self.assertEqual(set(re.findall(r'force (\S+) =',result)),set(re.findall(r'force (\S+) =',source)))
            self.assertNotIn('force command',result)
            for owner in ('telemetry','housekeeping'):
                base=manifest['top']+'.ca_child_'+owner
                self.assertIn(f"force {base}_source.ca_child_reservation.ca_primitive_payload.q = 2'h2;",result)
                self.assertIn(f"force {base}_grant_bridge.data_recovery = 1'h1;",result)

    def test_every_forced_source_requires_actual_register_or_matching_primitive_port(self):
        manifest,scopes,source,_=fixture()
        for path,scope in scopes.items():
            if 'registers' in scope:
                for register in scope['registers']:
                    bad=copy.deepcopy(scopes);del bad[path]['registers'][register]
                    with self.assertRaisesRegex(ValueError,'RECOVERY_BACKGROUND_DRIVER'):
                        publication_recovery_background(source,manifest,bad,1)
            else:
                for field,value in (('direction','input'),('width',17)):
                    bad=copy.deepcopy(scopes);bad[path]['ports']['q'][field]=value
                    with self.assertRaisesRegex(ValueError,'RECOVERY_BACKGROUND_DRIVER'):
                        publication_recovery_background(source,manifest,bad,1)
                bad=copy.deepcopy(scopes);bad[path]['model']='CombinationalAlias'
                with self.assertRaisesRegex(ValueError,'RECOVERY_BACKGROUND_DRIVER'):
                    publication_recovery_background(source,manifest,bad,1)

    def test_non_catalogued_source_force_is_rejected(self):
        manifest,scopes,source,_=fixture()
        for force in re.findall(r"force \S+ = \d+'h0;\n",source):
            with self.assertRaisesRegex(ValueError,'RECOVERY_BACKGROUND_DRIVER'):
                publication_recovery_background(source.replace(force,''),manifest,scopes,1)

    def test_role_layout_cannot_be_reinterpreted(self):
        manifest,scopes,source,_=fixture()
        storage=manifest['design']['children'][0]['contract']['children'][0]['contract']
        storage['channels'][0]['layout'][1]['lsb']=0
        with self.assertRaisesRegex(ValueError,'RECOVERY_BACKGROUND_LAYOUT'):
            publication_recovery_background(source,manifest,scopes,1)

    def test_owner_and_storage_model_changes_are_rejected(self):
        manifest,scopes,source,_=fixture()
        for key,value in (('model','CombinationalAlias'),('parameters',dict(WIDTH='2',RESET_VALUE='1'))):
            bad=copy.deepcopy(manifest);bad['design']['children'][0]['contract']['primitives'][1][key]=value
            with self.assertRaisesRegex(ValueError,'RECOVERY_BACKGROUND_STORAGE'):
                publication_recovery_background(source,bad,scopes,1)
        manifest['design']['children'][0]['contract']['module']='ClockedOwner'
        with self.assertRaisesRegex(ValueError,'RECOVERY_BACKGROUND_OWNER'):
            publication_recovery_background(source,manifest,scopes,1)

    def test_partial_owner_inventory_is_rejected(self):
        manifest,scopes,source,_=fixture();manifest['design']['children'].pop()
        with self.assertRaisesRegex(ValueError,'RECOVERY_BACKGROUND_INVENTORY'):
            publication_recovery_background(source,manifest,scopes,1)


if __name__=='__main__':unittest.main()

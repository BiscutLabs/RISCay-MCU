# SPDX-License-Identifier: Apache-2.0
import copy
import unittest
from check_export import validate_native_click
from check_application_reset import persistent_reset_children
from check_publication_source_export import validate_publication_source,publication_boundary_bindings,CHANNELS


class PublicationSourceExportTests(unittest.TestCase):
    def boundary_fixture(self,click=False,inline=False,owner='telemetry'):
        top='ClickSoc' if click else 'FourPhaseSoc';prefix='Click' if click else 'FourPhase'
        boundary=owner+'Boundary_'
        registers={boundary+n:1 for n in ('active','pending','issued','revoked','role')}
        registers[owner+'OwnerIdle']=1
        registers['fabric_'+('telemetryCommitPending' if owner=='telemetry' else 'housekeepingOrderedPending')]=1
        nets=dict(registers)
        nets.update({n:1 for n in (owner+'SourceEmpty',boundary+'io_occupied',
            f'fabric_io_{owner}Source_reserve_ready',f'fabric_io_{owner}Source_reserve_valid',f'fabric_io_{owner}Draining')})
        if inline:nets.update({boundary+n:1 for n in ('io_debt','io_eligible')})
        else:nets.update({n:1 for n in (boundary+'io_available',boundary+'io_reservationRecovery',
            f'fabric_io_{owner}Source_eligible',f'fabric_io_{owner}Source_ownerRecovery',f'fabric_io_{owner}Source_ownerRecovery_0')})
        scopes={top:dict(nets=nets,registers=registers)};endpoints={}
        for name in CHANNELS:
            path=top+f'.ca_child_{owner}_{name}_bridge'
            endpoints[name]={n:path+'.'+n for n in ('in_valid','in_ready','out_valid','out_data')}
            scopes[path]=dict(ports={'in_bits_recovery':dict(name='in_bits_recovery',width=1,direction='input')})
        command=dict(module='DecoupledTo'+prefix,rtl_path=top+f'.ca_child_{owner}_command_bridge')
        recovery_pin='in_bits' if owner=='housekeeping' else 'in_bits_recovery'
        if owner=='housekeeping':
            command['channels']=[dict(id=side,layout=[dict(field='bits',lsb=0,width=1,signed=False,
                source='~|'+command['module']+'>'+side+'.bits')]) for side in ('in','out')]
            command['endpoints']=[dict(id=side+'_data',width=1,
                source='~|'+command['module']+'>'+side+'.bits') for side in ('in','out')]
        scopes[command['rtl_path']]=dict(ports={
            recovery_pin:dict(name=recovery_pin,width=1,direction='input'),
            'in_ready':dict(name='in_ready',width=1,direction='output')})
        return top,owner,endpoints,command,top+'.applicationCancel',scopes

    def test_both_alias_forms_keep_complete_equations_and_real_consumer_pins(self):
        for click in (False,True):
            for inline in (False,True):
                for owner in ('telemetry','housekeeping'):
                    args=self.boundary_fixture(click,inline,owner);top,_,endpoints,command,cut,_=args
                    pairs=publication_boundary_bindings(*args);mapping=dict(pairs)
                    available=mapping[top+f'.fabric_io_{owner}Source_reserve_ready']
                    for term in ('active','pending','issued'):
                        self.assertIn(top+'.'+owner+'Boundary_'+term,available)
                    for name in ('reserve','decision','publication'):
                        self.assertIn(endpoints[name]['in_ready'],available)
                    for name in ('grant','drain'):self.assertIn('!'+endpoints[name]['out_valid'],available)
                    command_pin=command['rtl_path']+('.in_bits' if owner=='housekeeping' else '.in_bits_recovery')
                    for term in ('active','pending','revoked','role'):
                        self.assertIn(top+'.'+owner+'Boundary_'+term,mapping[command_pin])
                    self.assertIn(endpoints['grant']['out_data']+'[1]',mapping[command_pin])
                    self.assertIn(endpoints['decision']['in_ready'],mapping[command_pin])
                    reserve_pin=endpoints['reserve']['in_valid'].rsplit('.',1)[0]+'.in_bits_recovery'
                    self.assertEqual(mapping[reserve_pin],f'({top}.{owner}Boundary_pending || {cut})')
                    self.assertTrue(all('force' not in a+b for a,b in pairs))

    def test_all_surviving_aliases_are_checked_not_just_the_first_match(self):
        args=list(self.boundary_fixture());top=args[0];scope=args[-1][top]
        scope['nets'].update(telemetryBoundary_io_debt=1,telemetryBoundary_io_eligible=1)
        mapping=dict(publication_boundary_bindings(*args))
        self.assertEqual(mapping[top+'.telemetryBoundary_io_debt'],mapping[top+'.telemetryBoundary_io_reservationRecovery'])
        self.assertEqual(mapping[top+'.telemetryBoundary_io_eligible'],mapping[top+'.fabric_io_telemetrySource_eligible'])
        self.assertEqual(mapping[top+'.fabric_io_telemetrySource_ownerRecovery'],top+'.telemetryBoundary_role')
        self.assertEqual(mapping[top+'.fabric_io_telemetrySource_ownerRecovery_0'],top+'.telemetryBoundary_role')

    def test_housekeeping_scalar_role_rejects_old_layout_and_wrong_pins(self):
        for click in (False,True):
            for side in range(2):
                for key,value in (('field','recovery'),('width',2),('lsb',1),('source','wrong')):
                    args=list(self.boundary_fixture(click=click,owner='housekeeping'))
                    args[3]['channels'][side]['layout'][0][key]=value
                    with self.assertRaisesRegex(ValueError,'PUBLICATION_BOUNDARY_COMMAND_LAYOUT'):
                        publication_boundary_bindings(*args)
                args=list(self.boundary_fixture(click=click,owner='housekeeping'))
                args[3]['endpoints'][side]['width']=2
                with self.assertRaisesRegex(ValueError,'PUBLICATION_BOUNDARY_COMMAND_LAYOUT'):
                    publication_boundary_bindings(*args)
            for key,value in (('width',2),('direction','output')):
                args=list(self.boundary_fixture(click=click,owner='housekeeping'))
                args[-1][args[3]['rtl_path']]['ports']['in_bits'][key]=value
                with self.assertRaisesRegex(ValueError,'PUBLICATION_BOUNDARY_PIN'):
                    publication_boundary_bindings(*args)

    def test_missing_or_wrong_alias_state_and_actual_pin_fail_closed(self):
        for inline in (False,True):
            for group,name in (('nets','telemetryBoundary_io_debt' if inline else 'telemetryBoundary_io_reservationRecovery'),
                               ('registers','telemetryBoundary_role')):
                for wrong in (None,2):
                    args=list(self.boundary_fixture(inline=inline));values=args[-1][args[0]][group]
                    if wrong is None:values.pop(name)
                    else:values[name]=wrong
                    with self.assertRaisesRegex(ValueError,'PUBLICATION_BOUNDARY_(ALIAS|NET)'):
                        publication_boundary_bindings(*args)
        args=list(self.boundary_fixture(inline=True))
        args[-1][args[3]['rtl_path']]['ports']['in_bits_recovery']['direction']='output'
        with self.assertRaisesRegex(ValueError,'PUBLICATION_BOUNDARY_PIN'):publication_boundary_bindings(*args)

    def test_unknown_owners_are_rejected(self):
        for name in ('ClockedPublicationSource','ClickPublicationSourceRTZ','FourPhasePublicationSourceAdapter'):
            with self.assertRaisesRegex(ValueError,'PUBLICATION_SOURCE_OWNER'):
                validate_publication_source(dict(module=name))

    def test_native_click_owner_cannot_hide_rtz(self):
        node=dict(module='ClickPublicationSource',channels=[],primitives=[],children=[])
        validate_native_click(dict(top='ClickPublicationSource',design=node))
        for hidden in (dict(module='FourPhaseStage',channels=[],primitives=[],children=[]),
                       dict(module='Boundary',channels=[dict(protocol='four-phase-bundled-v1')],primitives=[],children=[]),
                       dict(module='Storage',channels=[],primitives=[dict(model='ChiselAsyncClosingLatch_v1')],children=[])):
            bad=copy.deepcopy(node);bad['children'].append(dict(id='hidden',contract=hidden))
            with self.assertRaisesRegex(ValueError,'MCU_CLICK_HAS_RTZ_IMPLEMENTATION'):
                validate_native_click(dict(top='ClickPublicationSource',design=bad))

    def test_every_publication_crossing_requires_por_ownership_and_complete_inventory(self):
        for click in (False,True):
            prefix='Click' if click else 'FourPhase'
            for owner in ('telemetry','housekeeping'):
                expected={owner+'_source':prefix+'PublicationSource'}
                expected[owner+'_final_return']=prefix+'ReturnReceipt'
                for name in CHANNELS:
                    expected[owner+'_'+name+'_bridge']=(prefix+'ToDecoupled' if name in ('grant','drain') else 'DecoupledTo'+prefix)
                children=[dict(id=n,contract=dict(module=m)) for n,m in expected.items()]
                manifest=dict(top=prefix+'Soc',design=dict(children=children))
                classified=persistent_reset_children(manifest)
                self.assertTrue(all(classified[n]==m for n,m in expected.items()))
                for i in range(len(children)):
                    missing=copy.deepcopy(manifest);missing['design']['children'].pop(i)
                    with self.assertRaisesRegex(ValueError,'SOC_PUBLICATION_SOURCE_RESET_INVENTORY'):
                        persistent_reset_children(missing)
                    wrong=copy.deepcopy(manifest);wrong['design']['children'][i]['contract']['module']='ClockedAdapter'
                    with self.assertRaisesRegex(ValueError,'SOC_PERSISTENT_RESET_OWNER'):
                        persistent_reset_children(wrong)


if __name__=='__main__':unittest.main()

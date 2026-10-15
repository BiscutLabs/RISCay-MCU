# SPDX-License-Identifier: Apache-2.0
"""Pure graph/string adversarial controls; never execute HDL or subprocesses."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import quiescing_gate_control as gate
import check_quiescing_receipt_controls as controls
from reset_bridge_proof import Cone


class Graph:
    def __init__(self):
        self.module = dict(cells={}, netnames={}); self.next = 2
    def net(self, name, width=1):
        bits = list(range(self.next, self.next+width)); self.next += width
        self.module['netnames'][name] = dict(bits=bits)
        return bits
    def alias(self, name, bits):
        self.module['netnames'][name] = dict(bits=bits); return bits
    def cell(self, kind, pins, output='Y', parameters=None):
        name = 'cell_'+str(len(self.module['cells']))
        self.module['cells'][name] = dict(type=kind, connections=pins,
            port_directions={p: 'output' if p == output else 'input' for p in pins}, parameters=parameters or {})
        return name
    def op(self, kind, a, b=None, width=1, select=None):
        y = self.net('tmp_'+str(self.next), width); pins = dict(A=a, Y=y)
        if b is not None: pins['B'] = b
        if select is not None: pins['S'] = select
        self.cell(kind, pins); return y
    def adff(self, name, d, clock, reset, value):
        q = self.module['netnames'][name]['bits']
        return self.cell('$adff', dict(Q=q, D=d, CLK=clock, ARST=reset), 'Q',
            dict(CLK_POLARITY='1', ARST_POLARITY='1', ARST_VALUE=bin(value)[2:]))


def ready_graph():
    g = Graph(); good = {}
    for name, value in gate.PREDICATES + (('gate_enabled', 1),):
        bits = g.net(name); good[name] = bits if value else g.op('$not', bits)
    for name in gate.BRANCH: g.net(name)
    def all_of(names):
        bits = ['1']
        for name in names: bits = g.op('$and', bits, good[name])
        return bits
    cpu = all_of([n for n, _ in gate.CPU] + ['gate_enabled']); g.alias('fabric_cpuAvailable', cpu)
    ram = all_of([n for n, _ in gate.PREDICATES[-4:]])
    ram = g.op('$or', g.op('$not', g.module['netnames']['fabric_ramOperation']['bits']), ram)
    program = g.op('$or', g.op('$not', g.module['netnames']['fabric_programCpuOperation']['bits']), g.net('programAdmission'))
    mmio = g.op('$mux', good['fabric_controlBusy'], g.net('mmioComplete'),
                select=g.module['netnames']['fabric_nativeMmio']['bits'])
    ready = g.op('$and', g.op('$and', g.op('$and', cpu, ram), program), mmio)
    g.alias('fabric_io_request_ready', ready)
    return g


def topology_graph():
    g = ready_graph(); bits = lambda n: g.module['netnames'][n]['bits']
    service = g.net('serviceClock'); reset = g.net('reset')
    work = g.op('$and', service, bits('gate_enabled')); g.alias('workClock', work); g.alias('receivingClock', work)
    for name in gate.FORCES + ('gate_needClock', 'gate_drain'): g.net(name)
    for name in gate.FORCES: g.adff(name, g.net(name+'_input'), service, reset, 1)
    g.adff('gate_needClock', bits('gate_demandFirst'), service, reset, 1)
    g.adff('gate_drain', bits('gate_drainFirst'), service, reset, 1)
    count = g.net('gate_grace', 3); nonzero = g.op('$reduce_bool', count)
    decrement = g.op('$sub', count, ['1','0','0'], width=3)
    down = g.op('$mux', count, decrement, width=3, select=nonzero)
    gd = g.op('$mux', down, ['1']*3, width=3, select=bits('gate_drain'))
    g.adff('gate_grace', gd, service, reset, 7)
    run = g.op('$or', g.op('$or', nonzero, bits('gate_needClock')), reset)
    g.adff('gate_enabled', run, g.op('$not', service), reset, 1)
    for instance in ('ca_child_ram_access', 'ca_child_ram_grant_bridge', 'ca_child_ram_decision_bridge'):
        g.alias(instance+'.clock', work)
    g.alias('ca_child_request_bridge.clock', service)
    g.alias('ca_child_request_bridge.out_ready', bits('fabric_io_request_ready'))
    for name, width in (('ca_child_ram_access.active', 1), ('fabric_ram_state', 2)):
        g.net(name, width); g.adff(name, ['0']*width, work, reset, 0)
    for output, actual in (('rawRequest', 'ca_child_request_bridge.in_req'),
                           ('rawAck', 'ca_child_request_bridge.in_ack'),
                           ('offered', 'ca_child_request_bridge.out_valid'),
                           ('ramGrantWaiting', 'ca_child_ram_grant_bridge.out_valid')):
        g.alias(output, g.net(actual))
    for field, width in (('operation',2),('address',32),('data',32),('mask',4)):
        for output, actual in (('rawPayload_', 'ca_child_request_bridge.in_bits_'),
                              ('captured_', 'ca_child_request_bridge.out_bits_')):
            g.alias(output+field, g.net(actual+field, width))
    g.alias('accepted', g.op('$and', bits('offered'), bits('fabric_io_request_ready')))
    g.alias('wordAccepted', g.op('$and', g.net('ca_child_ram_access.io_request_valid'),
                               g.net('ca_child_ram_access.io_request_ready')))
    g.module['cells']['fabric_ram_macros_0'] = dict(type='gf180mcu_ocd_ip_sram__sram1024x8m8wm1',
        connections=dict(CLK=work),port_directions=dict(CLK='input'))
    return g


def testbench():
    predicates = ','.join(('' if good else '~')+'dut.'+name for name, good in gate.PREDICATES)
    return f'''module Testbench;
wire [16:0] gatePredicates = {{{predicates}}};
wire gateOtherReady = &gatePredicates;
wire gateWithoutDecision = &{{gatePredicates[16:3],gatePredicates[1:0]}};
wire gateStoreBranch = dut.fabric_ramOperation && !dut.fabric_nativeMmio && !dut.fabric_programCpuOperation;
wire gateEligibleWrite = dut.ca_child_ram_source.eligible && dut.ca_child_ram_grant_bridge.out_bits;
initial begin
 force dut.gate_demandFirst=1'b0; force dut.gate_drainFirst=1'b0;
 release dut.gate_demandFirst; release dut.gate_drainFirst;
 if(bad) $fatal(1,"{gate.FATAL}");
end
endmodule
'''


def local_ram_por(g):
    clock=g.module['netnames']['workClock']['bits'];reset=g.module['netnames']['reset']['bits']
    first=g.net('ca_child_ram_access.localReset_release_0')
    second=g.net('ca_child_ram_access.localReset_release_1')
    g.adff('ca_child_ram_access.localReset_release_0',['0'],clock,reset,1)
    g.adff('ca_child_ram_access.localReset_release_1',first,clock,reset,1)
    Cone(g.module).flop('ca_child_ram_access.active')[1]['connections']['ARST']=second
    return g


def fixture(variant):
    prefix = 'FourPhase' if variant == 'bd' else 'Click'; top = ('Bd' if variant == 'bd' else 'Click')+'ResetBoundarySocFixture'
    terms = ' & '.join(('' if good else '~')+name for name, good in gate.CPU)+' & gate_enabled'
    body = 'module '+top+';\nwire fabric_cpuAvailable = '+terms+';\n'
    children = []
    for identity, kind in (('request_bridge',prefix+'QuiescingReceipt'),('ram_source',prefix+'RamSource'),('ram_grant_bridge',prefix+'ToDecoupled')):
        instance='ca_child_'+identity
        body += kind+' '+instance+' (.clock(serviceClock),.out_ready(fabric_io_request_ready));\n'
        children.append(dict(id=identity,contract=dict(module=kind,rtl_path=top+'.'+instance)))
    return {top+'.sv':body+'endmodule\n','testbench.sv':testbench()}, dict(top=top,design=dict(children=children))


class GateTests(unittest.TestCase):
    def setUp(self):
        blocked=patch('subprocess.Popen',side_effect=AssertionError('NO_HARDWARE_OR_CHILD_PROCESSES'))
        blocked.start();self.addCleanup(blocked.stop)

    def test_fixture_reset_origin_includes_only_actual_por_watchdog_and_input(self):
        from check_reset_crossings import prove_reset_origin
        g=Graph();por=g.net('reset');watchdog=g.net('watchdog_');application=g.net('applicationReset')
        production=g.op('$or',por,watchdog);fixture=g.op('$or',production,application)
        prove_reset_origin(Cone(g.module),production,False)
        prove_reset_origin(Cone(g.module),fixture,True)
        extra=g.net('holdRamDecision');wrong=g.net('stopWorkClock')
        for origin in (production,g.op('$or',por,application),g.op('$or',watchdog,application),
                       g.op('$or',production,wrong),g.op('$or',fixture,extra),g.op('$and',production,application)):
            with self.assertRaises(ValueError):prove_reset_origin(Cone(g.module),origin,True)
        with self.assertRaises(ValueError):prove_reset_origin(Cone(g.module),fixture,False)

    def test_fixture_identity_and_port_changes_are_rejected(self):
        from check_reset_crossings import fixture_ports, FIXTURE_TOPS
        # Explicit ABI is independently stated here; it is not obtained from
        # the checker's schema or an accepted arbitrary callback.
        inp=dict(reset=1,serviceClock=1,watchdogClock=1,scl=1,sda=1,gpioIn=32,adcMiso=1,
                 applicationReset=1,stopWorkClock=1,holdRamDecision=1)
        out={n:1 for n in ('sdaLow adcCsN adcSclk programmed locked systemReset resetReason sleeping '
             'serviceClockEnable traceEvent commit_valid receivingClock boundaryClosed boundaryRebased '
             'boundaryRebaseIdle ingressRebased rebasing coreResetHeld wakeDemand cutoff islandReset ingressClosed '
             'serviceClosed rawRequest rawAck offered accepted wordAccepted ramBusy ramGrantWaiting nativeTraceEvent').split()}
        out.update(gpioOut=32,gpioOe=32,sleepEntries=32,mode=3,workClosedAcks=4,workRebaseAcks=4)
        for prefix in ('trace','nativeTrace'):
            for name,width in [('valid',1),('pc',32),('instruction',32),('rd',4),('data',32),('writeRegister',1),('trap',1),('cause',4)]:out[prefix+'_'+name]=width
        for prefix in ('commit_bits','rawPayload','captured'):
            for name,width in [('operation',2),('address',32),('data',32),('mask',4)]:out[prefix+'_'+name]=width
        g=Graph();g.module['ports']={}
        for direction,ports in [('input',inp),('output',out)]:
            for name,width in ports.items():g.module['ports'][name]=dict(direction=direction,bits=g.net(name,width))
        for top in FIXTURE_TOPS:fixture_ports(g.module,top)
        with self.assertRaisesRegex(ValueError,'IDENTITY'):fixture_ports(g.module,'OtherFixture')
        for change in ('missing','extra','width','direction','alias'):
            m=copy.deepcopy(g.module)
            if change=='missing':m['ports'].pop('applicationReset')
            if change=='extra':m['ports']['extraReset']=dict(direction='input',bits=[99999])
            if change=='width':m['ports']['applicationReset']['bits'] += [99999]
            if change=='direction':m['ports']['applicationReset']['direction']='output'
            if change=='alias':m['netnames']['applicationReset']['bits']=[99999]
            with self.subTest(change=change),self.assertRaises(ValueError):fixture_ports(m,FIXTURE_TOPS[0])

    def test_full_graph_proof_cannot_skip_real_coordinator_or_mask(self):
        import check_reset_crossings
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'graph.json';g=topology_graph();top='BdResetBoundarySocFixture'
            path.write_text(json.dumps(dict(modules={top:g.module})))
            full=dict(status='pass',violations=[],receiver_proofs=[dict(prefix='applicationResetCoordinator'),
                dict(prefix='ca_child_request_bridge',masked_bits=70)])
            args=(str(path),controls.sha(path),'synthetic-helper-id',top,(('program',64),('ram',32)))
            gate._full_graph_proof.cache_clear()
            with patch.object(check_reset_crossings,'audit_graph',return_value=full):
                result=json.loads(gate._full_graph_proof(*args));self.assertEqual(result['full'],full)
            for change in ('no_coordinator','no_mask','failed','violations'):
                bad=copy.deepcopy(full)
                if change=='no_coordinator':bad['receiver_proofs'].pop(0)
                if change=='no_mask':bad['receiver_proofs'].pop()
                if change=='failed':bad['status']='fail'
                if change=='violations':bad['violations']=['synthetic failure']
                gate._full_graph_proof.cache_clear()
                with patch.object(check_reset_crossings,'audit_graph',return_value=bad),self.assertRaises(ValueError):gate._full_graph_proof(*args)
            gate._full_graph_proof.cache_clear()

    def test_complete_ready_and_topology(self):
        gate.prove_graph(topology_graph().module)

    def test_both_exact_falling_edge_normalizations(self):
        for polarity in ('0', '0'*32):
            g=topology_graph();cell=Cone(g.module).flop('gate_enabled')[1]
            cell['connections']['CLK']=g.module['netnames']['serviceClock']['bits']
            cell['parameters']['CLK_POLARITY']=polarity
            gate.prove_graph(g.module)
        for polarity in ('1', '0'*31+'1'):
            for kind in ('$not','$logic_not'):
                g=topology_graph();cone=Cone(g.module);cell=cone.flop('gate_enabled')[1]
                cone.drivers[cell['connections']['CLK'][0]][1]['type']=kind
                cell['parameters']['CLK_POLARITY']=polarity
                gate.prove_graph(g.module)

    def test_falling_edge_normalization_rejects_other_clocks_and_edges(self):
        for form in ('direct_rising','inverted_falling','unrelated_falling','mixed',
                     'double_inverted','invalid_polarity'):
            g=topology_graph();cell=Cone(g.module).flop('gate_enabled')[1]
            service=g.module['netnames']['serviceClock']['bits']
            if form=='direct_rising':cell['connections']['CLK']=service
            elif form=='inverted_falling':cell['parameters']['CLK_POLARITY']='0'
            elif form=='unrelated_falling':
                cell['connections']['CLK']=g.net('unrelatedClock');cell['parameters']['CLK_POLARITY']='0'
            elif form=='mixed':
                cell['connections']['CLK']=g.op('$not',g.op('$and',service,g.net('hiddenClockEnable')))
            elif form=='double_inverted':
                cell['connections']['CLK']=g.op('$not',cell['connections']['CLK'])
            else:cell['parameters']['CLK_POLARITY']='10'
            with self.subTest(form=form),self.assertRaisesRegex(ValueError,'GATE_FALLING_CLOCK$'):
                gate.prove_graph(g.module)

    def test_falling_normalization_preserves_enable_por_contract(self):
        for form in ('inverted','direct'):
            for fault in ('inverted_reset','negative_reset','reset_value'):
                g=topology_graph();cell=Cone(g.module).flop('gate_enabled')[1]
                if form=='direct':
                    cell['connections']['CLK']=g.module['netnames']['serviceClock']['bits']
                    cell['parameters']['CLK_POLARITY']='0'*32
                if fault=='inverted_reset':
                    cell['connections']['ARST']=g.op('$not',g.module['netnames']['reset']['bits'])
                elif fault=='negative_reset':cell['parameters']['ARST_POLARITY']='0'
                else:cell['parameters']['ARST_VALUE']='0'
                with self.subTest(form=form,fault=fault),self.assertRaisesRegex(ValueError,'GATE_ENABLE_POR$'):
                    gate.prove_graph(g.module)

    def test_actual_consumer_accepts_exact_two_edge_por_release(self):
        gate.prove_graph(local_ram_por(topology_graph()).module)

    def test_actual_consumer_rejects_altered_por_release(self):
        for stage in (0,1):
            for fault in ('clock','reset','data','clock_edge','reset_edge','reset_value'):
                g=local_ram_por(topology_graph())
                cell=Cone(g.module).flop('ca_child_ram_access.localReset_release_'+str(stage))[1]
                if fault=='clock':cell['connections']['CLK']=g.module['netnames']['serviceClock']['bits']
                elif fault=='reset':cell['connections']['ARST']=g.net('wrongReset')
                elif fault=='data':cell['connections']['D']=['1']
                elif fault=='clock_edge':cell['parameters']['CLK_POLARITY']='0'
                elif fault=='reset_edge':cell['parameters']['ARST_POLARITY']='0'
                else:cell['parameters']['ARST_VALUE']='0'
                with self.subTest(stage=stage,fault=fault),self.assertRaises(ValueError):gate.prove_graph(g.module)
        g=local_ram_por(topology_graph())
        Cone(g.module).flop('ca_child_ram_access.active')[1]['connections']['ARST']=g.module['netnames']['ca_child_ram_access.localReset_release_0']['bits']
        with self.assertRaisesRegex(ValueError,'GATE_CONSUMER_POR_RELEASE$'):gate.prove_graph(g.module)

    def test_every_ready_factor_is_essential(self):
        for predicate, good in gate.PREDICATES + (('gate_enabled',1),):
            with self.subTest(predicate=predicate):
                g=ready_graph(); bit=g.module['netnames'][predicate]['bits'][0]
                for cell in g.module['cells'].values():
                    for port, values in cell['connections'].items():
                        if cell['port_directions'][port]=='input':
                            cell['connections'][port]=[str(good) if b==bit else b for b in values]
                with self.assertRaises(ValueError): gate.prove_ready(Cone(g.module))

    def test_extra_condition_rejected(self):
        g=ready_graph(); ready=g.module['netnames']['fabric_io_request_ready']['bits']
        g.alias('fabric_io_request_ready',g.op('$and',ready,g.net('hiddenBlocker')))
        with self.assertRaisesRegex(ValueError,'COMPLETE_READY'): gate.prove_ready(Cone(g.module))

    def test_branch_and_alias_substitution_rejected(self):
        for target, source in (('fabric_ramOperation','fabric_nativeMmio'),
                               ('fabric_cpuAvailable','fabric_io_request_ready'),
                               ('fabric_bootWait','fabric_eventWait')):
            g=ready_graph();g.alias(target,g.module['netnames'][source]['bits'])
            with self.assertRaises(ValueError): gate.prove_ready(Cone(g.module))

    def test_clock_and_state_faults_rejected(self):
        for target in ('gate_enabled','gate_needClock','gate_drain','gate_grace','ca_child_ram_access.active','fabric_ram_state'):
            for port in ('CLK','ARST'):
                g=topology_graph(); cell=Cone(g.module).flop(target)[1]
                cell['connections'][port]=g.net('wrong_'+port)
                with self.subTest(target=target,port=port), self.assertRaises(ValueError): gate.prove_graph(g.module)

    def test_short_grace_and_skipped_synchronizer_rejected(self):
        for target in ('gate_grace','gate_needClock','gate_drain','gate_enabled'):
            g=topology_graph(); cell=Cone(g.module).flop(target)[1]
            cell['connections']['D']=['0']*len(cell['connections']['Q'])
            with self.subTest(target=target), self.assertRaises(ValueError): gate.prove_graph(g.module)

    def test_observer_and_macro_bypass_rejected(self):
        for target in ('receivingClock','rawRequest','rawAck','offered','ramGrantWaiting',
                       'captured_address','rawPayload_mask','accepted','wordAccepted'):
            g=topology_graph(); width=len(g.module['netnames'][target]['bits']);g.alias(target,['0']*width)
            with self.subTest(target=target), self.assertRaises(ValueError): gate.prove_graph(g.module)
        g=topology_graph();g.module['cells']['fabric_ram_macros_0']['connections']['CLK']=g.module['netnames']['serviceClock']['bits']
        with self.assertRaisesRegex(ValueError,'ACTUAL_MACRO_CLOCK'):gate.prove_graph(g.module)

    def test_exact_single_gate_mutation(self):
        for variant in ('bd','click'):
            texts,manifest=fixture(variant);before=copy.deepcopy(texts)
            name,changed,site=gate.mutate(texts,manifest,variant)
            self.assertEqual(changed,texts[name].replace('& gate_enabled;',"& 1'h1;"))
            self.assertEqual(texts,before);self.assertEqual(site['scope'],'Testbench')

    def test_wrong_receipt_or_qualification_rejected(self):
        for old,new in (('& gate_enabled;', '& other_gate;'),('& gate_enabled;', '& gate_enabled & gate_enabled;'),
                        ('.out_ready(fabric_io_request_ready)', '.out_ready(other_ready)')):
            texts,manifest=fixture('bd');name=manifest['top']+'.sv';texts[name]=texts[name].replace(old,new)
            with self.assertRaises(ValueError):gate.mutate(texts,manifest,'bd')

    def test_force_and_observation_whitelist(self):
        gate.validate_testbench(testbench())
        for old,new in (("force dut.gate_drainFirst=1'b0;", "force dut.gate_enabled=1'b0;"),
                        ('~dut.fabric_bootWait',"1'b1"),
                        ('&gatePredicates',"1'b1"),
                        ('release dut.gate_drainFirst;', ''),
                        ('initial begin','initial begin force dut.rawAck=0;')):
            with self.assertRaises(ValueError):gate.validate_testbench(testbench().replace(old,new))


if __name__ == '__main__':
    with patch('subprocess.Popen',side_effect=AssertionError('NO_HARDWARE_OR_CHILD_PROCESSES')):
        unittest.main()

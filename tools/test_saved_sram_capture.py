# SPDX-License-Identifier: Apache-2.0
"""Finite local proof-helper controls; these do not simulate emitted hardware."""
import copy
import unittest
from reset_bridge_proof import prove_sram_capture, saved_sram_address_width, sram_capacities


def fixture(capacity):
    width=saved_sram_address_width(capacity);serial=0;cells={};nets={};index=0
    def alloc(n):
        nonlocal serial
        result=list(range(serial+1,serial+n+1));serial+=n;return result
    def wire(name,n):
        bits=alloc(n);nets[name]=dict(bits=bits);return bits
    def gate(kind,pins,width):
        nonlocal index
        index+=1;y=alloc(width);connections=dict(pins,Y=y)
        cells['gate'+str(index)]=dict(type=kind,connections=connections,
            parameters={},port_directions={k:('output' if k=='Y' else 'input') for k in connections})
        return y
    def constant(value,width):return [str((value>>i)&1) for i in range(width)]
    def mux(select,a,b):return gate('$mux',dict(A=a,B=b,S=select),len(a))
    def eq(a,n):return gate('$eq',dict(A=a,B=constant(n,len(a))),1)
    clock=wire('service_clock',1);reset=wire('reset',1)
    state=wire('fabric_ram_state',2)
    cells['state']=dict(type='$adff',connections=dict(CLK=clock,ARST=reset,Q=state,D=state),
        parameters=dict(CLK_POLARITY='1',ARST_POLARITY='1',ARST_VALUE='00'),
        port_directions=dict(CLK='input',ARST='input',D='input',Q='output'))
    valids=[];inputs={}
    for lane in range(4):
        receipt=f'ca_child_ram_access.ca_child_byte_request_{lane}'
        nets[receipt+'.clock']=dict(bits=clock)
        valids.append(wire(receipt+'.out_valid',1))
        for field,n in dict(address=32,write=1,data=8,enable=1).items():
            data=wire(receipt+'.in_bits_'+field,n);inputs[lane,field]=data
            nets[receipt+'.out_bits_'+field]=dict(bits=data)
            nets[f'ca_child_ram_access.ca_child_native.byteRequest_{lane}_bits_{field}']=dict(bits=data)
    selected=constant(3,2)
    for lane in (2,1,0):selected=mux(valids[lane],selected,constant(lane,2))
    nets['fabric_ram_selected']=dict(bits=selected)
    ready=gate('$and',dict(A=eq(state,0),B=gate('$not',dict(A=reset),1)),1)
    has=gate('$reduce_or',dict(A=sum(valids,[])),1)
    capture=gate('$and',dict(A=ready,B=has),1)
    for lane in range(4):
        nets[f'ca_child_ram_access.ca_child_byte_request_{lane}.out_ready']=dict(
            bits=gate('$and',dict(A=ready,B=eq(selected,lane)),1))
    for field,n in dict(address=width,write=1,data=8,enable=1,tag=2).items():
        name='fabric_ram_'+('tag' if field=='tag' else 'saved_'+field)
        q=wire(name,n)
        data=selected if field=='tag' else inputs[3,field][:n]
        if field!='tag':
            for lane in (2,1,0):data=mux(eq(selected,lane),data,inputs[lane,field][:n])
        d=mux(capture,q,data)
        cells[name]=dict(type='$dff',connections=dict(CLK=clock,Q=q,D=d),parameters=dict(CLK_POLARITY='1'),
            port_directions=dict(CLK='input',Q='output',D='input'))
    module=dict(cells=cells,netnames=nets)
    return module,lambda r,c:r==reset and c==clock,inputs


class SavedWidthProof(unittest.TestCase):
    def test_capacity_width_and_independent_inventory(self):
        for capacity,width in ((4,2),(12,4),(1024,10),(2048,11),(1028,11),(3072,12)):
            self.assertEqual(saved_sram_address_width(capacity),width)
            inventory=dict(schema='riscay-gf180-sram-v1',macro='gf180mcu_ocd_ip_sram__sram1024x8m8wm1',
                program_bytes=capacity,working_ram_bytes=capacity,instances=[
                    dict(path=f'Top.fabric_{bank}_macros_{i}',bank=bank,index=i)
                    for bank in ('program','ram') for i in range((capacity+1023)//1024)])
            self.assertEqual(sram_capacities(inventory,'Top'),dict(program=capacity,ram=capacity))
            wrong=copy.deepcopy(inventory);wrong['instances'][0]['path']='Wrong.macro'
            with self.assertRaisesRegex(ValueError,'RDC_SRAM_INSTANCE_INVENTORY'):sram_capacities(wrong,'Top')
        for capacity in (0,-4,3,True,4.0,0x80000000):
            with self.assertRaisesRegex(ValueError,'RDC_SRAM_CAPACITY'):saved_sram_address_width(capacity)

    def test_all_128_capture_hold_and_priority_cases_at_each_width(self):
        for capacity in (4,12,1024,1028,2048,3072):
            module,por,_=fixture(capacity)
            result=prove_sram_capture(module,'ram',por,capacity)
            self.assertEqual(result['rows'],128)
            self.assertEqual(result['source_fields']['address'],32)
            self.assertEqual(result['retained_fields']['address'],saved_sram_address_width(capacity))
            self.assertEqual(set(result['payload']),{'fabric_ram_saved_'+f for f in ('address','write','data','enable')})

    def test_retained_address_bits_and_every_discarded_source_alias_remain_checked(self):
        for capacity in (4,12,1024,1028,2048,3072):
            module,por,inputs=fixture(capacity);width=saved_sram_address_width(capacity)
            for bit in range(width):
                fault=copy.deepcopy(module)
                fault['cells']['fabric_ram_saved_address']['connections']['D'][bit]=inputs[0,'address'][31]
                with self.assertRaisesRegex(ValueError,'RDC_SRAM_CAPTURE_address'):
                    prove_sram_capture(fault,'ram',por,capacity)
            for lane in range(4):
                for bit in range(width,32):
                    fault=copy.deepcopy(module)
                    name=f'ca_child_ram_access.ca_child_byte_request_{lane}.out_bits_address'
                    # The fixture aliases equal wire vectors through the same
                    # list object. Isolate this one net before a single-net
                    # mutation; otherwise deepcopy preserves shared identity.
                    fault['netnames'][name]['bits']=list(fault['netnames'][name]['bits'])
                    fault['netnames'][name]['bits'][bit]='0'
                    with self.assertRaisesRegex(ValueError,'RDC_SRAM_HELD_ALIAS'):
                        prove_sram_capture(fault,'ram',por,capacity)

    def test_width_is_bound_to_capacity_and_no_bank_wide_exemption(self):
        module,por,_=fixture(1024)
        with self.assertRaisesRegex(ValueError,'RDC_SRAM_CAPTURE_CLOCK'):prove_sram_capture(module,'ram',por,2048)
        for field in ('address','write','data','enable'):
            fault=copy.deepcopy(module)
            fault['cells']['fabric_ram_saved_'+field]['parameters']['CLK_POLARITY']='0'
            with self.assertRaisesRegex(ValueError,'RDC_SRAM_CAPTURE_CLOCK'):
                prove_sram_capture(fault,'ram',por,1024)

    def test_all_32_native_and_receipt_alias_bits_stay_checked(self):
        for capacity in (4,12,1024,1028,2048,3072):
            module,por,_=fixture(capacity)
            for lane in range(4):
                aliases=((f'ca_child_ram_access.ca_child_byte_request_{lane}.out_bits_address','RDC_SRAM_HELD_ALIAS'),
                         (f'ca_child_ram_access.ca_child_native.byteRequest_{lane}_bits_address','RDC_SRAM_NATIVE_ALIAS'))
                for name,diagnostic in aliases:
                    for bit in range(32):
                        fault=copy.deepcopy(module)
                        fault['netnames'][name]['bits']=list(fault['netnames'][name]['bits'])
                        fault['netnames'][name]['bits'][bit]='0'
                        with self.assertRaisesRegex(ValueError,diagnostic):
                            prove_sram_capture(fault,'ram',por,capacity)


if __name__=='__main__':unittest.main()

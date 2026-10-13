# SPDX-License-Identifier: Apache-2.0
"""Reject ordinary clocked storage anywhere inside catalogued native owners.

Library primitives retain their independently validated event/latch state.
Clocked boundary wrappers and the Services scheduler are deliberately outside
these roots; this check is not a claim that the whole SoC is clockless.
"""
import re

ROLES = ('Core','Fabric','Control','Telemetry','Housekeeping','Supervisor','Sram',
         'FrameStore','Elapsed','Sample','SpiAdc','I2c','Admission','Completion',
         'RamSource','RamReturn','ProgramSource','ProgramReturn','PublicationSource','RecoveryReturn')
PRIMITIVES = {'ChiselAsync'+name+'_v1' for name in ('ControlGate','AsymmetricC',
              'TimingMarker','ClosingLatch','EventRegister','And','ProtocolGuard',
              'PhaseRegister','Xor','ClickMarker')}


def native_clock_inventory(manifest, scopes):
    roots=[]; primitives={}
    def visit(node, native=False):
        if re.fullmatch(r'(?:FourPhase|Click)(?:'+'|'.join(ROLES)+r')(?:_\d+)?', node['module']):
            native=True; roots.append(node['rtl_path'])
        if native:
            for p in node.get('primitives',[]):
                if p['model'] not in PRIMITIVES or p['rtl_path'] in primitives:
                    raise ValueError('NATIVE_CLOCK_PRIMITIVE_KIND:'+p['rtl_path'])
                primitives[p['rtl_path']]=p['model']
        for child in node.get('children',[]): visit(child['contract'],native)
    visit(manifest['design'])
    if any(path not in scopes for path in roots):
        raise ValueError('NATIVE_CLOCK_INVENTORY_MISSING_ROOT')
    if any(scopes.get(path,{}).get('model') != model for path,model in primitives.items()):
        raise ValueError('NATIVE_CLOCK_PRIMITIVE_BINDING')
    checked=[]
    for path,scope in scopes.items():
        if not any(path == p or path.startswith(p+'.') for p in roots): continue
        if path in primitives: continue
        if any(path.startswith(p+'.') for p in primitives):
            raise ValueError('NATIVE_CLOCK_PRIMITIVE_DESCENDANT:'+path)
        if (scope.get('registers') or scope.get('memories') or
                any(n == 'clock' or n.endswith('_clock') for n in scope.get('ports',{}))):
            raise ValueError('NATIVE_CLOCKED_STATE:'+path)
        checked.append(path)
    if roots and not checked: raise ValueError('NATIVE_CLOCK_INVENTORY_EMPTY')
    return dict(roots=roots, checked=checked)

# SPDX-License-Identifier: Apache-2.0
"""Prove the uncontracted OpenDB graph before/after wire-dependent repair."""
from pathlib import Path
import json

from characterize_gf180_liberty import CORNERS
from gf180_estimate import library
from gf180_physical import ROOT, SC, sha, write_json
from repair_gf180_control import require
from repair_gf180_design import graph_proof, protected_cells, validate_sram_clock_drivers, validate_native_output_drivers, validate_native_input_drivers


def read_graph(path):
    cells={};ports={};nets={}
    def bit(name):
        require(name not in ('','NULL'),'PNR_REPAIR_DISCONNECTED_PIN')
        if name not in nets:nets[name]=len(nets)+1
        return nets[name]
    for line in path.read_text().splitlines():
        row=line.split('\t');kind=row[0]
        if kind=='C':
            require(len(row)==3 and row[1] not in cells,'PNR_REPAIR_CELL_ROW')
            cells[row[1]]=dict(type=row[2],connections={},port_directions={})
        elif kind=='P':
            require(len(row)==5 and row[1] in cells and row[2] not in cells[row[1]]['connections']
                and row[3] in ('input','output'),'PNR_REPAIR_PIN_ROW')
            c=cells[row[1]];c['connections'][row[2]]=[bit(row[4])];c['port_directions'][row[2]]=row[3]
        elif kind=='T':
            require(len(row)==4 and row[1] not in ports and row[2] in ('input','output'),'PNR_REPAIR_PORT_ROW')
            ports[row[1]]=dict(direction=row[2],bits=[bit(row[3])])
        else:raise ValueError('PNR_REPAIR_UNKNOWN_ROW')
    require(cells and ports,'PNR_REPAIR_EMPTY_GRAPH')
    return dict(modules=dict(RiscayMcuDigital=dict(ports=ports,cells=cells)))


def check(mapping,out,stage):
    require(stage in ('place','global'),'PNR_REPAIR_STAGE')
    files=[out/(stage+'-repair-'+side+'.tsv') for side in ('before','after')]
    frozen={str(p.resolve()):sha(p) for p in files}
    a,b=map(read_graph,files)
    libs=[library(ROOT/'.tools/physical/pdk'/(SC+c+'.lib')) for c in CORNERS]
    proof=graph_proof(a,b,'RiscayMcuDigital',protected_cells(mapping),libs)
    proof['sram_clock_drivers']=validate_sram_clock_drivers(b,'RiscayMcuDigital')
    original=json.loads((mapping/'electrical-repair/proof.json').read_text())
    if 'native_output_drivers' in original:
        proof['native_output_drivers']=validate_native_output_drivers(b,'RiscayMcuDigital',original['native_output_drivers'])
    if 'native_input_drivers' in original:
        proof['native_input_drivers']=validate_native_input_drivers(b,'RiscayMcuDigital',original['native_input_drivers'])
    proof['inputs_sha256']=frozen
    require(all(sha(Path(p))==h for p,h in frozen.items()),'PNR_REPAIR_INPUT_CHANGED')
    output=out/(stage+'-repair-proof.json');write_json(output,proof)
    return dict(proof_sha256=sha(output),inputs_sha256=frozen,
                protected_nets_sha256=sha(out/(stage+'-native-protected-nets.txt')))

# SPDX-License-Identifier: Apache-2.0
"""Negative controls on each complete emitted SoC's invalid-data fanout audit."""
import argparse
import json
from pathlib import Path
from native_allowance_audit import audit_elaborated, require
from gf180_physical import sha, write_json


def controls(export, output):
    export=Path(export).resolve(); output=Path(output).resolve()
    manifest_path=export/'contract.json'; graph_path=export/'reset-crossings/netlist.json'
    frozen={str(p):sha(p) for p in (manifest_path,graph_path,Path(__file__),
            Path(__file__).with_name('native_allowance_audit.py'),
            Path(__file__).with_name('passive_constant_proof.py'))}
    manifest=json.loads(manifest_path.read_text())['manifest']; db=json.loads(graph_path.read_text())
    baseline=audit_elaborated(db,manifest)
    require(baseline['instance_count']>0,'CONTROLS_EMPTY')
    source=baseline['instances'][0]['instance'].removeprefix(manifest['top']+'.')
    body=db['modules'][manifest['top']]; cells=body['cells']; bit=cells[source]['connections']['q'][0]
    target=baseline['instances'][0]['capture_sinks'][0]
    target_name=target['instance'].removeprefix(manifest['top']+'.')
    event=target['event_pin'].rsplit('.',1)[1]
    expected='ALLOWANCE_AUDIT_ELABORATED_INVALID_DATA_ESCAPE:'+source+':'
    cases=[]
    def run(name):
        try:audit_elaborated(db,manifest)
        except ValueError as exc:
            require(str(exc).startswith(expected),'CONTROLS_WRONG_FAILURE:'+name+':'+str(exc))
            cases.append(dict(fault=name,diagnostic=str(exc)))
        else:raise ValueError('ALLOWANCE_AUDIT_CONTROLS_FAULT_PASSED:'+name)
    for pin in (event,'reset'):
        old=cells[target_name]['connections'][pin]
        try:
            cells[target_name]['connections'][pin]=[bit]
            run('native-'+pin+'-from-invalid-payload')
        finally:cells[target_name]['connections'][pin]=old
    periodic=next((cell for cell in cells.values() if cell['type'] in ('$dff','$adff') and cell['connections'].get('D')),None)
    require(periodic is not None,'CONTROLS_NO_PERIODIC_SINK')
    old=periodic['connections']['D']
    try:
        periodic['connections']['D']=[bit,*old[1:]]
        run('periodic-D-from-invalid-payload')
    finally:periodic['connections']['D']=old
    require(all(sha(p)==h for p,h in frozen.items()),'CONTROLS_INPUT_CHANGED')
    output.parent.mkdir(parents=True,exist_ok=True)
    result=dict(inputs=frozen,baseline_instances=baseline['instance_count'],baseline_lanes=baseline['data_lanes'],controls=cases,
                scope='Actual full emitted graph, three exact structural invalid-consumer controls; not functional timing simulation')
    write_json(output,result)
    print('ALLOWANCE_CONTROLS_PASS:3')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('export',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();controls(a.export,a.output)

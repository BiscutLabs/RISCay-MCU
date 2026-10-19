# SPDX-License-Identifier: Apache-2.0
"""Matched mapping-only hierarchy cost; protected native recipes stay hierarchical.

This is not a routed candidate and does not bypass the production repair audit.
Uses the identical converted source/library/ABC settings as gf180_implement.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from gf180_estimate import groups, scalar, linux
from gf180_implement import leaves, instances
from gf180_physical import ROOT, SC, SRAM, write_json, sha, audit_alias_binding
from run_receipt import RunReceipt
from physical_tools import tool


def native_inventory(mapping, database, *, flat, audit_file=None):
    modules=database['modules']; hierarchy=dict(instances(modules,'RiscayMcuDigital'))
    audit=json.loads((audit_file or mapping/'netlist-audit.json').read_text())
    record=json.loads((mapping/'mapping.json').read_text())
    expected=set()
    for b in record['bindings']:
        for instance in b['instances']:
            path=audit['adapter_instances'][instance]
            path=path.replace('/','.') if flat else path
            if path not in hierarchy: raise ValueError('FLAT_NATIVE_INSTANCE_MISSING_'+path)
            module=modules[hierarchy[path]]; cells=module.get('cells',{})
            audit_alias_binding(b,module)
            if set(cells)!={c['name'] for c in b['cells']}: raise ValueError('FLAT_NATIVE_INVENTORY_'+path)
            def bit(net):
                if net in ("1'b0","1'b1"): return net[-1]
                match=re.fullmatch(r'(\w+)\[(\d+)\]',net)
                n,i=(match[1],int(match[2])) if match else (net,0)
                return module['netnames'][n]['bits'][i]
            for c in b['cells']:
                actual=cells[c['name']]
                if actual['type']!=c['cell'] or actual['connections']!={p:[bit(n)] for p,n in c['pins'].items()}:
                    raise ValueError('FLAT_NATIVE_GRAPH_'+path+'/'+c['name'])
            expected.add(path)
    actual={p for p,k in hierarchy.items() if k in {b['module'] for b in record['bindings']}}
    if actual!=expected: raise ValueError('FLAT_NATIVE_EXTRA_OR_MISSING')
    return len(expected)


def compare(mapping,out):
    out.mkdir(parents=True,exist_ok=False)
    lib=ROOT/'.tools/physical/pdk'/(SC+'tt_025C_3v30.lib')
    yosys=ROOT/'.tools/physical/root/usr/bin/yosys'; abc=yosys.with_name('yosys-abc')
    synthesis=json.loads((mapping/'synthesis-tools.json').read_text())
    for name,digest in synthesis['inputs_sha256'].items():
        path=Path(name)
        if not path.is_file() or sha(path)!=digest:
            raise ValueError('SYNTHESIS_COMPARISON_INPUT_CHANGED_'+name)
    selected=tool('yosys') if synthesis['configured_yosys'] else None
    if selected:
        yosys=selected.host_path();abc=selected.host_path(synthesis['abc'])
    for path in (yosys,abc):
        if str(path.resolve()) not in synthesis['inputs_sha256']:
            raise ValueError('SYNTHESIS_COMPARISON_TOOL_CHANGED_'+str(path))
    abc_path=synthesis['abc']
    reference=mapping/'electrical-repair/reference/netlist.json'
    if not reference.exists(): reference=mapping/'netlist.json'
    # PNR configuration re-runs the same audit and rewrites its report. This
    # comparison consumes a frozen copy, never a concurrently rewritten file.
    audit_file=out/'native-audit-input.json'
    audit_file.write_bytes((mapping/'netlist-audit.json').read_bytes())
    receipt=RunReceipt(out/'receipt.json',inputs=[mapping/'converted.v',mapping/'mapping.json',audit_file,mapping/'synthesis-tools.json',reference,lib],
                       tools=[Path(__file__),ROOT/'tools/gf180_implement.py',yosys,abc])
    script=out/'flat.ys'
    script.write_text(f'read_liberty -lib {linux(lib)}\nread_verilog -defer -sv {linux(mapping/"converted.v")}\n'
        'hierarchy -check -top RiscayMcuDigital\nflatten -noscopeinfo\nsynth -top RiscayMcuDigital -noabc\n'
        f'dfflibmap -liberty {linux(lib)}\nabc -exe {abc_path} -liberty {linux(lib)}\n'
        f'clean\ncheck\nstat -liberty {linux(lib)}\nwrite_json {linux(out/"netlist.json")}\n')
    command=selected.command(['-s',selected.path(script)],timeout=synthesis['timeout_seconds']) if selected else ['wsl','-e',linux(yosys),'-s',linux(script)]
    code=receipt.command(command,cwd=ROOT,log=out/'flat.log')
    if code: receipt.finish(outputs=[script,out/'flat.log'],status='fail')
    before=json.loads(reference.read_text()); after=json.loads((out/'netlist.json').read_text())
    # Audit both inventories against the mapped primitive recipes, not a count.
    native_inventory(mapping,before,flat=False,audit_file=audit_file)
    primitives=native_inventory(mapping,after,flat=True,audit_file=audit_file)
    area={n:scalar(b,'area') for n,b in groups(lib.read_text(),'cell')}
    def totals(db):
        counts=Counter(c['type'] for _,c in leaves(db['modules'],'RiscayMcuDigital'))
        if counts[SRAM]!=3: raise ValueError('FLAT_SRAM_INVENTORY')
        return dict(logic_mm2=sum(n*area[k] for k,n in counts.items() if k!=SRAM)/1e6,
                    cells=sum(counts.values()),sram_macros=counts[SRAM],masters=dict(counts))
    a,b=totals(before),totals(after)
    result=dict(hierarchical=a,flat=b,hierarchy_cost_mm2=a['logic_mm2']-b['logic_mm2'],
                hierarchy_cost_percent=100*(a['logic_mm2']/b['logic_mm2']-1),native_recipes_intact=primitives,
                scope='Mapped ordinary hierarchy vs ordinary flatten; native recipes protected in both. No repair/route/timing qualification.')
    write_json(out/'comparison.json',result)
    receipt.finish(outputs=[script,out/'flat.log',out/'netlist.json',out/'comparison.json'])
    print(json.dumps({k:v for k,v in result.items() if k not in ('hierarchical','flat')},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('mapping',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args(); compare(a.mapping.resolve(),a.output.resolve())

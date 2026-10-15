# SPDX-License-Identifier: Apache-2.0
"""Exact-site runner for reviewed emitted SPI slot-replay wiring mutations.

The plan must be bound to freshly emitted files before running the controls.
It cannot accept guessed assignment shapes, edited testbenches, generic crashes,
or stale sources. This supplements all mandatory strict export campaigns.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hashes(path):
    return {str(p.relative_to(path)):sha(p) for p in sorted(path.rglob('*')) if p.is_file()}


def require(condition, message):
    if not condition: raise ValueError('SPI_REPLAY_CONTROL_'+message)


def local_file(root, relative):
    part = Path(relative)
    require(bool(relative) and not part.is_absolute() and '..' not in part.parts,
            'NONLOCAL_PATH:'+str(relative))
    target = (root / part).resolve()
    require(target != root.resolve() and target.is_relative_to(root.resolve()),
            'NONLOCAL_PATH:'+str(relative))
    return target


def safe_name(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', value),
            'BAD_CASE_OR_GROUP_NAME')
    return value


def validate_coverage(plan):
    native = {'recipe-occupied', 'recipe-cs', 'recipe-sclk',
              'recipe-initial-cs', 'recipe-initial-sclk'}
    wire = native | {'slot-load', 'slot-advance', 'occupancy-terminal',
                     'divider-enable', 'miso-capture'}
    names = [safe_name(g['name']) for g in plan['groups']]
    require(len(names) == len(set(names)), 'DUPLICATE_GROUP')
    for group in plan['groups']:
        require(group['variant'] in ('bd', 'click') and group['mode'] in ('wire', 'strict'),
                'UNKNOWN_GROUP')
        labels = [safe_name(c['label']) for c in group['cases']]
        require(labels and len(labels) == len(set(labels)) and 'positive' not in labels,
                'DUPLICATE_OR_RESERVED_LABEL')
        require(all(c['family'] in (wire if group['mode'] == 'wire' else native)
                    for c in group['cases']), 'UNKNOWN_FAULT_FAMILY')
    for variant in ('bd', 'click'):
        for mode, required in (('wire', wire), ('strict', native)):
            observed = {c['family'] for g in plan['groups']
                        if g['variant'] == variant and g['mode'] == mode for c in g['cases']}
            require(required <= observed, 'MISSING_FAULT_FAMILY:'+variant+':'+mode)


def message_pattern(message):
    """Exact literal format, allowing only independently parsed scalar values."""
    result=''; offset=0
    for match in re.finditer(r'%(?:0?\d*)?([dhbf])',message):
        result+=re.escape(message[offset:match.start()])
        result+={'d':r'[ +-]*\d+', 'h':r'[0-9a-fA-FxXzZ]+',
                 'b':r'[01xXzZ]+', 'f':r'[ +-]*\d+(?:\.\d+)?'}[match[1]]
        offset=match.end()
    result+=re.escape(message[offset:])
    require('%' not in message[offset:],'UNKNOWN_FATAL_FORMAT')
    return result


def bind_sites(tb, declared):
    # Callers supply the expected actual task/named-block scope. Exact source
    # line is derived from the original file, never copied from a failing log.
    sites=[]
    for declaration in declared:
        literal=declaration['format'];scope=declaration['scope']
        pattern=r'\$fatal\s*\(\s*1\s*,\s*"'+re.escape(literal)+r'"'
        matches=list(re.finditer(pattern,tb))
        require(len(matches)==1,'FATAL_SITE_SHAPE:'+literal)
        match=matches[0]
        sites.append(dict(source=declaration.get('source','testbench.sv'),
            line=tb.count('\n',0,match.start())+1, scope=scope,
            format=literal, message_regex=message_pattern(literal)))
    require(bool(sites),'NO_FATAL_SITE')
    return sites


def classify(log, compiled, simulated, sites):
    require(compiled['exit_code']==0 and not compiled['timed_out'],'COMPILE_NOT_PASS')
    require(simulated['exit_code']==1 and not simulated['timed_out'],'SIMULATION_NOT_FAULT')
    require(not re.search(r'DEADLINE|TIMEOUT|RISCAY_SOC_PASS|CONTRACT_PROBES_PASS|\bERROR\b|syntax error',log,re.I),
            'UNRELATED_RESULT')
    lines=log.splitlines();records=[]
    for i,line in enumerate(lines):
        if 'fatal' not in line.lower():continue
        m=re.fullmatch(r'FATAL: (.+):(\d+): (.+)',line)
        require(m is not None and i+1<len(lines),'MALFORMED_FATAL')
        context=re.fullmatch(r'\s+Time: (\d+)\s+Scope: ([\w.]+)\s*',lines[i+1])
        require(context is not None,'MISSING_FATAL_CONTEXT')
        matches=[s for s in sites if (m[1],int(m[2]),context[2])==(s['source'],s['line'],s['scope'])
                 and re.fullmatch(s['message_regex'],m[3])]
        require(len(matches)==1,'WRONG_FATAL_SITE:'+m[3])
        records.append(dict(source=m[1],line=int(m[2]),message=m[3],scope=context[2],time=int(context[1])))
    require(bool(records),'NO_TARGET_FATAL')
    return records


def run(command, cwd, label, timeout):
    start=time.monotonic();timed_out=False
    try:
        result=subprocess.run(command,cwd=cwd,text=True,capture_output=True,timeout=timeout)
        code=result.returncode;log=result.stdout+result.stderr
    except subprocess.TimeoutExpired as error:
        timed_out=True;code=None
        def decode(x):return x.decode(errors='replace') if isinstance(x,bytes) else (x or '')
        log=decode(error.stdout)+decode(error.stderr)+'\nCONTROL_TIMEOUT\n'
    target=cwd/(label+'.log');target.write_text(log)
    return dict(command=command,exit_code=code,timed_out=timed_out,
                seconds=round(time.monotonic()-start,3),log_sha256=sha(target)),log


def nodes(node):
    yield node
    for child in node.get('children',[]):yield from nodes(child['contract'])


def execute(group, out):
    origin=Path(group['export']).resolve()
    require(origin.is_dir(),'EXPORT_MISSING')
    require(not out.is_relative_to(origin) and not origin.is_relative_to(out),'OVERLAP')
    before=tree_hashes(origin)
    require(group['export_tree_sha256']==hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),
            'STALE_EXPORT_TREE')
    for relative,expected in group['source_hashes'].items():
        require(before.get(relative)==expected,'STALE_SOURCE:'+relative)
    mode=group['mode'];require(mode in ('wire','strict'),'MODE')
    tb_name='testbench.sv' if mode=='wire' else 'contract_probe.sv'
    oracle=(origin/tb_name).read_text();oracle_sha=sha(origin/tb_name)
    require(group['oracle_sha256']==oracle_sha,'STALE_ORACLE')
    require(group['cases'],'NO_CASES')
    records=[]
    for case in [dict(label='positive')]+group['cases']:
        label=safe_name(case['label']);directory=out/label
        shutil.copytree(origin,directory)
        mutation=None
        if label!='positive':
            relative=case['file'];file=local_file(directory,relative)
            require(file != (directory/tb_name).resolve(),'BAD_MUTATION_FILE')
            require(sha(file)==case['source_sha256'],'MUTATION_SOURCE_HASH')
            old,new=case['old'],case['new'];text=file.read_text()
            require(old!=new and text.count(old)==1,'MUTATION_BINDING:'+label)
            file.write_text(text.replace(old,new))
            mutation=dict(file=relative,old=old,new=new,before=case['source_sha256'],after=sha(file))
        require(sha(directory/tb_name)==oracle_sha,'ORACLE_EDITED')
        manifest=json.loads((directory/'contract.json').read_text())['manifest']
        sources=[]
        for name in (directory/'filelist.f').read_text().splitlines():
            if not name.strip():continue
            original=(origin/name.strip()).resolve()
            require(original.is_relative_to(origin),'EXTERNAL_SOURCE:'+str(original))
            sources.append((directory/original.relative_to(origin)).resolve())
        if mode=='wire':
            sources += [(directory/Path(p['resource']).name).resolve()
                        for n in nodes(manifest['design']) for p in n.get('primitives',[])]
        if mutation:
            require((directory/mutation['file']).resolve() in sources,'MUTANT_NOT_COMPILED')
        command=['iverilog','-g2012']
        command+=['-s','Testbench'] if mode=='wire' else ['-DCHISEL_ASYNC_MAPPING','-s',manifest['top'],'-s','ContractProbe']
        command+=['-o','control.vvp',*map(str,dict.fromkeys(sources)),tb_name]
        def inputs():
            return dict(oracle=sha(directory/tb_name),
                        sources={str(p):sha(p) for p in dict.fromkeys(sources)})
        compiled_inputs=inputs()
        require(compiled_inputs['oracle']==oracle_sha,'ORACLE_CHANGED_BEFORE_COMPILE')
        compiled,_=run(command,directory,'compile',600)
        require(compiled['exit_code']==0 and not compiled['timed_out'],'COMPILE:'+label)
        require(inputs()==compiled_inputs,'INPUT_CHANGED_DURING_COMPILE')
        compiled_binary_sha=sha(directory/'control.vvp')
        simulated,log=run(['vvp','control.vvp'],directory,'simulation',group.get('timeout_seconds',900))
        require(inputs()==compiled_inputs,'INPUT_CHANGED_DURING_EXECUTION')
        require(sha(directory/'control.vvp')==compiled_binary_sha,'BINARY_CHANGED_DURING_EXECUTION')
        fatal=None
        if label=='positive':
            marker='RISCAY_SOC_PASS' if mode=='wire' else 'CONTRACT_PROBES_PASS:'
            require(simulated['exit_code']==0 and not simulated['timed_out'] and log.count(marker)==1
                    and not re.search(r'FATAL|TIMEOUT|DEADLINE|\bERROR\b',log,re.I),
                    'POSITIVE:'+label)
        else:
            sites=bind_sites(oracle,[dict(s,source=tb_name) for s in case['fatal_sites']])
            fatal=classify(log,compiled,simulated,sites)
        records.append(dict(label=label,mutation=mutation,compiled=compiled,simulated=simulated,fatal=fatal,
                            oracle_sha256=oracle_sha,binary_sha256=compiled_binary_sha,
                            executed_source_hashes=compiled_inputs['sources']))
        (out/'partial.json').write_text(json.dumps(records,indent=2)+'\n')
    require(tree_hashes(origin)==before,'ORIGINAL_EXPORT_MODIFIED')
    return dict(group=group['name'],mode=mode,records=records,originals_preserved=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();plan_sha=sha(args.plan);runner_sha=sha(Path(__file__))
    plan=json.loads(args.plan.read_text())
    require(plan.get('status')=='BOUND_TO_FRESH_EMITTED_RTL','PLAN_NOT_BOUND')
    validate_coverage(plan)
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    results=[]
    for group in plan['groups']:
        target=out/group['name'];target.mkdir();results.append(execute(group,target))
        (out/'results.json').write_text(json.dumps(dict(status='PARTIAL',groups=results),indent=2)+'\n')
    require(sha(args.plan)==plan_sha and sha(Path(__file__))==runner_sha,'RUNNER_OR_PLAN_CHANGED')
    receipt=dict(status='PASS',scope='actual emitted isolated faults; physical timing remains open',
                 plan_sha256=plan_sha,runner_sha256=runner_sha,groups=results)
    (out/'results.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('ALL_SPI_REPLAY_EXACT_SITE_CONTROLS_PASS')


if __name__=='__main__':main()

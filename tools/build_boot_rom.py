# SPDX-License-Identifier: Apache-2.0
"""Reproduce and audit the generic RV32E boot ROM with the pinned toolchain."""
from pathlib import Path
import json
import os
import subprocess
import sys
import hashlib
import re
from build_firmware import ROOT, TOOLCHAIN, FLAGS, audit_instructions, stack_bound

def main():
    if os.name == 'nt':
        path=subprocess.check_output(['wsl','-d','Ubuntu','--exec','wslpath','-a',str(Path(__file__).resolve())],text=True).strip()
        return subprocess.call(['wsl','-d','Ubuntu','--exec','python3',path])
    src=ROOT/'firmware/boot'
    out=ROOT/'build/generic-boot/rom'
    out.mkdir(parents=True,exist_ok=True)
    prefix=TOOLCHAIN/'root/usr/bin/riscv64-unknown-elf-'
    env=dict(os.environ,PATH=str(prefix.parent)+os.pathsep+os.environ.get('PATH',''))
    def run(tool,args):
        result=subprocess.run([str(prefix)+tool,*map(str,args)],cwd=out,env=env,text=True,capture_output=True)
        (out/(tool+'.log')).write_text(result.stdout+result.stderr)
        if result.returncode: raise RuntimeError(result.stdout+result.stderr)
        return result.stdout
    for name in ('startup.S','boot.c'):
        run('gcc',[*FLAGS,'-c',src/name,'-o',out/(name+'.o')])
    elf=out/'boot.elf'; binary=out/'boot.bin'
    run('gcc',['-march=rv32e','-mabi=ilp32e','-nostdlib','-Wl,--no-relax,--gc-sections',
               '-T',src/'link.ld',out/'startup.S.o',out/'boot.c.o','-o',elf])
    dis=run('objdump',['-d','-M','no-aliases,numeric',elf]); (out/'boot.dis').write_text(dis)
    count=audit_instructions(dis)
    run('objcopy',['-O','binary',elf,binary])
    data=binary.read_bytes(); assert len(data)%4==0
    symbols=run('nm',['-n',elf])
    capacity=re.findall(r'^([0-9a-f]+)\s+\w\s+riscay_program_capacity$',symbols,re.M)
    if len(capacity)!=1 or int(capacity[0],16)!=len(data)-4 or data[-4:]!=bytes.fromhex('dec0dec0'):
        raise ValueError('BOOT_CAPACITY_LITERAL_NOT_FINAL')
    bound,chain,frames=stack_bound([p.read_text() for p in out.glob('*.ci')],root='boot_main')
    if bound>256: raise ValueError(f'BOOT_STACK_EXCEEDS_MINIMUM_RAM:{bound}')
    resource=ROOT/'soc/src/main/resources/riscay/boot.hex';resource.parent.mkdir(parents=True,exist_ok=True)
    resource.write_text(''.join(f'{int.from_bytes(data[i:i+4],"little"):08x}\n' for i in range(0,len(data),4)))
    chain=[value.replace(str(ROOT)+'/','') for value in chain]
    frames={key.replace(str(ROOT)+'/',''):value for key,value in frames.items()}
    report={'schema':'riscay-generic-boot-v1','rom_bytes':len(data),'instructions':count,
            'program_capacity_offset':len(data)-4,'program_capacity_sentinel':'c0dec0de',
            'stack_bytes':bound,'stack_chain':chain,'frames':frames,'binary_sha256':hashlib.sha256(data).hexdigest(),
            'sources':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [src/'boot.c',src/'startup.S',src/'link.ld',Path(__file__)]}}
    (src/'rom-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0

if __name__=='__main__': sys.exit(main())

# SPDX-License-Identifier: Apache-2.0
"""STA-only desync sizing. Missing, stale, or unqualified measurements fail.

The region probe includes full- and half-cycle register paths. Chain measurement
is supplied by the physical generator fixture, including its actual boundary
load/slew; there is deliberately no RTL delay or library-table-floor fallback.
"""
import argparse
import json
import math
from pathlib import Path
from gf180_physical import ROOT, SC, SRAM, sha, write_json
from characterize_gf180_liberty import CORNERS
from physical_tools import tool
from run_receipt import RunReceipt
from clocked_physical import electrical_gate


REGION_PROBE = r'''
foreach launch {rise fall} {
  foreach capture {rise fall} {
    set sources [all_registers -${launch}_clock [get_clocks {service work}] -output_pins]
    set sinks [all_registers -${capture}_clock [get_clocks {service work}] -data_pins]
    set fraction [expr {$launch eq $capture ? 1.0 : 0.5}]
    if {![llength $sources] || ![llength $sinks]} {error REGION_STORAGE_INVENTORY}
    set paths [find_timing_paths -from $sources -to $sinks -path_delay max -group_path_count 1]
    puts "REGION_GROUP\t$launch\t$capture\t[llength $sources]\t[llength $sinks]\t[llength $paths]"
    foreach path $paths {
      set slack [get_property $path slack]
      set requirement [expr {($period*$fraction-$slack)/$fraction}]
      set pins {}; foreach point [get_property $path points] {lappend pins [get_full_name [get_property $point pin]]}
      puts "REGION_PATH\t$launch\t$capture\t$requirement\t[join $pins ,]"
    }
  }
}
'''


def positive(number, name):
    if isinstance(number, bool) or not isinstance(number, (float,int)) or not math.isfinite(number) or number <= 0:
        raise ValueError('DESYNC_INVALID_MEASUREMENT:' + name)
    return number


def select_count(rows, derate=1.2):
    positive(derate, 'derate')
    if derate < 1.2: raise ValueError('DESYNC_DERATE_REQUIRES_APPROVAL')
    if {r['corner'] for r in rows} != set(CORNERS) or len(rows) != len(CORNERS):
        raise ValueError('DESYNC_CORNER_COVERAGE')
    for r in rows:
        positive(r['requirement_ns'],'requirement')
        positive(r['unit_period_min_ns'],'unit-period')
        if not r.get('critical_path') or not r.get('electrical_pass'):
            raise ValueError('DESYNC_UNQUALIFIED_PATH')
    limiting = max(rows, key=lambda r: derate*r['requirement_ns']/r['unit_period_min_ns'])
    count = math.ceil(derate*limiting['requirement_ns']/limiting['unit_period_min_ns'])
    return count, limiting['corner']


def load_recipe(policy, name, netlist, measurement):
    """Only entry point a physical mapper may use. No default count exists."""
    if policy.get('schema') != 1 or name not in policy.get('lines',{}):
        raise ValueError('DESYNC_DELAY_ENTRY_MISSING:' + name)
    row=policy['lines'][name]
    if row.get('kind') != 'relative' or row.get('status') != 'sta-measured':
        raise ValueError('DESYNC_DELAY_NOT_PHYSICAL')
    if row.get('netlist_sha256') != sha(netlist) or row.get('measurement_sha256') != sha(measurement):
        raise ValueError('DESYNC_DELAY_MEASUREMENT_STALE')
    measured=json.loads(measurement.read_text())
    if measured.get('netlist_sha256')!=sha(netlist):
        raise ValueError('DESYNC_DELAY_MEASUREMENT_STALE')
    count, corner=select_count(measured['corners'],policy['derate'])
    if row['count'] != count or row['limiting_corner'] != corner or row['cell_mix'] != measured['cell_mix']:
        raise ValueError('DESYNC_DELAY_RECIPE_CHANGED')
    if len({c['cell'] for c in row['cell_mix']}) < 2:
        raise ValueError('DESYNC_DELAY_MIX_REQUIRED')
    # Final loaded chain must be remeasured; multiplying one-unit measurements
    # chooses a candidate, but cannot prove actual slew/endpoint loading.
    final=measured.get('final_chain',[])
    if len(final)!=len(CORNERS) or {r['corner'] for r in final}!=set(CORNERS):
        raise ValueError('DESYNC_FINAL_CHAIN_MISSING')
    required={r['corner']:r['requirement_ns'] for r in measured['corners']}
    for r in final:
        if (r.get('count') != count or r.get('cell_mix') != row['cell_mix'] or
                r.get('netlist_sha256') != sha(netlist)):
            raise ValueError('DESYNC_FINAL_CHAIN_IDENTITY')
        if not r.get('electrical_pass') or positive(r['period_min_ns'],'final-chain') < policy['derate']*required[r['corner']]:
            raise ValueError('DESYNC_FINAL_CHAIN_TOO_SHORT')
    return row


def publish_policy(netlist, measurement, name, destination):
    """Publish only measured relative recipes, never populate speculative lines.

Absolute constraints deliberately require a separate characterized pulse/hold
record; this initial API rejects them rather than applying the relative rule.
"""
    data=json.loads(measurement.read_text())
    count,corner=select_count(data['corners'])
    result=dict(schema=1,derate=1.2,
        derate_source='User engineering allowance; not measured GF180 mismatch',lines={name:dict(
            kind='relative',status='sta-measured',count=count,limiting_corner=corner,
            cell_mix=data['cell_mix'],netlist_sha256=sha(netlist),measurement_sha256=sha(measurement))})
    load_recipe(result,name,netlist,measurement)
    if destination.exists():raise ValueError('DESYNC_POLICY_OUTPUT_EXISTS')
    write_json(destination,result)
    return result


def measure_region(physical, output):
    """Run ordinary STA on the actual repaired+CTS netlist at each PVT."""
    output.mkdir(parents=True,exist_ok=False)
    sta=tool('sta'); pdk=ROOT/'.tools/physical/pdk'; macros=ROOT/'.tools/gf180-sram'
    netlist=physical/'cts.v'; sdc=physical/'cts.sdc'
    electrical=electrical_gate(physical)
    run=RunReceipt(output/'receipt.json',inputs=[netlist,sdc,physical/'cts-proof.json',
        *[physical/('cts-'+c+'-electrical.rpt') for c in CORNERS],
        *[pdk/(SC+c+'.lib') for c in CORNERS], *[macros/(SRAM+'__'+c+'.lib') for c in CORNERS]],
        tools=[Path(__file__),*sta.input_files()])
    rows=[]; files=[]
    try:
        for c in CORNERS:
            script=output/(c+'.tcl'); log=output/(c+'.log')
            script.write_text(f'read_liberty {{{sta.path(pdk/(SC+c+".lib"))}}}\n'
                f'read_liberty {{{sta.path(macros/(SRAM+"__"+c+".lib"))}}}\n'
                f'read_verilog {{{sta.path(netlist)}}}\nlink_design RiscayMcuDigital\n'
                f'read_sdc {{{sta.path(sdc)}}}\n'
                'set period [get_property [get_clocks service] period]\n'+REGION_PROBE+'\nexit\n')
            files += [script,log]
            if run.command(sta.command(['-exit',sta.path(script)],timeout=180),cwd=ROOT,log=log):
                raise ValueError('DESYNC_REGION_STA_FAILED')
            groups=[]; paths=[]
            for line in log.read_text().splitlines():
                fields=line.split('\t')
                if fields[0]=='REGION_GROUP': groups.append(fields[1:])
                if fields[0]=='REGION_PATH':
                    paths.append(dict(launch=fields[1],capture=fields[2],
                        requirement_ns=positive(float(fields[3]),'period'),critical_path=fields[4].split(',')))
            if len(groups)!=4 or not paths: raise ValueError('DESYNC_REGION_PATHS_MISSING')
            rows.append(dict(corner=c,groups=groups,paths=paths,**max(paths,key=lambda r:r['requirement_ns'])))
        result=output/'region.json'
        write_json(result,dict(netlist_sha256=sha(netlist),corners=rows,
            scope='Measured requirement envelope on CTS netlist, zero wire RC; not a generator recipe',
            electrical_violations=electrical,status='measured-requirements-only',lines={}))
        files.append(result)
        run.finish(outputs=files)
    except BaseException:
        if not run.finished: run.finish(outputs=[p for p in files if p.is_file()],status='fail')
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('physical',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--chain-measurement',type=Path,
        help='Publish validated loaded-chain evidence instead; physical argument is the measured netlist')
    p.add_argument('--line',default='fast-region')
    a=p.parse_args()
    if a.chain_measurement:publish_policy(a.physical.resolve(),a.chain_measurement.resolve(),a.line,a.output.resolve())
    else:measure_region(a.physical.resolve(),a.output.resolve())

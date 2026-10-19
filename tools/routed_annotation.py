# SPDX-License-Identifier: Apache-2.0
"""Strict OpenSTA annotation inventory and reported-path coverage.

Unqueried drivers remain visible in the inventory. Reported-path coverage alone
does not prove annotation of competing paths or of the entire timing cone.
"""
import re
import json
from pathlib import Path
import subprocess

from gf180_constraints import brace
from gf180_physical import ROOT, SC, SRAM


BEGIN = 'ROUTED_ANNOTATION_BEGIN'
END = 'ROUTED_ANNOTATION_END'
REPORT_TCL = f'puts {BEGIN}\nreport_parasitic_annotation -report_unannotated\nputs {END}\n'
DRIVERS_BEGIN = 'ROUTED_DRIVERS_BEGIN'
DRIVERS_END = 'ROUTED_DRIVERS_END'
# Pinned OpenSTA SPEF reader diagnostics include invalid units/name maps and
# malformed/wrong-net RC nodes, not only missing instances or load annotation.
SPEF_WARNING = r'\bSTA-(?:164[0-9]|165[0-7])\b'


def require(condition, diagnostic):
    if not condition:
        raise ValueError(diagnostic)


def parse_annotation(log):
    lines = log.splitlines()
    require(lines.count(BEGIN) == lines.count(END) == 1,
            'ROUTED_ANNOTATION_MARKERS')
    start, finish = lines.index(BEGIN), lines.index(END)
    require(start < finish, 'ROUTED_ANNOTATION_MARKERS')
    rows = lines[start+1:finish]
    inventory = {'unannotated': [], 'partial': {}}
    counts = {}
    section = None
    driver = None
    seen = set()
    for line in rows:
        header = re.fullmatch(r'Found (\d+) (unannotated|partially unannotated) drivers\.', line)
        if header:
            kind = 'unannotated' if header[2] == 'unannotated' else 'partial'
            require(kind not in counts and
                    (kind == 'unannotated' and section is None or
                     kind == 'partial' and section == 'unannotated'),
                    'ROUTED_ANNOTATION_SECTIONS')
            counts[kind] = int(header[1])
            section, driver = kind, None
        elif re.fullmatch(r' [^\s]+', line):
            require(section is not None, 'ROUTED_ANNOTATION_SHAPE')
            driver = line[1:]
            require(driver not in seen, 'ROUTED_ANNOTATION_DUPLICATE_DRIVER')
            seen.add(driver)
            if section == 'unannotated':
                inventory['unannotated'].append(driver)
            else:
                inventory['partial'][driver] = []
        elif re.fullmatch(r'  [^\s]+', line):
            require(section == 'partial' and driver is not None,
                    'ROUTED_ANNOTATION_LOAD_WITHOUT_DRIVER')
            load = line[2:]
            require(load not in inventory['partial'][driver],
                    'ROUTED_ANNOTATION_DUPLICATE_LOAD')
            inventory['partial'][driver].append(load)
        else:
            raise ValueError('ROUTED_ANNOTATION_SHAPE')
    require(set(counts) == {'unannotated', 'partial'} and
            all(len(inventory[k]) == counts[k] for k in counts),
            'ROUTED_ANNOTATION_COUNTS')
    return inventory


def check_paths(inventory, paths):
    """Reject every listed driver appearing anywhere in a reported path."""
    missing = set(inventory['unannotated']) | set(inventory['partial'])
    checked = set()
    for points in paths.values():
        require(isinstance(points, (list, tuple)) and points and
                all(isinstance(p, str) and p for p in points),
                'ROUTED_ANNOTATION_PATH_SHAPE')
        checked.update(points)
    failures = sorted(checked & missing)
    require(not failures, 'ROUTED_PATH_UNANNOTATED_' + ','.join(failures[:5]))
    return dict(checked_path_pins=len(checked),
                unrelated_unannotated_drivers=len(inventory['unannotated']),
                unrelated_partially_annotated_drivers=len(inventory['partial']),
                coverage='reported paths only; competing paths require separate coverage')


def parse_drivers(log):
    lines = log.splitlines()
    require(lines.count(DRIVERS_BEGIN) == lines.count(DRIVERS_END) == 1,
            'ROUTED_DRIVER_MARKERS')
    start, finish = lines.index(DRIVERS_BEGIN), lines.index(DRIVERS_END)
    require(start < finish, 'ROUTED_DRIVER_MARKERS')
    rows = lines[start+1:finish]
    require(rows and re.fullmatch(r'COUNT\t\d+', rows[-1]) is not None,
            'ROUTED_DRIVER_COUNT')
    drivers = {}
    for line in rows[:-1]:
        row = line.split('\t')
        require(len(row) == 3 and row[0] == 'DRIVER' and row[1] and
                re.fullmatch(r'\d+', row[2]) is not None,
                'ROUTED_DRIVER_SHAPE')
        require(row[1] not in drivers, 'ROUTED_DRIVER_DUPLICATE')
        drivers[row[1]] = int(row[2])
    require(len(drivers) == int(rows[-1].split('\t')[1]) and
            any(drivers.values()), 'ROUTED_DRIVER_COUNT')
    return drivers


def check_loaded_drivers(log):
    """Cover all live loads, including paths absent from extremal STA reports."""
    require(re.search(SPEF_WARNING, log) is None,
            'ROUTED_SPEF_ANNOTATION_INCOMPLETE')
    inventory = parse_annotation(log)
    drivers = parse_drivers(log)
    missing = set(inventory['unannotated']) | set(inventory['partial'])
    require(missing <= drivers.keys(), 'ROUTED_ANNOTATION_UNKNOWN_DRIVER')
    failures = sorted(set(inventory['partial']) |
                      {pin for pin in inventory['unannotated'] if drivers[pin] > 0})
    require(not failures, 'ROUTED_LOADED_DRIVER_UNANNOTATED_' + ','.join(failures[:5]))
    return dict(driver_count=len(drivers), loaded_driver_count=sum(n > 0 for n in drivers.values()),
                unannotated_count=len(inventory['unannotated']), partial_count=len(inventory['partial']),
                no_load_exclusions=sorted(inventory['unannotated']),
                coverage='all live load-bearing drivers; unloaded exclusions use actual connectivity')


def flat_export_name(name):
    """ODB's Verilog writer removes stored slash escapes from flat names."""
    result=name.replace('\\/','/')
    require('\\' not in result, 'ROUTED_FLAT_NAME_ESCAPE')
    return result


def flat_driver_report(log, ports):
    """Encode actual ODB identities as standalone STA's flat path names.

    The ODB export has literal slashes inside instance names. OpenSTA's
    annotation report escapes those slashes, unlike get_full_name. Build a
    bijection from the live inventory; never normalize an unknown report name.
    """
    drivers=parse_drivers(log); encoded={}
    for pin,count in drivers.items():
        escape=lambda name:flat_export_name(name).replace('/','\\/')
        if pin in ports:
            name=escape(pin)
        else:
            instance,separator,term=pin.rpartition('/')
            require(separator and instance and term, 'ROUTED_FLAT_DRIVER_SHAPE')
            name=escape(instance)+'/'+term
        require(name not in encoded, 'ROUTED_FLAT_DRIVER_COLLISION')
        encoded[name]=count
    return (DRIVERS_BEGIN+'\n'+''.join(f'DRIVER\t{p}\t{n}\n' for p,n in encoded.items())+
            f'COUNT\t{len(encoded)}\n'+DRIVERS_END+'\n')


DRIVER_TCL = '''
set block [ord::get_db_block]
set net_loads [dict create]
foreach net [$block getNets] {
  set count 0
  foreach pin [$net getITerms] {
    if {[$pin getSigType] ni {POWER GROUND} && [$pin getIoType] in {INPUT INOUT}} {incr count}
  }
  foreach pin [$net getBTerms] {
    if {[$pin getSigType] ni {POWER GROUND} && [$pin getIoType] in {OUTPUT INOUT}} {incr count}
  }
  dict set net_loads [$net getId] $count
}
puts ROUTED_DRIVERS_BEGIN
set driver_count 0
foreach inst [$block getInsts] {
  foreach pin [$inst getITerms] {
    if {[$pin getSigType] in {POWER GROUND} || [$pin getIoType] ni {OUTPUT INOUT}} {continue}
    set count 0
    if {[$pin getNet] ne "NULL"} {
      set count [dict get $net_loads [[$pin getNet] getId]]
      if {[$pin getIoType] eq "INOUT"} {incr count -1}
    }
    puts "DRIVER\t[$inst getName]/[[$pin getMTerm] getName]\t$count"
    incr driver_count
  }
}
foreach pin [$block getBTerms] {
  if {[$pin getSigType] in {POWER GROUND} || [$pin getIoType] ni {INPUT INOUT}} {continue}
  set count [dict get $net_loads [[$pin getNet] getId]]
  if {[$pin getIoType] eq "INOUT"} {incr count -1}
  puts "DRIVER\t[$pin getName]\t$count"
  incr driver_count
}
puts "COUNT\t$driver_count"
puts ROUTED_DRIVERS_END
'''


def run(odb, spef, selected, out, corner='tt_025C_3v30', *, export_netlist=None):
    """Read-only diagnostic; caller's run receipt owns these output artifacts."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    script = (f'read_liberty {brace(selected.path(ROOT/".tools/physical/pdk"/(SC+corner+".lib")))}\n'
              f'read_liberty {brace(selected.path(ROOT/".tools/gf180-sram"/(SRAM+"__"+corner+".lib")))}\n'
              f'read_db {brace(selected.path(odb))}\n'
              + (f'write_verilog {brace(selected.path(export_netlist))}\n' if export_netlist is not None else '') +
              f'read_spef {brace(selected.path(spef))}\n' + REPORT_TCL + DRIVER_TCL +
              'puts ROUTED_ANNOTATION_COMPLETE\nexit\n')
    script_path, log_path = out/'annotation.tcl', out/'annotation.log'
    script_path.write_text(script, encoding='utf-8')
    with log_path.open('w', encoding='utf-8') as stream:
        result = subprocess.run(selected.command(['-no_init', '-exit', selected.path(script_path)], timeout=110),
                                stdout=stream, stderr=subprocess.STDOUT, timeout=120)
    log = log_path.read_text()
    require(result.returncode == 0 and 'ROUTED_ANNOTATION_COMPLETE' in log and
            re.search(r'\[(?:ERROR|CRITICAL) ', log) is None,
            'ROUTED_ANNOTATION_COMMAND_FAILED')
    summary = check_loaded_drivers(log)
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    return summary

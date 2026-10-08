# SPDX-License-Identifier: Apache-2.0
"""GF180 schematic experiments. A passing run is NOT physical qualification."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request

from design import Design, netlist

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def models(fetch):
    paths = {}
    for item in json.loads((BASE / "sources.json").read_text()):
        path = ROOT / item["local"]
        if not path.is_file() and fetch and item["source"].endswith(".ngspice"):
            url = item["repository"].replace("github.com", "raw.githubusercontent.com")
            url += "/" + item["revision"] + "/" + item["source"]
            data = urllib.request.urlopen(url, timeout=30).read()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise RuntimeError("Downloaded model hash mismatch: " + item["source"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        if not path.is_file() or sha(path) != item["sha256"]:
            raise RuntimeError("Missing or changed pinned source: " + str(path))
        paths[path.name] = path
    # ngspice 42 mistakes l=r_l for the behavioral resistance in this raw PDK
    # statement. Keep the complete resistance expression, terminal resistors,
    # substrate capacitance and all corner/temperature coefficients. The body
    # resistor's noise-only model/geometry is omitted: these are transient/DC
    # experiments, not resistor-noise or jitter characterization.
    source = paths["sm141064.ngspice"].read_text()
    prepared = ROOT/".tools/gf180-models-prepared"
    prepared.mkdir(parents=True, exist_ok=True)
    (prepared/"sm141064.ngspice").write_text(prepare_resistor_model(source))
    paths["sm141064.ngspice"] = prepared/"sm141064.ngspice"
    return paths


def prepare_resistor_model(source):
    old = ("rb  11 21  ppolyf_u_3k_body l=r_l w=r_w\n"
           "+r='r_temp*r_n*(r_rsh0+r_vc1*abs(v(11,21))/r_n+r_vc2*abs(v(11,21))*abs(v(11,21))/r_n/r_n)'")
    if source.count(old) != 1:
        raise ValueError("Unrecognized PDK resistor statement; refusing to patch")
    return source.replace(old, "rb 11 21 " + old.split("\n+")[1])


def check_resistor(paths, folder, simulator):
    """Independent DC oracle catches silent model parsing errors before a sweep."""
    folder.mkdir()
    checks = []
    for corner, sheet in (("typical", 3000), ("ss", 3750), ("ff", 2250)):
        for temp in (-40, 25, 125):
            deckfile = folder/f"{corner}-{temp}.spice"
            deckfile.write_text(f"""Independent PDK resistor DC check
.include "{paths['design.ngspice'].as_posix()}"
.lib "{paths['sm141064.ngspice'].as_posix()}" res_{corner}
.param sw_stat_global=0 sw_stat_mismatch=0
.temp {temp}
VTEST test 0 1
XR test 0 0 ppolyf_u_3k r_width=1u r_length=3181.2u
.control
set numdgt=12
op
print i(vtest)
quit
.endc
.end
""")
            process = subprocess.run([simulator, "-b", deckfile.name], cwd=folder,
                                     capture_output=True, text=True, timeout=30)
            log = process.stdout+process.stderr
            deckfile.with_suffix(".log").write_text(log)
            found = re.search(r"i\(vtest\)\s*=\s*([-+\deE.]+)", log)
            if process.returncode or not found:
                raise RuntimeError("PDK resistor DC check failed to simulate")
            delta = temp-25
            width = 1e-6-2*.02256e-6
            body = sheet*(3181.2e-6+2*.0932e-6)/width
            body *= 1-.001669823*delta+3.74326e-6*delta**2
            ends = 2*33.16*1e-6/width*(1-.003763316*delta+9.81166e-6*delta**2)
            expected = 1/(body+ends)
            observed = -float(found.group(1))
            if abs(observed/expected-1) > 1e-5:
                raise RuntimeError(f"PDK resistor {corner}/{temp}: expected {expected}, got {observed} A")
            checks.append(dict(corner=corner, temp=temp, expected_a=expected, observed_a=observed))
    return checks


@dataclass(frozen=True)
class Case:
    name: str = "nominal"
    mos: str = "typical"
    resistor: str = "typical"
    vdd: float = 3.3
    temp: float = 25
    ramp: float = .0001
    load: float = 20e-15
    restart: bool = False
    stuck: bool = False
    step: float = 1e-4
    gmin: float = 1e-15
    duration: float = 3.0
    settle: float = .2


def crossing(a, b, threshold, index=1):
    return a[0] + (b[0] - a[0]) * (threshold - a[index]) / (b[index] - a[index])


def rising(rows, threshold):
    return [crossing(a, b, threshold) for a, b in zip(rows, rows[1:])
            if a[1] < threshold <= b[1]]


def integrate(rows, index, lo, hi):
    """Trapezoids with interpolated endpoints, including nonuniform timesteps."""
    total = 0.0
    for a, b in zip(rows, rows[1:]):
        left, right = max(lo, a[0]), min(hi, b[0])
        if left >= right:
            continue
        slope = (b[index] - a[index]) / (b[0] - a[0])
        y0 = a[index] + slope * (left - a[0])
        y1 = a[index] + slope * (right - a[0])
        total += (right - left) * (y0 + y1) / 2
    return total


def check_window(rows, lo, hi, vdd):
    samples = [r for r in rows if lo <= r[0] <= hi]
    edges = rising(samples, vdd / 2)
    if len(edges) < 6:
        raise ValueError(f"No sustained oscillation: {len(edges)} rising edges in [{lo}, {hi}]")
    periods = [b - a for a, b in zip(edges, edges[1:])]
    # No arbitrary low-frequency candidate wins merely by stopping or fading out.
    if max(periods) / min(periods) > 1.05 or edges[-1] < hi - 1.5 * max(periods):
        raise ValueError("Unstable/missing late cycles")
    duration = edges[-1] - edges[0]
    current = -integrate(samples, 2, edges[0], edges[-1]) / duration
    if not math.isfinite(current) or current <= 0:
        raise ValueError("Invalid supply current")
    # 10%-90% edge times; require a rail-to-rail clock rather than a tiny ripple.
    rise_start = fall_start = None
    rise_times, fall_times = [], []
    for a, b in zip(samples, samples[1:]):
        if a[1] < .1 * vdd <= b[1]:
            rise_start = crossing(a, b, .1 * vdd)
        if a[1] < .9 * vdd <= b[1] and rise_start is not None:
            rise_times.append(crossing(a, b, .9 * vdd) - rise_start)
            rise_start = None
        if a[1] > .9 * vdd >= b[1]:
            fall_start = crossing(a, b, .9 * vdd)
        if a[1] > .1 * vdd >= b[1] and fall_start is not None:
            fall_times.append(crossing(a, b, .1 * vdd) - fall_start)
            fall_start = None
    if min(len(rise_times), len(fall_times)) < len(edges) - 1:
        raise ValueError("Missing full-swing edges")
    if max(rise_times + fall_times) > 1e-6:
        raise ValueError("Output slew exceeds exploratory 1 us acceptance bound")
    return dict(hz=(len(edges)-1)/duration, current_na=current*1e9,
                power_nw=current*vdd*1e9, measured_cycles=len(edges)-1,
                max_rise_ns=max(rise_times)*1e9, max_fall_ns=max(fall_times)*1e9,
                period_spread=max(periods)/min(periods)-1,
                first_edge_s=edges[0], last_edge_s=edges[-1])


def analyze(rows, c):
    if len(rows) < 2 or any(not all(math.isfinite(x) for x in r) for r in rows):
        raise ValueError("Missing or non-finite waveform")
    if any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
        raise ValueError("Non-increasing simulation time")
    release = c.ramp + .005
    end = release + c.duration
    if rows[0][0] > 1e-8 or rows[-1][0] < end - c.step:
        raise ValueError("Truncated transient")
    reset_samples = [r for r in rows if c.ramp + .00001 <= r[0] <= release - 1e-6]
    if not reset_samples or max(abs(r[1]) for r in reset_samples) > .1*c.vdd:
        raise ValueError("Clock not held low during reset")
    edges = [t for t in rising(rows, c.vdd/2) if t >= release]
    if not edges or edges[0] - release > .1:
        raise ValueError("Startup exceeds 100 ms after POR release")
    windows = [(release+c.settle, end)]
    if c.restart:
        reset_start = release+c.duration/2
        reset_end = reset_start+.005
        reset_rows = [r for r in rows if reset_start+.00001 < r[0] < reset_end-1e-6]
        if not reset_rows or max(abs(r[1]) for r in reset_rows) > .1*c.vdd:
            raise ValueError("Restart reset did not park the clock")
        resumed = [t for t in edges if t > reset_end]
        if not resumed or resumed[0] - reset_end > .1:
            raise ValueError("Restart exceeds 100 ms")
        windows = [(release+c.settle, reset_start-.00001), (reset_end+c.settle, end)]
    results = [check_window(rows, a, b, c.vdd) for a, b in windows]
    result = results[-1].copy()
    result["windows"] = results
    result["startup_ms"] = (edges[0]-release)*1e3
    result["startup_energy_nj"] = -integrate(rows, 3, 0, edges[0])*1e9
    result["reset_power_nw"] = -integrate(rows, 3, c.ramp+.001, release-.0001)/(.0039)*1e9
    return result


def deck(c, paths):
    release, end = c.ramp+.005, c.ramp+.005+c.duration
    reset = f"0 0 {release} 0 {release+1e-7} {c.vdd}"
    if c.restart:
        a = release+c.duration/2
        b = a+.005
        reset += f" {a} {c.vdd} {a+1e-7} 0 {b} 0 {b+1e-7} {c.vdd}"
    if c.stuck:
        reset = "0 0"
    return f"""RISCay GF180 oscillator schematic experiment: {c.name}
.include "{paths['design.ngspice'].as_posix()}"
.lib "{paths['sm141064.ngspice'].as_posix()}" {c.mos}
.lib "{paths['sm141064.ngspice'].as_posix()}" res_{c.resistor}
.param sw_stat_global=0 sw_stat_mismatch=0
.temp {c.temp}
.options reltol=1e-4 abstol=1e-15 vntol=1e-7 gmin={c.gmin} method=gear maxord=2
.include "oscillator.spice"
VDD vdd 0 pwl(0 0 {c.ramp} {c.vdd})
VRESET rst_n 0 pwl({reset})
XDUT vdd 0 rst_n clk riscay_lf_osc_gf180
CLOAD clk 0 {c.load}
.control
set wr_singlescale
set wr_vecnames
set numdgt=12
set num_threads=1
save v(clk) v(vdd) i(vdd)
tran {c.step} {end} 0 {c.step}
let supply_power = v(vdd)*i(vdd)
wrdata wave.txt v(clk) i(vdd) supply_power
quit
.endc
.end
"""


def run_one(c, design, paths, out, simulator, timeout):
    folder = out/c.name
    # Reject reuse: an old waveform must never turn a failed simulation into PASS.
    folder.mkdir(parents=True, exist_ok=False)
    (folder/"oscillator.spice").write_text(netlist(design))
    (folder/"tb.spice").write_text(deck(c, paths))
    result = dict(case=asdict(c), design=asdict(design), passed=False,
                  netlist_sha256=sha(folder/"oscillator.spice"))
    try:
        with (folder/"ngspice.log").open("w") as log_file:
            proc = subprocess.run([simulator, "-b", "tb.spice"], cwd=folder,
                                  stdout=log_file, stderr=subprocess.STDOUT, timeout=timeout)
        log = (folder/"ngspice.log").read_text()
        if proc.returncode or re.search(r"\b(error|fatal)\b|timestep too small|run simulation\(s\) aborted", log, re.I):
            raise ValueError("Ngspice reported a simulation failure; inspect ngspice.log")
        with (folder/"wave.txt").open() as stream:
            next(stream)
            rows = [tuple(map(float, line.split())) for line in stream]
        result.update(analyze(rows, c))
        result["passed"] = True
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        result["error"] = str(error)
    (folder/"result.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


def campaign(suite):
    chosen = Design()
    if suite == "nominal":
        return [(Case(), chosen)]
    if suite == "sweep":
        return [(Case(name=f"r{r}-s{s}-b{b}", duration=max(.4, r*s/700), settle=.05),
                 replace(chosen, resistor_megohm=r, stages=s, buffer_stack=b))
                for r in (30, 100, 300) for s in (3, 5, 7) for b in (2, 4, 8)]
    if suite == "controls":
        return [(Case(name="disabled-control", stuck=True), chosen)]
    cases = [Case(name=f"{m}-{v}-{t}", mos=m, vdd=v, temp=t)
             for m in ("typical", "ss", "ff", "fs", "sf")
             for v in (3.0, 3.3, 3.6) for t in (-40, 25, 125)]
    cases += [Case(name=f"resistor-{r}", resistor=r) for r in ("ss", "ff")]
    cases += [Case(name="slow-ramp", ramp=.1), Case(name="fast-ramp", ramp=1e-6),
              Case(name="restart", restart=True), Case(name="heavy-load", load=100e-15),
              Case(name="half-step", step=5e-5), Case(name="lower-gmin", gmin=1e-16),
              Case(name="slow-combined", mos="ss", temp=-40, vdd=3.0,
                   resistor="ss", ramp=.1, load=100e-15),
              Case(name="fast-combined", mos="ff", temp=125, vdd=3.6,
                   resistor="ff", load=100e-15)]
    return [(c, chosen) for c in cases]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("nominal", "sweep", "pvt", "controls"), default="nominal")
    parser.add_argument("--fetch-models", action="store_true")
    parser.add_argument("--output", type=Path, required=True, help="New directory under build/")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--ngspice", default="ngspice")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT/"build") or output.exists():
        parser.error("--output must be a new directory below the repository build/")
    if args.jobs < 1 or args.jobs > 8:
        parser.error("--jobs must be 1..8")
    simulator = shutil.which(args.ngspice)
    if simulator is None:
        parser.error("ngspice is required; missing tools are not passing results")
    paths = models(args.fetch_models)
    version = subprocess.run([simulator, "--version"], capture_output=True, text=True, check=True)
    output.mkdir(parents=True)
    resistor_checks = check_resistor(paths, output/"resistor-check", simulator)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_one, c, d, paths, output, simulator, args.timeout)
                   for c, d in campaign(args.suite)]
        results = []
        for future in futures:
            result = future.result()
            results.append(result)
            summary = {k: result[k] for k in ("passed", "hz", "power_nw", "startup_ms", "error") if k in result}
            print(result["case"]["name"], json.dumps(summary), flush=True)
    passed = all(r["passed"] for r in results)
    if args.suite == "controls":
        passed = all(not r["passed"] and r.get("error", "").startswith("Startup exceeds")
                     for r in results)
    report = dict(scope="SCHEMATIC_ONLY_NOT_QUALIFIED", suite=args.suite, passed=passed,
                  simulator=version.stdout.strip(), sources=json.loads((BASE/"sources.json").read_text()),
                  characterizer_sha256=sha(Path(__file__)), generator_sha256=sha(BASE/"design.py"),
                  prepared_model_sha256=sha(paths["sm141064.ngspice"]),
                  resistor_dc_checks=resistor_checks, results=results)
    if args.suite == "controls":
        report["expected_rejection_verified"] = passed
    (output/"report.json").write_text(json.dumps(report, indent=2)+"\n")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

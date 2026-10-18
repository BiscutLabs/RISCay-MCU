# SPDX-License-Identifier: Apache-2.0
"""Actual mapped-arc negative controls and event-period invariance for the shared stage check."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import control_relative_timing as r


def fault_sdf(plan, fault, capture=None):
    cells=plan["native"]["cells"]
    prefix=plan['native'].get('physical_prefix','')
    if fault=="short_request":
        selected=[c for c in cells if c["path"].startswith(prefix+"ca_primitive_request_delay/") and c["cell"]==r.SC+"dlyd_1"]
        value=0.000001
    elif fault=="early_ack":
        roots=("ca_primitive_acknowledge/",) if plan["variant"]=="bd" else ("ca_primitive_acknowledge_guard/","ca_primitive_input_phase/")
        roots=tuple(prefix+p for p in roots)
        selected=[c for c in cells if c["path"].startswith(roots)]
        value=0.000001
    else:
        r.require(fault=="late_capture","RELATIVE_CONTROL_FAULT")
        # Delay the branch that drives lane zero's actual E/CLK, including its
        # other 15 payload pins. No payload or protocol pin is rewired.
        cap=capture or next(c for c in plan["contexts"] if c["id"]=="common")["queries"][0]["sink"]
        storage,pin=cap.rsplit("/",1)
        node=next(c for c in cells if c["path"]==storage)["pins"][pin]
        selected=[c for c in cells if c["pins"].get("Z")==node]
        r.require(len(selected)==1 and selected[0]["cell"]==r.SC+"buf_4","RELATIVE_CAPTURE_BRANCH")
        value=1000
    r.require(bool(selected),"RELATIVE_CONTROL_EMPTY")
    rows=[];arcs=[]
    for c in selected:
        output=next(p for p in ("Z","ZN","Q") if p in c["pins"])
        inputs=["CLK"] if output=="Q" else [p for p in c["pins"] if p!=output]
        paths=[]
        for p in inputs:
            # Do not annotate storage RN-to-Q arcs. Reset stays inactive;
            # phase-owner reset buffers can be included but cannot cause ACK.
            if p=="RN":continue
            number=f"{value:.6f}"
            paths.append(f'(IOPATH {p} {output} ({number}:{number}:{number}) ({number}:{number}:{number}))')
            arcs.append(dict(cell=c["path"],source=p,sink=output,delay_ns=value))
        instance=c["path"].replace(".","\\.")
        rows.append(f'(CELL (CELLTYPE "{c["cell"]}") (INSTANCE {instance}) (DELAY (ABSOLUTE '+" ".join(paths)+')))')
    return '(DELAYFILE (SDFVERSION "3.0") (DESIGN "'+plan["module"]+'") (DIVIDER /) (TIMESCALE 1ns)\n'+"\n".join(rows)+')\n',arcs

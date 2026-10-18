# SPDX-License-Identifier: Apache-2.0
"""Render an actual routed OpenDB checkpoint using the run's pinned OpenROAD GUI."""
import argparse
import os
from pathlib import Path
import struct
from gf180_constraints import brace
from gf180_pnr import pnr_tool, validate_provenance
from run_receipt import RunReceipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mapping', type=Path)
    parser.add_argument('run', type=Path)
    parser.add_argument('output', type=Path, help='Fresh render evidence directory')
    parser.add_argument('--width', type=int, default=2400)
    args = parser.parse_args()
    if not 256 <= args.width <= 8192: parser.error('Width must be 256..8192 pixels')
    mapping, run, output = (p.resolve() for p in (args.mapping, args.run, args.output))
    meta = validate_provenance(mapping, run, 'route')
    output.mkdir(parents=True, exist_ok=False)
    selected = pnr_tool(meta)
    database = run/'route.odb'
    script, picture, log = (output/name for name in ('render.tcl', 'layout.png', 'render.log'))
    area = ' '.join(map(str, meta['die_um']))
    script.write_text(f'read_db {brace(selected.path(database))}\n'
                      f'save_image -area {{{area}}} -width {args.width} {brace(selected.path(picture))}\n'
                      'puts RISCAY_LAYOUT_RENDERED\nexit\n', encoding='utf-8')
    receipt = RunReceipt(output/'receipt.json', inputs=[database, run/'run.json', script],
                         tools=[Path(__file__), selected.host_path()])
    # Offscreen Qt works on native Linux and through the configured WSL runtime.
    # No desktop window or screenshot crop is involved.
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    if selected.distribution:
        os.environ['WSLENV'] = ':'.join(filter(None, [os.environ.get('WSLENV'), 'QT_QPA_PLATFORM']))
    code = receipt.command(selected.command(['-gui', '-no_settings', '-exit', selected.path(script)]),
                           cwd=run, log=log)
    try:
        if code or 'RISCAY_LAYOUT_RENDERED' not in log.read_text(errors='replace'):
            raise ValueError('LAYOUT_RENDER_FAILED')
        header = picture.read_bytes()[:24]
        if header[:8] != b'\x89PNG\r\n\x1a\n': raise ValueError('LAYOUT_NOT_PNG')
        width, height = struct.unpack('>II', header[16:24])
        if width != args.width or height == 0: raise ValueError('LAYOUT_IMAGE_DIMENSIONS')
        x0, y0, x1, y1 = meta['die_um']
        if abs(height - width * (y1 - y0) / (x1 - x0)) > 2:
            raise ValueError('LAYOUT_IMAGE_ASPECT_RATIO')
        validate_provenance(mapping, run, 'route')
        receipt.finish(outputs=[picture, log], coverage=dict(width=width, height=height,
            die_um=meta['die_um'], checkpoint='route.odb', physical_qualification=False))
        print(picture)
    except Exception:
        if not receipt.finished: receipt.finish(outputs=[log], status='fail')
        raise


if __name__ == '__main__': main()

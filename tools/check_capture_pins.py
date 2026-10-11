# SPDX-License-Identifier: Apache-2.0
"""Actual custom EventRegister pin monitors for validated 100 ps envelopes."""

def capture_monitors(node,captures,prefix):
    cells={p['id']:p for p in node['primitives']}
    output=[]
    for name,fire in captures.items():
        path='dut.'+cells[name]['rtl_path'].split('.',1)[1]
        origin='dut.'+cells[fire]['rtl_path'].split('.',1)[1]+'.q'
        output.append(f'''
time pc_{name}_rise=0, pc_{name}_fall=0, pc_{name}_data=0, pc_{name}_fire=0;
reg pc_{name}_rose=0, pc_{name}_fell=0, pc_{name}_changed=0;
integer pc_{name}_count=0;
always @(posedge {origin}) pc_{name}_fire=$time;
always @({path}.d or posedge {path}.reset) begin
  if ({path}.reset) pc_{name}_changed=0;
  else if ({path}.reset === 1'b0) begin
    if (pc_{name}_rose && $time-pc_{name}_rise <= 100000)
      $fatal(1,"{prefix}_HOLD:{name}");
    pc_{name}_changed=1; pc_{name}_data=$time;
  end
end
always @(posedge {path}.trigger or posedge {path}.reset) begin
  if ({path}.reset) begin pc_{name}_rose=0; pc_{name}_fell=0; end
  else if ({path}.reset === 1'b0) begin
    #0;
    if (pc_{name}_fell && $time-pc_{name}_fall <= 100000)
      $fatal(1,"{prefix}_PULSE_LOW:{name}");
    if ({origin} !== 1'b1 || $time-pc_{name}_fire > 100000)
      $fatal(1,"{prefix}_SKEW:{name}");
    if (pc_{name}_changed && $time-pc_{name}_data <= 100000)
      $fatal(1,"{prefix}_SETUP:{name}");
    pc_{name}_rise=$time; pc_{name}_rose=1;
    pc_{name}_count=pc_{name}_count+1;
  end
end
always @(negedge {path}.trigger) if ({path}.reset === 1'b0 && pc_{name}_rose) begin
  if ($time-pc_{name}_rise <= 100000) $fatal(1,"{prefix}_PULSE_HIGH:{name}");
  pc_{name}_fall=$time; pc_{name}_fell=1;
end
''')
    return '\n'.join(output)

# SPDX-License-Identifier: Apache-2.0
"""GF180 clock/reset schematic generators. Geometry is in micrometres."""
from pathlib import Path


def mos(name, d, g, s, p=False, w=1, l=.28, bulk=None):
    b = bulk or ("vdd" if p else "vss")
    return (f"X{name} {d} {g} {s} {b} {'pmos' if p else 'nmos'}_3p3 "
            f"w={w:g}u l={l:g}u ad={w*.5:g}p as={w*.5:g}p "
            f"pd={2*(w+.5):g}u ps={2*(w+.5):g}u\n")


def inv(name, a, z, w=1, l=.28):
    return mos(name+"p", z, a, "vdd", True, 2*w, l) + mos(name+"n", z, a, "vss", False, w, l)


def nand(name, a, b, z, w=1):
    return (mos(name+"p0",z,a,"vdd",True,2*w)+mos(name+"p1",z,b,"vdd",True,2*w)+
            mos(name+"n0",z,a,name+"mid",w=2*w)+mos(name+"n1",name+"mid",b,"vss",w=2*w))


def resistor(name, a, b, ohms):
    # Nominal 3k high-res poly; real model includes contacts and drawn-width bias.
    length = max(1, ohms * .955 / 3000 - .1864)
    return f"X{name} {a} {b} vss ppolyf_u_3k r_width=1u r_length={length:g}u\n"


def cap(name, node, width=10, length=10):
    return mos(name,"vss",node,"vss",w=width,l=length)


def service_osc(resistance=240000, capacitance_width=10):
    s = """* SPDX-License-Identifier: Apache-2.0
* GF180 stopped RC ring; schematic candidate, not layout-qualified.
.subckt riscay_service_osc_gf180 vdd vss rst_n enable clk
"""
    s += inv("reset", "rst_n", "reset")
    # Transparent-low enable latch. Reset dominates and parks the ring/output.
    s += inv("phase", "raw", "raw_b")
    s += nand("input_enable", "enable", "rst_n", "desired_b")
    s += inv("desired", "desired_b", "desired")
    s += mos("passn","hold","raw_b","desired",w=1)
    s += mos("passp","hold","raw","desired",True,w=2)
    s += inv("hold0","hold","hold_b")
    s += inv("hold1","hold_b","held")
    s += mos("feedbackn","hold","raw","held",w=1)
    s += mos("feedbackp","hold","raw_b","held",True,w=2)
    s += mos("clear","hold","reset","vss",w=4)
    s += nand("run", "held", "rst_n", "run_b") + inv("runinv","run_b","run")
    s += nand("ring0","r4","run","drive0",w=.25)
    for i in range(5):
        if i:
            s += inv(f"ring{i}",f"r{i-1}",f"drive{i}",w=.25)
        s += resistor(f"r{i}",f"drive{i}",f"r{i}",resistance)
        s += cap(f"c{i}",f"r{i}",capacitance_width,1)
    s += inv("rawinv","r4","raw",w=.25)
    s += nand("outgate","raw","run","out_b") + inv("out","out_b","clk",w=2)
    return s + ".ends riscay_service_osc_gf180\n"


def supply_monitor(ptat_resistance=500000, gain=9.5):
    s = """* SPDX-License-Identifier: Apache-2.0
* GF180 bandgap-referenced supply monitor; schematic candidate.
* All timing/storage caps are MOS devices. No ideal sources inside macro.
.subckt riscay_supply_monitor_gf180 vdd vss good
"""
    # Equal-current 1:8 vertical PNP pair with a PMOS-input servo.
    s += "Xq1 vss vss e1 vpnp_0p42x5\n"
    for i in range(8):
        s += f"Xq2_{i} vss vss e2 vpnp_0p42x5\n"
    s += "Xq3 vss vss e3 vpnp_0p42x5\n"
    s += resistor("ptat","sense2","e2",ptat_resistance)
    s += resistor("gain","vref","e3",ptat_resistance*gain)
    for name,node in (("b1","e1"),("b2","sense2"),("b3","vref")):
        s += mos(name,node,"pbias","vdd",True,w=2,l=4)
    s += mos("tail","tail","pbias","vdd",True,w=4,l=4)
    s += mos("ip","mirror","e1","tail",True,w=8,l=2)
    s += mos("in","ampout","sense2","tail",True,w=8,l=2)
    s += mos("mp","mirror","mirror","vss",w=2,l=4)
    s += mos("mn","ampout","mirror","vss",w=2,l=4)
    s += mos("gainstage","pbias","ampout","vss",w=2,l=4)
    s += mos("gainload","pbias","pbias","vdd",True,w=2,l=4)
    s += resistor("startup","pbias","vss",30000000)
    s += cap("comp","pbias",20,10)
    s += mos("miller","ampout","pbias","ampout",w=40,l=10)
    s += cap("ampcomp","ampout",40,10)
    # NMOS differential comparator; resistor divider selects supply threshold.
    s += resistor("top","vdd","sense",1680000)
    s += resistor("bottom","sense","vss",1000000)
    s += resistor("hysteresis","good","sense",80000000)
    s += mos("cbiasp","cbias","pbias","vdd",True,w=2,l=4)
    s += mos("cbiasn","cbias","cbias","vss",w=2,l=4)
    s += mos("ctail","ctail","cbias","vss",w=4,l=4)
    s += mos("cp","cmirror","vref","ctail",w=8,l=2)
    s += mos("cn","cresult","sense","ctail",w=8,l=2)
    s += mos("clp","cmirror","cmirror","vdd",True,w=4,l=4)
    s += mos("cln","cresult","cmirror","vdd",True,w=4,l=4)
    s += inv("decision","cresult","decision",w=.22,l=10)
    s += inv("good0","decision","decision_b",w=.25)
    s += inv("good1","decision_b","good",w=1)
    return s + ".ends riscay_supply_monitor_gf180\n"


if __name__ == "__main__":
    base=Path(__file__).resolve().parent
    (base/"riscay_service_osc_gf180.spice").write_text(service_osc(),newline="\n")
    (base/"riscay_supply_monitor_gf180.spice").write_text(supply_monitor(),newline="\n")

# Attribution and modifications

This work is based on the current-starved oscillator architecture in
[Tim Edwards / Efabless, sky130_ef_ip__rc_osc_500k](https://github.com/RTimothyEdwards/sky130_ef_ip__rc_osc_500k),
revision `343f4481b2199efe4ddba48428c89fcf1029ae9a`. The upstream README identifies
Tim Edwards, Efabless Corporation, November 4, 2023 as the designer/date.

The exact upstream schematic netlist and Apache-2.0 license are preserved in
`upstream/`. They are reference material for SKY130, not GF180 implementation
files. `sources.json` pins their revisions and SHA-256 hashes. The project root
and the new design use Apache-2.0 as well. No upstream endorsement is implied.

RISCay modifications, 2026-10-07:

- Replace SKY130 devices with GF180 3.3 V transistors; use one 3.3 V rail and
  remove the 1.8 V level shifter.
- Replace the supply-to-diode bias resistor with a self-biased beta multiplier
  using a 4:1 NMOS ratio and a high-resistance poly source resistor.
- Add explicit POR-assisted bias startup and a reset-qualified clock output.
- Explore fewer ring stages and smaller bias current without a fixed frequency
  requirement. Use ordinary NMOS devices as timing capacitors instead of MIM.
- Add a stacked, long-channel input buffer and an intermediate driver to reduce
  current during slow ring transitions.

GF180 simulation models are Copyright 2022 GlobalFoundries PDK Authors,
Apache-2.0. The runner fetches pinned originals into ignored `.tools/`, verifies
hashes, and prepares a separately identified ngspice compatibility copy. It
retains the upstream notices. See the README for the exact modification and
limits of the resulting simulation evidence.

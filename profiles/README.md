# Application profiles

Profiles bind the reusable MCU to a particular board and firmware application.
The `profiles` sbt project depends on `shared`; neither CPU design depends on a
particular profile. Both variants must use the same profile in any comparison.

- [Groundlark](groundlark/README.md) is the first deployment profile.
- [Groundlark.scala](src/main/scala/riscay/profiles/Groundlark.scala) defines its
  logical application ID/registers, control GPIO roles and battery channel.

These are validated interface/build descriptions, not integrated SoC hardware.
Physical ADC wiring, pad selection, boot ROM contents and qualified numerical
power policy remain separate implementation work. A counter-only profile exists
as a test fixture in `HostSchemaSpec`; it adds no optional peripheral IP.

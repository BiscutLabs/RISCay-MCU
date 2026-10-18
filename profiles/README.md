# Application profiles

Profiles bind the reusable MCU to a particular board and firmware application.
The `profiles` sbt project depends on the common `soc`/`shared` projects. CPU
logic has no profile dependency. Profiles contain descriptors and capacities only;
they never select runtime behavior in RTL or mask ROM.
Both variants must use the same profile in any comparison.

- [Groundlark](groundlark/README.md) is the first deployment profile.
- [Groundlark.scala](src/main/scala/riscay/profiles/Groundlark.scala) defines its
  logical application ID/registers, control GPIO roles and battery channel.

All GPIOs and application words are firmware-owned. Generic external-SPI boot
replaces the former hardware power supervisor. Groundlark application firmware
and board changes are separate from this MCU workstream.

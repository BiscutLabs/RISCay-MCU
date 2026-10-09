# Application profiles

Profiles bind the reusable MCU to a particular board and firmware application.
The `profiles` sbt project depends on the common `soc`/`shared` projects. CPU
logic has no profile dependency; SoC emitters select an immutable `BoardProfile` factory. Each design supplies
its own native runtime controller; profiles contain descriptors and policy only.
Both variants must use the same profile in any comparison.

- [Groundlark](groundlark/README.md) is the first deployment profile.
- [Groundlark.scala](src/main/scala/riscay/profiles/Groundlark.scala) defines its
  logical application ID/registers, control GPIO roles and battery channel.

Groundlark includes a permanent hardware power controller, independent of the
uploaded application. Physical ADC wiring, pad selection and qualified numerical
power policy remain board work. Generic profiles can use firmware-owned GPIO and
application words with `GenericBoard`. Unrelated fixtures in the schema and SoC
tests exercise reuse without adding optional peripheral IP.

# RISCay-MCU contributor instructions

- Implement the MCU here; chisel-async and Chiselator remain separate projects.
- Deliver a reusable SoC with on-chip boot ROM, executable RAM and working RAM.
  Keep common CPU/host services independent of board names, pins and policy.
  Board/application bindings belong in `profiles/`; follow `docs/reusable-interface.md`.
  Groundlark's permanent bootstrap must qualify power and start its Pi without
  an application image. Other profiles must define their own boot dependency.
- Maintain both `designs/four-phase-bd/` and `designs/two-phase-click/` as active
  targets. Keep ISA, firmware, memory/MMIO, board I/O and functional tests equal.
- Native Click core routing must not silently use four-phase wrappers. Identify
  every external boundary conversion and include it in comparison costs.
- `soc/` owns the common clocked service island; keep both native CPU bridges
  explicit. Follow `docs/soc-contract.md` for wire commands, MMIO and reset scope.
  Run SocSpec/FabricSpec after changes there and keep strict SoC exports valid.
- Retained sleep and programmable sampling are in scope. Follow
  `docs/sleep-and-clock.md`; run SleepSpec, DeepSleepSpec and oscillator-model tests as well.
  Preserve the cold-boot policy, programming lock and watchdog fault coverage.
  An oscillator model or synthesis black box is not implemented analog IP.
- Analog oscillator work lives in `analog/gf180-lf-osc/`. Preserve upstream
  attribution and pinned model hashes. Run its independent measurement controls
  and SPICE campaigns after circuit changes; document any model transformation.
  Never bind a slower analog candidate to the 4 kHz timer without updating its
  time units, Gray CDC contract, watchdog and board timing policy together.
  Source-stopping builds require the documented address-only I2C wake probe;
  preserve its startup/hold bounds and do not claim the fast-source model is
  implemented analog IP. LF reset is POR-only, never watchdog-generated reset.
- Groundlark's permanent controller owns its power GPIOs. Keep its default policy
  disabled until qualified board/battery values are deliberately supplied.
- Optional features are on hold. Follow `docs/features-and-ip.md` and
  `docs/groundlark-io.md`; do not add heartbeat, RTC wake or diagnostics. Pi-assisted
  firmware reload after power loss is now in scope; persistent field updates are not.
- Loader status, validated-image reporting and a hardware programming lock are
  required in both variants. Follow `docs/loader-status-and-lock.md`; only full
  MCU reset or MCU power loss clears the lock. Pi resets and bus resets do not.
- Generic measurement channels and an application register area are required.
  Groundlark binds these to battery/supervisor telemetry. Include validity,
  freshness and calibration status; lock must not block reads or sample updates.
- Use explicit reset and async contracts. A digital delay model is not a mapped
  delay cell, and passing simulation is not physical timing or power evidence.
- Run the relevant ScalaTest/Icarus suites after changes. For architectural or
  interface changes, run both core variants against independent references.
  Missing tools, no activity, skipped tests and failed controls are not passes.
- Keep shared production logic separate from independently written test oracles.
  Test reset, stalls and exactly-once effects, not only instruction arithmetic.
- Keep generated RTL, tools, simulator logs and test evidence under ignored
  `.tools/`, `build/` or `target/` directories. Pin dependencies and record limits.
- Update README and affected contracts when behavior or implementation status
  changes. Communicate succinctly and distinguish implemented IP from planned IP.

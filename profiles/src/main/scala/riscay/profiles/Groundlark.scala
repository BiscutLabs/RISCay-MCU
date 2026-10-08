// SPDX-License-Identifier: Apache-2.0
package riscay.profiles

import riscay._

/** Groundlark descriptors. GroundlarkSupervisor supplies permanent control;
  * physical pads and qualified battery policy are separate board decisions.
  */
object Groundlark {
  val application = ApplicationProfile(
    id = 0x474c524bL, version = 1, name = "groundlark",
    registers = Vector(
      HostRegister(0, "SUPERVISOR_MODE"),
      HostRegister(1, "PI_POWER_ENABLE"),
      HostRegister(2, "SHUTDOWN_REQUESTED"),
      HostRegister(3, "HALT_ACK_QUALIFIED"),
      HostRegister(4, "SUPERVISOR_FAULT"),
      HostRegister(5, "SHUTDOWN_TIMEOUT_COUNT")),
    pins = Vector(
      PinRole(0, "pi_power_enable", output = true),
      PinRole(1, "pi_shutdown_request", output = true),
      PinRole(2, "pi_halted_n", output = false, activeLow = true)))

  val configuration = McuConfiguration(
    programBytes = 2048, workingRamBytes = 1024, gpioCount = 3,
    measurements = Vector(MeasurementChannel(0, "battery_voltage", MeasurementUnit.Volt, -3)),
    application = application)
}

// SPDX-License-Identifier: Apache-2.0
package riscay

/** Host ABI descriptors shared by hardware configuration and SDK/test discovery.
  * A wire frame carries (space, instance, word); these are not CPU addresses.
  */
object HostSpace {
  val Device = 0
  val Loader = 1
  val Measurement = 2
  val Application = 128
}

final case class HostAddress(space: Int, instance: Int, word: Int) {
  require(Seq(space, instance, word).forall(v => v >= 0 && v <= 255),
    "host address components must fit unsigned bytes")
}

/** Host-visible words are read-only. Loader mutations use explicit commands. */
final case class HostRegister(word: Int, name: String) {
  require(word >= 0 && word < 64, "register word must be in 0..63")
  require(name.matches("[A-Z][A-Z0-9_]*"), "register name must be an uppercase identifier")
}

object MeasurementUnit {
  val Unspecified = 0
  val Volt = 1
  val Count = 2
}

/** VALUE is signed 32-bit fixed point: physical value = VALUE * 10^scale10 unit.
  * Labels are build/SDK metadata and do not require strings in the device ROM.
  */
final case class MeasurementChannel(index: Int, label: String, unit: Int, scale10: Int) {
  require(index >= 0 && index < 16, "measurement channel must be in 0..15")
  require(label.nonEmpty, "measurement label must not be empty")
  require(unit >= 0 && unit <= 65535, "unit must fit an unsigned 16-bit code")
  require(scale10 >= -9 && scale10 <= 9, "decimal scale must be in -9..9")
}

/** Logical GPIO bindings; physical pads and electrical characteristics are board work. */
final case class PinRole(index: Int, name: String, output: Boolean, activeLow: Boolean = false,
    resetHigh: Boolean = false) {
  require(index >= 0 && index < 32, "GPIO index must be in 0..31")
  require(name.nonEmpty, "pin role must not be empty")
  require(output || !resetHigh, "an input does not drive a reset level")
}

final case class ApplicationProfile(id: Long, version: Int, name: String,
    registers: Vector[HostRegister], pins: Vector[PinRole]) {
  require(id > 0 && id <= 0xffffffffL, "application ID must be a nonzero unsigned word")
  require(version > 0 && version <= 65535, "application version must fit a nonzero halfword")
  require(name.nonEmpty, "application name must not be empty")
  require(registers.map(_.word).distinct.size == registers.size, "duplicate application register word")
  require(registers.map(_.name).distinct.size == registers.size, "duplicate application register name")
  require(pins.map(_.index).distinct.size == pins.size, "duplicate GPIO binding")
  require(pins.map(_.name).distinct.size == pins.size, "duplicate GPIO role")
}

/** Elaboration-time capacities, also reported by the hardware device service. */
final case class McuConfiguration(programBytes: Int, workingRamBytes: Int, gpioCount: Int,
    measurements: Vector[MeasurementChannel], application: ApplicationProfile) {
  require(programBytes > 0 && programBytes % 4 == 0, "program RAM must contain aligned words")
  require(workingRamBytes > 0 && workingRamBytes % 4 == 0, "working RAM must contain aligned words")
  require(gpioCount >= 0 && gpioCount <= 32, "GPIO count must be in 0..32")
  require(application.pins.forall(_.index < gpioCount), "profile references an absent GPIO")
  require(measurements.map(_.index) == measurements.indices.toVector,
    "measurement channels must be ordered and contiguous from zero")
  require(measurements.map(_.label).distinct.size == measurements.size, "duplicate measurement label")
}

object HostSchema {
  val abiMajor = 1
  val abiMinor = 0
  private def words(names: String*): Vector[HostRegister] =
    names.zipWithIndex.map { case (name, index) => HostRegister(index, name) }.toVector

  val device: Vector[HostRegister] = words("ABI_VERSION", "APPLICATION_ID", "APPLICATION_VERSION",
    "PROGRAM_BYTES", "WORKING_RAM_BYTES", "GPIO_COUNT", "MEASUREMENT_COUNT", "RESET_REASON")
  val loader: Vector[HostRegister] = words("MODE", "PROGRAMMED", "PROGRAM_LOCKED", "CAN_PROGRAM",
    "BUSY", "LAST_ERROR", "IMAGE_ID", "RECEIVED_BYTES")
  val measurement: Vector[HostRegister] = words("VALUE", "FLAGS", "AGE_MS", "SEQUENCE", "UNIT", "SCALE10")

  /** Unknown/absent resources resolve to None, never alias another service or RAM. */
  def resolve(config: McuConfiguration, address: HostAddress): Option[HostRegister] = {
    val fields = address.space match {
      case HostSpace.Device if address.instance == 0 => device
      case HostSpace.Loader if address.instance == 0 => loader
      case HostSpace.Measurement if address.instance < config.measurements.size => measurement
      case HostSpace.Application if address.instance == 0 => config.application.registers
      case _ => Vector.empty
    }
    fields.find(_.word == address.word)
  }
}

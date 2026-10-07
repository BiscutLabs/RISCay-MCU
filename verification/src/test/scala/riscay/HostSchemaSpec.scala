// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import riscay.profiles.{Groundlark, PowerPolicy}

class HostSchemaSpec extends AnyFunSuite {
  test("Groundlark policy requires valid bounds and hysteresis before enabling") {
    assert(!PowerPolicy().enabled)
    assert(PowerPolicy(enabled=true).enabled)
    intercept[IllegalArgumentException](PowerPolicy(enabled=true, restartMv=10100))
    intercept[IllegalArgumentException](PowerPolicy(enabled=true, shutdownMv=8000))
    intercept[IllegalArgumentException](PowerPolicy(enabled=true, shutdownTimeoutMs=9999))
    intercept[IllegalArgumentException](PowerPolicy(enabled=true, minimumOffMs=29999))
  }
  // Deliberately unrelated fixture: no Pi, battery, ADC or switched-host dependency.
  private val counter = McuConfiguration(1024, 128, 1,
    Vector(MeasurementChannel(0, "event_count", MeasurementUnit.Count, 0)),
    ApplicationProfile(0x434e5452L, 1, "test-counter",
      Vector(HostRegister(0, "COUNTER_MODE")), Vector(PinRole(0, "event_input", output = false))))

  private def read(c: McuConfiguration, space: Int, instance: Int, word: Int) =
    HostSchema.resolve(c, HostAddress(space, instance, word)).map(_.name)

  test("unrelated projects share device and loader ABI without Groundlark fields") {
    for(c <- Seq(counter, Groundlark.configuration)) {
      assert(read(c, 0, 0, 0).contains("ABI_VERSION"))
      assert(read(c, 0, 0, 1).contains("APPLICATION_ID"))
      assert(read(c, 1, 0, 1).contains("PROGRAMMED"))
      assert(read(c, 1, 0, 2).contains("PROGRAM_LOCKED"))
      assert(read(c, 2, 0, 0).contains("VALUE"))
    }
    assert(read(counter, 128, 0, 0).contains("COUNTER_MODE"))
    assert(read(Groundlark.configuration, 128, 0, 0).contains("SUPERVISOR_MODE"))
    assert(read(counter, 128, 0, 1).isEmpty)
    assert(!counter.application.pins.exists(_.name.contains("pi_")))
  }

  test("unknown spaces, instances and words do not alias another resource") {
    for(c <- Seq(counter, Groundlark.configuration)) {
      for(space <- 0 to 255; instance <- 0 to 2; word <- Seq(0, 5, 63, 255)) {
        val known = (space == 0 && instance == 0 && word < 8) ||
          (space == 1 && instance == 0 && word < 8) ||
          (space == 2 && instance == 0 && word < 6) ||
          (space == 128 && instance == 0 && word < (if(c == counter) 1 else 6))
        assert(HostSchema.resolve(c, HostAddress(space, instance, word)).isDefined == known,
          s"unexpected routing for $space/$instance/$word")
      }
    }
  }

  test("application bindings can change within the same hardware resource counts") {
    val board = Groundlark.configuration
    val reused = board.copy(application = counter.application, measurements = counter.measurements)
    assert((reused.programBytes, reused.workingRamBytes, reused.gpioCount, reused.measurements.size) ==
      (2048, 256, 3, 1))
    assert(read(reused, 128, 0, 0).contains("COUNTER_MODE"))
    assert(read(reused, 128, 0, 1).isEmpty)
    assert(reused.application.id != board.application.id)
    assert(reused.measurements.head.unit == MeasurementUnit.Count)
  }

  test("profiles reject ambiguous registers and unsafe or absent pin bindings") {
    val app = counter.application
    intercept[IllegalArgumentException](app.copy(registers = Vector(HostRegister(0,"A"), HostRegister(0,"B"))))
    intercept[IllegalArgumentException](app.copy(registers = Vector(HostRegister(0,"A"), HostRegister(1,"A"))))
    intercept[IllegalArgumentException](app.copy(pins = app.pins ++ app.pins))
    intercept[IllegalArgumentException](counter.copy(gpioCount = 0))
    intercept[IllegalArgumentException](PinRole(0, "input", output = false, resetHigh = true))
    intercept[IllegalArgumentException](counter.copy(programBytes = 1023))
    intercept[IllegalArgumentException](counter.copy(workingRamBytes = 0))
    intercept[IllegalArgumentException](HostAddress(256, 0, 0))
    intercept[IllegalArgumentException](HostRegister(64, "OUT_OF_RANGE"))
  }

  test("measurement discovery supports zero and multiple channels with explicit units") {
    val empty = counter.copy(measurements = Vector.empty)
    assert(read(empty, 2, 0, 0).isEmpty)
    val pair = counter.copy(measurements = counter.measurements :+
      MeasurementChannel(1, "supply_voltage", MeasurementUnit.Volt, -3))
    assert(read(pair, 2, 1, 0).contains("VALUE"))
    assert(read(pair, 2, 2, 0).isEmpty)
    assert(Groundlark.configuration.measurements.head.scale10 == -3)
    intercept[IllegalArgumentException](counter.copy(measurements = Vector(MeasurementChannel(1,"gap",0,0))))
    intercept[IllegalArgumentException](pair.copy(measurements = pair.measurements.map(_.copy(label="same"))))
    intercept[IllegalArgumentException](MeasurementChannel(16, "overflow", 0, 0))
  }
}

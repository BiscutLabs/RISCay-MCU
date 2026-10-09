// SPDX-License-Identifier: Apache-2.0
package riscay.click

import riscay.soc._

import chisel3._
import chisel3.util._
import chisel3.util.experimental.InlineInstance

class HostFrame extends Bundle {
  val length = UInt(6.W)
  val overflow = Bool()
  val bytes = Vec(33, UInt(8.W))
}

/** Bounded, oversampled I2C target; service clock >= 8 * SCL. SDA is open drain.
  * Writes commit at STOP/repeated START only. START abandons partial bytes.
  * Read address acceptance captures all 8 response words in a single snapshot.
  * No clock stretching, and a master must NACK its final byte.
  */
class I2cTarget(address: Int, idleCycles: Int) extends Module with InlineInstance {
  val io = IO(new Bundle {
    val scl = Input(Bool()); val sda = Input(Bool()); val pullLow = Output(Bool())
    val frame = Valid(new HostFrame)
    val readStart = Output(Bool()); val wordIndex = Output(UInt(4.W))
    val readWord = Input(UInt(32.W))
    val busy = Output(Bool())
    val selected = Output(Bool()); val rejected = Output(Bool())
  })
  val sclSync = RegInit(3.U(2.W)); sclSync := Cat(sclSync(0), io.scl)
  val sdaSync = RegInit(3.U(2.W)); sdaSync := Cat(sdaSync(0), io.sda)
  val scl = sclSync(1); val sda = sdaSync(1)
  val lastScl = RegNext(scl, true.B); val lastSda = RegNext(sda, true.B)
  val rise = scl && !lastScl; val fall = !scl && lastScl
  val start = scl && lastScl && !sda && lastSda
  val stop = scl && lastScl && sda && !lastSda
  val busActive = RegInit(false.B)
  val idle = RegInit(0.U(log2Ceil(idleCycles).W))
  val changed = scl =/= lastScl || sda =/= lastSda
  val timeout = busActive && !changed && idle === (idleCycles-1).U
  when(!busActive || changed || timeout) { idle := 0.U }.otherwise { idle := idle + 1.U }
  when(start) { busActive := true.B }.elsewhen(stop) { busActive := false.B }
  io.busy := busActive || start || stop
  val state = RegInit(0.U(4.W))
  val addressByte = RegInit(true.B)
  val selectedWrite = RegInit(false.B)
  val receive = RegInit(0.U(8.W)); val bit = RegInit(0.U(3.W))
  val drive = RegInit(false.B); val ack = RegInit(false.B)
  val reading = RegInit(false.B); val masterAck = RegInit(false.B)
  val length = RegInit(0.U(6.W)); val overflow = RegInit(false.B)
  val bytes = Reg(Vec(33, UInt(8.W)))
  val send = Reg(UInt(32.W)); val sent = RegInit(0.U(6.W))
  val assembled = Cat(receive(6, 0), sda)
  io.readStart := !timeout && state === 1.U && rise && bit === 7.U && addressByte &&
    assembled(7,1) === address.U && assembled(0)
  io.wordIndex := ((sent +& 1.U) >> 2)(3,0)
  io.pullLow := drive
  io.frame.valid := !timeout && (start || stop) && selectedWrite && length =/= 0.U
  io.selected := busActive && !addressByte && ack
  io.rejected := state === 1.U && rise && bit === 7.U && addressByte && assembled(7,1) =/= address.U
  io.frame.bits.length := length
  // Preparing STOP/repeated START creates one sampled SCL rise after the ACK.
  // Two or more trailing bits indicate a genuinely interrupted extra byte.
  io.frame.bits.overflow := overflow || bit > 1.U || state =/= 1.U
  io.frame.bits.bytes := bytes
  when(timeout || start || stop) {
    state := Mux(start && !timeout, 1.U, 0.U); addressByte := true.B
    selectedWrite := false.B; reading := false.B; drive := false.B
    bit := 0.U; length := 0.U; overflow := false.B
    when(timeout) { busActive := false.B }
  }.otherwise {
    switch(state) {
      is(1.U) { when(rise) {
        receive := assembled; bit := bit + 1.U
        when(bit === 7.U) {
          state := 2.U
          when(addressByte) {
            ack := assembled(7, 1) === address.U
            reading := assembled(0)
            selectedWrite := assembled(7, 1) === address.U && !assembled(0)
            when(assembled(7, 1) === address.U && assembled(0)) { sent := 0.U }
          }.otherwise {
            ack := length < 33.U
            when(length < 33.U) { bytes(length) := assembled; length := length + 1.U }
              .otherwise { overflow := true.B }
          }
        }
      } }
      is(2.U) { when(fall) { drive := ack; state := 3.U } }
      is(3.U) { when(rise) { state := 4.U } }
      is(4.U) { when(fall) {
        drive := false.B; addressByte := false.B
        when(!ack) { state := 0.U; busActive := false.B }
          .elsewhen(reading) { send := io.readWord; drive := !io.readWord(7); state := 5.U }
          .otherwise { state := 1.U }
      } }
      is(5.U) {
        when(rise) { bit := bit + 1.U; when(bit === 7.U) { state := 6.U } }
        when(fall) { drive := !send(7, 0)(7.U - bit) }
      }
      is(6.U) { when(fall) { drive := false.B; state := 7.U } }
      is(7.U) { when(rise) { masterAck := !sda; state := 8.U } }
      is(8.U) { when(fall) {
        when(masterAck && sent < 35.U) {
          val nextWord = Mux(sent(1,0) === 3.U, io.readWord, Cat(0.U(8.W), send(31,8)))
          send := nextWord; sent := sent + 1.U
          drive := !nextWord(7); state := 5.U
        }.otherwise { drive := false.B; state := 0.U; busActive := false.B }
      } }
    }
  }
}

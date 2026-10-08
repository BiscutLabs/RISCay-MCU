// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import chisel3.util._
import chisel3.experimental.BundleLiterals._
import chisel3.experimental.VecLiterals._

object Operation {
  val Fetch = 0
  val Read = 1
  val Write = 2
  val Halt = 3
}

/** Byte-addressed little-endian bus. Data is lane-aligned to address & ~3.
  * Masks select physical byte lanes; exactly one response follows each request.
  * Halt is a terminal notification and must not receive a response before reset.
  */
class MemoryRequest extends Bundle {
  val operation = UInt(2.W)
  val address = UInt(32.W)
  val data = UInt(32.W)
  val mask = UInt(4.W)
}
class MemoryResponse extends Bundle {
  val data = UInt(32.W)
  val error = Bool()
}
class Retirement extends Bundle {
  val valid = Bool()
  val pc = UInt(32.W)
  val instruction = UInt(32.W)
  val rd = UInt(4.W)
  val data = UInt(32.W)
  val writeRegister = Bool()
  val trap = Bool()
  val cause = UInt(4.W)
}

class RegisterWrite extends Bundle {
  val enable = Bool(); val rd = UInt(4.W); val data = UInt(32.W)
}

/** Control and one pending writeback travel with the token. The architectural
  * register file and debug trace are not copied around the feedback loop.
  */
class CoreState extends Bundle {
  val pc = UInt(32.W)
  val operation = UInt(2.W)
  val instruction = UInt(32.W)
  val address = UInt(32.W)
  val storeData = UInt(32.W)
  val mask = UInt(4.W)
  // A pending memory operation already retains its complete instruction.
  def loadKind: UInt = instruction(14, 12)
  def destination: UInt = instruction(10, 7)
  val writeback = new RegisterWrite
}
object CoreState {
  def initial: CoreState = (new CoreState).Lit(
    _.pc -> 0.U(32.W), _.operation -> Operation.Fetch.U(2.W),
    _.instruction -> 0.U(32.W), _.address -> 0.U(32.W),
    _.storeData -> 0.U(32.W), _.mask -> 0.U(4.W),
    _.writeback -> (new RegisterWrite).Lit(
      _.enable -> false.B, _.rd -> 0.U(4.W), _.data -> 0.U(32.W)))
}

class ExecutionInput extends Bundle {
  val state = new CoreState; val response = new MemoryResponse
  // Wires from the single RF, never stored in the state/join token. Selection
  // here places read mux delay inside the execute transform timing budget.
  val registers = Vec(15, UInt(32.W))
  private def read(index: UInt): UInt = MuxLookup(index, 0.U(32.W))(
    (1 to 15).map(i => i.U -> registers(i-1)))
  def a: UInt = read(response.data(19,15))
  def b: UInt = read(response.data(24,20))
}
class ExecutionResult extends Bundle {
  val state = new CoreState; val trace = new Retirement
}

/** Shared combinational ISA semantics; the two designs own all protocol state.
  * RV32E v2.0, IALIGN=32, no compressed, CSR, privileged or M instructions yet.
  */
object Execute {
  def request(s: CoreState): MemoryRequest = {
    val r = Wire(new MemoryRequest)
    r.operation := s.operation
    r.address := Mux(s.operation === Operation.Fetch.U || s.operation === Operation.Halt.U, s.pc, s.address)
    r.data := Mux(s.operation === Operation.Write.U, s.storeData, 0.U)
    r.mask := Mux(s.operation === Operation.Halt.U, 0.U, Mux(s.operation === Operation.Fetch.U, 15.U, s.mask))
    r
  }

  def step(s: CoreState, response: MemoryResponse, a: UInt, b: UInt): ExecutionResult = {
    val n = Wire(new CoreState)
    n := s
    val trace = WireDefault(0.U.asTypeOf(new Retirement))
    n.writeback := 0.U.asTypeOf(new RegisterWrite)
    val insn = response.data
    val opcode = insn(6, 0)
    val rd = insn(11, 7)
    val f3 = insn(14, 12)
    val rs1 = insn(19, 15)
    val rs2 = insn(24, 20)
    val f7 = insn(31, 25)
    val immI = Cat(Fill(20, insn(31)), insn(31, 20))
    val immS = Cat(Fill(20, insn(31)), insn(31, 25), insn(11, 7))
    val immB = Cat(Fill(19, insn(31)), insn(31), insn(7), insn(30, 25), insn(11, 8), 0.U(1.W))
    val immU = Cat(insn(31, 12), 0.U(12.W))
    val immJ = Cat(Fill(11, insn(31)), insn(31), insn(19, 12), insn(20), insn(30, 21), 0.U(1.W))
    val sequential = s.pc + 4.U

    def fault(cause: UInt, instruction: UInt): Unit = {
      n.operation := Operation.Halt.U
      trace.valid := true.B
      trace.pc := s.pc
      trace.instruction := instruction
      trace.trap := true.B
      trace.cause := cause
      trace.writeRegister := false.B
    }
    def retire(instruction: UInt): Unit = {
      n.pc := sequential
      n.operation := Operation.Fetch.U
      trace.valid := true.B
      trace.pc := s.pc
      trace.instruction := instruction
    }
    def write(index: UInt, value: UInt): Unit = {
      when(index =/= 0.U) {
        n.writeback.enable := true.B; n.writeback.rd := index(3,0); n.writeback.data := value
        trace.writeRegister := true.B
        trace.rd := index(3, 0)
        trace.data := value
      }
    }

    when(s.operation === Operation.Fetch.U) {
      val legal = WireDefault(false.B)
      val usesRd = WireDefault(false.B)
      val usesA = WireDefault(false.B)
      val usesB = WireDefault(false.B)
      val result = WireDefault(0.U(32.W))
      val target = WireDefault(sequential)
      val writeRd = WireDefault(false.B)
      val memory = WireDefault(false.B)
      val store = WireDefault(false.B)
      val address = WireDefault(0.U(32.W))
      val misaligned = WireDefault(false.B)
      val systemCause = WireDefault(0.U(4.W))
      val systemTrap = WireDefault(false.B)
      switch(opcode) {
        is("h37".U) { legal := true.B; usesRd := true.B; writeRd := true.B; result := immU }
        is("h17".U) { legal := true.B; usesRd := true.B; writeRd := true.B; result := s.pc + immU }
        is("h6f".U) { legal := true.B; usesRd := true.B; writeRd := true.B; result := sequential; target := s.pc + immJ }
        is("h67".U) {
          legal := f3 === 0.U; usesRd := true.B; usesA := true.B; writeRd := true.B
          result := sequential; target := (a + immI) & "hfffffffe".U
        }
        is("h63".U) {
          usesA := true.B; usesB := true.B
          val take = WireDefault(false.B)
          switch(f3) {
            is(0.U) { legal := true.B; take := a === b }
            is(1.U) { legal := true.B; take := a =/= b }
            is(4.U) { legal := true.B; take := a.asSInt < b.asSInt }
            is(5.U) { legal := true.B; take := a.asSInt >= b.asSInt }
            is(6.U) { legal := true.B; take := a < b }
            is(7.U) { legal := true.B; take := a >= b }
          }
          target := Mux(take, s.pc + immB, sequential)
        }
        is("h13".U, "h33".U) {
          val immediate = opcode === "h13".U
          val operand = Mux(immediate, immI, b)
          usesRd := true.B; usesA := true.B; usesB := !immediate; writeRd := true.B
          val base = immediate || f7 === 0.U
          switch(f3) {
            is(0.U) { legal := base || (!immediate && f7 === 32.U); result := Mux(!immediate && f7 === 32.U, a - b, a + operand) }
            is(1.U) { legal := f7 === 0.U; result := a << operand(4, 0) }
            is(2.U) { legal := base; result := (a.asSInt < operand.asSInt).asUInt }
            is(3.U) { legal := base; result := (a < operand).asUInt }
            is(4.U) { legal := base; result := a ^ operand }
            is(5.U) { legal := f7 === 0.U || f7 === 32.U; result := Mux(f7 === 32.U, (a.asSInt >> operand(4, 0)).asUInt, a >> operand(4, 0)) }
            is(6.U) { legal := base; result := a | operand }
            is(7.U) { legal := base; result := a & operand }
          }
        }
        is("h03".U, "h23".U) {
          store := opcode === "h23".U
          memory := true.B; usesA := true.B; usesB := store; usesRd := !store
          address := a + Mux(store, immS, immI)
          legal := f3 === 0.U || f3 === 1.U || f3 === 2.U || (!store && (f3 === 4.U || f3 === 5.U))
          misaligned := (f3(1, 0) === 1.U && address(0)) || (f3(1, 0) === 2.U && address(1, 0) =/= 0.U)
        }
        is("h0f".U) { legal := f3 === 0.U } // FENCE: already one ordered transaction at a time.
        is("h73".U) {
          legal := insn === "h00000073".U || insn === "h00100073".U
          systemTrap := true.B
          systemCause := Mux(insn === "h00100073".U, 3.U, 11.U)
        }
      }
      val badRegister = (usesRd && rd(4)) || (usesA && rs1(4)) || (usesB && rs2(4))
      when(response.error) { fault(1.U, 0.U) }
        .elsewhen(!legal || badRegister) { fault(2.U, insn) }
        .elsewhen(systemTrap) { fault(systemCause, insn) }
        .elsewhen(misaligned) { fault(Mux(store, 6.U, 4.U), insn) }
        .elsewhen(target(1, 0) =/= 0.U) { fault(0.U, insn) }
        .elsewhen(memory) {
          n.operation := Mux(store, Operation.Write.U, Operation.Read.U)
          n.instruction := insn
          n.address := address
          n.storeData := b << Cat(address(1, 0), 0.U(3.W))
          n.mask := Mux(f3(1, 0) === 0.U, 1.U(4.W), Mux(f3(1, 0) === 1.U, 3.U(4.W), 15.U(4.W))) << address(1, 0)
        }.otherwise {
          retire(insn)
          n.pc := target
          when(writeRd) { write(rd, result) }
        }
    }.elsewhen(s.operation === Operation.Read.U || s.operation === Operation.Write.U) {
      when(response.error) { fault(Mux(s.operation === Operation.Read.U, 5.U, 7.U), s.instruction) }
        .otherwise {
          retire(s.instruction)
          when(s.operation === Operation.Read.U) {
            val shifted = response.data >> Cat(s.address(1, 0), 0.U(3.W))
            val value = MuxLookup(s.loadKind, shifted)(Seq(
              0.U -> Cat(Fill(24, shifted(7)), shifted(7, 0)),
              1.U -> Cat(Fill(16, shifted(15)), shifted(15, 0)),
              4.U -> Cat(0.U(24.W), shifted(7, 0)),
              5.U -> Cat(0.U(16.W), shifted(15, 0))))
            write(s.destination, value)
          }
        }
    }
    val result = Wire(new ExecutionResult); result.state := n; result.trace := trace
    result
  }
}

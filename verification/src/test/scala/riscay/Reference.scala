// SPDX-License-Identifier: Apache-2.0
package riscay

/** Independent software oracle: no import of the production datapath or encoding constants. */
object Reference {
  case class Access(op: Int, address: Long, data: Long, mask: Int, response: Long, error: Boolean = false)
  case class Trace(pc: Long, instruction: Long, rd: Int = 0, data: Long = 0, trap: Boolean = false, cause: Int = 0)
  case class Result(accesses: Vector[Access], traces: Vector[Trace], registers: Vector[Long])
  private def u(x: Long): Long = x & 0xffffffffL
  private def sx(x: Long, bits: Int): Long = (x << (64 - bits)) >> (64 - bits)

  def run(program: Seq[Long], denied: Set[Long] = Set.empty, limit: Int = 1000): Result = {
    val regs = Array.fill[Long](16)(0)
    val bytes = scala.collection.mutable.Map.empty[Long, Int]
    program.zipWithIndex.foreach { case (word, index) => (0 until 4).foreach(i => bytes(index * 4L + i) = ((word >>> (i * 8)) & 255).toInt) }
    var pc = 0L
    var halted = false
    var accesses = Vector.empty[Access]
    var traces = Vector.empty[Trace]
    var steps = 0
    def word(address: Long): Long = (0 until 4).map(i => bytes.getOrElse((address & ~3L) + i, 0).toLong << (8 * i)).foldLeft(0L)(_ | _)
    while (!halted && steps < limit) {
      steps += 1
      val insn = word(pc)
      val fetchFault = denied(pc) || pc >= program.length * 4L
      accesses :+= Access(0, pc, 0, 15, if(fetchFault) 0 else insn, fetchFault)
      var next = u(pc + 4)
      var dest = 0
      var value = 0L
      var cause = -1
      def trap(n: Int): Unit = { cause = n }
      val opcode = (insn & 127).toInt
      val rd = ((insn >>> 7) & 31).toInt
      val funct = ((insn >>> 12) & 7).toInt
      val rs1 = ((insn >>> 15) & 31).toInt
      val rs2 = ((insn >>> 20) & 31).toInt
      val high = (insn >>> 25).toInt
      def read(index: Int): Long = { if(index > 15) { trap(2); 0 } else regs(index) }
      def wr(index: Int, data: Long): Unit = { if(index > 15) trap(2) else { dest = index; value = u(data) } }
      val imm = sx(insn >>> 20, 12)
      if(fetchFault) trap(1)
      else opcode match {
        case 0x37 => wr(rd, insn & 0xfffff000L)
        case 0x17 => wr(rd, pc + (insn & 0xfffff000L))
        case 0x6f =>
          val offset = sx(((insn >>> 31) << 20) | (((insn >>> 12) & 255) << 12) | (((insn >>> 20) & 1) << 11) | (((insn >>> 21) & 1023) << 1), 21)
          wr(rd, next); next = u(pc + offset)
        case 0x67 =>
          next = u(read(rs1) + imm) & ~1L
          wr(rd, pc + 4)
          if(funct != 0) trap(2)
        case 0x63 =>
          val a = read(rs1); val b = read(rs2)
          val offset = sx(((insn >>> 31) << 12) | (((insn >>> 7) & 1) << 11) | (((insn >>> 25) & 63) << 5) | (((insn >>> 8) & 15) << 1), 13)
          val taken = funct match {
            case 0 => a == b
            case 1 => a != b
            case 4 => a.toInt < b.toInt
            case 5 => a.toInt >= b.toInt
            case 6 => a < b
            case 7 => a >= b
            case _ => trap(2); false
          }
          if(taken) next = u(pc + offset)
        case 0x13 | 0x33 =>
          val a = read(rs1)
          val immediate = opcode == 0x13
          val b = if(immediate) u(imm) else read(rs2)
          val shift = (b & 31).toInt
          val answer = funct match {
            case 0 => if(!immediate && high == 32) a - b else a + b
            case 1 => a << shift
            case 2 => if(a.toInt < b.toInt) 1L else 0L
            case 3 => if(a < b) 1L else 0L
            case 4 => a ^ b
            case 5 => if(high == 32) (a.toInt >> shift).toLong else a >>> shift
            case 6 => a | b
            case 7 => a & b
          }
          wr(rd, answer)
          val allowedHigh = if(funct == 1) high == 0 else if(funct == 5) high == 0 || high == 32
            else immediate || high == 0 || (funct == 0 && high == 32)
          if(!allowedHigh) trap(2)
        case 0x03 | 0x23 =>
          val store = opcode == 0x23
          val base = read(rs1)
          val datum = if(store) read(rs2) else 0L
          if(!store && rd > 15) trap(2)
          val offset = if(store) sx(((insn >>> 25) << 5) | ((insn >>> 7) & 31), 12) else imm
          val address = u(base + offset)
          val size = funct & 3
          if(!(Set(0,1,2).contains(funct) || (!store && Set(4,5).contains(funct)))) trap(2)
          if(cause < 0 && (size == 1 && address % 2 != 0 || size == 2 && address % 4 != 0)) trap(if(store) 6 else 4)
          if(cause < 0) {
            val mask = ((1 << (1 << size)) - 1) << (address.toInt & 3)
            val error = denied(address)
            val old = word(address)
            val payload = if(store) u(datum << ((address.toInt & 3) * 8)) else 0L
            accesses :+= Access(if(store) 2 else 1, address, payload, mask, if(store || error) 0 else old, error)
            if(error) trap(if(store) 7 else 5)
            else if(store) (0 until (1 << size)).foreach(i => bytes(address + i) = ((datum >>> (8*i)) & 255).toInt)
            else {
              val raw = old >>> ((address.toInt & 3) * 8)
              val bits = 8 << size
              wr(rd, if(funct < 4) sx(raw & ((1L << bits) - 1), bits) else raw & ((1L << bits) - 1))
            }
          }
        case 0x0f => if(funct != 0) trap(2)
        case 0x73 => trap(if(insn == 0x73) 11 else if(insn == 0x100073) 3 else 2)
        case _ => trap(2)
      }
      if(cause < 0 && (next & 3) != 0) trap(0)
      if(cause >= 0) {
        traces :+= Trace(pc, if(fetchFault) 0 else insn, trap=true, cause=cause)
        accesses :+= Access(3, pc, 0, 0, 0)
        halted = true
      } else {
        if(dest != 0) regs(dest) = value
        traces :+= Trace(pc, insn, dest, if(dest == 0) 0 else value)
        pc = next
      }
    }
    require(halted, "reference workload did not terminate")
    Result(accesses, traces, regs.toVector)
  }
}

object Assembly {
  def i(op: Int, rd: Int, f: Int, a: Int, imm: Int): Long =
    ((imm.toLong & 4095) << 20) | (a.toLong << 15) | (f.toLong << 12) | (rd.toLong << 7) | op
  def r(rd: Int, f: Int, a: Int, b: Int, high: Int = 0): Long =
    (high.toLong << 25) | (b.toLong << 20) | (a.toLong << 15) | (f.toLong << 12) | (rd.toLong << 7) | 0x33
  def store(a: Int, b: Int, offset: Int, f: Int): Long =
    ((offset.toLong & 0xfe0) << 20) | (b.toLong << 20) | (a.toLong << 15) | (f.toLong << 12) | ((offset.toLong & 31) << 7) | 0x23
  def branch(a: Int, b: Int, offset: Int, f: Int): Long = {
    val x = offset.toLong & 8191
    ((x & 4096) << 19) | ((x & 2048) >>> 4) | ((x & 2016) << 20) | ((x & 30) << 7) |
      (b.toLong << 20) | (a.toLong << 15) | (f.toLong << 12) | 0x63
  }
  def jal(rd: Int, offset: Int): Long = {
    val x = offset.toLong & 0x1fffff
    ((x & 0x100000) << 11) | (x & 0xff000) | ((x & 0x800) << 9) | ((x & 0x7fe) << 20) | (rd.toLong << 7) | 0x6f
  }
  val breakpoint = 0x100073L
}

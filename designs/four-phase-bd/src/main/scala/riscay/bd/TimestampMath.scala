// SPDX-License-Identifier: Apache-2.0
package riscay.bd

import chisel3._
import chisel3.util.Cat

/** A combinational carry-select nibble. Keeping this ordinary module boundary
  * prevents area mapping from rebuilding a word-wide ripple carry. It has no
  * clock, reset, storage, delay cell or native handshake.
  */
private[riscay] class TimestampNibble extends RawModule {
  val a=IO(Input(UInt(4.W)));val b=IO(Input(UInt(4.W)))
  val sum0=IO(Output(UInt(4.W)));val sum1=IO(Output(UInt(4.W)))
  val generate=IO(Output(Bool()));val propagate=IO(Output(Bool()))
  val total=a +& b
  sum0:=total(3,0);sum1:=(total+1.U)(3,0)
  generate:=total(4);propagate:=(a|b).andR
}

/** Preserve each associative prefix-combine node. Flattened area mapping can
  * otherwise turn the logarithmic group carry back into a serial AOI chain.
  */
private[riscay] class TimestampPrefix extends RawModule {
  val highP=IO(Input(Bool()));val highG=IO(Input(Bool()))
  val lowP=IO(Input(Bool()));val lowG=IO(Input(Bool()))
  val propagate=IO(Output(Bool()));val generate=IO(Output(Bool()))
  propagate:=highP && lowP
  generate:=highG || (highP && lowG)
}

/** Bounded combinational timestamp arithmetic; no added storage or clock. */
private[riscay] object TimestampMath {
  private def arithmetic(a: UInt, b: UInt, subtract: Boolean): (UInt, Bool) = {
    val width=a.getWidth
    require(width == b.getWidth && (width == 32 || width == 64))
    val operand = if (subtract) ~b else b
    val blocks=(0 until width/4).map { i =>
      val block=Module(new TimestampNibble)
      block.a:=a(4*i+3,4*i);block.b:=operand(4*i+3,4*i)
      block
    }
    val groups=blocks.size
    var prefixes=blocks.map(b => (b.propagate,b.generate))
    for(distance <- Seq(1,2,4,8).filter(_ < groups)) {
      val previous=prefixes
      prefixes=previous.indices.map { i =>
        if(i < distance) previous(i) else {
          val node=Module(new TimestampPrefix)
          node.highP:=previous(i)._1;node.highG:=previous(i)._2
          node.lowP:=previous(i-distance)._1;node.lowG:=previous(i-distance)._2
          (node.propagate,node.generate)
        }
      }
    }
    val carries=prefixes.map { case(p,g) => if(subtract) g || p else g }
    val sums=blocks.zipWithIndex.map { case(block,i) =>
      Mux(if(i==0) subtract.B else carries(i-1),block.sum1,block.sum0)
    }
    (Cat(sums.reverse),carries(groups-1))
  }
  def apply(a: UInt, b: UInt, subtract: Boolean = false): UInt =
    arithmetic(a,b,subtract)._1

  /** The elapsed operand is 32 bits. Prepare the upper increment independently
    * of the low-word carry, then select; no carry chain crosses both words.
    */
  def advance(now: UInt, elapsed: UInt): UInt = {
    require(now.getWidth == 64 && elapsed.getWidth == 32)
    val (low,carry)=arithmetic(now(31,0),elapsed,subtract=false)
    val high=arithmetic(now(63,32),1.U(32.W),subtract=false)._1
    Cat(Mux(carry,high,now(63,32)),low)
  }

  /** Saturate the unsigned modular 64-bit difference without propagating its
    * low-word borrow through a second word and then reducing 32 high bits.
    * A difference fits iff high words match without borrow, or differ by one
    * with borrow. The timestamp-only increment must settle before a qualified read.
    */
  def saturatedAge(now: UInt, timestamp: UInt): UInt = {
    require(now.getWidth == 64 && timestamp.getWidth == 64)
    val (low,noBorrow)=arithmetic(now(31,0),timestamp(31,0),subtract=true)
    val sameHigh=now(63,32) === timestamp(63,32)
    val nextHigh=now(63,32) === arithmetic(timestamp(63,32),1.U(32.W),subtract=false)._1
    Mux(Mux(noBorrow,sameHigh,nextHigh),low,"hffffffff".U(32.W))
  }
}

// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util.Cat
import riscay.soc.SampleTime

/** A combinational carry-select nibble. Keeping this ordinary module boundary
  * prevents area mapping from rebuilding a word-wide ripple carry. It has no
  * clock, reset, storage, delay cell or native handshake.
  */
private[riscay] class TimestampNibble(width: Int) extends RawModule {
  require(width >= 1 && width <= 4)
  val a=IO(Input(UInt(width.W)));val b=IO(Input(UInt(width.W)))
  val sum0=IO(Output(UInt(width.W)));val sum1=IO(Output(UInt(width.W)))
  val generate=IO(Output(Bool()));val propagate=IO(Output(Bool()))
  val total=a +& b
  sum0:=total(width-1,0);sum1:=(total+1.U)(width-1,0)
  generate:=total(width);propagate:=(a|b).andR
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
    require(width == b.getWidth && width >= 1 && width <= 64)
    val operand = if (subtract) ~b else b
    val blocks=(0 until (width+3)/4).map { i =>
      val bits=(width-4*i).min(4)
      val block=Module(new TimestampNibble(bits))
      block.a:=a(4*i+bits-1,4*i);block.b:=operand(4*i+bits-1,4*i)
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

  /** The elapsed operand is 32 bits. Precompute the high increment so no
    * carry chain crosses both words. Saturate the POR coordinate, never wrap.
    */
  def advance(now: UInt, elapsed: UInt): UInt = {
    require(now.getWidth == SampleTime.Width && elapsed.getWidth == 32)
    val upper=now(SampleTime.Width-1,32)
    val (low,carry)=arithmetic(now(31,0),elapsed,subtract=false)
    val (high,overflow)=arithmetic(upper,1.U(upper.getWidth.W),subtract=false)
    Mux(carry && overflow,SampleTime.Maximum.U(SampleTime.Width.W),
      Cat(Mux(carry,high,upper),low))
  }

  /** A difference fits iff high words match without borrow, or differ by one
    * with borrow. Reject a future timestamp and high-word wrap. Terminal time
    * always reports stale, including samples captured at the terminal value.
    */
  def saturatedAge(now: UInt, timestamp: UInt): UInt = {
    require(now.getWidth == SampleTime.Width && timestamp.getWidth == SampleTime.Width)
    val (low,noBorrow)=arithmetic(now(31,0),timestamp(31,0),subtract=true)
    val nowHigh=now(SampleTime.Width-1,32)
    val stampHigh=timestamp(SampleTime.Width-1,32)
    val (incremented,overflow)=arithmetic(stampHigh,1.U(stampHigh.getWidth.W),subtract=false)
    val fits=Mux(noBorrow,nowHigh === stampHigh,!overflow && nowHigh === incremented)
    Mux(!now.andR && fits,low,"hffffffff".U(32.W))
  }
}

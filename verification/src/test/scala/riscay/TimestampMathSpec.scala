// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class TimestampMathFixture(click: Boolean) extends FabricFixture(SocParameters(McuConfiguration(
  8,8,0,Vector.empty,ApplicationProfile(1,1,"timestamp-math",Vector.empty,Vector.empty)))) {
  val a=IO(Input(UInt(SampleTime.Width.W))); val b=IO(Input(UInt(SampleTime.Width.W)))
  val sum=IO(Output(UInt(SampleTime.Width.W))); val difference=IO(Output(UInt(SampleTime.Width.W)))
  val age=IO(Output(UInt(32.W)));val advance=IO(Output(UInt(SampleTime.Width.W)))
  if(click) {
    sum:=riscay.click.TimestampMath(a,b);difference:=riscay.click.TimestampMath(a,b,subtract=true)
    age:=riscay.click.TimestampMath.saturatedAge(a,b)
    advance:=riscay.click.TimestampMath.advance(a,b(31,0))
  } else {
    sum:=riscay.bd.TimestampMath(a,b);difference:=riscay.bd.TimestampMath(a,b,subtract=true)
    age:=riscay.bd.TimestampMath.saturatedAge(a,b)
    advance:=riscay.bd.TimestampMath.advance(a,b(31,0))
  }
}
class TimestampMathSpec extends AnyFunSuite {
  for(click <- Seq(false,true)) test(s"${if(click) "click" else "bd"}: timestamp carry, borrow and saturation match a wide integer oracle") {
    val random=new scala.util.Random(0x54494d45L)
    val width=SampleTime.Width
    val mask=SampleTime.Maximum
    val lowMask=(BigInt(1)<<32)-1
    val vectors=(0 to width).flatMap { n =>
      val x=((BigInt(1)<<n)-1)&mask
      Seq((x,BigInt(1)),(BigInt(0),x),(x,x),(mask,x))
    } ++ Seq.fill(512)((BigInt(width,random),BigInt(width,random))) ++
      (0 until 128).flatMap { _ =>
        val high=BigInt(width-32,random);val aLow=BigInt(32,random);val bLow=BigInt(32,random)
        Seq(-1,0,1).map(d => ((((high+d)&((BigInt(1)<<(width-32))-1))<<32)|aLow,(high<<32)|bLow))
      } ++ Seq((mask,mask),(mask,mask-1),(mask-1,mask),(mask-1,BigInt(2)),
        (mask-1,BigInt(0)),(BigInt(0),mask),(lowMask,BigInt(1)))
    val body=vectors.map { case(a,b) =>
      val age=if(a==mask || a<b) lowMask else (a-b).min(lowMask)
      val advanced=(a+(b&lowMask)).min(mask)
      s"a=$width'h${a.toString(16)};b=$width'h${b.toString(16)};#1;if(sum!==$width'h${((a+b)&mask).toString(16)} || difference!==$width'h${((a-b)&mask).toString(16)} || advance!==$width'h${advanced.toString(16)} || age!==32'h${age.toString(16)}) $$fatal(1,\"TIMESTAMP_ARITHMETIC\");"
    }.mkString("\n")
    ClockedSimulation.run(new TimestampMathFixture(click),"timestamp-math",body)
  }
}

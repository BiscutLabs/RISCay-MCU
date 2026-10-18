// SPDX-License-Identifier: Apache-2.0
package riscay

import chisel3._
import org.scalatest.funsuite.AnyFunSuite
import riscay.soc._

class TimestampMathFixture(click: Boolean) extends FabricFixture(SocParameters(McuConfiguration(
  8,8,0,Vector.empty,ApplicationProfile(1,1,"timestamp-math",Vector.empty,Vector.empty)))) {
  val a=IO(Input(UInt(64.W))); val b=IO(Input(UInt(64.W)))
  val sum=IO(Output(UInt(64.W))); val difference=IO(Output(UInt(64.W)))
  val age=IO(Output(UInt(32.W)));val advance=IO(Output(UInt(64.W)))
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
  for(click <- Seq(false,true)) test(s"${if(click) "click" else "bd"}: timestamp carry, borrow and rollover match a wide integer oracle") {
    val random=new scala.util.Random(0x54494d45L)
    val mask=(BigInt(1)<<64)-1
    val vectors=(0 to 64).flatMap { n =>
      val x=((BigInt(1)<<n)-1)&mask
      Seq((x,BigInt(1)),(BigInt(0),x),(x,x),(mask,x))
    } ++ Seq.fill(512)((BigInt(64,random),BigInt(64,random))) ++
      (0 until 128).flatMap { _ =>
        val high=BigInt(32,random);val aLow=BigInt(32,random);val bLow=BigInt(32,random)
        Seq(-1,0,1).map(d => ((((high+d)&((BigInt(1)<<32)-1))<<32)|aLow,(high<<32)|bLow))
      }
    val body=vectors.map { case(a,b) =>
      s"a=64'h${a.toString(16)};b=64'h${b.toString(16)};#1;if(sum!==64'h${((a+b)&mask).toString(16)} || difference!==64'h${((a-b)&mask).toString(16)} || advance!==64'h${((a+(b&((BigInt(1)<<32)-1)))&mask).toString(16)} || age!==32'h${(((a-b)&mask).min((BigInt(1)<<32)-1)).toString(16)}) $$fatal(1,\"TIMESTAMP_ARITHMETIC\");"
    }.mkString("\n")
    ClockedSimulation.run(new TimestampMathFixture(click),"timestamp-math",body)
  }
}

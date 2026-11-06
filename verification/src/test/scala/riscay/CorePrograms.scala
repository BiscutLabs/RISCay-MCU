// SPDX-License-Identifier: Apache-2.0
package riscay

/** Identical architectural programs for all three CPU implementations. */
object CorePrograms {
  import Assembly._
  val known = Seq(
    i(0x13,1,0,0,-1), i(0x13,2,0,0,1), r(3,0,1,2), r(4,2,1,2), r(5,3,1,2),
    i(0x13,0,0,0,99), i(0x13,6,0,0,7), breakpoint)

  def arithmetic: Seq[Long] = {
    val random = new scala.util.Random(3027)
    val seeds = (1 to 15).map(r => i(0x13,r,0,0,random.nextInt(4096)-2048))
    val body = (0 until 120).map { _ =>
      val rd=random.nextInt(16); val a=random.nextInt(16); val b=random.nextInt(16); val f=random.nextInt(8)
      if(random.nextBoolean()) r(rd,f,a,b,if((f==0 || f==5) && random.nextBoolean()) 32 else 0)
      else i(0x13,rd,f,a,if(f==1) random.nextInt(32) else if(f==5) random.nextInt(32)+(if(random.nextBoolean()) 1024 else 0) else random.nextInt(4096)-2048)
    }
    known.dropRight(1) ++ seeds ++ body ++ Seq(0x800002b7L,0x297L,0x0fL,breakpoint)
  }

  val memoryAndControl = Seq(
    i(0x13,15,0,0,1024), i(0x13,1,0,0,-128), store(15,1,0,2),
    i(0x03,2,0,15,0), i(0x03,3,4,15,0), i(0x03,4,1,15,0), i(0x03,5,5,15,0), i(0x03,6,2,15,0),
    i(0x13,7,0,0,18), store(15,7,1,0), i(0x03,8,4,15,1),
    store(15,1,2,1), i(0x03,9,1,15,2), i(0x03,10,5,15,2),
    i(0x13,11,0,0,3), i(0x13,11,0,11,-1), branch(11,0,-4,1),
    branch(1,7,8,4), i(0x13,1,0,0,99), branch(7,1,8,6), i(0x13,2,0,0,99),
    jal(12,8), i(0x13,3,0,0,99),
    i(0x17,13,0,0,0), // AUIPC x13,0 (i encoder supplies the same zero upper immediate)
    i(0x67,14,0,13,12), i(0x13,4,0,0,99),
    breakpoint)

  val predicates = Seq(i(0x13,1,0,0,-1),i(0x13,2,0,0,1),i(0x13,3,0,0,0)) ++
    Seq(0,1,4,5,6,7).flatMap { f =>
      Seq(branch(1,2,8,f),i(0x13,3,0,3,1),branch(2,1,8,f),i(0x13,3,0,3,2),
        branch(1,1,8,f),i(0x13,3,0,3,4))
    } ++ Seq(jal(0,8),i(0x13,3,0,3,100),i(0x13,4,0,0,7),breakpoint)

}

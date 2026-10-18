// SPDX-License-Identifier: Apache-2.0
package riscay

import org.scalatest.funsuite.AnyFunSuite
import scala.util.Random
import riscay.soc.SocParameters

/** Semantics and counterexample tests. These are not RTL qualification. */
class EventReferenceSpec extends AnyFunSuite {
  import EventReferenceModel._

  test("all event sources coalesce and one clear consumes all observed occurrences") {
    for (bit <- 0 until Width) {
      val m = new EventReferenceModel
      for (_ <- 0 until 20) m.raise(bit)
      assert(m.pending == (1 << bit))
      m.commitClear(m.arriveClear(1 << bit))
      assert(m.pending == 0)
    }
  }

  test("clear preserves every source raised after arrival, including under backpressure") {
    for (bit <- 0 until Width) {
      val m = new EventReferenceModel
      m.raise(bit); m.raise(bit)
      val cut = m.arriveClear(All)
      for (_ <- 0 until 100) m.raise(bit)
      m.commitClear(cut)
      assert(m.pending == (1 << bit))
      m.commitClear(m.arriveClear(All)); assert(m.pending == 0)
    }
  }

  test("WAIT uses the selected mask plus unconditional lease and host wake") {
    for (bit <- 0 until Width; mask <- 0 to All) {
      val m = new EventReferenceModel
      assert(!m.waitReady(mask))
      m.raise(bit)
      assert(m.waitReady(mask) == (((mask | AlwaysWake) & (1 << bit)) != 0))
    }
  }

  test("an event on the clear-arrival edge survives, including immediate clear commit") {
    for (bit <- 0 until Width; delayedCommit <- Seq(false, true)) {
      val m = new EventReferenceModel
      m.raise(bit)
      // A logical edge samples the old watermark before applying its events.
      val cut = m.arriveClear(All)
      m.raise(bit)
      if (delayedCommit) for (_ <- 0 until 10) m.raise(bit)
      m.commitClear(cut)
      assert(m.pending == (1 << bit))
      m.commitClear(m.arriveClear(All)); assert(m.pending == 0)
    }
  }

  test("deadline replacement removes only old due and rejects delayed old publications") {
    val m = new EventReferenceModel
    val old = m.deadline
    m.due(old); m.raise(Gpio)
    val fresh = m.replaceDeadline()
    m.due(old); assert(m.pending == (1 << Gpio))
    m.due(fresh); assert(m.pending == ((1 << Gpio) | (1 << Due)))
  }

  test("reset cancels old cuts and tags without discarding events after reopening") {
    for (powerOn <- Seq(false, true)) {
      val m = new EventReferenceModel
      m.raise(Gpio); val cut = m.arriveClear(All); val old = m.deadline
      if (powerOn) m.por() else m.beginReset()
      m.raise(Host); m.commitClear(cut); assert(m.pending == 0)
      m.endReset(); m.raise(Gpio); m.due(old); m.commitClear(cut)
      assert(m.pending == (1 << Gpio))
    }
  }

  test("SPI boot pins are excluded by the production GPIO event mask") {
    val config = McuConfiguration(256,256,7,Vector.empty,
      ApplicationProfile(1,1,"events",Vector.empty,Vector.empty))
    val mask = SocParameters(config, spiBoot=true).gpioEventMask
    val m = new EventReferenceModel
    for (pin <- 3 to 6) m.gpio(0, BigInt(1) << pin, mask)
    assert(m.pending == 0)
    m.gpio(0,1,mask); assert(m.pending == (1 << Gpio))
  }

  test("independent random source histories agree with an occurrence-set oracle") {
    for (seed <- Seq(1, 7, 31, 101)) {
      val rng = new Random(seed); val m = new EventReferenceModel
      var events = Vector.empty[(Int, Int)]
      var cut = Option.empty[(Clear, Int, Int)]
      for (time <- 0 until 20000) {
        rng.nextInt(10) match {
          case 0 if cut.isEmpty =>
            val mask = rng.nextInt(All + 1)
            cut = Some((m.arriveClear(mask), time, mask))
          case 1 if cut.nonEmpty =>
            val (snapshot, arrived, mask) = cut.get
            m.commitClear(snapshot)
            events = events.filterNot { case (at, bit) => at < arrived && (mask & (1 << bit)) != 0 }
            cut = None
          case 2 =>
            m.beginReset(); m.endReset(); events = Vector.empty; cut = None
          case _ =>
            val bit = rng.nextInt(Width); m.raise(bit); events :+= ((time, bit))
        }
        assert(m.pending == events.foldLeft(0)((bits, e) => bits | (1 << e._2)), s"seed=$seed time=$time")
      }
    }
  }

  test("the proposed saturated two-credit snapshot loses a post-arrival event") {
    val m = new EventReferenceModel
    var raised = 0; var acked = 0
    def offer(): Unit = { m.raise(Gpio); if (((raised - acked) & 3) < 2) raised = (raised + 1) & 3 }
    offer(); offer()
    val cut = m.arriveClear(All); val observed = raised
    offer(); m.commitClear(cut); acked = observed
    assert(m.pending == (1 << Gpio))
    assert(raised == acked, "counterexample must empty the defective protocol")
    def gray(n: Int): Int = n ^ (n >> 1)
    assert(Integer.bitCount(gray(0) ^ gray(acked)) == 2,
      "jumping ACK to the two-credit snapshot also breaks the single-bit crossing rule")
  }

  test("ignoring the two-credit limit is detected before modular wrap hides pending") {
    var raised = 0; val acked = 0
    def step(): Unit = { raised = (raised + 1) & 3 }
    step(); step(); step()
    assert(((raised - acked) & 3) > 2, "credit monitor must reject the third unacknowledged generation")
    step(); assert(raised == acked, "fault demonstrates why equality alone is not a wrap proof")
  }
}

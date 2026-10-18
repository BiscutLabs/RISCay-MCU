// SPDX-License-Identifier: Apache-2.0
package riscay

/** Shared architectural oracle for the BD and Click event conversion.
  * Unbounded sequence numbers describe observable behavior, not an RTL design.
  * An implementation must prove its finite representation refines this model.
  */
object EventReferenceModel {
  val Tick = 0; val Due = 1; val Gpio = 2
  val Acquisition = 3; val Lease = 4; val Host = 5
  val Width = 6
  val All = (1 << Width) - 1
  val AlwaysWake = 0x30
  final case class Clear private[riscay] (lifetime: BigInt, mask: Int, observed: Vector[BigInt])
  final case class Deadline private[riscay] (lifetime: BigInt, generation: BigInt)
}

final class EventReferenceModel {
  import EventReferenceModel._
  private var lifetime = BigInt(0)
  private var generation = BigInt(0)
  private var cancelled = false
  private var raised = Vector.fill(Width)(BigInt(0))
  private var cleared = raised

  def pending: Int = raised.indices.foldLeft(0) { (bits, i) =>
    if (raised(i) != cleared(i)) bits | (1 << i) else bits
  }
  def waitReady(wakeMask: Int): Boolean = (pending & (wakeMask | AlwaysWake)) != 0

  /** Source publication at its existing ABI commit point. */
  def raise(bit: Int): Unit = {
    require(bit >= 0 && bit < Width)
    if (!cancelled) raised = raised.updated(bit, raised(bit) + 1)
  }
  def gpio(previous: BigInt, current: BigInt, eventMask: BigInt): Unit = {
    if (((previous ^ current) & eventMask) != 0) raise(Gpio)
  }

  /** Capture at request arrival, even if admission/response is backpressured.
    * For simultaneous arrival and raises, call this BEFORE raise: the current
    * set-wins ABI preserves events on the arrival edge as well as later ones.
    */
  def arriveClear(mask: Int): Clear = Clear(lifetime, mask & All, raised)
  def commitClear(cut: Clear): Unit = {
    if (!cancelled && cut.lifetime == lifetime) {
      cleared = cleared.indices.map { i =>
        if ((cut.mask & (1 << i)) != 0) cleared(i).max(cut.observed(i)) else cleared(i)
      }.toVector
    }
  }

  def deadline: Deadline = Deadline(lifetime, generation)
  /** A successful replacement retires old due; a rejected store never calls this. */
  def replaceDeadline(): Deadline = {
    generation += 1
    cleared = cleared.updated(Due, raised(Due))
    deadline
  }
  def due(tag: Deadline): Unit = if (tag == deadline) raise(Due)

  /** Synchronous application cutoff drops events; reopening admits fresh ones.
    * Old-lifetime publications and clears must not be passed as fresh raises.
    */
  def beginReset(): Unit = {
    lifetime += 1; generation = 0; cancelled = true
    raised = Vector.fill(Width)(BigInt(0)); cleared = raised
  }
  def endReset(): Unit = { cancelled = false }
  def por(): Unit = beginReset()
}

// SPDX-License-Identifier: Apache-2.0
// Shared schemas and finite digital choices for the isolated experimental owner.
package riscay.soc.experimental

import chisel3._

/** Shared schemas and finite digital model choices; no shared service logic. */
class MacroBytePins extends Bundle {
  val CLK = Output(Bool()); val CEN = Output(Bool()); val GWEN = Output(Bool())
  val WEN = Output(UInt(8.W)); val A = Output(UInt(10.W)); val D = Output(UInt(8.W))
  val Q = Input(UInt(8.W))
}

class MacroByteObservations extends Bundle {
  val armed = Bool(); val launchRequest = Bool(); val launchGrant = Bool()
  val stopPending = Bool(); val stopGrant = Bool(); val ready = Bool()
  val pinsCaptured = Bool(); val sourceRelease = Bool(); val setupReady = Bool()
  val highReady = Bool(); val accessReady = Bool(); val resultCapture = Bool()
  val captureHold = Bool(); val pulseDone = Bool(); val lowReady = Bool()
  val periodSeen = Bool(); val cycleComplete = Bool(); val publication = Bool()
  val fullyReturned = Bool(); val retired = Bool(); val guardsEmpty = Bool()
  val electricalQuiescent = Bool(); val joinedQuiescent = Bool()
}

/** These are simulation parameters, not mapped guard or MUTEX bounds.
  * Defaults exceed the declared macro constraints plus the receiver's digital
  * 1 ns setup / 2 ns hold aperture. Physical measurement remains a separate gate.
  */
case class ByteModelTiming(cellPs: Long = 1000, requestPs: Long = 10000,
    pinsPs: Long = 4000, sourcePs: Long = 10000, setupPs: Long = 12000,
    highPs: Long = 10000, accessPs: Long = 24000, captureHoldPs: Long = 8000,
    lowPs: Long = 10000, periodPs: Long = 20000, publicationPs: Long = 3000,
    mutexPs: Long = 1000, mutexJitterPs: Long = 6000, mutexPolicy: Int = 3,
    mutexSeed: Long = 1)

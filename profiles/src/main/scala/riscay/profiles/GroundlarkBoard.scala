// SPDX-License-Identifier: Apache-2.0
package riscay.profiles

import riscay.soc._

/** Build-time policy. Disabled defaults deliberately cannot energize the Pi.
  * Numeric limits follow Groundlark's power.c; selecting enabled values requires
  * board/battery qualification, not just passing these structural checks.
  */
final case class PowerPolicy(enabled: Boolean = false, shutdownMv: Int = 10000,
    restartMv: Int = 12000, lowConfirmMs: Int = 1000, restartConfirmMs: Int = 1000,
    shutdownTimeoutMs: Int = 10000, minimumOffMs: Int = 30000, ackStableMs: Int = 20) {
  require(ackStableMs >= 2)
  require(!enabled || (shutdownMv >= 8500 && shutdownMv <= 17500 &&
    restartMv >= shutdownMv + 500 && restartMv <= 18000 &&
    lowConfirmMs >= 1000 && lowConfirmMs <= 3600000 &&
    restartConfirmMs >= 1000 && restartConfirmMs <= 3600000 &&
    shutdownTimeoutMs >= 10000 && shutdownTimeoutMs <= 300000 &&
    minimumOffMs >= 30000 && minimumOffMs <= 86400000))
}

/** Immutable Groundlark binding. Each design supplies its own native supervisor. */
class GroundlarkBoard(p: SocParameters, val policy: PowerPolicy) extends BoardProfile(p) {
  require(p.config.gpioCount >= 3 && p.config.measurements.nonEmpty)
  override def ownedRegisters: Set[Int] = (0 until 6).toSet
  override def mask: BigInt = 7
  override def enables: BigInt = 3
}

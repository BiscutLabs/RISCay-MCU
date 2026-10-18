// SPDX-License-Identifier: Apache-2.0
package riscay.click

import chisel3._
import chisel3.util.Cat
import chiselasync.bundled.ClickStage
import chiselasync.core.ResetDomain
import chiselasync.metadata.ClickTiming
import riscay.soc.Crc32Command

/** One native two-phase result store, with context retained by Control.
  * The reflected CRC consumes the word least-significant byte first, without
  * final complement; only Control's Stored transition commits the candidate.
  */
object ClickCrc32 {
  // Build the fixed GF(2) transform at elaboration, not with runtime arithmetic.
  private val columns = (0 until 32).map { bit =>
    var value = BigInt(1) << bit
    for(_ <- 0 until 32) {
      value = (value >> 1) ^ (if(value.testBit(0)) BigInt("edb88320", 16) else BigInt(0))
    }
    value
  }
  private val rows = (0 until 32).map { bit =>
    (0 until 32).filter(j => columns(j).testBit(bit))
      .foldLeft(BigInt(0))((mask, j) => mask.setBit(j))
  }

  def stage(domain: ResetDomain) = new ClickStage(new Crc32Command, UInt(32.W),
    (x: Crc32Command) => {
      val folded = x.crc ^ x.word
      val computed = Cat(rows.reverse.map(mask => (folded & mask.U(32.W)).xorR))
      Mux(x.pending, computed, x.crc)
    }, OwnerTiming.base, domain)
}

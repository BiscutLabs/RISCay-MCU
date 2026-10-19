// SPDX-License-Identifier: Apache-2.0
package riscay.soc

/** Checked-in RV32E artifact, reproduced by tools/build_boot_rom.py. No profile
  * policy or compiler invocation is permitted during hardware elaboration. */
object GenericBootRom {
  private val capacitySentinel = 0xc0dec0deL
  lazy val words: Vector[Long] = {
    val stream = Option(getClass.getResourceAsStream("/riscay/boot.hex"))
      .getOrElse(sys.error("Missing generic boot ROM; run tools/build_boot_rom.py"))
    val source = scala.io.Source.fromInputStream(stream)
    try source.getLines().filter(_.nonEmpty).map(java.lang.Long.parseUnsignedLong(_,16)).toVector
    finally source.close()
  }
  def wordsFor(programBytes: Int): Vector[Long] = {
    require(words.nonEmpty && words.last == capacitySentinel, "generic boot capacity literal is missing")
    require(programBytes > 0 && programBytes % 4 == 0)
    words.updated(words.size-1,programBytes.toLong)
  }
}

// SPDX-License-Identifier: Apache-2.0
package riscay

import java.nio.file.Files
import org.scalatest.funsuite.AnyFunSuite
import scala.sys.process.{Process, ProcessLogger}

/** Isolated finite digital experiment: no production instantiation or physical qualification. */
class AsyncMacroByteOwnerSpec extends AnyFunSuite {
  test("separate native byte owners: complete actual-pin, result lifetime and exact-fault cohort") {
    val root = MacroByteCohort.repository
    val base = root.resolve("build/experimental-macro-byte-tests")
    Files.createDirectories(base)
    val cohort = Files.createTempDirectory(base, "native-byte-")
    val exports = MacroByteCohort.emit(cohort.resolve("exports"))
    val output = cohort.resolve("campaign")
    val python = sys.env.getOrElse("PYTHON", "python")
    val argv = Seq(python, root.resolve("tools/check_macro_byte_owner.py").toString, exports.toString, output.toString)
    val log = new StringBuffer
    val code = Process(argv, root.toFile).!(ProcessLogger(line => log.append(line).append('\n'), line => log.append(line).append('\n')))
    Files.writeString(cohort.resolve("campaign.log"), log.toString)
    assert(code == 0, s"Native byte campaign failed; retained evidence at $cohort\n$log")
    val receipt = ujson.read(Files.readString(output.resolve("receipt.json")))
    assert(receipt("status").str == "pass")
    val coverage = receipt("coverage")
    assert(coverage("status").str == "FINITE_DIGITAL_CANDIDATE_CAMPAIGN_PASS_PHYSICAL_UNQUALIFIED")
    val expected = coverage("required_cases").arr.map(r => (r("variant").str, r("name").str)).toSet
    val cases = coverage("cases").arr
    val actual = cases.map(r => (r("variant").str, r("case")("name").str))
    assert(expected.nonEmpty && expected.map(_._1) == Set("bd", "click"))
    assert(actual.toSet == expected && actual.distinct.size == actual.size)
    assert(cases.forall(_("status").str == "PASS"))
  }
}

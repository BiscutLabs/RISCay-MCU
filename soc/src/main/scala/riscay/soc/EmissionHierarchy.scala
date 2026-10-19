// SPDX-License-Identifier: Apache-2.0
package riscay.soc

import chisel3.experimental.{BaseModule, annotate}
import firrtl.passes.InlineAnnotation
import firrtl.transforms.NoDedupAnnotation

/** An emission choice only: physical experiments retain clocked owner boundaries. */
object EmissionHierarchy {
  def inlineUnless(module: BaseModule, preserve: Boolean): Unit = {
    if (!preserve) annotate(module)(Seq(new InlineAnnotation(module.toNamed),
      new NoDedupAnnotation(module.toTarget)))
  }
}

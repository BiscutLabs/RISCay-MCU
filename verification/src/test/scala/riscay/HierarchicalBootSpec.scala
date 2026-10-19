// SPDX-License-Identifier: Apache-2.0
package riscay

/** The identical boot/reset/sleep oracles, exercised with retained BD hierarchy. */
class HierarchicalBootSpec extends GenericBootSpec {
  override protected def preserveHierarchy: Boolean = true
}

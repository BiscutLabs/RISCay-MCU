// SPDX-License-Identifier: Apache-2.0
package riscay

// Inherit the original stimuli, deadlines and assertions without substitutions.
class DesyncSocSpec extends ClockedSocSpec {override protected def desynchronized = true}
class DesyncFabricSpec extends ClockedFabricSpec {override protected def desynchronized = true}
class DesyncSleepSpec extends ClockedSleepSpec {override protected def desynchronized = true}
class DesyncDeepSleepSpec extends ClockedDeepSleepSpec {override protected def desynchronized = true}
class DesyncGenericBootSpec extends ClockedGenericBootSpec {override protected def desynchronized = true}
class DesyncFirmwareSpec extends ClockedFirmwareSpec {override protected def desynchronized = true}
class DesyncBoundarySpec extends ClockedBoundarySpec {override protected def desynchronized = true}

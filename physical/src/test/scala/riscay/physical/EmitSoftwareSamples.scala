// SPDX-License-Identifier: Apache-2.0
package riscay.physical

import java.nio.file.Paths
import riscay.soc._
import riscay.MeasurementChannel

/** A mapped fixture for the optional CPU-written sample bank. Production has
  * only ADC channel zero; this adds one independent software channel.
  */
object EmitSoftwareSamples extends App {
  require(args.length==1,"Usage: EmitSoftwareSamples new-output-directory")
  val base=PhysicalSocExport.parameters
  val config=base.config.copy(measurements=base.config.measurements :+
    MeasurementChannel(1,"software",1,0))
  PhysicalSocExport.emit(Paths.get(args(0)).toAbsolutePath,base.copy(config=config),Seq("bd"))
}

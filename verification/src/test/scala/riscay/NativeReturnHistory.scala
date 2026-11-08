// SPDX-License-Identifier: Apache-2.0
package riscay

import java.nio.file.{Files,Path}

/** Causal cleanup oracle shared by the independent BD memory return owners. */
object NativeReturnHistory {
  def monitor(directory: Path, body: String): String = {
    val node=ujson.read(Files.readString(directory.resolve("export/contract.json")))("manifest")("design")
    def pin(id: String): String = "dut."+node("primitives").arr.find(_("id").str==id).get
      .apply("rtl_path").str.split('.').drop(1).mkString(".")+".q"
    val pending=pin("pending");val history=pin("history_common");val released=pin("released")
    s"""
      fork
        forever begin
          @(posedge $released); #1;
          if(!$pending || !$history) $$fatal(1,"RETURN_RELEASE_WITHOUT_HISTORY");
          @(negedge $pending); #1;
          if(!$released || !$history) $$fatal(1,"RETURN_CLEAR_LOST_HISTORY");
          @(negedge $history); #1;
          if(!$released) $$fatal(1,"RETURN_RELEASE_BEFORE_HISTORY");
          @(negedge $released); #1;
          if($pending || $history) $$fatal(1,"RETURN_REARM_WITH_LIVE_HISTORY");
        end
        begin $body end
      join_any
      disable fork;
    """
  }
}

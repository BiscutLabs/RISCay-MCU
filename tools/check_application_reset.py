# SPDX-License-Identifier: Apache-2.0
"""Fail-closed audit of the digital application reset hold and its actual island."""
import re


def validate_application_reset(manifest,scopes,rtl):
    top=manifest["top"]
    if top not in ("FourPhaseSoc","ClickSoc"):return
    # This pinned emitter spelling is intentionally strict. A changed emitter
    # must be inspected, not silently accepted through a loose textual match.
    clean=re.sub(r"/\*.*?\*/|//[^\n]*","",rtl,flags=re.S)
    compact=re.sub(r"\s+","",clean)
    if scopes.get(top,{}).get("registers",{}).get("release_0") != 8:
        raise ValueError("APPLICATION_RESET_HOLD_REGISTER")
    expected=("always@(posedgeserviceClockorposedgeapplicationResetRequest)begin"
              "if(applicationResetRequest)release_0<=8'hFF;"
              "elserelease_0<={release_0[6:0],1'h0};end")
    if (compact.count(expected)!=1 or compact.count("release_0<=")!=2 or
        compact.count("wireapplicationResetRequest=reset|watchdog_;")!=1 or
        compact.count("wire_systemReset_output=|{applicationResetRequest,release_0};")!=1 or
        compact.count("assignsystemReset=_systemReset_output;")!=1):
        raise ValueError("APPLICATION_RESET_HOLD_LOGIC")
    children={c["id"]:c["contract"] for c in manifest["design"]["children"]}
    application={"core","transactions","request_bridge","completion","admission","admission_grant_bridge"} | {"completion_"+n+"_bridge" for n in ("plan","memory","telemetry","housekeeping")}
    if not application<=children.keys():raise ValueError("APPLICATION_RESET_ISLAND_INVENTORY")
    def audit(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in ("DELAY_FS","max_fs") and int(item)>250000000:
                    raise ValueError("APPLICATION_RESET_SETTLEMENT_BUDGET")
                audit(item)
        elif isinstance(value,list):
            for item in value:audit(item)
    # Use exactly the same complete ownership classification as the emitted
    # reset-binding probe. Additional children default to application reset;
    # their actual pin must match that domain in the probe and their full
    # recursive timing contract must fit this hold. No child is skipped.
    persistent = persistent_reset_children(manifest)
    for name in children.keys() - persistent.keys():
        audit(children[name])


def persistent_reset_children(manifest):
    """One reset-domain policy for the binding probe and settlement audit."""
    top = manifest["top"]
    root = manifest["design"]
    persistent = {"control": "ClickControl" if top == "ClickSoc" else "FourPhaseControl",
                  "control_command_bridge": "DecoupledToClick" if top == "ClickSoc" else "DecoupledToFourPhase",
                  "control_reply_bridge": "ClickToDecoupled" if top == "ClickSoc" else "FourPhaseToDecoupled"}
    present = {c.get("id") for c in root["children"]} & persistent.keys()
    if present and present != persistent.keys():
        raise ValueError("SOC_PERSISTENT_RESET_INVENTORY")
    telemetry = {"telemetry": "ClickTelemetry" if top == "ClickSoc" else "FourPhaseTelemetry",
                 "telemetry_command_bridge": "DecoupledToClick" if top == "ClickSoc" else "DecoupledToFourPhase",
                 "telemetry_reply_bridge": "ClickToDecoupled" if top == "ClickSoc" else "FourPhaseToDecoupled"}
    present = {c.get("id") for c in root["children"]} & telemetry.keys()
    if present and present != telemetry.keys():
        raise ValueError("SOC_PERSISTENT_RESET_INVENTORY")
    persistent.update(telemetry)
    supervisor = {"supervisor": "ClickSupervisor" if top == "ClickSoc" else "FourPhaseSupervisor",
                  "supervisor_command_bridge": "DecoupledToClick" if top == "ClickSoc" else "DecoupledToFourPhase",
                  "supervisor_reply_bridge": "ClickToDecoupled" if top == "ClickSoc" else "FourPhaseToDecoupled"}
    present = {c.get("id") for c in root["children"]} & supervisor.keys()
    if present and present != supervisor.keys():
        raise ValueError("SOC_PERSISTENT_RESET_INVENTORY")
    persistent.update(supervisor)
    housekeeping = {"housekeeping": "ClickHousekeeping" if top == "ClickSoc" else "FourPhaseHousekeeping",
                    "housekeeping_command_bridge": "DecoupledToClick" if top == "ClickSoc" else "DecoupledToFourPhase",
                    "housekeeping_reply_bridge": "ClickToDecoupled" if top == "ClickSoc" else "FourPhaseToDecoupled"}
    present = {c.get("id") for c in root["children"]} & housekeeping.keys()
    if present and present != housekeeping.keys():
        raise ValueError("SOC_PERSISTENT_RESET_INVENTORY")
    persistent.update(housekeeping)
    sram = {"program_access": "SramAccess", "ram_access": "SramAccess"}
    present = {c.get("id") for c in root["children"]} & sram.keys()
    if present and present != sram.keys():
        raise ValueError("SOC_PERSISTENT_RESET_INVENTORY")
    persistent.update(sram)
    ram_source = {"ram_source": "ClickRamSource" if top == "ClickSoc" else "FourPhaseRamSource",
                  "ram_grant_bridge": "ClickToDecoupled" if top == "ClickSoc" else "FourPhaseToDecoupled"}
    ram_source.update({"ram_"+n+"_bridge": "DecoupledToClick" if top == "ClickSoc" else "DecoupledToFourPhase"
                       for n in ("reserve", "decision", "publication")})
    present = {c.get("id") for c in root["children"]} & ram_source.keys()
    if present and present != ram_source.keys():
        raise ValueError("SOC_RAM_SOURCE_RESET_INVENTORY")
    persistent.update(ram_source)
    program_source = {"program_source": "ClickProgramSource" if top == "ClickSoc" else "FourPhaseProgramSource"}
    program_source["program_grant_bridge"] = "ClickToDecoupled" if top == "ClickSoc" else "FourPhaseToDecoupled"
    program_source["program_stored_bridge"] = "ClickStoredReceipt" if top == "ClickSoc" else "FourPhaseStoredReceipt"
    program_source.update({"program_"+n+"_bridge": "DecoupledToClick" if top == "ClickSoc" else "DecoupledToFourPhase"
                           for n in ("reserve", "decision", "publication")})
    present = {c.get("id") for c in root["children"]} & program_source.keys()
    if present and present != program_source.keys():
        raise ValueError("SOC_PROGRAM_SOURCE_RESET_INVENTORY")
    persistent.update(program_source)
    persistent["i2c"] = "I2cTarget"
    persistent.update({"elapsed_scaler": "ElapsedTicks", "sample_scaler": "SampleScaler", "spi_adc": "SpiAdc"})
    for child in root["children"]:
        if child.get("id") in persistent and not re.fullmatch(
                re.escape(persistent[child["id"]]) + r"(?:_[0-9]+)?", child["contract"].get("module", "")):
            raise ValueError("SOC_PERSISTENT_RESET_OWNER")

    return persistent

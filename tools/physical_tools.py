# SPDX-License-Identifier: Apache-2.0
"""Configured native/WSL physical-tool invocation, without shell command strings."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil

ROOT=Path(__file__).resolve().parents[1]


def configuration():
    selected=os.environ.get("RISCAY_PHYSICAL_TOOLS")
    path=(Path(selected) if selected else ROOT/"physical/gf180"/("tools.windows.json" if os.name=="nt" else "tools.linux.json")).resolve()
    data=json.loads(path.read_text())
    if data.get("schema")!=1 or not isinstance(data.get("tools"),dict):raise ValueError("PHYSICAL_TOOL_CONFIG")
    return path,data


@dataclass(frozen=True)
class Tool:
    name:str
    executable:str
    distribution:str|None
    timeout_executable:str
    timeout_arguments:tuple
    config_path:Path

    def host_path(self, executable=None):
        value=executable or self.executable
        if self.distribution is not None:
            if not value.startswith("/") or ".." in value.split("/"):raise ValueError("PHYSICAL_WSL_EXECUTABLE_ABSOLUTE")
            mounted=re.fullmatch(r"/mnt/([a-z])/(.+)",value)
            if os.name=="nt" and mounted:return Path(mounted[1].upper()+":/"+mounted[2])
            return Path("//wsl.localhost/"+self.distribution+value)
        found=shutil.which(value)
        path=Path(found or value)
        if not path.is_file():raise ValueError("PHYSICAL_TOOL_UNAVAILABLE_"+self.name)
        return path.resolve()

    def path(self, value):
        path=str(Path(value).resolve()).replace("\\","/")
        if self.distribution is not None and len(path)>1 and path[1]==":":
            return "/mnt/"+path[0].lower()+path[2:]
        return path

    def command(self, args, *, timeout=None):
        command=[]
        if self.distribution is not None:
            command=["wsl","-d",self.distribution]
            command += ["-e"]
        if timeout is not None:
            if type(timeout)!=int or timeout<=0:raise ValueError("PHYSICAL_TOOL_TIMEOUT")
            command += [self.timeout_executable,*self.timeout_arguments,"--signal=TERM","--kill-after=5s",str(timeout)+"s"]
        return command+[self.executable,*map(str,args)]

    def input_files(self):
        return [self.config_path.resolve(),self.host_path(),self.host_path(self.timeout_executable),Path(__file__).resolve()]


def tool(name):
    path,data=configuration()
    entry=data["tools"].get(name)
    if not isinstance(entry,dict) or set(entry)-{"executable","distribution","timeout_executable","timeout_arguments"}:raise ValueError("PHYSICAL_TOOL_ENTRY")
    executable=entry.get("executable")
    distribution=entry.get("distribution")
    timeout=entry.get("timeout_executable","timeout")
    arguments=entry.get("timeout_arguments",[])
    if not isinstance(arguments,list):raise ValueError("PHYSICAL_TOOL_ARGUMENT")
    if not all(isinstance(x,str) and x and not any(c in x for c in "\r\n\x00") for x in [executable,timeout,*arguments]):raise ValueError("PHYSICAL_TOOL_ARGUMENT")
    if distribution is not None and (not isinstance(distribution,str) or not distribution or any(c in distribution for c in "/\\\r\n\x00")):raise ValueError("PHYSICAL_TOOL_DISTRIBUTION")
    return Tool(name,executable,distribution,timeout,tuple(arguments),path)

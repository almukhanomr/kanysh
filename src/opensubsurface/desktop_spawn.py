"""Launch a shared Windows viewer independently of an individual MCP client's job.

Only the managed local viewer uses this path. Workers keep their existing process-tree
ownership and cancellation. WMI runs as the calling user, without elevation or a task.
"""

import os
import subprocess
import sys
from pathlib import Path

from opensubsurface.desktop_lifecycle import alive, identity
from opensubsurface.errors import DomainError


class WindowsViewerProcess:
    launch_method = "windows-wmi"

    def __init__(self, pid):
        self.pid = pid
        self.record = identity(pid)
        self.returncode = None

    def poll(self):
        if not alive(self.record):
            # WMI provides a PID, not a waitable Popen handle/exit code.
            self.returncode = 1
        return self.returncode


def launch_windows_viewer(home, port, log):
    """Use local WMI's documented process creation; never change the host's job limits.

    The SDK's Windows Job Object kills its descendants when closed, including detached
    process groups. A shared viewer must have its own lifetime, supervised by leases.
    WMI is local only; a workstation policy denying it produces a visible startup error.
    Environment values travel through WMI startup information, never command arguments.
    """
    import pythoncom
    import win32com.client

    # WMI does not inherit the client's stdio handles. Establish real log handles before
    # loading the viewer, and retain the bundle's source path in a non-installed UV app.
    bootstrap = (
        "import os,runpy,sys;"
        "sys.stdin=open(os.devnull,encoding='utf-8');"
        "sys.stdout=open(sys.argv.pop(1),'a',encoding='utf-8',buffering=1);"
        "sys.stderr=sys.stdout;"
        "runpy.run_module('opensubsurface.desktop_viewer',run_name='__main__')"
    )
    command = subprocess.list2cmdline([sys.executable, "-c", bootstrap, str(log), str(home), str(port)])
    environment = dict(os.environ)
    source = str(Path(__file__).resolve().parents[1])
    environment["PYTHONPATH"] = source + (
        os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
    )
    pythoncom.CoInitialize()
    try:
        locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        services = locator.ConnectServer(".", r"root\cimv2")
        services.Security_.ImpersonationLevel = 3
        startup = services.Get("Win32_ProcessStartup").SpawnInstance_()
        startup.ShowWindow = 0
        # Break away from the WMI provider's own job, using its supported creation flag.
        # This neither edits nor relaxes the MCP host's job/security configuration.
        startup.CreateFlags = 0x01000000 | 0x00000400 | 0x00000200 | 0x08000000
        startup.EnvironmentVariables = [f"{key}={value}" for key, value in environment.items()]
        process = services.Get("Win32_Process")
        arguments = process.Methods_("Create").InParameters.SpawnInstance_()
        arguments.CommandLine = command
        arguments.CurrentDirectory = str(home)
        arguments.ProcessStartupInformation = startup
        result = process.ExecMethod_("Create", arguments)
        if int(result.ReturnValue) != 0:
            raise RuntimeError(f"Win32_Process.Create returned {result.ReturnValue}")
        return WindowsViewerProcess(int(result.ProcessId))
    except Exception as error:
        message = (
            "Cannot launch the shared Windows viewer through local WMI: "
            + str(error)
            + ". Check the Windows Management Instrumentation service and workstation policy. "
            "No elevation or scheduled task is used."
        )
        with Path(log).open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")
        raise DomainError("VIEWER_LAUNCH_UNAVAILABLE", message) from error
    finally:
        pythoncom.CoUninitialize()

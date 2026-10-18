"""WMI marshalling/error tests; native process/job behavior runs in Windows CI."""

import os
import sys
from types import SimpleNamespace

import pytest

from opensubsurface.desktop_spawn import launch_windows_viewer
from opensubsurface.errors import DomainError


def wmi(monkeypatch, result_code):
    calls = []
    startup, arguments = SimpleNamespace(), SimpleNamespace()
    process = SimpleNamespace(
        Methods_=lambda name: SimpleNamespace(InParameters=SimpleNamespace(SpawnInstance_=lambda: arguments)),
        ExecMethod_=lambda name, parameters: SimpleNamespace(ReturnValue=result_code, ProcessId=os.getpid()),
    )
    services = SimpleNamespace(
        Security_=SimpleNamespace(),
        Get=lambda name: (
            SimpleNamespace(SpawnInstance_=lambda: startup) if name == "Win32_ProcessStartup" else process
        ),
    )
    locator = SimpleNamespace(ConnectServer=lambda host, namespace: services)
    monkeypatch.setitem(
        sys.modules,
        "pythoncom",
        SimpleNamespace(
            CoInitialize=lambda: calls.append("init"), CoUninitialize=lambda: calls.append("exit")
        ),
    )
    client = SimpleNamespace(Dispatch=lambda name: locator)
    monkeypatch.setitem(sys.modules, "win32com", SimpleNamespace(client=client))
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    return calls, startup, arguments


def test_wmi_preserves_environment_without_putting_values_on_command_line(tmp_path, monkeypatch):
    calls, startup, arguments = wmi(monkeypatch, 0)
    monkeypatch.setenv("KANYSH_LAUNCH_TEST", "unicode Ж; value with spaces")
    process = launch_windows_viewer(tmp_path, 8765, tmp_path / "viewer.log")
    assert process.poll() is None and process.pid == os.getpid()
    assert calls == ["init", "exit"]
    assert "KANYSH_LAUNCH_TEST=unicode Ж; value with spaces" in startup.EnvironmentVariables
    assert "unicode Ж" not in arguments.CommandLine
    assert arguments.CurrentDirectory == str(tmp_path)
    assert arguments.ProcessStartupInformation is startup
    assert any(item.startswith("PYTHONPATH=") for item in startup.EnvironmentVariables)


def test_wmi_policy_denial_is_visible_and_does_not_fall_back_to_client_job(tmp_path, monkeypatch):
    calls, _, _ = wmi(monkeypatch, 2)
    log = tmp_path / "viewer.log"
    with pytest.raises(DomainError) as error:
        launch_windows_viewer(tmp_path, 8765, log)
    assert error.value.code == "VIEWER_LAUNCH_UNAVAILABLE"
    assert "returned 2" in log.read_text(encoding="utf-8")
    assert calls == ["init", "exit"]

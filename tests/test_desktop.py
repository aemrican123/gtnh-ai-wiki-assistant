import os
import time
from pathlib import Path

from fastapi.testclient import TestClient
from test_answer import StubIndex

from gtnh_assistant.api import create_app
from gtnh_assistant.config import Settings
from gtnh_assistant.launcher import browser_command, interface_needs_build
from gtnh_assistant.lifecycle import Lifecycle
from gtnh_assistant.shortcuts import script


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def lifecycle(clock, **kwargs):
    calls = []
    return Lifecycle(
        on_idle=lambda: calls.append(1), clock=clock, close_grace=15, idle_timeout=300, **kwargs
    ), calls


def test_window_close_shuts_down_after_grace_period():
    clock = Clock()
    life, calls = lifecycle(clock)
    life.seen()
    life.closing()
    clock.now += 10
    assert not life.check()
    clock.now += 6
    assert life.check() and calls == [1]
    assert not life.check() and calls == [1]  # only once


def test_reload_or_second_window_cancels_shutdown():
    clock = Clock()
    life, calls = lifecycle(clock)
    life.closing()
    clock.now += 3
    life.seen()  # the reloaded page (or another window) polls again
    clock.now += 60
    assert not life.check() and calls == []


def test_silence_fallback_and_busy_guards():
    clock = Clock()
    busy = {"job": True}
    life, calls = lifecycle(clock, busy=lambda: busy["job"])
    clock.now += 301
    assert not life.check()  # a collection job is running
    busy["job"] = False
    life.stream_started()
    assert not life.check()  # an answer is streaming
    life.stream_finished()
    assert life.check() and calls == [1]


def test_api_closing_beacon_reaches_lifecycle(tmp_path):
    clock = Clock()
    life, calls = lifecycle(clock)
    index = StubIndex()
    app = create_app(
        Settings(data_dir=tmp_path),
        index_factory=lambda: index,
        gpu=lambda: None,
        lifecycle=life,
        client_factory=lambda: type("Down", (), {"version": lambda self: (_ for _ in ()).throw(OSError())})(),
    )
    client = TestClient(app)
    assert client.post("/api/closing").status_code == 204
    assert life.closing_at is not None and life.last_seen <= life.closing_at
    clock.now += 20
    assert life.check() and calls == [1]


def test_interface_needs_build(tmp_path):
    frontend = tmp_path
    (frontend / "src").mkdir()
    (frontend / "src" / "App.tsx").write_text("x")
    (frontend / "package-lock.json").write_text("{}")
    assert interface_needs_build(frontend)  # never built
    (frontend / "dist").mkdir()
    (frontend / "node_modules").mkdir()
    (frontend / "node_modules" / ".package-lock.json").write_text("{}")
    (frontend / "dist" / "index.html").write_text("<html>")
    old = time.time() - 100
    for path in [frontend / "src" / "App.tsx", frontend / "package-lock.json"]:
        os.utime(path, (old, old))
    assert not interface_needs_build(frontend)
    os.utime(frontend / "package-lock.json", None)  # git pull changed dependencies
    assert interface_needs_build(frontend)


def test_browser_command_prefers_edge_app_window(tmp_path):
    edge = tmp_path / "Microsoft" / "Edge" / "Application" / "msedge.exe"
    edge.parent.mkdir(parents=True)
    edge.write_text("")
    command = browser_command("http://127.0.0.1:8501", env={"ProgramFiles(x86)": str(tmp_path)})
    assert command[0] == str(edge) and "--app=http://127.0.0.1:8501" in command


def test_shortcut_script_targets_windowless_launcher():
    code = script(root=Path("C:/coding/wiki'scraper"))
    assert "pythonw.exe" in code and "-m gtnh_assistant.launcher" in code
    assert "wiki''scraper" in code  # quotes in paths are escaped for PowerShell
    assert "GetFolderPath('Desktop')" in code and "GetFolderPath('Programs')" in code
    assert "Remove-Item" in script(remove=True)

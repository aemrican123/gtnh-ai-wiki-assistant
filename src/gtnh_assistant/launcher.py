"""Desktop launcher: what the "GTNH Field Guide" shortcut runs (with ``pythonw``, so no console window).

1. If the app is already running, it only opens another app window.
2. Starts Ollama in the background if it is installed but not running.
3. When something needs the user (Ollama missing, model not downloaded, interface not built or out of date),
   it runs ``start_gtnh.bat --prepare`` in a visible console, which explains, downloads and builds.
4. Starts the local server, opens the interface in its own Edge app window, and exits (unloading the model)
   once that window has been closed. Output goes to ``data/launcher.log``.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORT = 8501
URL = f"http://127.0.0.1:{PORT}"
TITLE = "GTNH Field Guide"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0)


def message(text, error=False):
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, TITLE, 0x10 if error else 0x40)
    else:
        print(text, file=sys.stderr)


def app_running(timeout=1.5):
    try:
        with urllib.request.urlopen(URL + "/api/status", timeout=timeout) as response:
            return "knowledge_base" in json.loads(response.read())
    except Exception:
        return False


def port_free(port=PORT):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def newest_mtime(paths):
    newest = 0.0
    for path in paths:
        if path.is_dir():
            newest = max([newest, *(p.stat().st_mtime for p in path.rglob("*") if p.is_file())])
        elif path.exists():
            newest = max(newest, path.stat().st_mtime)
    return newest


def interface_needs_build(frontend):
    """Mirror of the check in start_gtnh.bat: missing build, newer sources, or newer package lock."""
    built = frontend / "dist" / "index.html"
    if not built.exists():
        return True
    sources = [
        frontend / "src",
        frontend / "index.html",
        frontend / "package.json",
        frontend / "package-lock.json",
    ]
    if newest_mtime(sources) > built.stat().st_mtime:
        return True
    marker = frontend / "node_modules" / ".package-lock.json"
    lock = frontend / "package-lock.json"
    return lock.exists() and (not marker.exists() or lock.stat().st_mtime > marker.stat().st_mtime)


def browser_command(url, env=os.environ):
    """Edge (installed with Windows) or Chrome in app mode: its own window, no tabs or address bar."""
    candidates = []
    for base in (env.get("ProgramFiles(x86)"), env.get("ProgramFiles"), env.get("LOCALAPPDATA")):
        if base:
            candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
            candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for found in (shutil.which("msedge"), shutil.which("chrome")):
        if found:
            candidates.append(Path(found))
    for path in candidates:
        if path.exists():
            return [str(path), f"--app={url}", "--window-size=1280,860", "--no-first-run"]
    return None


def open_window():
    command = browser_command(URL)
    if command:
        subprocess.Popen(command, creationflags=DETACHED)
    else:
        webbrowser.open(URL)


def wait_for(check, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.5)
    return False


def ensure_ollama(settings):
    """Return (ready, reason). Starts ``ollama serve`` hidden when Ollama is installed but not running."""
    from .llm import LLMError, OllamaClient

    client = OllamaClient(settings.ollama_host, timeout=3)

    def up():
        try:
            client.version()
            return True
        except LLMError:
            return False

    if not up():
        if not shutil.which("ollama"):
            return False, "ollama-missing"
        subprocess.Popen(["ollama", "serve"], creationflags=NO_WINDOW | DETACHED, cwd=ROOT)
        if not wait_for(up, 30):
            return False, "ollama-not-starting"
    try:
        if not client.has_model(settings.llm_model):
            return False, "model-missing"
    except LLMError:
        return False, "ollama-not-starting"
    return True, ""


def prepare_in_console():
    """Let start_gtnh.bat explain and fix what is missing, in a window the user can read."""
    process = subprocess.Popen(
        ["cmd.exe", "/c", str(ROOT / "start_gtnh.bat"), "--prepare"], cwd=ROOT, creationflags=NEW_CONSOLE
    )
    return process.wait() == 0


def run():
    os.chdir(ROOT)  # .env and data/ are relative to the project folder
    if app_running():
        open_window()
        return 0
    from .config import Settings

    settings = Settings()
    ready, _ = ensure_ollama(settings)
    if not ready or interface_needs_build(ROOT / "frontend"):
        if not prepare_in_console():
            return 1
        settings = Settings()
        ready, reason = ensure_ollama(settings)
        if not ready:
            message(f"The app cannot start yet ({reason}). Run start_gtnh.bat to see what is missing.", True)
            return 1
    if not port_free():
        message(
            f"Port {PORT} is used by another program, so the app cannot start. Close it and try again.", True
        )
        return 1
    from .api import serve

    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} starting on {URL}", flush=True)
    if not serve(PORT, exit_when_closed=True, on_ready=open_window):
        message("The app could not start. Details are in data\\launcher.log.", True)
        return 1
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} window closed; stopped", flush=True)
    return 0


def main():
    log_dir = ROOT / "data"
    log_dir.mkdir(exist_ok=True)
    # pythonw has no console: keep output (and any crash) in a log file instead of losing it.
    log = open(log_dir / "launcher.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    try:
        code = run()
    except Exception:
        traceback.print_exc()
        message("The GTNH Field Guide stopped with an error. Details are in data\\launcher.log.", True)
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()

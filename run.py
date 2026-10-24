"""One-step launcher: sets up everything the first time, then starts the app and opens the browser.

    python3 run.py            live Hyperliquid data
    python3 run.py --demo     offline demo data

Optional keys (Finnhub for earnings, Anthropic for Deep research) go in a .env file next to this one;
see .env.example.

Uses only the standard library, so it works before anything is installed.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
VENV = ROOT / ".venv"
REQUIREMENTS = BACKEND / "requirements.txt"
STAMP = VENV / ".requirements-installed"
PORT = int(os.environ.get("MA_PORT", "8000"))
URL = f"http://localhost:{PORT}"


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def python_version(exe: str) -> tuple[int, int] | None:
    try:
        out = subprocess.run([exe, "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                             capture_output=True, text=True, timeout=10)
        major, minor = out.stdout.split()
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def newest_python() -> str | None:
    """The newest Python 3.10+ on this machine, which may not be the one that started this script."""
    names = [f"python3.{m}" for m in range(14, 9, -1)] + ["python3", "python"]
    extra_dirs = [Path.home() / ".local/bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    found: dict[str, tuple[int, int]] = {}
    for name in names:
        candidates = [shutil.which(name)] + [str(d / name) for d in extra_dirs if (d / name).exists()]
        for exe in filter(None, candidates):
            v = python_version(exe)
            if v and v >= (3, 10):
                found[exe] = v
    return max(found, key=found.get) if found else None


def fail(message: str) -> None:
    print("\n" + message)
    sys.exit(1)


def ensure_environment() -> None:
    if not venv_python().exists() or not STAMP.exists():
        # first run, or an earlier setup that never finished: start clean with the newest Python available
        python = newest_python() or sys.executable
        version = python_version(python)
        if version is None or version < (3, 10):
            fail("Python 3.10 or newer is needed. Get it from https://www.python.org/downloads/ and run this again.")
        if VENV.exists():
            shutil.rmtree(VENV)
        print(f"First run: creating a private Python environment in .venv with Python {version[0]}.{version[1]} ...")
        result = subprocess.run([python, "-m", "venv", str(VENV)])
        if result.returncode != 0 or not venv_python().exists():
            fail("Could not create the .venv folder. Check the message above, or send a screenshot of it.")
        subprocess.run([str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-q", "--upgrade", "pip"])

    # reinstall only when requirements.txt changes
    wanted = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    if not STAMP.exists() or STAMP.read_text().strip() != wanted:
        print("Installing the app's packages (about a minute, first run only) ...")
        result = subprocess.run([str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)])
        if result.returncode != 0:
            hint = (
                "Installing the packages failed (the reason is in the lines above).\n"
                "Common fixes:\n"
                "  - Check you are online, then run this again.\n"
                "  - If you see 'SSL' or 'CERTIFICATE_VERIFY_FAILED' on a Mac: open Applications > Python 3.x and\n"
                "    double-click 'Install Certificates.command', then run this again.\n"
                "If it still fails, send a screenshot of this window."
            )
            fail(hint)
        STAMP.write_text(wanted)


def read_env_file() -> dict[str, str]:
    """KEY=value lines from .env, ignoring blanks, comments and empty values."""
    path = ROOT / ".env"
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value:
                out[key.strip()] = value
    return out


def open_browser_when_ready() -> None:
    for _ in range(60):
        try:
            urllib.request.urlopen(URL + "/api/config", timeout=1)
            webbrowser.open(URL)
            return
        except OSError:
            time.sleep(0.5)


def main() -> None:
    ensure_environment()
    env = {**read_env_file(), **os.environ}
    for key, what in (("FINNHUB_API_KEY", "earnings dates and EPS"), ("ANTHROPIC_API_KEY", "Deep research")):
        print(f"  {what}: {'on' if env.get(key) else f'off (add {key} to .env to turn on)'}")
    if "--demo" in sys.argv:
        env["MA_DEMO"] = "1"
    print(f"Starting Market Analyser at {URL}  (press Ctrl+C here to stop)")
    threading.Thread(target=open_browser_when_ready, daemon=True).start()
    try:
        subprocess.call(
            [str(venv_python()), "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
            cwd=BACKEND,
            env=env,
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

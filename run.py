"""One-step launcher: sets up everything the first time, then starts the app and opens the browser.

    python3 run.py            live Hyperliquid data
    python3 run.py --demo     offline demo data

Uses only the standard library, so it works before anything is installed.
"""

import hashlib
import os
import subprocess
import sys
import threading
import time
import urllib.request
import venv
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


def ensure_environment() -> None:
    if sys.version_info < (3, 10):
        sys.exit(f"Python 3.10 or newer is needed (this is {sys.version.split()[0]}). Get it from https://www.python.org/downloads/")

    if not venv_python().exists():
        print("First run: creating a private Python environment in .venv ...")
        venv.EnvBuilder(with_pip=True).create(VENV)

    # reinstall only when requirements.txt changes
    wanted = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    if not STAMP.exists() or STAMP.read_text().strip() != wanted:
        print("Installing the app's packages (one minute, first run only) ...")
        subprocess.check_call([str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(REQUIREMENTS)])
        STAMP.write_text(wanted)


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
    env = dict(os.environ)
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

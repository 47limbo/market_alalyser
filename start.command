#!/bin/bash
# Double-click this file on a Mac to start Market Analyser.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 run.py "$@"
else
  echo "Python 3 is not installed. Get it from https://www.python.org/downloads/ and double-click this file again."
fi
read -r -p "Press Enter to close this window."

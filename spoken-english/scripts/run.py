#!/usr/bin/env python3
"""Launch practice.py with the configured isolated Python runtime."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main() -> None:
    config_path = Path.home() / ".config/spoken-english/config.json"
    configured = os.environ.get("SPOKEN_ENGLISH_PYTHON")
    if not configured and config_path.exists():
        configured = json.loads(config_path.read_text(encoding="utf-8")).get("python_path")
    if not configured:
        raise SystemExit("Configure SPOKEN_ENGLISH_PYTHON or config.json python_path to the venv Python containing fsrs==6.3.2")
    python = Path(configured).expanduser()
    if not python.is_absolute() or not python.is_file():
        raise SystemExit("Configured python_path must be an existing absolute file")
    practice = Path(__file__).with_name("practice.py")
    os.execv(str(python), [str(python), str(practice), *sys.argv[1:]])


if __name__ == "__main__":
    main()

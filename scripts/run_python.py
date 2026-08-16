"""Run a command with the repository-local Python virtual environment."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = (
    ROOT / ".venv" / "Scripts" / "python.exe"
    if os.name == "nt"
    else ROOT / ".venv" / "bin" / "python"
)


def main() -> int:
    if not VENV_PYTHON.exists():
        print("AgentDesk environment is missing. Run `npm run setup` first.", file=sys.stderr)
        return 2

    completed = subprocess.run([str(VENV_PYTHON), *sys.argv[1:]], cwd=ROOT, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())


"""Create the isolated ADK scoper environment needed by the Story 7 browser stack."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / ".venv-scoper"
PYTHON = ENVIRONMENT / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main() -> int:
    if not PYTHON.is_file():
        result = subprocess.run(
            [sys.executable, "-m", "venv", str(ENVIRONMENT)],
            cwd=ROOT,
            check=False,
        )
        if result.returncode:
            return result.returncode
    return subprocess.run(
        [
            str(PYTHON),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(ROOT / "services" / "scoper" / "requirements.lock"),
        ],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())

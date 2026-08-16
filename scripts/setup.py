"""Create the local Python environment and install the AgentDesk workspace."""

from __future__ import annotations

import subprocess
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"


def venv_python() -> Path:
    if VENV.joinpath("Scripts", "python.exe").exists():
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def main() -> None:
    if not VENV.exists():
        venv.EnvBuilder(with_pip=True).create(VENV)

    subprocess.run(
        [str(venv_python()), "-m", "pip", "install", "--editable", ".[dev]"],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()


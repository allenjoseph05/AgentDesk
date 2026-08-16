"""Run the API and web development servers as one interruptible process group."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = (
    ROOT / ".venv" / "Scripts" / "python.exe"
    if os.name == "nt"
    else ROOT / ".venv" / "bin" / "python"
)


def npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        process.terminate()


def main() -> int:
    if not VENV_PYTHON.exists():
        print("AgentDesk environment is missing. Run `npm run setup` first.", file=sys.stderr)
        return 2

    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    commands = [
        [
            str(VENV_PYTHON),
            "-m",
            "uvicorn",
            "agents.coordinator.main:app",
            "--reload",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        [npm_command(), "run", "dev", "--workspace", "@agentdesk/web"],
    ]
    processes = [
        subprocess.Popen(command, cwd=ROOT, creationflags=creation_flags) for command in commands
    ]

    try:
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    return return_code
            signal.pause() if os.name != "nt" else processes[0].wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        return main_loop(processes)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes:
            terminate(process)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def main_loop(processes: list[subprocess.Popen[bytes]]) -> int:
    try:
        while True:
            for process in processes:
                return_code = process.poll()
                if return_code is not None:
                    return return_code
            try:
                processes[0].wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                continue
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

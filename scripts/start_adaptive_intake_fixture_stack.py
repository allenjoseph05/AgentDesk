"""Start the key-free adaptive-intake stack used by Playwright Story 7 checks."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from packages.persistence import Database, metadata

ROOT = Path(__file__).resolve().parents[1]
ROOT_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
SCOPER_PYTHON = ROOT / ".venv-scoper" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
NPM = "npm.cmd" if os.name == "nt" else "npm"

COORDINATOR_URL = "http://127.0.0.1:8180"
RESEARCHER_URL = "http://127.0.0.1:8185"
ANALYST_URL = "http://127.0.0.1:8186"
VERIFIER_URL = "http://127.0.0.1:8187"
SCOPER_URL = "http://127.0.0.1:8191"
WEB_URL = "http://127.0.0.1:5183"


def main() -> int:
    """Run all fixture services until Playwright terminates the launcher."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-only", action="store_true")
    arguments = parser.parse_args()
    missing = [path for path in (ROOT_PYTHON, SCOPER_PYTHON) if not path.is_file()]
    if missing:
        rendered = ", ".join(str(path.relative_to(ROOT)) for path in missing)
        print(f"Adaptive fixture environments are missing: {rendered}", file=sys.stderr)
        print("Run `python scripts/setup_adaptive_intake_e2e.py` first.", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="agentdesk-intake-e2e-") as temporary:
        database_path = Path(temporary) / "agentdesk.sqlite3"
        database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
        database = Database.connect(database_url)
        metadata.create_all(database.engine)
        database.dispose()

        common = os.environ.copy()
        common.update(
            {
                "AGENTDESK_AUTH_MODE": "local",
                "AGENTDESK_ADAPTIVE_SCOPING_ENABLED": "true",
                "AGENTDESK_COORDINATOR_MODEL": "",
                "AGENTDESK_REGISTRY_MAX_ATTEMPTS": "1",
                "ANALYST_AGENT_URL": ANALYST_URL,
                "DATABASE_URL": database_url,
                "OPENAI_API_KEY": "",
                "RESEARCH_AGENT_URL": RESEARCHER_URL,
                "SCOPER_AGENT_URL": SCOPER_URL,
                "VERIFIER_AGENT_URL": VERIFIER_URL,
            }
        )
        processes = [
            _start_python("agents.researcher.fixture_app:app", 8185, common),
            _start_python("agents.analyst.fixture_app:app", 8186, common),
            _start_python("agents.verifier.fixture_app:app", 8187, common),
            _start_scoper(common),
        ]
        try:
            _wait_for(
                [
                    f"{RESEARCHER_URL}/ready",
                    f"{ANALYST_URL}/ready",
                    f"{VERIFIER_URL}/ready",
                    f"{SCOPER_URL}/ready",
                ],
                processes,
            )
            processes.append(_start_python("agents.coordinator.fixture_app:app", 8180, common))
            _wait_for([f"{COORDINATOR_URL}/ready"], processes)
            if arguments.backend_only:
                return _wait_until_stopped(processes)
            web_environment = common | {
                "AGENTDESK_COORDINATOR_URL": COORDINATOR_URL,
                "VITE_AGENTDESK_RUNTIME_MODE": "adaptive-demo",
            }
            processes.append(
                subprocess.Popen(
                    [
                        NPM,
                        "run",
                        "dev",
                        "--workspace",
                        "@agentdesk/web",
                        "--",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "5183",
                        "--strictPort",
                    ],
                    cwd=ROOT,
                    env=web_environment,
                )
            )
            _wait_for([WEB_URL], processes)
            return _wait_until_stopped(processes)
        finally:
            _terminate(processes)


def _start_python(module: str, port: int, environment: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            str(ROOT_PYTHON),
            "-m",
            "uvicorn",
            module,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=environment,
    )


def _start_scoper(environment: dict[str, str]) -> subprocess.Popen[bytes]:
    scoper_environment = environment | {
        "PYTHONPATH": os.pathsep.join([str(ROOT / "services" / "scoper" / "src"), str(ROOT)]),
        "SCOPER_BASE_URL": SCOPER_URL,
        "SCOPER_FIXTURE_ID": "technology-database",
        "SCOPER_FIXTURE_DELAY_SECONDS": os.getenv(
            "AGENTDESK_INTAKE_E2E_SCOPER_DELAY_SECONDS", "0.5"
        ),
        "SCOPER_MODE": "fixture",
    }
    return subprocess.Popen(
        [
            str(SCOPER_PYTHON),
            "-m",
            "uvicorn",
            "agentdesk_scoper.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8191",
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=scoper_environment,
    )


def _wait_for(
    urls: list[str],
    processes: list[subprocess.Popen[bytes]],
    *,
    timeout_seconds: float = 30,
) -> None:
    pending = set(urls)
    deadline = time.monotonic() + timeout_seconds
    while pending and time.monotonic() < deadline:
        _raise_for_early_exit(processes)
        for url in tuple(pending):
            try:
                with urllib.request.urlopen(url, timeout=0.5) as response:
                    if response.status == 200:
                        pending.remove(url)
            except OSError, urllib.error.URLError:
                pass
        if pending:
            time.sleep(0.1)
    if pending:
        raise TimeoutError(f"Fixture services did not become ready: {sorted(pending)}")


def _raise_for_early_exit(processes: list[subprocess.Popen[bytes]]) -> None:
    stopped = [process for process in processes if process.poll() is not None]
    if stopped:
        raise RuntimeError(f"Fixture service stopped with exit code {stopped[0].returncode}.")


def _wait_until_stopped(processes: list[subprocess.Popen[bytes]]) -> int:
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    while not stopping:
        _raise_for_early_exit(processes)
        time.sleep(0.25)
    return 0


def _terminate(processes: list[subprocess.Popen[bytes]]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()
    for process in reversed(processes):
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())

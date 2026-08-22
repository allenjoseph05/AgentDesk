"""Contract tests for the required Python validation pipeline."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_SCRIPTS = {
    "lint:python": (
        "python scripts/run_python.py -m ruff check . && "
        "python scripts/run_python.py -m ruff format --check agents packages scripts tests"
    ),
    "typecheck:python": "python scripts/run_python.py -m mypy",
    "test:python": "python scripts/run_python.py -m pytest",
}


def test_root_scripts_expose_reproducible_python_validation_gates() -> None:
    package = json.loads(ROOT.joinpath("package.json").read_text(encoding="utf-8"))

    assert {name: package["scripts"].get(name) for name in EXPECTED_SCRIPTS} == (EXPECTED_SCRIPTS)


def test_ci_requires_each_python_gate_as_an_explicit_step() -> None:
    workflow = ROOT.joinpath(".github", "workflows", "ci.yml").read_text(encoding="utf-8")
    commands = [
        "run: npm run lint:python",
        "run: npm run typecheck:python",
        "run: npm run test:python",
    ]

    assert all(workflow.count(command) == 1 for command in commands)
    assert [workflow.index(command) for command in commands] == sorted(
        workflow.index(command) for command in commands
    )

"""Reviewer-documentation contract checks for current architecture decisions."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "demo.md",
    ROOT / "docs" / "deployment.md",
    ROOT / "docs" / "adr" / "README.md",
    ROOT / "docs" / "adr" / "0002-ag-ui-frontend-protocol.md",
    ROOT / "docs" / "adr" / "0003-bounded-a2ui-adk-intake.md",
    ROOT / "docs" / "adaptive-intake-plan.md",
    ROOT / "docs" / "adaptive-intake-benchmark.md",
)
MARKDOWN_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: path.name)
def test_reviewer_documentation_has_no_broken_relative_links(document: Path) -> None:
    content = document.read_text(encoding="utf-8")
    for target in MARKDOWN_LINK.findall(content):
        path_text = target.strip().strip("<>").split("#", maxsplit=1)[0]
        if not path_text or "://" in path_text or path_text.startswith("mailto:"):
            continue
        resolved = (document.parent / path_text).resolve()
        assert resolved.is_relative_to(ROOT)
        assert resolved.exists(), f"Broken link in {document.relative_to(ROOT)}: {target}"


def test_readme_explains_current_and_superseded_protocol_boundaries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "**AG-UI** is the browser-to-Coordinator boundary" in readme
    assert "**A2A** is the Coordinator-to-specialist boundary" in readme
    assert "**A2UI is not part of the running system.**" in readme
    assert "./docs/architecture.md" in readme
    assert "./docs/demo.md" in readme
    assert "./docs/deployment.md" in readme
    assert "./docs/adr/0002-ag-ui-frontend-protocol.md" in readme


def test_architecture_has_system_and_complete_request_diagrams() -> None:
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    assert "```mermaid\nflowchart" in architecture
    assert "```mermaid\nsequenceDiagram" in architecture
    for participant in ("React", "Coordinator", "PostgreSQL", "Researcher", "Analyst", "Verifier"):
        assert participant in architecture
    for identifier in ("threadId", "runId", "actionId", "sessionId", "A2A task ID"):
        assert identifier in architecture


def test_demo_walkthrough_and_root_command_are_kept_in_sync() -> None:
    demo = (ROOT / "docs" / "demo.md").read_text(encoding="utf-8")
    root_package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert "docker compose -f compose.yaml -f compose.demo.yaml up --build --wait" in demo
    assert "docker compose -f compose.yaml -f compose.demo.yaml down" in demo
    assert "npm run test:e2e:demo" in demo
    assert "Strongest alternative: MongoDB" in demo
    assert (
        root_package["scripts"]["test:e2e:demo"]
        == "npm run test:e2e:demo --workspace @agentdesk/web"
    )


def test_current_adr_supersedes_only_the_frontend_protocol_decision() -> None:
    adr = (ROOT / "docs" / "adr" / "0002-ag-ui-frontend-protocol.md").read_text(encoding="utf-8")

    assert "Status: Accepted" in adr
    assert "Supersedes: the A2UI frontend protocol" in adr
    assert "A2A" in adr and "Retained from ADR 0001" in adr
    assert "@ag-ui/client` 0.0.58" in adr
    assert "ag-ui-protocol` 0.1.20" in adr


def test_adaptive_intake_plan_preserves_protocol_and_dependency_boundaries() -> None:
    adr = (ROOT / "docs" / "adr" / "0003-bounded-a2ui-adk-intake.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "adaptive-intake-plan.md").read_text(encoding="utf-8")

    assert "Keep the existing Coordinator as the deterministic control plane" in adr
    assert "Do not install `google-adk` or `a2ui-agent-sdk` in the root" in adr
    assert "AG-UI remains the sole browser" in adr
    assert "Stories 1 through 3 complete; Story 4 is next" in plan
    assert "compatibility decision and evidence" in plan
    assert "benchmark, rubric, baseline, and go/no-go evidence" in plan
    assert "isolated service implementation and evidence" in plan
    assert "A2UI protocol 0.9.1" in plan
    assert "improves the predefined ambiguous-prompt quality score" in plan


def test_adaptive_intake_baseline_is_explicitly_not_a_rollout_claim() -> None:
    benchmark = (ROOT / "docs" / "adaptive-intake-benchmark.md").read_text(encoding="utf-8")

    assert "30 ambiguous comparison prompts and 10 already-complete controls" in benchmark
    assert "0.2000 direct ambiguous quality * 1.15 = 0.2300" in benchmark
    assert "decision remains `not_eligible`" in benchmark
    assert "zero model calls" in benchmark
    assert "not evidence that adaptive intake" in benchmark
    assert "improves final recommendations" in benchmark

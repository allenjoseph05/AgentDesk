"""Regenerate adaptive-intake JSON Schema and the contract-only baseline."""

from __future__ import annotations

import json
from pathlib import Path

from packages.contracts import IntakeResponse, ScopeProposalArtifact
from packages.contracts.base import ContractModel
from packages.evaluation import (
    BenchmarkCapture,
    generate_fixture_evaluation,
    generate_intake_baseline,
    load_intake_benchmark,
)
from packages.testing import load_intake_fixture

ROOT = Path(__file__).resolve().parents[1]
INTAKE_ROOT = ROOT / "fixtures" / "intake"


class IntakeContractDocument(ContractModel):
    artifact: ScopeProposalArtifact
    response: IntakeResponse


def main() -> None:
    schema = IntakeContractDocument.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://agentdesk.dev/schemas/intake-contracts-1.0.json"
    schema["title"] = "AgentDesk adaptive-intake artifact and response"
    _write_json(INTAKE_ROOT / "intake-contracts.schema.json", schema)
    suite = load_intake_benchmark()
    _write_json(INTAKE_ROOT / "baseline.json", generate_intake_baseline(suite))
    scoped_captures = {
        case_id: BenchmarkCapture.model_validate(
            load_intake_fixture(fixture_id).expected_request.model_dump(
                mode="python", exclude={"question"}
            )
        )
        for case_id, fixture_id in {
            "amb-tech-01": "technology-database",
            "amb-proc-01": "procurement-design-laptop",
            "amb-travel-01": "travel-team-offsite",
        }.items()
    }
    _write_json(
        INTAKE_ROOT / "fixture-evaluation.json",
        generate_fixture_evaluation(suite, scoped_captures),
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

"""Reproducible scoring for the adaptive-intake benchmark."""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from packages.contracts.base import ContractModel, NonEmptyText
from packages.contracts.domain import Depth

BENCHMARK_VERSION: Literal["1.0"] = "1.0"
RUBRIC_VERSION: Literal["1.0"] = "1.0"
INTAKE_BENCHMARK_PATH = (
    Path(__file__).resolve().parents[2] / "fixtures" / "intake" / "benchmark.json"
)
BenchmarkCohort = Literal["ambiguous", "complete_control"]
BenchmarkDomain = Literal["technology", "procurement", "travel"]
Score = FiniteFloat


class BenchmarkCapture(ContractModel):
    options: list[NonEmptyText] = Field(default_factory=list, max_length=4)
    constraints: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    criteria: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    desired_depth: Depth = "normal"


class IntakeBenchmarkCase(ContractModel):
    case_id: NonEmptyText
    cohort: BenchmarkCohort
    domain: BenchmarkDomain
    prompt: NonEmptyText
    expected: BenchmarkCapture
    direct_capture: BenchmarkCapture
    direct_final_usefulness: Score = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_targets(self) -> IntakeBenchmarkCase:
        if len(self.expected.options) < 2:
            raise ValueError("Benchmark targets require at least two expected options.")
        if not self.expected.criteria:
            raise ValueError("Benchmark targets require at least one expected criterion.")
        for capture in (self.expected, self.direct_capture):
            for values in (capture.options, capture.constraints, capture.criteria):
                normalized = [_normalized(value) for value in values]
                if len(normalized) != len(set(normalized)):
                    raise ValueError("Benchmark values must be unique after normalization.")
        if self.cohort == "complete_control" and self.direct_capture != self.expected:
            raise ValueError("Complete controls must preserve the full expected request.")
        return self


class IntakeBenchmarkSuite(ContractModel):
    benchmark_version: Literal["1.0"] = BENCHMARK_VERSION
    rubric_version: Literal["1.0"] = RUBRIC_VERSION
    cases: list[IntakeBenchmarkCase] = Field(min_length=40)

    @model_validator(mode="after")
    def validate_coverage(self) -> IntakeBenchmarkSuite:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Benchmark case IDs must be unique.")
        ambiguous = [case for case in self.cases if case.cohort == "ambiguous"]
        controls = [case for case in self.cases if case.cohort == "complete_control"]
        if len(ambiguous) < 30 or len(controls) < 10:
            raise ValueError("Benchmark requires 30 ambiguous prompts and 10 complete controls.")
        if {case.domain for case in ambiguous} != {"technology", "procurement", "travel"}:
            raise ValueError("Ambiguous prompts must cover all three intake domains.")
        return self


def load_intake_benchmark() -> IntakeBenchmarkSuite:
    return IntakeBenchmarkSuite.model_validate_json(
        INTAKE_BENCHMARK_PATH.read_text(encoding="utf-8")
    )


def score_intake_case(case: IntakeBenchmarkCase) -> dict[str, float]:
    """Score one preserved direct capture without invoking a model or workflow."""

    dimensions = {
        "option_completeness": _recall(case.direct_capture.options, case.expected.options),
        "constraint_capture": _recall(
            case.direct_capture.constraints,
            case.expected.constraints,
        ),
        "criterion_relevance": _recall(case.direct_capture.criteria, case.expected.criteria),
        "downstream_request_validity": float(_is_valid_request(case.direct_capture)),
        "final_recommendation_usefulness": float(case.direct_final_usefulness),
    }
    dimensions["quality_score"] = fmean(dimensions.values())
    return {name: round(value, 4) for name, value in dimensions.items()}


def generate_intake_baseline(suite: IntakeBenchmarkSuite) -> dict[str, object]:
    """Generate the checked-in contract-only baseline and conservative go/no-go result."""

    case_results: list[dict[str, object]] = []
    grouped: dict[str, list[dict[str, float]]] = defaultdict(list)
    for case in suite.cases:
        case_scores = score_intake_case(case)
        case_results.append(
            {
                "case_id": case.case_id,
                "cohort": case.cohort,
                "domain": case.domain,
                "scores": case_scores,
            }
        )
        grouped[case.cohort].append(case_scores)

    aggregates: dict[str, dict[str, float | int]] = {}
    for cohort, cohort_scores in grouped.items():
        dimensions = cohort_scores[0]
        aggregates[cohort] = {
            "case_count": len(cohort_scores),
            **{
                dimension: round(fmean(score[dimension] for score in cohort_scores), 4)
                for dimension in dimensions
            },
        }

    ambiguous_baseline = float(aggregates["ambiguous"]["quality_score"])
    target = round(ambiguous_baseline * 1.15, 4)
    return {
        "benchmark_version": suite.benchmark_version,
        "rubric_version": suite.rubric_version,
        "profile": "contract-only-direct-baseline",
        "model_calls": 0,
        "case_results": case_results,
        "cohort_results": aggregates,
        "go_no_go": {
            "decision": "not_eligible",
            "ambiguous_direct_quality": ambiguous_baseline,
            "required_scoped_quality": target,
            "relative_improvement_required": 0.15,
            "calculation": f"{ambiguous_baseline:.4f} * 1.15 = {target:.4f}",
            "reasons": [
                "No scoped candidate exists before the scoping-agent stories.",
                "Final recommendation usefulness has not been executed and remains scored as zero.",
                "Story 7 must execute and preserve direct and scoped outputs before rollout.",
            ],
        },
    }


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", " ".join(value.split())).lower()


def _recall(captured: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    captured_values = {_normalized(value) for value in captured}
    expected_values = {_normalized(value) for value in expected}
    return len(captured_values & expected_values) / len(expected_values)


def _is_valid_request(capture: BenchmarkCapture) -> bool:
    return (
        2 <= len(capture.options) <= 4
        and 1 <= len(capture.criteria) <= 20
        and len(capture.constraints) <= 20
    )

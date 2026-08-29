"""Reproducible scoring for the adaptive-intake benchmark."""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Mapping
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

    return score_intake_capture(
        case.direct_capture,
        case.expected,
        final_usefulness=case.direct_final_usefulness,
    )


def score_intake_capture(
    capture: BenchmarkCapture,
    expected: BenchmarkCapture,
    *,
    final_usefulness: float = 0,
) -> dict[str, float]:
    """Score one explicit capture against the predeclared target values."""

    dimensions = {
        "option_completeness": _recall(capture.options, expected.options),
        "constraint_capture": _recall(capture.constraints, expected.constraints),
        "criterion_relevance": _recall(capture.criteria, expected.criteria),
        "downstream_request_validity": float(_is_valid_request(capture)),
        "final_recommendation_usefulness": float(final_usefulness),
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


def generate_fixture_evaluation(
    suite: IntakeBenchmarkSuite,
    scoped_captures: Mapping[str, BenchmarkCapture],
) -> dict[str, object]:
    """Evaluate the full suite without inventing outputs for unsupported fixture cases."""

    direct = generate_intake_baseline(suite)
    case_results: list[dict[str, object]] = []
    grouped: dict[str, list[dict[str, float]]] = defaultdict(list)
    supported_ambiguous = 0
    for case in suite.cases:
        if case.cohort == "complete_control":
            capture = case.direct_capture
            status = "deterministic_bypass"
        elif case.case_id in scoped_captures:
            capture = scoped_captures[case.case_id]
            status = "fixture_scoped"
            supported_ambiguous += 1
        else:
            capture = BenchmarkCapture()
            status = "fixture_unavailable"
        scores = score_intake_capture(capture, case.expected)
        grouped[case.cohort].append(scores)
        case_results.append(
            {
                "case_id": case.case_id,
                "cohort": case.cohort,
                "domain": case.domain,
                "status": status,
                "capture": capture.model_dump(mode="json"),
                "scores": scores,
            }
        )

    cohort_results = _aggregate_scores(grouped)
    direct_cohorts = direct["cohort_results"]
    if not isinstance(direct_cohorts, dict):
        raise TypeError("Generated direct baseline has invalid cohort results.")
    direct_ambiguous = direct_cohorts["ambiguous"]
    if not isinstance(direct_ambiguous, dict):
        raise TypeError("Generated direct baseline has invalid ambiguous results.")
    direct_quality = float(direct_ambiguous["quality_score"])
    scoped_quality = float(cohort_results["ambiguous"]["quality_score"])
    required_quality = round(direct_quality * 1.15, 4)
    return {
        "benchmark_version": suite.benchmark_version,
        "rubric_version": suite.rubric_version,
        "profile": "deterministic-fixture-candidate",
        "model_calls": 0,
        "live_provider_credentials_required": False,
        "coverage": {
            "ambiguous_fixture_scoped": supported_ambiguous,
            "ambiguous_total": sum(case.cohort == "ambiguous" for case in suite.cases),
            "complete_control_bypassed": sum(
                case.cohort == "complete_control" for case in suite.cases
            ),
        },
        "case_results": case_results,
        "cohort_results": cohort_results,
        "go_no_go": {
            "decision": "not_eligible",
            "ambiguous_direct_quality": direct_quality,
            "ambiguous_fixture_quality": scoped_quality,
            "required_scoped_quality": required_quality,
            "relative_improvement": round(
                (scoped_quality - direct_quality) / direct_quality,
                4,
            ),
            "reasons": [
                "The deterministic scoper covers only three of thirty ambiguous benchmark cases.",
                "Unsupported fixture cases are scored as unavailable rather than inferred from "
                "targets.",
                "Final recommendation usefulness has not been independently scored across the "
                "suite.",
                "The predefined fifteen-percent scoped quality gate did not pass.",
            ],
        },
    }


def _aggregate_scores(
    grouped: Mapping[str, list[dict[str, float]]],
) -> dict[str, dict[str, float | int]]:
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
    return aggregates


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

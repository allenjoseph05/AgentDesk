"""Adaptive-intake benchmark definition, baseline, and go/no-go tests."""

import json
from collections import Counter
from pathlib import Path

from packages.evaluation import (
    BenchmarkCapture,
    generate_fixture_evaluation,
    generate_intake_baseline,
    load_intake_benchmark,
)
from packages.testing import load_intake_fixture


def test_benchmark_has_predeclared_three_domain_and_control_coverage() -> None:
    suite = load_intake_benchmark()
    coverage = Counter((case.cohort, case.domain) for case in suite.cases)

    assert len(suite.cases) == 40
    assert coverage == {
        ("ambiguous", "technology"): 10,
        ("ambiguous", "procurement"): 10,
        ("ambiguous", "travel"): 10,
        ("complete_control", "technology"): 4,
        ("complete_control", "procurement"): 3,
        ("complete_control", "travel"): 3,
    }


def test_checked_in_baseline_is_reproducible_and_not_a_rollout_claim() -> None:
    suite = load_intake_benchmark()
    generated = generate_intake_baseline(suite)
    committed = json.loads(Path("fixtures/intake/baseline.json").read_text(encoding="utf-8"))

    assert committed == generated
    assert committed["model_calls"] == 0
    assert committed["cohort_results"]["ambiguous"] == {
        "case_count": 30,
        "option_completeness": 0.7833,
        "constraint_capture": 0.0,
        "criterion_relevance": 0.2167,
        "downstream_request_validity": 0.0,
        "final_recommendation_usefulness": 0.0,
        "quality_score": 0.2,
    }
    assert committed["cohort_results"]["complete_control"]["quality_score"] == 0.8
    assert committed["go_no_go"] == {
        "decision": "not_eligible",
        "ambiguous_direct_quality": 0.2,
        "required_scoped_quality": 0.23,
        "relative_improvement_required": 0.15,
        "calculation": "0.2000 * 1.15 = 0.2300",
        "reasons": [
            "No scoped candidate exists before the scoping-agent stories.",
            "Final recommendation usefulness has not been executed and remains scored as zero.",
            "Story 7 must execute and preserve direct and scoped outputs before rollout.",
        ],
    }


def test_baseline_keeps_prompts_and_scores_without_reasoning_traces() -> None:
    benchmark_text = Path("fixtures/intake/benchmark.json").read_text(encoding="utf-8")
    baseline_text = Path("fixtures/intake/baseline.json").read_text(encoding="utf-8")

    assert "chain_of_thought" not in benchmark_text
    assert "reasoning_trace" not in benchmark_text
    assert "prompt" not in baseline_text
    assert "answer" not in baseline_text


def test_fixture_candidate_executes_full_suite_and_remains_no_go() -> None:
    captures = {
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
    generated = generate_fixture_evaluation(load_intake_benchmark(), captures)
    committed = json.loads(
        Path("fixtures/intake/fixture-evaluation.json").read_text(encoding="utf-8")
    )

    assert committed == generated
    assert committed["model_calls"] == 0
    assert committed["coverage"] == {
        "ambiguous_fixture_scoped": 3,
        "ambiguous_total": 30,
        "complete_control_bypassed": 10,
    }
    assert committed["cohort_results"]["complete_control"]["quality_score"] == 0.8
    assert committed["go_no_go"]["decision"] == "not_eligible"
    assert committed["go_no_go"]["ambiguous_fixture_quality"] < 0.23


def test_fixture_evaluation_does_not_store_reasoning_traces() -> None:
    evaluation_text = Path("fixtures/intake/fixture-evaluation.json").read_text(encoding="utf-8")

    assert "chain_of_thought" not in evaluation_text
    assert "reasoning_trace" not in evaluation_text
    assert '"prompt"' not in evaluation_text

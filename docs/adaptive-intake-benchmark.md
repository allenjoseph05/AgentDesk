# Adaptive intake benchmark and contract baseline

- Story: Adaptive intake Story 2
- Benchmark version: 1.0
- Rubric version: 1.0
- Baseline profile: contract-only direct baseline
- Verified: 2026-08-27
- Rollout decision: not eligible

Story 7 has now executed the complete suite against the zero-cost deterministic fixture profile.
See the [published candidate result and gate matrix](./adaptive-intake-evaluation.md). The fixture
candidate remains `not_eligible`; this baseline is intentionally unchanged.

## What is fixed before agent tuning

The committed benchmark contains 30 ambiguous comparison prompts and 10 already-complete controls.
The ambiguous cohort has ten prompts in each of technology, procurement, and travel. The controls
preserve a complete set of options, constraints, criteria, and depth so later scoper changes cannot
claim improvement by degrading requests that were already usable.

Each case commits the target decision context and the values captured by the current direct path.
Prompts and target values are evaluation inputs, not model prompts or expected chain-of-thought. The
baseline stores only case identifiers and numeric scores; it does not duplicate questions, answers,
reasoning, or generated output.

## Scoring rubric

Each dimension is bounded from zero to one and has equal weight. The case quality score is their
arithmetic mean.

| Dimension | Deterministic scoring rule |
|---|---|
| Option completeness | Recall of normalized target options in the captured request |
| Constraint capture | Recall of normalized target constraints in the captured request |
| Criterion relevance | Recall of normalized target criteria in the captured request |
| Downstream request validity | One only for two to four options, at least one criterion, and bounded collections |
| Final recommendation usefulness | Preserved human score from zero to one; zero when no final output was executed |

Normalization trims outer whitespace, collapses internal whitespace, applies Unicode NFKC, and
compares case-insensitively.
It does not use semantic similarity, a model judge, or hidden reasoning. Story 7 may add a separately
versioned human or model-assisted usefulness rubric, but it must preserve both direct and scoped
outputs and cannot rewrite this baseline after seeing candidate results.

## Baseline result

This story deliberately performs zero model calls and does not execute 40 full research workflows.
The checked-in result is therefore an input-contract baseline, not evidence that adaptive intake
improves final recommendations.

| Cohort | Cases | Options | Constraints | Criteria | Valid request | Final usefulness | Quality |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ambiguous direct | 30 | 0.7833 | 0.0000 | 0.2167 | 0.0000 | 0.0000 | 0.2000 |
| Complete controls | 10 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.8000 |

The predefined 15 percent relative gate yields a provisional scoped threshold of:

```text
0.2000 direct ambiguous quality * 1.15 = 0.2300 required scoped quality
```

The current decision remains `not_eligible`: there is no scoped candidate, final-output usefulness
has not been executed, and the integration/product gates belong to Story 7. A future score above
0.2300 alone is insufficient; every accessibility, conformance, safety, control-regression, call
budget, and dependency gate in the implementation plan must also pass.

## Reproduction and evidence

The authoritative inputs and generated evidence are:

- `fixtures/intake/benchmark.json`: human-reviewed prompts, targets, and direct captures;
- `fixtures/intake/baseline.json`: generated per-case scores, cohort means, and go/no-go calculation;
- `fixtures/intake/fixture-evaluation.json`: generated Story 7 deterministic candidate and no-go;
- `fixtures/intake/intake-contracts.schema.json`: generated schema for the artifact and response;
- `scripts/export_intake_evidence.py`: deterministic generator for both generated files.

Regenerate from the repository root, then review the diff:

```powershell
python scripts/run_python.py scripts/export_intake_evidence.py
python scripts/run_python.py -m pytest tests/unit/test_intake_benchmark.py
```

The Python and TypeScript fixture suites independently validate the three golden domains and the same
20-case malformed corpus. Executable validators remain authoritative for normalized uniqueness,
proposal feasibility, and response-to-proposal checks that JSON Schema cannot fully express.

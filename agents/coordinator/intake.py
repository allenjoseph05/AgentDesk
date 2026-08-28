"""Deterministic adaptive-intake completeness and compilation rules."""

from __future__ import annotations

import unicodedata

from packages.contracts import IntakeResponse, ResearchRequest, ScopeProposal, ScopingRequest
from packages.contracts.intake import validate_intake_response


class IntakeCompilationError(ValueError):
    """Accepted intake data cannot form a valid research request."""


def request_is_complete(request: ScopingRequest) -> bool:
    """Return whether scoping can be bypassed without another model call."""
    return 2 <= len(request.options) <= 4 and bool(request.criteria)


def compile_research_request(
    request: ScopingRequest,
    proposal: ScopeProposal,
    response: IntakeResponse | None,
) -> ResearchRequest:
    """Combine immutable request, proposal defaults, and validated answers."""
    if proposal.question != request.question:
        raise IntakeCompilationError("Scope proposal question does not match the request.")
    if response is not None:
        validate_intake_response(proposal, response)

    destinations: dict[str, list[str]] = {
        "option": [*request.options, *proposal.suggested_options],
        "criterion": [*request.criteria, *proposal.suggested_criteria],
        "constraint": [*request.constraints, *proposal.suggested_constraints],
    }
    if response is not None:
        fields = {field.field_id: field for field in proposal.fields}
        for field_id, answer in response.answers.items():
            field = fields[field_id]
            if isinstance(answer, bool):
                values = [field.label] if answer else []
            elif isinstance(answer, str):
                values = [answer]
            else:
                values = list(answer)
            destinations[field.destination].extend(values)

    options = _unique(destinations["option"])
    criteria = _unique(destinations["criterion"])
    constraints = _unique(destinations["constraint"])
    if not 2 <= len(options) <= 4:
        raise IntakeCompilationError("Intake must produce two to four unique options.")
    if not criteria:
        raise IntakeCompilationError("Intake must produce at least one criterion.")
    if len(criteria) > 20 or len(constraints) > 20:
        raise IntakeCompilationError("Intake produced too many research values.")
    return ResearchRequest(
        question=request.question,
        options=options,
        constraints=constraints,
        criteria=criteria,
        desired_depth=proposal.default_depth,
    )


def direct_research_request(request: ScopingRequest) -> ResearchRequest:
    """Convert only a deterministically complete scoping request."""
    if not request_is_complete(request):
        raise IntakeCompilationError("An incomplete request cannot bypass intake.")
    return ResearchRequest.model_validate(request.model_dump(exclude={"schema_version"}))


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    observed: set[str] = set()
    for value in values:
        normalized = unicodedata.normalize("NFKC", " ".join(value.split())).casefold()
        if normalized not in observed:
            observed.add(normalized)
            result.append(value)
    return result

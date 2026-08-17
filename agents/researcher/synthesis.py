"""Provider-neutral evidence extraction and synthesis for the Research Agent."""

from __future__ import annotations

import json

from agents.researcher.tools import (
    ResearchToolFailure,
    SearchProvider,
    SearchQuery,
    SourceDocument,
    SourceProvider,
    SourceProviderError,
)
from packages.contracts import Evidence, EvidenceBundle, ResearchRequest
from packages.llm import LLMProvider, Message

RESEARCH_SYNTHESIS_PROMPT = """You are the evidence-synthesis stage of a research agent.
Return only the requested EvidenceBundle structure. Use only the supplied source IDs and source
material. Every claim must cite at least one supplied evidence ID. Preserve important unknowns,
caveats, source conflicts, and missing information. Do not choose a winner, rank the options, make
a final recommendation, or produce decision analysis; a separate Analyst Agent owns that work.
"""

_SEARCH_LIMIT_BY_DEPTH = {"fast": 3, "normal": 5, "deep": 10}


class ResearchSynthesisError(RuntimeError):
    """Raised when provider output cannot form a trustworthy evidence bundle."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ResearchSynthesizer:
    """Search, fetch, and synthesize evidence without making a recommendation."""

    def __init__(
        self,
        *,
        search_provider: SearchProvider,
        source_provider: SourceProvider,
        llm_provider: LLMProvider,
    ) -> None:
        self._search_provider = search_provider
        self._source_provider = source_provider
        self._llm_provider = llm_provider

    async def synthesize(self, request: ResearchRequest) -> EvidenceBundle:
        """Produce a validated bundle grounded exclusively in fetched sources."""
        validated_request = ResearchRequest.model_validate(request.model_dump(mode="python"))
        results = await self._search_provider.search(
            SearchQuery(
                text=_search_text(validated_request),
                limit=_SEARCH_LIMIT_BY_DEPTH[validated_request.desired_depth],
            )
        )
        if not results:
            raise ResearchSynthesisError(
                "no_search_results",
                "Research did not return any sources to synthesize.",
            )

        result_ids = [result.source_id for result in results]
        if len(result_ids) != len(set(result_ids)):
            raise ResearchSynthesisError(
                "duplicate_search_results",
                "Research returned duplicate source identifiers.",
            )

        documents: list[SourceDocument] = []
        failures: list[ResearchToolFailure] = []
        for result in results:
            try:
                document = await self._source_provider.fetch(result)
            except SourceProviderError as error:
                failures.append(error.failure)
                continue
            if document.source_id != result.source_id:
                raise ResearchSynthesisError(
                    "source_identity_mismatch",
                    f"Fetched source ID {document.source_id} did not match {result.source_id}.",
                )
            documents.append(document)

        if not documents:
            if failures:
                raise SourceProviderError(failures[0])
            raise ResearchSynthesisError(
                "no_source_documents",
                "Research could not fetch any source documents to synthesize.",
            )

        candidate = await self._llm_provider.generate_structured(
            system_prompt=RESEARCH_SYNTHESIS_PROMPT,
            messages=[
                Message(role="user", content=_synthesis_context(validated_request, documents))
            ],
            response_model=EvidenceBundle,
        )
        return _ground_bundle(validated_request, documents, failures, candidate)


def _search_text(request: ResearchRequest) -> str:
    parts = [request.question]
    if request.options:
        parts.append(f"Options: {', '.join(request.options)}")
    if request.criteria:
        parts.append(f"Criteria: {', '.join(request.criteria)}")
    if request.constraints:
        parts.append(f"Constraints: {', '.join(request.constraints)}")
    return " | ".join(parts)


def _synthesis_context(request: ResearchRequest, documents: list[SourceDocument]) -> str:
    return json.dumps(
        {
            "request": request.model_dump(mode="json"),
            "sources": [document.model_dump(mode="json") for document in documents],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _ground_bundle(
    request: ResearchRequest,
    documents: list[SourceDocument],
    failures: list[ResearchToolFailure],
    candidate: EvidenceBundle,
) -> EvidenceBundle:
    if candidate.question != request.question:
        raise ResearchSynthesisError(
            "question_mismatch",
            "Synthesized evidence did not preserve the research question.",
        )
    if not candidate.claims or not candidate.evidence:
        raise ResearchSynthesisError(
            "empty_synthesis",
            "Synthesis must contain at least one evidence-backed claim.",
        )

    documents_by_id = {document.source_id: document for document in documents}
    unknown_ids = [item.id for item in candidate.evidence if item.id not in documents_by_id]
    if unknown_ids:
        raise ResearchSynthesisError(
            "ungrounded_evidence",
            f"Synthesized evidence referenced unavailable sources: {sorted(unknown_ids)}",
        )

    grounded_evidence = []
    for item in candidate.evidence:
        document = documents_by_id[item.id]
        grounded_evidence.append(
            Evidence(
                id=document.source_id,
                title=document.title,
                source_url=document.source_url,
                source_type=document.source_type,
                summary=item.summary,
                relevance=item.relevance,
                retrieved_at=document.retrieved_at,
            )
        )

    unknowns = list(candidate.unknowns)
    research_notes = list(candidate.research_notes)
    for failure in failures:
        source = failure.source_id or "unknown source"
        unknown = f"Source {source} could not be retrieved: {failure.message}"
        note = f"Source {source} fetch failed ({failure.code}); synthesis used remaining sources."
        if unknown not in unknowns:
            unknowns.append(unknown)
        if note not in research_notes:
            research_notes.append(note)

    return EvidenceBundle(
        question=request.question,
        claims=candidate.claims,
        evidence=grounded_evidence,
        unknowns=unknowns,
        research_notes=research_notes,
    )

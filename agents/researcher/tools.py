"""Typed tool boundaries used by Research Agent orchestration."""

from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import AnyHttpUrl, AwareDatetime, Field

from packages.contracts.base import ContractModel, NonEmptyText
from packages.contracts.domain import SourceType

SearchLimit = Annotated[int, Field(ge=1, le=20)]
ToolOperation = Literal["search", "fetch"]


class SearchQuery(ContractModel):
    """One validated query submitted to a search provider."""

    text: NonEmptyText
    limit: SearchLimit = 5


class SearchResult(ContractModel):
    """Provider-neutral search result that can be fetched independently."""

    source_id: NonEmptyText
    title: NonEmptyText
    snippet: NonEmptyText
    source_url: AnyHttpUrl | None = None
    source_type: SourceType


class SourceDocument(ContractModel):
    """Normalized source content returned by a source provider."""

    source_id: NonEmptyText
    title: NonEmptyText
    content: NonEmptyText
    source_url: AnyHttpUrl | None = None
    source_type: SourceType
    retrieved_at: AwareDatetime


class ResearchToolFailure(ContractModel):
    """Serializable failure information safe for workflow decisions."""

    code: NonEmptyText
    message: NonEmptyText
    provider: NonEmptyText
    operation: ToolOperation
    retryable: bool
    source_id: NonEmptyText | None = None


class ResearchToolError(RuntimeError):
    """Base exception carrying a typed research-tool failure."""

    def __init__(self, failure: ResearchToolFailure) -> None:
        self.failure = failure
        super().__init__(failure.message)


class SearchProviderError(ResearchToolError):
    """Raised when a search provider cannot return normalized results."""

    def __init__(self, failure: ResearchToolFailure) -> None:
        if failure.operation != "search":
            raise ValueError("Search provider errors require a search failure.")
        super().__init__(failure)


class SourceProviderError(ResearchToolError):
    """Raised when a source provider cannot retrieve normalized content."""

    def __init__(self, failure: ResearchToolFailure) -> None:
        if failure.operation != "fetch":
            raise ValueError("Source provider errors require a fetch failure.")
        super().__init__(failure)


@runtime_checkable
class SearchProvider(Protocol):
    """Search interface consumed by Research Agent logic."""

    async def search(self, query: SearchQuery) -> list[SearchResult]: ...


@runtime_checkable
class SourceProvider(Protocol):
    """Source retrieval interface consumed by Research Agent logic."""

    async def fetch(self, result: SearchResult) -> SourceDocument: ...

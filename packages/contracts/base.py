"""Shared strictness rules for cross-agent domain contracts."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

MAX_BOUNDED_TEXT_LENGTH = 16 * 1024
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ContractModel(BaseModel):
    """Reject unrecognized fields and validate defaults at every boundary."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_default=True)

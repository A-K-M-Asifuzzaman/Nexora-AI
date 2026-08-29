from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Bounded because an unbounded prompt is both a cost and an injection
    # surface; API.md §7 requires explicit max_length on free text.
    question: str = Field(min_length=1, max_length=2000)


class ToolInvocation(BaseModel):
    tool: str
    arguments: dict[str, Any]
    error: bool
    rows: int


class AskResponse(BaseModel):
    answer: str | None
    grounded: bool
    regenerated: bool
    note: str | None = None
    tool_calls: list[ToolInvocation]
    data: list[Any]


class ToolDescription(BaseModel):
    name: str
    description: str
    permissions: list[str]

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import Strict
from app.services.ai.parser import Entities, Intent


class InterpretIn(Strict):
    text: str = Field(min_length=1, max_length=500)
    use_llm: bool = Field(True, description="Use the LLM parser when configured; falls back to rules")


class Candidate(BaseModel):
    id: int
    label: str
    detail: str | None = None


class ProposedAction(BaseModel):
    """A normal REST call the client performs *after* the user confirms, with a fresh Idempotency-Key."""

    method: Literal["POST", "PUT", "PATCH"]
    path: str
    body: dict[str, Any]
    label: str


class Proposal(BaseModel):
    title: str
    summary: list[str]
    actions: list[ProposedAction]
    warnings: list[str] = []
    permitted: bool = True
    ready: bool = Field(True, description="False when something must be resolved before confirming")
    preview: dict[str, Any] | None = None


class InterpretOut(BaseModel):
    text: str
    intent: Intent
    kind: Literal["read", "write"]
    source: Literal["rules", "llm"]
    confidence: float
    entities: Entities
    message: str
    result: Any | None = None
    proposal: Proposal | None = None
    candidates: dict[str, list[Candidate]] = {}

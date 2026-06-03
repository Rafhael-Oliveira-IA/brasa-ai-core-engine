from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ModelTier(str, Enum):
    LOCAL = "local"
    FLASH = "flash"
    PLUS = "plus"
    MAX = "max"


class MemoryScope(str, Enum):
    USER = "user"
    PROJECT = "project"
    EPISODIC = "episodic"


class RequestEnvelope(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    user_id: str
    prompt: str = Field(min_length=1)
    tier_hint: ModelTier | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextSnippet(BaseModel):
    source: str
    content: str
    score: float = Field(default=0.5, ge=0.0, le=1.0)
    scores: dict[str, float] = Field(default_factory=dict)


class ContextPacket(BaseModel):
    snippets: list[ContextSnippet] = Field(default_factory=list)
    token_budget: int = 3000
    provenance: list[str] = Field(default_factory=list)


class MemoryEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    user_id: str
    scope: MemoryScope = MemoryScope.EPISODIC
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MemoryCreateRequest(BaseModel):
    project_id: str
    user_id: str
    scope: MemoryScope = MemoryScope.EPISODIC
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    provenance: dict[str, Any] = Field(default_factory=dict)


class MemorySearchResponse(BaseModel):
    items: list[MemoryEntry]


class RetrievalResult(BaseModel):
    query: str
    entries: list[MemoryEntry] = Field(default_factory=list)
    took_ms: int = 0
    assembled: dict[str, Any] = Field(default_factory=dict)


class ContextAssembleResponse(BaseModel):
    packet: ContextPacket
    retrieval: RetrievalResult


class WatcherCheckRequest(BaseModel):
    project_path: str
    auto_rebuild: bool = True


class WatcherFileEvent(BaseModel):
    event_type: str
    path: str
    previous_path: str | None = None
    previous_hash: str | None = None
    current_hash: str | None = None


class WatcherCheckReport(BaseModel):
    project_name: str
    project_path: str
    scanned_files: int
    changes_detected: int
    created: int
    modified: int
    deleted: int
    renamed: int
    rebuilt: bool = False
    events: list[WatcherFileEvent] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class RouteDecision(BaseModel):
    selected_tier: ModelTier
    provider: str
    model_name: str
    reason: str
    escalation_depth: int = 0
    estimated_cost_usd: float = 0.0


class ProviderResponse(BaseModel):
    answer: str
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    provider: str
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class TraceEvent(BaseModel):
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    request_id: str
    event_type: str
    created_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    request_id: str
    answer: str
    confidence: float
    route: RouteDecision
    context_sources: list[str]
    trace_id: str


class ReflectionTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    trigger: str = "manual"
    started_at: datetime = Field(default_factory=utc_now)


class ReflectionReport(BaseModel):
    task_id: str
    started_at: datetime
    finished_at: datetime
    scanned_entries: int
    duplicates_removed: int
    low_confidence_entries: int
    summary_entry_id: str
    notes: list[str] = Field(default_factory=list)

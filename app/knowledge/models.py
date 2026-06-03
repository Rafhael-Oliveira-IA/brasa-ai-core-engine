from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeLevel(str, Enum):
    FILE = "file"
    FOLDER = "folder"
    MODULE = "module"
    PROJECT = "project"
    GLOBAL = "global"


class KnowledgeSyncRequest(BaseModel):
    force: bool = False
    include_extensions: list[str] | None = None


class KnowledgeNode(BaseModel):
    node_id: str
    level: KnowledgeLevel
    title: str
    source_path: str
    source_hash: str
    last_scan: datetime = Field(default_factory=utc_now)
    file_versions: list[dict[str, str]] = Field(default_factory=list)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    stale: bool = False
    generation: int = 1
    dependencies: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    related_systems: list[str] = Field(default_factory=list)
    risk_level: str = "low"
    children: list[str] = Field(default_factory=list)
    parent_id: str | None = None
    summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    readme_path: str = ""
    metadata_path: str = ""


class KnowledgeNodeView(BaseModel):
    node_id: str
    level: KnowledgeLevel
    title: str
    source_path: str
    stale: bool
    confidence: float
    generation: int
    dependencies: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)
    readme_path: str = ""
    metadata_path: str = ""


class KnowledgeSyncReport(BaseModel):
    sync_id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime
    scanned_files: int
    changed_nodes: int
    regenerated_nodes: int
    removed_nodes: int
    stale_nodes: int
    notes: list[str] = Field(default_factory=list)


class KnowledgeTreeResponse(BaseModel):
    generated_at: datetime = Field(default_factory=utc_now)
    nodes: list[KnowledgeNodeView] = Field(default_factory=list)
    stale_nodes: int = 0

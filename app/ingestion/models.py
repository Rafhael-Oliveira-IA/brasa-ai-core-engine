from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProjectIngestionRequest(BaseModel):
    project_path: str
    force: bool = False


class ScannedFile(BaseModel):
    path: str
    hash: str
    language: str
    modified_at: datetime
    size: int
    module: str
    folder: str


class ProjectProfile(BaseModel):
    project_name: str
    project_type: str
    engine: str


class FileKnowledgeArtifact(BaseModel):
    path: str
    summary_path: str
    metadata_path: str
    dependencies: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)


class IngestionState(BaseModel):
    updated_at: datetime = Field(default_factory=utc_now)
    files: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ProjectIngestionReport(BaseModel):
    project_name: str
    project_path: str
    output_path: str
    scanned_files: int
    changed_files: int
    removed_files: int
    generated_file_summaries: int
    generated_folder_summaries: int
    generated_project_summary: bool
    project_type: str
    engine: str
    notes: list[str] = Field(default_factory=list)

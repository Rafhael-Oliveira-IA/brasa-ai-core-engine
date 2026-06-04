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
    workspace_id: str = "brasa_ai_workspace"
    project_id: str
    user_id: str
    prompt: str = Field(min_length=1)
    tier_hint: ModelTier | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskType(str, Enum):
    CHAT = "chat"
    SUMMARIZE = "summarize"
    REASONING = "reasoning"
    REFLECTION = "reflection"
    REPAIR = "repair"
    PLANNING = "planning"
    ARCHITECTURE = "architecture"
    DEBUGGING = "debugging"
    GENERATION = "generation"


class TaskExecutionOptions(BaseModel):
    persist_memory: bool = True
    run_reflection: bool = False


class TaskRequest(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    workspace_id: str = "brasa_ai_workspace"
    project_id: str
    user_id: str
    task_type: TaskType = TaskType.CHAT
    prompt: str = Field(min_length=1)
    tier_hint: ModelTier | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    options: TaskExecutionOptions = Field(default_factory=TaskExecutionOptions)


class ActionType(str, Enum):
    CREATE_FILE = "create_file"
    UPDATE_FILE = "update_file"
    PATCH_FILE = "patch_file"
    DELETE_FILE = "delete_file"


class ActionRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ValidationSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class ActionStepStatus(str, Enum):
    PLANNED = "planned"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ActionPatchOperation(BaseModel):
    find: str = Field(min_length=1)
    replace: str = ""
    replace_all: bool = False
    use_regex: bool = False


class ActionStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid4()))
    type: ActionType = ActionType.UPDATE_FILE
    target: str = Field(min_length=1)
    intent: str = Field(min_length=2)
    risk: ActionRisk = ActionRisk.MEDIUM
    rationale: str = ""
    patches: list[ActionPatchOperation] = Field(default_factory=list)
    content: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionPlanRequest(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    workspace_id: str = "brasa_ai_workspace"
    project_id: str
    user_id: str
    prompt: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    max_actions: int = Field(default=8, ge=1, le=40)


class ActionPlan(BaseModel):
    plan_id: str
    workspace_id: str = "brasa_ai_workspace"
    project_id: str
    user_id: str
    prompt: str
    summary: str = ""
    actions: list[ActionStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=utc_now)


class ActionValidationIssue(BaseModel):
    step_id: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    code: str
    message: str


class ActionValidationReport(BaseModel):
    ok: bool = True
    issues: list[ActionValidationIssue] = Field(default_factory=list)
    blocked_steps: list[str] = Field(default_factory=list)


class ActionExecutionOptions(BaseModel):
    dry_run: bool = True
    allow_high_risk: bool = False
    auto_rollback_on_error: bool = True
    run_feedback_loop: bool = True


class ActionExecuteRequest(BaseModel):
    workspace_id: str = "brasa_ai_workspace"
    project_id: str
    user_id: str
    plan: ActionPlan
    options: ActionExecutionOptions = Field(default_factory=ActionExecutionOptions)


class ActionStepResult(BaseModel):
    step_id: str
    target: str
    status: ActionStepStatus
    message: str = ""
    backup_path: str | None = None
    bytes_written: int = 0


class ActionExecutionReport(BaseModel):
    execution_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str
    dry_run: bool = True
    applied: int = 0
    skipped: int = 0
    failed: int = 0
    changed_files: list[str] = Field(default_factory=list)
    validation: ActionValidationReport = Field(default_factory=ActionValidationReport)
    results: list[ActionStepResult] = Field(default_factory=list)
    feedback_notes: list[str] = Field(default_factory=list)
    rollback_performed: bool = False
    rollback_restored_files: int = 0
    created_at: datetime = Field(default_factory=utc_now)


class ActionRollbackRequest(BaseModel):
    workspace_id: str = "brasa_ai_workspace"
    project_id: str
    user_id: str
    execution_id: str = Field(min_length=8)


class ActionRollbackReport(BaseModel):
    execution_id: str
    restored_files: int = 0
    removed_files: int = 0
    skipped_files: int = 0
    notes: list[str] = Field(default_factory=list)


class OrchestratorMode(str, Enum):
    MANUAL = "manual"
    AUTOPILOT = "autopilot"


class OrchestratorDecisionState(str, Enum):
    AUTO_EXECUTE = "auto_execute"
    REQUIRES_APPROVAL = "requires_approval"
    BLOCKED = "blocked"


class OrchestratorDecision(BaseModel):
    state: OrchestratorDecisionState = OrchestratorDecisionState.REQUIRES_APPROVAL
    highest_risk: ActionRisk = ActionRisk.MEDIUM
    execute_now: bool = False
    reason: str = ""


class OrchestratorRunRequest(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    workspace_id: str = "brasa_ai_workspace"
    project_id: str
    user_id: str
    intent: str = Field(min_length=1)
    mode: OrchestratorMode = OrchestratorMode.MANUAL
    max_iterations: int = Field(default=1, ge=1, le=5)
    project_path: str | None = None
    dry_run: bool = False
    auto_execute_low_risk: bool = True
    auto_execute_medium_risk: bool = False
    allow_high_risk: bool = False
    block_critical_risk: bool = True
    evaluation_limit: int = Field(default=120, ge=20, le=2000)
    run_reflection: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrchestratorIterationReport(BaseModel):
    iteration: int
    plan: ActionPlan
    decision: OrchestratorDecision
    execution: ActionExecutionReport | None = None
    ingestion: dict[str, Any] = Field(default_factory=dict)
    context_refresh: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)
    reflection: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class OrchestratorRunReport(BaseModel):
    run_id: str
    workspace_id: str
    project_id: str
    user_id: str
    mode: OrchestratorMode
    final_state: OrchestratorDecisionState = OrchestratorDecisionState.REQUIRES_APPROVAL
    iterations: list[OrchestratorIterationReport] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime = Field(default_factory=utc_now)


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
    workspace_id: str = "brasa_ai_workspace"
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
    workspace_id: str = "brasa_ai_workspace"
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


class TaskStageResult(BaseModel):
    stage: str
    status: str = "ok"
    took_ms: int = 0
    details: dict[str, Any] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    task_id: str
    task_type: TaskType
    answer: str
    confidence: float
    route: RouteDecision
    context_sources: list[str] = Field(default_factory=list)
    trace_id: str
    pipeline: list[TaskStageResult] = Field(default_factory=list)
    retrieval: dict[str, Any] = Field(default_factory=dict)


class EvaluationRunRequest(BaseModel):
    limit: int = Field(default=300, ge=20, le=5000)
    workspace_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None


class CognitiveFeedbackVerdict(str, Enum):
    CORRECT = "correct"
    PARTIAL = "partial"
    INCORRECT = "incorrect"


class CognitiveIssueTag(str, Enum):
    CONTEXT_BAD = "context_bad"
    XML_MISSING = "xml_missing"
    HALLUCINATION = "hallucination"
    RETRIEVAL_INCORRECT = "retrieval_incorrect"
    COMPRESSION_BAD = "compression_bad"
    ARCHITECTURAL_LOSS = "architectural_loss"


class CognitiveFeedbackCreateRequest(BaseModel):
    workspace_id: str = "brasa_ai_workspace"
    project_id: str
    user_id: str
    query: str = Field(min_length=2)
    request_id: str | None = None
    verdict: CognitiveFeedbackVerdict = CognitiveFeedbackVerdict.PARTIAL
    issues: list[CognitiveIssueTag] = Field(default_factory=list)
    notes: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


class CognitiveFeedbackEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    workspace_id: str = "brasa_ai_workspace"
    project_id: str
    user_id: str
    query: str = Field(min_length=2)
    request_id: str | None = None
    verdict: CognitiveFeedbackVerdict = CognitiveFeedbackVerdict.PARTIAL
    issues: list[CognitiveIssueTag] = Field(default_factory=list)
    notes: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class CognitiveFeedbackSearchResponse(BaseModel):
    items: list[CognitiveFeedbackEntry]


class EvaluationReport(BaseModel):
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    generated_at: datetime = Field(default_factory=utc_now)
    workspace_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None
    sample_size: int = 0
    retrieval_samples: int = 0
    route_samples: int = 0
    metrics: dict[str, float] = Field(default_factory=dict)
    totals: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


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

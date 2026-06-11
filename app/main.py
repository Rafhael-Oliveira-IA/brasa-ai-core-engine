from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from app.action_engine import CognitiveActionEngine
from app.calibration import CognitiveDiagnosticsEngine
from app.conversation import ConversationRepository
from app.context_builder import ContextBuilder
from app.contracts import (
    ActionExecuteRequest,
    ActionExecutionOptions,
    ActionExecutionReport,
    ActionPlan,
    ActionPlanRequest,
    ActionRollbackReport,
    ActionRollbackRequest,
    ChatResponse,
    CognitiveFeedbackCreateRequest,
    CognitiveFeedbackEntry,
    CognitiveFeedbackSearchResponse,
    ConversationMessage,
    ConversationMessageRole,
    ConversationMessageSearchResponse,
    ConversationSendRequest,
    ConversationSendResponse,
    ConversationSession,
    ConversationSessionCreateRequest,
    ConversationSessionSearchResponse,
    ContextAssembleResponse,
    EvaluationReport,
    EvaluationRunRequest,
    MemoryCreateRequest,
    MemoryEntry,
    MemoryScope,
    MemorySearchResponse,
    OrchestratorRunReport,
    OrchestratorRunRequest,
    ProjectArtifactFileContentResponse,
    ProjectArtifactsTreeResponse,
    ReflectionReport,
    RequestEnvelope,
    TaskRequest,
    TaskResponse,
    TaskType,
    ProjectArtifactFileContentResponse,
    ProjectArtifactsTreeResponse,
    WatcherCheckReport,
    WatcherCheckRequest,
    WorkspaceFileContentResponse,
)
from app.evaluation import EvaluationEngine
from app.feedback import CognitiveFeedbackRepository
from app.ingestion import ProjectIngestionPipeline, ProjectIngestionReport, ProjectIngestionRequest
from app.knowledge import (
    KnowledgeCompiler,
    KnowledgeNodeView,
    KnowledgeSyncReport,
    KnowledgeSyncRequest,
    KnowledgeTreeResponse,
)
from app.memory.repository import MemoryRepository
from app.orchestrator import CognitiveOrchestrator
from app.providers import AlibabaAdapter, AlibabaEmbeddingAdapter, LocalAdapter
from app.query_engine import CognitiveQueryEngine
from app.reflection.nightly_reflection import ReflectionService
from app.router import AIRouter
from app.settings import Settings, get_settings
from app.task_engine import CognitiveTaskEngine
from app.telemetry.tracing import TraceLogger
from app.watcher import FileSystemWatcherEngine
from app.workspace import normalize_workspace_id, resolve_project_root, scoped_project_id, split_scoped_project_id


@dataclass
class RuntimeContainer:
    settings: Settings
    memory_repository: MemoryRepository
    feedback_repository: CognitiveFeedbackRepository
    conversation_repository: ConversationRepository
    knowledge_compiler: KnowledgeCompiler
    ingestion_pipeline: ProjectIngestionPipeline
    watcher_engine: FileSystemWatcherEngine
    context_builder: ContextBuilder
    router: AIRouter
    query_engine: CognitiveQueryEngine
    task_engine: CognitiveTaskEngine
    action_engine: CognitiveActionEngine
    orchestrator: CognitiveOrchestrator
    reflection: ReflectionService
    evaluation_engine: EvaluationEngine
    telemetry: TraceLogger
    diagnostics_engine: CognitiveDiagnosticsEngine


def build_runtime(settings: Settings) -> RuntimeContainer:
    memory_repository = MemoryRepository(settings.sqlite_path)
    feedback_repository = CognitiveFeedbackRepository(settings.sqlite_path)
    conversation_repository = ConversationRepository(settings.sqlite_path)

    include_extensions = {
        item.strip()
        for item in settings.knowledge_include_extensions.split(",")
        if item.strip()
    }
    knowledge_compiler = KnowledgeCompiler(
        project_root=settings.data_dir.parent,
        output_dir=settings.knowledge_dir,
        state_file=settings.knowledge_state_file,
        include_extensions=include_extensions,
        max_file_bytes=settings.knowledge_max_file_bytes,
    )
    ingestion_pipeline = ProjectIngestionPipeline(
        output_projects_root=settings.data_dir.parent / ".brasa",
        max_file_bytes=settings.knowledge_max_file_bytes,
    )
    watcher_engine = FileSystemWatcherEngine(
        snapshot_root=settings.data_dir.parent / ".brasa" / "watchers",
        max_file_bytes=settings.knowledge_max_file_bytes,
    )
    try:
        knowledge_compiler.sync(force=False)
    except Exception:
        # Runtime should remain available even if knowledge sync fails.
        pass

    embedding_client = None
    if settings.alibaba_embedding_enabled and settings.alibaba_api_key:
        embedding_client = AlibabaEmbeddingAdapter(
            api_key=settings.alibaba_api_key,
            base_url=settings.alibaba_base_url,
            region_base_urls=[
                item.strip()
                for item in settings.alibaba_region_base_urls.split(",")
                if item.strip()
            ]
            or None,
            model_name=settings.alibaba_embedding_model,
            timeout_seconds=settings.alibaba_embedding_timeout_seconds,
            max_retries=settings.alibaba_max_retries,
            retry_backoff_seconds=settings.alibaba_retry_backoff_seconds,
            max_batch_size=settings.alibaba_embedding_max_batch_size,
            cache_file=settings.alibaba_embedding_cache_file,
        )

    local_provider = LocalAdapter(model_name=settings.local_model_name)
    alibaba_provider = AlibabaAdapter(
        api_key=settings.alibaba_api_key,
        base_url=settings.alibaba_base_url,
        region_base_urls=[
            item.strip()
            for item in settings.alibaba_region_base_urls.split(",")
            if item.strip()
        ]
        or None,
        max_retries=settings.alibaba_max_retries,
        retry_backoff_seconds=settings.alibaba_retry_backoff_seconds,
    )

    context_builder = ContextBuilder(
        memory_repository=memory_repository,
        max_chars=settings.chat_context_max_chars,
        knowledge_compiler=knowledge_compiler,
        project_artifacts_root=settings.data_dir.parent / ".brasa",
        embedding_client=embedding_client,
        retrieval_assist_provider=alibaba_provider,
        retrieval_assist_enabled=settings.retrieval_cloud_assist_enabled,
        retrieval_assist_model_name=(
            settings.retrieval_cloud_assist_model.strip()
            or settings.alibaba_model_flash
        ),
        retrieval_assist_min_candidates=settings.retrieval_cloud_assist_min_candidates,
        retrieval_assist_timeout_seconds=settings.retrieval_cloud_assist_timeout_seconds,
        auto_reingest_on_weak_context=settings.chat_auto_reingest_on_weak_context,
        auto_reingest_min_selected_context=settings.chat_auto_reingest_min_selected_context,
        auto_reingest_cooldown_seconds=settings.chat_auto_reingest_cooldown_seconds,
    )
    router = AIRouter(
        settings=settings,
        local_provider=local_provider,
        alibaba_provider=alibaba_provider,
    )

    blocked_paths = tuple(
        item.strip()
        for item in settings.action_blocked_paths.split(",")
        if item.strip()
    )
    action_engine = CognitiveActionEngine(
        context_builder=context_builder,
        memory_repository=memory_repository,
        workspace_root=settings.action_workspace_root,
        backup_root=settings.action_backup_dir,
        blocked_path_prefixes=blocked_paths,
        allow_delete=settings.action_allow_delete,
        max_file_bytes=settings.action_max_file_bytes,
        router=router,
        model_assist_enabled=settings.action_model_assist_enabled,
        model_assist_tier=settings.action_model_assist_tier,
    )

    diagnostics_engine = CognitiveDiagnosticsEngine(
        trace_file=settings.trace_file,
        output_dir=settings.calibration_failures_dir,
        usage_dataset_dir=settings.evaluation_dir / "cognitive_usage",
        feedback_repository=feedback_repository,
    )

    reflection = ReflectionService(
        repository=memory_repository,
        report_dir=settings.reflection_dir,
        knowledge_compiler=knowledge_compiler,
        feedback_repository=feedback_repository,
        diagnostics_engine=diagnostics_engine,
    )
    evaluation_engine = EvaluationEngine(
        trace_file=settings.trace_file,
        report_dir=settings.evaluation_dir,
    )
    telemetry = TraceLogger(file_path=settings.trace_file)
    query_engine = CognitiveQueryEngine(
        context_builder=context_builder,
        router=router,
        telemetry=telemetry,
        memory_repository=memory_repository,
    )
    task_engine = CognitiveTaskEngine(
        context_builder=context_builder,
        router=router,
        telemetry=telemetry,
        memory_repository=memory_repository,
        reflection=reflection,
    )
    orchestrator = CognitiveOrchestrator(
        action_engine=action_engine,
        context_builder=context_builder,
        ingestion_pipeline=ingestion_pipeline,
        knowledge_compiler=knowledge_compiler,
        evaluation_engine=evaluation_engine,
        reflection=reflection,
        memory_repository=memory_repository,
    )

    return RuntimeContainer(
        settings=settings,
        memory_repository=memory_repository,
        feedback_repository=feedback_repository,
        conversation_repository=conversation_repository,
        knowledge_compiler=knowledge_compiler,
        ingestion_pipeline=ingestion_pipeline,
        watcher_engine=watcher_engine,
        context_builder=context_builder,
        router=router,
        query_engine=query_engine,
        task_engine=task_engine,
        action_engine=action_engine,
        orchestrator=orchestrator,
        reflection=reflection,
        evaluation_engine=evaluation_engine,
        telemetry=telemetry,
        diagnostics_engine=diagnostics_engine,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = ensure_runtime(app)
    settings = runtime.settings

    stop_event = asyncio.Event()
    scheduler_task = None

    if settings.enable_reflection_scheduler:
        scheduler_task = asyncio.create_task(
            runtime.reflection.run_forever(
                interval_minutes=settings.reflection_interval_minutes,
                stop_event=stop_event,
            )
        )

    app.state.reflection_stop_event = stop_event
    app.state.reflection_scheduler_task = scheduler_task

    try:
        yield
    finally:
        stop_event.set()
        if scheduler_task is not None:
            await scheduler_task


app = FastAPI(
    title="Brasa AI Core Lite",
    version="0.1.0",
    lifespan=lifespan,
)

_cors_origins = [
    item.strip()
    for item in get_settings().frontend_allowed_origins.split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_runtime(app: FastAPI) -> RuntimeContainer:
    runtime = getattr(app.state, "runtime", None)
    if runtime is None:
        runtime = build_runtime(get_settings())
        app.state.runtime = runtime
    return runtime


def runtime_from(request: Request) -> RuntimeContainer:
    return ensure_runtime(request.app)


def scope_envelope(payload: RequestEnvelope) -> RequestEnvelope:
    workspace_id = normalize_workspace_id(payload.workspace_id)
    metadata = dict(payload.metadata)
    metadata.setdefault("workspace_id", workspace_id)
    metadata.setdefault("project_id", payload.project_id)

    return payload.model_copy(
        update={
            "workspace_id": workspace_id,
            "project_id": scoped_project_id(project_id=payload.project_id, workspace_id=workspace_id),
            "metadata": metadata,
        }
    )


def scope_task(payload: TaskRequest) -> TaskRequest:
    workspace_id = normalize_workspace_id(payload.workspace_id)
    metadata = dict(payload.metadata)
    metadata.setdefault("workspace_id", workspace_id)
    metadata.setdefault("project_id", payload.project_id)

    return payload.model_copy(
        update={
            "workspace_id": workspace_id,
            "project_id": scoped_project_id(project_id=payload.project_id, workspace_id=workspace_id),
            "metadata": metadata,
        }
    )


def scope_action_plan(payload: ActionPlanRequest) -> ActionPlanRequest:
    workspace_id = normalize_workspace_id(payload.workspace_id)
    metadata = dict(payload.metadata)
    metadata.setdefault("workspace_id", workspace_id)
    metadata.setdefault("project_id", payload.project_id)

    return payload.model_copy(
        update={
            "workspace_id": workspace_id,
            "project_id": scoped_project_id(project_id=payload.project_id, workspace_id=workspace_id),
            "metadata": metadata,
        }
    )


def scope_action_execute(payload: ActionExecuteRequest) -> ActionExecuteRequest:
    workspace_id = normalize_workspace_id(payload.workspace_id)
    scoped_project = scoped_project_id(project_id=payload.project_id, workspace_id=workspace_id)
    scoped_plan = payload.plan.model_copy(
        update={
            "workspace_id": workspace_id,
            "project_id": scoped_project,
            "user_id": payload.user_id,
        }
    )

    return payload.model_copy(
        update={
            "workspace_id": workspace_id,
            "project_id": scoped_project,
            "plan": scoped_plan,
        }
    )


def scope_action_rollback(payload: ActionRollbackRequest) -> ActionRollbackRequest:
    workspace_id = normalize_workspace_id(payload.workspace_id)
    scoped_project = scoped_project_id(project_id=payload.project_id, workspace_id=workspace_id)
    return payload.model_copy(
        update={
            "workspace_id": workspace_id,
            "project_id": scoped_project,
        }
    )


def scope_orchestrator(payload: OrchestratorRunRequest) -> OrchestratorRunRequest:
    workspace_id = normalize_workspace_id(payload.workspace_id)
    metadata = dict(payload.metadata)
    metadata.setdefault("workspace_id", workspace_id)
    metadata.setdefault("project_id", payload.project_id)

    return payload.model_copy(
        update={
            "workspace_id": workspace_id,
            "project_id": scoped_project_id(project_id=payload.project_id, workspace_id=workspace_id),
            "metadata": metadata,
        }
    )


def scope_conversation_session_create(
    payload: ConversationSessionCreateRequest,
) -> ConversationSessionCreateRequest:
    workspace_id = normalize_workspace_id(payload.workspace_id)

    return payload.model_copy(
        update={
            "workspace_id": workspace_id,
            "project_id": scoped_project_id(project_id=payload.project_id, workspace_id=workspace_id),
        }
    )


def scope_conversation_send(payload: ConversationSendRequest) -> ConversationSendRequest:
    workspace_id = normalize_workspace_id(payload.workspace_id)
    return payload.model_copy(
        update={
            "workspace_id": workspace_id,
            "project_id": scoped_project_id(project_id=payload.project_id, workspace_id=workspace_id),
        }
    )


def resolve_workspace_file_path(*, workspace_root: Path, relative_path: str) -> Path:
    raw = str(relative_path or "").replace("\\", "/").strip()
    if not raw:
        raise ValueError("File path is required.")

    if raw.startswith("/"):
        raise ValueError("Absolute paths are not allowed.")
    if len(raw) >= 2 and raw[1] == ":":
        raise ValueError("Drive-prefixed absolute paths are not allowed.")

    while raw.startswith("./"):
        raw = raw[2:]

    parts = [item for item in raw.split("/") if item and item != "."]
    if not parts or ".." in parts:
        raise ValueError("Path is invalid or escapes workspace root.")

    normalized = "/".join(parts)
    resolved_root = workspace_root.resolve()
    resolved_target = (resolved_root / normalized).resolve()

    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("Path is outside workspace root.") from exc

    return resolved_target


async def run_chat_task(runtime: RuntimeContainer, payload: RequestEnvelope) -> tuple[TaskResponse, dict[str, Any]]:
    if hasattr(runtime, "task_engine"):
        task_request = TaskRequest(
            task_id=payload.request_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            user_id=payload.user_id,
            task_type=TaskType.CHAT,
            prompt=payload.prompt,
            tier_hint=payload.tier_hint,
            metadata=payload.metadata,
        )
        task_response, retrieval = await runtime.task_engine.run(task_request)
        return task_response, _payload_of(retrieval)

    if hasattr(runtime, "query_engine"):
        chat_response, retrieval = await runtime.query_engine.run(payload)
        return (
            TaskResponse(
                task_id=payload.request_id,
                task_type=TaskType.CHAT,
                answer=chat_response.answer,
                confidence=chat_response.confidence,
                route=chat_response.route,
                context_sources=chat_response.context_sources,
                trace_id=chat_response.trace_id,
                pipeline=[],
                retrieval={},
            ),
            _payload_of(retrieval),
        )

    raise HTTPException(status_code=503, detail="No chat execution engine is available in this runtime.")


def _payload_of(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except Exception:
            pass
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return [_payload_of(item) for item in value]
    return value


def normalize_path_for_artifacts(path: str) -> str:
    text = str(path or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if isinstance(payload, dict):
        return payload
    return {}


def resolve_project_artifacts_context(
    *,
    runtime: RuntimeContainer,
    workspace_id: str,
    project_id: str,
) -> tuple[str, str, str, Path]:
    normalized_workspace, plain_project = split_scoped_project_id(
        project_id,
        fallback_workspace_id=workspace_id,
    )
    scoped_project = scoped_project_id(project_id=plain_project, workspace_id=normalized_workspace)

    artifacts_root = resolve_project_root(
        artifacts_base_root=runtime.context_builder.project_artifacts_root,
        project_id=plain_project,
        workspace_id=normalized_workspace,
    )
    return normalized_workspace, plain_project, scoped_project, artifacts_root


def resolve_project_source_root(artifacts_root: Path) -> Path | None:
    files_index = artifacts_root / "raw" / "files_index.json"
    payload = _load_json_file(files_index)
    raw_project_path = str(payload.get("project_path") or "").strip()
    if not raw_project_path:
        return None

    source_root = Path(raw_project_path).resolve()
    if not source_root.exists() or not source_root.is_dir():
        return None

    return source_root


def _read_text_with_fallback(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _trim_content(content: str, max_chars: int) -> tuple[str, bool]:
    truncated = len(content) > max_chars
    if truncated:
        return content[:max_chars], True
    return content, False


def _resolve_artifact_metadata_path(*, artifacts_root: Path, relative_path: str) -> Path:
    normalized = normalize_path_for_artifacts(relative_path)
    rel = Path(normalized)
    return artifacts_root / "metadata" / "files" / rel.parent / f"{rel.stem}.meta.json"


def _is_browsable_project_artifact_path(path: str) -> bool:
    normalized = normalize_path_for_artifacts(path).lower()
    if not normalized:
        return False

    blocked_prefixes = (
        ".brasa/",
        "data/knowledge/",
        "data/evaluations/",
        "data/reflection_reports/",
        "app-front/dist/",
    )
    if any(normalized.startswith(prefix) for prefix in blocked_prefixes):
        return False

    if normalized in {"data/traces.jsonl", "data/memory.db"}:
        return False

    scoped = f"/{normalized}/"
    blocked_segments = (
        "/.git/",
        "/build/",
        "/cmake/",
        "/vc17/",
        "/vcpkg_installed/",
        "/node_modules/",
        "/metadata/files/",
    )
    if any(segment in scoped for segment in blocked_segments):
        return False

    return True


def _bool_option(raw: Any, *, default: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _int_option(raw: Any, *, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(raw)
    except Exception:
        value = default

    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _task_type_from_command(raw: str) -> TaskType:
    normalized = (raw or "").strip().lower()
    try:
        return TaskType(normalized)
    except ValueError as exc:
        supported = ", ".join(item.value for item in TaskType)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_type '{raw}'. Supported values: {supported}",
        ) from exc


async def run_conversation_command(
    *,
    runtime: RuntimeContainer,
    session_id: str,
    user_message: ConversationMessage,
    payload: ConversationSendRequest,
) -> dict[str, Any]:
    command = str(payload.command or "chat").strip().lower()
    options = payload.options if isinstance(payload.options, dict) else {}

    if command == "chat":
        envelope = RequestEnvelope(
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            user_id=payload.user_id,
            prompt=payload.prompt,
            metadata={
                **payload.metadata,
                "source": "conversation_api",
                "task_type": "chat",
                "conversation_session_id": session_id,
                "conversation_message_id": user_message.message_id,
            },
        )
        task_response, retrieval_payload = await run_chat_task(runtime, envelope)
        return {
            "operation": command,
            "answer": task_response.answer,
            "task": task_response,
            "operation_result": {
                "task_id": task_response.task_id,
                "task_type": task_response.task_type.value,
                "retrieval": retrieval_payload,
            },
            "request_id": task_response.task_id,
            "trace_id": task_response.trace_id,
            "route": task_response.route,
            "context_sources": task_response.context_sources,
            "confidence": task_response.confidence,
        }

    if command == "task":
        if not hasattr(runtime, "task_engine"):
            raise HTTPException(status_code=503, detail="Task engine is not available in this runtime.")

        task_type = _task_type_from_command(str(options.get("task_type") or "chat"))
        task_request = scope_task(
            TaskRequest(
                workspace_id=payload.workspace_id,
                project_id=payload.project_id,
                user_id=payload.user_id,
                task_type=task_type,
                prompt=payload.prompt,
                metadata={
                    **payload.metadata,
                    "source": "conversation_api",
                    "conversation_session_id": session_id,
                    "conversation_message_id": user_message.message_id,
                    "conversation_command": command,
                },
            )
        )
        task_response, retrieval = await runtime.task_engine.run(task_request)
        return {
            "operation": command,
            "answer": task_response.answer,
            "task": task_response,
            "operation_result": {
                "task": _payload_of(task_response),
                "retrieval": _payload_of(retrieval),
            },
            "request_id": task_response.task_id,
            "trace_id": task_response.trace_id,
            "route": task_response.route,
            "context_sources": task_response.context_sources,
            "confidence": task_response.confidence,
        }

    if command == "action_plan":
        if not hasattr(runtime, "action_engine"):
            raise HTTPException(status_code=503, detail="Action engine is not available in this runtime.")

        plan_request = scope_action_plan(
            ActionPlanRequest(
                workspace_id=payload.workspace_id,
                project_id=payload.project_id,
                user_id=payload.user_id,
                prompt=payload.prompt,
                max_actions=_int_option(options.get("max_actions"), default=8, minimum=1, maximum=40),
                metadata={
                    **payload.metadata,
                    "source": "conversation_api",
                    "conversation_session_id": session_id,
                    "conversation_message_id": user_message.message_id,
                    "conversation_command": command,
                },
            )
        )
        plan, retrieval = runtime.action_engine.plan(plan_request)
        highest_risk = max((step.risk.value for step in plan.actions), default="low")
        return {
            "operation": command,
            "answer": (
                f"Action plan generated with {len(plan.actions)} action(s). "
                f"Highest risk: {highest_risk}."
            ),
            "task": None,
            "operation_result": {
                "plan": _payload_of(plan),
                "retrieval": _payload_of(retrieval),
            },
            "request_id": plan.plan_id,
            "trace_id": None,
            "route": None,
            "context_sources": [],
            "confidence": None,
        }

    if command == "action_execute":
        if not hasattr(runtime, "action_engine"):
            raise HTTPException(status_code=503, detail="Action engine is not available in this runtime.")

        raw_plan = options.get("plan")
        if not isinstance(raw_plan, dict):
            raise HTTPException(status_code=400, detail="action_execute requires options.plan payload.")

        execution_options_payload = options.get("execution_options", {})
        scoped_request = scope_action_execute(
            ActionExecuteRequest(
                workspace_id=payload.workspace_id,
                project_id=payload.project_id,
                user_id=payload.user_id,
                plan=ActionPlan.model_validate(raw_plan),
                options=ActionExecutionOptions.model_validate(execution_options_payload),
            )
        )

        report = runtime.action_engine.execute(scoped_request)
        if scoped_request.options.run_feedback_loop and not scoped_request.options.dry_run and report.applied > 0:
            report.feedback_notes = run_action_feedback_loop(
                runtime=runtime,
                workspace_id=scoped_request.workspace_id,
                project_id=scoped_request.project_id,
                user_id=scoped_request.user_id,
                report=report,
            )

        return {
            "operation": command,
            "answer": (
                f"Action execution completed. applied={report.applied}, "
                f"failed={report.failed}, changed_files={len(report.changed_files)}."
            ),
            "task": None,
            "operation_result": {
                "execution": _payload_of(report),
            },
            "request_id": report.execution_id,
            "trace_id": None,
            "route": None,
            "context_sources": [],
            "confidence": None,
        }

    if command == "action_rollback":
        if not hasattr(runtime, "action_engine"):
            raise HTTPException(status_code=503, detail="Action engine is not available in this runtime.")

        execution_id = str(options.get("execution_id") or "").strip()
        if not execution_id:
            raise HTTPException(status_code=400, detail="action_rollback requires options.execution_id.")

        rollback_request = scope_action_rollback(
            ActionRollbackRequest(
                workspace_id=payload.workspace_id,
                project_id=payload.project_id,
                user_id=payload.user_id,
                execution_id=execution_id,
            )
        )
        report = runtime.action_engine.rollback(rollback_request)

        if report.restored_files > 0 or report.removed_files > 0:
            runtime.memory_repository.add_entry(
                MemoryEntry(
                    project_id=rollback_request.project_id,
                    user_id=rollback_request.user_id,
                    scope=MemoryScope.EPISODIC,
                    content=(
                        f"Rollback executed for action execution {rollback_request.execution_id}.\n"
                        f"Restored={report.restored_files}, Removed={report.removed_files}."
                    ),
                    tags=["action", "rollback", "auto"],
                    confidence=0.75,
                    provenance={
                        "workspace_id": rollback_request.workspace_id,
                        "execution_id": rollback_request.execution_id,
                    },
                )
            )

        return {
            "operation": command,
            "answer": (
                f"Rollback completed. restored={report.restored_files}, "
                f"removed={report.removed_files}, skipped={report.skipped_files}."
            ),
            "task": None,
            "operation_result": {
                "rollback": _payload_of(report),
            },
            "request_id": execution_id,
            "trace_id": None,
            "route": None,
            "context_sources": [],
            "confidence": None,
        }

    if command == "orchestrator":
        if not hasattr(runtime, "orchestrator"):
            raise HTTPException(status_code=503, detail="Orchestrator is not available in this runtime.")

        orchestrator_payload = {
            "workspace_id": payload.workspace_id,
            "project_id": payload.project_id,
            "user_id": payload.user_id,
            "intent": payload.prompt,
            "metadata": {
                **payload.metadata,
                "source": "conversation_api",
                "conversation_session_id": session_id,
                "conversation_message_id": user_message.message_id,
                "conversation_command": command,
            },
            **options,
        }
        orchestrator_request = scope_orchestrator(OrchestratorRunRequest.model_validate(orchestrator_payload))
        report = runtime.orchestrator.run(orchestrator_request)

        return {
            "operation": command,
            "answer": (
                f"Orchestrator run finished with state '{report.final_state.value}'. "
                f"Iterations: {len(report.iterations)}."
            ),
            "task": None,
            "operation_result": {
                "orchestrator": _payload_of(report),
            },
            "request_id": report.run_id,
            "trace_id": None,
            "route": None,
            "context_sources": [],
            "confidence": None,
        }

    if command == "context_assemble":
        envelope = scope_envelope(
            RequestEnvelope(
                workspace_id=payload.workspace_id,
                project_id=payload.project_id,
                user_id=payload.user_id,
                prompt=payload.prompt,
                metadata={
                    **payload.metadata,
                    "source": "conversation_api",
                    "conversation_session_id": session_id,
                    "conversation_message_id": user_message.message_id,
                    "conversation_command": command,
                },
            )
        )
        packet, retrieval = runtime.context_builder.build(envelope)
        trace_id = runtime.telemetry.new_trace_id()
        runtime.telemetry.log_retrieval(trace_id=trace_id, envelope=envelope, retrieval=retrieval)

        return {
            "operation": command,
            "answer": (
                f"Context assembled with {len(packet.snippets)} snippet(s). "
                f"Retrieval took {retrieval.took_ms} ms."
            ),
            "task": None,
            "operation_result": {
                "packet": _payload_of(packet),
                "retrieval": _payload_of(retrieval),
            },
            "request_id": envelope.request_id,
            "trace_id": trace_id,
            "route": None,
            "context_sources": packet.provenance,
            "confidence": None,
        }

    if command == "knowledge_sync":
        sync_payload = KnowledgeSyncRequest.model_validate(options)
        report = runtime.knowledge_compiler.sync(
            force=sync_payload.force,
            include_extensions=sync_payload.include_extensions,
        )
        return {
            "operation": command,
            "answer": (
                f"Knowledge sync completed. scanned={report.scanned_files}, "
                f"changed={report.changed_nodes}, stale={report.stale_nodes}."
            ),
            "task": None,
            "operation_result": {
                "knowledge_sync": _payload_of(report),
            },
            "request_id": None,
            "trace_id": None,
            "route": None,
            "context_sources": [],
            "confidence": None,
        }

    if command == "ingestion_run":
        project_path = str(options.get("project_path") or "").strip()
        if not project_path:
            raise HTTPException(status_code=400, detail="ingestion_run requires options.project_path.")

        report = runtime.ingestion_pipeline.run(
            project_path=Path(project_path),
            force=_bool_option(options.get("force"), default=False),
            workspace_id=payload.workspace_id,
        )

        return {
            "operation": command,
            "answer": (
                f"Ingestion completed for project '{report.project_name}'. "
                f"Files indexed: {report.indexed_files}."
            ),
            "task": None,
            "operation_result": {
                "ingestion": _payload_of(report),
            },
            "request_id": None,
            "trace_id": None,
            "route": None,
            "context_sources": [],
            "confidence": None,
        }

    if command == "watcher_check":
        project_path = str(options.get("project_path") or "").strip()
        if not project_path:
            raise HTTPException(status_code=400, detail="watcher_check requires options.project_path.")

        report = runtime.watcher_engine.check(
            project_path=Path(project_path),
            workspace_id=payload.workspace_id,
        )
        if _bool_option(options.get("auto_rebuild"), default=True) and report.changes_detected > 0:
            runtime.ingestion_pipeline.run(
                project_path=Path(project_path),
                force=False,
                workspace_id=payload.workspace_id,
            )
            report = report.model_copy(
                update={
                    "rebuilt": True,
                    "notes": [*report.notes, "Incremental ingestion triggered by watcher."],
                }
            )

        return {
            "operation": command,
            "answer": (
                f"Watcher check completed. changes_detected={report.changes_detected}, "
                f"rebuilt={report.rebuilt}."
            ),
            "task": None,
            "operation_result": {
                "watcher": _payload_of(report),
            },
            "request_id": None,
            "trace_id": None,
            "route": None,
            "context_sources": [],
            "confidence": None,
        }

    if command == "evaluation_run":
        report = runtime.evaluation_engine.run(
            limit=_int_option(options.get("limit"), default=300, minimum=20, maximum=5000),
            project_id=payload.project_id,
            user_id=payload.user_id,
        )
        return {
            "operation": command,
            "answer": (
                f"Evaluation completed. sample_size={report.sample_size}, "
                f"retrieval_precision={report.metrics.get('retrieval_precision', 0.0):.3f}."
            ),
            "task": None,
            "operation_result": {
                "evaluation": _payload_of(report),
            },
            "request_id": report.report_id,
            "trace_id": None,
            "route": None,
            "context_sources": [],
            "confidence": None,
        }

    if command == "reflection_run":
        report = runtime.reflection.run_once(
            trigger="conversation",
            project_id=payload.project_id,
            user_id=payload.user_id,
        )
        return {
            "operation": command,
            "answer": (
                f"Reflection completed. duplicates_removed={report.duplicates_removed}, "
                f"low_confidence_entries={report.low_confidence_entries}."
            ),
            "task": None,
            "operation_result": {
                "reflection": _payload_of(report),
            },
            "request_id": report.task_id,
            "trace_id": None,
            "route": None,
            "context_sources": [],
            "confidence": None,
        }

    if command == "diagnostics":
        report = runtime.diagnostics_engine.run(project_id=payload.project_id, user_id=payload.user_id)
        return {
            "operation": command,
            "answer": (
                f"Diagnostics completed with {len(report.get('failure_counts', {}))} failure bucket(s)."
            ),
            "task": None,
            "operation_result": {
                "diagnostics": _payload_of(report),
            },
            "request_id": None,
            "trace_id": None,
            "route": None,
            "context_sources": [],
            "confidence": None,
        }

    raise HTTPException(
        status_code=400,
        detail=(
            "Invalid command. Supported commands: "
            "chat, task, action_plan, action_execute, action_rollback, orchestrator, "
            "context_assemble, knowledge_sync, ingestion_run, watcher_check, "
            "evaluation_run, reflection_run, diagnostics"
        ),
    )


def run_action_feedback_loop(
    *,
    runtime: RuntimeContainer,
    workspace_id: str,
    project_id: str,
    user_id: str,
    report: ActionExecutionReport,
) -> list[str]:
    notes: list[str] = []

    try:
        knowledge_report = runtime.knowledge_compiler.sync(force=False)
        notes.append(
            (
                "knowledge_sync: "
                f"scanned={knowledge_report.scanned_files}, changed={knowledge_report.changed_nodes}"
            )
        )
    except Exception as exc:
        notes.append(f"knowledge_sync_failed: {exc}")

    try:
        evaluation_report = runtime.evaluation_engine.run(
            limit=120,
            project_id=project_id,
            user_id=user_id,
        )
        notes.append(f"evaluation: sample_size={evaluation_report.sample_size}")
    except Exception as exc:
        notes.append(f"evaluation_failed: {exc}")

    try:
        reflection_report = runtime.reflection.run_once(
            trigger="action_execution",
            project_id=project_id,
            user_id=user_id,
        )
        notes.append(f"reflection: summary_entry_id={reflection_report.summary_entry_id}")
    except Exception as exc:
        notes.append(f"reflection_failed: {exc}")

    runtime.memory_repository.add_entry(
        MemoryEntry(
            project_id=project_id,
            user_id=user_id,
            scope=MemoryScope.EPISODIC,
            content=(
                f"Action execution completed. Applied={report.applied}, Failed={report.failed}.\n"
                f"Changed files: {', '.join(report.changed_files[:20])}\n"
                f"Feedback loop: {' | '.join(notes)}"
            ),
            tags=["action", "feedback-loop", "auto"],
            confidence=0.76,
            provenance={
                "workspace_id": workspace_id,
                "execution_id": report.execution_id,
            },
        )
    )

    return notes


@app.get("/health")
def health(request: Request) -> dict[str, object]:
    runtime = runtime_from(request)
    return {
        "status": "ok",
        "app_name": runtime.settings.app_name,
        "environment": runtime.settings.environment,
        "reflection_scheduler": runtime.settings.enable_reflection_scheduler,
        "knowledge_stale_nodes": runtime.knowledge_compiler.stale_count(),
    }


@app.get("/v1/workspace/file", response_model=WorkspaceFileContentResponse)
def read_workspace_file(
    request: Request,
    path: str = Query(..., min_length=1),
    max_chars: int = Query(default=20000, ge=200, le=200000),
) -> WorkspaceFileContentResponse:
    runtime = runtime_from(request)
    workspace_root = runtime.settings.action_workspace_root.resolve()

    try:
        target = resolve_workspace_file_path(workspace_root=workspace_root, relative_path=path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Workspace file not found.")

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = target.read_text(encoding="utf-8", errors="replace")

    size_bytes = target.stat().st_size
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars]

    relative = target.relative_to(workspace_root).as_posix()

    return WorkspaceFileContentResponse(
        path=relative,
        exists=True,
        content=content,
        truncated=truncated,
        size_bytes=size_bytes,
        encoding="utf-8",
    )


@app.get("/v1/project/artifacts/tree", response_model=ProjectArtifactsTreeResponse)
def project_artifacts_tree(
    request: Request,
    workspace_id: str = Query(default="brasa_ai_workspace"),
    project_id: str = Query(...),
    limit: int = Query(default=5000, ge=1, le=50000),
) -> ProjectArtifactsTreeResponse:
    runtime = runtime_from(request)
    normalized_workspace, plain_project, scoped_project, artifacts_root = resolve_project_artifacts_context(
        runtime=runtime,
        workspace_id=workspace_id,
        project_id=project_id,
    )

    metadata_root = artifacts_root / "metadata" / "files"
    ingested = metadata_root.exists()
    files: list[str] = []
    notes: list[str] = []

    if ingested:
        for meta_path in metadata_root.rglob("*.meta.json"):
            payload = _load_json_file(meta_path)
            relative_path = normalize_path_for_artifacts(str(payload.get("path") or ""))
            if not relative_path:
                continue
            if not _is_browsable_project_artifact_path(relative_path):
                continue
            files.append(relative_path)
            if len(files) >= limit:
                notes.append(f"File list truncated to limit={limit}.")
                break
    else:
        notes.append("Project artifacts not ingested for selected workspace/project.")

    source_root = resolve_project_source_root(artifacts_root)
    if source_root is None:
        notes.append("Source project path is unavailable; run ingestion with project_path.")

    dedup_files = sorted(set(files))

    return ProjectArtifactsTreeResponse(
        workspace_id=normalized_workspace,
        project_id=plain_project,
        scoped_project_id=scoped_project,
        artifacts_root=artifacts_root.as_posix(),
        ingested=ingested,
        source_project_path=source_root.as_posix() if source_root else None,
        file_count=len(dedup_files),
        files=dedup_files,
        notes=notes,
    )


@app.get("/v1/project/artifacts/file", response_model=ProjectArtifactFileContentResponse)
def project_artifact_file(
    request: Request,
    workspace_id: str = Query(default="brasa_ai_workspace"),
    project_id: str = Query(...),
    path: str = Query(..., min_length=1),
    max_chars: int = Query(default=50000, ge=200, le=200000),
) -> ProjectArtifactFileContentResponse:
    runtime = runtime_from(request)
    normalized_workspace, plain_project, scoped_project, artifacts_root = resolve_project_artifacts_context(
        runtime=runtime,
        workspace_id=workspace_id,
        project_id=project_id,
    )

    normalized_relative = normalize_path_for_artifacts(path)
    if not normalized_relative:
        raise HTTPException(status_code=400, detail="File path is required.")

    source_root = resolve_project_source_root(artifacts_root)
    if source_root is not None:
        try:
            source_file = resolve_workspace_file_path(
                workspace_root=source_root,
                relative_path=normalized_relative,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if source_file.exists() and source_file.is_file():
            content = _read_text_with_fallback(source_file)
            trimmed, truncated = _trim_content(content, max_chars)
            return ProjectArtifactFileContentResponse(
                workspace_id=normalized_workspace,
                project_id=plain_project,
                scoped_project_id=scoped_project,
                path=normalized_relative,
                exists=True,
                content=trimmed,
                truncated=truncated,
                size_bytes=source_file.stat().st_size,
                encoding="utf-8",
                source="project_source",
            )

    metadata_path = _resolve_artifact_metadata_path(
        artifacts_root=artifacts_root,
        relative_path=normalized_relative,
    )
    metadata_payload = _load_json_file(metadata_path)
    summary_path_value = str(metadata_payload.get("summary_path") or "").strip()

    if summary_path_value:
        summary_path = Path(summary_path_value)
    else:
        rel = Path(normalized_relative)
        summary_path = artifacts_root / "summaries" / "files" / rel.parent / f"{rel.stem}.summary.md"

    if summary_path.exists() and summary_path.is_file():
        content = _read_text_with_fallback(summary_path)
        trimmed, truncated = _trim_content(content, max_chars)
        return ProjectArtifactFileContentResponse(
            workspace_id=normalized_workspace,
            project_id=plain_project,
            scoped_project_id=scoped_project,
            path=normalized_relative,
            exists=True,
            content=trimmed,
            truncated=truncated,
            size_bytes=summary_path.stat().st_size,
            encoding="utf-8",
            source="artifact_summary",
        )

    raise HTTPException(
        status_code=404,
        detail="Project artifact file not found. Run ingestion for this workspace/project.",
    )


@app.post("/v1/memory", response_model=MemoryEntry)
def create_memory(payload: MemoryCreateRequest, request: Request) -> MemoryEntry:
    runtime = runtime_from(request)
    workspace_id = normalize_workspace_id(payload.workspace_id)
    scoped_project = scoped_project_id(project_id=payload.project_id, workspace_id=workspace_id)

    entry = MemoryEntry(
        project_id=scoped_project,
        user_id=payload.user_id,
        scope=payload.scope,
        content=payload.content,
        tags=payload.tags,
        confidence=payload.confidence,
        provenance={
            **payload.provenance,
            "workspace_id": workspace_id,
            "project_id": payload.project_id,
        },
    )

    return runtime.memory_repository.add_entry(entry)


@app.post("/v1/feedback", response_model=CognitiveFeedbackEntry)
def create_feedback(payload: CognitiveFeedbackCreateRequest, request: Request) -> CognitiveFeedbackEntry:
    runtime = runtime_from(request)
    workspace_id = normalize_workspace_id(payload.workspace_id)
    scoped_project = scoped_project_id(project_id=payload.project_id, workspace_id=workspace_id)

    entry = CognitiveFeedbackEntry(
        workspace_id=workspace_id,
        project_id=scoped_project,
        user_id=payload.user_id,
        query=payload.query,
        request_id=payload.request_id,
        verdict=payload.verdict,
        issues=payload.issues,
        notes=payload.notes,
        provenance={
            **payload.provenance,
            "workspace_id": workspace_id,
            "project_id": payload.project_id,
        },
    )
    stored = runtime.feedback_repository.add_entry(entry)
    trace_id = runtime.telemetry.new_trace_id()
    runtime.telemetry.log_feedback(trace_id=trace_id, entry=stored)
    return stored


@app.get("/v1/feedback/recent", response_model=CognitiveFeedbackSearchResponse)
def recent_feedback(
    request: Request,
    workspace_id: str = Query(default="brasa_ai_workspace"),
    project_id: str = Query(...),
    user_id: str = Query(...),
    limit: int = Query(default=40, ge=1, le=500),
) -> CognitiveFeedbackSearchResponse:
    runtime = runtime_from(request)
    scoped_project = scoped_project_id(project_id=project_id, workspace_id=workspace_id)
    items = runtime.feedback_repository.list_recent(
        project_id=scoped_project,
        user_id=user_id,
        limit=limit,
    )
    return CognitiveFeedbackSearchResponse(items=items)


@app.get("/v1/memory/search", response_model=MemorySearchResponse)
def search_memory(
    request: Request,
    workspace_id: str = Query(default="brasa_ai_workspace"),
    project_id: str = Query(...),
    user_id: str = Query(...),
    query: str = Query(default=""),
    limit: int = Query(default=8, ge=1, le=50),
) -> MemorySearchResponse:
    runtime = runtime_from(request)
    scoped_project = scoped_project_id(project_id=project_id, workspace_id=workspace_id)
    items = runtime.memory_repository.search(
        project_id=scoped_project,
        user_id=user_id,
        query=query,
        limit=limit,
    )
    return MemorySearchResponse(items=items)


@app.post("/v1/conversations/sessions", response_model=ConversationSession)
def create_conversation_session(
    payload: ConversationSessionCreateRequest,
    request: Request,
) -> ConversationSession:
    runtime = runtime_from(request)
    payload = scope_conversation_session_create(payload)

    session = ConversationSession(
        workspace_id=payload.workspace_id,
        project_id=payload.project_id,
        user_id=payload.user_id,
        title=payload.title,
        metadata=payload.metadata,
    )
    return runtime.conversation_repository.create_session(session)


@app.get("/v1/conversations/sessions", response_model=ConversationSessionSearchResponse)
def list_conversation_sessions(
    request: Request,
    workspace_id: str = Query(default="brasa_ai_workspace"),
    project_id: str = Query(...),
    user_id: str = Query(...),
    limit: int = Query(default=40, ge=1, le=200),
) -> ConversationSessionSearchResponse:
    runtime = runtime_from(request)
    normalized_workspace = normalize_workspace_id(workspace_id)
    scoped_project = scoped_project_id(project_id=project_id, workspace_id=normalized_workspace)

    items = runtime.conversation_repository.list_sessions(
        project_id=scoped_project,
        user_id=user_id,
        limit=limit,
    )
    return ConversationSessionSearchResponse(items=items)


@app.get("/v1/conversations/{session_id}/messages", response_model=ConversationMessageSearchResponse)
def list_conversation_messages(
    session_id: str,
    request: Request,
    workspace_id: str = Query(default="brasa_ai_workspace"),
    project_id: str = Query(...),
    user_id: str = Query(...),
    limit: int = Query(default=300, ge=1, le=1000),
) -> ConversationMessageSearchResponse:
    runtime = runtime_from(request)
    normalized_workspace = normalize_workspace_id(workspace_id)
    scoped_project = scoped_project_id(project_id=project_id, workspace_id=normalized_workspace)

    session = runtime.conversation_repository.get_session(
        session_id=session_id,
        project_id=scoped_project,
        user_id=user_id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Conversation session not found.")

    items = runtime.conversation_repository.list_messages(
        session_id=session_id,
        project_id=scoped_project,
        user_id=user_id,
        limit=limit,
    )
    return ConversationMessageSearchResponse(items=items)


@app.post("/v1/conversations/{session_id}/send", response_model=ConversationSendResponse)
async def send_conversation_message(
    session_id: str,
    payload: ConversationSendRequest,
    request: Request,
) -> ConversationSendResponse:
    runtime = runtime_from(request)
    payload = scope_conversation_send(payload)

    session = runtime.conversation_repository.get_session(
        session_id=session_id,
        project_id=payload.project_id,
        user_id=payload.user_id,
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Conversation session not found.")

    user_message = runtime.conversation_repository.add_message(
        ConversationMessage(
            session_id=session_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            user_id=payload.user_id,
            role=ConversationMessageRole.USER,
            content=payload.prompt,
            metadata={
                **payload.metadata,
                "source": "conversation_api",
                "command": payload.command,
                "options": payload.options,
            },
        )
    )

    try:
        operation = await run_conversation_command(
            runtime=runtime,
            session_id=session_id,
            user_message=user_message,
            payload=payload,
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Conversation execution failed: {exc}") from exc

    task_response = operation.get("task")
    trace_id = str(operation.get("trace_id") or "").strip() or None
    request_id = str(operation.get("request_id") or "").strip() or None

    assistant_message = runtime.conversation_repository.add_message(
        ConversationMessage(
            session_id=session_id,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            user_id=payload.user_id,
            role=ConversationMessageRole.ASSISTANT,
            content=str(operation.get("answer") or ""),
            request_id=request_id,
            trace_id=trace_id,
            route=operation.get("route"),
            context_sources=list(operation.get("context_sources") or []),
            confidence=operation.get("confidence"),
            metadata={
                "source": "conversation_runtime",
                "operation": operation.get("operation"),
                "operation_result": operation.get("operation_result"),
            },
        )
    )

    updated_session = runtime.conversation_repository.get_session(
        session_id=session_id,
        project_id=payload.project_id,
        user_id=payload.user_id,
    )

    return ConversationSendResponse(
        session=updated_session or session,
        user_message=user_message,
        assistant_message=assistant_message,
        task=task_response,
        operation=str(operation.get("operation") or "chat"),
        operation_result=dict(operation.get("operation_result") or {}),
    )


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(payload: RequestEnvelope, request: Request) -> ChatResponse:
    runtime = runtime_from(request)
    payload = scope_envelope(payload)

    try:
        task_response, _ = await run_chat_task(runtime, payload)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Chat execution failed: {exc}") from exc

    return ChatResponse(
        request_id=payload.request_id,
        answer=task_response.answer,
        confidence=task_response.confidence,
        route=task_response.route,
        context_sources=task_response.context_sources,
        trace_id=task_response.trace_id,
    )


@app.post("/v1/tasks/execute", response_model=TaskResponse)
async def execute_task(payload: TaskRequest, request: Request) -> TaskResponse:
    runtime = runtime_from(request)
    payload = scope_task(payload)

    if not hasattr(runtime, "task_engine"):
        raise HTTPException(status_code=503, detail="Task engine is not available in this runtime.")

    try:
        task_response, _ = await runtime.task_engine.run(payload)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Task execution failed: {exc}") from exc

    return task_response


@app.post("/v1/actions/plan", response_model=ActionPlan)
def plan_actions(payload: ActionPlanRequest, request: Request) -> ActionPlan:
    runtime = runtime_from(request)
    payload = scope_action_plan(payload)

    if not hasattr(runtime, "action_engine"):
        raise HTTPException(status_code=503, detail="Action engine is not available in this runtime.")

    try:
        plan, _ = runtime.action_engine.plan(payload)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Action planning failed: {exc}") from exc

    return plan


@app.post("/v1/actions/execute", response_model=ActionExecutionReport)
def execute_actions(payload: ActionExecuteRequest, request: Request) -> ActionExecutionReport:
    runtime = runtime_from(request)
    payload = scope_action_execute(payload)

    if not hasattr(runtime, "action_engine"):
        raise HTTPException(status_code=503, detail="Action engine is not available in this runtime.")

    try:
        report = runtime.action_engine.execute(payload)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Action execution failed: {exc}") from exc

    if payload.options.run_feedback_loop and not payload.options.dry_run and report.applied > 0:
        report.feedback_notes = run_action_feedback_loop(
            runtime=runtime,
            workspace_id=payload.workspace_id,
            project_id=payload.project_id,
            user_id=payload.user_id,
            report=report,
        )

    return report


@app.post("/v1/actions/rollback", response_model=ActionRollbackReport)
def rollback_actions(payload: ActionRollbackRequest, request: Request) -> ActionRollbackReport:
    runtime = runtime_from(request)
    payload = scope_action_rollback(payload)

    if not hasattr(runtime, "action_engine"):
        raise HTTPException(status_code=503, detail="Action engine is not available in this runtime.")

    try:
        rollback_report = runtime.action_engine.rollback(payload)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Action rollback failed: {exc}") from exc

    if rollback_report.restored_files > 0 or rollback_report.removed_files > 0:
        runtime.memory_repository.add_entry(
            MemoryEntry(
                project_id=payload.project_id,
                user_id=payload.user_id,
                scope=MemoryScope.EPISODIC,
                content=(
                    f"Rollback executed for action execution {payload.execution_id}.\n"
                    f"Restored={rollback_report.restored_files}, Removed={rollback_report.removed_files}."
                ),
                tags=["action", "rollback", "auto"],
                confidence=0.75,
                provenance={
                    "workspace_id": payload.workspace_id,
                    "execution_id": payload.execution_id,
                },
            )
        )

    return rollback_report


@app.post("/v1/orchestrator/run", response_model=OrchestratorRunReport)
def run_orchestrator(payload: OrchestratorRunRequest, request: Request) -> OrchestratorRunReport:
    runtime = runtime_from(request)
    payload = scope_orchestrator(payload)

    if not hasattr(runtime, "orchestrator"):
        raise HTTPException(status_code=503, detail="Orchestrator is not available in this runtime.")

    try:
        report = runtime.orchestrator.run(payload)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Orchestrator execution failed: {exc}") from exc

    return report


@app.post("/v1/context/assemble", response_model=ContextAssembleResponse)
def context_assemble(payload: RequestEnvelope, request: Request) -> ContextAssembleResponse:
    runtime = runtime_from(request)
    payload = scope_envelope(payload)
    packet, retrieval = runtime.context_builder.build(payload)

    trace_id = runtime.telemetry.new_trace_id()
    runtime.telemetry.log_retrieval(
        trace_id=trace_id,
        envelope=payload,
        retrieval=retrieval,
    )

    return ContextAssembleResponse(packet=packet, retrieval=retrieval)


@app.post("/v1/reflection/run", response_model=ReflectionReport)
def run_reflection(
    request: Request,
    workspace_id: str = Query(default="brasa_ai_workspace"),
    project_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
) -> ReflectionReport:
    runtime = runtime_from(request)
    scoped_project = (
        scoped_project_id(project_id=project_id, workspace_id=workspace_id)
        if project_id is not None
        else None
    )
    return runtime.reflection.run_once(
        trigger="manual",
        project_id=scoped_project,
        user_id=user_id,
    )


@app.post("/v1/evaluation/run", response_model=EvaluationReport)
def run_evaluation(
    request: Request,
    payload: EvaluationRunRequest | None = Body(default=None),
) -> EvaluationReport:
    runtime = runtime_from(request)
    request_payload = payload or EvaluationRunRequest()
    scoped_project = (
        scoped_project_id(
            project_id=request_payload.project_id,
            workspace_id=request_payload.workspace_id,
        )
        if request_payload.project_id is not None
        else None
    )

    return runtime.evaluation_engine.run(
        limit=request_payload.limit,
        project_id=scoped_project,
        user_id=request_payload.user_id,
    )


@app.get("/v1/evaluation/recent")
def recent_evaluations(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, object]:
    runtime = runtime_from(request)
    items = runtime.evaluation_engine.read_recent(limit=limit)
    return {"items": items}


@app.post("/v1/calibration/diagnostics")
def run_calibration_diagnostics(
    request: Request,
    workspace_id: str = Query(default="brasa_ai_workspace"),
    project_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
) -> dict[str, object]:
    runtime = runtime_from(request)
    scoped_project = (
        scoped_project_id(project_id=project_id, workspace_id=workspace_id)
        if project_id is not None
        else None
    )
    return runtime.diagnostics_engine.run(project_id=scoped_project, user_id=user_id)


@app.post("/v1/knowledge/sync", response_model=KnowledgeSyncReport)
def knowledge_sync(
    request: Request,
    payload: KnowledgeSyncRequest | None = Body(default=None),
) -> KnowledgeSyncReport:
    runtime = runtime_from(request)
    request_payload = payload or KnowledgeSyncRequest()
    return runtime.knowledge_compiler.sync(
        force=request_payload.force,
        include_extensions=request_payload.include_extensions,
    )


@app.get("/v1/knowledge/tree", response_model=KnowledgeTreeResponse)
def knowledge_tree(request: Request) -> KnowledgeTreeResponse:
    runtime = runtime_from(request)
    return runtime.knowledge_compiler.tree()


@app.get("/v1/knowledge/search")
def knowledge_search(
    request: Request,
    query: str = Query(..., min_length=2),
    limit: int = Query(default=8, ge=1, le=20),
) -> dict[str, object]:
    runtime = runtime_from(request)
    nodes = runtime.knowledge_compiler.search(query=query, limit=limit)

    items = [
        KnowledgeNodeView(
            node_id=node.node_id,
            level=node.level,
            title=node.title,
            source_path=node.source_path,
            stale=node.stale,
            confidence=node.confidence,
            generation=node.generation,
            dependencies=node.dependencies,
            patterns=node.patterns,
            children=node.children,
            readme_path=node.readme_path,
            metadata_path=node.metadata_path,
        ).model_dump(mode="json")
        for node in nodes
    ]

    return {"items": items}


@app.post("/v1/ingestion/run", response_model=ProjectIngestionReport)
def run_project_ingestion(payload: ProjectIngestionRequest, request: Request) -> ProjectIngestionReport:
    runtime = runtime_from(request)
    project_path = Path(payload.project_path)
    workspace_id = normalize_workspace_id(payload.workspace_id)

    try:
        return runtime.ingestion_pipeline.run(
            project_path=project_path,
            force=payload.force,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/watcher/check", response_model=WatcherCheckReport)
def run_watcher_check(payload: WatcherCheckRequest, request: Request) -> WatcherCheckReport:
    runtime = runtime_from(request)
    project_path = Path(payload.project_path)
    workspace_id = normalize_workspace_id(payload.workspace_id)

    try:
        report = runtime.watcher_engine.check(
            project_path=project_path,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.auto_rebuild and report.changes_detected > 0:
        runtime.ingestion_pipeline.run(
            project_path=project_path,
            force=False,
            workspace_id=workspace_id,
        )
        notes = list(report.notes)
        notes.append("Incremental ingestion triggered by watcher.")
        report = report.model_copy(update={"rebuilt": True, "notes": notes})

    return report


@app.get("/v1/traces/recent")
def recent_traces(request: Request, limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
    runtime = runtime_from(request)
    items = runtime.telemetry.read_recent(limit=limit)
    return {"items": items}

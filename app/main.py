from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request

from app.calibration import CognitiveDiagnosticsEngine
from app.context_builder import ContextBuilder
from app.contracts import (
    ChatResponse,
    CognitiveFeedbackCreateRequest,
    CognitiveFeedbackEntry,
    CognitiveFeedbackSearchResponse,
    ContextAssembleResponse,
    EvaluationReport,
    EvaluationRunRequest,
    MemoryCreateRequest,
    MemoryEntry,
    MemoryScope,
    MemorySearchResponse,
    ReflectionReport,
    RequestEnvelope,
    TaskRequest,
    TaskResponse,
    TaskType,
    WatcherCheckReport,
    WatcherCheckRequest,
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
from app.providers import AlibabaAdapter, AlibabaEmbeddingAdapter, LocalAdapter
from app.query_engine import CognitiveQueryEngine
from app.reflection.nightly_reflection import ReflectionService
from app.router import AIRouter
from app.settings import Settings, get_settings
from app.task_engine import CognitiveTaskEngine
from app.telemetry.tracing import TraceLogger
from app.watcher import FileSystemWatcherEngine
from app.workspace import normalize_workspace_id, scoped_project_id


@dataclass
class RuntimeContainer:
    settings: Settings
    memory_repository: MemoryRepository
    feedback_repository: CognitiveFeedbackRepository
    knowledge_compiler: KnowledgeCompiler
    ingestion_pipeline: ProjectIngestionPipeline
    watcher_engine: FileSystemWatcherEngine
    context_builder: ContextBuilder
    router: AIRouter
    query_engine: CognitiveQueryEngine
    task_engine: CognitiveTaskEngine
    reflection: ReflectionService
    evaluation_engine: EvaluationEngine
    telemetry: TraceLogger
    diagnostics_engine: CognitiveDiagnosticsEngine


def build_runtime(settings: Settings) -> RuntimeContainer:
    memory_repository = MemoryRepository(settings.sqlite_path)
    feedback_repository = CognitiveFeedbackRepository(settings.sqlite_path)

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

    context_builder = ContextBuilder(
        memory_repository=memory_repository,
        knowledge_compiler=knowledge_compiler,
        project_artifacts_root=settings.data_dir.parent / ".brasa",
        embedding_client=embedding_client,
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
    router = AIRouter(
        settings=settings,
        local_provider=local_provider,
        alibaba_provider=alibaba_provider,
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

    return RuntimeContainer(
        settings=settings,
        memory_repository=memory_repository,
        feedback_repository=feedback_repository,
        knowledge_compiler=knowledge_compiler,
        ingestion_pipeline=ingestion_pipeline,
        watcher_engine=watcher_engine,
        context_builder=context_builder,
        router=router,
        query_engine=query_engine,
        task_engine=task_engine,
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


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(payload: RequestEnvelope, request: Request) -> ChatResponse:
    runtime = runtime_from(request)
    payload = scope_envelope(payload)

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

        try:
            task_response, _ = await runtime.task_engine.run(task_request)
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

    try:
        chat_response, _ = await runtime.query_engine.run(payload)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Chat execution failed: {exc}") from exc

    return chat_response


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

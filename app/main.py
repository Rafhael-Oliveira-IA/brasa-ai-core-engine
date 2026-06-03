from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request

from app.context_builder import ContextBuilder
from app.contracts import (
    ChatResponse,
    ContextAssembleResponse,
    MemoryCreateRequest,
    MemoryEntry,
    MemoryScope,
    MemorySearchResponse,
    ReflectionReport,
    RequestEnvelope,
    WatcherCheckReport,
    WatcherCheckRequest,
)
from app.ingestion import ProjectIngestionPipeline, ProjectIngestionReport, ProjectIngestionRequest
from app.knowledge import (
    KnowledgeCompiler,
    KnowledgeNodeView,
    KnowledgeSyncReport,
    KnowledgeSyncRequest,
    KnowledgeTreeResponse,
)
from app.memory.repository import MemoryRepository
from app.providers import AlibabaAdapter, LocalAdapter
from app.query_engine import CognitiveQueryEngine
from app.reflection.nightly_reflection import ReflectionService
from app.router import AIRouter
from app.settings import Settings, get_settings
from app.telemetry.tracing import TraceLogger
from app.watcher import FileSystemWatcherEngine


@dataclass
class RuntimeContainer:
    settings: Settings
    memory_repository: MemoryRepository
    knowledge_compiler: KnowledgeCompiler
    ingestion_pipeline: ProjectIngestionPipeline
    watcher_engine: FileSystemWatcherEngine
    context_builder: ContextBuilder
    router: AIRouter
    query_engine: CognitiveQueryEngine
    reflection: ReflectionService
    telemetry: TraceLogger


def build_runtime(settings: Settings) -> RuntimeContainer:
    memory_repository = MemoryRepository(settings.sqlite_path)

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
        output_projects_root=settings.data_dir.parent / ".brasa" / "projects",
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

    context_builder = ContextBuilder(
        memory_repository=memory_repository,
        knowledge_compiler=knowledge_compiler,
        project_artifacts_root=settings.data_dir.parent / ".brasa" / "projects",
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

    reflection = ReflectionService(
        repository=memory_repository,
        report_dir=settings.reflection_dir,
        knowledge_compiler=knowledge_compiler,
    )
    telemetry = TraceLogger(file_path=settings.trace_file)
    query_engine = CognitiveQueryEngine(
        context_builder=context_builder,
        router=router,
        telemetry=telemetry,
        memory_repository=memory_repository,
    )

    return RuntimeContainer(
        settings=settings,
        memory_repository=memory_repository,
        knowledge_compiler=knowledge_compiler,
        ingestion_pipeline=ingestion_pipeline,
        watcher_engine=watcher_engine,
        context_builder=context_builder,
        router=router,
        query_engine=query_engine,
        reflection=reflection,
        telemetry=telemetry,
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

    entry = MemoryEntry(
        project_id=payload.project_id,
        user_id=payload.user_id,
        scope=payload.scope,
        content=payload.content,
        tags=payload.tags,
        confidence=payload.confidence,
        provenance=payload.provenance,
    )

    return runtime.memory_repository.add_entry(entry)


@app.get("/v1/memory/search", response_model=MemorySearchResponse)
def search_memory(
    request: Request,
    project_id: str = Query(...),
    user_id: str = Query(...),
    query: str = Query(default=""),
    limit: int = Query(default=8, ge=1, le=50),
) -> MemorySearchResponse:
    runtime = runtime_from(request)
    items = runtime.memory_repository.search(
        project_id=project_id,
        user_id=user_id,
        query=query,
        limit=limit,
    )
    return MemorySearchResponse(items=items)


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(payload: RequestEnvelope, request: Request) -> ChatResponse:
    runtime = runtime_from(request)

    try:
        chat_response, _ = await runtime.query_engine.run(payload)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Chat execution failed: {exc}") from exc

    return chat_response


@app.post("/v1/context/assemble", response_model=ContextAssembleResponse)
def context_assemble(payload: RequestEnvelope, request: Request) -> ContextAssembleResponse:
    runtime = runtime_from(request)
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
    project_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
) -> ReflectionReport:
    runtime = runtime_from(request)
    return runtime.reflection.run_once(
        trigger="manual",
        project_id=project_id,
        user_id=user_id,
    )


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

    try:
        return runtime.ingestion_pipeline.run(
            project_path=project_path,
            force=payload.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/watcher/check", response_model=WatcherCheckReport)
def run_watcher_check(payload: WatcherCheckRequest, request: Request) -> WatcherCheckReport:
    runtime = runtime_from(request)
    project_path = Path(payload.project_path)

    try:
        report = runtime.watcher_engine.check(project_path=project_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.auto_rebuild and report.changes_detected > 0:
        runtime.ingestion_pipeline.run(project_path=project_path, force=False)
        notes = list(report.notes)
        notes.append("Incremental ingestion triggered by watcher.")
        report = report.model_copy(update={"rebuilt": True, "notes": notes})

    return report


@app.get("/v1/traces/recent")
def recent_traces(request: Request, limit: int = Query(default=20, ge=1, le=200)) -> dict[str, object]:
    runtime = runtime_from(request)
    items = runtime.telemetry.read_recent(limit=limit)
    return {"items": items}

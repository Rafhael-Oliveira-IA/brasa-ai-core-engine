# BRASA Cognitive Runtime

Persistent cognitive runtime for long-lived game codebases.

BRASA combines hierarchical project knowledge, hybrid retrieval, model routing, action planning/execution, and feedback-driven calibration into one operational runtime.

## Project Evolution (Key PRs)

Use these PRs as historical anchors when starting a new AI chat or reviewing architecture decisions.

- [Cognitive Runtime Update (PR #1)](https://github.com/Rafhael-Oliveira-IA/brasa-ai-core-engine/pull/1)
  - baseline cognitive runtime foundation
  - initial integration between retrieval, routing, and persistent operation
- [Reflection + Cognitive Calibration + Agent System + Better UI (PR #2)](https://github.com/Rafhael-Oliveira-IA/brasa-ai-core-engine/pull/2)
  - reflection and calibration quality loop improvements
  - agent system and usability/workbench evolution
- [Cognitive Distributed Runtime (PR #4)](https://github.com/Rafhael-Oliveira-IA/brasa-ai-core-engine/pull/4)
  - distributed cognition direction and runtime specialization strategy
  - stronger separation between local deterministic layers and cloud reasoning layers
- [Phase 5.5 — Cognitive Workspace Foundation (PR #5)](https://github.com/Rafhael-Oliveira-IA/brasa-ai-core-engine/pull/5)
  - session-based Cognitive Studio conversation workflow (IDE-like explorer + editor + chat thread)
  - workspace/project-scoped artifact explorer and file reading endpoints
  - manual and one-click ingestion flow for project contextualization per workspace

<img width="519" height="894" alt="image" src="https://github.com/user-attachments/assets/70b6f4af-32e3-4ad6-9ddf-e1c09467cc55" />
<img width="697" height="699" alt="image" src="https://github.com/user-attachments/assets/db4fffb2-134d-4b20-90b7-38e860b80de5" />
<img width="1201" height="753" alt="image" src="https://github.com/user-attachments/assets/c03ee921-127b-4df4-9b1f-cde7a23cbfe6" />
<img width="887" height="716" alt="image" src="https://github.com/user-attachments/assets/a252f537-bdc7-483b-b655-3bc0354d40c8" />

## What BRASA Solves

Large game projects usually suffer from:

- fragmented architectural knowledge
- stale documentation
- context loss across sessions
- high onboarding friction
- weak traceability between reasoning and real code

BRASA addresses this by treating your repository as a cognitive system, not just plain text.

## Architecture Overview

```txt
FILES
 ↓
FILE KNOWLEDGE
 ↓
FOLDER KNOWLEDGE
 ↓
MODULE KNOWLEDGE
 ↓
PROJECT KNOWLEDGE
 ↓
GLOBAL MEMORY
 ↓
REFLECTION
 ↓
KNOWLEDGE REPAIR
```

## Architecture Decision Records

- [ADR-0001: Cognitive Distributed Runtime Roadmap](docs/adr/ADR-0001-cognitive-distributed-runtime-roadmap.md)

## Runtime Layers

### 1. Ingestion Engine

Builds project artifacts incrementally from source code.

Core capabilities:

- file scanning and hashing
- change detection (create/modify/delete/rename)
- incremental rebuild
- watcher-triggered rebuilds

### 2. Knowledge Compiler

Compiles source structure into hierarchical, searchable artifacts.

Outputs include:

- summaries per file/folder/module/project
- metadata per file (symbols, dependencies, confidence)
- persistent state for stale drift detection

### 3. Hybrid Retrieval Engine

Assembles context packets from multiple sources:

- artifact summaries/metadata
- memory entries
- knowledge graph expansion
- optional semantic scoring via Alibaba embeddings

Retrieval also provides:

- compression diagnostics
- risk signals (stale context, dropped candidates, xml gaps)
- relevant systems and dependency sets

### 4. Routing + Providers

Routing chooses model tier by intent, context shape, confidence gates, and budget:

- `local`
- `flash`
- `plus`
- `max`

Provider stack:

- local provider (fast fallback/assist)
- Alibaba provider (Qwen via compatible OpenAI API)

### 5. Query and Task Engines

Two execution paths for language outputs:

- query engine (`/v1/chat` fallback path)
- task engine (`/v1/tasks/execute`, chat included)

Both paths include retrieval, route logging, memory update, and tracing.

### 6. Action Engine

Structured file operations with validation and rollback safety:

- create/update/patch/delete actions
- path policy validation
- file size guards
- backup + rollback
- optional model-assisted action planning

### 7. Orchestrator (Auto-Agent Loop)

Coordinates planning/execution iterations with explicit guardrails:

- manual or autopilot modes
- risk-aware execution policy
- optional reflection/evaluation pass
- per-iteration reporting

### 8. Evaluation, Calibration, Reflection

Operational quality loops:

- evaluation reports from traces
- calibration diagnostics/failure buckets
- reflection runs (manual/scheduled)

## Chat Reliability Features

### Grounded Chat Policy

For chat responses:

- final response is forced through Alibaba
- local retrieval and local draft are still used as guidance
- prompt contract emphasizes confirmed evidence vs hypotheses
- prompt contract forbids invented formulas/constants when evidence is missing

### Auto-Reingest on Weak Context

When chat context quality is weak, runtime can trigger `knowledge_compiler.sync()` automatically before re-assembling context.

Retrieval payload includes `auto_reingest` diagnostics:

- whether reingest triggered
- trigger reason
- sync status and counters

### Optional Low-Cost Cloud Retrieval Assist

BRASA can optionally run a low-cost Alibaba assist pass during retrieval to avoid over-reliance on hardcoded heuristics.

When enabled, the assist pass can:

- classify retrieval intent cheaply
- suggest priority candidate sources
- suggest short lexical hint terms for reranking

The runtime remains deterministic and safe when the assist model is unavailable:

- retrieval falls back to local heuristic + graph + semantic flow
- no endpoint failure is introduced by assist unavailability

## Cognitive Distributed Runtime (Target Architecture)

BRASA should not evolve into a "local does everything, cloud only answers" architecture.

That model scales poorly for long-lived cognitive systems.

The target is a distributed cognition runtime where each layer has a specialized responsibility and cost profile.

### Local Runtime Responsibilities

Local infrastructure should remain responsible for deterministic, high-frequency, low-cost operations:

- scanning and hashing
- file watching and incremental change detection
- AST/index pipelines
- cache and queue management
- lightweight retrieval and reranking prefilters
- hot/episodic memory assembly
- context compression pre-pass
- fast local drafts
- offline fallback behavior

### Alibaba Cloud Responsibilities

Cloud layers should be dedicated to high-value cognition:

- deep reasoning over architecture and system interactions
- code planning and patch strategy synthesis
- long-context analysis windows
- reflection and critique passes
- semantic synthesis over multi-source evidence

## Specialized Model Routing (Next Stage)

Current tier routing (`flash`, `plus`, `max`) is a good baseline, but long-term quality requires role-specialized routing.

Target routing roles:

- intent/classification model
- coding model
- long-context architecture model
- planning model
- reflection/critic model
- embedding model
- compression/summarization model
- repair model
- verification model

Example decision flow:

1. Intent classifier detects request shape and risk.
2. Task router selects the most appropriate model role.
3. Execution path applies role-specific prompts and constraints.
4. Critic/verifier layers score output quality before persistence.

## Dynamic Cognitive Windows

For MMO and large live-service architectures, retrieval should support dynamic context windows, not only small fixed packets.

Temporary windows can include full subsystem slices such as:

- combat architecture
- inventory architecture
- networking/packet/opcode pipelines
- startup XML/Lua registration chains

This enables architecture-level reasoning in a single cognitive session when required.

## Reflection Model Strategy

Reflection should be split into two cost bands:

### Cheap Reflection Pass (frequent)

- stale knowledge detection
- dependency drift
- missing/broken references
- context quality anomalies

### Deep Reflection Pass (scheduled)

- design inconsistency analysis
- duplication and coupling risks
- scaling bottlenecks
- structural modernization opportunities

## Multi-Embedding Strategy

A single embedding strategy is useful for bootstrap, but retrieval quality improves with specialization:

- code embeddings (C++, Lua, C#, XML, TS)
- architecture embeddings (summaries, modules, ADR-like artifacts)
- episodic embeddings (traces, failures, patches, reflection outcomes)

This creates better semantic separation between implementation facts, architecture intent, and operational memory.

## Cognitive Compression Pipeline

Compression should become recursive and role-aware:

```txt
FILES
 ↓
MICRO SUMMARIES
 ↓
SYSTEM SUMMARIES
 ↓
ARCHITECTURE SUMMARIES
 ↓
GLOBAL COGNITION
```

Different compression stages can use different model roles and confidence policies.

## Autonomous Evaluation Cluster (Cognitive CI/CD)

The evaluation path can evolve from a single report endpoint to a multi-role quality chain:

1. Executor model performs action plan.
2. Critic model scores risk and side effects.
3. Verifier model validates patch/results against intent.
4. Reflection model updates memory and calibration hints.

This forms a cognitive CI/CD loop for safer autonomous changes.

## Tiered Runtime Blueprint

### Tier 0 (Local)

- indexing, watchers, cache, base retrieval, AST, fallback

### Tier 1 (Cheap Cloud)

- intent detection, tagging, reranking, lightweight summaries

### Tier 2 (Mid Cloud)

- coding, retrieval synthesis, architecture understanding, medium plans

### Tier 3 (Heavy Reasoning)

- orchestrator cognition, deep architecture reasoning, large context windows, reflection and redesign

## Phase 6 Execution Priorities

To implement this architecture safely, prioritize in order:

1. role-based router contracts (classifier/planner/coder/critic/verifier)
2. dynamic context window policy by intent and risk
3. dual-pass reflection scheduler (cheap + deep)
4. multi-embedding indexes with explicit store separation
5. evaluator chain integration into orchestrator/action feedback loops

This path prevents the common anti-pattern of relying on one giant model for every cognitive task.

## Repository Structure

```txt
AlibabaProject/
├── app/                        # FastAPI runtime and cognitive engines
├── app-front/                  # React + Vite workbench UI
├── data/                       # runtime db, traces, reports
├── docs/                       # ADR and documentation artifacts
├── tests/                      # pytest suite
├── tools/                      # utility and E2E scripts
├── run-all-services.bat        # starts backend + frontend on Windows
└── requirements.txt
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- npm

### 1) Backend

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

### 2) Frontend

```bash
cd app-front
npm install
npm run dev
```

Frontend default URL: `http://127.0.0.1:5173`

### 3) One-Command Start (Windows)

```bat
run-all-services.bat
```

This starts:

- backend on `http://127.0.0.1:8000`
- frontend on `http://127.0.0.1:5173`

## Configuration (Environment Variables)

`Settings` are loaded from `.env` via `pydantic-settings`.

Key variables:

- `ALIBABA_API_KEY`
- `ALIBABA_BASE_URL`
- `ALIBABA_MODEL_FLASH`
- `ALIBABA_MODEL_PLUS`
- `ALIBABA_MODEL_MAX`
- `ALIBABA_EMBEDDING_ENABLED`
- `REQUEST_BUDGET_USD`
- `MAX_ESCALATION_DEPTH`
- `CHAT_FORCE_ALIBABA_RESPONSE`
- `CHAT_FORCE_ALIBABA_IGNORE_BUDGET`
- `CHAT_CONTEXT_MAX_CHARS`
- `CHAT_QWEN_MULTI_MODEL_ENABLED`
- `CHAT_QWEN_CLASSIFICATION_ENABLED`
- `CHAT_QWEN_VERIFIER_ENABLED`
- `CHAT_QWEN_REPAIR_ENABLED`
- `CHAT_QWEN_VERIFIER_MIN_CONFIDENCE`
- `CHAT_LOCAL_ASSIST_ENABLED`
- `CHAT_LOCAL_ASSIST_MAX_CHARS`
- `CHAT_AUTO_REINGEST_ON_WEAK_CONTEXT`
- `CHAT_AUTO_REINGEST_MIN_SELECTED_CONTEXT`
- `CHAT_AUTO_REINGEST_COOLDOWN_SECONDS`
- `RETRIEVAL_CLOUD_ASSIST_ENABLED`
- `RETRIEVAL_CLOUD_ASSIST_MODEL`
- `RETRIEVAL_CLOUD_ASSIST_MIN_CANDIDATES`
- `RETRIEVAL_CLOUD_ASSIST_TIMEOUT_SECONDS`
- `ACTION_MODEL_ASSIST_ENABLED`
- `ACTION_MODEL_ASSIST_TIER`
- `ACTION_BLOCKED_PATHS`
- `ACTION_ALLOW_DELETE`

## API Surface

### Runtime and Context

- `GET /health`
- `POST /v1/context/assemble`
- `GET /v1/traces/recent`
- `GET /v1/workspace/file`

### Cognitive Studio Conversation

- `POST /v1/conversations/sessions`
- `GET /v1/conversations/sessions`
- `GET /v1/conversations/{session_id}/messages`
- `POST /v1/conversations/{session_id}/send`
- `GET /v1/project/artifacts/tree`
- `GET /v1/project/artifacts/file`

### Chat and Tasks

- `POST /v1/chat`
- `POST /v1/tasks/execute`

### Action and Auto-Agent

- `POST /v1/actions/plan`
- `POST /v1/actions/execute`
- `POST /v1/actions/rollback`
- `POST /v1/orchestrator/run`

### Memory and Feedback

- `POST /v1/memory`
- `GET /v1/memory/search`
- `POST /v1/feedback`
- `GET /v1/feedback/recent`

### Knowledge, Ingestion, Watcher

- `POST /v1/knowledge/sync`
- `GET /v1/knowledge/tree`
- `GET /v1/knowledge/search`
- `POST /v1/ingestion/run`
- `POST /v1/watcher/check`

### Evaluation, Calibration, Reflection

- `POST /v1/evaluation/run`
- `GET /v1/evaluation/recent`
- `POST /v1/calibration/diagnostics`
- `POST /v1/reflection/run`

## Example Requests

### Chat

```json
{
  "workspace_id": "mmo_workspace",
  "project_id": "SERVIDOR - ORIGINAL",
  "user_id": "cognitive-user",
  "prompt": "Explain the capture flow and list uncertain points.",
  "metadata": {
    "source": "manual-test"
  }
}
```

### Action Plan

```json
{
  "workspace_id": "mmo_workspace",
  "project_id": "SERVIDOR - ORIGINAL",
  "user_id": "cognitive-user",
  "prompt": "Apply a minimal safe patch to increase catch rate by +2",
  "max_actions": 8
}
```

### Orchestrator Run

```json
{
  "workspace_id": "mmo_workspace",
  "project_id": "SERVIDOR - ORIGINAL",
  "user_id": "cognitive-user",
  "intent": "Increase catch rate by +2 with a minimal safe patch",
  "mode": "manual",
  "max_iterations": 1,
  "dry_run": false,
  "auto_execute_low_risk": true,
  "auto_execute_medium_risk": false,
  "allow_high_risk": false,
  "block_critical_risk": true,
  "run_reflection": false
}
```

## Workbench UI

The frontend provides two operational views:

- **Cognitive Studio Conversation**: IDE-like workspace explorer + project files + session-specific chat thread + command-driven runtime operations
- **Action + Auto-Agent Runtime**: plan/execution/rollback/orchestrator loops with guardrails

## Testing and Validation

### Backend tests

```bash
python -m pytest -q
```

### Frontend build validation

```bash
cd app-front
npm run build
```

### Cognitive usage dataset runner

```bash
python tools/run_cognitive_usage_phase.py
```

### Action + orchestrator E2E sample

```bash
python tools/test_orchestrator_execute_catch_rate.py
```

This script performs:

1. `POST /v1/orchestrator/run`
2. `POST /v1/actions/execute`
3. prints execution summary with validation/issues/changed files

## Operational Notes

- Workspace/project IDs are scoped internally (`workspace::project`) to isolate runtime state.
- Action execution enforces blocked paths and validation before writing files.
- Use rollback endpoint after risky operations or test runs.
- If project artifacts are stale, run `POST /v1/knowledge/sync` before heavy reasoning sessions.
- For project-scoped context quality (MMO XML/Lua rules, runtime repo, etc.), run `POST /v1/ingestion/run` with the real `project_path` for the selected workspace.
- Cognitive Studio can then use project-scoped artifact endpoints (`/v1/project/artifacts/tree`, `/v1/project/artifacts/file`) to keep Explorer/Editor aligned with the selected workspace/project.

## AI Handoff (Quick Start For Next Chat)

Use this when starting a new AI session and you need the assistant to be productive quickly.

### 1) Verify runtime in < 30 seconds

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/health"
```

If down, run:

```bat
run-all-services.bat
```

### 2) Verify context quality before asking for patches

```powershell
$body = @{workspace_id='mmo_workspace'; project_id='SERVIDOR - ORIGINAL'; user_id='cognitive-user'; prompt='quais os loots do arcanine ?'} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/context/assemble" -ContentType "application/json" -Body $body
```

Expected for this prompt:

- `artifact:file:data/monster/kanto/arcanine.lua` should appear near top context sources.
- snippet content should include a `LootEvidence[...]` block with concrete `pokemon.loot` rows.

For workspace/project-scoped runs, ensure the project is ingested first:

```powershell
$ingest = @{workspace_id='mmo_workspace'; project_path='F:/POKECONTEST/SERVIDOR - ORIGINAL'; force=$false} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/v1/ingestion/run" -ContentType "application/json" -Body $ingest
```

### 3) Current chat stack behavior (important)

- Chat uses Alibaba final response policy.
- Chat supports Qwen multi-model pipeline (classification -> generation -> verifier -> repair), with safe fallback when classifier/verifier is unavailable.
- Route tier/cost now reflects effective model family from resolved `model_name` (flash/plus/max), not only initial tier heuristic.
- Chat retrieval budget is configurable via `CHAT_CONTEXT_MAX_CHARS` (default currently expanded for richer context windows).

### 4) Retrieval safeguards already in place

- Loot queries prioritize monster artifacts in `data/monster` and `data/monsters` (including `.lua`).
- Short stopwords are filtered in intent terms to reduce noisy relevance spikes.
- Stale episodic "no evidence" chat memories are downweighted for code/loot factual queries.
- Alibaba provider consumes all selected context snippets from `ContextPacket` (no hard small cap).

### 5) Regression commands used for this runtime

```bash
python -m pytest tests/test_routing.py tests/test_retrieval_engine.py tests/test_retrieval_noise_filtering.py tests/test_alibaba_provider_runtime.py tests/test_main_runtime_bootstrap.py -q
```

### 6) Memory files for future chats

Repository notes live in:

- `memories/repo/retrieval-chat-lessons.md`

Use this file as the first reference when a new AI chat starts and behavior regresses.

## Built For

- MMO and OTServ/TFS ecosystems
- Unity/gameplay-heavy repositories
- long-lived, multi-system projects needing persistent architectural memory

## Vision

BRASA is designed to evolve from a runtime assistant into a persistent studio cognition layer:

- architecture-aware memory
- measurable retrieval quality
- safer autonomous change planning
- continuous feedback-driven improvement
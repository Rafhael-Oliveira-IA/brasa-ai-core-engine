# BRASA Cognitive Runtime

Persistent cognitive runtime for long-lived game codebases.

BRASA combines hierarchical project knowledge, hybrid retrieval, model routing, action planning/execution, and feedback-driven calibration into one operational runtime.

Cognitive Runtime Update
https://github.com/Rafhael-Oliveira-IA/brasa-ai-core-engine/pull/1

Reflection & Cognitive Calibration & Agent System + Better UI Update
https://github.com/Rafhael-Oliveira-IA/brasa-ai-core-engine/pull/2

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
- `CHAT_LOCAL_ASSIST_ENABLED`
- `CHAT_LOCAL_ASSIST_MAX_CHARS`
- `CHAT_AUTO_REINGEST_ON_WEAK_CONTEXT`
- `CHAT_AUTO_REINGEST_MIN_SELECTED_CONTEXT`
- `CHAT_AUTO_REINGEST_COOLDOWN_SECONDS`
- `ACTION_MODEL_ASSIST_ENABLED`
- `ACTION_MODEL_ASSIST_TIER`
- `ACTION_BLOCKED_PATHS`
- `ACTION_ALLOW_DELETE`

## API Surface

### Runtime and Context

- `GET /health`
- `POST /v1/context/assemble`
- `GET /v1/traces/recent`

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

- **Chat Runtime**: context packet, grounded routing, diagnostics, traces, feedback
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
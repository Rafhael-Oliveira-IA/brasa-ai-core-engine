# Brasa AI Core Lite

Implementacao local-first para rodar rapido, com evolucao incremental e auditavel.

## Objetivo

- Entregar uma base funcional sem bancos complexos.
- Manter arquitetura pronta para evoluir por camadas.
- Introduzir conhecimento hierarquico para evitar context drift.

## Stack atual

- FastAPI para orquestracao.
- SQLite para memoria persistente local.
- Telemetria em JSONL.
- Provider local sempre disponivel.
- Adapter Alibaba OpenAI-compatible opcional.
- Compilador cognitivo hierarquico incremental.

## Workspace Isolation

Workspaces suportados por padrao:

- `mmo_workspace`
- `unity_workspace`
- `brasa_ai_workspace`

Isolamento aplicado em:

- ingestion artifacts
- retrieval context
- watcher snapshots
- memory scoping (via `workspace_id::project_id`)

Layout de artefatos isolados:

- `.brasa/workspaces/<workspace>/<project>/raw`
- `.brasa/workspaces/<workspace>/<project>/summaries`
- `.brasa/workspaces/<workspace>/<project>/memories`
- `.brasa/workspaces/<workspace>/<project>/graphs`
- `.brasa/workspaces/<workspace>/<project>/contexts`
- `.brasa/workspaces/<workspace>/<project>/metadata`

## Context Compression Hierarquico

Fluxo de compilacao:

- file knowledge
- folder knowledge
- module knowledge
- project knowledge
- global project memory

Cada node possui:

- resumo humano em Markdown
- metadata estruturada em JSON
- `source_hash`, `generation`, `confidence`, `stale`, `file_versions`

Quando um arquivo muda, apenas o subgrafo necessario e regenerado.

## Setup rapido

1. Crie e ative um ambiente virtual.
2. Instale dependencias:

```bash
pip install -r requirements.txt
```

3. Copie `.env.example` para `.env`.
4. Se quiser Alibaba, preencha `ALIBABA_API_KEY`.
5. Execute:

```bash
uvicorn app.main:app --reload
```

## Endpoints principais

- `GET /health`
- `POST /v1/chat`
- `POST /v1/tasks/execute`
- `POST /v1/memory`
- `GET /v1/memory/search`
- `POST /v1/reflection/run`
- `POST /v1/knowledge/sync`
- `GET /v1/knowledge/tree`
- `GET /v1/knowledge/search?query=...`
- `POST /v1/ingestion/run`
- `POST /v1/context/assemble`
- `POST /v1/watcher/check`
- `POST /v1/evaluation/run`
- `GET /v1/evaluation/recent`

Observacao: endpoints cognitivos aceitam `workspace_id` no payload (default `brasa_ai_workspace`).

## Artefatos gerados

- `data/knowledge/files/...` (README + metadata por arquivo)
- `data/knowledge/folders/...`
- `data/knowledge/modules/...`
- `data/knowledge/project/PROJECT_KNOWLEDGE.md`
- `data/knowledge/global/GLOBAL_MEMORY.md`
- `data/knowledge/state.json`

## Project Ingestion MVP

Entrada:

- caminho do projeto, ex: `D:/Projects/MMO`

Saida:

- `.brasa/projects/MMO/`
	- `raw/`
	- `summaries/`
	- `memories/`
	- `graphs/`
	- `contexts/`
	- `metadata/`

Exemplo de execucao via API:

```bash
curl -X POST http://127.0.0.1:8000/v1/ingestion/run \
	-H "Content-Type: application/json" \
	-d '{"workspace_id":"mmo_workspace","project_path":"D:/Projects/MMO","force":false}'
```

## Context Retrieval Engine

`POST /v1/context/assemble` monta pacote contextual com:

- intent da consulta
- sistemas relevantes
- expansao de dependencias
- riscos e compressao por budget

Retrieval hibrido atual:

- lexical relevance
- Alibaba embeddings (`text-embedding-v4`)
- graph expansion
- freshness/confidence/importance weighting

Quando `ALIBABA_API_KEY` esta configurada, o runtime usa embeddings Alibaba com cache local para melhorar ranking semantico.

## Cognitive Task Runtime (Phase 3 bootstrap)

`POST /v1/tasks/execute` executa tarefas cognitivas tipadas com pipeline observavel.

Tipos iniciais:

- `chat`
- `summarize`
- `reasoning`
- `reflection`
- `repair`
- `planning`
- `architecture`
- `debugging`
- `generation`

Pipeline atual (runtime local):

- intent analysis
- context retrieval
- graph expansion
- reasoning (router + provider)
- memory update
- optional reflection

`POST /v1/chat` continua disponivel para compatibilidade e agora funciona como wrapper para `task_type=chat` quando o task runtime esta habilitado.

## Watcher Incremental

`POST /v1/watcher/check` detecta mudancas de filesystem e pode acionar rebuild incremental automaticamente.

## Provider + Reasoning Layer (Phase 2.5)

Pipeline cognitivo atualizado:

```text
FILES -> LOCAL INGESTION -> LOCAL KNOWLEDGE -> LOCAL RETRIEVAL -> CONTEXT ASSEMBLY -> ALIBABA/QWEN -> REASONING
```

Implementado no runtime:

- Cognitive Query Engine: retrieval + assembly + model routing + response
- Alibaba Provider Runtime: retries, region fallback, streaming interface, token accounting, cost estimation
- Cost-aware routing policy: escolhe tier com base em intent/contexto e budget

Configuracoes novas no `.env` (opcionais):

```bash
ALIBABA_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
ALIBABA_REGION_BASE_URLS=
ALIBABA_MAX_RETRIES=2
ALIBABA_RETRY_BACKOFF_SECONDS=0.35
ALIBABA_EMBEDDING_ENABLED=true
ALIBABA_EMBEDDING_MODEL=text-embedding-v4
ALIBABA_EMBEDDING_TIMEOUT_SECONDS=25
ALIBABA_EMBEDDING_MAX_BATCH_SIZE=16
```

Observacao: `ALIBABA_REGION_BASE_URLS` aceita uma lista separada por virgula para fallback de regiao.

## Evaluation Engine

`POST /v1/evaluation/run` calcula metricas operacionais a partir de traces do runtime:

- retrieval precision
- hallucination rate (proxy)
- stale context rate
- architectural consistency
- token efficiency
- reasoning success

`GET /v1/evaluation/recent` retorna os relatarios de avaliacao mais recentes.

## Golden Cognitive Tests

Benchmark cognitivo inicial implementado em:

- `tests/golden/golden_cognitive_cases.json` (20 queries)
- `tests/test_golden_cognitive_benchmark.py`

Cada caso define:

- expected systems
- expected files
- expected dependencies
- expected concepts

Metricas validadas no benchmark:

- file precision
- file recall
- dependency recall
- system hit rate
- concept hit rate

Execucao:

```bash
python -m pytest -q tests/test_golden_cognitive_benchmark.py
```

Esse benchmark marca o inicio da fase cientifica: calibrar retrieval/context/reasoning/evaluation antes de adicionar novas features.

## Evolucao recomendada

1. Substituir retrieval lexical por vetor local.
2. Adicionar parser AST por linguagem para aumentar confidence.
3. Integrar policy de aprovacao humana para rotas Ultra.

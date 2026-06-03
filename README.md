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
- `POST /v1/memory`
- `GET /v1/memory/search`
- `POST /v1/reflection/run`
- `POST /v1/knowledge/sync`
- `GET /v1/knowledge/tree`
- `GET /v1/knowledge/search?query=...`
- `POST /v1/ingestion/run`
- `POST /v1/context/assemble`
- `POST /v1/watcher/check`

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
	-d '{"project_path":"D:/Projects/MMO","force":false}'
```

## Context Retrieval Engine

`POST /v1/context/assemble` monta pacote contextual com:

- intent da consulta
- sistemas relevantes
- expansao de dependencias
- riscos e compressao por budget

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
```

Observacao: `ALIBABA_REGION_BASE_URLS` aceita uma lista separada por virgula para fallback de regiao.

## Evolucao recomendada

1. Substituir retrieval lexical por vetor local.
2. Adicionar parser AST por linguagem para aumentar confidence.
3. Integrar policy de aprovacao humana para rotas Ultra.

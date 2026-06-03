# BRASA Cognitive Runtime

## Hierarchical Cognitive Operating System for Game Development

Cognitive Runtime Update
https://github.com/Rafhael-Oliveira-IA/brasa-ai-core-engine/pull/1

Reflection & Cognitive Calibration Update
https://github.com/Rafhael-Oliveira-IA/brasa-ai-core-engine/pull/2

BRASA Cognitive Runtime is a hybrid cognitive architecture designed for large-scale game development workflows, persistent architectural memory, and AI-assisted software reasoning.

The system combines:

* local cognition (Ollama)
* Alibaba Cloud reasoning (Qwen / ModelStudio)
* hierarchical knowledge compilation
* semantic retrieval
* incremental context rebuilding
* cognitive evaluation
* architectural reflection

Unlike traditional copilots, BRASA is not designed to be a simple prompt assistant.

Its goal is to become:

> A persistent architectural brain for long-lived game projects.

---

# Vision

Modern game projects suffer from:

* fragmented architectural knowledge
* outdated documentation
* context loss
* onboarding difficulty
* disconnected systems
* increasing cognitive complexity

BRASA solves this by transforming source code into:

* structured knowledge
* hierarchical memory
* semantic context graphs
* persistent architectural cognition

The runtime continuously compiles project knowledge into navigable cognitive layers.

---

# Core Philosophy

The system does NOT treat code as plain text.

It treats projects as:

* evolving knowledge systems
* dependency graphs
* architectural ecosystems
* persistent cognitive domains

BRASA focuses on:

* context quality over raw prompting
* architectural understanding over autocomplete
* retrieval precision over token brute force
* persistent memory over isolated sessions

---

# Architecture Overview

```txt id="teovh8"
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

---

# Runtime Layers

## 1. Ingestion Engine

Scans projects incrementally and builds hierarchical knowledge artifacts.

Features:

* file scanning
* hashing
* incremental rebuild
* stale detection
* dependency invalidation
* structured metadata generation

Supported ecosystems:

* C++
* Lua
* Unity
* XML
* C#
* ShaderGraph
* OTServ/TFS architectures

---

## 2. Knowledge Compiler

Transforms raw source code into:

* summaries
* structured metadata
* dependency maps
* architectural memory

Generated artifacts:

* file README
* folder README
* module README
* project README
* structured JSON knowledge

---

## 3. Hybrid Retrieval Engine

The retrieval layer combines:

* lexical retrieval
* semantic retrieval
* graph traversal
* domain heuristics
* contextual ranking

Powered by:

* Alibaba Embeddings
* hybrid semantic scoring
* MMO-aware retrieval heuristics

The runtime understands:

* OTServ architectures
* Revscriptsys
* XML startup pipelines
* Lua registration flows
* Unity gameplay structures

XML Retrieval Guarantee:

* XML-focused queries (for example `actions.xml`, `movements.xml`, `talkactions.xml`) always keep XML context in the final selected packet.
* When a specific XML filename is mentioned, retrieval preserves the exact XML file in selected context when that file exists in artifacts.
* Ranking boosts the exact XML filename mentioned in the prompt, so classic XML and runtime script models are returned together when relevant.
* Budget compression truncates oversized high-priority candidates instead of dropping them entirely, reducing loss of architectural anchor files.

Regression coverage:

* [tests/test_retrieval_noise_filtering.py](tests/test_retrieval_noise_filtering.py) validates XML selection and exact filename preservation across actions, movements, and talkactions queries.
* [tests/test_retrieval_engine.py](tests/test_retrieval_engine.py) validates clipping behavior for oversized high-priority candidates.

---

## 4. Cognitive Query Engine

Central runtime orchestration layer responsible for:

* retrieval
* context assembly
* routing
* reasoning
* memory
* telemetry

The engine dynamically decides:

* local vs cloud reasoning
* context expansion depth
* token budget
* retrieval strategies
* fallback policies

---

## 5. Evaluation Engine

Operational cognition evaluation system.

Measures:

* retrieval quality
* context quality
* semantic ranking
* reasoning consistency
* hallucination risk
* runtime effectiveness

This enables:

* benchmark-driven evolution
* regression detection
* retrieval tuning
* cognitive observability

---

## 6. Reflection System (WIP)

Future self-healing cognition layer.

Goals:

* stale context detection
* architecture drift analysis
* dead system detection
* summary repair
* dependency repair
* confidence re-scoring

---

# Hybrid AI Architecture

BRASA uses a hybrid reasoning model.

## Local Runtime (Ollama)

Used for:

* lightweight reasoning
* preprocessing
* embeddings
* caching
* fallback execution
* low-cost cognition

---

## Alibaba Cloud (Qwen / ModelStudio)

Used for:

* advanced reasoning
* large context analysis
* architectural planning
* semantic retrieval
* reflection
* high-complexity cognition

Models currently targeted:

* Qwen3.5-Plus
* Qwen3.7-Plus
* Qwen-Max
* text-embedding-v4

---

# Cognitive Retrieval Flow

```txt id="9htr3m"
Query
 ↓
Intent Classification
 ↓
Hybrid Retrieval
 ↓
Graph Expansion
 ↓
Context Ranking
 ↓
Context Budgeting
 ↓
Reasoning Routing
 ↓
LLM Execution
 ↓
Evaluation
 ↓
Memory Update
```

---

# Current Features

## Operational

* Hierarchical knowledge generation
* Incremental ingestion
* Dependency invalidation
* Hybrid semantic retrieval
* Alibaba embedding integration
* Context assembly
* Routing engine
* Evaluation engine
* Cognitive telemetry
* Runtime tracing
* Cognitive feedback loop API
* Daily cognitive usage runner
* MMO-aware ranking
* Unity-aware ranking
* FastAPI runtime
* Local-first architecture

---

## Domain-Aware Cognition

The runtime already understands:

* MMO startup pipelines
* Revscriptsys architecture
* XML event registration
* Lua event systems
* OTServ/TFS project structures
* Unity gameplay architecture
* gameplay systems
* inventory systems
* networking systems

---

# Project Structure

```txt id="c0tnly"
.brasa/
 ├── projects/
 │    ├── <project>/
 │    │    ├── raw/
 │    │    ├── summaries/
 │    │    ├── memories/
 │    │    ├── graphs/
 │    │    ├── contexts/
 │    │    └── metadata/
 │
 ├── evaluations/
 ├── traces/
 └── cache/
```

---

# Cognition Plane Separation

```txt id="calibration-planes"
.brasa/
 ├── runtime/
 │    ├── sessions/
 │    ├── traces/
 │    └── temporary_context/
 │
 ├── cognition/
 │    ├── projects/
 │    ├── reflections/
 │    ├── evaluations/
 │    ├── graph_memory/
 │    └── generations/
 │
 └── calibration/
	├── failures/
	├── heuristics/
	├── weights/
	└── ranking_profiles/
```

Runtime cognition keeps fast-changing state (sessions/traces/context packets).

Knowledge cognition keeps durable architectural memory and reflective intelligence.

---

# API Endpoints

## Ingestion

```http id="5w7by8"
POST /v1/ingestion/run
```

Runs project ingestion and hierarchical compilation.

---

## Context Assembly

```http id="ux6b7d"
POST /v1/context/assemble
```

Builds runtime cognitive context.

---

## Chat / Reasoning

```http id="esjlwm"
POST /v1/chat
```

Executes cognitive reasoning pipeline.

---

## Evaluation

```http id="vbqvgs"
POST /v1/evaluation/run
GET /v1/evaluation/recent
```

Runs cognition evaluation and retrieves reports.

---

## Cognitive Feedback Loop

```http id="feedback-loop"
POST /v1/feedback
GET /v1/feedback/recent
```

Collects user verdicts from real usage, including:

* correct / partial / incorrect
* context_bad
* xml_missing
* hallucination
* retrieval_incorrect
* compression_bad
* architectural_loss

These signals feed evaluation and reflection cycles.

---

## Daily Cognitive Usage Dataset

Run daily real-usage query batches and store a proprietary calibration dataset:

* query set: [tools/cognitive_usage_daily_queries.json](tools/cognitive_usage_daily_queries.json)
* runner: [tools/run_cognitive_usage_phase.py](tools/run_cognitive_usage_phase.py)
* output: data/evaluations/cognitive_usage/*.jsonl

Example:

python tools/run_cognitive_usage_phase.py

---

## Retrieval Failure Taxonomy

The calibration layer classifies retrieval failures into explicit buckets:

* xml_missing
* wrong_module
* wrong_generation
* stale_summary
* dependency_noise
* graph_underexpansion
* graph_overexpansion
* compression_loss
* ranking_collision
* semantic_misdirection

Diagnostics are generated via:

```http id="calibration-diagnostics"
POST /v1/calibration/diagnostics
```

---

## Calibration Profiles

Profile-aware retrieval is now supported for adaptive ranking:

* mmo_profile
* unity_profile
* networking_profile
* lua_profile
* shader_profile
* xml_profile

This is the base of a self-calibrating retrieval system where MMO and Unity queries can be tuned independently.

---

# Long-Term Goal

BRASA is evolving toward:

> A fully persistent cognitive operating system for game studios.

Not a copilot.

Not a chatbot.

But:

* a living architectural memory
* a software cognition engine
* a self-improving reasoning runtime
* a persistent AI layer for long-lived game ecosystems

---

# Status

Current Phase:

* Phase 3 - Cognitive Usage

Focus:

* daily real usage
* real trace collection
* retrieval debugging
* context quality scoring
* hallucination detection
* feedback-driven calibration

---

# Future Roadmap

## Phase 3

Cognitive Usage

* daily usage on real project tasks
* cognitive telemetry dataset growth
* feedback loop adoption across teams
* regression tracking from real traces

## Phase 4

Reflection + Self-Healing Cognition

* trace failure analysis
* stale knowledge detection
* confidence repair
* auto-weight adjustment

## Phase 5

Persistent Studio Brain

* long-term architectural evolution tracking
* gameplay cognition continuity
* autonomous documentation suggestions
* architecture-aware planning assistance

## Phase 6

Specialized MMO/Unity Agents

## Phase 7

Autonomous Architectural Reasoning

---

# Built For

* MMO servers
* Unity projects
* persistent online games
* large gameplay systems
* long-lived codebases
* community-driven ecosystems
* AI-assisted game studios

---

# Philosophy

The future of software development is not:

* larger prompts
* more tokens
* isolated chat sessions

The future is:

* persistent cognition
* architectural memory
* hierarchical knowledge
* semantic reasoning
* self-evolving context systems

# ADR 0001: Runtime vs Knowledge Boundary (Lite)

## Status
Accepted

## Context
The first implementation must run fast with minimal operational friction.

## Decision
- Runtime owns orchestration, routing, provider calls, and telemetry.
- Knowledge layer owns persisted memory entries and reflection summaries.
- In MVP, knowledge persistence uses local SQLite and JSON reports.

## Consequences
- Fast local setup, no external database needed.
- Contracts stay stable for later migration to MongoDB/Qdrant/Redis.

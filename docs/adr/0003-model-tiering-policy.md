# ADR 0003: Model Tiering Policy (Lite)

## Status
Accepted

## Context
Need quality and cost control while keeping implementation simple.

## Decision
- Tier order: local -> flash -> plus -> max.
- Start tier is selected by prompt complexity or optional tier hint.
- Escalate when confidence is below threshold and budget allows.
- Enforce per-request budget cap before external provider calls.

## Consequences
- Most requests remain local for speed and cost.
- Complex requests can escalate with explicit guardrails.

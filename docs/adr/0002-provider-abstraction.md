# ADR 0002: Provider Abstraction and Fallback

## Status
Accepted

## Context
Need to support local-first execution and Alibaba escalation without coupling business logic to a single provider.

## Decision
- Use provider interface with `generate(prompt, context, model_name)`.
- Keep one always-available local provider.
- Use Alibaba OpenAI-compatible adapter for flash/plus/max tiers.
- On provider failure/unavailability, fallback to local provider.

## Consequences
- Routing and context logic remain provider-agnostic.
- Easy to add new providers later.

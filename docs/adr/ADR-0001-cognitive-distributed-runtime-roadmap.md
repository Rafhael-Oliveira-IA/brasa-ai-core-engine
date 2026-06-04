# ADR-0001: Cognitive Distributed Runtime Roadmap

- Status: Proposed (Phase 6 bootstrap)
- Date: 2026-06-04
- Decision owners: Runtime / Retrieval / Orchestrator maintainers

## Context

BRASA currently uses a tiered model routing strategy (`local`, `flash`, `plus`, `max`) and already supports:

- grounded chat with project evidence
- auto-reingest on weak chat context
- hybrid retrieval + graph expansion
- action planning/execution with rollback and validation
- orchestrator loops (manual/autopilot)

However, architecture specialization is still mostly tier-based and not yet role-specialized.

## Decision

Adopt a Cognitive Distributed Runtime architecture where responsibilities are split by execution layer and model role.

### Local layer (Tier 0)

The local runtime remains the default owner for deterministic, high-frequency operations:

- scanning, hashing, watcher flows
- indexing, cache and queueing
- baseline retrieval + compression pre-pass
- hot episodic memory assembly
- fast local draft generation
- offline fallback

### Cloud layers (Tier 1..3)

Alibaba cloud models are used for heavy cognition and role-specialized tasks.

Target roles:

- classification
- coding
- long_context
- planning
- reflection
- compression
- repair
- verifier

## Initial implementation scope (this phase)

1. Add role-aware model configuration keys in settings.
2. Add role resolution in router based on metadata/task type/retrieval intent.
3. Keep tier policy and budget gates unchanged.
4. Default role models fallback to current tier defaults to preserve backward compatibility.

## Why this decision

- Avoids the anti-pattern of using one model path for all cognitive tasks.
- Improves cost/quality trade-offs by matching workload to model role.
- Creates a stable migration path toward critic/verifier/reflection clusters.

## Consequences

### Positive

- Better model-task alignment.
- Cleaner evolution toward cognitive CI/CD loops.
- Safer incremental rollout without breaking current endpoints.

### Risks

- Misconfigured role model names can reduce quality.
- More configuration keys increase operational complexity.

### Mitigations

- Keep strict defaults mapped to existing model names.
- Add explicit tests for role routing behavior.
- Preserve tier fallback behavior when metadata is absent.

## Rollout plan

1. Router role selection (task_type + metadata + retrieval intent).
2. Add tests for planning/coding/reflection role selection.
3. Observe route telemetry and adjust role defaults.
4. Expand to multi-pass critic/verifier chain in follow-up ADR.

## Out of scope for this ADR

- Full multi-model executor/critic/verifier orchestration cluster.
- Multi-embedding store split.
- Nightly deep reflection redesign pipeline.

These are tracked as follow-up ADRs.

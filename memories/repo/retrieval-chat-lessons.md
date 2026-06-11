# Retrieval and Chat Lessons

- Loot queries in MMO projects must prioritize monster artifacts (data/monster, data/monsters) including .lua files, not only XML/items.
- Avoid short stopword intent terms (e.g., os/do/the/of) because substring matching can inflate unrelated relevance to 1.0.
- For chat factual code queries, downweight stale episodic chat memories that claim "no evidence" to prevent self-reinforcing retrieval loops.
- Alibaba adapter should receive all selected context snippets from ContextPacket; avoid fixed low snippet caps when retrieval already compresses context.
- For generic summaries, enrich context with raw source excerpts (e.g., LootEvidence block) so the final answer can cite concrete values.
- Chat can use a Qwen multi-model pipeline (classification -> generation -> verifier -> repair) with safe fallbacks when classifier/verifier payloads are unavailable.
- Route decision tier/cost should reflect the effective model family (flash/plus/max) inferred from model_name, especially when role-specific model overrides tier defaults.

## New Chat Checklist

1. Verify backend health: `GET /health`.
2. Run `POST /v1/context/assemble` before complex chat/action prompts.
3. For loot prompts, confirm top context includes monster artifact path (for example `data/monster/.../arcanine.lua`).
4. If summary is generic, confirm snippet contains `LootEvidence[...]` raw excerpt.
5. If chat quality drops, inspect route fields (`selected_tier`, `model_name`, `reason`) and confirm multi-model pipeline flags in settings.
6. Re-run routing + retrieval regression tests before changing heuristics.

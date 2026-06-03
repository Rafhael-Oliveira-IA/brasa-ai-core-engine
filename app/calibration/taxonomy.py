from __future__ import annotations

from enum import Enum


class RetrievalFailureType(str, Enum):
    XML_MISSING = "xml_missing"
    WRONG_MODULE = "wrong_module"
    WRONG_GENERATION = "wrong_generation"
    STALE_SUMMARY = "stale_summary"
    DEPENDENCY_NOISE = "dependency_noise"
    GRAPH_UNDEREXPANSION = "graph_underexpansion"
    GRAPH_OVEREXPANSION = "graph_overexpansion"
    COMPRESSION_LOSS = "compression_loss"
    RANKING_COLLISION = "ranking_collision"
    SEMANTIC_MISDIRECTION = "semantic_misdirection"


DEFAULT_FAILURE_TAXONOMY = [item.value for item in RetrievalFailureType]

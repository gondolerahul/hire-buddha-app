"""
constants.py — Centralized constants for the AI engine.

All magic numbers, model names, and internal keys that were previously
scattered across worker.py, memory_service.py, and service.py are
consolidated here as the single source of truth.
"""
from typing import FrozenSet

# ---------------------------------------------------------------------------
# Embedding Model (Fallback Default)
# ---------------------------------------------------------------------------
# This is the FALLBACK model used when no embedding model is configured
# via the Integrations/AI Configuration admin pages.
# The system should preferably resolve the embedding model from the
# company's IntegrationRegistry / AI Configuration at runtime.
# Previously: "text-embedding-004" in memory_service.py vs
#             "gemini-embedding-004" in worker.py/service.py (DATA-4 bug)
EMBEDDING_MODEL_FALLBACK = "text-embedding-005"

# Backward compat alias — existing code references EMBEDDING_MODEL directly
EMBEDDING_MODEL = EMBEDDING_MODEL_FALLBACK

# ---------------------------------------------------------------------------
# Internal Context Keys
# ---------------------------------------------------------------------------
# Keys injected into context_state for engine bookkeeping.
# Must be stripped before persisting or sending to LLM prompts.
# Previously duplicated at worker.py:1974 (7 members) and worker.py:2334
# (11 members) with different sets — a latent context-leakage bug (R5).
INTERNAL_CONTEXT_KEYS: FrozenSet[str] = frozenset({
    "input",
    "cortex_tree_id",
    "subtree_root_id",
    "__memory__",
    "__cortex_viewport__",
    "__cortex_tree_id__",
    "__cortex_cursor__",
    "__cortex_knowledge__",
    "__context_sources__",
    "__episodic_memory__",
    "__semantic_context__",
    "__memory_context__",
    "__completed_steps__",
    "tool_call_counts",
    "company_id",
    "user_id",
    # --- v2.0: Unified memory domain keys ---
    "__intelligence__",
    "__experience__",
    "__episodic__",
    "__knowledge_refs__",
    # --- Phase 10D/10E: New internal keys ---
    "__execution_metadata__",
    "__intelligence_rules__",
    "__alignment_correction__",
    "__goal_check_counter__",
})

# ---------------------------------------------------------------------------
# Execution Limits
# ---------------------------------------------------------------------------
MAX_REACT_TURNS = 12
CONTEXT_TOKEN_ESTIMATION_DIVISOR = 4
MAX_CONTENT_CHARS = 50000
MAX_CONTEXT_TRUNCATION_CHARS = 6000
CONTEXT_SUMMARIZE_THRESHOLD = 20000
DEFAULT_TIMEOUT_MS = 60000

# ---------------------------------------------------------------------------
# Dreaming / Consolidation Defaults
# ---------------------------------------------------------------------------
# These are system-wide defaults. App admins can override via the
# AI Configuration admin page. Values stored in IntegrationRegistry.
DREAMING_CONSOLIDATION_INTERVAL_HOURS = 24
DREAMING_MIN_EPISODES = 5
DREAMING_BATCH_SIZE = 20
DREAMING_OBSERVATION_CONFIDENCE_THRESHOLD = 0.5
DREAMING_PATTERN_STRENGTH_THRESHOLD = 0.7

# ---------------------------------------------------------------------------
# Semantic Graph Defaults
# ---------------------------------------------------------------------------
GRAPH_SIMILARITY_THRESHOLD = 0.85
GRAPH_MAX_AUTO_EDGES_PER_NODE = 5
GRAPH_WEIGHT_DECAY_RATE = 0.95
GRAPH_MIN_EDGE_WEIGHT = 0.01
GRAPH_MAX_EXPANSION_DEPTH = 2

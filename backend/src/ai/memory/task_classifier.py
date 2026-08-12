"""
ai.memory.task_classifier — Phase 11 Track 4 task-class identifier.

Maps a run's (task_description, entity) to a stable short string used
to group statistics across runs:

  * :class:`ai.planning.plan_style_bandit.PlanStyleBandit` keys arm
    state per ``(entity_id, task_class)``.
  * :class:`ai.planning.critic_calibration.CriticCalibrator` groups
    false-pass / false-fail metrics per task class.
  * :class:`ai.planning.supervisor_critic.SupervisorCritic` filters
    intelligence rules to those tagged for the current class.

The v1 classifier is deterministic and rule-based — small enough to
unit-test exhaustively. A v2 embedding-nearest-neighbour classifier is
behind ``task_classifier.v2_enabled`` (default OFF in Track 4).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "TaskClassifier",
    "TAG_TO_CLASS",
    "KEYWORD_TO_CLASS",
    "DEFAULT_CLASS",
]


DEFAULT_CLASS = "general"


# Stable canonical class names. Keep this list small and revision-controlled.
TAG_TO_CLASS: dict[str, str] = {
    "research": "research_topic",
    "extract": "extract_from_url",
    "scrape": "extract_from_url",
    "email": "draft_email",
    "social": "post_social_content",
    "social_post": "post_social_content",
    "report": "generate_report",
    "summarise": "summarise_content",
    "summarize": "summarise_content",
    "campaign": "run_campaign",
    "outreach": "draft_outreach",
    "lead": "score_lead",
    "intelligence": "research_topic",
    "qa": "answer_question",
    "support": "answer_question",
}


# Order matters — earlier rules win. Substring match (case-insensitive).
KEYWORD_TO_CLASS: list[tuple[str, str]] = [
    ("draft email", "draft_email"),
    ("email draft", "draft_email"),
    ("social post", "post_social_content"),
    ("write a post", "post_social_content"),
    ("research", "research_topic"),
    ("scrape", "extract_from_url"),
    ("crawl", "extract_from_url"),
    ("extract", "extract_from_url"),
    ("summari", "summarise_content"),
    ("report", "generate_report"),
    ("answer", "answer_question"),
    ("question", "answer_question"),
    ("outreach", "draft_outreach"),
    ("lead score", "score_lead"),
    ("rank lead", "score_lead"),
    ("campaign", "run_campaign"),
]


class TaskClassifier:
    """Best-effort classifier. Always returns a string (never None)."""

    def __init__(
        self,
        db: Any = None,
        company_id: Any = None,
        embedding_service: Any = None,
        *,
        v2_enabled: bool = False,
    ):
        self.db = db
        self.company_id = company_id
        self.emb = embedding_service
        self.v2_enabled = v2_enabled

    async def classify(
        self,
        *,
        task_description: str = "",
        entity: Any = None,
    ) -> str:
        """Return the task class for the (entity, task_description) pair."""
        # 1) Explicit override on the entity's metadata_extensions.
        if entity is not None:
            explicit = self._read_explicit(entity)
            if explicit:
                return explicit

            # 2) Tag-based mapping.
            for tag in self._read_tags(entity):
                key = str(tag or "").strip().lower()
                if key in TAG_TO_CLASS:
                    return TAG_TO_CLASS[key]

            # 3) Entity name / goal heuristic.
            for source in (
                getattr(entity, "name", "") or "",
                getattr(entity, "goal", "") or "",
            ):
                cls = self._keyword_lookup(source)
                if cls != DEFAULT_CLASS:
                    return cls

        # 4) Task-description heuristic.
        cls = self._keyword_lookup(task_description or "")
        if cls != DEFAULT_CLASS:
            return cls

        # 5) Optional v2 embedding NN — only when explicitly enabled.
        if self.v2_enabled and self.emb is not None and task_description:
            try:
                nn = await self._embedding_nn(task_description)
                if nn:
                    return nn
            except Exception as exc:                                        # pragma: no cover
                logger.debug("task_classifier v2 NN failed: %s", exc)

        return DEFAULT_CLASS

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_explicit(entity: Any) -> Optional[str]:
        meta = getattr(entity, "metadata_extensions", None)
        if isinstance(meta, dict):
            cls = meta.get("task_class")
            if isinstance(cls, str) and cls.strip():
                return cls.strip()
        return None

    @staticmethod
    def _read_tags(entity: Any) -> list[str]:
        tags = getattr(entity, "tags", None)
        if isinstance(tags, list):
            return [t for t in tags if isinstance(t, str)]
        return []

    @staticmethod
    def _keyword_lookup(text: str) -> str:
        if not text:
            return DEFAULT_CLASS
        lower = text.lower()
        # Normalise whitespace + punctuation for stable matches.
        norm = re.sub(r"\s+", " ", lower).strip()
        for kw, cls in KEYWORD_TO_CLASS:
            if kw in norm:
                return cls
        return DEFAULT_CLASS

    async def _embedding_nn(self, task_description: str) -> Optional[str]:
        """Optional v2 path — returns the nearest known class label.

        Implemented as a thin wrapper so existing tests don't need a
        live embedding service. The vocabulary is the union of values
        in TAG_TO_CLASS + KEYWORD_TO_CLASS.
        """
        if self.emb is None:
            return None
        vocab = sorted({*TAG_TO_CLASS.values(), *(c for _, c in KEYWORD_TO_CLASS)})
        try:
            best_class: Optional[str] = None
            best_score = -1.0
            qv = await self.emb.embed_query(task_description)
            if not qv:
                return None
            for label in vocab:
                lv = await self.emb.embed_query(label.replace("_", " "))
                if not lv:
                    continue
                # Cosine similarity (assume both lists are pre-L2-normalised
                # by the embedding service; if not this is a rough match).
                score = sum(a * b for a, b in zip(qv, lv))
                if score > best_score:
                    best_score = score
                    best_class = label
            # Conservative gate so we don't mis-route on noisy embeddings.
            if best_score >= 0.45:
                return best_class
        except Exception:                                                   # pragma: no cover
            return None
        return None

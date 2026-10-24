"""What a charge is, for customers: the billing category of a usage row (Phase 15 T3-3, tech design §5.3).

Derived when the row is written, from its attribution and its SKU, and kept on
the row (``usage_logs.category``) and on billing lines (T3-4), so a bill reads
"AI models ₹…, voice ₹…, hosting ₹…" without re-deriving anything.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Optional


class Category(StrEnum):
    AI_MODELS = "ai_models"
    KNOWLEDGE = "knowledge"
    TOOLS = "tools"
    MEDIA = "media"
    VOICE = "voice"
    VIDEO = "video"
    SANDBOX = "sandbox"
    HOSTING = "hosting"
    DATABASE = "database"
    PHONE_NUMBERS = "phone_numbers"


_MODEL_ATTRIBUTIONS = frozenset({
    "planner", "actor_step", "critic_pre", "critic_post", "critic_align", "critic_super", "reformat_retry",
    "meta_review", "dreaming", "meta_spec_critic", "test_driver", "child_run",
})
_MEDIA_SKU_CATEGORIES = frozenset({"IMAGE_GENERATION", "VIDEO_GENERATION", "SPEECH_GENERATION", "MUSIC_GENERATION"})
_DATABASE_SKUS = frozenset({"tenant-db-pool-share", "tenant-db-dedicated", "tenant-db-storage-gb-month",
                            "tenant-backup-gb-month"})


def category_for(attribution: Optional[str], *, sku_category: Optional[str] = None,
                 sku: Optional[str] = None) -> Category:
    """The billing category of a row with this attribution and SKU."""
    attribution = attribution or "tool"
    if attribution in _MODEL_ATTRIBUTIONS:
        return Category.AI_MODELS
    if attribution == "embedding":
        return Category.KNOWLEDGE
    if attribution == "voice_call":
        return Category.VOICE
    if attribution == "video_frame":
        return Category.VIDEO
    if attribution == "sandbox":
        return Category.SANDBOX
    if attribution == "hosting":
        return Category.DATABASE if sku in _DATABASE_SKUS else Category.HOSTING
    return Category.MEDIA if sku_category in _MEDIA_SKU_CATEGORIES else Category.TOOLS

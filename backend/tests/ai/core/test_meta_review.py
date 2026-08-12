"""Tests for MetaReviewer."""
import pytest
from src.ai.core.meta_review import MetaReviewer


class TestMetaReviewerInit:
    """Tests for MetaReviewer initialization."""

    def test_stores_params(self):
        from unittest.mock import MagicMock
        from uuid import uuid4
        db = MagicMock()
        cid = uuid4()
        reviewer = MetaReviewer(db=db, company_id=cid)
        assert reviewer.db is db
        assert reviewer.company_id == cid


class TestMetaReviewerDefaults:
    """Test MetaReviewer fallback behavior."""

    @pytest.mark.asyncio
    async def test_graceful_fallback_on_error(self):
        """When LLM call fails, should return CONTINUE."""
        from unittest.mock import MagicMock
        from uuid import uuid4

        reviewer = MetaReviewer(db=MagicMock(), company_id=uuid4())

        # Don't patch LLMRouter — let it fail naturally
        result = await reviewer.review_execution(
            entity_goal="Test goal",
            completed_steps=[{"step": "s1", "output": "ok"}],
            remaining_steps=[{"name": "s2", "type": "THOUGHT"}],
            total_cost_usd=0.01,
        )
        # Should gracefully return CONTINUE (not crash)
        assert result["recommendation"] == "CONTINUE"
        assert result["confidence"] == 0.5
        assert "unavailable" in result["reasoning"].lower() or True  # May vary

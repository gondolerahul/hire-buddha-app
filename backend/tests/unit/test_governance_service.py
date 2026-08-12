"""
Unit tests for src.ai.governance_service
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from decimal import Decimal
from uuid import uuid4

from src.ai.governance.governance_service import GovernanceService
from src.billing.credit_service import InsufficientCreditsError


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def mock_redis():
    return AsyncMock()


@pytest.fixture
def service(mock_db, mock_redis):
    return GovernanceService(mock_db, mock_redis)


class TestCreditGate:

    @pytest.mark.asyncio
    async def test_check_credit_gate_sufficient(self, service):
        """Should pass when credits are sufficient."""
        with patch.object(service.credit_service, 'check_sufficient_for_execution',
                          AsyncMock(return_value={"total_available": Decimal("100.00")})):
            result = await service.check_credit_gate(uuid4(), "AGENT")
            assert result.get("total_available") == Decimal("100.00")

    @pytest.mark.asyncio
    async def test_check_credit_gate_insufficient(self, service):
        """Should raise when credits are zero."""
        with patch.object(service.credit_service, 'check_sufficient_for_execution',
                          AsyncMock(side_effect=InsufficientCreditsError("No credits"))):
            with pytest.raises(InsufficientCreditsError):
                await service.check_credit_gate(uuid4(), "AGENT")

    @pytest.mark.asyncio
    async def test_check_credit_gate_db_error_swallowed(self, service):
        """Should swallow non-fatal DB errors and return empty dict."""
        with patch.object(service.credit_service, 'check_sufficient_for_execution',
                          AsyncMock(side_effect=RuntimeError("DB down"))):
            result = await service.check_credit_gate(uuid4(), "AGENT")
            assert result == {}


class TestConsumeStepCost:

    @pytest.mark.asyncio
    async def test_consume_step_cost_calls_credit_service(self, service):
        """Should call credit_service.consume_incremental."""
        run = MagicMock()
        run.company_id = uuid4()
        run.total_cost_usd = Decimal("1.00")

        with patch.object(service.credit_service, 'consume_incremental',
                          AsyncMock(return_value={"deducted": Decimal("0.50"), "shortfall": Decimal("0"), "exhausted": False})):
            result = await service.consume_step_cost(run, "step_1", Decimal("0.50"))
            assert result["deducted"] == Decimal("0.50")

    @pytest.mark.asyncio
    async def test_consume_step_cost_zero_noop(self, service):
        """Should return zero-cost result when step_cost <= 0."""
        run = MagicMock()
        run.company_id = uuid4()

        result = await service.consume_step_cost(run, "step_1", Decimal("0"))
        assert result["deducted"] == Decimal("0")


class TestSettleBilling:

    @pytest.mark.asyncio
    async def test_settle_billing_child_run_skips(self, service):
        """Should return 0 for child runs (parent_run_id is set)."""
        run = MagicMock()
        run.parent_run_id = uuid4()
        run.total_cost_usd = Decimal("5.00")

        result = await service.settle_billing(run, "TestEntity")
        assert result == Decimal("0")

    @pytest.mark.asyncio
    async def test_settle_billing_zero_cost(self, service):
        """Should return 0 when total_cost_usd is 0."""
        run = MagicMock()
        run.parent_run_id = None
        run.total_cost_usd = Decimal("0")
        run.id = uuid4()
        run.company_id = uuid4()

        result = await service.settle_billing(run, "TestEntity")
        assert result == Decimal("0")
        assert run.billed_amount == Decimal("0")

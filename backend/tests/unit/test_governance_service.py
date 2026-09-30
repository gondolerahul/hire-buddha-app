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
    async def test_check_credit_gate_holds_the_estimate(self, service):
        """The gate places a hold with the entity type's minimum as the floor."""
        run = MagicMock(id=uuid4(), company_id=uuid4())
        place = AsyncMock(return_value=Decimal("1.50"))
        with patch.object(service.credit_service, "place_hold", place):
            held = await service.check_credit_gate(run, "PROCESS", Decimal("1.50"))
        assert held == Decimal("1.50")
        place.assert_awaited_once_with(run.company_id, run.id, Decimal("1.50"), Decimal("0.50"))

    @pytest.mark.asyncio
    async def test_check_credit_gate_insufficient(self, service):
        with patch.object(service.credit_service, "place_hold",
                          AsyncMock(side_effect=InsufficientCreditsError("No credits"))):
            with pytest.raises(InsufficientCreditsError):
                await service.check_credit_gate(MagicMock(), "AGENT", Decimal("0"))

    @pytest.mark.asyncio
    async def test_check_credit_gate_fails_closed_on_db_error(self, service):
        """A wallet that cannot be read does not let the run start (BC-05)."""
        with patch.object(service.credit_service, "place_hold",
                          AsyncMock(side_effect=RuntimeError("DB down"))):
            with pytest.raises(RuntimeError):
                await service.check_credit_gate(MagicMock(), "AGENT", Decimal("0"))


class TestCircuitBreaker:

    @pytest.mark.asyncio
    async def test_stops_when_the_bill_reaches_spendable_credit(self, service):
        run = MagicMock(id=uuid4(), company_id=uuid4())
        config = MagicMock(multiplier_factor=Decimal("2"), platform_fee_pct=Decimal("0"),
                           sales_partner_fee_pct=Decimal("0"), discount_pct=Decimal("0"))
        with patch.object(service.billing_service, "get_billing_config", AsyncMock(return_value=config)), \
             patch.object(service.credit_service, "get_balance", AsyncMock(return_value={"total_available": 3.0})), \
             patch.object(service.credit_service, "held_by_others", AsyncMock(return_value=Decimal("1"))):
            await service.check_credit_circuit_breaker(run, Decimal("0.99"))   # bill 1.98 < 2
            with pytest.raises(InsufficientCreditsError):
                await service.check_credit_circuit_breaker(run, Decimal("1.00"))  # bill 2.00


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

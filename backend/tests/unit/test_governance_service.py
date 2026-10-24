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
    svc = GovernanceService(mock_db, mock_redis)
    # No monthly spend cap set (GH-18); tests/integration/test_spend_cap.py has the cap.
    svc.credit_service.spend_cap_refusal = AsyncMock(return_value=None)
    return svc


class TestCreditGate:

    @pytest.mark.asyncio
    async def test_check_credit_gate_holds_the_estimate(self, service):
        """The gate places a hold with the entity type's minimum as the floor."""
        run = MagicMock(id=uuid4(), company_id=uuid4())
        place = AsyncMock(return_value=Decimal("1.50"))
        with patch.object(service.credit_service, "place_hold", place), \
             patch.object(service.credit_service, "check_spend_cap", AsyncMock()), \
             patch("src.billing.settings_catalogue.min_balance", AsyncMock(return_value=Decimal("0.50"))):
            held = await service.check_credit_gate(run, "PROCESS", Decimal("1.50"))
        assert held == Decimal("1.50")
        place.assert_awaited_once_with(run.company_id, run.id, Decimal("1.50"), Decimal("0.50"))

    @pytest.mark.asyncio
    async def test_check_credit_gate_insufficient(self, service):
        with patch.object(service.credit_service, "place_hold",
                          AsyncMock(side_effect=InsufficientCreditsError("No credits"))), \
             patch.object(service.credit_service, "check_spend_cap", AsyncMock()), \
             patch("src.billing.settings_catalogue.min_balance", AsyncMock(return_value=Decimal("0.05"))):
            with pytest.raises(InsufficientCreditsError):
                await service.check_credit_gate(MagicMock(), "AGENT", Decimal("0"))

    @pytest.mark.asyncio
    async def test_check_credit_gate_fails_closed_on_db_error(self, service):
        """A wallet that cannot be read does not let the run start (BC-05)."""
        with patch.object(service.credit_service, "place_hold",
                          AsyncMock(side_effect=RuntimeError("DB down"))), \
             patch.object(service.credit_service, "check_spend_cap", AsyncMock()), \
             patch("src.billing.settings_catalogue.min_balance", AsyncMock(return_value=Decimal("0.05"))):
            with pytest.raises(RuntimeError):
                await service.check_credit_gate(MagicMock(), "AGENT", Decimal("0"))


class TestCircuitBreaker:

    @pytest.mark.asyncio
    async def test_stops_when_the_bill_reaches_spendable_credit(self, service):
        """Headroom = free + tolerance − debt − the bill so far (Phase 15 §6.3), in the wallet's currency."""
        from src.billing.formulas import Formula

        run = MagicMock(id=uuid4(), company_id=uuid4())
        doubled = Formula(Decimal("2"), Decimal("0"), Decimal("0"))     # the run's formula (Phase 15 T3-2)
        balance = {"currency": "USD", "state": "ok", "free": Decimal("2"), "tolerance": Decimal("0"),
                   "debt": Decimal("0")}

        async def headroom(company_id, run_id, billed):
            return balance["free"] + balance["tolerance"] - balance["debt"] - billed, balance

        with patch("src.ai.governance.governance_service.formula_for_run", AsyncMock(return_value=doubled)), \
             patch.object(service.credit_service, "headroom", headroom):
            await service.check_credit_circuit_breaker(run, Decimal("0.99"))   # bill 1.98 < 2
            with pytest.raises(InsufficientCreditsError):
                await service.check_credit_circuit_breaker(run, Decimal("1.00"))  # bill 2.00

    @pytest.mark.asyncio
    async def test_a_wallet_over_its_tolerance_stops_running_runs(self, service):
        from src.billing.formulas import Formula

        run = MagicMock(id=uuid4(), company_id=uuid4())
        over = {"currency": "INR", "state": "over_tolerance", "free": Decimal("0"), "tolerance": Decimal("500"),
                "debt": Decimal("600")}
        with patch("src.ai.governance.governance_service.formula_for_run",
                   AsyncMock(return_value=Formula(Decimal("1"), Decimal("0"), Decimal("0")))), \
             patch.object(service.credit_service, "headroom", AsyncMock(return_value=(Decimal("-1"), over))):
            with pytest.raises(InsufficientCreditsError, match="over its limit"):
                await service.check_credit_circuit_breaker(run, Decimal("0.01"))


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
        """A run with no billable rows settles for 0 (the settlement still claims it)."""
        from contextlib import asynccontextmanager

        from src.billing.settlement import Settled

        run = MagicMock()
        run.parent_run_id = None
        run.total_cost_usd = Decimal("0")
        run.id = uuid4()
        run.company_id = uuid4()

        @asynccontextmanager
        async def same(db):
            yield db

        with patch("src.billing.settlement.settle_run", AsyncMock(return_value=Settled(claimed=True))), \
             patch("src.common.tenancy.session.control_db_for", same), \
             patch.object(service.credit_service, "release_hold", AsyncMock()):
            result = await service.settle_billing(run, "TestEntity")
        assert result == Decimal("0")
        assert run.billed_amount == Decimal("0")

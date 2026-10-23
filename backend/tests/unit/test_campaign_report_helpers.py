"""Unit tests for campaign report helpers: TB billing amounts and the
disposition sort order used by the Excel export and campaign detail API."""

from decimal import Decimal
from types import SimpleNamespace

from src.billing.billing_service import calculate_tb
from src.billing.formulas import IDENTITY, Formula
from src.ai.campaign_models import DISPOSITION_PRIORITY, campaign_call_sort_order


class TestBilledAmount:
    """The campaign report's billed column: the company's formula on a call's cost
    (Phase 15 T3-2: ``Formula``; ``spf`` is folded into ``pf``)."""

    def test_identity_when_no_formula(self):
        assert IDENTITY.rate(Decimal("1.25")) == Decimal("1.25")

    def test_applies_tb_formula(self):
        # TB = c*mf * (1 + pf - d) = 1 * 2 * (1 + 0.15 - 0.03) = 2.24
        assert Formula(Decimal("2"), Decimal("0.15"), Decimal("0.03")).rate(Decimal("1")) == Decimal("2.24")

    def test_discount_exceeding_fees(self):
        assert Formula(Decimal("1"), Decimal("0"), Decimal("0.50")).rate(Decimal("10")) == Decimal("5.00")

    def test_matches_the_old_formula_with_spf_folded(self):
        expected = calculate_tb(
            Decimal("0.4321"), Decimal("1.5"), Decimal("0.08"),
            Decimal("0.02"), Decimal("0.01"),
        )["total_billing"]
        assert Formula(Decimal("1.5"), Decimal("0.10"), Decimal("0.01")).rate(Decimal("0.4321")) == expected

    def test_accepts_float_base_cost(self):
        # VoiceSession.total_cost_usd arrives as Numeric/float
        assert IDENTITY.rate(0.5) == Decimal("0.5")


class TestNormalizePhone:
    """Dialer number normalization — Tata rejects non-E.164 with HTTP 422."""

    def setup_method(self):
        from src.ai.campaign_executor import CampaignExecutor
        self.normalize = CampaignExecutor.normalize_phone

    def test_ten_digits_get_default_country_code(self):
        assert self.normalize("8149603309", "91") == "+918149603309"

    def test_plus_without_country_code(self):
        # The exact failure from the 2026-07-13 campaign
        assert self.normalize("+8149603309", "91") == "+918149603309"
        assert self.normalize("+9310231211", "91") == "+919310231211"

    def test_already_e164_unchanged(self):
        assert self.normalize("+919310231302", "91") == "+919310231302"

    def test_bare_country_code_gets_plus(self):
        assert self.normalize("919310231302", "91") == "+919310231302"

    def test_trunk_zero_dropped(self):
        assert self.normalize("08149603309", "91") == "+918149603309"

    def test_separators_stripped(self):
        assert self.normalize("+91 81496-03309", "91") == "+918149603309"

    def test_empty(self):
        assert self.normalize(None, "91") == ""
        assert self.normalize("", "91") == ""


class TestDispositionSortOrder:
    def test_priority_ordering(self):
        ordered = sorted(DISPOSITION_PRIORITY, key=DISPOSITION_PRIORITY.get)
        assert ordered == [
            "interested", "not_interested", "voicemail",
            "rejected", "busy", "no_answer", "failed",
        ]

    def test_case_expression_compiles_with_status_fallback(self):
        expr = campaign_call_sort_order()
        sql = str(expr.compile(compile_kwargs={"literal_binds": True}))
        assert "CASE" in sql
        assert "interested" in sql
        # Unclassified completed calls must outrank the failure buckets
        assert "completed" in sql
        # Anything else (pending/calling) sorts last
        assert "50" in sql

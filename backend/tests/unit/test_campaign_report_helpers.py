"""Unit tests for campaign report helpers: TB billing amounts and the
disposition sort order used by the Excel export and campaign detail API."""

from decimal import Decimal
from types import SimpleNamespace

from src.billing.billing_service import calculate_tb, compute_billed_amount
from src.ai.campaign_models import DISPOSITION_PRIORITY, campaign_call_sort_order


class TestComputeBilledAmount:
    def test_identity_when_no_config(self):
        assert compute_billed_amount(Decimal("1.25"), None) == Decimal("1.25")

    def test_applies_tb_formula(self):
        config = SimpleNamespace(
            multiplier_factor="2",
            platform_fee_pct="0.10",
            sales_partner_fee_pct="0.05",
            discount_pct="0.03",
        )
        # TB = c*mf * (1 + pf + spf - d) = 1 * 2 * 1.12 = 2.24
        assert compute_billed_amount(Decimal("1"), config) == Decimal("2.24")

    def test_discount_exceeding_fees(self):
        config = SimpleNamespace(
            multiplier_factor="1",
            platform_fee_pct="0",
            sales_partner_fee_pct="0",
            discount_pct="0.50",
        )
        assert compute_billed_amount(Decimal("10"), config) == Decimal("5.00")

    def test_matches_calculate_tb(self):
        config = SimpleNamespace(
            multiplier_factor="1.5",
            platform_fee_pct="0.08",
            sales_partner_fee_pct="0.02",
            discount_pct="0.01",
        )
        expected = calculate_tb(
            Decimal("0.4321"), Decimal("1.5"), Decimal("0.08"),
            Decimal("0.02"), Decimal("0.01"),
        )["total_billing"]
        assert compute_billed_amount(Decimal("0.4321"), config) == expected

    def test_accepts_float_base_cost(self):
        # VoiceSession.total_cost_usd arrives as Numeric/float; helper coerces
        assert compute_billed_amount(0.5, None) == Decimal("0.5")


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

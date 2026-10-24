"""The money settings catalogue (Phase 15 T5-1, T5-2; tech design §8.4).

Every key code reads is in the catalogue; values are checked against their
type and bounds; the defaults of the constants moved into settings are what
the constants were.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

from src.billing.settings_catalogue import CATALOGUE, InvalidSetting, UnknownSetting, coerce, spec_for, typed

SRC = Path(__file__).resolve().parents[2] / "src"
READ = re.compile(r"""(?:\bvalue|\bresolve|get_platform_setting|set_platform_setting)\(\s*[\w.]+,\s*["']([a-z0-9_.A-Z]+)["']""")


def test_every_key_the_code_reads_is_in_the_catalogue():
    read = {}
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "settings_catalogue" not in source and "settings_store" not in source:
            continue                       # another module's value()/resolve()
        for key in READ.findall(source):
            read.setdefault(key, path.relative_to(SRC).as_posix())
    assert read, "the pattern found no reads"
    unknown = {k: v for k, v in read.items() if k not in CATALOGUE}
    assert unknown == {}, f"keys read but not in the catalogue: {unknown}"


def test_an_unknown_key_is_refused():
    with pytest.raises(UnknownSetting):
        spec_for("billing.no_such_thing")


@pytest.mark.parametrize("key, default", [
    ("admission.min_balance.GRAPH", Decimal("2.00")), ("admission.min_balance.AGENT", Decimal("0.05")),
    ("admission.hold_history_runs", 10), ("checkout.abandoned_after_hours", 24),
    ("subscriptions.total_cycles", 120), ("voice.call_hold_seconds", 300), ("voice.credit_check_seconds", 30),
    ("wallet.topup_validity_days", 90), ("wallet.topup_min_usd", Decimal("5")),
    ("wallet.topup_max_usd", Decimal("10000")), ("wallet.negative_tolerance_usd", Decimal("0")),
    ("billing.suspend_after_days", 7), ("billing.app_stop_grace_hours", 0),
])
def test_the_moved_constants_keep_their_values(key, default):
    assert spec_for(key).default == default


def test_values_are_checked_against_type_and_bounds():
    assert coerce(spec_for("wallet.topup_min_usd"), "7.5") == "7.5"
    assert typed(spec_for("wallet.topup_min_usd"), "7.5") == Decimal("7.5")
    assert coerce(spec_for("wallet.topup_presets_usd"), [10, "25"]) == ["10", "25"]
    assert coerce(spec_for("daily_credits.inherit_up_partner_chain"), True) is True
    assert coerce(spec_for("billing.v2_mode"), "off") == "off"
    assert coerce(spec_for("billing.v2_mode"), "on") == "on"            # the switch-on (T10-3)
    for key, bad in [("wallet.topup_min_usd", -1), ("wallet.topup_min_usd", "lots"),
                     ("admission.hold_history_runs", 2.5), ("daily_credits.inherit_up_partner_chain", "yes"),
                     ("billing.v2_mode", "live"), ("wallet.topup_presets_usd", []),
                     ("wallet.topup_min_usd", None), ("wallet.topup_min_usd", True)]:
        with pytest.raises(InvalidSetting):
            coerce(spec_for(key), bad)
    assert coerce(spec_for("alerts.low_balance_usd"), None) is None        # nullable


def test_only_staff_edit_money_settings():
    assert {spec.editors for spec in CATALOGUE.values()} == {("app_admin",)}

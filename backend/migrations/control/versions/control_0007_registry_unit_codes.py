"""registry prices name their unit by code (Phase 15 T1-2)

Revision ID: control_0007_registry_unit_codes
Revises: control_0006_cost_units
Create Date: 2026-10-23

``integration_registry.cost_unit_code`` → ``cost_units.code``, filled from the
old free-text ``cost_unit`` through an explicit table of the spellings in use
(``LEGACY_SPELLINGS``: every scale × noun the old parser accepted, written
out). **A row the table does not map stops the upgrade** and names it: fix that
row's unit (or add its spelling here) and run again. Nothing is guessed.

``cost_unit`` stays one release, nullable, for a rollback; it is dropped after
(plan §4 step 10). ``python -m src.billing.unit_codes_report`` shows, without
changing anything, what this revision would do to a database.

"""
import re
from typing import Dict, List, Optional, Sequence, Tuple, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'control_0007_registry_unit_codes'
down_revision: Union[str, Sequence[str], None] = 'control_0006_cost_units'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Scales the old parser read, as written before the noun.
_ONE = ("", "1")
_THOUSAND = ("1k", "1 k", "k", "1000", "thousand", "1 thousand")
_MILLION = ("1m", "1 m", "m", "1000000", "million", "1 million")
# noun spellings → {scale group: code}
_NOUNS: List[Tuple[Tuple[str, ...], Dict[Tuple[str, ...], str]]] = [
    (("token", "tokens"), {_ONE: "PER_TOKEN", _THOUSAND: "PER_1K_TOKENS", _MILLION: "PER_1M_TOKENS"}),
    (("character", "characters", "char", "chars"),
     {_ONE: "PER_CHARACTER", _THOUSAND: "PER_1K_CHARACTERS", _MILLION: "PER_1M_CHARACTERS"}),
    (("second", "seconds", "sec", "secs"), {_ONE: "PER_SECOND"}),
    (("minute", "minutes", "min", "mins"), {_ONE: "PER_MINUTE"}),
    (("hour", "hours"), {_ONE: "PER_HOUR"}),
    (("call", "calls", "request", "requests", "flat fee"), {_ONE: "PER_REQUEST", _THOUSAND: "PER_1K_REQUESTS"}),
    (("image", "images"), {_ONE: "PER_IMAGE"}),
    (("video", "videos"), {_ONE: "PER_VIDEO"}),
    (("message", "messages"), {_ONE: "PER_MESSAGE"}),
    (("email", "emails"), {_ONE: "PER_EMAIL"}),
    (("page", "pages"), {_ONE: "PER_PAGE"}),
    (("query", "queries", "search", "searches"), {_ONE: "PER_QUERY", _THOUSAND: "PER_1K_QUERIES"}),
    (("gb", "gigabyte", "gigabytes"), {_ONE: "PER_GB"}),
    (("gb hour", "gb hours"), {_ONE: "PER_GB_HOUR"}),
    (("gb month", "gb months"), {_ONE: "PER_GB_MONTH"}),
    (("vcpu hour", "vcpu hours"), {_ONE: "PER_VCPU_HOUR"}),
    (("day", "days"), {_ONE: "PER_DAY"}),
    (("month", "months"), {_ONE: "PER_MONTH"}),
    (("unit", "units"), {_ONE: "PER_UNIT"}),
]


def _spellings() -> Dict[str, str]:
    table: Dict[str, str] = {}
    for nouns, scales in _NOUNS:
        for group, code in scales.items():
            for scale in group:
                for noun in nouns:
                    table[f"{scale} {noun}".strip()] = code
    return table


LEGACY_SPELLINGS: Dict[str, str] = _spellings()


def normalise(text: Optional[str]) -> str:
    """Lower case, one space for any run of ``_ - space``, no leading ``per``, no digit commas."""
    out = re.sub(r"[_\-\s]+", " ", (text or "").strip().lower()).strip()
    out = re.sub(r"(?<=\d),(?=\d{3})", "", out)
    return re.sub(r"^per\s+", "", out)


def code_for(text: Optional[str]) -> Optional[str]:
    return LEGACY_SPELLINGS.get(normalise(text))


def plan(rows) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str, str]]]:
    """``(mapped [(id, code)], unmapped [(id, service_sku, cost_unit)])`` for registry rows."""
    mapped, unmapped = [], []
    for row_id, sku, unit in rows:
        code = code_for(unit)
        if code is None:
            unmapped.append((str(row_id), sku, unit))
        else:
            mapped.append((str(row_id), code))
    return mapped, unmapped


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, service_sku, cost_unit FROM integration_registry")).all()
    mapped, unmapped = plan(rows)
    if unmapped:
        listing = "\n".join(f"  {sku} ({row_id}): cost_unit={unit!r}" for row_id, sku, unit in unmapped)
        raise RuntimeError(
            "control_0007: registry rows whose cost_unit has no code — fix them, then upgrade again:\n" + listing)
    op.add_column('integration_registry', sa.Column('cost_unit_code', sa.Text(), nullable=True))
    for row_id, code in mapped:
        bind.execute(sa.text("UPDATE integration_registry SET cost_unit_code = :c WHERE id = :i"),
                     {"c": code, "i": row_id})
    op.alter_column('integration_registry', 'cost_unit_code', nullable=False)
    op.create_foreign_key('integration_registry_cost_unit_code_fkey', 'integration_registry', 'cost_units',
                          ['cost_unit_code'], ['code'])
    op.alter_column('integration_registry', 'cost_unit', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # A row written after the upgrade has no text unit: give it its code.
    op.execute("UPDATE integration_registry SET cost_unit = cost_unit_code WHERE cost_unit IS NULL")
    op.alter_column('integration_registry', 'cost_unit', existing_type=sa.String(), nullable=False)
    op.drop_constraint('integration_registry_cost_unit_code_fkey', 'integration_registry', type_='foreignkey')
    op.drop_column('integration_registry', 'cost_unit_code')

"""Give each telephony SKU its carrier billing increment (Phase 15 T1-6) — idempotently.

    python -m scripts.set_telephony_increments                 # 60 s where none is set
    TELEPHONY_INCREMENT_SECONDS=1 python -m scripts.set_telephony_increments

Stamps ``service_metadata.provider_billing_increment_seconds`` on every active
telephony SKU (``VoiceUsageLogger.TELEPHONY_SKU_MAP``) that has none. Prices
are not touched. The value is read only by the cost reconciliation
(``src/billing/reconciliation.py``); customers are billed per second whatever
it says.
"""
from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def main() -> int:
    import src.main  # noqa: F401  (every model mapped)
    from src.billing.reconciliation import DEFAULT_INCREMENT_SECONDS, INCREMENT_KEY
    from src.common import database
    from src.common.tenancy.session import control_session
    from src.config.models import IntegrationRegistry
    from src.voice.usage_logger import VoiceUsageLogger

    increment = int(os.environ.get("TELEPHONY_INCREMENT_SECONDS", DEFAULT_INCREMENT_SECONDS))
    skus = tuple(VoiceUsageLogger.TELEPHONY_SKU_MAP.values())
    try:
        async with control_session() as db:
            rows = (await db.execute(select(IntegrationRegistry).where(
                IntegrationRegistry.service_sku.in_(skus), IntegrationRegistry.status == "active"))).scalars().all()
            for row in rows:
                metadata = dict(row.service_metadata or {})
                if metadata.get(INCREMENT_KEY):
                    print(f"  [SKIP] {row.service_sku} ({row.company_id}): {metadata[INCREMENT_KEY]} s")
                    continue
                metadata[INCREMENT_KEY] = increment
                row.service_metadata = metadata
                print(f"  [OK]   {row.service_sku} ({row.company_id}): {increment} s")
            await db.commit()
            if not rows:
                print("No telephony SKUs registered.")
    finally:
        await database.engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

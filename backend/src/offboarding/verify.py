"""Staff check: what an offboarding left behind (docs/phase15/13 §6 step 13).

    python -m src.offboarding.verify OFFBOARDING_ID

Prints each finding (a database, a namespace, storage objects, an identity,
users, rows) and exits 1 when there is one; read-only.
"""
from __future__ import annotations

import asyncio
import sys
from uuid import UUID


async def _main(offboarding_id: UUID) -> int:
    from src.common.orm_models import import_all_models
    from src.common.tenancy.session import control_session
    from src.offboarding.models import CompanyOffboarding
    from src.offboarding.runner import _workspace, leftovers

    import_all_models()
    async with control_session() as db:
        off = await db.get(CompanyOffboarding, offboarding_id)
        if off is None:
            print(f"no offboarding {offboarding_id}")
            return 2
        found = await leftovers(db, off, _workspace(off))
    print(f"{off.company_ref} ({off.mode}, {off.state}): " + ("nothing left" if not found else "; ".join(found)))
    return 1 if found else 0


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    return asyncio.run(_main(UUID(sys.argv[1])))


if __name__ == "__main__":
    sys.exit(main())

"""Re-encrypt every stored credential under the current ENCRYPTION_MASTER_KEY (AU-24).

    # 1. Upgrade pre-AU-24 ciphertexts to v2 under the same key (no key change):
    python -m scripts.rotate_encryption_key            # dry run: counts only
    python -m scripts.rotate_encryption_key --apply

    # 2. Move to a new key: put the NEW key in ENCRYPTION_MASTER_KEY and the old
    #    one in OLD_ENCRYPTION_MASTER_KEY, run with --apply, then remove the old
    #    key from the environment. Restart the API and both workers afterwards.

One transaction: a value that decrypts under neither key aborts the run and
nothing is written. A value already under the new key is left as it is, so an
interrupted run can be re-run. Keys are never printed.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys


async def main(apply: bool) -> int:
    sys.path.insert(0, ".")
    import src.main  # noqa: F401 — registers every ORM mapper
    from src.common.config import settings
    from src.common.database import AsyncSessionLocal
    from src.common.encrypted_fields import RotationError, reencrypt_all

    new = settings.ENCRYPTION_MASTER_KEY
    old = os.environ.get("OLD_ENCRYPTION_MASTER_KEY") or new
    print("Moving to a new key." if old != new else "Same key: upgrading old ciphertexts to v2.")
    async with AsyncSessionLocal() as db:
        try:
            counts = await reencrypt_all(db, old, new)
        except RotationError as exc:
            await db.rollback()
            print(f"Aborted, nothing written: {exc}")
            return 1
        for field, n in counts.items():
            print(f"  {field}: {n}")
        if apply:
            await db.commit()
            print(f"Re-encrypted {sum(counts.values())} value(s).")
        else:
            await db.rollback()
            print(f"Dry run: {sum(counts.values())} value(s) would change. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="commit (default: dry run)")
    sys.exit(asyncio.run(main(parser.parse_args().apply)))

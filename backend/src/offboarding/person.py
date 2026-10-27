"""Erasing one person from a business (docs/phase15/13 §6.6): a contact or caller asks the business.

The business's admin searches by e-mail or phone; every row of the business's
own tables whose text or JSON holds it is listed for review (``search``).
Confirmed (``erase``), rows of the tables that are about a person (a contact, a
call, a conversation) are deleted; elsewhere the matching value is replaced by
``[erased]``. Files those rows point at (recordings) are deleted from storage.
The request and its counts are logged; the value itself is not.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

# Rows that exist only because of the person: deleted whole.
PERSON_TABLES = frozenset({
    "voice_sessions", "call_logs", "conversation_history", "lead_queue", "whatsapp_sessions",
    "mobile_call_attempts", "contact_uploads",
})
TEXT_TYPES = ("text", "character varying", "jsonb", "json")
SEARCH_LIMIT = 500
MASK = "[erased]"


def _terms(query: str) -> List[str]:
    query = (query or "").strip()
    if "@" in query and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", query):
        return [query.lower()]
    digits = re.sub(r"\D", "", query)
    if len(digits) >= 8:
        return [digits[-10:]]
    raise HTTPException(status_code=422, detail="Search by an e-mail address or a phone number (8 digits or more)")


async def _columns(tdb: Any) -> Dict[str, List[tuple]]:
    rows = (await tdb.execute(text(
        "SELECT c.table_schema, c.table_name, c.column_name, c.data_type FROM information_schema.columns c "
        "WHERE c.table_schema = ANY(current_schemas(false)) AND c.data_type = ANY(:types) "
        "AND EXISTS (SELECT 1 FROM information_schema.columns k WHERE k.table_schema = c.table_schema "
        "AND k.table_name = c.table_name AND k.column_name = 'company_id') "
        "AND EXISTS (SELECT 1 FROM information_schema.columns k WHERE k.table_schema = c.table_schema "
        "AND k.table_name = c.table_name AND k.column_name = 'id')"), {"types": list(TEXT_TYPES)})).all()
    # The business's own data only: tenant-plane tables (in single mode the shared database
    # also holds the control plane — users, wallets — which this must never touch).
    from src.common.tenancy.bases import TENANT, plane_tables

    tenant_tables = {t.name for t in plane_tables(TENANT)}
    out: Dict[str, List[tuple]] = {}
    for schema, table, column, kind in rows:
        if table in tenant_tables or schema == "business":
            out.setdefault(f"{schema}.{table}", []).append((column, kind))
    return out


def _match(column: str, kind: str, term: str) -> str:
    target = f'"{column}"::text' if kind in ("jsonb", "json") else f'"{column}"'
    if term.isdigit():
        return f"regexp_replace(coalesce({target}, ''), '[^0-9]', '', 'g') LIKE '%' || :term || '%'"
    return f"lower(coalesce({target}, '')) LIKE '%' || :term || '%'"


async def search(company_id: UUID, query: str) -> Dict[str, Any]:
    from src.common.tenancy.session import tenant_session

    term = _terms(query)[0]
    found: List[Dict[str, Any]] = []
    async with tenant_session(company_id) as tdb:
        for qualified, cols in (await _columns(tdb)).items():
            where = " OR ".join(_match(c, k, term) for c, k in cols)
            hits = (await tdb.execute(text(
                f"SELECT id FROM {qualified} WHERE company_id = :c AND ({where}) LIMIT :n"),
                {"c": company_id, "term": term, "n": SEARCH_LIMIT})).scalars().all()
            for row_id in hits:
                found.append({"table": qualified.split(".", 1)[1], "id": str(row_id),
                              "action": "delete" if qualified.split(".", 1)[1] in PERSON_TABLES else "mask"})
    return {"matches": found, "count": len(found)}


async def erase(company_id: UUID, query: str, *, actor: Any) -> Dict[str, Any]:
    from src.common.platform.storage import get_storage
    from src.common.tenancy.session import control_session, tenant_session

    term = _terms(query)[0]
    deleted: Dict[str, int] = {}
    masked: Dict[str, int] = {}
    files: List[str] = []
    key_pattern = re.compile(r"\b((?:t|c)-[a-z0-9]{6,40}/[A-Za-z0-9_./-]+)")
    async with tenant_session(company_id) as tdb:
        for qualified, cols in (await _columns(tdb)).items():
            table = qualified.split(".", 1)[1]
            where = " OR ".join(_match(c, k, term) for c, k in cols)
            rows = (await tdb.execute(text(f"SELECT * FROM {qualified} WHERE company_id = :c AND ({where})"),
                                      {"c": company_id, "term": term})).mappings().all()
            if not rows:
                continue
            for row in rows:
                for value in row.values():
                    if isinstance(value, str):
                        files += key_pattern.findall(value)
            ids = [r["id"] for r in rows]
            if table in PERSON_TABLES:
                await tdb.execute(text(f"DELETE FROM {qualified} WHERE id = ANY(:ids)"), {"ids": ids})
                deleted[table] = len(ids)
                continue
            for column, kind in cols:
                if kind in ("jsonb", "json"):
                    pattern = term if not term.isdigit() else term
                    await tdb.execute(text(
                        f'UPDATE {qualified} SET "{column}" = CAST(regexp_replace("{column}"::text, :p, :m, \'gi\') '
                        f"AS {kind}) WHERE id = ANY(:ids) AND {_match(column, kind, term)}"),
                        {"p": re.escape(pattern), "m": MASK, "ids": ids, "term": term})
                else:
                    await tdb.execute(text(
                        f'UPDATE {qualified} SET "{column}" = :m WHERE id = ANY(:ids) AND {_match(column, kind, term)}'),
                        {"m": MASK, "ids": ids, "term": term})
            masked[table] = len(ids)
        await tdb.commit()
    storage = get_storage()
    for key in set(files):
        try:
            await storage.delete(key)
        except Exception:  # noqa: BLE001 - not a key after all
            pass
    async with control_session() as db:
        from src.common.admin_audit import record_admin_change

        record_admin_change(db, actor=actor, action="erase_person", object_type="data_request",
                            object_key=str(company_id), target_company_id=company_id,
                            new_value={"deleted": deleted, "masked": masked, "files": len(set(files))},
                            reason="a person asked to be erased")
        await db.commit()
    return {"deleted": deleted, "masked": masked, "files_deleted": len(set(files))}

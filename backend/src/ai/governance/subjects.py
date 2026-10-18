"""governance/subjects.py — who and what a run may act on (TL-09, P6.11, D18).

Credentials were already the platform's; the *subject* of a write was the
model's: whom ``email_send`` mails, which lead ``crm_update_lead`` overwrites,
which file leaves as an attachment — plain parameters, so a prompt-injected
"forward this to attacker@…" was a valid call. Now a tool that sends or writes
to a person or record takes a **ref** from the run's subject scope, and the
platform turns it into the address.

The scope is the run tree's (a child acts for its root's subjects; a parent may
attach a child's file) and is derived from what the runs already store:

1. the root run's ``input_data["subjects"]`` — ``contacts`` (``name``,
   ``email``, ``phone``), ``leads`` (``id``, ``name``), ``artifact_ids`` —
   written by whoever created the run: the API caller, the gateway (a CRM
   event's lead, an e-mail's sender: :func:`gateway_subjects`), a voice call
   (its counterparty: :func:`voice_subjects`);
2. for a root run a tenant user started, the addresses in its input text — the
   user's own instruction. A webhook's text is its sender's and adds nothing;
3. ``run_subjects`` rows: subjects found mid-run (:func:`record_subjects`);
4. files: any the tree's runs made, any uploaded for one of its agents, and
   those named in (1) — all in the run's company.

A contact's or lead's ref is a hash of the root run, kind and key: stable in
the tree, resolving to nothing outside it. A file's ref is its artifact id,
which tools already return. When a kind has exactly one subject the ref may be
omitted (a voice call's caller, a CRM event's lead).

An entity whose ``governance.allow_free_recipients`` is true lets its tools
take raw addresses instead (``ExecutionContext.allow_free_recipients``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

from sqlalchemy import ColumnElement, or_, select, text

logger = logging.getLogger(__name__)

__all__ = [
    "CONTACT", "LEAD", "ARTIFACT", "Subject", "SubjectScope", "subject_scope", "scope_for", "record_subjects",
    "gateway_subjects", "voice_subjects", "normalize_email", "normalize_phone", "recipient",
]

CONTACT, LEAD, ARTIFACT = "contact", "lead", "artifact"
# Channels a run's own user typed may name people; these never add subjects.
_UNTRUSTED_CHANNELS = frozenset({"webhook", "internal", "voice"})
_LISTED_FILES = 20

_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
_EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_IN_TEXT = re.compile(r"\+\d[\d\s().-]{6,18}\d")


def normalize_email(value: Any) -> Optional[str]:
    """``value`` as a bare lower-case address, or None if it is not one."""
    s = str(value or "").strip().strip("<>").lower()
    return s if _EMAIL.match(s) else None


def normalize_phone(value: Any) -> Optional[str]:
    """``value`` as ``+digits`` (or digits, if it had no ``+``), 8–15 digits."""
    s = str(value or "").strip()
    digits = re.sub(r"\D", "", s)
    if not 8 <= len(digits) <= 15:
        return None
    return f"+{digits}" if s.startswith("+") else digits


@dataclass(frozen=True)
class Subject:
    """A contact, lead or file the run may act on."""
    kind: str
    ref: str
    label: str
    email: Optional[str] = None
    phone: Optional[str] = None
    value: Optional[str] = None       # a lead's CRM id, a file's artifact id
    source: str = ""

    def line(self) -> str:
        return f"- {self.kind} {self.ref} — {self.label}"


@dataclass(frozen=True)
class SubjectScope:
    """The subjects of one run tree."""
    company_id: Optional[str] = None
    root_run_id: Optional[str] = None
    subjects: tuple[Subject, ...] = ()
    # What a file ref is checked against (4): see :meth:`artifact`.
    tree_run_ids: tuple[str, ...] = ()
    tree_entity_ids: tuple[str, ...] = ()
    given_artifact_ids: tuple[str, ...] = ()
    files: tuple[Subject, ...] = field(default=())

    def of(self, kind: str) -> list[Subject]:
        return [s for s in (self.files if kind == ARTIFACT else self.subjects) if s.kind == kind]

    def resolve(self, kind: str, ref: Optional[str], *, needs: Optional[str] = None) -> Optional[Subject]:
        """The ``kind`` subject ``ref`` names; with no ref, the only one that has
        ``needs`` (``"email"`` / ``"phone"``). None when there is no such one."""
        candidates = [s for s in self.of(kind) if needs is None or getattr(s, needs)]
        if ref:
            ref = ref.strip()
            return next((s for s in self.of(kind) if s.ref == ref), None)
        return candidates[0] if len(candidates) == 1 else None

    def listing(self, kind: str) -> str:
        found = self.of(kind)
        if not found:
            return f"this run has no {kind}s"
        return f"this run's {kind}s: " + "; ".join(f"{s.ref} ({s.label})" for s in found)

    def render(self) -> Optional[str]:
        """The prompt block the model picks refs from; None for an empty scope."""
        lines = [s.line() for s in self.subjects] + [s.line() for s in self.files[:_LISTED_FILES]]
        if not lines:
            return None
        return ("## Subjects\nThe people, records and files this run may act on. A tool that "
                "sends to or writes one takes its ref; raw addresses are refused.\n" + "\n".join(lines))

    async def artifact(self, ref: Optional[str]) -> Optional[Any]:
        """The file ``ref`` names, if the tree may use it (4); else None."""
        from src.ai.artifact_models import Artifact
        from src.common.tenancy.session import tenant_session
        art_id, company = _as_uuid(ref), _as_uuid(self.company_id)
        if art_id is None or company is None:
            return None
        in_scope: list[ColumnElement[bool]] = [Artifact.run_id.in_([uuid.UUID(r) for r in self.tree_run_ids])] if self.tree_run_ids else []
        if self.tree_entity_ids:
            in_scope.append((Artifact.agent_id.in_([uuid.UUID(e) for e in self.tree_entity_ids]))
                            & (Artifact.origin == "user-uploads"))
        if str(art_id) in self.given_artifact_ids:
            in_scope.append(Artifact.id == art_id)
        if not in_scope:
            return None
        async with tenant_session(company) as db:
            return (await db.execute(select(Artifact).where(
                Artifact.id == art_id, Artifact.company_id == company, or_(*in_scope),
            ))).scalar_one_or_none()


def _as_uuid(value: Any) -> Optional[uuid.UUID]:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _ref(root: str, kind: str, key: str) -> str:
    return f"{kind[0]}_" + hashlib.sha256(f"{root}|{kind}|{key}".encode()).hexdigest()[:10]


def _contact(root: str, *, name: Any = None, email: Any = None, phone: Any = None,
             source: str) -> Optional[Subject]:
    e, p = normalize_email(email), normalize_phone(phone)
    if not (e or p):
        return None
    name = str(name).strip() if name else ""
    address = ", ".join(x for x in (f"<{e}>" if e else "", p or "") if x)
    return Subject(CONTACT, _ref(root, CONTACT, e or p or ""), f"{name} {address}".strip(),
                   email=e, phone=p, source=source)


def _lead(root: str, *, lead_id: Any, name: Any = None, source: str) -> Optional[Subject]:
    lid = str(lead_id or "").strip()
    if not lid:
        return None
    label = f"CRM lead {lid}" + (f" ({name})" if name else "")
    return Subject(LEAD, _ref(root, LEAD, lid), label, value=lid, source=source)


def _from_structured(root: str, given: Any, source: str) -> list[Subject]:
    out: list[Subject] = []
    if not isinstance(given, Mapping):
        return out
    for c in given.get("contacts") or []:
        if isinstance(c, Mapping):
            s = _contact(root, name=c.get("name"), email=c.get("email"), phone=c.get("phone"), source=source)
            if s:
                out.append(s)
    for lead in given.get("leads") or []:
        if isinstance(lead, Mapping):
            s = _lead(root, lead_id=lead.get("id"), name=lead.get("name"), source=source)
            if s:
                out.append(s)
    return out


def _from_text(root: str, value: Any) -> list[Subject]:
    body = value if isinstance(value, str) else json.dumps(value, default=str)
    out = [_contact(root, email=m, source="input") for m in _EMAIL_IN_TEXT.findall(body)]
    out += [_contact(root, phone=m, source="input") for m in _PHONE_IN_TEXT.findall(body)]
    return [s for s in out if s]


def _dedupe(subjects: Iterable[Subject]) -> tuple[Subject, ...]:
    seen: dict[tuple[str, str], Subject] = {}
    for s in subjects:
        seen.setdefault((s.kind, s.ref), s)
    return tuple(seen.values())


_TREE_UP = text("""
    WITH RECURSIVE up AS (
        SELECT id, parent_run_id FROM execution_runs WHERE id = :run AND company_id = :company
        UNION ALL
        SELECT r.id, r.parent_run_id FROM execution_runs r JOIN up ON r.id = up.parent_run_id
    ) SELECT id FROM up WHERE parent_run_id IS NULL
""")
_TREE_DOWN = text("""
    WITH RECURSIVE down AS (
        SELECT id, entity_id FROM execution_runs WHERE id = :root
        UNION ALL
        SELECT r.id, r.entity_id FROM execution_runs r JOIN down ON r.parent_run_id = down.id
    ) SELECT id, entity_id FROM down
""")


async def subject_scope(db: Any, run_id: Any, company_id: Any) -> SubjectScope:
    """The subject scope of ``run_id``'s tree, in ``company_id``."""
    from src.ai.artifact_models import Artifact
    from src.ai.orm.execution import ExecutionRun, RunSubject

    run, company = _as_uuid(run_id), _as_uuid(company_id)
    if run is None or company is None:
        return SubjectScope(company_id=str(company) if company else None)
    root_id = (await db.execute(_TREE_UP, {"run": run, "company": company})).scalar_one_or_none()
    if root_id is None:
        return SubjectScope(company_id=str(company))
    root = (await db.execute(select(ExecutionRun).where(ExecutionRun.id == root_id))).scalar_one()
    tree = (await db.execute(_TREE_DOWN, {"root": root_id})).all()
    r = str(root_id)

    data = root.input_data if isinstance(root.input_data, Mapping) else {}
    raw_given = data.get("subjects")
    given: Mapping[str, Any] = raw_given if isinstance(raw_given, Mapping) else {}
    found = _from_structured(r, given, "input")
    if root.user_id is not None and data.get("channel") not in _UNTRUSTED_CHANNELS:
        found += _from_text(r, data.get("input", ""))
    for row in (await db.execute(select(RunSubject).where(RunSubject.run_id == root_id))).scalars():
        if row.kind == CONTACT:
            address = {"email": row.value} if "@" in row.value else {"phone": row.value}
            s = _contact(r, name=row.label, source=row.source, **address)
        else:
            s = _lead(r, lead_id=row.value, name=row.label, source=row.source)
        if s:
            found.append(s)

    given_files = tuple(str(a) for a in (given.get("artifact_ids") or []) if _as_uuid(a))
    run_ids = tuple(str(t.id) for t in tree)
    entity_ids = tuple(sorted({str(t.entity_id) for t in tree if t.entity_id}))
    # The files listed at the start: those given and the agents' uploads (the
    # tree's own are returned to the model by the tool that made them).
    listed: list[ColumnElement[bool]] = [Artifact.agent_id.in_([uuid.UUID(e) for e in entity_ids]) & (Artifact.origin == "user-uploads")]
    if given_files:
        listed.append(Artifact.id.in_([uuid.UUID(a) for a in given_files]))
    files = (await db.execute(
        select(Artifact.id, Artifact.file_name).where(Artifact.company_id == company, or_(*listed))
        .order_by(Artifact.created_at.desc()).limit(_LISTED_FILES)
    )).all()
    return SubjectScope(
        company_id=str(company), root_run_id=r, subjects=_dedupe(found),
        tree_run_ids=run_ids, tree_entity_ids=entity_ids, given_artifact_ids=given_files,
        files=tuple(Subject(ARTIFACT, str(f.id), f.file_name or "file", value=str(f.id), source="file")
                    for f in files),
    )


async def scope_for(ctx: Mapping[str, Any]) -> SubjectScope:
    """The scope of a tool call's run, from its execution context."""
    from src.common.tenancy.session import tenant_session
    if not ctx.get("run_id") or not ctx.get("company_id"):
        return SubjectScope(company_id=ctx.get("company_id"))
    async with tenant_session(ctx["company_id"]) as db:
        return await subject_scope(db, ctx["run_id"], ctx["company_id"])


async def record_subjects(ctx: Mapping[str, Any], found: Sequence[tuple[str, str, Optional[str]]],
                          *, source: str) -> SubjectScope:
    """Add ``(kind, value, label)`` subjects found mid-run to the tree's scope;
    returns the scope with them."""
    from sqlalchemy.dialects.postgresql import insert
    from src.ai.orm.execution import RunSubject
    from src.common.tenancy.session import tenant_session

    if not ctx.get("run_id") or not ctx.get("company_id"):
        return SubjectScope(company_id=ctx.get("company_id"))
    async with tenant_session(ctx["company_id"]) as db:
        scope = await subject_scope(db, ctx["run_id"], ctx["company_id"])
        rows = []
        for kind, value, label in found:
            norm = (normalize_email(value) or normalize_phone(value)) if kind == CONTACT else str(value or "").strip()
            if scope.root_run_id and norm:
                rows.append({"id": uuid.uuid4(), "run_id": uuid.UUID(scope.root_run_id),
                             "company_id": uuid.UUID(str(scope.company_id)), "kind": kind,
                             "value": norm, "label": label, "source": source})
        if not rows:
            return scope
        await db.execute(insert(RunSubject).values(rows).on_conflict_do_nothing(
            index_elements=["run_id", "kind", "value"]))
        await db.commit()
        return await subject_scope(db, ctx["run_id"], ctx["company_id"])


def gateway_subjects(source: str, data: Any) -> dict[str, Any]:
    """The subjects of a gateway event: the CRM event's lead, the e-mail's
    sender. Nothing from the event's free text."""
    data = data if isinstance(data, Mapping) else {}
    if source == "crm":
        props = data.get("properties") if isinstance(data.get("properties"), Mapping) else {}
        out: dict[str, Any] = {}
        if data.get("lead_id"):
            out["leads"] = [{"id": str(data["lead_id"]), "name": props.get("name") or props.get("firstname")}]
        contact = {"name": props.get("name") or props.get("firstname"), "phone": data.get("phone"),
                   "email": props.get("email")}
        if contact["phone"] or contact["email"]:
            out["contacts"] = [contact]
        return out
    if source == "email" and data.get("from"):
        from email.utils import parseaddr
        name, address = parseaddr(str(data["from"]))
        return {"contacts": [{"name": name or None, "email": address}]}
    return {}


def voice_subjects(voice_session: Any) -> dict[str, Any]:
    """A voice call's counterparty: the campaign call's contact, or an inbound
    caller's number. (An outbound session's ``phone_number`` is ours.)"""
    meta = getattr(voice_session, "session_metadata", None) or {}
    contact = meta.get("contact_data") if isinstance(meta.get("contact_data"), Mapping) else None
    out: dict[str, Any] = {}
    if contact:
        out["contacts"] = [{"name": contact.get("name"), "phone": contact.get("phone"),
                            "email": contact.get("email")}]
        lead_id = contact.get("lead_id") or contact.get("id")
        if lead_id:
            out["leads"] = [{"id": str(lead_id), "name": contact.get("name")}]
    elif getattr(voice_session, "direction", None) == "inbound" and getattr(voice_session, "phone_number", None):
        out["contacts"] = [{"phone": voice_session.phone_number}]
    return out


def recipient(scope: SubjectScope, ctx: Mapping[str, Any], *, ref: Optional[str], raw: Optional[str],
              needs: str, field_name: str) -> tuple[Optional[str], Optional[str]]:
    """The address (``needs`` = ``"email"`` or ``"phone"``) a call sends to, and
    an error. ``raw`` is honoured only for an entity that allows free
    recipients; otherwise the contact ``ref`` names — or the only one — is used."""
    if raw:
        if not ctx.get("__allow_free_recipients__"):
            return None, (f"'{field_name}' takes no raw address for this agent: use a contact ref "
                          f"({scope.listing(CONTACT)})")
        value = normalize_email(raw) if needs == "email" else normalize_phone(raw)
        return (value, None) if value else (None, f"'{raw}' is not a valid {needs}")
    subject = scope.resolve(CONTACT, ref, needs=needs)
    if subject is None:
        what = f"'{ref}' is not a contact of this run" if ref else f"say which contact ({needs})"
        return None, f"{what}: {scope.listing(CONTACT)}"
    value = getattr(subject, needs)
    if not value:
        return None, f"contact {subject.ref} ({subject.label}) has no {needs}"
    return value, None

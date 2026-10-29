"""What a business's AI assistant follows in conversations with its customers
(META-E4, META-E5; docs/phase15/14_connector_approvals/01 §5–§6).

* **It says it is an AI.** Its first reply in a conversation, its first after a
  long gap (``DISCLOSURE_GAP``) and its first after a person hands the
  conversation back begin with ``disclosure()``.
* **A person can take over.** A customer who asks for one ("talk to a person",
  "human" …) is handed off: the assistant stops answering, the business's
  admins are told, and the customer hears that a person will reply. The
  business hands it back on its Conversations screen.
* **WhatsApp's service window.** Within 24 hours of the customer's last
  message the business may write freely; outside it, only an approved
  template, and only to a customer who opted in (``messaging_opt_ins``). STOP
  opts a customer out, START back in.
* **Business-specific assistants only on WhatsApp** (Meta's 2026 policy): the
  assistant's instructions end with ``WHATSAPP_SCOPE``.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.messaging.models import MessagingConversation, MessagingOptIn

logger = logging.getLogger(__name__)

DISCLOSURE_GAP = timedelta(hours=24)
SERVICE_WINDOW = timedelta(hours=24)
CHANNEL_LABELS = {"messenger": "Messenger", "instagram": "Instagram", "whatsapp": "WhatsApp"}

# A whole message that is one of these asks for a person; so does a message containing a phrase.
_PERSON_WORDS = frozenset({"human", "person", "agent", "representative", "operator", "staff", "someone",
                           "real person", "a person", "a human", "human please", "person please", "agent please"})
_PERSON_PHRASES = ("talk to a person", "talk to someone", "talk to a human", "talk to a real", "speak to a person",
                   "speak to someone", "speak to a human", "speak with a person", "speak with someone",
                   "chat with a person", "chat with a human", "real person", "customer care", "customer service",
                   "human agent", "live agent", "connect me to")
OPT_OUT_WORDS = frozenset({"stop", "unsubscribe", "stop all", "opt out", "optout"})
OPT_IN_WORDS = frozenset({"start", "subscribe", "unstop", "opt in", "optin"})

WHATSAPP_SCOPE = (
    "\n\n## Scope (WhatsApp)\nYou are {business}'s assistant on WhatsApp. Help only with {business}: its "
    "products, services, orders, bookings and support. If you are asked for anything unrelated to {business} "
    "(general knowledge, writing, coding, advice on other subjects), say politely that you can only help with "
    "{business}, and offer to connect the customer with a person from the team.")


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", (text or "").lower())).strip()


def wants_person(text: str) -> bool:
    message = _normal(text)
    return message in _PERSON_WORDS or any(phrase in message for phrase in _PERSON_PHRASES)


def opt_keyword(text: str) -> Optional[str]:
    """``out`` for STOP and its kind, ``in`` for START, else ``None`` (the whole message only)."""
    message = _normal(text)
    return "out" if message in OPT_OUT_WORDS else "in" if message in OPT_IN_WORDS else None


def whatsapp_agent_problem(agent: Any) -> Optional[str]:
    """Why an agent may not answer a business's customers on WhatsApp, or ``None``
    (META-E5: business-specific assistants only, no general-purpose one)."""
    tags = {str(t).lower() for t in agent.tags} if isinstance(getattr(agent, "tags", None), list) else set()
    if tags & {"meta_agent", "system"}:
        return ("HireBuddha's own builder assistant can't answer customers on WhatsApp: WhatsApp allows only "
                "assistants built for one business. Assign an agent made for this business.")
    if len((getattr(agent, "description", None) or "").strip()) < 20:
        return ("Describe what this agent does for the business (at least a sentence) before it answers on "
                "WhatsApp: WhatsApp allows only assistants built for one business.")
    return None


def disclosure(business: str) -> str:
    return f"You're chatting with {business}'s AI assistant. Reply \"person\" at any time to reach someone from the team."


def handoff_reply(business: str) -> str:
    return f"Thanks — I've asked someone from {business} to reply. They'll answer here as soon as they can."


async def business_name(company_id: Any) -> str:
    from src.auth.models import Company
    from src.common.tenancy.session import control_session

    try:
        async with control_session() as db:
            name = (await db.execute(select(Company.name).where(Company.id == uuid.UUID(str(company_id))))).scalar()
    except Exception:  # noqa: BLE001 - a name is a courtesy; the rule holds without it
        name = None
    return str(name or "this business")


# ── Conversations ───────────────────────────────────────────────────────────

async def _conversation(db: Any, company_id: Any, channel: str, account_id: str, contact_id: str,
                        now: datetime) -> MessagingConversation:
    whatsapp = channel == "whatsapp"   # numbers kept as digits, however the provider wrote them
    key = {"company_id": uuid.UUID(str(company_id)), "channel": channel,
           "account_id": normal_number(account_id) if whatsapp else str(account_id),
           "contact_id": normal_number(contact_id) if whatsapp else str(contact_id)}
    await db.execute(pg_insert(MessagingConversation).values(id=uuid.uuid4(), created_at=now, updated_at=now, **key)
                     .on_conflict_do_nothing(index_elements=list(key)))
    return (await db.execute(select(MessagingConversation).filter_by(**key))).scalar_one()


@dataclass
class Inbound:
    """What a customer's message did: the conversation, and what to answer at once (if anything)."""
    conversation_id: str
    with_person: bool             # a person has the conversation: the assistant does not answer
    reply: Optional[str] = None   # the platform's own answer (hand-off, STOP, START)
    opted: Optional[str] = None


async def inbound(company_id: Any, channel: str, account_id: str, contact_id: str, text: str, *,
                  now: Optional[datetime] = None) -> Inbound:
    """A customer wrote: the window opens, STOP / START are recorded (WhatsApp), and
    a request for a person hands the conversation off."""
    from src.common.tenancy.session import tenant_session

    at = now or datetime.utcnow()
    async with tenant_session(company_id) as db:
        conversation = await _conversation(db, company_id, channel, account_id, contact_id, at)
        conversation.last_inbound_at, conversation.updated_at = at, at
        result = Inbound(conversation_id=str(conversation.id), with_person=conversation.handed_off_at is not None)
        opted = opt_keyword(text) if channel == "whatsapp" else None
        if opted:
            await _record_opt(db, company_id, channel, conversation.contact_id, opted, source="keyword",
                              evidence=(text or "").strip()[:200], by="customer", now=at)
            business = await business_name(company_id)
            result.opted = opted
            result.reply = (f"You won't get messages from {business} here any more. Reply START to change your mind."
                            if opted == "out" else f"Thanks, you'll get updates from {business} here. Reply STOP to stop them.")
        elif not result.with_person and wants_person(text):
            conversation.handed_off_at, conversation.handoff_reason = at, (text or "").strip()[:300]
            result.with_person = True
            result.reply = handoff_reply(await business_name(company_id))
        await db.commit()
    if result.with_person and result.reply:   # just handed off: the team hears of it
        await _tell_team(company_id, channel, result.conversation_id, at)
    return result


async def _tell_team(company_id: Any, channel: str, conversation_id: str, at: datetime) -> None:
    from src.notifications.service import notify

    await notify(company_id, kind="conversation_handoff",
                 title=f"A customer asked for a person on {CHANNEL_LABELS.get(channel, channel)}",
                 body="The AI assistant has stopped answering this conversation. Reply to the customer, then hand it "
                      "back on the Conversations screen.",
                 dedupe_key=f"handoff:{conversation_id}:{at:%Y%m%d%H%M}", link="/conversations",
                 audience="operators", severity="warning")


@dataclass
class Reply:
    """What the assistant may send: ``refusal`` when it may not, else ``text`` (with the disclosure when due)."""
    text: str
    refusal: Optional[str] = None
    disclosed: bool = False


async def before_reply(company_id: Any, channel: str, account_id: str, contact_id: str, text: str, *,
                       now: Optional[datetime] = None) -> Reply:
    from src.common.tenancy.session import tenant_session

    at = now or datetime.utcnow()
    async with tenant_session(company_id) as db:
        conversation = await _conversation(db, company_id, channel, account_id, contact_id, at)
        await db.commit()
    if conversation.handed_off_at is not None:
        return Reply(text=text, refusal=(
            "A person from the team has this conversation (the customer asked for one); the AI assistant answers "
            "again once they hand it back on the Conversations screen."))
    last = conversation.last_ai_at
    due = last is None or at - last > DISCLOSURE_GAP or (
        conversation.handed_back_at is not None and conversation.handed_back_at > last)
    if not due:
        return Reply(text=text)
    return Reply(text=f"{disclosure(await business_name(company_id))}\n\n{text}", disclosed=True)


async def replied(company_id: Any, channel: str, account_id: str, contact_id: str, *, disclosed: bool,
                  now: Optional[datetime] = None) -> None:
    from src.common.tenancy.session import tenant_session

    at = now or datetime.utcnow()
    async with tenant_session(company_id) as db:
        conversation = await _conversation(db, company_id, channel, account_id, contact_id, at)
        conversation.last_ai_at, conversation.updated_at = at, at
        if disclosed:
            conversation.disclosed_at = at
        await db.commit()


async def hand_back(db: Any, company_id: Any, conversation_id: Any, user_id: Any, *,
                    now: Optional[datetime] = None) -> Optional[MessagingConversation]:
    """The team is done: the assistant answers again, saying first that it is one (the caller commits)."""
    conversation = (await db.execute(select(MessagingConversation).where(
        MessagingConversation.id == uuid.UUID(str(conversation_id)),
        MessagingConversation.company_id == uuid.UUID(str(company_id))))).scalar_one_or_none()
    if conversation is None:
        return None
    at = now or datetime.utcnow()
    conversation.handed_off_at, conversation.handoff_reason = None, None
    conversation.handed_back_at, conversation.handed_back_by, conversation.updated_at = at, user_id, at
    return conversation


# ── WhatsApp: the window and opt-ins ────────────────────────────────────────

async def _record_opt(db: Any, company_id: Any, channel: str, contact_id: str, status: str, *, source: str,
                      evidence: Optional[str], by: Optional[str], now: datetime) -> None:
    values = {"company_id": uuid.UUID(str(company_id)), "channel": channel, "contact_id": str(contact_id),
              "status": status, "source": source, "evidence": evidence, "recorded_by": by, "recorded_at": now}
    statement = pg_insert(MessagingOptIn).values(id=uuid.uuid4(), **values)
    await db.execute(statement.on_conflict_do_update(
        index_elements=["company_id", "channel", "contact_id"],
        set_={k: statement.excluded[k] for k in ("status", "source", "evidence", "recorded_by", "recorded_at")}))


async def record_opt(db: Any, company_id: Any, contact_id: str, status: str, *, source: str,
                     evidence: Optional[str] = None, by: Optional[str] = None, channel: str = "whatsapp",
                     now: Optional[datetime] = None) -> None:
    """Record a contact's opt-in or opt-out (the caller commits)."""
    await _record_opt(db, company_id, channel, normal_number(contact_id), status, source=source, evidence=evidence,
                      by=by, now=now or datetime.utcnow())


def normal_number(number: str) -> str:
    """A WhatsApp number as conversations store it: digits only (Twilio's ``whatsapp:+…`` and Tata's plain)."""
    return re.sub(r"\D", "", str(number or ""))


async def business_initiated_refusal(company_id: Any, contact_id: str, *, template: Optional[str],
                                     by_person: bool = False, now: Optional[datetime] = None) -> Optional[str]:
    """Why the business may not message this WhatsApp contact now, or ``None`` (META-E5).

    Inside the 24-hour window (the customer wrote last within it) anything may be
    sent; outside it, only an approved template to a contact who opted in. A
    conversation a person has taken over is theirs, so no agent writes into it
    (``by_person``: the team's own send).
    """
    from src.common.tenancy.session import tenant_session

    at = now or datetime.utcnow()
    number = normal_number(contact_id)
    async with tenant_session(company_id) as db:
        rows = (await db.execute(select(MessagingConversation).where(
            MessagingConversation.company_id == uuid.UUID(str(company_id)),
            MessagingConversation.channel == "whatsapp", MessagingConversation.contact_id == number))).scalars().all()
        opt = (await db.execute(select(MessagingOptIn.status).where(
            MessagingOptIn.company_id == uuid.UUID(str(company_id)), MessagingOptIn.channel == "whatsapp",
            MessagingOptIn.contact_id == number))).scalar()
    if not by_person and any(r.handed_off_at is not None for r in rows):
        return "A person from the team has this customer's WhatsApp conversation; the AI assistant waits until it is handed back."
    if opt == "out":
        return "This customer replied STOP: they get no messages the business starts until they reply START."
    window = any(r.last_inbound_at is not None and at - r.last_inbound_at <= SERVICE_WINDOW for r in rows)
    if window:
        return None
    if not template:
        return ("Outside WhatsApp's 24-hour customer service window (the customer last wrote more than 24 hours "
                "ago, or never): only an approved message template may be sent.")
    if opt != "in":
        return ("This customer has not opted in to messages from the business on WhatsApp; record their opt-in "
                "(Customers & calls → Conversations) before sending a template.")
    return None

"""
Email AI Agent Tools using IMAP/SMTP.

Provides four tools for AI agents to interact with customer inboxes:
- EmailIngestTool: Monitor and fetch emails via IMAP IDLE
- EmailClassifyTool: Classify emails into folders via IMAP MOVE
- EmailDraftTool: Create draft replies via IMAP APPEND
- EmailSendTool: Send emails via SMTP

The account is the company's connection (``email_address`` may pick one of
them). Whom a message goes to is not the model's to choose: ``email_send`` and
``email_draft`` take contact refs from the run's subject scope, and the file
an e-mail carries is an artifact of the run (TL-09). ``email_ingest`` adds the
senders it reads to that scope, so a reply can be addressed.
"""
import asyncio
import logging
import json
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from typing import Dict, Any, List, Optional
import os
import re

from pydantic import Field

from src.ai.governance.subjects import CONTACT, SubjectScope, normalize_email, record_subjects, recipient, scope_for
from src.ai.tools.base import NO_CONTEXT_ERROR, Tool, ToolOutput, ToolParams, context_company_id

logger = logging.getLogger(__name__)

# Try to import html2text for HTML sanitization
try:
    import html2text
    HTML2TEXT_AVAILABLE = True
except ImportError:
    HTML2TEXT_AVAILABLE = False
    logger.warning("html2text not installed, HTML emails will use basic fallback stripping")


def _sanitize_html(html_content: str) -> str:
    """Convert HTML email content to clean Markdown/plain text."""
    if HTML2TEXT_AVAILABLE:
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.body_width = 0  # Don't wrap lines
        return h.handle(html_content).strip()
    else:
        # Basic fallback: strip HTML tags
        clean = re.sub(r'<[^>]+>', '', html_content)
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()


def _parse_email_body(msg: email.message.Message) -> str:
    """Extract and sanitize email body from MIME message."""
    body = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            
            # Skip attachments
            if "attachment" in content_disposition:
                continue
            
            if content_type == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                try:
                    body = part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    body = str(part.get_payload(decode=True))
                break  # Prefer plain text
            elif content_type == "text/html" and not body:
                charset = part.get_content_charset() or "utf-8"
                try:
                    html = part.get_payload(decode=True).decode(charset, errors="replace")
                    body = _sanitize_html(html)
                except Exception:
                    body = str(part.get_payload(decode=True))
    else:
        content_type = msg.get_content_type()
        charset = msg.get_content_charset() or "utf-8"
        try:
            payload = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            payload = str(msg.get_payload(decode=True))
        
        if content_type == "text/html":
            body = _sanitize_html(payload)
        else:
            body = payload
    
    return body


# A mail server that does not answer gives up after this (TL-57); without it a
# call waited for the OS TCP timeout. The IMAP/SMTP work itself runs in a
# thread (``asyncio.to_thread``): the libraries block, and the worker's event
# loop serves every other run meanwhile.
_MAIL_TIMEOUT_S = 30


def _get_imap_connection(imap_host: str, imap_port: int, email_address: str, password: str) -> imaplib.IMAP4_SSL:
    """Create and authenticate an IMAP connection."""
    conn = imaplib.IMAP4_SSL(imap_host, imap_port, timeout=_MAIL_TIMEOUT_S)
    conn.login(email_address, password)
    return conn


def _get_smtp_connection(smtp_host: str, smtp_port: int, email_address: str, password: str) -> smtplib.SMTP:
    """Create and authenticate an SMTP connection."""
    server = smtplib.SMTP(smtp_host, smtp_port, timeout=_MAIL_TIMEOUT_S)
    server.starttls()
    server.login(email_address, password)
    return server


async def _resolve_connection(company_id: Optional[str], email_address: Optional[str] = None) -> Dict[str, Any]:
    """Look up email credentials from EmailConnection table for the company."""
    if not company_id:
        return {}
        
    try:
        from uuid import UUID as _UUID
        from src.common.tenancy.session import tenant_session
        from sqlalchemy import select
        from src.ai.email_models import EmailConnection
        from src.common.security import decrypt_api_key

        async with tenant_session(company_id) as db:
            company_uuid = _UUID(str(company_id))
            query = select(EmailConnection).where(EmailConnection.company_id == company_uuid)
            
            if email_address:
                query = query.where(EmailConnection.email_address == email_address)
            
            result = await db.execute(query)
            conn = result.scalars().first()
            
            if conn:
                return {
                    "email_address": conn.email_address,
                    "password": decrypt_api_key(conn.encrypted_app_password),
                    "imap_host": conn.imap_host,
                    "imap_port": conn.imap_port,
                    "smtp_host": conn.smtp_host,
                    "smtp_port": conn.smtp_port
                }
    except Exception as e:
        logger.error(f"Failed to resolve email connection: {e}")
    
    return {}


class EmailIngestTool(Tool):
    """
    Monitor and fetch new emails from an inbox via IMAP.
    
    Fetches the latest email(s), parses MIME content, and returns
    structured data (body, subject, sender, message-id) with 
    HTML sanitized to Markdown.
    """
    name = "email_ingest"
    description = (
        "Fetch and read the latest emails from an inbox. "
        "Will automatically use company credentials if not provided."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "email_address": {"type": "string", "description": "Optional email address (if none, uses company default)"},
                    "count": {"type": "integer", "description": "Number of emails to fetch (default: 5)"},
                    "unread_only": {"type": "boolean", "description": "Only fetch unread emails (default: true)"}
                }
            }
        }

    async def run(self, input_data: str) -> str:
        return await self.run_with_context(input_data, None)

    async def run_with_context(self, input_data: str, context: Optional[Dict[str, Any]] = None) -> str:
        try:
            params = json.loads(input_data)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON input"})

        # Resolve credentials
        company_id = context_company_id(context)
        if not company_id:
            return json.dumps({"error": NO_CONTEXT_ERROR})
        resolved = await _resolve_connection(company_id, params.get("email_address"))
        
        # Server, account and password come from the company's connection row
        # only. ``email_address`` may pick which of the company's connections;
        # it cannot point the tool at another server or supply a password
        # (TL-04, TL-56).
        imap_host = resolved.get("imap_host")
        imap_port = resolved.get("imap_port") or 993
        email_address = resolved.get("email_address")
        password = resolved.get("password")
        folder = params.get("folder", "INBOX")
        count = params.get("count", 5)
        unread_only = params.get("unread_only", True)
        
        if not all([imap_host, email_address, password]):
            return json.dumps({"error": "Missing email credentials. Please configure an Email Connection for this company first."})

        def _fetch() -> Dict[str, Any]:
            conn = _get_imap_connection(imap_host, imap_port, email_address, password)
            try:
                conn.select(folder)
                # UIDs, not sequence numbers: a sequence number changes after
                # every expunge, so email_classify moved the wrong message (TL-58).
                status, data = conn.uid("SEARCH", None, "UNSEEN" if unread_only else "ALL")
                if status != "OK":
                    return {"error": "Failed to search emails"}
                uids = data[0].split()
                if not uids:
                    return {"emails": [], "count": 0, "message": "No emails found"}
                emails = []
                for uid in reversed(uids[-count:]):
                    status, msg_data = conn.uid("FETCH", uid, "(RFC822)")
                    if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    body = _parse_email_body(msg)
                    if len(body) > 5000:  # the model's context window
                        body = body[:5000] + "\n\n[... truncated for context window ...]"
                    attachments = []  # names and sizes only
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get("Content-Disposition") and "attachment" in str(part.get("Content-Disposition", "")):
                                attachments.append({"filename": part.get_filename() or "unnamed",
                                                    "size_bytes": len(part.get_payload(decode=True) or b"")})
                    emails.append({
                        "uid": uid.decode(),
                        "message_id": msg.get("Message-ID", ""),
                        "from": msg.get("From", ""),
                        "to": msg.get("To", ""),
                        "subject": msg.get("Subject", ""),
                        "date": msg.get("Date", ""),
                        "body": body,
                        "attachments": attachments,
                    })
                return {"emails": emails, "count": len(emails)}
            finally:
                try:
                    conn.logout()
                except Exception:  # noqa: BLE001
                    pass

        try:
            result = await asyncio.to_thread(_fetch)
        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP error: {e}")
            return json.dumps({"error": f"IMAP connection failed: {str(e)}"})
        except Exception as e:
            logger.error(f"Email ingest error: {e}", exc_info=True)
            return json.dumps({"error": f"Email ingest failed: {str(e)}"})
        if result.get("emails"):
            await _add_senders(context or {}, result["emails"])
        return json.dumps(result)


async def _add_senders(context: Dict[str, Any], emails: List[Dict[str, Any]]) -> None:
    """Record each fetched message's sender in the run's subject scope and
    give the message its ``contact_ref``, so ``email_draft`` / ``email_send``
    can reply (TL-09). A message read from the tenant's inbox is the run's."""
    from email.utils import parseaddr
    senders = []
    for e in emails:
        name, address = parseaddr(e.get("from") or "")
        if normalize_email(address):
            senders.append((CONTACT, address, name or None))
    if not senders:
        return
    try:
        scope = await record_subjects(context, senders, source="email_ingest")
    except Exception as exc:  # noqa: BLE001 - the mail was read; replying needs the scope
        logger.warning(f"Could not record the senders as subjects: {exc}")
        return
    by_address = {s.email: s.ref for s in scope.of(CONTACT) if s.email}
    for e in emails:
        ref = by_address.get(normalize_email(parseaddr(e.get("from") or "")[1]) or "")
        if ref:
            e["contact_ref"] = ref


class EmailClassifyTool(Tool):
    """
    Classify emails by moving them to AI-created IMAP folders.
    Reflects classification directly in the user's email client.
    """
    name = "email_classify"
    description = (
        "Classify an email by moving it to an AI-created folder. "
        "Will automatically use company credentials if not provided. "
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "email_address": {"type": "string"},
                    "uid": {"type": "string", "description": "Email UID to classify"},
                    "category": {"type": "string", "description": "Category name (e.g. 'Refunds', 'Sales')"},
                    "source_folder": {"type": "string", "description": "Source folder (default: INBOX)"}
                },
                "required": ["uid", "category"]
            }
        }

    async def run(self, input_data: str) -> str:
        return await self.run_with_context(input_data, None)

    async def run_with_context(self, input_data: str, context: Optional[Dict[str, Any]] = None) -> str:
        try:
            params = json.loads(input_data)
        except json.JSONDecodeError:
            return json.dumps({"error": "Invalid JSON input"})

        # Resolve credentials
        company_id = context_company_id(context)
        if not company_id:
            return json.dumps({"error": NO_CONTEXT_ERROR})
        resolved = await _resolve_connection(company_id, params.get("email_address"))

        # Server, account and password come from the company's connection row
        # only. ``email_address`` may pick which of the company's connections;
        # it cannot point the tool at another server or supply a password
        # (TL-04, TL-56).
        imap_host = resolved.get("imap_host")
        imap_port = resolved.get("imap_port") or 993
        email_address = resolved.get("email_address")
        password = resolved.get("password")
        uid = params.get("uid")
        category = params.get("category")
        source_folder = params.get("source_folder", "INBOX")
        
        if not all([imap_host, email_address, password, uid, category]):
            return json.dumps({"error": "Missing required parameters or email credentials."})

        def _move() -> Dict[str, Any]:
            conn = _get_imap_connection(imap_host, imap_port, email_address, password)
            try:
                folder_prefix = "[Gmail]/" if "gmail" in imap_host.lower() else ""
                target_folder = f"{folder_prefix}AI-Classified/{category}"
                status, folder_list = conn.list('', target_folder)
                if status != "OK" or not folder_list or folder_list[0] is None:
                    logger.info(f"Creating IMAP folder: {target_folder}")
                    conn.create(target_folder)
                    conn.subscribe(target_folder)
                conn.select(source_folder)
                # By UID (the one email_ingest returns), atomically where the
                # server can (RFC 6851) — TL-58, TL-39.
                if "MOVE" in getattr(conn, "capabilities", ()):
                    status, _ = conn.uid("MOVE", uid, target_folder)
                    if status != "OK":
                        return {"error": f"Failed to move email {uid} to {target_folder}"}
                else:
                    status, _ = conn.uid("COPY", uid, target_folder)
                    if status != "OK":
                        return {"error": f"Failed to copy email {uid} to {target_folder}"}
                    conn.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
                    if "UIDPLUS" in getattr(conn, "capabilities", ()):
                        conn.uid("EXPUNGE", uid)
                    else:
                        conn.expunge()
                return {"success": True, "uid": uid, "moved_to": target_folder, "category": category}
            finally:
                try:
                    conn.logout()
                except Exception:  # noqa: BLE001
                    pass

        try:
            return json.dumps(await asyncio.to_thread(_move))

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP classify error: {e}")
            return json.dumps({"error": f"Email classification failed: {str(e)}"})
        except Exception as e:
            logger.error(f"Email classify error: {e}", exc_info=True)
            return json.dumps({"error": f"Classification failed: {str(e)}"})


def _drafts_folder(imap_host: str) -> str:
    return "[Gmail]/Drafts" if "gmail" in imap_host.lower() else "Drafts"


def _body_parts(body: str) -> MIMEMultipart:
    """The body as text and html alternatives."""
    part = MIMEMultipart("alternative")
    part.attach(MIMEText(body, "plain", "utf-8"))
    html_body = body.replace("\n", "<br>")
    part.attach(MIMEText(f"<html><body>{html_body}</body></html>", "html", "utf-8"))
    return part


def _addresses(scope: SubjectScope, ctx: Dict[str, Any], refs: List[str], raw: Optional[str],
               field_name: str) -> tuple[List[str], Optional[str]]:
    """The e-mail addresses ``refs`` name, plus ``raw`` (comma-separated) for an
    agent that allows free recipients; or an error."""
    out: List[str] = []
    for ref in refs:
        value, error = recipient(scope, ctx, ref=ref, raw=None, needs="email", field_name=field_name)
        if error:
            return [], error
        out.append(value or "")
    for item in (raw or "").split(","):
        if item.strip():
            value, error = recipient(scope, ctx, ref=None, raw=item.strip(), needs="email", field_name=field_name)
            if error:
                return [], error
            out.append(value or "")
    return out, None


_TO_REF = ("Ref of the contact to write to, from the run's Subjects list (an email_ingest message's "
           "contact_ref for a reply). May be omitted when the run has one contact with an e-mail.")
_RAW = "A raw address: only for an agent that allows free recipients."


class EmailDraftParams(ToolParams):
    original_message_id: str = Field(..., description="Message-ID of the email being replied to")
    draft_body: str = Field(..., description="Body text for the draft reply")
    subject: str = Field(..., description="Email subject (usually 'Re: original subject')")
    to_ref: Optional[str] = Field(None, description=_TO_REF)
    to: Optional[str] = Field(None, description=_RAW)
    email_address: Optional[str] = Field(None, description="Which of the company's mailboxes (default: the first)")


class EmailDraftTool(Tool):
    """
    Create draft email replies directly in the user's Drafts folder.
    Maintains thread context via In-Reply-To and References headers.
    """
    name = "email_draft"
    description = (
        "Create a draft reply to an email in the company mailbox's Drafts folder, addressed to a "
        "contact of this run (to_ref)."
    )
    Params = EmailDraftParams

    async def execute(self, params: EmailDraftParams, ctx: Dict[str, Any]) -> ToolOutput:
        company_id = context_company_id(ctx)
        if not company_id:
            return ToolOutput.failed(NO_CONTEXT_ERROR, code="no_context")
        scope = await scope_for(ctx)
        to_addr, error = recipient(scope, ctx, ref=params.to_ref, raw=params.to, needs="email", field_name="to")
        if error:
            return ToolOutput.failed(error, code="recipient_not_in_scope")

        # Server, account and password come from the company's connection row
        # only. ``email_address`` may pick which of the company's connections;
        # it cannot point the tool at another server or supply a password
        # (TL-04, TL-56).
        resolved = await _resolve_connection(company_id, params.email_address)
        imap_host = resolved.get("imap_host")
        imap_port = resolved.get("imap_port") or 993
        email_address = resolved.get("email_address")
        password = resolved.get("password")
        if not all([imap_host, email_address, password]):
            return ToolOutput.failed("no email connection: configure one for this company first",
                                     code="no_connection")

        msg = _body_parts(params.draft_body)
        msg["From"] = email_address
        msg["To"] = to_addr
        msg["Subject"] = params.subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()
        # Thread headers keep the reply in the conversation.
        msg["In-Reply-To"] = params.original_message_id
        msg["References"] = params.original_message_id
        drafts_folder = _drafts_folder(imap_host)

        def _append() -> str:
            conn = _get_imap_connection(imap_host, imap_port, email_address, password)
            try:
                status, _ = conn.append(drafts_folder, "\\Draft", None, msg.as_bytes())
                return status
            finally:
                try:
                    conn.logout()
                except Exception:  # noqa: BLE001
                    pass

        try:
            status = await asyncio.to_thread(_append)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Email draft error: {e}", exc_info=True)
            return ToolOutput.failed(f"Draft creation failed: {e}")
        if status != "OK":
            return ToolOutput.failed(f"Failed to save draft to {drafts_folder}")
        return ToolOutput(output={
            "success": True, "draft_saved_to": drafts_folder, "to": to_addr,
            "subject": params.subject, "in_reply_to": params.original_message_id,
        })


# Gmail's limit is 25MB and base64 adds ~33%: files over 18MB raw are refused.
MAX_ATTACHMENT_BYTES = 18 * 1024 * 1024


class EmailSendParams(ToolParams):
    subject: str = Field(..., description="Email subject")
    body: str = Field(..., description="Email body text")
    to_ref: Optional[str] = Field(None, description=_TO_REF)
    cc_refs: List[str] = Field(default_factory=list, description="Refs of contacts to copy")
    bcc_refs: List[str] = Field(default_factory=list, description="Refs of contacts to blind-copy")
    attachment_ref: Optional[str] = Field(
        None, description="artifact_id of a file to attach: one this run made, or one in its Subjects list")
    to: Optional[str] = Field(None, description=_RAW)
    cc: Optional[str] = Field(None, description=_RAW + " Comma-separated.")
    bcc: Optional[str] = Field(None, description=_RAW + " Comma-separated.")
    email_address: Optional[str] = Field(None, description="Which of the company's mailboxes (default: the first)")


class EmailSendTool(Tool):
    """
    Send emails via SMTP using stored credentials, to the run's contacts.
    Attaches a file of the run by its artifact id.
    """
    name = "email_send"
    description = (
        "Send an email from the company mailbox to a contact of this run (to_ref), optionally "
        "attaching a file this run made or was given (attachment_ref = its artifact_id)."
    )
    Params = EmailSendParams

    async def execute(self, params: EmailSendParams, ctx: Dict[str, Any]) -> ToolOutput:
        company_id = context_company_id(ctx)
        if not company_id:
            return ToolOutput.failed(NO_CONTEXT_ERROR, code="no_context")
        scope = await scope_for(ctx)
        to_addr, error = recipient(scope, ctx, ref=params.to_ref, raw=params.to, needs="email", field_name="to")
        cc, cc_error = _addresses(scope, ctx, params.cc_refs, params.cc, "cc")
        bcc, bcc_error = _addresses(scope, ctx, params.bcc_refs, params.bcc, "bcc")
        if error or cc_error or bcc_error:
            return ToolOutput.failed(error or cc_error or bcc_error or "", code="recipient_not_in_scope")

        # The file is one the run may use, or the call is refused: before, an
        # attachment that was not found was dropped and the mail sent anyway.
        attachment = None
        if params.attachment_ref:
            attachment = await scope.artifact(params.attachment_ref)
            if attachment is None:
                return ToolOutput.failed(
                    f"'{params.attachment_ref}' is not a file of this run: attach one this run made "
                    f"(its artifact_id) or one in its Subjects list", code="attachment_not_in_scope")
            from src.ai.artifact_service import artifact_size

            size = await artifact_size(attachment)
            if size is None:
                return ToolOutput.failed(f"the file of {params.attachment_ref} is missing from storage")
            if size > MAX_ATTACHMENT_BYTES:
                return ToolOutput.failed(
                    f"Attachment '{attachment.file_name}' is {size / (1024 * 1024):.1f}MB which exceeds "
                    f"the 18MB email limit. Please use a smaller/compressed version.", code="attachment_too_large")

        # Server, account and password come from the company's connection row
        # only. ``email_address`` may pick which of the company's connections;
        # it cannot point the tool at another server — an open relay from the
        # tenant's identity — or supply a password (TL-04).
        resolved = await _resolve_connection(company_id, params.email_address)
        smtp_host = resolved.get("smtp_host")
        smtp_port = resolved.get("smtp_port") or 587
        email_address = resolved.get("email_address")
        password = resolved.get("password")
        if not all([smtp_host, email_address, password]):
            return ToolOutput.failed("no email connection: configure one for this company first",
                                     code="no_connection")

        if attachment is not None:
            # 'mixed': the body (text and html) plus the file.
            from email.mime.base import MIMEBase
            from email import encoders as email_encoders
            import mimetypes

            from src.ai.artifact_service import read_artifact_bytes
            from src.common.platform.storage import StorageObjectNotFound

            try:
                content = await read_artifact_bytes(attachment)
            except StorageObjectNotFound:
                return ToolOutput.failed(f"the file of {params.attachment_ref} is missing from storage")
            msg = MIMEMultipart("mixed")
            msg.attach(_body_parts(params.body))
            file_name = attachment.file_name or os.path.basename(attachment.file_path)
            mime_type = attachment.mime_type or mimetypes.guess_type(file_name)[0]
            maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
            file_part = MIMEBase(maintype, subtype)
            file_part.set_payload(content)
            email_encoders.encode_base64(file_part)
            file_part.add_header("Content-Disposition", "attachment", filename=file_name)
            msg.attach(file_part)
        else:
            msg = _body_parts(params.body)

        msg["From"] = email_address
        msg["To"] = to_addr
        msg["Subject"] = params.subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()
        if cc:
            msg["Cc"] = ", ".join(cc)
        recipients = [to_addr or ""] + cc + bcc

        def _send() -> None:
            server = _get_smtp_connection(smtp_host, smtp_port, email_address, password)
            try:
                server.send_message(msg, from_addr=email_address, to_addrs=recipients)
            finally:
                server.quit()

        try:
            await asyncio.to_thread(_send)
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP auth error: {e}")
            return ToolOutput.failed("SMTP authentication failed. Check email/password (use App Password for Gmail).")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Email send error: {e}", exc_info=True)
            return ToolOutput.failed(f"Email send failed: {e}")

        logger.info(f"Email sent: {email_address} -> {to_addr}, subject: {params.subject}"
                    f"{', with attachment' if attachment is not None else ''}")
        return ToolOutput(output={
            "success": True, "from": email_address, "to": to_addr, "subject": params.subject,
            "cc": ", ".join(cc), "message_id": msg["Message-ID"],
            "attachment": attachment.file_name if attachment is not None else None,
        })

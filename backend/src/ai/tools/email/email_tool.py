"""
Email AI Agent Tools using IMAP/SMTP.

Provides four tools for AI agents to interact with customer inboxes:
- EmailIngestTool: Monitor and fetch emails via IMAP IDLE
- EmailClassifyTool: Classify emails into folders via IMAP MOVE
- EmailDraftTool: Create draft replies via IMAP APPEND
- EmailSendTool: Send emails via SMTP

All tools require an email_connection_id parameter to identify which
email account credentials to use.
"""
import logging
import json
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from typing import Dict, Any, Optional
import os
import re

from src.ai.tools.base import Tool

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


def _get_imap_connection(imap_host: str, imap_port: int, email_address: str, password: str) -> imaplib.IMAP4_SSL:
    """Create and authenticate an IMAP connection."""
    conn = imaplib.IMAP4_SSL(imap_host, imap_port)
    conn.login(email_address, password)
    return conn


def _get_smtp_connection(smtp_host: str, smtp_port: int, email_address: str, password: str) -> smtplib.SMTP:
    """Create and authenticate an SMTP connection."""
    server = smtplib.SMTP(smtp_host, smtp_port)
    server.starttls()
    server.login(email_address, password)
    return server


async def _resolve_connection(company_id: Optional[str], email_address: Optional[str] = None) -> Dict[str, Any]:
    """Look up email credentials from EmailConnection table for the company."""
    if not company_id:
        return {}
        
    try:
        from uuid import UUID as _UUID
        from src.common.database import AsyncSessionLocal
        from sqlalchemy import select
        from src.ai.email_models import EmailConnection
        from src.common.security import decrypt_api_key

        async with AsyncSessionLocal() as db:
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
        company_id = context.get("company_id") if context else params.get("company_id")
        resolved = await _resolve_connection(company_id, params.get("email_address"))
        
        imap_host = params.get("imap_host") or resolved.get("imap_host")
        imap_port = params.get("imap_port") or resolved.get("imap_port") or 993
        email_address = params.get("email_address") or resolved.get("email_address")
        password = params.get("password") or resolved.get("password")
        folder = params.get("folder", "INBOX")
        count = params.get("count", 5)
        unread_only = params.get("unread_only", True)
        
        if not all([imap_host, email_address, password]):
            return json.dumps({"error": "Missing email credentials. Please configure an Email Connection for this company first."})

        try:
            conn = _get_imap_connection(imap_host, imap_port, email_address, password)
            conn.select(folder)
            
            # Search for emails
            search_criteria = "UNSEEN" if unread_only else "ALL"
            status, message_ids = conn.search(None, search_criteria)
            
            if status != "OK":
                conn.logout()
                return json.dumps({"error": "Failed to search emails"})
            
            ids = message_ids[0].split()
            if not ids:
                conn.logout()
                return json.dumps({"emails": [], "count": 0, "message": "No emails found"})
            
            # Fetch latest N emails
            latest_ids = ids[-count:]
            emails = []
            
            for uid in reversed(latest_ids):
                status, msg_data = conn.fetch(uid, "(RFC822)")
                if status != "OK":
                    continue
                
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                # Parse body
                body = _parse_email_body(msg)
                
                # Truncate very long bodies for AI context
                if len(body) > 5000:
                    body = body[:5000] + "\n\n[... truncated for context window ...]"
                
                # Get attachment info (names only, not content)
                attachments = []
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get("Content-Disposition") and "attachment" in str(part.get("Content-Disposition", "")):
                            filename = part.get_filename() or "unnamed"
                            size = len(part.get_payload(decode=True) or b"")
                            attachments.append({"filename": filename, "size_bytes": size})
                
                emails.append({
                    "uid": uid.decode(),
                    "message_id": msg.get("Message-ID", ""),
                    "from": msg.get("From", ""),
                    "to": msg.get("To", ""),
                    "subject": msg.get("Subject", ""),
                    "date": msg.get("Date", ""),
                    "body": body,
                    "attachments": attachments
                })
            
            conn.logout()
            return json.dumps({"emails": emails, "count": len(emails)})

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP error: {e}")
            return json.dumps({"error": f"IMAP connection failed: {str(e)}"})
        except Exception as e:
            logger.error(f"Email ingest error: {e}", exc_info=True)
            return json.dumps({"error": f"Email ingest failed: {str(e)}"})


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
        company_id = context.get("company_id") if context else params.get("company_id")
        resolved = await _resolve_connection(company_id, params.get("email_address"))

        imap_host = params.get("imap_host") or resolved.get("imap_host")
        imap_port = params.get("imap_port") or resolved.get("imap_port") or 993
        email_address = params.get("email_address") or resolved.get("email_address")
        password = params.get("password") or resolved.get("password")
        uid = params.get("uid")
        category = params.get("category")
        source_folder = params.get("source_folder", "INBOX")
        
        if not all([imap_host, email_address, password, uid, category]):
            return json.dumps({"error": "Missing required parameters or email credentials."})

        try:
            conn = _get_imap_connection(imap_host, imap_port, email_address, password)
            
            # Determine folder prefix based on provider
            folder_prefix = ""
            if "gmail" in imap_host.lower():
                folder_prefix = "[Gmail]/"
            
            target_folder = f"{folder_prefix}AI-Classified/{category}"
            
            # Check if target folder exists, create if not
            status, folder_list = conn.list('', target_folder)
            if status != "OK" or not folder_list or folder_list[0] is None:
                logger.info(f"Creating IMAP folder: {target_folder}")
                conn.create(target_folder)
                conn.subscribe(target_folder)
            
            # Select source folder
            conn.select(source_folder)
            
            # Copy email to target folder
            status, _ = conn.copy(uid, target_folder)
            if status != "OK":
                conn.logout()
                return json.dumps({"error": f"Failed to copy email to {target_folder}"})
            
            # Mark original as deleted and expunge
            conn.store(uid, "+FLAGS", "\\Deleted")
            conn.expunge()
            
            conn.logout()
            return json.dumps({
                "success": True,
                "uid": uid,
                "moved_to": target_folder,
                "category": category
            })

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP classify error: {e}")
            return json.dumps({"error": f"Email classification failed: {str(e)}"})
        except Exception as e:
            logger.error(f"Email classify error: {e}", exc_info=True)
            return json.dumps({"error": f"Classification failed: {str(e)}"})


class EmailDraftTool(Tool):
    """
    Create draft email replies directly in the user's Drafts folder.
    Maintains thread context via In-Reply-To and References headers.
    """
    name = "email_draft"
    description = (
        "Create a draft reply to an email in the user's Drafts folder. "
        "Will automatically use company credentials if not provided."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "email_address": {"type": "string"},
                    "original_message_id": {"type": "string", "description": "Message-ID of the email being replied to"},
                    "draft_body": {"type": "string", "description": "Body text for the draft reply"},
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject (usually 'Re: original subject')"}
                },
                "required": ["original_message_id", "draft_body", "to", "subject"]
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
        company_id = context.get("company_id") if context else params.get("company_id")
        resolved = await _resolve_connection(company_id, params.get("email_address"))

        imap_host = params.get("imap_host") or resolved.get("imap_host")
        imap_port = params.get("imap_port") or resolved.get("imap_port") or 993
        email_address = params.get("email_address") or resolved.get("email_address")
        password = params.get("password") or resolved.get("password")
        original_message_id = params.get("original_message_id")
        draft_body = params.get("draft_body")
        to_addr = params.get("to")
        subject = params.get("subject")
        
        if not all([imap_host, email_address, password, original_message_id, draft_body, to_addr, subject]):
            return json.dumps({"error": "Missing required parameters or email credentials."})

        try:
            conn = _get_imap_connection(imap_host, imap_port, email_address, password)
            
            # Construct MIME message
            msg = MIMEMultipart("alternative")
            msg["From"] = email_address
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg["Date"] = formatdate(localtime=True)
            msg["Message-ID"] = make_msgid()
            
            # Thread headers - CRUCIAL for maintaining conversation thread
            msg["In-Reply-To"] = original_message_id
            msg["References"] = original_message_id
            
            # Add body (plain text + HTML)
            plain_part = MIMEText(draft_body, "plain", "utf-8")
            html_body = draft_body.replace("\n", "<br>")
            html_part = MIMEText(f"<html><body>{html_body}</body></html>", "html", "utf-8")
            
            msg.attach(plain_part)
            msg.attach(html_part)
            
            # Determine drafts folder
            if "gmail" in imap_host.lower():
                drafts_folder = "[Gmail]/Drafts"
            elif "outlook" in imap_host.lower() or "office365" in imap_host.lower():
                drafts_folder = "Drafts"
            else:
                drafts_folder = "Drafts"
            
            # Append to drafts folder
            status, _ = conn.append(
                drafts_folder,
                "\\Draft",
                None,
                msg.as_bytes()
            )
            
            conn.logout()
            
            if status != "OK":
                return json.dumps({"error": f"Failed to save draft to {drafts_folder}"})
            
            return json.dumps({
                "success": True,
                "draft_saved_to": drafts_folder,
                "to": to_addr,
                "subject": subject,
                "in_reply_to": original_message_id
            })

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP draft error: {e}")
            return json.dumps({"error": f"Draft creation failed: {str(e)}"})
        except Exception as e:
            logger.error(f"Email draft error: {e}", exc_info=True)
            return json.dumps({"error": f"Draft creation failed: {str(e)}"})


class EmailSendTool(Tool):
    """
    Send emails via SMTP using stored credentials.
    Supports optional file attachments via artifact ID.
    """
    name = "email_send"
    description = (
        "Send an email via SMTP. "
        "Will automatically use company credentials if not provided. "
        "Can attach a file by providing its artifact_id."
    )

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "email_address": {"type": "string"},
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body text"},
                    "cc": {"type": "string", "description": "CC recipients (comma-separated)"},
                    "bcc": {"type": "string", "description": "BCC recipients (comma-separated)"},
                    "attachment_artifact_id": {
                        "type": "string",
                        "description": "UUID of an artifact to attach to the email (e.g. a product catalog PDF)"
                    }
                },
                "required": ["to", "subject", "body"]
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
        company_id = context.get("company_id") if context else params.get("company_id")
        resolved = await _resolve_connection(company_id, params.get("email_address"))

        smtp_host = params.get("smtp_host") or resolved.get("smtp_host")
        smtp_port = params.get("smtp_port") or resolved.get("smtp_port") or 587
        email_address = params.get("email_address") or resolved.get("email_address")
        password = params.get("password") or resolved.get("password")
        to_addr = params.get("to")
        subject = params.get("subject")
        body = params.get("body")
        cc = params.get("cc", "")
        bcc = params.get("bcc", "")
        attachment_artifact_id = params.get("attachment_artifact_id")
        
        if not all([smtp_host, email_address, password, to_addr, subject, body]):
            return json.dumps({"error": "Missing required parameters or email credentials."})

        try:
            # Resolve attachment file path from artifact ID (if provided)
            attachment_path = None
            attachment_filename = None
            if attachment_artifact_id and company_id:
                attachment_path, attachment_filename = await self._resolve_artifact_file(
                    attachment_artifact_id, company_id
                )
                if not attachment_path:
                    logger.warning(f"Attachment artifact not found: {attachment_artifact_id}")

            # Gmail's limit is 25MB, but base64 encoding adds ~33% overhead.
            # Reject files over 18MB raw (~24MB after encoding) to be safe.
            MAX_ATTACHMENT_BYTES = 18 * 1024 * 1024  # 18MB
            if attachment_path:
                file_size = os.path.getsize(attachment_path)
                if file_size > MAX_ATTACHMENT_BYTES:
                    size_mb = file_size / (1024 * 1024)
                    logger.error(f"Attachment too large: {size_mb:.1f}MB (limit {MAX_ATTACHMENT_BYTES // 1024 // 1024}MB)")
                    return json.dumps({
                        "error": f"Attachment '{attachment_filename}' is {size_mb:.1f}MB which exceeds the 18MB email limit. "
                                 f"Please use a smaller/compressed version."
                    })

            # Use 'mixed' when we have attachments so both body + file are included;
            # 'alternative' when it's just text/html variants of the same content.
            if attachment_path:
                msg = MIMEMultipart("mixed")
                # Create a sub-part for the body (text + html alternatives)
                body_part = MIMEMultipart("alternative")
                body_part.attach(MIMEText(body, "plain", "utf-8"))
                html_body = body.replace("\n", "<br>")
                body_part.attach(MIMEText(f"<html><body>{html_body}</body></html>", "html", "utf-8"))
                msg.attach(body_part)

                # Attach the file
                from email.mime.base import MIMEBase
                from email import encoders as email_encoders
                import mimetypes

                mime_type, _ = mimetypes.guess_type(attachment_path)
                maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
                with open(attachment_path, "rb") as f:
                    file_part = MIMEBase(maintype, subtype)
                    file_part.set_payload(f.read())
                email_encoders.encode_base64(file_part)
                file_part.add_header(
                    "Content-Disposition", "attachment",
                    filename=attachment_filename or os.path.basename(attachment_path)
                )
                msg.attach(file_part)
                logger.info(f"Attached file: {attachment_filename or attachment_path}")
            else:
                msg = MIMEMultipart("alternative")
                plain_part = MIMEText(body, "plain", "utf-8")
                html_body = body.replace("\n", "<br>")
                html_part = MIMEText(f"<html><body>{html_body}</body></html>", "html", "utf-8")
                msg.attach(plain_part)
                msg.attach(html_part)

            msg["From"] = email_address
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg["Date"] = formatdate(localtime=True)
            msg["Message-ID"] = make_msgid()
            
            if cc:
                msg["Cc"] = cc
            
            # Build recipient list
            recipients = [to_addr]
            if cc:
                recipients.extend([a.strip() for a in cc.split(",")])
            if bcc:
                recipients.extend([a.strip() for a in bcc.split(",")])
            
            # Send via SMTP
            server = _get_smtp_connection(smtp_host, smtp_port, email_address, password)
            server.send_message(msg, from_addr=email_address, to_addrs=recipients)
            server.quit()
            
            logger.info(f"Email sent: {email_address} -> {to_addr}, subject: {subject}"
                        f"{', with attachment' if attachment_path else ''}")
            
            return json.dumps({
                "success": True,
                "from": email_address,
                "to": to_addr,
                "subject": subject,
                "cc": cc,
                "message_id": msg["Message-ID"],
                "attachment": attachment_filename or None
            })

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP auth error: {e}")
            return json.dumps({"error": "SMTP authentication failed. Check email/password (use App Password for Gmail)."})
        except Exception as e:
            logger.error(f"Email send error: {e}", exc_info=True)
            return json.dumps({"error": f"Email send failed: {str(e)}"})

    @staticmethod
    async def _resolve_artifact_file(artifact_id: str, company_id: str):
        """Look up an artifact's file_path and file_name from the DB."""
        try:
            from uuid import UUID as _UUID
            from src.common.database import AsyncSessionLocal
            from sqlalchemy import select, text

            async with AsyncSessionLocal() as db:
                row = await db.execute(
                    text(
                        "SELECT file_path, file_name FROM artifacts "
                        "WHERE id = :aid AND company_id = :cid"
                    ),
                    {"aid": str(artifact_id), "cid": str(company_id)},
                )
                result = row.first()
                if result and result.file_path:
                    path = result.file_path
                    if os.path.exists(path):
                        return path, result.file_name
                    else:
                        logger.error(f"Artifact file not on disk: {path}")
        except Exception as e:
            logger.error(f"Failed to resolve artifact {artifact_id}: {e}")
        return None, None


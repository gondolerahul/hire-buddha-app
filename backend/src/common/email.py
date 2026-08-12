import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging
import asyncio

logger = logging.getLogger(__name__)


class EmailService:
    """
    System email service for verification, dunning, and notification emails.

    SMTP credentials are loaded from the Integration Registry
    (service_sku = 'smtp-system') on first use instead of environment variables.
    """

    def __init__(self):
        self._smtp_host = None
        self._smtp_port = None
        self._smtp_user = None
        self._smtp_password = None
        self._smtp_from = None
        self._credentials_loaded = False

    async def _load_credentials(self):
        """
        Load SMTP credentials from Integration Registry (service_sku='smtp-system').

        Looks for the APP company's SMTP integration. The service_metadata
        should contain: smtp_host, smtp_port, smtp_user, smtp_from.
        The api_key field stores the SMTP password (encrypted).
        """
        if self._credentials_loaded:
            return

        try:
            from src.common.database import AsyncSessionLocal
            from src.config.models import IntegrationRegistry
            from src.common.security import decrypt_api_key
            from src.auth.models import Company
            from sqlalchemy import select

            async with AsyncSessionLocal() as db:
                # Get the APP company ID
                result = await db.execute(
                    select(Company.id).where(Company.type == "APP").limit(1)
                )
                app_company_id = result.scalar_one_or_none()

                if not app_company_id:
                    logger.warning(
                        "No APP company found. SMTP credentials cannot be loaded. "
                        "Register an 'smtp-system' integration in the Integration Registry."
                    )
                    return

                # Look up smtp-system integration
                result = await db.execute(
                    select(IntegrationRegistry).where(
                        IntegrationRegistry.company_id == app_company_id,
                        IntegrationRegistry.service_sku == "smtp-system",
                        IntegrationRegistry.status == "active",
                    )
                )
                entry = result.scalar_one_or_none()

                if not entry:
                    logger.warning(
                        "SMTP integration not found in Integration Registry. "
                        "Register a 'smtp-system' integration with service_metadata "
                        "containing smtp_host, smtp_port, smtp_user, smtp_from and "
                        "the SMTP password as the api_key."
                    )
                    return

                metadata = entry.service_metadata or {}
                self._smtp_host = metadata.get("smtp_host", "localhost")
                self._smtp_port = int(metadata.get("smtp_port", 587))
                self._smtp_user = metadata.get("smtp_user", "")
                self._smtp_from = metadata.get("smtp_from", "noreply@hirebuddha.com")
                self._smtp_password = (
                    decrypt_api_key(entry.encrypted_api_key)
                    if entry.encrypted_api_key
                    else ""
                )
                self._credentials_loaded = True
                logger.info("SMTP credentials loaded from Integration Registry")

        except Exception as e:
            logger.error(f"Failed to load SMTP credentials from Integration Registry: {e}")

    def send_email(self, to_email: str, subject: str, body: str):
        # Lazy-load credentials (run async loader in sync context)
        if not self._credentials_loaded:
            try:
                loop = asyncio.get_running_loop()
                # If we're already in an async context, schedule and await
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    loop.run_in_executor(pool, self._sync_load_credentials)
            except RuntimeError:
                # No running loop — run directly
                asyncio.run(self._load_credentials())

        if not self._credentials_loaded:
            logger.error(
                "Cannot send email: SMTP credentials not configured. "
                "Register a 'smtp-system' integration in the Integration Registry."
            )
            return False

        try:
            msg = MIMEMultipart()
            msg["From"] = self._smtp_from
            msg["To"] = to_email
            msg["Subject"] = subject

            msg.attach(MIMEText(body, "html"))

            # Connect to server
            if self._smtp_user and self._smtp_password:
                server = smtplib.SMTP(self._smtp_host, self._smtp_port)
                server.starttls()
                server.login(self._smtp_user, self._smtp_password)
            else:
                server = smtplib.SMTP(self._smtp_host, self._smtp_port)

            server.send_message(msg)
            server.quit()
            logger.info(f"Email sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    def _sync_load_credentials(self):
        """Helper to run async credential loading in a new event loop."""
        asyncio.run(self._load_credentials())

    async def async_send_email(self, to_email: str, subject: str, body: str):
        """Async version of send_email — preferred in async contexts."""
        await self._load_credentials()

        if not self._credentials_loaded:
            logger.error(
                "Cannot send email: SMTP credentials not configured. "
                "Register a 'smtp-system' integration in the Integration Registry."
            )
            return False

        # Run sync SMTP in thread pool to avoid blocking
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._send_email_sync, to_email, subject, body
        )

    def _send_email_sync(self, to_email: str, subject: str, body: str):
        """Synchronous email sending logic."""
        try:
            msg = MIMEMultipart()
            msg["From"] = self._smtp_from
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html"))

            if self._smtp_user and self._smtp_password:
                server = smtplib.SMTP(self._smtp_host, self._smtp_port)
                server.starttls()
                server.login(self._smtp_user, self._smtp_password)
            else:
                server = smtplib.SMTP(self._smtp_host, self._smtp_port)

            server.send_message(msg)
            server.quit()
            logger.info(f"Email sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    def send_verification_email(self, to_email: str, token: str):
        subject = "Verify your HireBuddha account"
        verification_link = f"{os.getenv('FRONTEND_URL', 'http://localhost:5173')}/verify-email?token={token}"
        
        body = f"""
        <html>
            <body>
                <h1>Welcome to HireBuddha!</h1>
                <p>Please click the link below to verify your email address:</p>
                <a href="{verification_link}">Verify Email</a>
                <p>If you didn't request this, please ignore this email.</p>
            </body>
        </html>
        """
        return self.send_email(to_email, subject, body)

    def send_dunning_email(self, to_email: str, invoice_id: str, amount: str, attempt: int = 1):
        subject = f"Payment Failed - Action Required (Attempt {attempt})"
        
        urgency_message = ""
        if attempt == 1:
            urgency_message = "We noticed that your recent payment failed. Please update your payment method to continue using HireBuddha."
        elif attempt == 2:
            urgency_message = "This is the second attempt to collect payment. Please update your payment method immediately to avoid service interruption."
        else:
            urgency_message = "URGENT: Multiple payment attempts have failed. Your account may be suspended if payment is not received soon."
        
        body = f"""
        <html>
            <body>
                <h1>Payment Failed</h1>
                <p>{urgency_message}</p>
                <p><strong>Invoice ID:</strong> {invoice_id}</p>
                <p><strong>Amount Due:</strong> ${amount}</p>
                <p>Please log in to your account to update your payment method:</p>
                <a href="{os.getenv('FRONTEND_URL', 'http://localhost:5173')}/billing">Update Payment Method</a>
                <p>If you have any questions, please contact our support team.</p>
            </body>
        </html>
        """
        return self.send_email(to_email, subject, body)

email_service = EmailService()


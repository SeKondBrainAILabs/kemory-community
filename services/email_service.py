"""
S9N Memory Vault — Email Service

Pluggable email delivery: SMTP, SendGrid, or Resend.
Renders Jinja2 HTML templates with SeKondBrain branding.
All sends are best-effort (fire-and-forget with logging).
"""
import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import aiosmtplib
import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.config.settings import settings

logger = structlog.get_logger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "email"


class EmailService:
    """Sends transactional emails using configured provider."""

    def __init__(self) -> None:
        self._jinja = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape(["html"]),
        )

    # ─── Public API ────────────────────────────────────────────────

    async def send_welcome(
        self,
        to_email: str,
        display_name: str | None,
        position: int,
        referral_code: str,
    ) -> bool:
        """Send welcome-to-waitlist email."""
        return await self._send(
            to=to_email,
            subject="Welcome to the S9N Memory Vault waitlist",
            template="welcome.html",
            context={
                "name": display_name or to_email.split("@")[0],
                "position": position,
                "referral_code": referral_code,
                "referral_url": f"https://kora.sekondbrain.ai/vault/ref/{referral_code}",
            },
        )

    async def send_approved(
        self,
        to_email: str,
        display_name: str | None,
    ) -> bool:
        """Send approval notification email."""
        return await self._send(
            to=to_email,
            subject="You're in! Your S9N Memory Vault access is ready",
            template="approved.html",
            context={
                "name": display_name or to_email.split("@")[0],
                "dashboard_url": "https://kora.sekondbrain.ai/vault/waitlist",
            },
        )

    async def send_referral_notification(
        self,
        to_email: str,
        display_name: str | None,
        new_position: int,
        referral_count: int,
    ) -> bool:
        """Notify referrer that someone used their code."""
        return await self._send(
            to=to_email,
            subject="Someone joined with your referral link!",
            template="referral_notification.html",
            context={
                "name": display_name or to_email.split("@")[0],
                "new_position": new_position,
                "referral_count": referral_count,
            },
        )

    # ─── Internal ──────────────────────────────────────────────────

    async def _send(
        self,
        to: str,
        subject: str,
        template: str,
        context: dict,
    ) -> bool:
        """Render template and send via configured provider."""
        if not settings.email_enabled:
            logger.debug("email.skipped", to=to, subject=subject, reason="disabled")
            return False

        try:
            html = self._jinja.get_template(template).render(**context)
        except Exception as exc:
            logger.error("email.template_error", template=template, error=str(exc))
            return False

        provider = settings.email_provider
        try:
            if provider == "smtp":
                return await self._send_smtp(to, subject, html)
            else:
                logger.warning("email.unknown_provider", provider=provider)
                return False
        except Exception as exc:
            logger.error(
                "email.send_failed",
                provider=provider,
                to=to,
                subject=subject,
                error=str(exc),
            )
            return False

    async def _send_smtp(self, to: str, subject: str, html: str) -> bool:
        """Send email via SMTP (async)."""
        msg = MIMEMultipart("alternative")
        msg["From"] = settings.email_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html"))

        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            use_tls=settings.smtp_port == 465,
            start_tls=settings.smtp_port == 587,
        )
        logger.info("email.sent", to=to, subject=subject, provider="smtp")
        return True


# ─── Singleton ─────────────────────────────────────────────────────

email_service = EmailService()

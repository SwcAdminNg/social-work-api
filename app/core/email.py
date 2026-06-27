import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Thin wrapper around aiosmtplib configured for Gmail SMTP (smtp.gmail.com:587,
    STARTTLS). Requires a Google "App Password" in SMTP_PASSWORD, not the account
    password, since Gmail rejects plain password auth for SMTP."""

    async def _send(self, to_email: str, subject: str, html_body: str) -> None:
        message = EmailMessage()
        message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(html_body, subtype="html")

        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            start_tls=settings.smtp_use_tls,
        )

    async def send_password_reset_email(self, to_email: str, first_name: str, reset_link: str) -> None:
        subject = "Reset your password"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #1a1a1a;">
          <h2 style="color: #111827;">Reset your password</h2>
          <p>Hi {first_name},</p>
          <p>We received a request to reset the password for your account. Click the
          button below to choose a new password. This link expires in
          {settings.password_reset_token_expire_minutes} minutes.</p>
          <p style="text-align: center; margin: 32px 0;">
            <a href="{reset_link}"
               style="background-color: #2563eb; color: #ffffff; padding: 12px 24px;
                      border-radius: 6px; text-decoration: none; font-weight: bold;">
              Reset Password
            </a>
          </p>
          <p>If the button doesn't work, copy and paste this link into your browser:</p>
          <p style="word-break: break-all; color: #2563eb;">{reset_link}</p>
          <p>If you didn't request a password reset, you can safely ignore this email.</p>
          <p style="margin-top: 32px; color: #6b7280; font-size: 12px;">
            Social Workers &mdash; this is an automated message, please don't reply.
          </p>
        </div>
        """
        await self._send(to_email, subject, html_body)


email_service = EmailService()

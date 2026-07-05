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

    async def send_admin_invite_email(self, to_email: str, first_name: str, invite_link: str) -> None:
        subject = "You've been invited as an admin"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #1a1a1a;">
          <h2 style="color: #111827;">You've been invited as an admin</h2>
          <p>Hi {first_name},</p>
          <p>You've been invited to join Social Workers as an admin. Click the button
          below to set up your password and activate your account. This link expires in
          {settings.admin_invite_token_expire_minutes // 60 // 24} days.</p>
          <p style="text-align: center; margin: 32px 0;">
            <a href="{invite_link}"
               style="background-color: #2563eb; color: #ffffff; padding: 12px 24px;
                      border-radius: 6px; text-decoration: none; font-weight: bold;">
              Set Up Password
            </a>
          </p>
          <p>If the button doesn't work, copy and paste this link into your browser:</p>
          <p style="word-break: break-all; color: #2563eb;">{invite_link}</p>
          <p style="margin-top: 32px; color: #6b7280; font-size: 12px;">
            Social Workers &mdash; this is an automated message, please don't reply.
          </p>
        </div>
        """
        await self._send(to_email, subject, html_body)

    async def send_subscription_expiring_soon_email(self, to_email: str, first_name: str, plan_name: str, updated_price: float, expiry_date: str) -> None:
        subject = f"Your {plan_name} subscription is expiring soon"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #1a1a1a;">
          <h2 style="color: #111827;">Your subscription is expiring soon</h2>
          <p>Hi {first_name},</p>
          <p>This is a quick reminder that your <strong>{plan_name}</strong> subscription will expire on {expiry_date}.</p>
          <p>If you have a saved bank card, we will automatically charge it <strong>${updated_price:,.2f}</strong> to renew your subscription. If you do not have a saved card or your card is declined, your subscription will be paused.</p>
          <p style="margin-top: 32px; color: #6b7280; font-size: 12px;">
            Social Workers &mdash; this is an automated message, please don't reply.
          </p>
        </div>
        """
        await self._send(to_email, subject, html_body)

    async def send_subscription_renewed_email(self, to_email: str, first_name: str, plan_name: str, amount: float, next_expiry_date: str) -> None:
        subject = f"Your {plan_name} subscription has been renewed"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #1a1a1a;">
          <h2 style="color: #111827;">Subscription Renewed Successfully</h2>
          <p>Hi {first_name},</p>
          <p>Your <strong>{plan_name}</strong> subscription has been successfully renewed. We have charged your saved card <strong>${amount:,.2f}</strong>.</p>
          <p>Your new subscription expiry date is {next_expiry_date}.</p>
          <p style="margin-top: 32px; color: #6b7280; font-size: 12px;">
            Social Workers &mdash; this is an automated message, please don't reply.
          </p>
        </div>
        """
        await self._send(to_email, subject, html_body)

    async def send_subscription_renewal_failed_email(self, to_email: str, first_name: str, plan_name: str) -> None:
        subject = f"Action Required: {plan_name} renewal failed"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #1a1a1a;">
          <h2 style="color: #dc2626;">Subscription Renewal Failed</h2>
          <p>Hi {first_name},</p>
          <p>We attempted to automatically renew your <strong>{plan_name}</strong> subscription, but the charge to your saved card was declined.</p>
          <p>As a result, your subscription has been paused. Please log in and update your payment information to restore access.</p>
          <p style="margin-top: 32px; color: #6b7280; font-size: 12px;">
            Social Workers &mdash; this is an automated message, please don't reply.
          </p>
        </div>
        """
        await self._send(to_email, subject, html_body)

    async def send_subscription_expired_email(self, to_email: str, first_name: str, plan_name: str) -> None:
        subject = f"Your {plan_name} subscription has expired"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #1a1a1a;">
          <h2 style="color: #111827;">Subscription Expired</h2>
          <p>Hi {first_name},</p>
          <p>Your <strong>{plan_name}</strong> subscription has expired.</p>
          <p>Because you did not have a saved card on file for automatic renewal, your subscription has been paused. Please log in and purchase a new subscription to restore access.</p>
          <p style="margin-top: 32px; color: #6b7280; font-size: 12px;">
            Social Workers &mdash; this is an automated message, please don't reply.
          </p>
        </div>
        """
        await self._send(to_email, subject, html_body)


email_service = EmailService()

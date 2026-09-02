import base64
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"

FOOTER = f"""
          <p style="margin-top: 32px; color: #6b7280; font-size: 12px;">
            {settings.company_name} &mdash; this is an automated message, please don't reply.
          </p>
"""


class EmailService:
    """Thin wrapper around the Resend HTTP API."""

    async def _send(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        attachments: list[dict] | None = None,
    ) -> None:
        payload = {
            "from": f"{settings.resend_from_name} <{settings.resend_from_email}>",
            "to": [to_email],
            "subject": subject,
            "html": html_body,
        }
        if attachments:
            payload["attachments"] = attachments

        async with httpx.AsyncClient() as client:
            response = await client.post(
                RESEND_API_URL,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json=payload,
            )
            response.raise_for_status()

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
          {FOOTER}
        </div>
        """
        await self._send(to_email, subject, html_body)

    async def send_two_factor_code_email(self, to_email: str, first_name: str, code: str) -> None:
        subject = f"{code} is your verification code"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #1a1a1a;">
          <h2 style="color: #111827;">Your verification code</h2>
          <p>Hi {first_name},</p>
          <p>Use the code below to continue. It expires in
          {settings.two_factor_challenge_expire_minutes} minutes.</p>
          <p style="text-align: center; margin: 32px 0;">
            <span style="display: inline-block; font-size: 32px; font-weight: bold;
                         letter-spacing: 8px; color: #111827; background-color: #f3f4f6;
                         padding: 16px 24px; border-radius: 8px;">
              {code}
            </span>
          </p>
          <p>If you didn't request this code, you can safely ignore this email.</p>
          {FOOTER}
        </div>
        """
        await self._send(to_email, subject, html_body)

    async def send_admin_invite_email(self, to_email: str, first_name: str, invite_link: str) -> None:
        subject = "You've been invited as an admin"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #1a1a1a;">
          <h2 style="color: #111827;">You've been invited as an admin</h2>
          <p>Hi {first_name},</p>
          <p>You've been invited to join {settings.company_name} as an admin. Click the button
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
          {FOOTER}
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
          {FOOTER}
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
          {FOOTER}
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
          {FOOTER}
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
          {FOOTER}
        </div>
        """
        await self._send(to_email, subject, html_body)

    async def send_support_escalation_email(
        self, to_email: str, first_name: str, ticket_subject: str, dashboard_link: str
    ) -> None:
        subject = f"Support ticket needs attention: {ticket_subject}"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #1a1a1a;">
          <h2 style="color: #dc2626;">A support ticket needs attention</h2>
          <p>Hi {first_name},</p>
          <p>A user opened a support ticket &mdash; <strong>{ticket_subject}</strong> &mdash;
          and no one from the Support Desk has responded yet. Please jump in as soon as
          you can.</p>
          <p style="text-align: center; margin: 32px 0;">
            <a href="{dashboard_link}"
               style="background-color: #2563eb; color: #ffffff; padding: 12px 24px;
                      border-radius: 6px; text-decoration: none; font-weight: bold;">
              Open Ticket
            </a>
          </p>
          <p>If the button doesn't work, copy and paste this link into your browser:</p>
          <p style="word-break: break-all; color: #2563eb;">{dashboard_link}</p>
          {FOOTER}
        </div>
        """
        await self._send(to_email, subject, html_body)

    async def send_course_payment_receipt_email(
        self,
        to_email: str,
        first_name: str,
        items_summary: str,
        amount: float,
        reference: str,
        payment_date: str,
        receipt_pdf: bytes,
    ) -> None:
        subject = f"Payment received — {items_summary}"
        html_body = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto; color: #1a1a1a;">
          <h2 style="color: #111827;">Thank you for your payment!</h2>
          <p>Hi {first_name},</p>
          <p>We've received your payment for <strong>{items_summary}</strong>. You now have full access &mdash; happy learning!</p>
          <table style="width: 100%; border-collapse: collapse; margin: 24px 0; font-size: 14px;">
            <tr>
              <td style="padding: 8px 0; color: #6b7280;">Amount paid</td>
              <td style="padding: 8px 0; text-align: right; font-weight: bold;">&#8358;{amount:,.2f}</td>
            </tr>
            <tr>
              <td style="padding: 8px 0; color: #6b7280; border-top: 1px solid #e5e7eb;">Reference</td>
              <td style="padding: 8px 0; text-align: right; border-top: 1px solid #e5e7eb;">{reference}</td>
            </tr>
            <tr>
              <td style="padding: 8px 0; color: #6b7280; border-top: 1px solid #e5e7eb;">Date</td>
              <td style="padding: 8px 0; text-align: right; border-top: 1px solid #e5e7eb;">{payment_date}</td>
            </tr>
          </table>
          <p>A PDF receipt is attached to this email for your records.</p>
          {FOOTER}
          <p style="color: #6b7280; font-size: 12px;">
            {settings.company_name}<br/>
            {settings.company_address}<br/>
            {settings.company_phone}<br/>
            {settings.company_support_email}
          </p>
        </div>
        """
        attachment = {
            "filename": f"Receipt-{reference}.pdf",
            "content": base64.b64encode(receipt_pdf).decode("ascii"),
        }
        await self._send(to_email, subject, html_body, attachments=[attachment])


email_service = EmailService()

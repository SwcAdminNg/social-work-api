import base64
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


def _button(label: str, href: str) -> str:
    return f"""
    <p style="text-align: center; margin: 32px 0;">
      <a href="{href}"
         style="background-color: #2563eb; color: #ffffff; padding: 12px 28px;
                border-radius: 6px; text-decoration: none; font-weight: bold;
                font-size: 14px; display: inline-block;">
        {label}
      </a>
    </p>
    """


def _wrap_email(body_html: str, preheader: str = "") -> str:
    """The one email shell every outgoing message is rendered into: a logo header,
    a white content card, and a footer with the company's contact details. Keeping
    a single wrapper means every email - receipts, OTPs, invites, alerts - looks
    like it came from the same product."""
    return f"""
    <div style="background-color: #f3f4f6; padding: 40px 16px; font-family: Arial, sans-serif;">
      <span style="display: none; max-height: 0; overflow: hidden;">{preheader}</span>
      <div style="max-width: 520px; margin: 0 auto; background-color: #ffffff; border-radius: 12px;
                  overflow: hidden; border: 1px solid #e5e7eb;">
        <div style="background-color: #111827; padding: 20px 32px; text-align: center;">
          <img src="{settings.company_logo_url}" alt="{settings.company_name}" style="height: 32px;" />
        </div>
        <div style="padding: 32px; color: #1a1a1a; font-size: 14px; line-height: 1.6;">
          {body_html}
        </div>
        <div style="background-color: #f9fafb; padding: 24px 32px; border-top: 1px solid #e5e7eb;">
          <p style="margin: 0 0 4px; color: #6b7280; font-size: 12px;">{settings.company_name}</p>
          <p style="margin: 0 0 4px; color: #9ca3af; font-size: 12px;">{settings.company_address}</p>
          <p style="margin: 0; color: #9ca3af; font-size: 12px;">
            {settings.company_phone} &middot;
            <a href="mailto:{settings.company_support_email}" style="color: #6b7280;">{settings.company_support_email}</a>
          </p>
          <p style="margin: 16px 0 0; color: #9ca3af; font-size: 11px;">
            This is an automated message, please don't reply directly to this email.
          </p>
        </div>
      </div>
    </div>
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
        body = f"""
          <h2 style="color: #111827; margin-top: 0;">Reset your password</h2>
          <p>Hi {first_name},</p>
          <p>We received a request to reset the password for your account. Click the
          button below to choose a new password. This link expires in
          {settings.password_reset_token_expire_minutes} minutes.</p>
          {_button("Reset Password", reset_link)}
          <p>If the button doesn't work, copy and paste this link into your browser:</p>
          <p style="word-break: break-all; color: #2563eb;">{reset_link}</p>
          <p>If you didn't request a password reset, you can safely ignore this email.</p>
        """
        await self._send(to_email, subject, _wrap_email(body, preheader="Reset the password on your account."))

    async def send_two_factor_code_email(self, to_email: str, first_name: str, code: str) -> None:
        subject = f"{code} is your verification code"
        body = f"""
          <h2 style="color: #111827; margin-top: 0;">Your verification code</h2>
          <p>Hi {first_name},</p>
          <p>Use the code below to finish verifying it's you. It expires in
          {settings.two_factor_challenge_expire_minutes} minutes, so grab it while it's fresh.</p>
          <p style="text-align: center; margin: 32px 0;">
            <span style="display: inline-block; font-size: 32px; font-weight: bold;
                         letter-spacing: 8px; color: #111827; background-color: #f3f4f6;
                         padding: 16px 24px; border-radius: 8px;">
              {code}
            </span>
          </p>
          <p style="color: #6b7280; font-size: 13px;">
            Didn't request this code? Someone may have typed your email by mistake - you can safely
            ignore this message, your account is still secure.
          </p>
        """
        await self._send(to_email, subject, _wrap_email(body, preheader=f"Your verification code is {code}."))

    async def send_admin_invite_email(self, to_email: str, first_name: str, invite_link: str) -> None:
        subject = "You've been invited as an admin"
        body = f"""
          <h2 style="color: #111827; margin-top: 0;">You've been invited as an admin</h2>
          <p>Hi {first_name},</p>
          <p>You've been invited to join {settings.company_name} as an admin. Click the button
          below to set up your password and activate your account. This link expires in
          {settings.admin_invite_token_expire_minutes // 60 // 24} days.</p>
          {_button("Set Up Password", invite_link)}
          <p>If the button doesn't work, copy and paste this link into your browser:</p>
          <p style="word-break: break-all; color: #2563eb;">{invite_link}</p>
        """
        await self._send(to_email, subject, _wrap_email(body, preheader="Set up your admin account."))

    async def send_subscription_expiring_soon_email(self, to_email: str, first_name: str, plan_name: str, updated_price: float, expiry_date: str) -> None:
        subject = f"Your {plan_name} subscription is expiring soon"
        body = f"""
          <h2 style="color: #111827; margin-top: 0;">Your subscription is expiring soon</h2>
          <p>Hi {first_name},</p>
          <p>This is a quick reminder that your <strong>{plan_name}</strong> subscription will expire on {expiry_date}.</p>
          <p>If you have a saved bank card, we will automatically charge it <strong>&#8358;{updated_price:,.2f}</strong> to renew your subscription. If you do not have a saved card or your card is declined, your subscription will be paused.</p>
        """
        await self._send(to_email, subject, _wrap_email(body, preheader=f"Your {plan_name} subscription expires on {expiry_date}."))

    async def send_subscription_renewed_email(self, to_email: str, first_name: str, plan_name: str, amount: float, next_expiry_date: str) -> None:
        subject = f"Your {plan_name} subscription has been renewed"
        body = f"""
          <h2 style="color: #111827; margin-top: 0;">Subscription renewed successfully</h2>
          <p>Hi {first_name},</p>
          <p>Your <strong>{plan_name}</strong> subscription has been successfully renewed. We have charged your saved card <strong>&#8358;{amount:,.2f}</strong>.</p>
          <p>Your new subscription expiry date is {next_expiry_date}.</p>
        """
        await self._send(to_email, subject, _wrap_email(body, preheader=f"Your {plan_name} subscription was renewed."))

    async def send_subscription_renewal_failed_email(self, to_email: str, first_name: str, plan_name: str) -> None:
        subject = f"Action Required: {plan_name} renewal failed"
        body = f"""
          <h2 style="color: #dc2626; margin-top: 0;">Subscription renewal failed</h2>
          <p>Hi {first_name},</p>
          <p>We attempted to automatically renew your <strong>{plan_name}</strong> subscription, but the charge to your saved card was declined.</p>
          <p>As a result, your subscription has been paused. Please log in and update your payment information to restore access.</p>
        """
        await self._send(to_email, subject, _wrap_email(body, preheader=f"We couldn't renew your {plan_name} subscription."))

    async def send_subscription_expired_email(self, to_email: str, first_name: str, plan_name: str) -> None:
        subject = f"Your {plan_name} subscription has expired"
        body = f"""
          <h2 style="color: #111827; margin-top: 0;">Subscription expired</h2>
          <p>Hi {first_name},</p>
          <p>Your <strong>{plan_name}</strong> subscription has expired.</p>
          <p>Because you did not have a saved card on file for automatic renewal, your subscription has been paused. Please log in and purchase a new subscription to restore access.</p>
        """
        await self._send(to_email, subject, _wrap_email(body, preheader=f"Your {plan_name} subscription has expired."))

    async def send_support_escalation_email(
        self, to_email: str, first_name: str, ticket_subject: str, dashboard_link: str
    ) -> None:
        subject = f"Support ticket needs attention: {ticket_subject}"
        body = f"""
          <h2 style="color: #dc2626; margin-top: 0;">A support ticket needs attention</h2>
          <p>Hi {first_name},</p>
          <p>A user opened a support ticket &mdash; <strong>{ticket_subject}</strong> &mdash;
          and no one from the Support Desk has responded yet. Please jump in as soon as
          you can.</p>
          {_button("Open Ticket", dashboard_link)}
          <p>If the button doesn't work, copy and paste this link into your browser:</p>
          <p style="word-break: break-all; color: #2563eb;">{dashboard_link}</p>
        """
        await self._send(to_email, subject, _wrap_email(body, preheader="A support ticket needs attention."))

    async def send_registration_welcome_email(self, to_email: str, first_name: str, login_link: str) -> None:
        subject = f"Welcome to {settings.company_name}, {first_name}!"
        body = f"""
          <h2 style="color: #111827; margin-top: 0;">Welcome aboard, {first_name}! &#127881;</h2>
          <p>Your account with {settings.company_name} has been created &mdash; we're glad to have you here.</p>
          <p>You're one short step away from getting started: secure your account by finishing
          two-factor authentication setup, then dive into our courses whenever you're ready.
          Learning at your own pace, with real support along the way, starts now.</p>
          {_button("Continue to " + settings.company_name, login_link)}
          <p style="color: #6b7280; font-size: 13px;">
            Questions before you begin? Just reply to this email or reach us at
            {settings.company_support_email} &mdash; we're happy to help.
          </p>
        """
        await self._send(to_email, subject, _wrap_email(body, preheader=f"Your {settings.company_name} account is ready."))

    async def send_course_payment_receipt_email(
        self,
        to_email: str,
        first_name: str,
        items_summary: str,
        amount: float,
        reference: str,
        payment_date: str,
        receipt_pdf: bytes,
        dashboard_link: str,
        course_links: list[tuple[str, str]],
    ) -> None:
        subject = f"Payment received — {items_summary}"

        if len(course_links) == 1:
            title, link = course_links[0]
            course_section = f"""
              <p>Ready to dive in? Head to your course page to pick up where you left off:</p>
              {_button(f"Start \"{title}\"", link)}
            """
        elif course_links:
            rows = "".join(
                f"""
                <tr>
                  <td style="padding: 8px 0; border-top: 1px solid #e5e7eb;">
                    <a href="{link}" style="color: #2563eb; text-decoration: none;">{title}</a>
                  </td>
                </tr>
                """
                for title, link in course_links
            )
            course_section = f"""
              <p>Ready to dive in? Here are direct links to each course:</p>
              <table style="width: 100%; border-collapse: collapse; margin: 8px 0 24px; font-size: 14px;">
                {rows}
              </table>
            """
        else:
            course_section = ""

        body = f"""
          <h2 style="color: #111827; margin-top: 0;">Thank you for your payment! &#127881;</h2>
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
          {course_section}
          <p>You can always get back to everything you're learning from your dashboard:</p>
          {_button("Go to My Dashboard", dashboard_link)}
          <p style="color: #6b7280; font-size: 13px;">
            A little encouragement: the best time to start a course is right after you buy it &mdash;
            momentum is everything. Happy learning, and we can't wait to see what you build with what
            you learn!
          </p>
          <p>A PDF receipt is attached to this email for your records.</p>
        """
        attachment = {
            "filename": f"Receipt-{reference}.pdf",
            "content": base64.b64encode(receipt_pdf).decode("ascii"),
        }
        await self._send(
            to_email,
            subject,
            _wrap_email(body, preheader=f"Your receipt for {items_summary} is ready - happy learning!"),
            attachments=[attachment],
        )


    async def send_live_session_scheduled_email(
        self,
        to_email: str,
        first_name: str,
        course_title: str,
        session_title: str,
        start_at_display: str,
        guest_name: str | None,
        guest_title: str | None,
        join_link: str,
        google_calendar_link: str,
        outlook_calendar_link: str,
        ics_bytes: bytes,
    ) -> None:
        subject = f"You're invited: {session_title} ({course_title})"
        guest_section = ""
        if guest_name:
            guest_line = guest_name if not guest_title else f"{guest_name} &mdash; {guest_title}"
            guest_section = f"""
              <p style="margin: 16px 0; padding: 12px 16px; background-color: #f3f4f6; border-radius: 8px;">
                <strong>Guest speaker:</strong> {guest_line}
              </p>
            """
        body = f"""
          <h2 style="color: #111827; margin-top: 0;">A live session has been scheduled &#128197;</h2>
          <p>Hi {first_name},</p>
          <p>A live session for <strong>{course_title}</strong> has been scheduled:</p>
          <p style="font-size: 16px; font-weight: bold; margin: 4px 0;">{session_title}</p>
          <p style="color: #6b7280; margin-top: 0;">{start_at_display}</p>
          {guest_section}
          {_button("Join Live Session", join_link)}
          <p style="text-align: center; margin: 16px 0; font-size: 13px;">
            <a href="{google_calendar_link}" style="color: #2563eb; text-decoration: none; margin: 0 8px;">Add to Google Calendar</a>
            &middot;
            <a href="{outlook_calendar_link}" style="color: #2563eb; text-decoration: none; margin: 0 8px;">Add to Outlook</a>
          </p>
          <p style="color: #6b7280; font-size: 13px;">
            A calendar invite (.ics) is attached to this email - open it to add the session to any calendar app.
          </p>
        """
        attachment = {
            "filename": "live-session.ics",
            "content": base64.b64encode(ics_bytes).decode("ascii"),
        }
        await self._send(
            to_email,
            subject,
            _wrap_email(body, preheader=f"{session_title} is scheduled - {start_at_display}"),
            attachments=[attachment],
        )

    async def send_live_session_rescheduled_email(
        self,
        to_email: str,
        first_name: str,
        course_title: str,
        session_title: str,
        old_start_at_display: str,
        new_start_at_display: str,
        join_link: str,
        google_calendar_link: str,
        outlook_calendar_link: str,
        ics_bytes: bytes,
    ) -> None:
        subject = f"Rescheduled: {session_title} ({course_title})"
        body = f"""
          <h2 style="color: #111827; margin-top: 0;">This live session has been rescheduled</h2>
          <p>Hi {first_name},</p>
          <p>The live session <strong>{session_title}</strong> for <strong>{course_title}</strong> has a new date/time:</p>
          <p style="color: #9ca3af; text-decoration: line-through; margin: 4px 0;">{old_start_at_display}</p>
          <p style="font-size: 16px; font-weight: bold; margin: 4px 0; color: #111827;">{new_start_at_display}</p>
          {_button("Join Live Session", join_link)}
          <p style="text-align: center; margin: 16px 0; font-size: 13px;">
            <a href="{google_calendar_link}" style="color: #2563eb; text-decoration: none; margin: 0 8px;">Add to Google Calendar</a>
            &middot;
            <a href="{outlook_calendar_link}" style="color: #2563eb; text-decoration: none; margin: 0 8px;">Add to Outlook</a>
          </p>
          <p style="color: #6b7280; font-size: 13px;">
            An updated calendar invite (.ics) is attached - re-adding it will replace the old time in most calendar apps.
          </p>
        """
        attachment = {
            "filename": "live-session.ics",
            "content": base64.b64encode(ics_bytes).decode("ascii"),
        }
        await self._send(
            to_email,
            subject,
            _wrap_email(body, preheader=f"{session_title} moved to {new_start_at_display}"),
            attachments=[attachment],
        )

    async def send_live_session_reminder_email(
        self,
        to_email: str,
        first_name: str,
        course_title: str,
        session_title: str,
        start_at_display: str,
        join_link: str,
    ) -> None:
        subject = f"Starting soon: {session_title}"
        body = f"""
          <h2 style="color: #111827; margin-top: 0;">Your live session is starting soon &#9200;</h2>
          <p>Hi {first_name},</p>
          <p><strong>{session_title}</strong> ({course_title}) starts at <strong>{start_at_display}</strong>.</p>
          {_button("Join Now", join_link)}
        """
        await self._send(to_email, subject, _wrap_email(body, preheader=f"{session_title} starts at {start_at_display}"))


email_service = EmailService()

import logging
import uuid
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import PaginationParams
from app.core.ws_pubsub import channel_name, publish_event
from app.modules.notification.dto import NotificationReadDTO
from app.modules.notification.entity import Notification, NotificationTypeEnum
from app.modules.notification.repository import NotificationRepository
from app.modules.user.entity import TwoFactorMethodEnum, User
from app.modules.user.repository import UserRepository

logger = logging.getLogger(__name__)

_CHANNEL_NAMESPACE = "notifications"


def notification_channel(user_id: uuid.UUID) -> str:
    return channel_name(_CHANNEL_NAMESPACE, user_id)


class NotificationService:
    """One method per notifiable event, mirroring `app/core/email.py`'s shape.
    Every method persists a row and fans it out over `_CHANNEL_NAMESPACE` so a
    connected `notifications/ws` client (see router.py) gets it immediately;
    a client that isn't connected just reads it later via the list endpoint.

    Called directly from the relevant service right after the triggering write
    commits - there's no domain event bus in this codebase (see the email call
    sites this mirrors), so this is the same pattern already in use."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = NotificationRepository(session)
        self.users = UserRepository(session)

    # -- core --------------------------------------------------------------------

    async def _create(
        self,
        user_id: uuid.UUID,
        type: NotificationTypeEnum,
        title: str,
        body: str | None = None,
        link: str | None = None,
        metadata_json: dict | None = None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id, type=type, title=title, body=body, link=link, metadata_json=metadata_json
        )
        await self.repo.create(notification)
        await self.session.commit()
        await self.session.refresh(notification)

        try:
            dto = NotificationReadDTO.model_validate(notification)
            await publish_event(_CHANNEL_NAMESPACE, user_id, {"type": "notification", "data": dto.model_dump(mode="json")})
        except Exception as exc:
            logger.warning("Failed to publish notification %s to user %s: %s", type.value, user_id, exc)

        return notification

    async def _notify_admins(
        self,
        type: NotificationTypeEnum,
        title: str,
        body: str | None = None,
        link: str | None = None,
        metadata_json: dict | None = None,
        exclude_user_id: uuid.UUID | None = None,
    ) -> None:
        admin_ids = await self.users.list_active_admin_ids()
        for admin_id in admin_ids:
            if exclude_user_id is not None and admin_id == exclude_user_id:
                continue
            await self._create(admin_id, type, title, body, link, metadata_json)

    # -- read side -----------------------------------------------------------------

    async def list_for_user(
        self, user: User, pagination: PaginationParams, unread_only: bool = False
    ) -> tuple[Sequence[Notification], int]:
        return await self.repo.list_for_user(user.id, pagination, unread_only)

    async def get_unread_count(self, user: User) -> int:
        return await self.repo.count_unread(user.id)

    async def mark_read(self, notification_id: uuid.UUID, user: User) -> Notification:
        from fastapi import HTTPException, status

        notification = await self.repo.get_for_user(notification_id, user.id)
        if notification is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
        await self.repo.mark_read(notification)
        await self.session.commit()
        await self.session.refresh(notification)
        return notification

    async def mark_all_read(self, user: User) -> None:
        await self.repo.mark_all_read(user.id)
        await self.session.commit()

    # -- account / auth -------------------------------------------------------------

    async def notify_signup_welcome(self, user: User) -> None:
        await self._create(
            user.id, NotificationTypeEnum.SIGNUP_WELCOME,
            "Welcome aboard!", f"Your account has been created - glad to have you here, {user.first_name}.",
            "/dashboard",
        )

    async def notify_login(self, user: User) -> None:
        await self._create(
            user.id, NotificationTypeEnum.LOGIN,
            "New login to your account", "We noticed a new sign-in to your account.",
            "/dashboard/settings",
        )

    async def notify_password_reset_requested(self, user: User) -> None:
        await self._create(
            user.id, NotificationTypeEnum.PASSWORD_RESET_REQUESTED,
            "Password reset requested", "A password reset was requested for your account. If this wasn't you, secure your account.",
            "/dashboard/settings",
        )

    async def notify_password_reset_completed(self, user: User) -> None:
        await self._create(
            user.id, NotificationTypeEnum.PASSWORD_RESET_COMPLETED,
            "Password changed", "Your password was changed successfully.",
            "/dashboard/settings",
        )

    async def notify_profile_picture_updated(self, user: User) -> None:
        await self._create(
            user.id, NotificationTypeEnum.PROFILE_PICTURE_UPDATED,
            "Profile picture updated", "Your profile picture was updated successfully.",
            "/dashboard/settings",
        )

    async def notify_two_factor_enabled(self, user: User, method: TwoFactorMethodEnum) -> None:
        await self._create(
            user.id, NotificationTypeEnum.TWO_FACTOR_ENABLED,
            "Two-factor authentication enabled", f"Two-factor authentication via {method.value.title()} is now active on your account.",
            "/dashboard/settings",
        )

    async def notify_account_suspended(self, user: User) -> None:
        await self._create(
            user.id, NotificationTypeEnum.ACCOUNT_SUSPENDED,
            "Account suspended", "Your account has been suspended. Contact support if you believe this is a mistake.",
            "/dashboard/support-tickets",
        )

    async def notify_account_unsuspended(self, user: User) -> None:
        await self._create(
            user.id, NotificationTypeEnum.ACCOUNT_UNSUSPENDED,
            "Account reinstated", "Your account has been unsuspended and full access has been restored.",
            "/dashboard",
        )

    async def notify_role_changed(self, user: User, role: str) -> None:
        await self._create(
            user.id, NotificationTypeEnum.ROLE_CHANGED,
            "Account role updated", f"Your account role was changed to {role.title()}.",
            "/dashboard/settings",
        )

    # -- payments --------------------------------------------------------------------

    async def notify_payment_successful(self, user: User, amount: float, reference: str, items_summary: str) -> None:
        await self._create(
            user.id, NotificationTypeEnum.PAYMENT_SUCCESSFUL,
            "Payment received", f"We received your payment of NGN {amount:,.2f} for {items_summary}.",
            "/dashboard/orders",
            {"reference": reference, "amount": amount},
        )

    async def notify_subscription_renewed(self, user: User, plan_name: str) -> None:
        await self._create(
            user.id, NotificationTypeEnum.SUBSCRIPTION_RENEWED,
            "Subscription renewed", f"Your {plan_name} subscription was renewed successfully.",
            "/dashboard/pricing",
        )

    async def notify_subscription_renewal_failed(self, user: User, plan_name: str) -> None:
        await self._create(
            user.id, NotificationTypeEnum.SUBSCRIPTION_RENEWAL_FAILED,
            "Subscription renewal failed", f"We couldn't renew your {plan_name} subscription - please update your payment method.",
            "/dashboard/pricing",
        )

    async def notify_subscription_expiring_soon(self, user: User, plan_name: str, expiry_date: str) -> None:
        await self._create(
            user.id, NotificationTypeEnum.SUBSCRIPTION_EXPIRING_SOON,
            "Subscription expiring soon", f"Your {plan_name} subscription expires on {expiry_date}.",
            "/dashboard/pricing",
        )

    async def notify_subscription_expired(self, user: User, plan_name: str) -> None:
        await self._create(
            user.id, NotificationTypeEnum.SUBSCRIPTION_EXPIRED,
            "Subscription expired", f"Your {plan_name} subscription has expired.",
            "/dashboard/pricing",
        )

    # -- courses / learning ------------------------------------------------------------

    async def notify_course_enrolled(self, user: User, course_id: uuid.UUID, course_title: str) -> None:
        await self._create(
            user.id, NotificationTypeEnum.COURSE_ENROLLED,
            "Enrolled in a course", f"You're now enrolled in \"{course_title}\". Happy learning!",
            f"/learn/{course_id}",
            {"course_id": str(course_id)},
        )

    async def notify_course_completed(self, user: User, course_id: uuid.UUID, course_title: str) -> None:
        await self._create(
            user.id, NotificationTypeEnum.COURSE_COMPLETED,
            "Course completed!", f"Congratulations - you've completed \"{course_title}\".",
            f"/dashboard/certificates/{course_id}",
            {"course_id": str(course_id)},
        )

    async def notify_certificate_issued(self, user: User, course_id: uuid.UUID, course_title: str) -> None:
        await self._create(
            user.id, NotificationTypeEnum.CERTIFICATE_ISSUED,
            "Certificate issued", f"Your certificate for \"{course_title}\" is ready to view and download.",
            f"/dashboard/certificates/{course_id}",
            {"course_id": str(course_id)},
        )

    async def notify_live_session_scheduled(
        self, user: User, course_id: uuid.UUID, course_slug: str, item_id: uuid.UUID, session_title: str, start_at_display: str
    ) -> None:
        await self._create(
            user.id, NotificationTypeEnum.LIVE_SESSION_SCHEDULED,
            "Live session scheduled", f"{session_title} has been scheduled - {start_at_display}.",
            f"/courses/{course_slug}/live-session/{item_id}",
            {"course_id": str(course_id), "item_id": str(item_id)},
        )

    async def notify_live_session_rescheduled(
        self, user: User, course_id: uuid.UUID, course_slug: str, item_id: uuid.UUID, session_title: str, new_start_at_display: str
    ) -> None:
        await self._create(
            user.id, NotificationTypeEnum.LIVE_SESSION_RESCHEDULED,
            "Live session rescheduled", f"{session_title} moved to {new_start_at_display}.",
            f"/courses/{course_slug}/live-session/{item_id}",
            {"course_id": str(course_id), "item_id": str(item_id)},
        )

    async def notify_live_session_reminder(
        self, user: User, course_id: uuid.UUID, course_slug: str, item_id: uuid.UUID, session_title: str, start_at_display: str
    ) -> None:
        await self._create(
            user.id, NotificationTypeEnum.LIVE_SESSION_REMINDER,
            "Live session starting soon", f"{session_title} starts at {start_at_display}.",
            f"/courses/{course_slug}/live-session/{item_id}",
            {"course_id": str(course_id), "item_id": str(item_id)},
        )

    async def notify_course_review_replied(self, user: User, course_id: uuid.UUID, course_title: str) -> None:
        await self._create(
            user.id, NotificationTypeEnum.COURSE_REVIEW_REPLIED,
            "Reply to your review", f"The instructor replied to your review of \"{course_title}\".",
            f"/dashboard/course-catalogue/{course_id}",
            {"course_id": str(course_id)},
        )

    # -- community ---------------------------------------------------------------------

    async def notify_community_new_message(
        self, user_id: uuid.UUID, community_id: uuid.UUID, community_name: str, sender_name: str, preview: str
    ) -> None:
        await self._create(
            user_id, NotificationTypeEnum.COMMUNITY_NEW_MESSAGE,
            f"New message in {community_name}", f"{sender_name}: {preview}",
            f"/dashboard/community?community_id={community_id}",
            {"community_id": str(community_id)},
        )

    # -- support -------------------------------------------------------------------------

    async def notify_support_ticket_message(
        self, user_id: uuid.UUID, ticket_id: uuid.UUID, subject: str, sender_name: str, preview: str, for_admin: bool
    ) -> None:
        link = f"/dashboard/help-support/tickets/{ticket_id}" if for_admin else f"/dashboard/support-tickets/{ticket_id}"
        await self._create(
            user_id, NotificationTypeEnum.SUPPORT_TICKET_MESSAGE,
            f"New reply on \"{subject}\"", f"{sender_name}: {preview}",
            link,
            {"ticket_id": str(ticket_id)},
        )

    async def notify_support_ticket_status_changed(self, user: User, ticket_id: uuid.UUID, subject: str, status_value: str) -> None:
        await self._create(
            user.id, NotificationTypeEnum.SUPPORT_TICKET_STATUS_CHANGED,
            f"Ticket {status_value.lower()}", f"Your ticket \"{subject}\" is now {status_value.lower()}.",
            f"/dashboard/support-tickets/{ticket_id}",
            {"ticket_id": str(ticket_id), "status": status_value},
        )

    async def notify_support_ticket_assigned(self, admin: User, ticket_id: uuid.UUID, subject: str) -> None:
        await self._create(
            admin.id, NotificationTypeEnum.SUPPORT_TICKET_ASSIGNED,
            "Ticket assigned to you", f"You've been assigned to the ticket \"{subject}\".",
            f"/dashboard/help-support/tickets/{ticket_id}",
            {"ticket_id": str(ticket_id)},
        )

    # -- admin / back-office -------------------------------------------------------------

    async def notify_admins_new_user_signup(self, new_user: User) -> None:
        await self._notify_admins(
            NotificationTypeEnum.NEW_USER_SIGNUP,
            "New user sign-up", f"{new_user.first_name} {new_user.last_name} ({new_user.email}) just signed up.",
            f"/dashboard/user-management/{new_user.id}",
            {"user_id": str(new_user.id)},
        )

    async def notify_admins_new_payment(self, user: User, amount: float, reference: str) -> None:
        await self._notify_admins(
            NotificationTypeEnum.NEW_PAYMENT,
            "New payment received", f"{user.first_name} {user.last_name} paid NGN {amount:,.2f} (ref: {reference}).",
            "/dashboard/payments",
            {"reference": reference, "amount": amount, "user_id": str(user.id)},
        )

    async def notify_admins_new_contact_message(self, name: str, message_id: uuid.UUID) -> None:
        await self._notify_admins(
            NotificationTypeEnum.NEW_CONTACT_MESSAGE,
            "New contact message", f"{name} sent a message via the contact form.",
            "/dashboard/contact-messages",
            {"message_id": str(message_id)},
        )

    async def notify_admins_new_support_ticket(self, ticket_id: uuid.UUID, subject: str) -> None:
        await self._notify_admins(
            NotificationTypeEnum.NEW_SUPPORT_TICKET,
            "New support ticket", f"A new ticket was opened: \"{subject}\".",
            f"/dashboard/help-support/tickets/{ticket_id}",
            {"ticket_id": str(ticket_id)},
        )

    async def notify_admins_new_course_review(self, course_title: str, course_id: uuid.UUID) -> None:
        await self._notify_admins(
            NotificationTypeEnum.NEW_COURSE_REVIEW,
            "New course review", f"A new review was submitted for \"{course_title}\".",
            "/dashboard/reviews",
            {"course_id": str(course_id)},
        )

    async def notify_admin_invited(self, invitee: User) -> None:
        await self._create(
            invitee.id, NotificationTypeEnum.ADMIN_INVITED,
            "You've been invited as an admin", "Check your email to finish setting up your admin account.",
            "/dashboard",
        )

    async def notify_admins_invite_accepted(self, new_admin: User) -> None:
        await self._notify_admins(
            NotificationTypeEnum.ADMIN_INVITE_ACCEPTED,
            "Admin invite accepted", f"{new_admin.first_name} {new_admin.last_name} accepted their admin invite and is now active.",
            "/dashboard/user-management",
            {"user_id": str(new_admin.id)},
            exclude_user_id=new_admin.id,
        )

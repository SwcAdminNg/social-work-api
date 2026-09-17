import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.calendar_invite import build_calendar_links, build_ics
from app.core.config import settings
from app.core.daily import get_daily_client
from app.core.email import email_service
from app.core.qstash import get_qstash_client
from app.core.security import generate_opaque_token, hash_token
from app.modules.course.content_dto import LiveSessionExternalJoinDTO, LiveSessionJoinDTO
from app.modules.course.content_entity import (
    CourseLiveSession,
    LiveSessionExternalInvite,
    LiveSessionStatusEnum,
    VideoStatusEnum,
)
from app.modules.course.content_repository import CourseContentRepository
from app.modules.course.entity import Course, CourseItem
from app.modules.course.repository import CourseRepository
from app.modules.learning.repository import LearningRepository
from app.modules.notification.service import NotificationService
from app.modules.user.entity import User, UserTypeEnum
from app.modules.user.repository import UserRepository

logger = logging.getLogger(__name__)


class LiveSessionService:
    """Join-token issuance, enrolled-student notifications (email + calendar
    invite) and daily.co webhook handling for LIVE_SESSION curriculum items.
    Kept separate from CourseContentService, which only owns the authoring
    (create/update/delete) side of the item."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CourseContentRepository(session)
        self.course_repo = CourseRepository(session)
        self.learning_repo = LearningRepository(session)
        self.user_repo = UserRepository(session)
        self._daily = None

    @property
    def daily(self):
        if self._daily is None:
            self._daily = get_daily_client()
        return self._daily

    # -- join ------------------------------------------------------------------

    @staticmethod
    def _join_window(live_session: CourseLiveSession) -> tuple[datetime, datetime]:
        window_start = live_session.scheduled_start_at - timedelta(minutes=10)
        window_end = live_session.scheduled_start_at + timedelta(minutes=live_session.duration_minutes + 30)
        return window_start, window_end

    @staticmethod
    def _check_join_window(window_start: datetime, window_end: datetime) -> None:
        now = datetime.now(timezone.utc)
        if now < window_start:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This live session hasn't opened for joining yet")
        if now > window_end:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This live session has ended")

    async def get_join_info(self, item_id: uuid.UUID, current_user: User) -> LiveSessionJoinDTO:
        item = await self.repo.get_item(item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        live_session = await self.repo.get_live_session_by_item(item.id)
        if live_session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found for this item")

        section = await self.repo.get_section(item.section_id)
        course = await self.course_repo.get_by_id(section.course_id) if section else None
        if course is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")

        is_owner = current_user.user_type == UserTypeEnum.ADMIN or course.instructor_id == current_user.id
        if not is_owner:
            access = await self.learning_repo.get_user_course_access(current_user.id, course.id)
            if access is None:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "You are not enrolled in this course")

        window_start, window_end = self._join_window(live_session)
        self._check_join_window(window_start, window_end)

        token_exp = int(window_end.timestamp())
        token = await self.daily.create_meeting_token(
            room_name=live_session.daily_room_name,
            user_name=f"{current_user.first_name} {current_user.last_name}",
            is_owner=is_owner,
            exp=token_exp,
        )
        # The call runs entirely on daily.co's own hosted page (their subdomain,
        # e.g. socialworknigeria.daily.co) - not embedded in our frontend. Baking
        # the token into the URL as ?t=... lets the browser land there already
        # authenticated, no separate sign-in step on daily.co's side.
        join_url = f"{live_session.daily_room_url}?t={token}"
        return LiveSessionJoinDTO(
            join_url=join_url,
            is_owner=is_owner,
            expires_at=window_end,
        )

    # -- external (guest) invites ------------------------------------------------

    async def _get_owned_live_session(
        self, item_id: uuid.UUID, current_user: User
    ) -> tuple[CourseItem, Course, CourseLiveSession]:
        """Loads the live session for `item_id` and checks the caller is an admin
        or the course's own instructor - the same authorization `get_join_info`
        applies to owners, reused here since inviting external guests is an
        authoring action, not something any enrolled student can do."""
        item = await self.repo.get_item(item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
        live_session = await self.repo.get_live_session_by_item(item.id)
        if live_session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found for this item")

        section = await self.repo.get_section(item.section_id)
        course = await self.course_repo.get_by_id(section.course_id) if section else None
        if course is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")

        is_owner = current_user.user_type == UserTypeEnum.ADMIN or course.instructor_id == current_user.id
        if not is_owner:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You don't manage this course's live sessions")

        return item, course, live_session

    async def invite_external_guests(
        self,
        item_id: uuid.UUID,
        current_user: User,
        invites: list[tuple[str, str | None]],
    ) -> list[LiveSessionExternalInvite]:
        """Invites people who aren't (or may not be) enrolled - or platform users
        at all - to this specific live session, regardless of whether it has
        already started (only a CANCELLED/ENDED session is rejected, since
        there's nothing left to join). Each invite is a (email, name) pair;
        re-inviting an already-invited email rotates its token and un-revokes it
        rather than creating a duplicate row."""
        item, course, live_session = await self._get_owned_live_session(item_id, current_user)
        if live_session.status in (LiveSessionStatusEnum.ENDED, LiveSessionStatusEnum.CANCELLED):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This live session has already ended")

        _, window_end = self._join_window(live_session)
        content = self._build_notification_content(course, item, live_session)

        created: list[LiveSessionExternalInvite] = []
        for email, name in invites:
            email = email.strip().lower()
            invite = await self.repo.get_external_invite_by_email(live_session.id, email)
            raw_token = generate_opaque_token()
            if invite is None:
                invite = LiveSessionExternalInvite(
                    live_session_id=live_session.id,
                    email=email,
                    name=name,
                    invited_by_id=current_user.id,
                    token_hash=hash_token(raw_token),
                    expires_at=window_end,
                )
                self.session.add(invite)
            else:
                invite.name = name or invite.name
                invite.invited_by_id = current_user.id
                invite.token_hash = hash_token(raw_token)
                invite.expires_at = window_end
                invite.revoked_at = None
            await self.session.flush()

            join_link = f"{settings.frontend_url.rstrip('/')}/live-session/guest-join?token={raw_token}"
            try:
                await email_service.send_live_session_external_invite_email(
                    to_email=email,
                    guest_display_name=name or email,
                    course_title=course.title,
                    session_title=item.title,
                    start_at_display=content["display"],
                    join_link=join_link,
                    google_calendar_link=content["calendar_links"]["google"],
                    outlook_calendar_link=content["calendar_links"]["outlook"],
                    ics_bytes=content["ics_bytes"],
                )
            except Exception as exc:
                logger.warning("Failed to send live-session guest invite to %s: %s", email, exc)

            created.append(invite)

        await self.session.commit()
        return created

    async def list_external_invites(
        self, item_id: uuid.UUID, current_user: User
    ) -> list[LiveSessionExternalInvite]:
        _, _, live_session = await self._get_owned_live_session(item_id, current_user)
        return list(await self.repo.list_external_invites(live_session.id))

    async def revoke_external_invite(
        self, item_id: uuid.UUID, invite_id: uuid.UUID, current_user: User
    ) -> None:
        _, _, live_session = await self._get_owned_live_session(item_id, current_user)
        invite = await self.repo.get_external_invite(invite_id)
        if invite is None or invite.live_session_id != live_session.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
        invite.revoked_at = datetime.now(timezone.utc)
        await self.session.commit()

    async def get_external_join_info(self, token: str) -> LiveSessionExternalJoinDTO:
        """Public, unauthenticated join path for an external invite. No enrollment
        or platform account is checked - only that the token is valid, unrevoked,
        unexpired, and that the session's own join window has opened."""
        invite = await self.repo.get_external_invite_by_token_hash(hash_token(token))
        if invite is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
        if invite.revoked_at is not None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This invite has been revoked")
        now = datetime.now(timezone.utc)
        if invite.expires_at < now:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This invite link has expired")

        live_session = await self.repo.get_live_session(invite.live_session_id)
        if live_session is None or live_session.status == LiveSessionStatusEnum.CANCELLED:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Live session not found")

        window_start, window_end = self._join_window(live_session)
        self._check_join_window(window_start, window_end)

        token_exp = int(window_end.timestamp())
        meeting_token = await self.daily.create_meeting_token(
            room_name=live_session.daily_room_name,
            user_name=invite.name or invite.email,
            is_owner=False,
            exp=token_exp,
        )
        invite.last_joined_at = now
        invite.join_count += 1
        await self.session.commit()

        join_url = f"{live_session.daily_room_url}?t={meeting_token}"
        return LiveSessionExternalJoinDTO(join_url=join_url, expires_at=window_end)

    # -- notifications -----------------------------------------------------------

    def _build_notification_content(self, course: Course, item: CourseItem, live_session: CourseLiveSession) -> dict:
        start = live_session.scheduled_start_at
        end = start + timedelta(minutes=live_session.duration_minutes)
        display = start.strftime("%A, %B %d, %Y at %I:%M %p UTC")
        description = f"Live session for {course.title}: {item.title}"
        calendar_links = build_calendar_links(item.title, description, start, end, live_session.daily_room_url)
        ics_bytes = build_ics(
            uid=f"live-session-{live_session.id}@{settings.company_name.lower().replace(' ', '-')}",
            summary=item.title,
            description=description,
            start=start,
            end=end,
            location_url=live_session.daily_room_url,
            organizer_email=settings.company_support_email,
        )
        return {"display": display, "calendar_links": calendar_links, "ics_bytes": ics_bytes}

    async def notify_enrolled_students(
        self,
        course: Course,
        item: CourseItem,
        live_session: CourseLiveSession,
        kind: str,
        previous_start_display: str | None = None,
    ) -> None:
        user_ids = await self.learning_repo.list_enrolled_user_ids(course.id)
        if not user_ids:
            return

        content = self._build_notification_content(course, item, live_session)
        join_link = f"{settings.frontend_url.rstrip('/')}/courses/{course.slug}/live-session/{item.id}"
        notifications = NotificationService(self.session)

        for user_id in user_ids:
            user = await self.user_repo.get_by_id(user_id)
            if user is None:
                continue
            try:
                if kind == "scheduled":
                    await email_service.send_live_session_scheduled_email(
                        to_email=user.email,
                        first_name=user.first_name,
                        course_title=course.title,
                        session_title=item.title,
                        start_at_display=content["display"],
                        guest_name=live_session.guest_name,
                        guest_title=live_session.guest_title,
                        join_link=join_link,
                        google_calendar_link=content["calendar_links"]["google"],
                        outlook_calendar_link=content["calendar_links"]["outlook"],
                        ics_bytes=content["ics_bytes"],
                    )
                    await notifications.notify_live_session_scheduled(
                        user, course.id, course.slug, item.id, item.title, content["display"]
                    )
                elif kind == "rescheduled":
                    await email_service.send_live_session_rescheduled_email(
                        to_email=user.email,
                        first_name=user.first_name,
                        course_title=course.title,
                        session_title=item.title,
                        old_start_at_display=previous_start_display or "",
                        new_start_at_display=content["display"],
                        join_link=join_link,
                        google_calendar_link=content["calendar_links"]["google"],
                        outlook_calendar_link=content["calendar_links"]["outlook"],
                        ics_bytes=content["ics_bytes"],
                    )
                    await notifications.notify_live_session_rescheduled(
                        user, course.id, course.slug, item.id, item.title, content["display"]
                    )
                elif kind == "reminder":
                    await email_service.send_live_session_reminder_email(
                        to_email=user.email,
                        first_name=user.first_name,
                        course_title=course.title,
                        session_title=item.title,
                        start_at_display=content["display"],
                        join_link=join_link,
                    )
                    await notifications.notify_live_session_reminder(
                        user, course.id, course.slug, item.id, item.title, content["display"]
                    )
            except Exception as exc:
                logger.warning("Failed to send live-session %s email to %s: %s", kind, user.email, exc)

        now = datetime.now(timezone.utc)
        if kind in ("scheduled", "rescheduled"):
            live_session.invite_sent_at = now
        elif kind == "reminder":
            live_session.reminder_sent_at = now
        await self.session.commit()

    async def schedule_reminder(self, live_session_id: uuid.UUID, scheduled_start_at: datetime) -> None:
        if not settings.qstash_token:
            return
        delay_seconds = (
            scheduled_start_at - timedelta(minutes=settings.live_session_reminder_minutes) - datetime.now(timezone.utc)
        ).total_seconds()
        if delay_seconds <= 0:
            return
        try:
            client = get_qstash_client()
            await client.message.publish_json(
                url=f"{settings.api_base_url.rstrip('/')}/courses/cron/live-session-reminder",
                body={"live_session_id": str(live_session_id)},
                delay=int(delay_seconds),
            )
        except Exception as exc:
            logger.warning("Failed to schedule live-session reminder for %s: %s", live_session_id, exc)

    async def run_reminder(self, live_session_id: uuid.UUID) -> None:
        live_session = await self.repo.get_live_session(live_session_id)
        if live_session is None or live_session.reminder_sent_at is not None:
            return
        if live_session.status != LiveSessionStatusEnum.SCHEDULED:
            return
        item = await self.repo.get_item(live_session.course_item_id)
        section = await self.repo.get_section(item.section_id) if item else None
        course = await self.course_repo.get_by_id(section.course_id) if section else None
        if item is None or course is None:
            return
        await self.notify_enrolled_students(course, item, live_session, kind="reminder")

    # -- webhook -----------------------------------------------------------------

    async def handle_daily_webhook(self, event_type: str, payload: dict) -> None:
        room_name = payload.get("room") or payload.get("room_name")
        if not room_name:
            return
        live_session = await self._get_live_session_by_room(room_name)
        if live_session is None:
            return

        if event_type == "meeting.ended":
            live_session.status = LiveSessionStatusEnum.ENDED
        elif event_type == "recording.ready-to-download":
            recording_id = payload.get("recording_id")
            if recording_id:
                # Store the id, not a playback URL - daily.co's access-links expire
                # within hours, so a playable link is minted fresh on every request
                # (see LearningService.get_item_content) instead of being persisted.
                live_session.recording_id = recording_id
                live_session.recording_status = VideoStatusEnum.READY

        await self.session.commit()

    async def _get_live_session_by_room(self, room_name: str) -> CourseLiveSession | None:
        stmt = select(CourseLiveSession).where(CourseLiveSession.daily_room_name == room_name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

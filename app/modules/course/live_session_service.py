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
from app.modules.course.content_dto import LiveSessionJoinDTO
from app.modules.course.content_entity import CourseLiveSession, LiveSessionStatusEnum, VideoStatusEnum
from app.modules.course.content_repository import CourseContentRepository
from app.modules.course.entity import Course, CourseItem
from app.modules.course.repository import CourseRepository
from app.modules.learning.repository import LearningRepository
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

        now = datetime.now(timezone.utc)
        window_start = live_session.scheduled_start_at - timedelta(minutes=10)
        window_end = live_session.scheduled_start_at + timedelta(minutes=live_session.duration_minutes + 30)
        if now < window_start:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This live session hasn't opened for joining yet")
        if now > window_end:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This live session has ended")

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
                elif kind == "reminder":
                    await email_service.send_live_session_reminder_email(
                        to_email=user.email,
                        first_name=user.first_name,
                        course_title=course.title,
                        session_title=item.title,
                        start_at_display=content["display"],
                        join_link=join_link,
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
                download_link = await self.daily.get_recording_download_link(recording_id)
                live_session.recording_status = VideoStatusEnum.READY
                live_session.recording_playback_url = download_link

        await self.session.commit()

    async def _get_live_session_by_room(self, room_name: str) -> CourseLiveSession | None:
        stmt = select(CourseLiveSession).where(CourseLiveSession.daily_room_name == room_name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

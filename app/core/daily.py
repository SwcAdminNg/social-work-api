import time
import uuid
from datetime import datetime
from functools import lru_cache

import httpx

from app.core.config import settings


class DailyClient:
    """Wraps daily.co's REST API for scheduled live-session rooms. Rooms are
    created server-side per live-session curriculum item; per-participant join
    tokens are minted on demand (never reused across sessions/users) so access
    can be revoked simply by not issuing one."""

    def __init__(self) -> None:
        self._api_key = settings.daily_api_key
        self._api_base = settings.daily_api_base_url

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def build_room_name(self, course_item_id: uuid.UUID) -> str:
        return f"session-{course_item_id}-{uuid.uuid4().hex[:8]}"

    async def create_room(
        self, name: str, scheduled_start_at: datetime, duration_minutes: int
    ) -> dict:
        # Joinable from 10 minutes before start until 30 minutes after the
        # scheduled end, then daily.co auto-ejects any stragglers.
        nbf = int(scheduled_start_at.timestamp()) - 600
        exp = int(scheduled_start_at.timestamp()) + duration_minutes * 60 + 1800
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._api_base}/rooms",
                headers=self._headers(),
                json={
                    "name": name,
                    "privacy": "private",
                    "properties": {
                        "nbf": nbf,
                        "exp": exp,
                        "enable_recording": "cloud",
                        "eject_at_room_exp": True,
                        "enable_chat": True,
                        "enable_prejoin_ui": True,
                    },
                },
            )
            response.raise_for_status()
            return response.json()

    async def update_room_schedule(
        self, room_name: str, scheduled_start_at: datetime, duration_minutes: int
    ) -> dict:
        nbf = int(scheduled_start_at.timestamp()) - 600
        exp = int(scheduled_start_at.timestamp()) + duration_minutes * 60 + 1800
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._api_base}/rooms/{room_name}",
                headers=self._headers(),
                json={"properties": {"nbf": nbf, "exp": exp}},
            )
            response.raise_for_status()
            return response.json()

    async def delete_room(self, room_name: str) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.delete(f"{self._api_base}/rooms/{room_name}", headers=self._headers())
            if response.status_code != 404:
                response.raise_for_status()

    async def create_meeting_token(
        self, room_name: str, user_name: str, is_owner: bool, exp: int
    ) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._api_base}/meeting-tokens",
                headers=self._headers(),
                json={
                    "properties": {
                        "room_name": room_name,
                        "user_name": user_name,
                        "is_owner": is_owner,
                        "exp": exp,
                    }
                },
            )
            response.raise_for_status()
            return response.json()["token"]

    async def get_recording_download_link(self, recording_id: str) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._api_base}/recordings/{recording_id}/access-link", headers=self._headers()
            )
            response.raise_for_status()
            return response.json()["download_link"]


@lru_cache
def get_daily_client() -> DailyClient:
    return DailyClient()

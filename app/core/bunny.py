import hashlib
import time
from functools import lru_cache

import httpx

from app.core.config import settings

_API_BASE = "https://video.bunnycdn.com"
_TUS_ENDPOINT = "https://video.bunnycdn.com/tusupload"


class BunnyStreamClient:
    """Wraps Bunny Stream's REST API. Videos are created server-side (to get a
    guid) but the actual bytes are uploaded by the frontend straight to Bunny
    via a TUS resumable upload, using signed credentials we hand back."""

    def __init__(self) -> None:
        self._library_id = settings.bunny_stream_library_id
        self._api_key = settings.bunny_stream_api_key

    async def create_video(self, title: str) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{_API_BASE}/library/{self._library_id}/videos",
                headers={"AccessKey": self._api_key, "Content-Type": "application/json"},
                json={"title": title},
            )
            response.raise_for_status()
            return response.json()["guid"]

    async def delete_video(self, video_guid: str) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{_API_BASE}/library/{self._library_id}/videos/{video_guid}",
                headers={"AccessKey": self._api_key},
            )
            response.raise_for_status()

    def build_tus_credentials(self, video_guid: str) -> dict:
        expire = int(time.time()) + settings.bunny_tus_upload_expire_seconds
        signature = hashlib.sha256(
            f"{self._library_id}{self._api_key}{expire}{video_guid}".encode()
        ).hexdigest()
        return {
            "tus_endpoint": _TUS_ENDPOINT,
            "library_id": self._library_id,
            "video_id": video_guid,
            "authorization_signature": signature,
            "authorization_expire": expire,
        }

    def build_playback_url(self, video_guid: str) -> str:
        url = f"https://{settings.bunny_stream_cdn_hostname}/{video_guid}/playlist.m3u8"
        if settings.bunny_stream_token_auth_key:
            expire = int(time.time()) + 3600  # 1 hour expiration
            signature = hashlib.sha256(
                f"{settings.bunny_stream_token_auth_key}{video_guid}{expire}".encode()
            ).hexdigest()
            url += f"?token={signature}&expires={expire}"
        return url

    def build_thumbnail_url(self, video_guid: str) -> str:
        return f"https://{settings.bunny_stream_cdn_hostname}/{video_guid}/thumbnail.jpg"


@lru_cache
def get_bunny_client() -> BunnyStreamClient:
    return BunnyStreamClient()

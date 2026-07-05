import uuid
from functools import lru_cache
from urllib.parse import quote

import boto3

from app.core.config import settings


class R2Client:
    """Thin wrapper around Cloudflare R2's S3-compatible API, used only to mint
    short-lived presigned URLs so the frontend can upload/download documents
    directly - file bytes never pass through our server."""

    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )

    def build_document_key(self, course_id: uuid.UUID, file_name: str) -> str:
        return f"courses/{course_id}/documents/{uuid.uuid4()}-{file_name}"

    def build_thumbnail_key(self, course_id: uuid.UUID, file_name: str) -> str:
        return f"courses/{course_id}/thumbnails/{uuid.uuid4()}-{file_name}"

    def generate_upload_url(self, key: str, content_type: str | None = None) -> str:
        params = {"Bucket": settings.r2_bucket_name, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        return self._client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=settings.presigned_url_expire_seconds
        )

    def generate_download_url(self, key: str) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.r2_bucket_name, "Key": key},
            ExpiresIn=settings.presigned_url_expire_seconds,
        )

    def get_public_url(self, key: str) -> str:
        return f"{settings.r2_public_url.rstrip('/')}/{quote(key, safe=':/')}"


@lru_cache
def get_r2_client() -> R2Client:
    return R2Client()

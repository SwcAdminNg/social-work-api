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

    def build_avatar_key(self, user_id: uuid.UUID, file_name: str) -> str:
        return f"users/{user_id}/avatar/{uuid.uuid4()}-{file_name}"

    def build_essay_document_key(self, item_id: uuid.UUID, user_id: uuid.UUID, file_name: str) -> str:
        return f"essays/{item_id}/{user_id}/{uuid.uuid4()}-{file_name}"

    def build_certificate_template_image_key(self, template_id: uuid.UUID, file_name: str) -> str:
        return f"certificate-templates/{template_id}/{uuid.uuid4()}-{file_name}"

    def build_certificate_pdf_key(self, course_id: uuid.UUID, user_id: uuid.UUID, certificate_id: uuid.UUID) -> str:
        return f"certificates/{course_id}/{user_id}/{certificate_id}.pdf"

    def build_support_attachment_key(self, ticket_id: uuid.UUID, file_name: str) -> str:
        return f"support-tickets/{ticket_id}/attachments/{uuid.uuid4()}-{file_name}"

    def build_resource_thumbnail_key(self, resource_id: uuid.UUID, file_name: str) -> str:
        return f"resources/{resource_id}/thumbnails/{uuid.uuid4()}-{file_name}"

    def build_resource_document_key(self, resource_id: uuid.UUID, file_name: str) -> str:
        return f"resources/{resource_id}/documents/{uuid.uuid4()}-{file_name}"

    def upload_bytes(self, key: str, data: bytes, content_type: str) -> None:
        """Direct server-side upload, unlike `generate_upload_url` - used only for
        content we generate ourselves (e.g. rendered certificate PDFs), never for
        user-supplied file bytes."""
        self._client.put_object(Bucket=settings.r2_bucket_name, Key=key, Body=data, ContentType=content_type)

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

    def delete_object(self, key: str) -> None:
        self._client.delete_object(Bucket=settings.r2_bucket_name, Key=key)

    def delete_many_objects(self, keys: list[str]) -> None:
        if not keys:
            return
        self._client.delete_objects(
            Bucket=settings.r2_bucket_name,
            Delete={"Objects": [{"Key": key} for key in keys]},
        )

    def get_public_url(self, key: str) -> str:
        return f"{settings.r2_public_url.rstrip('/')}/{quote(key, safe=':/')}"


@lru_cache
def get_r2_client() -> R2Client:
    return R2Client()

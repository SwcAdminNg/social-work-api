"""Serves unpacked SCORM / interactive packages to the learner's iframe and
receives the runtime data the package reports back.

Everything hangs off a signed launch token embedded in the URL path
(`/scorm/{token}/index.html`), so the package's own relative asset URLs
(`assets/audio/1-01.mp3`) resolve to `/scorm/{token}/assets/...` and are
authorised without cookies or headers - neither of which an iframe sends
across origins. The token is minted by the learning item endpoint (learn mode,
progress is saved) or the staff preview endpoint (browse mode, nothing saved).
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import ApiResponse
from app.core.database import get_db
from app.core.storage import get_r2_client
from app.modules.course import scorm as scorm_lib
from app.modules.course.content_entity import CourseScormPackage, VideoStatusEnum
from app.modules.course.content_repository import CourseContentRepository
from app.modules.learning.dto import ScormCommitDTO, ScormCommitResultDTO
from app.modules.learning.repository import LearningRepository
from app.modules.learning.service import LearningService

router = APIRouter(prefix="/scorm", tags=["Learning"])

_CHUNK = 256 * 1024
_HTML_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_ASSET_HEADERS = {
    "Cache-Control": "private, max-age=3600",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Accept-Ranges": "bytes",
}


async def _resolve(token: str, db: AsyncSession) -> tuple[scorm_lib.LaunchClaims, CourseScormPackage]:
    claims = scorm_lib.decode_launch_token(token)
    if claims is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This lesson link has expired - reopen the lesson")
    package = await CourseContentRepository(db).get_scorm_package(claims.package_id)
    if (
        package is None
        or package.course_item_id != claims.item_id
        or package.status != VideoStatusEnum.READY
        or not package.extracted_prefix
        or not package.launch_path
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Package not available")
    return claims, package


@router.get("/{token}/{path:path}", include_in_schema=False)
async def serve_package_file(
    token: str, path: str, request: Request, db: AsyncSession = Depends(get_db)
) -> Response:
    claims, package = await _resolve(token, db)
    rel = scorm_lib.safe_package_path(path)
    if rel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    r2 = get_r2_client()
    key = f"{package.extracted_prefix}/{rel}"
    is_launch = rel.lower() == package.launch_path.lower()

    if is_launch:
        if claims.mode == "learn":
            access = await LearningRepository(db).get_user_course_access(claims.user_id, claims.course_id)
            if not access:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "You are no longer enrolled in this course")
        obj = await asyncio.to_thread(scorm_lib.fetch_object, r2, key)
        if obj is None or obj.get("_invalid_range"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Launch page not found in the package")
        body = await asyncio.to_thread(obj["Body"].read)
        seed = await LearningService(db).build_scorm_runtime_seed(
            claims.user_id, claims.course_id, claims.item_id, claims.mode, scorm_lib.build_commit_url(token)
        )
        seed["version"] = package.scorm_version
        seed["sessionId"] = uuid.uuid4().hex
        return Response(
            content=scorm_lib.build_launch_html(body, seed),
            media_type="text/html; charset=utf-8",
            headers=_HTML_HEADERS,
        )

    range_header = request.headers.get("range")
    obj = await asyncio.to_thread(scorm_lib.fetch_object, r2, key, range_header)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    if obj.get("_invalid_range"):
        return Response(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, headers=_ASSET_HEADERS)

    content_type = obj.get("ContentType") or scorm_lib.guess_content_type(rel)
    if content_type in ("binary/octet-stream", "application/octet-stream"):
        content_type = scorm_lib.guess_content_type(rel)
    headers = dict(_ASSET_HEADERS)
    if obj.get("ContentLength") is not None:
        headers["Content-Length"] = str(obj["ContentLength"])
    status_code = status.HTTP_200_OK
    if range_header and obj.get("ContentRange"):
        headers["Content-Range"] = obj["ContentRange"]
        status_code = status.HTTP_206_PARTIAL_CONTENT
    if request.method == "HEAD":
        return Response(status_code=status_code, headers=headers, media_type=content_type)
    return StreamingResponse(
        obj["Body"].iter_chunks(_CHUNK), status_code=status_code, media_type=content_type, headers=headers
    )


@router.post(
    "/{token}/_lms/commit",
    response_model=ApiResponse[ScormCommitResultDTO],
    summary="Runtime data reported by a running SCORM / interactive package (called by the "
    "injected LMS API shim, authorised by the launch token in the path)",
)
async def commit_package_runtime(
    token: str, payload: ScormCommitDTO, db: AsyncSession = Depends(get_db)
) -> ApiResponse[ScormCommitResultDTO]:
    claims, _ = await _resolve(token, db)
    if claims.mode != "learn":
        return ApiResponse(message="Preview mode - nothing saved", data=ScormCommitResultDTO(is_completed=False))
    result = await LearningService(db).commit_scorm(claims.user_id, claims.course_id, claims.item_id, payload)
    return ApiResponse(message="Progress saved", data=result)

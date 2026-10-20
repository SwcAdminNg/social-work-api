"""SCORM / interactive-package support for course items.

Three pieces live here, all pure helpers with no database access:

* **Ingestion** - `ingest_package` downloads the uploaded zip from R2, checks it
  is safe (no path traversal, within size/file limits), finds the launch file
  (from `imsmanifest.xml`, else `index.html`) and copies every file into an
  extracted prefix in R2 with a sensible content type.
* **Launch tokens** - a short-lived JWT that identifies (user, item, package,
  mode). It is a *path segment* of the launch URL, so every relative asset the
  package requests (`assets/audio/1-01.mp3`) resolves under the same token and
  can be authorised without cookies or headers - which an iframe can't send.
* **Serving** - `build_launch_html` injects the runtime shim (scorm_api.js) and
  the learner's saved data into the launch page; `stream_object` proxies any
  other file from R2 with Range support so audio/video seek correctly.
"""

from __future__ import annotations

import io
import json
import mimetypes
import os
import posixpath
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from xml.etree import ElementTree

import jwt

from app.core.config import settings
from app.core.storage import R2Client

LAUNCH_TOKEN_TYPE = "scorm_launch"
MANIFEST_NAME = "imsmanifest.xml"
_MANIFEST_MAX_BYTES = 2 * 1024 * 1024

_EXTRA_MIME = {
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".mjs": "text/javascript",
    ".js": "text/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".vtt": "text/vtt",
    ".xml": "application/xml",
    ".css": "text/css",
    ".html": "text/html",
    ".htm": "text/html",
    ".wasm": "application/wasm",
}

mimetypes.init()


class ScormPackageError(ValueError):
    """The uploaded zip is not something we can serve. The message is safe to
    show to the instructor/admin who uploaded it."""


@dataclass
class ManifestInfo:
    launch_path: str | None = None
    scorm_version: str | None = None
    identifier: str | None = None
    title: str | None = None


@dataclass
class IngestResult:
    extracted_prefix: str
    launch_path: str
    file_count: int
    total_size_bytes: int
    manifest: ManifestInfo = field(default_factory=ManifestInfo)


# ---------------------------------------------------------------------------
# Manifest + zip handling
# ---------------------------------------------------------------------------


def guess_content_type(path: str) -> str:
    ext = posixpath.splitext(path.lower())[1]
    if ext in _EXTRA_MIME:
        return _EXTRA_MIME[ext]
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_manifest(xml_bytes: bytes) -> ManifestInfo:
    """Pulls the launch href and metadata out of an IMS manifest. Tolerant of
    SCORM 1.2 and 2004 namespaces; returns an empty info object when the XML
    can't be read rather than failing the whole upload."""
    info = ManifestInfo()
    if len(xml_bytes) > _MANIFEST_MAX_BYTES:
        return info
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return info

    info.identifier = (root.attrib.get("identifier") or "").strip() or None

    for el in root.iter():
        if _local(el.tag) == "schemaversion" and el.text:
            version = el.text.strip()
            info.scorm_version = "2004" if version.lower().startswith("2004") or "cam" in version.lower() else version
            break

    resources: dict[str, dict[str, str | None]] = {}
    for el in root.iter():
        if _local(el.tag) != "resource":
            continue
        ident = el.attrib.get("identifier")
        if not ident:
            continue
        scorm_type = next((v for k, v in el.attrib.items() if _local(k) == "scormtype" or _local(k) == "scormType"), None)
        resources[ident] = {"href": el.attrib.get("href"), "scormtype": scorm_type}

    organizations = [el for el in root.iter() if _local(el.tag) == "organizations"]
    default_org = organizations[0].attrib.get("default") if organizations else None
    chosen_org = None
    for el in root.iter():
        if _local(el.tag) == "organization":
            if chosen_org is None or (default_org and el.attrib.get("identifier") == default_org):
                chosen_org = el
    if chosen_org is not None:
        for child in chosen_org:
            if _local(child.tag) == "title" and child.text and child.text.strip():
                info.title = child.text.strip()[:500]
                break
        for el in chosen_org.iter():
            if _local(el.tag) != "item":
                continue
            ref = el.attrib.get("identifierref")
            if ref and ref in resources and resources[ref]["href"]:
                info.launch_path = resources[ref]["href"]
                break

    if info.launch_path is None:
        for res in resources.values():
            if res["href"] and (res["scormtype"] or "").lower() == "sco":
                info.launch_path = res["href"]
                break
    if info.launch_path is None:
        for res in resources.values():
            if res["href"]:
                info.launch_path = res["href"]
                break

    if info.launch_path:
        info.launch_path = info.launch_path.split("?", 1)[0].split("#", 1)[0].lstrip("./")
    return info


def _safe_relative_path(name: str) -> str | None:
    """Normalises a zip entry name to a clean, forward-slash relative path or
    returns None when the entry must be skipped (directories, absolute paths,
    traversal, OS metadata)."""
    if not name or name.endswith("/"):
        return None
    name = name.replace("\\", "/")
    if name.startswith("/") or ":" in name.split("/", 1)[0]:
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    if parts[0] == "__MACOSX" or parts[-1] == ".DS_Store" or parts[-1] == "Thumbs.db":
        return None
    return "/".join(parts)


def inspect_zip(zf: zipfile.ZipFile) -> tuple[list[tuple[zipfile.ZipInfo, str]], str, ManifestInfo]:
    """Validates the archive and works out its content root. Returns the
    (zip entry, path relative to the root) pairs to extract, the root prefix
    inside the zip and the manifest info (empty for plain HTML packages)."""
    entries: list[tuple[zipfile.ZipInfo, str]] = []
    total = 0
    for zi in zf.infolist():
        rel = _safe_relative_path(zi.filename)
        if rel is None:
            continue
        total += zi.file_size
        entries.append((zi, rel))

    if not entries:
        raise ScormPackageError("The zip file is empty")
    if len(entries) > settings.scorm_max_files:
        raise ScormPackageError(f"The package has too many files (limit is {settings.scorm_max_files})")
    if total > settings.scorm_max_package_bytes:
        limit_mb = settings.scorm_max_package_bytes // (1024 * 1024)
        raise ScormPackageError(f"The unpacked package is larger than the {limit_mb} MB limit")

    paths = {rel for _, rel in entries}

    def shallowest(filename: str) -> str | None:
        candidates = [p for p in paths if posixpath.basename(p).lower() == filename]
        if not candidates:
            return None
        return min(candidates, key=lambda p: (p.count("/"), p))

    # Many packages are zipped with a single wrapper folder; whichever directory
    # holds the manifest (or, failing that, index.html) becomes the root.
    manifest_path = shallowest(MANIFEST_NAME)
    root = ""
    manifest = ManifestInfo()
    if manifest_path is not None:
        root = posixpath.dirname(manifest_path)
        manifest = parse_manifest(zf.read(manifest_path))
    else:
        index_path = shallowest("index.html") or shallowest("index.htm") or shallowest("story.html")
        if index_path is None:
            raise ScormPackageError(
                "No imsmanifest.xml or index.html found - upload a SCORM package or a zipped web page"
            )
        root = posixpath.dirname(index_path)

    prefix = f"{root}/" if root else ""
    scoped = [(zi, rel[len(prefix):]) for zi, rel in entries if rel.startswith(prefix)]
    scoped_paths = {rel for _, rel in scoped}

    launch = manifest.launch_path
    if launch and launch not in scoped_paths:
        # Manifest hrefs are occasionally relative to a sub-folder or use odd casing.
        lowered = {p.lower(): p for p in scoped_paths}
        launch = lowered.get(launch.lower())
    if not launch:
        for candidate in ("index.html", "index.htm", "story.html", "index_lms.html", "launch.html"):
            if candidate in scoped_paths:
                launch = candidate
                break
    if not launch:
        html = sorted(p for p in scoped_paths if p.lower().endswith((".html", ".htm")))
        launch = html[0] if html else None
    if not launch:
        raise ScormPackageError("Could not find a launch page (index.html) in the package")
    manifest.launch_path = launch
    return scoped, root, manifest


def ingest_package(r2: R2Client, zip_key: str, extracted_prefix: str) -> IngestResult:
    """Synchronous (run it in a thread): downloads the zip from R2, validates it
    and uploads every file under `extracted_prefix`."""
    try:
        obj = r2._client.get_object(Bucket=settings.r2_bucket_name, Key=zip_key)
    except Exception as exc:  # noqa: BLE001 - boto raises many client error types
        raise ScormPackageError("The uploaded file could not be found in storage - try uploading again") from exc

    size = int(obj.get("ContentLength") or 0)
    if size > settings.scorm_max_package_bytes:
        limit_mb = settings.scorm_max_package_bytes // (1024 * 1024)
        raise ScormPackageError(f"The zip is larger than the {limit_mb} MB limit")
    buffer = io.BytesIO(obj["Body"].read())

    try:
        zf = zipfile.ZipFile(buffer)
    except zipfile.BadZipFile as exc:
        raise ScormPackageError("The uploaded file is not a valid zip archive") from exc

    with zf:
        entries, _, manifest = inspect_zip(zf)
        total = 0
        for zi, rel in entries:
            with zf.open(zi) as fh:
                body = fh.read()
            total += len(body)
            r2._client.put_object(
                Bucket=settings.r2_bucket_name,
                Key=f"{extracted_prefix}/{rel}",
                Body=body,
                ContentType=guess_content_type(rel),
            )

    return IngestResult(
        extracted_prefix=extracted_prefix,
        launch_path=manifest.launch_path or "index.html",
        file_count=len(entries),
        total_size_bytes=total,
        manifest=manifest,
    )


# ---------------------------------------------------------------------------
# Launch tokens
# ---------------------------------------------------------------------------


def create_launch_token(
    *, user_id: uuid.UUID, item_id: uuid.UUID, package_id: uuid.UUID, course_id: uuid.UUID, mode: str
) -> str:
    """`mode` is "learn" (progress is saved) or "preview" (staff preview, nothing
    is saved). Expiry is long enough to sit through a whole lesson."""
    expire_at = datetime.now(timezone.utc) + timedelta(minutes=settings.scorm_launch_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": LAUNCH_TOKEN_TYPE,
        "item": str(item_id),
        "pkg": str(package_id),
        "course": str(course_id),
        "mode": mode,
        "exp": expire_at,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@dataclass
class LaunchClaims:
    user_id: uuid.UUID
    item_id: uuid.UUID
    package_id: uuid.UUID
    course_id: uuid.UUID
    mode: str


def decode_launch_token(token: str) -> LaunchClaims | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != LAUNCH_TOKEN_TYPE:
        return None
    try:
        return LaunchClaims(
            user_id=uuid.UUID(payload["sub"]),
            item_id=uuid.UUID(payload["item"]),
            package_id=uuid.UUID(payload["pkg"]),
            course_id=uuid.UUID(payload["course"]),
            mode=str(payload.get("mode") or "learn"),
        )
    except (KeyError, ValueError):
        return None


def build_launch_url(token: str, launch_path: str) -> str:
    return f"{settings.api_base_url.rstrip('/')}/scorm/{token}/{launch_path.lstrip('/')}"


def build_commit_url(token: str) -> str:
    return f"{settings.api_base_url.rstrip('/')}/scorm/{token}/_lms/commit"


# ---------------------------------------------------------------------------
# Serving
# ---------------------------------------------------------------------------


@lru_cache
def _shim_source() -> str:
    with open(os.path.join(os.path.dirname(__file__), "scorm_api.js"), encoding="utf-8") as fh:
        return fh.read()


def format_total_time_12(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:04d}:{minutes:02d}:{secs:02d}"


def format_total_time_2004(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    out = "PT"
    if hours:
        out += f"{hours}H"
    if minutes:
        out += f"{minutes}M"
    if secs or out == "PT":
        out += f"{secs}S"
    return out


def build_launch_html(html: bytes, seed: dict[str, Any]) -> bytes:
    """Injects the runtime seed + shim at the top of <head> so it is defined
    before any of the package's own scripts run."""
    seed_json = json.dumps(seed).replace("</", "<\\/")
    block = f"<script>window.__SWN_SCORM__={seed_json};</script>\n<script>{_shim_source()}</script>\n"
    text = html.decode("utf-8", errors="replace")
    lowered = text.lower()
    idx = lowered.find("<head")
    if idx != -1:
        end = lowered.find(">", idx)
        if end != -1:
            return (text[: end + 1] + "\n" + block + text[end + 1 :]).encode("utf-8")
    idx = lowered.find("<html")
    if idx != -1:
        end = lowered.find(">", idx)
        if end != -1:
            return (text[: end + 1] + "\n" + block + text[end + 1 :]).encode("utf-8")
    return (block + text).encode("utf-8")


def safe_package_path(path: str) -> str | None:
    rel = _safe_relative_path(path)
    return rel


def fetch_object(r2: R2Client, key: str, range_header: str | None = None) -> dict | None:
    """Synchronous R2 GET (run in a thread). Returns the boto response dict, or
    None when the key does not exist."""
    params: dict[str, Any] = {"Bucket": settings.r2_bucket_name, "Key": key}
    if range_header:
        params["Range"] = range_header
    try:
        return r2._client.get_object(**params)
    except r2._client.exceptions.NoSuchKey:
        return None
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "response", {}).get("Error", {}).get("Code") if hasattr(exc, "response") else None
        if code in ("NoSuchKey", "404", "NotFound"):
            return None
        if code in ("InvalidRange",):
            return {"_invalid_range": True}
        raise

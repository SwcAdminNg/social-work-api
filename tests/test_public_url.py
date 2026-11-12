"""Links handed to browsers must never point at localhost on a deployed API
(SCORM lessons showed "localhost refused to connect" on staging)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import public_url
from app.core.public_url import RequestBaseURLMiddleware, public_api_base_url
from app.modules.course import scorm as scorm_lib


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestBaseURLMiddleware)

    @app.get("/launch")
    def launch() -> dict:
        return {
            "base": public_api_base_url(),
            "launch": scorm_lib.build_launch_url("tok", "index.html"),
            "commit": scorm_lib.build_commit_url("tok"),
        }

    return app


def test_unset_base_url_falls_back_to_request_host(monkeypatch):
    monkeypatch.setattr(public_url.settings, "api_base_url", "http://localhost:8000")
    client = TestClient(_app(), base_url="https://social-work-api-staging.up.railway.app")
    data = client.get("/launch").json()
    assert data["base"] == "https://social-work-api-staging.up.railway.app"
    assert data["launch"] == "https://social-work-api-staging.up.railway.app/scorm/tok/index.html"
    assert data["commit"] == "https://social-work-api-staging.up.railway.app/scorm/tok/_lms/commit"


def test_configured_public_base_url_wins(monkeypatch):
    monkeypatch.setattr(public_url.settings, "api_base_url", "https://api.example.org/")
    client = TestClient(_app(), base_url="http://internal-host:8080")
    assert client.get("/launch").json()["launch"] == "https://api.example.org/scorm/tok/index.html"


def test_loopback_variants_are_ignored(monkeypatch):
    for value in ("http://127.0.0.1:8000", "http://0.0.0.0:8000", "http://app.localhost", ""):
        monkeypatch.setattr(public_url.settings, "api_base_url", value)
        client = TestClient(_app(), base_url="https://public.example.org")
        assert client.get("/launch").json()["base"] == "https://public.example.org"


def test_outside_a_request_uses_configured_value(monkeypatch):
    monkeypatch.setattr(public_url.settings, "api_base_url", "http://localhost:8000")
    assert public_api_base_url() == "http://localhost:8000"

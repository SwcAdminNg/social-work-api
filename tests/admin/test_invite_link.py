"""Admin invite emails must open the admin panel (the student site has no
/accept-admin-invite page, so invitees landed on a 404)."""

from app.modules.admin import service


def test_invite_link_uses_admin_panel(monkeypatch):
    monkeypatch.setattr(service.settings, "frontend_url", "https://www.socialworknigeria.org")
    monkeypatch.setattr(service.settings, "admin_frontend_url", "https://mgnt.socialworknigeria.org/")
    assert service.admin_invite_link("abc") == "https://mgnt.socialworknigeria.org/accept-admin-invite?token=abc"


def test_invite_link_falls_back_to_frontend_url(monkeypatch):
    monkeypatch.setattr(service.settings, "frontend_url", "http://localhost:3000")
    monkeypatch.setattr(service.settings, "admin_frontend_url", "")
    assert service.admin_invite_link("abc") == "http://localhost:3000/accept-admin-invite?token=abc"

import sqlite3
from pathlib import Path

import pytest

from llmgrader.app import create_app


@pytest.fixture()
def app_factory(tmp_path: Path, monkeypatch):
    storage_path = tmp_path / "storage"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LLMGRADER_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("LLMGRADER_GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("LLMGRADER_GOOGLE_REDIRECT_URI", "http://localhost/auth/callback")

    def _create(**env):
        for key, value in env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        app = create_app(scratch_dir=str(scratch), soln_pkg=None)
        app.config["TESTING"] = True
        return app

    return _create, storage_path / "db" / "llmgrader.db"


def _mock_google_login(monkeypatch, email: str):
    class _Resp:
        def __init__(self, payload):
            self._payload = payload
            self.ok = True

        def json(self):
            return self._payload

    monkeypatch.setattr(
        "llmgrader.routes.api.requests.post",
        lambda *args, **kwargs: _Resp({"access_token": "token-123"}),
    )
    monkeypatch.setattr(
        "llmgrader.routes.api.requests.get",
        lambda *args, **kwargs: _Resp(
            {
                "email": email,
                "email_verified": True,
                "sub": "google-sub-123",
                "name": "Test User",
                "picture": "https://example.com/pic.png",
            }
        ),
    )


def test_admin_route_requires_admin_role(app_factory):
    create, _ = app_factory
    app = create(LLMGRADER_AUTH_MODE="normal", LLMGRADER_INITIAL_ADMIN_EMAIL=None)

    with app.test_client() as client:
        resp = client.get("/admin")
        assert resp.status_code == 403


def test_dev_open_mode_allows_admin_routes_without_login(app_factory):
    create, _ = app_factory
    app = create(LLMGRADER_AUTH_MODE="dev-open", LLMGRADER_INITIAL_ADMIN_EMAIL=None)

    with app.test_client() as client:
        resp = client.get("/admin")
        assert resp.status_code == 200


def test_google_callback_persists_user_and_non_admin_role(app_factory, monkeypatch):
    create, db_path = app_factory
    app = create(LLMGRADER_AUTH_MODE="normal", LLMGRADER_INITIAL_ADMIN_EMAIL=None)
    _mock_google_login(monkeypatch, email="student@example.com")

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["oauth_state"] = "state-1"

        callback = client.get("/auth/callback?state=state-1&code=abc", follow_redirects=False)
        assert callback.status_code == 302

        auth = client.get("/api/auth/session")
        payload = auth.get_json()
        assert payload["authenticated"] is True
        assert payload["is_admin"] is False
        assert payload["user"]["email"] == "student@example.com"

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT email, name FROM users WHERE email = ?",
            ("student@example.com",),
        ).fetchone()
    finally:
        conn.close()
    assert row == ("student@example.com", "Test User")


def test_admin_can_manage_admin_users(app_factory, monkeypatch):
    create, _ = app_factory
    app = create(
        LLMGRADER_AUTH_MODE="normal",
        LLMGRADER_INITIAL_ADMIN_EMAIL="admin@example.com",
    )
    _mock_google_login(monkeypatch, email="admin@example.com")

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["oauth_state"] = "state-2"

        callback = client.get("/auth/callback?state=state-2&code=abc", follow_redirects=False)
        assert callback.status_code == 302

        add_resp = client.post("/api/admin/users", json={"email": "ta@example.com"})
        assert add_resp.status_code == 200

        list_resp = client.get("/api/admin/users")
        admins = list_resp.get_json()["admins"]
        emails = {item["email"] for item in admins}
        assert "admin@example.com" in emails
        assert "ta@example.com" in emails

        delete_resp = client.delete("/api/admin/users/ta@example.com")
        assert delete_resp.status_code == 200

        last_admin_delete = client.delete("/api/admin/users/admin@example.com")
        assert last_admin_delete.status_code == 400

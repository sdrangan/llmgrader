from llmgrader.scripts.llmgrader_env_vars import build_report


def test_build_report_marks_missing_values(monkeypatch):
    monkeypatch.delenv("LLMGRADER_SECRET_KEY", raising=False)
    monkeypatch.delenv("LLMGRADER_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("LLMGRADER_GOOGLE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("LLMGRADER_GOOGLE_REDIRECT_URI", raising=False)
    monkeypatch.delenv("LLMGRADER_INITIAL_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("LLMGRADER_AUTH_MODE", raising=False)
    monkeypatch.delenv("LLMGRADER_STORAGE_PATH", raising=False)

    report = build_report()

    assert "LLMGRADER_SECRET_KEY=MISSING" in report
    assert "LLMGRADER_GOOGLE_CLIENT_ID=MISSING" in report
    assert "LLMGRADER_GOOGLE_CLIENT_SECRET=MISSING" in report
    assert "LLMGRADER_GOOGLE_REDIRECT_URI=MISSING" in report
    assert "LLMGRADER_INITIAL_ADMIN_EMAIL=MISSING" in report
    assert "LLMGRADER_AUTH_MODE=MISSING" in report
    assert "LLMGRADER_STORAGE_PATH=MISSING" in report


def test_build_report_masks_secrets_by_default(monkeypatch):
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("LLMGRADER_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("LLMGRADER_GOOGLE_CLIENT_SECRET", "secret-value-123456")
    monkeypatch.setenv("LLMGRADER_GOOGLE_REDIRECT_URI", "http://127.0.0.1:5000/auth/callback")
    monkeypatch.setenv("LLMGRADER_INITIAL_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("LLMGRADER_AUTH_MODE", "normal")
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", "/var/data")

    report = build_report()

    assert "LLMGRADER_SECRET_KEY=abcd...wxyz" in report
    assert "LLMGRADER_GOOGLE_CLIENT_SECRET=secr...3456" in report
    assert "LLMGRADER_GOOGLE_CLIENT_ID=client-id" in report
    assert "LLMGRADER_GOOGLE_REDIRECT_URI=http://127.0.0.1:5000/auth/callback" in report
    assert "LLMGRADER_INITIAL_ADMIN_EMAIL=admin@example.com" in report
    assert "LLMGRADER_AUTH_MODE=normal" in report
    assert "LLMGRADER_STORAGE_PATH=/var/data" in report


def test_build_report_can_show_secrets(monkeypatch):
    monkeypatch.setenv("LLMGRADER_SECRET_KEY", "full-secret")
    monkeypatch.setenv("LLMGRADER_GOOGLE_CLIENT_SECRET", "full-client-secret")

    report = build_report(show_secrets=True)

    assert "LLMGRADER_SECRET_KEY=full-secret" in report
    assert "LLMGRADER_GOOGLE_CLIENT_SECRET=full-client-secret" in report
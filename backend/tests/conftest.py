import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="opschest_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["SIM_TODAY"] = "2026-11-07"  # Thu 7 -> NCC01, NCC02 (hang ngay) den lich dat
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["PDF_OUTPUT_DIR"] = str(_tmp / "pdf")
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402

# Test KHONG BAO GIO goi LLM that, ke ca khi .env cua dev co key
settings.llm_api_key = ""
settings.llm_base_url = "https://llm.invalid/v1"
settings.llm_api_key_fallback = ""
settings.llm_base_url_fallback = ""
settings.llm_model_fallback = ""


@pytest.fixture(scope="session")
def seeded():
    from app.sim.seed import seed
    return seed(days=200, reset=True)


@pytest.fixture()
def db(seeded):
    from app.db import SessionLocal
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def outbox(monkeypatch):
    """Thay SMTP bang hop thu trong bo nho."""
    sent = []

    def fake_send(to, subject, html, attachments=None):
        sent.append({"to": to, "subject": subject, "html": html, "attachments": attachments or []})
        return f"<test-{len(sent)}@opschest.test>"

    monkeypatch.setattr("app.notify.email.send_email", fake_send)
    return sent


@pytest.fixture(scope="session")
def client(seeded):
    from app.api.main import app
    with TestClient(app) as c:
        yield c


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def manager(client):
    return _login(client, "quanly", "quanly123")


@pytest.fixture(scope="session")
def staff(client):
    return _login(client, "nhanvien", "nhanvien123")

"""FastAPI server tests. We run the server in setup-mode (no cookies) so the
tests don't hit Gemini's real endpoints. Live integration testing requires
real cookies and isn't done here."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app(monkeypatch, tmp_path):
    """Build a fresh FastAPI app in setup mode (no real client)."""
    # Point at an empty env file so no cookies are picked up, even if the
    # developer has SECURE_1PSID set in their environment.
    empty_env = tmp_path / ".env"
    empty_env.write_text("")
    monkeypatch.setenv("AITUNNEL_ENV_PATH", str(empty_env))
    monkeypatch.delenv("SECURE_1PSID", raising=False)
    monkeypatch.delenv("SECURE_1PSIDTS", raising=False)

    # Build after env is patched.
    from aitunnel.server.app import build_app
    return build_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def test_health_in_setup_mode(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["setup"] is True


def test_root_serves_setup_when_not_ready(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # setup.html includes a unique element, not present in dashboard.html
    assert "first-time setup" in r.text or "Paste your" in r.text


def test_favicon_svg(client: TestClient) -> None:
    r = client.get("/favicon.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in r.content


def test_favicon_ico_serves_svg(client: TestClient) -> None:
    # Browsers that auto-fetch /favicon.ico get the SVG too.
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert b"<svg" in r.content


def test_query_returns_503_without_cookies(client: TestClient) -> None:
    r = client.post("/query", json={"prompt": "hi"})
    assert r.status_code == 503


def test_query_stream_returns_503_without_cookies(client: TestClient) -> None:
    r = client.post("/query/stream", json={"prompt": "hi"})
    assert r.status_code == 503


def test_chats_returns_503_without_cookies(client: TestClient) -> None:
    r = client.get("/chats")
    assert r.status_code == 503


def test_gems_returns_503_without_cookies(client: TestClient) -> None:
    r = client.get("/gems")
    assert r.status_code == 503


def test_query_validates_empty_prompt(client: TestClient) -> None:
    # Even before the 503, FastAPI validates body shape.
    r = client.post("/query", json={"prompt": ""})
    assert r.status_code == 400
    assert "prompt required" in r.json()["detail"].lower()


def test_query_validates_whitespace_prompt(client: TestClient) -> None:
    r = client.post("/query", json={"prompt": "   \n  \t"})
    assert r.status_code == 400


def test_query_rejects_missing_prompt_field(client: TestClient) -> None:
    r = client.post("/query", json={})
    # Pydantic returns 422 for missing required field
    assert r.status_code == 422


def test_query_rejects_non_json_body(client: TestClient) -> None:
    r = client.post("/query", content=b"not json", headers={"Content-Type": "application/json"})
    assert r.status_code in (400, 422)


def test_setup_requires_psid(client: TestClient) -> None:
    r = client.post("/setup", json={"psid": "", "psidts": "anything"})
    assert r.status_code == 400


def test_setup_flash_returns_string(client: TestClient) -> None:
    r = client.get("/setup/flash")
    assert r.status_code == 200
    assert "flash" in r.json()


def test_jobs_list_returns_array(client: TestClient) -> None:
    r = client.get("/jobs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_unknown_route_404(client: TestClient) -> None:
    r = client.get("/this-does-not-exist")
    assert r.status_code == 404


def test_dashboard_route_serves_setup_when_not_ready(client: TestClient) -> None:
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_setup_html_has_required_form_fields(client: TestClient) -> None:
    r = client.get("/")
    body = r.text
    # The form needs both fields by id; verify they're present.
    assert 'id="psid"' in body
    assert 'id="psidts"' in body


def test_dashboard_html_well_formed(client: TestClient) -> None:
    """Verify embedded dashboard.html is valid (not truncated, has the routes
    JS will call). We can't reach it without cookies, but we can verify the
    file Python embedded for serving."""
    from aitunnel.server.app import _read_asset
    html = _read_asset("dashboard.html").decode("utf-8")
    assert "<!DOCTYPE html>" in html
    assert "</html>" in html.lower()
    # Sanity-check that the JS still references key endpoints.
    assert "/query" in html
    assert "/jobs/stream" in html
    assert "/upload" in html


def test_all_routes_registered(app) -> None:
    """Smoke-check that every route we expect is wired."""
    paths = {r.path for r in app.routes if hasattr(r, "path")}
    must_have = {
        "/", "/dashboard", "/favicon.svg", "/favicon.ico", "/health",
        "/setup/flash", "/setup",
        "/query", "/query/stream", "/upload",
        "/chats", "/chats/{cid}", "/chats/{cid}/history",
        "/gems", "/gems/{gem_id}",
        "/deep-research",
        "/jobs", "/jobs/stream",
    }
    missing = must_have - paths
    assert not missing, f"missing routes: {missing}"


def test_query_accepts_cid_for_multiturn(client: TestClient) -> None:
    """Multi-turn shape validation: cid/rid/rcid are accepted (returns 503
    because no client, but the body shape passes)."""
    r = client.post("/query", json={
        "prompt": "follow up",
        "cid": "c_abc",
        "rid": "r_abc",
        "rcid": "rc_abc",
    })
    # 503 (client not ready) means we got past validation, which is what
    # we're testing here.
    assert r.status_code == 503

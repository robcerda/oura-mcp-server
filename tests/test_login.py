"""The terminal OAuth sign in flow."""

import socket
import threading
import urllib.error
import urllib.request
from urllib.parse import parse_qs, parse_qsl, urlparse

import httpx
import pytest
from conftest import FakeOura, make_session, token_body

from oura_mcp_server import login as login_module
from oura_mcp_server.login import LoginError, parse_callback, wait_for_callback


def test_parse_callback_accepts_a_full_url_or_just_the_query():
    url = "http://localhost:8765/callback?code=abc&state=s1"
    assert parse_callback(url, "s1") == "abc"
    assert parse_callback("?code=abc&state=s1", "s1") == "abc"
    assert parse_callback("code=abc&state=s1", "s1") == "abc"


def test_parse_callback_rejects_a_state_mismatch():
    with pytest.raises(LoginError, match="state"):
        parse_callback("http://localhost/cb?code=abc&state=forged", "s1")


def test_parse_callback_reports_a_declined_consent():
    with pytest.raises(LoginError, match="access_denied"):
        parse_callback("http://localhost/cb?error=access_denied&state=s1", "s1")


def test_parse_callback_needs_a_code():
    with pytest.raises(LoginError, match="no authorization code"):
        parse_callback("http://localhost/cb?state=s1", "s1")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_callback_server_catches_the_redirect_and_ignores_other_paths():
    port = _free_port()
    statuses = []

    def browser():
        for path in ("/favicon.ico", "/callback?code=abc&state=s1"):
            for _ in range(50):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}") as r:
                        statuses.append(r.status)
                    break
                except urllib.error.HTTPError as e:
                    statuses.append(e.code)
                    break
                except urllib.error.URLError:
                    threading.Event().wait(0.05)

    thread = threading.Thread(target=browser)
    thread.start()
    received = wait_for_callback(f"http://localhost:{port}/callback", timeout=10)
    thread.join()

    assert parse_callback(received, "s1") == "abc"
    assert statuses == [404, 200]


def test_callback_server_refuses_non_local_redirects():
    with pytest.raises(LoginError, match="--paste"):
        wait_for_callback("https://example.com/callback", timeout=1)


def test_paste_login_end_to_end(monkeypatch, isolated):
    fake = FakeOura()
    fake.json("/oauth/token", token_body(1, scope="daily personal"))
    fake.json("/personal_info", {"id": "u1", "email": "me@example.com"})
    http = httpx.Client(transport=httpx.MockTransport(fake.handle))

    monkeypatch.setenv("OURA_CLIENT_ID", "client-123")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "secret-456")
    captured = {}

    def fake_input(prompt):
        # The authorize URL was printed just before; answer with a redirect
        # carrying the state it asked for.
        state = parse_qs(urlparse(captured["url"]).query)["state"][0]
        return f"http://localhost:8765/callback?code=the-code&state={state}"

    real_build = login_module.oauth.build_authorize_url

    def spy_build(*args, **kwargs):
        captured["url"] = real_build(*args, **kwargs)
        return captured["url"]

    monkeypatch.setattr(login_module.oauth, "build_authorize_url", spy_build)
    monkeypatch.setattr("builtins.input", fake_input)

    session = login_module.login(
        "http://localhost:8765/callback", paste=True, store=isolated, http=http
    )

    authorize = parse_qs(urlparse(captured["url"]).query)
    assert authorize["client_id"] == ["client-123"]
    assert authorize["response_type"] == ["code"]
    assert "heartrate" in authorize["scope"][0].split()
    exchange = dict(parse_qsl(fake.to("/oauth/token")[0].content.decode()))
    assert exchange == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "redirect_uri": "http://localhost:8765/callback",
        "client_id": "client-123",
        "client_secret": "secret-456",
    }
    assert isolated.load() == session
    assert session.scope == "daily personal"


def test_bad_client_secret_gets_a_hint(monkeypatch, isolated):
    fake = FakeOura()
    fake.json("/oauth/token", {"error": "invalid_client"}, 401)
    http = httpx.Client(transport=httpx.MockTransport(fake.handle))
    monkeypatch.setenv("OURA_CLIENT_ID", "c")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "wrong")
    monkeypatch.setattr(login_module, "parse_callback", lambda url, state: "code")
    monkeypatch.setattr("builtins.input", lambda prompt: "ignored")

    with pytest.raises(LoginError, match="Check the client ID and secret"):
        login_module.login("http://localhost:8765/callback", paste=True, store=isolated, http=http)
    assert isolated.load() is None


def test_logout_deletes_the_session(isolated, capsys):
    isolated.save(make_session())

    assert login_module.main(["--logout"]) == 0

    assert isolated.load() is None


def test_status_never_prints_secrets(isolated, capsys):
    isolated.save(make_session())

    login_module.main(["--status"])

    out = capsys.readouterr().out
    assert "client-123" in out
    for secret in ("secret-456", "access-1", "refresh-1"):
        assert secret not in out

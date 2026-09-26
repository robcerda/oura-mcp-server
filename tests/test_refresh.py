"""Access token refresh, including rotation races between processes."""

import asyncio
import time
from urllib.parse import parse_qsl

import httpx
import pytest
from conftest import call_tool, make_session, token_body
from mcp.server.fastmcp.exceptions import ToolError

from oura_mcp_server import client as client_module


def _form(request: httpx.Request) -> dict:
    return dict(parse_qsl(request.content.decode()))


@pytest.fixture
def expired(isolated):
    session = make_session(expires_at=time.time() - 10)
    isolated.save(session)
    return session


async def test_expired_token_is_refreshed_before_the_request(oura, expired, isolated):
    oura.json("/oauth/token", token_body(2))
    oura.rows("/daily_sleep", [])

    await call_tool("get_daily_sleep", {})

    refresh = _form(oura.to("/oauth/token")[0])
    assert refresh == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-1",
        "client_id": "client-123",
        "client_secret": "secret-456",
    }
    assert oura.to("/daily_sleep")[0].headers["Authorization"] == "Bearer access-2"
    # The rotated refresh token must be stored, or the next restart is locked out.
    stored = isolated.load()
    assert (stored.access_token, stored.refresh_token) == ("access-2", "refresh-2")
    assert stored.expires_at > time.time() + 80000


async def test_a_refresh_response_without_refresh_token_keeps_the_old_one(
    oura, expired, isolated
):
    body = token_body(2)
    del body["refresh_token"]
    oura.json("/oauth/token", body)
    oura.rows("/daily_sleep", [])

    await call_tool("get_daily_sleep", {})

    assert isolated.load().refresh_token == "refresh-1"


async def test_401_triggers_one_refresh_and_retry(oura, signed_in):
    oura.json("/oauth/token", token_body(2))
    oura.add(
        "/daily_sleep",
        httpx.Response(401, json={"detail": "expired"}),
        httpx.Response(200, json={"data": [], "next_token": None}),
    )

    await call_tool("get_daily_sleep", {})

    assert [r.headers["Authorization"] for r in oura.to("/daily_sleep")] == [
        "Bearer access-1",
        "Bearer access-2",
    ]


async def test_401_after_refresh_is_an_error_not_a_loop(oura, signed_in):
    oura.json("/oauth/token", token_body(2))
    oura.json("/daily_sleep", {"detail": "nope"}, 401)

    with pytest.raises(ToolError, match="401.*login_setup.py"):
        await call_tool("get_daily_sleep", {})
    assert len(oura.to("/daily_sleep")) == 2
    assert len(oura.to("/oauth/token")) == 1


async def test_concurrent_calls_refresh_once(oura, expired):
    oura.json("/oauth/token", token_body(2))
    oura.rows("/daily_sleep", [])

    await asyncio.gather(*(call_tool("get_daily_sleep", {}) for _ in range(5)))

    assert len(oura.to("/oauth/token")) == 1
    assert {r.headers["Authorization"] for r in oura.to("/daily_sleep")} == {"Bearer access-2"}


async def test_session_refreshed_by_another_process_is_used(oura, expired, isolated):
    """Another server process refreshed first, so storage already has a live token."""
    oura.rows("/daily_sleep", [])
    client_module._session = expired
    isolated.save(make_session(access_token="access-9", refresh_token="refresh-9"))

    await call_tool("get_daily_sleep", {})

    assert oura.to("/oauth/token") == []
    assert oura.last.headers["Authorization"] == "Bearer access-9"


async def test_invalid_grant_recovers_from_a_concurrent_rotation(oura, expired, isolated):
    """This process lost the refresh race: Oura rejects its spent token, but the
    winner's session has since landed in storage."""

    def lose_race(request):
        isolated.save(make_session(access_token="access-9", refresh_token="refresh-9"))
        return httpx.Response(400, json={"error": "invalid_grant"})

    oura.add("/oauth/token", lose_race)
    oura.rows("/daily_sleep", [])

    await call_tool("get_daily_sleep", {})

    assert oura.last.headers["Authorization"] == "Bearer access-9"


async def test_revoked_refresh_token_asks_for_a_new_login(oura, expired):
    oura.json("/oauth/token", {"error": "invalid_grant"}, 400)

    with pytest.raises(ToolError, match="rejected the stored refresh token.*login_setup.py"):
        await call_tool("get_daily_sleep", {})
    assert oura.to("/daily_sleep") == []


async def test_token_endpoint_outage_is_reported(oura, expired):
    oura.add("/oauth/token", httpx.Response(503, text="unavailable"))

    with pytest.raises(ToolError, match="Could not refresh the Oura session"):
        await call_tool("get_daily_sleep", {})

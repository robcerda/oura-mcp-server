"""Tests for the shared Oura HTTP client: dates, paging, retries and errors."""

from datetime import date, timedelta

import httpx
import pytest
from conftest import call_tool
from mcp.server.fastmcp.exceptions import ToolError

from oura_mcp_server import client as client_module


async def test_end_date_is_inclusive(oura, signed_in):
    """Oura's end_date is exclusive, so the tool sends the day after."""
    oura.rows("/daily_sleep", [])

    result = await call_tool(
        "get_daily_sleep", {"start_date": "2026-09-01", "end_date": "2026-09-03"}
    )

    assert oura.last_params == {"start_date": "2026-09-01", "end_date": "2026-09-04"}
    assert result["args"] == {"start_date": "2026-09-01", "end_date": "2026-09-03"}


async def test_default_range_is_the_last_seven_days_including_today(oura, signed_in):
    oura.rows("/daily_readiness", [])
    today = date.today()

    result = await call_tool("get_daily_readiness", {})

    assert oura.last_params == {
        "start_date": (today - timedelta(days=6)).isoformat(),
        "end_date": (today + timedelta(days=1)).isoformat(),
    }
    assert result["args"]["end_date"] == today.isoformat()


async def test_bearer_token_is_sent(oura, signed_in):
    oura.rows("/daily_sleep", [])

    await call_tool("get_daily_sleep", {})

    assert oura.last.headers["Authorization"] == "Bearer access-1"


async def test_pages_are_followed(oura, signed_in):
    oura.add(
        "/workout",
        httpx.Response(200, json={"data": [{"id": "a"}], "next_token": "page2"}),
        httpx.Response(200, json={"data": [{"id": "b"}], "next_token": None}),
    )

    result = await call_tool("get_workouts", {})

    assert [r["id"] for r in result["data"]] == ["a", "b"]
    assert result["truncated"] is False
    assert oura.last_params["next_token"] == "page2"


async def test_paging_stops_at_the_cap_and_hands_back_next_token(oura, signed_in, monkeypatch):
    monkeypatch.setattr(client_module, "MAX_PAGES", 2)
    oura.rows("/workout", [{"id": "x"}], next_token="more")

    result = await call_tool("get_workouts", {})

    assert len(oura.requests) == 2
    assert result["count"] == 2
    assert result["truncated"] is True
    assert result["next_token"] == "more"


async def test_next_token_is_passed_through(oura, signed_in):
    oura.rows("/workout", [])

    await call_tool("get_workouts", {"next_token": "resume-here"})

    assert oura.last_params["next_token"] == "resume-here"


async def test_rate_limit_honours_retry_after(oura, signed_in, monkeypatch):
    waits = []

    async def record(seconds):
        waits.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", record)
    oura.add(
        "/daily_sleep",
        httpx.Response(429, json={"detail": "slow down"}, headers={"Retry-After": "7"}),
        httpx.Response(200, json={"data": [], "next_token": None}),
    )

    await call_tool("get_daily_sleep", {})

    assert waits == [7.0]
    assert len(oura.requests) == 2


async def test_long_retry_after_is_reported_not_waited(oura, signed_in):
    oura.json(
        "/daily_sleep",
        {"detail": "slow down"},
        429,
        **{"Retry-After": "600", "X-RateLimit-Tier": "token"},
    )

    with pytest.raises(ToolError, match="rate limit reached \\(tier: token\\)"):
        await call_tool("get_daily_sleep", {})
    assert len(oura.requests) == 1


async def test_rate_limit_gives_up_after_retries(oura, signed_in):
    oura.json("/daily_sleep", {"detail": "slow down"}, 429)

    with pytest.raises(ToolError, match="429"):
        await call_tool("get_daily_sleep", {})
    assert len(oura.requests) == client_module.MAX_RETRIES + 1


async def test_forbidden_explains_scopes(oura, signed_in):
    oura.json("/daily_spo2", {"detail": "Forbidden"}, 403)

    with pytest.raises(ToolError, match="lacks the scope"):
        await call_tool("get_daily_spo2", {})


async def test_validation_errors_are_flattened(oura, signed_in):
    detail = [
        {"loc": ["query", "start_date", "datetime"], "msg": "Input should be a valid date"},
        {"loc": ["query", "start_date", "date"], "msg": "Input should be a valid date"},
    ]
    oura.json("/daily_sleep", {"detail": detail}, 422)

    with pytest.raises(ToolError) as info:
        await call_tool("get_daily_sleep", {})
    assert str(info.value).count("start_date: Input should be a valid date") == 1


async def test_bad_dates_are_rejected_before_any_request(oura, signed_in):
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        await call_tool("get_daily_sleep", {"start_date": "last week"})
    with pytest.raises(ToolError, match="is after end_date"):
        await call_tool("get_daily_sleep", {"start_date": "2026-09-05", "end_date": "2026-09-01"})
    assert oura.requests == []


async def test_not_signed_in(oura):
    with pytest.raises(ToolError, match="login_setup.py"):
        await call_tool("get_daily_sleep", {})
    assert oura.requests == []


async def test_network_error_is_reported(oura, signed_in):
    def fail(request):
        raise httpx.ConnectError("connection refused", request=request)

    oura.add("/daily_sleep", fail)

    with pytest.raises(ToolError, match="Could not reach Oura"):
        await call_tool("get_daily_sleep", {})


async def test_sandbox_needs_no_session(oura, monkeypatch):
    monkeypatch.setenv("OURA_MCP_SANDBOX", "1")
    oura.add("/v2/sandbox/usercollection/daily_sleep", httpx.Response(
        200, json={"data": [{"day": "2026-09-01"}], "next_token": None}
    ))

    result = await call_tool("get_daily_sleep", {})

    assert result["count"] == 1
    assert oura.last.headers["Authorization"] == "Bearer sandbox"

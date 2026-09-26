"""Tool level behaviour: time series stripping, aggregation, summary, lookups."""

import json

import pytest
from conftest import call_tool, make_session
from mcp.server.fastmcp.exceptions import ToolError

SLEEP_PERIOD = {
    "id": "s1",
    "day": "2026-09-20",
    "type": "long_sleep",
    "total_sleep_duration": 27000,
    "average_hrv": 55,
    "sleep_phase_5_min": "4422331",
    "movement_30_sec": "1111",
    "heart_rate": {"interval": 300, "items": [60, 58], "timestamp": "2026-09-19T23:00:00+00:00"},
}


async def test_time_series_are_stripped_by_default(oura, signed_in):
    oura.rows("/sleep", [SLEEP_PERIOD])

    result = await call_tool("get_sleep_periods", {})

    row = result["data"][0]
    assert row["total_sleep_duration"] == 27000
    assert not {"sleep_phase_5_min", "movement_30_sec", "heart_rate"} & set(row)
    assert set(result["omitted_time_series"]) == {
        "sleep_phase_5_min",
        "movement_30_sec",
        "heart_rate",
    }


async def test_time_series_can_be_included(oura, signed_in):
    oura.rows("/sleep", [SLEEP_PERIOD])

    result = await call_tool("get_sleep_periods", {"include_time_series": True})

    assert result["data"][0] == SLEEP_PERIOD
    assert "omitted_time_series" not in result


async def test_heart_rate_window_and_aggregation(oura, signed_in):
    oura.rows(
        "/heartrate",
        [
            {"timestamp": "2026-09-20T10:00:00+00:00", "bpm": 60, "source": "awake"},
            {"timestamp": "2026-09-20T10:05:00+00:00", "bpm": 80, "source": "awake"},
            {"timestamp": "2026-09-20T11:00:00+00:00", "bpm": 50, "source": "rest"},
        ],
    )

    result = await call_tool(
        "get_heart_rate",
        {
            "start_datetime": "2026-09-20T00:00:00Z",
            "end_datetime": "2026-09-21T00:00:00Z",
            "aggregate": "hour",
        },
    )

    assert oura.last_params["start_datetime"] == "2026-09-20T00:00:00+00:00"
    assert result["sample_count"] == 3
    assert result["data"] == [
        {
            "start": "2026-09-20T10:00",
            "samples": 2,
            "min_bpm": 60,
            "avg_bpm": 70.0,
            "max_bpm": 80,
            "sources": {"awake": 2},
        },
        {
            "start": "2026-09-20T11:00",
            "samples": 1,
            "min_bpm": 50,
            "avg_bpm": 50.0,
            "max_bpm": 50,
            "sources": {"rest": 1},
        },
    ]


async def test_heart_rate_latest_skips_the_window(oura, signed_in):
    oura.rows("/heartrate", [{"timestamp": "2026-09-20T10:00:00+00:00", "bpm": 61}])

    await call_tool("get_heart_rate", {"latest": True})

    assert oura.last_params == {"latest": "true"}


async def test_heart_rate_rejects_a_bad_datetime(oura, signed_in):
    with pytest.raises(ToolError, match="ISO 8601"):
        await call_tool("get_heart_rate", {"start_datetime": "yesterday"})


async def test_daily_summary_merges_collections(oura, signed_in):
    oura.rows("/daily_sleep", [{"day": "2026-09-20", "score": 81}])
    oura.rows(
        "/daily_readiness", [{"day": "2026-09-20", "score": 77, "temperature_deviation": -0.2}]
    )
    oura.rows("/daily_activity", [{"day": "2026-09-20", "score": 90, "steps": 12000}])
    oura.rows(
        "/daily_stress", [{"day": "2026-09-21", "stress_high": 1800, "day_summary": "normal"}]
    )
    oura.json("/daily_spo2", {"detail": "Forbidden"}, 403)
    oura.rows("/daily_resilience", [{"day": "2026-09-20", "level": "solid"}])
    oura.rows(
        "/sleep",
        [
            {**SLEEP_PERIOD, "id": "nap", "type": "late_nap", "total_sleep_duration": 1200},
            SLEEP_PERIOD,
        ],
    )

    result = await call_tool(
        "get_daily_summary", {"start_date": "2026-09-20", "end_date": "2026-09-21"}
    )

    assert list(result["unavailable"]) == ["daily_spo2"]
    first, second = result["data"]
    assert first["day"] == "2026-09-20"
    assert (first["sleep_score"], first["readiness_score"], first["activity_score"]) == (81, 77, 90)
    assert first["resilience_level"] == "solid"
    assert first["main_sleep"]["id"] == "s1"
    assert first["main_sleep"]["total_sleep_seconds"] == 27000
    assert second == {
        "day": "2026-09-21",
        "stress_high_seconds": 1800,
        "recovery_high_seconds": None,
        "stress_summary": "normal",
    }


async def test_daily_summary_surfaces_a_shared_failure(oura):
    with pytest.raises(ToolError, match="Not signed in"):
        await call_tool("get_daily_summary", {})


async def test_get_document_maps_the_collection_name(oura, signed_in):
    oura.json("/vO2_max/v1", {"id": "v1", "vo2_max": 45})

    result = await call_tool("get_document", {"data_type": "vo2_max", "document_id": "v1"})

    assert result == {"id": "v1", "vo2_max": 45}


async def test_get_document_cannot_escape_its_collection(oura, signed_in):
    """An id is one path segment; a slash in it must not reach another route."""
    oura.json("/sleep/x", {"id": "x"})

    with pytest.raises(ToolError):
        await call_tool("get_document", {"data_type": "sleep", "document_id": "../x"})
    assert oura.last.url.raw_path.decode() == "/v2/usercollection/sleep/..%2Fx"


async def test_check_auth_status_reports_without_leaking_tokens(isolated):
    isolated.save(make_session(scope="daily personal"))

    result = await call_tool("check_auth_status", {})

    assert result["authenticated"] is True
    assert "heartrate" in result["scopes_missing"]
    text = json.dumps(result)
    for secret in ("secret-456", "access-1", "refresh-1"):
        assert secret not in text


async def test_check_auth_status_signed_out():
    result = await call_tool("check_auth_status", {})

    assert result["authenticated"] is False
    assert "login_setup.py" in result["next_step"]

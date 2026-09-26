"""Sleep tools (/daily_sleep, /sleep, /sleep_time)."""

from typing import Any, Dict

from oura_mcp_server.app import mcp
from oura_mcp_server.params import EndDate, IncludeTimeSeries, NextToken, StartDate
from oura_mcp_server.queries import daily_collection


@mcp.tool()
async def get_daily_sleep(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """
    Get daily sleep scores (0-100) with their contributors: deep sleep, efficiency,
    latency, REM sleep, restfulness, timing and total sleep.

    For durations, stages, heart rate and HRV use get_sleep_periods.
    """
    return await daily_collection(
        "get_daily_sleep", "/daily_sleep", start_date, end_date, next_token
    )


@mcp.tool()
async def get_sleep_periods(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
    include_time_series: IncludeTimeSeries = False,
) -> Dict[str, Any]:
    """
    Get detailed sleep periods: bedtime start and end, total, deep, REM and light sleep
    durations (seconds), awake time, latency, efficiency, average and lowest heart rate,
    average HRV, breathing rate, and the readiness computed from that sleep.

    A day can have several periods. type 'long_sleep' is the main sleep; naps and
    short rests appear as 'sleep', 'late_nap' or 'rest'.
    """
    return await daily_collection(
        "get_sleep_periods", "/sleep", start_date, end_date, next_token, include_time_series
    )


@mcp.tool()
async def get_sleep_time(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """Get Oura's recommended bedtime window for each day, calculated from recent sleep."""
    return await daily_collection(
        "get_sleep_time", "/sleep_time", start_date, end_date, next_token
    )

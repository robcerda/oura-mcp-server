"""Activity, workout and session tools (/daily_activity, /workout, /session)."""

from typing import Any, Dict

from oura_mcp_server.app import mcp
from oura_mcp_server.params import EndDate, IncludeTimeSeries, NextToken, StartDate
from oura_mcp_server.queries import daily_collection


@mcp.tool()
async def get_daily_activity(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
    include_time_series: IncludeTimeSeries = False,
) -> Dict[str, Any]:
    """
    Get daily activity: activity score (0-100) and contributors, steps, active and total
    calories (kcal), equivalent walking distance (meters), time in high, medium and low
    activity and sedentary (seconds), MET minutes, and inactivity alerts.
    """
    return await daily_collection(
        "get_daily_activity",
        "/daily_activity",
        start_date,
        end_date,
        next_token,
        include_time_series,
    )


@mcp.tool()
async def get_workouts(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """
    Get workouts, auto detected or entered by the user: activity type, start and end
    time, calories, distance (meters), intensity, and source.
    """
    return await daily_collection("get_workouts", "/workout", start_date, end_date, next_token)


@mcp.tool()
async def get_sessions(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
    include_time_series: IncludeTimeSeries = False,
) -> Dict[str, Any]:
    """
    Get guided and unguided sessions from the Oura app (breathing, meditation, rest,
    etc.): type, start and end time, and mood. Set include_time_series for the heart
    rate, HRV and motion recorded during each session.
    """
    return await daily_collection(
        "get_sessions", "/session", start_date, end_date, next_token, include_time_series
    )

"""The fetch-and-wrap step shared by every collection tool."""

from typing import Any, Dict, Optional

from oura_mcp_server.client import get_collection
from oura_mcp_server.params import (
    api_date_params,
    date_range,
    datetime_range,
    envelope,
)


async def daily_collection(
    tool: str,
    path: str,
    start_date: Optional[str],
    end_date: Optional[str],
    next_token: Optional[str] = None,
    include_time_series: bool = True,
) -> Dict[str, Any]:
    """Fetch a collection keyed by day, over an inclusive date range."""
    start, end = date_range(start_date, end_date)
    params = {**api_date_params(start, end), "next_token": next_token}
    rows, token = await get_collection(path, params)
    args = {"start_date": start.isoformat(), "end_date": end.isoformat()}
    return envelope(tool, args, rows, token, include_time_series)


async def time_series_collection(
    tool: str,
    path: str,
    start_datetime: Optional[str],
    end_datetime: Optional[str],
    next_token: Optional[str] = None,
    latest: Optional[bool] = None,
) -> Dict[str, Any]:
    """Fetch a time series (heart rate, battery) over a datetime window."""
    if latest:
        rows, token = await get_collection(path, {"latest": "true"}, max_pages=1)
        return envelope(tool, {"latest": True}, rows, token)
    start, end = datetime_range(start_datetime, end_datetime)
    params = {
        "start_datetime": start.isoformat(),
        "end_datetime": end.isoformat(),
        "next_token": next_token,
    }
    rows, token = await get_collection(path, params)
    args = {"start_datetime": start.isoformat(), "end_datetime": end.isoformat()}
    return envelope(tool, args, rows, token)

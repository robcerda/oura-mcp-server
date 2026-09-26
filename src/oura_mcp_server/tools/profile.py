"""User and ring tools (/personal_info, /ring_configuration, /ring_battery_level,
/enhanced_tag, /rest_mode_period)."""

from typing import Annotated, Any, Dict, Optional

from pydantic import Field

from oura_mcp_server.app import mcp
from oura_mcp_server.client import get_collection, oura_get
from oura_mcp_server.params import (
    EndDate,
    EndDatetime,
    NextToken,
    StartDate,
    StartDatetime,
    envelope,
)
from oura_mcp_server.queries import daily_collection, time_series_collection


@mcp.tool()
async def get_personal_info() -> Dict[str, Any]:
    """
    Get the signed in user's profile: age, weight, height, biological sex and email.
    Fields the user did not grant a scope for come back null.
    """
    return await oura_get("/personal_info")


@mcp.tool()
async def get_ring_configuration() -> Dict[str, Any]:
    """Get the user's ring(s): hardware generation, color, design, size, firmware and setup date."""
    rows, token = await get_collection("/ring_configuration", {})
    return envelope("get_ring_configuration", {}, rows, token)


@mcp.tool()
async def get_ring_battery_level(
    start_datetime: StartDatetime = None,
    end_datetime: EndDatetime = None,
    latest: Annotated[
        Optional[bool], Field(description="Return only the most recent reading.")
    ] = True,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """
    Get ring battery level (%) and charging state. Returns the latest reading by
    default; set latest to false for readings over a window.
    """
    return await time_series_collection(
        "get_ring_battery_level",
        "/ring_battery_level",
        start_datetime,
        end_datetime,
        next_token,
        latest,
    )


@mcp.tool()
async def get_enhanced_tags(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """
    Get tags the user logged in the Oura app (caffeine, alcohol, illness, travel, custom
    tags, etc.) with start and end times and comments. Useful for explaining changes in
    sleep or readiness.
    """
    return await daily_collection(
        "get_enhanced_tags", "/enhanced_tag", start_date, end_date, next_token
    )


@mcp.tool()
async def get_rest_mode_periods(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """
    Get rest mode periods (when the user turned on rest mode, typically for illness or
    recovery), with start and end times and logged episodes.
    """
    return await daily_collection(
        "get_rest_mode_periods", "/rest_mode_period", start_date, end_date, next_token
    )

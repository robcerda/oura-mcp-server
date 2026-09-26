"""Readiness and resilience tools (/daily_readiness, /daily_resilience)."""

from typing import Any, Dict

from oura_mcp_server.app import mcp
from oura_mcp_server.params import EndDate, NextToken, StartDate
from oura_mcp_server.queries import daily_collection


@mcp.tool()
async def get_daily_readiness(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """
    Get daily readiness scores (0-100) with contributors (activity balance, body
    temperature, HRV balance, previous day activity, previous night, recovery index,
    resting heart rate, sleep balance, sleep regularity) and body temperature deviation
    from baseline in degrees Celsius.
    """
    return await daily_collection(
        "get_daily_readiness", "/daily_readiness", start_date, end_date, next_token
    )


@mcp.tool()
async def get_daily_resilience(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """
    Get daily resilience: an estimate of the ability to withstand and recover from
    physiological stress, as a level (limited, adequate, solid, strong, exceptional)
    with sleep recovery, daytime recovery and stress contributors.
    """
    return await daily_collection(
        "get_daily_resilience", "/daily_resilience", start_date, end_date, next_token
    )

"""Heart and stress tools (/heartrate, /daily_stress, /daily_spo2,
/daily_cardiovascular_age, /vO2_max)."""

from collections import Counter
from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import Field

from oura_mcp_server.app import mcp
from oura_mcp_server.params import EndDate, EndDatetime, NextToken, StartDate, StartDatetime
from oura_mcp_server.queries import daily_collection, time_series_collection


def aggregate_heart_rate(rows: List[Dict[str, Any]], bucket: str) -> List[Dict[str, Any]]:
    """Collapse 5 minute heart rate samples into hourly or daily buckets.

    Buckets are keyed by the sample timestamp as Oura reports it (UTC), so a
    'day' bucket is a UTC day, not the user's local day.
    """
    width = 13 if bucket == "hour" else 10  # "YYYY-MM-DDTHH" or "YYYY-MM-DD"
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        timestamp, bpm = row.get("timestamp"), row.get("bpm")
        if not isinstance(timestamp, str) or not isinstance(bpm, (int, float)):
            continue
        try:
            key = datetime.fromisoformat(timestamp).isoformat()[:width]
        except ValueError:
            key = timestamp[:width]
        groups.setdefault(key, []).append(row)

    buckets = []
    for key in sorted(groups):
        bpms = [r["bpm"] for r in groups[key]]
        buckets.append(
            {
                "start": key + (":00" if bucket == "hour" else ""),
                "samples": len(bpms),
                "min_bpm": min(bpms),
                "avg_bpm": round(sum(bpms) / len(bpms), 1),
                "max_bpm": max(bpms),
                "sources": dict(Counter(str(r.get("source")) for r in groups[key])),
            }
        )
    return buckets


@mcp.tool()
async def get_heart_rate(
    start_datetime: StartDatetime = None,
    end_datetime: EndDatetime = None,
    aggregate: Annotated[
        Optional[Literal["hour", "day"]],
        Field(
            description=(
                "Summarize samples into hourly or daily min/avg/max buckets (UTC). "
                "Recommended for windows longer than a day; raw data is 288 samples a day."
            )
        ),
    ] = None,
    latest: Annotated[
        Optional[bool], Field(description="Return only the most recent sample.")
    ] = None,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """
    Get heart rate samples (bpm) at roughly 5 minute intervals, each tagged with its
    source: awake, rest, sleep, workout, session or live. Defaults to the last 24 hours.
    """
    result = await time_series_collection(
        "get_heart_rate", "/heartrate", start_datetime, end_datetime, next_token, latest
    )
    if aggregate and not latest:
        result["args"]["aggregate"] = aggregate
        result["sample_count"] = result["count"]
        result["data"] = aggregate_heart_rate(result["data"], aggregate)
        result["count"] = len(result["data"])
    return result


@mcp.tool()
async def get_daily_stress(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """
    Get daytime stress: seconds spent in high stress and in high recovery each day,
    and a day summary of restored, normal or stressful.
    """
    return await daily_collection(
        "get_daily_stress", "/daily_stress", start_date, end_date, next_token
    )


@mcp.tool()
async def get_daily_spo2(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """
    Get average blood oxygen saturation (SpO2 %) during sleep and the breathing
    disturbance index. Requires a Gen 3 or later ring.
    """
    return await daily_collection(
        "get_daily_spo2", "/daily_spo2", start_date, end_date, next_token
    )


@mcp.tool()
async def get_daily_cardiovascular_age(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """
    Get cardiovascular age: Oura's estimate of vascular age in years, from pulse wave
    velocity, to compare against actual age.
    """
    return await daily_collection(
        "get_daily_cardiovascular_age",
        "/daily_cardiovascular_age",
        start_date,
        end_date,
        next_token,
    )


@mcp.tool()
async def get_vo2_max(
    start_date: StartDate = None,
    end_date: EndDate = None,
    next_token: NextToken = None,
) -> Dict[str, Any]:
    """Get VO2 max (cardio capacity) estimates in ml/kg/min. Updated infrequently."""
    return await daily_collection("get_vo2_max", "/vO2_max", start_date, end_date, next_token)

"""Cross collection daily overview."""

import asyncio
from typing import Any, Dict, List, Optional

from oura_mcp_server.app import mcp
from oura_mcp_server.client import OuraError, get_collection
from oura_mcp_server.params import EndDate, StartDate, api_date_params, date_range

# Collections read for the overview. Each one needs its own scope, so any of
# them can fail on its own without sinking the rest.
_SOURCES = (
    "daily_sleep",
    "daily_readiness",
    "daily_activity",
    "daily_stress",
    "daily_spo2",
    "daily_resilience",
    "sleep",
)


def _main_sleep(periods: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The day's main sleep: the longest long_sleep period, else the longest of any type."""
    candidates = [p for p in periods if p.get("type") != "deleted"]
    long_sleeps = [p for p in candidates if p.get("type") == "long_sleep"] or candidates
    if not long_sleeps:
        return None
    main = max(long_sleeps, key=lambda p: p.get("total_sleep_duration") or 0)
    return {
        "id": main.get("id"),
        "bedtime_start": main.get("bedtime_start"),
        "bedtime_end": main.get("bedtime_end"),
        "total_sleep_seconds": main.get("total_sleep_duration"),
        "time_in_bed_seconds": main.get("time_in_bed"),
        "deep_sleep_seconds": main.get("deep_sleep_duration"),
        "rem_sleep_seconds": main.get("rem_sleep_duration"),
        "efficiency": main.get("efficiency"),
        "average_hrv": main.get("average_hrv"),
        "lowest_heart_rate": main.get("lowest_heart_rate"),
        "average_heart_rate": main.get("average_heart_rate"),
    }


def build_days(results: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Merge per collection rows into one record per day."""
    days: Dict[str, Dict[str, Any]] = {}

    def day(key: Any) -> Dict[str, Any]:
        return days.setdefault(str(key), {"day": str(key)})

    for row in results.get("daily_sleep", []):
        day(row.get("day"))["sleep_score"] = row.get("score")
    for row in results.get("daily_readiness", []):
        record = day(row.get("day"))
        record["readiness_score"] = row.get("score")
        record["temperature_deviation_c"] = row.get("temperature_deviation")
    for row in results.get("daily_activity", []):
        record = day(row.get("day"))
        record["activity_score"] = row.get("score")
        record["steps"] = row.get("steps")
        record["active_calories"] = row.get("active_calories")
        record["total_calories"] = row.get("total_calories")
    for row in results.get("daily_stress", []):
        record = day(row.get("day"))
        record["stress_high_seconds"] = row.get("stress_high")
        record["recovery_high_seconds"] = row.get("recovery_high")
        record["stress_summary"] = row.get("day_summary")
    for row in results.get("daily_spo2", []):
        record = day(row.get("day"))
        record["spo2_average"] = (row.get("spo2_percentage") or {}).get("average")
        record["breathing_disturbance_index"] = row.get("breathing_disturbance_index")
    for row in results.get("daily_resilience", []):
        day(row.get("day"))["resilience_level"] = row.get("level")

    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for row in results.get("sleep", []):
        by_day.setdefault(str(row.get("day")), []).append(row)
    for key, periods in by_day.items():
        main = _main_sleep(periods)
        if main is not None:
            day(key)["main_sleep"] = main

    return [days[k] for k in sorted(days)]


@mcp.tool()
async def get_daily_summary(
    start_date: StartDate = None,
    end_date: EndDate = None,
) -> Dict[str, Any]:
    """
    Get one record per day combining the headline numbers: sleep, readiness and activity
    scores, steps and calories, stress and recovery time, SpO2, resilience level,
    temperature deviation, and the main sleep period (bedtime, durations, efficiency,
    HRV, heart rate). Durations are in seconds.

    The best starting point for questions like "how have I been sleeping" or "how was
    my week". Collections the session has no scope for are listed under 'unavailable'
    and the rest are still returned.
    """
    start, end = date_range(start_date, end_date)
    params = api_date_params(start, end)
    fetched = await asyncio.gather(
        *(get_collection(f"/{source}", dict(params)) for source in _SOURCES),
        return_exceptions=True,
    )

    results: Dict[str, List[Dict[str, Any]]] = {}
    unavailable: Dict[str, str] = {}
    truncated: List[str] = []
    for source, outcome in zip(_SOURCES, fetched, strict=True):
        if isinstance(outcome, OuraError):
            unavailable[source] = str(outcome)
        elif isinstance(outcome, BaseException):
            raise outcome
        else:
            rows, token = outcome
            results[source] = rows
            if token:
                truncated.append(source)

    if not results:
        # Nothing worked, which is almost always one shared cause (signed out,
        # rate limited). Surface it rather than an empty summary.
        raise OuraError(next(iter(unavailable.values())))

    days = build_days(results)
    return {
        "tool": "get_daily_summary",
        "args": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "count": len(days),
        "truncated": bool(truncated),
        "truncated_sources": truncated,
        "unavailable": unavailable,
        "data": days,
    }

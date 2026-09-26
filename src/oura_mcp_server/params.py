"""Shared tool parameter types, date handling and response shaping."""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Dict, List, Optional, Tuple

from pydantic import Field

from oura_mcp_server.client import OuraError

DEFAULT_DAYS = 7

StartDate = Annotated[
    Optional[str],
    Field(description="First day to include, YYYY-MM-DD. Defaults to 6 days before end_date."),
]
EndDate = Annotated[
    Optional[str],
    Field(description="Last day to include (inclusive), YYYY-MM-DD. Defaults to today."),
]
StartDatetime = Annotated[
    Optional[str],
    Field(
        description=(
            "Start of the window, ISO 8601 datetime such as '2026-01-15T00:00:00-08:00'. "
            "Defaults to 24 hours before end_datetime."
        )
    ),
]
EndDatetime = Annotated[
    Optional[str],
    Field(description="End of the window, ISO 8601 datetime. Defaults to now."),
]
NextToken = Annotated[
    Optional[str],
    Field(
        description=(
            "Continue a truncated result: pass the next_token from the previous "
            "response along with the same dates."
        )
    ),
]
IncludeTimeSeries = Annotated[
    bool,
    Field(
        description=(
            "Include the embedded time series (5 minute sleep phases, 30 second movement, "
            "per sample heart rate and HRV, MET samples). Off by default because they "
            "dominate the response size."
        )
    ),
]

# Embedded series that are strings with one character per interval. Series
# stored as {"interval", "items", "timestamp"} objects are detected by shape.
_STRING_SERIES = frozenset(
    {
        "class_5_min",
        "sleep_phase_5_min",
        "sleep_phase_30_sec",
        "app_sleep_phase_5_min",
        "movement_30_sec",
    }
)


def _parse_date(value: str, name: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise OuraError(f"{name} must be a date in YYYY-MM-DD format, got {value!r}") from None


def date_range(
    start_date: Optional[str], end_date: Optional[str], default_days: int = DEFAULT_DAYS
) -> Tuple[date, date]:
    """Resolve an inclusive date range, filling in defaults.

    Oura treats end_date as exclusive (asking for 09-01 to 09-03 returns the
    1st and 2nd only) and with no dates at all returns just yesterday. Neither
    is what someone asking for "this week" means, so tools take an inclusive
    range and convert with api_date_params.
    """
    end = _parse_date(end_date, "end_date") if end_date else date.today()
    start = (
        _parse_date(start_date, "start_date")
        if start_date
        else end - timedelta(days=default_days - 1)
    )
    if start > end:
        raise OuraError(f"start_date {start} is after end_date {end}")
    return start, end


def api_date_params(start: date, end: date) -> Dict[str, str]:
    """Query parameters for an inclusive range, with Oura's exclusive end_date."""
    return {"start_date": start.isoformat(), "end_date": (end + timedelta(days=1)).isoformat()}


def _parse_datetime(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise OuraError(
            f"{name} must be an ISO 8601 datetime such as 2026-01-15T08:00:00Z, got {value!r}"
        ) from None
    # A naive time is ambiguous; UTC matches how Oura reports heart rate.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def datetime_range(
    start_datetime: Optional[str], end_datetime: Optional[str], default_hours: int = 24
) -> Tuple[datetime, datetime]:
    end = (
        _parse_datetime(end_datetime, "end_datetime")
        if end_datetime
        else datetime.now(timezone.utc).replace(microsecond=0)
    )
    start = (
        _parse_datetime(start_datetime, "start_datetime")
        if start_datetime
        else end - timedelta(hours=default_hours)
    )
    if start > end:
        raise OuraError(f"start_datetime {start.isoformat()} is after end_datetime")
    return start, end


def _is_sample_series(value: Any) -> bool:
    return isinstance(value, dict) and "items" in value and "interval" in value


def strip_time_series(doc: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Drop embedded time series from a document. Returns the doc and what was removed."""
    removed = [k for k, v in doc.items() if k in _STRING_SERIES or _is_sample_series(v)]
    if not removed:
        return doc, removed
    return {k: v for k, v in doc.items() if k not in removed}, removed


def envelope(
    tool: str,
    args: Dict[str, Any],
    rows: List[Dict[str, Any]],
    next_token: Optional[str] = None,
    include_time_series: bool = True,
) -> Dict[str, Any]:
    """Wrap rows in a self describing envelope.

    Tells the model what range was actually queried (after defaults), how much
    came back, and whether there is more, without it having to ask again.
    """
    omitted: List[str] = []
    if not include_time_series:
        stripped = []
        for row in rows:
            row, removed = strip_time_series(row)
            stripped.append(row)
            omitted.extend(k for k in removed if k not in omitted)
        rows = stripped

    result: Dict[str, Any] = {
        "tool": tool,
        "args": args,
        "count": len(rows),
        "truncated": next_token is not None,
        "next_token": next_token,
        "data": rows,
    }
    if omitted:
        result["omitted_time_series"] = omitted
    return result

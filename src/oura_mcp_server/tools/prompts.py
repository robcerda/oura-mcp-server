"""Prompt templates for common Oura questions."""

from oura_mcp_server.app import mcp

WEEKLY_REVIEW = (
    "Review my Oura data for the last {days} days. Include:\n"
    "1. Trends in sleep, readiness and activity scores (use get_daily_summary)\n"
    "2. Sleep timing and consistency: bedtimes, wake times, total sleep, deep and REM\n"
    "3. HRV, resting heart rate and temperature deviation compared across the period\n"
    "4. Any tags I logged (get_enhanced_tags) that line up with good or bad days\n\n"
    "Finish with the two or three changes most likely to improve my recovery."
)

SLEEP_DEEP_DIVE = (
    "Analyze my sleep on the night of {date}. Use get_sleep_periods for that day and "
    "get_daily_sleep for the score and contributors, and compare against the previous "
    "two weeks. Explain which contributors pulled the score down and what the stages, "
    "heart rate and HRV suggest."
)


@mcp.prompt()
def weekly_health_review(days: str = "7") -> str:
    """Review recent sleep, readiness, activity and recovery trends."""
    return WEEKLY_REVIEW.format(days=days)


@mcp.prompt()
def sleep_deep_dive(date: str) -> str:
    """Analyze a single night's sleep against recent nights."""
    return SLEEP_DEEP_DIVE.format(date=date)

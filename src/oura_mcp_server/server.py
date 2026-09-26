"""
Oura MCP Server entry point.

This module re-exports every public name so that ``python server.py``,
``mcp run server.py`` and imports like
``from oura_mcp_server.server import get_daily_sleep`` keep working.
The implementation lives in ``app``, ``client``, ``params`` and ``tools``.
"""

from oura_mcp_server.app import app, main, mcp  # noqa: F401
from oura_mcp_server.client import OuraError, get_http_client  # noqa: F401
from oura_mcp_server.tools.activity import (  # noqa: F401
    get_daily_activity,
    get_sessions,
    get_workouts,
)
from oura_mcp_server.tools.auth import check_auth_status, setup_authentication  # noqa: F401
from oura_mcp_server.tools.documents import get_document  # noqa: F401
from oura_mcp_server.tools.health import (  # noqa: F401
    get_daily_cardiovascular_age,
    get_daily_spo2,
    get_daily_stress,
    get_heart_rate,
    get_vo2_max,
)
from oura_mcp_server.tools.profile import (  # noqa: F401
    get_enhanced_tags,
    get_personal_info,
    get_rest_mode_periods,
    get_ring_battery_level,
    get_ring_configuration,
)
from oura_mcp_server.tools.prompts import sleep_deep_dive, weekly_health_review  # noqa: F401
from oura_mcp_server.tools.readiness import get_daily_readiness, get_daily_resilience  # noqa: F401
from oura_mcp_server.tools.sleep import (  # noqa: F401
    get_daily_sleep,
    get_sleep_periods,
    get_sleep_time,
)
from oura_mcp_server.tools.summary import get_daily_summary  # noqa: F401

if __name__ == "__main__":
    main()

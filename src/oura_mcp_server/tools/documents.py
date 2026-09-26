"""Single document lookup (/{data_type}/{document_id})."""

from typing import Annotated, Any, Dict, Literal
from urllib.parse import quote

from pydantic import Field

from oura_mcp_server.app import mcp
from oura_mcp_server.client import oura_get

# Tool facing name -> API path segment. Oura spells one of them vO2_max.
DOCUMENT_PATHS = {
    "daily_activity": "daily_activity",
    "daily_cardiovascular_age": "daily_cardiovascular_age",
    "daily_readiness": "daily_readiness",
    "daily_resilience": "daily_resilience",
    "daily_sleep": "daily_sleep",
    "daily_spo2": "daily_spo2",
    "daily_stress": "daily_stress",
    "enhanced_tag": "enhanced_tag",
    "rest_mode_period": "rest_mode_period",
    "ring_configuration": "ring_configuration",
    "session": "session",
    "sleep": "sleep",
    "sleep_time": "sleep_time",
    "vo2_max": "vO2_max",
    "workout": "workout",
}

DataType = Literal[
    "daily_activity",
    "daily_cardiovascular_age",
    "daily_readiness",
    "daily_resilience",
    "daily_sleep",
    "daily_spo2",
    "daily_stress",
    "enhanced_tag",
    "rest_mode_period",
    "ring_configuration",
    "session",
    "sleep",
    "sleep_time",
    "vo2_max",
    "workout",
]


@mcp.tool()
async def get_document(
    data_type: Annotated[
        DataType, Field(description="Collection the document belongs to, e.g. 'sleep'.")
    ],
    document_id: Annotated[
        str, Field(description="The document's 'id' field from a list result.")
    ],
) -> Dict[str, Any]:
    """
    Get one Oura document by id, with every field including embedded time series.
    Use it to drill into a single sleep period, workout or session from a list result.
    """
    path = f"/{DOCUMENT_PATHS[data_type]}/{quote(document_id, safe='')}"
    return await oura_get(path)

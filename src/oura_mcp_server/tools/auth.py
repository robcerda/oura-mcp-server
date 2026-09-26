"""Authentication status tools.

Signing in happens outside the model, in login_setup.py: the OAuth consent
screen needs a browser, and the client secret should never pass through a
tool argument. Signing out is also left to that script, so nothing the model
reads back can talk it into deleting the stored session.
"""

import time
from typing import Any, Dict

from oura_mcp_server.app import mcp
from oura_mcp_server.client import sandbox
from oura_mcp_server.oauth import ALL_SCOPES
from oura_mcp_server.token_store import get_store


@mcp.tool()
async def setup_authentication() -> str:
    """Get instructions for connecting this server to an Oura account."""
    return """Oura: authentication setup

1. Register an API application at https://cloud.ouraring.com/oauth/applications
   Set its redirect URI to exactly: http://localhost:8765/callback
2. In a terminal, from the oura-mcp-server directory, run:
       uv run python login_setup.py
   Enter the client ID and secret, approve access in the browser window that
   opens, and the session is saved to the system keyring.
3. Restart the MCP client if a tool still reports that you are not signed in.

The session refreshes itself. Run the script again only if Oura revokes it.
Run `uv run python login_setup.py --logout` to remove the stored session.

To try the tools without an account, set OURA_MCP_SANDBOX=1 in the server's
environment to read Oura's sample data instead."""


@mcp.tool()
async def check_auth_status() -> Dict[str, Any]:
    """Report whether an Oura session is stored, which scopes it has, and when it expires.

    Never returns token values. The access token refreshes automatically, so an
    expired access token with a stored refresh token is still a working session.
    """
    if sandbox():
        return {"mode": "sandbox", "authenticated": True, "note": "Serving Oura sample data."}

    store = get_store()
    session = store.load()
    if session is None:
        return {
            "mode": "live",
            "authenticated": False,
            "storage": store.backend,
            "next_step": "Run `uv run python login_setup.py` (see setup_authentication).",
        }

    # Oura reports scopes with a prefix ("extapi:daily") but requests them bare.
    granted = [s.removeprefix("extapi:") for s in session.scope.split()]
    remaining = int(session.expires_at - time.time())
    return {
        "mode": "live",
        "authenticated": True,
        "storage": store.backend,
        "client_id": session.client_id,
        "scopes_granted": granted,
        "scopes_missing": [s for s in ALL_SCOPES if granted and s not in granted],
        "access_token_expires_in_seconds": max(remaining, 0),
        "note": (
            "The access token refreshes automatically on the next call."
            if remaining <= 0
            else "Session is active."
        ),
    }

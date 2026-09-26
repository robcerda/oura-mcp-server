"""OAuth2 authorization code flow for the Oura API.

Personal access tokens were retired in December 2025, so the only way in is a
registered API application (https://cloud.ouraring.com/oauth/applications)
and the standard authorization code grant. Access tokens are short lived and
the refresh token rotates: every refresh returns a new one and the old one
stops working, so the new session has to be persisted before it is used.
"""

import time
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlencode

import httpx

from oura_mcp_server.token_store import OuraSession

AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"
DEFAULT_REDIRECT_URI = "http://localhost:8765/callback"

# Every read scope the API defines. The user can still untick any of them on
# Oura's consent screen; tools for a declined scope then fail with a 403.
ALL_SCOPES = (
    "email",
    "personal",
    "daily",
    "heartrate",
    "workout",
    "tag",
    "session",
    "spo2",
    "heart_health",
)

# Used when a token response leaves out expires_in. Oura documents access
# tokens as lasting about a day; assuming less only costs an early refresh.
_DEFAULT_EXPIRES_IN = 24 * 60 * 60


class OAuthError(Exception):
    """A token endpoint failure. ``error`` is the OAuth error code if Oura sent one."""

    def __init__(self, message: str, error: Optional[str] = None, status_code: int = 0):
        super().__init__(message)
        self.error = error
        self.status_code = status_code


def build_authorize_url(
    client_id: str, redirect_uri: str, state: str, scopes: Iterable[str] = ALL_SCOPES
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _parse_token_response(response: httpx.Response) -> Dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if response.is_success and body.get("access_token"):
        return body
    error = body.get("error")
    detail = body.get("error_description") or error or response.text or response.reason_phrase
    raise OAuthError(
        f"Oura token endpoint returned {response.status_code}: {detail}",
        error=error if isinstance(error, str) else None,
        status_code=response.status_code,
    )


def session_from_token_response(
    body: Dict[str, Any],
    client_id: str,
    client_secret: str,
    previous: Optional[OuraSession] = None,
    now: Optional[float] = None,
) -> OuraSession:
    """Build a session from a token response.

    A refresh response that leaves out refresh_token or scope keeps the
    previous values rather than storing a session that can never refresh.
    """
    refresh_token = body.get("refresh_token") or (previous.refresh_token if previous else None)
    if not refresh_token:
        raise OAuthError("Oura did not return a refresh token")
    try:
        expires_in = float(body.get("expires_in") or _DEFAULT_EXPIRES_IN)
    except (TypeError, ValueError):
        expires_in = _DEFAULT_EXPIRES_IN
    return OuraSession(
        client_id=client_id,
        client_secret=client_secret,
        access_token=body["access_token"],
        refresh_token=refresh_token,
        expires_at=(now if now is not None else time.time()) + expires_in,
        scope=body.get("scope") or (previous.scope if previous else ""),
        token_type=body.get("token_type") or "Bearer",
    )


def exchange_code(
    http: httpx.Client, client_id: str, client_secret: str, code: str, redirect_uri: str
) -> OuraSession:
    """Trade an authorization code for a session. Codes are single use and expire in 10 minutes."""
    response = http.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    return session_from_token_response(
        _parse_token_response(response), client_id, client_secret
    )


async def refresh(http: httpx.AsyncClient, session: OuraSession) -> OuraSession:
    """Exchange the session's refresh token for a new session."""
    try:
        response = await http.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": session.refresh_token,
                "client_id": session.client_id,
                "client_secret": session.client_secret,
            },
        )
    except httpx.HTTPError as e:
        raise OAuthError(f"Could not reach the Oura token endpoint: {e}") from e
    return session_from_token_response(
        _parse_token_response(response), session.client_id, session.client_secret, session
    )

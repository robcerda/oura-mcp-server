"""HTTP client for the Oura API v2 (https://cloud.ouraring.com/v2/docs)."""

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx
from dotenv import load_dotenv

from oura_mcp_server import oauth
from oura_mcp_server.token_store import OuraSession, get_store

logger = logging.getLogger(__name__)

load_dotenv()

BASE_URL = "https://api.ouraring.com"
USER_PATH = "/v2/usercollection"
SANDBOX_PATH = "/v2/sandbox/usercollection"
MAX_RETRIES = 3
# Longest Retry-After worth waiting out inside a tool call. Anything longer is
# reported so the model can tell the user, rather than hanging the call.
MAX_RETRY_WAIT_SECONDS = 30
TIMEOUT_SECONDS = 30.0
# Refresh this long before the recorded expiry, so a token cannot expire
# between the check and the request.
EXPIRY_MARGIN_SECONDS = 120
# Pages followed per tool call before handing back a next_token instead.
MAX_PAGES = 10

NOT_AUTHENTICATED = (
    "Not signed in to Oura. Run `uv run python login_setup.py` in the "
    "oura-mcp-server directory, then retry. Set OURA_MCP_SANDBOX=1 to try the "
    "server against Oura's sample data without an account."
)

_client: Optional[httpx.AsyncClient] = None
_session: Optional[OuraSession] = None
_refresh_lock = asyncio.Lock()


class OuraError(Exception):
    """Raised when an Oura request fails. The message is shown to the model."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


def sandbox() -> bool:
    """Whether to serve Oura's sandbox (sample) data instead of the user's own."""
    value = os.environ.get("OURA_MCP_SANDBOX", "")
    return value.strip().lower() in ("1", "true", "yes", "on")


def get_http_client() -> httpx.AsyncClient:
    """Get the shared HTTP client, creating it on first use."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )
    return _client


def clear_session_cache() -> None:
    """Forget the in memory session so the next call reloads it from storage."""
    global _session
    _session = None


def _expiring(session: OuraSession) -> bool:
    return session.expires_at - EXPIRY_MARGIN_SECONDS <= time.time()


async def _refresh(session: OuraSession) -> OuraSession:
    """Refresh *session*, persist the result, and return it.

    Refresh tokens rotate, and an MCP host can run several copies of this
    server against the same stored session. If another process refreshes
    first, the token held here is already spent and Oura answers
    invalid_grant, but storage holds its replacement, so check there before
    giving up.
    """
    http = get_http_client()
    store = get_store()
    try:
        new = await oauth.refresh(http, session)
    except oauth.OAuthError as e:
        if e.error != "invalid_grant" and e.status_code not in (400, 401):
            raise OuraError(f"Could not refresh the Oura session: {e}") from e
        # Give a concurrent refresh a moment to finish writing.
        await asyncio.sleep(1)
        latest = store.load()
        if latest is None or latest.refresh_token == session.refresh_token:
            raise OuraError(
                "Oura rejected the stored refresh token (it was revoked, or the "
                "session is older than Oura allows). Run `uv run python "
                "login_setup.py` again.",
                401,
            ) from e
        if not _expiring(latest):
            return latest
        try:
            new = await oauth.refresh(http, latest)
        except oauth.OAuthError as retry_error:
            raise OuraError(
                f"Could not refresh the Oura session: {retry_error}. Run "
                "`uv run python login_setup.py` again."
            ) from retry_error

    try:
        store.save(new)
    except Exception as e:
        # The old refresh token is already spent, so this process can keep
        # working from memory but a restart will need a fresh login.
        logger.error("Refreshed the Oura session but could not store it: %s", e)
    logger.info("Refreshed the Oura access token")
    return new


async def access_token(force_refresh: bool = False) -> str:
    """Return a usable access token, refreshing it when it is about to expire."""
    global _session
    if sandbox():
        # The sandbox accepts any bearer value but rejects a missing one.
        return "sandbox"
    if _session is None:
        _session = get_store().load()
    if _session is None:
        raise OuraError(NOT_AUTHENTICATED, 401)
    if not force_refresh and not _expiring(_session):
        return _session.access_token

    stale = _session.access_token
    async with _refresh_lock:
        # Another task in this process may have refreshed while this one
        # waited for the lock; then _session has already moved on. Otherwise
        # another process may have, in which case storage holds a newer
        # session. Either way, use that instead of spending a refresh token.
        if _session.access_token == stale:
            stored = get_store().load()
            if stored and stored.access_token != stale and not _expiring(stored):
                _session = stored
            else:
                _session = await _refresh(_session)
        return _session.access_token


def _validation_detail(body: Any) -> Optional[str]:
    """Flatten a FastAPI style {"detail": [...]} validation error."""
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = item.get("loc") or []
                name = next((str(p) for p in reversed(loc) if p not in ("date", "datetime")), "")
                parts.append(f"{name}: {item.get('msg')}" if name else str(item.get("msg")))
        # Oura reports one entry per accepted type, which repeats the field.
        return "; ".join(dict.fromkeys(parts)) or None
    return None


def _missing_scope(response: httpx.Response) -> bool:
    """Whether a 401 means the token lacks a scope rather than being invalid.

    Oura answers a missing scope with 401 and a body such as "Token is not
    authorized access stress scope.", not the 403 its docs describe.
    Refreshing cannot fix that, and each refresh spends the refresh token.
    """
    try:
        detail = _validation_detail(response.json())
    except ValueError:
        return False
    return response.status_code == 401 and bool(detail) and "scope" in detail.lower()


_SCOPE_HINT = (
    "The session lacks the scope this data needs (it was unticked on "
    "Oura's consent screen), or the Oura membership has lapsed. Re-run "
    "login_setup.py and grant it."
)


def error_message(response: httpx.Response) -> str:
    """Build a readable error from an Oura error response."""
    try:
        detail = _validation_detail(response.json()) or response.text
    except ValueError:
        detail = response.text or response.reason_phrase
    if _missing_scope(response):
        return f"Oura API error {response.status_code}: {detail} ({_SCOPE_HINT})"
    hints = {
        401: "Run `uv run python login_setup.py` to sign in again.",
        403: _SCOPE_HINT,
        429: (
            "Oura rate limit reached"
            + (
                f" (tier: {response.headers['X-RateLimit-Tier']})"
                if "X-RateLimit-Tier" in response.headers
                else ""
            )
            + ". Try again shortly, or request a smaller date range."
        ),
    }
    message = f"Oura API error {response.status_code}: {detail}"
    hint = hints.get(response.status_code)
    return f"{message} ({hint})" if hint else message


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return float(2**attempt)


async def oura_get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """GET *path* under the user collection and return the JSON body.

    None values are dropped from params. A 401 triggers one token refresh and
    retry, unless it says a scope is missing. Rate limited requests (429) are
    retried, honouring Retry-After. Any other non-2xx response raises
    OuraError with the API's message.
    """
    client = get_http_client()
    url = (SANDBOX_PATH if sandbox() else USER_PATH) + path
    query = {k: v for k, v in (params or {}).items() if v is not None}
    token = await access_token()
    refreshed = False

    attempt = 0
    while True:
        try:
            response = await client.get(
                url, params=query, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.TimeoutException as e:
            raise OuraError(f"Request to Oura timed out: {path}") from e
        except httpx.HTTPError as e:
            raise OuraError(f"Could not reach Oura: {e}") from e

        if (
            response.status_code == 401
            and not refreshed
            and not sandbox()
            and not _missing_scope(response)
        ):
            # The recorded expiry can be wrong (revoked early, clock skew).
            refreshed = True
            token = await access_token(force_refresh=True)
            continue
        if response.status_code == 429 and attempt < MAX_RETRIES:
            delay = _retry_delay(response, attempt)
            if delay <= MAX_RETRY_WAIT_SECONDS:
                attempt += 1
                logger.warning("Rate limited on %s, retrying in %ss", path, delay)
                await asyncio.sleep(delay)
                continue
        break

    if response.is_success:
        return response.json()
    logger.error("GET %s failed with %s", path, response.status_code)
    raise OuraError(error_message(response), response.status_code)


async def get_collection(
    path: str, params: Dict[str, Any], max_pages: Optional[int] = None
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Fetch a paginated collection, following next_token up to *max_pages* (MAX_PAGES).

    Returns the rows and the next_token still outstanding (None when the
    collection was read to the end).
    """
    rows: List[Dict[str, Any]] = []
    token = params.get("next_token")
    for _ in range(max_pages or MAX_PAGES):
        body = await oura_get(path, {**params, "next_token": token})
        rows.extend(body.get("data") or [])
        token = body.get("next_token")
        if not token:
            break
    return rows, token

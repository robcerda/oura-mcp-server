"""Shared test fixtures for Oura MCP Server tests."""

import asyncio
import json
import time
from typing import Any, Callable, Dict, List, Union
from urllib.parse import parse_qsl

import httpx
import pytest

from oura_mcp_server import client as client_module
from oura_mcp_server import token_store as token_store_module
from oura_mcp_server.token_store import OuraSession, TokenStore

Handler = Union[httpx.Response, Callable[[httpx.Request], httpx.Response]]


class FakeOura:
    """Stands in for api.ouraring.com and records every request made to it."""

    def __init__(self) -> None:
        self.routes: Dict[str, List[Handler]] = {}
        self.requests: List[httpx.Request] = []

    def add(self, path: str, *responses: Handler) -> None:
        """Queue responses for a path. The last one repeats once the queue runs out.

        Paths starting with /oauth are used as is; anything else is taken to be
        under /v2/usercollection.
        """
        full = path if path.startswith(("/oauth", "/v2")) else f"/v2/usercollection{path}"
        self.routes[full] = list(responses)

    def json(self, path: str, body: Any, status: int = 200, **headers: str) -> None:
        self.add(path, httpx.Response(status, json=body, headers=headers))

    def rows(self, path: str, rows: List[Dict[str, Any]], next_token: Any = None) -> None:
        self.json(path, {"data": rows, "next_token": next_token})

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        queue = self.routes.get(request.url.path)
        if not queue:
            return httpx.Response(404, json={"detail": f"no fake route for {request.url.path}"})
        handler = queue.pop(0) if len(queue) > 1 else queue[0]
        return handler(request) if callable(handler) else handler

    def to(self, path: str) -> List[httpx.Request]:
        full = path if path.startswith(("/oauth", "/v2")) else f"/v2/usercollection{path}"
        return [r for r in self.requests if r.url.path == full]

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    @property
    def last_params(self) -> Dict[str, str]:
        return dict(parse_qsl(self.last.url.query.decode()))


def make_session(**overrides: Any) -> OuraSession:
    values: Dict[str, Any] = {
        "client_id": "client-123",
        "client_secret": "secret-456",
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_at": time.time() + 3600,
        "scope": "daily heartrate personal",
    }
    values.update(overrides)
    return OuraSession(**values)


def token_body(n: int, **overrides: Any) -> Dict[str, Any]:
    body = {
        "access_token": f"access-{n}",
        "refresh_token": f"refresh-{n}",
        "expires_in": 86400,
        "token_type": "bearer",
        "scope": "daily heartrate personal",
    }
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path) -> TokenStore:
    """Keep every test off the real keyring, the real home directory and the network."""
    for name in ("OURA_MCP_SANDBOX", "OURA_CLIENT_ID", "OURA_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    store = TokenStore(directory=tmp_path / "session", use_keyring=False)
    monkeypatch.setattr(token_store_module, "_store", store)
    monkeypatch.setattr(client_module, "_session", None)
    monkeypatch.setattr(client_module, "_refresh_lock", asyncio.Lock())
    monkeypatch.setattr(client_module, "_client", None)

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(client_module.asyncio, "sleep", no_sleep)
    return store


@pytest.fixture
def oura(monkeypatch) -> FakeOura:
    """Route the shared HTTP client to a fake Oura API."""
    fake = FakeOura()
    monkeypatch.setattr(
        client_module,
        "_client",
        httpx.AsyncClient(
            base_url=client_module.BASE_URL, transport=httpx.MockTransport(fake.handle)
        ),
    )
    return fake


@pytest.fixture
def signed_in(isolated) -> OuraSession:
    """A stored session with a valid access token."""
    session = make_session()
    isolated.save(session)
    return session


async def call_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """Call a tool through the MCP server and return its decoded JSON result."""
    from oura_mcp_server.app import mcp

    result = await mcp.call_tool(name, arguments)
    content = result[0] if isinstance(result, tuple) else result
    return json.loads(content[0].text)

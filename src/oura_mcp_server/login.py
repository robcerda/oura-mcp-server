"""Terminal sign in for the Oura MCP server.

Runs the OAuth authorization code flow: opens Oura's consent page in a
browser, catches the redirect on a local port, exchanges the code for tokens
and saves the session to the system keyring. The client secret is typed here
and never passes through the model.

    uv run python login_setup.py              # browser + local callback
    uv run python login_setup.py --paste      # no local server; paste the redirect URL
    uv run python login_setup.py --status
    uv run python login_setup.py --logout
"""

import argparse
import getpass
import os
import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, Optional
from urllib.parse import parse_qs, urlparse

import httpx
from dotenv import load_dotenv

from oura_mcp_server import oauth
from oura_mcp_server.client import BASE_URL, USER_PATH
from oura_mcp_server.token_store import OuraSession, TokenStore, get_store

APPLICATIONS_URL = "https://cloud.ouraring.com/oauth/applications"

_SUCCESS_PAGE = b"""<!doctype html><meta charset="utf-8"><title>Oura MCP</title>
<body style="font-family:system-ui;margin:3em">
<h2>Oura authorization received</h2><p>You can close this tab and return to the terminal.</p>"""


class LoginError(Exception):
    """A sign in failure with a message meant for the person at the terminal."""


def parse_callback(url: str, expected_state: str) -> str:
    """Pull the authorization code out of a redirect URL, checking state.

    Accepts a full URL or just its query string, since people paste either.
    """
    query = urlparse(url).query if "?" in url or "://" in url else url.lstrip("?")
    params = {k: v[0] for k, v in parse_qs(query).items()}
    if "error" in params:
        detail = params.get("error_description") or params["error"]
        raise LoginError(f"Oura declined the authorization: {detail}")
    state = params.get("state", "")
    # The state ties this redirect to the request made above. Without the
    # check, any page could hand the local listener a code for someone
    # else's account.
    if not secrets.compare_digest(state, expected_state):
        raise LoginError("The redirect's state does not match this login attempt. Start over.")
    code = params.get("code")
    if not code:
        raise LoginError("The redirect URL has no authorization code in it.")
    return code


def wait_for_callback(redirect_uri: str, timeout: float) -> str:
    """Listen on the redirect URI's port until Oura redirects back, and return that URL."""
    target = urlparse(redirect_uri)
    if target.scheme != "http" or target.hostname not in ("localhost", "127.0.0.1"):
        raise LoginError(
            f"Can only listen on an http://localhost redirect URI, not {redirect_uri}. "
            "Use --paste for any other redirect URI."
        )
    received: Dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (http.server naming)
            if urlparse(self.path).path != (target.path or "/"):
                self.send_response(404)
                self.end_headers()
                return
            received["url"] = self.path
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_SUCCESS_PAGE)

        def log_message(self, format: str, *args: object) -> None:
            # The default handler logs the request line, which holds the code.
            pass

    try:
        server = HTTPServer(("127.0.0.1", target.port or 80), Handler)
    except OSError as e:
        raise LoginError(
            f"Could not listen on port {target.port}: {e}. Free the port, or use --paste."
        ) from e
    server.timeout = 1
    deadline = time.monotonic() + timeout
    try:
        while "url" not in received:
            if time.monotonic() > deadline:
                raise LoginError("Timed out waiting for the browser to return from Oura.")
            server.handle_request()
    finally:
        server.server_close()
    return received["url"]


def _client_credentials(reuse: Optional[OuraSession]) -> tuple[str, str]:
    client_id = os.environ.get("OURA_CLIENT_ID", "").strip()
    client_secret = os.environ.get("OURA_CLIENT_SECRET", "").strip()
    if client_id and client_secret:
        return client_id, client_secret
    if reuse is not None:
        answer = input(f"Reuse the stored client ID {reuse.client_id}? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            return reuse.client_id, reuse.client_secret
    print(f"Find these on your application at {APPLICATIONS_URL}")
    client_id = client_id or input("Client ID: ").strip()
    client_secret = client_secret or getpass.getpass("Client secret (hidden): ").strip()
    if not client_id or not client_secret:
        raise LoginError("Both a client ID and a client secret are required.")
    return client_id, client_secret


def verify(http: httpx.Client, session: OuraSession) -> str:
    """Call the API with the new token and return who it belongs to."""
    response = http.get(
        BASE_URL + USER_PATH + "/personal_info",
        headers={"Authorization": f"Bearer {session.access_token}"},
    )
    if not response.is_success:
        raise LoginError(
            f"Oura issued a token but rejected it ({response.status_code}): {response.text}"
        )
    info = response.json()
    return info.get("email") or f"user {info.get('id')}"


def login(
    redirect_uri: str,
    paste: bool = False,
    open_browser: bool = True,
    timeout: float = 300,
    store: Optional[TokenStore] = None,
    http: Optional[httpx.Client] = None,
) -> OuraSession:
    store = store or get_store()
    client_id, client_secret = _client_credentials(store.load())
    state = secrets.token_urlsafe(32)
    url = oauth.build_authorize_url(client_id, redirect_uri, state)

    print("\nOpen this URL to approve access (grant every scope you want the tools to read):")
    print(f"\n  {url}\n")
    if paste:
        print("After approving, your browser is sent to the redirect URI. The page may")
        print("fail to load; that is expected. Copy the full URL from the address bar.")
        redirect = input("Paste the redirect URL: ").strip()
    else:
        if open_browser:
            webbrowser.open(url)
        print(f"Waiting for Oura to redirect back to {redirect_uri} ...")
        redirect = wait_for_callback(redirect_uri, timeout)

    code = parse_callback(redirect, state)
    owns_http = http is None
    http = http or httpx.Client(timeout=30)
    try:
        try:
            session = oauth.exchange_code(http, client_id, client_secret, code, redirect_uri)
        except oauth.OAuthError as e:
            hint = {
                "invalid_client": "Check the client ID and secret.",
                "invalid_grant": "The code expired or was already used. Run the script again.",
            }.get(e.error or "", "Check that the redirect URI matches the application exactly.")
            raise LoginError(f"{e} ({hint})") from e
        who = verify(http, session)
    finally:
        if owns_http:
            http.close()

    store.save(session)
    print(f"\nSigned in to Oura as {who}.")
    print(f"Scopes granted: {session.scope or '(not reported)'}")
    print(f"Session saved to {store.backend}.")
    return session


def status(store: TokenStore) -> None:
    session = store.load()
    if session is None:
        print(f"No Oura session stored ({store.backend}).")
        return
    remaining = int(session.expires_at - time.time())
    print(f"Oura session stored in {store.backend}")
    print(f"  client ID: {session.client_id}")
    print(f"  scopes:    {session.scope or '(not reported)'}")
    if remaining > 0:
        print(f"  access token expires in {remaining // 60} minutes (refreshes automatically)")
    else:
        print("  access token expired; it refreshes on the next tool call")


def main(argv: Optional[list[str]] = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Sign the Oura MCP server in to Oura.")
    parser.add_argument(
        "--redirect-uri",
        default=os.environ.get("OURA_MCP_REDIRECT_URI", oauth.DEFAULT_REDIRECT_URI),
        help="Must match the application's redirect URI exactly "
        f"(env: OURA_MCP_REDIRECT_URI; default: {oauth.DEFAULT_REDIRECT_URI})",
    )
    parser.add_argument(
        "--paste",
        action="store_true",
        help="Do not listen for the redirect; paste the redirected URL instead "
        "(for containers, remote shells, or a non-localhost redirect URI)",
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="Print the URL without opening a browser"
    )
    parser.add_argument("--status", action="store_true", help="Show the stored session")
    parser.add_argument("--logout", action="store_true", help="Delete the stored session")
    args = parser.parse_args(argv)

    store = get_store()
    if args.status:
        status(store)
        return 0
    if args.logout:
        store.delete()
        print("Deleted the stored Oura session.")
        print(f"To revoke the app's access entirely, remove it at {APPLICATIONS_URL}")
        return 0
    try:
        login(args.redirect_uri, paste=args.paste, open_browser=not args.no_browser, store=store)
    except LoginError as e:
        print(f"\nLogin failed: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Persistent storage for the Oura OAuth session.

The session (client credentials, access token, refresh token, expiry) is kept
in the system keyring, with a 0600 file fallback for environments that have
no keyring backend (containers, WSL, headless Linux).

Adapted from monarch-mcp-server's secure_session.py. The Oura blob is a few
hundred characters, well under the Windows Credential Manager limit, so the
chunking that module needs is left out. Two of its lessons are kept because
they cost real debugging time there:

- The keyring probe username is per process, so two server processes started
  by the same MCP host cannot race each other's probe and silently drop one of
  them to file storage.
- Load prefers the keyring, so any save that falls back to the file first
  deletes the keyring entry. Otherwise a stale keyring session shadows the
  fresh one in the file, which with rotating refresh tokens means a dead
  session that never recovers.
"""

import json
import logging
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "com.mcp.oura-mcp-server"
KEYRING_USERNAME = "oura-oauth-session"

_PROBE_USERNAME = f"__keyring_probe__{os.getpid()}"
_PROBE_VALUE = "x" * 1024


def _default_dir() -> Path:
    override = os.environ.get("OURA_MCP_SESSION_DIR")
    return Path(override).expanduser() if override else Path.home() / ".oura-mcp-server"


@dataclass
class OuraSession:
    """Everything needed to call the API and to refresh when the token expires.

    The client id and secret are stored with the tokens because a refresh
    token is bound to the application that issued it: refreshing with any
    other credentials fails, so they have to travel together.
    """

    client_id: str
    client_secret: str
    access_token: str
    refresh_token: str
    expires_at: float
    scope: str = ""
    token_type: str = "Bearer"
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> Optional["OuraSession"]:
        """Parse a stored blob, or return None if it is not a usable session."""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        required = ("client_id", "client_secret", "access_token", "refresh_token")
        if not all(isinstance(data.get(k), str) and data[k] for k in required):
            return None
        try:
            expires_at = float(data.get("expires_at", 0))
        except (TypeError, ValueError):
            expires_at = 0.0
        return cls(
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=expires_at,
            scope=str(data.get("scope") or ""),
            token_type=str(data.get("token_type") or "Bearer"),
            extra=data.get("extra") if isinstance(data.get("extra"), dict) else {},
        )


def _keyring_available() -> bool:
    """Probe whether the keyring backend can actually round-trip a value.

    Class name sniffing is unreliable (the macOS backend and the no-op fail
    backend are both called ``Keyring``), so set, get and delete a sentinel
    instead. Only set and get decide the verdict; cleanup is best effort.
    """
    try:
        import keyring
    except ImportError:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, _PROBE_USERNAME, _PROBE_VALUE)
        stored = keyring.get_password(KEYRING_SERVICE, _PROBE_USERNAME)
    except Exception:
        return False
    finally:
        try:
            keyring.delete_password(KEYRING_SERVICE, _PROBE_USERNAME)
        except Exception:
            pass
    return stored == _PROBE_VALUE


def _write_secret_file(path: Path, data: str) -> None:
    """Write *data* to *path* atomically, created at 0600 from the start.

    ``write_text`` then ``chmod`` leaves a window where the file exists under
    the umask (usually 0644). Writing a temp file opened with an explicit
    mode and ``os.replace``-ing it into place avoids that, and means a reader
    never sees a half written session.
    """
    tmp_path = path.parent / f".{path.name}.{os.getpid()}.tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class TokenStore:
    """Keyring backed session storage with a file fallback."""

    def __init__(self, directory: Optional[Path] = None, use_keyring: Optional[bool] = None):
        self.directory = directory or _default_dir()
        self.file = self.directory / "session.json"
        self._use_keyring = _keyring_available() if use_keyring is None else use_keyring

    @property
    def backend(self) -> str:
        return "keyring" if self._use_keyring else f"file ({self.file})"

    # -- file ---------------------------------------------------------------

    def _save_file(self, blob: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=stat.S_IRWXU)
        try:
            self.directory.chmod(stat.S_IRWXU)
        except OSError as e:
            logger.warning("Could not restrict %s: %s", self.directory, e)
        _write_secret_file(self.file, blob)

    def _load_file(self) -> Optional[str]:
        try:
            raw = self.file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        return raw or None

    def _delete_file(self) -> None:
        try:
            self.file.unlink()
        except FileNotFoundError:
            pass

    # -- keyring --------------------------------------------------------------

    def _load_keyring(self) -> Optional[str]:
        if not self._use_keyring:
            return None
        try:
            import keyring

            return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception as e:
            logger.warning("Keyring load failed, trying file fallback: %s", e)
            return None

    def _delete_keyring(self) -> None:
        if not self._use_keyring:
            return
        try:
            import keyring

            keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
        except Exception:
            pass

    # -- public ---------------------------------------------------------------

    def save(self, session: OuraSession) -> None:
        blob = session.to_json()
        if self._use_keyring:
            try:
                import keyring

                keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, blob)
                # A leftover file is an older session. Remove it so there is
                # only ever one refresh token on disk.
                self._delete_file()
                return
            except Exception as e:
                logger.warning("Keyring save failed, falling back to file: %s", e)
                # Load prefers the keyring, so a stale entry there would
                # shadow the session about to be written to the file.
                self._delete_keyring()
        self._save_file(blob)

    def load(self) -> Optional[OuraSession]:
        """Return the stored session, trying the keyring then the file.

        A source holding an unusable value does not end the search: a corrupt
        keyring entry must not strand a good session in the file.
        """
        for raw, source in ((self._load_keyring(), "keyring"), (self._load_file(), "file")):
            if not raw:
                continue
            session = OuraSession.from_json(raw)
            if session is not None:
                return session
            logger.error("Stored Oura session in %s is unusable; trying the next source", source)
        return None

    def delete(self) -> None:
        self._delete_keyring()
        self._delete_file()


_store: Optional[TokenStore] = None


def get_store() -> TokenStore:
    """The process wide store, created on first use so importing is side effect free."""
    global _store
    if _store is None:
        _store = TokenStore()
    return _store

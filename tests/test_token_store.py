"""Session storage: keyring first, 0600 file fallback, no stale shadowing."""

import os
import stat
import sys

import keyring
import pytest
from conftest import make_session

from oura_mcp_server import token_store as token_store_module
from oura_mcp_server.token_store import KEYRING_SERVICE, KEYRING_USERNAME, OuraSession, TokenStore


class FakeKeyring:
    def __init__(self):
        self.values = {}
        self.fail_set = False

    def set_password(self, service, user, value):
        if self.fail_set:
            raise RuntimeError("CredWrite failed")
        self.values[(service, user)] = value

    def get_password(self, service, user):
        return self.values.get((service, user))

    def delete_password(self, service, user):
        self.values.pop((service, user), None)


@pytest.fixture
def fake_keyring(monkeypatch):
    fake = FakeKeyring()
    for name in ("set_password", "get_password", "delete_password"):
        monkeypatch.setattr(keyring, name, getattr(fake, name))
    return fake


def test_round_trip_through_the_file(tmp_path):
    store = TokenStore(directory=tmp_path / "s", use_keyring=False)
    session = make_session()

    store.save(session)

    assert store.load() == session


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_file_is_private(tmp_path):
    store = TokenStore(directory=tmp_path / "s", use_keyring=False)
    store.save(make_session())

    assert stat.S_IMODE(os.stat(store.file).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(store.directory).st_mode) == 0o700
    assert not [p for p in store.directory.iterdir() if p.name.endswith(".tmp")]


def test_probe_detects_a_working_keyring(fake_keyring):
    assert token_store_module._keyring_available() is True
    # The probe cleans up after itself.
    assert fake_keyring.values == {}


def test_probe_rejects_a_failing_keyring(fake_keyring):
    fake_keyring.fail_set = True
    assert token_store_module._keyring_available() is False


def test_keyring_save_removes_an_older_file(tmp_path, fake_keyring):
    file_only = TokenStore(directory=tmp_path, use_keyring=False)
    file_only.save(make_session(refresh_token="old"))
    store = TokenStore(directory=tmp_path, use_keyring=True)

    store.save(make_session(refresh_token="new"))

    assert not store.file.exists()
    assert store.load().refresh_token == "new"


def test_failed_keyring_save_does_not_leave_a_stale_session_in_front(tmp_path, fake_keyring):
    """Load prefers the keyring, so a stale entry there would hide the new file."""
    store = TokenStore(directory=tmp_path, use_keyring=True)
    store.save(make_session(refresh_token="old"))
    fake_keyring.fail_set = True

    store.save(make_session(refresh_token="new"))

    assert (KEYRING_SERVICE, KEYRING_USERNAME) not in fake_keyring.values
    assert store.load().refresh_token == "new"


def test_corrupt_keyring_entry_falls_through_to_the_file(tmp_path, fake_keyring):
    TokenStore(directory=tmp_path, use_keyring=False).save(make_session(refresh_token="file"))
    fake_keyring.values[(KEYRING_SERVICE, KEYRING_USERNAME)] = '{"truncated'
    store = TokenStore(directory=tmp_path, use_keyring=True)

    assert store.load().refresh_token == "file"


def test_delete_clears_both(tmp_path, fake_keyring):
    TokenStore(directory=tmp_path, use_keyring=False).save(make_session())
    store = TokenStore(directory=tmp_path, use_keyring=True)
    store.save(make_session())

    store.delete()

    assert store.load() is None
    assert fake_keyring.values == {}


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"client_id": "a", "client_secret": "b", "access_token": "c"}',
        '{"client_id": "", "client_secret": "b", "access_token": "c", "refresh_token": "d"}',
    ],
)
def test_unusable_blobs_are_rejected(raw):
    assert OuraSession.from_json(raw) is None


def test_session_dir_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv("OURA_MCP_SESSION_DIR", str(tmp_path / "custom"))
    assert TokenStore(use_keyring=False).file == tmp_path / "custom" / "session.json"

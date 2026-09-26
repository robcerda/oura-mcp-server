"""The README tool table is the contract an LLM plans against.

A wrong parameter name tends to fail quietly: the filter the user asked for
is simply not applied and the too broad result still looks like an answer.
These tests check the table against the live registry so it cannot drift.
Adapted from monarch-mcp-server.
"""

import inspect
import re
from pathlib import Path

from oura_mcp_server import server as srv
from oura_mcp_server.app import mcp

README = Path(__file__).resolve().parent.parent / "README.md"
ROW = re.compile(
    r"^\|[ \t]*`(?P<name>\w+)`[ \t]*\|[^|\r\n]*\|(?P<params>[^|\r\n]*)\|[ \t]*$",
    re.M,
)


def _documented():
    return {
        m.group("name"): m.group("params")
        for m in ROW.finditer(README.read_text(encoding="utf-8"))
    }


async def _registered():
    return {t.name for t in await mcp.list_tools()}


async def test_every_documented_tool_exists():
    documented, registered = set(_documented()), await _registered()
    assert not (documented - registered), (
        f"README documents tools that are not registered: {sorted(documented - registered)}"
    )


async def test_every_registered_tool_is_documented():
    documented, registered = set(_documented()), await _registered()
    assert not (registered - documented), (
        f"tools missing from the README table: {sorted(registered - documented)}"
    )


async def test_every_tool_is_re_exported_from_server():
    missing = sorted(n for n in await _registered() if not hasattr(srv, n))
    assert not missing, f"tools not re-exported from server.py: {missing}"


async def test_documented_parameters_match_the_signatures():
    mismatches = []
    for name, params in _documented().items():
        fn = getattr(srv, name, None)
        if fn is None:
            continue
        actual = [p.name for p in inspect.signature(fn).parameters.values()]
        listed = (
            []
            if params.strip() == "None"
            else [p.strip().strip("`?").strip("`") for p in params.split(",")]
        )
        if listed != actual:
            mismatches.append((name, listed, actual))
    assert not mismatches, f"README parameters out of sync: {mismatches}"


async def test_tool_count_in_readme_is_current():
    text = README.read_text(encoding="utf-8")
    assert f"All {len(await _registered())} registered tools" in text

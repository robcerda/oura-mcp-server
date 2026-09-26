#!/usr/bin/env python3
"""Sign the Oura MCP server in to Oura. See ``oura_mcp_server.login`` for options.

Kept as a script at the repo root so the documented command works from a
checkout without installing: ``uv run python login_setup.py``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from oura_mcp_server.login import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

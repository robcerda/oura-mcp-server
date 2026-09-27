# Oura MCP Server

A Model Context Protocol (MCP) server for the [Oura Ring API v2](https://cloud.ouraring.com/v2/docs). It gives Claude Desktop, Claude Code and other MCP clients read only access to your sleep, readiness, activity, heart rate, stress, workouts and the rest of the data Oura exposes.

Everything here reads. There are no tools that change anything in your Oura account.

## Quick Start

### 1. Register an Oura API application

Oura retired personal access tokens in December 2025, so the server signs in with OAuth like any other Oura app. You register your own application once; it is free and needs no approval for personal use (Oura only reviews apps with more than 10 users).

1. Go to https://cloud.ouraring.com/oauth/applications and create an application.
2. Set its **Redirect URI** to exactly:
   ```
   http://localhost:8765/callback
   ```
3. Keep the page open. You need the **Client ID** and **Client Secret** in step 3.

### 2. Install

```bash
git clone https://github.com/robcerda/oura-mcp-server.git
cd oura-mcp-server
uv sync --locked
```

`--locked` installs exactly what `uv.lock` pins, verified against the hashes it records, and refuses to re-resolve.

**Using `pip`** instead:
```bash
pip install -r requirements-lock.txt --require-hashes
pip install -e . --no-deps
```

### 3. Sign in (one time)

Authentication happens in your terminal, not in Claude, so the client secret never passes through the model:

```bash
uv run python login_setup.py
```

The script asks for the client ID and secret (or reads `OURA_CLIENT_ID` and `OURA_CLIENT_SECRET`), opens Oura's consent page in your browser, catches the redirect on `localhost:8765`, and saves the session to your system keyring. Grant every data type you want the tools to read; a type you untick makes its tool fail with a 403 until you sign in again.

The access token refreshes itself from then on. You only need to run the script again if the session is revoked.

| Command                                    | What it does                                                           |
| ------------------------------------------ | ---------------------------------------------------------------------- |
| `uv run python login_setup.py`             | Sign in through the browser                                            |
| `uv run python login_setup.py --paste`     | Sign in without the local listener: paste the redirected URL instead   |
| `uv run python login_setup.py --status`    | Show the stored session's scopes and expiry (never the tokens)         |
| `uv run python login_setup.py --logout`    | Delete the stored session                                              |

Use `--paste` over SSH, in a container, or if you registered a redirect URI other than `http://localhost:8765/callback` (pass it with `--redirect-uri`). After approving, the browser lands on the redirect URI; the page may fail to load, which is fine, because the address bar holds the code the script needs.

### 4. Configure your MCP client

**Claude Code**:

```bash
claude mcp add oura -- uv run --locked --project /path/to/oura-mcp-server oura-mcp-server
```

**Claude Desktop**: add this to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "Oura": {
      "command": "uv",
      "args": [
        "run",
        "--locked",
        "--project",
        "/path/to/oura-mcp-server",
        "oura-mcp-server"
      ]
    }
  }
}
```

Replace `/path/to/oura-mcp-server` with your checkout, and use the full path to `uv` if your client cannot find it (`which uv`). `--locked` makes a lockfile that has drifted from `pyproject.toml` a startup error instead of a silent re-resolve against PyPI.

Restart the client, then ask something like *"How has my sleep been this week?"*

### Try it without an account

Set `OURA_MCP_SANDBOX=1` in the server's environment and every tool reads Oura's sandbox sample data instead. No sign in is needed. The sandbox has no personal info, so `get_personal_info` returns a 404 there.

```json
"env": { "OURA_MCP_SANDBOX": "1" }
```

## Available Tools

All 22 registered tools. Optional parameters are marked with a trailing question mark. The table is checked against the live tool registry and the functions' signatures by `tests/test_readme_tool_reference.py`, so it does not drift.

| Tool                           | Description                                                                  | Parameters                                                                 |
| ------------------------------ | ---------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `check_auth_status`            | Report whether a session is stored, its scopes, and when it expires          | None                                                                       |
| `get_daily_activity`           | Activity score, steps, calories, activity time by intensity                  | `start_date`?, `end_date`?, `next_token`?, `include_time_series`?          |
| `get_daily_cardiovascular_age` | Estimated vascular age                                                       | `start_date`?, `end_date`?, `next_token`?                                  |
| `get_daily_readiness`          | Readiness score, contributors, temperature deviation                         | `start_date`?, `end_date`?, `next_token`?                                  |
| `get_daily_resilience`         | Resilience level and its contributors                                        | `start_date`?, `end_date`?, `next_token`?                                  |
| `get_daily_sleep`              | Sleep score and its contributors                                             | `start_date`?, `end_date`?, `next_token`?                                  |
| `get_daily_spo2`               | Average SpO2 during sleep and breathing disturbance index                    | `start_date`?, `end_date`?, `next_token`?                                  |
| `get_daily_stress`             | Time in high stress and high recovery, day summary                           | `start_date`?, `end_date`?, `next_token`?                                  |
| `get_daily_summary`            | One record per day combining scores, activity, stress, SpO2 and main sleep   | `start_date`?, `end_date`?                                                 |
| `get_document`                 | One document by id, with every field                                         | `data_type`, `document_id`                                                 |
| `get_enhanced_tags`            | Tags logged in the Oura app                                                  | `start_date`?, `end_date`?, `next_token`?                                  |
| `get_heart_rate`               | Heart rate samples, optionally aggregated by hour or day                     | `start_datetime`?, `end_datetime`?, `aggregate`?, `latest`?, `next_token`? |
| `get_personal_info`            | Age, weight, height, biological sex, email                                   | None                                                                       |
| `get_rest_mode_periods`        | Rest mode periods and episodes                                               | `start_date`?, `end_date`?, `next_token`?                                  |
| `get_ring_battery_level`       | Ring battery level and charging state                                        | `start_datetime`?, `end_datetime`?, `latest`?, `next_token`?               |
| `get_ring_configuration`       | Ring hardware, color, size, firmware                                         | None                                                                       |
| `get_sessions`                 | Guided and unguided sessions (meditation, breathing, rest)                   | `start_date`?, `end_date`?, `next_token`?, `include_time_series`?          |
| `get_sleep_periods`            | Detailed sleep periods: bedtimes, stages, heart rate, HRV                    | `start_date`?, `end_date`?, `next_token`?, `include_time_series`?          |
| `get_sleep_time`               | Recommended bedtime window                                                   | `start_date`?, `end_date`?, `next_token`?                                  |
| `get_vo2_max`                  | VO2 max estimates                                                            | `start_date`?, `end_date`?, `next_token`?                                  |
| `get_workouts`                 | Workouts: type, time, calories, distance, intensity                          | `start_date`?, `end_date`?, `next_token`?                                  |
| `setup_authentication`         | Instructions for connecting an Oura account                                  | None                                                                       |

Two prompts are also registered: `weekly_health_review` and `sleep_deep_dive`.

### How the tools behave

- **Dates are inclusive.** `start_date="2026-09-01", end_date="2026-09-07"` returns all seven days. (Oura's own `end_date` is exclusive; the server adds the day for you.) With no dates, tools return the last 7 days including today.
- **Heart rate and battery take datetimes**, ISO 8601 such as `2026-09-20T22:00:00-07:00`. A time without an offset is read as UTC. Heart rate defaults to the last 24 hours; raw data is 288 samples a day, so pass `aggregate="hour"` or `"day"` for longer windows.
- **Embedded time series are left out by default.** Sleep periods, daily activity and sessions carry 5 minute sleep phases, 30 second movement, per sample heart rate and HRV, which dominate the response. The envelope's `omitted_time_series` lists what was dropped; pass `include_time_series=true`, or use `get_document` on a single item, to get them.
- **Paging is automatic.** Tools follow Oura's `next_token` for up to 10 pages. If there is more, the response has `truncated: true` and a `next_token` to pass back with the same dates.
- **Responses are self describing.** Every list tool returns `{tool, args, count, truncated, next_token, data}`, where `args` shows the dates actually queried after defaults.
- **`get_daily_summary` degrades gracefully.** Each collection needs its own scope; any that fail are listed under `unavailable` and the rest are still returned.

### Data freshness

Oura only has what the ring has synced. Sleep, readiness and bedtime recommendations appear after you open the Oura app in the morning; activity, stress and heart rate sync in the background through the day. Today's sleep missing is almost always a sync that has not happened yet.

## Usage Examples

```
How has my sleep been over the last two weeks?
```
```
Compare my readiness on days after I logged alcohol to the other days this month.
```
```
What was my heart rate doing overnight on September 20th? Aggregate by hour.
```
```
Show my workouts this month and the activity score on each of those days.
```

## Containerized Deployment

The Docker image uses Astral's uv/Python 3.12 slim base, installs from `uv.lock`, and defaults to HTTP on `0.0.0.0:8000` inside the container.

```bash
docker build -t oura-mcp-server .
```

Sign in once into a persistent volume. A container cannot open your browser, so use `--paste`:

```bash
docker run --rm -it \
  -v oura-session:/home/app/.oura-mcp-server \
  oura-mcp-server oura-mcp-login --paste
```

Then start the server with the same volume:

```bash
docker run -d --name oura-mcp --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v oura-session:/home/app/.oura-mcp-server \
  oura-mcp-server
```

Connect your MCP client to `http://127.0.0.1:8000/mcp` using Streamable HTTP.

> [!IMPORTANT]
> **The session is stored unencrypted in that volume.** A container has no keyring backend, so the session falls back to a file (mode 0600 in a 0700 directory owned by uid 10001). File permissions do not help against anyone who can reach the volume from outside the container: root on the host, the `docker` group, `docker cp`, backups of `/var/lib/docker`. The volume holds your client secret and a refresh token that renews itself, so treat it like a password, and remove it with `docker volume rm oura-session` when you are done.

> [!WARNING]
> This server is single account. Every client that can reach it reads the same person's health data. Put it behind an authenticated HTTPS reverse proxy or a private network before exposing it beyond localhost. Host and Origin checks protect against DNS rebinding; they do not authenticate callers.

To run the image over STDIO instead, add `-e OURA_MCP_TRANSPORT=stdio` and `-i`.

## HTTP Transport Configuration

The server supports MCP Streamable HTTP at `/mcp` when explicitly selected:

```bash
uv run --locked oura-mcp-server --transport http --host 127.0.0.1 --port 8000
```

| Setting                            | CLI flag                        | Environment variable                         | Default outside Docker                         |
| ---------------------------------- | ------------------------------- | -------------------------------------------- | ---------------------------------------------- |
| Transport                          | `--transport`                   | `OURA_MCP_TRANSPORT`                         | `stdio` (`http` aliases `streamable-http`)     |
| Listen address                     | `--host`                        | `OURA_MCP_HOST`                              | `127.0.0.1`                                    |
| Listen port                        | `--port`                        | `OURA_MCP_PORT`                              | `8000`                                         |
| Additional allowed Host headers    | `--allowed-host` (repeatable)   | `OURA_MCP_ALLOWED_HOSTS` (comma-separated)   | None; loopback hosts are always allowed        |
| Additional allowed browser Origins | `--allowed-origin` (repeatable) | `OURA_MCP_ALLOWED_ORIGINS` (comma-separated) | None; HTTP loopback origins are always allowed |

CLI flags override their environment settings.

### Other environment variables

| Variable                                  | Purpose                                                                     |
| ----------------------------------------- | --------------------------------------------------------------------------- |
| `OURA_MCP_SANDBOX`                        | `1` to serve Oura's sample data with no sign in                             |
| `OURA_CLIENT_ID`, `OURA_CLIENT_SECRET`    | Read by `login_setup.py` instead of prompting. Only used at sign in.       |
| `OURA_MCP_REDIRECT_URI`                   | Redirect URI for sign in, if not `http://localhost:8765/callback`           |
| `OURA_MCP_SESSION_DIR`                    | Directory for the file fallback (default `~/.oura-mcp-server`)             |

## Meta Muse

Works great with Meta Muse, Meta's AI assistant, alongside Claude Desktop and
Claude Code. Muse speaks MCP, so it connects the same way as any other client:
give it the stdio launch command from the installation section, or point it at
the Streamable HTTP endpoint if you are running the container.

Using Muse? Ask it to install this server from this repo. Muse can handle the
install and register the server with itself, but signing in to Oura is a step
only you can do: run login_setup.py once and approve access in your browser.
After that, ask Muse how you slept last night to confirm it is working.

Check out Muse, your personal AI agent. Redeem my code in Settings within 48
hours of joining and we'll both get 1 billion Muse tokens.

Code: O63W0U

https://muse.ai/join

## Troubleshooting

**"Not signed in to Oura"**: run `uv run python login_setup.py`, then retry. Restart the client if it still says so.

**401 or 403 mentioning a scope on one tool**: that data type's scope was unticked on Oura's consent screen, or was granted before this server requested it (resilience needs `stress`, which sessions created before it was added lack), or it needs hardware you do not have (SpO2 needs a Gen 3 ring or later). `check_auth_status` lists the granted and missing scopes. Sign in again and grant it.

**"Oura rejected the stored refresh token"**: the session was revoked (for example by removing the app's access in your Oura account). Sign in again.

**`invalid_client` at sign in**: the client ID or secret is wrong. **Redirect URI mismatch**: the application's redirect URI must match the one the script uses character for character, including `http` and the port.

**Port 8765 in use**: free it, or register a different redirect URI and pass `--redirect-uri`, or use `--paste`.

**Today's data is missing**: open the Oura app to sync the ring. See [Data freshness](#data-freshness).

## Technical Details

### Project Structure

```
oura-mcp-server/
├── src/oura_mcp_server/
│   ├── app.py          # FastMCP instance, transport flags, entry point
│   ├── client.py       # httpx client, token refresh, retries, paging
│   ├── oauth.py        # Authorization URL, code exchange, refresh
│   ├── token_store.py  # Keyring storage with 0600 file fallback
│   ├── login.py        # Terminal sign in (also the oura-mcp-login command)
│   ├── params.py       # Shared parameters, date handling, response envelope
│   ├── queries.py      # Fetch and wrap step shared by the list tools
│   ├── server.py       # Re-exports every tool
│   └── tools/          # MCP tools grouped by domain
├── login_setup.py      # Terminal sign in script
├── requirements-lock.txt
└── tests/
```

### Session management

- The session (client ID and secret, access token, refresh token, expiry) is stored in the system keyring, falling back to `~/.oura-mcp-server/session.json` at mode 0600 where no keyring backend exists.
- Access tokens refresh automatically shortly before expiry, and once more if Oura answers 401.
- Oura rotates refresh tokens: each refresh spends the old one. MCP clients often start several copies of a server, so before refreshing the server checks storage for a session another copy already renewed, and if Oura rejects a spent refresh token it looks there again before asking you to sign in.

### Security

- Sign in happens in the terminal. The client secret never appears in a tool argument or in the model's context, and no tool returns token values.
- There is no sign out tool, so nothing the model reads back can talk it into deleting your session. Use `login_setup.py --logout`.
- All tools are read only. The webhook subscription API is not exposed: it needs a public HTTPS endpoint and writes to your application's configuration.
- The server requests every read scope Oura offers. You choose what to actually grant on the consent screen.

## Development

```bash
uv sync --locked --extra dev
uv run --no-sync pytest -q
uv run --no-sync ruff check .
```

After changing dependencies in `pyproject.toml`, run `uv lock` and regenerate the pip pins; CI fails if they disagree:

```bash
uv export --frozen --no-emit-project --no-editable --no-dev \
  --format requirements-txt --output-file requirements-lock.txt
```

## License

MIT

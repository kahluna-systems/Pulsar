# KahLuna Pulsar

Distributed network diagnostics node: FastAPI backend + single-file vanilla-JS dashboard. Part of the **KahLuna Nexus** suite (docs: `D:\NetworkNinjas\ndp-dev\kahluna-docs` — read `product-strategy.md` "Deployment Philosophy" before making identity/tenancy decisions). Runs **standalone** (SQLite, local auth) today; designed to also run **managed** by platform-core later (hub-sync fields already exist in schema/config but are unwired).

## Live test deployment & workflow

- Live node: **http://34.75.134.203:8000** — GCP Ubuntu VM (project `decoded-nebula-493003-b2`, network tag `ndp-dev`), repo cloned at `~/pulsar`, running via `docker compose up -d`.
- **Deploy loop:** edit locally (this repo, Windows) → commit/push to `github.com/kahluna-systems/Pulsar` (direct to `main`) → the user pulls/rebuilds on the VM over SSH (Claude has no SSH access; hand the user exact commands) → verify live in Chrome.
- **Static-only changes need no rebuild**: `node/static/` is bind-mounted read-only into the container, so `git pull` on the VM is live immediately. Backend/Dockerfile changes need `docker compose up -d --build`.
- GCP firewall is target-tag scoped (`ndp-dev`): tcp 3000/5000/8000 (`ndp-allow-dev`), tcp+udp 5201 (`allow-iperf3`). New ports need a new rule with the same tag.
- Verification style: drive the dashboard via the Chrome MCP. Use `javascript_tool` `.click()` for buttons — raw coordinate clicks are flaky through the extension. Take API shortcuts (`fetch` in page context) to assert state.

## Architecture

| Path | What it is |
|------|------------|
| `node/main.py` | All FastAPI endpoints: auth (incl. first-run setup), admin, orgs/circuits, tests + background execution, tokens, MTR SSE stream, ping sessions, speedtest, `/api/stats`, `/downloads/*` |
| `node/config.py` | `NodeConfig`. Precedence: **env > node_config.json > defaults** (`_ENV_MAP`). First run persists generated `node_id`/`secret_key`. Env-pinned fields revert on restart (compose pins `NODE_NAME`, `NODE_ID`, `REQUIRE_AUTH`, `DATABASE_PATH`, `NODE_CONFIG`) — the admin UI flags these. |
| `node/database.py` | Models: `TestResult`, `CustomerToken`, `User`, `Organization`, `Circuit`, `ContinuousPing` + `_migrate_columns()` — SQLite `ALTER TABLE` shim because `create_all` only adds *tables*; add new columns there too. |
| `node/auth.py` | JWT HS256 (secret = config `secret_key`), roles `viewer < engineer < admin`. **`require_role()` is a no-op when `require_auth` is false** — safe to put on any endpoint. `user_from_token()` = SSE query-param auth. |
| `node/runners/*` | Subprocess wrappers per tool. Capability-first: only prepend `sudo` if `shutil.which("sudo")` (containers have none). |
| `node/static/index.html` | The **entire dashboard** (~2300 lines: CSS+HTML+JS). Sidenav shell, auth overlay (monkeypatched `fetch` injects Bearer token; 401 → re-run auth check), one panel per tool, attribution bar, Customers master-detail, admin panel. |
| `node/static/speedtest.html` | Public customer speed-test page (token-tracked). Deliberately unbranded (white-label candidate). |
| `shared/models.py` | Pydantic schemas shared with the future hub. |

## Auth model

- `REQUIRE_AUTH=true` in compose. First boot has no admin → dashboard shows **Create Admin** (`POST /api/auth/setup`, allowed only while no admin exists). No default credentials, ever.
- Access tokens: 60-min JWT in localStorage (`pulsar_token`). No auto-refresh yet.
- Gated `engineer`+: tests, history, orgs/circuits, tokens, ping, MTR stream (`?token=` — EventSource can't send headers). Gated `admin`: `/api/admin/*` (user CRUD with self/last-admin delete guards, node settings). Public: `/speedtest`, `/api/speedtest/*`, `/api/node/info`, `/api/auth/status|login|setup`, `/downloads/*`.

## Customer attribution (Phases 1–2, done)

- `organizations` (customer|partner; nullable `tenant_id`/`site_id` for forward-mapping to platform Tenants/Sites) → `circuits` (label + registered target endpoint).
- "Run tests for:" bar stamps `org_id`/`circuit_id` on **every** test path: `POST /api/tests`, MTR SSE (query params), continuous ping (`_ping_attribution` session map). Circuit selection pre-fills the active panel's target.
- History filters by org; tokens link to orgs; customer speed tests inherit the token's org.

## Roadmap (agreed order)

1. **Phase 3 — customer access links**: org-scoped *revocable* links → scoped portal (run tests **against own circuits only**, view own history). Explicit platform decision: NO node-local customer logins — identity belongs to platform-core; edge customer access is token-based (see kahluna-docs Deployment Philosophy). Portal should reuse the iPerf3 Remote Client Guide pattern.
2. **Phase 4 — per-org reports**: professional printable HTML (reuse the `renderResult` formatters), per org/circuit/date-range.
3. Deferred: f-string 3.12-only syntax portability (`node/main.py` MTR stream area); packet-capture interface dropdown is hardcoded (host networking changed real NIC names).

## Container & capability model — critical gotchas

- Base image `python:3.12-slim`. Code **requires Python 3.12+** (backslash inside f-string expressions). Never downgrade the image.
- **No sudo in the container.** Privileged tools work via file capabilities set in `Dockerfile.node` (requires `libcap2-bin`): ping/traceroute/mtr-packet get `cap_net_raw`, tcpdump also `cap_net_admin`. Compose adds `NET_RAW`/`NET_ADMIN`.
- `network_mode: host` — diagnostics measure from the VM's real vantage point (no docker-bridge fake hop). App binds host `:8000` directly; no port mapping.
- Volume `pulsar_node_data` → `/app/data`: `tests.db` + `node_config.json` (contains `secret_key` — never commit; `.gitignore` covers it). Survives rebuilds. Wiping the volume resets auth to first-run.
- Dockerfile vendors **iperf3 3.21 win64** (URL + SHA-256 pinned as ARGs; build fails on mismatch), served publicly at `/downloads/iperf3-win64.zip` for the one-paste customer setup.
- `Dockerfile.node` has **CRLF line endings** and the Read/Edit tools treat `.node` as binary — patch it with a small Python script (see git history for the pattern).

## Known behaviors (not bugs)

- Traceroute/MTR **from GCP** show `* * *` intermediate hops (Google's Andromeda SDN doesn't emit ICMP time-exceeded); destinations still resolve. Non-GCP vantage points show full paths.
- iperf3 **server-side** `--bidir` JSON reports server→client in `end.sum_sent_bidir_reverse` (`sum_sent` stays 0) — handled in `runners/iperf.py`.
- MTR SSE persistence lives in the generator's `finally` — client disconnect (EventSource close) cancels the generator, which would skip any in-loop save.
- iperf3 server mode = one-off listener, 5-minute window, one client session; the in-app guide documents this workflow.

## Conventions

- Direct commits to `main`; commit messages explain *why*. Every change is verified on the live node before moving on.
- Brand: **KahLuna Pulsar** (never "Network Diagnostic Platform"/"NDP"). Lucide-style inline SVG icons. No emojis in UI. Product naming follows the Nexus space theme.
- UI: single-file dashboard by design for now; reuse existing CSS classes (`.card`, `.status-badge`, `.metric`, `.guide-note`, `.dash-grid`) before inventing new ones.

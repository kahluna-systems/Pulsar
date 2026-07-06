# KahLuna Pulsar

**KahLuna Pulsar** is a distributed network diagnostics suite — a deployable test point that measures connectivity, path, latency, packet loss, and throughput from wherever you stand it up (cloud, datacenter, or the network edge).

Part of the **KahLuna Nexus** suite: Pulsar runs **standalone** as a dedicated probe, or **embeds** as the built-in diagnostics engine inside KahLuna WARP Gateway.

## Features

### Dashboard
- **Overview dashboard** — test counts, success rate, node uptime, tests-by-type breakdown, recent activity
- Collapsible side navigation, authenticated single-page app

### Diagnostic Tools
- **HTTP Speed Test** - Ookla-style speed test with customer-facing portal
- **Traceroute** - Path analysis with ICMP/UDP/TCP options
- **MTR** - Live-streaming traceroute + ping with packet loss statistics
- **DNS Lookup** - Query any record type, check propagation across public DNS
- **TCP Port Check** - Test port connectivity with connection timing
- **SSL Certificate Check** - Validate certificates, check expiry
- **Continuous Ping** - Long-running ping monitor with jitter tracking
- **iPerf3** - Raw bandwidth testing, client or server mode, with a built-in **Remote Client Guide**: per-OS install pointers, copy-paste commands pre-filled with the node's address, and a **one-paste Windows setup** that downloads a version-pinned, checksum-verified iperf3 client straight from the node (`/downloads/iperf3-win64.zip`)
- **Packet Capture** - tcpdump integration for traffic analysis

### Authentication & Administration
- **First-run setup** — no default credentials; the first visit creates the admin account
- JWT-based login; roles: `viewer`, `engineer`, `admin`
- **Admin panel** — user management, password changes, node settings (name, location, feature toggles, limits) editable from the UI

### Customers & Attribution
- **Organizations registry** (customers and partners) with **circuits** carrying registered test endpoints
- **"Run tests for:"** attribution — every test can be stamped with an organization/circuit; selecting a circuit pre-fills its endpoint as the target
- Test History filterable by organization; searchable customer master-detail view

### Customer Portal & Access Links
- Generate **revocable, org-scoped access links** — the customer clicks one URL and lands on their own portal (`/portal`): no account, no install
- Portal customers run tests **against their own registered circuit endpoints only** (server-enforced allowlist + rate limiting), see their own history, and open their own reports
- Speed test handoff from the portal attributes results to the organization automatically

### Reports
- **Printable performance reports** (`/report`) per organization and date range: branded header, throughput / latency & quality / path & connectivity sections, period aggregates (avg/max speeds, RTT, end-to-end loss)
- Available to staff from the Customers pane and to customers through their access link — print or save as PDF from the browser

### Customer Testing
- Generate time-limited, tracked test tokens (linkable to an organization)
- Customer-facing speed test portal (no software required)
- Results automatically associated with customer/circuit/organization
- All tests logged for historical analysis

### Architecture
- **Standalone Mode**: Single node deployment with local SQLite
- **Hub Mode**: Central PostgreSQL database with multiple edge nodes (planned — sync fields present)
- Docker-first deployment with host networking for a true network vantage point

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/kahluna-systems/Pulsar.git pulsar
cd pulsar
docker compose up -d --build
```

Then open `http://<host>:8000` — the first visit prompts you to **create the admin account**.

Notes:
- The compose file uses `network_mode: host` so diagnostics measure from the host's real network position; the app binds `0.0.0.0:8000` directly.
- Data (SQLite DB + generated node config, including the token-signing secret) persists on the `pulsar_node_data` volume across rebuilds.
- Privileged tools (ping/traceroute/MTR/tcpdump) work via file capabilities baked into the image — the app runs as a non-root user with no sudo.

### Python (development)

```bash
git clone https://github.com/kahluna-systems/Pulsar.git pulsar
cd pulsar
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# Run the node (from the repo root, so package imports resolve)
export PYTHONPATH=$(pwd)   # Windows PowerShell: $env:PYTHONPATH = $PWD
python -m uvicorn node.main:app --reload --host 0.0.0.0 --port 8000
```

Requires **Python 3.12+**.

## Access

- **Engineer Dashboard**: `http://<host>:8000` (login required once auth is enabled)
- **Customer Speed Test**: `http://<host>:8000/speedtest` (public)
- **Customer Portal**: `http://<host>:8000/portal?key=...` (via an access link generated per organization)
- **Reports**: `http://<host>:8000/report?org_id=...` (staff) or `?key=...` (customer access link)
- **API docs**: `http://<host>:8000/docs`

## Configuration

Configuration layers, highest precedence first: **environment variables → `node_config.json` → defaults**. On first run the node generates and persists its identity (`node_id`, `secret_key`).

Common environment variables (see `docker-compose.yml`):

| Variable | Purpose |
|----------|---------|
| `NODE_ID` / `NODE_NAME` / `NODE_LOCATION` | Node identity shown in the UI |
| `REQUIRE_AUTH` | Enable login + first-run admin setup (`true` recommended) |
| `DATABASE_PATH` | SQLite path (point at a persistent volume) |
| `NODE_CONFIG` | Where the generated config file lives |
| `HUB_URL` / `HUB_API_KEY` | Reserved for hub mode |

Fields set via environment override the config file on every start; the admin panel flags such fields as environment-pinned. Feature toggles and limits are editable in the **Admin** tab.

## Ports

| Port | Use |
|------|-----|
| 8000/tcp | Dashboard, API, customer speed test |
| 5201/tcp+udp | iPerf3 server mode (open in your cloud/host firewall if used) |

## Security Notes

- Authentication ships enabled with **no default credentials** — the first visitor creates the admin account (do this immediately on a public deployment)
- Customer tokens are time-limited and use-limited
- `node_config.json` contains the token-signing secret — it is gitignored and must stay per-deploy
- Use HTTPS in production (reverse proxy recommended)

## License

Part of the KahLuna ecosystem. All rights reserved.

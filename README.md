# KahLuna Pulsar

**KahLuna Pulsar** is a distributed network diagnostics suite — a deployable test point that measures connectivity, path, latency, packet loss, and throughput from wherever you stand it up (cloud, datacenter, or the network edge).

Part of the **KahLuna Nexus** suite: Pulsar runs **standalone** as a dedicated probe, or **embeds** as the built-in diagnostics engine inside KahLuna WARP Gateway.

## Features

### Diagnostic Tools
- **HTTP Speed Test** - Ookla-style speed test with customer-facing portal
- **Traceroute** - Path analysis with ICMP/UDP/TCP options
- **MTR** - Combined traceroute + ping with packet loss statistics
- **DNS Lookup** - Query any record type, check propagation across public DNS
- **TCP Port Check** - Test port connectivity with connection timing
- **SSL Certificate Check** - Validate certificates, check expiry
- **Continuous Ping** - Long-running ping monitor with jitter tracking
- **iPerf3** - Raw bandwidth testing (requires iperf3 on both ends)
- **Packet Capture** - tcpdump integration for traffic analysis

### Customer Testing
- Generate time-limited, tracked test tokens
- Customer-facing speed test portal (no software required)
- Results automatically associated with customer/circuit ID
- All tests logged for historical analysis

### Architecture
- **Standalone Mode**: Single node deployment with local SQLite
- **Hub Mode**: Central PostgreSQL database with multiple edge nodes
- Docker support for easy deployment

## Quick Start

### Option 1: Python (Development)

```bash
# Clone and setup
cd pulsar
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# Run the node (from the repo root, so package imports resolve)
export PYTHONPATH=$(pwd)   # Windows PowerShell: $env:PYTHONPATH = $PWD
python -m uvicorn node.main:app --reload --host 0.0.0.0 --port 8000
```

### Option 2: Docker

```bash
# Build and run
docker-compose up -d

# Or build manually
docker build -f Dockerfile.node -t pulsar-node .
docker run -p 8000:8000 --cap-add=NET_RAW pulsar-node
```

## Access

- **Engineer Dashboard**: http://localhost:8000
- **Customer Speed Test**: http://localhost:8000/speedtest

## Usage

### For Engineers

1. Open the dashboard at http://localhost:8000
2. Select a diagnostic tool from the tabs
3. Enter target information and run the test
4. View results in the Test History

### For Customer Testing

1. Go to "Customer Tokens" tab
2. Enter customer/circuit ID and create a token
3. Copy the generated link and send to customer
4. Customer opens link and runs speed test
5. Results appear in your Test History with customer ID

## Configuration

Create `node_config.json` to customize:

```json
{
  "node_id": "edge-node-charlotte-01",
  "node_name": "Charlotte Edge Node",
  "location": "Charlotte, NC",
  "require_auth": false,
  "features": {
    "speedtest": true,
    "traceroute": true,
    "mtr": true,
    "dns": true,
    "tcp_check": true,
    "ssl_check": true,
    "iperf": true,
    "packet_capture": true,
    "continuous_ping": true
  }
}
```

## System Requirements

### Required
- Python 3.8+
- Network access to targets

### Optional (for full functionality)
- `iperf3` - for iPerf bandwidth tests
- `tcpdump` - for packet capture (requires root/sudo)
- `mtr` - for MTR diagnostics (falls back to simulated if not available)
- `traceroute` - for traceroute (uses system traceroute/tracert)

### Install on Ubuntu/Debian
```bash
sudo apt-get install iperf3 tcpdump mtr-tiny traceroute dnsutils
```

### Install on Windows
- iPerf3: Download from https://iperf.fr/iperf-download.php
- Other tools have Windows alternatives or fallbacks built-in

## API Reference

### Test Endpoints
- `POST /api/tests` - Create and run a test
- `GET /api/tests` - List recent tests
- `GET /api/tests/{id}` - Get test details

### Speed Test Endpoints
- `GET /api/speedtest/ping` - Latency measurement
- `GET /api/speedtest/download` - Download data
- `POST /api/speedtest/upload` - Upload data
- `POST /api/speedtest/result` - Save customer result

### Token Endpoints
- `POST /api/tokens` - Create customer token
- `GET /api/tokens` - List tokens
- `DELETE /api/tokens/{id}` - Delete token

### Continuous Ping
- `POST /api/ping/start` - Start ping session
- `GET /api/ping/{id}` - Get session status
- `POST /api/ping/{id}/stop` - Stop session

## Security Notes

- Customer tokens are time-limited and use-limited
- Packet capture requires elevated privileges
- Consider enabling authentication for production (`require_auth: true`)
- Use HTTPS in production (reverse proxy recommended)

## License

Part of the KahLuna ecosystem. All rights reserved.

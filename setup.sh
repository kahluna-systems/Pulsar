#!/bin/bash
# KahLuna Pulsar - Server Setup
# Run with: sudo bash setup.sh

set -e

echo "=== Installing system dependencies ==="
apt-get update
apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    iperf3 \
    tcpdump \
    traceroute \
    mtr-tiny \
    dnsutils \
    iputils-ping \
    nmap \
    curl

echo "=== Setting up Python virtual environment ==="
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt

echo "=== Setup complete ==="
echo "To start the server:"
echo "  source venv/bin/activate"
echo "  export PYTHONPATH=$(pwd)"
echo "  uvicorn node.main:app --host 0.0.0.0 --port 8000 --reload"

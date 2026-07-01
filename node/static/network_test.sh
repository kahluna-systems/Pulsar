#!/bin/bash
#
# KahLuna Pulsar - Network Test Client for macOS/Linux
# =====================================================
# A lightweight, transparent network testing tool.
#
# This script:
# - Tests connectivity to a diagnostic server
# - Measures latency, download speed, and upload speed
# - Optionally uploads results for your support team
# - Can self-delete after completion
#
# No data collected beyond what's shown on screen.
# Source code fully visible and auditable.
#
# Usage: bash network_test.sh [server_url]
#

SERVER_URL="${1:-{{SERVER_URL}}}"
VERSION="1.0.0"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Check for required tools
check_requirements() {
    if ! command -v curl &> /dev/null; then
        echo -e "${RED}Error: curl is required but not installed.${NC}"
        echo "Install with: sudo apt install curl (Debian/Ubuntu) or brew install curl (macOS)"
        exit 1
    fi
}

print_banner() {
    clear
    echo ""
    echo "============================================================"
    echo -e "${BOLD}  KAHLUNA PULSAR - NETWORK TEST${NC}"
    echo "============================================================"
    echo ""
    echo "Version: $VERSION"
    echo "Server:  $SERVER_URL"
    echo "Time:    $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""
    echo "This tool will:"
    echo "  1. Test connectivity to the diagnostic server"
    echo "  2. Measure network latency (ping)"
    echo "  3. Test download speed"
    echo "  4. Test upload speed"
    echo "  5. Display results"
    echo ""
    echo "------------------------------------------------------------"
    read -p "Press Enter to start the test..."
    echo ""
}

test_connectivity() {
    echo -e "${CYAN}[1/5] Testing connectivity...${NC}"
    
    response=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 10 -k "$SERVER_URL/api/speedtest/ping" 2>/dev/null)
    
    if [ "$response" = "200" ]; then
        echo -e "      ${GREEN}✓ Server is reachable${NC}"
        return 0
    else
        echo -e "      ${RED}✗ Connection failed (HTTP $response)${NC}"
        return 1
    fi
}

test_latency() {
    local count=${1:-10}
    echo -e "${CYAN}[2/5] Measuring latency ($count samples)...${NC}"
    
    local times=()
    local total=0
    local successful=0
    
    for ((i=1; i<=count; i++)); do
        start=$(date +%s%N)
        curl -s -o /dev/null -k "$SERVER_URL/api/speedtest/ping" 2>/dev/null
        end=$(date +%s%N)
        
        # Calculate milliseconds
        elapsed=$(( (end - start) / 1000000 ))
        times+=($elapsed)
        total=$((total + elapsed))
        successful=$((successful + 1))
        
        printf "\r      Sample %d/%d: %dms" $i $count $elapsed
    done
    echo ""
    
    if [ $successful -gt 0 ]; then
        avg=$((total / successful))
        
        # Find min and max
        min=${times[0]}
        max=${times[0]}
        for t in "${times[@]}"; do
            ((t < min)) && min=$t
            ((t > max)) && max=$t
        done
        
        echo -e "      ${GREEN}✓ Latency: ${avg}ms avg (min: ${min}ms, max: ${max}ms)${NC}"
        
        LATENCY_MIN=$min
        LATENCY_AVG=$avg
        LATENCY_MAX=$max
        return 0
    else
        echo -e "      ${RED}✗ Could not measure latency${NC}"
        return 1
    fi
}

test_download() {
    local duration=${1:-10}
    echo -e "${CYAN}[3/5] Testing download speed (${duration}s)...${NC}"
    
    local total_bytes=0
    local start_time=$(date +%s)
    local end_time=$((start_time + duration))
    
    while [ $(date +%s) -lt $end_time ]; do
        # Download 1MB chunk
        bytes=$(curl -s -k "$SERVER_URL/api/speedtest/download?size=1048576" 2>/dev/null | wc -c)
        total_bytes=$((total_bytes + bytes))
        
        elapsed=$(($(date +%s) - start_time))
        if [ $elapsed -gt 0 ]; then
            current_mbps=$(echo "scale=1; ($total_bytes * 8) / ($elapsed * 1000000)" | bc 2>/dev/null || echo "0")
            downloaded_mb=$(echo "scale=1; $total_bytes / 1048576" | bc 2>/dev/null || echo "0")
            printf "\r      Downloaded: %s MB | Speed: %s Mbps" "$downloaded_mb" "$current_mbps"
        fi
    done
    echo ""
    
    elapsed=$(($(date +%s) - start_time))
    if [ $elapsed -gt 0 ]; then
        mbps=$(echo "scale=2; ($total_bytes * 8) / ($elapsed * 1000000)" | bc 2>/dev/null || echo "0")
        downloaded_mb=$(echo "scale=1; $total_bytes / 1048576" | bc 2>/dev/null || echo "0")
        
        echo -e "      ${GREEN}✓ Download: ${mbps} Mbps (${downloaded_mb} MB in ${elapsed}s)${NC}"
        
        DOWNLOAD_MBPS=$mbps
        DOWNLOAD_BYTES=$total_bytes
        return 0
    fi
    return 1
}

test_upload() {
    local duration=${1:-10}
    echo -e "${CYAN}[4/5] Testing upload speed (${duration}s)...${NC}"
    
    # Generate 256KB of random data
    local test_data=$(head -c 262144 /dev/urandom | base64)
    local chunk_size=262144
    
    local total_bytes=0
    local start_time=$(date +%s)
    local end_time=$((start_time + duration))
    
    while [ $(date +%s) -lt $end_time ]; do
        # Upload chunk
        response=$(curl -s -k -X POST -H "Content-Type: application/octet-stream" \
            --data-binary "@-" "$SERVER_URL/api/speedtest/upload" <<< "$test_data" 2>/dev/null)
        
        if [ -n "$response" ]; then
            total_bytes=$((total_bytes + chunk_size))
        fi
        
        elapsed=$(($(date +%s) - start_time))
        if [ $elapsed -gt 0 ]; then
            current_mbps=$(echo "scale=1; ($total_bytes * 8) / ($elapsed * 1000000)" | bc 2>/dev/null || echo "0")
            uploaded_mb=$(echo "scale=1; $total_bytes / 1048576" | bc 2>/dev/null || echo "0")
            printf "\r      Uploaded: %s MB | Speed: %s Mbps" "$uploaded_mb" "$current_mbps"
        fi
    done
    echo ""
    
    elapsed=$(($(date +%s) - start_time))
    if [ $elapsed -gt 0 ]; then
        mbps=$(echo "scale=2; ($total_bytes * 8) / ($elapsed * 1000000)" | bc 2>/dev/null || echo "0")
        uploaded_mb=$(echo "scale=1; $total_bytes / 1048576" | bc 2>/dev/null || echo "0")
        
        echo -e "      ${GREEN}✓ Upload: ${mbps} Mbps (${uploaded_mb} MB in ${elapsed}s)${NC}"
        
        UPLOAD_MBPS=$mbps
        UPLOAD_BYTES=$total_bytes
        return 0
    fi
    return 1
}

show_results() {
    echo ""
    echo "============================================================"
    echo -e "${BOLD}  TEST RESULTS${NC}"
    echo "============================================================"
    echo ""
    echo "  Latency:   ${LATENCY_AVG} ms"
    echo "             (min: ${LATENCY_MIN} ms, max: ${LATENCY_MAX} ms)"
    echo ""
    echo "  Download:  ${DOWNLOAD_MBPS} Mbps"
    echo ""
    echo "  Upload:    ${UPLOAD_MBPS} Mbps"
    echo ""
    echo "  Tested:    $(date '+%Y-%m-%d %H:%M:%S')"
    echo "  Server:    $SERVER_URL"
    echo ""
    echo "============================================================"
}

upload_results() {
    echo ""
    echo -e "${CYAN}[5/5] Upload results to support team?${NC}"
    
    read -p "      Enter ticket/circuit ID (or press Enter to skip): " customer_id
    read -p "      Upload results? (Y/n): " choice
    
    if [ "$choice" = "n" ] || [ "$choice" = "N" ]; then
        echo "      Results not uploaded."
        return
    fi
    
    # Build JSON payload
    local payload=$(cat <<EOF
{
    "ping_ms": $LATENCY_AVG,
    "ping_min": $LATENCY_MIN,
    "ping_max": $LATENCY_MAX,
    "download_mbps": $DOWNLOAD_MBPS,
    "upload_mbps": $UPLOAD_MBPS,
    "customer_id": $([ -n "$customer_id" ] && echo "\"$customer_id\"" || echo "null"),
    "client_type": "bash_client",
    "client_version": "$VERSION",
    "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
)
    
    response=$(curl -s -o /dev/null -w "%{http_code}" -k -X POST \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "$SERVER_URL/api/speedtest/result" 2>/dev/null)
    
    if [ "$response" = "200" ]; then
        echo -e "      ${GREEN}✓ Results uploaded successfully!${NC}"
    else
        echo -e "      ${RED}✗ Upload failed (HTTP $response)${NC}"
    fi
}

cleanup() {
    echo ""
    echo "------------------------------------------------------------"
    echo "Test complete!"
    echo ""
    
    read -p "Delete this test script from your computer? (y/N): " choice
    
    if [ "$choice" = "y" ] || [ "$choice" = "Y" ]; then
        script_path="$0"
        echo "Deleting: $script_path"
        rm -f "$script_path" 2>/dev/null
        echo -e "${GREEN}✓ Script deleted.${NC}"
    else
        echo "Script kept. You can delete it manually when done."
    fi
    
    echo ""
    echo "Thank you for using KahLuna Pulsar!"
}

# Main
main() {
    # Validate server URL
    if [ "$SERVER_URL" = "{{SERVER_URL}}" ] || [ -z "$SERVER_URL" ]; then
        echo -e "${RED}Error: No server URL configured.${NC}"
        echo "Usage: bash network_test.sh http://server:8000"
        exit 1
    fi
    
    # Remove trailing slash
    SERVER_URL="${SERVER_URL%/}"
    
    check_requirements
    print_banner
    
    if ! test_connectivity; then
        echo -e "\n${RED}Cannot reach server. Please check your connection.${NC}"
        read -p "Press Enter to exit..."
        exit 1
    fi
    
    test_latency
    test_download
    test_upload
    
    show_results
    upload_results
    cleanup
}

main

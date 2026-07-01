#!/usr/bin/env python3
"""
KahLuna Pulsar - Network Test Client
====================================
A lightweight, transparent network testing tool.

This script:
- Tests connectivity to a diagnostic server
- Measures latency, download speed, and upload speed
- Optionally uploads results for your support team to review
- Can self-delete after completion

No data is collected beyond what's shown on screen.
Source code is fully visible and auditable.

Usage: python network_test.py [server_url]
"""

import sys
import time
import socket
import urllib.request
import urllib.error
import json
import os
import ssl
from datetime import datetime

# Configuration - set by the download page or passed as argument
DEFAULT_SERVER = "{{SERVER_URL}}"
VERSION = "1.0.0"

# ANSI colors for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'

def color(text, c):
    """Apply color if terminal supports it."""
    if sys.platform == 'win32':
        return text  # Windows cmd doesn't support ANSI by default
    return f"{c}{text}{Colors.END}"

def print_banner():
    """Display welcome banner."""
    print("\n" + "=" * 60)
    print(color("  KAHLUNA PULSAR - NETWORK TEST", Colors.BOLD))
    print("=" * 60)
    print(f"\nVersion: {VERSION}")
    print(f"Server:  {DEFAULT_SERVER}")
    print(f"Time:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\nThis tool will:")
    print("  1. Test connectivity to the diagnostic server")
    print("  2. Measure network latency (ping)")
    print("  3. Test download speed")
    print("  4. Test upload speed")
    print("  5. Display results")
    print("\n" + "-" * 60)
    input("Press Enter to start the test...")
    print()

def test_connectivity(server_url):
    """Test basic connectivity to server."""
    print(color("[1/5] Testing connectivity...", Colors.CYAN))
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        req = urllib.request.Request(f"{server_url}/api/speedtest/ping")
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            if response.status == 200:
                print(color("      ✓ Server is reachable", Colors.GREEN))
                return True
    except Exception as e:
        print(color(f"      ✗ Connection failed: {e}", Colors.RED))
        return False

def test_latency(server_url, count=10):
    """Measure latency to server."""
    print(color(f"[2/5] Measuring latency ({count} samples)...", Colors.CYAN))
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    times = []
    for i in range(count):
        try:
            start = time.time()
            req = urllib.request.Request(f"{server_url}/api/speedtest/ping")
            with urllib.request.urlopen(req, timeout=5, context=ctx) as response:
                response.read()
            elapsed = (time.time() - start) * 1000
            times.append(elapsed)
            sys.stdout.write(f"\r      Sample {i+1}/{count}: {elapsed:.1f}ms")
            sys.stdout.flush()
        except:
            pass
    
    print()
    
    if times:
        result = {
            'min': round(min(times), 2),
            'avg': round(sum(times) / len(times), 2),
            'max': round(max(times), 2),
            'samples': len(times)
        }
        print(color(f"      ✓ Latency: {result['avg']}ms avg (min: {result['min']}ms, max: {result['max']}ms)", Colors.GREEN))
        return result
    else:
        print(color("      ✗ Could not measure latency", Colors.RED))
        return None

def test_download(server_url, duration=10):
    """Test download speed."""
    print(color(f"[3/5] Testing download speed ({duration}s)...", Colors.CYAN))
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    total_bytes = 0
    start_time = time.time()
    end_time = start_time + duration
    
    while time.time() < end_time:
        try:
            req = urllib.request.Request(f"{server_url}/api/speedtest/download?size=1048576")
            with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
                data = response.read()
                total_bytes += len(data)
            
            elapsed = time.time() - start_time
            current_mbps = (total_bytes * 8) / (elapsed * 1000000)
            sys.stdout.write(f"\r      Downloaded: {total_bytes / 1024 / 1024:.1f} MB | Speed: {current_mbps:.1f} Mbps")
            sys.stdout.flush()
        except:
            pass
    
    print()
    
    elapsed = time.time() - start_time
    mbps = round((total_bytes * 8) / (elapsed * 1000000), 2)
    print(color(f"      ✓ Download: {mbps} Mbps ({total_bytes / 1024 / 1024:.1f} MB in {elapsed:.1f}s)", Colors.GREEN))
    
    return {'mbps': mbps, 'bytes': total_bytes, 'duration': round(elapsed, 2)}

def test_upload(server_url, duration=10):
    """Test upload speed."""
    print(color(f"[4/5] Testing upload speed ({duration}s)...", Colors.CYAN))
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    # Generate test data (256KB chunks)
    test_data = os.urandom(262144)
    
    total_bytes = 0
    start_time = time.time()
    end_time = start_time + duration
    
    while time.time() < end_time:
        try:
            req = urllib.request.Request(
                f"{server_url}/api/speedtest/upload",
                data=test_data,
                headers={'Content-Type': 'application/octet-stream'}
            )
            with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
                response.read()
                total_bytes += len(test_data)
            
            elapsed = time.time() - start_time
            current_mbps = (total_bytes * 8) / (elapsed * 1000000)
            sys.stdout.write(f"\r      Uploaded: {total_bytes / 1024 / 1024:.1f} MB | Speed: {current_mbps:.1f} Mbps")
            sys.stdout.flush()
        except:
            pass
    
    print()
    
    elapsed = time.time() - start_time
    mbps = round((total_bytes * 8) / (elapsed * 1000000), 2)
    print(color(f"      ✓ Upload: {mbps} Mbps ({total_bytes / 1024 / 1024:.1f} MB in {elapsed:.1f}s)", Colors.GREEN))
    
    return {'mbps': mbps, 'bytes': total_bytes, 'duration': round(elapsed, 2)}

def display_results(results):
    """Display final results."""
    print("\n" + "=" * 60)
    print(color("  TEST RESULTS", Colors.BOLD))
    print("=" * 60)
    
    if results.get('latency'):
        print(f"\n  Latency:   {results['latency']['avg']} ms")
        print(f"             (min: {results['latency']['min']} ms, max: {results['latency']['max']} ms)")
    
    if results.get('download'):
        print(f"\n  Download:  {results['download']['mbps']} Mbps")
    
    if results.get('upload'):
        print(f"\n  Upload:    {results['upload']['mbps']} Mbps")
    
    print(f"\n  Tested:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Server:    {DEFAULT_SERVER}")
    print("\n" + "=" * 60)
    
    return results

def upload_results(server_url, results):
    """Optionally upload results to server."""
    print("\n" + color("[5/5] Upload results to support team?", Colors.CYAN))
    
    # Get optional customer ID
    customer_id = input("      Enter ticket/circuit ID (or press Enter to skip): ").strip()
    
    choice = input("      Upload results? (Y/n): ").strip().lower()
    if choice == 'n':
        print("      Results not uploaded.")
        return
    
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        payload = {
            'ping_ms': results.get('latency', {}).get('avg'),
            'ping_min': results.get('latency', {}).get('min'),
            'ping_max': results.get('latency', {}).get('max'),
            'download_mbps': results.get('download', {}).get('mbps'),
            'upload_mbps': results.get('upload', {}).get('mbps'),
            'customer_id': customer_id or None,
            'client_type': 'python_client',
            'client_version': VERSION,
            'timestamp': datetime.now().isoformat()
        }
        
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            f"{server_url}/api/speedtest/result",
            data=data,
            headers={'Content-Type': 'application/json'}
        )
        
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            if response.status == 200:
                print(color("      ✓ Results uploaded successfully!", Colors.GREEN))
            else:
                print(color("      ✗ Upload failed", Colors.RED))
    except Exception as e:
        print(color(f"      ✗ Upload failed: {e}", Colors.RED))

def cleanup():
    """Offer to delete this script."""
    print("\n" + "-" * 60)
    print("Test complete!")
    
    choice = input("\nDelete this test script from your computer? (y/N): ").strip().lower()
    if choice == 'y':
        try:
            script_path = os.path.abspath(__file__)
            print(f"Deleting: {script_path}")
            os.remove(script_path)
            print(color("✓ Script deleted.", Colors.GREEN))
        except Exception as e:
            print(color(f"Could not delete script: {e}", Colors.YELLOW))
            print(f"You can manually delete: {os.path.abspath(__file__)}")
    else:
        print("Script kept. You can delete it manually when done.")
    
    print("\nThank you for using KahLuna Pulsar!")

def main():
    """Main entry point."""
    global DEFAULT_SERVER
    
    # Allow server URL override via command line
    if len(sys.argv) > 1:
        DEFAULT_SERVER = sys.argv[1]
    
    # Validate server URL
    if DEFAULT_SERVER == "{{SERVER_URL}}" or not DEFAULT_SERVER:
        print(color("Error: No server URL configured.", Colors.RED))
        print("Usage: python network_test.py http://server:8000")
        sys.exit(1)
    
    # Ensure URL doesn't have trailing slash
    DEFAULT_SERVER = DEFAULT_SERVER.rstrip('/')
    
    print_banner()
    
    results = {}
    
    # Run tests
    if not test_connectivity(DEFAULT_SERVER):
        print(color("\nCannot reach server. Please check your connection.", Colors.RED))
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    results['latency'] = test_latency(DEFAULT_SERVER)
    results['download'] = test_download(DEFAULT_SERVER)
    results['upload'] = test_upload(DEFAULT_SERVER)
    
    # Show results
    display_results(results)
    
    # Upload results
    upload_results(DEFAULT_SERVER, results)
    
    # Cleanup
    cleanup()

if __name__ == "__main__":
    main()

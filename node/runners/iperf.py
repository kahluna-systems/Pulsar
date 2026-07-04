"""iPerf3 diagnostic runner."""
import subprocess
import json
from typing import Optional


class IperfRunner:
    """Run iPerf3 bandwidth tests."""
    
    def run(self, config: dict) -> dict:
        """Execute iPerf3 test."""
        mode = config.get("mode", "client")
        
        if mode == "server":
            return self._run_server(config)
        else:
            return self._run_client(config)
    
    def _run_client(self, config: dict) -> dict:
        """Run iPerf3 in client mode."""
        server = config.get("server")
        port = config.get("port", 5201)
        protocol = config.get("protocol", "tcp")
        duration = config.get("duration", 10)
        parallel = config.get("parallel", 1)
        bandwidth = config.get("bandwidth")
        window = config.get("window")
        
        if not server:
            return {"error": "Server address is required"}
        
        cmd = ["iperf3", "-c", server, "-p", str(port)]
        cmd.extend(["-t", str(duration)])
        
        if parallel > 1:
            cmd.extend(["-P", str(parallel)])
        
        if protocol == "udp":
            cmd.append("-u")
            if bandwidth:
                cmd.extend(["-b", bandwidth])
        
        if window:
            cmd.extend(["-w", window])
        
        # JSON output
        cmd.append("-J")
        
        timeout = duration + 30
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            if result.returncode == 0:
                return self._parse_client_result(result.stdout, config)
            else:
                # iperf3 -J reports the real error as JSON on stdout even when it
                # exits non-zero (e.g. "the server is busy running a test").
                err = (result.stderr or "").strip()
                if not err and result.stdout:
                    try:
                        err = json.loads(result.stdout).get("error", "")
                    except json.JSONDecodeError:
                        pass
                return {
                    "error": err or "iPerf3 failed",
                    "returncode": result.returncode
                }
                
        except subprocess.TimeoutExpired:
            return {"error": "iPerf3 test timed out"}
        except FileNotFoundError:
            return {"error": "iPerf3 is not installed"}
        except Exception as e:
            return {"error": str(e)}
    
    def _run_server(self, config: dict) -> dict:
        """Run iPerf3 in server mode (one-off)."""
        port = config.get("port", 5201)
        one_off = config.get("one_off", True)
        
        cmd = ["iperf3", "-s", "-p", str(port)]
        
        if one_off:
            cmd.append("-1")  # One-off mode
        
        cmd.append("-J")
        
        timeout = 300  # 5 minutes max for server mode
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            return self._parse_server_result(result, port)

        except subprocess.TimeoutExpired:
            return {"error": "Server mode timed out (no client connected)"}
        except FileNotFoundError:
            return {"error": "iPerf3 is not installed"}
        except Exception as e:
            return {"error": str(e)}
    
    def _parse_server_result(self, result, port: int) -> dict:
        """Parse iperf3 -s -J output into a readable summary (mirrors client parsing)."""
        parsed = None
        try:
            parsed = json.loads(result.stdout) if result.stdout else None
        except json.JSONDecodeError:
            parsed = None

        if parsed and parsed.get("error"):
            return {"mode": "server", "port": port, "error": parsed["error"]}

        if parsed and "end" in parsed:
            start = parsed.get("start", {})
            end = parsed.get("end", {})
            connected = (start.get("connected") or [{}])[0]
            # Server perspective: sum_received = client -> server (client upload),
            # sum_sent = server -> client (only nonzero for -R / --bidir sessions).
            sum_recv = end.get("sum_received") or end.get("sum") or {}
            sum_sent = end.get("sum_sent") or {}
            return {
                "mode": "server",
                "port": port,
                "client": connected.get("remote_host"),
                "duration": round(sum_recv.get("seconds") or 0, 1),
                "received_mbps": round(sum_recv.get("bits_per_second", 0) / 1_000_000, 2),
                "sent_mbps": round(sum_sent.get("bits_per_second", 0) / 1_000_000, 2),
                "received_bytes": sum_recv.get("bytes", 0),
                "sent_bytes": sum_sent.get("bytes", 0),
                "iperf_version": start.get("version"),
                "raw": parsed,
            }

        # Fell through: no JSON we understand — keep the raw output for debugging
        return {
            "mode": "server",
            "port": port,
            "error": "No client connected" if result.returncode != 0 else None,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    def _parse_client_result(self, output: str, config: dict) -> dict:
        """Parse iPerf3 JSON output into structured result."""
        try:
            data = json.loads(output)
            
            result = {
                "mode": "client",
                "server": config.get("server"),
                "port": config.get("port", 5201),
                "protocol": config.get("protocol", "tcp"),
                "duration": config.get("duration", 10),
                "parallel": config.get("parallel", 1)
            }
            
            # Extract end summary
            end = data.get("end", {})
            
            if config.get("protocol") == "udp":
                # UDP results
                sum_data = end.get("sum", {})
                result["bytes"] = sum_data.get("bytes", 0)
                result["bits_per_second"] = sum_data.get("bits_per_second", 0)
                result["jitter_ms"] = sum_data.get("jitter_ms")
                result["lost_packets"] = sum_data.get("lost_packets", 0)
                result["packets"] = sum_data.get("packets", 0)
                result["lost_percent"] = sum_data.get("lost_percent", 0)
            else:
                # TCP results
                sum_sent = end.get("sum_sent", {})
                sum_received = end.get("sum_received", {})
                
                result["sent"] = {
                    "bytes": sum_sent.get("bytes", 0),
                    "bits_per_second": sum_sent.get("bits_per_second", 0),
                    "retransmits": sum_sent.get("retransmits", 0)
                }
                
                result["received"] = {
                    "bytes": sum_received.get("bytes", 0),
                    "bits_per_second": sum_received.get("bits_per_second", 0)
                }
                
                # Calculate Mbps for easy display
                result["download_mbps"] = round(sum_received.get("bits_per_second", 0) / 1000000, 2)
                result["upload_mbps"] = round(sum_sent.get("bits_per_second", 0) / 1000000, 2)
            
            # Include raw data for detailed analysis
            result["raw"] = data
            
            return result
            
        except json.JSONDecodeError:
            return {
                "error": "Failed to parse iPerf3 output",
                "raw_output": output
            }

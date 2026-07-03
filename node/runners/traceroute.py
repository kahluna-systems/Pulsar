"""Traceroute diagnostic runner."""
import subprocess
import re
import socket
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class TracerouteHop:
    hop: int
    ip: Optional[str]
    hostname: Optional[str]
    rtt_ms: Optional[float]
    timeout: bool = False


@dataclass
class TracerouteResult:
    target: str
    resolved_ip: Optional[str]
    hops: List[TracerouteHop]
    completed: bool
    error: Optional[str] = None


class TracerouteRunner:
    """Run traceroute diagnostics."""
    
    def run(self, config: dict) -> dict:
        """Execute traceroute to target."""
        target = config.get("target")
        protocol = config.get("protocol", "icmp")
        max_hops = config.get("max_hops", 30)
        timeout = config.get("timeout", 2.0)
        resolve_hostnames = config.get("resolve_hostnames", True)
        
        if not target:
            return {"error": "Target is required"}
        
        # Resolve target IP
        resolved_ip = None
        try:
            resolved_ip = socket.gethostbyname(target)
        except socket.gaierror:
            pass
        
        # Build command based on OS
        import platform
        system = platform.system().lower()
        
        if system == "windows":
            cmd = self._build_windows_cmd(target, max_hops, timeout)
        else:
            cmd = self._build_unix_cmd(target, protocol, max_hops, timeout, resolve_hostnames)
        
        # ICMP and TCP traceroute need elevated privileges. Prefer file
        # capabilities (setcap cap_net_raw on the traceroute binary); only fall
        # back to sudo when it actually exists (bare-metal with a sudoers rule).
        # A capability-granted container has no sudo, so run the binary directly.
        import os, shutil
        needs_priv = protocol in ("icmp", "tcp") and (
            os.geteuid() != 0 if hasattr(os, 'geteuid') else False
        )
        if needs_priv and shutil.which("sudo"):
            cmd = ["sudo", "-n"] + cmd
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=max_hops * timeout + 10
            )
            
            # Check for sudo failure
            if result.returncode != 0 and ("sudo" in result.stderr.lower() or "password" in result.stderr.lower()):
                return {
                    "target": target,
                    "resolved_ip": resolved_ip,
                    "hops": [],
                    "completed": False,
                    "error": f"ICMP/TCP traceroute requires root. Configure passwordless sudo or use UDP protocol."
                }
            
            hops = self._parse_output(result.stdout, system)
            
            return {
                "target": target,
                "resolved_ip": resolved_ip,
                "hops": [vars(h) for h in hops],
                "completed": len(hops) > 0 and (hops[-1].ip == resolved_ip if resolved_ip else True),
                "raw_output": result.stdout
            }
            
        except subprocess.TimeoutExpired:
            return {
                "target": target,
                "resolved_ip": resolved_ip,
                "hops": [],
                "completed": False,
                "error": "Traceroute timed out"
            }
        except Exception as e:
            return {
                "target": target,
                "resolved_ip": resolved_ip,
                "hops": [],
                "completed": False,
                "error": str(e)
            }
    
    def _build_unix_cmd(self, target: str, protocol: str, max_hops: int, 
                        timeout: float, resolve: bool) -> list:
        """Build traceroute command for Unix systems."""
        cmd = ["traceroute"]
        
        if protocol == "icmp":
            cmd.append("-I")
        elif protocol == "tcp":
            cmd.append("-T")
        # UDP is default
        
        cmd.extend(["-m", str(max_hops)])
        cmd.extend(["-w", str(timeout)])
        
        if not resolve:
            cmd.append("-n")
        
        cmd.append(target)
        return cmd
    
    def _build_windows_cmd(self, target: str, max_hops: int, timeout: float) -> list:
        """Build tracert command for Windows."""
        cmd = ["tracert"]
        cmd.extend(["-h", str(max_hops)])
        cmd.extend(["-w", str(int(timeout * 1000))])  # Windows uses milliseconds
        cmd.append(target)
        return cmd
    
    def _parse_output(self, output: str, system: str) -> List[TracerouteHop]:
        """Parse traceroute output into structured hops."""
        hops = []
        lines = output.strip().split('\n')
        
        for line in lines:
            # Skip header lines
            if not line.strip() or 'traceroute' in line.lower() or 'tracing' in line.lower():
                continue
            if 'hops' in line.lower() or 'over' in line.lower():
                continue
            
            hop = self._parse_hop_line(line, system)
            if hop:
                hops.append(hop)
        
        return hops
    
    def _parse_hop_line(self, line: str, system: str) -> Optional[TracerouteHop]:
        """Parse a single hop line."""
        # Match hop number at start
        hop_match = re.match(r'^\s*(\d+)', line)
        if not hop_match:
            return None
        
        hop_num = int(hop_match.group(1))
        
        # Check for timeout
        if '* * *' in line or 'Request timed out' in line:
            return TracerouteHop(hop=hop_num, ip=None, hostname=None, rtt_ms=None, timeout=True)
        
        # Extract IP address
        ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', line)
        ip = ip_match.group(1) if ip_match else None
        
        # Extract hostname (text before IP in parentheses, or the IP itself)
        hostname = None
        hostname_match = re.search(r'([a-zA-Z][a-zA-Z0-9\-\.]+)\s+\(', line)
        if hostname_match:
            hostname = hostname_match.group(1)
        
        # Extract RTT (first numeric value with ms)
        rtt_match = re.search(r'(\d+\.?\d*)\s*ms', line)
        rtt = float(rtt_match.group(1)) if rtt_match else None
        
        return TracerouteHop(hop=hop_num, ip=ip, hostname=hostname, rtt_ms=rtt, timeout=False)

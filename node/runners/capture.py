"""Packet capture diagnostic runner."""
import subprocess
import os
import re
from datetime import datetime
from typing import Optional


class PacketCaptureRunner:
    """Run tcpdump packet captures."""
    
    # Allowed filter tokens to prevent command injection
    ALLOWED_FILTER_PATTERN = r'^[a-zA-Z0-9\s\.\:\-\/\(\)and or not host port net src dst tcp udp icmp arp proto len greater less]+$'
    
    def __init__(self, capture_dir: str = "/tmp"):
        self.capture_dir = capture_dir
    
    def run(self, config: dict) -> dict:
        """Execute packet capture."""
        interface = config.get("interface", "any")
        filter_expr = config.get("filter")
        count = config.get("count")
        duration = config.get("duration")
        snaplen = config.get("snaplen", 65535)
        promiscuous = config.get("promiscuous", True)
        
        # Validate filter
        if filter_expr:
            filter_expr = self._sanitize_filter(filter_expr)
            if filter_expr is None:
                return {"error": "Invalid filter expression"}
        
        # Generate output filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = os.path.join(self.capture_dir, f"capture_{timestamp}.pcap")
        
        # Build command
        cmd = ["tcpdump", "-i", interface, "-w", output_file]
        
        # Add snaplen
        cmd.extend(["-s", str(snaplen)])
        
        # Promiscuous mode
        if not promiscuous:
            cmd.append("-p")
        
        # Determine timeout
        if count:
            cmd.extend(["-c", str(count)])
            timeout = 120  # 2 minutes max for count-based
        elif duration:
            timeout = duration + 10
        else:
            timeout = 60  # Default 1 minute
        
        # Add filter
        if filter_expr:
            cmd.append(filter_expr)
        
        # Prefer file capabilities (setcap on tcpdump). Only prepend sudo when it
        # actually exists — a capability-granted container has no sudo, and blindly
        # prepending it crashes with a misleading "tcpdump is not installed".
        import shutil
        needs_priv = os.geteuid() != 0 if hasattr(os, 'geteuid') else True
        if needs_priv and shutil.which("sudo"):
            cmd = ["sudo"] + cmd
        
        try:
            if duration and not count:
                # Run with timeout for duration-based capture
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
            else:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
            
            # Check if file was created
            file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
            
            # Get packet count from output
            packet_count = self._parse_packet_count(result.stderr)
            
            # Check for common errors
            stderr_lower = result.stderr.lower() if result.stderr else ""
            if "permission denied" in stderr_lower or "operation not permitted" in stderr_lower:
                return {
                    "error": "Permission denied. Run the server with sudo or configure passwordless sudo for tcpdump.",
                    "stderr": result.stderr,
                    "command": ' '.join(cmd)
                }
            
            if "no suitable device found" in stderr_lower or "no such device" in stderr_lower:
                return {
                    "error": f"Interface '{interface}' not found. Check available interfaces.",
                    "stderr": result.stderr,
                    "command": ' '.join(cmd)
                }
            
            if result.returncode != 0 and file_size == 0:
                return {
                    "error": f"tcpdump failed (exit code {result.returncode})",
                    "stderr": result.stderr,
                    "stdout": result.stdout,
                    "command": ' '.join(cmd)
                }
            
            return {
                "output_file": output_file,
                "file_size": file_size,
                "file_size_human": self._format_size(file_size),
                "packet_count": packet_count,
                "interface": interface,
                "filter": filter_expr,
                "command": ' '.join(cmd),
                "returncode": result.returncode,
                "stderr": result.stderr if result.stderr else None
            }
            
        except subprocess.TimeoutExpired:
            # For duration-based captures, timeout is expected
            file_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
            
            return {
                "output_file": output_file,
                "file_size": file_size,
                "file_size_human": self._format_size(file_size),
                "packet_count": None,
                "interface": interface,
                "filter": filter_expr,
                "command": ' '.join(cmd),
                "returncode": 0,
                "note": "Capture completed (duration limit reached)"
            }
            
        except FileNotFoundError as e:
            missing = getattr(e, "filename", None) or "tcpdump"
            return {"error": f"Required binary not found: {missing}"}
        except PermissionError:
            return {"error": "Permission denied. Packet capture requires root/sudo privileges."}
        except Exception as e:
            return {"error": str(e)}
    
    def _sanitize_filter(self, filter_expr: str) -> Optional[str]:
        """Validate and sanitize tcpdump filter expression."""
        if not filter_expr:
            return None
        
        filter_expr = filter_expr.strip()
        
        if not re.match(self.ALLOWED_FILTER_PATTERN, filter_expr, re.IGNORECASE):
            return None
        
        return filter_expr
    
    def _parse_packet_count(self, stderr: str) -> Optional[int]:
        """Parse packet count from tcpdump output."""
        # tcpdump outputs: "X packets captured"
        match = re.search(r'(\d+)\s+packets?\s+captured', stderr)
        if match:
            return int(match.group(1))
        return None
    
    def _format_size(self, size: int) -> str:
        """Format file size in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
    
    def list_captures(self) -> list:
        """List available capture files."""
        captures = []
        
        if not os.path.exists(self.capture_dir):
            return captures
        
        for filename in os.listdir(self.capture_dir):
            if filename.startswith("capture_") and filename.endswith(".pcap"):
                filepath = os.path.join(self.capture_dir, filename)
                stat = os.stat(filepath)
                captures.append({
                    "filename": filename,
                    "path": filepath,
                    "size": stat.st_size,
                    "size_human": self._format_size(stat.st_size),
                    "created": datetime.fromtimestamp(stat.st_ctime).isoformat()
                })
        
        return sorted(captures, key=lambda x: x["created"], reverse=True)
    
    def delete_capture(self, filename: str) -> dict:
        """Delete a capture file."""
        # Validate filename to prevent path traversal
        if not filename.startswith("capture_") or not filename.endswith(".pcap"):
            return {"error": "Invalid filename"}
        
        if "/" in filename or "\\" in filename:
            return {"error": "Invalid filename"}
        
        filepath = os.path.join(self.capture_dir, filename)
        
        if not os.path.exists(filepath):
            return {"error": "File not found"}
        
        try:
            os.remove(filepath)
            return {"deleted": filename}
        except Exception as e:
            return {"error": str(e)}
    
    def cleanup_old_captures(self, max_age_hours: int = 24) -> dict:
        """Delete capture files older than specified age."""
        deleted = []
        errors = []
        
        cutoff = datetime.now().timestamp() - (max_age_hours * 3600)
        
        for capture in self.list_captures():
            filepath = capture["path"]
            if os.path.getmtime(filepath) < cutoff:
                try:
                    os.remove(filepath)
                    deleted.append(capture["filename"])
                except Exception as e:
                    errors.append({"file": capture["filename"], "error": str(e)})
        
        return {
            "deleted": deleted,
            "deleted_count": len(deleted),
            "errors": errors
        }

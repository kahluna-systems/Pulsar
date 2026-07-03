"""Continuous ping diagnostic runner."""
import subprocess
import time
import threading
import re
import platform
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class PingResult:
    timestamp: str
    seq: int
    rtt_ms: Optional[float]
    timeout: bool = False
    error: Optional[str] = None


@dataclass
class PingSession:
    id: int
    target: str
    interval: float
    duration: int
    status: str = "running"
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    results: List[Dict] = field(default_factory=list)
    stats: Dict = field(default_factory=dict)
    _stop_event: threading.Event = field(default_factory=threading.Event)
    _thread: Optional[threading.Thread] = None


class ContinuousPingRunner:
    """Run continuous ping with statistics."""
    
    def __init__(self):
        self.sessions: Dict[int, PingSession] = {}
        self._next_id = 1
        # Optional callback(session_id, status_dict) invoked when a session ends.
        self.on_complete = None
    
    def start(self, config: dict) -> dict:
        """Start a continuous ping session."""
        target = config.get("target")
        interval = config.get("interval", 1.0)
        duration = config.get("duration", 60)
        
        if not target:
            return {"error": "Target is required"}
        
        session_id = self._next_id
        self._next_id += 1
        
        session = PingSession(
            id=session_id,
            target=target,
            interval=interval,
            duration=duration
        )
        
        self.sessions[session_id] = session
        
        # Start ping thread
        session._thread = threading.Thread(
            target=self._ping_loop,
            args=(session,),
            daemon=True
        )
        session._thread.start()
        
        return {
            "session_id": session_id,
            "target": target,
            "interval": interval,
            "duration": duration,
            "status": "running"
        }
    
    def stop(self, session_id: int) -> dict:
        """Stop a continuous ping session."""
        session = self.sessions.get(session_id)
        
        if not session:
            return {"error": "Session not found"}
        
        session._stop_event.set()
        session.status = "stopped"
        
        return self.get_status(session_id)
    
    def get_status(self, session_id: int) -> dict:
        """Get status and results of a ping session."""
        session = self.sessions.get(session_id)
        
        if not session:
            return {"error": "Session not found"}
        
        # Calculate statistics
        rtts = [r["rtt_ms"] for r in session.results if r.get("rtt_ms") is not None]
        timeouts = sum(1 for r in session.results if r.get("timeout"))
        
        stats = {
            "packets_sent": len(session.results),
            "packets_received": len(rtts),
            "packets_lost": timeouts,
            "loss_percent": (timeouts / len(session.results) * 100) if session.results else 0,
            "rtt_min": min(rtts) if rtts else None,
            "rtt_avg": sum(rtts) / len(rtts) if rtts else None,
            "rtt_max": max(rtts) if rtts else None,
            "rtt_jitter": self._calc_jitter(rtts) if len(rtts) > 1 else None
        }
        
        return {
            "session_id": session_id,
            "target": session.target,
            "status": session.status,
            "started_at": session.started_at,
            "stats": stats,
            "results": session.results[-100:]  # Last 100 results
        }
    
    def get_all_sessions(self) -> List[dict]:
        """Get all ping sessions."""
        return [
            {
                "session_id": s.id,
                "target": s.target,
                "status": s.status,
                "started_at": s.started_at,
                "packets_sent": len(s.results)
            }
            for s in self.sessions.values()
        ]
    
    def _ping_loop(self, session: PingSession):
        """Main ping loop running in background thread."""
        system = platform.system().lower()
        seq = 0
        start_time = time.time()
        
        while not session._stop_event.is_set():
            # Check duration
            if time.time() - start_time >= session.duration:
                session.status = "completed"
                break
            
            seq += 1
            result = self._single_ping(session.target, system, seq)
            session.results.append(result)
            
            # Wait for interval
            session._stop_event.wait(session.interval)
        
        if session.status == "running":
            session.status = "stopped"

        # Notify completion hook (e.g. persist the finished session to history).
        if self.on_complete:
            try:
                self.on_complete(session.id, self.get_status(session.id))
            except Exception:
                pass
    
    def _single_ping(self, target: str, system: str, seq: int) -> dict:
        """Execute a single ping."""
        timestamp = datetime.utcnow().isoformat()
        
        if system == "windows":
            cmd = ["ping", "-n", "1", "-w", "2000", target]
        else:
            cmd = ["ping", "-c", "1", "-W", "2", target]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                # Parse RTT from output
                rtt = self._parse_ping_rtt(result.stdout, system)
                return {
                    "timestamp": timestamp,
                    "seq": seq,
                    "rtt_ms": rtt,
                    "timeout": False,
                    "error": None
                }
            else:
                return {
                    "timestamp": timestamp,
                    "seq": seq,
                    "rtt_ms": None,
                    "timeout": True,
                    "error": None
                }
                
        except subprocess.TimeoutExpired:
            return {
                "timestamp": timestamp,
                "seq": seq,
                "rtt_ms": None,
                "timeout": True,
                "error": "Ping command timed out"
            }
        except Exception as e:
            return {
                "timestamp": timestamp,
                "seq": seq,
                "rtt_ms": None,
                "timeout": True,
                "error": str(e)
            }
    
    def _parse_ping_rtt(self, output: str, system: str) -> Optional[float]:
        """Parse RTT from ping output."""
        if system == "windows":
            # Windows: "Reply from x.x.x.x: bytes=32 time=10ms TTL=64"
            match = re.search(r'time[=<](\d+\.?\d*)ms', output, re.IGNORECASE)
        else:
            # Unix: "64 bytes from x.x.x.x: icmp_seq=1 ttl=64 time=10.5 ms"
            match = re.search(r'time[=](\d+\.?\d*)\s*ms', output, re.IGNORECASE)
        
        if match:
            return float(match.group(1))
        return None
    
    def _calc_jitter(self, rtts: List[float]) -> float:
        """Calculate jitter from RTT values."""
        if len(rtts) < 2:
            return 0.0
        diffs = [abs(rtts[i] - rtts[i-1]) for i in range(1, len(rtts))]
        return round(sum(diffs) / len(diffs), 2)


# Global instance for managing ping sessions
ping_runner = ContinuousPingRunner()

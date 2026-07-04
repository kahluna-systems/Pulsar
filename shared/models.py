"""Pydantic models shared between node and hub."""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class TestType(str, Enum):
    SPEEDTEST = "speedtest"
    SPEEDTEST_CUSTOMER = "speedtest_customer"
    TRACEROUTE = "traceroute"
    MTR = "mtr"
    DNS = "dns"
    TCP_CHECK = "tcp_check"
    SSL_CHECK = "ssl_check"
    IPERF = "iperf"
    PACKET_CAPTURE = "packet_capture"
    CONTINUOUS_PING = "continuous_ping"


class TestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class UserRole(str, Enum):
    ADMIN = "admin"
    ENGINEER = "engineer"
    VIEWER = "viewer"


# Authentication Models
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: int
    username: str
    role: UserRole
    created_at: datetime
    last_login: Optional[datetime]


# Customer Token Models
class CustomerTokenCreate(BaseModel):
    customer_id: Optional[str] = None
    org_id: Optional[int] = None
    expires_hours: int = Field(default=24, ge=1, le=168)
    max_uses: int = Field(default=1, ge=1, le=100)
    note: Optional[str] = None


class CustomerTokenResponse(BaseModel):
    id: int
    token: str
    customer_id: Optional[str]
    expires_at: datetime
    max_uses: int
    use_count: int
    created_at: datetime
    test_url: str


# Test Configuration Models
class SpeedTestConfig(BaseModel):
    mode: str = "client"  # client or server
    target_url: Optional[str] = None
    duration: int = Field(default=10, ge=5, le=60)
    parallel: int = Field(default=4, ge=1, le=16)


class TracerouteConfig(BaseModel):
    target: str
    protocol: str = Field(default="icmp", pattern="^(icmp|udp|tcp)$")
    max_hops: int = Field(default=30, ge=1, le=64)
    timeout: float = Field(default=2.0, ge=0.5, le=10.0)
    resolve_hostnames: bool = True


class MTRConfig(BaseModel):
    target: str
    protocol: str = Field(default="icmp", pattern="^(icmp|udp|tcp)$")
    count: int = Field(default=10, ge=1, le=100)
    max_hops: int = Field(default=30, ge=1, le=64)
    timeout: float = Field(default=2.0, ge=0.5, le=10.0)


class DNSConfig(BaseModel):
    query: str
    record_type: str = Field(default="A", pattern="^(A|AAAA|MX|TXT|CNAME|NS|SOA|PTR)$")
    server: Optional[str] = None
    timeout: float = Field(default=5.0, ge=1.0, le=30.0)


class TCPCheckConfig(BaseModel):
    host: str
    port: int = Field(ge=1, le=65535)
    timeout: float = Field(default=5.0, ge=1.0, le=30.0)


class SSLCheckConfig(BaseModel):
    host: str
    port: int = Field(default=443, ge=1, le=65535)


class ContinuousPingConfig(BaseModel):
    target: str
    interval: float = Field(default=1.0, ge=0.1, le=10.0)
    duration: int = Field(default=60, ge=10, le=86400)  # max 24 hours


class IperfConfig(BaseModel):
    mode: str = Field(default="client", pattern="^(client|server)$")
    server: Optional[str] = None
    port: int = Field(default=5201, ge=1, le=65535)
    protocol: str = Field(default="tcp", pattern="^(tcp|udp)$")
    duration: int = Field(default=10, ge=1, le=3600)
    parallel: int = Field(default=1, ge=1, le=128)
    bandwidth: Optional[str] = None
    window: Optional[str] = None
    one_off: bool = False


class PacketCaptureConfig(BaseModel):
    interface: str = "any"
    filter: Optional[str] = None
    count: Optional[int] = Field(default=None, ge=1, le=100000)
    duration: Optional[int] = Field(default=None, ge=1, le=300)
    snaplen: int = Field(default=65535, ge=64, le=65535)
    promiscuous: bool = True


# Test Request/Response Models
class TestRequest(BaseModel):
    test_type: TestType
    config: Dict[str, Any]
    org_id: Optional[int] = None
    circuit_id: Optional[int] = None


class TestResponse(BaseModel):
    id: int
    test_type: TestType
    status: TestStatus
    config: Dict[str, Any]
    result: Optional[Dict[str, Any]]
    created_at: datetime
    completed_at: Optional[datetime]


# Speed Test Results
class SpeedTestResult(BaseModel):
    ping_min: Optional[float] = None
    ping_avg: Optional[float] = None
    ping_max: Optional[float] = None
    ping_jitter: Optional[float] = None
    download_mbps: Optional[float] = None
    download_bytes: Optional[int] = None
    upload_mbps: Optional[float] = None
    upload_bytes: Optional[int] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    customer_id: Optional[str] = None
    errors: List[str] = []


# Traceroute Results
class TracerouteHop(BaseModel):
    hop: int
    ip: Optional[str]
    hostname: Optional[str]
    rtt_ms: Optional[float]
    timeout: bool = False


class TracerouteResult(BaseModel):
    target: str
    resolved_ip: Optional[str]
    hops: List[TracerouteHop]
    completed: bool
    error: Optional[str] = None


# MTR Results
class MTRHop(BaseModel):
    hop: int
    ip: Optional[str]
    hostname: Optional[str]
    loss_percent: float
    sent: int
    received: int
    rtt_min: Optional[float]
    rtt_avg: Optional[float]
    rtt_max: Optional[float]
    rtt_jitter: Optional[float]


class MTRResult(BaseModel):
    target: str
    resolved_ip: Optional[str]
    hops: List[MTRHop]
    packet_count: int
    error: Optional[str] = None


# DNS Results
class DNSResult(BaseModel):
    query: str
    record_type: str
    server: str
    answers: List[Dict[str, Any]]
    response_time_ms: float
    error: Optional[str] = None


# Node Models (for hub)
class NodeInfo(BaseModel):
    node_id: str
    name: str
    location: Optional[str]
    status: str
    last_seen: Optional[datetime]
    features: List[str]


class NodeSyncRequest(BaseModel):
    node_id: str
    results: List[Dict[str, Any]]

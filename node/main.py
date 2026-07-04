"""KahLuna Pulsar - Network Diagnostics Node Application."""
from fastapi import FastAPI, Depends, BackgroundTasks, Request, Response, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime
import json
import os
import sys
import asyncio

# Add parent directory for shared imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from .config import get_config, NodeConfig, save_config, set_config, _ENV_MAP
from .database import get_db, init_db, TestResult, CustomerToken, User, Organization, Circuit
from .auth import (
    get_current_user, get_optional_user, require_role,
    create_access_token, create_refresh_token, authenticate_user,
    create_customer_token, validate_customer_token, get_customer_token_info,
    ensure_admin_exists, create_user, user_from_token
)
from .runners import (
    SpeedTestRunner, TracerouteRunner, MTRRunner, DNSRunner,
    TCPCheckRunner, SSLCheckRunner, IperfRunner, PacketCaptureRunner
)
from .runners.ping import ping_runner

from shared.models import (
    TestType, TestStatus, LoginRequest, TokenResponse,
    CustomerTokenCreate, CustomerTokenResponse, TestRequest
)
from shared.utils import get_client_ip, RateLimiter, verify_password, hash_password
from pydantic import BaseModel

# Initialize app
app = FastAPI(
    title="KahLuna Pulsar",
    description="KahLuna Pulsar — distributed network diagnostics node",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiters
speedtest_limiter = RateLimiter(max_requests=10, window_seconds=60)
api_limiter = RateLimiter(max_requests=100, window_seconds=60)

# Runner instances
speedtest_runner = SpeedTestRunner()
traceroute_runner = TracerouteRunner()
mtr_runner = MTRRunner()
dns_runner = DNSRunner()
tcp_runner = TCPCheckRunner()
ssl_runner = SSLCheckRunner()
iperf_runner = IperfRunner()
capture_runner = PacketCaptureRunner()


# Process start time, used for the dashboard uptime metric
_process_started = datetime.utcnow()


@app.on_event("startup")
async def startup():
    """Initialize database and ensure admin exists."""
    init_db()
    db = next(get_db())
    ensure_admin_exists(db)
    db.close()
    # Persist continuous-ping sessions to history when they finish.
    ping_runner.on_complete = lambda sid, status: _persist_result(
        "continuous_ping", {"target": status.get("target")}, status,
        **_ping_attribution.pop(sid, {})
    )


# ============== Authentication Endpoints ==============

@app.post("/api/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and get access token."""
    user = authenticate_user(db, request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    access_token = create_access_token(user.username, user.role)
    refresh_token = create_refresh_token(user.username)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=3600
    )


@app.get("/api/auth/me")
async def get_me(user = Depends(get_current_user)):
    """Get current user info."""
    if user is None:
        return {"authenticated": False, "auth_required": get_config().require_auth}
    
    return {
        "authenticated": True,
        "username": user.username,
        "role": user.role
    }


@app.get("/api/auth/status")
async def auth_status(db: Session = Depends(get_db)):
    """Report whether auth is enabled and whether first-run admin setup is needed."""
    config = get_config()
    admin = db.query(User).filter(User.role == "admin").first()
    return {
        "auth_required": config.require_auth,
        "setup_required": config.require_auth and admin is None,
    }


@app.post("/api/auth/setup", response_model=TokenResponse)
async def setup_admin(request: LoginRequest, db: Session = Depends(get_db)):
    """First-run admin creation. Allowed only while no admin account exists yet."""
    if db.query(User).filter(User.role == "admin").first() is not None:
        raise HTTPException(status_code=403, detail="Admin already configured")
    if not request.username or len(request.password or "") < 8:
        raise HTTPException(
            status_code=400,
            detail="Username is required and password must be at least 8 characters"
        )
    user = create_user(db, request.username, request.password, role="admin")
    return TokenResponse(
        access_token=create_access_token(user.username, user.role),
        refresh_token=create_refresh_token(user.username),
        expires_in=3600
    )


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class AdminUserCreate(BaseModel):
    username: str
    password: str
    role: str = "engineer"


class AdminPasswordReset(BaseModel):
    new_password: str


@app.post("/api/auth/password")
async def change_own_password(
    req: PasswordChangeRequest,
    db: Session = Depends(get_db),
    user = Depends(get_current_user)
):
    """Change the current user's password (requires the current password)."""
    if user is None:
        raise HTTPException(status_code=400, detail="Authentication is disabled")
    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    user.password_hash = hash_password(req.new_password)
    db.commit()
    return {"changed": True}


# ============== Admin Endpoints ==============

@app.get("/api/admin/users")
async def admin_list_users(db: Session = Depends(get_db), user = Depends(require_role("admin"))):
    """List all user accounts."""
    users = db.query(User).order_by(User.id).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in users
    ]


@app.post("/api/admin/users")
async def admin_create_user(
    req: AdminUserCreate,
    db: Session = Depends(get_db),
    user = Depends(require_role("admin"))
):
    """Create a new user account."""
    if req.role not in ("viewer", "engineer", "admin"):
        raise HTTPException(status_code=400, detail="Role must be viewer, engineer, or admin")
    if not req.username or len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Username required; password must be at least 8 characters")
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    new_user = create_user(db, req.username, req.password, req.role)
    return {"id": new_user.id, "username": new_user.username, "role": new_user.role}


@app.post("/api/admin/users/{user_id}/password")
async def admin_reset_password(
    user_id: int,
    req: AdminPasswordReset,
    db: Session = Depends(get_db),
    user = Depends(require_role("admin"))
):
    """Reset another user's password."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    target.password_hash = hash_password(req.new_password)
    db.commit()
    return {"reset": target.username}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_role("admin"))
):
    """Delete a user account (cannot delete yourself or the last admin)."""
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if user is not None and target.id == user.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")
    if target.role == "admin" and db.query(User).filter(User.role == "admin").count() <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last admin account")
    db.delete(target)
    db.commit()
    return {"deleted": target.username}


def _env_pinned_fields() -> list:
    """Config fields currently overridden by environment variables (file edits
    to these fields are ignored on restart because env wins at load time)."""
    return [
        field for env_key, (field, _) in _ENV_MAP.items()
        if os.environ.get(env_key) not in (None, "")
    ]


@app.get("/api/admin/settings")
async def admin_get_settings(user = Depends(require_role("admin"))):
    """Current editable node settings."""
    config = get_config()
    return {
        "node_name": config.node_name,
        "node_id": config.node_id,
        "location": config.location,
        "features": config.features.model_dump(),
        "limits": config.limits.model_dump(),
        "token_expiry_hours": config.token_expiry_hours,
        "env_pinned": _env_pinned_fields(),
    }


@app.put("/api/admin/settings")
async def admin_update_settings(updates: dict, user = Depends(require_role("admin"))):
    """Update node settings (whitelisted fields only) and persist to node_config.json."""
    config = get_config()
    data = config.model_dump()

    for key in ("node_name", "location", "token_expiry_hours"):
        if key in updates:
            data[key] = updates[key]
    if isinstance(updates.get("features"), dict):
        data["features"].update(
            {k: bool(v) for k, v in updates["features"].items() if k in data["features"]}
        )
    if isinstance(updates.get("limits"), dict):
        data["limits"].update(
            {k: int(v) for k, v in updates["limits"].items() if k in data["limits"]}
        )

    try:
        new_config = NodeConfig(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid settings: {e}")

    config_path = os.environ.get("NODE_CONFIG", "node_config.json")
    save_config(new_config, config_path)
    set_config(new_config)
    return {"saved": True, "env_pinned": _env_pinned_fields()}


# ============== Customer Token Endpoints ==============

@app.post("/api/tokens", response_model=CustomerTokenResponse)
async def create_token(
    token_config: CustomerTokenCreate,
    request: Request,
    db: Session = Depends(get_db),
    user = Depends(require_role("engineer"))
):
    """Create a customer test token."""
    if token_config.org_id is not None:
        if not db.query(Organization).filter(Organization.id == token_config.org_id).first():
            raise HTTPException(status_code=400, detail="Organization not found")
    token = create_customer_token(
        db,
        customer_id=token_config.customer_id,
        expires_hours=token_config.expires_hours,
        max_uses=token_config.max_uses,
        note=token_config.note,
        created_by=user.username if user else None,
        org_id=token_config.org_id
    )
    
    # Build test URL
    host = request.headers.get("host", "localhost:8000")
    protocol = "https" if request.url.scheme == "https" else "http"
    test_url = f"{protocol}://{host}/speedtest?token={token.token}"
    
    return CustomerTokenResponse(
        id=token.id,
        token=token.token,
        customer_id=token.customer_id,
        expires_at=token.expires_at,
        max_uses=token.max_uses,
        use_count=token.use_count,
        created_at=token.created_at,
        test_url=test_url
    )


@app.get("/api/tokens")
async def list_tokens(
    db: Session = Depends(get_db),
    user = Depends(require_role("engineer"))
):
    """List all customer tokens."""
    tokens = db.query(CustomerToken).order_by(CustomerToken.created_at.desc()).all()
    org_names = {o.id: o.name for o in db.query(Organization).all()}
    return [
        {
            "id": t.id,
            "token": t.token[:8] + "...",  # Partial token for display
            "customer_id": t.customer_id,
            "org_id": t.org_id,
            "org_name": org_names.get(t.org_id),
            "expires_at": t.expires_at.isoformat(),
            "max_uses": t.max_uses,
            "use_count": t.use_count,
            "created_at": t.created_at.isoformat(),
            "expired": t.expires_at < datetime.utcnow(),
            "exhausted": t.use_count >= t.max_uses
        }
        for t in tokens
    ]


@app.delete("/api/tokens/{token_id}")
async def delete_token(
    token_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_role("engineer"))
):
    """Delete/revoke a customer token."""
    token = db.query(CustomerToken).filter(CustomerToken.id == token_id).first()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    
    db.delete(token)
    db.commit()
    return {"deleted": token_id}


# ============== Speed Test Endpoints ==============

@app.get("/api/speedtest/ping")
async def speedtest_ping():
    """Ping endpoint for latency measurement."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/speedtest/download")
async def speedtest_download(size: int = 1048576):
    """Generate data for download speed test."""
    size = min(size, 10485760)  # Cap at 10MB
    data = os.urandom(size)
    return Response(content=data, media_type="application/octet-stream")


@app.post("/api/speedtest/upload")
async def speedtest_upload(request: Request):
    """Receive data for upload speed test."""
    body = await request.body()
    return {"received": len(body)}


@app.get("/api/client-script")
async def get_client_script(request: Request):
    """Serve the Python test client with server URL pre-configured."""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    script_path = os.path.join(static_dir, "network_test.py")
    
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="Client script not found")
    
    with open(script_path, "r") as f:
        script_content = f.read()
    
    # Replace placeholder with actual server URL
    host = request.headers.get("host", "localhost:8000")
    protocol = "https" if request.url.scheme == "https" else "http"
    server_url = f"{protocol}://{host}"
    
    script_content = script_content.replace('DEFAULT_SERVER = "{{SERVER_URL}}"', f'DEFAULT_SERVER = "{server_url}"')
    
    return Response(
        content=script_content,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=network_test.py"}
    )


@app.get("/api/client-script/ps1")
async def get_powershell_script(request: Request):
    """Serve the PowerShell test client with server URL pre-configured."""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    script_path = os.path.join(static_dir, "network_test.ps1")
    
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="PowerShell script not found")
    
    with open(script_path, "r") as f:
        script_content = f.read()
    
    # Replace placeholder with actual server URL
    host = request.headers.get("host", "localhost:8000")
    protocol = "https" if request.url.scheme == "https" else "http"
    server_url = f"{protocol}://{host}"
    
    script_content = script_content.replace('{{SERVER_URL}}', server_url)
    
    return Response(
        content=script_content,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=network_test.ps1"}
    )


@app.get("/api/client-script/sh")
async def get_bash_script(request: Request):
    """Serve the Bash test client with server URL pre-configured."""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    script_path = os.path.join(static_dir, "network_test.sh")
    
    if not os.path.exists(script_path):
        raise HTTPException(status_code=404, detail="Bash script not found")
    
    with open(script_path, "r") as f:
        script_content = f.read()
    
    # Replace placeholder with actual server URL
    host = request.headers.get("host", "localhost:8000")
    protocol = "https" if request.url.scheme == "https" else "http"
    server_url = f"{protocol}://{host}"
    
    script_content = script_content.replace('{{SERVER_URL}}', server_url)
    
    return Response(
        content=script_content,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=network_test.sh"}
    )


@app.post("/api/speedtest/result")
async def speedtest_save_result(
    request: Request,
    db: Session = Depends(get_db)
):
    """Save speed test result from customer portal."""
    data = await request.json()
    client_ip = get_client_ip(request)
    
    # Check for token
    token_str = data.get("token")
    customer_id = None
    token_org_id = None

    if token_str:
        token = validate_customer_token(db, token_str)
        if token:
            customer_id = token.customer_id
            token_org_id = token.org_id

    test_result = TestResult(
        test_type="speedtest_customer",
        customer_id=customer_id,
        org_id=token_org_id,
        client_ip=client_ip,
        config=json.dumps({
            "user_agent": request.headers.get("User-Agent", "unknown"),
            "token_used": bool(token_str)
        }),
        result=json.dumps(data),
        status="completed",
        completed_at=datetime.utcnow()
    )
    
    db.add(test_result)
    db.commit()
    db.refresh(test_result)
    
    return {"id": test_result.id, "status": "saved"}


# ============== Customer Organizations & Circuits ==============

class OrgCreate(BaseModel):
    name: str
    org_type: str = "customer"
    notes: str = None


class CircuitCreate(BaseModel):
    label: str
    target: str = None
    notes: str = None


def _org_dict(o: Organization, circuits: list, tests_count: int = 0) -> dict:
    return {
        "id": o.id,
        "name": o.name,
        "org_type": o.org_type,
        "notes": o.notes,
        "is_active": o.is_active,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "tests_count": tests_count,
        "circuits": [
            {
                "id": c.id,
                "label": c.label,
                "target": c.target,
                "notes": c.notes,
                "is_active": c.is_active,
            }
            for c in circuits
        ],
    }


@app.get("/api/orgs")
async def list_orgs(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user = Depends(require_role("engineer"))
):
    """List organizations with their circuits."""
    q = db.query(Organization).order_by(Organization.name)
    if not include_inactive:
        q = q.filter(Organization.is_active == True)
    orgs = q.all()
    circuits = db.query(Circuit).filter(Circuit.is_active == True).all()
    by_org = {}
    for c in circuits:
        by_org.setdefault(c.org_id, []).append(c)
    from sqlalchemy import func
    test_counts = dict(
        db.query(TestResult.org_id, func.count(TestResult.id))
        .filter(TestResult.org_id.isnot(None))
        .group_by(TestResult.org_id).all()
    )
    return [_org_dict(o, by_org.get(o.id, []), test_counts.get(o.id, 0)) for o in orgs]


@app.post("/api/orgs")
async def create_org(
    req: OrgCreate,
    db: Session = Depends(get_db),
    user = Depends(require_role("engineer"))
):
    """Create an organization."""
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Organization name is required")
    if req.org_type not in ("customer", "partner"):
        raise HTTPException(status_code=400, detail="Type must be customer or partner")
    if db.query(Organization).filter(Organization.name == name).first():
        raise HTTPException(status_code=400, detail="An organization with that name already exists")
    org = Organization(name=name, org_type=req.org_type, notes=req.notes)
    db.add(org)
    db.commit()
    db.refresh(org)
    return _org_dict(org, [])


@app.delete("/api/orgs/{org_id}")
async def delete_org(
    org_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_role("engineer"))
):
    """Delete an organization and its circuits. Historical tests keep their org_id."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    db.query(Circuit).filter(Circuit.org_id == org_id).delete()
    db.delete(org)
    db.commit()
    return {"deleted": org.name}


@app.post("/api/orgs/{org_id}/circuits")
async def create_circuit(
    org_id: int,
    req: CircuitCreate,
    db: Session = Depends(get_db),
    user = Depends(require_role("engineer"))
):
    """Add a circuit to an organization."""
    org = db.query(Organization).filter(Organization.id == org_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    label = (req.label or "").strip()
    if not label:
        raise HTTPException(status_code=400, detail="Circuit label is required")
    dup = db.query(Circuit).filter(
        Circuit.org_id == org_id, Circuit.label == label, Circuit.is_active == True
    ).first()
    if dup:
        raise HTTPException(status_code=400, detail="That circuit label already exists for this organization")
    circuit = Circuit(org_id=org_id, label=label, target=(req.target or "").strip() or None, notes=req.notes)
    db.add(circuit)
    db.commit()
    db.refresh(circuit)
    return {"id": circuit.id, "org_id": org_id, "label": circuit.label, "target": circuit.target}


@app.delete("/api/circuits/{circuit_id}")
async def delete_circuit(
    circuit_id: int,
    db: Session = Depends(get_db),
    user = Depends(require_role("engineer"))
):
    """Remove a circuit."""
    circuit = db.query(Circuit).filter(Circuit.id == circuit_id).first()
    if not circuit:
        raise HTTPException(status_code=404, detail="Circuit not found")
    db.delete(circuit)
    db.commit()
    return {"deleted": circuit.label}


# ============== Diagnostic Test Endpoints ==============

@app.post("/api/tests")
async def create_test(
    test_request: TestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user = Depends(require_role("engineer"))
):
    """Create and run a diagnostic test."""
    config = get_config()
    
    # Check if feature is enabled
    feature_map = {
        TestType.SPEEDTEST: config.features.speedtest,
        TestType.TRACEROUTE: config.features.traceroute,
        TestType.MTR: config.features.mtr,
        TestType.DNS: config.features.dns,
        TestType.TCP_CHECK: config.features.tcp_check,
        TestType.SSL_CHECK: config.features.ssl_check,
        TestType.IPERF: config.features.iperf,
        TestType.PACKET_CAPTURE: config.features.packet_capture,
        TestType.CONTINUOUS_PING: config.features.continuous_ping,
    }
    
    if not feature_map.get(test_request.test_type, False):
        raise HTTPException(status_code=400, detail=f"Feature {test_request.test_type} is disabled")
    
    # Create test record
    test_result = TestResult(
        test_type=test_request.test_type.value,
        config=json.dumps(test_request.config),
        status="running",
        org_id=test_request.org_id,
        circuit_id=test_request.circuit_id
    )
    db.add(test_result)
    db.commit()
    db.refresh(test_result)
    
    # Run test in background
    background_tasks.add_task(
        execute_test,
        test_result.id,
        test_request.test_type.value,
        test_request.config
    )
    
    return {"id": test_result.id, "status": "running"}


def execute_test(test_id: int, test_type: str, config: dict):
    """Execute a diagnostic test."""
    db = next(get_db())
    test_result = db.query(TestResult).filter(TestResult.id == test_id).first()
    
    if not test_result:
        db.close()
        return
    
    try:
        # Select runner based on test type
        runners = {
            "speedtest": speedtest_runner,
            "traceroute": traceroute_runner,
            "mtr": mtr_runner,
            "dns": dns_runner,
            "tcp_check": tcp_runner,
            "ssl_check": ssl_runner,
            "iperf": iperf_runner,
            "packet_capture": capture_runner,
        }
        
        runner = runners.get(test_type)
        if not runner:
            raise Exception(f"Unknown test type: {test_type}")
        
        # Special handling for DNS
        if test_type == "dns":
            lookup_type = config.get("lookup_type", "lookup")
            if lookup_type == "reverse":
                result = runner.reverse_lookup(config)
            elif lookup_type == "propagation":
                result = runner.propagation_check(config)
            else:
                result = runner.lookup(config)
        else:
            result = runner.run(config)
        
        test_result.status = "completed"
        test_result.result = json.dumps(result)
        test_result.completed_at = datetime.utcnow()
        
    except Exception as e:
        test_result.status = "failed"
        test_result.result = json.dumps({"error": str(e)})
        test_result.completed_at = datetime.utcnow()
    
    db.commit()
    db.close()


def _persist_result(test_type: str, config: dict, result: dict, org_id: int = None, circuit_id: int = None):
    """Best-effort save of a streaming/session test (MTR, continuous ping) to history."""
    try:
        db = next(get_db())
        try:
            db.add(TestResult(
                test_type=test_type,
                config=json.dumps(config),
                result=json.dumps(result),
                status="completed",
                completed_at=datetime.utcnow(),
                org_id=org_id,
                circuit_id=circuit_id,
            ))
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


@app.get("/api/tests")
async def list_tests(
    limit: int = 50,
    test_type: str = None,
    org_id: int = None,
    db: Session = Depends(get_db),
    user = Depends(require_role("engineer"))
):
    """List recent tests."""
    query = db.query(TestResult).order_by(TestResult.created_at.desc())

    if test_type:
        query = query.filter(TestResult.test_type == test_type)
    if org_id:
        query = query.filter(TestResult.org_id == org_id)

    tests = query.limit(limit).all()

    org_names = {o.id: o.name for o in db.query(Organization).all()}
    circuit_labels = {c.id: c.label for c in db.query(Circuit).all()}

    return [
        {
            "id": t.id,
            "test_type": t.test_type,
            "customer_id": t.customer_id,
            "org_id": t.org_id,
            "org_name": org_names.get(t.org_id),
            "circuit_id": t.circuit_id,
            "circuit_label": circuit_labels.get(t.circuit_id),
            "status": t.status,
            "created_at": t.created_at.isoformat(),
            "completed_at": t.completed_at.isoformat() if t.completed_at else None
        }
        for t in tests
    ]


@app.get("/api/tests/{test_id}")
async def get_test(test_id: int, db: Session = Depends(get_db),
                   user = Depends(require_role("engineer"))):
    """Get test details."""
    test = db.query(TestResult).filter(TestResult.id == test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    
    org = db.query(Organization).filter(Organization.id == test.org_id).first() if test.org_id else None
    circuit = db.query(Circuit).filter(Circuit.id == test.circuit_id).first() if test.circuit_id else None

    return {
        "id": test.id,
        "test_type": test.test_type,
        "customer_id": test.customer_id,
        "org_id": test.org_id,
        "org_name": org.name if org else None,
        "circuit_id": test.circuit_id,
        "circuit_label": circuit.label if circuit else None,
        "client_ip": test.client_ip,
        "config": json.loads(test.config) if test.config else None,
        "result": json.loads(test.result) if test.result else None,
        "status": test.status,
        "created_at": test.created_at.isoformat(),
        "completed_at": test.completed_at.isoformat() if test.completed_at else None
    }


# ============== Live MTR Streaming Endpoint ==============

_active_mtr_sessions = {}  # session_id -> cancel flag


@app.get("/api/mtr/stream")
async def stream_mtr(target: str, max_hops: int = 30, protocol: str = "icmp", token: str = None,
                     org_id: int = None, circuit_id: int = None):
    """Stream live MTR results via SSE. Runs repeated single-cycle passes until stopped."""
    # EventSource can't set an Authorization header, so the JWT arrives as ?token=.
    config = get_config()
    if config.require_auth:
        db = next(get_db())
        try:
            authed = user_from_token(db, token)
        finally:
            db.close()
        if authed is None or authed.role not in ("engineer", "admin"):
            raise HTTPException(status_code=401, detail="Authentication required")

    if not target:
        raise HTTPException(status_code=400, detail="Target is required")

    import socket
    resolved_ip = None
    try:
        resolved_ip = socket.gethostbyname(target)
    except socket.gaierror:
        pass

    session_id = os.urandom(4).hex()

    async def mtr_event_stream():
        # All cycles use --no-dns for consistency; first cycle also does a DNS lookup
        cmd = ["mtr", "--json", "-c", "1", "-m", str(max_hops), "--no-dns"]

        if protocol == "tcp":
            cmd.append("--tcp")
        elif protocol == "udp":
            cmd.append("--udp")

        cmd.append(target)

        import shutil
        needs_priv = protocol in ("icmp", "tcp") and (
            os.geteuid() != 0 if hasattr(os, 'geteuid') else False
        )
        if needs_priv and shutil.which("sudo"):
            cmd = ["sudo", "-n"] + cmd

        # Track cumulative stats per hop keyed by position index
        hop_stats = {}  # position (int) -> {hop, ip, hostname, sent, received, rtts}
        hostnames = {}  # ip -> hostname (resolved once on first cycle)
        hops_snapshot = []  # last emitted snapshot; persisted in finally
        cancel_event = asyncio.Event()
        _active_mtr_sessions[session_id] = cancel_event

        try:
            yield f"data: {json.dumps({'session_id': session_id, 'status': 'started'})}\n\n"

            cycle = 0
            dns_resolved = False

            while not cancel_event.is_set():
                cycle += 1

                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(), timeout=15
                    )
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                    break

                try:
                    data = json.loads(stdout.decode())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Check if sudo failed
                    err_text = stderr.decode() if stderr else ""
                    if "password" in err_text.lower() or "sudo" in err_text.lower():
                        yield f"data: {json.dumps({'error': 'mtr requires sudo. Run: echo \"bigtex ALL=(ALL) NOPASSWD: /usr/bin/mtr\" | sudo tee /etc/sudoers.d/pulsar'})}\n\n"
                        break
                    continue

                hubs = data.get("report", {}).get("hubs", [])

                # On first cycle, resolve hostnames via a separate DNS lookup
                if not dns_resolved and hubs:
                    dns_resolved = True
                    import socket as _socket
                    for hub in hubs:
                        ip = hub.get("host", "???")
                        if ip != "???" and ip not in hostnames:
                            try:
                                hostname_result = _socket.gethostbyaddr(ip)
                                hostnames[ip] = hostname_result[0]
                            except (_socket.herror, _socket.gaierror, OSError):
                                pass

                for i, hub in enumerate(hubs):
                    ip = hub.get("host", "???")
                    loss_pct = hub.get("Loss%", 0)
                    snt = hub.get("Snt", 0)

                    if i not in hop_stats:
                        hop_stats[i] = {
                            "hop": i + 1,  # 1-indexed like standard mtr
                            "ip": ip if ip != "???" else None,
                            "hostname": hostnames.get(ip),
                            "sent": 0,
                            "received": 0,
                            "rtts": []
                        }

                    h = hop_stats[i]
                    # Update IP if it was previously unknown
                    if ip != "???" and h["ip"] is None:
                        h["ip"] = ip
                    # Update hostname if we have one
                    if ip in hostnames and not h["hostname"]:
                        h["hostname"] = hostnames[ip]

                    h["sent"] += snt
                    received_this_cycle = int(snt * (100 - loss_pct) / 100)
                    h["received"] += received_this_cycle

                    avg_rtt = hub.get("Avg")
                    if received_this_cycle > 0 and avg_rtt is not None:
                        h["rtts"].append(avg_rtt)

                # Build ordered snapshot
                hops_snapshot = []
                for pos in sorted(hop_stats.keys()):
                    h = hop_stats[pos]
                    rtts = h["rtts"]
                    total_sent = h["sent"]
                    total_recv = h["received"]
                    loss = ((total_sent - total_recv) / total_sent * 100) if total_sent > 0 else 100

                    hops_snapshot.append({
                        "hop": h["hop"],
                        "ip": h["ip"],
                        "hostname": h["hostname"] or h["ip"],
                        "loss_percent": round(loss, 1),
                        "sent": total_sent,
                        "received": total_recv,
                        "rtt_min": round(min(rtts), 1) if rtts else None,
                        "rtt_avg": round(sum(rtts) / len(rtts), 1) if rtts else None,
                        "rtt_max": round(max(rtts), 1) if rtts else None,
                        "rtt_jitter": round(
                            sum(abs(rtts[j] - rtts[j - 1]) for j in range(1, len(rtts))) / (len(rtts) - 1), 1
                        ) if len(rtts) > 1 else None
                    })

                event_data = json.dumps({
                    "target": target,
                    "resolved_ip": resolved_ip,
                    "hops": hops_snapshot,
                    "complete": False
                })
                yield f"data: {event_data}\n\n"

                # Small delay between cycles
                try:
                    await asyncio.wait_for(cancel_event.wait(), timeout=0.5)
                    break  # cancel_event was set
                except asyncio.TimeoutError:
                    pass  # Continue next cycle

            # Final event
            yield f"data: {json.dumps({'complete': True})}\n\n"

        except asyncio.CancelledError:
            pass
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # Persist in finally so the run is saved on every exit path —
            # including client disconnect (EventSource close cancels the
            # generator before the in-loop code can reach a save).
            if hops_snapshot:
                _persist_result(
                    "mtr",
                    {"target": target, "protocol": protocol, "max_hops": max_hops},
                    {"target": target, "resolved_ip": resolved_ip, "hops": hops_snapshot},
                    org_id=org_id,
                    circuit_id=circuit_id,
                )
            _active_mtr_sessions.pop(session_id, None)

    return StreamingResponse(
        mtr_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/mtr/stop/{session_id}")
async def stop_mtr(session_id: str, user = Depends(require_role("engineer"))):
    """Stop a running MTR session."""
    cancel_event = _active_mtr_sessions.get(session_id)
    if not cancel_event:
        raise HTTPException(status_code=404, detail="MTR session not found")
    cancel_event.set()
    return {"stopped": session_id}


# ============== Continuous Ping Endpoints ==============

# session_id -> attribution, consumed by the on_complete persistence hook
_ping_attribution = {}


@app.post("/api/ping/start")
async def start_ping(config: dict, user = Depends(require_role("engineer"))):
    """Start a continuous ping session."""
    org_id = config.pop("org_id", None)
    circuit_id = config.pop("circuit_id", None)
    result = ping_runner.start(config)
    session_id = result.get("session_id")
    if session_id is not None and (org_id or circuit_id):
        _ping_attribution[session_id] = {"org_id": org_id, "circuit_id": circuit_id}
    return result


@app.get("/api/ping/{session_id}")
async def get_ping_status(session_id: int, user = Depends(require_role("engineer"))):
    """Get continuous ping session status."""
    return ping_runner.get_status(session_id)


@app.post("/api/ping/{session_id}/stop")
async def stop_ping(session_id: int, user = Depends(require_role("engineer"))):
    """Stop a continuous ping session."""
    return ping_runner.stop(session_id)


@app.get("/api/ping")
async def list_ping_sessions(user = Depends(require_role("engineer"))):
    """List all ping sessions."""
    return ping_runner.get_all_sessions()


# ============== Utility Endpoints ==============

@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db), user = Depends(require_role("engineer"))):
    """Aggregate test statistics for the dashboard overview."""
    from sqlalchemy import func
    total = db.query(func.count(TestResult.id)).scalar() or 0
    failed = db.query(func.count(TestResult.id)).filter(TestResult.status == "failed").scalar() or 0
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today = db.query(func.count(TestResult.id)).filter(TestResult.created_at >= today_start).scalar() or 0
    by_type = dict(
        db.query(TestResult.test_type, func.count(TestResult.id))
        .group_by(TestResult.test_type).all()
    )
    last = db.query(func.max(TestResult.created_at)).scalar()
    return {
        "total_tests": total,
        "tests_today": today,
        "failed_tests": failed,
        "success_rate": round((total - failed) / total * 100, 1) if total else None,
        "by_type": by_type,
        "last_test_at": last.isoformat() if last else None,
        "uptime_seconds": int((datetime.utcnow() - _process_started).total_seconds()),
    }


@app.get("/api/node/info")
async def get_node_info():
    """Get node information."""
    config = get_config()
    return {
        "node_id": config.node_id,
        "node_name": config.node_name,
        "location": config.location,
        "features": config.features.model_dump(),
        "auth_required": config.require_auth
    }


# ============== Static Files ==============

@app.get("/speedtest", response_class=HTMLResponse)
async def speedtest_page(token: str = None):
    """Serve customer speed test page."""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    speedtest_path = os.path.join(static_dir, "speedtest.html")
    
    if os.path.exists(speedtest_path):
        with open(speedtest_path, "r") as f:
            return HTMLResponse(content=f.read())
    
    return HTMLResponse(content="<h1>Speed Test page not found</h1>", status_code=404)


# Mount static files last
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

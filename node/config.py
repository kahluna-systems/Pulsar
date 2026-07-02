"""Node configuration management."""
import os
import json
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field


class NodeFeatures(BaseModel):
    speedtest: bool = True
    traceroute: bool = True
    mtr: bool = True
    dns: bool = True
    tcp_check: bool = True
    ssl_check: bool = True
    iperf: bool = True
    packet_capture: bool = True
    continuous_ping: bool = True


class NodeLimits(BaseModel):
    max_capture_duration: int = 300
    max_ping_duration: int = 86400
    max_concurrent_tests: int = 10
    max_mtr_count: int = 100


class NodeConfig(BaseModel):
    node_id: str = Field(default_factory=lambda: f"node-{os.urandom(4).hex()}")
    node_name: str = "Pulsar Node"
    location: Optional[str] = None
    
    # Hub connection (optional)
    hub_url: Optional[str] = None
    hub_api_key: Optional[str] = None
    sync_interval_seconds: int = 60
    standalone_mode: bool = True
    
    # Local settings
    database_path: str = "tests.db"
    secret_key: str = Field(default_factory=lambda: os.urandom(32).hex())
    
    # Features and limits
    features: NodeFeatures = Field(default_factory=NodeFeatures)
    limits: NodeLimits = Field(default_factory=NodeLimits)
    
    # Authentication
    require_auth: bool = False
    admin_username: str = "admin"
    admin_password_hash: Optional[str] = None
    
    # Token settings
    token_expiry_hours: int = 24
    
    class Config:
        extra = "ignore"


def _as_bool(value: str) -> bool:
    """Parse a boolean from an environment variable string."""
    return value.strip().lower() in ("1", "true", "yes", "on")


# Environment variable -> (config field, caster). Env vars take precedence over
# the config file, which lets containers/orchestration inject settings without a
# mounted node_config.json.
_ENV_MAP = {
    "NODE_ID": ("node_id", str),
    "NODE_NAME": ("node_name", str),
    "NODE_LOCATION": ("location", str),
    "HUB_URL": ("hub_url", str),
    "HUB_API_KEY": ("hub_api_key", str),
    "SYNC_INTERVAL_SECONDS": ("sync_interval_seconds", int),
    "STANDALONE_MODE": ("standalone_mode", _as_bool),
    "DATABASE_PATH": ("database_path", str),
    "SECRET_KEY": ("secret_key", str),
    "REQUIRE_AUTH": ("require_auth", _as_bool),
    "ADMIN_USERNAME": ("admin_username", str),
    "TOKEN_EXPIRY_HOURS": ("token_expiry_hours", int),
}


def _env_overrides() -> dict:
    """Collect recognized environment variables into a config overlay dict."""
    overrides = {}
    for env_key, (field, caster) in _ENV_MAP.items():
        raw = os.environ.get(env_key)
        if raw is not None and raw != "":
            overrides[field] = caster(raw)
    return overrides


def load_config(config_path: str = None) -> NodeConfig:
    """Load configuration, layering env vars over the config file over defaults.

    Precedence (highest first): environment variables, node_config.json, defaults.
    On first run the resolved config is written to disk so generated values
    (node_id, secret_key) stay stable across restarts.
    """
    if config_path is None:
        config_path = os.environ.get("NODE_CONFIG", "node_config.json")
    path = Path(config_path)

    data = {}
    if path.exists():
        with open(path) as f:
            data = json.load(f)

    # Environment variables win over the file.
    data.update(_env_overrides())
    config = NodeConfig(**data)

    # Persist on first run so node_id/secret_key don't regenerate each restart.
    if not path.exists():
        save_config(config, config_path)

    return config


def save_config(config: NodeConfig, config_path: str = "node_config.json"):
    """Save configuration to file."""
    with open(config_path, "w") as f:
        json.dump(config.model_dump(), f, indent=2)


# Global config instance
_config: Optional[NodeConfig] = None


def get_config() -> NodeConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def set_config(config: NodeConfig):
    """Set the global configuration instance."""
    global _config
    _config = config

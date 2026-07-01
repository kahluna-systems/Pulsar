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


def load_config(config_path: str = "node_config.json") -> NodeConfig:
    """Load configuration from file or create default."""
    path = Path(config_path)
    
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        return NodeConfig(**data)
    
    # Create default config
    config = NodeConfig()
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

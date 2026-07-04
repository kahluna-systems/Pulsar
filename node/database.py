"""SQLite database setup for test node."""
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from .config import get_config

Base = declarative_base()


class Organization(Base):
    """Customer/partner organization registry (local; maps to platform tenants/sites in managed mode)."""
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    org_type = Column(String(20), default="customer")  # customer | partner
    notes = Column(String(1000))
    is_active = Column(Boolean, default=True)
    # Forward-mapping keys, populated when this node joins a platform (hub mode)
    tenant_id = Column(String(36))
    site_id = Column(String(36))
    created_at = Column(DateTime, default=datetime.utcnow)


class Circuit(Base):
    """A circuit/service belonging to an organization; target is its registered test endpoint."""
    __tablename__ = "circuits"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, index=True, nullable=False)
    label = Column(String(100), nullable=False)  # e.g. CLT-0042
    target = Column(String(255))  # registered endpoint (IP/hostname) tests run against
    notes = Column(String(500))
    is_active = Column(Boolean, default=True)
    site_id = Column(String(36))
    created_at = Column(DateTime, default=datetime.utcnow)


class TestResult(Base):
    """Local test results storage."""
    __tablename__ = "test_results"

    id = Column(Integer, primary_key=True, index=True)
    test_type = Column(String(50), index=True, nullable=False)
    customer_id = Column(String(100), index=True)
    org_id = Column(Integer, index=True)
    circuit_id = Column(Integer, index=True)
    client_ip = Column(String(45))
    config = Column(Text)  # JSON
    result = Column(Text)  # JSON
    status = Column(String(20), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime)
    synced = Column(Boolean, default=False, index=True)


class CustomerToken(Base):
    """Customer test tokens."""
    __tablename__ = "customer_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(100), unique=True, nullable=False, index=True)
    customer_id = Column(String(100), index=True)
    org_id = Column(Integer, index=True)
    note = Column(String(500))
    expires_at = Column(DateTime, nullable=False)
    max_uses = Column(Integer, default=1)
    use_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(50))


class User(Base):
    """Local user accounts (for standalone mode)."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="engineer")
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)


class ContinuousPing(Base):
    """Active continuous ping sessions."""
    __tablename__ = "continuous_pings"
    
    id = Column(Integer, primary_key=True, index=True)
    target = Column(String(255), nullable=False)
    interval = Column(Integer, default=1)
    duration = Column(Integer, default=60)
    status = Column(String(20), default="running")
    started_at = Column(DateTime, default=datetime.utcnow)
    results = Column(Text)  # JSON array of ping results


# Database connection
_engine = None
_SessionLocal = None


def init_db(db_path: str = None):
    """Initialize the database."""
    global _engine, _SessionLocal
    
    if db_path is None:
        db_path = get_config().database_path
    
    _engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False}
    )
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    # Create tables
    Base.metadata.create_all(bind=_engine)
    _migrate_columns(_engine)


def _migrate_columns(engine):
    """Add columns introduced after a table already exists on disk.

    create_all() only creates missing tables; SQLite needs explicit
    ALTER TABLE for new columns on existing databases (e.g. the volume
    of an already-deployed node).
    """
    from sqlalchemy import text

    additions = [
        ("test_results", "org_id", "INTEGER"),
        ("test_results", "circuit_id", "INTEGER"),
        ("customer_tokens", "org_id", "INTEGER"),
    ]
    with engine.connect() as conn:
        for table, column, ddl_type in additions:
            existing = [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()]
            if existing and column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
        conn.commit()


def get_db():
    """Get database session."""
    global _SessionLocal
    
    if _SessionLocal is None:
        init_db()
    
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session():
    """Get a database session directly (not as generator)."""
    global _SessionLocal
    
    if _SessionLocal is None:
        init_db()
    
    return _SessionLocal()

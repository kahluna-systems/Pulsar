"""Authentication for test node."""
import jwt
from datetime import datetime, timedelta
from typing import Optional
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .config import get_config
from .database import get_db, User, CustomerToken
import sys
sys.path.append('..')
from shared.utils import verify_password, hash_password, generate_token

security = HTTPBearer(auto_error=False)


def create_access_token(username: str, role: str, expires_minutes: int = 60) -> str:
    """Create a JWT access token."""
    config = get_config()
    expires = datetime.utcnow() + timedelta(minutes=expires_minutes)
    
    payload = {
        "sub": username,
        "role": role,
        "exp": expires,
        "type": "access"
    }
    
    return jwt.encode(payload, config.secret_key, algorithm="HS256")


def create_refresh_token(username: str) -> str:
    """Create a JWT refresh token."""
    config = get_config()
    expires = datetime.utcnow() + timedelta(days=7)
    
    payload = {
        "sub": username,
        "exp": expires,
        "type": "refresh"
    }
    
    return jwt.encode(payload, config.secret_key, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token."""
    config = get_config()
    
    try:
        payload = jwt.decode(token, config.secret_key, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Get current authenticated user from JWT token."""
    config = get_config()
    
    # If auth not required, return None (anonymous access)
    if not config.require_auth:
        return None
    
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Get current user if authenticated, None otherwise."""
    if not credentials:
        return None
    
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        return None
    
    username = payload.get("sub")
    return db.query(User).filter(User.username == username).first()


def user_from_token(db: Session, token_str: Optional[str]) -> Optional[User]:
    """Resolve a user from a raw access-token string.

    Used for SSE endpoints (EventSource can't set an Authorization header, so
    the token arrives as a query parameter instead).
    """
    if not token_str:
        return None
    payload = decode_token(token_str)
    if not payload or payload.get("type") != "access":
        return None
    return db.query(User).filter(User.username == payload.get("sub")).first()


def require_role(required_role: str):
    """Dependency to require a specific role."""
    async def role_checker(user: User = Depends(get_current_user)):
        if user is None:
            return None  # Auth not required
        
        role_hierarchy = {"viewer": 0, "engineer": 1, "admin": 2}
        user_level = role_hierarchy.get(user.role, 0)
        required_level = role_hierarchy.get(required_role, 0)
        
        if user_level < required_level:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        
        return user
    
    return role_checker


# Customer Token Functions

def create_customer_token(
    db: Session,
    customer_id: Optional[str] = None,
    expires_hours: int = 24,
    max_uses: int = 1,
    note: Optional[str] = None,
    created_by: Optional[str] = None
) -> CustomerToken:
    """Create a new customer test token."""
    token = CustomerToken(
        token=generate_token(24),
        customer_id=customer_id,
        note=note,
        expires_at=datetime.utcnow() + timedelta(hours=expires_hours),
        max_uses=max_uses,
        created_by=created_by
    )
    
    db.add(token)
    db.commit()
    db.refresh(token)
    
    return token


def validate_customer_token(db: Session, token_str: str) -> Optional[CustomerToken]:
    """Validate a customer token and increment use count."""
    token = db.query(CustomerToken).filter(CustomerToken.token == token_str).first()
    
    if not token:
        return None
    
    # Check expiry
    if token.expires_at < datetime.utcnow():
        return None
    
    # Check use count
    if token.use_count >= token.max_uses:
        return None
    
    # Increment use count
    token.use_count += 1
    db.commit()
    
    return token


def get_customer_token_info(db: Session, token_str: str) -> Optional[CustomerToken]:
    """Get token info without incrementing use count."""
    return db.query(CustomerToken).filter(CustomerToken.token == token_str).first()


# User Management Functions

def create_user(db: Session, username: str, password: str, role: str = "engineer") -> User:
    """Create a new user."""
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    return user


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Authenticate a user by username and password."""
    user = db.query(User).filter(User.username == username).first()
    
    if not user:
        return None
    
    if not verify_password(password, user.password_hash):
        return None
    
    # Update last login
    user.last_login = datetime.utcnow()
    db.commit()
    
    return user


def ensure_admin_exists(db: Session):
    """Ensure at least one admin user exists."""
    config = get_config()
    
    admin = db.query(User).filter(User.role == "admin").first()
    if admin:
        return
    
    # Create default admin if password hash is configured
    if config.admin_password_hash:
        admin = User(
            username=config.admin_username,
            password_hash=config.admin_password_hash,
            role="admin"
        )
        db.add(admin)
        db.commit()

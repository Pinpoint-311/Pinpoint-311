from datetime import datetime, timedelta, timezone
from typing import Optional
import secrets as pysecrets
import jwt
from jwt.exceptions import PyJWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_db

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Mint a signed session token.

    Always carries a `jti`. The audit log records it as the session id, so a
    token without one produces an audit row reading session_id="unknown" --
    which is what every login wrote before this. Callers that need the id
    (to log it alongside the login) should pass their own `jti` in `data`
    rather than decoding the token back apart.
    """
    to_encode = data.copy()
    to_encode.setdefault("jti", pysecrets.token_hex(16))
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def create_session_token(user, expires_delta: Optional[timedelta] = None, **extra) -> str:
    """Mint a session token bound to this account's current session generation.

    `uid` pins the token to this row (a deleted-and-recreated username does not
    inherit the old account's sessions) and `tv` to `users.token_version`, which
    get_current_user compares on every request. Every place that signs a user
    in should come through here rather than calling create_access_token with a
    bare `sub`, or its tokens survive sign-out.
    """
    data = {
        "sub": user.username,
        "role": user.role,
        "uid": user.id,
        "tv": int(getattr(user, "token_version", 0) or 0),
    }
    data.update({k: v for k, v in extra.items() if v is not None})
    return create_access_token(data, expires_delta=expires_delta)


def session_is_current(payload: dict, user) -> bool:
    """Has this token been revoked since it was issued?

    Compared against the users row the caller has already loaded, so the
    check costs no extra query. Tokens minted before `tv` existed carry no
    claim and read as generation 0, matching the column default -- the deploy
    does not sign anyone out, but the first bump ends those sessions too.
    """
    uid = payload.get("uid")
    if uid is not None and uid != user.id:
        return False
    try:
        tv = int(payload.get("tv", 0) or 0)
    except (TypeError, ValueError):
        return False
    return tv == int(getattr(user, "token_version", 0) or 0)


def revoke_user_sessions(user) -> None:
    """End every session this account has open (caller commits).

    An atomic SQL increment rather than a read-modify-write, so two concurrent
    revocations cannot collapse into one bump.
    """
    from sqlalchemy import func
    from app.models import User

    user.token_version = func.coalesce(User.token_version, 0) + 1


def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
):
    from app.models import User
    
    payload = decode_token(token)
    username: str = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )

    # Single-purpose tokens (e.g. purpose="onboarding" links minted by the
    # provisioning API) are not session tokens — they must be redeemed at
    # their dedicated endpoint, never used directly against the API.
    if payload.get("purpose"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Single-purpose token cannot be used for API access",
        )

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    if not session_is_current(payload, user):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This session has ended. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_staff(current_user = Depends(get_current_user)):
    if current_user.role not in ["staff", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff access required",
        )
    return current_user


async def get_current_admin(current_user = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def get_current_researcher(current_user = Depends(get_current_user)):
    """Require researcher or admin role for Research Suite access"""
    if current_user.role not in ["researcher", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Researcher access required",
        )
    return current_user

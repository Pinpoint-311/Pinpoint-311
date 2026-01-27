"""
Auth0 Service for SSO Authentication

Provides secure single sign-on using Auth0's Universal Login.
Supports Google, Microsoft, and other identity providers configured in Auth0.
Includes built-in MFA support.
"""

import httpx
import logging
from typing import Optional, Dict, Any
from jose import jwt, JWTError
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


async def get_auth0_config() -> Optional[Dict[str, str]]:
    """Get Auth0 configuration from SystemSecrets."""
    from app.db.session import SessionLocal
    from app.models import SystemSecret
    from app.core.encryption import decrypt_safe
    from sqlalchemy import select
    
    async with SessionLocal() as db:
        result = await db.execute(
            select(SystemSecret).where(
                SystemSecret.key_name.in_([
                    "AUTH0_DOMAIN",
                    "AUTH0_CLIENT_ID",
                    "AUTH0_CLIENT_SECRET",
                    "AUTH0_AUDIENCE",
                ])
            )
        )
        secrets = result.scalars().all()
        
        config = {}
        for secret in secrets:
            if secret.key_value and secret.is_configured:
                key = secret.key_name.replace("AUTH0_", "").lower()
                config[key] = decrypt_safe(secret.key_value)
        
        # Check required keys
        required = ["domain", "client_id", "client_secret"]
        if not all(k in config for k in required):
            logger.warning("Auth0 not configured - missing required secrets")
            return None
        
        return config


async def get_auth0_status() -> Dict[str, Any]:
    """Get Auth0 configuration status."""
    config = await get_auth0_config()
    
    return {
        "configured": config is not None,
        "domain": config.get("domain", "").split(".")[0] + "..." if config else None,
    }


def get_auth0_login_url(redirect_uri: str, state: str) -> Optional[str]:
    """Generate Auth0 authorization URL for Universal Login."""
    import asyncio
    
    async def _get():
        config = await get_auth0_config()
        if not config:
            return None
        
        params = {
            "client_id": config["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
        }
        
        # Add audience if configured (for API access tokens)
        if config.get("audience"):
            params["audience"] = config["audience"]
        
        return f"https://{config['domain']}/authorize?{urlencode(params)}"
    
    # Handle both sync and async contexts
    try:
        loop = asyncio.get_running_loop()
        # We're in an async context, need to handle differently
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, _get())
            return future.result()
    except RuntimeError:
        # No running loop, safe to use asyncio.run
        return asyncio.run(_get())


async def exchange_auth0_code(code: str, redirect_uri: str) -> Optional[Dict[str, Any]]:
    """
    Exchange Auth0 authorization code for tokens and user info.
    
    Returns user profile with email, name, and Auth0 user ID.
    """
    config = await get_auth0_config()
    if not config:
        return None
    
    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for tokens
            token_response = await client.post(
                f"https://{config['domain']}/oauth/token",
                json={
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
                headers={"Content-Type": "application/json"}
            )
            
            if token_response.status_code != 200:
                logger.error(f"Auth0 token exchange failed: {token_response.text}")
                return None
            
            tokens = token_response.json()
            access_token = tokens.get("access_token")
            id_token = tokens.get("id_token")
            
            if not access_token:
                logger.error("No access token in Auth0 response")
                return None
            
            # Get user info from Auth0
            userinfo_response = await client.get(
                f"https://{config['domain']}/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if userinfo_response.status_code != 200:
                logger.error(f"Auth0 userinfo failed: {userinfo_response.text}")
                return None
            
            userinfo = userinfo_response.json()
            
            return {
                "provider": "auth0",
                "provider_id": userinfo.get("sub"),  # Auth0 user ID
                "email": userinfo.get("email"),
                "email_verified": userinfo.get("email_verified", False),
                "name": userinfo.get("name") or userinfo.get("nickname"),
                "picture": userinfo.get("picture"),
                "access_token": access_token,
                "id_token": id_token,
            }
            
    except Exception as e:
        logger.error(f"Auth0 OAuth error: {e}")
        return None


async def verify_auth0_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify an Auth0 access token or ID token.
    
    This is used for API authentication after initial login.
    """
    config = await get_auth0_config()
    if not config:
        return None
    
    try:
        # Get JWKS (JSON Web Key Set) from Auth0
        async with httpx.AsyncClient() as client:
            jwks_response = await client.get(
                f"https://{config['domain']}/.well-known/jwks.json"
            )
            
            if jwks_response.status_code != 200:
                logger.error("Failed to fetch Auth0 JWKS")
                return None
            
            jwks = jwks_response.json()
        
        # Decode and verify the token
        # Note: python-jose handles JWKS verification
        unverified_header = jwt.get_unverified_header(token)
        
        # Find the key
        rsa_key = {}
        for key in jwks.get("keys", []):
            if key.get("kid") == unverified_header.get("kid"):
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"]
                }
                break
        
        if not rsa_key:
            logger.error("Unable to find matching Auth0 key")
            return None
        
        # Verify the token
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=config.get("audience") or config["client_id"],
            issuer=f"https://{config['domain']}/"
        )
        
        return payload
        
    except JWTError as e:
        logger.warning(f"Auth0 token verification failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Auth0 token verification error: {e}")
        return None


def get_auth0_logout_url(return_to: str) -> Optional[str]:
    """Generate Auth0 logout URL."""
    import asyncio
    
    async def _get():
        config = await get_auth0_config()
        if not config:
            return None
        
        params = {
            "client_id": config["client_id"],
            "returnTo": return_to,
        }
        
        return f"https://{config['domain']}/v2/logout?{urlencode(params)}"
    
    try:
        loop = asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, _get())
            return future.result()
    except RuntimeError:
        return asyncio.run(_get())

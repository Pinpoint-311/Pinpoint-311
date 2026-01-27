"""
Zitadel Service for SSO Authentication

Provides secure single sign-on using Zitadel Cloud.
Supports Google, Microsoft, passkeys, and other identity providers.
Includes built-in MFA support.

Configuration is stored in Google Secret Manager (production)
or encrypted database (local development).

Supports both JWT (private key) and client secret authentication.
"""

import httpx
import logging
import time
import json
from typing import Optional, Dict, Any
from jose import jwt, JWTError
from urllib.parse import urlencode
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)


async def get_zitadel_config() -> Optional[Dict[str, str]]:
    """Get Zitadel configuration from Secret Manager or database."""
    from app.services.secret_manager import get_secrets_bundle
    
    # Get all Zitadel secrets
    secrets = await get_secrets_bundle("ZITADEL_")
    
    if not secrets:
        logger.warning("Zitadel not configured - no secrets found")
        return None
    
    config = {}
    for key, value in secrets.items():
        # Convert ZITADEL_DOMAIN -> domain, ZITADEL_CLIENT_ID -> client_id
        config_key = key.replace("ZITADEL_", "").lower()
        config[config_key] = value
    
    # Check required keys - either JWT or client secret
    has_jwt = "jwt_private_key" in config
    has_secret = "client_secret" in config
    
    if not (has_jwt or has_secret):
        logger.warning("Zitadel missing authentication: need either JWT_PRIVATE_KEY or CLIENT_SECRET")
        return None
    
    if "domain" not in config or "client_id" not in config:
        logger.warning("Zitadel missing required config: domain and client_id")
        return None
    
    return config


def create_jwt_assertion(config: Dict[str, str]) -> str:
    """Create a JWT assertion for client authentication using private key."""
    domain = config["domain"]
    if domain.startswith("http"):
        base_url = domain
    else:
        base_url = f"https://{domain}"
    
    # Parse the private key
    private_key_pem = config["jwt_private_key"]
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode(),
        password=None,
        backend=default_backend()
    )
    
    # Create JWT payload
    now = int(time.time())
    payload = {
        "iss": config["client_id"],
        "sub": config["client_id"],
        "aud": f"{base_url}/oauth/v2/token",
        "iat": now,
        "exp": now + 300,  # 5 minutes
    }
    
    # Sign the JWT with RS256
    token = jwt.encode(
        payload,
        private_key,
        algorithm="RS256"
    )
    
    return token


async def get_zitadel_status() -> Dict[str, Any]:
    """Get Zitadel configuration status."""
    config = await get_zitadel_config()
    
    return {
        "configured": config is not None,
        "provider": "zitadel" if config else None,
    }


async def get_zitadel_login_url(redirect_uri: str, state: str) -> Optional[str]:
    """Generate Zitadel authorization URL for OIDC login."""
    config = await get_zitadel_config()
    if not config:
        return None
    
    domain = config["domain"]
    # Handle both internal Docker and external domains
    if domain.startswith("http"):
        base_url = domain
    else:
        base_url = f"https://{domain}"
    
    params = {
        "client_id": config["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    }
    
    return f"{base_url}/oauth/v2/authorize?{urlencode(params)}"


async def exchange_zitadel_code(code: str, redirect_uri: str) -> Optional[Dict[str, Any]]:
    """
    Exchange Zitadel authorization code for tokens and user info.
    
    Returns user profile with email, name, and Zitadel user ID.
    Supports both JWT (private key) and client secret authentication.
    """
    config = await get_zitadel_config()
    if not config:
        return None
    
    domain = config["domain"]
    if domain.startswith("http"):
        base_url = domain
    else:
        base_url = f"https://{domain}"
    
    try:
        async with httpx.AsyncClient() as client:
            # Prepare token request data
            token_data = {
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
            
            # Use JWT assertion if private key is configured
            if "jwt_private_key" in config:
                logger.info("Using JWT assertion for Zitadel authentication")
                jwt_assertion = create_jwt_assertion(config)
                token_data.update({
                    "client_id": config["client_id"],
                    "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                    "client_assertion": jwt_assertion,
                })
            else:
                # Fall back to client secret
                logger.info("Using client secret for Zitadel authentication")
                token_data.update({
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                })
            
            # Exchange code for tokens
            token_response = await client.post(
                f"{base_url}/oauth/v2/token",
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if token_response.status_code != 200:
                logger.error(f"Zitadel token exchange failed: {token_response.text}")
                return None
            
            tokens = token_response.json()
            access_token = tokens.get("access_token")
            id_token = tokens.get("id_token")
            
            if not access_token:
                logger.error("No access token in Zitadel response")
                return None
            
            # Get user info from Zitadel
            userinfo_response = await client.get(
                f"{base_url}/oidc/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if userinfo_response.status_code != 200:
                logger.error(f"Zitadel userinfo failed: {userinfo_response.text}")
                return None
            
            userinfo = userinfo_response.json()
            
            return {
                "provider": "zitadel",
                "provider_id": userinfo.get("sub"),  # Zitadel user ID
                "email": userinfo.get("email"),
                "email_verified": userinfo.get("email_verified", False),
                "name": userinfo.get("name") or userinfo.get("preferred_username"),
                "picture": userinfo.get("picture"),
                "access_token": access_token,
                "id_token": id_token,
            }
            
    except Exception as e:
        logger.error(f"Zitadel OAuth error: {e}")
        return None


async def verify_zitadel_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify a Zitadel access token or ID token.
    
    This is used for API authentication after initial login.
    """
    config = await get_zitadel_config()
    if not config:
        return None
    
    domain = config["domain"]
    if domain.startswith("http"):
        base_url = domain
    else:
        base_url = f"https://{domain}"
    
    try:
        # Get JWKS (JSON Web Key Set) from Zitadel
        async with httpx.AsyncClient() as client:
            jwks_response = await client.get(
                f"{base_url}/oauth/v2/keys"
            )
            
            if jwks_response.status_code != 200:
                logger.error("Failed to fetch Zitadel JWKS")
                return None
            
            jwks = jwks_response.json()
        
        # Decode and verify the token
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
            logger.error("Unable to find matching Zitadel key")
            return None
        
        # Verify the token
        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=config["client_id"],
            issuer=base_url
        )
        
        return payload
        
    except JWTError as e:
        logger.warning(f"Zitadel token verification failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Zitadel token verification error: {e}")
        return None


async def get_zitadel_logout_url(return_to: str) -> Optional[str]:
    """Generate Zitadel logout URL."""
    config = await get_zitadel_config()
    if not config:
        return None
    
    domain = config["domain"]
    if domain.startswith("http"):
        base_url = domain
    else:
        base_url = f"https://{domain}"
    
    params = {
        "client_id": config["client_id"],
        "post_logout_redirect_uri": return_to,
    }
    
    return f"{base_url}/oidc/v1/end_session?{urlencode(params)}"

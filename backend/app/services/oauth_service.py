"""
OAuth Service for Google and Microsoft SSO

Provides secure single sign-on authentication using OAuth 2.0 / OpenID Connect.
Supports Google Sign-In and Microsoft Entra ID (Azure AD).
"""

import httpx
import logging
from typing import Optional, Dict, Any
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# OAuth endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

MICROSOFT_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MICROSOFT_USERINFO_URL = "https://graph.microsoft.com/v1.0/me"


async def get_oauth_config(provider: str) -> Optional[Dict[str, str]]:
    """Get OAuth configuration from Secret Manager."""
    from app.services.secret_manager import get_secret
    
    provider_upper = provider.upper()
    
    # Get secrets from Secret Manager (checks GCP first, then DB)
    client_id = await get_secret(f"OAUTH_{provider_upper}_CLIENT_ID")
    client_secret = await get_secret(f"OAUTH_{provider_upper}_CLIENT_SECRET")
    redirect_uri = await get_secret(f"OAUTH_{provider_upper}_REDIRECT_URI")
    
    # Check required keys
    if not client_id or not client_secret:
        logger.warning(f"{provider} OAuth not configured - missing required secrets")
        return None
    
    config = {
        "client_id": client_id,
        "client_secret": client_secret,
    }
    if redirect_uri:
        config["redirect_uri"] = redirect_uri
    
    return config



def get_google_auth_url(redirect_uri: str, state: str) -> Optional[str]:
    """Generate Google OAuth authorization URL."""
    import asyncio
    
    async def _get():
        config = await get_oauth_config("google")
        if not config:
            return None
        
        params = {
            "client_id": config["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    
    # Run async function
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _get())
                return future.result()
        return asyncio.run(_get())
    except:
        return asyncio.run(_get())


async def exchange_google_code(code: str, redirect_uri: str) -> Optional[Dict[str, Any]]:
    """Exchange Google authorization code for tokens and user info."""
    config = await get_oauth_config("google")
    if not config:
        return None
    
    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for tokens
            token_response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                }
            )
            
            if token_response.status_code != 200:
                logger.error(f"Google token exchange failed: {token_response.text}")
                return None
            
            tokens = token_response.json()
            access_token = tokens.get("access_token")
            
            if not access_token:
                return None
            
            # Get user info
            userinfo_response = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if userinfo_response.status_code != 200:
                logger.error(f"Google userinfo failed: {userinfo_response.text}")
                return None
            
            userinfo = userinfo_response.json()
            
            return {
                "provider": "google",
                "provider_id": userinfo.get("id"),
                "email": userinfo.get("email"),
                "email_verified": userinfo.get("verified_email", False),
                "name": userinfo.get("name"),
                "picture": userinfo.get("picture"),
            }
            
    except Exception as e:
        logger.error(f"Google OAuth error: {e}")
        return None


def get_microsoft_auth_url(redirect_uri: str, state: str) -> Optional[str]:
    """Generate Microsoft OAuth authorization URL."""
    import asyncio
    
    async def _get():
        config = await get_oauth_config("microsoft")
        if not config:
            return None
        
        params = {
            "client_id": config["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile User.Read",
            "state": state,
            "response_mode": "query",
        }
        return f"{MICROSOFT_AUTH_URL}?{urlencode(params)}"
    
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, _get())
                return future.result()
        return asyncio.run(_get())
    except:
        return asyncio.run(_get())


async def exchange_microsoft_code(code: str, redirect_uri: str) -> Optional[Dict[str, Any]]:
    """Exchange Microsoft authorization code for tokens and user info."""
    config = await get_oauth_config("microsoft")
    if not config:
        return None
    
    try:
        async with httpx.AsyncClient() as client:
            # Exchange code for tokens
            token_response = await client.post(
                MICROSOFT_TOKEN_URL,
                data={
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                }
            )
            
            if token_response.status_code != 200:
                logger.error(f"Microsoft token exchange failed: {token_response.text}")
                return None
            
            tokens = token_response.json()
            access_token = tokens.get("access_token")
            
            if not access_token:
                return None
            
            # Get user info from Microsoft Graph
            userinfo_response = await client.get(
                MICROSOFT_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if userinfo_response.status_code != 200:
                logger.error(f"Microsoft userinfo failed: {userinfo_response.text}")
                return None
            
            userinfo = userinfo_response.json()
            
            return {
                "provider": "microsoft",
                "provider_id": userinfo.get("id"),
                "email": userinfo.get("mail") or userinfo.get("userPrincipalName"),
                "email_verified": True,  # Microsoft accounts are always verified
                "name": userinfo.get("displayName"),
                "picture": None,  # Microsoft Graph requires separate call for photo
            }
            
    except Exception as e:
        logger.error(f"Microsoft OAuth error: {e}")
        return None


async def get_sso_status() -> Dict[str, Any]:
    """Get SSO configuration status for both providers."""
    google_config = await get_oauth_config("google")
    microsoft_config = await get_oauth_config("microsoft")
    
    return {
        "google": {
            "configured": google_config is not None,
            "client_id_set": bool(google_config.get("client_id")) if google_config else False,
        },
        "microsoft": {
            "configured": microsoft_config is not None,
            "client_id_set": bool(microsoft_config.get("client_id")) if microsoft_config else False,
        }
    }

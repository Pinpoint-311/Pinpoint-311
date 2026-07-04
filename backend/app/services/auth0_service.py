"""
Auth0 authentication service using pure OAuth 2.0 / OpenID Connect.
Clean abstraction with no Auth0 SDK dependencies.
"""

import httpx
import jwt
from typing import Optional, Dict, Any
from fastapi import HTTPException
from sqlalchemy.orm import Session



class Auth0Service:
    """
    OIDC authentication (Auth0 default; Entra ID / Okta / generic OIDC also
    supported). Auth0's code paths are preserved byte-for-byte; other providers
    are handled through the standards-based generic OIDC layer
    (app/services/identity.py). Config stored via SystemSecret / Secret Manager.
    """

    @staticmethod
    async def _active_provider() -> str:
        from app.services.secret_manager import get_secret
        return ((await get_secret("IDENTITY_PROVIDER")) or "auth0").strip().lower()

    @staticmethod
    async def is_identity_configured(db: Session) -> bool:
        """True if ANY identity provider is configured (used by the bootstrap
        gate so a non-Auth0 deployment doesn't leave passwordless bootstrap open)."""
        from app.services.identity import resolve_identity_config
        return (await resolve_identity_config(db)) is not None

    @staticmethod
    async def get_config(db: Session) -> Optional[Dict[str, str]]:
        """
        Retrieve Auth0 configuration from Secret Manager (GCP) or database fallback.
        
        Returns dict with: domain, client_id, client_secret
        Returns None if not configured.
        """
        from app.services.secret_manager import get_secret
        
        # Use Secret Manager (checks GCP first, falls back to DB)
        domain = await get_secret("AUTH0_DOMAIN")
        client_id = await get_secret("AUTH0_CLIENT_ID")
        client_secret = await get_secret("AUTH0_CLIENT_SECRET")
        
        if not all([domain, client_id, client_secret]):
            return None
        
        return {
            "domain": domain,
            "client_id": client_id,
            "client_secret": client_secret
        }

    
    @staticmethod
    async def get_authorization_url(
        redirect_uri: str,
        state: str,
        db: Session
    ) -> str:
        """
        Generate Auth0 authorization URL for OAuth flow.
        
        Args:
            redirect_uri: Where Auth0 should redirect after login
            state: CSRF protection token
            db: Database session
        
        Returns:
            Full authorization URL to redirect user to
        """
        # Non-Auth0 providers → standards-based generic OIDC via discovery
        if await Auth0Service._active_provider() != "auth0":
            from app.services.identity import resolve_identity_config, get_oidc_metadata
            idc = await resolve_identity_config(db)
            if not idc:
                raise HTTPException(status_code=500, detail="Identity provider not configured")
            meta = await get_oidc_metadata(idc)
            params = {
                "response_type": "code",
                "client_id": idc["client_id"],
                "redirect_uri": redirect_uri,
                "scope": "openid profile email",
                "state": state,
                **(idc.get("extra_authorize_params") or {}),
            }
            query_string = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
            return f"{meta['authorization_endpoint']}?{query_string}"

        config = await Auth0Service.get_config(db)
        if not config:
            raise HTTPException(status_code=500, detail="Auth0 not configured")

        domain = config["domain"]
        client_id = config["client_id"]

        # Build authorization URL
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email",
            "state": state,
            "audience": f"https://{domain}/api/v2/"  # For API access tokens
        }

        query_string = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
        return f"https://{domain}/authorize?{query_string}"
    
    @staticmethod
    async def exchange_code_for_tokens(
        code: str,
        redirect_uri: str,
        db: Session
    ) -> Dict[str, Any]:
        """
        Exchange authorization code for access token and ID token.
        
        Args:
            code: Authorization code from Auth0 callback
            redirect_uri: Same redirect URI used in authorization request
            db: Database session
        
        Returns:
            Dict with: access_token, id_token, token_type, expires_in
        """
        # Non-Auth0 providers → generic OIDC token endpoint (form-encoded, per spec)
        if await Auth0Service._active_provider() != "auth0":
            from app.services.identity import resolve_identity_config, get_oidc_metadata
            idc = await resolve_identity_config(db)
            if not idc:
                raise HTTPException(status_code=500, detail="Identity provider not configured")
            meta = await get_oidc_metadata(idc)
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    meta["token_endpoint"],
                    data={
                        "grant_type": "authorization_code",
                        "client_id": idc["client_id"],
                        "client_secret": idc["client_secret"],
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            if response.status_code != 200:
                detail = response.json().get("error_description", "Token exchange failed") if response.headers.get("content-type", "").startswith("application/json") else "Token exchange failed"
                raise HTTPException(status_code=400, detail=detail)
            return response.json()

        config = await Auth0Service.get_config(db)
        if not config:
            raise HTTPException(status_code=500, detail="Auth0 not configured")

        domain = config["domain"]
        client_id = config["client_id"]
        client_secret = config["client_secret"]

        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://{domain}/oauth/token",
                json={
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri
                },
                headers={
                    "Content-Type": "application/json"
                }
            )

            if response.status_code != 200:
                error_detail = response.json().get("error_description", "Token exchange failed")
                raise HTTPException(status_code=400, detail=error_detail)

            return response.json()
    
    @staticmethod
    async def get_jwks(domain: str) -> Dict[str, Any]:
        """
        Fetch JSON Web Key Set (JWKS) from Auth0 for JWT verification.
        
        Args:
            domain: Auth0 domain
        
        Returns:
            JWKS dictionary
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://{domain}/.well-known/jwks.json")
            response.raise_for_status()
            return response.json()
    
    @staticmethod
    async def verify_token(token: str, db: Session) -> Dict[str, Any]:
        """
        Verify and decode JWT token from Auth0.
        
        Args:
            token: JWT access token or ID token
            db: Database session
        
        Returns:
            Decoded token payload
        """
        # Non-Auth0 providers → standards-based generic OIDC verification
        if await Auth0Service._active_provider() != "auth0":
            from app.services.identity import resolve_identity_config, verify_oidc_token
            idc = await resolve_identity_config(db)
            if not idc:
                raise HTTPException(status_code=500, detail="Identity provider not configured")
            return await verify_oidc_token(token, idc)

        config = await Auth0Service.get_config(db)
        if not config:
            raise HTTPException(status_code=500, detail="Auth0 not configured")

        domain = config["domain"]
        client_id = config["client_id"]

        # Get JWKS for verification
        jwks = await Auth0Service.get_jwks(domain)
        
        # Decode header to get key ID (kid)
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        
        # Find the matching key
        key = None
        for jwk in jwks.get("keys", []):
            if jwk.get("kid") == kid:
                key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
                break
        
        if not key:
            raise HTTPException(status_code=401, detail="Unable to find appropriate key")
        
        # Verify and decode token
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=f"https://{domain}/"
            )
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.JWTClaimsError:
            raise HTTPException(status_code=401, detail="Invalid token claims")
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Token validation failed: {str(e)}")
    
    @staticmethod
    async def get_user_info(access_token: str, db: Session) -> Dict[str, Any]:
        """
        Fetch user profile information from Auth0.
        
        Args:
            access_token: Auth0 access token
            db: Database session
        
        Returns:
            User profile dict
        """
        # Non-Auth0 providers → generic userinfo endpoint from discovery
        if await Auth0Service._active_provider() != "auth0":
            from app.services.identity import resolve_identity_config, get_oidc_metadata
            idc = await resolve_identity_config(db)
            if not idc:
                raise HTTPException(status_code=500, detail="Identity provider not configured")
            meta = await get_oidc_metadata(idc)
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    meta["userinfo_endpoint"],
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to fetch user info")
            return response.json()

        config = await Auth0Service.get_config(db)
        if not config:
            raise HTTPException(status_code=500, detail="Auth0 not configured")

        domain = config["domain"]

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://{domain}/userinfo",
                headers={
                    "Authorization": f"Bearer {access_token}"
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to fetch user info")
            
            return response.json()
    
    @staticmethod
    async def check_status(db: Session) -> Dict[str, Any]:
        """
        Check Auth0 configuration status for health check.
        
        Returns:
            Dict with status, domain, client_id (masked), and connectivity
        """
        config = await Auth0Service.get_config(db)
        
        if not config:
            return {
                "status": "not_configured",
                "message": "Auth0 is not configured"
            }
        
        domain = config["domain"]
        client_id = config["client_id"]
        
        # Test OIDC discovery endpoint
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"https://{domain}/.well-known/openid-configuration"
                )
                oidc_reachable = response.status_code == 200
        except Exception:
            oidc_reachable = False
        
        return {
            "status": "configured" if oidc_reachable else "error",
            "message": "Auth0 is configured and reachable" if oidc_reachable else "Auth0 configured but unreachable",
            "domain": domain,
            "client_id": f"{client_id[:10]}...",  # Mask for security
            "oidc_discovery": "reachable" if oidc_reachable else "unreachable"
        }

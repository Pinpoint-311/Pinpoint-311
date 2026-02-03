"""
Social Connections Configuration API

Endpoints to configure Google and Microsoft OAuth credentials for Auth0 social login.
Credentials are processed in-memory and never persisted to the database.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field
from typing import Optional, List
import logging
import httpx

from app.db.session import get_db
from app.core.auth import get_current_user
from app.models import User, SystemSecret
from app.services.audit_service import AuditService
from app.core.encryption import decrypt_safe

router = APIRouter()
logger = logging.getLogger(__name__)


# Request Models
class GoogleOAuthRequest(BaseModel):
    """Google OAuth 2.0 credentials"""
    client_id: str = Field(..., description="Google OAuth Client ID")
    client_secret: str = Field(..., description="Google OAuth Client Secret")


class MicrosoftOAuthRequest(BaseModel):
    """Microsoft/Azure AD OAuth credentials"""
    client_id: str = Field(..., description="Azure App Client ID")
    client_secret: str = Field(..., description="Azure App Client Secret")
    tenant_id: Optional[str] = Field(default="common", description="Azure Tenant ID (default: 'common' for multi-tenant)")


class SocialConnectionStatus(BaseModel):
    """Status of social connections"""
    google: bool = False
    microsoft: bool = False
    google_error: Optional[str] = None
    microsoft_error: Optional[str] = None


async def get_auth0_management_token(domain: str, client_id: str, client_secret: str) -> str:
    """Get Auth0 Management API access token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{domain}/oauth/token",
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "audience": f"https://{domain}/api/v2/",
                "grant_type": "client_credentials"
            }
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to get Auth0 Management API token: {response.text}"
            )
        
        return response.json()["access_token"]


async def get_auth0_credentials(db: AsyncSession) -> tuple[str, str, str]:
    """Get stored Auth0 credentials from database"""
    result = await db.execute(
        select(SystemSecret).where(SystemSecret.key_name.in_([
            "AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET",
            "AUTH0_MANAGEMENT_CLIENT_ID", "AUTH0_MANAGEMENT_CLIENT_SECRET"
        ]))
    )
    secrets = {s.key_name: decrypt_safe(s.key_value) for s in result.scalars().all()}
    
    domain = secrets.get("AUTH0_DOMAIN")
    # Prefer management API credentials if available
    mgmt_client_id = secrets.get("AUTH0_MANAGEMENT_CLIENT_ID") or secrets.get("AUTH0_CLIENT_ID")
    mgmt_client_secret = secrets.get("AUTH0_MANAGEMENT_CLIENT_SECRET") or secrets.get("AUTH0_CLIENT_SECRET")
    
    if not all([domain, mgmt_client_id, mgmt_client_secret]):
        raise HTTPException(
            status_code=400,
            detail="Auth0 is not configured. Please complete Auth0 setup first."
        )
    
    return domain, mgmt_client_id, mgmt_client_secret


@router.get("/status")
async def get_social_connection_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> SocialConnectionStatus:
    """
    Get the status of configured social connections in Auth0.
    
    **Admin only.**
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    status = SocialConnectionStatus()
    
    try:
        domain, mgmt_client_id, mgmt_client_secret = await get_auth0_credentials(db)
        access_token = await get_auth0_management_token(domain, mgmt_client_id, mgmt_client_secret)
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            # Check Google connection
            google_response = await client.get(
                f"https://{domain}/api/v2/connections",
                headers=headers,
                params={"strategy": "google-oauth2"}
            )
            if google_response.status_code == 200:
                google_conns = google_response.json()
                # Check if any connection has credentials configured (not just dev keys)
                status.google = any(
                    conn.get("options", {}).get("client_id") 
                    for conn in google_conns
                )
            
            # Check Microsoft connection
            ms_response = await client.get(
                f"https://{domain}/api/v2/connections",
                headers=headers,
                params={"strategy": "windowslive"}
            )
            if ms_response.status_code == 200:
                ms_conns = ms_response.json()
                status.microsoft = any(
                    conn.get("options", {}).get("client_id")
                    for conn in ms_conns
                )
                
    except HTTPException as e:
        status.google_error = str(e.detail)
        status.microsoft_error = str(e.detail)
    except Exception as e:
        logger.error(f"Error checking social connection status: {e}")
        status.google_error = str(e)[:100]
        status.microsoft_error = str(e)[:100]
    
    return status


@router.post("/google")
async def configure_google_oauth(
    request: GoogleOAuthRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Configure Google OAuth for Auth0 social login.
    
    Credentials are used to configure Auth0 and are NOT stored in the database.
    
    **Admin only.**
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        domain, mgmt_client_id, mgmt_client_secret = await get_auth0_credentials(db)
        access_token = await get_auth0_management_token(domain, mgmt_client_id, mgmt_client_secret)
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            # Check if google-oauth2 connection exists
            list_response = await client.get(
                f"https://{domain}/api/v2/connections",
                headers=headers,
                params={"strategy": "google-oauth2"}
            )
            
            existing_conns = list_response.json() if list_response.status_code == 200 else []
            
            # Get the main application client ID to enable the connection for it
            app_result = await db.execute(
                select(SystemSecret).where(SystemSecret.key_name == "AUTH0_CLIENT_ID")
            )
            app_secret = app_result.scalar_one_or_none()
            app_client_id = decrypt_safe(app_secret.key_value) if app_secret else None
            
            connection_options = {
                "client_id": request.client_id,
                "client_secret": request.client_secret,
                "scope": ["email", "profile", "openid"]
            }
            
            if existing_conns:
                # Update existing connection
                conn_id = existing_conns[0]["id"]
                enabled_clients = existing_conns[0].get("enabled_clients", [])
                
                if app_client_id and app_client_id not in enabled_clients:
                    enabled_clients.append(app_client_id)
                
                update_response = await client.patch(
                    f"https://{domain}/api/v2/connections/{conn_id}",
                    headers=headers,
                    json={
                        "options": connection_options,
                        "enabled_clients": enabled_clients
                    }
                )
                
                if update_response.status_code not in [200, 201]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to update Google connection: {update_response.text}"
                    )
            else:
                # Create new connection
                create_response = await client.post(
                    f"https://{domain}/api/v2/connections",
                    headers=headers,
                    json={
                        "name": "google-oauth2",
                        "strategy": "google-oauth2",
                        "options": connection_options,
                        "enabled_clients": [app_client_id] if app_client_id else []
                    }
                )
                
                if create_response.status_code not in [200, 201]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to create Google connection: {create_response.text}"
                    )
        
        # Log successful configuration (credentials are NOT logged)
        await AuditService.log_event(
            db=db,
            event_type="social_connection_configured",
            success=True,
            user_id=current_user.id,
            username=current_user.username,
            details={
                "provider": "google",
                "client_id_preview": f"{request.client_id[:20]}..." if len(request.client_id) > 20 else "[hidden]"
            }
        )
        
        logger.info(f"Google OAuth configured successfully by {current_user.username}")
        
        return {
            "success": True,
            "message": "Google OAuth configured successfully",
            "provider": "google"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google OAuth configuration failed: {e}")
        await AuditService.log_event(
            db=db,
            event_type="social_connection_failed",
            success=False,
            user_id=current_user.id,
            username=current_user.username,
            failure_reason=str(e)[:200],
            details={"provider": "google"}
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to configure Google OAuth: {str(e)}"
        )


@router.post("/microsoft")
async def configure_microsoft_oauth(
    request: MicrosoftOAuthRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Configure Microsoft/Azure AD OAuth for Auth0 social login.
    
    Credentials are used to configure Auth0 and are NOT stored in the database.
    
    **Admin only.**
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        domain, mgmt_client_id, mgmt_client_secret = await get_auth0_credentials(db)
        access_token = await get_auth0_management_token(domain, mgmt_client_id, mgmt_client_secret)
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            # Check if windowslive connection exists
            list_response = await client.get(
                f"https://{domain}/api/v2/connections",
                headers=headers,
                params={"strategy": "windowslive"}
            )
            
            existing_conns = list_response.json() if list_response.status_code == 200 else []
            
            # Get the main application client ID
            app_result = await db.execute(
                select(SystemSecret).where(SystemSecret.key_name == "AUTH0_CLIENT_ID")
            )
            app_secret = app_result.scalar_one_or_none()
            app_client_id = decrypt_safe(app_secret.key_value) if app_secret else None
            
            connection_options = {
                "client_id": request.client_id,
                "client_secret": request.client_secret,
                "tenant_domain": request.tenant_id or "common",
                "scope": ["openid", "profile", "email"]
            }
            
            if existing_conns:
                # Update existing connection
                conn_id = existing_conns[0]["id"]
                enabled_clients = existing_conns[0].get("enabled_clients", [])
                
                if app_client_id and app_client_id not in enabled_clients:
                    enabled_clients.append(app_client_id)
                
                update_response = await client.patch(
                    f"https://{domain}/api/v2/connections/{conn_id}",
                    headers=headers,
                    json={
                        "options": connection_options,
                        "enabled_clients": enabled_clients
                    }
                )
                
                if update_response.status_code not in [200, 201]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to update Microsoft connection: {update_response.text}"
                    )
            else:
                # Create new connection
                create_response = await client.post(
                    f"https://{domain}/api/v2/connections",
                    headers=headers,
                    json={
                        "name": "windowslive",
                        "strategy": "windowslive",
                        "options": connection_options,
                        "enabled_clients": [app_client_id] if app_client_id else []
                    }
                )
                
                if create_response.status_code not in [200, 201]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to create Microsoft connection: {create_response.text}"
                    )
        
        # Log successful configuration
        await AuditService.log_event(
            db=db,
            event_type="social_connection_configured",
            success=True,
            user_id=current_user.id,
            username=current_user.username,
            details={
                "provider": "microsoft",
                "tenant_id": request.tenant_id or "common"
            }
        )
        
        logger.info(f"Microsoft OAuth configured successfully by {current_user.username}")
        
        return {
            "success": True,
            "message": "Microsoft OAuth configured successfully",
            "provider": "microsoft"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Microsoft OAuth configuration failed: {e}")
        await AuditService.log_event(
            db=db,
            event_type="social_connection_failed",
            success=False,
            user_id=current_user.id,
            username=current_user.username,
            failure_reason=str(e)[:200],
            details={"provider": "microsoft"}
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to configure Microsoft OAuth: {str(e)}"
        )

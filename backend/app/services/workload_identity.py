"""
GCP Workload Identity Federation Service

Enables keyless GCP authentication by federating Auth0 identity with Google Cloud.
After initial setup with a service account key, the key self-destructs and all 
future authentication uses Auth0 OIDC tokens.

Flow:
1. Staff uploads service account JSON (temporary)
2. App creates Workload Identity Pool + OIDC provider
3. App grants IAM permissions to the pool
4. App tests federation works
5. App deletes service account key from database
6. Future access uses Auth0 → GCP token exchange
"""

import json
import logging
import os
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Federation configuration
POOL_ID = "pinpoint-311-federation"
PROVIDER_ID = "auth0-oidc"
POOL_DISPLAY_NAME = "Pinpoint 311 Federation"
PROVIDER_DISPLAY_NAME = "Auth0 OIDC Provider"


def _get_gcp_client_with_key():
    """Get GCP IAM client using the temporary service account key from database."""
    try:
        from google.oauth2 import service_account
        from google.cloud import iam_admin_v1
        from app.db.session import sync_engine
        from app.core.encryption import decrypt_safe
        from sqlalchemy import text
        
        with sync_engine.connect() as conn:
            result = conn.execute(
                text("SELECT key_value FROM system_secrets WHERE key_name = 'GCP_SERVICE_ACCOUNT_JSON'")
            )
            row = result.fetchone()
            if not row or not row[0]:
                return None, None, "Service account key not found in database"
            
            sa_json = decrypt_safe(row[0])
            if not sa_json:
                return None, None, "Failed to decrypt service account key"
            
            sa_data = json.loads(sa_json)
            project_id = sa_data.get("project_id")
            
            credentials = service_account.Credentials.from_service_account_info(
                sa_data,
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            
            return credentials, project_id, None
            
    except Exception as e:
        logger.error(f"Failed to get GCP client: {e}")
        return None, None, str(e)


def _get_auth0_config() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Get Auth0 configuration from database."""
    try:
        from app.db.session import sync_engine
        from app.core.encryption import decrypt_safe
        from sqlalchemy import text
        
        with sync_engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT key_name, key_value FROM system_secrets 
                    WHERE key_name IN ('AUTH0_DOMAIN', 'AUTH0_CLIENT_ID', 'AUTH0_CLIENT_SECRET')
                """)
            )
            rows = {row[0]: decrypt_safe(row[1]) for row in result.fetchall()}
            
            domain = rows.get("AUTH0_DOMAIN")
            client_id = rows.get("AUTH0_CLIENT_ID")
            client_secret = rows.get("AUTH0_CLIENT_SECRET")
            
            if not all([domain, client_id, client_secret]):
                return None, None, "Auth0 not fully configured"
            
            return domain, client_id, None
            
    except Exception as e:
        logger.error(f"Failed to get Auth0 config: {e}")
        return None, None, str(e)


async def setup_federation() -> Dict[str, Any]:
    """
    Create Workload Identity Pool and OIDC provider for Auth0 federation.
    
    This is a one-time setup that uses the temporary service account key
    to create the federation infrastructure.
    
    Returns:
        Dict with status, pool_name, provider_name, or error
    """
    import httpx
    
    # Get credentials from temporary service account key
    credentials, project_id, error = _get_gcp_client_with_key()
    if error:
        return {"status": "error", "error": error}
    
    # Get Auth0 configuration
    auth0_domain, auth0_client_id, error = _get_auth0_config()
    if error:
        return {"status": "error", "error": error}
    
    issuer_uri = f"https://{auth0_domain}/"
    
    try:
        # Get access token
        from google.auth.transport.requests import Request
        credentials.refresh(Request())
        access_token = credentials.token
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            # Step 1: Create Workload Identity Pool
            pool_parent = f"projects/{project_id}/locations/global"
            pool_name = f"{pool_parent}/workloadIdentityPools/{POOL_ID}"
            
            # Check if pool exists
            check_resp = await client.get(
                f"https://iam.googleapis.com/v1/{pool_name}",
                headers=headers
            )
            
            if check_resp.status_code == 404:
                # Create pool
                pool_body = {
                    "displayName": POOL_DISPLAY_NAME,
                    "description": "Workload Identity Pool for Pinpoint 311 Auth0 federation"
                }
                
                create_resp = await client.post(
                    f"https://iam.googleapis.com/v1/{pool_parent}/workloadIdentityPools?workloadIdentityPoolId={POOL_ID}",
                    headers=headers,
                    json=pool_body
                )
                
                if create_resp.status_code not in [200, 201]:
                    # Check if it's a long-running operation
                    if "operation" in create_resp.text.lower():
                        # Wait for operation to complete
                        import asyncio
                        await asyncio.sleep(5)
                    elif create_resp.status_code != 409:  # 409 = already exists
                        return {
                            "status": "error",
                            "error": f"Failed to create pool: {create_resp.text}",
                            "step": "create_pool"
                        }
                
                logger.info(f"Created Workload Identity Pool: {POOL_ID}")
            else:
                logger.info(f"Workload Identity Pool already exists: {POOL_ID}")
            
            # Step 2: Create OIDC Provider
            provider_name = f"{pool_name}/providers/{PROVIDER_ID}"
            
            check_provider = await client.get(
                f"https://iam.googleapis.com/v1/{provider_name}",
                headers=headers
            )
            
            if check_provider.status_code == 404:
                provider_body = {
                    "displayName": PROVIDER_DISPLAY_NAME,
                    "description": "Auth0 OIDC provider for Pinpoint 311",
                    "oidc": {
                        "issuerUri": issuer_uri,
                        "allowedAudiences": [auth0_client_id]
                    },
                    "attributeMapping": {
                        "google.subject": "assertion.sub",
                        "attribute.aud": "assertion.aud"
                    }
                }
                
                create_provider_resp = await client.post(
                    f"https://iam.googleapis.com/v1/{pool_name}/providers?workloadIdentityPoolProviderId={PROVIDER_ID}",
                    headers=headers,
                    json=provider_body
                )
                
                if create_provider_resp.status_code not in [200, 201]:
                    if "operation" in create_provider_resp.text.lower():
                        import asyncio
                        await asyncio.sleep(5)
                    elif create_provider_resp.status_code != 409:
                        return {
                            "status": "error",
                            "error": f"Failed to create provider: {create_provider_resp.text}",
                            "step": "create_provider"
                        }
                
                logger.info(f"Created OIDC Provider: {PROVIDER_ID}")
            else:
                logger.info(f"OIDC Provider already exists: {PROVIDER_ID}")
            
            # Step 3: Grant IAM permissions
            # Grant the federated identity access to Secret Manager and KMS
            project_number = await _get_project_number(client, project_id, headers)
            
            if project_number:
                member = f"principalSet://iam.googleapis.com/projects/{project_number}/locations/global/workloadIdentityPools/{POOL_ID}/*"
                
                # Get current IAM policy
                policy_resp = await client.post(
                    f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}:getIamPolicy",
                    headers=headers,
                    json={}
                )
                
                if policy_resp.status_code == 200:
                    policy = policy_resp.json()
                    bindings = policy.get("bindings", [])
                    
                    # Add Secret Manager accessor role
                    roles_to_add = [
                        "roles/secretmanager.secretAccessor",
                        "roles/secretmanager.secretVersionManager",
                        "roles/cloudkms.cryptoKeyEncrypterDecrypter"
                    ]
                    
                    for role in roles_to_add:
                        role_binding = next(
                            (b for b in bindings if b.get("role") == role), 
                            None
                        )
                        if role_binding:
                            if member not in role_binding.get("members", []):
                                role_binding.setdefault("members", []).append(member)
                        else:
                            bindings.append({
                                "role": role,
                                "members": [member]
                            })
                    
                    policy["bindings"] = bindings
                    
                    # Set updated policy
                    set_policy_resp = await client.post(
                        f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}:setIamPolicy",
                        headers=headers,
                        json={"policy": policy}
                    )
                    
                    if set_policy_resp.status_code != 200:
                        logger.warning(f"Failed to set IAM policy: {set_policy_resp.text}")
                    else:
                        logger.info("IAM permissions granted to federation pool")
            
            # Store federation config in database
            await _store_federation_config(project_id, project_number, auth0_domain, auth0_client_id)
            
            return {
                "status": "success",
                "pool_name": pool_name,
                "provider_name": provider_name,
                "issuer": issuer_uri,
                "message": "Federation setup complete. You can now delete the service account key."
            }
            
    except Exception as e:
        logger.error(f"Federation setup failed: {e}")
        return {"status": "error", "error": str(e)}


async def _get_project_number(client, project_id: str, headers: dict) -> Optional[str]:
    """Get the numeric project number from project ID."""
    try:
        resp = await client.get(
            f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}",
            headers=headers
        )
        if resp.status_code == 200:
            return resp.json().get("projectNumber")
    except Exception as e:
        logger.error(f"Failed to get project number: {e}")
    return None


async def _store_federation_config(project_id: str, project_number: str, auth0_domain: str, auth0_client_id: str):
    """Store federation configuration for future credential fetching."""
    from app.db.session import SessionLocal
    from app.models import SystemSecret
    from app.core.encryption import encrypt
    from sqlalchemy import select
    
    config = {
        "project_id": project_id,
        "project_number": project_number,
        "pool_id": POOL_ID,
        "provider_id": PROVIDER_ID,
        "auth0_domain": auth0_domain,
        "auth0_client_id": auth0_client_id
    }
    
    async with SessionLocal() as db:
        result = await db.execute(
            select(SystemSecret).where(SystemSecret.key_name == "WORKLOAD_IDENTITY_CONFIG")
        )
        secret = result.scalar_one_or_none()
        
        encrypted_config = encrypt(json.dumps(config))
        
        if secret:
            secret.key_value = encrypted_config
            secret.is_configured = True
        else:
            secret = SystemSecret(
                key_name="WORKLOAD_IDENTITY_CONFIG",
                key_value=encrypted_config,
                description="Workload Identity Federation configuration",
                is_configured=True
            )
            db.add(secret)
        
        await db.commit()


async def test_federation() -> Dict[str, Any]:
    """
    Test that federation works by getting credentials via Auth0 and accessing GCP.
    
    Returns:
        Dict with status and test results
    """
    try:
        credentials = await get_federation_credentials()
        if not credentials:
            return {"status": "error", "error": "Failed to get federation credentials"}
        
        # Try to access Secret Manager
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient(credentials=credentials)
        
        # Just list secrets to verify access works
        config = await _get_federation_config()
        if not config:
            return {"status": "error", "error": "Federation config not found"}
        
        parent = f"projects/{config['project_id']}"
        list(client.list_secrets(request={"parent": parent}))
        
        return {
            "status": "success",
            "message": "Federation test passed - GCP access verified"
        }
        
    except Exception as e:
        logger.error(f"Federation test failed: {e}")
        return {"status": "error", "error": str(e)}


async def _get_federation_config() -> Optional[Dict[str, Any]]:
    """Get stored federation configuration."""
    from app.db.session import SessionLocal
    from app.models import SystemSecret
    from app.core.encryption import decrypt_safe
    from sqlalchemy import select
    
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(SystemSecret).where(SystemSecret.key_name == "WORKLOAD_IDENTITY_CONFIG")
            )
            secret = result.scalar_one_or_none()
            
            if secret and secret.key_value:
                config_json = decrypt_safe(secret.key_value)
                return json.loads(config_json)
    except Exception as e:
        logger.error(f"Failed to get federation config: {e}")
    
    return None


async def get_federation_credentials():
    """
    Get GCP credentials via Auth0 token exchange.
    
    Uses the Workload Identity Federation to exchange an Auth0 M2M token
    for short-lived GCP credentials.
    
    Returns:
        google.auth.credentials.Credentials or None
    """
    try:
        import httpx
        from google.auth import identity_pool
        from google.oauth2 import sts
        
        config = await _get_federation_config()
        if not config:
            logger.debug("No federation config found, federation not available")
            return None
        
        # Get Auth0 M2M token
        auth0_domain = config["auth0_domain"]
        
        # Get Auth0 credentials from database
        from app.db.session import SessionLocal
        from app.models import SystemSecret
        from app.core.encryption import decrypt_safe
        from sqlalchemy import select
        
        async with SessionLocal() as db:
            result = await db.execute(
                select(SystemSecret).where(
                    SystemSecret.key_name.in_(["AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET"])
                )
            )
            secrets = {s.key_name: decrypt_safe(s.key_value) for s in result.scalars()}
        
        client_id = secrets.get("AUTH0_CLIENT_ID")
        client_secret = secrets.get("AUTH0_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            logger.warning("Auth0 credentials not found for federation")
            return None
        
        # Get M2M token from Auth0
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                f"https://{auth0_domain}/oauth/token",
                json={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "audience": f"https://iam.googleapis.com/projects/{config['project_number']}/locations/global/workloadIdentityPools/{config['pool_id']}/providers/{config['provider_id']}"
                }
            )
            
            if token_resp.status_code != 200:
                logger.error(f"Failed to get Auth0 token: {token_resp.text}")
                return None
            
            auth0_token = token_resp.json().get("access_token")
        
        # Exchange for GCP credentials using STS
        audience = f"//iam.googleapis.com/projects/{config['project_number']}/locations/global/workloadIdentityPools/{config['pool_id']}/providers/{config['provider_id']}"
        
        # Create identity pool credentials
        credentials_config = {
            "type": "external_account",
            "audience": audience,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "token_url": "https://sts.googleapis.com/v1/token",
            "credential_source": {
                "file": None  # We'll provide the token directly
            }
        }
        
        # Use the STS client directly
        sts_client = sts.Client(token_exchange_endpoint="https://sts.googleapis.com/v1/token")
        
        response = sts_client.exchange_token(
            request=None,
            grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
            subject_token=auth0_token,
            subject_token_type="urn:ietf:params:oauth:token-type:jwt",
            audience=audience
        )
        
        # Create credentials from the exchanged token
        from google.oauth2 import credentials as oauth2_credentials
        
        return oauth2_credentials.Credentials(
            token=response.get("access_token"),
            expiry=None  # Will be refreshed as needed
        )
        
    except Exception as e:
        logger.error(f"Failed to get federation credentials: {e}")
        return None


def get_federation_credentials_sync():
    """Synchronous wrapper for get_federation_credentials."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(get_federation_credentials())
    except RuntimeError:
        # No event loop, create new one
        return asyncio.run(get_federation_credentials())


async def delete_bootstrap_key() -> Dict[str, Any]:
    """
    Delete the service account key from database after federation is verified.
    
    This is the "self-destruct" step that removes the temporary bootstrap key.
    
    Returns:
        Dict with status
    """
    from app.db.session import SessionLocal
    from app.models import SystemSecret
    from sqlalchemy import delete
    
    try:
        async with SessionLocal() as db:
            # Delete the service account key
            await db.execute(
                delete(SystemSecret).where(
                    SystemSecret.key_name == "GCP_SERVICE_ACCOUNT_JSON"
                )
            )
            await db.commit()
        
        logger.info("Bootstrap service account key deleted - federation is now the only access path")
        
        return {
            "status": "success",
            "message": "Service account key deleted. Future access will use Auth0 federation."
        }
        
    except Exception as e:
        logger.error(f"Failed to delete bootstrap key: {e}")
        return {"status": "error", "error": str(e)}


async def is_federation_available() -> bool:
    """Check if federation is set up and available."""
    config = await _get_federation_config()
    return config is not None


def is_federation_available_sync() -> bool:
    """Synchronous wrapper for is_federation_available."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(is_federation_available())
    except RuntimeError:
        return asyncio.run(is_federation_available())

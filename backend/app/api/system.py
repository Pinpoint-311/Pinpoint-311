from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from typing import List
import subprocess
import os
import uuid
import logging
import aiofiles

logger = logging.getLogger(__name__)

from app.db.session import get_db
from app.models import SystemSettings, SystemSecret, ServiceRequest, User
from app.schemas import (
    SystemSettingsBase, SystemSettingsResponse,
    SecretCreate, SecretUpdate, SecretResponse,
    StatisticsResponse, ServiceRequestResponse
)
from app.core.auth import get_current_admin, get_current_staff

router = APIRouter()


# ============ Settings ============

@router.get("/settings", response_model=SystemSettingsResponse)
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Get system settings (public - for branding)"""
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalar_one_or_none()
    if not settings:
        # Create default settings if none exist
        settings = SystemSettings()
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


@router.post("/settings", response_model=SystemSettingsResponse)
async def update_settings(
    settings_data: SystemSettingsBase,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Update system settings (admin only)"""
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalar_one_or_none()
    
    if not settings:
        settings = SystemSettings()
        db.add(settings)
    
    for field, value in settings_data.model_dump().items():
        setattr(settings, field, value)
    
    await db.commit()
    await db.refresh(settings)
    return settings


# ============ Secrets ============

@router.get("/secrets", response_model=List[SecretResponse])
async def list_secrets(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """List all secrets (admin only). Non-sensitive config values are returned."""
    # These keys can have their values exposed (they're config choices, not secrets)
    SAFE_TO_RETURN = {'SMS_PROVIDER', 'EMAIL_ENABLED', 'SMTP_USE_TLS', 'SMTP_PORT'}
    
    result = await db.execute(select(SystemSecret))
    secrets = result.scalars().all()
    
    response = []
    for secret in secrets:
        data = SecretResponse.model_validate(secret)
        # Only include key_value for non-sensitive config options
        if secret.key_name in SAFE_TO_RETURN and secret.is_configured:
            data.key_value = secret.key_value
        response.append(data)
    
    return response


@router.post("/secrets", response_model=SecretResponse)
async def create_or_update_secret(
    secret_data: SecretCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Create or update a secret (admin only) - values are encrypted at rest"""
    from app.core.encryption import encrypt
    
    result = await db.execute(
        select(SystemSecret).where(SystemSecret.key_name == secret_data.key_name)
    )
    secret = result.scalar_one_or_none()
    
    # Encrypt the secret value before storing
    encrypted_value = encrypt(secret_data.key_value) if secret_data.key_value else None
    
    if secret:
        secret.key_value = encrypted_value
        secret.is_configured = bool(secret_data.key_value)
    else:
        secret = SystemSecret(
            key_name=secret_data.key_name,
            key_value=encrypted_value,
            description=secret_data.description,
            is_configured=bool(secret_data.key_value)
        )
        db.add(secret)
    
    await db.commit()
    await db.refresh(secret)
    return secret


@router.post("/secrets/sync")
async def sync_secrets(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Add any missing secrets from the default list (admin only)"""
    from app.db.init_db import DEFAULT_SECRETS
    
    added = []
    for secret_data in DEFAULT_SECRETS:
        result = await db.execute(
            select(SystemSecret).where(SystemSecret.key_name == secret_data["key_name"])
        )
        existing = result.scalar_one_or_none()
        
        if not existing:
            secret = SystemSecret(
                key_name=secret_data["key_name"],
                description=secret_data.get("description", ""),
                is_configured=False
            )
            db.add(secret)
            added.append(secret_data["key_name"])
    
    await db.commit()
    return {"status": "success", "added_secrets": added, "count": len(added)}


@router.post("/secrets/migrate-encryption")
async def migrate_secrets_to_encrypted(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """
    Migrate existing plaintext secrets to encrypted format.
    
    This is a one-time migration for secrets that were stored before 
    encryption was implemented. Safe to run multiple times - already
    encrypted values are skipped.
    """
    from app.core.encryption import encrypt, is_encrypted
    
    result = await db.execute(
        select(SystemSecret).where(SystemSecret.is_configured == True)
    )
    secrets = result.scalars().all()
    
    migrated = []
    already_encrypted = []
    errors = []
    
    for secret in secrets:
        if not secret.key_value:
            continue
            
        # Check if already encrypted (starts with gAAAA)
        if is_encrypted(secret.key_value):
            already_encrypted.append(secret.key_name)
            continue
        
        try:
            # Encrypt the plaintext value
            secret.key_value = encrypt(secret.key_value)
            migrated.append(secret.key_name)
        except Exception as e:
            errors.append({"key": secret.key_name, "error": str(e)})
    
    await db.commit()
    
    return {
        "status": "success",
        "migrated": migrated,
        "migrated_count": len(migrated),
        "already_encrypted": already_encrypted,
        "already_encrypted_count": len(already_encrypted),
        "errors": errors
    }


# ============ Document Retention ============

@router.get("/retention/states")
async def get_retention_states(
    _: User = Depends(get_current_admin)
):
    """Get all supported states with their retention policies"""
    from app.services.retention_service import get_all_states
    return get_all_states()


@router.get("/retention/policy")
async def get_current_retention_policy(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Get current retention policy configuration"""
    from app.services.retention_service import get_retention_policy, get_retention_stats
    
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalar_one_or_none()
    
    state_code = settings.retention_state_code if settings else "NJ"
    override_days = settings.retention_days_override if settings else None
    mode = settings.retention_mode if settings else "anonymize"
    
    policy = get_retention_policy(state_code)
    stats = await get_retention_stats(db, state_code, override_days)
    
    return {
        "state_code": state_code,
        "policy": policy,
        "override_days": override_days,
        "effective_days": override_days if override_days else policy["retention_days"],
        "mode": mode,
        "stats": stats
    }


@router.post("/retention/policy")
async def update_retention_policy(
    state_code: str = None,
    override_days: int = None,
    mode: str = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Update retention policy configuration (admin only)"""
    from app.services.retention_service import get_retention_policy
    
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalar_one_or_none()
    
    if not settings:
        settings = SystemSettings()
        db.add(settings)
    
    if state_code:
        # Validate state code
        policy = get_retention_policy(state_code)
        if policy["state_code"] == "DEFAULT" and state_code != "DEFAULT":
            raise HTTPException(400, f"Unknown state code: {state_code}")
        settings.retention_state_code = state_code.upper()
    
    if override_days is not None:
        if override_days < 365:
            raise HTTPException(400, "Override must be at least 365 days (1 year)")
        settings.retention_days_override = override_days
    
    if mode:
        if mode not in ["anonymize", "delete"]:
            raise HTTPException(400, "Mode must be 'anonymize' or 'delete'")
        settings.retention_mode = mode
    
    await db.commit()
    await db.refresh(settings)
    
    return {
        "status": "updated",
        "state_code": settings.retention_state_code,
        "override_days": settings.retention_days_override,
        "mode": settings.retention_mode
    }


@router.post("/retention/run")
async def run_retention_now(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Manually trigger retention enforcement (admin only)"""
    from app.tasks.service_requests import enforce_retention_policy
    
    # Trigger async task
    task = enforce_retention_policy.delay()
    return {
        "status": "triggered",
        "task_id": task.id,
        "message": "Retention enforcement task started"
    }


@router.get("/retention/legal-hold")
async def get_legal_hold_requests(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Get all requests currently under legal hold (flagged)"""
    from app.models import ServiceRequest
    
    result = await db.execute(
        select(ServiceRequest).where(
            and_(
                ServiceRequest.flagged == True,
                ServiceRequest.deleted_at.is_(None)
            )
        ).order_by(ServiceRequest.requested_datetime.desc())
    )
    requests = result.scalars().all()
    
    return {
        "count": len(requests),
        "requests": [
            {
                "id": r.id,
                "service_request_id": r.service_request_id,
                "service_name": r.service_name,
                "description": r.description[:100] + "..." if r.description and len(r.description) > 100 else r.description,
                "status": r.status,
                "address": r.address,
                "requested_datetime": r.requested_datetime.isoformat() if r.requested_datetime else None,
                "closed_datetime": r.closed_datetime.isoformat() if r.closed_datetime else None,
            }
            for r in requests
        ]
    }


@router.get("/retention/export")
async def export_for_public_records(
    start_date: str = None,
    end_date: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Export records for OPRA/FOIA/public records requests.
    Uses state-specific format based on configured retention policy.
    """
    from app.services.retention_service import get_retention_policy
    from app.models import ServiceRequest
    from datetime import datetime
    import csv
    import io
    from fastapi.responses import StreamingResponse
    
    # Get current state policy
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalar_one_or_none()
    state_code = settings.retention_state_code if settings else "NJ"
    policy = get_retention_policy(state_code)
    
    # Build query
    query = select(ServiceRequest).where(
        ServiceRequest.deleted_at.is_(None)
    ).order_by(ServiceRequest.requested_datetime.desc())
    
    if start_date:
        query = query.where(ServiceRequest.requested_datetime >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.where(ServiceRequest.requested_datetime <= datetime.fromisoformat(end_date))
    
    result = await db.execute(query)
    records = result.scalars().all()
    
    # Generate CSV with state-specific header
    output = io.StringIO()
    
    # Write header with public records law info
    output.write(f"# {policy['public_records_law']} EXPORT\n")
    output.write(f"# State: {policy['name']} ({state_code})\n")
    output.write(f"# Generated: {datetime.utcnow().isoformat()}Z\n")
    output.write(f"# Total Records: {len(records)}\n")
    output.write(f"# Exported by: {current_user.username}\n")
    output.write("#\n")
    
    writer = csv.writer(output)
    writer.writerow([
        "Request ID", "Service Type", "Status", "Submitted Date", 
        "Address", "Lat", "Long", "Description",
        "Resolution Date", "Resolution Notes"
    ])
    
    for r in records:
        # Handle archived records - show [Archived] for description
        desc = "[Content archived per retention policy]" if r.archived_at else (r.description or "")
        writer.writerow([
            r.service_request_id,
            r.service_name,
            r.status,
            r.requested_datetime.isoformat() if r.requested_datetime else "",
            r.address or "",
            r.lat or "",
            r.long or "",
            desc,
            r.closed_datetime.isoformat() if r.closed_datetime else "",
            r.completion_message or ""
        ])
    
    output.seek(0)
    
    # Create filename with law name
    law_abbrev = policy['public_records_law'].split('(')[0].strip().replace(' ', '_')
    filename = f"{law_abbrev}_export_{datetime.utcnow().strftime('%Y%m%d')}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ============ Statistics ============

@router.get("/statistics", response_model=StatisticsResponse)
async def get_statistics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff)
):
    """Get system statistics (staff only)"""
    # Total counts by status
    total = await db.execute(select(func.count(ServiceRequest.id)))
    total_count = total.scalar() or 0
    
    open_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(ServiceRequest.status == "open")
    )
    open_count = open_result.scalar() or 0
    
    in_progress_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(ServiceRequest.status == "in_progress")
    )
    in_progress_count = in_progress_result.scalar() or 0
    
    closed_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(ServiceRequest.status == "closed")
    )
    closed_count = closed_result.scalar() or 0
    
    # Requests by category
    category_result = await db.execute(
        select(ServiceRequest.service_name, func.count(ServiceRequest.id))
        .group_by(ServiceRequest.service_name)
    )
    requests_by_category = {row[0]: row[1] for row in category_result.all()}
    
    # Recent requests
    recent_result = await db.execute(
        select(ServiceRequest)
        .order_by(ServiceRequest.requested_datetime.desc())
        .limit(10)
    )
    recent_requests = recent_result.scalars().all()
    
    return StatisticsResponse(
        total_requests=total_count,
        open_requests=open_count,
        in_progress_requests=in_progress_count,
        closed_requests=closed_count,
        requests_by_category=requests_by_category,
        requests_by_status={
            "open": open_count,
            "in_progress": in_progress_count,
            "closed": closed_count
        },
        recent_requests=recent_requests
    )


# ============ Advanced Statistics (PostGIS-powered) ============

from sqlalchemy import text, extract, case
from sqlalchemy.sql.expression import literal_column
from datetime import timedelta
import json
from app.schemas import (
    AdvancedStatisticsResponse, HotspotData, TrendData, DepartmentMetrics,
    PredictiveInsights, CostEstimate, RepeatLocation
)
from app.models import Department

# Redis client import (reuse from open311)
try:
    from app.api.open311 import redis_client
except ImportError:
    redis_client = None

STATS_CACHE_TTL = 300  # 5 minutes


@router.get("/advanced-statistics", response_model=AdvancedStatisticsResponse)
async def get_advanced_statistics(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff)
):
    """Get advanced PostGIS-powered statistics (staff only, cached for 5 minutes)"""
    
    # Check cache first
    cache_key = "advanced_statistics"
    try:
        if redis_client:
            cached = await redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                data["cached_at"] = data.get("cached_at")
                return AdvancedStatisticsResponse(**data)
    except Exception:
        pass  # Redis unavailable

    from datetime import datetime
    now = datetime.utcnow()
    
    # ========== Basic Counts ==========
    base_query = select(ServiceRequest).where(ServiceRequest.deleted_at.is_(None))
    
    total_result = await db.execute(select(func.count(ServiceRequest.id)).where(ServiceRequest.deleted_at.is_(None)))
    total_count = total_result.scalar() or 0
    
    open_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(ServiceRequest.deleted_at.is_(None), ServiceRequest.status == "open")
    )
    open_count = open_result.scalar() or 0
    
    in_progress_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(ServiceRequest.deleted_at.is_(None), ServiceRequest.status == "in_progress")
    )
    in_progress_count = in_progress_result.scalar() or 0
    
    closed_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(ServiceRequest.deleted_at.is_(None), ServiceRequest.status == "closed")
    )
    closed_count = closed_result.scalar() or 0
    
    # ========== Temporal Analytics ==========
    
    # Requests by hour of day
    hour_query = select(
        extract('hour', ServiceRequest.requested_datetime).label('hour'),
        func.count(ServiceRequest.id)
    ).where(ServiceRequest.deleted_at.is_(None)).group_by('hour')
    hour_result = await db.execute(hour_query)
    requests_by_hour = {int(row[0]): row[1] for row in hour_result.all() if row[0] is not None}
    # Fill missing hours with 0
    for h in range(24):
        if h not in requests_by_hour:
            requests_by_hour[h] = 0
    
    # Requests by day of week
    dow_query = select(
        extract('dow', ServiceRequest.requested_datetime).label('dow'),
        func.count(ServiceRequest.id)
    ).where(ServiceRequest.deleted_at.is_(None)).group_by('dow')
    dow_result = await db.execute(dow_query)
    day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    requests_by_day_of_week = {}
    for row in dow_result.all():
        if row[0] is not None:
            requests_by_day_of_week[day_names[int(row[0])]] = row[1]
    for day in day_names:
        if day not in requests_by_day_of_week:
            requests_by_day_of_week[day] = 0
    
    # Requests by month (last 12 months)
    month_query = select(
        func.to_char(ServiceRequest.requested_datetime, 'YYYY-MM').label('month'),
        func.count(ServiceRequest.id)
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.requested_datetime >= now - timedelta(days=365)
    ).group_by('month').order_by('month')
    month_result = await db.execute(month_query)
    requests_by_month = {row[0]: row[1] for row in month_result.all() if row[0]}
    
    # Average resolution hours by category
    resolution_query = select(
        ServiceRequest.service_name,
        func.avg(
            extract('epoch', ServiceRequest.closed_datetime - ServiceRequest.requested_datetime) / 3600
        ).label('avg_hours')
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status == "closed",
        ServiceRequest.closed_datetime.isnot(None)
    ).group_by(ServiceRequest.service_name)
    resolution_result = await db.execute(resolution_query)
    avg_resolution_hours_by_category = {
        row[0]: round(float(row[1]), 2) if row[1] else 0 
        for row in resolution_result.all() if row[0]
    }
    
    # ========== Geospatial Analytics (PostGIS) ==========
    
    # Hotspot detection using PostGIS ST_ClusterDBSCAN
    # Cluster points within 500m with minimum 2 points per cluster
    hotspots = []
    try:
        # Get clusters with addresses, categories, and unique reporter count
        hotspot_query = text("""
            WITH clustered AS (
                SELECT 
                    id, lat, long, address, service_name, email,
                    ST_ClusterDBSCAN(location, eps := 0.005, minpoints := 2) OVER () as cluster_id
                FROM service_requests
                WHERE deleted_at IS NULL 
                AND location IS NOT NULL
            ),
            cluster_stats AS (
                SELECT 
                    cluster_id,
                    AVG(lat) as center_lat,
                    AVG(long) as center_lng,
                    COUNT(*) as point_count,
                    COUNT(DISTINCT email) as unique_reporters,
                    (ARRAY_AGG(address ORDER BY id DESC))[1] as sample_address,
                    (ARRAY_AGG(DISTINCT service_name))[1:3] as top_categories
                FROM clustered
                WHERE cluster_id IS NOT NULL
                GROUP BY cluster_id
            )
            SELECT center_lat, center_lng, point_count, cluster_id, sample_address, top_categories, unique_reporters
            FROM cluster_stats
            ORDER BY point_count DESC
            LIMIT 10
        """)
        hotspot_result = await db.execute(hotspot_query)
        for row in hotspot_result.mappings().all():
            hotspots.append(HotspotData(
                lat=float(row['center_lat']),
                lng=float(row['center_lng']),
                count=int(row['point_count']),
                cluster_id=int(row['cluster_id']),
                sample_address=row.get('sample_address'),
                top_categories=row.get('top_categories') or [],
                unique_reporters=int(row['unique_reporters']) if row.get('unique_reporters') else None
            ))
    except Exception as e:
        logger.warning(f"Hotspot query failed (PostGIS may not be enabled): {e}")
    
    # Geographic center
    center_query = select(
        func.avg(ServiceRequest.lat),
        func.avg(ServiceRequest.long)
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.lat.isnot(None),
        ServiceRequest.long.isnot(None)
    )
    center_result = await db.execute(center_query)
    center_row = center_result.one_or_none()
    geographic_center = None
    if center_row and center_row[0] and center_row[1]:
        geographic_center = {"lat": float(center_row[0]), "lng": float(center_row[1])}
    
    # Geospatial metrics in imperial units (miles)
    # 1 meter = 0.000621371 miles, 1 sq meter = 0.0000003861 sq miles
    geographic_spread_miles = None
    total_coverage_sq_miles = None
    avg_distance_from_center_miles = None
    furthest_request_miles = None
    
    try:
        geo_metrics_query = text("""
            WITH centroid AS (
                SELECT ST_Centroid(ST_Collect(location))::geography as center
                FROM service_requests 
                WHERE deleted_at IS NULL AND location IS NOT NULL
            ),
            distances AS (
                SELECT 
                    ST_Distance(location::geography, (SELECT center FROM centroid)) as dist_meters
                FROM service_requests
                WHERE deleted_at IS NULL AND location IS NOT NULL
            )
            SELECT 
                STDDEV(dist_meters) * 0.000621371 as spread_miles,
                AVG(dist_meters) * 0.000621371 as avg_distance_miles,
                MAX(dist_meters) * 0.000621371 as max_distance_miles,
                (SELECT ST_Area(ST_ConvexHull(ST_Collect(location))::geography) * 0.0000003861 
                 FROM service_requests WHERE deleted_at IS NULL AND location IS NOT NULL) as coverage_sq_miles
            FROM distances
        """)
        geo_result = await db.execute(geo_metrics_query)
        geo_row = geo_result.mappings().one_or_none()
        if geo_row:
            geographic_spread_miles = round(float(geo_row['spread_miles']), 2) if geo_row['spread_miles'] else None
            avg_distance_from_center_miles = round(float(geo_row['avg_distance_miles']), 2) if geo_row['avg_distance_miles'] else None
            furthest_request_miles = round(float(geo_row['max_distance_miles']), 2) if geo_row['max_distance_miles'] else None
            total_coverage_sq_miles = round(float(geo_row['coverage_sq_miles']), 2) if geo_row['coverage_sq_miles'] else None
    except Exception as e:
        logger.warning(f"Geographic metrics query failed: {e}")
    
    # ========== Department Analytics ==========
    
    dept_result = await db.execute(select(Department))
    departments = dept_result.scalars().all()
    
    department_metrics = []
    for dept in departments:
        dept_total = await db.execute(
            select(func.count(ServiceRequest.id)).where(
                ServiceRequest.deleted_at.is_(None),
                ServiceRequest.assigned_department_id == dept.id
            )
        )
        dept_total_count = dept_total.scalar() or 0
        
        dept_open = await db.execute(
            select(func.count(ServiceRequest.id)).where(
                ServiceRequest.deleted_at.is_(None),
                ServiceRequest.assigned_department_id == dept.id,
                ServiceRequest.status == "open"
            )
        )
        dept_open_count = dept_open.scalar() or 0
        
        dept_closed = await db.execute(
            select(func.count(ServiceRequest.id)).where(
                ServiceRequest.deleted_at.is_(None),
                ServiceRequest.assigned_department_id == dept.id,
                ServiceRequest.status == "closed"
            )
        )
        dept_closed_count = dept_closed.scalar() or 0
        
        # Average resolution time for department
        dept_resolution = await db.execute(
            select(func.avg(
                extract('epoch', ServiceRequest.closed_datetime - ServiceRequest.requested_datetime) / 3600
            )).where(
                ServiceRequest.deleted_at.is_(None),
                ServiceRequest.assigned_department_id == dept.id,
                ServiceRequest.status == "closed",
                ServiceRequest.closed_datetime.isnot(None)
            )
        )
        dept_avg_hours = dept_resolution.scalar()
        
        department_metrics.append(DepartmentMetrics(
            name=dept.name,
            total_requests=dept_total_count,
            open_requests=dept_open_count,
            avg_resolution_hours=round(float(dept_avg_hours), 2) if dept_avg_hours else None,
            resolution_rate=round(dept_closed_count / dept_total_count * 100, 1) if dept_total_count > 0 else 0
        ))
    
    # Top staff by resolutions
    staff_query = select(
        ServiceRequest.assigned_to,
        func.count(ServiceRequest.id)
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status == "closed",
        ServiceRequest.assigned_to.isnot(None),
        ServiceRequest.assigned_to != ""
    ).group_by(ServiceRequest.assigned_to).order_by(func.count(ServiceRequest.id).desc()).limit(10)
    staff_result = await db.execute(staff_query)
    top_staff_by_resolutions = {row[0]: row[1] for row in staff_result.all() if row[0]}
    
    # ========== Performance Metrics ==========
    
    # Average resolution time overall
    overall_resolution = await db.execute(
        select(func.avg(
            extract('epoch', ServiceRequest.closed_datetime - ServiceRequest.requested_datetime) / 3600
        )).where(
            ServiceRequest.deleted_at.is_(None),
            ServiceRequest.status == "closed",
            ServiceRequest.closed_datetime.isnot(None)
        )
    )
    avg_resolution_hours = overall_resolution.scalar()
    if avg_resolution_hours:
        avg_resolution_hours = round(float(avg_resolution_hours), 2)
    
    # Backlog by age
    backlog_by_age = {"<1 day": 0, "1-3 days": 0, "3-7 days": 0, "1-2 weeks": 0, ">2 weeks": 0}
    open_requests_query = select(ServiceRequest.requested_datetime).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status.in_(["open", "in_progress"])
    )
    open_requests_result = await db.execute(open_requests_query)
    for row in open_requests_result.all():
        if row[0]:
            age = now - row[0].replace(tzinfo=None)
            if age < timedelta(days=1):
                backlog_by_age["<1 day"] += 1
            elif age < timedelta(days=3):
                backlog_by_age["1-3 days"] += 1
            elif age < timedelta(days=7):
                backlog_by_age["3-7 days"] += 1
            elif age < timedelta(days=14):
                backlog_by_age["1-2 weeks"] += 1
            else:
                backlog_by_age[">2 weeks"] += 1
    
    # Resolution rate (fixed: proper completion rate)
    # This is the percentage of all requests that have been successfully closed
    resolution_rate = round(closed_count / total_count * 100, 1) if total_count > 0 else 0
    
    # Category distribution
    category_query = select(
        ServiceRequest.service_name,
        func.count(ServiceRequest.id)
    ).where(ServiceRequest.deleted_at.is_(None)).group_by(ServiceRequest.service_name)
    category_result = await db.execute(category_query)
    requests_by_category = {row[0]: row[1] for row in category_result.all() if row[0]}
    
    # Flagged count
    flagged_result = await db.execute(
        select(func.count(ServiceRequest.id)).where(
            ServiceRequest.deleted_at.is_(None),
            ServiceRequest.flagged == True
        )
    )
    flagged_count = flagged_result.scalar() or 0
    
    # ========== Infrastructure Metrics ==========
    
    # Backlog by priority (current open + in_progress)
    priority_query = select(
        ServiceRequest.priority,
        func.count(ServiceRequest.id)
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status.in_(["open", "in_progress"])
    ).group_by(ServiceRequest.priority)
    priority_result = await db.execute(priority_query)
    backlog_by_priority = {int(row[0]): row[1] for row in priority_result.all() if row[0]}
    # Ensure all priorities 1-10 are represented
    for p in range(1, 11):
        if p not in backlog_by_priority:
            backlog_by_priority[p] = 0
    
    # Current workload by staff (active assignments)
    workload_query = select(
        ServiceRequest.assigned_to,
        func.count(ServiceRequest.id)
    ).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status.in_(["open", "in_progress"]),
        ServiceRequest.assigned_to.isnot(None),
        ServiceRequest.assigned_to != ""
    ).group_by(ServiceRequest.assigned_to)
    workload_result = await db.execute(workload_query)
    workload_by_staff = {row[0]: row[1] for row in workload_result.all() if row[0]}
    
    # SLA tracking (open requests only, by age)
    open_by_age_sla = {"<1 day": 0, "1-3 days": 0, "3-7 days": 0, "1-2 weeks": 0, ">2 weeks": 0}
    open_only_query = select(ServiceRequest.requested_datetime).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status == "open"  # Only "open" status, not in_progress
    )
    open_only_result = await db.execute(open_only_query)
    for row in open_only_result.all():
        if row[0]:
            age = now - row[0].replace(tzinfo=None)
            if age < timedelta(days=1):
                open_by_age_sla["<1 day"] += 1
            elif age < timedelta(days=3):
                open_by_age_sla["1-3 days"] += 1
            elif age < timedelta(days=7):
                open_by_age_sla["3-7 days"] += 1
            elif age < timedelta(days=14):
                open_by_age_sla["1-2 weeks"] += 1
            else:
                open_by_age_sla[">2 weeks"] += 1
    
    # ========== Predictive & Government Analytics ==========
    
    # Labor cost rates (hourly, in dollars)
    LABOR_RATES = {
        "Pothole": 50, "Street Repair": 75, "Snow Removal": 50,
        "Sewer": 85, "Water": 85, "Traffic Signal": 65,
        "Drainage": 70, "Road Maintenance": 65
    }
    DEFAULT_LABOR_RATE = 55
    
    # Cost estimates by category
    cost_estimates = []
    for category, total_cat_count in requests_by_category.items():
        # Get avg resolution hours for this category
        avg_hours = avg_resolution_hours_by_category.get(category, 2.5)
        labor_rate = LABOR_RATES.get(category, DEFAULT_LABOR_RATE)
        estimated_cost = avg_hours * labor_rate
        
        # Count open tickets in this category
        open_cat_query = await db.execute(
            select(func.count(ServiceRequest.id)).where(
                ServiceRequest.deleted_at.is_(None),
                ServiceRequest.service_name == category,
                ServiceRequest.status.in_(["open", "in_progress"])
            )
        )
        open_in_category = open_cat_query.scalar() or 0
        
        cost_estimates.append(CostEstimate(
            category=category,
            avg_hours=round(avg_hours, 2),
            estimated_cost=round(estimated_cost, 2),
            open_tickets=open_in_category,
            total_estimated_cost=round(open_in_category * estimated_cost, 2)
        ))
    
    # Sort by total cost descending
    cost_estimates.sort(key=lambda x: x.total_estimated_cost, reverse=True)
    
    # Repeat locations (infrastructure maintenance indicators)
    repeat_locations = []
    try:
        repeat_query = text("""
            SELECT address, lat, long, COUNT(*) as request_count
            FROM service_requests
            WHERE deleted_at IS NULL 
            AND address IS NOT NULL
            AND lat IS NOT NULL
            AND long IS NOT NULL
            GROUP BY address, lat, long
            HAVING COUNT(*) >= 3
            ORDER BY COUNT(*) DESC
            LIMIT 10
        """)
        repeat_result = await db.execute(repeat_query)
        for row in repeat_result.mappings().all():
            if row['address'] and row['lat'] and row['long']:
                repeat_locations.append(RepeatLocation(
                    address=str(row['address']),
                    lat=float(row['lat']),
                    lng=float(row['long']),
                    request_count=int(row['request_count'])
                ))
    except Exception as e:
        logger.warning(f"Repeat locations query failed: {e}")
    
    # Aging high-priority count (P1-P3 open > 7 days)
    aging_hp_query = select(func.count(ServiceRequest.id)).where(
        ServiceRequest.deleted_at.is_(None),
        ServiceRequest.status == "open",
        ServiceRequest.priority.in_([1, 2, 3]),
        ServiceRequest.requested_datetime < now - timedelta(days=7)
    )
    aging_hp_result = await db.execute(aging_hp_query)
    aging_high_priority_count = aging_hp_result.scalar() or 0
    
    # ========== Trends ==========
    
    # Weekly trend (last 8 weeks)
    weekly_trend = []
    for i in range(7, -1, -1):
        week_start = now - timedelta(weeks=i+1)
        week_end = now - timedelta(weeks=i)
        week_label = f"W{8-i}"
        
        week_stats = {"period": week_label, "open": 0, "in_progress": 0, "closed": 0, "total": 0}
        for status in ["open", "in_progress", "closed"]:
            count_result = await db.execute(
                select(func.count(ServiceRequest.id)).where(
                    ServiceRequest.deleted_at.is_(None),
                    ServiceRequest.status == status,
                    ServiceRequest.requested_datetime >= week_start,
                    ServiceRequest.requested_datetime < week_end
                )
            )
            week_stats[status] = count_result.scalar() or 0
        week_stats["total"] = week_stats["open"] + week_stats["in_progress"] + week_stats["closed"]
        weekly_trend.append(TrendData(**week_stats))
    
    # Monthly trend (last 6 months)
    monthly_trend = []
    for i in range(5, -1, -1):
        month_start = (now.replace(day=1) - timedelta(days=30*i)).replace(day=1)
        if i > 0:
            month_end = (now.replace(day=1) - timedelta(days=30*(i-1))).replace(day=1)
        else:
            month_end = now
        month_label = month_start.strftime("%b")
        
        month_stats = {"period": month_label, "open": 0, "in_progress": 0, "closed": 0, "total": 0}
        for status in ["open", "in_progress", "closed"]:
            count_result = await db.execute(
                select(func.count(ServiceRequest.id)).where(
                    ServiceRequest.deleted_at.is_(None),
                    ServiceRequest.status == status,
                    ServiceRequest.requested_datetime >= month_start,
                    ServiceRequest.requested_datetime < month_end
                )
            )
            month_stats[status] = count_result.scalar() or 0
        month_stats["total"] = month_stats["open"] + month_stats["in_progress"] + month_stats["closed"]
        monthly_trend.append(TrendData(**month_stats))
    
    # Predictive insights
    # Volume forecast (simple moving average of last 4 weeks)
    if len(weekly_trend) >= 4:
        recent_volumes = [w.total for w in weekly_trend[-4:]]
        volume_forecast_next_week = int(sum(recent_volumes) / len(recent_volumes))
    else:
        volume_forecast_next_week = 0
    
    # Trend direction (compare last 2 weeks vs previous 2 weeks)
    if len(weekly_trend) >= 4:
        recent_avg = sum(w.total for w in weekly_trend[-2:]) / 2
        previous_avg = sum(w.total for w in weekly_trend[-4:-2]) / 2
        if recent_avg > previous_avg * 1.1:
            trend_direction = "increasing"
        elif recent_avg < previous_avg * 0.9:
            trend_direction = "decreasing"
        else:
            trend_direction = "stable"
    else:
        trend_direction = "stable"
    
    # Seasonal patterns
    peak_day = max(requests_by_day_of_week.items(), key=lambda x: x[1])[0] if requests_by_day_of_week else "Monday"
    peak_month = max(requests_by_month.items(), key=lambda x: x[1])[0] if requests_by_month else "January"
    if peak_month:
        # Extract month name from YYYY-MM format
        try:
            from datetime import datetime as dt
            peak_month = dt.strptime(peak_month, "%Y-%m").strftime("%B")
        except:
            pass
    
    predictive_insights = PredictiveInsights(
        volume_forecast_next_week=volume_forecast_next_week,
        trend_direction=trend_direction,
        seasonal_peak_day=peak_day,
        seasonal_peak_month=peak_month
    )
    
    # Build response
    response_data = AdvancedStatisticsResponse(
        total_requests=total_count,
        open_requests=open_count,
        in_progress_requests=in_progress_count,
        closed_requests=closed_count,
        requests_by_hour=requests_by_hour,
        requests_by_day_of_week=requests_by_day_of_week,
        requests_by_month=requests_by_month,
        avg_resolution_hours_by_category=avg_resolution_hours_by_category,
        hotspots=hotspots,
        geographic_center=geographic_center,
        geographic_spread_miles=geographic_spread_miles,
        total_coverage_sq_miles=total_coverage_sq_miles,
        avg_distance_from_center_miles=avg_distance_from_center_miles,
        furthest_request_miles=furthest_request_miles,
        requests_density_by_zone={},
        department_metrics=department_metrics,
        top_staff_by_resolutions=top_staff_by_resolutions,
        avg_resolution_hours=avg_resolution_hours,
        avg_first_response_hours=None,  # Would need audit log analysis
        backlog_by_age=backlog_by_age,
        resolution_rate=resolution_rate,
        backlog_by_priority=backlog_by_priority,
        workload_by_staff=workload_by_staff,
        open_by_age_sla=open_by_age_sla,
        predictive_insights=predictive_insights,
        cost_estimates=cost_estimates,
        avg_response_time_hours=None,  # Would need comment/audit log analysis
        repeat_locations=repeat_locations,
        aging_high_priority_count=aging_high_priority_count,
        requests_by_category=requests_by_category,
        flagged_count=flagged_count,
        weekly_trend=weekly_trend,
        monthly_trend=monthly_trend,
        cached_at=now
    )
    
    # Cache the result
    try:
        if redis_client:
            cache_data = response_data.model_dump()
            cache_data["cached_at"] = now.isoformat()
            await redis_client.setex(cache_key, STATS_CACHE_TTL, json.dumps(cache_data, default=str))
    except Exception:
        pass
    
    return response_data


# ============ System Update ============


@router.post("/update")
async def update_system(_: User = Depends(get_current_admin)):
    """Pull updates from GitHub (admin only). Code changes reload automatically."""
    try:
        # Get the project root
        project_root = os.environ.get("PROJECT_ROOT", "/project")
        
        # Add safe directory to fix ownership issues in Docker
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", project_root],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Pull latest code
        pull_result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if pull_result.returncode != 0:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Git pull failed: {pull_result.stderr}"
            )
        
        # Check what was updated
        git_output = pull_result.stdout.strip()
        
        # Determine if restart is needed
        needs_restart = any(x in git_output.lower() for x in [
            'requirements.txt', 'dockerfile', 'docker-compose', 'package.json'
        ])
        
        return {
            "status": "success",
            "message": "Updates pulled successfully. " + (
                "Container restart may be needed for dependency changes." 
                if needs_restart 
                else "Code changes will reload automatically."
            ),
            "git_output": git_output,
            "needs_restart": needs_restart
        }
    
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Update operation timed out"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ============ Version Switcher ============

GITHUB_REPO = "WestWindsorForward/WWF-Open-Source-311-Template"
GITHUB_API_BASE = "https://api.github.com"


@router.get("/current-version")
async def get_current_version(_: User = Depends(get_current_admin)):
    """Get current git version information (admin only)."""
    try:
        project_root = os.environ.get("PROJECT_ROOT", "/project")
        
        # Add safe directory to fix ownership issues in Docker
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", project_root],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Get current commit SHA
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        if sha_result.returncode != 0:
            logger.warning(f"Git rev-parse failed: {sha_result.stderr}")
        current_sha = sha_result.stdout.strip()[:7] if sha_result.returncode == 0 else "unknown"
        
        # Get current tag (if on a tag)
        tag_result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        current_tag = tag_result.stdout.strip() if tag_result.returncode == 0 else None
        
        # Get commit date
        date_result = subprocess.run(
            ["git", "log", "-1", "--format=%ci"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        commit_date = date_result.stdout.strip() if date_result.returncode == 0 else None
        
        # Get commit message (first line)
        msg_result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        commit_message = msg_result.stdout.strip()[:60] if msg_result.returncode == 0 else None
        
        return {
            "sha": current_sha,
            "tag": current_tag,
            "commit_date": commit_date,
            "commit_message": commit_message,
            "display": current_tag or f"@{current_sha}"
        }
    except Exception as e:
        logger.error(f"Failed to get current version: {e}")
        return {"sha": "unknown", "tag": None, "commit_date": None, "display": "@unknown"}


@router.get("/releases")
async def get_releases(_: User = Depends(get_current_admin)):
    """Fetch available releases from GitHub (admin only)."""
    import httpx
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/releases",
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"GitHub API error: {response.text}"
                )
            
            releases = response.json()
            
            # Also get recent commits from main for unreleased versions
            commits_response = await client.get(
                f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/commits",
                params={"per_page": 5},
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            
            recent_commits = []
            if commits_response.status_code == 200:
                for commit in commits_response.json()[:5]:
                    recent_commits.append({
                        "sha": commit["sha"][:7],
                        "full_sha": commit["sha"],
                        "message": commit["commit"]["message"].split("\n")[0][:80],
                        "date": commit["commit"]["committer"]["date"],
                        "author": commit["commit"]["author"]["name"]
                    })
            
            return {
                "releases": [
                    {
                        "tag": r["tag_name"],
                        "name": r["name"] or r["tag_name"],
                        "body": r["body"] or "No release notes.",
                        "published_at": r["published_at"],
                        "author": r["author"]["login"] if r.get("author") else None,
                        "html_url": r["html_url"],
                        "prerelease": r["prerelease"],
                        "target_commitish": r["target_commitish"]
                    }
                    for r in releases
                ],
                "recent_commits": recent_commits
            }
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="GitHub API request timed out"
        )
    except Exception as e:
        logger.error(f"Failed to fetch releases: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/releases/{ref}/security")
async def get_release_security(ref: str, _: User = Depends(get_current_admin)):
    """
    Fetch security verification status for a specific release/commit (admin only).
    Returns workflow run status for security scans, CodeQL, accessibility, etc.
    """
    import httpx
    
    # Workflow names to check - must match exactly the 'name:' field in each workflow file
    # Note: Accessibility only runs on PRs and schedule, not direct pushes
    SECURITY_WORKFLOWS = {
        "Security Scan (OWASP ZAP)": {"icon": "🛡️", "key": "owasp_zap"},
        "CodeQL Security Analysis": {"icon": "🔒", "key": "codeql"},
        "Build and Publish Docker Images": {"icon": "📦", "key": "docker_build"},
        "Accessibility Audit (axe-core)": {"icon": "♿", "key": "accessibility"}
    }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # First, resolve the ref to a commit SHA if it's a tag
            commit_sha = ref
            if ref.startswith("v") or not ref.isalnum():
                # It's likely a tag, resolve to SHA
                tag_response = await client.get(
                    f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/git/refs/tags/{ref}",
                    headers={"Accept": "application/vnd.github.v3+json"}
                )
                if tag_response.status_code == 200:
                    tag_data = tag_response.json()
                    # Handle both lightweight and annotated tags
                    if tag_data["object"]["type"] == "commit":
                        commit_sha = tag_data["object"]["sha"]
                    else:
                        # Annotated tag - need to dereference
                        annotated_response = await client.get(
                            tag_data["object"]["url"],
                            headers={"Accept": "application/vnd.github.v3+json"}
                        )
                        if annotated_response.status_code == 200:
                            commit_sha = annotated_response.json().get("object", {}).get("sha", ref)
            
            # Get workflow runs for this commit
            runs_response = await client.get(
                f"{GITHUB_API_BASE}/repos/{GITHUB_REPO}/actions/runs",
                params={"head_sha": commit_sha, "per_page": 50},
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            
            verification = {}
            
            if runs_response.status_code == 200:
                runs = runs_response.json().get("workflow_runs", [])
                
                for workflow_name, info in SECURITY_WORKFLOWS.items():
                    matching_runs = [r for r in runs if r["name"] == workflow_name]
                    
                    if matching_runs:
                        # Get the most recent run for this workflow
                        latest_run = matching_runs[0]
                        verification[info["key"]] = {
                            "name": workflow_name,
                            "icon": info["icon"],
                            "status": latest_run["status"],  # queued, in_progress, completed
                            "conclusion": latest_run.get("conclusion"),  # success, failure, neutral, cancelled, skipped, timed_out
                            "run_url": latest_run["html_url"],
                            "run_id": latest_run["id"],
                            "created_at": latest_run["created_at"],
                            "passed": latest_run.get("conclusion") == "success"
                        }
                    else:
                        verification[info["key"]] = {
                            "name": workflow_name,
                            "icon": info["icon"],
                            "status": "not_found",
                            "conclusion": None,
                            "run_url": None,
                            "passed": None
                        }
            
            # Calculate overall security score
            checks = [v for v in verification.values() if v.get("conclusion") is not None]
            passed_checks = len([v for v in checks if v.get("passed")])
            total_checks = len(checks)
            
            return {
                "ref": ref,
                "commit_sha": commit_sha[:7] if len(commit_sha) > 7 else commit_sha,
                "verification": verification,
                "summary": {
                    "passed": passed_checks,
                    "total": total_checks,
                    "all_passed": passed_checks == total_checks and total_checks > 0,
                    "score": f"{passed_checks}/{total_checks}" if total_checks > 0 else "N/A"
                }
            }
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="GitHub API request timed out"
        )
    except Exception as e:
        logger.error(f"Failed to fetch security status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/switch-version")
async def switch_version(
    ref: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Production-grade version deployment with automatic rollback.
    
    This endpoint performs a full deployment cycle:
    1. Save rollback point (current git HEAD)
    2. Create database backup (pg_dump)
    3. Git checkout target version
    4. Run database migrations (alembic upgrade)
    5. Rebuild and restart all containers
    6. Health check the new deployment
    7. Automatic rollback on any failure
    """
    import httpx
    from datetime import datetime
    
    project_root = os.environ.get("PROJECT_ROOT", "/project")
    deployment_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_dir = "/project/backups"
    
    # Deployment state tracking
    state = {
        "original_sha": None,
        "backup_file": None,
        "migrations_run": False,
        "containers_rebuilt": False,
        "steps_completed": [],
        "errors": []
    }
    
    def log_step(step: str, success: bool = True, detail: str = ""):
        state["steps_completed"].append({
            "step": step,
            "success": success,
            "detail": detail,
            "timestamp": datetime.utcnow().isoformat()
        })
        if not success:
            state["errors"].append(f"{step}: {detail}")
    
    async def rollback():
        """Rollback to original state on failure."""
        rollback_errors = []
        
        # 1. Restore git to original SHA
        if state["original_sha"]:
            try:
                subprocess.run(
                    ["git", "checkout", state["original_sha"]],
                    cwd=project_root,
                    capture_output=True,
                    timeout=60
                )
                log_step("rollback_git", True, f"Restored to {state['original_sha'][:7]}")
            except Exception as e:
                rollback_errors.append(f"Git rollback failed: {e}")
        
        # 2. Note: We don't auto-restore database because migrations are forward-only
        # and designed to be non-destructive. Admin should review if needed.
        if state["migrations_run"]:
            log_step("rollback_db", True, "Migrations were forward-only (additive). Manual review recommended if issues persist.")
        
        # 3. Restart original containers
        try:
            subprocess.run(
                ["docker-compose", "restart", "backend", "frontend"],
                cwd=project_root,
                capture_output=True,
                timeout=120
            )
            log_step("rollback_containers", True, "Restarted containers with original code")
        except Exception as e:
            rollback_errors.append(f"Container restart failed: {e}")
        
        return rollback_errors
    
    try:
        # ===== STEP 0: Setup =====
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", project_root],
            cwd=project_root,
            capture_output=True,
            timeout=10
        )
        
        # Create backup directory if it doesn't exist
        os.makedirs(backup_dir, exist_ok=True)
        
        # ===== STEP 1: Save Rollback Point =====
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        if sha_result.returncode != 0:
            raise Exception("Failed to get current git HEAD")
        
        state["original_sha"] = sha_result.stdout.strip()
        log_step("save_rollback_point", True, f"Saved: {state['original_sha'][:7]}")
        
        # ===== STEP 2: Create Database Backup =====
        backup_file = f"{backup_dir}/db_backup_{deployment_id}.sql"
        state["backup_file"] = backup_file
        
        # Get database URL from environment
        db_url = os.environ.get("DATABASE_URL", "")
        # Parse connection info (format: postgresql+asyncpg://user:pass@host/db)
        try:
            # Extract host, user, password, dbname from DATABASE_URL
            import re
            match = re.match(r"postgresql\+asyncpg://([^:]+):([^@]+)@([^/]+)/(.+)", db_url)
            if match:
                db_user, db_pass, db_host, db_name = match.groups()
                
                # Run pg_dump
                env = os.environ.copy()
                env["PGPASSWORD"] = db_pass
                
                backup_result = subprocess.run(
                    ["pg_dump", "-h", db_host.split(":")[0], "-U", db_user, "-d", db_name, "-f", backup_file],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 min timeout for large DBs
                )
                
                if backup_result.returncode == 0:
                    # Get backup size
                    backup_size = os.path.getsize(backup_file) if os.path.exists(backup_file) else 0
                    log_step("database_backup", True, f"Created {backup_size // 1024}KB backup")
                else:
                    log_step("database_backup", False, backup_result.stderr[:200])
                    # Continue anyway - backup failure shouldn't block deployment
            else:
                log_step("database_backup", False, "Could not parse DATABASE_URL")
        except Exception as e:
            log_step("database_backup", False, str(e)[:200])
        
        # ===== STEP 3: Git Fetch and Checkout =====
        # Stash any local changes
        subprocess.run(
            ["git", "stash"],
            cwd=project_root,
            capture_output=True,
            timeout=30
        )
        
        # Fetch all
        fetch_result = subprocess.run(
            ["git", "fetch", "--all", "--tags"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if fetch_result.returncode != 0:
            log_step("git_fetch", False, fetch_result.stderr[:200])
            raise Exception(f"Git fetch failed: {fetch_result.stderr}")
        
        log_step("git_fetch", True, "Fetched latest from remote")
        
        # Checkout target ref
        checkout_result = subprocess.run(
            ["git", "checkout", ref],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if checkout_result.returncode != 0:
            log_step("git_checkout", False, checkout_result.stderr[:200])
            raise Exception(f"Git checkout failed: {checkout_result.stderr}")
        
        # Get new SHA
        new_sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10
        )
        new_sha = new_sha_result.stdout.strip()[:7] if new_sha_result.returncode == 0 else "unknown"
        log_step("git_checkout", True, f"Checked out {new_sha}")
        
        # ===== STEP 4: Run Database Migrations =====
        # Check if alembic.ini exists and run migrations
        alembic_cfg = os.path.join(project_root, "backend", "alembic.ini")
        if os.path.exists(alembic_cfg):
            try:
                migration_result = subprocess.run(
                    ["alembic", "upgrade", "head"],
                    cwd=os.path.join(project_root, "backend"),
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                
                if migration_result.returncode == 0:
                    state["migrations_run"] = True
                    log_step("database_migrations", True, "Applied pending migrations")
                else:
                    # Check if it's just "no migrations to run"
                    if "already at head" in migration_result.stdout.lower() or "no upgrade" in migration_result.stdout.lower():
                        log_step("database_migrations", True, "No new migrations")
                    else:
                        log_step("database_migrations", False, migration_result.stderr[:200])
                        raise Exception(f"Migration failed: {migration_result.stderr}")
            except subprocess.TimeoutExpired:
                log_step("database_migrations", False, "Migration timed out")
                raise Exception("Database migration timed out")
        else:
            log_step("database_migrations", True, "No alembic config found, skipping")
        
        # ===== STEP 5: Rebuild Containers =====
        try:
            # First, rebuild images
            build_result = subprocess.run(
                ["docker-compose", "build", "--no-cache", "backend", "frontend"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=600  # 10 min for build
            )
            
            if build_result.returncode != 0:
                log_step("container_build", False, build_result.stderr[:300])
                raise Exception(f"Container build failed: {build_result.stderr[:200]}")
            
            log_step("container_build", True, "Built backend and frontend images")
            
            # Then restart with new images
            restart_result = subprocess.run(
                ["docker-compose", "up", "-d", "--force-recreate", "backend", "frontend"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if restart_result.returncode != 0:
                log_step("container_restart", False, restart_result.stderr[:200])
                raise Exception(f"Container restart failed: {restart_result.stderr[:200]}")
            
            state["containers_rebuilt"] = True
            log_step("container_restart", True, "Restarted containers with new code")
            
        except subprocess.TimeoutExpired:
            log_step("container_rebuild", False, "Container rebuild timed out")
            raise Exception("Container rebuild timed out")
        
        # ===== STEP 6: Health Check =====
        # Wait for containers to be healthy
        import asyncio
        await asyncio.sleep(10)  # Give containers time to start
        
        health_ok = False
        for attempt in range(6):  # 6 attempts over 30 seconds
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    # Check backend health
                    health_resp = await client.get("http://localhost:8000/health")
                    if health_resp.status_code == 200:
                        health_ok = True
                        break
            except Exception:
                pass
            await asyncio.sleep(5)
        
        if not health_ok:
            log_step("health_check", False, "Backend health check failed after 30s")
            raise Exception("Health check failed - backend not responding")
        
        log_step("health_check", True, "Backend healthy and responding")
        
        # ===== STEP 7: Log to Audit =====
        try:
            audit_entry = AuditLog(
                action="version_deployed",
                entity_type="system",
                entity_id=0,
                user_id=current_user.id,
                details={
                    "deployment_id": deployment_id,
                    "from_sha": state["original_sha"][:7],
                    "to_sha": new_sha,
                    "to_ref": ref,
                    "backup_file": state["backup_file"],
                    "migrations_run": state["migrations_run"],
                    "steps": state["steps_completed"]
                }
            )
            db.add(audit_entry)
            await db.commit()
        except Exception as e:
            logger.warning(f"Failed to log deployment to audit: {e}")
        
        # ===== SUCCESS =====
        return {
            "status": "success",
            "message": f"Successfully deployed @{new_sha}",
            "deployment_id": deployment_id,
            "from_sha": state["original_sha"][:7],
            "to_sha": new_sha,
            "ref": ref,
            "backup_file": state["backup_file"],
            "migrations_run": state["migrations_run"],
            "steps": state["steps_completed"]
        }
        
    except Exception as e:
        # ===== ROLLBACK ON FAILURE =====
        log_step("deployment_failed", False, str(e)[:300])
        logger.error(f"Deployment failed, initiating rollback: {e}")
        
        rollback_errors = await rollback()
        
        # Log failed deployment to audit
        try:
            audit_entry = AuditLog(
                action="version_deployment_failed",
                entity_type="system",
                entity_id=0,
                user_id=current_user.id,
                details={
                    "deployment_id": deployment_id,
                    "target_ref": ref,
                    "error": str(e)[:500],
                    "rollback_errors": rollback_errors,
                    "steps": state["steps_completed"]
                }
            )
            db.add(audit_entry)
            await db.commit()
        except Exception as audit_error:
            logger.warning(f"Failed to log deployment failure: {audit_error}")
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "message": "Deployment failed and rollback initiated",
                "error": str(e),
                "rollback_performed": True,
                "rollback_errors": rollback_errors,
                "backup_available": state["backup_file"],
                "steps": state["steps_completed"]
            }
        )


# ============ Custom Domain ============

@router.post("/domain/configure")
async def configure_domain(
    domain: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Configure custom domain with automatic HTTPS via Caddy"""
    import re
    import httpx
    
    # Validate domain format
    domain = domain.strip().lower()
    domain_regex = r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$'
    if not re.match(domain_regex, domain):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid domain format"
        )
    
    # Save domain to settings
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalar_one_or_none()
    if settings:
        settings.custom_domain = domain
        await db.commit()
    
    # Generate Caddyfile with custom domain (Caddy auto-handles HTTPS)
    caddyfile_content = f"""# Global options - enable admin API for auto-reload
{{
    admin 0.0.0.0:2019
}}

# Caddy configuration for Township 311
# Auto-generated - Custom domain: {domain}

# Custom domain with automatic HTTPS
{domain} {{
    # API routes
    handle /api/* {{
        reverse_proxy backend:8000
    }}

    # Frontend - SPA routing
    handle {{
        reverse_proxy frontend:5173
    }}

    encode gzip

    header {{
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy strict-origin-when-cross-origin
    }}
}}

# Also keep IP access on HTTP for fallback
:80 {{
    handle /api/* {{
        reverse_proxy backend:8000
    }}
    handle {{
        reverse_proxy frontend:5173
    }}
    encode gzip
}}
"""
    
    # Write Caddyfile to shared volume
    caddyfile_path = os.environ.get("PROJECT_ROOT", "/project") + "/Caddyfile"
    
    try:
        with open(caddyfile_path, 'w') as f:
            f.write(caddyfile_content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write Caddyfile: {str(e)}"
        )
    
    # Try to reload Caddy via its admin API
    reload_success = False
    reload_message = ""
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try to load the new Caddyfile config
            response = await client.post(
                "http://caddy:2019/load",
                content=caddyfile_content,
                headers={"Content-Type": "text/caddyfile"}
            )
            if response.status_code == 200:
                reload_success = True
                reload_message = "Caddy reloaded - HTTPS will be active shortly!"
            else:
                reload_message = f"Caddy API returned {response.status_code}. Container restart may be needed."
    except Exception as e:
        reload_message = f"Caddyfile saved but could not reload Caddy automatically. Please run: docker-compose restart caddy"
    
    return {
        "status": "success" if reload_success else "partial",
        "message": f"Domain {domain} configured! {reload_message}",
        "domain": domain,
        "url": f"https://{domain}",
        "reload_success": reload_success,
        "next_step": None if reload_success else "Run: docker-compose restart caddy"
    }


@router.get("/domain/status")
async def get_domain_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Get current domain configuration status"""
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalar_one_or_none()
    
    return {
        "custom_domain": settings.custom_domain if settings else None,
        "server_ip": "132.226.32.116"
    }


# ============ Image Upload ============

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/project/uploads")
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/upload/image")
async def upload_image(
    file: UploadFile = File(...),
    _: User = Depends(get_current_staff)
):
    """Upload an image file (staff only). Returns the URL to access it."""
    # Validate file extension
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Read and validate file size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"
        )
    
    # Generate unique filename
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    
    # Ensure upload directory exists
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Save file
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(content)
    
    # Return URL (relative to API)
    return {
        "url": f"/api/uploads/{unique_filename}",
        "filename": unique_filename
    }


# ============ Translation ============

from pydantic import BaseModel

class TranslationRequest(BaseModel):
    text: str
    source_lang: str = "en"
    target_lang: str = "es"


class MultiTranslationRequest(BaseModel):
    data: dict  # e.g., {"name": "Pothole", "description": "..."}
    source_lang: str = "en"
    target_languages: list[str] = None  # If None, translates to all supported languages


@router.get("/translate/languages")
async def get_supported_languages():
    """Get list of supported languages (public)"""
    from app.services.translation import get_supported_languages
    languages = get_supported_languages()
    return {
        "languages": [
            {"code": code, "name": name} 
            for code, name in languages.items()
        ]
    }


@router.post("/translate/health")
async def check_translation_service(
    _: User = Depends(get_current_admin)
):
    """Check if Google Cloud Translation API key is configured (admin only)"""
    from app.services.translation import check_translation_service
    is_available = await check_translation_service()
    return {
        "available": is_available,
        "service": "Google Cloud Translation",
        "url": "https://cloud.google.com/translate"
    }


@router.post("/translate/suggest")
async def suggest_translation(
    request: TranslationRequest,
    _: User = Depends(get_current_admin)
):
    """
    Auto-translate text using LibreTranslate (admin only).
    Used by Admin Console to suggest translations for service categories, departments, etc.
    """
    from app.services.translation import translate_text
    
    translated = await translate_text(
        request.text,
        request.source_lang,
        request.target_lang
    )
    
    if translated is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Translation service unavailable"
        )
    
    return {
        "original": request.text,
        "translated": translated,
        "source_lang": request.source_lang,
        "target_lang": request.target_lang
    }


@router.post("/translate/auto")
async def auto_translate_object(
    request: MultiTranslationRequest,
    _: User = Depends(get_current_admin)
):
    """
    Auto-translate an object (dictionary) to multiple languages (admin only).
    Returns translation dictionary ready to be saved to database.
    
    Example input:
    {
        "data": {"name": "Pothole Repair", "description": "Report road damage"},
        "source_lang": "en",
        "target_languages": ["es", "zh"]
    }
    
    Example output:
    {
        "translations": {
            "en": {"name": "Pothole Repair", "description": "Report road damage"},
            "es": {"name": "Repar

ación de Baches", "description": "Reportar daños en carreteras"},
            "zh": {"name": "坑洼修复", "description": "报告道路损坏"}
        }
    }
    """
    from app.services.translation import auto_translate_object as translate_obj
    
    translations = await translate_obj(
        request.data,
        request.source_lang,
        request.target_languages
    )
    
    return {"translations": translations}


@router.post("/translate/batch")
async def batch_translate(
    request: Request
):
    """
    Batch translate multiple UI strings (public endpoint).
    Used by frontend to translate static UI text.
    """
    from app.services.translation import translate_text
    
    data = await request.json()
    texts = data.get("texts", [])
    target_lang = data.get("target_lang", "es")
    
    if not texts:
        return {"translations": []}
    
    # Translate all texts
    translations = []
    for text in texts:
        translated = await translate_text(text, "en", target_lang)
        translations.append(translated or text)
    
    return {"translations": translations}


# ============ Database Backups ============

@router.get("/backups/status")
async def get_backup_status_endpoint(
    _: User = Depends(get_current_admin)
):
    """Get backup system status including configuration and last backup"""
    from app.services.backup_service import get_backup_status
    return await get_backup_status()


@router.get("/backups")
async def list_backups_endpoint(
    _: User = Depends(get_current_admin)
):
    """List all available database backups"""
    from app.services.backup_service import list_backups
    return await list_backups()


@router.post("/backups/create")
async def create_backup_endpoint(
    _: User = Depends(get_current_admin)
):
    """Trigger a manual database backup"""
    from app.services.backup_service import create_backup
    
    result = await create_backup()
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result.get("message", "Backup failed"))
    
    return result


@router.post("/backups/cleanup")
async def cleanup_backups_endpoint(
    retention_days: int = None,
    _: User = Depends(get_current_admin)
):
    """Clean up old backups based on retention policy"""
    from app.services.backup_service import cleanup_old_backups
    return await cleanup_old_backups(retention_days)


@router.delete("/backups/{backup_name}")
async def delete_backup_endpoint(
    backup_name: str,
    _: User = Depends(get_current_admin)
):
    """Delete a specific backup"""
    from app.services.backup_service import delete_backup
    
    result = await delete_backup(backup_name)
    if result["status"] == "error":
        raise HTTPException(status_code=500, detail=result.get("message", "Delete failed"))
    
    return result


# ============ Health Dashboard (Bus Factor Mitigation) ============

@router.get("/health-dashboard")
async def get_health_dashboard(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """
    Comprehensive system health dashboard for non-technical administrators.
    Returns status of all services, database metrics, and last backup info.
    """
    import asyncio
    from datetime import datetime
    
    health = {
        "timestamp": datetime.utcnow().isoformat(),
        "services": {},
        "database": {},
        "cache": {},
        "last_backup": None,
        "overall_status": "healthy"
    }
    
    # Check container statuses via docker
    containers = ["backend", "frontend", "db", "redis", "caddy"]
    for container in containers:
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", f"name={container}", "--format", "{{.Status}}"],
                capture_output=True, text=True, timeout=5
            )
            status = result.stdout.strip()
            health["services"][container] = {
                "status": "running" if "Up" in status else "stopped",
                "uptime": status if "Up" in status else None
            }
        except Exception as e:
            health["services"][container] = {"status": "unknown", "error": str(e)}
    
    # Database size and connection count
    try:
        db_size_result = await db.execute(text(
            "SELECT pg_size_pretty(pg_database_size(current_database())) as size"
        ))
        health["database"]["size"] = db_size_result.scalar()
        
        conn_result = await db.execute(text(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        ))
        health["database"]["connections"] = conn_result.scalar()
        health["database"]["status"] = "healthy"
    except Exception as e:
        health["database"]["status"] = "error"
        health["database"]["error"] = str(e)
        health["overall_status"] = "degraded"
    
    # Redis health check
    try:
        if redis_client:
            info = redis_client.info()
            health["cache"]["status"] = "healthy"
            health["cache"]["used_memory"] = info.get("used_memory_human", "unknown")
            health["cache"]["connected_clients"] = info.get("connected_clients", 0)
        else:
            health["cache"]["status"] = "not_configured"
    except Exception as e:
        health["cache"]["status"] = "error"
        health["cache"]["error"] = str(e)
        health["overall_status"] = "degraded"
    
    # Last backup info
    try:
        from app.services.backup_service import list_backups
        backups = await list_backups()
        if backups.get("backups"):
            last = backups["backups"][0]
            health["last_backup"] = {
                "name": last.get("name"),
                "created": last.get("created"),
                "size": last.get("size")
            }
    except Exception:
        health["last_backup"] = {"status": "unknown"}
    
    # Check for any down services
    for svc, data in health["services"].items():
        if data.get("status") != "running":
            health["overall_status"] = "degraded"
            break
    
    return health


# ============ Runbook Automation (Emergency Operations) ============

@router.post("/runbook/{action}")
async def execute_runbook(
    action: str,
    backup_name: str = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """
    Execute emergency runbook actions (admin only).
    
    Available actions:
    - restart-all: Restart all containers
    - restart-{service}: Restart specific service (backend, frontend, redis, caddy)
    - clear-cache: Clear Redis cache
    - vacuum: Run PostgreSQL vacuum analyze
    - restore: Restore from backup (requires backup_name parameter)
    """
    from datetime import datetime
    
    result = {
        "action": action,
        "executed_by": current_user.email,
        "timestamp": datetime.utcnow().isoformat(),
        "status": "success",
        "details": {}
    }
    
    try:
        if action == "restart-all":
            # Restart all containers (except database to avoid data issues)
            for service in ["backend", "frontend", "redis", "caddy"]:
                subprocess.run(
                    ["docker-compose", "restart", service],
                    cwd="/home/ubuntu/WWF-Open-Source-311-Template",
                    capture_output=True, timeout=60
                )
            result["details"]["restarted"] = ["backend", "frontend", "redis", "caddy"]
            result["details"]["note"] = "Database not restarted for safety"
        
        elif action.startswith("restart-"):
            service = action.replace("restart-", "")
            if service not in ["backend", "frontend", "redis", "caddy"]:
                raise HTTPException(status_code=400, detail=f"Cannot restart service: {service}")
            subprocess.run(
                ["docker-compose", "restart", service],
                cwd="/home/ubuntu/WWF-Open-Source-311-Template",
                capture_output=True, timeout=60
            )
            result["details"]["restarted"] = [service]
        
        elif action == "clear-cache":
            if redis_client:
                redis_client.flushdb()
                result["details"]["cleared"] = True
            else:
                result["status"] = "skipped"
                result["details"]["reason"] = "Redis not configured"
        
        elif action == "vacuum":
            await db.execute(text("VACUUM ANALYZE"))
            result["details"]["operation"] = "VACUUM ANALYZE completed"
        
        elif action == "restore":
            if not backup_name:
                raise HTTPException(status_code=400, detail="backup_name required for restore action")
            from app.services.backup_service import restore_backup
            restore_result = await restore_backup(backup_name)
            result["details"] = restore_result
        
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {action}")
        
        # Log the action to audit
        try:
            from app.models import RequestAuditLog
            audit = RequestAuditLog(
                request_id=None,
                user_id=current_user.id,
                action=f"runbook_{action}",
                details=json.dumps(result["details"])
            )
            db.add(audit)
            await db.commit()
        except Exception:
            pass  # Don't fail if audit logging fails
        
        return result
        
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["details"]["error"] = "Operation timed out after 60 seconds"
        raise HTTPException(status_code=504, detail="Operation timed out")
    except HTTPException:
        raise
    except Exception as e:
        result["status"] = "error"
        result["details"]["error"] = str(e)
        raise HTTPException(status_code=500, detail=str(e))

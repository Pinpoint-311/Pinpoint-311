"""
Audit Log API endpoints for Admin Console.
Provides querying, filtering, and export capabilities for authentication audit logs.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc
from typing import Optional, List
from datetime import datetime, timedelta
import io
import csv

from app.db.session import get_db
from app.models import AuditLog, User
from app.core.auth import get_current_admin

router = APIRouter()


@router.get("/logs")
async def get_audit_logs(
    event_type: Optional[str] = Query(None),
    success: Optional[bool] = Query(None),
    username: Optional[str] = Query(None),
    days: Optional[int] = Query(None, ge=1, le=365),
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD format"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """
    Query audit logs with filtering and pagination.
    
    Admin only endpoint.
    Supports date range filtering via start_date/end_date or days parameter.
    """
    # Build query conditions
    conditions = []
    
    # Time range filter - prefer start_date/end_date, fall back to days
    if start_date and end_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)  # Include end date
            conditions.append(AuditLog.timestamp >= start_dt)
            conditions.append(AuditLog.timestamp < end_dt)
        except ValueError:
            # Invalid date format, fall back to days
            since = datetime.utcnow() - timedelta(days=days or 7)
            conditions.append(AuditLog.timestamp >= since)
    elif days:
        since = datetime.utcnow() - timedelta(days=days)
        conditions.append(AuditLog.timestamp >= since)
    else:
        # Default to last 7 days
        since = datetime.utcnow() - timedelta(days=7)
        conditions.append(AuditLog.timestamp >= since)
    
    # Event type filter
    if event_type and event_type != "all":
        conditions.append(AuditLog.event_type == event_type)
    
    # Success filter
    if success is not None:
        conditions.append(AuditLog.success == success)
    
    # Username filter
    if username:
        conditions.append(AuditLog.username.ilike(f"%{username}%"))
    
    # Get total count for pagination
    count_query = select(func.count(AuditLog.id)).where(and_(*conditions))
    count_result = await db.execute(count_query)
    total_count = count_result.scalar() or 0
    
    # Calculate offset from page
    offset = (page - 1) * page_size
    
    # Execute query with pagination
    query = (
        select(AuditLog)
        .where(and_(*conditions))
        .order_by(desc(AuditLog.timestamp))
        .limit(page_size)
        .offset(offset)
    )
    
    result = await db.execute(query)
    logs = result.scalars().all()
    
    # Convert to dict
    logs_data = []
    for log in logs:
        logs_data.append({
            "id": log.id,
            "event_type": log.event_type,
            "success": log.success,
            "username": log.username,
            "ip_address": log.ip_address,
            "user_agent": log.user_agent,
            "session_id": log.session_id,
            "failure_reason": log.failure_reason,
            "timestamp": log.timestamp.isoformat(),
            "details": log.details
        })
    
    return {
        "logs": logs_data,
        "count": len(logs_data),
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size,
        "filters": {
            "event_type": event_type,
            "success": success,
            "username": username,
            "start_date": start_date,
            "end_date": end_date,
            "days": days
        }
    }


@router.get("/stats")
async def get_audit_stats(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """
    Get audit log statistics.
    
    Admin only endpoint.
    """
    since = datetime.utcnow() - timedelta(days=days)
    
    # Total events
    total_result = await db.execute(
        select(func.count(AuditLog.id))
        .where(AuditLog.timestamp >= since)
    )
    total_events = total_result.scalar() or 0
    
    # Successful logins
    success_result = await db.execute(
        select(func.count(AuditLog.id))
        .where(
            and_(
                AuditLog.timestamp >= since,
                AuditLog.event_type == "login_success",
                AuditLog.success == True
            )
        )
    )
    successful_logins = success_result.scalar() or 0
    
    # Failed logins
    failed_result = await db.execute(
        select(func.count(AuditLog.id))
        .where(
            and_(
                AuditLog.timestamp >= since,
                AuditLog.event_type == "login_failed",
                AuditLog.success == False
            )
        )
    )
    failed_logins = failed_result.scalar() or 0
    
    # Logouts
    logout_result = await db.execute(
        select(func.count(AuditLog.id))
        .where(
            and_(
                AuditLog.timestamp >= since,
                AuditLog.event_type == "logout"
            )
        )
    )
    total_logouts = logout_result.scalar() or 0
    
    # Unique users
    unique_result = await db.execute(
        select(func.count(func.distinct(AuditLog.username)))
        .where(
            and_(
                AuditLog.timestamp >= since,
                AuditLog.username.isnot(None)
            )
        )
    )
    unique_users = unique_result.scalar() or 0
    
    # Recent failures (last 24 hours)
    recent_since = datetime.utcnow() - timedelta(hours=24)
    recent_failures_result = await db.execute(
        select(func.count(AuditLog.id))
        .where(
            and_(
                AuditLog.timestamp >= recent_since,
                AuditLog.success == False
            )
        )
    )
    recent_failures = recent_failures_result.scalar() or 0
    
    return {
        "total_events": total_events,
        "successful_logins": successful_logins,
        "failed_logins": failed_logins,
        "total_logouts": total_logouts,
        "unique_users": unique_users,
        "recent_failures": recent_failures,
        "period_days": days
    }


@router.get("/export")
async def export_audit_logs(
    event_type: Optional[str] = Query(None),
    success: Optional[bool] = Query(None),
    username: Optional[str] = Query(None),
    days: Optional[int] = Query(None, ge=1, le=365),
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD format"),
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """
    Export audit logs to CSV.
    
    Admin only endpoint.
    Supports date range filtering via start_date/end_date or days parameter.
    """
    # Build query (same as get_audit_logs but no limit)
    conditions = []
    
    # Time range filter - prefer start_date/end_date, fall back to days
    if start_date and end_date:
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            conditions.append(AuditLog.timestamp >= start_dt)
            conditions.append(AuditLog.timestamp < end_dt)
        except ValueError:
            since = datetime.utcnow() - timedelta(days=days or 30)
            conditions.append(AuditLog.timestamp >= since)
    elif days:
        since = datetime.utcnow() - timedelta(days=days)
        conditions.append(AuditLog.timestamp >= since)
    else:
        since = datetime.utcnow() - timedelta(days=30)
        conditions.append(AuditLog.timestamp >= since)
    
    if event_type and event_type != "all":
        conditions.append(AuditLog.event_type == event_type)
    
    if success is not None:
        conditions.append(AuditLog.success == success)
    
    if username:
        conditions.append(AuditLog.username.ilike(f"%{username}%"))
    
    query = (
        select(AuditLog)
        .where(and_(*conditions))
        .order_by(desc(AuditLog.timestamp))
    )
    
    result = await db.execute(query)
    logs = result.scalars().all()
    
    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "ID",
        "Timestamp",
        "Event Type",
        "Success",
        "Username",
        "IP Address",
        "User Agent",
        "Session ID",
        "Failure Reason",
        "Details"
    ])
    
    # Data
    for log in logs:
        writer.writerow([
            log.id,
            log.timestamp.isoformat(),
            log.event_type,
            "Yes" if log.success else "No",
            log.username or "",
            log.ip_address or "",
            log.user_agent or "",
            log.session_id or "",
            log.failure_reason or "",
            str(log.details) if log.details else ""
        ])
    
    # Return as downloadable CSV
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=audit_logs_{datetime.utcnow().strftime('%Y%m%d')}.csv"
        }
    )


@router.get("/verify-integrity")
async def verify_audit_log_integrity(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """
    Verify the integrity of the audit log chain.
    
    Checks if any logs have been tampered with by validating hash chain.
    Admin only endpoint.
    """
    from app.services.audit_service import AuditService
    
    is_valid = await AuditService.verify_integrity(db)
    
    return {
        "integrity_valid": is_valid,
        "message": "Audit log chain is intact" if is_valid else "WARNING: Tampering detected in audit logs",
        "timestamp": datetime.utcnow().isoformat()
    }

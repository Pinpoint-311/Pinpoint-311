"""
Data Export API

Provides endpoints for municipalities to export their 311 request data
in various formats (CSV, JSON, GeoJSON) for reporting and integration.
"""

import csv
import io
import json
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models import ServiceRequest, ServiceDefinition, User, Department, SystemSettings
from app.api.auth import get_current_user, get_current_staff_user
from app.core.encryption import decrypt_pii

router = APIRouter(prefix="/export", tags=["data-export"])


def format_datetime(dt: Optional[datetime]) -> str:
    """Format datetime for export."""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def safe_decrypt(encrypted_value: Optional[str]) -> str:
    """Safely decrypt PII, returning empty string on failure."""
    if not encrypted_value:
        return ""
    try:
        return decrypt_pii(encrypted_value)
    except Exception:
        return "[encrypted]"


async def get_requests_for_export(
    db: AsyncSession,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status: Optional[str] = None,
    service_code: Optional[str] = None
) -> List[ServiceRequest]:
    """Fetch requests with optional filters."""
    query = select(ServiceRequest).order_by(ServiceRequest.requested_datetime.desc())
    
    conditions = [ServiceRequest.deleted_at.is_(None)]  # Exclude soft-deleted
    if start_date:
        conditions.append(ServiceRequest.requested_datetime >= start_date)
    if end_date:
        conditions.append(ServiceRequest.requested_datetime <= end_date)
    if status:
        conditions.append(ServiceRequest.status == status)
    if service_code:
        conditions.append(ServiceRequest.service_code == service_code)
    
    if conditions:
        query = query.where(and_(*conditions))
    
    result = await db.execute(query)
    return result.scalars().all()


def request_to_dict(request: ServiceRequest, include_pii: bool = True) -> dict:
    """Convert request to dictionary for export."""
    data = {
        "id": request.id,
        "request_id": request.service_request_id,
        "status": request.status,
        "priority": request.priority,
        "service_code": request.service_code,
        "service_name": request.service_name,
        "department_id": request.assigned_department_id,
        "department_name": request.assigned_department.name if request.assigned_department else "",
        "description": request.description,
        "address": request.address,
        "latitude": request.lat,
        "longitude": request.long,
        "created_at": format_datetime(request.requested_datetime),
        "updated_at": format_datetime(request.updated_datetime),
        "closed_at": format_datetime(request.closed_datetime),
        "assigned_to": request.assigned_to or "",
        "staff_notes": request.staff_notes or "",
        "ai_summary": request.vertex_ai_summary or "",
        "source": request.source or "",
    }
    
    if include_pii:
        data["reporter_name"] = f"{request.first_name or ''} {request.last_name or ''}".strip()
        data["reporter_email"] = request.email or ""
        data["reporter_phone"] = request.phone or ""
    else:
        data["reporter_name"] = "[redacted]"
        data["reporter_email"] = "[redacted]"
        data["reporter_phone"] = "[redacted]"
    
    return data


def request_to_geojson_feature(request: ServiceRequest, include_pii: bool = True) -> dict:
    """Convert request to GeoJSON feature."""
    properties = request_to_dict(request, include_pii)
    # Remove lat/lng from properties since they're in geometry
    properties.pop("latitude", None)
    properties.pop("longitude", None)
    
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [request.long or 0, request.lat or 0]
        },
        "properties": properties
    }


@router.get("/requests")
async def export_requests(
    format: str = Query("csv", description="Export format: csv, json, or geojson"),
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    status: Optional[str] = Query(None, description="Status filter"),
    service_code: Optional[str] = Query(None, description="Service code filter"),
    include_pii: bool = Query(True, description="Include reporter PII (name, email, phone)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff_user)
):
    """
    Export 311 requests as CSV, JSON, or GeoJSON.
    
    - **format**: csv, json, or geojson
    - **start_date**: Optional start date filter (YYYY-MM-DD)
    - **end_date**: Optional end date filter (YYYY-MM-DD)
    - **status**: Optional status filter (open, in_progress, closed)
    - **service_code**: Optional service code filter
    - **include_pii**: Include reporter PII or redact it (default: true)
    
    Requires staff or admin authentication.
    """
    requests = await get_requests_for_export(db, start_date, end_date, status, service_code)
    
    # Get township name for filename
    settings_result = await db.execute(select(SystemSettings).limit(1))
    settings = settings_result.scalar_one_or_none()
    township_name = settings.township_name.replace(" ", "_") if settings else "township"
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    if format.lower() == "csv":
        # Generate CSV
        output = io.StringIO()
        
        if requests:
            fieldnames = list(request_to_dict(requests[0], include_pii).keys())
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            
            for req in requests:
                writer.writerow(request_to_dict(req, include_pii))
        
        output.seek(0)
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={township_name}_requests_{timestamp}.csv"
            }
        )
    
    elif format.lower() == "json":
        # Generate JSON
        data = {
            "export_info": {
                "township": settings.township_name if settings else "Unknown",
                "exported_at": datetime.utcnow().isoformat(),
                "exported_by": current_user.full_name,
                "total_records": len(requests),
                "filters": {
                    "start_date": start_date.isoformat() if start_date else None,
                    "end_date": end_date.isoformat() if end_date else None,
                    "status": status,
                    "service_code": service_code,
                    "pii_included": include_pii
                }
            },
            "requests": [request_to_dict(req, include_pii) for req in requests]
        }
        
        json_str = json.dumps(data, indent=2)
        
        return StreamingResponse(
            iter([json_str]),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={township_name}_requests_{timestamp}.json"
            }
        )
    
    elif format.lower() == "geojson":
        # Generate GeoJSON
        geojson = {
            "type": "FeatureCollection",
            "properties": {
                "township": settings.township_name if settings else "Unknown",
                "exported_at": datetime.utcnow().isoformat(),
                "total_features": len(requests)
            },
            "features": [request_to_geojson_feature(req, include_pii) for req in requests]
        }
        
        json_str = json.dumps(geojson, indent=2)
        
        return StreamingResponse(
            iter([json_str]),
            media_type="application/geo+json",
            headers={
                "Content-Disposition": f"attachment; filename={township_name}_requests_{timestamp}.geojson"
            }
        )
    
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}. Use csv, json, or geojson.")


@router.get("/statistics")
async def export_statistics(
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    format: str = Query("json", description="Export format: csv or json"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff_user)
):
    """
    Export aggregated statistics as CSV or JSON.
    
    Includes:
    - Request counts by status
    - Request counts by category
    - Request counts by department
    - Average resolution time
    - Requests per day/week/month
    
    Requires staff or admin authentication.
    """
    # Build date filter
    conditions = []
    if start_date:
        conditions.append(ServiceRequest.created_at >= start_date)
    if end_date:
        conditions.append(ServiceRequest.created_at <= end_date)
    
    base_query = select(ServiceRequest).where(ServiceRequest.deleted_at.is_(None))
    if conditions:
        base_query = base_query.where(and_(*conditions))
    
    # Get all requests in range
    result = await db.execute(base_query)
    requests = result.scalars().all()
    
    # Calculate statistics
    total = len(requests)
    by_status = {}
    by_category = {}
    by_department = {}
    resolution_times = []
    
    for req in requests:
        # By status
        by_status[req.status] = by_status.get(req.status, 0) + 1
        
        # By category (service_name)
        cat_name = req.service_name or "Unknown"
        by_category[cat_name] = by_category.get(cat_name, 0) + 1
        
        # By department
        dept_name = req.assigned_department.name if req.assigned_department else "Unassigned"
        by_department[dept_name] = by_department.get(dept_name, 0) + 1
        
        # Resolution time
        if req.closed_datetime and req.requested_datetime:
            resolution_times.append((req.closed_datetime - req.requested_datetime).total_seconds() / 3600)  # hours
    
    avg_resolution_hours = sum(resolution_times) / len(resolution_times) if resolution_times else 0
    
    # Get township info
    settings_result = await db.execute(select(SystemSettings).limit(1))
    settings = settings_result.scalar_one_or_none()
    township_name = settings.township_name.replace(" ", "_") if settings else "township"
    
    stats = {
        "export_info": {
            "township": settings.township_name if settings else "Unknown",
            "exported_at": datetime.utcnow().isoformat(),
            "exported_by": current_user.full_name,
            "date_range": {
                "start": start_date.isoformat() if start_date else "all time",
                "end": end_date.isoformat() if end_date else "present"
            }
        },
        "summary": {
            "total_requests": total,
            "average_resolution_hours": round(avg_resolution_hours, 2),
            "resolved_count": len(resolution_times)
        },
        "by_status": by_status,
        "by_category": by_category,
        "by_department": by_department
    }
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    if format.lower() == "json":
        json_str = json.dumps(stats, indent=2)
        return StreamingResponse(
            iter([json_str]),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename={township_name}_statistics_{timestamp}.json"
            }
        )
    
    elif format.lower() == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Summary section
        writer.writerow(["Pinpoint 311 Statistics Export"])
        writer.writerow(["Township", settings.township_name if settings else "Unknown"])
        writer.writerow(["Exported At", datetime.utcnow().isoformat()])
        writer.writerow(["Date Range", f"{start_date or 'All time'} to {end_date or 'Present'}"])
        writer.writerow([])
        
        # Summary stats
        writer.writerow(["Summary Statistics"])
        writer.writerow(["Total Requests", total])
        writer.writerow(["Average Resolution (hours)", round(avg_resolution_hours, 2)])
        writer.writerow(["Resolved Count", len(resolution_times)])
        writer.writerow([])
        
        # By status
        writer.writerow(["Requests by Status"])
        writer.writerow(["Status", "Count"])
        for status, count in by_status.items():
            writer.writerow([status, count])
        writer.writerow([])
        
        # By category
        writer.writerow(["Requests by Category"])
        writer.writerow(["Category", "Count"])
        for cat, count in sorted(by_category.items(), key=lambda x: x[1], reverse=True):
            writer.writerow([cat, count])
        writer.writerow([])
        
        # By department
        writer.writerow(["Requests by Department"])
        writer.writerow(["Department", "Count"])
        for dept, count in sorted(by_department.items(), key=lambda x: x[1], reverse=True):
            writer.writerow([dept, count])
        
        output.seek(0)
        
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={township_name}_statistics_{timestamp}.csv"
            }
        )
    
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}. Use csv or json.")

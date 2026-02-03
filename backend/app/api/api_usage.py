"""
API Usage and Cost Tracking Endpoints

Provides endpoints for administrators to view API usage statistics
and estimated costs for external services.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import logging

from app.db.session import get_db
from app.core.auth import get_current_user
from app.models import User
from app.services.api_usage import (
    get_usage_summary,
    estimate_costs,
    get_daily_usage,
    SERVICE_PRICING
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/usage")
async def get_api_usage(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to look back"),
    service: Optional[str] = Query(default=None, description="Filter by specific service"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get API usage statistics for the specified time period.
    
    **Admin only.**
    
    Returns aggregated usage per service including:
    - Total tokens (for AI services)
    - Total characters (for translation)
    - Total API calls
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        summary = await get_usage_summary(db, days=days, service_name=service)
        return {
            "period_days": days,
            "services": summary,
            "available_services": list(SERVICE_PRICING.keys())
        }
    except Exception as e:
        logger.error(f"Error getting API usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cost-estimate")
async def get_cost_estimate(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to analyze"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get estimated costs based on API usage.
    
    **Admin only.**
    
    Returns:
    - Estimated cost per service
    - Total estimated cost
    - Monthly projection
    - Pricing information
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        costs = await estimate_costs(db, days=days)
        return costs
    except Exception as e:
        logger.error(f"Error estimating costs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily")
async def get_daily_usage_data(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to look back"),
    service: Optional[str] = Query(default=None, description="Filter by specific service"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get daily usage breakdown for charting.
    
    **Admin only.**
    
    Returns an array of daily usage data suitable for time-series charts.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        daily = await get_daily_usage(db, days=days, service_name=service)
        return {
            "period_days": days,
            "data": daily
        }
    except Exception as e:
        logger.error(f"Error getting daily usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pricing")
async def get_pricing_info(
    current_user: User = Depends(get_current_user)
):
    """
    Get current pricing information for all tracked services.
    
    **Admin only.**
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    return {
        "services": SERVICE_PRICING,
        "disclaimer": "Prices are estimates based on published Google Cloud pricing. Actual billing may vary based on usage tier, commitment discounts, and regional pricing."
    }

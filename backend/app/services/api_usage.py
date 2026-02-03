"""
API Usage Tracking Service

Tracks API calls to external services for cost estimation and monitoring.
Supports:
- Vertex AI (Gemini) - token-based pricing
- Google Translate - character-based pricing
- Google Maps (Geocoding) - per-call pricing
- Google Cloud Secret Manager - per-operation pricing
- Google Cloud KMS - per-operation pricing
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Pricing estimates (as of 2026, subject to change)
# These are approximate - actual billing depends on Google Cloud pricing
SERVICE_PRICING = {
    "vertex_ai": {
        "description": "Gemini 3.0 Flash",
        "input_tokens_per_million": 0.075,  # $0.075 per 1M input tokens
        "output_tokens_per_million": 0.30,   # $0.30 per 1M output tokens
        "unit": "tokens"
    },
    "translation": {
        "description": "Google Cloud Translation API",
        "per_million_chars": 20.00,  # $20 per 1M characters
        "unit": "characters"
    },
    "maps_geocode": {
        "description": "Google Maps Geocoding API",
        "per_thousand_calls": 5.00,  # $5 per 1,000 requests
        "unit": "calls"
    },
    "maps_reverse_geocode": {
        "description": "Google Maps Reverse Geocoding API",
        "per_thousand_calls": 5.00,  # $5 per 1,000 requests
        "unit": "calls"
    },
    "maps_static": {
        "description": "Google Maps Static API",
        "per_thousand_calls": 2.00,  # $2 per 1,000 requests
        "unit": "calls"
    },
    "maps_places": {
        "description": "Google Maps Places API",
        "per_thousand_calls": 17.00,  # $17 per 1,000 requests (autocomplete)
        "unit": "calls"
    },
    "maps_directions": {
        "description": "Google Maps Directions API",
        "per_thousand_calls": 5.00,  # $5 per 1,000 requests
        "unit": "calls"
    },
    "secret_manager": {
        "description": "Google Cloud Secret Manager",
        "per_ten_thousand_ops": 0.03,  # $0.03 per 10,000 access operations
        "unit": "calls"
    },
    "kms": {
        "description": "Google Cloud KMS",
        "per_ten_thousand_ops": 0.03,  # $0.03 per 10,000 cryptographic operations
        "unit": "calls"
    },
    "email": {
        "description": "SMTP Email Notifications",
        "per_thousand_messages": 0.0,  # Free (SendGrid/Mailgun have free tiers, or self-hosted SMTP)
        "unit": "messages",
        "note": "Cost depends on provider. Track for volume monitoring."
    },
    "sms": {
        "description": "SMS Notifications",
        "per_message": 0.0079,  # ~$0.0079 per segment (Twilio average)
        "unit": "messages",
        "note": "Cost varies by provider and destination."
    }
}


async def track_api_usage(
    db: AsyncSession,
    service_name: str,
    operation: Optional[str] = None,
    tokens_input: int = 0,
    tokens_output: int = 0,
    characters: int = 0,
    api_calls: int = 1,
    request_id: Optional[str] = None
) -> None:
    """
    Record an API usage event.
    
    Args:
        db: Database session
        service_name: Name of the service (vertex_ai, translation, maps_geocode, etc.)
        operation: Specific operation type
        tokens_input: Number of input tokens (for AI services)
        tokens_output: Number of output tokens (for AI services)
        characters: Number of characters (for translation)
        api_calls: Number of API calls made
        request_id: Optional link to service_request_id
    """
    try:
        from app.models import ApiUsageRecord
        
        record = ApiUsageRecord(
            service_name=service_name,
            operation=operation,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            characters=characters,
            api_calls=api_calls,
            request_id=request_id
        )
        db.add(record)
        await db.commit()
        
        logger.debug(f"Tracked API usage: {service_name}/{operation} - calls={api_calls}, tokens_in={tokens_input}, tokens_out={tokens_output}, chars={characters}")
    except Exception as e:
        logger.warning(f"Failed to track API usage: {e}")
        # Don't fail the main operation if tracking fails
        await db.rollback()


async def get_usage_summary(
    db: AsyncSession,
    days: int = 30,
    service_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get usage summary for the specified time period.
    
    Returns:
        Dictionary with usage stats per service
    """
    from app.models import ApiUsageRecord
    
    since = datetime.utcnow() - timedelta(days=days)
    
    query = (
        select(
            ApiUsageRecord.service_name,
            func.sum(ApiUsageRecord.tokens_input).label("total_tokens_input"),
            func.sum(ApiUsageRecord.tokens_output).label("total_tokens_output"),
            func.sum(ApiUsageRecord.characters).label("total_characters"),
            func.sum(ApiUsageRecord.api_calls).label("total_calls"),
            func.count(ApiUsageRecord.id).label("record_count")
        )
        .where(ApiUsageRecord.created_at >= since)
        .group_by(ApiUsageRecord.service_name)
    )
    
    if service_name:
        query = query.where(ApiUsageRecord.service_name == service_name)
    
    result = await db.execute(query)
    rows = result.all()
    
    summary = {}
    for row in rows:
        summary[row.service_name] = {
            "tokens_input": row.total_tokens_input or 0,
            "tokens_output": row.total_tokens_output or 0,
            "characters": row.total_characters or 0,
            "api_calls": row.total_calls or 0,
            "record_count": row.record_count
        }
    
    return summary


async def estimate_costs(
    db: AsyncSession,
    days: int = 30
) -> Dict[str, Any]:
    """
    Estimate costs based on usage data.
    
    Returns:
        Dictionary with estimated costs per service and total
    """
    usage = await get_usage_summary(db, days)
    
    costs = {}
    total_cost = 0.0
    
    for service, data in usage.items():
        pricing = SERVICE_PRICING.get(service, {})
        estimated_cost = 0.0
        
        if service == "vertex_ai":
            # Token-based pricing
            input_cost = (data["tokens_input"] / 1_000_000) * pricing.get("input_tokens_per_million", 0)
            output_cost = (data["tokens_output"] / 1_000_000) * pricing.get("output_tokens_per_million", 0)
            estimated_cost = input_cost + output_cost
        
        elif service == "translation":
            # Character-based pricing
            estimated_cost = (data["characters"] / 1_000_000) * pricing.get("per_million_chars", 0)
        
        elif service in ["maps_geocode", "maps_reverse_geocode", "maps_static", "maps_places", "maps_directions"]:
            # Per-call pricing (per 1,000)
            estimated_cost = (data["api_calls"] / 1000) * pricing.get("per_thousand_calls", 0)
        
        elif service in ["secret_manager", "kms"]:
            # Per-operation pricing (per 10,000)
            estimated_cost = (data["api_calls"] / 10000) * pricing.get("per_ten_thousand_ops", 0)
        
        elif service == "email":
            # Per-thousand messages (usually free)
            estimated_cost = (data["api_calls"] / 1000) * pricing.get("per_thousand_messages", 0)
        
        elif service == "sms":
            # Per-message pricing
            estimated_cost = data["api_calls"] * pricing.get("per_message", 0)
        
        costs[service] = {
            "description": pricing.get("description", service),
            "usage": data,
            "estimated_cost": round(estimated_cost, 4),
            "pricing_info": pricing
        }
        total_cost += estimated_cost
    
    return {
        "period_days": days,
        "services": costs,
        "total_estimated_cost": round(total_cost, 2),
        "monthly_projection": round((total_cost / days) * 30, 2) if days > 0 else 0,
        "pricing_disclaimer": "Costs are estimates based on published Google Cloud pricing. Actual billing may vary."
    }


async def get_daily_usage(
    db: AsyncSession,
    days: int = 30,
    service_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get daily usage breakdown for charting.
    """
    from app.models import ApiUsageRecord
    
    since = datetime.utcnow() - timedelta(days=days)
    
    query = (
        select(
            func.date(ApiUsageRecord.created_at).label("date"),
            ApiUsageRecord.service_name,
            func.sum(ApiUsageRecord.tokens_input).label("tokens_input"),
            func.sum(ApiUsageRecord.tokens_output).label("tokens_output"),
            func.sum(ApiUsageRecord.characters).label("characters"),
            func.sum(ApiUsageRecord.api_calls).label("api_calls")
        )
        .where(ApiUsageRecord.created_at >= since)
        .group_by(func.date(ApiUsageRecord.created_at), ApiUsageRecord.service_name)
        .order_by(func.date(ApiUsageRecord.created_at))
    )
    
    if service_name:
        query = query.where(ApiUsageRecord.service_name == service_name)
    
    result = await db.execute(query)
    rows = result.all()
    
    return [
        {
            "date": str(row.date),
            "service_name": row.service_name,
            "tokens_input": row.tokens_input or 0,
            "tokens_output": row.tokens_output or 0,
            "characters": row.characters or 0,
            "api_calls": row.api_calls or 0
        }
        for row in rows
    ]

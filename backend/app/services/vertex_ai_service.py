"""
Vertex AI Service for 311 Request Analysis using Gemini (Flash-Lite)

This service analyzes service requests using Google's Gemini model to provide:
- Priority scoring (1-10)
- Qualitative analysis
- Quantitative metrics
- Safety flags
"""

import json
import os
import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Structured result from AI analysis"""
    priority_score: float
    priority_justification: str
    qualitative_analysis: str
    quantitative_metrics: Dict[str, Any]
    safety_flags: List[str]
    recommended_response_time: str
    analyzed_at: datetime


def strip_pii(text: str) -> str:
    """
    Remove personally identifiable information from text.
    Strips: email addresses, phone numbers, names patterns, etc.
    """
    if not text:
        return text
    
    # Remove email addresses
    text = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL]', text)
    
    # Remove phone numbers (various formats)
    text = re.sub(r'\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b', '[PHONE]', text)
    text = re.sub(r'\(\d{3}\)\s*\d{3}[-.\s]?\d{4}', '[PHONE]', text)
    text = re.sub(r'\+1\s*\d{10}', '[PHONE]', text)
    
    # Remove potential SSN patterns
    text = re.sub(r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b', '[REDACTED]', text)
    
    # Remove "my name is X" patterns
    text = re.sub(r'(?i)(my name is|i am|this is)\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)?', r'\1 [NAME]', text)
    
    # Remove "call me at" patterns
    text = re.sub(r'(?i)(call|contact|reach)\s+(me|us)\s+(at|on)\s+[\d\-().+\s]+', r'\1 \2 at [PHONE]', text)
    
    return text


def build_analysis_prompt(
    request_data: Dict[str, Any],
    historical_context: Optional[Dict[str, Any]] = None,
    spatial_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build a comprehensive prompt for Gemini analysis.
    All PII should already be stripped from request_data.
    """
    
    prompt = """You are an AI assistant for a municipal 311 service. Analyze the following service request and provide a structured assessment.

## Service Request Information
- **Request Type**: {service_type}
- **Description**: {description}
- **Address**: {address}
- **Submitted**: {submitted_date}
""".format(
        service_type=request_data.get('service_name', 'Unknown'),
        description=strip_pii(request_data.get('description', 'No description')),
        address=request_data.get('address', 'No address provided'),
        submitted_date=request_data.get('submitted_date', 'Unknown')
    )
    
    # Add matched asset context if available
    if request_data.get('matched_asset'):
        asset = request_data['matched_asset']
        prompt += f"""
## Matched Infrastructure Asset
- **Asset Type**: {asset.get('asset_type', 'Unknown')}
- **Layer**: {asset.get('layer_name', 'Unknown')}
- **Distance**: {asset.get('distance_meters', 'N/A')}m from reported location
"""
        properties = asset.get('properties', {})
        if properties:
            prompt += "- **Asset Attributes (Specific Properties)**:\n"
            for k, v in properties.items():
                prompt += f"  - {k}: {v}\n"

    # Add custom fields (resident survey responses)
    if request_data.get('custom_fields'):
        prompt += "\n## Resident Survey Responses\n"
        for label, answer in request_data['custom_fields'].items():
            prompt += f"- **{label}**: {answer}\n"

    # Add historical context
    if historical_context:
        prompt += f"""
## Historical Context & Evidence
- **Previous reports at this location**: {historical_context.get('recurrence_count', 0)}
- **Evidence (Address-based)**: {historical_context.get('recent_address_reports', 'None')}
- **Past resolution quality (Address)**: {historical_context.get('past_resolution_quality', 'No previous history')}
- **Similar active reports (geo + category + content matched)**: {len(historical_context.get('similar_reports', []))}
- **Matched Similar Report IDs**: {[r['id'] for r in historical_context.get('similar_reports', [])] if historical_context.get('similar_reports') else 'None'}
- **Duplicate Density (within 20m)**: {historical_context.get('duplicate_density', 0)} reports
"""

    # Add spatial context
    if spatial_context:
        infra_list = spatial_context.get('critical_infrastructure', [])
        infra_str = '; '.join(infra_list) if infra_list else 'None identified within 500m'
        prompt += f"""
## Spatial & Environmental Context
- **Proximity to Critical Infrastructure**: {infra_str}
- **Nearby active outages**: {spatial_context.get('nearby_outages', 0)} detected within 100m
- **Area profile**: {spatial_context.get('area_type', 'Unknown')} (High Traffic: {spatial_context.get('is_high_traffic', 'N/A')})
- **Vulnerable population impact**: {spatial_context.get('vulnerable_pop_prox', 'Low')}
"""

    prompt += f"""
## Analysis-Time Context (Live Triage)
- **Current Weather at Location**: {request_data.get('current_weather', 'Clear skies')}
- **Actual Time of Analysis**: {request_data.get('analysis_time', 'Unknown')}
- **Time of Day Context**: {request_data.get('analysis_time', 'Unknown')[11:16] if request_data.get('analysis_time') else 'Unknown'} (Current visibility impact)

## Analysis Required

**CRITICAL — NON-ENGLISH SUBMISSIONS**: If the resident's description is NOT in English, you MUST:
1. Detect the language (e.g., "Spanish", "Chinese", "Hindi")
2. Provide a VERBATIM English translation of the ENTIRE description
3. Include both in the "translation" field of the JSON response
4. Then proceed with your full analysis as normal, using the translated content

Analyze the provided description, photos, and deep context to provide a professional triage assessment.

### Diagnostic Instructions:
1. **Real-time Prioritization**: You MUST prioritize the **Current Weather** and **Actual Time of Analysis** over the submission time for immediate triage. For example, if it is currently night or raining, the urgency for road hazards or outages is significantly higher.
2. **Evidence Citing**: For every diagnostic context claim (Infrastructure, Trend, Weather), you MUST cite specific raw data or report IDs provided above. 
3. **Critical Proximity**: If within 50ft of a hospital, school, or fire station, urgency must be elevated.
4. **Chronic vs One-off**: Use recurrence data and past resolution quality to determine if this is a systemic failure.
5. **Nodal Reporting**: High duplicate density indicates high public frustration/visibility. Citing specific nearby IDs increases trust.
6. **Visual Assessment**: Analyze photos for physical scale, required effort, and blockage severity.

Provide your analysis in the following JSON format ONLY:

```json
{{
  "translation": {{
    "detected_language": "<language name or 'English' if already English>",
    "original_text": "<verbatim original description if not English, else null>",
    "english_translation": "<full English translation if not English, else null>"
  }},
  "priority_score": <float 1.0-10.0>,
  "priority_justification": "<brief explanation covering scale, effort, and context multipliers>",
  "qualitative_analysis": "<assessment of issue, root cause, and systemic impact>",
  "photo_assessment": {{
    "physical_scale": "<desc>",
    "blocking_severity": "<none|partial|full_block>"
  }},
  "content_flags": ["<inappropriate_content|malicious_intent|obscene_language|none>"],
  "diagnostic_context": {{
    "infrastructure_proximity": {{
      "details": "<desc>",
      "evidence": "<specific citation from spatial data>"
    }},
    "historical_trend": {{
      "details": "<desc>",
      "evidence": "<citation of specific previous report IDs or dates>"
    }},
    "weather_impact": {{
      "details": "<desc>",
      "evidence": "<citation from real-time weather scenario>"
    }},
    "nodal_density": "<low|medium|high>"
  }},
  "quantitative_metrics": {{
    "estimated_severity": "<low|medium|high|critical>",
    "estimated_affected_area": "<localized|block|neighborhood|widespread>",
    "is_likely_duplicate": <true|false>,
    "recurrence_risk": "<low|medium|high>",
    "systemic_failure_probability": <float 0-1>
  }},
  "safety_flags": ["<flag1>", "<flag2>"],
  "recommended_response_time": "<immediate|24h|48h|1week|scheduled>"
}}
```
"""
    return prompt


def _gemini_fallback(err: str, reachable: bool) -> Dict[str, Any]:
    """Safe analysis shape returned when the AI call fails. `reachable` is True
    when the API responded (auth + model OK) but produced no usable JSON, so a
    connection test can still pass; False for network/auth/HTTP failures."""
    return {
        "priority_score": 5.0,
        "priority_justification": f"AI analysis failed: {err[:100]}",
        "qualitative_analysis": "AI analysis could not be completed due to a service error. Manual review recommended.",
        "quantitative_metrics": {
            "estimated_severity": "unknown",
            "estimated_affected_area": "unknown",
            "is_likely_duplicate": False,
            "recurrence_risk": "unknown",
        },
        "safety_flags": [],
        "recommended_response_time": "48h",
        "_error": err,
        "_reachable": reachable,
    }


async def analyze_with_gemini(
    project_id: str,
    location: str,
    prompt: str,
    image_data: Optional[List[str]] = None,
    service_account_json: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Call Gemini (Flash-Lite) via Vertex AI API.
    
    Args:
        project_id: Google Cloud project ID
        location: Vertex AI location (e.g., us-central1)
        prompt: The analysis prompt
        image_data: Optional list of base64-encoded images
        service_account_json: Optional service account JSON key
    
    Returns:
        Parsed JSON response from Gemini
    """
    try:
        import google.auth
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        import aiohttp
        
        # Set up authentication
        if service_account_json:
            # Use provided service account
            sa_info = json.loads(service_account_json)
            credentials = service_account.Credentials.from_service_account_info(
                sa_info,
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
        else:
            # Use default credentials (from environment)
            credentials, _ = google.auth.default(
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
        
        # Refresh the credentials
        credentials.refresh(Request())
        
        # Which publisher, and therefore which protocol.
        #
        # Model Garden serves Anthropic alongside Google, and they are not
        # interchangeable at the wire: different path, different verb,
        # different body, different response shape. Building a Gemini request
        # for a Claude model produces a 404 that reads like a wrong model name.
        from app.services.ai import vertex_publishers as vp

        model_id = model or "gemini-3.1-flash-lite"
        location = os.getenv("VERTEX_AI_LOCATION") or "global"
        endpoint = vp.endpoint_for(model_id, project_id, location)

        images: List[Dict[str, str]] = []
        for img_b64 in (image_data or [])[:3]:
            if img_b64.startswith('data:'):
                match = re.match(r'data:image/(\w+);base64,(.+)', img_b64)
                if not match:
                    continue
                images.append({"mime_type": f"image/{match.group(1)}", "data": match.group(2)})
            else:
                images.append({"mime_type": "image/jpeg", "data": img_b64})

        payload = vp.build_payload(model_id, prompt, images)

        # Make the API call
        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {credentials.token}",
                    "Content-Type": "application/json"
                },
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Vertex AI API error ({response.status}): {error_text}")
                
                result = await response.json()
        
        # A 200 here means Vertex is reachable and the auth + model are valid.
        # Parse the model's JSON defensively: if the answer text is empty or
        # unparseable (e.g. a trivial connection-test prompt where the token
        # budget went to "thinking"), still report the call as REACHABLE so
        # connectivity checks don't false-negative on a working configuration.
        try:
            text_response = vp.extract_text(model_id, result)
            json_match = re.search(r'```json\s*(.*?)\s*```', text_response, re.DOTALL)
            json_str = json_match.group(1) if json_match else text_response.strip()
            if not json_str:
                raise ValueError("model returned no text output")
            return json.loads(json_str)
        except Exception as parse_err:
            logger.warning(f"[Vertex] reachable but response not parseable: {parse_err}")
            return _gemini_fallback(f"Model reachable but returned no parseable JSON: {parse_err}", reachable=True)

    except Exception as e:
        # Network / auth / HTTP error — genuinely not reachable.
        return _gemini_fallback(str(e), reachable=False)


async def get_historical_context(db, address: str, service_code: str, lat: Optional[float] = None, long: Optional[float] = None, exclude_id: Optional[int] = None, description: str = "") -> Dict[str, Any]:
    """
    Query historical data for context including chronic recurrence and nodal reporting.
    """
    from sqlalchemy import select, func
    from app.models import ServiceRequest
    from datetime import datetime, timedelta
    
    context = {
        "recurrence_count": 0,
        "chronic_factor": False,
        "nearby_similar": 0,
        "duplicate_density": 0,
        "resolution_rate": None,
        "past_resolution_quality": None
    }
    
    # No address is not an address. Matching `address == ""` made every
    # location-less report in a category a "recurrence" of all the others (and
    # chronic at five), so a blank address matches nothing instead.
    from sqlalchemy import false
    addr_filter = (ServiceRequest.address == address) if (address or "").strip() else false()

    try:
        # 1. Chronic Factor: Count reports at this address in last 90 days
        three_months_ago = datetime.now() - timedelta(days=90)
        addr_history_query = select(ServiceRequest.id, ServiceRequest.service_request_id, ServiceRequest.requested_datetime).where(
            addr_filter,
            ServiceRequest.service_code == service_code,  # Category-specific check
            ServiceRequest.requested_datetime >= three_months_ago,
            ServiceRequest.deleted_at.is_(None)
        )
        
        if exclude_id:
            addr_history_query = addr_history_query.where(ServiceRequest.id != exclude_id)
            
        addr_history_query = addr_history_query.order_by(ServiceRequest.requested_datetime.desc())
        
        addr_result = await db.execute(addr_history_query)
        addr_history = addr_result.all()
        
        context["recurrence_count"] = len(addr_history)
        context["chronic_factor"] = len(addr_history) >= 5
        context["recent_address_reports"] = [
            {"id": r[1], "date": r[2].strftime('%Y-%m-%d')} for r in addr_history[:3]
        ]
        
        # 2. Past Resolution Quality (Last closed report at this address)
        last_res_query = select(ServiceRequest.service_request_id, ServiceRequest.closed_substatus, ServiceRequest.completion_message, ServiceRequest.status).where(
            addr_filter,
            ServiceRequest.status == "closed",
            ServiceRequest.deleted_at.is_(None)
        )
        
        if exclude_id:
            last_res_query = last_res_query.where(ServiceRequest.id != exclude_id)
            
        last_res = await db.execute(
            last_res_query.order_by(ServiceRequest.closed_datetime.desc()).limit(1)
        )
        row = last_res.first()
        if row:
            context["past_resolution_quality"] = {
                "request_id": row[0],
                "substatus": row[1],
                "message": row[2]
            }

        # 3. Nodal reporting / Proximity Similarity with TEXT-BASED matching
        if lat is not None and long is not None:
            from geoalchemy2 import Geography
            from sqlalchemy import cast
            from difflib import SequenceMatcher
            point = func.ST_SetSRID(func.ST_MakePoint(long, lat), 4326)
            
            # Nearby candidates (500m, same category) - fetch descriptions for similarity
            nearby_query = select(
                ServiceRequest.service_request_id,
                ServiceRequest.description
            ).where(
                ServiceRequest.service_code == service_code,
                ServiceRequest.status.in_(["open", "in_progress"]),
                ServiceRequest.deleted_at.is_(None),
                func.ST_DWithin(cast(ServiceRequest.location, Geography), cast(point, Geography), 500)
            )
            
            if exclude_id:
                nearby_query = nearby_query.where(ServiceRequest.id != exclude_id)
                
            nearby_result = await db.execute(nearby_query.limit(10))
            nearby_rows = nearby_result.all()
            
            # Compute text similarity for each candidate
            # Get the current request's description from the caller context (passed via address or a new param)
            # For now, we'll store candidates and let the caller filter using the request description
            similar_reports = []
            for row in nearby_rows:
                candidate_id, candidate_desc = row
                if candidate_desc:
                    # Use SequenceMatcher for text similarity between descriptions
                    similarity = SequenceMatcher(None, description.lower(), candidate_desc.lower()).ratio()
                    if similarity > 0.25:  # 25% content match threshold
                        # Build justification explaining why this report is similar
                        similarity_pct = int(similarity * 100)
                        justification = f"Within 500m • Same category • {similarity_pct}% description match"
                        similar_reports.append({
                            "id": candidate_id,
                            "description": candidate_desc[:100] + ("..." if len(candidate_desc) > 100 else ""),
                            "similarity": round(similarity, 2),
                            "justification": justification
                        })
            
            # Sort by similarity and take top 3
            similar_reports.sort(key=lambda x: x["similarity"], reverse=True)
            context["similar_reports"] = similar_reports[:3]
            context["nearby_similar"] = len(similar_reports)
            context["nearby_similar_ids"] = [r["id"] for r in similar_reports[:3]]
            
            # Duplicate Density (Nodal - within 15m)
            nodal_query = select(func.count(ServiceRequest.id)).where(
                ServiceRequest.service_code == service_code,
                ServiceRequest.deleted_at.is_(None),
                func.ST_DWithin(cast(ServiceRequest.location, Geography), cast(point, Geography), 15)
            )
            
            if exclude_id:
                nodal_query = nodal_query.where(ServiceRequest.id != exclude_id)
                
            nodal_result = await db.execute(nodal_query)
            context["duplicate_density"] = nodal_result.scalar() or 0
            
    except Exception as e:
        logger.warning(f"Error getting historical context: {e}")
    
    return context


async def get_spatial_context(db, lat: float, long: float, service_code: str) -> Dict[str, Any]:
    """
    Gather spatial context: Infrastructure proximity, Traffic, Vulnerable Areas, and Lighting.

    Entirely local. Critical infrastructure comes from the town's facility
    store (refreshed weekly in one query, app/services/critical_facilities.py)
    plus the admin's own facility layers; no resident's location is sent to
    any third party, and a slow public API can no longer blank the answer.
    """
    from sqlalchemy import select, func, cast
    from geoalchemy2 import Geography
    from app.models import MapLayer, ServiceRequest
    from app.services import critical_facilities

    spatial_info = {
        "critical_infrastructure": [],
        "nearby_outages": 0,
        "is_high_density": False,
        "is_school_zone": False,
        "vulnerable_pop_impact": "Unknown"
    }

    if lat is None or long is None:
        return spatial_info

    try:
        point = func.ST_SetSRID(func.ST_MakePoint(long, lat), 4326)

        layers = await db.execute(select(MapLayer).where(MapLayer.is_active == True))
        all_layers = layers.scalars().all()

        # 1. Proximity to critical infrastructure, and school zones: the stored
        # facilities merged with the admin's layers, nearest first.
        nearby = await critical_facilities.proximity(db, lat, long, all_layers)
        spatial_info["critical_infrastructure"] = nearby["critical_infrastructure"]
        spatial_info["is_school_zone"] = nearby["is_school_zone"]
        for line in nearby["critical_infrastructure"]:
            logger.info(f"[Critical Infrastructure] {line}")

        # 2. Lighting / Outages (Streetlight reports within 100m)
        outage_query = select(func.count(ServiceRequest.id)).where(
            ServiceRequest.service_code.ilike("%streetlight%"),
            ServiceRequest.status.in_(["open", "in_progress"]),
            ServiceRequest.deleted_at.is_(None),
            func.ST_DWithin(cast(ServiceRequest.location, Geography), cast(point, Geography), 100)
        )
        async with db.begin_nested():
            spatial_info["nearby_outages"] = (await db.execute(outage_query)).scalar() or 0

        # 3. Traffic heuristic
        for layer in all_layers:
            if "traffic" in layer.name.lower() or "arterial" in layer.name.lower():
                spatial_info["is_high_density"] = True

    except Exception as e:
        logger.warning(f"Error getting spatial context: {e}")

    return spatial_info

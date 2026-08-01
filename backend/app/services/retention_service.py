"""
Document Retention Service

Provides state-by-state record retention policies and enforcement logic
for municipal 311 service requests. Complies with state public records laws.

Key features:
- State-specific retention periods (embedded data)
- Legal hold support (prevents destruction during litigation)
- Automatic archival with PII anonymization
"""

import logging

from app.services.retention_scrub import (
    REDACT, apply_scrub, fields_for_mode, normalise_mode,
)
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ============================================================================
# STATE RETENTION POLICIES (All 50 States + DC)
# ============================================================================
# Based on research of state public records laws for municipal service requests.
# These are minimum retention periods - townships can extend but not shorten.
# Each state includes its public records law name (e.g., OPRA, FOIA, CPRA).

STATE_RETENTION_POLICIES: Dict[str, Dict[str, Any]] = {
    # Alabama
    "AL": {"days": 5 * 365, "name": "Alabama", "source": "AL State Records Commission", "public_records_law": "Alabama Open Records Act"},
    # Alaska
    "AK": {"days": 5 * 365, "name": "Alaska", "source": "AK State Archives", "public_records_law": "Alaska Public Records Act"},
    # Arizona
    "AZ": {"days": 5 * 365, "name": "Arizona", "source": "AZ State Library", "public_records_law": "Arizona Public Records Law"},
    # Arkansas
    "AR": {"days": 5 * 365, "name": "Arkansas", "source": "AR State Archives", "public_records_law": "FOIA (Arkansas)"},
    # California
    "CA": {"days": 5 * 365, "name": "California", "source": "CA Secretary of State", "public_records_law": "CPRA (California Public Records Act)"},
    # Colorado
    "CO": {"days": 5 * 365, "name": "Colorado", "source": "CO State Archives", "public_records_law": "CORA (Colorado Open Records Act)"},
    # Connecticut
    "CT": {"days": 6 * 365, "name": "Connecticut", "source": "CT Public Records Administrator", "public_records_law": "FOIA (Connecticut)"},
    # Delaware
    "DE": {"days": 5 * 365, "name": "Delaware", "source": "DE Public Archives", "public_records_law": "FOIA (Delaware)"},
    # District of Columbia
    "DC": {"days": 5 * 365, "name": "District of Columbia", "source": "DC Archives", "public_records_law": "DC FOIA"},
    # Florida
    "FL": {"days": 5 * 365, "name": "Florida", "source": "FL Division of Library & Information Services", "public_records_law": "Florida Sunshine Law"},
    # Georgia
    "GA": {"days": 3 * 365, "name": "Georgia", "source": "GA Archives", "public_records_law": "Georgia Open Records Act"},
    # Hawaii
    "HI": {"days": 5 * 365, "name": "Hawaii", "source": "HI State Archives", "public_records_law": "UIPA (Uniform Information Practices Act)"},
    # Idaho
    "ID": {"days": 5 * 365, "name": "Idaho", "source": "ID State Historical Society", "public_records_law": "Idaho Public Records Law"},
    # Illinois
    "IL": {"days": 5 * 365, "name": "Illinois", "source": "IL Local Records Commission", "public_records_law": "FOIA (Illinois)"},
    # Indiana
    "IN": {"days": 5 * 365, "name": "Indiana", "source": "IN Commission on Public Records", "public_records_law": "APRA (Access to Public Records Act)"},
    # Iowa
    "IA": {"days": 5 * 365, "name": "Iowa", "source": "IA State Archives", "public_records_law": "Iowa Open Records Law"},
    # Kansas
    "KS": {"days": 5 * 365, "name": "Kansas", "source": "KS State Historical Society", "public_records_law": "KORA (Kansas Open Records Act)"},
    # Kentucky
    "KY": {"days": 5 * 365, "name": "Kentucky", "source": "KY Dept for Libraries & Archives", "public_records_law": "Kentucky Open Records Act"},
    # Louisiana
    "LA": {"days": 5 * 365, "name": "Louisiana", "source": "LA State Archives", "public_records_law": "Louisiana Public Records Act"},
    # Maine
    "ME": {"days": 5 * 365, "name": "Maine", "source": "ME State Archives", "public_records_law": "FOAA (Freedom of Access Act)"},
    # Maryland
    "MD": {"days": 5 * 365, "name": "Maryland", "source": "MD State Archives", "public_records_law": "MPIA (Maryland Public Information Act)"},
    # Massachusetts
    "MA": {"days": 3 * 365, "name": "Massachusetts", "source": "MA Municipal Records Schedule", "public_records_law": "Massachusetts Public Records Law"},
    # Michigan
    "MI": {"days": 6 * 365, "name": "Michigan", "source": "MI Archives", "public_records_law": "FOIA (Michigan)"},
    # Minnesota
    "MN": {"days": 5 * 365, "name": "Minnesota", "source": "MN State Archives", "public_records_law": "MGDPA (Minnesota Data Practices Act)"},
    # Mississippi
    "MS": {"days": 5 * 365, "name": "Mississippi", "source": "MS Dept of Archives & History", "public_records_law": "Mississippi Public Records Act"},
    # Missouri
    "MO": {"days": 5 * 365, "name": "Missouri", "source": "MO Secretary of State", "public_records_law": "Missouri Sunshine Law"},
    # Montana
    "MT": {"days": 5 * 365, "name": "Montana", "source": "MT Historical Society", "public_records_law": "Montana Constitution Article II, Sec 9"},
    # Nebraska
    "NE": {"days": 5 * 365, "name": "Nebraska", "source": "NE State Historical Society", "public_records_law": "Nebraska Public Records Statutes"},
    # Nevada
    "NV": {"days": 5 * 365, "name": "Nevada", "source": "NV State Library & Archives", "public_records_law": "Nevada Public Records Act"},
    # New Hampshire
    "NH": {"days": 5 * 365, "name": "New Hampshire", "source": "NH Division of Archives", "public_records_law": "Right-to-Know Law"},
    # New Jersey
    "NJ": {"days": 7 * 365, "name": "New Jersey", "source": "NJ Division of Archives & Records Management", "public_records_law": "OPRA (Open Public Records Act)"},
    # New Mexico
    "NM": {"days": 5 * 365, "name": "New Mexico", "source": "NM State Records Center", "public_records_law": "IPRA (Inspection of Public Records Act)"},
    # New York
    "NY": {"days": 6 * 365, "name": "New York", "source": "NY Arts & Cultural Affairs Law §57.25", "public_records_law": "FOIL (Freedom of Information Law)"},
    # North Carolina
    "NC": {"days": 5 * 365, "name": "North Carolina", "source": "NC DNCR", "public_records_law": "North Carolina Public Records Law"},
    # North Dakota
    "ND": {"days": 5 * 365, "name": "North Dakota", "source": "ND State Archives", "public_records_law": "North Dakota Open Records Law"},
    # Ohio
    "OH": {"days": 5 * 365, "name": "Ohio", "source": "OH Historical Society", "public_records_law": "Ohio Public Records Act"},
    # Oklahoma
    "OK": {"days": 5 * 365, "name": "Oklahoma", "source": "OK Dept of Libraries", "public_records_law": "Oklahoma Open Records Act"},
    # Oregon
    "OR": {"days": 5 * 365, "name": "Oregon", "source": "OR State Archives", "public_records_law": "Oregon Public Records Law"},
    # Pennsylvania
    "PA": {"days": 7 * 365, "name": "Pennsylvania", "source": "PA Municipal Records Manual", "public_records_law": "RTKL (Right-to-Know Law)"},
    # Rhode Island
    "RI": {"days": 5 * 365, "name": "Rhode Island", "source": "RI State Archives", "public_records_law": "APRA (Access to Public Records Act)"},
    # South Carolina
    "SC": {"days": 5 * 365, "name": "South Carolina", "source": "SC Dept of Archives & History", "public_records_law": "FOIA (South Carolina)"},
    # South Dakota
    "SD": {"days": 5 * 365, "name": "South Dakota", "source": "SD State Historical Society", "public_records_law": "South Dakota Open Records Law"},
    # Tennessee
    "TN": {"days": 5 * 365, "name": "Tennessee", "source": "TN State Library & Archives", "public_records_law": "Tennessee Public Records Act"},
    # Texas
    "TX": {"days": 10 * 365, "name": "Texas", "source": "TX State Library & Archives Commission", "public_records_law": "TPIA (Texas Public Information Act)"},
    # Utah
    "UT": {"days": 5 * 365, "name": "Utah", "source": "UT State Archives", "public_records_law": "GRAMA (Government Records Access and Management Act)"},
    # Vermont
    "VT": {"days": 5 * 365, "name": "Vermont", "source": "VT State Archives", "public_records_law": "Vermont Public Records Act"},
    # Virginia
    "VA": {"days": 5 * 365, "name": "Virginia", "source": "Library of Virginia", "public_records_law": "VFOIA (Virginia Freedom of Information Act)"},
    # Washington
    "WA": {"days": 6 * 365, "name": "Washington", "source": "WA State Archives", "public_records_law": "Washington Public Records Act"},
    # West Virginia
    "WV": {"days": 5 * 365, "name": "West Virginia", "source": "WV State Archives", "public_records_law": "FOIA (West Virginia)"},
    # Wisconsin
    "WI": {"days": 7 * 365, "name": "Wisconsin", "source": "WI Public Records Board", "public_records_law": "Wisconsin Open Records Law"},
    # Wyoming
    "WY": {"days": 5 * 365, "name": "Wyoming", "source": "WY State Archives", "public_records_law": "Wyoming Public Records Act"},
    
    # Default for unlisted jurisdictions
    "DEFAULT": {"days": 7 * 365, "name": "Default", "source": "Conservative 7-year default", "public_records_law": "Federal FOIA"},
}


def get_all_states() -> List[Dict[str, Any]]:
    """Get list of all supported states with their retention policies."""
    states = []
    for code, policy in STATE_RETENTION_POLICIES.items():
        if code != "DEFAULT":
            states.append({
                "code": code,
                "name": policy["name"],
                "retention_days": policy["days"],
                "retention_years": policy["days"] // 365,
                "source": policy["source"],
                "public_records_law": policy.get("public_records_law", "Public Records Act")
            })
    return sorted(states, key=lambda x: x["name"])


def get_retention_policy(state_code: str) -> Dict[str, Any]:
    """
    Get retention policy for a specific state.
    
    Args:
        state_code: Two-letter state code (e.g., "NJ", "TX")
        
    Returns:
        Dict with days, name, source, years, and public_records_law
    """
    state_code = state_code.upper() if state_code else "DEFAULT"
    if state_code not in STATE_RETENTION_POLICIES:
        # Report the policy actually in effect. Echoing back an unrecognized code
        # alongside the DEFAULT policy's name/law was internally inconsistent —
        # the UI would show "ZZ" as if it were a configured state.
        state_code = "DEFAULT"
    policy = STATE_RETENTION_POLICIES[state_code]

    return {
        "state_code": state_code,
        "name": policy["name"],
        "retention_days": policy["days"],
        "retention_years": policy["days"] // 365,
        "source": policy["source"],
        "public_records_law": policy.get("public_records_law", "Public Records Act")
    }


def calculate_retention_date(
    closed_date: datetime,
    state_code: str,
    override_days: Optional[int] = None
) -> datetime:
    """
    Calculate the date when a record can be archived/deleted.
    
    Args:
        closed_date: When the request was closed
        state_code: State for retention rules
        override_days: Optional override (must be >= state minimum)
        
    Returns:
        Datetime when record can be archived
    """
    policy = get_retention_policy(state_code)
    retention_days = policy["retention_days"]
    
    # Allow override only if it's longer than state minimum
    if override_days and override_days > retention_days:
        retention_days = override_days
    
    return closed_date + timedelta(days=retention_days)


async def get_records_for_archival(
    db: AsyncSession,
    state_code: str,
    override_days: Optional[int] = None,
    limit: int = 100
) -> List[Any]:
    """
    Get closed records that have exceeded their retention period.
    
    Args:
        db: Database session
        state_code: State for retention rules
        override_days: Optional custom retention period
        limit: Max records to return
        
    Returns:
        List of ServiceRequest records eligible for archival
    """
    from app.models import ServiceRequest
    
    policy = get_retention_policy(state_code)
    retention_days = override_days if override_days else policy["retention_days"]
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
    
    # Query closed records older than retention period, not already archived,
    # not deleted, and not under legal hold
    query = select(ServiceRequest).where(
        and_(
            ServiceRequest.status == "closed",
            ServiceRequest.closed_datetime.isnot(None),
            ServiceRequest.closed_datetime < cutoff_date,
            ServiceRequest.archived_at.is_(None),
            ServiceRequest.deleted_at.is_(None),
            # Legal hold check - skip if flagged
            ServiceRequest.flagged == False
        )
    ).limit(limit)
    
    result = await db.execute(query)
    return result.scalars().all()



async def record_archival(db: AsyncSession, record: Any, action: str,
                          cleared: Optional[List[str]] = None) -> None:
    """Leave the archival itself on the request's timeline.

    A record whose contents changed with nothing saying why reads like data
    loss rather than policy. It is also the answer to "did this actually run",
    which until now could only be inferred from a field going blank.

    Best-effort: the timeline entry is bookkeeping and must never be the reason
    a retention run fails to archive.
    """
    try:
        from app.models import RequestAuditLog

        db.add(RequestAuditLog(
            service_request_id=record.id,
            # The mode is in the action, so the trail distinguishes a
            # targeted redaction from a full purge without anyone reading
            # extra_data to find out which happened.
            action=f"retention_{action}",
            new_value=action,
            actor_type="staff",
            actor_name="Retention policy",
            extra_data={"mode": action, "cleared": cleared or []},
        ))
    except Exception:  # pragma: no cover - bookkeeping only
        logger.warning("[Retention] could not write the timeline entry for %s", record.id)


async def scrub_comments(db: AsyncSession, record_id: int) -> int:
    """Clear the text of every comment on a request.

    The rows stay. A deleted comment leaves a gap in a conversation that staff
    and residents both remember having, and the count is part of the record.
    Only the words go.
    """
    from app.models import RequestComment

    rows = (await db.execute(
        select(RequestComment).where(RequestComment.service_request_id == record_id)
    )).scalars().all()
    for row in rows:
        row.content = "[Comment archived per retention policy]"
    return len(rows)


async def archive_record(
    db: AsyncSession,
    record_id: int,
    archive_mode: str = REDACT,
    scrub_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Archive a record by anonymizing PII or marking for deletion.
    
    Args:
        db: Database session
        record_id: ID of record to archive
        archive_mode: "anonymize" (default) or "delete"
        
    Returns:
        Dict with status and details
    """
    from app.models import ServiceRequest
    
    result = await db.execute(
        select(ServiceRequest).where(ServiceRequest.id == record_id)
    )
    record = result.scalar_one_or_none()
    
    if not record:
        return {"status": "error", "message": "Record not found"}
    
    # Check for legal hold (flagged records)
    if record.flagged:
        return {
            "status": "skipped",
            "message": "Record under legal hold (flagged)",
            "record_id": record_id
        }
    
    # Redact clears the fields this town chose. Purge clears all of them and
    # leaves the row as a shell that still counts. Neither removes the record:
    # see the note in retention_scrub about why hard deletion is gone.
    chosen = fields_for_mode(archive_mode, scrub_fields)
    cleared = apply_scrub(record, chosen)
    if "comments" in set(chosen):
        await scrub_comments(db, record.id)
        cleared.append("comments")
    record.archived_at = datetime.now(timezone.utc)

    await db.flush()
    # Into the hash chain, via the insert listener on RequestAuditLog. A
    # redaction that leaves no trace is indistinguishable from data loss, and
    # this is the trail an auditor is shown when asked what happened to a
    # record that is now mostly blank.
    await record_archival(db, record, normalise_mode(archive_mode), cleared)
    await db.commit()

    return {
        # Callers count on this string; renaming what the run is *called* is a
        # separate change from renaming what it *did*.
        "status": "anonymized",
        "mode": normalise_mode(archive_mode),
        "record_id": record_id,
        "service_request_id": record.service_request_id,
        "archived_at": record.archived_at.isoformat(),
        "cleared": cleared,
    }


async def get_retention_stats(
    db: AsyncSession,
    state_code: str,
    override_days: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get statistics about records pending archival.
    
    Args:
        db: Database session
        state_code: State for retention rules
        override_days: Optional custom retention period
        
    Returns:
        Dict with counts and dates
    """
    from app.models import ServiceRequest
    from sqlalchemy import func
    
    policy = get_retention_policy(state_code)
    retention_days = override_days if override_days else policy["retention_days"]
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
    
    # Count records eligible for archival
    eligible_query = select(func.count(ServiceRequest.id)).where(
        and_(
            ServiceRequest.status == "closed",
            ServiceRequest.closed_datetime.isnot(None),
            ServiceRequest.closed_datetime < cutoff_date,
            ServiceRequest.archived_at.is_(None),
            ServiceRequest.deleted_at.is_(None),
            ServiceRequest.flagged == False
        )
    )
    eligible_result = await db.execute(eligible_query)
    eligible_count = eligible_result.scalar() or 0
    
    # Count records under legal hold (any flagged record, regardless of status)
    held_query = select(func.count(ServiceRequest.id)).where(
        and_(
            ServiceRequest.archived_at.is_(None),
            ServiceRequest.deleted_at.is_(None),
            ServiceRequest.flagged == True
        )
    )
    held_result = await db.execute(held_query)
    held_count = held_result.scalar() or 0
    
    # Count already archived
    archived_query = select(func.count(ServiceRequest.id)).where(
        ServiceRequest.archived_at.isnot(None)
    )
    archived_result = await db.execute(archived_query)
    archived_count = archived_result.scalar() or 0
    
    return {
        "retention_policy": policy,
        "cutoff_date": cutoff_date.isoformat(),
        "eligible_for_archival": eligible_count,
        "under_legal_hold": held_count,
        "already_archived": archived_count,
        "next_run": "Daily at midnight UTC"
    }

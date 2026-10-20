"""
Document Retention Service

Enforces the retention schedule a municipality has told us it is on: which
closed records have passed their period, and what a run clears from them.

This module used to *supply* the schedule as well as enforce it, from a table
of periods and statutes for all 51 US jurisdictions that nobody had verified.
The table is gone; see app/services/retention_config.py for why, and for what
an unconfigured town gets instead. Every function here now takes the period the
town itself set, and there is no fallback to take if it is missing.

Key features:
- Legal hold support (prevents destruction during litigation)
- Archival by redacting the fields the town chose, or purging all of them
"""

import logging

from app.services.retention_scrub import (
    REDACT, apply_scrub, fields_for_mode, normalise_mode, upload_filenames,
)
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def upload_directory() -> str:
    """Where POST /api/system/upload puts photos. Same default as main.py."""
    import os

    return os.environ.get("UPLOAD_DIR", "/project/uploads")


def delete_upload_files(names: List[str]) -> List[str]:
    """Delete uploaded photo files by bare filename. Returns what went.

    The catalog entry for "Photos" told towns that "the files themselves are
    removed by the storage cleanup that follows". There was no storage cleanup.
    Nothing anywhere deleted from UPLOAD_DIR, so a town that ticked Photos --
    or ran a full purge, which ticks everything -- had the links cleared out of
    the database and every image still sitting on disk, served by the
    unauthenticated /api/uploads static mount to anyone who had the URL.

    This is the cleanup that was being promised. It lives here rather than in
    retention_scrub because that module is deliberately pure, which is what lets
    CI run it without a filesystem.

    A file that cannot be deleted is logged and the run continues: the database
    redaction is the part with the legal weight, and aborting a retention run
    over one unlinkable file would leave the rest of the record intact.
    """
    import os

    directory = upload_directory()
    removed: List[str] = []
    for name in names:
        # upload_filenames() has already refused anything that is not a bare
        # filename. Joining is safe, and the check is repeated at the boundary
        # that actually touches the disk rather than trusted from a caller.
        if name != os.path.basename(name):
            logger.warning("[Retention] refusing to delete a non-basename path: %r", name)
            continue
        path = os.path.join(directory, name)
        try:
            os.remove(path)
            removed.append(name)
        except FileNotFoundError:
            # Already gone. The record's promise is that it is not reachable,
            # and it is not.
            removed.append(name)
        except Exception as exc:
            logger.warning("[Retention] could not delete uploaded photo %s: %s",
                           name, str(exc)[:200])
    if removed:
        logger.info("[Retention] deleted %d uploaded photo file(s)", len(removed))
    return removed


# One definition of the cutoff, shared by the eligibility query, the stats
# panel, and the preview an administrator confirms against. A preview computed
# differently from the run invites somebody to confirm against a list that is
# not the list.
from app.services.retention_window import retention_cutoff


async def get_records_for_archival(
    db: AsyncSession,
    retention_days: int,
    limit: int = 100
) -> List[Any]:
    """
    Get closed records that have exceeded their retention period.

    Args:
        db: Database session
        retention_days: The retention period this town configured
        limit: Max records to return

    Returns:
        List of ServiceRequest records eligible for archival
    """
    from app.models import ServiceRequest

    cutoff_date = retention_cutoff(retention_days)

    # Query closed records older than retention period, not already archived,
    # not deleted, and not under legal hold
    query = select(ServiceRequest).where(
        and_(
            ServiceRequest.status == "closed",
            ServiceRequest.closed_datetime.isnot(None),
            ServiceRequest.closed_datetime < cutoff_date,
            ServiceRequest.archived_at.is_(None),
            ServiceRequest.deleted_at.is_(None),
            # Legal hold check. Reads `legal_hold`, NOT `flagged`: `flagged` is
            # the content-moderation marker and an anonymous public comment can
            # set it, which made "rude comment on your neighbour's report"
            # a way to exempt that neighbour's PII from the retention policy
            # forever. See the a1c2e3f4b5d6 migration.
            ServiceRequest.legal_hold == False
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


async def comment_texts(db: AsyncSession, record_id: int) -> List[str]:
    """The comment text on a request, read before it is cleared (for the translation cache)."""
    from app.models import RequestComment

    rows = (await db.execute(
        select(RequestComment.content).where(RequestComment.service_request_id == record_id)
    )).all()
    return [r[0] for r in rows if r[0]]


ARCHIVED_COPY = "[Content archived per retention policy]"


async def scrub_description_copies(db: AsyncSession, service_request_id: str) -> int:
    """Clear this request's description where other requests quote it.

    The triage context of every later report nearby stores the first 100
    characters of up to three "similar reports" -- this one's words, under this
    one's id, in somebody else's row. Redacting the description here left those
    copies in records that may be kept years longer.
    """
    from sqlalchemy import String, cast
    from app.models import ServiceRequest

    needle = f'"{service_request_id}"'
    rows = (await db.execute(
        select(ServiceRequest).where(cast(ServiceRequest.ai_analysis, String).contains(needle))
    )).scalars().all()
    changed = 0
    for row in rows:
        analysis = row.ai_analysis
        if not isinstance(analysis, dict):
            continue
        analysis = dict(analysis)
        touched = False
        for holder in (analysis, analysis.get("context") if isinstance(analysis.get("context"), dict) else None):
            if holder is None or not isinstance(holder.get("similar_reports"), list):
                continue
            entries = []
            for entry in holder["similar_reports"]:
                if isinstance(entry, dict) and entry.get("id") == service_request_id and entry.get("description") != ARCHIVED_COPY:
                    entry = {**entry, "description": ARCHIVED_COPY}
                    entry.pop("justification", None)   # model prose about the same text
                    touched = True
                entries.append(entry)
            if holder is analysis:
                analysis["similar_reports"] = entries
            else:
                analysis["context"] = {**holder, "similar_reports": entries}
        if touched:
            row.ai_analysis = analysis
            changed += 1
    return changed


async def purge_cached_translations(db: AsyncSession, texts: List[str]) -> int:
    """Drop cached translations of text that retention just cleared.

    Status messages and closing notes are translated into a resident's language
    and cached, and the portal's page translation passes report text through the
    same cache. Without this the words survive retention in `translations`,
    in two languages.
    """
    from sqlalchemy import delete
    from app.models import Translation

    texts = [t for t in {t for t in texts if t and t.strip()}]
    if not texts:
        return 0
    result = await db.execute(delete(Translation).where(Translation.source_text.in_(texts)))
    return result.rowcount or 0


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
    
    # Check for legal hold. `legal_hold`, not `flagged` -- see the note in
    # get_records_for_archival.
    if record.legal_hold:
        return {
            "status": "skipped",
            "message": "Record under legal hold",
            "record_id": record_id
        }
    
    # Redact clears the fields this town chose. Purge clears all of them and
    # leaves the row as a shell that still counts. Neither removes the record:
    # see the note in retention_scrub about why hard deletion is gone.
    chosen = fields_for_mode(archive_mode, scrub_fields)
    # Read the photo filenames BEFORE apply_scrub clears the columns that name
    # them -- afterwards there is nothing left to say which files to delete.
    photo_files = upload_filenames(record) if "media" in set(chosen) else []
    # Likewise the text about to be cleared, so its cached translations can go.
    old_texts: List[str] = []
    if "description" in set(chosen):
        old_texts.append(record.description or "")
    if "closing_message" in set(chosen):
        old_texts.append(getattr(record, "completion_message", None) or "")
    if "comments" in set(chosen):
        old_texts.extend(await comment_texts(db, record.id))
    cleared = apply_scrub(record, chosen)
    if photo_files:
        delete_upload_files(photo_files)
    if "comments" in set(chosen):
        await scrub_comments(db, record.id)
        cleared.append("comments")
    if "description" in set(chosen):
        await scrub_description_copies(db, record.service_request_id)
    await purge_cached_translations(db, old_texts)
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
    retention_days: int,
) -> Dict[str, Any]:
    """
    Get statistics about records pending archival.

    Args:
        db: Database session
        retention_days: The retention period this town configured

    Returns:
        Dict with counts and dates
    """
    from app.models import ServiceRequest
    from sqlalchemy import func
    
    cutoff_date = retention_cutoff(retention_days)
    
    # Count records eligible for archival
    eligible_query = select(func.count(ServiceRequest.id)).where(
        and_(
            ServiceRequest.status == "closed",
            ServiceRequest.closed_datetime.isnot(None),
            ServiceRequest.closed_datetime < cutoff_date,
            ServiceRequest.archived_at.is_(None),
            ServiceRequest.deleted_at.is_(None),
            ServiceRequest.legal_hold == False
        )
    )
    eligible_result = await db.execute(eligible_query)
    eligible_count = eligible_result.scalar() or 0
    
    # Count records under legal hold, regardless of status
    held_query = select(func.count(ServiceRequest.id)).where(
        and_(
            ServiceRequest.archived_at.is_(None),
            ServiceRequest.deleted_at.is_(None),
            ServiceRequest.legal_hold == True
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
        "retention_days": retention_days,
        "cutoff_date": cutoff_date.isoformat(),
        "eligible_for_archival": eligible_count,
        "under_legal_hold": held_count,
        "already_archived": archived_count,
        "next_run": "Daily at midnight UTC"
    }

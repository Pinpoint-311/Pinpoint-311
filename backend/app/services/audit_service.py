"""
Audit logging service for government-compliant authentication event tracking.
Implements NIST 800-53 AU-2, AU-3, AU-6, AU-9, AU-12 controls.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app.models import AuditLog, AuditAnchor, User
from app.core import audit_chain

# Rows read per query while verifying, so a seven-year table is never loaded
# into memory at once.
VERIFY_BATCH_SIZE = 1000

# purge_old_ip_addresses deletes ip_address/user_agent (and the salt that
# commits to them) after 90 days. A row whose context was removed while it was
# still well inside that window was not redacted by retention. One day of
# slack keeps a nightly purge racing the clock from looking like tampering.
CONTEXT_RETENTION_DAYS = 90
_EARLY_REDACTION = timedelta(days=CONTEXT_RETENTION_DAYS - 1)


def _prefix(value: Optional[str]) -> Optional[str]:
    return value[:12] if value else None


class AuditService:
    """
    Service for logging authentication events with tamper detection.

    Each entry is chained to the one before it when it is flushed (the
    before_flush listener in app.models, scheme in app.core.audit_chain).
    """

    @staticmethod
    async def log_event(
        db: Session,
        event_type: str,
        success: bool,
        username: Optional[str] = None,
        user_id: Optional[int] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        session_id: Optional[str] = None,
        failure_reason: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Log an authentication event to the audit trail.
        
        Args:
            event_type: Type of event (login_success, login_failed, etc.)
            success: Whether the event was successful
            username: Username (for failed attempts, this is the attempted username)
            user_id: User ID (null for failed login attempts)
            ip_address: Client IP address
            user_agent: Client user agent string
            session_id: Session/JWT identifier
            failure_reason: Reason for failure (if success=False)
            details: Additional event-specific data
        
        Returns:
            Created AuditLog entry
        """
        # previous_hash/entry_hash/chain_version are filled in at flush time,
        # under the chain lock; the timestamp is set here so the stored value
        # is the hashed value.
        audit_log = AuditLog(
            user_id=user_id,
            username=username,
            event_type=event_type,
            success=success,
            failure_reason=failure_reason,
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id,
            details=details,
            timestamp=datetime.now(timezone.utc),
        )
        
        db.add(audit_log)
        await db.commit()
        await db.refresh(audit_log)
        
        return audit_log
    
    @staticmethod
    async def log_login_success(
        db: Session,
        user: User,
        ip_address: str,
        user_agent: str,
        session_id: str,
        mfa_used: Optional[str] = None
    ) -> AuditLog:
        """Log successful login"""
        details = {}
        if mfa_used:
            details["mfa_type"] = mfa_used
        
        return await AuditService.log_event(
            db=db,
            event_type="login_success",
            success=True,
            username=user.username,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id,
            details=details
        )
    
    @staticmethod
    async def log_login_failed(
        db: Session,
        username: str,
        ip_address: str,
        user_agent: str,
        reason: str
    ) -> AuditLog:
        """Log failed login attempt"""
        return await AuditService.log_event(
            db=db,
            event_type="login_failed",
            success=False,
            username=username,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason=reason
        )
    
    @staticmethod
    async def log_logout(
        db: Session,
        user: User,
        ip_address: str,
        session_id: str
    ) -> AuditLog:
        """Log user logout"""
        return await AuditService.log_event(
            db=db,
            event_type="logout",
            success=True,
            username=user.username,
            user_id=user.id,
            ip_address=ip_address,
            session_id=session_id
        )
    
    @staticmethod
    async def log_role_change(
        db: Session,
        user: User,
        old_role: str,
        new_role: str,
        changed_by: str,
        ip_address: str
    ) -> AuditLog:
        """Log role/permission change"""
        return await AuditService.log_event(
            db=db,
            event_type="role_changed",
            success=True,
            username=user.username,
            user_id=user.id,
            ip_address=ip_address,
            details={
                "old_role": old_role,
                "new_role": new_role,
                "changed_by": changed_by
            }
        )
    
    @staticmethod
    async def verify_integrity(db, batch_size: int = VERIFY_BATCH_SIZE) -> Dict[str, Any]:
        """Recompute the audit_logs chain from stored data and check anchors.

        Reads the table in id order, ``batch_size`` rows at a time. Rows of
        chain version 1 at the start of the table are counted as a legacy
        segment that cannot be recomputed (their hash covered a timestamp that
        was never stored); verification starts at the first version 2 row,
        which must link to the last legacy row's stored hash. A version 1 row
        after that point is a break -- it is how an edit would be hidden.

        Every anchor that recorded this chain must still be found at its head
        id, with the same hash and the same number of rows up to it, so
        deleting entries from the tail is detected.

        Stops at the first problem and reports it. Rows inserted while this
        runs are outside the snapshot (``id <= max(id)`` taken at the start).
        """
        # Anchors before max(id): any anchored head was committed before its
        # anchor, so it is <= the max read afterwards.
        anchors = list((await db.execute(
            select(AuditAnchor.id, AuditAnchor.created_at, AuditAnchor.auth_head_id,
                   AuditAnchor.auth_head_hash, AuditAnchor.auth_entry_count,
                   AuditAnchor.auth_legacy_count)
            .where(AuditAnchor.auth_head_id.isnot(None))
            .order_by(AuditAnchor.auth_head_id, AuditAnchor.id)
        )).all())
        max_id = (await db.execute(select(func.max(AuditLog.id)))).scalar()
        total = 0
        if max_id is not None:
            total = (await db.execute(
                select(func.count()).select_from(AuditLog).where(AuditLog.id <= max_id)
            )).scalar() or 0

        result: Dict[str, Any] = {
            "integrity_valid": True,
            "total_entries": total,
            "legacy_entries": 0,
            "verified_entries": 0,
            "redacted_context_entries": 0,
            "first_verified_id": None,
            "anchors_total": len(anchors),
            "anchors_checked": 0,
            "first_break": None,
        }

        def _break(row_id, ts, reason, expected=None, stored=None):
            result["integrity_valid"] = False
            result["first_break"] = {
                "id": row_id,
                "timestamp": audit_chain.timestamp_text(ts),
                "reason": reason,
                "expected_hash_prefix": _prefix(expected),
                "stored_hash_prefix": _prefix(stored),
            }
            return result

        now = datetime.now(timezone.utc)
        cols = AuditLog.__table__.c
        position = 0              # rows seen so far (legacy included)
        last_stored: Optional[str] = None
        seen_v2 = False
        a = 0                     # next anchor to check
        last_id = 0

        while max_id is not None and last_id < max_id:
            rows = (await db.execute(
                select(cols.id, cols.timestamp, cols.event_type, cols.success,
                       cols.failure_reason, cols.username, cols.user_id,
                       cols.session_id, cols.details, cols.ip_address,
                       cols.user_agent, cols.context_salt, cols.context_digest,
                       cols.previous_hash, cols.entry_hash, cols.chain_version)
                .where(cols.id > last_id, cols.id <= max_id)
                .order_by(cols.id)
                .limit(batch_size)
            )).all()
            if not rows:
                break
            for row in rows:
                # An anchored head that the scan stepped over has been deleted.
                if a < len(anchors) and anchors[a].auth_head_id < row.id:
                    an = anchors[a]
                    return _break(an.auth_head_id, an.created_at,
                                  f"anchored entry {an.auth_head_id} (anchor {an.id}) is missing from the chain",
                                  an.auth_head_hash, None)
                position += 1
                version = row.chain_version or audit_chain.LEGACY_CHAIN_VERSION

                if version == audit_chain.LEGACY_CHAIN_VERSION:
                    if seen_v2:
                        return _break(row.id, row.timestamp,
                                      "legacy-format entry after the chain upgrade (cannot be verified)",
                                      None, row.entry_hash)
                    result["legacy_entries"] += 1
                elif version == audit_chain.CHAIN_VERSION:
                    if not seen_v2:
                        seen_v2 = True
                        result["first_verified_id"] = row.id
                    expected = audit_chain.compute_hash(row, row.previous_hash)
                    if expected != row.entry_hash:
                        return _break(row.id, row.timestamp, "entry contents do not match its hash",
                                      expected, row.entry_hash)
                    if row.previous_hash != last_stored:
                        return _break(row.id, row.timestamp,
                                      "link to the previous entry is broken (an entry was removed, inserted or reordered)",
                                      last_stored, row.previous_hash)
                    if row.context_salt is not None:
                        if audit_chain.context_digest(row.context_salt, row.ip_address,
                                                      row.user_agent) != row.context_digest:
                            return _break(row.id, row.timestamp,
                                          "IP address or user agent does not match its recorded commitment",
                                          row.context_digest, None)
                    elif row.ip_address is not None or row.user_agent is not None:
                        return _break(row.id, row.timestamp,
                                      "IP address or user agent present without a commitment")
                    elif row.context_digest is not None:
                        if row.timestamp is not None and \
                                audit_chain.normalize_timestamp(row.timestamp) > now - _EARLY_REDACTION:
                            return _break(row.id, row.timestamp,
                                          f"IP address removed inside the {CONTEXT_RETENTION_DAYS}-day retention window")
                        result["redacted_context_entries"] += 1
                    result["verified_entries"] += 1
                else:
                    return _break(row.id, row.timestamp, f"unknown chain version {version}")

                while a < len(anchors) and anchors[a].auth_head_id == row.id:
                    an = anchors[a]
                    if an.auth_head_hash != row.entry_hash:
                        return _break(row.id, row.timestamp,
                                      f"entry no longer has the hash recorded by anchor {an.id}",
                                      an.auth_head_hash, row.entry_hash)
                    if an.auth_entry_count is not None and an.auth_entry_count != position:
                        return _break(row.id, row.timestamp,
                                      f"anchor {an.id} recorded {an.auth_entry_count} entries up to here; "
                                      f"{position} remain")
                    if an.auth_legacy_count is not None and an.auth_legacy_count != result["legacy_entries"]:
                        return _break(row.id, row.timestamp,
                                      f"anchor {an.id} recorded {an.auth_legacy_count} legacy entries up to here; "
                                      f"{result['legacy_entries']} are now marked legacy")
                    result["anchors_checked"] += 1
                    a += 1

                last_stored = row.entry_hash
                last_id = row.id

        if a < len(anchors):
            an = anchors[a]
            return _break(an.auth_head_id, an.created_at,
                          f"chain truncated: anchored entry {an.auth_head_id} (anchor {an.id}) "
                          f"is beyond the last remaining entry",
                          an.auth_head_hash, last_stored)
        return result

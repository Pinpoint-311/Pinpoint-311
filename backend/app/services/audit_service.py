"""
Audit logging service for government-compliant authentication event tracking.
Implements NIST 800-53 AU-2, AU-3, AU-6, AU-9, AU-12 controls.
"""

import hashlib
import json
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, desc
from app.models import AuditLog, User


class AuditService:
    """
    Service for logging authentication events with tamper detection.
    
    Each log entry includes a hash of the previous entry to detect tampering.
    """
    
    @staticmethod
    def _compute_hash(entry_data: Dict[str, Any]) -> str:
        """Compute SHA-256 hash of audit log entry for tamper detection"""
        # Sort keys for consistent hashing
        canonical = json.dumps(entry_data, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()
    
    @staticmethod
    def _get_last_entry_hash(db: Session) -> Optional[str]:
        """Get hash of the most recent audit log entry"""
        result = db.execute(
            select(AuditLog.entry_hash)
            .order_by(desc(AuditLog.id))
            .limit(1)
        )
        last_entry = result.scalar_one_or_none()
        return last_entry
    
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
        # Get previous hash for integrity chain
        previous_hash = AuditService._get_last_entry_hash(db)
        
        # Prepare entry data for hashing
        entry_data = {
            "event_type": event_type,
            "success": success,
            "username": username,
            "user_id": user_id,
            "ip_address": ip_address,
            "timestamp": datetime.utcnow().isoformat(),
            "session_id": session_id,
            "details": details or {}
        }
        
        # Compute this entry's hash
        entry_hash = AuditService._compute_hash(entry_data)
        
        # Create audit log entry
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
            previous_hash=previous_hash,
            entry_hash=entry_hash
        )
        
        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)
        
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
    async def verify_integrity(db: Session, start_id: Optional[int] = None) -> bool:
        """
        Verify the integrity of the audit log chain.
        
        Args:
            start_id: Optional starting ID to verify from (verifies all if None)
        
        Returns:
            True if chain is intact, False if tampering detected
        """
        query = select(AuditLog).order_by(AuditLog.id)
        if start_id:
            query = query.where(AuditLog.id >= start_id)
        
        result = db.execute(query)
        logs = result.scalars().all()
        
        previous_hash = None
        for log in logs:
            # Verify this entry's hash matches stored hash
            entry_data = {
                "event_type": log.event_type,
                "success": log.success,
                "username": log.username,
                "user_id": log.user_id,
                "ip_address": log.ip_address,
                "timestamp": log.timestamp.isoformat(),
                "session_id": log.session_id,
                "details": log.details or {}
            }
            computed_hash = AuditService._compute_hash(entry_data)
            
            if computed_hash != log.entry_hash:
                return False  # Entry has been tampered with
            
            # Verify chain linkage
            if previous_hash != log.previous_hash:
                return False  # Chain has been broken
            
            previous_hash = log.entry_hash
        
        return True

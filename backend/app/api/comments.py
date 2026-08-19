"""
Comments API for two-way communication on service requests
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.db.session import get_db
from app.models import RequestAuditLog, RequestComment, User
from app.schemas import RequestCommentCreate, RequestCommentResponse
from app.core.auth import get_current_user, get_current_staff
from app.api.scoping import scoped_request
from app.services.enqueue import enqueue

router = APIRouter(prefix="/api/requests", tags=["comments"])


@router.get("/{request_id}/comments", response_model=List[RequestCommentResponse])
async def get_comments(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff)
):
    """Get all comments for a service request (staff/admin, own departments).

    Includes INTERNAL notes, which is why the department scope matters here as
    much as on the request itself: without it any staffer could read the
    internal discussion on another department's report by walking the integer
    ids, which are sequential.
    """
    request = await scoped_request(db, current_user, record_id=request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Service request not found")
    
    # Get comments
    result = await db.execute(
        select(RequestComment)
        .where(RequestComment.service_request_id == request_id)
        .order_by(RequestComment.created_at.asc())
    )
    comments = result.scalars().all()
    
    return comments


@router.post("/{request_id}/comments", response_model=RequestCommentResponse)
async def create_comment(
    request_id: int,
    comment_data: RequestCommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff)
):
    """Add a comment to a service request (staff/admin, own departments)"""
    request = await scoped_request(db, current_user, record_id=request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Service request not found")
    
    # Create comment
    comment = RequestComment(
        service_request_id=request_id,
        user_id=current_user.id,
        username=current_user.username,
        content=comment_data.content,
        visibility=comment_data.visibility.value
    )
    
    db.add(comment)

    # Same timeline entry as the public path. `new_value` carries the
    # visibility rather than the text: an internal note is a different event to
    # a reply the resident can read, and the timeline is shown to both.
    #
    # The comment body stays in request_comments, which is what the retention
    # policy scrubs. The audit trail is append-only, so a copy here would be a
    # copy the scrub cannot reach.
    db.add(RequestAuditLog(
        service_request_id=request_id,
        action="comment_added",
        new_value=comment_data.visibility.value,
        actor_type="staff",
        actor_name=current_user.username,
    ))
    await db.commit()
    await db.refresh(comment)

    # Everything below is enqueued, never called: the comment is committed, and
    # a broker that is unreachable must cost a notification rather than turn a
    # saved comment into a 500 that invites the author to post it twice.
    #
    # Send notification to resident if comment is public/external
    if comment_data.visibility.value == "external":
        from app.tasks.service_requests import send_comment_notification_task
        enqueue(
            send_comment_notification_task,
            request_id,
            current_user.full_name or current_user.username,
            comment_data.content
        )

        # Mirror the comment to linked govtech platforms
        from app.tasks.integrations import push_comment_to_integrations
        enqueue(push_comment_to_integrations, comment.id)

    # Notify assigned staff / department of the comment (internal or external),
    # respecting each user's notification preferences. The commenter is skipped.
    from app.tasks.service_requests import notify_staff_of_activity
    enqueue(notify_staff_of_activity, request_id, "comments", actor=current_user.username)

    return comment


@router.delete("/{request_id}/comments/{comment_id}")
async def delete_comment(
    request_id: int,
    comment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a comment (only owner or admin can delete)"""
    result = await db.execute(
        select(RequestComment)
        .where(RequestComment.id == comment_id)
        .where(RequestComment.service_request_id == request_id)
    )
    comment = result.scalar_one_or_none()
    
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    
    # Check authorization: only comment owner or admin can delete
    if comment.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to delete this comment")
    
    await db.delete(comment)
    await db.commit()
    
    return {"message": "Comment deleted"}

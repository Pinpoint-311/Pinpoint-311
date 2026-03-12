"""
Comments API for two-way communication on service requests
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.db.session import get_db
from app.models import RequestComment, ServiceRequest, User
from app.schemas import RequestCommentCreate, RequestCommentResponse
from app.core.auth import get_current_user

router = APIRouter(prefix="/api/requests", tags=["comments"])


@router.get("/{request_id}/comments", response_model=List[RequestCommentResponse])
async def get_comments(
    request_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all comments for a service request"""
    # Verify request exists
    result = await db.execute(
        select(ServiceRequest).where(ServiceRequest.id == request_id)
    )
    request = result.scalar_one_or_none()
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
    current_user: User = Depends(get_current_user)
):
    """Add a comment to a service request"""
    # Verify request exists
    result = await db.execute(
        select(ServiceRequest).where(ServiceRequest.id == request_id)
    )
    request = result.scalar_one_or_none()
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
    await db.commit()
    await db.refresh(comment)
    
    # Send notification to resident if comment is public/external
    if comment_data.visibility.value == "external":
        from app.tasks.service_requests import send_comment_notification_task
        send_comment_notification_task.delay(
            request_id,
            current_user.full_name or current_user.username,
            comment_data.content
        )
    
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

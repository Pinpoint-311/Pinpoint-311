"""Built-in practice vendor for verifying integrations without vendor access.

This mounts a tiny in-memory "town system" at /api/integrations/sandbox-vendor
that speaks the same REST shape as the vendor-issued connectors. Connecting
the "Practice Sandbox" platform to it exercises the ENTIRE real pipeline —
push on submit, photo upload, comment sync both ways, status pull, asset
layer sync, and new-record import — with no external account.

To make the demo self-driving, the sandbox simulates a town crew:
  ~90 seconds after a request arrives it moves to "in_progress" and gains a
  comment; ~4 minutes after arrival it becomes "completed". The next pull
  (or "Check for updates") mirrors those changes back into Pinpoint.

Data is in-memory and process-local: restarting the backend clears it. The
store is capped, and the endpoints only ever serve this practice data.
"""

import itertools
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)

router = APIRouter()

MAX_REQUESTS = 200
_counter = itertools.count(1)

# Pre-seeded record that "originated" in the sandbox town system — lets the
# import_new_records flow be demonstrated without a second system.
_SEED = {
    "id": "SBX-SEED-1",
    "status": "new",
    "description": "Practice record: a pothole reported directly in the sandbox town system. "
                   "Turn on 'import new records' to watch it appear in Pinpoint.",
    "category": "Pothole",
    "address": "12 Practice Lane",
    "latitude": 40.2206,
    "longitude": -74.7597,
    "created_ts": time.time(),
    "comments": [],
    "documents": 0,
    "manual_status": None,
}

_requests: Dict[str, Dict[str, Any]] = {_SEED["id"]: dict(_SEED)}


def _now_iso(ts: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(ts or time.time()))


def _simulated(item: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the pretend town crew's progress to a stored request."""
    age = time.time() - item["created_ts"]
    status = item["manual_status"]
    comments = list(item["comments"])
    if status is None:
        if age > 240:
            status = "completed"
        elif age > 90:
            status = "in_progress"
        else:
            status = "new"
    if age > 90 and not any(c["id"] == f"{item['id']}-auto1" for c in comments):
        comments.append({
            "id": f"{item['id']}-auto1",
            "content": "Practice update from the sandbox town system: a work crew has been assigned.",
            "author": "Sandbox Crew",
            "created_at": _now_iso(item["created_ts"] + 90),
        })
    if age > 240 and item["manual_status"] is None and not any(c["id"] == f"{item['id']}-auto2" for c in comments):
        comments.append({
            "id": f"{item['id']}-auto2",
            "content": "Practice update: work completed. This request will now show as closed in Pinpoint after the next update check.",
            "author": "Sandbox Crew",
            "created_at": _now_iso(item["created_ts"] + 240),
        })
    return {
        "id": item["id"],
        "status": status,
        "description": item["description"],
        "category": item.get("category"),
        "address": item.get("address"),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "updated_at": _now_iso(),
        "comments": comments,
        "documents": item["documents"],
    }


def _get_or_404(request_id: str) -> Dict[str, Any]:
    item = _requests.get(request_id)
    if not item:
        raise HTTPException(status_code=404, detail="No such practice request")
    return item


@router.get("/requests")
async def sandbox_list(limit: int = 100):
    items = sorted(_requests.values(), key=lambda r: r["created_ts"], reverse=True)[:limit]
    return {"results": [_simulated(i) for i in items]}


@router.post("/requests", status_code=201)
@limiter.limit("60/minute")
async def sandbox_create(request: Request, body: Dict[str, Any] = Body(...)):
    if len(_requests) >= MAX_REQUESTS:
        # Drop the oldest non-seed record to stay bounded
        oldest = min((r for r in _requests.values() if r["id"] != _SEED["id"]),
                     key=lambda r: r["created_ts"], default=None)
        if oldest:
            _requests.pop(oldest["id"], None)
    rid = f"SBX-{next(_counter):04d}"
    _requests[rid] = {
        "id": rid,
        "status": "new",
        "description": str(body.get("description") or "")[:2000],
        "category": str(body.get("category") or body.get("category_code") or "")[:100],
        "address": str(body.get("address") or "")[:300],
        "latitude": body.get("latitude"),
        "longitude": body.get("longitude"),
        "created_ts": time.time(),
        "comments": [],
        "documents": 0,
        "manual_status": None,
    }
    logger.info(f"[Sandbox vendor] Received practice request {rid}")
    return _simulated(_requests[rid])


@router.get("/requests/{request_id}")
async def sandbox_get(request_id: str):
    return _simulated(_get_or_404(request_id))


@router.put("/requests/{request_id}/status")
async def sandbox_status(request_id: str, body: Dict[str, Any] = Body(...)):
    item = _get_or_404(request_id)
    item["manual_status"] = str(body.get("status") or "new")[:30]
    if body.get("notes"):
        item["comments"].append({
            "id": f"{request_id}-note-{len(item['comments']) + 1}",
            "content": f"Status note from Pinpoint: {str(body['notes'])[:500]}",
            "author": "Pinpoint 311",
            "created_at": _now_iso(),
        })
    return {"ok": True, "status": item["manual_status"]}


@router.get("/requests/{request_id}/comments")
async def sandbox_comments(request_id: str):
    return {"comments": _simulated(_get_or_404(request_id))["comments"]}


@router.post("/requests/{request_id}/comments", status_code=201)
@limiter.limit("60/minute")
async def sandbox_comment_create(request: Request, request_id: str, body: Dict[str, Any] = Body(...)):
    item = _get_or_404(request_id)
    comment = {
        "id": f"{request_id}-c{len(item['comments']) + 1}",
        "content": str(body.get("content") or "")[:2000],
        "author": str(body.get("author") or "Unknown")[:100],
        "created_at": _now_iso(),
    }
    item["comments"].append(comment)
    return comment


@router.post("/requests/{request_id}/documents", status_code=201)
@limiter.limit("60/minute")
async def sandbox_document(request: Request, request_id: str):
    item = _get_or_404(request_id)
    # The upload body is accepted and discarded — only the count is kept
    item["documents"] += 1
    return {"ok": True, "documents": item["documents"]}


@router.get("/assets")
async def sandbox_assets():
    """A small practice asset inventory (hydrants and streetlights)."""
    base_lat, base_lng = 40.2206, -74.7597
    features = []
    for i, (dlat, dlng, kind) in enumerate([
        (0.0015, 0.001, "hydrant"), (-0.001, 0.002, "hydrant"),
        (0.002, -0.0015, "streetlight"), (-0.0022, -0.001, "streetlight"),
        (0.0005, 0.003, "sign"),
    ], start=1):
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [base_lng + dlng, base_lat + dlat]},
            "properties": {
                "asset_id": f"SBX-ASSET-{i}",
                "name": f"Practice {kind.title()} #{i}",
                "type": kind,
            },
        })
    return {"type": "FeatureCollection", "features": features}

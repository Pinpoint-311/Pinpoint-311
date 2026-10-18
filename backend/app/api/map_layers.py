from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from typing import Any, Dict, List, Optional
import json
import logging

from app.db.session import get_db
from app.models import MapLayer, ServiceRequest, User
from app.schemas import (
    MapLayerAdminResponse, MapLayerCreate, MapLayerFeatureReupload, MapLayerPolygonCreate,
    MapLayerResponse, MapLayerUpdate,
)
from app.core.auth import get_current_admin, get_current_staff
from app.services import gis_layers
from app.services.gis_layers import LayerUploadError
from app.core.client_ip import rate_limit_key
from slowapi import Limiter

router = APIRouter()
# Keyed on the resolved caller, like every other public route; see app/core/client_ip.py.
limiter = Limiter(key_func=rate_limit_key)
logger = logging.getLogger(__name__)


async def get_current_user_optional(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """The signed-in user, or None — without ever refusing the request.

    `get_current_user` is a hard gate: no token means 401. The layer-by-id route
    has to answer both an anonymous resident (with the public layers) and an
    admin (with all of them) from the same URL, so it needs to ASK who is
    calling rather than demand it. Every failure mode -- no header, malformed
    token, expired signature, single-purpose token, unknown or deactivated user
    -- resolves to None, i.e. "treat this as anonymous", never to an exception:
    an unreadable token must not be more privileged than no token, and must not
    turn a public read into a 500.
    """
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return None
    try:
        from app.core.auth import decode_token, session_is_current

        payload = decode_token(header.split(" ", 1)[1].strip())
        if payload.get("purpose"):
            return None  # onboarding/provisioning links are not sessions
        username = payload.get("sub")
        if not username:
            return None
        user = (
            await db.execute(select(User).where(User.username == username))
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        if not session_is_current(payload, user):
            return None  # signed out / revoked: anonymous, same as get_current_user
        return user
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Serialisation: public vs admin
# ---------------------------------------------------------------------------

def public_layer(layer: MapLayer) -> Dict[str, Any]:
    """A layer for an anonymous caller.

    A context layer's features never leave the server this way, whatever its
    storage: they are parcels, and parcel files carry owner names. The public
    schema has no field for the allowlist or the file's column names either.
    """
    out = MapLayerResponse.model_validate(layer).model_dump()
    if (getattr(layer, "routing_mode", None) == gis_layers.CONTEXT_MODE
            or (getattr(layer, "feature_storage", None) or gis_layers.INLINE) == gis_layers.TABLE):
        out["geojson"] = dict(gis_layers.EMPTY_FEATURE_COLLECTION)
    return out


def admin_layer(layer: MapLayer, *, warnings: Optional[List[str]] = None,
                import_summary: Optional[Dict[str, Any]] = None) -> MapLayerAdminResponse:
    out = MapLayerAdminResponse.model_validate(layer)
    out.field_flags = {
        name: flag for name in (getattr(layer, "available_properties", None) or [])
        if (flag := gis_layers.classify_field(name))
    }
    out.warnings = list(warnings or [])
    out.import_summary = import_summary
    return out


async def _layer_or_404(db: AsyncSession, layer_id: int) -> MapLayer:
    layer = (await db.execute(select(MapLayer).where(MapLayer.id == layer_id))).scalar_one_or_none()
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")
    return layer


async def _audit(db: AsyncSession, admin: User, event: str, details: Dict[str, Any]) -> None:
    from app.services.admin_audit import record_admin_action
    await record_admin_action(db, event_type=event, actor=admin, details=details)


# ---------------------------------------------------------------------------
# Public and admin listings
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[MapLayerResponse])
async def list_public_layers(db: AsyncSession = Depends(get_db)):
    """List all active layers visible on resident portal (public)"""
    result = await db.execute(
        select(MapLayer)
        .where(MapLayer.is_active == True)
        .where(MapLayer.show_on_resident_portal == True)
        .order_by(MapLayer.name)
    )
    return [public_layer(layer) for layer in result.scalars().all()]


@router.get("/all", response_model=List[MapLayerAdminResponse])
async def list_all_layers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """List all layers including inactive (admin only)"""
    result = await db.execute(
        select(MapLayer).order_by(MapLayer.name)
    )
    return [admin_layer(layer) for layer in result.scalars().all()]


@router.get("/context")
async def list_context_layers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff),
):
    """Active context layers for the staff map (staff). No features, no field values.

    Every table-backed polygon layer, context or display-only: their outlines
    are drawn per viewport through `/{layer_id}/features`, never shipped whole.
    """
    rows = (await db.execute(
        select(MapLayer)
        .where(MapLayer.is_active == True)  # noqa: E712
        .where(MapLayer.feature_storage == gis_layers.TABLE)
        .order_by(MapLayer.name)
    )).scalars().all()
    return [
        {
            "id": layer.id, "name": layer.name, "description": layer.description,
            "purpose": "context" if layer.routing_mode == gis_layers.CONTEXT_MODE else "display",
            "fill_color": layer.fill_color, "stroke_color": layer.stroke_color,
            "fill_opacity": layer.fill_opacity, "stroke_width": layer.stroke_width,
            "visible_on_map": layer.visible_on_map is not False,
            "feature_count": layer.feature_count,
            "min_zoom": gis_layers.MIN_BBOX_ZOOM,
        }
        for layer in rows
    ]


# ---------------------------------------------------------------------------
# Chunked upload (admin)
# ---------------------------------------------------------------------------
#
# A parcel layer is far larger than the 13 MB request ceiling the proxy and
# the app enforce, and raising that ceiling for one route would raise it for
# the unauthenticated photo endpoint too (it is site-wide in the Caddyfile).
# So the browser sends the file in 8 MB parts, staged on disk, and the layer is
# built from the finished file. Staging is local to the API container: a
# multi-replica deployment needs sticky routing for these routes.

@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def start_layer_upload(
    payload: Dict[str, Any],
    admin: User = Depends(get_current_admin),
):
    """Start a chunked GeoJSON upload for a polygon layer (admin only)"""
    try:
        return gis_layers.start_upload(payload.get("size_bytes"), admin.id)
    except LayerUploadError as exc:
        raise HTTPException(status_code=413 if "limit" in str(exc) else 400, detail=str(exc))


@router.put("/uploads/{upload_id}/chunks/{index}")
async def upload_layer_chunk(
    upload_id: str,
    index: int,
    request: Request,
    admin: User = Depends(get_current_admin),
):
    """Append one part of a chunked layer upload (admin only)"""
    body = await request.body()
    try:
        return gis_layers.append_chunk(upload_id, index, body, admin.id)
    except LayerUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_layer_upload(
    upload_id: str,
    admin: User = Depends(get_current_admin),
):
    """Discard a staged layer upload (admin only)"""
    if gis_layers.owns_upload(upload_id, admin.id):
        gis_layers.discard_upload(upload_id)
    return None


async def _import_from_upload(db: AsyncSession, layer: MapLayer, upload_id: str, user_id) -> Dict[str, Any]:
    """Parse the staged file into the layer's features. Raises HTTPException(400)."""
    try:
        path = gis_layers.completed_upload(upload_id, user_id)
    except LayerUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        with path.open("r", encoding="utf-8-sig") as fh:
            return await gis_layers.import_features(db, layer, gis_layers.iter_feature_collection(fh))
    except LayerUploadError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        # ST_GeomFromGeoJSON refusing a geometry lands here. The database's
        # own words are the useful part; anything longer is a stack trace.
        logger.warning("[GIS] layer import failed", exc_info=True)
        reason = str(getattr(exc, "orig", exc)).splitlines()[0][:200]
        raise HTTPException(status_code=400, detail=f"PostGIS could not read a geometry in the file: {reason}")
    finally:
        gis_layers.discard_upload(upload_id)


@router.post("/polygon", response_model=MapLayerAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_polygon_layer(
    data: MapLayerPolygonCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Create a table-backed polygon layer from a finished upload (admin only)"""
    if not gis_layers.is_postgres(db):
        raise HTTPException(status_code=503, detail="Polygon layers need the PostGIS database.")
    layer = MapLayer(
        name=data.name,
        description=data.description,
        layer_type="polygon",
        fill_color=data.fill_color,
        stroke_color=data.stroke_color,
        fill_opacity=data.fill_opacity,
        stroke_width=data.stroke_width,
        geojson=dict(gis_layers.EMPTY_FEATURE_COLLECTION),
        is_active=True,
        # Off until an admin has reviewed the fields; see portal_visibility_problems.
        show_on_resident_portal=False,
        visible_on_map=data.visible_on_map,
        routing_mode=data.routing_mode,
        service_codes=data.service_codes or [],
        feature_storage=gis_layers.TABLE,
        feature_id_property=data.feature_id_property,
        staff_properties=[],
    )
    db.add(layer)
    await db.flush()
    summary = await _import_from_upload(db, layer, data.upload_id, admin.id)
    await db.commit()
    await db.refresh(layer)
    await _audit(db, admin, "map_layer_imported", {
        "layer_id": layer.id, "layer_name": layer.name, "features": summary["feature_count"],
        "skipped": summary["skipped"], "created": True,
    })
    return admin_layer(layer, import_summary=summary)


@router.post("/{layer_id}/features", response_model=MapLayerAdminResponse)
async def reupload_layer_features(
    layer_id: int,
    data: MapLayerFeatureReupload,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Replace a polygon layer's features from a finished upload (admin only).

    Reports keep their gis_context snapshots: that is the GIS history.
    """
    if not gis_layers.is_postgres(db):
        raise HTTPException(status_code=503, detail="Polygon layers need the PostGIS database.")
    layer = await _layer_or_404(db, layer_id)
    if (layer.layer_type or "polygon") != "polygon":
        raise HTTPException(status_code=400, detail="Only polygon layers take a feature upload.")
    summary = await _import_from_upload(db, layer, data.upload_id, admin.id)
    await db.commit()
    await db.refresh(layer)
    await _audit(db, admin, "map_layer_imported", {
        "layer_id": layer.id, "layer_name": layer.name, "features": summary["feature_count"],
        "skipped": summary["skipped"], "created": False,
    })
    return admin_layer(layer, import_summary=summary)


@router.post("/", response_model=MapLayerAdminResponse, status_code=status.HTTP_201_CREATED)
async def create_layer(
    layer_data: MapLayerCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Create a new map layer (admin only)"""
    # Auto-detect layer type from GeoJSON if not provided
    layer_type = layer_data.layer_type
    if not layer_type and layer_data.geojson:
        geojson = layer_data.geojson
        if geojson.get("type") == "FeatureCollection":
            features = geojson.get("features", [])
            if features:
                geom_type = features[0].get("geometry", {}).get("type", "")
                if geom_type in ["Polygon", "MultiPolygon"]:
                    layer_type = "polygon"
                elif geom_type in ["LineString", "MultiLineString"]:
                    layer_type = "line"
                elif geom_type in ["Point", "MultiPoint"]:
                    layer_type = "point"
        elif geojson.get("type") == "Feature":
            geom_type = geojson.get("geometry", {}).get("type", "")
            if geom_type in ["Polygon", "MultiPolygon"]:
                layer_type = "polygon"
            elif geom_type in ["LineString", "MultiLineString"]:
                layer_type = "line"
            elif geom_type in ["Point", "MultiPoint"]:
                layer_type = "point"

    is_context = layer_data.routing_mode == gis_layers.CONTEXT_MODE
    if is_context and layer_type != "polygon":
        raise HTTPException(status_code=400, detail="Only polygon layers can record location context.")

    layer = MapLayer(
        name=layer_data.name,
        description=layer_data.description,
        layer_type=layer_type,
        fill_color=layer_data.fill_color,
        stroke_color=layer_data.stroke_color,
        fill_opacity=layer_data.fill_opacity,
        stroke_width=layer_data.stroke_width,
        geojson=layer_data.geojson,
        # A context layer starts staff-only, like one built from an upload.
        show_on_resident_portal=False if is_context else layer_data.show_on_resident_portal,
        visible_on_map=layer_data.visible_on_map if hasattr(layer_data, 'visible_on_map') else True,
        routing_mode=layer_data.routing_mode if hasattr(layer_data, 'routing_mode') else 'log',
        service_codes=layer_data.service_codes or [],
        routing_config=layer_data.routing_config,
        feature_storage=gis_layers.INLINE,
    )

    db.add(layer)
    summary = None
    if is_context:
        await db.flush()
        summary = await _import_inline(db, layer, layer_data.geojson)
    await db.commit()
    await db.refresh(layer)
    return admin_layer(layer, import_summary=summary)


async def _import_inline(db: AsyncSession, layer: MapLayer, geojson: Any) -> Dict[str, Any]:
    """Move a small inline polygon layer into the feature table (to make it context)."""
    if not gis_layers.is_postgres(db):
        raise HTTPException(status_code=503, detail="Context layers need the PostGIS database.")
    try:
        return await gis_layers.import_features(db, layer, gis_layers.iter_inline_features(geojson))
    except LayerUploadError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Staff reads on a context layer
# ---------------------------------------------------------------------------

@router.get("/{layer_id}/features")
async def layer_features_in_view(
    layer_id: int,
    bbox: str = Query(..., description="west,south,east,north in degrees"),
    zoom: Optional[float] = Query(None, ge=0, le=25),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff),
):
    """Simplified outlines of a context layer inside a map viewport (staff).

    Capped per request; past the cap, or below the minimum zoom, the answer is
    `zoom_in: true` and no features. Feature properties are not included: the
    label is all the map shows.
    """
    layer = await _layer_or_404(db, layer_id)
    if (layer.feature_storage or gis_layers.INLINE) != gis_layers.TABLE or not layer.is_active:
        raise HTTPException(status_code=404, detail="Layer not found")
    try:
        box = gis_layers.parse_bbox(bbox)
    except LayerUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await gis_layers.features_in_bbox(db, layer, box, zoom)


@router.get("/{layer_id}/public-outlines")
# Below @router.get, so the router registers the limited function (see gis.py).
# A panning map asks once per settled view per layer; 120/minute is a resident
# dragging the map continuously, and the global ceiling keeps one client from
# spending the database on everyone's behalf.
@limiter.limit("1200/minute", key_func=lambda request: "map-layers:outlines:global")
@limiter.limit("120/minute")
async def public_layer_outlines(
    request: Request,
    layer_id: int,
    bbox: str = Query(..., description="west,south,east,north in degrees"),
    zoom: float = Query(..., ge=0, le=25),
    db: AsyncSession = Depends(get_db),
):
    """Shapes of a resident-visible polygon layer inside a map viewport (public).

    Geometry only: no properties, no feature keys, no ids. Served only for a
    layer an admin put on the resident portal and that still passes the
    portal guard; everything else is a 404, as for the layer-by-id route.
    """
    layer = (await db.execute(select(MapLayer).where(MapLayer.id == layer_id))).scalar_one_or_none()
    if not layer or not gis_layers.layer_is_resident_visible(layer):
        raise HTTPException(status_code=404, detail="Layer not found")
    try:
        box = gis_layers.parse_bbox(bbox)
    except LayerUploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await gis_layers.public_outlines_in_bbox(db, layer, box, zoom)


@router.get("/{layer_id}/features/requests")
async def reports_in_feature(
    layer_id: int,
    feature_key: Optional[str] = Query(None, max_length=200),
    feature_id: Optional[int] = Query(None),
    exclude_request_id: Optional[str] = Query(None, max_length=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff),
):
    """Reports that fell inside one feature of a context layer (staff, own departments).

    Keyed on the layer and the feature's stable key (its PARCEL_ID / PIN), not
    on the row id, so a parcel's history survives the layer being re-uploaded.
    A feature_id is resolved to its key while that feature still exists.
    """
    from app.api.scoping import department_scope_filters

    if not gis_layers.is_postgres(db):
        return []
    if not feature_key and feature_id is None:
        raise HTTPException(status_code=400, detail="Give a feature_key or a feature_id.")
    needles = []
    if feature_key:
        needles.append({"layer_id": layer_id, "feature_key": feature_key})
    if feature_id is not None:
        key = (await db.execute(
            text("SELECT feature_key FROM map_layer_features WHERE id = :id AND layer_id = :l"),
            {"id": feature_id, "l": layer_id},
        )).scalar_one_or_none()
        if key and not feature_key:
            needles.append({"layer_id": layer_id, "feature_key": key})
        needles.append({"layer_id": layer_id, "feature_id": feature_id})

    from sqlalchemy import or_
    containment = or_(*[
        text(f"service_requests.gis_context @> CAST(:needle{i} AS jsonb)").bindparams(
            **{f"needle{i}": json.dumps([needle])})
        for i, needle in enumerate(needles)
    ])
    query = (
        select(ServiceRequest)
        .where(ServiceRequest.gis_context.isnot(None), ServiceRequest.deleted_at.is_(None), containment)
        .order_by(ServiceRequest.requested_datetime.desc())
        .limit(500)
    )
    # Same department rule as the asset history: "other reports in this
    # parcel" must not become a way to read another department's queue.
    for clause in await department_scope_filters(db, current_user):
        query = query.where(clause)
    rows = (await db.execute(query)).scalars().all()
    return [
        {
            "service_request_id": r.service_request_id,
            "service_name": r.service_name,
            "status": r.status,
            "requested_datetime": r.requested_datetime.isoformat() if r.requested_datetime else None,
            "address": r.address,
            "description": r.description[:100] if r.description else None,
        }
        for r in rows
        if r.service_request_id != exclude_request_id
    ]


@router.post("/{layer_id}/backfill")
async def backfill_layer_context(
    layer_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """Record this layer's context on existing reports that lack it (admin only)"""
    if not gis_layers.is_postgres(db):
        raise HTTPException(status_code=503, detail="Context layers need the PostGIS database.")
    layer = await _layer_or_404(db, layer_id)
    if layer.routing_mode != gis_layers.CONTEXT_MODE or layer.feature_storage != gis_layers.TABLE:
        raise HTTPException(status_code=400, detail="Only a context layer can be backfilled.")
    result = await gis_layers.backfill_layer(db, layer, actor_name=admin.username)
    await _audit(db, admin, "map_layer_backfilled", {
        "layer_id": layer.id, "layer_name": layer.name, **result,
    })
    return result


# ---------------------------------------------------------------------------
# One layer
# ---------------------------------------------------------------------------

@router.get("/{layer_id}", response_model=MapLayerAdminResponse)
async def get_layer(
    layer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Get a layer by ID.

    Same visibility rule as its two siblings, which it did not have. `GET /`
    filters on `show_on_resident_portal` and `GET /all` requires an admin,
    while this took no credential at all -- and layer ids are sequential
    integers, so every hidden and inactive layer a town had drawn (staff-only
    overlays, draft boundaries, whatever the town chose not to publish) could be
    walked one id at a time by anyone.

    Admins get any layer. Everyone else gets only what `GET /` would have
    listed, and a 404 rather than a 403 for the rest: telling an anonymous
    caller that layer 7 exists but is hidden is most of what they wanted.
    Everyone else also gets the public shape, without context-layer settings.
    """
    result = await db.execute(
        select(MapLayer).where(MapLayer.id == layer_id)
    )
    layer = result.scalar_one_or_none()
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    is_admin = current_user is not None and getattr(current_user, "role", None) == "admin"
    if is_admin:
        return admin_layer(layer)
    if not (layer.is_active and layer.show_on_resident_portal):
        raise HTTPException(status_code=404, detail="Layer not found")
    # Bypasses response_model on purpose: the admin schema would add the
    # settings fields back (as nulls) to an anonymous answer.
    return JSONResponse(jsonable_encoder(public_layer(layer)))


@router.put("/{layer_id}", response_model=MapLayerAdminResponse)
async def update_layer(
    layer_id: int,
    layer_data: MapLayerUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    """Update a map layer (admin only)"""
    result = await db.execute(
        select(MapLayer).where(MapLayer.id == layer_id)
    )
    layer = result.scalar_one_or_none()
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    # Update fields
    if layer_data.name is not None:
        layer.name = layer_data.name
    if layer_data.description is not None:
        layer.description = layer_data.description
    if layer_data.layer_type is not None:
        layer.layer_type = layer_data.layer_type
    if layer_data.fill_color is not None:
        layer.fill_color = layer_data.fill_color
    if layer_data.stroke_color is not None:
        layer.stroke_color = layer_data.stroke_color
    if layer_data.fill_opacity is not None:
        layer.fill_opacity = layer_data.fill_opacity
    if layer_data.stroke_width is not None:
        layer.stroke_width = layer_data.stroke_width
    if layer_data.is_active is not None:
        layer.is_active = layer_data.is_active
    if layer_data.visible_on_map is not None:
        layer.visible_on_map = layer_data.visible_on_map
    if layer_data.service_codes is not None:
        layer.service_codes = layer_data.service_codes
    if layer_data.routing_config is not None:
        layer.routing_config = layer_data.routing_config

    is_table = (layer.feature_storage or gis_layers.INLINE) == gis_layers.TABLE
    if layer_data.geojson is not None and not is_table:
        layer.geojson = layer_data.geojson
    # A table-backed layer's features change only through a feature upload;
    # the admin console round-trips the (empty) geojson it was given, which
    # must not be mistaken for "replace every parcel with nothing".

    summary = None
    if layer_data.routing_mode is not None and layer_data.routing_mode != layer.routing_mode:
        if layer_data.routing_mode == gis_layers.CONTEXT_MODE:
            if (layer.layer_type or "") != "polygon":
                raise HTTPException(status_code=400, detail="Only polygon layers can record location context.")
            if not is_table:
                # A small hand-drawn polygon layer: move its features into the
                # table so the one matching query covers it too.
                summary = await _import_inline(db, layer, layer.geojson)
                is_table = True
        layer.routing_mode = layer_data.routing_mode

    # Context-layer settings: every name must be a field the file has.
    available = list(layer.available_properties or [])
    if layer_data.staff_properties is not None:
        unknown = [p for p in layer_data.staff_properties if p not in available]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Not a field in this layer: {', '.join(unknown[:5])}")
        # De-duplicated, in the file's own order.
        chosen = set(layer_data.staff_properties)
        layer.staff_properties = [p for p in available if p in chosen]
    if layer_data.label_property is not None:
        if layer_data.label_property and layer_data.label_property not in available:
            raise HTTPException(status_code=400, detail=f"Not a field in this layer: {layer_data.label_property}")
        layer.label_property = layer_data.label_property or None
    if layer_data.feature_id_property is not None:
        prop = layer_data.feature_id_property or None
        if prop and prop not in available:
            raise HTTPException(status_code=400, detail=f"Not a field in this layer: {prop}")
        if prop != layer.feature_id_property:
            layer.feature_id_property = prop
            if is_table and gis_layers.is_postgres(db):
                await gis_layers.assign_feature_keys(db, layer)

    # Portal visibility last, judged on the settings as they now stand.
    warnings: List[str] = []
    if layer_data.show_on_resident_portal is not None:
        if layer_data.show_on_resident_portal:
            errors, warnings = gis_layers.portal_visibility_problems(layer)
            if errors:
                await db.rollback()
                raise HTTPException(status_code=400, detail=" ".join(errors))
        layer.show_on_resident_portal = layer_data.show_on_resident_portal
    elif layer.show_on_resident_portal and layer.routing_mode == gis_layers.CONTEXT_MODE:
        # Turning a public layer into a context layer, or emptying its
        # allowlist, takes it off the portal rather than leaving it there.
        errors, warnings = gis_layers.portal_visibility_problems(layer)
        if errors:
            layer.show_on_resident_portal = False
            warnings = ["Hidden from the resident portal: " + " ".join(errors)]

    await db.commit()
    await db.refresh(layer)
    return admin_layer(layer, warnings=warnings, import_summary=summary)


@router.delete("/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_layer(
    layer_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Delete a map layer (admin only)"""
    result = await db.execute(
        select(MapLayer).where(MapLayer.id == layer_id)
    )
    layer = result.scalar_one_or_none()
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    # Features go with it (ON DELETE CASCADE). Reports keep their snapshots.
    if (layer.feature_storage or gis_layers.INLINE) == gis_layers.TABLE and gis_layers.is_postgres(db):
        await db.execute(text("DELETE FROM map_layer_features WHERE layer_id = :l"), {"l": layer.id})
    await db.delete(layer)
    await db.commit()

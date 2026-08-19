from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

from app.db.session import get_db
from app.models import MapLayer, User
from app.schemas import MapLayerCreate, MapLayerUpdate, MapLayerResponse
from app.core.auth import get_current_admin

router = APIRouter()


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
        from app.core.auth import decode_token

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
        return user
    except Exception:
        return None


@router.get("/", response_model=List[MapLayerResponse])
async def list_public_layers(db: AsyncSession = Depends(get_db)):
    """List all active layers visible on resident portal (public)"""
    result = await db.execute(
        select(MapLayer)
        .where(MapLayer.is_active == True)
        .where(MapLayer.show_on_resident_portal == True)
        .order_by(MapLayer.name)
    )
    return result.scalars().all()


@router.get("/all", response_model=List[MapLayerResponse])
async def list_all_layers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """List all layers including inactive (admin only)"""
    result = await db.execute(
        select(MapLayer).order_by(MapLayer.name)
    )
    return result.scalars().all()


@router.post("/", response_model=MapLayerResponse, status_code=status.HTTP_201_CREATED)
async def create_layer(
    layer_data: MapLayerCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
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
    
    layer = MapLayer(
        name=layer_data.name,
        description=layer_data.description,
        layer_type=layer_type,
        fill_color=layer_data.fill_color,
        stroke_color=layer_data.stroke_color,
        fill_opacity=layer_data.fill_opacity,
        stroke_width=layer_data.stroke_width,
        geojson=layer_data.geojson,
        show_on_resident_portal=layer_data.show_on_resident_portal,
        visible_on_map=layer_data.visible_on_map if hasattr(layer_data, 'visible_on_map') else True,
        routing_mode=layer_data.routing_mode if hasattr(layer_data, 'routing_mode') else 'log',
        service_codes=layer_data.service_codes or [],
        routing_config=layer_data.routing_config,
    )
    
    db.add(layer)
    await db.commit()
    await db.refresh(layer)
    return layer


@router.get("/{layer_id}", response_model=MapLayerResponse)
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
    """
    result = await db.execute(
        select(MapLayer).where(MapLayer.id == layer_id)
    )
    layer = result.scalar_one_or_none()
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    is_admin = current_user is not None and getattr(current_user, "role", None) == "admin"
    if not is_admin and not (layer.is_active and layer.show_on_resident_portal):
        raise HTTPException(status_code=404, detail="Layer not found")
    return layer


@router.put("/{layer_id}", response_model=MapLayerResponse)
async def update_layer(
    layer_id: int,
    layer_data: MapLayerUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
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
    if layer_data.show_on_resident_portal is not None:
        layer.show_on_resident_portal = layer_data.show_on_resident_portal
    if layer_data.visible_on_map is not None:
        layer.visible_on_map = layer_data.visible_on_map
    if layer_data.routing_mode is not None:
        layer.routing_mode = layer_data.routing_mode
    if layer_data.geojson is not None:
        layer.geojson = layer_data.geojson
    if layer_data.service_codes is not None:
        layer.service_codes = layer_data.service_codes
    if layer_data.routing_config is not None:
        layer.routing_config = layer_data.routing_config
    
    await db.commit()
    await db.refresh(layer)
    return layer


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
    
    await db.delete(layer)
    await db.commit()

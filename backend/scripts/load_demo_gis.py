#!/usr/bin/env python3
"""Load, or remove, the SYNTHETIC DEMO GIS layers written by generate_demo_gis.py.

    python load_demo_gis.py load   --in /tmp/demo-gis [--admin USERNAME] [--no-backfill]
    python load_demo_gis.py remove [--admin USERNAME]
    python load_demo_gis.py status

Run inside the instance's backend container with `-w /app` (see
docs/DEMO_DATA.md). It goes through the app's own code paths, as the admin
console would: the chunked upload + POST /map-layers/polygon handler for
polygon context layers, POST /map-layers/ for point layers, PUT for the staff
allowlist and label, and the backfill handler. Admin-audit rows are written
under the chosen admin account.

A demo layer is one whose name starts with "Demo — " AND whose description
contains "Synthetic demo data, not official records". `load` first removes
every demo layer and then creates them again, so it is idempotent; `remove`
removes them. Neither ever touches any other layer. Removing a demo layer also
strips its entries from reports' gis_context (they describe fictional
parcels); the timeline rows written by the backfill are left as history.

Category scoping: each layer in manifest.json lists keywords; the layer is
scoped to the instance's active categories whose code or name contains one,
or left unscoped (all categories) when none matches.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

for _p in (Path(__file__).resolve().parent.parent, Path("/app")):
    if (_p / "app").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DEMO_PREFIX = "Demo — "
DEMO_MARKER = "Synthetic demo data, not official records"


def is_demo_layer(layer) -> bool:
    return (layer.name or "").startswith(DEMO_PREFIX) and DEMO_MARKER in (layer.description or "")


async def _admin(db, username: Optional[str]):
    from sqlalchemy import select
    from app.models import User
    q = select(User).where(User.role == "admin", User.is_active.is_(True))
    if username:
        q = q.where(User.username == username)
    user = (await db.execute(q.order_by(User.id).limit(1))).scalar_one_or_none()
    if not user:
        sys.exit("No active admin account" + (f" named {username!r}." if username else "."))
    return user


async def _demo_layers(db) -> List[Any]:
    from sqlalchemy import select
    from app.models import MapLayer
    rows = (await db.execute(select(MapLayer).order_by(MapLayer.id))).scalars().all()
    return [layer for layer in rows if is_demo_layer(layer)]


async def remove(db, admin) -> List[str]:
    from sqlalchemy import text
    from app.api import map_layers as api

    layers = await _demo_layers(db)
    ids = [layer.id for layer in layers]
    names = [f"{layer.name} (#{layer.id})" for layer in layers]
    if ids:
        # Their snapshots on reports describe fictional parcels: drop them.
        await db.execute(text("""
            UPDATE service_requests sr SET gis_context = (
                SELECT CASE WHEN count(*) = 0 THEN NULL ELSE jsonb_agg(e) END
                FROM jsonb_array_elements(sr.gis_context::jsonb) e
                WHERE NOT ((e ->> 'layer_id')::int = ANY(:ids)
                           AND coalesce(e ->> 'layer_name', '') LIKE :prefix))
            WHERE sr.gis_context IS NOT NULL AND jsonb_typeof(sr.gis_context::jsonb) = 'array'
              AND EXISTS (SELECT 1 FROM jsonb_array_elements(sr.gis_context::jsonb) e
                          WHERE (e ->> 'layer_id')::int = ANY(:ids))
        """), {"ids": ids, "prefix": DEMO_PREFIX + "%"})
        await db.commit()
    for layer_id in ids:
        await api.delete_layer(layer_id, db=db, _=admin)
    return names


async def _service_codes(db, keywords: List[str]) -> List[str]:
    from sqlalchemy import select
    from app.models import ServiceDefinition
    if not keywords:
        return []
    rows = (await db.execute(
        select(ServiceDefinition.service_code, ServiceDefinition.service_name)
        .where(ServiceDefinition.is_active.is_(True)).order_by(ServiceDefinition.service_code)
    )).all()
    kws = [k.lower() for k in keywords]
    return [code for code, name in rows
            if any(k in f"{code} {name}".lower() for k in kws)]


async def _create_context(db, admin, spec: Dict[str, Any], path: Path, codes: List[str]):
    from app.api import map_layers as api
    from app.schemas import MapLayerPolygonCreate, MapLayerUpdate
    from app.services import gis_layers

    data = path.read_bytes()
    staged = gis_layers.start_upload(len(data), admin.id)
    step = staged["chunk_bytes"]
    for index, start in enumerate(range(0, len(data), step)):
        gis_layers.append_chunk(staged["upload_id"], index, data[start:start + step], admin.id)
    created = await api.create_polygon_layer(MapLayerPolygonCreate(
        name=spec["name"], description=spec["description"], upload_id=staged["upload_id"],
        fill_color=spec["fill_color"], stroke_color=spec["stroke_color"],
        fill_opacity=spec["fill_opacity"], stroke_width=spec["stroke_width"],
        visible_on_map=True, routing_mode="context", service_codes=codes,
        feature_id_property=spec["feature_id_property"],
    ), db=db, admin=admin)
    updated = await api.update_layer(created.id, MapLayerUpdate(
        feature_id_property=spec["feature_id_property"],
        label_property=spec["label_property"],
        staff_properties=spec["staff_properties"],
        show_on_resident_portal=False,
    ), db=db, admin=admin)
    return updated


async def _create_points(db, admin, spec: Dict[str, Any], path: Path, codes: List[str]):
    from app.api import map_layers as api
    from app.schemas import MapLayerCreate
    geojson = json.loads(path.read_text(encoding="utf-8"))
    return await api.create_layer(MapLayerCreate(
        name=spec["name"], description=spec["description"], layer_type="point",
        fill_color=spec["fill_color"], stroke_color=spec["stroke_color"],
        show_on_resident_portal=True, visible_on_map=True, routing_mode="log",
        service_codes=codes, geojson=geojson,
    ), db=db, admin=admin)


async def load(db, admin, src: Path, backfill: bool) -> List[Dict[str, Any]]:
    from app.api import map_layers as api
    manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
    for spec in manifest["layers"]:
        if not (spec["name"].startswith(DEMO_PREFIX) and DEMO_MARKER in spec["description"]):
            sys.exit(f"manifest layer {spec['name']!r} is not marked as demo data; refusing.")
    removed = await remove(db, admin)
    for name in removed:
        print(f"removed  {name}")
    report = []
    for spec in manifest["layers"]:
        codes = await _service_codes(db, spec.get("service_keywords") or [])
        path = src / spec["file"]
        if spec["kind"] == "context":
            layer = await _create_context(db, admin, spec, path, codes)
            result = {"id": layer.id, "name": layer.name, "features": layer.feature_count,
                      "service_codes": codes, "staff_properties": layer.staff_properties,
                      "label": layer.label_property, "id_field": layer.feature_id_property,
                      "on_portal": layer.show_on_resident_portal,
                      "warnings": list(layer.field_flags or {})}
            if backfill:
                result["backfill"] = await api.backfill_layer_context(layer.id, db=db, admin=admin)
        else:
            layer = await _create_points(db, admin, spec, path, codes)
            result = {"id": layer.id, "name": layer.name,
                      "features": len((layer.geojson or {}).get("features") or []),
                      "service_codes": codes, "on_portal": layer.show_on_resident_portal}
        if result["features"] != spec.get("count", result["features"]):
            print(f"warning: {spec['name']} has {result['features']} features, "
                  f"manifest says {spec['count']}")
        print("created  " + json.dumps(result, ensure_ascii=False))
        report.append(result)
    return report


async def status(db) -> None:
    for layer in await _demo_layers(db):
        n = layer.feature_count if layer.feature_storage == "table" else \
            len((layer.geojson or {}).get("features") or [])
        print(f"#{layer.id} {layer.name}: {n} features, mode={layer.routing_mode}, "
              f"portal={layer.show_on_resident_portal}, codes={layer.service_codes}")


async def amain(args) -> int:
    from app.db.session import SessionLocal
    async with SessionLocal() as db:
        if args.cmd == "status":
            await status(db)
            return 0
        admin = await _admin(db, args.admin)
        if args.cmd == "remove":
            removed = await remove(db, admin)
            print("\n".join(f"removed  {n}" for n in removed) or "no demo layers")
        else:
            await load(db, admin, Path(args.src), backfill=not args.no_backfill)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_load = sub.add_parser("load", help="replace the demo layers with the files in --in")
    p_load.add_argument("--in", dest="src", required=True)
    p_load.add_argument("--no-backfill", action="store_true")
    p_load.add_argument("--admin", help="admin username to act as (default: first admin)")
    p_rm = sub.add_parser("remove", help="delete every demo layer, and nothing else")
    p_rm.add_argument("--admin")
    sub.add_parser("status", help="list the demo layers")
    return asyncio.run(amain(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())

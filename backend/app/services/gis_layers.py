"""Polygon layers that scale to tax parcels, and the GIS context of a report.

A town's parcel layer is tens of thousands of polygons. The original map-layer
design kept every feature in one JSON column and shipped it whole to every
browser, which is fine for forty storm drains and impossible for 30,000
parcels. So polygon layers uploaded through the new path are "table-backed":

  * the GeoJSON is uploaded in chunks (each under the 13 MB request ceiling the
    proxy and the app both enforce), parsed here one feature at a time so a
    100 MB file never sits in memory as Python objects, repaired with
    ST_MakeValid and bulk-inserted into `map_layer_features` in batches;
  * every new report with coordinates is matched against all context layers
    with ONE PostGIS query (ST_Covers on the point, GIST-indexed) and the
    containing features are snapshotted onto `service_requests.gis_context`;
  * the staff map asks for the features inside its viewport, simplified on the
    fly and capped per request.

Privacy rules, which every function here keeps:

  * Only the layer's staff allowlist (`staff_properties`, empty by default) is
    ever copied onto a report or returned with a feature. Owner names and
    mailing addresses in a parcel file stay in `map_layer_features.properties`
    and are read by nothing but the matcher, which discards them.
  * Nothing here is public. Context-layer properties never reach a public
    endpoint; the public layer list gets an empty FeatureCollection for them.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import secrets
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------
#
# 500 MB / 500,000 features covers a county-sized parcel layer with its
# attribute table (a large New Jersey county is ~150k parcels and a statewide
# export of one county can run to several hundred MB of GeoJSON; a single
# township is 5-30k) while bounding what one admin upload can cost: the parse
# is streamed, so memory is one insert batch whatever the file size, and the
# insert is batched inside one transaction. Features outside the township are
# dropped before the feature cap is applied (see Clip), so a county file whose
# in-town part fits is accepted.
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
MAX_FEATURES = 500_000
# Features read from one file or one ArcGIS layer, before the township clip.
# Only a sanity ceiling: the byte limit bounds a file first, and an ArcGIS
# download is already limited to the township's envelope.
MAX_SCAN_FEATURES = 2_000_000
# Point layers are stored INLINE (map_layers.geojson) and shipped whole to
# every resident's map, so they have their own, much smaller cap. 50,000
# points is a whole town's street trees, hydrants or streetlights; at a typical
# 200-500 bytes per point with a few attributes that is 10-25 MB, which is
# already the most a phone on a cellular connection should be asked to load
# for one overlay. Past either limit the answer is to split the layer, or to
# use a polygon (table-backed) layer, whose features are served per viewport.
MAX_INLINE_FEATURES = 50_000
MAX_INLINE_BYTES = 25 * 1024 * 1024
# The upload staging directory must have this many times the declared size
# free (minus what unfinished uploads have already claimed) before an upload
# starts: the file itself, plus room for the database to grow as it imports.
DISK_HEADROOM_FACTOR = 2
# Features within this distance of the township boundary are kept, so parcels
# and roads on the border are not lost to a boundary drawn a few metres off.
CLIP_BUFFER_M = 100
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
UPLOAD_TTL_SECONDS = 6 * 3600
# An upload nobody has added to for this long is abandoned. An active one
# writes a part every few seconds; at 500 MB an abandoned file is worth
# removing well before the TTL.
UPLOAD_IDLE_SECONDS = 3600
INSERT_BATCH = 1000
MAX_AVAILABLE_PROPERTIES = 300
# A point on a shared parcel line is covered by both parcels, and layers can
# overlap; past this many matches something is wrong with the data.
MAX_CONTEXT_MATCHES = 20
# Staff map: below this zoom a parcel is a few pixels wide and the request
# would be thousands of features, so the client does not ask.
MIN_BBOX_ZOOM = 15
# Past this many outlines in one request the answer is "zoom in". The map asks
# for a margin around the screen so pans redraw from what it already has; at
# zoom 15 over a dense subdivision that margin alone is several hundred
# parcels, and at 500 the outlines stayed hidden until zoom 16. Simplified to
# 6 decimals a parcel is about 230 bytes, so 1500 is roughly 350 KB.
MAX_BBOX_FEATURES = 1500
BACKFILL_BATCH = 500

EMPTY_FEATURE_COLLECTION: Dict[str, Any] = {"type": "FeatureCollection", "features": []}

CONTEXT_MODE = "context"
ROUTING_MODES = ("none", "log", "block", CONTEXT_MODE)
TABLE = "table"
INLINE = "inline"


class LayerUploadError(ValueError):
    """An upload the admin can fix. The message is shown to them as-is."""


class UploadNoSpace(LayerUploadError):
    """The server has no room for the upload right now (HTTP 507)."""


# ---------------------------------------------------------------------------
# Chunked upload staging
# ---------------------------------------------------------------------------

_UPLOAD_ID = re.compile(r"^[0-9a-f]{32}$")


def _upload_root() -> Path:
    root = Path(os.environ.get("MAP_LAYER_UPLOAD_DIR") or tempfile.gettempdir()) / "pinpoint-layer-uploads"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _paths(upload_id: str) -> Tuple[Path, Path]:
    if not isinstance(upload_id, str) or not _UPLOAD_ID.match(upload_id):
        raise LayerUploadError("Unknown upload.")
    root = _upload_root()
    return root / f"{upload_id}.geojson", root / f"{upload_id}.json"


def _staged_uploads(root: Path) -> Dict[str, List[Path]]:
    """{upload_id: [its files]} for everything in the staging directory."""
    groups: Dict[str, List[Path]] = {}
    for path in root.iterdir():
        groups.setdefault(path.stem, []).append(path)
    return groups


def prune_stale_uploads(now: Optional[float] = None) -> int:
    """Delete staged uploads nobody finished. Never raises.

    An upload is abandoned once neither of its files has been written for
    UPLOAD_IDLE_SECONDS (an active upload writes a part every few seconds),
    and both files go together, so a half-pair never lingers. Returns the
    number of files removed.
    """
    now = now or time.time()
    removed = 0
    try:
        for paths in _staged_uploads(_upload_root()).values():
            try:
                newest = max(p.stat().st_mtime for p in paths)
            except (OSError, ValueError):
                continue
            if now - newest <= min(UPLOAD_IDLE_SECONDS, UPLOAD_TTL_SECONDS):
                continue
            for path in paths:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    continue
    except OSError:
        pass
    return removed


def _reserved_bytes(root: Path) -> int:
    """Bytes unfinished uploads have declared but not yet written."""
    reserved = 0
    for path in root.glob("*.json"):
        try:
            meta = json.loads(path.read_text())
            reserved += max(0, int(meta.get("size", 0)) - int(meta.get("received", 0)))
        except (OSError, ValueError, TypeError):
            continue
    return reserved


def _free_bytes(root: Path) -> int:
    return shutil.disk_usage(root).free


def check_disk_space(size_bytes: int) -> None:
    """Refuse an upload the staging disk cannot hold twice over (UploadNoSpace)."""
    root = _upload_root()
    try:
        available = _free_bytes(root) - _reserved_bytes(root)
    except OSError:
        return  # cannot tell; the write itself will fail loudly if it must
    needed = size_bytes * DISK_HEADROOM_FACTOR
    if available < needed:
        raise UploadNoSpace(
            f"The server does not have room for a {size_bytes / 1048576:.0f} MB file right now "
            f"(it needs {needed / 1048576:.0f} MB free and has {max(available, 0) / 1048576:.0f} MB). "
            "Try again later, or ask whoever runs the server to free some disk space.")


def start_upload(size_bytes: int, user_id: Optional[int]) -> Dict[str, Any]:
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes <= 0:
        raise LayerUploadError("The file is empty.")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise LayerUploadError(
            f"The file is {size_bytes / 1048576:.0f} MB; the limit is {MAX_UPLOAD_BYTES // 1048576} MB. "
            "Split the layer, or drop columns you do not need before exporting.")
    prune_stale_uploads()
    check_disk_space(size_bytes)
    upload_id = secrets.token_hex(16)
    data, meta = _paths(upload_id)
    data.write_bytes(b"")
    meta.write_text(json.dumps({"size": size_bytes, "received": 0, "next": 0, "user_id": user_id}))
    return {"upload_id": upload_id, "chunk_bytes": UPLOAD_CHUNK_BYTES, "max_bytes": MAX_UPLOAD_BYTES}


def _read_meta(upload_id: str, user_id: Optional[int]) -> Tuple[Path, Path, Dict[str, Any]]:
    data, meta_path = _paths(upload_id)
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError):
        raise LayerUploadError("Unknown or expired upload. Start the upload again.")
    if meta.get("user_id") != user_id:
        # Another admin's staged file is not yours to append to or import.
        raise LayerUploadError("Unknown or expired upload. Start the upload again.")
    return data, meta_path, meta


def append_chunk(upload_id: str, index: int, chunk: bytes, user_id: Optional[int]) -> Dict[str, Any]:
    data, meta_path, meta = _read_meta(upload_id, user_id)
    if index != meta["next"]:
        raise LayerUploadError(f"Expected part {meta['next']} of the upload, got part {index}.")
    if not chunk:
        raise LayerUploadError("Empty upload part.")
    if len(chunk) > UPLOAD_CHUNK_BYTES:
        raise LayerUploadError(f"Each upload part may be at most {UPLOAD_CHUNK_BYTES // 1048576} MB.")
    received = meta["received"] + len(chunk)
    if received > meta["size"] or received > MAX_UPLOAD_BYTES:
        raise LayerUploadError("The upload is larger than it said it would be.")
    with data.open("ab") as fh:
        fh.write(chunk)
    meta.update(received=received, next=index + 1)
    meta_path.write_text(json.dumps(meta))
    return {"received_bytes": received, "size_bytes": meta["size"]}


def owns_upload(upload_id: str, user_id: Optional[int]) -> bool:
    try:
        _read_meta(upload_id, user_id)
        return True
    except LayerUploadError:
        return False


def completed_upload(upload_id: str, user_id: Optional[int]) -> Path:
    data, _, meta = _read_meta(upload_id, user_id)
    if meta["received"] != meta["size"]:
        raise LayerUploadError(
            f"The upload is incomplete ({meta['received']} of {meta['size']} bytes). Start it again.")
    return data


def discard_upload(upload_id: str) -> None:
    try:
        for path in _paths(upload_id):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    except LayerUploadError:
        pass


# ---------------------------------------------------------------------------
# Streaming GeoJSON parse
# ---------------------------------------------------------------------------

_DECODER = json.JSONDecoder()
_WS = " \t\r\n"
_READ_CHUNK = 1 << 20


class _JsonStream:
    """Just enough of a streaming JSON reader to walk a FeatureCollection.

    Each feature is decoded on its own with the stdlib decoder, so peak memory
    is one feature plus a read buffer, not the whole file as Python objects --
    a 100 MB GeoJSON parsed with json.load is the better part of a gigabyte.
    """

    def __init__(self, fh, chunk: int = 1 << 20):
        self.fh = fh
        self.chunk = chunk
        self.buf = ""
        self.pos = 0
        self.eof = False

    def _more(self, at_least: int) -> bool:
        # Doubling, so a feature larger than the buffer costs O(log n) retries.
        try:
            data = self.fh.read(max(self.chunk, at_least))
        except UnicodeDecodeError:
            raise LayerUploadError("The file is not UTF-8 text. Export the layer as GeoJSON (UTF-8).")
        if not data:
            self.eof = True
            return False
        self.buf = self.buf[self.pos:] + data
        self.pos = 0
        return True

    def peek(self) -> str:
        while True:
            n = len(self.buf)
            while self.pos < n and self.buf[self.pos] in _WS:
                self.pos += 1
            if self.pos < n:
                return self.buf[self.pos]
            if self.eof or not self._more(0):
                return ""

    def take(self, ch: str, what: str) -> None:
        if self.peek() != ch:
            raise LayerUploadError(what)
        self.pos += 1

    def value(self) -> Any:
        if self.peek() == "":
            raise LayerUploadError("The file ended before the GeoJSON did. Was the upload cut short?")
        while True:
            try:
                obj, end = _DECODER.raw_decode(self.buf, self.pos)
            except json.JSONDecodeError as exc:
                if self.eof or not self._more(len(self.buf) - self.pos):
                    raise LayerUploadError(f"The file is not valid JSON ({exc.msg}).")
                continue
            if end == len(self.buf) and not self.eof and not isinstance(obj, (dict, list, str)):
                # A bare number or literal may continue past the buffer.
                if self._more(0):
                    continue
            self.pos = end
            return obj


_WGS84_NAMES = {
    "urn:ogc:def:crs:ogc:1.3:crs84",
    "urn:ogc:def:crs:ogc::crs84",
    "urn:ogc:def:crs:epsg::4326",
    "urn:ogc:def:crs:epsg:4326",
    "epsg:4326",
    "crs84",
    "http://www.opengis.net/def/crs/ogc/1.3/crs84",
    "http://www.opengis.net/def/crs/epsg/0/4326",
}


def check_crs(crs: Any) -> None:
    """Accept no CRS (RFC 7946: WGS 84) or one that names WGS 84; refuse the rest.

    There is no reprojection: a declared WGS 84 is already what PostGIS is
    given, and a State Plane file reprojected by guesswork is worse than one
    refused with instructions.
    """
    if crs is None:
        return
    name = None
    if isinstance(crs, dict):
        props = crs.get("properties")
        if isinstance(props, dict):
            name = props.get("name") or props.get("code")
    if isinstance(name, int):
        name = f"EPSG:{name}"
    if isinstance(name, str) and name.strip().lower() in _WGS84_NAMES:
        return
    shown = name if isinstance(name, str) else json.dumps(crs)[:80]
    raise LayerUploadError(
        f"The file declares the coordinate system {shown}. Only WGS 84 (EPSG:4326 / CRS84) is "
        "accepted. Re-export the layer as GeoJSON in EPSG:4326 (in QGIS: Export > Save Features "
        "As, CRS 'EPSG:4326 - WGS 84'; in ArcGIS Pro: Features To JSON with 'Output to GeoJSON' "
        "and 'Project to WGS_1984').")


def iter_feature_collection(fh) -> Iterator[Any]:
    """Yield the features of a GeoJSON FeatureCollection read from a text file.

    Top-level members other than `features` are decoded whole (they are small)
    and checked as they appear: `type` must be FeatureCollection and `crs`, in
    whichever order it comes, must name WGS 84.
    """
    s = _JsonStream(fh, chunk=_READ_CHUNK)
    not_fc = "The file must be a GeoJSON FeatureCollection."
    s.take("{", not_fc)
    members: Dict[str, Any] = {}
    saw_features = False
    if s.peek() == "}":
        raise LayerUploadError(not_fc)
    while True:
        key = s.value()
        if not isinstance(key, str):
            raise LayerUploadError(not_fc)
        s.take(":", "The file is not valid JSON.")
        if key == "features":
            saw_features = True
            s.take("[", "`features` must be a list.")
            if s.peek() == "]":
                s.pos += 1
            else:
                while True:
                    yield s.value()
                    c = s.peek()
                    if c == ",":
                        s.pos += 1
                        continue
                    if c == "]":
                        s.pos += 1
                        break
                    raise LayerUploadError("The file is not valid JSON (in the features list).")
        else:
            members[key] = s.value()
            if key == "type" and members[key] != "FeatureCollection":
                raise LayerUploadError(f"{not_fc} This file is a {members[key]!s:.40}.")
            if key == "crs":
                check_crs(members[key])
        c = s.peek()
        if c == ",":
            s.pos += 1
            continue
        if c == "}":
            s.pos += 1
            break
        raise LayerUploadError("The file is not valid JSON.")
    if not saw_features or members.get("type") != "FeatureCollection":
        raise LayerUploadError(not_fc)


def iter_inline_features(geojson: Any) -> Iterator[Any]:
    """The features of a GeoJSON dict already in memory (an inline layer)."""
    if not isinstance(geojson, dict):
        raise LayerUploadError("The layer has no GeoJSON.")
    check_crs(geojson.get("crs"))
    kind = geojson.get("type")
    if kind == "FeatureCollection":
        yield from (geojson.get("features") or [])
    elif kind == "Feature":
        yield geojson
    elif kind in ("Polygon", "MultiPolygon"):
        yield {"type": "Feature", "properties": {}, "geometry": geojson}
    else:
        raise LayerUploadError("The layer's GeoJSON is not a FeatureCollection.")


def _check_positions(coords: Any, depth: int, n: int) -> None:
    """Every position is [lon, lat] inside WGS 84's range, at the right depth."""
    if depth == 0:
        if (not isinstance(coords, list) or len(coords) < 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in coords[:2])):
            raise LayerUploadError(f"Feature {n} has a malformed coordinate.")
        lon, lat = coords[0], coords[1]
        if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
            raise LayerUploadError(
                f"Feature {n} has a coordinate ({lon}, {lat}) outside longitude/latitude range. The "
                "file is probably in a projected system such as State Plane: re-export it in "
                "WGS 84 (EPSG:4326).")
        return
    if not isinstance(coords, list) or not coords:
        raise LayerUploadError(f"Feature {n} has empty or malformed coordinates.")
    for part in coords:
        _check_positions(part, depth - 1, n)


def _clean(value: Any) -> Any:
    # Postgres jsonb refuses \u0000, which spreadsheet exports do produce.
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {str(k).replace("\x00", ""): _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def feature_parts(feature: Any, n: int) -> Tuple[str, Dict[str, Any]]:
    """(geometry as GeoJSON text, properties) for one feature, or LayerUploadError.

    `n` is 1-based, as an admin counting rows in QGIS's attribute table would.
    """
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise LayerUploadError(f"Item {n} in `features` is not a GeoJSON Feature.")
    geom = feature.get("geometry")
    if not isinstance(geom, dict):
        raise LayerUploadError(f"Feature {n} has no geometry.")
    kind = geom.get("type")
    if kind not in ("Polygon", "MultiPolygon"):
        raise LayerUploadError(
            f"Feature {n} is a {kind!s:.30}. Polygon layers take Polygon and MultiPolygon features "
            "only; upload points as a point layer.")
    coords = geom.get("coordinates")
    _check_positions(coords, 2 if kind == "Polygon" else 3, n)
    props = feature.get("properties")
    if props is None:
        props = {}
    if not isinstance(props, dict):
        raise LayerUploadError(f"Feature {n} has properties that are not an object.")
    return json.dumps({"type": kind, "coordinates": coords}), _clean(props)


# ---------------------------------------------------------------------------
# Field heuristics
# ---------------------------------------------------------------------------

_ID_CANDIDATES = (
    "pamspin", "parcelid", "parcelno", "parcelnum", "parcelnumber", "pin", "apn", "gispin",
    "blocklot", "pid", "parcel", "zoneid", "districtid", "id",
)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def guess_id_property(available: Iterable[str]) -> Optional[str]:
    by_norm = {}
    for name in available:
        by_norm.setdefault(_norm(name), name)
    for candidate in _ID_CANDIDATES:
        if candidate in by_norm:
            return by_norm[candidate]
    return None


# Owner and mailing details in parcel files. Confident: refused for a layer
# shown on the resident portal. Unsure: a warning, because "NAME" is as often
# a zone or a street as a person.
_OWNER = re.compile(r"owner|ownr|ownnam|own_?name|taxpayer|grantee|grantor|deedholder|occupant|mail(ing)?_?addr|mailing", re.I)
_MAYBE_PERSONAL = re.compile(r"name|addr|phone|tel|email|mail|contact|resident|buyer|seller", re.I)


def classify_field(name: str) -> Optional[str]:
    """'owner' (confidently personal), 'maybe', or None."""
    if not isinstance(name, str):
        return None
    if _OWNER.search(name):
        return "owner"
    if _MAYBE_PERSONAL.search(name):
        return "maybe"
    return None


def portal_visibility_problems(layer) -> Tuple[List[str], List[str]]:
    """(errors, warnings) for showing a context layer on the resident portal.

    The public map never carries a context layer's properties whatever is
    decided here; this is the second lock, so that turning the layer public is
    a deliberate act on a layer whose staff fields have been chosen with care.
    """
    if (layer.routing_mode or "") != CONTEXT_MODE:
        return [], []
    errors: List[str] = []
    warnings: List[str] = []
    allow = list(layer.staff_properties or [])
    if not allow:
        errors.append(
            "Choose which fields staff see before showing this layer on the resident portal. "
            "A layer with no reviewed fields stays staff-only.")
    owner = [p for p in allow if classify_field(p) == "owner"]
    if owner:
        errors.append(
            "This layer's staff fields look like owner details (" + ", ".join(owner) + "). "
            "Layers carrying owner information stay off the resident portal.")
    maybe = [p for p in allow if classify_field(p) == "maybe"]
    if maybe:
        warnings.append(
            "Check that these fields are not personal information: " + ", ".join(maybe) + ". "
            "Field values are never sent to the public map, only the outlines.")
    hidden_owner = [p for p in (layer.available_properties or [])
                    if p not in allow and classify_field(p) == "owner"]
    if hidden_owner and not owner:
        warnings.append(
            "The file also carries " + ", ".join(hidden_owner[:5]) + ("..." if len(hidden_owner) > 5 else "")
            + ". Those fields are stored for matching only and are never shown or published.")
    return errors, warnings


# ---------------------------------------------------------------------------
# The township clip
# ---------------------------------------------------------------------------
#
# A town that uploads the county's parcel file wants the town's parcels. Every
# file upload and ArcGIS import keeps only the features that intersect the
# township boundary (SystemSettings.township_boundary, the outline the maps
# draw) buffered by CLIP_BUFFER_M, so border parcels and roads survive a
# boundary drawn a little off. The buffered outline is built once per import,
# in PostGIS (geography buffer, so the margin is metres everywhere), and kept
# as EWKB: each later statement decodes it as a constant, which lets PostGIS
# prepare it once per statement. A cheap bounding-box test in Python drops
# most out-of-town features before they reach the database at all.

_CLIP_GEOM = "ST_GeomFromEWKB(decode(CAST(:clip AS text), 'hex'))"
_CLIP_BUILD_SQL = (
    "SELECT encode(ST_AsEWKB(g), 'hex') AS clip, ST_XMin(g) AS w, ST_YMin(g) AS s, "
    "ST_XMax(g) AS e, ST_YMax(g) AS n FROM (SELECT ST_Buffer(CAST(ST_CollectionExtract(ST_MakeValid("
    "ST_SetSRID(ST_GeomFromGeoJSON(:b), 4326)), 3) AS geography), CAST(:m AS float8))::geometry AS g) q"
)


@dataclass
class Clip:
    """The township outline an import is clipped to, or why there is none.

    `reason` when not applied: "no_boundary" (none set in Setup),
    "unreadable" (set, but PostGIS could not make an outline of it), or
    "no_postgis" (a development database without spatial support).
    """
    applied: bool
    reason: Optional[str] = None
    area_name: Optional[str] = None
    ewkb_hex: Optional[str] = None
    bbox: Optional[Tuple[float, float, float, float]] = None

    @property
    def area(self) -> str:
        return self.area_name or "your township boundary"

    def message(self, kept: int, total: int) -> str:
        if self.applied:
            where = f"inside {self.area_name}" if self.area_name else "within your township boundary"
            return f"Kept {kept:,} of {total:,} features {where}."
        if self.reason == "no_boundary":
            return (f"No township boundary is set, so all {total:,} features were imported. "
                    "Set one in Setup to limit layers to the township.")
        return f"The township boundary could not be used, so all {total:,} features were imported."

    def summary(self, kept: int, total: int) -> Dict[str, Any]:
        return {"applied": self.applied, "reason": self.reason, "area": self.area_name,
                "kept": kept, "total": total, "outside": total - kept if self.applied else 0}


def _boundary_multipolygon(boundary: Any) -> Optional[Dict[str, Any]]:
    """Every polygon of the stored boundary as one MultiPolygon, or None."""
    from app.services.boundary_geo import extract_boundary_geometry

    geom = extract_boundary_geometry(boundary) if isinstance(boundary, dict) else None
    polygons: List[Any] = []

    def collect(g: Any) -> None:
        if not isinstance(g, dict):
            return
        if g.get("type") == "Polygon" and g.get("coordinates"):
            polygons.append(g["coordinates"])
        elif g.get("type") == "MultiPolygon":
            polygons.extend(p for p in (g.get("coordinates") or []) if p)
        elif g.get("type") == "GeometryCollection":
            for part in g.get("geometries") or []:
                collect(part)

    collect(geom)
    return {"type": "MultiPolygon", "coordinates": polygons} if polygons else None


def _area_name(row) -> Optional[str]:
    name = (getattr(row, "township_name", None) or "").strip()
    # The column's default is a placeholder, not a place.
    return name if name and name.lower() != "your township" else None


async def load_clip(db) -> Clip:
    """The township outline to clip imports to. Never raises."""
    from sqlalchemy import select, text
    from app.models import SystemSettings

    try:
        row = (await db.execute(
            select(SystemSettings).order_by(SystemSettings.id).limit(1))).scalar_one_or_none()
    except Exception:
        logger.warning("[GIS] could not read the township boundary", exc_info=True)
        return Clip(applied=False, reason="unreadable")
    shape = _boundary_multipolygon(getattr(row, "township_boundary", None) if row else None)
    name = _area_name(row) if row else None
    if shape is None:
        return Clip(applied=False, reason="no_boundary", area_name=name)
    if not is_postgres(db):
        return Clip(applied=False, reason="no_postgis", area_name=name)
    try:
        async with db.begin_nested():
            r = (await db.execute(text(_CLIP_BUILD_SQL), {
                "b": json.dumps(shape), "m": float(CLIP_BUFFER_M)})).mappings().one()
    except Exception:
        logger.warning("[GIS] the township boundary could not be buffered", exc_info=True)
        return Clip(applied=False, reason="unreadable", area_name=name)
    if not r["clip"] or r["w"] is None:
        return Clip(applied=False, reason="unreadable", area_name=name)
    return Clip(applied=True, area_name=name, ewkb_hex=r["clip"],
                bbox=(float(r["w"]), float(r["s"]), float(r["e"]), float(r["n"])))


def geometry_bbox(coords: Any) -> Optional[Tuple[float, float, float, float]]:
    """(minx, miny, maxx, maxy) of a GeoJSON coordinates array, iteratively."""
    minx = miny = math.inf
    maxx = maxy = -math.inf
    stack = [coords]
    while stack:
        node = stack.pop()
        if not isinstance(node, list) or not node:
            continue
        if isinstance(node[0], (int, float)) and not isinstance(node[0], bool):
            if len(node) >= 2 and isinstance(node[1], (int, float)):
                x, y = node[0], node[1]
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
            continue
        stack.extend(node)
    if minx is math.inf:
        return None
    return minx, miny, maxx, maxy


def _overlaps(a: Optional[Tuple[float, float, float, float]], b: Tuple[float, float, float, float]) -> bool:
    if a is None:
        return True  # let the exact test decide
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


async def _aiter(features: Any):
    """Iterate a plain or an async iterable alike."""
    if hasattr(features, "__aiter__"):
        async for f in features:
            yield f
    else:
        for f in features:
            yield f


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

_INSERT_SQL = (
    "INSERT INTO map_layer_features (layer_id, properties, geom) VALUES ("
    ":layer_id, CAST(:props AS jsonb), "
    "ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)), 3)))"
)

# The ID property when the feature has one, else a hash of the repaired
# geometry -- which survives a re-upload of the same shapes, where a row
# number would not.
_KEY_SQL = (
    "UPDATE map_layer_features SET feature_key = COALESCE("
    "NULLIF(left(btrim(properties ->> CAST(:prop AS text)), 200), ''), "
    "'g:' || left(md5(ST_AsBinary(geom)), 16)) WHERE layer_id = :layer_id"
)
_EMPTY_SQL = "DELETE FROM map_layer_features WHERE layer_id = :l AND ST_IsEmpty(geom)"
_OUTSIDE_SQL = f"DELETE FROM map_layer_features WHERE layer_id = :l AND NOT ST_Intersects(geom, {_CLIP_GEOM})"


async def assign_feature_keys(db, layer) -> None:
    from sqlalchemy import text
    await db.execute(text(_KEY_SQL), {"prop": layer.feature_id_property, "layer_id": layer.id})


async def _prune_rows(db, layer, clip: Optional[Clip]) -> Tuple[int, int]:
    """(empty, outside) rows deleted from the layer: repaired-to-nothing, then out of town."""
    from sqlalchemy import text

    empty = (await db.execute(text(_EMPTY_SQL), {"l": layer.id})).rowcount or 0
    outside = 0
    if clip is not None and clip.applied:
        outside = (await db.execute(text(_OUTSIDE_SQL), {"l": layer.id, "clip": clip.ewkb_hex})).rowcount or 0
    return empty, outside


def _too_many(limit: int, clip: Optional[Clip]) -> LayerUploadError:
    where = f" inside {clip.area}" if clip is not None and clip.applied else ""
    return LayerUploadError(
        f"The layer has more than {limit:,} features{where}, the limit for one layer. "
        "Split it into several layers.")


async def import_features(db, layer, features: Any, *, clip: Optional[Clip] = None,
                          progress=None) -> Dict[str, Any]:
    """Replace a layer's features with `features`. The caller commits.

    One transaction: the old features are deleted and the new ones inserted
    under it, so a failed or rejected upload leaves the layer exactly as it
    was, and reports filed during the import match the old parcels.

    `features` may be a plain or an async iterable (an ArcGIS download). With
    an applied `clip`, features outside the buffered township are dropped --
    most by a bounding-box test before they are inserted, the rest by one
    DELETE against the exact outline -- and MAX_FEATURES counts what is kept.
    `progress(read)` is called after each insert batch.
    """
    from sqlalchemy import text

    clipping = clip is not None and clip.applied
    await db.execute(text("DELETE FROM map_layer_features WHERE layer_id = :l"), {"l": layer.id})
    fields: Dict[str, None] = {}
    batch: List[Dict[str, Any]] = []
    total = inserted = outside_box = 0
    removed_empty = removed_outside = 0

    async def flush() -> None:
        nonlocal batch, removed_empty, removed_outside
        if batch:
            await db.execute(text(_INSERT_SQL), batch)
            batch = []
        if progress is not None:
            progress(total)
        if clipping and inserted - removed_empty - removed_outside > MAX_FEATURES:
            # Over the cap counting everything in the envelope: apply the
            # exact outline now, and only refuse if it is still over.
            empty, outside = await _prune_rows(db, layer, clip)
            removed_empty += empty
            removed_outside += outside
            if inserted - removed_empty - removed_outside > MAX_FEATURES:
                raise _too_many(MAX_FEATURES, clip)

    async for feature in _aiter(features):
        total += 1
        if total > MAX_SCAN_FEATURES:
            raise LayerUploadError(
                f"The layer has more than {MAX_SCAN_FEATURES:,} features. Split it into several layers.")
        geometry, props = feature_parts(feature, total)
        if clipping and not _overlaps(geometry_bbox(feature["geometry"]["coordinates"]), clip.bbox):
            outside_box += 1
            continue
        inserted += 1
        if not clipping and inserted > MAX_FEATURES:
            raise _too_many(MAX_FEATURES, clip)
        if len(fields) < MAX_AVAILABLE_PROPERTIES:
            for key in props:
                if key not in fields and len(fields) < MAX_AVAILABLE_PROPERTIES:
                    fields[key] = None
        batch.append({"layer_id": layer.id, "props": json.dumps(props), "g": geometry})
        if len(batch) >= INSERT_BATCH:
            await flush()
    await flush()
    if total == 0:
        raise LayerUploadError("The file has no features.")

    # A self-intersecting sliver can repair to nothing at all. Kept out rather
    # than refusing a 30,000-parcel file over one, and reported back.
    empty, outside = await _prune_rows(db, layer, clip)
    removed_empty += empty
    removed_outside += outside
    skipped = removed_empty
    kept = inserted - removed_empty - removed_outside
    if kept > MAX_FEATURES:
        raise _too_many(MAX_FEATURES, clip)
    if kept <= 0:
        if clipping and (outside_box or removed_outside):
            raise LayerUploadError(
                f"None of the {total:,} features is inside {clip.area}. Check that this is the right "
                "layer, and that the township boundary in Setup is right.")
        raise LayerUploadError("None of the features has any area once repaired.")

    available = list(fields)
    if not layer.feature_id_property or layer.feature_id_property not in available:
        layer.feature_id_property = guess_id_property(available)
    await assign_feature_keys(db, layer)

    clip = clip or Clip(applied=False, reason="no_boundary")
    layer.available_properties = available
    layer.staff_properties = [p for p in (layer.staff_properties or []) if p in available]
    if layer.label_property and layer.label_property not in available:
        layer.label_property = None
    layer.feature_count = kept
    layer.features_imported_at = datetime.now(timezone.utc)
    layer.feature_storage = TABLE
    layer.layer_type = "polygon"
    layer.geojson = dict(EMPTY_FEATURE_COLLECTION)
    considered = total - skipped
    return {"feature_count": kept, "skipped": skipped, "properties": available,
            "feature_id_property": layer.feature_id_property, "total": total,
            "outside": outside_box + removed_outside,
            "clip": clip.summary(kept, considered), "clip_message": clip.message(kept, considered)}


# ---------------------------------------------------------------------------
# Inline point layers
# ---------------------------------------------------------------------------

POINT_BATCH = 2000
_POINTS_INSIDE_SQL = (
    "SELECT t.i FROM unnest(CAST(:gs AS text[])) WITH ORDINALITY AS t(g, i) "
    f"WHERE ST_Intersects(ST_SetSRID(ST_GeomFromGeoJSON(t.g), 4326), {_CLIP_GEOM})"
)


def point_parts(feature: Any, n: int) -> Dict[str, Any]:
    """One point feature, checked and cleaned, or LayerUploadError."""
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise LayerUploadError(f"Item {n} in `features` is not a GeoJSON Feature.")
    geom = feature.get("geometry")
    if not isinstance(geom, dict):
        raise LayerUploadError(f"Feature {n} has no geometry.")
    kind = geom.get("type")
    if kind not in ("Point", "MultiPoint"):
        raise LayerUploadError(
            f"Feature {n} is a {kind!s:.30}. Point layers take Point and MultiPoint features only; "
            "add areas as a polygon layer.")
    coords = geom.get("coordinates")
    _check_positions(coords, 0 if kind == "Point" else 1, n)
    props = feature.get("properties")
    if props is None:
        props = {}
    if not isinstance(props, dict):
        raise LayerUploadError(f"Feature {n} has properties that are not an object.")
    return {"type": "Feature", "geometry": {"type": kind, "coordinates": coords}, "properties": _clean(props)}


def _too_many_points(clip: Optional[Clip], *, by_size: bool = False) -> LayerUploadError:
    where = f" inside {clip.area}" if clip is not None and clip.applied else ""
    what = (f"more than {MAX_INLINE_BYTES // 1048576} MB of points" if by_size
            else f"more than {MAX_INLINE_FEATURES:,} points")
    return LayerUploadError(
        f"The layer has {what}{where}. A point layer is sent whole to every resident's map, so it "
        f"is limited to {MAX_INLINE_FEATURES:,} points and {MAX_INLINE_BYTES // 1048576} MB. Split it "
        "into several layers (by area or by type), or add it as a polygon layer if the features are areas.")


def check_inline_size(geojson: Any) -> None:
    """The inline cap for a layer saved whole (a point or hand-drawn layer)."""
    if not isinstance(geojson, dict):
        return
    features = geojson.get("features") if geojson.get("type") == "FeatureCollection" else None
    if isinstance(features, list) and len(features) > MAX_INLINE_FEATURES:
        raise _too_many_points(None)
    if len(json.dumps(geojson, separators=(",", ":"))) > MAX_INLINE_BYTES:
        raise _too_many_points(None, by_size=True)


async def build_inline_points(db, features: Any, *, clip: Optional[Clip] = None,
                              progress=None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(FeatureCollection, summary) for an inline point layer.

    Clipped to the township first -- a bounding-box test, then one PostGIS
    query per batch against the buffered outline -- and capped after, by
    MAX_INLINE_FEATURES and MAX_INLINE_BYTES, so a county file whose in-town
    part fits is accepted.
    """
    from sqlalchemy import text

    clipping = clip is not None and clip.applied
    kept: List[Dict[str, Any]] = []
    size = 0
    total = outside = 0
    fields: Dict[str, None] = {}
    pending: List[Dict[str, Any]] = []

    async def settle() -> None:
        nonlocal pending, size, outside
        chosen = pending
        if clipping and pending:
            rows = (await db.execute(text(_POINTS_INSIDE_SQL), {
                "gs": [json.dumps(f["geometry"]) for f in pending], "clip": clip.ewkb_hex,
            })).scalars().all()
            inside = {int(i) for i in rows}
            chosen = [f for i, f in enumerate(pending, start=1) if i in inside]
            outside += len(pending) - len(chosen)
        pending = []
        for f in chosen:
            size += len(json.dumps(f, separators=(",", ":"))) + 1
            kept.append(f)
            if len(fields) < MAX_AVAILABLE_PROPERTIES:
                for key in f["properties"]:
                    if len(fields) < MAX_AVAILABLE_PROPERTIES:
                        fields.setdefault(key, None)
        if len(kept) > MAX_INLINE_FEATURES:
            raise _too_many_points(clip)
        if size > MAX_INLINE_BYTES:
            raise _too_many_points(clip, by_size=True)
        if progress is not None:
            progress(total)

    async for feature in _aiter(features):
        total += 1
        if total > MAX_SCAN_FEATURES:
            raise LayerUploadError(
                f"The layer has more than {MAX_SCAN_FEATURES:,} features. Split it into several layers.")
        f = point_parts(feature, total)
        if clipping and not _overlaps(geometry_bbox(f["geometry"]["coordinates"]), clip.bbox):
            outside += 1
            continue
        pending.append(f)
        if len(pending) >= POINT_BATCH:
            await settle()
    await settle()
    if total == 0:
        raise LayerUploadError("The file has no features.")
    if not kept:
        raise LayerUploadError(
            f"None of the {total:,} points is inside {clip.area}. Check that this is the right "
            "layer, and that the township boundary in Setup is right.")
    clip = clip or Clip(applied=False, reason="no_boundary")
    geojson = {"type": "FeatureCollection", "features": kept}
    return geojson, {"feature_count": len(kept), "skipped": 0, "properties": list(fields),
                     "feature_id_property": None, "total": total, "outside": outside,
                     "clip": clip.summary(len(kept), total), "clip_message": clip.message(len(kept), total)}


# ---------------------------------------------------------------------------
# Matching: the GIS context of a point
# ---------------------------------------------------------------------------

_CONTEXT_SQL = (
    "SELECT f.id AS feature_id, f.feature_key, f.properties, l.id AS layer_id, "
    "l.name AS layer_name, l.label_property, l.staff_properties, l.service_codes "
    "FROM map_layer_features f JOIN map_layers l ON l.id = f.layer_id "
    "WHERE l.is_active IS TRUE AND l.routing_mode = 'context' AND l.feature_storage = 'table' "
    "AND ST_Covers(f.geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)) "
    "ORDER BY l.name, l.id, f.feature_key LIMIT :cap"
)


def _loads(value: Any) -> Any:
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def is_postgres(db) -> bool:
    try:
        return db.get_bind().dialect.name == "postgresql"
    except Exception:
        return False


def _applies(service_codes: Any, service_code: Optional[str]) -> bool:
    codes = _loads(service_codes) or []
    return not codes or not service_code or service_code in codes


def snapshot_entry(*, layer_id, layer_name, feature_id, feature_key, properties,
                   label_property, staff_properties) -> Dict[str, Any]:
    """One gis_context entry: the allowlisted properties ONLY, as they are now."""
    props = _loads(properties) or {}
    allow = _loads(staff_properties) or []
    label = props.get(label_property) if label_property else None
    label = str(label).strip() if label not in (None, "") else ""
    return {
        "layer_id": layer_id,
        "layer_name": layer_name,
        "feature_id": feature_id,
        "feature_key": feature_key,
        "label": (label or feature_key or "")[:200],
        "properties": {k: props[k] for k in allow if k in props},
    }


async def query_context(db, lat: float, lng: float, service_code: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """The context entries for a point. Raises on a database error."""
    from sqlalchemy import text

    async with db.begin_nested():
        rows = (await db.execute(
            text(_CONTEXT_SQL), {"lat": float(lat), "lng": float(lng), "cap": MAX_CONTEXT_MATCHES}
        )).mappings().all()
    entries = [
        snapshot_entry(
            layer_id=r["layer_id"], layer_name=r["layer_name"], feature_id=r["feature_id"],
            feature_key=r["feature_key"], properties=r["properties"],
            label_property=r["label_property"], staff_properties=r["staff_properties"],
        )
        for r in rows if _applies(r["service_codes"], service_code)
    ]
    return entries or None


async def context_for_point(db, lat: Optional[float], lng: Optional[float],
                            service_code: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
    """gis_context for a new report. Never raises: intake must not fail over GIS.

    Run inside a SAVEPOINT, so a failure (a town still on the previous schema
    during a rolling deploy, say) cannot poison the intake transaction.
    """
    if lat is None or lng is None or not is_postgres(db):
        return None
    try:
        return await query_context(db, lat, lng, service_code)
    except Exception:
        logger.warning("[GIS] context lookup failed; the report is saved without it", exc_info=True)
        return None


def _keys(entries: Any) -> set:
    return {(e.get("layer_id"), e.get("feature_key")) for e in (entries or []) if isinstance(e, dict)}


def summarize(entries: Any) -> str:
    """'Tax Parcels: 12-4; Zoning: R-1' for an audit row."""
    parts = [f"{e.get('layer_name')}: {e.get('label') or e.get('feature_key')}"
             for e in (entries or []) if isinstance(e, dict)]
    return ("; ".join(parts) or "none")[:500]


async def refresh_request_context(db, request, *, actor_type: str, actor_name: str,
                                  reason: str) -> bool:
    """Recompute a report's GIS context after its location moved. The caller commits.

    Writes a timeline entry when the set of containing features changed. When
    it did not, the stored snapshot is kept: it is the record of what the
    parcel said at intake, and a location nudge within the same parcel is not
    a reason to overwrite it. On a database error nothing is changed.
    """
    from app.models import RequestAuditLog

    if request.lat is None or request.long is None:
        new = None
    elif not is_postgres(db):
        return False
    else:
        try:
            new = await query_context(db, request.lat, request.long, request.service_code)
        except Exception:
            logger.warning("[GIS] context refresh failed for request %s", request.id, exc_info=True)
            return False
    old = request.gis_context
    if _keys(old) == _keys(new):
        return False
    request.gis_context = new
    db.add(RequestAuditLog(
        service_request_id=request.id,
        action="location_context_updated",
        old_value=summarize(old),
        new_value=summarize(new),
        actor_type=actor_type,
        actor_name=actor_name,
        extra_data={"reason": reason},
    ))
    return True


_BACKFILL_SQL = (
    "SELECT sr.id AS request_id, f.id AS feature_id, f.feature_key, f.properties "
    "FROM service_requests sr JOIN map_layer_features f ON f.layer_id = :layer_id "
    "AND ST_Covers(f.geom, ST_SetSRID(ST_MakePoint(sr.long, sr.lat), 4326)) "
    "WHERE sr.id = ANY(:ids) ORDER BY sr.id, f.feature_key"
)


async def backfill_layer(db, layer, *, actor_name: str, batch_size: int = BACKFILL_BATCH) -> Dict[str, int]:
    """Add this layer's context to existing reports that lack it. Commits per batch.

    Reports that already carry an entry for the layer are left alone: that
    entry is their intake snapshot. Each report that gains context gets a
    timeline entry saying so, and that it came from a backfill rather than
    from intake -- the properties are today's, not the day it was filed.
    """
    from sqlalchemy import select, text
    from sqlalchemy.orm.attributes import flag_modified
    from app.models import RequestAuditLog, ServiceRequest

    last_id = 0
    scanned = updated = 0
    while True:
        rows = (await db.execute(
            select(ServiceRequest)
            .where(ServiceRequest.id > last_id,
                   ServiceRequest.lat.isnot(None), ServiceRequest.long.isnot(None),
                   ServiceRequest.deleted_at.is_(None))
            .order_by(ServiceRequest.id)
            .limit(batch_size)
        )).scalars().all()
        if not rows:
            break
        last_id = rows[-1].id
        scanned += len(rows)
        candidates = {
            r.id: r for r in rows
            if _applies(layer.service_codes, r.service_code)
            and not any(isinstance(e, dict) and e.get("layer_id") == layer.id for e in (r.gis_context or []))
        }
        if candidates:
            matches = (await db.execute(
                text(_BACKFILL_SQL), {"layer_id": layer.id, "ids": list(candidates)}
            )).mappings().all()
            found: Dict[int, List[Dict[str, Any]]] = {}
            for m in matches:
                if len(found.get(m["request_id"], [])) >= MAX_CONTEXT_MATCHES:
                    continue
                found.setdefault(m["request_id"], []).append(snapshot_entry(
                    layer_id=layer.id, layer_name=layer.name, feature_id=m["feature_id"],
                    feature_key=m["feature_key"], properties=m["properties"],
                    label_property=layer.label_property, staff_properties=layer.staff_properties,
                ))
            for request_id, entries in found.items():
                request = candidates[request_id]
                request.gis_context = list(request.gis_context or []) + entries
                flag_modified(request, "gis_context")
                db.add(RequestAuditLog(
                    service_request_id=request.id,
                    action="location_context_updated",
                    old_value=None,
                    new_value=summarize(entries),
                    actor_type="staff",
                    actor_name=actor_name,
                    extra_data={"reason": "backfill", "layer_id": layer.id},
                ))
                updated += 1
        await db.commit()
    return {"scanned": scanned, "updated": updated}


# ---------------------------------------------------------------------------
# Staff map: features in a viewport
# ---------------------------------------------------------------------------

_BBOX_SQL = (
    "SELECT f.id, f.feature_key, f.properties ->> CAST(:label AS text) AS label, "
    "ST_AsGeoJSON(ST_SimplifyPreserveTopology(f.geom, :tol), 6) AS g "
    "FROM map_layer_features f "
    "WHERE f.layer_id = :layer_id AND f.geom && ST_MakeEnvelope(:w, :s, :e, :n, 4326) "
    "ORDER BY f.id LIMIT :cap"
)


def parse_bbox(raw: str) -> Tuple[float, float, float, float]:
    try:
        w, s, e, n = (float(v) for v in str(raw).split(","))
    except ValueError:
        raise LayerUploadError("bbox must be west,south,east,north in degrees.")
    if not all(math.isfinite(v) for v in (w, s, e, n)) or not (
            -180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise LayerUploadError("bbox must be west,south,east,north in degrees.")
    return w, s, e, n


async def features_in_bbox(db, layer, bbox: Tuple[float, float, float, float],
                           zoom: Optional[float]) -> Dict[str, Any]:
    """Simplified outlines inside a viewport, or a zoom-in flag past the cap.

    Past the cap the answer is no features rather than the first 500: a map
    that silently draws an arbitrary subset of parcels reads as "these are the
    parcels", which is worse than asking the user to zoom in.
    """
    from sqlalchemy import text

    out: Dict[str, Any] = {"type": "FeatureCollection", "features": [], "zoom_in": False,
                           "limit": MAX_BBOX_FEATURES}
    if zoom is not None and zoom < MIN_BBOX_ZOOM:
        out["zoom_in"] = True
        return out
    w, s, e, n = bbox
    # About a pixel on a ~1500 px wide viewport: invisible, and it drops the
    # vertex-per-foot detail survey-grade parcel files carry.
    tolerance = max(e - w, n - s) / 1500.0
    rows = (await db.execute(text(_BBOX_SQL), {
        "label": layer.label_property, "tol": tolerance, "layer_id": layer.id,
        "w": w, "s": s, "e": e, "n": n, "cap": MAX_BBOX_FEATURES + 1,
    })).mappings().all()
    if len(rows) > MAX_BBOX_FEATURES:
        out["zoom_in"] = True
        return out
    out["features"] = [
        {
            "type": "Feature",
            "id": r["id"],
            "geometry": _loads(r["g"]),
            "properties": {
                "feature_id": r["id"],
                "feature_key": r["feature_key"],
                "label": (r["label"] or r["feature_key"] or "")[:200],
            },
        }
        for r in rows
    ]
    return out


# ---------------------------------------------------------------------------
# Resident portal: shapes only
# ---------------------------------------------------------------------------

_PUBLIC_BBOX_SQL = (
    "SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(f.geom, :tol), 6) AS g "
    "FROM map_layer_features f "
    "WHERE f.layer_id = :layer_id AND f.geom && ST_MakeEnvelope(:w, :s, :e, :n, 4326) "
    "ORDER BY f.id LIMIT :cap"
)


def layer_is_resident_visible(layer) -> bool:
    """Whether a table-backed layer's outlines may be served to anyone.

    Re-judged on every request rather than trusted from the flag alone: a
    layer whose allowlist was later emptied, or gained an owner field, stops
    being served even if nobody turned the flag off.
    """
    if not (layer.is_active and layer.show_on_resident_portal):
        return False
    if (layer.feature_storage or INLINE) != TABLE:
        return False
    errors, _ = portal_visibility_problems(layer)
    return not errors


async def public_outlines_in_bbox(db, layer, bbox: Tuple[float, float, float, float],
                                  zoom: float) -> Dict[str, Any]:
    """Simplified shapes in a viewport for the resident map: geometry ONLY.

    No properties, no feature key, no ids -- a parcel id is a lookup key into
    the county's owner records, and an id would let a caller enumerate the
    layer. The same zoom rule and cap as the staff map.
    """
    from sqlalchemy import text

    out: Dict[str, Any] = {"type": "FeatureCollection", "features": [], "zoom_in": False,
                           "limit": MAX_BBOX_FEATURES}
    if zoom < MIN_BBOX_ZOOM:
        out["zoom_in"] = True
        return out
    w, s, e, n = bbox
    rows = (await db.execute(text(_PUBLIC_BBOX_SQL), {
        "tol": max(e - w, n - s) / 1500.0, "layer_id": layer.id,
        "w": w, "s": s, "e": e, "n": n, "cap": MAX_BBOX_FEATURES + 1,
    })).scalars().all()
    if len(rows) > MAX_BBOX_FEATURES:
        out["zoom_in"] = True
        return out
    out["features"] = [{"type": "Feature", "properties": {}, "geometry": _loads(g)} for g in rows]
    return out

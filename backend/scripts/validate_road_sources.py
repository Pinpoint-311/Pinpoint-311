#!/usr/bin/env python3
"""Check every entry in the state road-source registry against the live service.

The registry was assembled in a sandbox whose egress is allowlisted to GitHub,
so not one of its endpoints was ever called. Each entry's URL came from a
search-indexed ArcGIS REST directory page -- good evidence the layer exists,
no evidence at all that the layer id is right, that the service still answers,
or that the field names are what we assume.

This script closes that gap. Run it from any machine with normal internet
access:

    python scripts/validate_road_sources.py                # check everything
    python scripts/validate_road_sources.py NJ NY PA       # check some states
    python scripts/validate_road_sources.py --json out.json

It reads only. It never writes to the registry -- paste the output back and the
registry gets corrected by hand, so a bad automated rewrite can't quietly
replace good entries with garbage.

Requires: httpx (already in requirements.txt). No database, no app config.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import httpx
except ImportError:
    sys.exit("httpx is required:  pip install httpx")

from app.services.road_sources_registry import STATE_ROAD_SOURCES  # noqa: E402

TIMEOUT = 45.0

# A road-centreline layer must be lines. Anything else means we recorded the
# wrong layer id -- a point layer here is usually address points, a polygon
# layer is usually municipal boundaries.
LINE_GEOMETRY = {"esriGeometryPolyline"}

# Field names that plausibly carry a street name, in rough order of preference.
# Used to suggest a field_map for the entries that have none.
NAME_HINTS = [
    "fullname", "full_name", "completestreetname", "street_name", "streetname",
    "st_name", "rd_name", "roadname", "road_name", "label", "name",
]


def _get(client: httpx.Client, url: str, **params) -> Dict[str, Any]:
    params.setdefault("f", "json")
    response = client.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    # ArcGIS reports failures with HTTP 200 and an {"error": {...}} body.
    if isinstance(payload, dict) and "error" in payload:
        raise RuntimeError(payload["error"].get("message", "ArcGIS error"))
    return payload


def _name_candidates(fields: List[Dict[str, Any]], display_field: str) -> List[str]:
    names = [f.get("name", "") for f in fields]
    ranked = []
    if display_field:
        ranked.append(display_field)
    for hint in NAME_HINTS:
        for name in names:
            if name.lower() == hint and name not in ranked:
                ranked.append(name)
    for hint in NAME_HINTS:
        for name in names:
            if hint in name.lower() and name not in ranked:
                ranked.append(name)
    return ranked[:6]


def check(client: httpx.Client, code: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"state": code, "name": entry.get("name"), "ok": False}

    layer_id = entry.get("layer_id")
    service_url = entry.get("service_url")
    url = entry.get("url")

    if layer_id is None:
        # Only the service root was ever indexed. List its layers so a human can
        # pick the right one rather than us guessing.
        try:
            info = _get(client, service_url)
        except Exception as exc:
            result["error"] = f"service unreachable: {exc}"
            return result
        result["needs_layer_id"] = [
            {"id": lyr.get("id"), "name": lyr.get("name"), "geometry": lyr.get("geometryType")}
            for lyr in info.get("layers", []) or []
        ]
        result["error"] = "layer_id is None; pick one from needs_layer_id"
        return result

    try:
        info = _get(client, url)
    except Exception as exc:
        result["error"] = f"layer unreachable: {exc}"
        return result

    geometry_type = info.get("geometryType")
    result["layer_name"] = info.get("name")
    result["geometry_type"] = geometry_type
    result["display_field"] = info.get("displayField")

    if geometry_type not in LINE_GEOMETRY:
        result["error"] = f"not a line layer ({geometry_type}) -- wrong layer id"
        return result

    # A layer named "... DEPRECATED" or "previous schema" is exactly the trap
    # the NJ entry documents; surface it rather than silently accepting.
    lowered = (info.get("name") or "").lower()
    if "deprecat" in lowered or "previous schema" in lowered or "archive" in lowered:
        result["warning"] = f"layer name suggests it is superseded: {info.get('name')!r}"

    fields = info.get("fields", []) or []
    result["field_count"] = len(fields)
    result["name_field_candidates"] = _name_candidates(fields, info.get("displayField") or "")

    declared = entry.get("field_map") or {}
    if declared:
        present = {f.get("name", "").lower() for f in fields}
        missing = [v for v in declared.values() if isinstance(v, str) and v.lower() not in present]
        if missing:
            result["field_map_missing"] = missing

    # Does it actually return features? An empty statewide layer is a live
    # endpoint that would still seed a town with nothing.
    try:
        sample = _get(
            client, f"{url}/query",
            where="1=1", returnCountOnly="true",
        )
        result["feature_count"] = sample.get("count")
    except Exception as exc:
        result["warning"] = f"{result.get('warning', '')} count query failed: {exc}".strip()

    result["ok"] = "error" not in result
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("states", nargs="*", help="state codes to check (default: all)")
    parser.add_argument("--json", dest="json_out", help="write full results to this path")
    args = parser.parse_args()

    wanted = [s.upper() for s in args.states] if args.states else list(STATE_ROAD_SOURCES)
    # DEFAULT (TIGER) first and always: a wrong value there breaks every state
    # that falls back, which is most of the country.
    if "DEFAULT" in wanted:
        wanted.remove("DEFAULT")
    wanted = ["DEFAULT"] + sorted(wanted)

    results = []
    with httpx.Client(follow_redirects=True, headers={"User-Agent": "Pinpoint311-registry-check"}) as client:
        for code in wanted:
            entry = STATE_ROAD_SOURCES.get(code)
            if not entry:
                print(f"{code:8} SKIP   no registry entry")
                continue
            result = check(client, code, entry)
            results.append(result)

            if result["ok"]:
                count = result.get("feature_count")
                count_text = f"{count:,} features" if isinstance(count, int) else "count unknown"
                print(f"{code:8} OK     {result.get('layer_name')!r} -- {count_text}")
                if result.get("warning"):
                    print(f"{'':8}        WARNING: {result['warning']}")
                if result.get("field_map_missing"):
                    print(f"{'':8}        field_map references missing fields: {result['field_map_missing']}")
                if not (entry.get("field_map")):
                    print(f"{'':8}        name field candidates: {result['name_field_candidates']}")
            else:
                print(f"{code:8} FAIL   {result.get('error')}")
                for layer in result.get("needs_layer_id", [])[:25]:
                    print(f"{'':8}        [{layer['id']}] {layer['name']} ({layer['geometry']})")

    ok = sum(1 for r in results if r["ok"])
    print(f"\n{ok}/{len(results)} entries verified.")

    default = next((r for r in results if r["state"] == "DEFAULT"), None)
    if default and not default["ok"]:
        print("\nDEFAULT (TIGER) FAILED -- this is the fallback for every state without\n"
              "its own entry, so it breaks the majority of the country, not one state.\n"
              "Fix this before anything else.")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(results, indent=2))
        print(f"\nFull results written to {args.json_out}")

    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

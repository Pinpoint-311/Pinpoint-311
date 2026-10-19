"""Check an agencies file against this town's road data, read-only.

    python -m app.cli.check_jurisdictions PATH [--json]

PATH is a jurisdictions file in the format the admin console imports
({"format": "pinpoint311.agencies", "agencies": [{name, roads: [...]}, ...]}),
kept wherever the town's own data lives -- not in this repository. For every
road it reports which road_segments names it matches, and for a road limited
to a stretch ("Oak Road (Elm Street to Route 10)") whether the limits were
found on the map, and how long the claimed stretch is.

Run it before importing, so a road that matches nothing or a limit that falls
back to the whole road is fixed first. It opens its own connection from
DATABASE_URL with default_transaction_read_only on, and never writes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Sequence

from app.services.road_matching import parse_road_entry, road_entry_name


def load_agencies(doc: Any) -> List[Dict[str, Any]]:
    """The agencies in a parsed file: [{name, roads: [labels]}]. Raises ValueError."""
    items = doc if isinstance(doc, list) else (doc or {}).get("agencies") if isinstance(doc, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError('no agencies found: the file needs an "agencies" list')
    out = []
    for i, raw in enumerate(items, 1):
        if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
            raise ValueError(f"agency {i} has no name")
        roads = raw.get("roads")
        if roads is None and isinstance(raw.get("road_list"), str):
            roads = [r.strip() for r in raw["road_list"].split(",")]
        entries = [parse_road_entry(r) for r in (roads or [])]
        out.append({"name": str(raw["name"]).strip(), "roads": [e.label for e in entries if e]})
    return out


def match_rows(agencies: Sequence[Dict[str, Any]], known_names: Sequence[str]) -> List[Dict[str, Any]]:
    """One row per road: what it matches by name. Pure, so it is testable."""
    from app.services.road_limits import matching_names

    rows = []
    for agency in agencies:
        for label in agency["roads"]:
            entry = parse_road_entry(label)
            rows.append({
                "agency": agency["name"],
                "entry": label,
                "road": road_entry_name(label),
                "has_limits": bool(entry and entry.has_limits),
                "matches": matching_names(road_entry_name(label), known_names),
            })
    return rows


async def _run(path: str) -> List[Dict[str, Any]]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.services import road_limits

    with open(path, encoding="utf-8") as fh:
        agencies = load_agencies(json.load(fh))
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    engine = create_async_engine(
        url, connect_args={"server_settings": {"default_transaction_read_only": "on"}}
    )
    try:
        async with AsyncSession(engine) as db:
            names = [r[0] for r in (await db.execute(
                text("SELECT DISTINCT name FROM road_segments WHERE name IS NOT NULL")
            )).all()]
            rows = match_rows(agencies, names)
            for row in rows:
                if row["has_limits"]:
                    entry = parse_road_entry(row["entry"])
                    res = await road_limits.resolve_limits(db, entry, known_names=names, use_cache=False)
                    row["limits"] = {"status": res.status, "message": res.message,
                                     "stretch_m": round(res.stretch_m) if res.stretch_m else None}
            await db.rollback()
    finally:
        await engine.dispose()
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.check_jurisdictions")
    parser.add_argument("path", help="agencies JSON file")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = parser.parse_args(argv)
    rows = asyncio.run(_run(args.path))
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            found = ", ".join(row["matches"][:4]) + (" ..." if len(row["matches"]) > 4 else "")
            line = f"{row['agency'][:32]:32}  {row['entry'][:44]:44}  {found or 'NO MATCH'}"
            if "limits" in row:
                line += f"\n{'':78}limits: {row['limits']['status']} -- {row['limits']['message']}"
            print(line)
    return 0 if all(r["matches"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())

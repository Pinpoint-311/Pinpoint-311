"""Who filed the reports: the arithmetic behind the Spatial Bias detector.

The detector compares where reports are with where *reporters* are, so an area
where one resident files again and again stands out from one where many
neighbours each file once. That needs "is this the same person?", and the
answer here was wrong in two ways at once:

  * The reporter total was the number of ~100 m grid cells with any report,
    not a count of people at all.
  * The per-cell de-duplication keyed on the `email` column, which holds
    AES-GCM ciphertext under a fresh nonce per row. Two reports from the same
    address never share a ciphertext, so every report was its own "reporter"
    and the ratio was pinned at 1.0x everywhere -- a bias detector that could
    not detect bias.

The only stable identifier the database holds is the keyed fingerprint of the
normalised email (`resident_email_index`, see core/resident_index). It exists
only while the town has the "Resident history" module on; with it off the town
has deliberately chosen to hold no linkable identifier, and the honest answer
is "unknown", never a number. PII is never decrypted to count people.

A report without a fingerprint (no email given, an intake placeholder, a
retention-scrubbed record, or one not yet fingerprinted) cannot be attributed
to anyone. It is counted as a report, never as a reporter, and kept out of the
reports-per-reporter average; the caller shows it separately.

Pure functions, so CI can test them without FastAPI or a database.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional, Tuple

# ~111 m north-south; ~85 m east-west at mid-latitudes. Coarse enough not to
# pinpoint a house, fine enough to show a street.
_GRID = Decimal("0.001")

Row = Tuple[Optional[float], Optional[float], Optional[str]]


def grid(value: float) -> float:
    """Round to the grid the same way Postgres' ROUND(numeric, 3) does
    (half away from zero), not Python's banker's rounding."""
    return float(Decimal(str(value)).quantize(_GRID, rounding=ROUND_HALF_UP))


def summarise(rows: Iterable[Row], identity_available: bool) -> dict:
    """Heat-map payload from (lat, lng, reporter fingerprint) rows.

    `identity_available` is whether reporter fingerprints are being kept at
    all (the Resident history module). When it is False every reporter figure
    is None -- unknown -- and fingerprints present in the rows are ignored.
    """
    report_points = []
    cells: dict = {}
    reporters = set()
    identified = 0

    for lat, lng, key in rows:
        if lat is None or lng is None:
            continue
        glat, glng = grid(lat), grid(lng)
        report_points.append({"lat": glat, "lng": glng, "weight": 1})
        if not identity_available or not key:
            continue
        identified += 1
        reporters.add(key)
        cells.setdefault((glat, glng), set()).add(key)

    total = len(report_points)
    if not identity_available:
        return {
            "report_points": report_points,
            "reporter_points": [],
            "total_reports": total,
            "total_unique_reporters": None,
            "identified_reports": None,
            "anonymous_reports": None,
            "reporter_identity_available": False,
        }
    return {
        "report_points": report_points,
        # One point per cell, weighted by the distinct people who reported
        # there: the same resident filing five times in one cell counts once.
        "reporter_points": [
            {"lat": lat, "lng": lng, "weight": len(keys)}
            for (lat, lng), keys in sorted(cells.items())
        ],
        "total_reports": total,
        "total_unique_reporters": len(reporters),
        "identified_reports": identified,
        "anonymous_reports": total - identified,
        "reporter_identity_available": True,
    }


"""Pure mapping rules shared by every connector and the sync tasks.

Nothing here touches the database or the network, so the rules that decide
what crosses between Pinpoint and a vendor can be tested on their own.

Two kinds of mapping live here:

* **Service codes.** ``service_code_map_out`` is local code -> vendor code and
  is what a push sends. ``service_code_map_in`` is vendor code (or name) ->
  local code and is what an import files under. The original single
  ``service_code_map`` key was validated by the /mapping endpoint as holding
  *vendor* codes, so its values are treated as the outbound map.

* **Inbound status.** A pull reports the vendor's raw status on every poll,
  whether or not it changed. Applying it whenever it differs from ours meant a
  vendor whose vocabulary is coarser than ours (Open311 has only open/closed)
  undid every "in progress" a staff member set, every fifteen minutes.
  ``decide_inbound_status`` applies a vendor status only when the vendor
  actually moved.
"""

from typing import Any, Callable, Dict, Optional

# Our lifecycle, in order. Used only to decide which way a first sighting moves.
STATUS_RANK = {"open": 0, "in_progress": 1, "closed": 2}

# A link's external_status column is String(50).
EXTERNAL_STATUS_MAX = 50


def _clean_map(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()
            if k not in (None, "") and v not in (None, "")}


def service_code_map_out(config: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Local service code -> vendor code, for pushes.

    Falls back to the legacy ``service_code_map`` key, whose values the
    /mapping endpoint always checked against the vendor's own codes -- so they
    are outbound values, whatever the import path once assumed.
    """
    config = config or {}
    explicit = _clean_map(config.get("service_code_map_out"))
    if explicit:
        return explicit
    return _clean_map(config.get("service_code_map"))


def service_code_map_in(config: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Vendor code or name -> local service code, for imports.

    When no inbound map is set, the outbound one is read backwards: a town
    that mapped "Pothole -> PTH" means a PTH record coming back is a pothole.
    Where two local codes share one vendor code the first one wins, which is
    the best a reverse lookup can do and still better than no category.
    """
    config = config or {}
    explicit = _clean_map(config.get("service_code_map_in"))
    if explicit:
        return explicit
    reverse: Dict[str, str] = {}
    for local, vendor in service_code_map_out(config).items():
        reverse.setdefault(vendor, local)
    return reverse


def local_code_for(config: Optional[Dict[str, Any]], *candidates: Optional[str]) -> Optional[str]:
    """The local code an imported record files under, from the vendor's code
    or name, matched exactly first and then case-insensitively."""
    mapping = service_code_map_in(config)
    lowered = {k.strip().lower(): v for k, v in mapping.items()}
    for candidate in candidates:
        if candidate in (None, ""):
            continue
        text = str(candidate)
        if text in mapping:
            return mapping[text]
        if text.strip().lower() in lowered:
            return lowered[text.strip().lower()]
    return None


def normalize_raw_status(value: Any) -> Optional[str]:
    """A vendor status word, compared without case, spacing or underscores.

    "In Progress", "in_progress" and "IN  PROGRESS" are one status. Comparing
    the strings as stored made a vendor that echoes our own word back in a
    different case look like it had changed the record.
    """
    if value is None:
        return None
    text = " ".join(str(value).replace("_", " ").strip().lower().split())
    return text or None


def decide_inbound_status(*, previous_raw: Optional[str], current_raw: Optional[str],
                          inbound_status: Optional[str], local_status: Optional[str],
                          map_in: Callable[[Optional[str]], Optional[str]]) -> Optional[str]:
    """The status to apply to the local request, or None to leave it alone.

    ``previous_raw`` is the vendor status we last saw or last sent
    (``IntegrationLink.external_status``); ``current_raw`` is what the vendor
    reports now; ``inbound_status`` is that mapped into our vocabulary.

    * The vendor has not moved (same raw word as last time): nothing to apply.
      This is the whole clobber fix -- a poll repeating "open" says nothing about
      the "in progress" a staff member set after it.
    * The vendor moved between two words that mean the same thing to us
      ("Submitted" -> "Received"): nothing to apply either. Reading that as
      "open" would downgrade local work through a lossy map.
    * First sighting (no previous word on record): only a forward move is
      applied. Without a baseline there is no telling whether an "open" is a
      reopen or just the vendor's view of a record we have since progressed.
    * Otherwise the vendor genuinely changed the record after our last push,
      and that change is applied -- including a reopen.
    """
    if not inbound_status or inbound_status not in STATUS_RANK:
        return None
    if inbound_status == local_status:
        return None
    current = normalize_raw_status(current_raw if current_raw is not None else inbound_status)
    previous = normalize_raw_status(previous_raw)
    if previous is None:
        if STATUS_RANK[inbound_status] > STATUS_RANK.get(local_status or "open", 0):
            return inbound_status
        return None
    if current == previous:
        return None
    try:
        previous_status = map_in(previous_raw)
    except Exception:
        previous_status = None
    if previous_status == inbound_status:
        return None
    return inbound_status


def clip_external_status(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return str(value)[:EXTERNAL_STATUS_MAX]

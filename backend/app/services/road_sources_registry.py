"""
Road Centerline Source Registry

Provides a state-by-state registry of authoritative road-centerline services so
that a municipality can be seeded with road geometry automatically: a town sets
its boundary, we look up its state, and fetch centerlines from the best source
available for that state.

Roads are used to decide which jurisdiction maintains the road a resident
dropped a pin on, so street NAME and geometry are the only attributes that
really matter here.

Preference order per state:
1. Statewide NG9-1-1 road centerlines (NENA-STA-006 schema). Best available:
   county 911 authorities maintain it continuously because dispatch depends on
   it, and it is usually republished monthly.
2. Statewide centerlines from the state GIS clearinghouse or DOT
   ("All Public Roads", "Street Centerlines") where no NG911 layer is public.
3. Nothing. The fetcher falls back to Census TIGER/Line nationally, which
   always works. A state with no entry here is a perfectly acceptable outcome.

Key features:
- Statewide source per state (embedded data), keyed by two-letter code
- Every entry carries its own provenance: evidence URL + verification date
- Explicit, separate lists for sources that exist but could not be pinned to a
  queryable REST endpoint, so nobody mistakes absence for "does not exist"


========================= COVERAGE SUMMARY (2026-07-29) =========================

Jurisdictions in scope (50 states + DC) ................................... 51
Registry entries (states with a recorded REST endpoint) ................... 14
  DE IA ME MD MA MN NJ NY NC PA TX UT VT VA
  Of those, NENA / NG9-1-1 schema layers .................................. 2   (NJ, NC)
  Of those, custom state DOT / clearinghouse schemas ...................... 12
  Of those, layer ID still unresolved (service root only) ................. 2   (TX, VA)
States with a source known to exist but NO endpoint recorded .............. 7   (AZ AR CT KS MT NH OH)
States whose statewide data is download-only (no REST /query) ............. 3   (RI TN WI)
No entry at all - fall back to TIGER ...................................... 37

The registry deliberately does NOT carry a stub key for all 50 states + DC.
Absence IS the fallback signal: `get_road_source()` resolves any unknown code
to DEFAULT (TIGER), so an empty row would only be a place for a future reader
to mistake "unresearched" for "researched and found nothing". The states in
KNOWN_UNVERIFIED_SOURCES and DOWNLOAD_ONLY_SOURCES record the researched-but-
unusable cases explicitly; anything in neither list simply was not reached
before this pass was time-boxed. `coverage_summary()` reports all of this.

Honest scope note: the 14 registry entries plus the 10 documented non-entries
are the states that were individually researched. The other ~27 were not
examined one-by-one and are TIGER by default rather than by finding. Several
of them almost certainly have good statewide layers.

VERIFICATION CAVEAT - PLEASE READ BEFORE TRUSTING THIS TABLE
    Outbound HTTPS in the environment this registry was compiled in was
    restricted by egress policy to GitHub hosts only; every state GIS host
    (maps.nj.gov, *.arcgis.com, gisservices.its.ny.gov, mdgeodata.md.gov, ...)
    returned 403 at the proxy for both direct requests and page fetches. No
    endpoint below was contacted by this process.

    Every URL here is therefore recorded verbatim from a live web-search index
    entry for that exact REST directory page - in most cases the indexed page
    TITLE is the ArcGIS REST directory's own "Layer: <name> (ID: n)" heading,
    which is strong evidence the layer exists and is named as recorded. No URL
    was constructed, guessed, or extrapolated from a pattern.

    What that means operationally: treat `layer_id` and `field_map` as
    unconfirmed until the fetcher's first successful call. The fetcher MUST
    probe `<service_url>?f=json` and `<url>?f=json` before its first real
    query, and fall back to TIGER on any failure rather than erroring. See
    `verification_gaps()`.

Surprises worth knowing:
- Ohio has no statewide centerline REST service. Its LBRS program is excellent
  but published county-by-county, so Ohio falls back to TIGER.
- Minnesota's statewide layer is compiled from OPT-IN counties only, so it is
  not actually statewide. Coverage must be checked per municipality.
- Massachusetts and Pennsylvania both bake the vintage into the LAYER NAME
  ("Road Inventory 2024", "Pa Local Roads 2026_07"), so layer IDs shift as new
  years are published. Re-resolve by name, not by ID.
- Connecticut, Rhode Island and Tennessee all have first-rate statewide
  datasets that are only offered as downloads or through a portal page that
  never exposes the underlying service URL.
"""

import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


# ============================================================================
# SCHEMA FLAVORS
# ============================================================================
# "nena"   - NENA-STA-006 NG9-1-1 GIS Data Model. Street name is split across
#            standard pre/post directional, type and modifier fields.
# "custom" - State DOT or clearinghouse schema. Field names vary per state and
#            must be resolved against the layer's own metadata.
# "tiger"  - Census TIGER/Line. Single "NAME" / "FULLNAME" string.

# Street-name component fields as specified by NENA-STA-006.1-2018. These are
# the standard names, not names read off any particular layer - a state that
# says it is NENA-compliant should expose these, but confirm against the
# layer's field list on first fetch before relying on them.
NENA_NAME_FIELDS: Dict[str, str] = {
    "pre_directional": "St_PreDir",
    "pre_type": "St_PreTyp",
    "pre_separator": "St_PreSep",
    "base_name": "St_Name",
    "post_type": "St_PosTyp",
    "post_directional": "St_PosDir",
    "post_modifier": "St_PosMod",
}

# When `field_map` is None the fetcher has to discover the name field itself.
# Try these against the layer's field list, in order, case-insensitively; also
# honour the layer's own `displayField`, which is usually correct.
CANDIDATE_NAME_FIELDS: List[str] = [
    "FULLNAME", "FULL_NAME", "COMPLETESTREETNAME", "COMPLETE_STREET_NAME",
    "STREETNAME", "STREET_NAME", "ROADNAME", "ROAD_NAME", "RDNAME",
    "LABEL", "NAME", "ST_NAME", "SRD_NAME", "STREET",
]


# ============================================================================
# STATE ROAD CENTERLINE SOURCES
# ============================================================================
# Per-entry keys:
#   name         - human-readable source/dataset name
#   publisher    - agency that maintains and publishes it
#   service_url  - MapServer/FeatureServer root (enumerate layers here)
#   layer_id     - layer index, or None if not confirmed
#   url          - the layer URL that supports /query, or None if layer_id is
#   schema       - "nena" | "custom" | "tiger"
#   field_map    - street-name component mapping; None = resolve at load time
#   cadence      - publication cadence, only when the publisher states one
#   attribution  - string to display wherever this geometry is shown
#   verified     - date this entry was compiled
#   evidence     - the indexed page the URL was read from verbatim
#   confidence   - "endpoint-indexed" (REST directory page for this exact layer
#                  was in the search index) | "service-indexed" (only the
#                  service root was; layer_id unresolved)
#   notes        - anything the fetcher or a clerk needs to know

STATE_ROAD_SOURCES: Dict[str, Dict[str, Any]] = {
    # ---- Reference entry -------------------------------------------------
    # New Jersey: the statewide NG9-1-1 centerline layer NJOGIS built with
    # county GIS/public-safety agencies and NJDOT. Exceeds NENA 2018
    # (NENA-STA-006.1-2018); republished monthly. Layer 15 in the same service
    # is the Road Name Alias table, which matters for pin-to-road matching
    # because residents use alias names constantly ("Route 1" vs "Trenton Ave").
    "NJ": {
        "name": "Statewide Road Centerlines for New Jersey (Next Generation 9-1-1 Format)",
        "publisher": "NJ Office of Information Technology, Office of GIS (NJOGIS)",
        "service_url": "https://maps.nj.gov/arcgis/rest/services/Framework/Transportation/MapServer",
        "layer_id": 14,
        "url": "https://maps.nj.gov/arcgis/rest/services/Framework/Transportation/MapServer/14",
        "schema": "nena",
        "field_map": NENA_NAME_FIELDS,
        "cadence": "monthly",
        "attribution": "Road centerlines: NJ Office of GIS (NJOGIS), NJGIN Open Data",
        "verified": "2026-07-29",
        "evidence": "https://maps.nj.gov/arcgis/rest/services/Framework/Transportation/MapServer/14",
        "confidence": "endpoint-indexed",
        "notes": (
            "Layer 14 is the current NG911-schema 'Roads' layer; layer 0 in the same "
            "service is the old schema and is marked DEPRECATED - do not use it. "
            "Layer 15 is the Road Name Alias Table. Names are parsed into both the "
            "NG911 8-part and legacy 4-part forms."
        ),
    },

    # ---- Northeast -------------------------------------------------------

    # New York: NYS Streets from the ITS GIS Program Office. Not NG911-schema,
    # but statewide, name-attributed, and refreshed twice a month. The service
    # is scale-tiered: layer 4 is the largest-scale (fullest-detail) tier.
    "NY": {
        "name": "NYS Streets",
        "publisher": "NYS Office of Information Technology Services, GIS Program Office",
        "service_url": "https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Streets/MapServer",
        "layer_id": 4,
        "url": "https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Streets/MapServer/4",
        "schema": "custom",
        "field_map": {"full_name": "CompleteStreetName"},
        "cadence": "second and fourth Friday of each month",
        "attribution": "Road centerlines: NYS ITS GIS Program Office, NYS GIS Clearinghouse",
        "verified": "2026-07-29",
        "evidence": "https://gisservices.its.ny.gov/arcgis/rest/services/NYS_Streets/MapServer/4",
        "confidence": "endpoint-indexed",
        "notes": (
            "Scale-tiered service - layers 4..n are the same streets drawn at coarser "
            "scales. Layer 4 (1:1 to 1:2,200) is the full-detail tier and the only one "
            "worth bulk-querying. displayField is CompleteStreetName. A related alias "
            "table of alternate street names exists in the same service."
        ),
    },

    # Pennsylvania: PennDOT publishes state-maintained and locally-maintained
    # roads as two separate layers. A municipality needs BOTH - most township
    # streets are in the local layer.
    "PA": {
        "name": "PA Local Roads + PA State Roads (PennDOT)",
        "publisher": "PennDOT, served by PASDA (Penn State)",
        "service_url": "https://mapservices.pasda.psu.edu/server/rest/services/pasda/PennDOT/MapServer",
        "layer_id": 3,
        "url": "https://mapservices.pasda.psu.edu/server/rest/services/pasda/PennDOT/MapServer/3",
        "schema": "custom",
        "field_map": None,
        "cadence": "roughly quarterly (layer names carry a YYYY_MM vintage)",
        "attribution": "Road centerlines: PennDOT, distributed by PASDA",
        "verified": "2026-07-29",
        "evidence": "https://mapservices.pasda.psu.edu/server/rest/services/pasda/PennDOT/MapServer/3",
        "confidence": "endpoint-indexed",
        "notes": (
            "TWO layers are needed for full public-road coverage: layer 3 'Pa Local "
            "Roads' (all public roads not maintained by PennDOT) and layer 4 'Pa State "
            "Roads'. Layer names embed the vintage ('Pa Local Roads 2026_07'), so "
            "re-resolve by name prefix rather than trusting the ID across years."
        ),
        "extra_layer_ids": [4],
    },

    # Maryland: MD iMAP publishes a single comprehensive layer covering all
    # public roadways, assembled from FHWA/MDOT SHA/county/municipal sources.
    "MD": {
        "name": "MD iMAP: Maryland Road Centerlines - Comprehensive",
        "publisher": "Maryland Department of Information Technology (MD iMAP) / MDOT SHA",
        "service_url": "https://mdgeodata.md.gov/imap/rest/services/Transportation/MD_RoadCenterlinesComprehensive/MapServer",
        "layer_id": 0,
        "url": "https://mdgeodata.md.gov/imap/rest/services/Transportation/MD_RoadCenterlinesComprehensive/MapServer/0",
        "schema": "custom",
        "field_map": None,
        "cadence": "annual (published for the prior year)",
        "attribution": "Road centerlines: MD iMAP / MDOT SHA, Maryland Department of Information Technology",
        "verified": "2026-07-29",
        "evidence": "https://mdgeodata.md.gov/imap/rest/services/Transportation/MD_RoadCenterlinesComprehensive/MapServer/0",
        "confidence": "endpoint-indexed",
        "notes": (
            "'Comprehensive' is the one to use - it is the street centerline for ALL "
            "public roadways in the state. A separate MD_RoadCenterlines service splits "
            "Interstates / US Routes / Maryland Routes into per-class layers and does "
            "not include local streets in a single layer."
        ),
    },

    # Massachusetts: the MassDOT Road Inventory is the state's authoritative
    # linework - all public and some private roadways.
    "MA": {
        "name": "MassDOT Road Inventory (year-end file)",
        "publisher": "MassDOT Highway Division / MassGIS",
        "service_url": "https://gis.massdot.state.ma.us/arcgis/rest/services/Roads/RoadInventoryYearEndFiles/FeatureServer",
        "layer_id": 10,
        "url": "https://gis.massdot.state.ma.us/arcgis/rest/services/Roads/RoadInventoryYearEndFiles/FeatureServer/10",
        "schema": "custom",
        "field_map": None,
        "cadence": "annual (year-end file)",
        "attribution": "Road centerlines: MassDOT Highway Division / MassGIS",
        "verified": "2026-07-29",
        "evidence": "https://gis.massdot.state.ma.us/arcgis/rest/services/Roads/RoadInventoryYearEndFiles/FeatureServer/10",
        "confidence": "endpoint-indexed",
        "notes": (
            "Layer 10 was 'Road Inventory 2024' when recorded. This service holds one "
            "layer per year, so the ID for the CURRENT year changes annually - always "
            "enumerate the service and pick the highest year rather than pinning 10. "
            "Covers all public and a portion of private roadways."
        ),
    },

    # Maine: MaineDOT public road centerlines, derived from the METRANS LRS.
    "ME": {
        "name": "MaineDOT Public Roads",
        "publisher": "Maine Department of Transportation / Maine GeoLibrary",
        "service_url": "https://gis.maine.gov/arcgis/rest/services/dot/MaineDOT_OpenData/MapServer",
        "layer_id": 52,
        "url": "https://gis.maine.gov/arcgis/rest/services/dot/MaineDOT_OpenData/MapServer/52",
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: MaineDOT, Maine GeoLibrary",
        "verified": "2026-07-29",
        "evidence": "https://gis.maine.gov/arcgis/rest/services/dot/MaineDOT_OpenData/MapServer/52",
        "confidence": "endpoint-indexed",
        "notes": (
            "Public road centerlines built on MaineDOT basemap linework managed in "
            "METRANS (MaineDOT's LRS). Maine also has a separate NG911 road dataset "
            "documented in the GeoLibrary catalog, but no REST endpoint for it could "
            "be pinned - see KNOWN_UNVERIFIED_SOURCES."
        ),
    },

    # Vermont: VTrans is the steward of the E911 road centerline layer that the
    # VT E911 Board maintains as the authoritative road-name source.
    "VT": {
        "name": "VTrans ALL ROADS (E911-derived road centerlines)",
        "publisher": "Vermont Agency of Transportation (VTrans) / VCGI",
        "service_url": "https://maps.vtrans.vermont.gov/arcgis/rest/services/Master/General/FeatureServer",
        "layer_id": 39,
        "url": "https://maps.vtrans.vermont.gov/arcgis/rest/services/Master/General/FeatureServer/39",
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: Vermont Agency of Transportation (VTrans) / VCGI",
        "verified": "2026-07-29",
        "evidence": "https://maps.vtrans.vermont.gov/arcgis/rest/services/Master/General/FeatureServer/39",
        "confidence": "endpoint-indexed",
        "notes": (
            "Lower confidence than the rest of this section: the layer name 'ALL ROADS' "
            "and its URL are confirmed, but that this layer is specifically the E911 "
            "EmergencyE911_RDS lineage is inferred from VTrans being the documented "
            "steward of that layer. Validate feature count and name attribution against "
            "the VCGI 'VT Data - E911 Road Centerlines' open-data item before trusting."
        ),
    },

    # Delaware: FirstMap is the state enterprise GIS; DE_Road_Inventory carries
    # road name plus physical inventory attributes.
    "DE": {
        "name": "DE Road Inventory (FirstMap)",
        "publisher": "Delaware FirstMap / DelDOT",
        "service_url": "https://firstmap.gis.delaware.gov/arcgis/rest/services/Transportation/DE_Road_Inventory/FeatureServer",
        "layer_id": 0,
        "url": "https://firstmap.gis.delaware.gov/arcgis/rest/services/Transportation/DE_Road_Inventory/FeatureServer/0",
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: Delaware FirstMap / DelDOT",
        "verified": "2026-07-29",
        "evidence": "https://firstmap.gis.delaware.gov/arcgis/rest/services/Transportation/DE_Road_Inventory/FeatureServer/0",
        "confidence": "endpoint-indexed",
        "notes": (
            "Road inventory: name, width, lane count, guiderails, etc. Confirm it is "
            "not restricted to state-maintained roads - FirstMap also publishes a "
            "DE_STATE_MAINTAINED_ROADS service, which by name is a narrower subset and "
            "is NOT what we want. Ignore any *.firstmaptest.delaware.gov host that "
            "turns up in search: that is their test tier."
        ),
    },

    # ---- Mid-Atlantic / South --------------------------------------------

    # District of Columbia: DDOT is the sole road authority for the whole
    # District, so its own centerline IS the "statewide" layer.
    "DC": {
        "name": "Street Segment (DDOT LRS Support)",
        "publisher": "District Department of Transportation (DDOT) / DC GIS",
        "service_url": "https://rh.dcgis.dc.gov/dcgis/rest/services/DDOT/LRSSupport/FeatureServer",
        "layer_id": 3,
        "url": "https://rh.dcgis.dc.gov/dcgis/rest/services/DDOT/LRSSupport/FeatureServer/3",
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: District Department of Transportation (DDOT), Open Data DC",
        "verified": "2026-07-29",
        "evidence": "https://rh.dcgis.dc.gov/dcgis/rest/services/DDOT/LRSSupport/FeatureServer/3",
        "confidence": "endpoint-indexed",
        "notes": (
            "The 'rh' host is DDOT's Roads & Highways LRS support service - layer 3 is "
            "'Street Segment'. DC's public-facing 'Roadway Centerlines' product (all "
            "roads AND alleys open to traffic) lives in "
            "maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Transportation_WebMercator/"
            "MapServer, whose root and several unrelated layer IDs (47 National Highway "
            "System, 81 Street Right of Way Polygons) were indexed but whose roadway-block "
            "layer ID was not. If you resolve that ID it is the better source, because it "
            "is the one Open Data DC documents as authoritative."
        ),
    },

    # Georgia: GDOT's statewide LRS network. Georgia also has a strong NG911
    # program, but its road centerlines are provisioned per PSAP, not as one
    # public statewide service.
    "GA": {
        "name": "GDOT Route Network (statewide LRS)",
        "publisher": "Georgia Department of Transportation",
        "service_url": "https://egis.dot.ga.gov/arcgis/rest/services/GDOT_Network/MapServer",
        "layer_id": 0,
        "url": "https://egis.dot.ga.gov/arcgis/rest/services/GDOT_Network/MapServer/0",
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: Georgia Department of Transportation (GDOT)",
        "verified": "2026-07-29",
        "evidence": "https://egis.dot.ga.gov/arcgis/rest/services/GDOT_Network/MapServer/0",
        "confidence": "endpoint-indexed",
        "notes": (
            "Layer 0 is named simply 'GDOT' and is documented as the statewide LRS "
            "network. CHECK COVERAGE BEFORE TRUSTING IT for a city: an LRS network is "
            "sometimes routed state highways only. If local streets are missing, the "
            "next candidate is maps.itos.uga.edu/arcgis/rest/services/FrameWork/"
            "Transportation/MapServer - but its indexed layer 12 is 'Major Roads', which "
            "is explicitly NOT a full centerline layer, so do not substitute it blindly. "
            "Georgia's NG911 road centerlines are a documented statewide framework "
            "dataset but are provisioned through a PSAP-readiness experience app rather "
            "than a public REST layer."
        ),
    },

    # Florida: FLARIS is the FDOT State Safety Office's public network of ALL
    # Florida roadways - state, local and private - used for crash location.
    # That "all roads" scope is exactly what a municipality needs.
    "FL": {
        "name": "FLARIS ARBM Streets",
        "publisher": "FDOT State Safety Office (SSO), FDOT GIS Portal",
        "service_url": "https://gis.fdot.gov/arcgis/rest/services/sso/ssogis_flaris/FeatureServer",
        "layer_id": 5,
        "url": "https://gis.fdot.gov/arcgis/rest/services/sso/ssogis_flaris/FeatureServer/5",
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: Florida Department of Transportation (FDOT) State Safety Office, FLARIS",
        "verified": "2026-07-29",
        "evidence": "https://gis.fdot.gov/arcgis/rest/services/sso/ssogis_flaris/FeatureServer/5",
        "confidence": "endpoint-indexed",
        "notes": (
            "FLARIS is where FDOT SSO publicly shares the roadway/intersection/street "
            "segment network covering STATE, LOCAL AND PRIVATE roads - the widest public "
            "Florida coverage found. Layer 5 'FLARIS ARBM Streets' is the polyline street "
            "network; layer 100820 'FLARIS ARBM Routes' is the route-level polyline and "
            "layers 0/3 are 'FLARIS Intersections'. Do NOT use "
            "gis.fdot.gov/arcgis/rest/services/RCI_Layers/FeatureServer/15 ('State Roads') "
            "- that is state-maintained roads only. Ignore devgis.fdot.gov, their dev tier."
        ),
    },

    # Louisiana: DOTD's Roads & Highways open-data extract. Edited daily and
    # already carries NENA Road Centerline GUIDs, which is a good sign the
    # state's NG911 lineage feeds it.
    "LA": {
        "name": "Louisiana Roadways (Roads and Highways OpenData)",
        "publisher": "Louisiana Department of Transportation & Development (LADOTD)",
        "service_url": "https://maps.dotd.la.gov/road/rest/services/Roads_and_Highways_OpenData/FeatureServer",
        "layer_id": 49,
        "url": "https://maps.dotd.la.gov/road/rest/services/Roads_and_Highways_OpenData/FeatureServer/49",
        "schema": "custom",
        "field_map": None,
        "cadence": "daily (edits appear in the service with about a one-day delay)",
        "attribution": "Road centerlines: Louisiana Department of Transportation & Development (LADOTD)",
        "verified": "2026-07-29",
        "evidence": "https://maps.dotd.la.gov/road/rest/services/Roads_and_Highways_OpenData/FeatureServer/49",
        "confidence": "endpoint-indexed",
        "notes": (
            "Sourced from DOTD's enterprise Roads & Highways LRS. The indexed field list "
            "includes a Road Centerline NENA globally unique identifier alongside DOTD's "
            "own universal unique segment ID, so this is NG911-linked even though the "
            "schema is DOTD's. Freshest cadence of any entry in this registry. A parallel "
            "MapServer exists at the same path if the FeatureServer misbehaves."
        ),
    },

    # Mississippi: MDOT's Linear Referencing Model - state-maintained routes
    # AND local roads in one dataset, served by MARIS at Ole Miss.
    "MS": {
        "name": "MDOT Linear Referencing Model (MS_MDOTLRM_Oct24)",
        "publisher": "Mississippi DOT, served by MARIS (Mississippi Automated Resource Information System)",
        "service_url": "https://gis.mississippi.edu/server/rest/services/Transportation/MS_MDOTLRM_Oct24/MapServer",
        "layer_id": None,
        "url": None,
        "schema": "custom",
        "field_map": None,
        "cadence": "roughly annual (the service name carries an Oct24 vintage)",
        "attribution": "Road centerlines: Mississippi Department of Transportation, distributed by MARIS",
        "verified": "2026-07-29",
        "evidence": "https://gis.mississippi.edu/server/rest/services/Transportation/MS_MDOTLRM_Oct24/MapServer/10/metadata",
        "confidence": "service-indexed",
        "notes": (
            "MARIS documents the MDOT LRM as a complete dataset of roads in Mississippi "
            "containing state-maintained routes AS WELL AS local roads, including ramps, "
            "frontage roads and cross-overs. Layer ID NOT confirmed - the metadata page "
            "for layer 10 is what turned up, but nothing said layer 10 is the centerline "
            "layer, so enumerate. VINTAGE IS IN THE SERVICE NAME: re-resolve the folder "
            "listing under Transportation/ and prefer the newest MS_MDOTLRM_* service. "
            "Two stale alternatives to avoid: MS_MDEMRoadSegments_2012 (2012) and "
            "arcsrv.mfc.ms.gov Hosted/MS_MDOT_Centerlines (a Nov2022 copy on the "
            "Forestry Commission's server)."
        ),
    },

    # Virginia: VBMP Road Centerline File, maintained jointly by local
    # governments, VDOT and VGIN. Extracted and redistributed quarterly.
    "VA": {
        "name": "VBMP Road Centerlines (RCL)",
        "publisher": "Virginia Geographic Information Network (VGIN), VDEM",
        "service_url": "https://vginmaps.vdem.virginia.gov/arcgis/rest/services/VA_Base_Layers/VBMP_RCL/FeatureServer",
        "layer_id": None,
        "url": None,
        "schema": "custom",
        "field_map": None,
        "cadence": "quarterly",
        "attribution": "Road centerlines: Virginia Geographic Information Network (VGIN), VBMP",
        "verified": "2026-07-29",
        "evidence": "https://vginmaps.vdem.virginia.gov/arcgis/rest/services/VA_Base_Layers/VBMP_RCL/FeatureServer",
        "confidence": "service-indexed",
        "notes": (
            "Service root confirmed and documented as public (no credentials). Layer ID "
            "NOT confirmed - enumerate the FeatureServer and pick the polyline "
            "centerline layer. Statewide, seamless, with address, road name and state "
            "route number attribution. A parallel host gismaps.vdem.virginia.gov serves "
            "the same VA_Base_Layers/VBMP_RCL path if vginmaps is unreachable."
        ),
    },

    # North Carolina: NC OneMap serves the actual NG911 call-routing
    # centerlines - the NENA RoadCenterlineLine layer, aggregated by the state
    # from local GIS authorities.
    "NC": {
        "name": "NG911 Centerlines (NC1Map_Transportation)",
        "publisher": "NC Department of Information Technology / NC OneMap",
        "service_url": "https://services.gis.nc.gov/secure/rest/services/NC1Map_Transportation/MapServer",
        "layer_id": 0,
        "url": "https://services.gis.nc.gov/secure/rest/services/NC1Map_Transportation/MapServer/0",
        "schema": "nena",
        "field_map": NENA_NAME_FIELDS,
        "cadence": None,
        "attribution": "Road centerlines: NC OneMap, NC Department of Information Technology",
        "verified": "2026-07-29",
        "evidence": "https://services.gis.nc.gov/secure/rest/services/NC1Map_Transportation/MapServer/0",
        "confidence": "endpoint-indexed",
        "notes": (
            "The NENA-STA-010 RoadCenterlineLine layer used for NG911 call routing and "
            "location validation; carries full road-name elements, L/R address ranges "
            "with parity, directionality and jurisdiction. Despite the '/secure/' path "
            "segment these NC OneMap services are publicly readable - that is just how "
            "the folder is named. A mirror exists at "
            "services.nconemap.gov/secure/rest/services/NC1Map_Transportation/FeatureServer."
        ),
    },

    # Texas: TxDOT's statewide GIS roadway network.
    "TX": {
        "name": "TxDOT Roadways",
        "publisher": "Texas Department of Transportation",
        "service_url": "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_Roadways/FeatureServer",
        "layer_id": None,
        "url": None,
        "schema": "custom",
        "field_map": None,
        "cadence": "annual (Roadway Inventory product)",
        "attribution": "Road centerlines: Texas Department of Transportation (TxDOT)",
        "verified": "2026-07-29",
        "evidence": "https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_Roadways/FeatureServer",
        "confidence": "service-indexed",
        "notes": (
            "Service root confirmed on TxDOT's AGOL org. Layer ID not confirmed - "
            "enumerate. Note the on-system/off-system split in TxDOT products: confirm "
            "the chosen layer includes off-system (city and county) roads, or municipal "
            "streets will be missing entirely."
        ),
    },

    # ---- Midwest / Mountain West -----------------------------------------

    # Utah: UGRC maintains Utah Roads with local governments, the Utah 911
    # Committee and UDOT. Monthly refresh for the populous counties.
    "UT": {
        "name": "Utah Roads (SGID)",
        "publisher": "Utah Geospatial Resource Center (UGRC), SGID",
        "service_url": "https://services1.arcgis.com/99lidPhWCzftIe9K/ArcGIS/rest/services/UtahRoads/FeatureServer",
        "layer_id": 0,
        "url": "https://services1.arcgis.com/99lidPhWCzftIe9K/ArcGIS/rest/services/UtahRoads/FeatureServer/0",
        "schema": "custom",
        "field_map": None,
        "cadence": "monthly (Davis, Salt Lake, Utah, Washington, Weber every month; other counties on an annual schedule)",
        "attribution": "Road centerlines: Utah Geospatial Resource Center (UGRC), SGID - CC BY 4.0",
        "verified": "2026-07-29",
        "evidence": "https://services1.arcgis.com/99lidPhWCzftIe9K/ArcGIS/rest/services/UtahRoads/FeatureServer/0",
        "confidence": "endpoint-indexed",
        "notes": (
            "Multi-purpose statewide roads layer for cartography, routing and "
            "range-based address location; co-maintained with the Utah 911 Committee, "
            "so it is NG911-adjacent even though the schema is UGRC's own. UGRC's "
            "org-wide default license is CC BY 4.0 - attribution is required."
        ),
    },

    # Minnesota: MnGeo compiles county open data into one statewide-schema
    # layer. Read the coverage caveat - this is opt-in, not complete.
    "MN": {
        "name": "Road Centerlines, Compiled from Opt-In Open Data Counties",
        "publisher": "Minnesota Geospatial Information Office (MnGeo)",
        "service_url": "https://enterprise.gisdata.mn.gov/aghost/rest/services/us_mn_state_mngeo/trans_road_centerlines_open/FeatureServer",
        "layer_id": 0,
        "url": "https://enterprise.gisdata.mn.gov/aghost/rest/services/us_mn_state_mngeo/trans_road_centerlines_open/FeatureServer/0",
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: Minnesota Geospatial Information Office (MnGeo), Minnesota Geospatial Commons",
        "verified": "2026-07-29",
        "evidence": "https://enterprise.gisdata.mn.gov/aghost/rest/services/us_mn_state_mngeo/trans_road_centerlines_open/FeatureServer/layers",
        "confidence": "endpoint-indexed",
        "notes": (
            "COVERAGE CAVEAT: compiled only from counties that opted in to publishing "
            "open data, so it is NOT complete statewide coverage. Before seeding a "
            "Minnesota town, check whether its county is represented; if the boundary "
            "query returns nothing, fall back to TIGER rather than seeding an empty "
            "road table. Conformed by MnGeo to the GAC road centerline attribute "
            "schema and reprojected to UTM Zone 15."
        ),
    },

    # Iowa: the RAMS road network covers every route class including municipal.
    "IA": {
        "name": "RAMS Road Network",
        "publisher": "Iowa Department of Transportation",
        "service_url": "https://gis.iowadot.gov/agshost/rest/services/RAMS/Road_Network/FeatureServer",
        "layer_id": 0,
        "url": "https://gis.iowadot.gov/agshost/rest/services/RAMS/Road_Network/FeatureServer/0",
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: Iowa Department of Transportation (RAMS)",
        "verified": "2026-07-29",
        "evidence": "https://gis.iowadot.gov/agshost/rest/services/RAMS/Road_Network/FeatureServer/0",
        "confidence": "endpoint-indexed",
        "notes": (
            "Covers all routes in Iowa - Federal, State, County, Municipal, "
            "Institutional and Ramp systems - maintained in Iowa DOT's Roadway Asset "
            "Management System. Good jurisdiction attribution, which is exactly what "
            "pin-to-maintainer routing needs."
        ),
    },

    # Michigan: the Michigan Geographic Framework is the state's base map and
    # its "All Roads" layer is the statewide centerline.
    "MI": {
        "name": "All Roads (Michigan Geographic Framework)",
        "publisher": "State of Michigan, Center for Shared Solutions (MGF / MCGI)",
        "service_url": "https://gisagocss.state.mi.us/arcgis/rest/services/OpenData/michigan_geographic_framework/MapServer",
        "layer_id": 20,
        "url": "https://gisagocss.state.mi.us/arcgis/rest/services/OpenData/michigan_geographic_framework/MapServer/20",
        "schema": "custom",
        "field_map": None,
        "cadence": "versioned releases (the open-data item was 'All Roads (v17a)')",
        "attribution": "Road centerlines: Michigan Geographic Framework, MI Center for Shared Solutions",
        "verified": "2026-07-29",
        "evidence": "https://gisagocss.state.mi.us/arcgis/rest/services/OpenData/michigan_geographic_framework/MapServer/20",
        "confidence": "endpoint-indexed",
        "notes": (
            "Layer 20 is 'All Roads'. Layer 8 in the same service is 'State Owned Roads' "
            "- a narrower subset, NOT what we want. Layer 6 is the MGF Base. Two hosts "
            "serve the identical path, gisagocss.state.mi.us and gisago.mcgi.state.mi.us; "
            "both were indexed, either will do. The MGF is built from TIGER/Line plus "
            "MDNR MIRIS linework plus MDOT's Michigan Accident Location Index LRS, so it "
            "is meaningfully better than TIGER alone but shares some of its lineage. "
            "Version is baked into the DATASET name (v17a), not the layer ID."
        ),
    },

    # Indiana: IGIO harvests county-maintained centerlines annually into one
    # statewide layer. There is a stable "Current" alias service.
    "IN": {
        "name": "Road Centerlines of Indiana (Current)",
        "publisher": "Indiana Geographic Information Office (IGIO) / IndianaMap",
        "service_url": "https://gisdata.in.gov/server/rest/services/Hosted/Road_Centerlines_of_Indiana_Current/FeatureServer",
        "layer_id": 0,
        "url": "https://gisdata.in.gov/server/rest/services/Hosted/Road_Centerlines_of_Indiana_Current/FeatureServer/0",
        "schema": "custom",
        "field_map": None,
        "cadence": "annual (GIS Data Harvest Initiative, released around 31 December)",
        "attribution": "Road centerlines: Indiana Geographic Information Office (IGIO), IndianaMap",
        "verified": "2026-07-29",
        "evidence": "https://gisdata.in.gov/server/rest/services/Hosted/Road_Centerlines_of_Indiana_Current/FeatureServer/0/metadata",
        "confidence": "endpoint-indexed",
        "notes": (
            "Compiled from centerlines maintained by COUNTY agencies, so quality varies "
            "by county but coverage is genuinely statewide. Prefer the '_Current' service "
            "recorded here over the year-stamped siblings - IGIO also publishes "
            "Road_Centerlines_of_Indiana_2025 / _2023 and Street_Centerlines_of_Indiana_2022 "
            "as frozen vintages, and '_Current' is the alias that keeps moving. If "
            "'_Current' ever lags, the newest year-stamped service is the fallback. "
            "INDOT separately publishes its own centerlines on gis.indot.in.gov, but that "
            "is a DOT basemap product, not the county-maintained harvest."
        ),
    },

    # North Dakota: the ND GIS Hub serves one combined transportation service
    # spanning local, state and federal roads.
    "ND": {
        "name": "All_Transportation (ND GIS Hub)",
        "publisher": "North Dakota GIS Hub / NDDOT",
        "service_url": "https://ndgishub.nd.gov/ArcGIS/rest/services/All_Transportation/MapServer",
        "layer_id": None,
        "url": None,
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: North Dakota GIS Hub / NDDOT",
        "verified": "2026-07-29",
        "evidence": "https://ndgishub.nd.gov/ArcGIS/rest/services/All_Transportation/MapServer",
        "confidence": "service-indexed",
        "notes": (
            "Documented as covering local, state AND federal roads plus railroads, "
            "airports, scenic byways and snowmobile trails - so this service is a mixed "
            "bag and the roads layer must be picked out by name. Layer ID not confirmed. "
            "Do not use gis.dot.nd.gov external/rcrs_dynamic: that is the NDDOT Travel "
            "Map (road conditions), not a centerline layer."
        ),
    },

    # South Dakota: the state enterprise server carries a Transportation_Roads
    # service; layer 0 is the only layer that turned up.
    "SD": {
        "name": "SD_All / Transportation_Roads",
        "publisher": "State of South Dakota (BIT) enterprise GIS",
        "service_url": "https://arcgis.sd.gov/arcgis/rest/services/SD_All/Transportation_Roads/MapServer",
        "layer_id": 0,
        "url": "https://arcgis.sd.gov/arcgis/rest/services/SD_All/Transportation_Roads/MapServer/0",
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: State of South Dakota enterprise GIS",
        "verified": "2026-07-29",
        "evidence": "https://arcgis.sd.gov/arcgis/rest/services/SD_All/Transportation_Roads/MapServer/0?f=pjson",
        "confidence": "endpoint-indexed",
        "notes": (
            "WEAKER EVIDENCE THAN THE OTHER endpoint-indexed ENTRIES: what was indexed is "
            "the ?f=pjson form of layer 0, so the layer resource demonstrably exists at "
            "id 0, but its NAME was never seen - only the service name "
            "'Transportation_Roads' implies it is the roads layer. Verify the layer name "
            "and that it is statewide (SD's statewide roads lineage is the NSTRI "
            "compilation of county coverages) before seeding from it; the service is old "
            "(ArcGIS 10.71) and may predate current county linework."
        ),
    },

    # Colorado: CDOT splits state highways from locally-jurisdiction roads
    # across different services. A municipality needs the LOCAL one.
    "CO": {
        "name": "CDOT Local Roads (HUTF service)",
        "publisher": "Colorado Department of Transportation (CDOT)",
        "service_url": "https://dtdapps.colorado.gov/server/rest/services/HUTF/HUTF2/MapServer",
        "layer_id": None,
        "url": None,
        "schema": "custom",
        "field_map": {"full_name": "ROUTENAME"},
        "cadence": None,
        "attribution": "Road centerlines: Colorado Department of Transportation (CDOT)",
        "verified": "2026-07-29",
        "evidence": "https://dtdapps.colorado.gov/server/rest/services/HUTF/HUTF2/MapServer/layers?f=pjson",
        "confidence": "service-indexed",
        "notes": (
            "The service's layer listing was indexed and shows a 'LocalRoads' polyline "
            "layer whose fields include OBJECTID, GIS_ID, FIPS, ROUTE, SEGMID and "
            "ROUTENAME - field_map here is read off THAT listing, not assumed. Layer ID "
            "was not in the indexed excerpt, so enumerate and match on the name "
            "'LocalRoads'. Colorado needs TWO sources for full coverage: this for locally "
            "-classified roads, and CDOT Highways at "
            "dtdapps.coloradodot.info/arcgis/rest/services/CPLAN/HighwaySegments/MapServer/1 "
            "for state highways. The CDOT open-data 'Local Roads' item is functionally "
            "classified LOCAL roads only, so collectors and minor arterials inside a city "
            "may be in the highway service instead. Also note CDOT runs two hostnames "
            "(dtdapps.colorado.gov and dtdapps.coloradodot.info) with different content."
        ),
    },

    # Idaho: ITD runs ArcGIS Roads and Highways; its open-data mirror carries
    # an "All Idaho Road" layer covering the whole LRS.
    "ID": {
        "name": "Idaho Transportation Layers For Open Data ('All Idaho Road')",
        "publisher": "Idaho Transportation Department (ITD)",
        "service_url": "https://gis.itd.idaho.gov/arcgisprod/rest/services/ArcGISOnline/IdahoTransportationLayersForOpenData/MapServer",
        "layer_id": None,
        "url": None,
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: Idaho Transportation Department (ITD)",
        "verified": "2026-07-29",
        "evidence": "https://gis.itd.idaho.gov/arcgisprod/rest/services/ArcGISOnline/IdahoTransportationLayersForOpenData/MapServer",
        "confidence": "service-indexed",
        "notes": (
            "ITD moved to ArcGIS Roads and Highways in 2018; the layer to look for is "
            "named 'All Idaho Road' and is documented as all road centerlines in the ITD "
            "LRS. Layer ID unconfirmed - the only IDs indexed in this service were 131 "
            "'State Highway System (LRS)', which is a NARROWER subset and must not be "
            "substituted, and 12 'State Highway' in the sibling TransportationLayers "
            "service. Enumerate and match by name."
        ),
    },

    # Nevada: NDOT's ALRS extract. Weekly refresh, which is unusually good.
    "NV": {
        "name": "ALRS_Download (NDOT statewide routes)",
        "publisher": "Nevada Department of Transportation, Roadway Systems Division",
        "service_url": "https://gis.dot.nv.gov/arcgis/rest/services/ArcGISOnline/ALRS_Download/MapServer",
        "layer_id": None,
        "url": None,
        "schema": "custom",
        "field_map": None,
        "cadence": "weekly, Tuesdays",
        "attribution": "Road centerlines: Nevada Department of Transportation (NDOT)",
        "verified": "2026-07-29",
        "evidence": "https://gis.dot.nv.gov/arcgis/rest/services/ArcGISOnline/ALRS_Download/MapServer",
        "confidence": "service-indexed",
        "notes": (
            "Publishes statewide routes, street name and mileposts extracted from NDOT's "
            "Roads and Highways geodatabase. COVERAGE RISK: the NevadaRoutes dataset it "
            "derives from is described as all STATE, FEDERAL AND COUNTY roads - city "
            "streets are not named in that description, so check a municipality before "
            "relying on it. An alternative that explicitly claims 'local, county and "
            "state managed roads' is NDOT_Roads at "
            "arcgis.water.nv.gov/arcgis/rest/services/BaseLayers/NDOT_Roads/MapServer, "
            "but that is a copy republished on the Division of Water Resources' server, "
            "so treat it as a fallback rather than the source of truth."
        ),
    },

    # New Mexico: the real thing - NG911 centerlines consolidated MONTHLY by
    # EDAC at UNM from 80+ local data providers.
    "NM": {
        "name": "NM911 Road Centerlines",
        "publisher": "NM911 Program / Earth Data Analysis Center (EDAC), University of New Mexico",
        "service_url": "https://services.arcgis.com/hOpd7wfnKm16p9D9/ArcGIS/rest/services/NM911_Road_Centerlines/FeatureServer",
        "layer_id": None,
        "url": None,
        "schema": "nena",
        "field_map": None,
        "cadence": "monthly",
        "attribution": "Road centerlines: NM911 Program / EDAC, University of New Mexico",
        "verified": "2026-07-29",
        "evidence": "https://services.arcgis.com/hOpd7wfnKm16p9D9/ArcGIS/rest/services/NM911_Road_Centerlines/FeatureServer",
        "confidence": "service-indexed",
        "notes": (
            "Best-in-class provenance: EDAC consolidates local-government contributions "
            "from 80+ providers every month for the NM911 Program. Layer ID not confirmed "
            "- enumerate. field_map deliberately left None: the dataset is NG911 by "
            "purpose, but nothing indexed showed its field list, and an aggregation of 80 "
            "contributors may or may not have been conformed to literal NENA-STA-006 "
            "field names. Resolve names off the layer, not off NENA_NAME_FIELDS."
        ),
    },

    # ---- West / Pacific ---------------------------------------------------

    # California: Caltrans' ARNOLD submission - the LRS network of ALL public
    # roads in the state, not just the State Highway Network.
    "CA": {
        "name": "Caltrans All Roads (LRSN_AllRoads)",
        "publisher": "California Department of Transportation (Caltrans)",
        "service_url": "https://caltrans-gis.dot.ca.gov/arcgis/rest/services/CHhighway/All_Roads/FeatureServer",
        "layer_id": 0,
        "url": "https://caltrans-gis.dot.ca.gov/arcgis/rest/services/CHhighway/All_Roads/FeatureServer/0",
        "schema": "custom",
        "field_map": None,
        "cadence": "annual (tracks the federal HPMS submittal cycle)",
        "attribution": "Road centerlines: California Department of Transportation (Caltrans)",
        "verified": "2026-07-29",
        "evidence": "https://caltrans-gis.dot.ca.gov/arcgis/rest/services/CHhighway/All_Roads/FeatureServer/0/metadata",
        "confidence": "endpoint-indexed",
        "notes": (
            "LRSN_AllRoads is an Esri Roads and Highways network representing ALL PUBLIC "
            "ROADS in California including state highways - it is Caltrans' ARNOLD "
            "deliverable for HPMS. Do NOT substitute CHhighway/... State Highway Network "
            "or the 'State Highway Network Lines' open-data item: those are state "
            "highways only and a city would get almost nothing. Because this is an LRS "
            "built for federal reporting rather than for addressing, expect route-level "
            "naming (route/postmile) and verify that a usable local STREET NAME field "
            "exists before seeding - if it does not, TIGER may actually name streets "
            "better even though its geometry is worse. gisdata.dot.ca.gov mirrors the "
            "same CHhighway/All_Roads path."
        ),
    },

    # Oregon: ODOT's TransGIS catalog exposes an explicit "All Public Roads"
    # layer, the service form of the OR-Trans statewide compilation.
    "OR": {
        "name": "All Public Roads (ODOT TransGIS catalog)",
        "publisher": "Oregon Department of Transportation, GIS Unit",
        "service_url": "https://gis.odot.state.or.us/arcgis1006/rest/services/transgis/catalog/MapServer",
        "layer_id": 164,
        "url": "https://gis.odot.state.or.us/arcgis1006/rest/services/transgis/catalog/MapServer/164",
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: Oregon Department of Transportation (ODOT), TransGIS",
        "verified": "2026-07-29",
        "evidence": "https://gis.odot.state.or.us/arcgis1006/rest/services/transgis/catalog/MapServer/164",
        "confidence": "endpoint-indexed",
        "notes": (
            "Layer 164 'All Public Roads' is a polyline layer in ODOT's TransGIS PROD "
            "data catalog. Two sibling layers in the SAME service are narrower and must "
            "not be swapped in: 169 'Highway Network' and 10 'Road Network'. This is a "
            "single huge catalog service (200+ layers), so IDs plausibly shift between "
            "releases - re-resolve by layer name. Oregon's underlying statewide "
            "compilation is OR-Trans, published on Oregon GEOHub as 'Road Centerlines' / "
            "'All Public Roads'; the GEOHub items never exposed a service URL, so the "
            "TransGIS catalog is the queryable route in. Note the 'arcgis1006' path "
            "segment is a server-version marker and will change when ODOT upgrades."
        ),
    },

    # Washington: WSDOT splits state routes from local agency roads. For a
    # city, the LOCAL AGENCY layer is the one that matters.
    "WA": {
        "name": "Local Agency Public Road - Line",
        "publisher": "WSDOT Transportation Data, GIS & Modeling Office",
        "service_url": "https://data.wsdot.wa.gov/arcgis/rest/services/Shared/LocalAgencyPublicRoadData/FeatureServer",
        "layer_id": 0,
        "url": "https://data.wsdot.wa.gov/arcgis/rest/services/Shared/LocalAgencyPublicRoadData/FeatureServer/0",
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: WSDOT Transportation Data, GIS & Modeling Office",
        "verified": "2026-07-29",
        "evidence": "https://data.wsdot.wa.gov/arcgis/rest/services/Shared/LocalAgencyPublicRoadData/FeatureServer/0",
        "confidence": "endpoint-indexed",
        "notes": (
            "LAPR = county roads and city streets, plus some private roads included for "
            "network connectivity - i.e. exactly the municipal streets a 311 system "
            "cares about, but NOT state routes. For state routes too, either add "
            "Shared/LRSData/MapServer (its layer 10 is the same 'Local Agency Public Road "
            "- Line', which is a useful cross-check) or Shared/WSDOTPublicRoads/MapServer, "
            "which is documented as depicting state routes AND local agency public roads "
            "together but whose layer IDs were never indexed."
        ),
    },

    # Alaska: DOT&PF's route data service. Statewide by definition, though
    # Alaska's road network is tiny relative to its area.
    "AK": {
        "name": "AKDOT&PF Route Data (centerlines)",
        "publisher": "Alaska DOT&PF, Transportation Data Services Section",
        "service_url": "http://www.dot.state.ak.us/ArcGIS/rest/services/AKDOT_Route_Data/MapServer",
        "layer_id": None,
        "url": None,
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: Alaska Department of Transportation & Public Facilities (DOT&PF)",
        "verified": "2026-07-29",
        "evidence": "http://www.dot.state.ak.us/ArcGIS/rest/services/AKDOT_Route_Data/MapServer",
        "confidence": "service-indexed",
        "notes": (
            "HTTP, NOT HTTPS - the service root was indexed on plain http, and the "
            "fetcher should try https first and only fall back if DOT&PF genuinely has "
            "no TLS listener. The service bundles centerlines, intersections, bridges "
            "and mileposts, described as a linear centerline representation of all "
            "routes in the state in linear-referencing format. Layer ID unconfirmed: the "
            "AKDOT ArcGIS Hub item for 'Road Centerlines' deep-links with layer=20, which "
            "is a strong hint but is a Hub parameter, not this service's directory page - "
            "enumerate rather than trusting 20."
        ),
    },

    # Hawaii: the statewide GIS program publishes roads PER ISLAND, not as one
    # merged statewide layer. Read the note before using this.
    "HI": {
        "name": "Hawaii Statewide GIS Transportation (per-island road layers)",
        "publisher": "Hawaii Statewide GIS Program, Office of Planning and Sustainable Development",
        "service_url": "https://geodata.hawaii.gov/arcgis/rest/services/Transportation/MapServer",
        "layer_id": None,
        "url": None,
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: Hawaii Statewide GIS Program, Office of Planning and Sustainable Development",
        "verified": "2026-07-29",
        "evidence": "https://geodata.hawaii.gov/arcgis/rest/services/Transportation/MapServer/3",
        "confidence": "service-indexed",
        "notes": (
            "THERE IS NO SINGLE STATEWIDE ROADS LAYER. This service holds one roads layer "
            "PER ISLAND/COUNTY. Two were indexed by name: layer 3 'Oahu Roads' (the Oahu "
            "street network, non-military and military) and layer 4 'Kauai Roads' (Kauai "
            "centerlines as of November 2023). Maui and Hawaii County equivalents exist "
            "as open-data items but their layer IDs were not indexed, so layer_id is left "
            "None: the fetcher must enumerate and pick the layer matching the town's "
            "county. Do NOT grab layers 12 or 15 - those are HPMS Roads and HPMS 2012, "
            "federal reporting extracts, and 15 is a stale 2012 vintage."
        ),
    },

    # West Virginia: WVDOT's geospatial portal serves a Transportation service.
    "WV": {
        "name": "WVDOT Transportation (statewide roads)",
        "publisher": "West Virginia DOT, LRS Service Unit / WV GIS Technical Center",
        "service_url": "https://gis.transportation.wv.gov/arcgis/rest/services/Transportation/MapServer",
        "layer_id": None,
        "url": None,
        "schema": "custom",
        "field_map": None,
        "cadence": None,
        "attribution": "Road centerlines: West Virginia Department of Transportation (WVDOT)",
        "verified": "2026-07-29",
        "evidence": "https://gis.transportation.wv.gov/arcgis/rest/services/Transportation/MapServer",
        "confidence": "service-indexed",
        "notes": (
            "Only the service ROOT was indexed and no layer inside it was ever named, so "
            "this entry asserts less than most: WVDOT runs a Transportation map service "
            "on its geospatial portal, and WVDOT's LRS Service Unit maintains statewide "
            "road data. Whether this particular service carries a full public-road "
            "centerline layer is unverified - enumerate it, and if it turns out to be "
            "state-maintained routes only, DELETE THIS ENTRY so WV falls back to TIGER. "
            "Other routes worth trying: the WVDOT Open Data Portal at "
            "data-wvdot.opendata.arcgis.com and the WV GIS Technical Center's services "
            "at services.wvgis.wvu.edu."
        ),
    },

    # ---- National fallback -----------------------------------------------
    # Always available, always mediocre. Census TIGER/Line road features are
    # positionally loose and updated once a year, but they exist for every
    # county in the country, which is the whole point.
    "DEFAULT": {
        "name": "Census TIGERweb Transportation - Local Roads",
        "publisher": "US Census Bureau",
        "service_url": "https://tigerweb.geo.census.gov/arcgis/rest/services/Census2020/Transportation/MapServer",
        "layer_id": 8,
        "url": "https://tigerweb.geo.census.gov/arcgis/rest/services/Census2020/Transportation/MapServer/8",
        "schema": "tiger",
        "field_map": {"full_name": "NAME"},
        "cadence": "annual",
        "attribution": "Road centerlines: US Census Bureau TIGER/Line",
        "verified": "2026-07-29",
        "evidence": "https://tigerweb.geo.census.gov/arcgis/rest/services/Census2020/Transportation/MapServer/8",
        "confidence": "endpoint-indexed",
        "notes": (
            "Layer 8 is Local Roads; the same service carries Primary Roads and "
            "Secondary Roads in separate layers, so a full municipal pull needs all "
            "three. The 'Census2020' folder is a fixed vintage - enumerate "
            "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb and prefer "
            "the newest published vintage folder when one exists."
        ),
        "extra_layer_ids": [6, 7],
    },
}


# ============================================================================
# KNOWN TO EXIST, ENDPOINT UNVERIFIED
# ============================================================================
# These states demonstrably have a statewide centerline program. We could not
# pin a queryable REST layer URL to it and will not guess one, so they fall
# back to TIGER until somebody with unrestricted network access resolves the
# endpoint. Each carries the evidence that the dataset exists.

KNOWN_UNVERIFIED_SOURCES: Dict[str, Dict[str, Any]] = {
    "CT": {
        "dataset": "CTDOT State Routes and Local Roads",
        "publisher": "CTDOT Bureau of Policy & Planning, Roadway Inventory Unit",
        "cadence": "annual snapshot",
        "evidence": "https://connecticut-ctdot.opendata.arcgis.com/maps/CTDOT::ctdot-state-routes-and-local-roads",
        "why_unresolved": (
            "Annual snapshot of the full public road network as defined by FHWA, "
            "published on the CTDOT ArcGIS Hub. Every route to the underlying hosted "
            "feature service went through Hub pages that do not expose the service URL "
            "in indexed content. Resolve via the Hub item's /api tab."
        ),
    },
    "NH": {
        "dataset": "NH DOT Roads",
        "publisher": "NHDOT / NH GRANIT (UNH)",
        "cadence": None,
        "evidence": "https://www.nhgeodata.unh.edu/datasets/NHGRANIT::nh-dot-roads/about",
        "why_unresolved": (
            "Statewide layer of state, local and selected private roads with names and "
            "administrative attributes. GRANIT documents GeoServices/WMS/WFS API links "
            "but the FeatureServer URL never appeared in indexed content."
        ),
    },
    "OH": {
        "dataset": "LBRS (Location Based Response System) centerlines",
        "publisher": "OGRIP / ODOT, published per county",
        "cadence": None,
        "evidence": "https://ogrip-geohio.opendata.arcgis.com/",
        "why_unresolved": (
            "Ohio's centerlines are excellent but the LBRS program is published "
            "COUNTY BY COUNTY (Franklin, Lorain, MORPC, etc. each run their own "
            "service). No single statewide REST layer was found. Ohio should use TIGER "
            "unless and until a per-county source table is added."
        ),
    },
    "AR": {
        "dataset": "Arkansas Centerline File (ACF)",
        "publisher": "Arkansas GIS Office",
        "cadence": None,
        "evidence": "https://gis.arkansas.gov/programs/arkansas-centerline-file-acf/",
        "why_unresolved": (
            "Standardized statewide centerline layer distributed free through the "
            "Arkansas Spatial Data Infrastructure. Only application services "
            "(Apps/RapidDeploy, Apps/NG911_Boundaries_Comment) surfaced on "
            "gis.arkansas.gov; neither is the ACF centerline layer itself."
        ),
    },
    "KS": {
        "dataset": "Kansas NG9-1-1 road centerlines",
        "publisher": "Kansas 911 Coordinating Council / KSDOT / DASC",
        "cadence": None,
        "evidence": "https://kansas911.org/wp-content/uploads/2017/07/Kansas_NG911_GIS_Data_Model_v2_0_Final.pdf",
        "why_unresolved": (
            "Kansas has a published NG9-1-1 GIS Data Model and a composite geocoding "
            "service built on NG911 address points and centerlines, so the layer "
            "certainly exists. The centerline feature service URL was not indexed."
        ),
    },
    "MT": {
        "dataset": "Statewide Roads",
        "publisher": "Montana DNRC / Montana State Library",
        "cadence": None,
        "evidence": "https://gis.dnrc.mt.gov/arcgis/rest/services/DNRALL/Statewide_Roads/FeatureServer/2/iteminfo",
        "why_unresolved": (
            "A 'Statewide_Roads' FeatureServer exists on the DNRC server and layer 2 is "
            "indexed, but nothing confirms what layer 2 contains or whether DNRC (a "
            "natural-resources agency) is the authoritative publisher for road names. "
            "Not promoted to the registry on that basis alone."
        ),
    },
    "ME_NG911": {
        "dataset": "Maine NG911 Road Data (ng911rdss)",
        "publisher": "Maine GeoLibrary / Maine Emergency Services Communication Bureau",
        "cadence": None,
        "evidence": "https://www1.maine.gov/geolib/catalog/metadata/ng911rdss.html",
        "why_unresolved": (
            "Maine has a distinct NG911 road dataset catalogued separately from "
            "MaineDOT Public Roads. If its endpoint is resolved it should REPLACE the "
            "ME registry entry, since NG911 outranks a DOT layer in our preference "
            "order. Keyed oddly here because ME already has a registry entry."
        ),
    },
    "AZ": {
        "dataset": "Road Centerline NG911",
        "publisher": "Arizona State Land Department / AZGeo",
        "cadence": None,
        "evidence": "https://azgeo-open-data-agic.hub.arcgis.com/datasets/463d126960b84eea8be254fa82a7b250",
        "why_unresolved": (
            "AZGeo publishes it explicitly as a 'Downloadable Dataset', which suggests "
            "file distribution rather than a live service. Listed here rather than in "
            "DOWNLOAD_ONLY_SOURCES because a backing hosted service may well exist."
        ),
    },
}


# ============================================================================
# DOWNLOAD-ONLY STATEWIDE SOURCES
# ============================================================================
# Statewide centerlines that are published only as shapefile / file
# geodatabase downloads, with no queryable REST service. The fetcher needs a
# REST endpoint, so these states fall back to TIGER for now. They are the best
# candidates for a future "download, extract, load" ingestion path, since the
# data quality is generally far better than TIGER.

DOWNLOAD_ONLY_SOURCES: Dict[str, Dict[str, Any]] = {
    "RI": {
        "dataset": "RI E-911 Road Centerlines",
        "publisher": "RIDOT / RI E-911 Emergency Telephone System, via RIGIS",
        "format": "zipped shapefile",
        "evidence": "https://www.rigis.org/datasets/e-911-road-centerlines",
        "notes": (
            "Estimated centerlines statewide with street names and address ranges, "
            "built for the RI E 9-1-1 Uniform Emergency Telephone System and maintained "
            "by RIDOT from E-911 information. Distributed from the RIGIS Data "
            "Distribution System as a versioned zip (e.g. TRANS/e911Roads22r1.zip)."
        ),
    },
    "TN": {
        "dataset": "Tennessee NG 9-1-1 GIS Data (street centerlines)",
        "publisher": "TN STS-GIS Services under contract to the TN Emergency Communications Board",
        "format": "file geodatabase (.gdb)",
        "evidence": "https://www.tn.gov/finance/sts-gis/gis/gis-projects/gis-projects-ng911.html",
        "notes": (
            "Full NG911 product - street centerlines, address points, ESN boundaries - "
            "explicitly published for public consumption as a .gdb download. The "
            "companion NG911 Address Points ARE on the TN open data portal, so a "
            "centerline service may appear there later; worth re-checking."
        ),
    },
    "NJ_FILES": {
        "dataset": "Road Centerlines of NJ - Next Gen 911 (shapefile / file geodatabase)",
        "publisher": "NJOGIS via NJGIN Open Data",
        "format": "zipped shapefile with dbf alias table, or zipped file geodatabase",
        "evidence": "https://njogis-newjersey.opendata.arcgis.com/documents/2b11e237a6e149c0a94027780c22c9c4",
        "notes": (
            "Not a fallback - NJ's REST service is in the registry. Recorded because "
            "the file download is the better path for a full statewide bulk load "
            "(a whole-state /query pull against maps.nj.gov would be abusive), and it "
            "ships the road name alias table alongside."
        ),
    },
    "AR_ACF": {
        "dataset": "Arkansas Centerline File (ACF)",
        "publisher": "Arkansas GIS Office",
        "format": "download via Arkansas Spatial Data Infrastructure",
        "evidence": "https://gis.arkansas.gov/programs/arkansas-centerline-file-acf/",
        "notes": "Same dataset as the AR entry in KNOWN_UNVERIFIED_SOURCES; free download confirmed, service not.",
    },
    "WI": {
        "dataset": "WisDOT roads / WISLR",
        "publisher": "Wisconsin DOT, with the State Cartographer's Office documenting sources",
        "format": "download via WisDOT GIS Open Data",
        "evidence": "https://www.sco.wisc.edu/data/roads/",
        "notes": (
            "WisDOT publishes authoritative road data free through its GIS Open Data "
            "site, but no statewide centerline REST layer surfaced. Wisconsin falls "
            "back to TIGER."
        ),
    },
}


# ============================================================================
# ACCESSORS
# ============================================================================


def get_road_source(state_code: Optional[str]) -> Dict[str, Any]:
    """
    Get the road centerline source for a state, falling back to TIGER.

    Args:
        state_code: Two-letter state code (e.g., "NJ", "TX")

    Returns:
        Dict describing the source, with "state_code" set to the entry actually
        in effect and "is_fallback" telling the caller whether TIGER was used.
    """
    code = state_code.upper() if state_code else "DEFAULT"
    if code not in STATE_ROAD_SOURCES:
        # Report the source actually in effect rather than echoing back a code
        # we have no entry for - the seeding UI shows this string to a clerk.
        if code != "DEFAULT":
            logger.info("No statewide road source for %s; falling back to TIGER/Line", code)
        code = "DEFAULT"

    source = dict(STATE_ROAD_SOURCES[code])
    source["state_code"] = code
    source["is_fallback"] = code == "DEFAULT"
    return source


def get_query_urls(state_code: Optional[str]) -> List[str]:
    """
    Get every layer /query URL that must be pulled to cover a state's roads.

    Some states split public roads across layers (PA state vs local roads,
    TIGER primary/secondary/local), so this returns a list, not a single URL.

    Returns:
        List of fully-qualified /query URLs. Empty if the source's layer ID
        could not be confirmed and must be resolved at runtime.
    """
    source = get_road_source(state_code)
    if source.get("url") is None:
        return []

    layer_ids = [source["layer_id"]] + list(source.get("extra_layer_ids", []))
    return [f"{source['service_url']}/{lid}/query" for lid in layer_ids]


def needs_layer_resolution(state_code: Optional[str]) -> bool:
    """True if the fetcher must enumerate the service to find the right layer."""
    return get_road_source(state_code).get("layer_id") is None


def get_name_fields(state_code: Optional[str]) -> Optional[List[str]]:
    """
    Get the street-name field(s) for a state's source, in assembly order.

    Returns None when the mapping is unknown - the caller should then inspect
    the layer's `displayField` and CANDIDATE_NAME_FIELDS.
    """
    field_map = get_road_source(state_code).get("field_map")
    if not field_map:
        return None
    if "full_name" in field_map:
        return [field_map["full_name"]]
    # NENA order: pre-directional, pre-type, base, post-type, post-directional
    order = [
        "pre_directional", "pre_type", "pre_separator",
        "base_name", "post_type", "post_directional", "post_modifier",
    ]
    return [field_map[k] for k in order if k in field_map]


def get_all_sources() -> List[Dict[str, Any]]:
    """Get every registry entry except DEFAULT, sorted by state code."""
    sources = []
    for code, source in STATE_ROAD_SOURCES.items():
        if code == "DEFAULT":
            continue
        entry = dict(source)
        entry["state_code"] = code
        sources.append(entry)
    return sorted(sources, key=lambda x: x["state_code"])


def coverage_summary() -> Dict[str, Any]:
    """
    Summarise registry coverage across all 50 states + DC.

    Returns counts plus the actual state lists, so an operator can see exactly
    which towns will get real state data and which will get TIGER.
    """
    all_codes = [
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
        "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
        "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
        "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
        "WV", "WI", "WY",
    ]
    registered = [c for c in all_codes if c in STATE_ROAD_SOURCES]
    nena = [c for c in registered if STATE_ROAD_SOURCES[c]["schema"] == "nena"]
    custom = [c for c in registered if STATE_ROAD_SOURCES[c]["schema"] == "custom"]
    unresolved_layer = [c for c in registered if STATE_ROAD_SOURCES[c]["layer_id"] is None]
    known_unverified = [c for c in KNOWN_UNVERIFIED_SOURCES if c in all_codes]
    download_only = [c for c in DOWNLOAD_ONLY_SOURCES if c in all_codes]
    fallback = [c for c in all_codes if c not in registered]

    return {
        "total_jurisdictions": len(all_codes),
        "registered": len(registered),
        "registered_states": registered,
        "nena_ng911": len(nena),
        "nena_states": nena,
        "custom_schema": len(custom),
        "custom_states": custom,
        "layer_id_unresolved": unresolved_layer,
        "known_but_endpoint_unverified": known_unverified,
        "download_only": download_only,
        "falls_back_to_tiger": len(fallback),
        "fallback_states": fallback,
        "verification_note": (
            "No endpoint in this registry was contacted during compilation - outbound "
            "HTTPS was restricted to GitHub hosts. URLs are recorded verbatim from "
            "search-index entries for the ArcGIS REST directory page of each layer. "
            "Probe before first use."
        ),
    }


def verification_gaps() -> List[Dict[str, Any]]:
    """
    List everything a fetcher must confirm at runtime before trusting an entry.

    Intended to drive a one-off validation job: hit each service, compare the
    layer name and field list against what is recorded here, and report drift.
    """
    gaps = []
    for code, source in STATE_ROAD_SOURCES.items():
        missing = []
        if source.get("layer_id") is None:
            missing.append("layer_id unresolved - enumerate the service")
        if source.get("field_map") is None:
            missing.append("street-name field unknown - inspect displayField")
        elif source.get("schema") == "nena":
            missing.append("NENA field names assumed from the standard, not read off the layer")
        if source.get("confidence") == "service-indexed":
            missing.append("only the service root was confirmed, not the layer")
        if missing:
            gaps.append({
                "state_code": code,
                "name": source["name"],
                "service_url": source["service_url"],
                "gaps": missing,
            })
    return gaps

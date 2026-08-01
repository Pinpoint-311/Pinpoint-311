"""The map's filter panel offers three things, not seven.

Department, assigned-staff, priority and map-layer filtering were removed from
the request map. This pins what is left, because the removal deleted state,
effects, predicates and props across three files and a partial re-add -- a
checkbox list restored without its predicate, or a predicate without its state
-- would compile and silently filter nothing.

A frontend component checked from the backend suite, for the same reason as the
other contract tests here: this is the suite that runs on every change.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAP = ROOT / "frontend/src/components/StaffDashboardMap.tsx"

# Everything the panel may collapse or expand.
SECTIONS = {"status", "categories", "assignment"}

# State that only existed to drive the removed panels. Each is checked by name
# because a re-add typically starts with exactly one of them.
GONE = [
    "departmentFilters",
    "staffFilters",
    "priorityFilters",
    "layerFilters",
    "toggleAllDepartments",
    "toggleAllStaff",
    "toggleAllLayers",
    "updateLayers",
]


@pytest.fixture(scope="module")
def source() -> str:
    if not MAP.exists():
        pytest.skip("frontend not present in this checkout")
    return MAP.read_text()


def test_the_panel_offers_exactly_three_sections(source):
    found = set(re.findall(r"toggleSection\('(\w+)'\)", source))
    assert found == SECTIONS, f"unexpected: {sorted(found - SECTIONS)}, missing: {sorted(SECTIONS - found)}"


def test_the_section_list_and_the_panels_agree(source):
    """`expandedSections` is the record every panel reads its open/closed state
    from. A key left behind there is dead state; a key missing is a panel stuck
    closed, since `expandedSections.x` would be undefined."""
    # Anchored on the variable name. The first draft matched the earliest
    # `useState({` in the file, which is statusFilters -- so it compared the
    # request statuses against the section names and failed on correct code.
    block = re.search(r"setExpandedSections\] = useState\(\{\n(.*?)\n    \}\);", source, re.S)
    assert block, "expected the expandedSections initialiser"
    declared = set(re.findall(r"^\s+(\w+):", block.group(1), re.M))
    assert declared == SECTIONS, f"expandedSections holds {sorted(declared)}"


@pytest.mark.parametrize("name", GONE)
def test_the_removed_filter_left_nothing_behind(name, source):
    assert name not in source, f"{name} is back, or was left behind"


def test_the_map_no_longer_asks_for_data_it_does_not_use(source):
    """departments, users and mapLayers were props feeding the removed panels.
    Leaving them on the interface would keep every caller fetching and passing
    data the component ignores -- and on the resident portal one of those
    fetches was to a staff-only endpoint."""
    props = re.search(r"interface StaffDashboardMapProps \{(.*?)\n\}", source, re.S)
    assert props, "expected StaffDashboardMapProps"
    declared = set(re.findall(r"^\s+(\w+)\??:", props.group(1), re.M))
    for prop in ("departments", "users", "mapLayers"):
        assert prop not in declared, f"{prop} is still a prop but nothing reads it"


def test_the_township_boundary_still_renders():
    """The boundary is drawn with the same addGeoJsonLayer call the removed map
    layers used, so it is the thing most likely to be deleted alongside them."""
    source = MAP.read_text()
    assert "renderBoundaryAndFit" in source
    assert "addGeoJsonLayer" in source
    assert "townshipBoundary" in source


def test_the_callers_stopped_passing_the_removed_props():
    """Two pages render this map. A stale prop at either call site is a
    TypeScript error, but only if someone runs the typecheck -- and it was
    added recently enough that pinning it here is cheap."""
    for page in ("frontend/src/pages/StaffDashboard.tsx",
                 "frontend/src/pages/ResidentPortal.tsx"):
        source = (ROOT / page).read_text()
        call = re.search(r"<StaffDashboardMap(.*?)/>", source, re.S)
        assert call, f"{page} no longer renders the map"
        for prop in ("departments=", "users=", "mapLayers="):
            assert prop not in call.group(1), f"{page} still passes {prop}"

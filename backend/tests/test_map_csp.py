"""The edge policy has to permit what each map adapter actually fetches.

Configuring Esri on a live deployment produced a base map with nothing on it:
no request pin, no asset markers, no cluster bubbles, no township boundary
overlay. Nothing in the adapter was wrong. The browser was refusing two schemes
that `connect-src` did not list, and the ArcGIS SDK reaches for both by way of
`fetch` rather than the element types one would expect:

  data:   a PictureMarkerSymbol's image is fetched and decoded before being
          uploaded as a WebGL texture. Every glyph in src/maps/markerIcons.ts is
          an SVG data URI on purpose -- that is what makes the same pin identical
          across providers -- so `img-src ... data:` was not the directive that
          governed them.
  blob:   a GeoJSONLayer built from in-memory GeoJSON is serialised to a Blob and
          re-read through its blob: URL, so every addGeoJsonLayer call failed
          with "Failed to load layer".

Both look exactly like a broken renderer, because the basemap keeps drawing --
its tiles come from allowed https hosts. Google is unaffected: it renders icons
in <img> elements and parses GeoJSON in-process, so the gap only appeared once
providers other than the first one were added.

These assertions parse the directive and check membership rather than grepping
for a phrase, so widening the header in a way that drops one of these -- or
rewriting it from a template -- fails here rather than on a town's map.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# What each provider's SDK needs to be able to reach from the browser. The
# schemes are not hosts and are easy to lose in a rewrite; the hosts are here so
# that "which vendor did this line exist for" has an answer.
REQUIRED_CONNECT_SRC = {
    "blob:": "ArcGIS GeoJSONLayer re-reads in-memory GeoJSON through a blob: URL",
    "data:": "ArcGIS PictureMarkerSymbol fetches its SVG data: URI before texturing it",
    "https://js.arcgis.com": "Esri SDK modules and its web workers",
    "https://*.arcgis.com": "ArcGIS geocoding (geocode-api) and portal item resources",
    "https://*.arcgisonline.com": "Esri basemap tiles",
    "https://maps.googleapis.com": "Google Maps JS API",
    "https://places.googleapis.com": "Google Places (New) autocomplete",
    "https://atlas.microsoft.com": "Azure Maps SDK and tiles",
    "https://cdn.apple-mapkit.com": "MapKit JS",
}


def _caddyfile() -> str:
    path = ROOT / "Caddyfile"
    if not path.exists():
        # Only the backend tree is mounted in some runners; the proxy config is
        # a repo-root file.
        pytest.skip("repository root not available")
    return path.read_text()


def _csp_directives(caddyfile: str) -> dict[str, list[str]]:
    """The Content-Security-Policy header value, split into directives."""
    # The directive name also appears in a comment further up, so match the
    # quote that starts the value rather than the name alone.
    marker = 'Content-Security-Policy "'
    start = caddyfile.index(marker) + len(marker)
    header = caddyfile[start:caddyfile.index('"', start)]

    directives: dict[str, list[str]] = {}
    for chunk in header.split(";"):
        parts = chunk.split()
        if parts:
            directives[parts[0]] = parts[1:]
    return directives


def test_connect_src_permits_every_map_provider_it_claims_to_support():
    directives = _csp_directives(_caddyfile())
    connect_src = directives["connect-src"]

    missing = {
        source: why
        for source, why in REQUIRED_CONNECT_SRC.items()
        if source not in connect_src
    }
    assert not missing, (
        "connect-src is missing sources the map adapters fetch from: "
        + "; ".join(f"{source} ({why})" for source, why in sorted(missing.items()))
    )


def test_marker_and_overlay_schemes_are_not_left_to_img_src_alone():
    """The two schemes that were the actual bug, checked as a pair.

    `img-src` and `worker-src` already allowed both, which is what made this so
    slow to find -- the reasonable assumption is that an image URL is fetched by
    an <img> and a worker URL by a Worker. Neither is how the ArcGIS SDK
    consumes them.
    """
    directives = _csp_directives(_caddyfile())
    for scheme in ("blob:", "data:"):
        assert scheme in directives["connect-src"], (
            f"connect-src does not allow {scheme}: on Esri this silently drops "
            "every marker icon and every GeoJSON overlay while the basemap keeps "
            "rendering, which reads as a broken renderer"
        )


def test_the_policy_has_not_been_widened_to_everything():
    """A blanket default-src would make the test above vacuous."""
    directives = _csp_directives(_caddyfile())
    assert directives["default-src"] == ["'self'"]
    assert directives["object-src"] == ["'none'"]
    assert "*" not in directives["connect-src"]

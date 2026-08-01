import { MarkerIcon } from './types';

/**
 * Two kinds of dot on one map, and until now they were the same dot.
 *
 * A service request is something a resident reported and somebody has to go and
 * fix. An asset is a thing the town owns that sits there permanently -- a
 * hydrant, a catch basin, a streetlight. Both were drawn as a 10px filled
 * circle with a white ring, distinguished only by colour, and the colour of an
 * asset layer is chosen by whoever uploaded it. Pick red for your hydrants and
 * every hydrant in town becomes indistinguishable from an open pothole report.
 *
 * So the difference is now shape, which survives colour choice, greyscale
 * printing, and the several forms of colour blindness that make red and green
 * the same pin.
 *
 *   request   filled circle       "somebody reported this"
 *   asset     diamond with a hole "this belongs to the town"
 *
 * ## Why an SVG data URI and not a vendor symbol
 *
 * Google exposes `SymbolPath` and an SVG `path` string on its marker options.
 * Reaching for that is the obvious way to draw a diamond and it would tie this
 * map to Google, which is the one thing the provider abstraction exists to
 * prevent -- a town on Esri or Azure would get no marker at all, and the
 * failure would be silent.
 *
 * `MarkerIcon` offers exactly two shapes, `circle` and `image`, because those
 * are the two every adapter can honour. `image` takes any URL including a
 * `data:` URI, so an inline SVG is a description of a picture rather than a
 * vendor drawing instruction: Google makes it an Icon, Esri a PictureMarker,
 * MapLibre rasterises it into the sprite. Nothing here knows which.
 */

/** Only a hex colour reaches the SVG. See `safeColor`. */
const HEX = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

const FALLBACK_FILL = '#64748b';   // slate; a layer with no usable colour
const STROKE = '#ffffff';

/**
 * Colours come from `map_layers`, which an admin fills in by uploading a file.
 * They are interpolated into SVG markup, and SVG is a document format that
 * happily carries a `<script>` element -- so a stored value like
 * `#fff"/><script>...` would be markup, not a colour.
 *
 * The data URI is not same-origin in an <img>, which is how every provider
 * renders it, so this is defence in depth rather than the only thing standing
 * between us and script execution. It is cheap and the alternative is reasoning
 * about six adapters' rendering paths.
 *
 * Anything that is not a plain hex colour is replaced, not escaped: a value
 * that fails this test is a bug or an attack, and neither should be drawn.
 */
export function safeColor(value: string | null | undefined, fallback = FALLBACK_FILL): string {
    return typeof value === 'string' && HEX.test(value.trim()) ? value.trim() : fallback;
}

/** A resident's report. Unchanged -- the legend has always described this. */
export function requestIcon(color: string): MarkerIcon {
    return {
        type: 'circle',
        radius: 10,
        fillColor: safeColor(color, '#6366f1'),
        fillOpacity: 1,
        strokeColor: STROKE,
        strokeWidth: 2,
    };
}

/**
 * A town-owned asset: a diamond with a hollow centre.
 *
 * Rotated-square rather than a differently-sized circle, because "slightly
 * bigger circle" is not a distinction anybody makes at a glance on a map with
 * two hundred pins on it. The hollow centre reads as "reference point" rather
 * than "thing to action" and keeps the shape legible at small sizes.
 */
export function assetIcon(fillColor: string, strokeColor?: string): MarkerIcon {
    const fill = safeColor(fillColor);
    const stroke = safeColor(strokeColor, STROKE);
    const size = 22;   // rendered box; the diamond is inset so the stroke fits

    const svg = [
        `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">`,
        // Drop shadow, so an asset stays visible on a satellite basemap.
        `<path d="M11 2.5 L19.5 11 L11 19.5 L2.5 11 Z" fill="rgba(0,0,0,0.35)" transform="translate(0,1)"/>`,
        `<path d="M11 2.5 L19.5 11 L11 19.5 L2.5 11 Z" fill="${fill}" stroke="${stroke}" stroke-width="2.5" stroke-linejoin="round"/>`,
        `<circle cx="11" cy="11" r="3" fill="${STROKE}" fill-opacity="0.9"/>`,
        `</svg>`,
    ].join('');

    return {
        type: 'image',
        // encodeURIComponent rather than base64: smaller, and it leaves the
        // markup readable in devtools when somebody is working out why a pin
        // looks wrong.
        url: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`,
        width: size,
        height: size,
        // Centre of the box sits on the coordinate. Without this the provider
        // defaults vary -- some anchor top-left -- and the asset would sit
        // half a pin north-west of where it actually is.
        anchor: { x: size / 2, y: size / 2 },
    };
}

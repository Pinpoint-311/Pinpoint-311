import { MarkerIcon, MarkerLabel, TOP_MARKER_Z_INDEX } from './types';

/**
 * Every glyph that sits on top of a map, in one place.
 *
 * ## Why these are all images now
 *
 * `MarkerIcon` offers `circle` and `image`. `circle` looks like the cheaper
 * option and it is the reason the maps did not match each other: it is a
 * *drawing instruction*, so each adapter hands it to its own renderer and each
 * renderer answers differently -- Google's SymbolPath, Esri's SimpleMarker,
 * Azure's bubble layer. Stroke weights land on different subpixels, shadows
 * exist or do not, and a `label` is set in whatever font that vendor picked. The
 * same request pin genuinely looked like a different pin depending on which
 * provider a town had chosen.
 *
 * An SVG data URI is a *picture*, rasterised by the browser before any provider
 * sees it. Google makes it an Icon, Esri a PictureMarker, MapLibre rasterises it
 * into the sprite -- and all three get identical pixels. So everything here
 * returns `image`, including the cluster bubbles, whose counts are drawn into the
 * SVG rather than passed as a provider `label`.
 *
 * That is also why nothing in this file references a vendor symbol, and why the
 * components no longer define their own inline SVG. Before this there were three
 * different asset markers, three different cluster bubbles and a pin, spread
 * across four components -- which is a look nobody chose.
 *
 * ## The shapes, and why they differ by more than colour
 *
 *   request   solid puck        "somebody reported this, it needs actioning"
 *   asset     ring puck         "the town owns this, it is a reference point"
 *   cluster   large puck + count
 *   location  pin with a stem   "this exact spot, chosen just now"
 *
 * Colour cannot carry that distinction. An asset layer's colour is chosen by
 * whoever uploaded the file, so a town that picks red for hydrants would make
 * every hydrant look like an open pothole report. Solid-versus-hollow survives
 * that, and survives greyscale printing and the common forms of colour blindness.
 * The previous asset glyph was a diamond, which achieved the same separation but
 * read as a rotated sticker rather than something belonging on a map.
 */

/** Only a hex colour reaches the SVG. See `safeColor`. */
const HEX = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

const FALLBACK_FILL = '#64748b';   // slate; a layer with no usable colour
const STROKE = '#ffffff';
const CLUSTER_FILL = '#4f46e5';    // indigo, dark enough for WCAG AA on white text
const SHADOW = '#0b1020';

/** Generic families only: a data URI cannot fetch a web font. */
const FONT = 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif';

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

/**
 * encodeURIComponent rather than base64: smaller, and it leaves the markup
 * readable in devtools when somebody is working out why a pin looks wrong.
 */
function svgUrl(svg: string): string {
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

/**
 * Ids are unique per glyph variant because an adapter that inlines these into
 * one document (rather than using them as separate <img> sources) would
 * otherwise have several `<defs>` sharing an id, and every marker would take
 * whichever was parsed last.
 */
function uid(prefix: string, ...parts: string[]): string {
    return `${prefix}${parts.join('').replace(/[^0-9a-z]/gi, '')}`;
}

/**
 * A soft contact shadow, not an offset copy of the shape. The offset version
 * doubled a marker's visual weight and made a dense layer read as blocks of
 * colour rather than as individual points.
 */
function shadow(id: string, blur = 0.9, dy = 0.5, opacity = 0.45): string {
    return (
        `<filter id="${id}" x="-50%" y="-50%" width="200%" height="200%">` +
        `<feDropShadow dx="0" dy="${dy}" stdDeviation="${blur}" flood-color="${SHADOW}" flood-opacity="${opacity}"/>` +
        `</filter>`
    );
}

/** Light from above, the way every other surface in this product is lit. */
function gloss(id: string): string {
    return (
        `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">` +
        `<stop offset="0" stop-color="#ffffff" stop-opacity="0.30"/>` +
        `<stop offset="0.55" stop-color="#ffffff" stop-opacity="0"/>` +
        `</linearGradient>`
    );
}

export interface PuckOptions {
    /** Hex only; anything else is replaced. See `safeColor`. */
    fill: string;
    /** Hex only. Defaults to the white ring the whole set shares. */
    stroke?: string;
    /** Overall box in CSS pixels. */
    size?: number;
    strokeWidth?: number;
    /** A hole in the middle: "a reference point" rather than "an item". */
    hollow?: boolean;
}

/**
 * The one routine that draws a puck.
 *
 * Every round glyph on every map goes through here, which is the actual
 * mechanism behind "the maps look like each other" -- not a style guide anybody
 * has to remember. A caller chooses colour, size and solid-versus-hollow; the
 * ring, the contact shadow and the light-from-above gloss are not negotiable,
 * because those are what make a marker legible over satellite imagery. A flat
 * circle disappears into a dark roof.
 */
export function puckIcon({
    fill,
    stroke,
    size = 22,
    strokeWidth = 2.2,
    hollow = false,
}: PuckOptions): MarkerIcon {
    const f = safeColor(fill);
    const st = safeColor(stroke, STROKE);
    const s = uid('pk', f, st, String(size), String(hollow));

    const c = size / 2;
    const r = c - strokeWidth / 2 - 0.7;
    const hole = Math.max(1.6, r * 0.36);

    const svg =
        `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">` +
        `<defs>${shadow(`${s}s`)}${gloss(`${s}g`)}</defs>` +
        `<g filter="url(#${s}s)">` +
        `<circle cx="${c}" cy="${c}" r="${r.toFixed(2)}" fill="${f}" stroke="${st}" stroke-width="${strokeWidth}"/>` +
        `<circle cx="${c}" cy="${c}" r="${r.toFixed(2)}" fill="url(#${s}g)"/>` +
        (hollow ? `<circle cx="${c}" cy="${c}" r="${hole.toFixed(2)}" fill="${STROKE}"/>` : '') +
        `</g>` +
        `</svg>`;

    return {
        type: 'image',
        url: svgUrl(svg),
        width: size,
        height: size,
        // Centre of the box sits on the coordinate. Without this the provider
        // defaults vary -- some anchor top-left -- and the marker would sit half
        // a pin north-west of where it actually is.
        anchor: { x: size / 2, y: size / 2 },
    };
}

/**
 * A resident's report: a solid puck.
 *
 * Was `{ type: 'circle', radius: 10 }` in the staff dashboard and `radius: 9` in
 * the resident map, each drawn by the provider -- so the same report was a
 * different dot depending on which page you opened it from.
 */
export function requestIcon(color: string): MarkerIcon {
    return puckIcon({ fill: safeColor(color, '#6366f1'), size: 22 });
}

/**
 * A town-owned asset: a puck with a hollow centre.
 *
 * The hole is what separates it from a report at a glance, and it does so
 * without depending on colour. It is drawn opaque rather than cut through,
 * because a transparent centre picks up whatever is beneath it and stops reading
 * as a hole over busy imagery.
 *
 * Slightly smaller than a request, because an asset is a reference point rather
 * than something demanding attention.
 */
export function assetIcon(fillColor: string, strokeColor?: string): MarkerIcon {
    return puckIcon({ fill: fillColor, stroke: strokeColor, size: 18, strokeWidth: 2, hollow: true });
}

/**
 * A cluster bubble, with its count drawn in.
 *
 * The count used to be a provider `label`, which is the other half of why the
 * maps did not match: the resident view asked for 11px in whatever font Google
 * defaults to, the staff view asked for 12px, and an Esri town got neither. Text
 * inside the SVG is the same text everywhere.
 *
 * Growth is deliberately gentle and capped. The two call sites had diverged to
 * `16 + count/5` and `18 + count/4`, so the same forty reports drew a different
 * bubble depending on which page you were on, and a busy town produced bubbles
 * large enough to hide the streets underneath.
 */
export function clusterIcon(count: number): MarkerIcon {
    const n = Math.max(1, Math.floor(count));
    const label = n > 999 ? '999+' : String(n);
    // 34 at a handful, 52 at a hundred or more.
    const size = Math.round(34 + Math.min(n, 100) / 100 * 18);
    const s = uid('cl', String(size), label);

    const c = size / 2;
    const r = c - 3.2;
    const fontSize = label.length >= 4 ? size * 0.30 : label.length === 3 ? size * 0.34 : size * 0.40;

    const svg =
        `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">` +
        `<defs>${shadow(`${s}s`, size * 0.05, size * 0.03, 0.4)}${gloss(`${s}g`)}</defs>` +
        `<g filter="url(#${s}s)">` +
        // A translucent outer halo, so a bubble over dense imagery still has an
        // edge without needing a heavier white ring.
        `<circle cx="${c}" cy="${c}" r="${c - 0.6}" fill="${CLUSTER_FILL}" fill-opacity="0.22"/>` +
        `<circle cx="${c}" cy="${c}" r="${r}" fill="${CLUSTER_FILL}" stroke="${STROKE}" stroke-width="2.4"/>` +
        `<circle cx="${c}" cy="${c}" r="${r}" fill="url(#${s}g)"/>` +
        // dy rather than dominant-baseline: the latter is unevenly honoured when
        // an SVG is consumed as an image rather than inlined.
        `<text x="${c}" y="${c}" dy="0.35em" text-anchor="middle" ` +
        `font-family="${FONT}" font-size="${fontSize.toFixed(1)}" font-weight="700" ` +
        `fill="${STROKE}">${label}</text>` +
        `</g>` +
        `</svg>`;

    return {
        type: 'image',
        url: svgUrl(svg),
        width: size,
        height: size,
        anchor: { x: size / 2, y: size / 2 },
    };
}

/**
 * The whole `ClusterOptions.style` callback, so the three maps that cluster
 * cannot drift apart again. No `label` is returned: the count is in the image.
 */
export function clusterStyle(count: number): { icon: MarkerIcon; label?: MarkerLabel; zIndex?: number } {
    return { icon: clusterIcon(count), zIndex: TOP_MARKER_Z_INDEX + Math.min(count, 10000) };
}

/**
 * The spot somebody just chose, or the one a request is about: a pin with a
 * stem, because unlike everything else on the map this one is claiming an exact
 * point rather than marking a thing.
 *
 * Its head is the same puck as the rest of the set, so it belongs to the family
 * while being impossible to mistake for a report.
 */
export function locationPinIcon(color = '#6366f1'): MarkerIcon {
    const fill = safeColor(color, '#6366f1');
    const width = 26;
    const height = 36;
    const s = uid('pin', fill);

    const svg =
        `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 26 36">` +
        `<defs>${shadow(`${s}s`, 1.1, 0.8, 0.42)}${gloss(`${s}g`)}</defs>` +
        `<g filter="url(#${s}s)">` +
        // Head and stem as one path, so the join is a single filled shape rather
        // than a circle with a triangle poking out of it.
        `<path d="M13 1.6 C7.2 1.6 2.5 6.3 2.5 12.1 C2.5 19.4 10.2 28.1 12.3 34.0 ` +
        `C12.5 34.6 13.5 34.6 13.7 34.0 C15.8 28.1 23.5 19.4 23.5 12.1 ` +
        `C23.5 6.3 18.8 1.6 13 1.6 Z" ` +
        `fill="${fill}" stroke="${STROKE}" stroke-width="2" stroke-linejoin="round"/>` +
        `<path d="M13 1.6 C7.2 1.6 2.5 6.3 2.5 12.1 C2.5 16.5 5.5 21.0 8.0 24.5 ` +
        `C5.0 19.0 4.6 13.0 7.4 8.6 C9.6 5.2 13.8 3.6 18.0 4.6 ` +
        `C16.6 2.7 14.9 1.6 13 1.6 Z" fill="url(#${s}g)" stroke="none"/>` +
        `<circle cx="13" cy="12" r="4.1" fill="${STROKE}"/>` +
        `</g>` +
        `</svg>`;

    return {
        type: 'image',
        url: svgUrl(svg),
        width,
        height,
        // The tip, not the centre: a pin points at its coordinate.
        anchor: { x: width / 2, y: height - 1.5 },
    };
}

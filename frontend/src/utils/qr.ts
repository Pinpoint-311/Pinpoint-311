import qrcode from 'qrcode-generator';

/**
 * QR codes drawn here, rather than fetched from somebody else's server.
 *
 * The printed work order used to hot-link `api.qrserver.com`, passing the data
 * to be encoded in the query string. One of those codes carries the exact
 * latitude and longitude of a resident's report, so every time a clerk printed a
 * work order a third party with no relationship to the town — and no agreement
 * covering it — received an incident location. It also meant a work order could
 * not be printed at all without internet access to that particular vendor.
 *
 * `qrcode-generator` was chosen over the more obvious `qrcode` package because
 * it has no dependencies (`qrcode` brings `yargs` and `pngjs`, a CLI parser and
 * a PNG encoder, into a browser bundle) and because its API is synchronous. The
 * work order is assembled as one HTML string, so anything asynchronous would
 * have meant restructuring the whole document build around two small images.
 *
 * ## Error correction and the badge
 *
 * The two codes on a work order look alike, and a clerk holding a printout needs
 * to know which is the map and which is the record. A glyph in the middle solves
 * that, and costs readable area: the modules underneath it are not drawn.
 *
 * That is what error correction is for, but it has to be budgeted rather than
 * assumed. These use level `H`, which recovers around 30% of the symbol. The
 * badge is 24% of the width, so under 6% of the area — comfortably inside the
 * budget, and centred, where it cannot touch the three finder patterns in the
 * corners or the timing rows that run between them.
 *
 * SVG rather than a raster: a work order goes to a printer, and vector modules
 * stay square at any DPI instead of blurring into their neighbours.
 */

/** Which code this is, for the glyph in the middle. */
export type QrBadge = 'location' | 'record';

const INK = '#0f172a';
const BRAND = '#4f46e5';

/** Paths drawn in a 0..24 box, centred on 12,12. */
const GLYPHS: Record<QrBadge, string> = {
    // The same teardrop the maps use for "this exact spot".
    location:
        'M12 3.4c-3.5 0-6.3 2.8-6.3 6.3 0 4.4 4.6 8.6 6.3 10.9 1.7-2.3 6.3-6.5 6.3-10.9 0-3.5-2.8-6.3-6.3-6.3z'
        + 'M12 12.2a2.6 2.6 0 1 0 0-5.2 2.6 2.6 0 0 0 0 5.2z',
    // A page with lines on it: the request record.
    record:
        'M7 3.6h7.6L18 7v13a1.4 1.4 0 0 1-1.4 1.4H7A1.4 1.4 0 0 1 5.6 20V5A1.4 1.4 0 0 1 7 3.6z'
        + 'M13.9 4.2V7.7H17.6'
        + 'M8.3 11.4h7.4M8.3 14.3h7.4M8.3 17.2h4.6',
};

export interface QrOptions {
    /** Glyph in the middle, so two codes on one page are distinguishable. */
    badge?: QrBadge;
    /** Rendered edge length in CSS pixels. Vector, so this is a hint not a limit. */
    size?: number;
}

/**
 * An `<svg>` string encoding `text`, safe to drop into markup.
 *
 * Returns null only if the data cannot be encoded at all — too long for the
 * largest symbol at this error-correction level. Callers show the underlying
 * value instead rather than an empty box.
 */
export function qrSvg(text: string, { badge, size = 112 }: QrOptions = {}): string | null {
    if (!text) return null;

    let qr;
    try {
        // 0 = pick the smallest version that fits. 'H' = ~30% recovery, which is
        // what pays for the badge.
        qr = qrcode(0, 'H');
        qr.addData(text);
        qr.make();
    } catch {
        return null;
    }

    const count = qr.getModuleCount();
    const margin = 2;                 // quiet zone, in modules
    const extent = count + margin * 2;

    // The hole the badge sits in, in whole modules so no module is half-drawn.
    const holeSpan = badge ? Math.max(5, Math.round(count * 0.24)) : 0;
    const holeFrom = Math.floor((count - holeSpan) / 2);
    const holeTo = holeFrom + holeSpan;
    const inHole = (r: number, c: number) =>
        badge !== undefined && r >= holeFrom && r < holeTo && c >= holeFrom && c < holeTo;

    // One path for every dark module. Cheaper than `count * count` rects, and it
    // keeps the printed file small when a work order has several pages.
    let d = '';
    for (let r = 0; r < count; r++) {
        for (let c = 0; c < count; c++) {
            if (!qr.isDark(r, c) || inHole(r, c)) continue;
            d += `M${c + margin} ${r + margin}h1v1h-1z`;
        }
    }

    const badgeSvg = badge
        ? (() => {
            const pad = 0.6;
            const x = holeFrom + margin - pad;
            const w = holeSpan + pad * 2;
            const gx = holeFrom + margin;
            const scale = holeSpan / 24;
            return (
                `<rect x="${x}" y="${x}" width="${w}" height="${w}" rx="${w * 0.22}" fill="#ffffff"/>`
                + `<g transform="translate(${gx} ${gx}) scale(${scale})">`
                + `<path d="${GLYPHS[badge]}" fill="${BRAND}" stroke="${BRAND}"`
                + ` stroke-width="0.9" stroke-linejoin="round" stroke-linecap="round"/>`
                + `</g>`
            );
        })()
        : '';

    return (
        `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}"`
        + ` viewBox="0 0 ${extent} ${extent}" shape-rendering="crispEdges" role="img">`
        + `<rect width="${extent}" height="${extent}" fill="#ffffff"/>`
        + `<path d="${d}" fill="${INK}"/>`
        + badgeSvg
        + `</svg>`
    );
}

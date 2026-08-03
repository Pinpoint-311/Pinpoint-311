import { describe, it, expect } from 'vitest';

import { assetIcon, clusterIcon, clusterStyle, locationPinIcon, requestIcon, safeColor } from './markerIcons';

/**
 * A reported pothole and a fire hydrant were the same dot.
 *
 * Both were a 10px filled circle with a white ring, separated only by colour --
 * and an asset layer's colour is picked by whoever uploaded the file. Choose
 * red for hydrants and every hydrant is an open report. Choose green and they
 * are all closed ones.
 */

/** Every glyph in the set, for the properties all of them must share. */
const EVERY_GLYPH: [string, () => ReturnType<typeof requestIcon>][] = [
    ['request', () => requestIcon('#ef4444')],
    ['asset', () => assetIcon('#ef4444')],
    ['cluster', () => clusterIcon(12)],
    ['location pin', () => locationPinIcon()],
];

describe('a request and an asset do not look the same', () => {
    it('separates them by shape, not just by colour', () => {
        // Same colour on purpose. If the only difference were the fill, this
        // is exactly the collision a town would hit by accident.
        const request = requestIcon('#ef4444');
        const asset = assetIcon('#ef4444');
        if (request.type !== 'image' || asset.type !== 'image') throw new Error('expected images');
        expect(request.url).not.toBe(asset.url);
    });

    it('gives the asset a hollow centre and the request a solid one', () => {
        // This is the distinction that survives greyscale printing and the
        // common forms of colour blindness. The fill colour is identical here,
        // so a difference in the markup is the only thing carrying it.
        const request = requestIcon('#ef4444');
        const asset = assetIcon('#ef4444');
        if (request.type !== 'image' || asset.type !== 'image') throw new Error('expected images');
        const hole = (icon: typeof asset) =>
            (decodeURIComponent(icon.url.split(',')[1]).match(/<circle[^>]*fill="#ffffff"/g) || []).length;
        expect(hole(asset)).toBeGreaterThan(0);
        expect(hole(request)).toBe(0);
    });
});

describe('every glyph is drawn by us, not by the provider', () => {
    // `type: 'circle'` is a drawing instruction each adapter hands to its own
    // renderer, so the same marker genuinely looked different on Google, Esri
    // and Azure -- different stroke subpixels, different shadow, and a `label`
    // set in whatever font that vendor picked. An SVG data URI is rasterised by
    // the browser before any provider sees it.
    it.each(EVERY_GLYPH)('%s is a self-contained image', (_name, make) => {
        const icon = make();
        if (icon.type !== 'image') throw new Error('expected an image icon');
        expect(icon.url.startsWith('data:image/svg+xml')).toBe(true);
    });

    it.each(EVERY_GLYPH)('%s needs no network to draw', (_name, make) => {
        // A hosted PNG would be one more thing that fails on a municipal
        // network with tight egress, and it would fail as a missing pin.
        const icon = make();
        if (icon.type !== 'image') throw new Error('expected an image icon');
        expect(icon.url).not.toMatch(/^https?:/);
    });
});

describe('cluster bubbles are the same bubble on every map', () => {
    it('draws the count into the image rather than asking for a provider label', () => {
        // The resident map asked for an 11px label and the staff dashboard for
        // 12px, in whichever font the vendor defaulted to. Text in the SVG is
        // the same text everywhere, so no `label` is returned at all.
        const style = clusterStyle(42);
        expect(style.label).toBeUndefined();
        if (style.icon.type !== 'image') throw new Error('expected an image icon');
        expect(decodeURIComponent(style.icon.url.split(',')[1])).toContain('>42<');
    });

    it('grows with the count but stays bounded', () => {
        // The two call sites had diverged to `16 + count/5` and `18 + count/4`,
        // so a busy town got bubbles big enough to hide the streets under them.
        const small = clusterIcon(2);
        const large = clusterIcon(500);
        if (small.type !== 'image' || large.type !== 'image') throw new Error('expected images');
        expect(large.width).toBeGreaterThan(small.width);
        expect(large.width).toBeLessThanOrEqual(56);
    });

    it('does not render a four-figure count as overflowing text', () => {
        const icon = clusterIcon(4321);
        if (icon.type !== 'image') throw new Error('expected an image icon');
        expect(decodeURIComponent(icon.url.split(',')[1])).toContain('>999+<');
    });
});

describe('a pin points at its coordinate; a puck sits on it', () => {
    it('anchors the pin at its tip', () => {
        // Anchoring a pin at its centre floats it half its height above the
        // thing it is pointing at, which on a street map is most of a block.
        const icon = locationPinIcon();
        if (icon.type !== 'image') throw new Error('expected an image icon');
        expect(icon.anchor!.y).toBeGreaterThan(icon.height * 0.9);
        expect(icon.anchor!.x).toBe(icon.width / 2);
    });

    it('centres the pucks', () => {
        for (const make of [() => requestIcon('#ef4444'), () => assetIcon('#ef4444'), () => clusterIcon(3)]) {
            const icon = make();
            if (icon.type !== 'image') throw new Error('expected an image icon');
            expect(icon.anchor).toEqual({ x: icon.width / 2, y: icon.height / 2 });
        }
    });
});

describe('colours from an uploaded layer cannot become markup', () => {
    // fill_color and stroke_color are admin-supplied and land inside SVG, which
    // is a document format that carries <script>.
    const hostile = [
        '#fff"/><script>alert(1)</script><rect fill="#fff',
        'red" onload="alert(1)',
        'url(#x)',
        'javascript:alert(1)',
        '</svg><svg onload=alert(1)>',
    ];

    it.each(hostile)('replaces %s rather than escaping it', (value) => {
        const icon = assetIcon(value);
        if (icon.type !== 'image') throw new Error('expected an image icon');
        const svg = decodeURIComponent(icon.url.split(',')[1]);
        expect(svg).not.toContain('script');
        expect(svg).not.toContain('onload');
        // And what it drew is a real colour.
        expect(svg).toContain('#64748b');
    });

    it('lets a genuine hex colour through untouched', () => {
        expect(safeColor('#3b82f6')).toBe('#3b82f6');
        expect(safeColor('#FFF')).toBe('#FFF');
        expect(safeColor('  #3b82f6  ')).toBe('#3b82f6');   // stored with whitespace
        expect(safeColor('#3b82f6cc')).toBe('#3b82f6cc');   // 8-digit, with alpha
    });

    it('falls back when the colour is missing entirely', () => {
        // Layers predating the colour columns, and rows where an import left
        // them null. A marker that fails to draw is worse than a grey one.
        expect(safeColor(null)).toBe('#64748b');
        expect(safeColor(undefined)).toBe('#64748b');
        expect(safeColor('')).toBe('#64748b');
    });

    it('does not accept a colour name', () => {
        // Not hostile, but not a hex value either, and allowing names means
        // the validator has to know the CSS colour list. The fallback is
        // visible and debuggable; a partial allow-list is not.
        expect(safeColor('red')).toBe('#64748b');
    });
});

describe('the drawn asset icon', () => {
    it('is a round puck, not the rotated square it used to be', () => {
        // It was a diamond, which separated it from a report but read as a
        // sticker dropped on the map rather than something belonging to it.
        // Matched on the shape rather than exact coordinates so the glyph can be
        // refined without rewriting the test.
        const icon = assetIcon('#3b82f6');
        if (icon.type !== 'image') throw new Error('expected an image icon');
        const svg = decodeURIComponent(icon.url.split(',')[1]);
        expect(svg).toContain('<circle');
        expect(svg).not.toMatch(/d="M[\d.]+ [\d.]+ L[\d.]+ [\d.]+ L[\d.]+ [\d.]+ L[\d.]+ [\d.]+ Z"/);
        expect(svg).toContain('#3b82f6');
    });

    it('honours the layer stroke colour and defaults it to white', () => {
        const withStroke = assetIcon('#3b82f6', '#000000');
        const without = assetIcon('#3b82f6');
        if (withStroke.type !== 'image' || without.type !== 'image') throw new Error();
        expect(decodeURIComponent(withStroke.url)).toContain('stroke="#000000"');
        expect(decodeURIComponent(without.url)).toContain('stroke="#ffffff"');
    });
});

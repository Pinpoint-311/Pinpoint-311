import { describe, it, expect } from 'vitest';

import { assetIcon, requestIcon, safeColor } from './markerIcons';

/**
 * A reported pothole and a fire hydrant were the same dot.
 *
 * Both were a 10px filled circle with a white ring, separated only by colour --
 * and an asset layer's colour is picked by whoever uploaded the file. Choose
 * red for hydrants and every hydrant is an open report. Choose green and they
 * are all closed ones.
 */

describe('a request and an asset do not look the same', () => {
    it('uses a different kind of icon for each, not just a different colour', () => {
        // Same colour on purpose. If the only difference were the fill, this
        // is exactly the collision a town would hit by accident.
        const request = requestIcon('#ef4444');
        const asset = assetIcon('#ef4444');
        expect(request.type).toBe('circle');
        expect(asset.type).toBe('image');
        expect(request.type).not.toBe(asset.type);
    });

    it('keeps the request marker as the circle the legend describes', () => {
        const icon = requestIcon('#22c55e');
        expect(icon).toMatchObject({ type: 'circle', radius: 10, fillColor: '#22c55e' });
    });
});

describe('the asset marker belongs to no particular map provider', () => {
    it('is a self-contained image rather than a vendor drawing instruction', () => {
        // Google exposes SymbolPath and an SVG `path` string on its own marker
        // options. Using those is the obvious way to draw a diamond and it
        // would leave a town on Esri or Azure with no marker at all -- and no
        // error, which is worse.
        const icon = assetIcon('#3b82f6');
        if (icon.type !== 'image') throw new Error('expected an image icon');
        expect(icon.url.startsWith('data:image/svg+xml')).toBe(true);
    });

    it('needs no network to draw', () => {
        // A hosted PNG would be one more thing that fails on a municipal
        // network with tight egress, and it would fail as a missing pin.
        const icon = assetIcon('#3b82f6');
        if (icon.type !== 'image') throw new Error('expected an image icon');
        expect(icon.url).not.toMatch(/^https?:/);
    });

    it('sits on its coordinate rather than beside it', () => {
        // Providers disagree on the default anchor; some use the top-left. An
        // unanchored 22px icon puts the hydrant 11px north-west of the hydrant.
        const icon = assetIcon('#3b82f6');
        if (icon.type !== 'image') throw new Error('expected an image icon');
        expect(icon.anchor).toEqual({ x: icon.width / 2, y: icon.height / 2 });
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
    it('is a diamond, matching what the request-detail map already used', () => {
        const icon = assetIcon('#3b82f6');
        if (icon.type !== 'image') throw new Error('expected an image icon');
        const svg = decodeURIComponent(icon.url.split(',')[1]);
        // Four points, closed: the rotated square.
        expect(svg).toMatch(/<path d="M11 2\.5 L19\.5 11 L11 19\.5 L2\.5 11 Z"/);
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

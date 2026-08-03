import { describe, it, expect } from 'vitest';
import jsQR from 'jsqr';

import { qrSvg } from './qr';

/**
 * The point of these is that the codes still scan.
 *
 * A glyph in the middle of a QR code is not free: the modules underneath it are
 * not drawn, and the symbol survives only because error correction covers them.
 * That budget is easy to overspend by nudging the badge a little larger, and the
 * failure is invisible in review — the image looks like a QR code, and nobody
 * discovers otherwise until a crew in a van points a phone at a printed work
 * order and nothing happens.
 *
 * So these decode what `qrSvg` actually emits, rather than asserting on its
 * markup. The SVG is parsed back into a module matrix, rasterised the way a
 * camera would oversample it, and handed to a real decoder.
 */

/** Rasterise the emitted SVG by parsing the module rects back out of it. */
function decode(svg: string): string | null {
    const extent = Number(/viewBox="0 0 (\d+)/.exec(svg)![1]);
    const scale = 8;
    const size = extent * scale;
    const rgba = new Uint8ClampedArray(size * size * 4).fill(255);

    for (const m of svg.matchAll(/M(\d+) (\d+)h1v1h-1z/g)) {
        const col = Number(m[1]);
        const row = Number(m[2]);
        for (let y = 0; y < scale; y++) {
            for (let x = 0; x < scale; x++) {
                const px = ((row * scale + y) * size + (col * scale + x)) * 4;
                rgba[px] = rgba[px + 1] = rgba[px + 2] = 0;
            }
        }
    }
    const found = jsQR(rgba, size, size);
    return found ? found.data : null;
}

const STAFF = 'https://demo.pinpoint311.org/staff#active/request/SR-2026-000123';
const MAP = 'https://www.google.com/maps?q=40.732500,-74.275000';

describe('a work order QR code scans', () => {
    it.each([
        ['record badge', STAFF, 'record'],
        ['location badge', MAP, 'location'],
        ['no badge', 'https://example.org/plain', undefined],
        // Longer payloads push to a bigger symbol, where the badge covers a
        // different number of modules. It has to hold there too.
        ['long id', `${STAFF}-AND-A-MUCH-LONGER-TRAILING-IDENTIFIER-0987654321`, 'record'],
    ] as const)('%s round-trips through a decoder', (_name, text, badge) => {
        const svg = qrSvg(text, badge ? { badge } : {});
        expect(svg).not.toBeNull();
        expect(decode(svg!)).toBe(text);
    });
});

describe('the badge is actually there, and paid for', () => {
    it('punches a hole and fills it with the glyph', () => {
        const withBadge = qrSvg(STAFF, { badge: 'record' })!;
        const without = qrSvg(STAFF)!;
        // Fewer modules drawn, because the ones under the badge are skipped.
        const count = (s: string) => (s.match(/h1v1h-1z/g) || []).length;
        expect(count(withBadge)).toBeLessThan(count(without));
        expect(withBadge).toContain('<rect');
    });

    it('draws a different glyph for each kind, so two codes are distinguishable', () => {
        const a = qrSvg(STAFF, { badge: 'record' })!;
        const b = qrSvg(STAFF, { badge: 'location' })!;
        const glyph = (s: string) => /<g transform[^>]*><path d="([^"]+)"/.exec(s)?.[1];
        expect(glyph(a)).toBeTruthy();
        expect(glyph(b)).toBeTruthy();
        expect(glyph(a)).not.toBe(glyph(b));
    });

    it('keeps the hole clear of the corners, where the finder patterns live', () => {
        // A badge that reached a corner would destroy a finder pattern, which no
        // amount of error correction recovers -- the decoder would not locate the
        // symbol at all.
        const svg = qrSvg(STAFF, { badge: 'record' })!;
        const extent = Number(/viewBox="0 0 (\d+)/.exec(svg)![1]);
        const drawn = [...svg.matchAll(/M(\d+) (\d+)h1v1h-1z/g)]
            .map(m => ({ c: Number(m[1]), r: Number(m[2]) }));
        // The three finder corners still have modules drawn in them.
        const near = (r: number, c: number) => drawn.some(p => Math.abs(p.r - r) < 3 && Math.abs(p.c - c) < 3);
        expect(near(3, 3)).toBe(true);
        expect(near(3, extent - 4)).toBe(true);
        expect(near(extent - 4, 3)).toBe(true);
    });
});

describe('when it cannot encode', () => {
    it('returns null rather than an empty box', () => {
        expect(qrSvg('')).toBeNull();
        // Beyond the largest symbol at level H, so there is no code to draw.
        expect(qrSvg('x'.repeat(20000), { badge: 'record' })).toBeNull();
    });
});

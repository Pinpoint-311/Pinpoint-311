import { afterEach, describe, expect, it } from 'vitest';

import { markerSymbol } from './symbols';
import { clusterIcon, puckIcon } from '../../markerIcons';
import { MarkerIcon } from '../../types';

/**
 * What a PictureMarkerSymbol is handed, on a HiDPI screen.
 *
 * ArcGIS rasterises a picture marker once from the source image's intrinsic
 * size and then draws that raster at the symbol's CSS width/height. On a
 * `devicePixelRatio: 2` display that is twice as many device pixels as it
 * rasterised for, so a cluster bubble whose SVG says `width="52"` is stretched
 * across 104 device pixels and goes soft -- worse the larger the bubble, which
 * is why the cluster bubbles were what somebody noticed. Verified in a real
 * browser against demo.pinpoint311.org: the same cluster is crisp at
 * devicePixelRatio 1 and blurred at 2.
 *
 * These assert the two halves that have to hold together: the source image gets
 * bigger, and the *drawn* size does not. Getting only the first would grow every
 * marker on the map.
 */

const REAL_DPR = window.devicePixelRatio;

function setDpr(value: number): void {
    Object.defineProperty(window, 'devicePixelRatio', { value, configurable: true });
}

afterEach(() => setDpr(REAL_DPR));

/** Just enough of EsriModules for markerSymbol; each fake records its props. */
const mods: any = {
    PictureMarkerSymbol: class { constructor(public props: any) { } },
    SimpleMarkerSymbol: class { constructor(public props: any) { } },
};

/** MarkerIcon is a union; every icon in this file is the image arm. */
function imageUrl(icon: MarkerIcon): string {
    if (icon.type !== 'image') throw new Error('expected an image icon');
    return icon.url;
}

/** The `<svg>` element's own attributes, from a data URI. */
function rootAttributes(url: string): { width?: string; height?: string; viewBox?: string } {
    const markup = decodeURIComponent(url.slice(url.indexOf(',') + 1));
    const tag = (markup.match(/^\s*<svg\b[^>]*>/) || [''])[0];
    return {
        width: (tag.match(/\bwidth="([\d.]+)"/) || [])[1],
        height: (tag.match(/\bheight="([\d.]+)"/) || [])[1],
        viewBox: (tag.match(/viewBox="([^"]+)"/) || [])[1],
    };
}

describe('markerSymbol picture markers', () => {
    it('rasterises the image at device resolution while drawing it at CSS size', () => {
        setDpr(2);
        const icon = clusterIcon(100);          // 52px bubble, the largest one drawn
        const symbol = markerSymbol(mods, icon).props;

        expect(rootAttributes(imageUrl(icon))).toMatchObject({ width: '52', height: '52' });
        // The source image doubles...
        expect(rootAttributes(symbol.url)).toMatchObject({ width: '104', height: '104' });
        // ...the drawing does not.
        expect(symbol.width).toBe('52px');
        expect(symbol.height).toBe('52px');
    });

    it('keeps the viewBox, so nothing inside the image moves or rescales', () => {
        setDpr(3);
        const icon = puckIcon({ fill: '#4f46e5', size: 22 });
        const before = rootAttributes(imageUrl(icon));
        const after = rootAttributes(markerSymbol(mods, icon).props.url);

        expect(after.viewBox).toBe(before.viewBox);
        expect(after.width).toBe('66');
    });

    it('leaves the image untouched on a 1x display', () => {
        setDpr(1);
        const icon = clusterIcon(40);
        expect(markerSymbol(mods, icon).props.url).toBe(imageUrl(icon));
    });

    it('stops supersampling at 4x, so an exotic ratio cannot explode the texture', () => {
        setDpr(8);
        const icon = clusterIcon(100);
        expect(rootAttributes(markerSymbol(mods, icon).props.url).width).toBe('208');
    });

    it('does not touch an icon that is not an SVG data URI', () => {
        setDpr(2);
        // Asset layers can carry a PNG a town uploaded; rewriting markup we did
        // not author would be guesswork.
        const icon: MarkerIcon = { type: 'image', url: 'https://example.org/pin.png', width: 24, height: 24 };
        expect(markerSymbol(mods, icon).props.url).toBe(imageUrl(icon));
    });

    it('does not touch an SVG with no viewBox, whose size is its coordinate system', () => {
        setDpr(2);
        const raw = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><circle cx="10" cy="10" r="9"/></svg>';
        const icon: MarkerIcon = {
            type: 'image',
            url: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(raw)}`,
            width: 20,
            height: 20,
        };
        expect(markerSymbol(mods, icon).props.url).toBe(imageUrl(icon));
    });

    it('still centres the image on its anchor after the rewrite', () => {
        setDpr(2);
        // locationPinIcon anchors at the tip, not the centre; the offsets are
        // computed from MarkerIcon.width/height, which supersampling must not move.
        const icon: MarkerIcon = { type: 'image', url: imageUrl(clusterIcon(1)), width: 26, height: 36, anchor: { x: 13, y: 34.5 } };
        const symbol = markerSymbol(mods, icon).props;
        expect(symbol.xoffset).toBe('0px');
        expect(symbol.yoffset).toBe('16.5px');
    });
});

/**
 * MarkerIcon -> MapKit ImageAnnotation.
 *
 * MapKit has three annotation kinds: MarkerAnnotation (Apple's balloon pin,
 * styleable only by tint colour and a glyph), ImageAnnotation (an image at a
 * coordinate) and Annotation (a DOM factory). MarkerIcon's circle variant maps
 * onto none of them directly.
 *
 * A DOM Annotation would be the obvious route, but types.ts is explicit that
 * marker icons are data and never DOM, and DOM annotations are also the slowest
 * of the three at the marker counts a 311 map hits. So circles are rasterised
 * to an inline SVG data URI and fed to ImageAnnotation. That keeps one code
 * path for both MarkerIcon variants, and — usefully — lets a cluster's count be
 * baked straight into the artwork, which is the only way to get a label onto a
 * MapKit annotation that is not Apple's own balloon pin.
 */

import { MarkerIcon, MarkerLabel } from '../../types';

export interface RasterIcon {
    url: string;
    width: number;
    height: number;
    /** Pixel inside the image that sits on the coordinate. */
    anchorX: number;
    anchorY: number;
}

function escapeXml(value: string): string {
    return value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function svgDataUri(svg: string): string {
    // encodeURIComponent rather than base64: smaller, and readable in devtools.
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function circleIcon(icon: Extract<MarkerIcon, { type: 'circle' }>, label?: MarkerLabel): RasterIcon {
    const stroke = icon.strokeWidth ?? 0;
    // The stroke straddles the circle's edge, so half of it lies outside.
    const size = Math.ceil((icon.radius + stroke / 2) * 2);
    const centre = size / 2;

    const parts = [
        `<circle cx="${centre}" cy="${centre}" r="${icon.radius}"`,
        ` fill="${escapeXml(icon.fillColor)}" fill-opacity="${icon.fillOpacity ?? 1}"`,
        stroke ? ` stroke="${escapeXml(icon.strokeColor ?? '#ffffff')}" stroke-width="${stroke}"` : '',
        '/>',
    ];

    if (label?.text) {
        parts.push(
            `<text x="${centre}" y="${centre}" text-anchor="middle" dominant-baseline="central"`,
            ` font-family="sans-serif" font-size="${escapeXml(label.fontSize ?? '11px')}"`,
            ` font-weight="${escapeXml(label.fontWeight ?? 'bold')}"`,
            ` fill="${escapeXml(label.color ?? '#ffffff')}">${escapeXml(label.text)}</text>`,
        );
    }

    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">${parts.join('')}</svg>`;
    return { url: svgDataUri(svg), width: size, height: size, anchorX: centre, anchorY: centre };
}

export function rasterise(icon: MarkerIcon | undefined, label?: MarkerLabel): RasterIcon {
    if (!icon) {
        return circleIcon({ type: 'circle', radius: 6, fillColor: '#1d4ed8', strokeColor: '#ffffff', strokeWidth: 1 }, label);
    }
    if (icon.type === 'circle') return circleIcon(icon, label);

    // An image icon cannot have a MarkerLabel composited onto it without loading
    // and re-encoding the source image, so the label is dropped here and
    // surfaced as the annotation's accessible title instead. See renderer.ts.
    return {
        url: icon.url,
        width: icon.width,
        height: icon.height,
        anchorX: icon.anchor ? icon.anchor.x : icon.width / 2,
        anchorY: icon.anchor ? icon.anchor.y : icon.height / 2,
    };
}

/**
 * ImageAnnotation.anchorOffset is measured from the *bottom centre* of the
 * image, positive y downwards. Convert from MarkerIcon's top-left anchor.
 */
export function anchorOffset(icon: RasterIcon): { x: number; y: number } {
    return { x: icon.width / 2 - icon.anchorX, y: icon.height - icon.anchorY };
}

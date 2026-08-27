/**
 * MarkerIcon / VectorStyle -> ArcGIS symbol translation.
 *
 * Kept out of renderer.ts because the unit and anchor conventions differ from
 * Google's in ways that need explaining, and because both the GraphicsLayer and
 * the clustered FeatureLayer marker layers need the exact same translation.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

import { LatLng, LatLngBounds, MarkerIcon, MarkerLabel, VectorStyle } from '../../types';
import { EsriModules } from './loader';

/**
 * ArcGIS colours accept CSS strings, so the cheapest way to honour a separate
 * opacity is to fold it into an rgba() string. Symbol-level `opacity` does not
 * exist on 2D symbols, and Graphic has no opacity either — only whole layers do.
 */
export function withOpacity(color: string | undefined, opacity: number | undefined): string | undefined {
    if (!color) return undefined;
    if (opacity === undefined || opacity >= 1) return color;

    const hex = color.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (hex) {
        const raw = hex[1];
        const full = raw.length === 3 ? raw.split('').map(c => c + c).join('') : raw;
        const r = parseInt(full.slice(0, 2), 16);
        const g = parseInt(full.slice(2, 4), 16);
        const b = parseInt(full.slice(4, 6), 16);
        return `rgba(${r}, ${g}, ${b}, ${opacity})`;
    }

    const rgb = color.trim().match(/^rgba?\(([^)]+)\)$/i);
    if (rgb) {
        const parts = rgb[1].split(',').map(p => p.trim());
        const [r, g, b] = parts;
        return `rgba(${r}, ${g}, ${b}, ${opacity})`;
    }

    // Named colour or something exotic — ArcGIS will still parse the colour, we
    // just cannot pre-multiply the alpha into it.
    return color;
}

/**
 * ArcGIS rasterises a PictureMarkerSymbol once, from the source image's own
 * intrinsic size, and then draws that raster at `width`/`height` CSS pixels. On
 * a HiDPI screen those CSS pixels are `devicePixelRatio` device pixels, so a
 * 52px bubble rasterised at 52x52 is stretched over 104x104 and reads as soft.
 * It is worst on the largest symbols, which is why the cluster bubbles were the
 * ones somebody noticed: the bigger the bubble, the more of the screen the
 * blur covers. Google, Apple and Azure all resample per device pixel ratio
 * themselves -- Azure's icons.ts already says out loud that MarkerIcon's
 * width/height are the *rendered* size and the source image may be larger --
 * and Esri is the only provider that does not.
 *
 * PictureMarkerSymbol has no "rasterise at 2x" switch, so the one lever left is
 * the source image. Every marker in this product is an SVG data URI drawn in a
 * viewBox (see markerIcons.ts), so re-emitting the same markup with a larger
 * intrinsic width/height supersamples the raster without touching a single
 * coordinate. The symbol's own width/height stay in CSS pixels, so layout,
 * anchoring and every other provider are unaffected.
 */
const SVG_DATA_URI = /^data:image\/svg\+xml/;

/** Beyond 4x the texture cost stops buying visible sharpness. */
const MAX_SUPERSAMPLE = 4;

function supersampleFactor(): number {
    const ratio = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1;
    return Math.min(MAX_SUPERSAMPLE, Math.max(1, Math.ceil(ratio)));
}

export function supersampledIconUrl(url: string, factor: number): string {
    if (factor <= 1 || !SVG_DATA_URI.test(url)) return url;

    const comma = url.indexOf(',');
    if (comma < 0) return url;

    let markup: string;
    try {
        markup = decodeURIComponent(url.slice(comma + 1));
    } catch {
        // Base64 payload, or something we did not write. Leave it alone.
        return url;
    }

    const open = markup.match(/^\s*<svg\b[^>]*>/);
    if (!open) return url;
    const tag = open[0];

    // Without a viewBox the width and height *are* the coordinate system, and
    // enlarging them would enlarge the drawing rather than resample it.
    if (!/\bviewBox\s*=/.test(tag)) return url;

    const scaled = tag
        .replace(/\bwidth="([\d.]+)"/, (_m, v) => `width="${Number(v) * factor}"`)
        .replace(/\bheight="([\d.]+)"/, (_m, v) => `height="${Number(v) * factor}"`);
    if (scaled === tag) return url;

    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(scaled + markup.slice(tag.length))}`;
}

/**
 * Sizes are handed to ArcGIS as CSS px strings rather than bare numbers: a bare
 * number is interpreted as *points* and silently scaled by 4/3, which would make
 * every Esri marker a third larger than the same MarkerIcon on Google.
 */
export function markerSymbol(mods: EsriModules, icon: MarkerIcon | undefined): any {
    if (!icon) {
        return new mods.SimpleMarkerSymbol({
            style: 'circle',
            size: '12px',
            color: '#1d4ed8',
            outline: { color: '#ffffff', width: '1px' },
        });
    }

    if (icon.type === 'circle') {
        return new mods.SimpleMarkerSymbol({
            style: 'circle',
            // MarkerIcon.radius matches Google's SymbolPath.CIRCLE scale, which is
            // a radius; ArcGIS `size` is the full diameter.
            size: `${icon.radius * 2}px`,
            color: withOpacity(icon.fillColor, icon.fillOpacity),
            outline: icon.strokeWidth
                ? { color: icon.strokeColor ?? '#ffffff', width: `${icon.strokeWidth}px` }
                : { width: 0 },
        });
    }

    // PictureMarkerSymbol is centred on the geometry. MarkerIcon.anchor names the
    // pixel *inside the image* that should sit on the coordinate, so shift the
    // symbol by the difference. yoffset is positive upwards in ArcGIS.
    const ax = icon.anchor ? icon.anchor.x : icon.width / 2;
    const ay = icon.anchor ? icon.anchor.y : icon.height / 2;
    return new mods.PictureMarkerSymbol({
        url: supersampledIconUrl(icon.url, supersampleFactor()),
        width: `${icon.width}px`,
        height: `${icon.height}px`,
        xoffset: `${icon.width / 2 - ax}px`,
        yoffset: `${ay - icon.height / 2}px`,
    });
}

export function textSymbol(mods: EsriModules, label: MarkerLabel): any {
    return new mods.TextSymbol({
        text: label.text,
        color: label.color ?? '#ffffff',
        font: {
            size: label.fontSize ?? '11px',
            weight: (label.fontWeight as string) ?? 'normal',
            family: 'sans-serif',
        },
        horizontalAlignment: 'center',
        verticalAlignment: 'middle',
    });
}

export function fillSymbol(mods: EsriModules, style: VectorStyle | undefined): any {
    return new mods.SimpleFillSymbol({
        color: withOpacity(style?.fillColor ?? '#3b82f6', style?.fillOpacity ?? 0.2),
        outline: {
            color: withOpacity(style?.strokeColor ?? '#1d4ed8', style?.strokeOpacity),
            width: `${style?.strokeWidth ?? 2}px`,
        },
    });
}

export function lineSymbol(mods: EsriModules, style: VectorStyle | undefined): any {
    return new mods.SimpleLineSymbol({
        color: withOpacity(style?.strokeColor ?? '#1d4ed8', style?.strokeOpacity),
        width: `${style?.strokeWidth ?? 2}px`,
    });
}

/** Point symbol for a GeoJSON layer styled with a VectorStyle rather than an icon. */
export function pointSymbolFromStyle(mods: EsriModules, style: VectorStyle | undefined): any {
    return new mods.SimpleMarkerSymbol({
        style: 'circle',
        size: '8px',
        color: withOpacity(style?.fillColor ?? '#1d4ed8', style?.fillOpacity),
        outline: {
            color: withOpacity(style?.strokeColor ?? '#ffffff', style?.strokeOpacity),
            width: `${style?.strokeWidth ?? 1}px`,
        },
    });
}

/** Fully transparent symbols, for GeoJsonLayerOptions.pointRendering === 'hidden'. */
export function invisiblePointSymbol(mods: EsriModules): any {
    return new mods.SimpleMarkerSymbol({
        style: 'circle',
        size: '1px',
        color: 'rgba(0, 0, 0, 0)',
        outline: { width: 0 },
    });
}

// ---------------------------------------------------------------------------
// Geometry. The interface speaks WGS84 {lat,lng} only; every projection detail
// stays on this side of the boundary.
// ---------------------------------------------------------------------------

export function toEsriPoint(mods: EsriModules, position: LatLng): any {
    return new mods.Point({
        longitude: position.lng,
        latitude: position.lat,
        spatialReference: mods.SpatialReference.WGS84,
    });
}

/**
 * A MapView is normally Web Mercator, so `latitude`/`longitude` are populated
 * for free. They are null for any other spatial reference (a town whose basemap
 * is NJ State Plane, for instance), so fall back to an explicit unprojection.
 */
export function fromEsriPoint(mods: EsriModules, point: any): LatLng {
    if (!point) return { lat: 0, lng: 0 };
    if (typeof point.latitude === 'number' && typeof point.longitude === 'number') {
        return { lat: point.latitude, lng: point.longitude };
    }
    if (point.spatialReference?.isWebMercator) {
        const geo = mods.webMercatorUtils.webMercatorToGeographic(point);
        return { lat: geo.y, lng: geo.x };
    }
    // Already geographic (or an unsupported PCS we cannot unproject client-side).
    return { lat: point.y, lng: point.x };
}

export function fromEsriExtent(mods: EsriModules, extent: any): LatLngBounds | null {
    if (!extent) return null;
    const geo = extent.spatialReference?.isWebMercator
        ? mods.webMercatorUtils.webMercatorToGeographic(extent)
        : extent;
    if (!geo) return null;
    return { south: geo.ymin, west: geo.xmin, north: geo.ymax, east: geo.xmax };
}

export function toEsriExtent(mods: EsriModules, bounds: LatLngBounds): any {
    return new mods.Extent({
        xmin: bounds.west,
        ymin: bounds.south,
        xmax: bounds.east,
        ymax: bounds.north,
        spatialReference: mods.SpatialReference.WGS84,
    });
}

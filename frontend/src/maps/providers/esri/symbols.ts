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
        url: icon.url,
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

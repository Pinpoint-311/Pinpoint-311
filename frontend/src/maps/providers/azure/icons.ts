/**
 * MarkerIcon -> raster image, plus MarkerIcon -> DOM node.
 *
 * Azure Maps (a MapLibre fork) draws source-backed markers from a *named image
 * in a sprite* that a style expression points at. That is exactly what makes
 * MarkerIcon-as-data pay off: a `{type:'circle'}` description can be rasterised
 * here once, registered under a stable key, and referenced by a symbol layer
 * sitting on a clustered GeoJSON source — no DOM node per marker, no vendor
 * symbol type leaking into the interface.
 *
 * Nothing here imports a vendor SDK. Azure Maps is a MapLibre fork and this
 * rasterisation is identical work for both, so the Azure adapter imports this
 * module rather than duplicating it.
 */

import { MarkerIcon, MarkerLabel } from '../../types';

export interface ResolvedIcon {
    /** Stable sprite id derived from the icon description. */
    key: string;
    /** data: URI (or the original URL when the canvas could not be read). */
    url: string;
    /** Size in CSS pixels, i.e. the size the caller asked for. */
    width: number;
    height: number;
    pixelRatio: number;
    /** Point inside the image, in CSS pixels, that sits on the coordinate. */
    anchor: { x: number; y: number };
}

/**
 * Sprite ids must be stable across re-renders or every `setMarkers()` would
 * leak a new image into the style. Hashing the description gives that for free
 * and also dedupes the (very common) case of 500 markers sharing one icon.
 */
export function iconKey(icon: MarkerIcon, pixelRatio: number): string {
    const body = icon.type === 'circle'
        ? `c:${icon.radius}:${icon.fillColor}:${icon.fillOpacity ?? 1}:${icon.strokeColor ?? ''}:${icon.strokeWidth ?? 0}`
        : `i:${icon.width}x${icon.height}:${icon.anchor?.x ?? ''},${icon.anchor?.y ?? ''}:${icon.url}`;

    // djb2 over the description — short, collision-safe enough for a sprite id,
    // and keeps multi-kilobyte data: URIs out of the style JSON.
    let hash = 5381;
    for (let i = 0; i < body.length; i++) hash = ((hash << 5) + hash + body.charCodeAt(i)) | 0;
    return `pp-${icon.type}-${(hash >>> 0).toString(36)}-${pixelRatio}`;
}

function canvasOf(width: number, height: number, pixelRatio: number): HTMLCanvasElement {
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(width * pixelRatio));
    canvas.height = Math.max(1, Math.round(height * pixelRatio));
    return canvas;
}

export function loadImageElement(url: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
        const image = new Image();
        // Needed or toDataURL() on the scaling canvas throws for cross-origin
        // icons. Falls back to the untouched URL if the server refuses CORS.
        image.crossOrigin = 'anonymous';
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error(`Failed to load marker image: ${url}`));
        image.src = url;
    });
}

function drawCircle(icon: Extract<MarkerIcon, { type: 'circle' }>, pixelRatio: number): ResolvedIcon {
    const stroke = icon.strokeWidth ?? 0;
    // +2 CSS px of padding so the antialiased stroke edge is not clipped.
    const size = Math.ceil(icon.radius * 2 + stroke + 2);
    const canvas = canvasOf(size, size, pixelRatio);
    const ctx = canvas.getContext('2d')!;
    ctx.scale(pixelRatio, pixelRatio);

    const center = size / 2;
    ctx.beginPath();
    ctx.arc(center, center, icon.radius, 0, Math.PI * 2);
    ctx.globalAlpha = icon.fillOpacity ?? 1;
    ctx.fillStyle = icon.fillColor;
    ctx.fill();
    ctx.globalAlpha = 1;
    if (stroke > 0 && icon.strokeColor) {
        ctx.lineWidth = stroke;
        ctx.strokeStyle = icon.strokeColor;
        ctx.stroke();
    }

    return {
        key: iconKey(icon, pixelRatio),
        url: canvas.toDataURL('image/png'),
        width: size,
        height: size,
        pixelRatio,
        anchor: { x: center, y: center },
    };
}

async function drawImage(
    icon: Extract<MarkerIcon, { type: 'image' }>,
    pixelRatio: number,
): Promise<ResolvedIcon> {
    const key = iconKey(icon, pixelRatio);
    const anchor = icon.anchor ?? { x: icon.width / 2, y: icon.height / 2 };
    const base: ResolvedIcon = {
        key,
        url: icon.url,
        width: icon.width,
        height: icon.height,
        pixelRatio,
        anchor,
    };

    try {
        const image = await loadImageElement(icon.url);
        const canvas = canvasOf(icon.width, icon.height, pixelRatio);
        const ctx = canvas.getContext('2d')!;
        ctx.scale(pixelRatio, pixelRatio);
        // MarkerIcon.width/height are the *rendered* size; the source image can
        // be any size, so rescale here rather than relying on icon-size, which
        // would also scale the stroke of a retina asset.
        ctx.drawImage(image, 0, 0, icon.width, icon.height);
        return { ...base, url: canvas.toDataURL('image/png') };
    } catch {
        // Tainted canvas or a dead URL: hand the SDK the raw URL and let it
        // load the asset at its natural size. pixelRatio drops to 1 because
        // nothing was rescaled — claiming otherwise would halve the icon.
        return { ...base, pixelRatio: 1 };
    }
}

export function resolveIcon(icon: MarkerIcon, pixelRatio: number): Promise<ResolvedIcon> {
    if (icon.type === 'circle') return Promise.resolve(drawCircle(icon, pixelRatio));
    return drawImage(icon, pixelRatio);
}

/**
 * Symbol layers place an image by its centre, so an image icon's `anchor`
 * becomes a pixel offset from centre. Same maths on both SDKs.
 */
export function iconOffset(icon: ResolvedIcon): [number, number] {
    return [icon.width / 2 - icon.anchor.x, icon.height / 2 - icon.anchor.y];
}

export function parseFontSize(value: string | undefined, fallback: number): number {
    if (!value) return fallback;
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}

export interface DomMarkerContent {
    element: HTMLElement;
    /** Offset in CSS pixels to pass to the SDK's marker so the anchor lands right. */
    offset: [number, number];
}

/**
 * DOM rendering of the same MarkerIcon, used only by the *unclustered* marker
 * path (see renderer.ts for why that path exists at all).
 */
export function markerElement(
    icon: MarkerIcon | undefined,
    label: MarkerLabel | undefined,
    title: string | undefined,
): DomMarkerContent {
    const element = document.createElement('div');
    element.style.position = 'relative';
    element.style.lineHeight = '0';
    element.style.cursor = 'pointer';
    if (title) element.title = title;

    let offset: [number, number] = [0, 0];

    if (!icon || icon.type === 'circle') {
        const radius = icon?.type === 'circle' ? icon.radius : 8;
        const stroke = icon?.type === 'circle' ? (icon.strokeWidth ?? 0) : 0;
        const dot = document.createElement('div');
        dot.style.width = `${radius * 2}px`;
        dot.style.height = `${radius * 2}px`;
        dot.style.borderRadius = '50%';
        dot.style.boxSizing = 'content-box';
        dot.style.background = icon?.type === 'circle' ? icon.fillColor : '#2563eb';
        dot.style.opacity = String(icon?.type === 'circle' ? (icon.fillOpacity ?? 1) : 1);
        if (stroke > 0 && icon?.type === 'circle' && icon.strokeColor) {
            dot.style.border = `${stroke}px solid ${icon.strokeColor}`;
            dot.style.margin = `${-stroke}px`;
        }
        element.appendChild(dot);
    } else {
        const img = document.createElement('img');
        img.src = icon.url;
        img.width = icon.width;
        img.height = icon.height;
        img.style.display = 'block';
        img.draggable = false;
        element.appendChild(img);
        const anchor = icon.anchor;
        if (anchor) offset = [icon.width / 2 - anchor.x, icon.height / 2 - anchor.y];
    }

    if (label?.text) {
        const span = document.createElement('span');
        span.textContent = label.text;
        span.style.position = 'absolute';
        span.style.inset = '0';
        span.style.display = 'flex';
        span.style.alignItems = 'center';
        span.style.justifyContent = 'center';
        span.style.pointerEvents = 'none';
        span.style.color = label.color ?? '#ffffff';
        span.style.fontSize = label.fontSize ?? '12px';
        span.style.fontWeight = label.fontWeight ?? '600';
        span.style.lineHeight = '1';
        element.appendChild(span);
    }

    return { element, offset };
}

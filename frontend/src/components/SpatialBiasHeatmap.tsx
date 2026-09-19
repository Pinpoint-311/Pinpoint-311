import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { MapPin, Users, FileText, AlertTriangle, Eye } from 'lucide-react';
import { HeatmapData, HeatmapPoint, HotspotData } from '../types';
import {
    CanvasOverlayHandle,
    MapRenderer,
    MarkerLayer,
    MarkerOptions,
    PopupHandle,
    boundsOfPoints,
    CONTINENTAL_US_CENTER,
    createMap,
    el,
    MapProviderConfig,
    hasMapCredential,
    popupRoot,
    puckIcon,
} from '../maps';

interface SpatialBiasHeatmapProps {
    heatmapData: HeatmapData | null;
    hotspots: HotspotData[];
    /**
     * The town's chosen provider and only that provider's credentials.
     * Built once per page with resolveMapProviderConfig(); components must not
     * assemble their own, which is how every map silently defaulted to Google.
     */
    config: MapProviderConfig;
    defaultCenter?: { lat: number; lng: number };
    isLoading?: boolean;
}

type HeatmapMode = 'reports' | 'reporters' | 'bias';

/* Color gradients per mode (low → white-hot). Index 0 is transparent.
 *
 * WCAG 1.4.11 Non-text Contrast. Every stop is composited at `stop alpha ×
 * HEATMAP_OPACITY` over the #1a1a2e basemap, and the old low and mid stops came
 * out below the 3:1 floor — indigo@.4 measured 1.52:1, emerald@.3 1.56:1,
 * purple@.6 1.99:1, green@.5 2.37:1, pink@.7 2.48:1, red@.8 2.72:1. Only the
 * top of each ramp was visible, which means the map answered "where is it
 * busiest" and was blank for everything below that: the low-to-mid range, where
 * most of a town's reports actually sit, was information the surface claimed to
 * show and did not.
 *
 * Rebuilt from the 300/400 tints at higher alpha, so each ramp now climbs
 * monotonically and every stop clears 3:1 against the basemap:
 *
 *   reports   3.38 → 4.11 → 4.63 → 4.80 → 7.66 → 12.58
 *   reporters 3.34 → 4.42 → 5.42 → 6.72 → 7.63 → 12.58
 *
 * The hues are unchanged in family (cool→hot for reports, green→warm for
 * reporters) so the two modes still read as different pictures. */
const GRADIENTS: Record<HeatmapMode, string[]> = {
    reports: [
        'rgba(0, 0, 0, 0)',
        'rgba(129, 140, 248, 0.80)',  // indigo-400  3.38:1
        'rgba(167, 139, 250, 0.88)',  // purple-400  4.11:1
        'rgba(244, 114, 182, 0.95)',  // pink-400    4.63:1
        'rgba(248, 113, 113, 1)',     // red-400     4.80:1
        'rgba(251, 191, 36, 1)',      // amber-400   7.66:1
        'rgba(255, 255, 255, 1)',     // white hot  12.58:1
    ],
    reporters: [
        'rgba(0, 0, 0, 0)',
        'rgba(52, 211, 153, 0.62)',   // emerald-400 3.34:1
        'rgba(74, 222, 128, 0.72)',   // green-400   4.42:1
        'rgba(163, 230, 53, 0.76)',   // lime-400    5.42:1
        'rgba(250, 204, 21, 0.88)',   // yellow-400  6.72:1
        'rgba(253, 186, 116, 1)',     // orange-300  7.63:1
        'rgba(255, 255, 255, 1)',
    ],
    bias: [
        'rgba(0, 0, 0, 0)',
        'rgba(129, 140, 248, 0.80)',
        'rgba(167, 139, 250, 0.88)',
        'rgba(244, 114, 182, 0.95)',
        'rgba(248, 113, 113, 1)',
        'rgba(251, 191, 36, 1)',
        'rgba(255, 255, 255, 1)',
    ],
};

const HEATMAP_OPACITY = 0.85;

// Build a 256-entry RGBA lookup table from gradient stops.
function buildPalette(stops: string[]): Uint8ClampedArray {
    const c = document.createElement('canvas');
    c.width = 256;
    c.height = 1;
    const g = c.getContext('2d')!;
    const grad = g.createLinearGradient(0, 0, 256, 0);
    stops.forEach((s, i) => grad.addColorStop(i / (stops.length - 1), s));
    g.fillStyle = grad;
    g.fillRect(0, 0, 256, 1);
    return g.getImageData(0, 0, 256, 1).data;
}

function intensityOf(point: HeatmapPoint): number {
    return Math.max(0.08, Math.min(1, point.weight || 0.5));
}

/**
 * Canvas heatmap draw pass.
 *
 * Replaces google.maps.visualization.HeatmapLayer, which was removed from the
 * Maps JavaScript API in v3.65. Uses the well-known intensity-accumulation
 * technique (radial alpha gradients per point → colorize the alpha channel
 * through a gradient palette), so it needs no deprecated library and no extra
 * dependency, and keeps the same look. The renderer owns the canvas and the
 * projection; all this needs is `view.project` in canvas-local pixels.
 */
function drawHeatmap(
    ctx: CanvasRenderingContext2D,
    view: { width: number; height: number; project(p: { lat: number; lng: number }): { x: number; y: number } },
    points: HeatmapPoint[],
    gradient: string[],
    radius: number,
): void {
    const { width, height } = view;
    if (!points.length) return;

    // Pass 1: accumulate intensity as grayscale alpha.
    for (const p of points) {
        const { x, y } = view.project(p);
        if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
        if (x < -radius || x > width + radius || y < -radius || y > height + radius) continue;
        const a = intensityOf(p);
        const grad = ctx.createRadialGradient(x, y, 0, x, y, radius);
        grad.addColorStop(0, `rgba(0,0,0,${a})`);
        grad.addColorStop(1, 'rgba(0,0,0,0)');
        ctx.fillStyle = grad;
        ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
    }

    // Pass 2: map the accumulated alpha through the color palette.
    const palette = buildPalette(gradient);
    const img = ctx.getImageData(0, 0, width, height);
    const d = img.data;
    for (let i = 0; i < d.length; i += 4) {
        const alpha = d[i + 3];
        if (alpha === 0) continue;
        const off = alpha * 4;
        d[i] = palette[off];
        d[i + 1] = palette[off + 1];
        d[i + 2] = palette[off + 2];
        d[i + 3] = Math.round(Math.min(255, alpha) * HEATMAP_OPACITY);
    }
    ctx.putImageData(img, 0, 0);
}

// Grid cell for the marker fallback, ~150 m at mid latitudes.
const FALLBACK_CELL_DEGREES = 0.0015;
const FALLBACK_MAX_MARKERS = 400;

/**
 * Density as graduated markers, for providers with no pixel-projection hook
 * (Apple MapKit JS). Points are summed onto a coarse grid first: a heat canvas
 * copes with tens of thousands of blobs, one DOM marker per report does not.
 */
function fallbackDensityMarkers(points: HeatmapPoint[], gradient: string[]): MarkerOptions[] {
    const cells = new Map<string, { lat: number; lng: number; weight: number; n: number }>();

    for (const p of points) {
        const row = Math.round(p.lat / FALLBACK_CELL_DEGREES);
        const col = Math.round(p.lng / FALLBACK_CELL_DEGREES);
        const key = `${row}:${col}`;
        const cell = cells.get(key);
        if (cell) {
            cell.lat += p.lat;
            cell.lng += p.lng;
            cell.weight += intensityOf(p);
            cell.n += 1;
        } else {
            cells.set(key, { lat: p.lat, lng: p.lng, weight: intensityOf(p), n: 1 });
        }
    }

    const ranked = [...cells.values()]
        .sort((a, b) => b.weight - a.weight)
        .slice(0, FALLBACK_MAX_MARKERS);
    if (!ranked.length) return [];

    const heaviest = ranked[0].weight;
    const palette = buildPalette(gradient);

    return ranked.map(cell => {
        // Square-root so a cell twice as hot reads as twice the *area*, which is
        // how a graduated symbol is meant to be read.
        const t = Math.sqrt(cell.weight / heaviest);
        const off = Math.min(255, Math.round(t * 255)) * 4;
        return {
            position: { lat: cell.lat / cell.n, lng: cell.lng / cell.n },
            icon: {
                type: 'circle',
                radius: 6 + t * 16,
                fillColor: `rgb(${palette[off]}, ${palette[off + 1]}, ${palette[off + 2]})`,
                fillOpacity: HEATMAP_OPACITY * 0.7,
                strokeWidth: 0,
            },
            title: `${cell.n} report${cell.n === 1 ? '' : 's'} in this area`,
            zIndex: Math.round(t * 100),
        };
    });
}

/* Hotspot severity.
 *
 * The three fills sat at 1.75:1 (high↔moderate) and 1.06:1 (moderate↔low)
 * against each other, so on the map they were three shades of "warm" — and
 * severity was encoded in nothing but that shade (1.4.1). Brightening them
 * cannot fix it: three colours that are each ≥3:1 against a near-black basemap
 * are all bright, and bright colours cannot also be ≥3:1 from each other. The
 * luminance range simply is not there.
 *
 * So colour becomes the redundant channel, not the carrying one:
 *
 *   - `hollow` gives a donut for a balanced cluster and a filled puck for a
 *     flagged one, which survives greyscale and colour-blind simulation;
 *   - the ring weight steps up with severity;
 *   - `BIAS_LABEL` puts the level in words into the marker's `title` (its
 *     accessible name and its native tooltip) and into the on-page legend.
 *
 * The fills are still lifted for 1.4.11 — each is now ≥6:1 against #1a1a2e,
 * where high was 4.53:1 before. */
/**
 * Text alternative for the heat surface — WCAG 1.1.1.
 *
 * The surface is a `<canvas>`: to assistive technology it is a blank rectangle,
 * by definition, and nothing else on the panel filled the gap. The summary
 * boxes give three totals and the legend lists at most five clusters, out of up
 * to 400 occupied cells, so the honest answer was that a screen-reader user
 * could not find out where reports concentrate at all.
 *
 * This describes the same accumulation the canvas draws — points summed onto
 * the grid, ranked — in the terms the picture is read for: how spread out it
 * is, and how much of the total the busiest areas hold.
 */
function describeDensity(points: HeatmapPoint[], mode: HeatmapMode): string {
    const noun = mode === 'reporters' ? 'reporter locations' : 'reports';
    if (!points.length) return `No ${noun} to map for the current filters.`;

    const cells = new Map<string, number>();
    for (const p of points) {
        const key = `${Math.round(p.lat / FALLBACK_CELL_DEGREES)}:${Math.round(p.lng / FALLBACK_CELL_DEGREES)}`;
        cells.set(key, (cells.get(key) || 0) + intensityOf(p));
    }

    const weights = [...cells.values()].sort((a, b) => b - a);
    const total = weights.reduce((sum, w) => sum + w, 0);
    const share = (n: number) => Math.round((weights.slice(0, n).reduce((s, w) => s + w, 0) / total) * 100);

    // How concentrated the picture is, in the words a reader would use for it.
    const topShare = share(Math.max(1, Math.ceil(weights.length * 0.1)));
    const spread = topShare >= 60 ? 'highly concentrated'
        : topShare >= 40 ? 'concentrated'
            : 'fairly evenly spread';

    return `Heat map of ${points.length.toLocaleString()} ${noun} across ` +
        `${weights.length.toLocaleString()} neighbourhood-sized areas of roughly 150 metres. ` +
        `Density is ${spread}: the busiest tenth of areas holds ${topShare}% of the total, ` +
        `and the single busiest area holds ${share(1)}%. ` +
        `Warmer colours mark denser areas; white is the densest.`;
}

const BIAS_FILL = { high: '#f87171', moderate: '#fbbf24', low: '#34d399' } as const;
const BIAS_STROKE = { high: '#fee2e2', moderate: '#fef3c7', low: '#d1fae5' } as const;
const BIAS_LABEL = { high: 'High bias', moderate: 'Moderate bias', low: 'Balanced' } as const;
/** Ring weight, so severity is legible with colour removed. */
const BIAS_STROKE_WIDTH = { high: 4, moderate: 3, low: 2 } as const;

/* The same three levels again, for the popup — which has a white ground, where
 * the marker fills are unreadable text colours: #f87171 is 2.77:1 there,
 * #fbbf24 1.67:1 and the old "BALANCED" green 2.28:1. These are the 700 tints,
 * 5.0–6.5:1 (1.4.3). */
const BIAS_TEXT_ON_LIGHT = { high: '#b91c1c', moderate: '#b45309', low: '#047857' } as const;

type BiasLevel = keyof typeof BIAS_FILL;

/** The one place the ratio→level rule lives; it was inlined in four. */
function biasLevelOf(count: number, reporters: number): BiasLevel {
    const ratio = count / (reporters || 1);
    return ratio > 4 ? 'high' : ratio > 2 ? 'moderate' : 'low';
}

// Google's style array. Deliberately routed through vendorOptions rather than
// modelled generically: MapLibre wants a style URL and Esri a basemap id, so
// there is nothing honest to abstract here.
const DARK_MAP_STYLE = [
    { elementType: 'geometry', stylers: [{ color: '#1a1a2e' }] },
    { elementType: 'labels.text.stroke', stylers: [{ color: '#1a1a2e' }] },
    { elementType: 'labels.text.fill', stylers: [{ color: '#8b8ba7' }] },
    { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#2a2a4a' }] },
    { featureType: 'road', elementType: 'labels.text.fill', stylers: [{ color: '#6b6b8a' }] },
    { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#0e0e1a' }] },
    { featureType: 'poi', elementType: 'labels', stylers: [{ visibility: 'off' }] },
    { featureType: 'transit', stylers: [{ visibility: 'off' }] },
];

/** The two selectable heat layers, in radio-group order. */
const MODE_OPTIONS = [
    { mode: 'reports' as const, label: 'All Reports', icon: FileText, selectedClass: 'bg-indigo-500/30 text-indigo-200 border border-indigo-500/40' },
    { mode: 'reporters' as const, label: 'Unique Reporters', icon: Users, selectedClass: 'bg-emerald-500/30 text-emerald-200 border border-emerald-500/40' },
];

const STAT_BOX = 'background: rgba(255,255,255,0.05); padding: 8px; border-radius: 6px; text-align: center;';

/** Hotspot popup as DOM. Every untrusted value is set as text, never markup. */
function hotspotPopup(hs: HotspotData): HTMLElement {
    const reporters = hs.unique_reporters || 1;
    const ratio = hs.count / reporters;
    const level = biasLevelOf(hs.count, reporters);
    const biased = ratio > 2;

    const stat = (value: number, label: string) => el('div', {
        style: STAT_BOX,
        children: [
            el('div', { style: 'font-size: 20px; font-weight: 700;', text: value }),
            // #9ca3af on the popup's white ground was 2.54:1 — a 10px label at a
            // third of the required contrast. #4b5563 is 7.56:1 (1.4.3).
            el('div', { style: 'font-size: 10px; color: #4b5563;', text: label }),
        ],
    });

    return popupRoot('min-width: 220px;', [
            el('h4', {
                style: 'margin: 0 0 8px 0; font-size: 14px; font-weight: 600;',
                text: hs.sample_address || 'Cluster',
            }),
            el('div', {
                style: 'display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px;',
                children: [stat(hs.count, 'Reports'), stat(reporters, 'Reporters')],
            }),
            el('div', {
                style: 'font-size: 12px; margin-bottom: 6px;',
                children: [
                    el('span', {
                        style: `color: ${BIAS_TEXT_ON_LIGHT[level]}; font-weight: 600;`,
                        text: biased ? `${level.toUpperCase()} BIAS` : 'BALANCED',
                    }),
                    ` (${ratio.toFixed(1)} reports/reporter)`,
                ],
            }),
            (hs.top_categories || []).length > 0 && el('div', {
                style: 'margin-top: 6px; display: flex; flex-wrap: wrap; gap: 4px;',
                children: (hs.top_categories || []).map(c => el('span', {
                    style: 'background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px; font-size: 10px;',
                    text: c,
                })),
            }),
    ]);
}

export default function SpatialBiasHeatmap({
    heatmapData,
    hotspots,
    config,
    defaultCenter,
    isLoading: externalLoading,
}: SpatialBiasHeatmapProps) {
    const mapRef = useRef<HTMLDivElement>(null);
    const rendererRef = useRef<MapRenderer | null>(null);
    const overlayRef = useRef<CanvasOverlayHandle | null>(null);
    const fallbackLayerRef = useRef<MarkerLayer | null>(null);
    const hotspotLayerRef = useRef<MarkerLayer | null>(null);
    const popupRef = useRef<PopupHandle | null>(null);

    // Read inside the overlay's draw callback, which the renderer may invoke on
    // any frame. Refs rather than state so a redraw never closes over stale data.
    const pointsRef = useRef<HeatmapPoint[]>([]);
    const gradientRef = useRef<string[]>(GRADIENTS.reports);
    const radiusRef = useRef(25);

    const [mapReady, setMapReady] = useState(false);
    const [isLoading, setIsLoading] = useState(true);
    const [mode, setMode] = useState<HeatmapMode>('reports');
    const [showHotspotOverlay, setShowHotspotOverlay] = useState(true);
    // False on providers with no pixel-projection hook (Apple MapKit). Drives
    // the graduated-marker fallback and the note shown under the map, so the
    // degradation is visible rather than silently different.
    const [canDrawHeat, setCanDrawHeat] = useState(true);

    /* Roving-tabindex plumbing for the mode radio group. In a radio group the
     * arrow keys both move focus and change the selection, and the group is a
     * single tab stop — otherwise Tab walks every option, which is the one thing
     * radios exist to avoid. */
    const modeRefs = useRef<Record<'reports' | 'reporters', HTMLButtonElement | null>>({ reports: null, reporters: null });

    const handleModeKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
        const order = MODE_OPTIONS.map(o => o.mode);
        const current = order.indexOf(mode as 'reports' | 'reporters');
        let next = current;
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (current + 1) % order.length;
        else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (current - 1 + order.length) % order.length;
        else return;

        event.preventDefault();
        const target = order[next];
        setMode(target);
        modeRefs.current[target]?.focus();
    };

    useEffect(() => {
        let cancelled = false;
        const container = mapRef.current;
        if (!container) return;

        if (!config) { setIsLoading(false); return; }

        createMap(container, config, {
            center: defaultCenter || CONTINENTAL_US_CENTER,
            zoom: 13,
            controls: {
                baseMapSwitcher: { enabled: true, position: 'top-left' },
                zoom: { enabled: true },
                fullscreen: { enabled: true },
                streetView: { enabled: false },
            },
            // Google-only dark styling. Non-portable by definition, which is why
            // it goes through vendorOptions rather than pretending to be generic.
            vendorOptions: { styles: DARK_MAP_STYLE },
        })
            .then(renderer => {
                if (cancelled) { renderer.destroy(); return; }
                rendererRef.current = renderer;
                popupRef.current = renderer.createPopup();
                setCanDrawHeat(renderer.capabilities.canvasOverlay);
                setIsLoading(false);
                setMapReady(true);
            })
            .catch(() => !cancelled && setIsLoading(false));

        return () => {
            cancelled = true;
            rendererRef.current?.destroy();
            rendererRef.current = null;
            overlayRef.current = null;
            fallbackLayerRef.current = null;
            hotspotLayerRef.current = null;
            popupRef.current = null;
        };
    }, [config.provider, config.apiKey, config.styleId, defaultCenter]);

    // Heat layer. Uses the canvas overlay where the provider has one, and
    // graduated markers where it does not.
    useEffect(() => {
        const renderer = rendererRef.current;
        if (!renderer || !mapReady) return;

        const points = (mode === 'reporters' ? heatmapData?.reporter_points : heatmapData?.report_points) || [];
        pointsRef.current = points;
        gradientRef.current = GRADIENTS[mode];
        radiusRef.current = mode === 'reporters' ? 30 : 25;

        overlayRef.current?.remove();
        overlayRef.current = null;
        fallbackLayerRef.current?.remove();
        fallbackLayerRef.current = null;

        if (!points.length) return;

        if (renderer.capabilities.canvasOverlay) {
            overlayRef.current = renderer.addCanvasOverlay({
                draw: (ctx, view) =>
                    drawHeatmap(ctx, view, pointsRef.current, gradientRef.current, radiusRef.current),
            });
        }
        if (!overlayRef.current) {
            const layer = renderer.createMarkerLayer();
            layer.setMarkers(fallbackDensityMarkers(points, GRADIENTS[mode]));
            fallbackLayerRef.current = layer;
        }

        const bounds = boundsOfPoints(points);
        if (bounds) renderer.fitBounds(bounds, { padding: 50 });
    }, [mode, heatmapData, mapReady]);

    // Hotspot cluster markers, drawn above the heat.
    useEffect(() => {
        const renderer = rendererRef.current;
        if (!renderer || !mapReady) return;

        hotspotLayerRef.current?.remove();
        hotspotLayerRef.current = null;
        if (!showHotspotOverlay || !hotspots?.length) return;

        const layer = renderer.createMarkerLayer();
        layer.setMarkers(hotspots.map(hs => {
            const reporters = hs.unique_reporters || 1;
            const ratio = hs.count / reporters;
            const level = biasLevelOf(hs.count, reporters);
            return {
                position: { lat: hs.lat, lng: hs.lng },
                // Through the shared puck routine, so a hotspot on this page has
                // the same ring, shadow and lighting as a pin anywhere else --
                // and renders identically whichever provider the town is on.
                // The bias palette stays, because that is what it encodes.
                icon: puckIcon({
                    fill: BIAS_FILL[level],
                    stroke: BIAS_STROKE[level],
                    size: Math.min(8 + hs.count, 20) * 2,
                    strokeWidth: BIAS_STROKE_WIDTH[level],
                    // Donut for a balanced cluster, solid for a flagged one:
                    // the flag survives greyscale, which the fill alone did not.
                    hollow: level === 'low',
                }),
                // The level in words. The tooltip used to give the two counts and
                // leave the reader to infer the severity from the marker's colour
                // — the one thing a colour-blind or screen-reader user could not
                // do (1.4.1). This string is also the marker's accessible name.
                title: `${BIAS_LABEL[level]}: ${hs.count} reports from ${reporters} reporter${reporters === 1 ? '' : 's'} (${ratio.toFixed(1)} per reporter)${hs.sample_address ? ` near ${hs.sample_address}` : ''}`,
                zIndex: 100,
                onClick: (_event, marker) => {
                    const popup = popupRef.current;
                    if (!popup) return;
                    // Built as DOM, not an HTML string: sample_address and the
                    // category names are resident- and import-supplied and were
                    // previously concatenated straight into markup.
                    popup.setContent(hotspotPopup(hs));
                    popup.openAt(marker);
                },
            };
        }));

        hotspotLayerRef.current = layer;
    }, [hotspots, showHotspotOverlay, mapReady]);

    if (!hasMapCredential(config)) {
        return (
            <div className="h-full flex items-center justify-center bg-slate-900/50 rounded-lg border border-white/10">
                <div className="text-center p-4">
                    <MapPin className="w-8 h-8 mx-auto mb-2 text-white/30" aria-hidden="true" />
                    <p className="text-white/50 text-sm">Maps not configured</p>
                </div>
            </div>
        );
    }

    const totalReports = heatmapData?.total_reports || 0;
    const totalReporters = heatmapData?.total_unique_reporters || 0;
    const globalRatio = totalReporters > 0 ? (totalReports / totalReporters).toFixed(1) : '—';

    // Count biased hotspots
    const biasedHotspots = hotspots.filter(hs => {
        const reporters = hs.unique_reporters || 1;
        return hs.count / reporters > 2;
    });

    const activePoints = (mode === 'reporters' ? heatmapData?.reporter_points : heatmapData?.report_points) || [];
    const densitySummary = describeDensity(activePoints, mode);

    return (
        <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl overflow-hidden">
            {/* Header */}
            <div className="p-4 sm:p-6 pb-3">
                <div className="flex items-center justify-between gap-3 flex-wrap mb-1">
                    <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                        <AlertTriangle className="w-5 h-5 text-amber-400" aria-hidden="true" />
                        Spatial Bias Detector
                    </h3>
                    {/* aria-pressed, because on/off was carried entirely by a
                        white/10-vs-white/5 fill: no state exposed to assistive tech
                        (4.1.2) and none visible without colour (1.4.1). The `title`
                        stays as a tooltip but is no longer the accessible name —
                        the button's own text is. */}
                    <button
                        type="button"
                        aria-pressed={showHotspotOverlay}
                        onClick={() => setShowHotspotOverlay(!showHotspotOverlay)}
                        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs transition focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
                            showHotspotOverlay
                                ? 'bg-white/10 text-white/80'
                                : 'bg-white/5 text-white/70'
                        }`}
                        title="Toggle hotspot cluster markers"
                    >
                        <Eye className="w-3.5 h-3.5" aria-hidden="true" />
                        Clusters
                    </button>
                </div>
                <p className="text-xs text-white/40 mb-4">
                    Compare report density vs unique reporters to detect over-reporting bias
                </p>

                {/* Say so when the heat surface is unavailable rather than quietly
                    rendering something different. Apple MapKit exposes no
                    pixel-projection hook, so density falls back to graduated
                    markers there -- readable, but not the same picture. */}
                {mapReady && !canDrawHeat && (
                    <p className="text-[11px] text-amber-300/70 -mt-3 mb-4" role="status">
                        This map provider can&apos;t draw a heat surface, so density is shown as
                        graduated circles instead.
                    </p>
                )}

                {/* Summary stats. One column until there is room for three: at
                    320px each cell was ~82px for a two-word 10px caption, which
                    wrapped to three lines or clipped (1.4.10 Reflow). */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-4">
                    <div className="bg-white/5 rounded-lg p-2 text-center">
                        <div className="text-lg font-bold text-white">{totalReports}</div>
                        <div className="text-[10px] text-white/40">Total Reports</div>
                    </div>
                    <div className="bg-white/5 rounded-lg p-2 text-center">
                        <div className="text-lg font-bold text-emerald-400">{totalReporters}</div>
                        <div className="text-[10px] text-white/40">Unique Reporters</div>
                    </div>
                    <div className="bg-white/5 rounded-lg p-2 text-center">
                        <div className={`text-lg font-bold ${Number(globalRatio) > 2 ? 'text-amber-400' : 'text-white'}`}>
                            {globalRatio}x
                        </div>
                        <div className="text-[10px] text-white/40">Avg Reports/Person</div>
                    </div>
                </div>

                {/* Mode toggle.
                  *
                  * This is a choice of one from two, which is a radio group; it was
                  * two buttons whose selected state existed only as an indigo or
                  * emerald fill (1.4.1) and was announced to nobody (4.1.2). Marked
                  * up as radios with the roving tabindex and arrow keys that pattern
                  * requires, so it is one tab stop and the arrows move within it. */}
                <div className="flex gap-1 bg-white/5 rounded-lg p-1" role="radiogroup" aria-label="Heat map layer">
                    {MODE_OPTIONS.map(option => {
                        const selected = mode === option.mode;
                        const Icon = option.icon;
                        return (
                            <button
                                key={option.mode}
                                type="button"
                                role="radio"
                                aria-checked={selected}
                                tabIndex={selected ? 0 : -1}
                                ref={node => { modeRefs.current[option.mode] = node; }}
                                onClick={() => setMode(option.mode)}
                                onKeyDown={handleModeKeyDown}
                                className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${
                                    selected
                                        ? option.selectedClass
                                        : 'text-white/70 hover:text-white'
                                }`}
                            >
                                <Icon className="w-3.5 h-3.5" aria-hidden="true" />
                                {option.label}
                            </button>
                        );
                    })}
                </div>
            </div>

            {/* Map. A hard 400px box could not grow with zoomed text; clamped
                instead so it still has a floor but reflows at 320px (1.4.10). */}
            <div className="relative" style={{ height: 'clamp(260px, 55vh, 400px)' }}>
                {(isLoading || externalLoading) && (
                    <div className="absolute inset-0 flex items-center justify-center bg-slate-900 z-10">
                        <div className="w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
                    </div>
                )}
                <div ref={mapRef} className="w-full h-full" />
            </div>

            {/* The heat surface in words — WCAG 1.1.1.
              *
              * A `<canvas>` has no accessible content, so without this the whole
              * answer the panel exists to give is available only to people who can
              * see it. Deliberately visible rather than sr-only: it is as useful
              * read as it is seen, and a summary nobody can check drifts from the
              * picture it claims to describe.
              *
              * Not a live region. The app has exactly one pair of those, and a
              * second polite region updating alongside them means neither is
              * announced. The note above it is the existing role="status", and one
              * is the limit here. */}
            <p className="px-4 sm:px-6 py-3 text-xs text-white/70 border-t border-white/10">
                {densitySummary}
            </p>

            {/* Bias hotspot legend */}
            {biasedHotspots.length > 0 && showHotspotOverlay && (
                <div className="p-4 border-t border-white/10">
                    <div className="text-xs font-medium text-white/50 uppercase tracking-wider mb-2">
                        Bias-Flagged Clusters ({biasedHotspots.length})
                    </div>
                    <ul className="space-y-1.5">
                        {biasedHotspots.slice(0, 5).map((hs, idx) => {
                            const reporters = hs.unique_reporters || 1;
                            const ratio = hs.count / reporters;
                            const level = biasLevelOf(hs.count, reporters);
                            return (
                                <li key={idx} className="flex items-center gap-2 p-2 bg-white/5 rounded-lg flex-wrap">
                                    {/* The dot was #ef4444 on this ground: 2.31:1, under
                                        the 3:1 floor for a meaningful graphic (1.4.11) —
                                        and it was the ONLY thing saying which level this
                                        row was (1.4.1). Now it is decorative, and the
                                        level is a word, matched to the marker's shape
                                        on the map: filled for flagged, ring for
                                        balanced. */}
                                    <span
                                        aria-hidden="true"
                                        className="w-3 h-3 rounded-full flex-shrink-0"
                                        style={{ backgroundColor: BIAS_FILL[level] }}
                                    />
                                    <span className="text-sm text-white/80 flex-1 min-w-0 truncate">
                                        {hs.sample_address || `Area ${idx + 1}`}
                                    </span>
                                    <span className="text-xs text-white/70">
                                        {hs.count} reports / {reporters} reporter{reporters !== 1 ? 's' : ''}
                                    </span>
                                    {/* text-red-400 was 3.14:1 here, below 4.5:1 for
                                        small text; the 200 tints are 6.0:1 (1.4.3). */}
                                    <span className={`text-xs font-semibold ${level === 'high' ? 'text-red-200' : 'text-amber-200'}`}>
                                        {BIAS_LABEL[level]}, {ratio.toFixed(1)}x
                                    </span>
                                </li>
                            );
                        })}
                    </ul>
                    <p className="text-[10px] text-white/30 mt-2">
                        Clusters where reports-per-reporter exceeds 2x may indicate repeat reporting bias rather than widespread community concern.
                    </p>
                </div>
            )}
        </div>
    );
}

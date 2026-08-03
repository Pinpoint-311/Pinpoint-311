import { useEffect, useRef, useState } from 'react';
import { MapPin, Users, FileText, AlertTriangle, Eye } from 'lucide-react';
import { HeatmapData, HeatmapPoint, HotspotData } from '../types';
import {
    CanvasOverlayHandle,
    MapRenderer,
    MarkerLayer,
    MarkerOptions,
    PopupHandle,
    boundsOfPoints,
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

// Color gradients per mode (low → white-hot). Index 0 is transparent.
const GRADIENTS: Record<HeatmapMode, string[]> = {
    reports: [
        'rgba(0, 0, 0, 0)',
        'rgba(99, 102, 241, 0.4)',   // indigo
        'rgba(139, 92, 246, 0.6)',    // purple
        'rgba(236, 72, 153, 0.7)',    // pink
        'rgba(239, 68, 68, 0.8)',     // red
        'rgba(245, 158, 11, 0.9)',    // amber
        'rgba(255, 255, 255, 1)',     // white hot
    ],
    reporters: [
        'rgba(0, 0, 0, 0)',
        'rgba(16, 185, 129, 0.3)',    // emerald
        'rgba(34, 197, 94, 0.5)',     // green
        'rgba(132, 204, 22, 0.6)',    // lime
        'rgba(234, 179, 8, 0.7)',     // yellow
        'rgba(249, 115, 22, 0.8)',    // orange
        'rgba(255, 255, 255, 1)',
    ],
    bias: [
        'rgba(0, 0, 0, 0)',
        'rgba(99, 102, 241, 0.4)',
        'rgba(139, 92, 246, 0.6)',
        'rgba(236, 72, 153, 0.7)',
        'rgba(239, 68, 68, 0.8)',
        'rgba(245, 158, 11, 0.9)',
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

const BIAS_FILL = { high: '#ef4444', moderate: '#f59e0b', low: '#22c55e' } as const;
const BIAS_STROKE = { high: '#fca5a5', moderate: '#fcd34d', low: '#86efac' } as const;

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

const STAT_BOX = 'background: rgba(255,255,255,0.05); padding: 8px; border-radius: 6px; text-align: center;';

/** Hotspot popup as DOM. Every untrusted value is set as text, never markup. */
function hotspotPopup(hs: HotspotData): HTMLElement {
    const reporters = hs.unique_reporters || 1;
    const ratio = hs.count / reporters;
    const level = ratio > 4 ? 'high' : ratio > 2 ? 'moderate' : 'low';
    const biased = ratio > 2;

    const stat = (value: number, label: string) => el('div', {
        style: STAT_BOX,
        children: [
            el('div', { style: 'font-size: 20px; font-weight: 700;', text: value }),
            el('div', { style: 'font-size: 10px; color: #9ca3af;', text: label }),
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
                        style: `color: ${biased ? BIAS_FILL[level] : '#22c55e'}; font-weight: 600;`,
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

    useEffect(() => {
        let cancelled = false;
        const container = mapRef.current;
        if (!container) return;

        if (!config) { setIsLoading(false); return; }

        createMap(container, config, {
            center: defaultCenter || { lat: 40.3573, lng: -74.6672 },
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
            const level = ratio > 4 ? 'high' : ratio > 2 ? 'moderate' : 'low';
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
                    strokeWidth: 2,
                }),
                title: `${hs.count} reports / ${reporters} reporters`,
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
                    <MapPin className="w-8 h-8 mx-auto mb-2 text-white/30" />
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

    return (
        <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl overflow-hidden">
            {/* Header */}
            <div className="p-4 sm:p-6 pb-3">
                <div className="flex items-center justify-between mb-1">
                    <h3 className="text-lg font-semibold text-white flex items-center gap-2">
                        <AlertTriangle className="w-5 h-5 text-amber-400" />
                        Spatial Bias Detector
                    </h3>
                    <button
                        onClick={() => setShowHotspotOverlay(!showHotspotOverlay)}
                        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs transition ${
                            showHotspotOverlay
                                ? 'bg-white/10 text-white/80'
                                : 'bg-white/5 text-white/40'
                        }`}
                        title="Toggle hotspot cluster markers"
                    >
                        <Eye className="w-3.5 h-3.5" />
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

                {/* Summary stats */}
                <div className="grid grid-cols-3 gap-2 mb-4">
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

                {/* Mode toggle */}
                <div className="flex gap-1 bg-white/5 rounded-lg p-1">
                    <button
                        onClick={() => setMode('reports')}
                        className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition ${
                            mode === 'reports'
                                ? 'bg-indigo-500/30 text-indigo-300 border border-indigo-500/40'
                                : 'text-white/50 hover:text-white/70'
                        }`}
                    >
                        <FileText className="w-3.5 h-3.5" />
                        All Reports
                    </button>
                    <button
                        onClick={() => setMode('reporters')}
                        className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition ${
                            mode === 'reporters'
                                ? 'bg-emerald-500/30 text-emerald-300 border border-emerald-500/40'
                                : 'text-white/50 hover:text-white/70'
                        }`}
                    >
                        <Users className="w-3.5 h-3.5" />
                        Unique Reporters
                    </button>
                </div>
            </div>

            {/* Map */}
            <div className="relative" style={{ height: '400px' }}>
                {(isLoading || externalLoading) && (
                    <div className="absolute inset-0 flex items-center justify-center bg-slate-900 z-10">
                        <div className="w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
                    </div>
                )}
                <div ref={mapRef} className="w-full h-full" />
            </div>

            {/* Bias hotspot legend */}
            {biasedHotspots.length > 0 && showHotspotOverlay && (
                <div className="p-4 border-t border-white/10">
                    <div className="text-xs font-medium text-white/50 uppercase tracking-wider mb-2">
                        Bias-Flagged Clusters ({biasedHotspots.length})
                    </div>
                    <div className="space-y-1.5">
                        {biasedHotspots.slice(0, 5).map((hs, idx) => {
                            const reporters = hs.unique_reporters || 1;
                            const ratio = hs.count / reporters;
                            return (
                                <div key={idx} className="flex items-center gap-2 p-2 bg-white/5 rounded-lg">
                                    <div
                                        className="w-3 h-3 rounded-full flex-shrink-0"
                                        style={{ backgroundColor: ratio > 4 ? '#ef4444' : '#f59e0b' }}
                                    />
                                    <span className="text-sm text-white/80 flex-1 truncate">
                                        {hs.sample_address || `Area ${idx + 1}`}
                                    </span>
                                    <span className="text-xs text-white/50">
                                        {hs.count} reports / {reporters} reporter{reporters !== 1 ? 's' : ''}
                                    </span>
                                    <span className={`text-xs font-semibold ${ratio > 4 ? 'text-red-400' : 'text-amber-400'}`}>
                                        {ratio.toFixed(1)}x
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                    <p className="text-[10px] text-white/30 mt-2">
                        Clusters where reports-per-reporter exceeds 2x may indicate repeat reporting bias rather than widespread community concern.
                    </p>
                </div>
            )}
        </div>
    );
}

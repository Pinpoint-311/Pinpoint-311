import { useEffect, useRef, useState, useCallback } from 'react';
import { MapPin, Users, FileText, AlertTriangle, Eye } from 'lucide-react';
import { HeatmapData, HotspotData } from '../types';

interface SpatialBiasHeatmapProps {
    heatmapData: HeatmapData | null;
    hotspots: HotspotData[];
    apiKey: string;
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

/**
 * Canvas heatmap rendered as a Google Maps OverlayView.
 *
 * Replaces google.maps.visualization.HeatmapLayer, which was removed from the
 * Maps JavaScript API in v3.65. Uses the well-known intensity-accumulation
 * technique (radial alpha gradients per point → colorize the alpha channel
 * through a gradient palette), so it needs no deprecated library and no extra
 * dependency, and keeps the same look.
 */
function createHeatmapOverlay(
    map: google.maps.Map,
    getPoints: () => { lat: number; lng: number; weight: number }[],
    getGradient: () => string[],
    radius: number,
    opacity: number,
) {
    class HeatmapOverlay extends google.maps.OverlayView {
        private canvas: HTMLCanvasElement | null = null;

        onAdd() {
            const canvas = document.createElement('canvas');
            canvas.style.position = 'absolute';
            canvas.style.pointerEvents = 'none';
            this.canvas = canvas;
            this.getPanes()!.overlayLayer.appendChild(canvas);
        }

        onRemove() {
            this.canvas?.parentNode?.removeChild(this.canvas);
            this.canvas = null;
        }

        redraw() {
            this.draw();
        }

        draw() {
            const proj = this.getProjection();
            const canvas = this.canvas;
            if (!proj || !canvas) return;
            const bounds = map.getBounds();
            if (!bounds) return;

            // Position the canvas over the current viewport in the pane's
            // (div-pixel) coordinate space — the same space fromLatLngToDivPixel
            // returns, so points line up exactly.
            const ne = proj.fromLatLngToDivPixel(bounds.getNorthEast());
            const sw = proj.fromLatLngToDivPixel(bounds.getSouthWest());
            if (!ne || !sw) return;
            const left = Math.min(ne.x, sw.x);
            const top = Math.min(ne.y, sw.y);
            const width = Math.max(1, Math.round(Math.abs(ne.x - sw.x)));
            const height = Math.max(1, Math.round(Math.abs(ne.y - sw.y)));

            canvas.style.left = `${left}px`;
            canvas.style.top = `${top}px`;
            canvas.width = width;
            canvas.height = height;

            const ctx = canvas.getContext('2d');
            if (!ctx) return;
            ctx.clearRect(0, 0, width, height);

            const points = getPoints();
            if (!points.length) return;

            // Pass 1: accumulate intensity as grayscale alpha.
            for (const p of points) {
                const px = proj.fromLatLngToDivPixel(new google.maps.LatLng(p.lat, p.lng));
                if (!px) continue;
                const x = px.x - left;
                const y = px.y - top;
                if (x < -radius || x > width + radius || y < -radius || y > height + radius) continue;
                const a = Math.max(0.08, Math.min(1, p.weight || 0.5));
                const grad = ctx.createRadialGradient(x, y, 0, x, y, radius);
                grad.addColorStop(0, `rgba(0,0,0,${a})`);
                grad.addColorStop(1, 'rgba(0,0,0,0)');
                ctx.fillStyle = grad;
                ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
            }

            // Pass 2: map the accumulated alpha through the color palette.
            const palette = buildPalette(getGradient());
            const img = ctx.getImageData(0, 0, width, height);
            const d = img.data;
            for (let i = 0; i < d.length; i += 4) {
                const alpha = d[i + 3];
                if (alpha === 0) continue;
                const off = alpha * 4;
                d[i] = palette[off];
                d[i + 1] = palette[off + 1];
                d[i + 2] = palette[off + 2];
                d[i + 3] = Math.round(Math.min(255, alpha) * opacity);
            }
            ctx.putImageData(img, 0, 0);
        }
    }

    const overlay = new HeatmapOverlay();
    overlay.setMap(map);
    return overlay as google.maps.OverlayView & { redraw: () => void };
}

export default function SpatialBiasHeatmap({
    heatmapData,
    hotspots,
    apiKey,
    defaultCenter,
    isLoading: externalLoading,
}: SpatialBiasHeatmapProps) {
    const mapRef = useRef<HTMLDivElement>(null);
    const mapInstanceRef = useRef<google.maps.Map | null>(null);
    const heatmapOverlayRef = useRef<(google.maps.OverlayView & { redraw: () => void }) | null>(null);
    const biasMarkersRef = useRef<google.maps.Marker[]>([]);
    const infoWindowRef = useRef<google.maps.InfoWindow | null>(null);

    const [mapReady, setMapReady] = useState(false);
    const [isLoading, setIsLoading] = useState(true);
    const [mode, setMode] = useState<HeatmapMode>('reports');
    const [showHotspotOverlay, setShowHotspotOverlay] = useState(true);

    // Load Google Maps (core only — no deprecated visualization library).
    useEffect(() => {
        if (!apiKey) {
            setIsLoading(false);
            return;
        }
        const start = () => setTimeout(() => initMap(), 100);

        if (window.google?.maps) {
            start();
            return;
        }
        const existing = document.querySelector<HTMLScriptElement>('script[data-gmaps-loader]');
        if (existing) {
            existing.addEventListener('load', start);
            return;
        }
        const script = document.createElement('script');
        script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=places&loading=async`;
        script.async = true;
        script.dataset.gmapsLoader = '1';
        script.onload = start;
        script.onerror = () => setIsLoading(false);
        document.head.appendChild(script);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [apiKey]);

    const initMap = useCallback(() => {
        if (!mapRef.current || !window.google?.maps) return;

        const center = defaultCenter || { lat: 40.3573, lng: -74.6672 }; // Default to NJ

        const mapOptions: google.maps.MapOptions = {
            center,
            zoom: 13,
            mapTypeId: 'roadmap',
            mapTypeControl: true,
            streetViewControl: false,
            fullscreenControl: true,
            zoomControl: true,
            styles: [
                { elementType: 'geometry', stylers: [{ color: '#1a1a2e' }] },
                { elementType: 'labels.text.stroke', stylers: [{ color: '#1a1a2e' }] },
                { elementType: 'labels.text.fill', stylers: [{ color: '#8b8ba7' }] },
                { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#2a2a4a' }] },
                { featureType: 'road', elementType: 'labels.text.fill', stylers: [{ color: '#6b6b8a' }] },
                { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#0e0e1a' }] },
                { featureType: 'poi', elementType: 'labels', stylers: [{ visibility: 'off' }] },
                { featureType: 'transit', stylers: [{ visibility: 'off' }] },
            ],
        };

        if (window.google.maps.MapTypeControlStyle) {
            mapOptions.mapTypeControlOptions = {
                style: window.google.maps.MapTypeControlStyle.HORIZONTAL_BAR,
                position: window.google.maps.ControlPosition.TOP_LEFT,
            };
        }

        const map = new window.google.maps.Map(mapRef.current, mapOptions);
        mapInstanceRef.current = map;
        infoWindowRef.current = new window.google.maps.InfoWindow();
        setIsLoading(false);
        setMapReady(true);
    }, [defaultCenter]);

    // Render / refresh the custom canvas heatmap when mode or data changes.
    useEffect(() => {
        if (!mapInstanceRef.current || !mapReady || !window.google?.maps) return;

        const map = mapInstanceRef.current;
        const points = (mode === 'reporters' ? heatmapData?.reporter_points : heatmapData?.report_points) || [];

        // Recreate the overlay for the current mode/data (avoids stale closures).
        if (heatmapOverlayRef.current) {
            heatmapOverlayRef.current.setMap(null);
            heatmapOverlayRef.current = null;
        }
        if (!points.length) return;

        const radius = mode === 'reporters' ? 30 : 25;
        heatmapOverlayRef.current = createHeatmapOverlay(
            map,
            () => points,
            () => GRADIENTS[mode],
            radius,
            0.85,
        );

        // Auto-fit bounds to the data.
        const bounds = new window.google.maps.LatLngBounds();
        points.forEach(p => bounds.extend(new window.google.maps.LatLng(p.lat, p.lng)));
        map.fitBounds(bounds, 50);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [mode, heatmapData, mapReady]);

    // Hotspot bias markers overlay
    useEffect(() => {
        if (!mapInstanceRef.current || !mapReady || !window.google?.maps) return;

        const map = mapInstanceRef.current;

        // Clear old markers
        biasMarkersRef.current.forEach(m => m.setMap(null));
        biasMarkersRef.current = [];

        if (!showHotspotOverlay || !hotspots || hotspots.length === 0) return;

        hotspots.forEach((hs) => {
            const reporters = hs.unique_reporters || 1;
            const ratio = hs.count / reporters;
            // ratio > 2 means on average each reporter filed 2+ reports — potential bias
            const isBiased = ratio > 2;
            const biasLevel = ratio > 4 ? 'high' : ratio > 2 ? 'moderate' : 'low';

            const fillColor = biasLevel === 'high' ? '#ef4444' : biasLevel === 'moderate' ? '#f59e0b' : '#22c55e';
            const strokeColor = biasLevel === 'high' ? '#fca5a5' : biasLevel === 'moderate' ? '#fcd34d' : '#86efac';

            const marker = new window.google.maps.Marker({
                position: { lat: hs.lat, lng: hs.lng },
                map,
                icon: {
                    path: window.google.maps.SymbolPath.CIRCLE,
                    fillColor,
                    fillOpacity: 0.9,
                    strokeColor,
                    strokeWeight: 2,
                    scale: Math.min(8 + hs.count, 20),
                },
                title: `${hs.count} reports / ${reporters} reporters`,
                zIndex: 100,
            });

            marker.addListener('click', () => {
                if (!infoWindowRef.current) return;

                const biasLabel = isBiased
                    ? `<span style="color: ${fillColor}; font-weight: 600;">${biasLevel.toUpperCase()} BIAS</span> (${ratio.toFixed(1)} reports/reporter)`
                    : `<span style="color: #22c55e; font-weight: 600;">BALANCED</span> (${ratio.toFixed(1)} reports/reporter)`;

                const catsHtml = (hs.top_categories || [])
                    .map(c => `<span style="background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px; font-size: 10px;">${c}</span>`)
                    .join(' ');

                infoWindowRef.current!.setContent(`
                    <div style="padding: 12px; font-family: system-ui, -apple-system, sans-serif; background: #1f2937; border-radius: 8px; min-width: 220px; color: white;">
                        <h4 style="margin: 0 0 8px 0; font-size: 14px; font-weight: 600;">
                            ${hs.sample_address || 'Cluster'}
                        </h4>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 8px;">
                            <div style="background: rgba(255,255,255,0.05); padding: 8px; border-radius: 6px; text-align: center;">
                                <div style="font-size: 20px; font-weight: 700;">${hs.count}</div>
                                <div style="font-size: 10px; color: #9ca3af;">Reports</div>
                            </div>
                            <div style="background: rgba(255,255,255,0.05); padding: 8px; border-radius: 6px; text-align: center;">
                                <div style="font-size: 20px; font-weight: 700;">${reporters}</div>
                                <div style="font-size: 10px; color: #9ca3af;">Reporters</div>
                            </div>
                        </div>
                        <div style="font-size: 12px; margin-bottom: 6px;">${biasLabel}</div>
                        ${catsHtml ? `<div style="margin-top: 6px;">${catsHtml}</div>` : ''}
                    </div>
                `);
                infoWindowRef.current!.open(map, marker);
            });

            biasMarkersRef.current.push(marker);
        });
    }, [hotspots, showHotspotOverlay, mapReady]);

    if (!apiKey) {
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

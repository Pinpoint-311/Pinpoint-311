import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Loader2, MapPin, RotateCcw, X } from 'lucide-react';

import { api } from '../services/api';
import {
    CanvasOverlayHandle,
    GeoFeature,
    GeoJsonLayerHandle,
    LatLng,
    MapRenderer,
    MarkerLayer,
    VectorStyle,
    boundsOfGeoJson,
    createMap,
    fractionAlongLine,
    legacyMapProviderConfig,
    pointAtFraction, subPathByFractions,
} from '../maps';

/**
 * Show a clerk exactly which stretches of road a jurisdiction rule covers, and
 * let them correct it.
 *
 * Typing a road name selects every segment the data files under that name, and
 * the data is not always right about that: a service spur, a stretch the town
 * actually maintains, or a continuation past the border can all be lumped in.
 * Without seeing it, a clerk has no way to know — the rule looks correct and
 * quietly covers the wrong thing.
 *
 * Excluded segments are stored as a diff against the road NAME rather than as a
 * frozen list, so a monthly data refresh picks up a newly built block
 * automatically while keeping the clerk's corrections. That is also why
 * exclusions key on the publisher's own feature id and not our row id, which
 * changes on every refresh.
 */

export interface SegmentTrim { start: number; end: number }

interface RoadCorridorMapProps {
    /** Road names currently in the rule, comma-separated as routing_config stores them. */
    roads: string;
    townshipBoundary?: object | null;
    /** Feature ids the clerk has switched off. */
    excludedFeatureIds: string[];
    onExcludedChange: (ids: string[]) => void;
    /** Partial coverage, keyed by feature id, as fractions of segment length. */
    trims: Record<string, SegmentTrim>;
    onTrimsChange: (trims: Record<string, SegmentTrim>) => void;
    corridorMetres: number;
    onCorridorMetresChange: (metres: number) => void;
    apiKey?: string | null;
}

const INCLUDED = '#f87171';
const EXCLUDED = '#64748b';

export default function RoadCorridorMap({
    roads, townshipBoundary, excludedFeatureIds, onExcludedChange,
    trims, onTrimsChange,
    corridorMetres, onCorridorMetresChange, apiKey,
}: RoadCorridorMapProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const rendererRef = useRef<MapRenderer | null>(null);
    const bufferLayerRef = useRef<GeoJsonLayerHandle | null>(null);
    const centerlineLayerRef = useRef<GeoJsonLayerHandle | null>(null);
    // Read inside the style callback, which the renderer may call at any time.
    // A ref rather than state so a redraw never closes over a stale set.
    const excludedRef = useRef(new Set(excludedFeatureIds));
    const handleLayerRef = useRef<MarkerLayer | null>(null);
    const canvasOverlayRef = useRef<CanvasOverlayHandle | null>(null);
    const hasFittedBoundsRef = useRef<Record<string, boolean>>({});
    // The clicked stretch, and its vertices, so handles can be placed along it.
    const [selected, setSelected] = useState<{ id: string; name: string; path: LatLng[] } | null>(null);
    // feature id -> vertices, kept from the fetch. GeoFeature deliberately does
    // not carry raw coordinates (it is provider-neutral), so the click handler
    // looks the path up here rather than reaching into vendor geometry.
    const pathsRef = useRef<Map<string, LatLng[]>>(new Map());
    const trimsRef = useRef(trims);
    useEffect(() => { trimsRef.current = trims; }, [trims]);

    const [ready, setReady] = useState(false);
    const [zoomLevel, setZoomLevel] = useState(13);
    const [loading, setLoading] = useState(false);
    const [segmentCount, setSegmentCount] = useState(0);
    const [unavailable, setUnavailable] = useState(false);

    useEffect(() => { excludedRef.current = new Set(excludedFeatureIds); }, [excludedFeatureIds]);

    const roadList = roads.split(',').map(r => r.trim()).filter(Boolean);
    const roadKey = roadList.join('|');

    useEffect(() => {
        let cancelled = false;
        let unsubscribeIdle: (() => void) | undefined;
        const container = containerRef.current;
        const config = legacyMapProviderConfig(apiKey);
        if (!container || !config) return;

        createMap(container, config, {
            center: (townshipBoundary as any)?.center ? (townshipBoundary as any).center : { lat: 40.7312, lng: -74.2734 },
            zoom: 13,
            controls: { zoom: { enabled: true }, fullscreen: { enabled: true } },
        })
            .then(renderer => {
                if (cancelled) { renderer.destroy(); return; }
                rendererRef.current = renderer;

                // `idle` is the renderer-agnostic "camera has settled" event, and
                // every provider implements it. The previous call was to
                // onBoundsChange, which nothing implements -- so with optional
                // chaining it silently never fired and zoomLevel stayed at its
                // initial 13 for the life of the map.
                unsubscribeIdle = renderer.on('idle', () => {
                    const z = renderer.getZoom();
                    if (typeof z === "number") setZoomLevel(z);
                });

                if (townshipBoundary) {
                    try {
                        renderer.addGeoJsonLayer({
                            data: townshipBoundary,
                            style: {
                                fillColor: "#6366f1",
                                fillOpacity: 0.08,
                                strokeColor: "#6366f1",
                                strokeWidth: 2,
                                strokeOpacity: 0.8,
                                clickable: false,
                            },
                        });
                        const boundaryBounds = boundsOfGeoJson(townshipBoundary);
                        if (boundaryBounds) renderer.fitBounds(boundaryBounds);
                    } catch (e) {
                        console.warn("Failed to add boundary to corridor map:", e);
                    }
                }

                setReady(true);
            })
            .catch(() => !cancelled && setUnavailable(true));

        return () => {
            cancelled = true;
            unsubscribeIdle?.();
            rendererRef.current?.destroy();
            rendererRef.current = null;
            bufferLayerRef.current = null;
            centerlineLayerRef.current = null;
        };
    }, [apiKey]);

        const bufferStyleFor = useCallback((feature: GeoFeature): VectorStyle => {
        const id = String(feature.properties?.feature_id ?? "");
        const off = excludedRef.current.has(id);
        const lat = 40.73;
        const metersPerPixel = (156543.03392 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, zoomLevel || 15);
        const bufferPx = Math.max(4, Math.round(corridorMetres / metersPerPixel));
        return {
            strokeColor: off ? "#64748b" : "#ef4444",
            strokeWidth: off ? 4 : bufferPx,
            strokeOpacity: 0.0,
        };
    }, [corridorMetres, zoomLevel]);

    const centerlineStyleFor = useCallback((feature: GeoFeature): VectorStyle => {
        const id = String(feature.properties?.feature_id ?? '');
        const off = excludedRef.current.has(id);
        return {
            strokeColor: off ? EXCLUDED : INCLUDED,
            // Corridor width is metres on the ground and a stroke is screen
            // pixels, so this is indicative rather than a true buffer -- but it
            // makes the setting legible instead of abstract.
            strokeWidth: off ? 2 : Math.max(3, Math.round(corridorMetres / 3)),
            strokeOpacity: 0.0,
        };
    }, [corridorMetres]);

    /** Re-evaluate the existing layer rather than refetching: the geometry has
     *  not changed, only which pieces count. */
    const restyle = useCallback(() => {
        bufferLayerRef.current?.setStyle(bufferStyleFor);
        centerlineLayerRef.current?.setStyle(centerlineStyleFor);
    }, [bufferStyleFor, centerlineStyleFor]);

    // Live update map buffer stroke whenever slider moves
    useEffect(() => {
        restyle();
    }, [corridorMetres, restyle]);

    const toggleSegment = useCallback((featureId: string) => {
        const next = new Set(excludedRef.current);
        if (next.has(featureId)) next.delete(featureId);
        else next.add(featureId);
        excludedRef.current = next;
        onExcludedChange([...next]);
        restyle();
    }, [onExcludedChange, restyle]);

    useEffect(() => {
        const renderer = rendererRef.current;
        if (!renderer || !ready) return;

        bufferLayerRef.current?.remove();
        centerlineLayerRef.current?.remove();
        bufferLayerRef.current = null;
            centerlineLayerRef.current = null;
        setSegmentCount(0);

        if (!roadList || !roadList.length) return;

        let cancelled = false;
        setLoading(true);
        api.getRoadGeometry(roadList)
            .then(collection => {
                if (cancelled || !rendererRef.current) return;
                setUnavailable(collection.available === false);
                setSegmentCount((collection?.features || []).length);
                pathsRef.current = new Map(
                    collection.features.map(f => [
                        String(f.properties.feature_id),
                        (f.geometry.coordinates || []).map(([lng, lat]) => ({ lat, lng })),
                    ]),
                );
                if (!collection?.features?.length) return;

                bufferLayerRef.current = rendererRef.current.addGeoJsonLayer({
                    data: collection,
                    style: bufferStyleFor,
                });

                centerlineLayerRef.current = rendererRef.current.addGeoJsonLayer({
                    data: collection,
                    style: centerlineStyleFor,
                    onFeatureClick: feature => {
                        const id = feature.properties?.feature_id;
                        if (!id) return;
                        setSelected({
                            id: String(id),
                            name: String(feature.properties?.name || 'this stretch'),
                            path: pathsRef.current.get(String(id)) || [],
                        });
                    },
                });

                if (!hasFittedBoundsRef.current[roadKey]) {
                    const bounds = boundsOfGeoJson(collection);
                    if (bounds) {
                        rendererRef.current.fitBounds(bounds, { padding: 40 });
                        hasFittedBoundsRef.current[roadKey] = true;
                    }
                }
            })
            .catch(() => !cancelled && setUnavailable(true))
            .finally(() => !cancelled && setLoading(false));

        return () => { cancelled = true; };
        // roadKey rather than the array so a re-render with equal contents does
        // not refetch the whole town's geometry.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [roadKey, ready, bufferStyleFor, centerlineStyleFor, toggleSegment]);


    // Dynamic Canvas Overlay for crisp zoom-scaled striped buffer & live trim rendering
    useEffect(() => {
        const renderer = rendererRef.current;
        if (!renderer || !ready) return;

        canvasOverlayRef.current?.remove();
        canvasOverlayRef.current = renderer.addCanvasOverlay({
            draw: (ctx, view) => {
                const lat = view.bounds ? (view.bounds.north + view.bounds.south) / 2 : 40.73;
                const metersPerPixel = (156543.03392 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, view.zoom || 15);
                const bufferPx = Math.max(4, Math.round(corridorMetres / metersPerPixel));

                // 1. Draw Striped Translucent Buffer & Red Centerline for active road features
                pathsRef.current.forEach((path, id) => {
                    if (path.length < 2) return;
                    if (excludedRef.current.has(id)) return;

                    const trim = trimsRef.current[id] || { start: 0, end: 1 };
                    const isTrimmed = trim.start > 0.001 || trim.end < 0.999;
                    const activeSubPath = subPathByFractions(path, trim.start, trim.end);

                    // If segment is trimmed, draw the untrimmed full path in faint muted grey
                    if (isTrimmed) {
                        ctx.save();
                        ctx.beginPath();
                        path.forEach((p, idx) => {
                            const pt = view.project(p);
                            if (isNaN(pt.x) || isNaN(pt.y)) return;
                            if (idx === 0) ctx.moveTo(pt.x, pt.y);
                            else ctx.lineTo(pt.x, pt.y);
                        });
                        ctx.setLineDash([4, 4]);
                        ctx.strokeStyle = "rgba(100, 116, 139, 0.35)";
                        ctx.lineWidth = 3;
                        ctx.stroke();
                        ctx.restore();
                    }

                    // Draw Red Striped Buffer along activeSubPath
                    if (activeSubPath.length >= 2) {
                        ctx.save();
                        ctx.beginPath();
                        activeSubPath.forEach((p, idx) => {
                            const pt = view.project(p);
                            if (isNaN(pt.x) || isNaN(pt.y)) return;
                            if (idx === 0) ctx.moveTo(pt.x, pt.y);
                            else ctx.lineTo(pt.x, pt.y);
                        });
                        ctx.setLineDash([12, 8]);
                        ctx.strokeStyle = "rgba(239, 68, 68, 0.40)";
                        ctx.lineWidth = bufferPx;
                        ctx.lineCap = "round";
                        ctx.lineJoin = "round";
                        ctx.stroke();

                        // Draw Red Centerline along activeSubPath
                        ctx.setLineDash([]);
                        ctx.strokeStyle = "rgba(239, 68, 68, 0.95)";
                        ctx.lineWidth = 4;
                        ctx.stroke();
                        ctx.restore();
                    }
                });

                // 2. Draw Active Highlighted Trim Polyline for selected segment
                if (selected && selected.path.length >= 2) {
                    const trim = trimsRef.current[selected.id] || { start: 0, end: 1 };
                    const sub = subPathByFractions(selected.path, trim.start, trim.end);

                    if (sub.length >= 2) {
                        ctx.save();
                        ctx.beginPath();
                        sub.forEach((p, idx) => {
                            const pt = view.project(p);
                            if (isNaN(pt.x) || isNaN(pt.y)) return;
                            if (idx === 0) ctx.moveTo(pt.x, pt.y);
                            else ctx.lineTo(pt.x, pt.y);
                        });
                        ctx.setLineDash([8, 6]);
                        ctx.strokeStyle = "rgba(251, 191, 36, 0.55)";
                        ctx.lineWidth = bufferPx + 4;
                        ctx.lineCap = "round";
                        ctx.lineJoin = "round";
                        ctx.stroke();

                        ctx.setLineDash([]);
                        ctx.strokeStyle = "rgba(251, 191, 36, 1.0)";
                        ctx.lineWidth = 6;
                        ctx.stroke();
                        ctx.restore();
                    }
                }
            },
        });
    }, [ready, corridorMetres, selected, roadKey]);

    // Draggable handles at the trim boundaries of the selected stretch.
    useEffect(() => {
        const renderer = rendererRef.current;
        handleLayerRef.current?.remove();
        handleLayerRef.current = null;
        if (!renderer || !ready || !selected || (selected?.path || []).length < 2) return;

        const trim = trims[selected.id] || { start: 0, end: 1 };
        const layer = renderer.createMarkerLayer();

        const handleDrag = (which: 'start' | 'end') => (position: LatLng) => {
            const fraction = fractionAlongLine(selected.path, position);
            const current = trimsRef.current[selected.id] || { start: 0, end: 1 };
            const next = { ...current, [which]: fraction };
            const ordered = next.start <= next.end
                ? next
                : { start: next.end, end: next.start };

            const updated = { ...trimsRef.current };
            if (ordered.start <= 0.001 && ordered.end >= 0.999) delete updated[selected.id];
            else updated[selected.id] = ordered;

            trimsRef.current = updated;
            canvasOverlayRef.current?.redraw();
        };

        const handleDragEnd = (which: 'start' | 'end') => (position: LatLng) => {
            handleDrag(which)(position);
            onTrimsChange({ ...trimsRef.current });
        };

        const markers = (['start', 'end'] as const).flatMap(which => {
            const position = pointAtFraction(selected.path, trim[which]);
            return position ? [{
                position,
                draggable: true,
                icon: {
                    type: 'circle' as const,
                    radius: 9,
                    fillColor: '#fbbf24',
                    fillOpacity: 1,
                    strokeColor: '#78350f',
                    strokeWidth: 2,
                },
                title: which === 'start' ? 'Drag: where this rule starts' : 'Drag: where this rule ends',
                zIndex: 200,
                onDrag: handleDrag(which),
                onDragEnd: handleDragEnd(which),
            }] : [];
        });

        layer.setMarkers(markers);
        handleLayerRef.current = layer;
    }, [selected?.id, ready]);

    const excludedCount = (excludedFeatureIds || []).length;
    const selectedExcluded = selected ? excludedFeatureIds.includes(selected.id) : false;
    const selectedTrim = selected ? trims[selected.id] : undefined;

    return (
        <div className="space-y-3">
            <div className="flex items-center justify-between gap-4 flex-wrap">
                <div>
                    <p className="text-sm font-medium text-white">Coverage preview</p>
                    <p className="text-xs text-white/40 mt-0.5">
                        {segmentCount > 0
                            ? `${segmentCount - excludedCount} of ${segmentCount} stretches included. Click a stretch to switch it off.`
                            : 'Add a road above to see what the rule covers.'}
                    </p>
                </div>
                {excludedCount > 0 && (
                    <button
                        type="button"
                        onClick={() => { excludedRef.current = new Set(); onExcludedChange([]); restyle(); }}
                        className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs text-white/60 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400"
                    >
                        <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
                        Include all {segmentCount}
                    </button>
                )}
            </div>

            <div className="relative rounded-xl overflow-hidden border border-white/10 bg-slate-900/60" style={{ height: 300 }}>
                <div ref={containerRef} className="absolute inset-0" role="application" aria-label="Road coverage map" />
                {(loading || !ready) && !unavailable && (
                    <div className="absolute inset-0 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm">
                        <Loader2 className="w-5 h-5 animate-spin text-white/40" aria-hidden="true" />
                    </div>
                )}
                {unavailable && (
                    <div className="absolute top-3 left-3 z-10 flex items-center gap-2 rounded-lg bg-slate-900/80 backdrop-blur-md border border-white/10 px-3 py-1.5 text-xs text-white/70 shadow-lg pointer-events-none">
                        <MapPin className="w-3.5 h-3.5 text-amber-400 shrink-0" aria-hidden="true" />
                        <span>Road data loading for this boundary...</span>
                    </div>
                )}
            </div>

            {selected && (
                <div className="rounded-xl border border-amber-400/25 bg-amber-500/[0.07] px-3.5 py-3 space-y-2.5">
                    <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                            <p className="text-sm font-medium text-white truncate">{selected.name}</p>
                            <p className="text-[11px] text-white/45 mt-0.5">
                                {selectedExcluded
                                    ? 'Switched off — this stretch is not covered by the rule.'
                                    : selectedTrim
                                        ? `Covered from ${Math.round(selectedTrim.start * 100)}% to ${Math.round(selectedTrim.end * 100)}% along. Drag the amber handles to adjust.`
                                        : 'Fully covered. Drag the amber handles to cover only part of it.'}
                            </p>
                        </div>
                        <button
                            type="button"
                            onClick={() => setSelected(null)}
                            aria-label="Close stretch options"
                            className="p-1 rounded hover:bg-white/10 text-white/40 hover:text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400"
                        >
                            <X className="w-4 h-4" aria-hidden="true" />
                        </button>
                    </div>

                    <div className="flex flex-wrap gap-2">
                        <button
                            type="button"
                            onClick={() => toggleSegment(selected.id)}
                            className="rounded-lg px-2.5 py-1.5 text-xs bg-white/5 hover:bg-white/10 border border-white/10 text-white/75 hover:text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400"
                        >
                            {selectedExcluded ? 'Include this stretch' : 'Switch this stretch off'}
                        </button>
                        {selectedTrim && (
                            <button
                                type="button"
                                onClick={() => {
                                    const next = { ...trimsRef.current };
                                    delete next[selected.id];
                                    onTrimsChange(next);
                                }}
                                className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs bg-white/5 hover:bg-white/10 border border-white/10 text-white/60 hover:text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400"
                            >
                                <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
                                Cover all of it
                            </button>
                        )}
                    </div>

                    <p className="text-[11px] text-white/40 leading-relaxed">
                        Trimming is for where the road data splits in the wrong place — the
                        boundaries in the data are wherever the publisher happened to cut them,
                        not where responsibility actually changes.
                    </p>
                </div>
            )}

            {/* Corridor width. A number, not a map interaction, because the fix
                for a corridor that is too wide is almost always this and not
                editing any road. */}
            <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-3">
                <label htmlFor="corridor-width" className="flex items-baseline justify-between gap-4">
                    <span className="text-sm text-white/80">How close counts as &ldquo;on this road&rdquo;</span>
                    <span className="text-sm font-medium text-white tabular-nums">{Math.round(corridorMetres * 3.28084)} ft <span className="text-white/40 text-xs font-normal">({corridorMetres} m)</span></span>
                </label>
                <input
                    id="corridor-width"
                    type="range"
                    min={5}
                    max={40}
                    step={1}
                    value={corridorMetres}
                    onChange={e => onCorridorMetresChange(Number(e.target.value))}
                    className="w-full mt-2 accent-primary-500"
                    aria-describedby="corridor-width-hint"
                />
                <p id="corridor-width-hint" className="text-[11px] text-white/40 mt-1.5 leading-relaxed">
                    A report within this distance of the centreline is treated as being on the road.
                    Narrow it in dense areas where roads run close together; widen it where shoulders
                    are broad. It also absorbs small differences between the road data and the map
                    imagery.
                </p>
            </div>

            {excludedCount > 0 && (
                <p className="flex items-start gap-2 text-[11px] text-white/45 leading-relaxed">
                    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0 text-white/30" aria-hidden="true" />
                    {excludedCount} stretch{excludedCount === 1 ? '' : 'es'} switched off. These are remembered
                    against the road name, so a future data update keeps your changes while still picking up
                    newly built sections.
                </p>
            )}
        </div>
    );
}

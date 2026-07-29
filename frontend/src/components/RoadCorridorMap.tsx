import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Loader2, MapPin, RotateCcw, X } from 'lucide-react';

import { api } from '../services/api';
import {
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
    pointAtFraction,
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
    const layerRef = useRef<GeoJsonLayerHandle | null>(null);
    // Read inside the style callback, which the renderer may call at any time.
    // A ref rather than state so a redraw never closes over a stale set.
    const excludedRef = useRef(new Set(excludedFeatureIds));
    const handleLayerRef = useRef<MarkerLayer | null>(null);
    // The clicked stretch, and its vertices, so handles can be placed along it.
    const [selected, setSelected] = useState<{ id: string; name: string; path: LatLng[] } | null>(null);
    // feature id -> vertices, kept from the fetch. GeoFeature deliberately does
    // not carry raw coordinates (it is provider-neutral), so the click handler
    // looks the path up here rather than reaching into vendor geometry.
    const pathsRef = useRef<Map<string, LatLng[]>>(new Map());
    const trimsRef = useRef(trims);
    useEffect(() => { trimsRef.current = trims; }, [trims]);

    const [ready, setReady] = useState(false);
    const [loading, setLoading] = useState(false);
    const [segmentCount, setSegmentCount] = useState(0);
    const [unavailable, setUnavailable] = useState(false);

    useEffect(() => { excludedRef.current = new Set(excludedFeatureIds); }, [excludedFeatureIds]);

    const roadList = roads.split(',').map(r => r.trim()).filter(Boolean);
    const roadKey = roadList.join('|');

    useEffect(() => {
        let cancelled = false;
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
            rendererRef.current?.destroy();
            rendererRef.current = null;
            layerRef.current = null;
        };
    }, [apiKey]);

    const styleFor = useCallback((feature: GeoFeature): VectorStyle => {
        const id = String(feature.properties?.feature_id ?? '');
        const off = excludedRef.current.has(id);
        return {
            strokeColor: off ? EXCLUDED : INCLUDED,
            // Corridor width is metres on the ground and a stroke is screen
            // pixels, so this is indicative rather than a true buffer -- but it
            // makes the setting legible instead of abstract.
            strokeWidth: off ? 2 : Math.max(3, Math.round(corridorMetres / 3)),
            strokeOpacity: off ? 0.35 : 0.85,
        };
    }, [corridorMetres]);

    /** Re-evaluate the existing layer rather than refetching: the geometry has
     *  not changed, only which pieces count. */
    const restyle = useCallback(() => {
        layerRef.current?.setStyle(styleFor);
    }, [styleFor]);

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

        layerRef.current?.remove();
        layerRef.current = null;
        setSegmentCount(0);

        if (!roadList.length) return;

        let cancelled = false;
        setLoading(true);
        api.getRoadGeometry(roadList)
            .then(collection => {
                if (cancelled || !rendererRef.current) return;
                setUnavailable(collection.available === false);
                setSegmentCount(collection.features.length);
                pathsRef.current = new Map(
                    collection.features.map(f => [
                        String(f.properties.feature_id),
                        (f.geometry.coordinates || []).map(([lng, lat]) => ({ lat, lng })),
                    ]),
                );
                if (!collection.features.length) return;

                layerRef.current = rendererRef.current.addGeoJsonLayer({
                    data: collection,
                    style: styleFor,
                    onFeatureClick: feature => {
                        const id = feature.properties?.feature_id;
                        if (!id) return;
                        // Select rather than toggle: with trimming there is more
                        // than one thing a clerk might want to do to a stretch,
                        // so the click opens the choice instead of making it.
                        setSelected({
                            id: String(id),
                            name: String(feature.properties?.name || 'this stretch'),
                            path: pathsRef.current.get(String(id)) || [],
                        });
                    },
                });

                const bounds = boundsOfGeoJson(collection);
                if (bounds) rendererRef.current.fitBounds(bounds, { padding: 40 });
            })
            .catch(() => !cancelled && setUnavailable(true))
            .finally(() => !cancelled && setLoading(false));

        return () => { cancelled = true; };
        // roadKey rather than the array so a re-render with equal contents does
        // not refetch the whole town's geometry.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [roadKey, ready, styleFor, toggleSegment]);

    // Draggable handles at the trim boundaries of the selected stretch.
    useEffect(() => {
        const renderer = rendererRef.current;
        handleLayerRef.current?.remove();
        handleLayerRef.current = null;
        if (!renderer || !ready || !selected || selected.path.length < 2) return;

        const trim = trims[selected.id] || { start: 0, end: 1 };
        const layer = renderer.createMarkerLayer();

        const commit = (which: 'start' | 'end') => (position: LatLng) => {
            const fraction = fractionAlongLine(selected.path, position);
            const current = trimsRef.current[selected.id] || { start: 0, end: 1 };
            const next = { ...current, [which]: fraction };
            // Dragging the handles across each other is a normal thing to do
            // and should mean "the other way round", not an empty rule.
            const ordered = next.start <= next.end
                ? next
                : { start: next.end, end: next.start };

            const updated = { ...trimsRef.current };
            if (ordered.start <= 0.001 && ordered.end >= 0.999) delete updated[selected.id];
            else updated[selected.id] = ordered;
            onTrimsChange(updated);
        };

        const markers = (['start', 'end'] as const).flatMap(which => {
            const position = pointAtFraction(selected.path, trim[which]);
            return position ? [{
                position,
                draggable: true,
                icon: {
                    type: 'circle' as const,
                    radius: 8,
                    fillColor: '#fbbf24',
                    fillOpacity: 1,
                    strokeColor: '#78350f',
                    strokeWidth: 2,
                },
                title: which === 'start' ? 'Drag: where this rule starts' : 'Drag: where this rule ends',
                zIndex: 200,
                onDragEnd: commit(which),
            }] : [];
        });

        layer.setMarkers(markers);
        handleLayerRef.current = layer;
    }, [selected, trims, ready, onTrimsChange]);

    const excludedCount = excludedFeatureIds.length;
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
                    <div className="absolute inset-0 flex items-center justify-center text-center px-6">
                        <div>
                            <MapPin className="w-7 h-7 mx-auto mb-2 text-white/25" aria-hidden="true" />
                            <p className="text-sm text-white/50">Road data hasn&apos;t loaded for this town yet.</p>
                            <p className="text-xs text-white/35 mt-1">
                                Rules still work — you just can&apos;t preview them here.
                            </p>
                        </div>
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
                    <span className="text-sm font-medium text-white tabular-nums">{corridorMetres} m</span>
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

import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Loader2, MapPin, RotateCcw } from 'lucide-react';

import { api } from '../services/api';
import {
    GeoFeature,
    GeoJsonLayerHandle,
    MapRenderer,
    VectorStyle,
    boundsOfGeoJson,
    createMap,
    legacyMapProviderConfig,
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

interface RoadCorridorMapProps {
    /** Road names currently in the rule, comma-separated as routing_config stores them. */
    roads: string;
    /** Feature ids the clerk has switched off. */
    excludedFeatureIds: string[];
    onExcludedChange: (ids: string[]) => void;
    corridorMetres: number;
    onCorridorMetresChange: (metres: number) => void;
    apiKey?: string | null;
}

const INCLUDED = '#f87171';
const EXCLUDED = '#64748b';

export default function RoadCorridorMap({
    roads, excludedFeatureIds, onExcludedChange,
    corridorMetres, onCorridorMetresChange, apiKey,
}: RoadCorridorMapProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const rendererRef = useRef<MapRenderer | null>(null);
    const layerRef = useRef<GeoJsonLayerHandle | null>(null);
    // Read inside the style callback, which the renderer may call at any time.
    // A ref rather than state so a redraw never closes over a stale set.
    const excludedRef = useRef(new Set(excludedFeatureIds));

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
            center: { lat: 40.3573, lng: -74.6672 },
            zoom: 13,
            controls: { zoom: { enabled: true }, fullscreen: { enabled: true } },
        })
            .then(renderer => {
                if (cancelled) { renderer.destroy(); return; }
                rendererRef.current = renderer;
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
                if (!collection.features.length) return;

                layerRef.current = rendererRef.current.addGeoJsonLayer({
                    data: collection,
                    style: styleFor,
                    onFeatureClick: feature => {
                        const id = feature.properties?.feature_id;
                        if (id) toggleSegment(String(id));
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

    const excludedCount = excludedFeatureIds.length;

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

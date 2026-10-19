import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import { api, ContextLayer } from '../services/api';
import { GeoJsonLayerHandle, MapRenderer, PopupHandle, el, popupRoot } from '../maps';

/**
 * Context-layer outlines (tax parcels, zones) on the staff map, and in public
 * mode on the resident maps (Community Requests, the report form).
 *
 * A parcel layer is tens of thousands of polygons, so it is never shipped to
 * the browser whole. At parcel zoom the map asks the server for the outlines
 * inside its viewport -- simplified, and capped per request -- and redraws on
 * every settled pan or zoom. Zoomed out, or past the cap, nothing is drawn and
 * the filter panel says "zoom in" instead of drawing an arbitrary subset.
 */

export type OutlineStatus = 'loading' | 'zoom_in' | 'shown' | 'error';

/**
 * 'staff': every active polygon layer, from the staff routes, with a label
 * popup. 'public': only the polygon layers an admin put on the resident
 * portal, from the public geometry-only route -- thin outlines, no popup,
 * because there is nothing to say about a shape and it must not read as a
 * report. 'off': nothing.
 */
export type OutlineMode = 'staff' | 'public' | 'off';

const DEBOUNCE_MS = 80;
const MIN_ZOOM = 15;
/**
 * Each fetch covers a quarter of a screen more on every side, and is kept: a
 * pan within that margin, or zooming further in, redraws from it with no
 * request at all. That is most of the "slow to pop up" -- the outlines used to
 * be refetched for every settle of the camera.
 */
const PAD = 0.25;
/** Zooming in this many levels past a cached fetch still reuses it. */
const REUSE_ZOOM_LEVELS = 3;

type Box = { west: number; south: number; east: number; north: number };
const padded = (b: Box): Box => {
    const dx = (b.east - b.west) * PAD, dy = (b.north - b.south) * PAD;
    return { west: b.west - dx, south: b.south - dy, east: b.east + dx, north: b.north + dy };
};
const contains = (outer: Box, inner: Box) =>
    inner.west >= outer.west && inner.east <= outer.east && inner.south >= outer.south && inner.north <= outer.north;

/** A report's own feature in a layer, drawn stronger than its neighbours. */
export interface OutlineHighlight { layer_id: number; feature_key: string }

/**
 * Whether residents looking at `categories` see this layer. An admin scopes a
 * resident-visible layer with resident_service_codes; empty means every
 * category. `categories` null means no filter at all; an empty array means
 * none chosen, which leaves only the layers that apply everywhere.
 */
export function layerAppliesToCategories(
    layer: Pick<ContextLayer, 'resident_service_codes' | 'service_codes'>,
    categories: readonly string[] | null | undefined,
    audience: 'public' | 'staff' = 'public',
): boolean {
    // Residents: the categories an admin chose for the outlines. Staff: the
    // categories the layer is recorded on -- the same rule that decides whether
    // a report gets this layer's parcel attached.
    const codes = (audience === 'public' ? layer.resident_service_codes : layer.service_codes) || [];
    if (!categories || codes.length === 0) return true;
    return codes.some(code => categories.includes(code));
}

/** The resident-visible polygon layers, from the public layer list. */
async function publicPolygonLayers(): Promise<ContextLayer[]> {
    const layers = await api.getMapLayers();
    return layers
        .filter(l => l.feature_storage === 'table' && l.is_active !== false && l.visible_on_map !== false)
        .map(l => ({
            id: l.id, name: l.name, fill_color: l.fill_color, stroke_color: l.stroke_color,
            fill_opacity: l.fill_opacity, stroke_width: l.stroke_width, visible_on_map: true,
            resident_service_codes: l.resident_service_codes ?? [],
            feature_count: null, min_zoom: MIN_ZOOM,
        }));
}

export function useContextLayerOutlines(
    mapRef: MutableRefObject<MapRenderer | null>,
    popupRef: MutableRefObject<PopupHandle | null>,
    mapReady: boolean,
    mode: OutlineMode,
    /**
     * Public mode: draw only the layers that apply to these categories (see
     * layerAppliesToCategories). Omitted or null: every layer, as the staff
     * map always has.
     */
    categories?: readonly string[] | null,
    /** Features to draw stronger (staff mode): the parcel a report fell in. */
    highlight?: readonly OutlineHighlight[] | null,
) {
    const enabled = mode !== 'off';
    const isPublic = mode === 'public';
    const [allLayers, setLayers] = useState<ContextLayer[]>([]);
    // A new array each render from most callers; keyed on its contents so the
    // drawing effect only re-runs when the categories really change.
    const categoryKey = categories ? categories.join('\u0000') : null;
    const layers = useMemo(() => {
        if (categoryKey === null) return allLayers;
        const chosen = categoryKey === '' ? [] : categoryKey.split('\u0000');
        return allLayers.filter(l => layerAppliesToCategories(l, chosen, isPublic ? 'public' : 'staff'));
    }, [allLayers, isPublic, categoryKey]);
    const highlightKey = (highlight || []).map(h => `${h.layer_id}:${h.feature_key}`).sort().join('\u0000');
    const [visible, setVisible] = useState<Record<number, boolean>>({});
    const [status, setStatus] = useState<Record<number, OutlineStatus>>({});
    const handles = useRef<Record<number, GeoJsonLayerHandle>>({});
    /** Per layer: the last padded fetch, and whether it is what is drawn. */
    const cache = useRef<Record<number, { box: Box; zoom: number; fc: any; drawn: boolean }>>({});

    useEffect(() => {
        if (!enabled) return;
        let cancelled = false;
        (isPublic ? publicPolygonLayers() : api.getContextLayers())
            .then(rows => {
                if (cancelled) return;
                setLayers(rows);
                setVisible(Object.fromEntries(rows.map(l => [l.id, l.visible_on_map !== false])));
            })
            .catch(() => { /* no context layers, or not signed in: draw nothing */ });
        return () => { cancelled = true; };
    }, [enabled, isPublic]);

    const clear = useCallback((id: number) => {
        handles.current[id]?.remove();
        delete handles.current[id];
        if (cache.current[id]) cache.current[id].drawn = false;
    }, []);

    useEffect(() => {
        const map = mapRef.current;
        if (!enabled || !mapReady || !map || layers.length === 0) return;
        let timer: ReturnType<typeof setTimeout> | null = null;
        let controller: AbortController | null = null;

        const highlighted = new Set(highlightKey ? highlightKey.split('\u0000') : []);

        // Draw the new outlines first and only then remove the old ones, so a
        // redraw never blinks the map empty.
        const draw = (layer: ContextLayer, fc: any) => {
            const previous = handles.current[layer.id];
            handles.current[layer.id] = map.addGeoJsonLayer(isPublic ? {
                // Residents: shapes only, no popup. Strong enough to read over
                // satellite imagery, faint enough not to look like a report.
                data: fc,
                style: {
                    fillColor: layer.stroke_color,
                    fillOpacity: 0.08,
                    strokeColor: layer.stroke_color,
                    strokeWidth: 2,
                    strokeOpacity: 0.95,
                    // A click goes through to the map, where it places the pin.
                    clickable: false,
                },
            } : {
                data: fc,
                style: feature => {
                    const key = (feature.properties as { feature_key?: string }).feature_key;
                    const mine = key != null && highlighted.has(`${layer.id}:${key}`);
                    return {
                        fillColor: layer.fill_color,
                        fillOpacity: mine ? 0.35 : Math.min(Math.max(layer.fill_opacity ?? 0.1, 0.08), 0.15),
                        strokeColor: layer.stroke_color,
                        strokeWidth: mine ? 4 : Math.max(2, Math.min(layer.stroke_width ?? 2, 3)),
                        strokeOpacity: 0.95,
                        zIndex: mine ? 2 : 1,
                    };
                },
                onFeatureClick: (feature, e) => {
                    const popup = popupRef.current;
                    if (!popup) return;
                    const props = feature.properties as { label?: string; feature_key?: string };
                    // Values come from an uploaded file: set as text, never markup.
                    popup.setContent(popupRoot('padding: 12px 14px; min-width: 160px;', [
                        el('div', { style: 'font-size: 11px; color: #64748b; margin-bottom: 2px;', text: layer.name }),
                        el('div', { style: 'font-size: 14px; font-weight: 600; color: #0f172a;', text: String(props.label || props.feature_key || '') }),
                    ]));
                    popup.openAt(e.position);
                },
            });
            previous?.remove();
            if (cache.current[layer.id]) cache.current[layer.id].drawn = true;
        };

        const refresh = () => {
            controller?.abort();
            controller = new AbortController();
            const signal = controller.signal;
            const bounds = map.getBounds();
            const zoom = map.getZoom();
            layers.forEach(layer => {
                if (!visible[layer.id]) {
                    clear(layer.id);
                    return;
                }
                if (!bounds || zoom < (layer.min_zoom ?? MIN_ZOOM)) {
                    clear(layer.id);
                    setStatus(s => ({ ...s, [layer.id]: 'zoom_in' }));
                    return;
                }
                const view = bounds as Box;
                const hit = cache.current[layer.id];
                if (hit && contains(hit.box, view) && Math.abs(zoom - hit.zoom) <= REUSE_ZOOM_LEVELS) {
                    // Already have it: draw from the cache (or leave it drawn).
                    if (!hit.drawn) draw(layer, hit.fc);
                    setStatus(s => ({ ...s, [layer.id]: 'shown' }));
                    return;
                }
                setStatus(s => ({ ...s, [layer.id]: 'loading' }));
                const z = Math.round(zoom);
                const fetchBox = (box: Box) => (isPublic
                    ? api.getPublicLayerOutlines(layer.id, box, z, signal)
                    : api.getContextLayerFeatures(layer.id, box, z, signal));
                const wide = padded(view);
                fetchBox(wide)
                    // Too many features with the margin: the screen alone may still fit.
                    .then(fc => (fc.zoom_in ? fetchBox(view).then(exact => ({ fc: exact, box: view })) : { fc, box: wide }))
                    .then(({ fc, box }) => {
                        if (signal.aborted) return;
                        if (fc.zoom_in) {
                            clear(layer.id);
                            delete cache.current[layer.id];
                            setStatus(s => ({ ...s, [layer.id]: 'zoom_in' }));
                            return;
                        }
                        cache.current[layer.id] = { box, zoom, fc, drawn: false };
                        draw(layer, fc);
                        setStatus(s => ({ ...s, [layer.id]: 'shown' }));
                    })
                    .catch(err => {
                        if (signal.aborted || (err as Error)?.name === 'AbortError') return;
                        setStatus(s => ({ ...s, [layer.id]: 'error' }));
                    });
            });
        };
        const schedule = () => {
            if (timer) clearTimeout(timer);
            timer = setTimeout(refresh, DEBOUNCE_MS);
        };
        const off = map.on('idle', schedule);
        schedule();
        return () => {
            off();
            if (timer) clearTimeout(timer);
            controller?.abort();
            Object.keys(handles.current).forEach(id => clear(Number(id)));
        };
    }, [enabled, isPublic, mapReady, layers, visible, mapRef, popupRef, clear, highlightKey]);

    return { layers, visible, setVisible, status };
}

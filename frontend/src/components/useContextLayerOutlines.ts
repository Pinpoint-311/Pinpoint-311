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

const DEBOUNCE_MS = 250;
const MIN_ZOOM = 15;

/**
 * Whether residents looking at `categories` see this layer. An admin scopes a
 * resident-visible layer with resident_service_codes; empty means every
 * category. `categories` null means no filter at all; an empty array means
 * none chosen, which leaves only the layers that apply everywhere.
 */
export function layerAppliesToCategories(
    layer: Pick<ContextLayer, 'resident_service_codes'>,
    categories: readonly string[] | null | undefined,
): boolean {
    const codes = layer.resident_service_codes || [];
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
) {
    const enabled = mode !== 'off';
    const isPublic = mode === 'public';
    const [allLayers, setLayers] = useState<ContextLayer[]>([]);
    // A new array each render from most callers; keyed on its contents so the
    // drawing effect only re-runs when the categories really change.
    const categoryKey = categories ? categories.join('\u0000') : null;
    const layers = useMemo(() => {
        if (!isPublic || categoryKey === null) return allLayers;
        const chosen = categoryKey === '' ? [] : categoryKey.split('\u0000');
        return allLayers.filter(l => layerAppliesToCategories(l, chosen));
    }, [allLayers, isPublic, categoryKey]);
    const [visible, setVisible] = useState<Record<number, boolean>>({});
    const [status, setStatus] = useState<Record<number, OutlineStatus>>({});
    const handles = useRef<Record<number, GeoJsonLayerHandle>>({});

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
    }, []);

    useEffect(() => {
        const map = mapRef.current;
        if (!enabled || !mapReady || !map || layers.length === 0) return;
        let timer: ReturnType<typeof setTimeout> | null = null;
        let controller: AbortController | null = null;

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
                setStatus(s => ({ ...s, [layer.id]: 'loading' }));
                (isPublic
                    ? api.getPublicLayerOutlines(layer.id, bounds, Math.round(zoom), signal)
                    : api.getContextLayerFeatures(layer.id, bounds, Math.round(zoom), signal))
                    .then(fc => {
                        if (signal.aborted) return;
                        clear(layer.id);
                        if (fc.zoom_in) {
                            setStatus(s => ({ ...s, [layer.id]: 'zoom_in' }));
                            return;
                        }
                        handles.current[layer.id] = map.addGeoJsonLayer(isPublic ? {
                            // Residents: a thin line and almost no fill, no popup.
                            data: fc,
                            style: {
                                fillColor: layer.stroke_color,
                                fillOpacity: 0.03,
                                strokeColor: layer.stroke_color,
                                strokeWidth: 1,
                                strokeOpacity: 0.6,
                            },
                        } : {
                            data: fc,
                            style: {
                                fillColor: layer.fill_color,
                                fillOpacity: Math.min(layer.fill_opacity ?? 0.1, 0.15),
                                strokeColor: layer.stroke_color,
                                strokeWidth: Math.max(1, Math.min(layer.stroke_width ?? 1, 3)),
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
    }, [enabled, isPublic, mapReady, layers, visible, mapRef, popupRef, clear]);

    return { layers, visible, setVisible, status };
}

import { useEffect, useRef, useState } from 'react';
import { MapPin } from 'lucide-react';
import { MapLayer } from '../services/api';
import {
    GeoJsonLayerHandle,
    MapRenderer,
    MarkerHandle,
    PopupHandle,
    assetIcon,
    createMap,
    locationPinIcon,
    el,
    MapProviderConfig,
    firstPolygonRings,
    hasMapCredential,
    popupRoot,
    propertyRows,
} from '../maps';

interface MatchedAsset {
    layer_name: string;
    asset_id?: string;
    asset_type?: string;
    properties?: Record<string, any>;
    distance_meters?: number;
}

interface RequestDetailMapProps {
    lat: number;
    lng: number;
    matchedAsset?: MatchedAsset | null;
    mapLayers: MapLayer[];
    /**
     * The town's chosen provider and only that provider's credentials.
     * Built once per page with resolveMapProviderConfig(); components must not
     * assemble their own, which is how every map silently defaulted to Google.
     */
    config: MapProviderConfig;
    /**
     * The town's outline, drawn as context under the request pin. Same GeoJSON
     * LocationPicker takes, from the same `township_boundary` field of
     * /gis/config -- residents saw it while dropping the pin and then lost it
     * the moment they looked the request up again, because this component never
     * had a way to be told about it.
     */
    townshipBoundary?: object | null;
}

export default function RequestDetailMap({
    lat,
    lng,
    matchedAsset,
    mapLayers,
    config,
    townshipBoundary,
}: RequestDetailMapProps) {
    const mapRef = useRef<HTMLDivElement>(null);
    const mapInstanceRef = useRef<MapRenderer | null>(null);
    const markerRef = useRef<MarkerHandle | null>(null);
    const assetLayerRef = useRef<GeoJsonLayerHandle | null>(null);
    const assetMarkerRef = useRef<MarkerHandle | null>(null);
    const popupRef = useRef<PopupHandle | null>(null);
    const boundaryRef = useRef<{ remove(): void } | null>(null);

    const [isLoading, setIsLoading] = useState(true);
    const [mapReady, setMapReady] = useState(false);
    /**
     * Where the matched asset's own marker ended up, when the layer gives us a
     * point. Held in state only so the text equivalent below can say it: the
     * position is worked out inside a map effect and otherwise exists nowhere
     * outside the provider's canvas.
     */
    const [assetPoint, setAssetPoint] = useState<{ lat: number; lng: number } | null>(null);

    // Load the configured map provider and attach the map
    useEffect(() => {
        if (!hasMapCredential(config)) {
            setIsLoading(false);
            return;
        }

        let isMounted = true;

        (async () => {
            if (!mapRef.current) return;
            try {
                const map = await createMap(
                    mapRef.current,
                    config,
                    {
                        center: { lat, lng },
                        zoom: 18,
                        baseMapType: 'hybrid',
                        controls: {
                            baseMapSwitcher: {
                                enabled: true,
                                position: 'top-left',
                                types: ['roadmap', 'satellite', 'hybrid'],
                            },
                            streetView: { enabled: true },
                            fullscreen: { enabled: true },
                            zoom: { enabled: true, position: 'left-bottom' },
                        },
                    },
                );

                if (!isMounted) {
                    map.destroy();
                    return;
                }

                mapInstanceRef.current = map;
                popupRef.current = map.createPopup();
                setIsLoading(false);
                setMapReady(true);
            } catch (e) {
                console.error('Failed to initialize map:', e);
                if (isMounted) setIsLoading(false);
            }
        })();

        return () => {
            isMounted = false;
            markerRef.current = null;
            assetMarkerRef.current = null;
            assetLayerRef.current = null;
            boundaryRef.current = null;
            popupRef.current = null;
            mapInstanceRef.current?.destroy();
            mapInstanceRef.current = null;
        };
    }, [config.provider, config.apiKey, config.styleId]);

    /**
     * The town outline, drawn exactly the way LocationPicker draws it: ring 0 is
     * the outer boundary and the rest are holes, so one polygon renders the
     * holes, and anything that is not a simple polygon falls back to a GeoJSON
     * layer.
     *
     * No fitBounds, and that is the difference from LocationPicker rather than
     * an omission. That component is choosing a location anywhere in the town,
     * so the town is the right frame. This one is showing a resident where their
     * one request is, at street level -- fitting the whole municipality would
     * shrink the pin they came to look at to a dot. The outline is context for
     * a request near a border; the camera stays on the request.
     */
    useEffect(() => {
        const map = mapInstanceRef.current;
        if (!map) return;

        boundaryRef.current?.remove();
        boundaryRef.current = null;

        if (!townshipBoundary) return;

        try {
            const rings = firstPolygonRings(townshipBoundary);
            const style = {
                fillColor: '#6366f1',
                fillOpacity: 0.12,
                strokeColor: '#6366f1',
                strokeWidth: 3,
                strokeOpacity: 1,
                clickable: false,
            };
            boundaryRef.current = rings.length > 0
                ? map.addPolygon({ paths: rings, style })
                : map.addGeoJsonLayer({ data: townshipBoundary, style });
        } catch (e) {
            console.warn('Failed to add township boundary:', e);
        }
    }, [townshipBoundary, mapReady]);

    // Update map when coordinates change
    useEffect(() => {
        const map = mapInstanceRef.current;
        if (!map) return;

        map.setCenter({ lat, lng });

        markerRef.current?.remove();
        markerRef.current = map.addMarker({
            position: { lat, lng },
            // A pin, not a puck: this map is about one exact spot, which is what
            // the pin shape means everywhere else in the app.
            icon: locationPinIcon('#ef4444'),
            title: `Request location: ${lat.toFixed(6)}, ${lng.toFixed(6)}`,
            zIndex: 1000,
            onClick: (_e, marker) => {
                const popup = popupRef.current;
                if (!popup) return;

                popup.setContent(popupRoot('padding: 12px;', [
                    el('h4', {
                        style: 'margin: 0 0 8px 0; font-size: 14px; font-weight: 600; color: #1f2937;',
                        text: '📍 Request Location',
                    }),
                    el('p', {
                        style: 'margin: 0; font-size: 12px; color: #6b7280;',
                        text: `Lat: ${lat.toFixed(6)}, Lng: ${lng.toFixed(6)}`,
                    }),
                ]));
                popup.openAt(marker);
            },
        });
    }, [lat, lng, mapReady]);

    // Overlay matched asset with improved styling
    useEffect(() => {
        const map = mapInstanceRef.current;
        if (!map) return;

        assetLayerRef.current?.remove();
        assetLayerRef.current = null;
        assetMarkerRef.current?.remove();
        assetMarkerRef.current = null;
        setAssetPoint(null);

        if (!matchedAsset) return;

        // Find the layer that matches this asset
        const matchingLayer = mapLayers.find(l => l.name === matchedAsset.layer_name);
        if (!matchingLayer?.geojson) return;

        try {
            const geojson = matchingLayer.geojson as any;

            // Find the specific feature that matches the asset
            let targetFeature: any = null;

            if (geojson.type === 'FeatureCollection' && geojson.features) {
                targetFeature = geojson.features.find((f: any) => {
                    const props = f.properties || {};
                    return props.id === matchedAsset.asset_id ||
                        props.asset_id === matchedAsset.asset_id ||
                        props.OBJECTID === matchedAsset.asset_id ||
                        props.ID === matchedAsset.asset_id;
                });
            }

            assetLayerRef.current = map.addGeoJsonLayer({
                data: targetFeature
                    ? { type: 'FeatureCollection', features: [targetFeature] }
                    : geojson,
                style: {
                    fillColor: matchingLayer.fill_color || '#22c55e',
                    fillOpacity: 0.4,
                    strokeColor: '#22c55e',
                    strokeWidth: 3,
                    strokeOpacity: 1,
                },
            });

            // If it's a point feature, add a distinct marker with better icon
            if (targetFeature?.geometry?.type === 'Point') {
                const coords = targetFeature.geometry.coordinates;
                setAssetPoint({ lat: coords[1], lng: coords[0] });
                assetMarkerRef.current = map.addMarker({
                    position: { lat: coords[1], lng: coords[0] },
                    // The same asset glyph the other maps use. This had its own
                    // hardcoded green diamond, so the matched asset here looked
                    // nothing like the identical asset on the staff dashboard.
                    icon: assetIcon('#22c55e'),
                    title: `${matchedAsset.layer_name}${matchedAsset.asset_id ? ` - ${matchedAsset.asset_id}` : ''}`,
                    zIndex: 999,
                    onClick: (_e, marker) => {
                        const popup = popupRef.current;
                        if (!popup) return;

                        const rows = propertyRows(
                            matchedAsset.properties || {},
                            {
                                row: 'display: flex; justify-content: space-between; gap: 12px;',
                                key: 'color: #9ca3af;',
                                value: 'color: #fff;',
                            },
                            { skipKeys: ['id', 'name'], limit: 5 },
                        );

                        popup.setContent(popupRoot(
                            'padding: 12px; background: #1f2937; border-radius: 8px; min-width: 200px;',
                            [
                                el('h4', {
                                    style: 'margin: 0 0 8px 0; font-size: 14px; font-weight: 600; color: #22c55e; display: flex; align-items: center; gap: 6px;',
                                    children: [
                                        el('span', { style: 'display: inline-block; width: 8px; height: 8px; background: #22c55e; border-radius: 2px;' }),
                                        matchedAsset.layer_name,
                                    ],
                                }),
                                matchedAsset.asset_id && el('p', {
                                    style: 'margin: 0 0 8px 0; font-size: 11px; color: #9ca3af; font-family: monospace;',
                                    text: `ID: ${matchedAsset.asset_id}`,
                                }),
                                el('div', {
                                    style: 'font-size: 12px; display: flex; flex-direction: column; gap: 4px;',
                                    children: rows.length
                                        ? rows
                                        : [el('span', { style: 'color: #6b7280;', text: 'No properties' })],
                                }),
                            ],
                        ));
                        popup.openAt(marker);
                    },
                });
            }
        } catch (e) {
            console.error('Error overlaying matched asset:', e);
        }
    }, [matchedAsset, mapLayers, mapReady]);

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

    return (
        <div className="relative h-full rounded-lg overflow-hidden z-0">
            {/* Map Container */}
            {isLoading && (
                <div className="absolute inset-0 flex items-center justify-center bg-slate-900 z-10">
                    <div className="w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
                </div>
            )}
            <div ref={mapRef} className="w-full h-full" />

            {/* The map in words -- WCAG 1.1.1 / 2.1.1.
             *
             * Both markers here are mouse-only: the provider draws them onto a
             * canvas and their popups open on click, so everything the popups
             * say was unreadable without a pointer. The asset popup was the
             * worse half -- its property rows exist in no other DOM node on the
             * page, so a keyboard or screen-reader user could not reach them at
             * all.
             *
             * Rendered sr-only rather than as a visible block because every
             * caller sizes this component with a fixed-height wrapper it owns
             * (h-48 in the staff detail panel and in Track Requests); a visible
             * block here would eat the map inside that box. The content is not
             * operable -- it is the alternative text for a picture -- so being
             * available to assistive tech rather than focusable is the right
             * shape for it.
             *
             * The staff request panel already prints the matched asset's layer,
             * ID, type, distance and a filtered property table below this map,
             * so the overlap there is deliberate and small: the coordinates and
             * the properties that panel filters out (it drops purely numeric
             * values, which is most dimensions on a real asset layer) exist
             * only here. Track Requests renders this map with no matched asset
             * and no such panel, so this component cannot rely on a caller
             * having said any of it. */}
            <div className="sr-only">
                <h4>Map location details</h4>
                <p>{`Reported location: latitude ${lat.toFixed(6)}, longitude ${lng.toFixed(6)}.`}</p>
                {matchedAsset && (
                    <>
                        <h5>{`Matched asset marker: ${matchedAsset.layer_name}`}</h5>
                        <ul>
                            {matchedAsset.asset_id && <li>{`Asset ID: ${matchedAsset.asset_id}`}</li>}
                            {assetPoint && (
                                <li>
                                    {`Asset marker location: latitude ${assetPoint.lat.toFixed(6)}, longitude ${assetPoint.lng.toFixed(6)}.`}
                                </li>
                            )}
                            {/* The same rows, and the same trimming, the popup
                                shows -- so the text version cannot say more or
                                less than the picture does. */}
                            {Object.entries(matchedAsset.properties || {})
                                .filter(([k]) => k !== 'id' && k !== 'name')
                                .slice(0, 5)
                                .map(([k, v]) => <li key={k}>{`${k}: ${String(v)}`}</li>)}
                        </ul>
                    </>
                )}
            </div>
        </div>
    );
}

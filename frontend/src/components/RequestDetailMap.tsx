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
}

export default function RequestDetailMap({
    lat,
    lng,
    matchedAsset,
    mapLayers,
    config,
}: RequestDetailMapProps) {
    const mapRef = useRef<HTMLDivElement>(null);
    const mapInstanceRef = useRef<MapRenderer | null>(null);
    const markerRef = useRef<MarkerHandle | null>(null);
    const assetLayerRef = useRef<GeoJsonLayerHandle | null>(null);
    const assetMarkerRef = useRef<MarkerHandle | null>(null);
    const popupRef = useRef<PopupHandle | null>(null);

    const [isLoading, setIsLoading] = useState(true);
    const [mapReady, setMapReady] = useState(false);

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
            popupRef.current = null;
            mapInstanceRef.current?.destroy();
            mapInstanceRef.current = null;
        };
    }, [config.provider, config.apiKey, config.styleId]);

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
            title: 'Request Location',
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
                    <MapPin className="w-8 h-8 mx-auto mb-2 text-white/30" />
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
        </div>
    );
}

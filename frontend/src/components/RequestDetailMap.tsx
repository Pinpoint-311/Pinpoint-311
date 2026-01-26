import { useEffect, useRef, useState, useCallback } from 'react';
import { MapPin } from 'lucide-react';
import { MapLayer } from '../services/api';

declare global {
    interface Window {
        google: typeof google;
    }
}

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
    apiKey: string;
}

export default function RequestDetailMap({
    lat,
    lng,
    matchedAsset,
    mapLayers,
    apiKey,
}: RequestDetailMapProps) {
    const mapRef = useRef<HTMLDivElement>(null);
    const mapInstanceRef = useRef<google.maps.Map | null>(null);
    const markerRef = useRef<google.maps.Marker | null>(null);
    const assetLayerRef = useRef<google.maps.Data | null>(null);
    const assetMarkerRef = useRef<google.maps.Marker | null>(null);
    const infoWindowRef = useRef<google.maps.InfoWindow | null>(null);

    const [isLoading, setIsLoading] = useState(true);

    // Load Google Maps script
    useEffect(() => {
        if (!apiKey) {
            setIsLoading(false);
            return;
        }

        if (window.google?.maps) {
            initMap();
            return;
        }

        const script = document.createElement("script");
        script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=places`;
        script.async = true;
        script.onload = () => initMap();
        script.onerror = () => setIsLoading(false);
        document.head.appendChild(script);

        return () => {
            if (markerRef.current) markerRef.current.setMap(null);
            if (assetMarkerRef.current) assetMarkerRef.current.setMap(null);
            if (assetLayerRef.current) assetLayerRef.current.setMap(null);
        };
    }, [apiKey]);

    const initMap = useCallback(() => {
        if (!mapRef.current || !window.google) return;

        const map = new window.google.maps.Map(mapRef.current, {
            center: { lat, lng },
            zoom: 18,
            mapTypeId: 'hybrid',
            mapTypeControl: true,
            mapTypeControlOptions: {
                style: window.google.maps.MapTypeControlStyle.HORIZONTAL_BAR,
                position: window.google.maps.ControlPosition.TOP_LEFT,
                mapTypeIds: ['roadmap', 'satellite', 'hybrid'],
            },
            streetViewControl: true,
            fullscreenControl: true,
            zoomControl: true,
            zoomControlOptions: {
                position: window.google.maps.ControlPosition.LEFT_BOTTOM,
            },
        });

        mapInstanceRef.current = map;
        infoWindowRef.current = new window.google.maps.InfoWindow();
        setIsLoading(false);
    }, [lat, lng]);

    // Update map when coordinates change
    useEffect(() => {
        if (!mapInstanceRef.current || !window.google) return;

        const map = mapInstanceRef.current;
        map.setCenter({ lat, lng });

        // Clear old marker
        if (markerRef.current) markerRef.current.setMap(null);

        // Create request location marker - premium pulsing style
        markerRef.current = new window.google.maps.Marker({
            position: { lat, lng },
            map,
            icon: {
                path: window.google.maps.SymbolPath.CIRCLE,
                fillColor: '#ef4444',
                fillOpacity: 1,
                strokeColor: '#ffffff',
                strokeWeight: 3,
                scale: 12,
            },
            title: 'Request Location',
            zIndex: 1000,
        });

        markerRef.current.addListener('click', () => {
            if (infoWindowRef.current) {
                infoWindowRef.current.setContent(`
                    <div style="padding: 12px; font-family: system-ui, -apple-system, sans-serif;">
                        <h4 style="margin: 0 0 8px 0; font-size: 14px; font-weight: 600; color: #1f2937;">📍 Request Location</h4>
                        <p style="margin: 0; font-size: 12px; color: #6b7280;">Lat: ${lat.toFixed(6)}, Lng: ${lng.toFixed(6)}</p>
                    </div>
                `);
                infoWindowRef.current.open(map, markerRef.current);
            }
        });

    }, [lat, lng]);

    // Overlay matched asset with improved styling
    useEffect(() => {
        if (!mapInstanceRef.current || !window.google) return;

        const map = mapInstanceRef.current;

        // Clear previous asset overlay
        if (assetLayerRef.current) assetLayerRef.current.setMap(null);
        if (assetMarkerRef.current) assetMarkerRef.current.setMap(null);

        if (!matchedAsset) return;

        // Find the layer that matches this asset
        const matchingLayer = mapLayers.find(l => l.name === matchedAsset.layer_name);

        if (matchingLayer?.geojson) {
            try {
                const geojson = matchingLayer.geojson as any;
                const dataLayer = new window.google.maps.Data();

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

                if (targetFeature) {
                    dataLayer.addGeoJson({
                        type: 'FeatureCollection',
                        features: [targetFeature]
                    });
                } else {
                    dataLayer.addGeoJson(geojson);
                }

                // Style with emphasis
                dataLayer.setStyle(() => ({
                    fillColor: matchingLayer.fill_color || '#22c55e',
                    fillOpacity: 0.4,
                    strokeColor: '#22c55e',
                    strokeWeight: 3,
                    strokeOpacity: 1,
                }));

                dataLayer.setMap(map);
                assetLayerRef.current = dataLayer;

                // If it's a point feature, add a distinct marker with better icon
                if (targetFeature?.geometry?.type === 'Point') {
                    const coords = targetFeature.geometry.coordinates;
                    assetMarkerRef.current = new window.google.maps.Marker({
                        position: { lat: coords[1], lng: coords[0] },
                        map,
                        icon: {
                            // Use a diamond shape for assets
                            path: 'M 0,-10 L 7,0 L 0,10 L -7,0 Z',
                            fillColor: '#22c55e',
                            fillOpacity: 1,
                            strokeColor: '#ffffff',
                            strokeWeight: 2,
                            scale: 1.2,
                        },
                        title: `${matchedAsset.layer_name}${matchedAsset.asset_id ? ` - ${matchedAsset.asset_id}` : ''}`,
                        zIndex: 999,
                    });

                    // Add click handler for asset info
                    assetMarkerRef.current.addListener('click', () => {
                        if (infoWindowRef.current) {
                            const props = matchedAsset.properties || {};
                            const propsHtml = Object.entries(props)
                                .filter(([k]) => !['id', 'name'].includes(k.toLowerCase()))
                                .slice(0, 5)
                                .map(([k, v]) => `<div style="display: flex; justify-content: space-between; gap: 12px;"><span style="color: #9ca3af;">${k.replace(/_/g, ' ')}</span><span style="color: #fff;">${v}</span></div>`)
                                .join('');

                            infoWindowRef.current.setContent(`
                                <div style="padding: 12px; font-family: system-ui, -apple-system, sans-serif; background: #1f2937; border-radius: 8px; min-width: 200px;">
                                    <h4 style="margin: 0 0 8px 0; font-size: 14px; font-weight: 600; color: #22c55e; display: flex; align-items: center; gap: 6px;">
                                        <span style="display: inline-block; width: 8px; height: 8px; background: #22c55e; border-radius: 2px;"></span>
                                        ${matchedAsset.layer_name}
                                    </h4>
                                    ${matchedAsset.asset_id ? `<p style="margin: 0 0 8px 0; font-size: 11px; color: #9ca3af; font-family: monospace;">ID: ${matchedAsset.asset_id}</p>` : ''}
                                    <div style="font-size: 12px; display: flex; flex-direction: column; gap: 4px;">
                                        ${propsHtml || '<span style="color: #6b7280;">No properties</span>'}
                                    </div>
                                </div>
                            `);
                            infoWindowRef.current.open(map, assetMarkerRef.current);
                        }
                    });
                }

            } catch (e) {
                console.error('Error overlaying matched asset:', e);
            }
        }
    }, [matchedAsset, mapLayers]);

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

    return (
        <div className="relative h-full rounded-lg overflow-hidden">
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

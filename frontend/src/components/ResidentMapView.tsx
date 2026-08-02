import { useEffect, useRef, useState } from 'react';
import { MapPin, Layers, ChevronDown, ChevronRight, X } from 'lucide-react';
import {
    MapProviderId,
    MapRenderer,
    MarkerLayer,
    MarkerOptions,
    PopupHandle,
    boundsOfGeoJson,
    clusterStyle,
    createMap,
    requestIcon,
    el,
    legacyMapProviderConfig,
    popupRoot,
} from '../maps';

// Flexible request type that works with both PublicServiceRequest and ServiceRequest
interface MapRequest {
    service_request_id: string;
    service_code: string;
    service_name: string;
    description: string;
    status: string;
    address: string | null;
    lat: number | null;
    long: number | null;
    requested_datetime: string;
    assigned_department_name?: string | null;
}

interface ResidentMapViewProps {
    apiKey: string;
    mapId?: string | null;
    /** Overrides the configured provider; defaults to the town's setting. */
    provider?: MapProviderId;
    requests: MapRequest[];
    townshipBoundary?: object | null;
    defaultCenter?: { lat: number; lng: number };
    defaultZoom?: number;
    onRequestSelect?: (request: MapRequest) => void;
}

// Status colors
const STATUS_COLORS = {
    open: '#ef4444',        // red
    in_progress: '#f59e0b', // amber
    closed: '#22c55e',      // green
};

const STATUS_LABELS = {
    open: 'Open',
    in_progress: 'In Progress',
    closed: 'Resolved',
};

export default function ResidentMapView({
    apiKey,
    mapId,
    provider,
    requests,
    townshipBoundary,
    defaultCenter = { lat: 40.3573, lng: -74.6672 },
    defaultZoom = 13,
    onRequestSelect,
}: ResidentMapViewProps) {
    const mapRef = useRef<HTMLDivElement>(null);
    const mapInstanceRef = useRef<MapRenderer | null>(null);
    const requestLayerRef = useRef<MarkerLayer | null>(null);
    const popupRef = useRef<PopupHandle | null>(null);

    // Filter state
    const [statusFilters, setStatusFilters] = useState({
        open: true,
        in_progress: true,
        closed: true,
    });
    const [categoryFilters, setCategoryFilters] = useState<Record<string, boolean>>({});
    const [departmentFilters, setDepartmentFilters] = useState<Record<string, boolean>>({});

    // UI state
    const [isLoading, setIsLoading] = useState(true);
    const [mapReady, setMapReady] = useState(false);
    const [showFilters, setShowFilters] = useState(false);
    const [expandedStatus, setExpandedStatus] = useState(true);
    const [expandedCategories, setExpandedCategories] = useState(false);
    const [expandedDepartments, setExpandedDepartments] = useState(false);

    // Extract unique categories and departments from requests
    const uniqueCategories = Array.from(new Set(requests.map(r => r.service_code))).map(code => {
        const req = requests.find(r => r.service_code === code);
        return { code, name: req?.service_name || code };
    });
    const uniqueDepartments = Array.from(new Set(requests.map(r => r.assigned_department_name || 'Unassigned'))).sort();

    // Initialize category filters when requests change
    useEffect(() => {
        const newFilters: Record<string, boolean> = {};
        uniqueCategories.forEach(cat => {
            newFilters[cat.code] = categoryFilters[cat.code] ?? true;
        });
        setCategoryFilters(newFilters);
    }, [requests.map(r => r.service_code).join(',')]);

    // Initialize department filters when requests change
    useEffect(() => {
        const newFilters: Record<string, boolean> = {};
        uniqueDepartments.forEach(dept => {
            newFilters[dept] = departmentFilters[dept] ?? true;
        });
        setDepartmentFilters(newFilters);
    }, [requests.map(r => r.assigned_department_name).join(',')]);

    // Load the configured map provider and attach the map
    useEffect(() => {
        if (!apiKey) {
            setIsLoading(false);
            return;
        }

        let isMounted = true;

        (async () => {
            if (!mapRef.current) return;
            try {
                const map = await createMap(
                    mapRef.current,
                    legacyMapProviderConfig(apiKey, mapId, provider),
                    {
                        center: defaultCenter,
                        zoom: defaultZoom,
                        baseMapType: 'roadmap',
                        // Tilt/heading only take effect on providers rendering a
                        // vector basemap, which is what styleId selects.
                        tilt: mapId ? 45 : undefined,
                        heading: mapId ? 0 : undefined,
                        styleId: mapId,
                        controls: {
                            baseMapSwitcher: {
                                enabled: true,
                                position: 'top-left',
                                types: ['roadmap', 'satellite', 'hybrid'],
                            },
                            streetView: { enabled: false },
                            fullscreen: { enabled: true },
                            zoom: { enabled: true, position: 'right-bottom' },
                            rotate: { enabled: !!mapId },
                        },
                        // Google-only styling; other providers carry POI visibility
                        // in their own style document.
                        vendorOptions: {
                            styles: [
                                { featureType: 'poi', elementType: 'labels', stylers: [{ visibility: 'off' }] },
                            ],
                        },
                    },
                );

                if (!isMounted) {
                    map.destroy();
                    return;
                }

                mapInstanceRef.current = map;
                popupRef.current = map.createPopup();
                requestLayerRef.current = map.createMarkerLayer({
                    // Shared with the staff dashboard and the location picker.
                    // These two had drifted to different radii, stroke weights
                    // and label sizes, so the same forty reports drew a
                    // different bubble depending on which page you opened.
                    cluster: { style: clusterStyle },
                });

                // Render township boundary and fit to it
                if (townshipBoundary) {
                    renderBoundaryAndFit(map, townshipBoundary);
                }

                setIsLoading(false);
                setMapReady(true);
            } catch (e) {
                console.error('Failed to initialize map:', e);
                if (isMounted) setIsLoading(false);
            }
        })();

        return () => {
            isMounted = false;
            requestLayerRef.current = null;
            popupRef.current = null;
            mapInstanceRef.current?.destroy();
            mapInstanceRef.current = null;
        };
    }, [apiKey, mapId, provider]);

    const renderBoundaryAndFit = (map: MapRenderer, boundary: object) => {
        try {
            map.addGeoJsonLayer({
                data: boundary,
                style: {
                    fillColor: '#6366f1',
                    fillOpacity: 0.05,
                    strokeColor: '#6366f1',
                    strokeWidth: 2,
                    strokeOpacity: 0.6,
                },
            });

            const bounds = boundsOfGeoJson(boundary);
            if (bounds) map.fitBounds(bounds);
        } catch (e) {
            console.error('Error rendering boundary:', e);
        }
    };

    // Update markers when filters or requests change
    useEffect(() => {
        if (!mapInstanceRef.current) return;
        updateMarkers();
    }, [requests, statusFilters, categoryFilters, departmentFilters, mapReady]);

    const updateMarkers = () => {
        const requestLayer = requestLayerRef.current;
        if (!requestLayer) return;

        // Filter requests
        const filteredRequests = requests.filter(r => {
            if (!statusFilters[r.status as keyof typeof statusFilters]) return false;
            if (categoryFilters[r.service_code] === false) return false;
            const deptName = r.assigned_department_name || 'Unassigned';
            if (departmentFilters[deptName] === false) return false;
            if (!r.lat || !r.long) return false;
            return true;
        });

        // Create markers
        const markers: MarkerOptions[] = filteredRequests.map(request => ({
            position: { lat: request.lat!, lng: request.long! },
            // The same glyph the staff dashboard uses for the same report. This
            // was a provider-drawn `radius: 9` circle while the dashboard asked
            // for `radius: 10`, so one report was two different dots.
            icon: requestIcon(STATUS_COLORS[request.status as keyof typeof STATUS_COLORS] || '#6366f1'),
            title: request.service_name,
            onClick: (_e, marker) => {
                const popup = popupRef.current;
                if (!popup) return;

                const statusColor = STATUS_COLORS[request.status as keyof typeof STATUS_COLORS];
                const statusLabel = STATUS_LABELS[request.status as keyof typeof STATUS_LABELS] || request.status;
                const description = request.description?.substring(0, 100) || 'No description';
                const truncated = (request.description?.length || 0) > 100;

                popup.setContent(popupRoot('padding: 16px; max-width: 300px;', [
                    el('div', {
                        style: 'display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;',
                        children: [
                            el('span', {
                                style: 'font-size: 12px; color: #6366f1; font-family: monospace; font-weight: 600;',
                                text: `#${request.service_request_id.slice(-8)}`,
                            }),
                            el('span', {
                                style: `font-size: 11px; padding: 4px 10px; border-radius: 9999px; background: ${statusColor}; color: white; font-weight: 600;`,
                                text: statusLabel,
                            }),
                        ],
                    }),
                    el('h3', {
                        style: 'margin: 0 0 8px 0; font-size: 16px; font-weight: 700; color: #1f2937;',
                        text: request.service_name,
                    }),
                    el('p', {
                        style: 'margin: 0 0 12px 0; font-size: 13px; color: #4b5563; line-height: 1.5;',
                        text: truncated ? `${description}...` : description,
                    }),
                    request.address && el('p', {
                        style: 'margin: 0 0 12px 0; font-size: 12px; color: #6b7280;',
                        text: `📍 ${request.address}`,
                    }),
                    el('p', {
                        style: 'margin: 0; font-size: 11px; color: #9ca3af;',
                        text: `Reported ${new Date(request.requested_datetime).toLocaleDateString()}`,
                    }),
                    onRequestSelect && el('button', {
                        style: 'width: 100%; margin-top: 12px; padding: 10px 16px; background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); color: white; border: none; border-radius: 10px; font-size: 13px; font-weight: 600; cursor: pointer;',
                        text: 'View Details',
                        onClick: () => {
                            popup.close();
                            onRequestSelect(request);
                        },
                    }),
                ]));
                popup.openAt(marker);
            },
        }));

        // Bulk replace: the layer's clustering is rebuilt from the new set.
        requestLayer.setMarkers(markers);
    };

    // Count requests by status
    const statusCounts = {
        open: requests.filter(r => r.status === 'open').length,
        in_progress: requests.filter(r => r.status === 'in_progress').length,
        closed: requests.filter(r => r.status === 'closed').length,
    };

    if (!apiKey) {
        return (
            <div className="h-full min-h-[400px] flex items-center justify-center bg-white/5 rounded-2xl border border-white/10">
                <div className="text-center p-8">
                    <MapPin className="w-12 h-12 mx-auto mb-4 text-white/30" />
                    <p className="text-white/60">Map not available</p>
                </div>
            </div>
        );
    }

    return (
        <div className="h-full min-h-[400px] flex relative rounded-2xl overflow-hidden border border-white/10 shadow-xl">
            {/* Map Container */}
            <div className="flex-1 relative">
                {isLoading && (
                    <div className="absolute inset-0 flex items-center justify-center bg-[#1a1a2e] z-10">
                        <div className="w-10 h-10 border-3 border-primary-500 border-t-transparent rounded-full animate-spin" />
                    </div>
                )}
                <div ref={mapRef} className="w-full h-full" />
            </div>

            {/* Filter Toggle Button */}
            <button
                onClick={() => setShowFilters(!showFilters)}
                className="absolute top-4 right-4 z-20 px-4 py-2 bg-white/95 backdrop-blur-md rounded-xl border border-gray-200 hover:bg-white transition-all shadow-lg flex items-center gap-2"
            >
                <Layers className="w-4 h-4 text-gray-600" />
                <span className="text-sm font-medium text-gray-700">Filters</span>
                {!Object.values(statusFilters).every(v => v) && (
                    <span className="w-2 h-2 rounded-full bg-primary-500" />
                )}
            </button>

            {/* Filter Panel */}
            {showFilters && (
                <div className="absolute top-16 right-4 z-20 w-64 bg-white rounded-xl border border-gray-200 shadow-xl overflow-hidden">
                    <div className="p-3 border-b border-gray-100 flex items-center justify-between">
                        <h3 className="font-semibold text-gray-800 text-sm">Filter Requests</h3>
                        <button onClick={() => setShowFilters(false)} className="p-1 hover:bg-gray-100 rounded-lg" aria-label="Close filters">
                            <X className="w-4 h-4 text-gray-400" aria-hidden="true" />
                        </button>
                    </div>

                    <div className="p-3">
                        <button
                            onClick={() => setExpandedStatus(!expandedStatus)}
                            className="w-full flex items-center justify-between py-2"
                        >
                            <span className="text-sm font-medium text-gray-700">Status</span>
                            {expandedStatus ? (
                                <ChevronDown className="w-4 h-4 text-gray-400" />
                            ) : (
                                <ChevronRight className="w-4 h-4 text-gray-400" />
                            )}
                        </button>

                        {expandedStatus && (
                            <div className="space-y-2 pt-2">
                                {Object.entries(statusFilters).map(([status, enabled]) => (
                                    <label key={status} className="flex items-center gap-3 cursor-pointer group">
                                        <input
                                            type="checkbox"
                                            checked={enabled}
                                            onChange={(e) => setStatusFilters(prev => ({ ...prev, [status]: e.target.checked }))}
                                            className="w-4 h-4 rounded border-gray-300 text-primary-500 focus:ring-primary-500"
                                        />
                                        <span
                                            className="w-3 h-3 rounded-full"
                                            style={{ backgroundColor: STATUS_COLORS[status as keyof typeof STATUS_COLORS] }}
                                        />
                                        <span className="text-sm text-gray-600 flex-1">
                                            {STATUS_LABELS[status as keyof typeof STATUS_LABELS]}
                                        </span>
                                        <span className="text-xs text-gray-400">
                                            {statusCounts[status as keyof typeof statusCounts]}
                                        </span>
                                    </label>
                                ))}
                            </div>
                        )}

                        {/* Category Filter */}
                        <div className="border-t border-gray-100 pt-3 mt-3">
                            <button
                                onClick={() => setExpandedCategories(!expandedCategories)}
                                className="w-full flex items-center justify-between py-2"
                            >
                                <span className="text-sm font-medium text-gray-700">Categories</span>
                                {expandedCategories ? (
                                    <ChevronDown className="w-4 h-4 text-gray-400" />
                                ) : (
                                    <ChevronRight className="w-4 h-4 text-gray-400" />
                                )}
                            </button>

                            {expandedCategories && (
                                <div className="space-y-2 pt-2 max-h-40 overflow-y-auto">
                                    {uniqueCategories.map(cat => (
                                        <label key={cat.code} className="flex items-center gap-3 cursor-pointer group">
                                            <input
                                                type="checkbox"
                                                checked={categoryFilters[cat.code] ?? true}
                                                onChange={(e) => setCategoryFilters(prev => ({ ...prev, [cat.code]: e.target.checked }))}
                                                className="w-4 h-4 rounded border-gray-300 text-primary-500 focus:ring-primary-500"
                                            />
                                            <span className="text-sm text-gray-600 truncate flex-1">
                                                {cat.name}
                                            </span>
                                        </label>
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* Department Filter */}
                        <div className="border-t border-gray-100 pt-3 mt-3">
                            <button
                                onClick={() => setExpandedDepartments(!expandedDepartments)}
                                className="w-full flex items-center justify-between py-2"
                            >
                                <span className="text-sm font-medium text-gray-700">Departments</span>
                                {expandedDepartments ? (
                                    <ChevronDown className="w-4 h-4 text-gray-400" />
                                ) : (
                                    <ChevronRight className="w-4 h-4 text-gray-400" />
                                )}
                            </button>

                            {expandedDepartments && (
                                <div className="space-y-2 pt-2 max-h-40 overflow-y-auto">
                                    {uniqueDepartments.map(dept => (
                                        <label key={dept} className="flex items-center gap-3 cursor-pointer group">
                                            <input
                                                type="checkbox"
                                                checked={departmentFilters[dept] ?? true}
                                                onChange={(e) => setDepartmentFilters(prev => ({ ...prev, [dept]: e.target.checked }))}
                                                className="w-4 h-4 rounded border-gray-300 text-primary-500 focus:ring-primary-500"
                                            />
                                            <span className={`text-sm text-gray-600 truncate flex-1 ${dept === 'Unassigned' ? 'italic' : ''}`}>
                                                {dept}
                                            </span>
                                        </label>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Legend */}
            <div className="absolute bottom-4 left-4 z-10 bg-white/95 backdrop-blur-md rounded-xl border border-gray-200 px-4 py-3 shadow-lg">
                <div className="flex items-center gap-5 text-xs">
                    {Object.entries(STATUS_COLORS).map(([status, color]) => (
                        <div key={status} className="flex items-center gap-2">
                            <span className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
                            <span className="text-gray-600 font-medium">
                                {STATUS_LABELS[status as keyof typeof STATUS_LABELS]}
                            </span>
                        </div>
                    ))}
                </div>
            </div>

            {/* Request Count Badge */}
            <div className="absolute top-4 left-4 z-10 bg-white/95 backdrop-blur-md rounded-xl border border-gray-200 px-4 py-2 shadow-lg">
                <p className="text-sm font-medium text-gray-700">
                    <span className="text-primary-600 font-bold">{requests.filter(r => r.lat && r.long).length}</span> requests on map
                </p>
            </div>
        </div>
    );
}

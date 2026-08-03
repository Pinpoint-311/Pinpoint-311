import { useEffect, useRef, useState } from 'react';
import { MapPin, Layers, Search, X, ChevronDown, ChevronRight, Users } from 'lucide-react';
import { ServiceRequest, ServiceDefinition, User, Department } from '../types';
import { MapLayer } from '../services/api';
import { useTranslation } from '../context/TranslationContext';
import { BANDS, bandFor, bandLabel } from './priority';
import {
    GeoJsonLayerHandle,
    MapRenderer,
    MarkerLayer,
    MarkerOptions,
    PopupHandle,
    boundsOfGeoJson,
    assetIcon,
    CONTINENTAL_US_CENTER,
    clusterStyle,
    createMap,
    extractFeatures,
    MapProviderConfig,
    hasMapCredential,
    requestIcon,
    el,
    popupRoot,
} from '../maps';

interface StaffDashboardMapProps {
    /**
     * The town's chosen provider and only that provider's credentials.
     * Built once per page with resolveMapProviderConfig(); components must not
     * assemble their own, which is how every map silently defaulted to Google.
     */
    config: MapProviderConfig;
    requests: ServiceRequest[];
    services: ServiceDefinition[];
    departments: Department[];
    users: User[];
    mapLayers: MapLayer[];
    /**
     * Show the filters that expose how the town works internally: which
     * department owns a report, who it is assigned to, its priority score, and
     * the toggles for the operational map layers.
     *
     * Off by default, so a new caller has to opt in rather than opt out. The
     * resident portal renders this same map and must not get them.
     *
     * This flag is a *layout* decision and nothing more. It is compiled into a
     * public JS bundle, so anyone can flip it in a debugger -- the reason that
     * is not a hole is that the data behind these filters is not served to an
     * unauthenticated caller at all. `assigned_to` and `assigned_department_id`
     * are absent from the public requests payload, and the departments list is
     * staff-only. Flipping the flag on the resident portal renders empty
     * checkboxes over data that is not there.
     */
    operationalFilters?: boolean;
    townshipBoundary?: object | null;
    defaultCenter?: { lat: number; lng: number };
    defaultZoom?: number;
    onRequestSelect: (requestId: string) => void;
}

// Status colors
const STATUS_COLORS = {
    open: '#ef4444',        // red
    in_progress: '#f59e0b', // amber
    closed: '#22c55e',      // green
};

export default function StaffDashboardMap({
    config,
    requests,
    services,
    departments,
    users,
    mapLayers,
    operationalFilters = false,
    townshipBoundary,
    defaultCenter = CONTINENTAL_US_CENTER,
    defaultZoom = 14,
    onRequestSelect,
}: StaffDashboardMapProps) {
    const { language } = useTranslation();
    const mapRef = useRef<HTMLDivElement>(null);
    const mapInstanceRef = useRef<MapRenderer | null>(null);
    // Request pins cluster; layer asset pucks do not. Two layers, so clustering
    // is a property of the set rather than something bolted on afterwards.
    const requestLayerRef = useRef<MarkerLayer | null>(null);
    const layerMarkerLayerRef = useRef<MarkerLayer | null>(null);
    const popupRef = useRef<PopupHandle | null>(null);
    const layerDataRef = useRef<GeoJsonLayerHandle[]>([]);

    // Filter state
    const [statusFilters, setStatusFilters] = useState({
        open: true,
        in_progress: true,
        closed: true,
    });
    const [categoryFilters, setCategoryFilters] = useState<Record<string, boolean>>({});
    const [departmentFilters, setDepartmentFilters] = useState<Record<number, boolean>>({});
    const [staffFilters, setStaffFilters] = useState<Record<string, boolean>>({});
    const [layerFilters, setLayerFilters] = useState<Record<number, boolean>>({});
    const [assignmentFilter, setAssignmentFilter] = useState<string>('');
    const [priorityFilters, setPriorityFilters] = useState<Record<string, boolean>>({ high: true, medium: true, low: true });

    // UI state
    const [isLoading, setIsLoading] = useState(true);
    const [mapReady, setMapReady] = useState(false);
    const [showFilters, setShowFilters] = useState(true);
    // Close filters on mobile after mount
    useEffect(() => {
        if (typeof window !== 'undefined' && window.innerWidth < 768) {
            setShowFilters(false);
        }
    }, []);
    const [_mapType, setMapType] = useState<string>('hybrid');
    const [expandedSections, setExpandedSections] = useState({
        status: true,
        categories: false,
        departments: false,
        staff: false,
        priority: false,
        layers: true,
        assignment: false,
    });

    // Initialize category filters when services change
    useEffect(() => {
        const newFilters: Record<string, boolean> = {};
        services.forEach(s => {
            newFilters[s.service_code] = categoryFilters[s.service_code] ?? true;
        });
        setCategoryFilters(newFilters);
    }, [services]);

    // Initialize layer filters when mapLayers change
    useEffect(() => {
        const newFilters: Record<number, boolean> = {};
        mapLayers.forEach(layer => {
            newFilters[layer.id] = layerFilters[layer.id] ?? true;
        });
        setLayerFilters(newFilters);
    }, [mapLayers]);

    // Initialize department filters when departments change
    useEffect(() => {
        const newFilters: Record<number, boolean> = {};
        departments.forEach(d => {
            newFilters[d.id] = departmentFilters[d.id] ?? true;
        });
        // Add "unassigned" option
        newFilters[0] = departmentFilters[0] ?? true;
        setDepartmentFilters(newFilters);
    }, [departments]);

    // Initialize staff filters when users change
    useEffect(() => {
        const newFilters: Record<string, boolean> = {};
        users.forEach(u => {
            newFilters[u.username] = staffFilters[u.username] ?? true;
        });
        // Add "unassigned" option
        newFilters[''] = staffFilters[''] ?? true;
        setStaffFilters(newFilters);
    }, [users]);

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
                        center: defaultCenter,
                        zoom: defaultZoom,
                        baseMapType: 'hybrid', // Satellite with labels
                        // Tilt/heading only take effect on providers rendering a
                        // vector basemap, which is what styleId selects.
                        tilt: config.styleId ? 45 : undefined,
                        heading: config.styleId ? 0 : undefined,
                        styleId: config.styleId,
                        controls: {
                            baseMapSwitcher: {
                                enabled: true,
                                position: 'top-left',
                                types: ['roadmap', 'satellite', 'hybrid'],
                            },
                            streetView: { enabled: false },
                            fullscreen: { enabled: true },
                            zoom: { enabled: true, position: 'left-bottom' },
                            rotate: { enabled: !!config.styleId },
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
                    // Shared with the resident map and the location picker.
                    cluster: { style: clusterStyle },
                });
                layerMarkerLayerRef.current = map.createMarkerLayer();

                // Track map type changes for panel styling
                map.on('basemaptypechange', ({ type }) => setMapType(type || 'hybrid'));

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
            layerDataRef.current = [];
            requestLayerRef.current = null;
            layerMarkerLayerRef.current = null;
            popupRef.current = null;
            mapInstanceRef.current?.destroy();
            mapInstanceRef.current = null;
        };
    }, [config.provider, config.apiKey, config.styleId]);

    // Render township boundary and fit map to it
    const renderBoundaryAndFit = (map: MapRenderer, boundary: object) => {
        try {
            map.addGeoJsonLayer({
                data: boundary,
                style: {
                    fillColor: '#6366f1',
                    fillOpacity: 0.08,
                    strokeColor: '#818cf8',
                    strokeWidth: 3,
                    strokeOpacity: 0.8,
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
    }, [requests, statusFilters, categoryFilters, departmentFilters, staffFilters, assignmentFilter, priorityFilters, operationalFilters, mapReady]);

    // Update GeoJSON layers when layer filters change
    useEffect(() => {
        if (!mapInstanceRef.current) return;
        updateLayers();
    }, [mapLayers, layerFilters, mapReady]);

    const updateMarkers = () => {
        const map = mapInstanceRef.current;
        const requestLayer = requestLayerRef.current;
        if (!map || !requestLayer) return;

        // Filter requests
        const filteredRequests = requests.filter(r => {
            // Status filter
            if (!statusFilters[r.status as keyof typeof statusFilters]) return false;

            // Category filter
            if (categoryFilters[r.service_code] === false) return false;

            // Department filter - only filter if departments are loaded.
            // Skipped entirely when the panel is hidden: a checkbox nobody can
            // see must never be able to remove a pin from the map.
            const requestDeptId = (r as any).assigned_department_id ?? 0;
            if (operationalFilters && Object.keys(departmentFilters).length > 0) {
                // Convert to number for comparison (filter keys are numbers)
                const deptKey = Number(requestDeptId) || 0;
                if (departmentFilters[deptKey] === false) {
                    return false;
                }
            }

            // Staff filter - only filter if users are loaded
            const requestStaff = (r as any).assigned_to ?? '';
            if (operationalFilters && Object.keys(staffFilters).length > 0) {
                if (staffFilters[requestStaff] === false) {
                    return false;
                }
            }

            // Assignment filter - search in assigned_to, service_name, or description
            if (assignmentFilter) {
                const searchLower = assignmentFilter.toLowerCase();
                const assignedTo = ((r as any).assigned_to || '').toLowerCase();
                const serviceName = r.service_name.toLowerCase();
                const description = r.description.toLowerCase();
                const address = (r.address || '').toLowerCase();

                if (!assignedTo.includes(searchLower) &&
                    !serviceName.includes(searchLower) &&
                    !description.includes(searchLower) &&
                    !address.includes(searchLower)) {
                    return false;
                }
            }

            // Must have coordinates
            if (!r.lat || !r.long) return false;

            // Priority filter
            const ai = (r as any).ai_analysis;
            const priority = (r as any).manual_priority_score ?? ai?.priority_score ?? 5;
            const priorityLevel = bandFor(priority);
            if (operationalFilters && !priorityFilters[priorityLevel]) return false;

            return true;
        });

        // Create markers
        const markers: MarkerOptions[] = filteredRequests.map(request => ({
            position: { lat: request.lat!, lng: request.long! },
            icon: requestIcon(STATUS_COLORS[request.status as keyof typeof STATUS_COLORS]),
            title: request.service_name,
            onClick: async (_e, marker) => {
                const popup = popupRef.current;
                if (popup) {
                    // Pre-translate all text content for the popup
                    const viewDetailsText = "View Full Details";
                    const statusText = request.status === 'in_progress' ? 'In Progress' : request.status === 'open' ? 'Open' : 'Closed';

                    // Translate service name and description using the translation API
                    let translatedServiceName = request.service_name;
                    let translatedDescription = request.description.substring(0, 120);

                    // For non-English, try to get translations
                    if (language !== 'en') {
                        try {
                            const response = await fetch('/api/system/translate/batch', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    texts: [request.service_name, request.description.substring(0, 120)],
                                    target_lang: language
                                })
                            });

                            if (response.ok) {
                                const data = await response.json();
                                if (data.translations && data.translations.length >= 2) {
                                    translatedServiceName = data.translations[0] || request.service_name;
                                    translatedDescription = data.translations[1] || request.description.substring(0, 120);
                                }
                            }
                        } catch (error) {
                            console.error('Translation error in popup:', error);
                        }
                    }

                    popup.setContent(popupRoot('padding: 16px; max-width: 300px;', [
                        el('div', {
                            style: 'display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;',
                            children: [
                                el('span', {
                                    style: 'font-size: 12px; color: #6366f1; font-family: monospace; font-weight: 600;',
                                    text: request.service_request_id,
                                }),
                                el('span', {
                                    style: `font-size: 11px; padding: 4px 10px; border-radius: 9999px; background: ${STATUS_COLORS[request.status as keyof typeof STATUS_COLORS]}; color: white; font-weight: 600; text-transform: uppercase;`,
                                    text: statusText,
                                }),
                            ],
                        }),
                        el('h3', {
                            style: 'margin: 0 0 8px 0; font-size: 16px; font-weight: 700; color: #1f2937;',
                            text: translatedServiceName,
                        }),
                        el('p', {
                            style: 'margin: 0 0 12px 0; font-size: 13px; color: #4b5563; line-height: 1.5;',
                            text: translatedDescription + (request.description.length > 120 ? '...' : ''),
                        }),
                        request.address ? el('p', {
                            style: 'margin: 0 0 16px 0; font-size: 12px; color: #6b7280;',
                            text: `\u{1F4CD} ${request.address}`,
                        }) : null,
                        el('button', {
                            style: 'width: 100%; padding: 10px 16px; background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); color: white; border: none; border-radius: 10px; font-size: 13px; font-weight: 600; cursor: pointer;',
                            text: `${viewDetailsText} \u2192`,
                            // A real listener, not an onclick attribute reaching
                            // for a window global -- which was both an injection
                            // surface and a leak of internals onto the page.
                            onClick: () => {
                                popupRef.current?.close();
                                onRequestSelect(request.service_request_id);
                            },
                        }),
                    ]));
                    popup.openAt(marker);
                }
            },
        }));

        // Bulk replace: the layer's clustering is rebuilt from the new set.
        requestLayer.setMarkers(markers);
    };

    const updateLayers = () => {
        const map = mapInstanceRef.current;
        const layerMarkers = layerMarkerLayerRef.current;
        if (!map || !layerMarkers) return;

        // Clear existing layer data and markers
        layerDataRef.current.forEach(d => d.remove());
        layerDataRef.current = [];
        layerMarkers.clear();
        const pointMarkers: MarkerOptions[] = [];

        // Render active layers
        mapLayers.forEach(layer => {
            if (!layerFilters[layer.id]) return;
            if (layer.visible_on_map === false) return;

            try {
                if (!layer.geojson) return;

                // Points get bespoke markers, so the vector layer hides them.
                layerDataRef.current.push(map.addGeoJsonLayer({
                    data: layer.geojson,
                    pointRendering: 'hidden',
                    style: {
                        fillColor: layer.fill_color,
                        fillOpacity: layer.fill_opacity,
                        strokeColor: layer.stroke_color,
                        strokeWidth: layer.stroke_width,
                    },
                }));

                extractFeatures(layer.geojson).forEach((feature) => {
                    if (feature.geometryType !== 'Point' || !feature.position) return;
                    const props = feature.properties as Record<string, any>;

                    pointMarkers.push({
                        position: feature.position,
                        icon: assetIcon(layer.fill_color, layer.stroke_color),
                        title: props.name || layer.name,
                        onClick: (_e, marker) => {
                            const popup = popupRef.current;
                            if (!popup) return;

                            popup.setContent(popupRoot(
                                'padding: 16px; background: #1f2937; border-radius: 12px; min-width: 180px;',
                                [
                                    el('div', {
                                        style: 'display: flex; align-items: center; gap: 10px; margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1);',
                                        children: [
                                            el('span', {
                                                style: `width: 14px; height: 14px; border-radius: 50%; background: ${layer.fill_color}; box-shadow: 0 0 8px ${layer.fill_color}80;`,
                                            }),
                                            el('h4', {
                                                style: 'margin: 0; color: #f9fafb; font-size: 15px; font-weight: 600;',
                                                text: String(props.name || layer.name),
                                            }),
                                        ],
                                    }),
                                    // Keys and values both come from an uploaded
                                    // GeoJSON, so both are set as text.
                                    ...Object.entries(props)
                                        .filter(([k]) => k !== 'name')
                                        .map(([k, v]) => el('p', {
                                            style: 'margin: 6px 0; font-size: 13px; color: #e5e7eb;',
                                            children: [
                                                el('span', { style: 'color: #9ca3af;', text: `${k}:` }),
                                                ` ${v}`,
                                            ],
                                        })),
                                    Object.keys(props).filter(k => k !== 'name').length === 0
                                        ? el('p', { style: 'color: #9ca3af; font-size: 13px; margin: 0;', text: 'No additional properties' })
                                        : null,
                                ],
                            ));
                            popup.openAt(marker);
                        },
                    });
                });

            } catch (e) {
                console.error('Error rendering layer:', layer.name, e);
            }
        });

        layerMarkers.setMarkers(pointMarkers);
    };

    const toggleSection = (section: keyof typeof expandedSections) => {
        setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));
    };

    const toggleAllCategories = (value: boolean) => {
        const newFilters: Record<string, boolean> = {};
        Object.keys(categoryFilters).forEach(key => {
            newFilters[key] = value;
        });
        setCategoryFilters(newFilters);
    };

    const toggleAllDepartments = (value: boolean) => {
        const newFilters: Record<number, boolean> = {};
        Object.keys(departmentFilters).forEach(key => {
            newFilters[Number(key)] = value;
        });
        setDepartmentFilters(newFilters);
    };

    const toggleAllStaff = (value: boolean) => {
        const newFilters: Record<string, boolean> = {};
        Object.keys(staffFilters).forEach(key => {
            newFilters[key] = value;
        });
        setStaffFilters(newFilters);
    };

    const toggleAllLayers = (value: boolean) => {
        const newFilters: Record<number, boolean> = {};
        Object.keys(layerFilters).forEach(key => {
            newFilters[Number(key)] = value;
        });
        setLayerFilters(newFilters);
    };

    if (!hasMapCredential(config)) {
        return (
            <div className="h-full flex items-center justify-center bg-white/5 rounded-xl border border-white/10">
                <div className="text-center p-8">
                    <MapPin className="w-12 h-12 mx-auto mb-4 text-white/30" />
                    <p className="text-white/60">No map provider is configured yet</p>
                    <p className="text-white/40 text-sm mt-2">Choose one in Admin Console → Service Providers → Maps</p>
                </div>
            </div>
        );
    }

    return (
        <div className="h-full flex relative rounded-xl overflow-hidden border border-white/10">
            {/* Map Container */}
            <div className="flex-1 relative">
                {isLoading && (
                    <div className="absolute inset-0 flex items-center justify-center bg-[#1a1a2e] z-10">
                        <div className="w-10 h-10 border-3 border-primary-500 border-t-transparent rounded-full animate-spin" />
                    </div>
                )}
                <div ref={mapRef} className="w-full h-full" />
            </div>

            {/* Filter Panel - Right Side (full width on mobile, fixed width on desktop) */}
            <div
                className={`absolute top-0 right-0 bottom-0 w-full sm:w-72 border-l border-white/10 transform transition-all duration-300 z-20 shadow-2xl ${showFilters ? 'translate-x-0' : 'translate-x-full'
                    }`}
                style={{
                    backgroundColor: 'rgba(15, 15, 26, 0.95)',
                    backdropFilter: 'blur(20px)',
                    WebkitBackdropFilter: 'blur(20px)',
                }}
            >
                {/* Panel Header */}
                <div className="p-4 border-b border-white/10 flex items-center justify-between bg-gradient-to-r from-primary-500/10 to-transparent">
                    <h3 className="font-bold text-white flex items-center gap-2 text-lg">
                        <Layers className="w-5 h-5 text-primary-400" />
                        {"Filters"}
                    </h3>
                    <button
                        onClick={() => setShowFilters(false)}
                        className="p-1.5 hover:bg-white/10 rounded-lg transition-colors"
                        aria-label="Close filters"
                    >
                        <X className="w-5 h-5 text-white/60" aria-hidden="true" />
                    </button>
                </div>

                <div className="overflow-y-auto h-[calc(100%-60px)]">
                    {/* Status Filters */}
                    <div className="border-b border-white/5">
                        <button
                            onClick={() => toggleSection('status')}
                            className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
                        >
                            <span className="text-sm font-semibold text-white">{"Request Status"}</span>
                            {expandedSections.status ? (
                                <ChevronDown className="w-4 h-4 text-white/50" />
                            ) : (
                                <ChevronRight className="w-4 h-4 text-white/50" />
                            )}
                        </button>
                        {expandedSections.status && (
                            <div className="px-4 pb-4 space-y-3">
                                {Object.entries(statusFilters).map(([status, enabled]) => (
                                    <label key={status} className="flex items-center gap-3 cursor-pointer group">
                                        <input
                                            type="checkbox"
                                            checked={enabled}
                                            onChange={(e) => setStatusFilters(prev => ({ ...prev, [status]: e.target.checked }))}
                                            className="w-5 h-5 rounded border-2 border-white/20 bg-transparent text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                                        />
                                        <span
                                            className="w-4 h-4 rounded-full shadow-lg"
                                            style={{ backgroundColor: STATUS_COLORS[status as keyof typeof STATUS_COLORS] }}
                                        />
                                        <span className="text-sm text-white/80 capitalize group-hover:text-white transition-colors">
                                            {status === 'in_progress' ? 'In Progress' : status === 'open' ? 'Open' : 'Closed'}
                                        </span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Category Filters */}
                    <div className="border-b border-white/5">
                        <button
                            onClick={() => toggleSection('categories')}
                            className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
                        >
                            <span className="text-sm font-semibold text-white">{"Categories"}</span>
                            {expandedSections.categories ? (
                                <ChevronDown className="w-4 h-4 text-white/50" />
                            ) : (
                                <ChevronRight className="w-4 h-4 text-white/50" />
                            )}
                        </button>
                        {expandedSections.categories && (
                            <div className="px-4 pb-4 space-y-2">
                                <div className="flex gap-3 mb-3 pb-2 border-b border-white/5">
                                    <button
                                        onClick={() => toggleAllCategories(true)}
                                        className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                    >
                                        {"Select All"}
                                    </button>
                                    <span className="text-white/20">|</span>
                                    <button
                                        onClick={() => toggleAllCategories(false)}
                                        className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                    >
                                        Clear All
                                    </button>
                                </div>
                                {services.map(service => (
                                    <label key={service.service_code} className="flex items-center gap-3 cursor-pointer group">
                                        <input
                                            type="checkbox"
                                            checked={categoryFilters[service.service_code] ?? true}
                                            onChange={(e) => setCategoryFilters(prev => ({ ...prev, [service.service_code]: e.target.checked }))}
                                            className="w-5 h-5 rounded border-2 border-white/20 bg-transparent text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                                        />
                                        <span className="text-sm text-white/70 truncate group-hover:text-white transition-colors">
                                            {service.service_name}
                                        </span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Department Filters */}
                    {operationalFilters && (
                    <div className="border-b border-white/5">
                        <button
                            onClick={() => toggleSection('departments')}
                            className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
                        >
                            <span className="text-sm font-semibold text-white">{"Departments"}</span>
                            {expandedSections.departments ? (
                                <ChevronDown className="w-4 h-4 text-white/50" />
                            ) : (
                                <ChevronRight className="w-4 h-4 text-white/50" />
                            )}
                        </button>
                        {expandedSections.departments && (
                            <div className="px-4 pb-4 space-y-2">
                                <div className="flex gap-3 mb-3 pb-2 border-b border-white/5">
                                    <button
                                        onClick={() => toggleAllDepartments(true)}
                                        className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                    >
                                        Select All
                                    </button>
                                    <span className="text-white/20">|</span>
                                    <button
                                        onClick={() => toggleAllDepartments(false)}
                                        className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                    >
                                        Clear All
                                    </button>
                                </div>
                                <label className="flex items-center gap-3 cursor-pointer group">
                                    <input
                                        type="checkbox"
                                        checked={departmentFilters[0] ?? true}
                                        onChange={(e) => setDepartmentFilters(prev => ({ ...prev, [0]: e.target.checked }))}
                                        className="w-5 h-5 rounded border-2 border-white/20 bg-transparent text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                                    />
                                    <span className="text-sm text-white/70 truncate group-hover:text-white transition-colors italic">
                                        Unassigned
                                    </span>
                                </label>
                                {departments.map(dept => (
                                    <label key={dept.id} className="flex items-center gap-3 cursor-pointer group">
                                        <input
                                            type="checkbox"
                                            checked={departmentFilters[dept.id] ?? true}
                                            onChange={(e) => setDepartmentFilters(prev => ({ ...prev, [dept.id]: e.target.checked }))}
                                            className="w-5 h-5 rounded border-2 border-white/20 bg-transparent text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                                        />
                                        <span className="text-sm text-white/70 truncate group-hover:text-white transition-colors">
                                            {dept.name}
                                        </span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>
                    )}

                    {/* Staff Filters */}
                    {operationalFilters && (
                    <div className="border-b border-white/5">
                        <button
                            onClick={() => toggleSection('staff')}
                            className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
                        >
                            <span className="text-sm font-semibold text-white">{"Assigned Staff"}</span>
                            {expandedSections.staff ? (
                                <ChevronDown className="w-4 h-4 text-white/50" />
                            ) : (
                                <ChevronRight className="w-4 h-4 text-white/50" />
                            )}
                        </button>
                        {expandedSections.staff && (
                            <div className="px-4 pb-4 space-y-2">
                                <div className="flex gap-3 mb-3 pb-2 border-b border-white/5">
                                    <button
                                        onClick={() => toggleAllStaff(true)}
                                        className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                    >
                                        {"Select All"}
                                    </button>
                                    <span className="text-white/20">|</span>
                                    <button
                                        onClick={() => toggleAllStaff(false)}
                                        className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                    >
                                        {"Clear All"}
                                    </button>
                                </div>
                                <label className="flex items-center gap-3 cursor-pointer group">
                                    <input
                                        type="checkbox"
                                        checked={staffFilters[''] ?? true}
                                        onChange={(e) => setStaffFilters(prev => ({ ...prev, ['']: e.target.checked }))}
                                        className="w-5 h-5 rounded border-2 border-white/20 bg-transparent text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                                    />
                                    <span className="text-sm text-white/70 truncate group-hover:text-white transition-colors italic">
                                        {"Unassigned"}
                                    </span>
                                </label>
                                {users.filter(u => u.role === 'staff' || u.role === 'admin').map(user => (
                                    <label key={user.username} className="flex items-center gap-3 cursor-pointer group">
                                        <input
                                            type="checkbox"
                                            checked={staffFilters[user.username] ?? true}
                                            onChange={(e) => setStaffFilters(prev => ({ ...prev, [user.username]: e.target.checked }))}
                                            className="w-5 h-5 rounded border-2 border-white/20 bg-transparent text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                                        />
                                        <span className="text-sm text-white/70 truncate group-hover:text-white transition-colors">
                                            {user.full_name || user.username}
                                        </span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>
                    )}

                    {/* Priority Level Filter */}
                    {operationalFilters && (
                    <div className="border-b border-white/5">
                        <button
                            onClick={() => toggleSection('priority')}
                            className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
                        >
                            <span className="text-sm font-semibold text-white">{"Priority Level"}</span>
                            {expandedSections.priority ? (
                                <ChevronDown className="w-4 h-4 text-white/50" />
                            ) : (
                                <ChevronRight className="w-4 h-4 text-white/50" />
                            )}
                        </button>
                        {expandedSections.priority && (
                            <div className="px-4 pb-4 space-y-2">
                                {[
                                    BANDS.map(b => ({
                                        value: b.level, label: bandLabel(b.level), color: b.hex,
                                    }))
                                ].flat().map(option => (
                                    <label key={option.value} className="flex items-center gap-3 cursor-pointer group">
                                        <input
                                            type="checkbox"
                                            checked={priorityFilters[option.value]}
                                            onChange={(e) => setPriorityFilters(prev => ({ ...prev, [option.value]: e.target.checked }))}
                                            className="w-5 h-5 rounded border-2 border-white/20 bg-transparent text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                                        />
                                        <span
                                            className="w-4 h-4 rounded-full shadow-lg"
                                            style={{ backgroundColor: option.color }}
                                        />
                                        <span className="text-sm text-white/80 group-hover:text-white transition-colors">
                                            {option.label}
                                        </span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>
                    )}

                    {/* GeoJSON Layers */}
                    {operationalFilters && mapLayers.length > 0 && (
                        <div className="border-b border-white/5">
                            <button
                                onClick={() => toggleSection('layers')}
                                className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
                            >
                                <span className="text-sm font-semibold text-white">{"Map Layers"}</span>
                                {expandedSections.layers ? (
                                    <ChevronDown className="w-4 h-4 text-white/50" />
                                ) : (
                                    <ChevronRight className="w-4 h-4 text-white/50" />
                                )}
                            </button>
                            {expandedSections.layers && (
                                <div className="px-4 pb-4 space-y-2">
                                    <div className="flex gap-3 mb-3 pb-2 border-b border-white/5">
                                        <button
                                            onClick={() => toggleAllLayers(true)}
                                            className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                        >
                                            {"Show All"}
                                        </button>
                                        <span className="text-white/20">|</span>
                                        <button
                                            onClick={() => toggleAllLayers(false)}
                                            className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                        >
                                            {"Hide All"}
                                        </button>
                                    </div>
                                    {mapLayers.map(layer => (
                                        <label key={layer.id} className="flex items-center gap-3 cursor-pointer group">
                                            <input
                                                type="checkbox"
                                                checked={layerFilters[layer.id] ?? true}
                                                onChange={(e) => setLayerFilters(prev => ({ ...prev, [layer.id]: e.target.checked }))}
                                                className="w-5 h-5 rounded border-2 border-white/20 bg-transparent text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                                            />
                                            <span
                                                className="w-4 h-4 rounded border-2"
                                                style={{
                                                    backgroundColor: layer.fill_color,
                                                    borderColor: layer.stroke_color,
                                                    opacity: 0.9
                                                }}
                                            />
                                            <span className="text-sm text-white/70 truncate group-hover:text-white transition-colors">
                                                {layer.name}
                                            </span>
                                        </label>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Assignment Filter */}
                    <div>
                        <button
                            onClick={() => toggleSection('assignment')}
                            className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
                        >
                            <span className="text-sm font-semibold text-white flex items-center gap-2">
                                <Users className="w-4 h-4 text-white/50" />
                                {"Search Requests"}
                            </span>
                            {expandedSections.assignment ? (
                                <ChevronDown className="w-4 h-4 text-white/50" />
                            ) : (
                                <ChevronRight className="w-4 h-4 text-white/50" />
                            )}
                        </button>
                        {expandedSections.assignment && (
                            <div className="px-4 pb-4">
                                <div className="relative">
                                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
                                    <input
                                        type="text"
                                        placeholder={"Staff, address, description..."}
                                        value={assignmentFilter}
                                        onChange={(e) => setAssignmentFilter(e.target.value)}
                                        className="w-full pl-10 pr-10 py-3 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/40 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500/50 transition-all"
                                    />
                                    {assignmentFilter && (
                                        <button
                                            onClick={() => setAssignmentFilter('')}
                                            className="absolute right-3 top-1/2 -translate-y-1/2 p-1 hover:bg-white/10 rounded-full transition-colors"
                                        >
                                            <X className="w-4 h-4 text-white/50" />
                                        </button>
                                    )}
                                </div>
                                <p className="text-xs text-white/40 mt-2">
                                    {"Filter by assigned staff, address, or description"}
                                </p>
                            </div>
                        )}
                    </div>
                </div>
            </div>

            {/* Filter Toggle Button */}
            {!showFilters && (
                <button
                    onClick={() => setShowFilters(true)}
                    className="absolute top-4 right-4 z-20 p-3 bg-[#1a1a2e]/95 backdrop-blur-md rounded-xl border border-white/20 hover:bg-primary-500/20 transition-all shadow-xl"
                    title="Show Filters"
                >
                    <Layers className="w-5 h-5 text-white" />
                </button>
            )}

            {/* Legend */}
            <div className="absolute bottom-4 left-4 z-10 bg-[#0f0f1a]/95 backdrop-blur-md rounded-xl border border-white/10 px-4 py-3 shadow-xl">
                <div className="flex items-center gap-5 text-xs">
                    {Object.entries(STATUS_COLORS).map(([status, color]) => (
                        <div key={status} className="flex items-center gap-2">
                            <span className="w-3 h-3 rounded-full shadow-lg" style={{ backgroundColor: color }} />
                            <span className="text-white/70 font-medium capitalize">{status.replace('_', ' ')}</span>
                        </div>
                    ))}
                    {/* The shape, not the colour. An asset layer's colour is
                        chosen by whoever uploaded it and can be any of the
                        three above, so a colour swatch here would explain
                        nothing. */}
                    {mapLayers.length > 0 && (
                        <div className="flex items-center gap-2 pl-4 border-l border-white/15">
                            <span
                                className="w-3 h-3 bg-white/70 shadow-lg"
                                style={{ transform: 'rotate(45deg)' }}
                                aria-hidden="true"
                            />
                            <span className="text-white/70 font-medium">Town asset</span>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

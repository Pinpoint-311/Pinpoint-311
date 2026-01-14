import { useEffect, useRef, useState, useCallback } from 'react';
import { MapPin, Layers, Search, X, ChevronDown, ChevronRight, Users } from 'lucide-react';
import { MarkerClusterer } from '@googlemaps/markerclusterer';
import { ServiceRequest, ServiceDefinition, User, Department } from '../types';
import { MapLayer } from '../services/api';
import { useTranslation } from '../context/TranslationContext';

declare global {
    interface Window {
        google: typeof google;
    }
}

interface StaffDashboardMapProps {
    apiKey: string;
    requests: ServiceRequest[];
    services: ServiceDefinition[];
    departments: Department[];
    users: User[];
    mapLayers: MapLayer[];
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
    apiKey,
    requests,
    services,
    departments,
    users,
    mapLayers,
    townshipBoundary,
    defaultCenter = { lat: 40.3573, lng: -74.6672 },
    defaultZoom = 14,
    onRequestSelect,
}: StaffDashboardMapProps) {
    const { t, language } = useTranslation();
    const mapRef = useRef<HTMLDivElement>(null);
    const mapInstanceRef = useRef<google.maps.Map | null>(null);
    const markersRef = useRef<google.maps.Marker[]>([]);
    const clustererRef = useRef<MarkerClusterer | null>(null);
    const infoWindowRef = useRef<google.maps.InfoWindow | null>(null);
    const layerDataRef = useRef<google.maps.Data[]>([]);
    const layerMarkersRef = useRef<google.maps.Marker[]>([]);

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
    const [priorityFilter, setPriorityFilter] = useState<'all' | 'high' | 'medium' | 'low'>('all');

    // UI state
    const [isLoading, setIsLoading] = useState(true);
    const [showFilters, setShowFilters] = useState(true);
    const [mapType, setMapType] = useState<string>('hybrid');
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

        const script = document.createElement('script');
        script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=places`;
        script.async = true;
        script.onload = () => initMap();
        script.onerror = () => setIsLoading(false);
        document.head.appendChild(script);

        return () => {
            markersRef.current.forEach(m => m.setMap(null));
            markersRef.current = [];
            if (clustererRef.current) {
                clustererRef.current.clearMarkers();
            }
        };
    }, [apiKey]);

    const initMap = useCallback(() => {
        if (!mapRef.current || !window.google) return;

        const map = new window.google.maps.Map(mapRef.current, {
            center: defaultCenter,
            zoom: defaultZoom,
            mapTypeId: 'hybrid', // Satellite with labels
            mapTypeControl: true,
            mapTypeControlOptions: {
                style: window.google.maps.MapTypeControlStyle.HORIZONTAL_BAR,
                position: window.google.maps.ControlPosition.TOP_LEFT,
                mapTypeIds: ['roadmap', 'satellite', 'hybrid'],
            },
            streetViewControl: false,
            fullscreenControl: true,
            zoomControl: true,
            zoomControlOptions: {
                position: window.google.maps.ControlPosition.LEFT_BOTTOM,
            },
        });

        mapInstanceRef.current = map;
        infoWindowRef.current = new window.google.maps.InfoWindow();

        // Track map type changes for panel styling
        map.addListener('maptypeid_changed', () => {
            setMapType(map.getMapTypeId() || 'hybrid');
        });

        // Render township boundary and fit to it
        if (townshipBoundary) {
            renderBoundaryAndFit(map, townshipBoundary);
        }

        setIsLoading(false);
    }, [defaultCenter, defaultZoom, townshipBoundary]);

    // Render township boundary and fit map to it
    const renderBoundaryAndFit = (map: google.maps.Map, boundary: any) => {
        try {
            const dataLayer = new window.google.maps.Data();
            dataLayer.addGeoJson(boundary);
            dataLayer.setStyle({
                fillColor: '#6366f1',
                fillOpacity: 0.08,
                strokeColor: '#818cf8',
                strokeWeight: 3,
                strokeOpacity: 0.8,
            });
            dataLayer.setMap(map);

            // Fit bounds to the boundary
            const bounds = new window.google.maps.LatLngBounds();
            dataLayer.forEach((feature) => {
                const geometry = feature.getGeometry();
                if (geometry) {
                    geometry.forEachLatLng((latlng) => {
                        bounds.extend(latlng);
                    });
                }
            });
            map.fitBounds(bounds);
        } catch (e) {
            console.error('Error rendering boundary:', e);
        }
    };

    // Update markers when filters or requests change
    useEffect(() => {
        if (!mapInstanceRef.current || !window.google) return;
        updateMarkers();
    }, [requests, statusFilters, categoryFilters, departmentFilters, staffFilters, assignmentFilter, priorityFilter]);

    // Update GeoJSON layers when layer filters change
    useEffect(() => {
        if (!mapInstanceRef.current || !window.google) return;
        updateLayers();
    }, [mapLayers, layerFilters]);

    const updateMarkers = () => {
        const map = mapInstanceRef.current;
        if (!map) return;

        // Clear existing markers
        markersRef.current.forEach(m => m.setMap(null));
        markersRef.current = [];
        if (clustererRef.current) {
            clustererRef.current.clearMarkers();
        }

        // Filter requests
        const filteredRequests = requests.filter(r => {
            // Status filter
            if (!statusFilters[r.status as keyof typeof statusFilters]) return false;

            // Category filter
            if (categoryFilters[r.service_code] === false) return false;

            // Department filter - only filter if departments are loaded
            const requestDeptId = (r as any).assigned_department_id ?? 0;
            if (Object.keys(departmentFilters).length > 0) {
                // Convert to number for comparison (filter keys are numbers)
                const deptKey = Number(requestDeptId) || 0;
                if (departmentFilters[deptKey] === false) {
                    return false;
                }
            }

            // Staff filter - only filter if users are loaded
            const requestStaff = (r as any).assigned_to ?? '';
            if (Object.keys(staffFilters).length > 0) {
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
            if (priorityFilter !== 'all') {
                const ai = (r as any).ai_analysis;
                const priority = (r as any).manual_priority_score ?? ai?.priority_score ?? 5;
                if (priorityFilter === 'high' && priority < 8) return false;
                if (priorityFilter === 'medium' && (priority < 5 || priority >= 8)) return false;
                if (priorityFilter === 'low' && priority >= 5) return false;
            }

            return true;
        });

        // Create markers
        const markers = filteredRequests.map(request => {
            const marker = new window.google.maps.Marker({
                position: { lat: request.lat!, lng: request.long! },
                icon: {
                    path: window.google.maps.SymbolPath.CIRCLE,
                    fillColor: STATUS_COLORS[request.status as keyof typeof STATUS_COLORS] || '#6366f1',
                    fillOpacity: 1,
                    strokeColor: '#ffffff',
                    strokeWeight: 2,
                    scale: 10,
                },
                title: request.service_name,
            });

            marker.addListener('click', async () => {
                if (infoWindowRef.current) {
                    // Pre-translate all text content for the popup
                    const viewDetailsText = t('View Full Details');
                    const statusText = t(request.status === 'in_progress' ? 'In Progress' : request.status === 'open' ? 'Open' : 'Closed');

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

                    infoWindowRef.current.setContent(`
                        <div style="padding: 16px; max-width: 300px; font-family: system-ui, -apple-system, sans-serif;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                                <span style="font-size: 12px; color: #6366f1; font-family: monospace; font-weight: 600;">${request.service_request_id}</span>
                                <span style="font-size: 11px; padding: 4px 10px; border-radius: 9999px; background: ${STATUS_COLORS[request.status as keyof typeof STATUS_COLORS]}; color: white; font-weight: 600; text-transform: uppercase;">
                                    ${statusText}
                                </span>
                            </div>
                            <h3 style="margin: 0 0 8px 0; font-size: 16px; font-weight: 700; color: #1f2937;">${translatedServiceName}</h3>
                            <p style="margin: 0 0 12px 0; font-size: 13px; color: #4b5563; line-height: 1.5;">${translatedDescription}${request.description.length > 120 ? '...' : ''}</p>
                            ${request.address ? `<p style="margin: 0 0 16px 0; font-size: 12px; color: #6b7280; display: flex; align-items: center; gap: 6px;">📍 ${request.address}</p>` : ''}
                            <button 
                                onclick="window.staffDashboardSelectRequest('${request.service_request_id}')"
                                style="width: 100%; padding: 10px 16px; background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); color: white; border: none; border-radius: 10px; font-size: 13px; font-weight: 600; cursor: pointer; transition: transform 0.1s;"
                                onmouseover="this.style.transform='scale(1.02)'"
                                onmouseout="this.style.transform='scale(1)'"
                            >
                                ${viewDetailsText} →
                            </button>
                        </div>
                    `);
                    infoWindowRef.current.open(map, marker);
                }
            });

            return marker;
        });

        // Set up global callback for info window button
        (window as any).staffDashboardSelectRequest = (requestId: string) => {
            if (infoWindowRef.current) {
                infoWindowRef.current.close();
            }
            onRequestSelect(requestId);
        };

        markersRef.current = markers;

        // Create clusterer
        clustererRef.current = new MarkerClusterer({
            map,
            markers,
            renderer: {
                render: ({ count, position }) => {
                    return new window.google.maps.Marker({
                        position,
                        icon: {
                            path: window.google.maps.SymbolPath.CIRCLE,
                            fillColor: '#4f46e5',  // Was #6366f1, darker for WCAG AA contrast
                            fillOpacity: 0.95,
                            strokeColor: '#ffffff',
                            strokeWeight: 3,
                            scale: 18 + Math.min(count, 50) / 4,
                        },
                        label: {
                            text: String(count),
                            color: '#ffffff',
                            fontSize: '12px',
                            fontWeight: '700',
                        },
                        zIndex: 1000 + count,
                    });
                },
            },
        });
    };

    const updateLayers = () => {
        const map = mapInstanceRef.current;
        if (!map) return;

        // Clear existing layer data and markers
        layerDataRef.current.forEach(d => d.setMap(null));
        layerDataRef.current = [];
        layerMarkersRef.current.forEach(m => m.setMap(null));
        layerMarkersRef.current = [];

        // Render active layers
        mapLayers.forEach(layer => {
            if (!layerFilters[layer.id]) return;
            if (layer.visible_on_map === false) return;

            try {
                const geojson = layer.geojson as any;
                if (!geojson) return;

                // Use Google Maps Data layer for proper GeoJSON support
                const dataLayer = new window.google.maps.Data();

                // Handle different GeoJSON formats
                if (geojson.type === 'FeatureCollection') {
                    dataLayer.addGeoJson(geojson);
                } else if (geojson.type === 'Feature') {
                    dataLayer.addGeoJson({ type: 'FeatureCollection', features: [geojson] });
                } else if (geojson.type === 'Point' || geojson.type === 'Polygon' || geojson.type === 'MultiPolygon' || geojson.type === 'LineString') {
                    // Raw geometry - wrap in feature
                    dataLayer.addGeoJson({
                        type: 'FeatureCollection',
                        features: [{ type: 'Feature', geometry: geojson, properties: {} }]
                    });
                }

                // Style the layer
                dataLayer.setStyle((feature) => {
                    const geomType = feature.getGeometry()?.getType();

                    if (geomType === 'Point') {
                        // For points, we'll create custom markers instead
                        return { visible: false };
                    }

                    return {
                        fillColor: layer.fill_color,
                        fillOpacity: layer.fill_opacity,
                        strokeColor: layer.stroke_color,
                        strokeWeight: layer.stroke_width,
                    };
                });

                // Handle point features with custom markers
                dataLayer.forEach((feature) => {
                    const geom = feature.getGeometry();
                    if (geom && geom.getType() === 'Point') {
                        const point = geom as google.maps.Data.Point;
                        const latLng = point.get();
                        const props = {};
                        feature.forEachProperty((value, key) => {
                            (props as any)[key] = value;
                        });

                        const marker = new window.google.maps.Marker({
                            position: latLng,
                            map,
                            icon: {
                                path: window.google.maps.SymbolPath.CIRCLE,
                                fillColor: layer.fill_color,
                                fillOpacity: 0.95,
                                strokeColor: '#ffffff',
                                strokeWeight: 2.5,
                                scale: 10,
                            },
                            title: (props as any).name || layer.name,
                        });

                        // Add click listener for point info
                        marker.addListener('click', () => {
                            if (infoWindowRef.current) {
                                const propsHtml = Object.entries(props)
                                    .filter(([k]) => k !== 'name')
                                    .map(([k, v]) => `<p style="margin: 6px 0; font-size: 13px; color: #e5e7eb;"><span style="color: #9ca3af;">${k}:</span> ${v}</p>`)
                                    .join('');

                                infoWindowRef.current.setContent(`
                                    <div style="padding: 16px; font-family: system-ui, -apple-system, sans-serif; background: #1f2937; border-radius: 12px; min-width: 180px;">
                                        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1);">
                                            <span style="width: 14px; height: 14px; border-radius: 50%; background: ${layer.fill_color}; box-shadow: 0 0 8px ${layer.fill_color}80;"></span>
                                            <h4 style="margin: 0; color: #f9fafb; font-size: 15px; font-weight: 600;">${(props as any).name || layer.name}</h4>
                                        </div>
                                        ${propsHtml || '<p style="color: #9ca3af; font-size: 13px; margin: 0;">No additional properties</p>'}
                                    </div>
                                `);
                                infoWindowRef.current.open(map, marker);
                            }
                        });

                        layerMarkersRef.current.push(marker);
                    }
                });

                dataLayer.setMap(map);
                layerDataRef.current.push(dataLayer);

            } catch (e) {
                console.error('Error rendering layer:', layer.name, e);
            }
        });
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

    if (!apiKey) {
        return (
            <div className="h-full flex items-center justify-center bg-white/5 rounded-xl border border-white/10">
                <div className="text-center p-8">
                    <MapPin className="w-12 h-12 mx-auto mb-4 text-white/30" />
                    <p className="text-white/60">Google Maps API key not configured</p>
                    <p className="text-white/40 text-sm mt-2">Configure in Admin Console → API Keys</p>
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
                        {t('Filters')}
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
                            <span className="text-sm font-semibold text-white">{t('Request Status')}</span>
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
                                            {t(status === 'in_progress' ? 'In Progress' : status === 'open' ? 'Open' : 'Closed')}
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
                            <span className="text-sm font-semibold text-white">{t('Categories')}</span>
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
                                        {t('Select All')}
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
                    <div className="border-b border-white/5">
                        <button
                            onClick={() => toggleSection('departments')}
                            className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
                        >
                            <span className="text-sm font-semibold text-white">{t('Departments')}</span>
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

                    {/* Staff Filters */}
                    <div className="border-b border-white/5">
                        <button
                            onClick={() => toggleSection('staff')}
                            className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
                        >
                            <span className="text-sm font-semibold text-white">{t('Assigned Staff')}</span>
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
                                        {t('Select All')}
                                    </button>
                                    <span className="text-white/20">|</span>
                                    <button
                                        onClick={() => toggleAllStaff(false)}
                                        className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                    >
                                        {t('Clear All')}
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
                                        {t('Unassigned')}
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

                    {/* Priority Level Filter */}
                    <div className="border-b border-white/5">
                        <button
                            onClick={() => toggleSection('priority')}
                            className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
                        >
                            <span className="text-sm font-semibold text-white">{t('Priority Level')}</span>
                            {expandedSections.priority ? (
                                <ChevronDown className="w-4 h-4 text-white/50" />
                            ) : (
                                <ChevronRight className="w-4 h-4 text-white/50" />
                            )}
                        </button>
                        {expandedSections.priority && (
                            <div className="px-4 pb-4 space-y-2">
                                {[
                                    { value: 'all', label: t('All Priorities'), color: null },
                                    { value: 'high', label: t('High (8-10)'), color: '#ef4444' },
                                    { value: 'medium', label: t('Medium (5-7)'), color: '#f59e0b' },
                                    { value: 'low', label: t('Low (1-4)'), color: '#22c55e' },
                                ].map(option => (
                                    <label key={option.value} className="flex items-center gap-3 cursor-pointer group">
                                        <input
                                            type="radio"
                                            name="priorityFilter"
                                            checked={priorityFilter === option.value}
                                            onChange={() => setPriorityFilter(option.value as typeof priorityFilter)}
                                            className="w-4 h-4 text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                                        />
                                        {option.color && (
                                            <span
                                                className="w-3 h-3 rounded-full shadow-lg"
                                                style={{ backgroundColor: option.color }}
                                            />
                                        )}
                                        <span className="text-sm text-white/70 group-hover:text-white transition-colors">
                                            {option.label}
                                        </span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* GeoJSON Layers */}
                    {mapLayers.length > 0 && (
                        <div className="border-b border-white/5">
                            <button
                                onClick={() => toggleSection('layers')}
                                className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
                            >
                                <span className="text-sm font-semibold text-white">{t('Map Layers')}</span>
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
                                            {t('Show All')}
                                        </button>
                                        <span className="text-white/20">|</span>
                                        <button
                                            onClick={() => toggleAllLayers(false)}
                                            className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                        >
                                            {t('Hide All')}
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
                                {t('Search Requests')}
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
                                        placeholder={t('Staff, address, description...')}
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
                                    {t('Filter by assigned staff, address, or description')}
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
                </div>
            </div>
        </div>
    );
}

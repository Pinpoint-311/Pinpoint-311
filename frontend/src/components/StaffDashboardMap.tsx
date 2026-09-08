import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { MapPin, Layers, List, Search, X, ChevronDown, ChevronRight, Users } from 'lucide-react';
import { ServiceRequest, ServiceDefinition, User, Department } from '../types';
import { MapLayer } from '../services/api';
import { useTranslation } from '../context/TranslationContext';
import { useAnnounce } from '../context/AccessibilityContext';
import { BANDS, bandFor, bandLabel } from './priority';
import {
    GeoJsonLayerHandle,
    MapRenderer,
    MarkerIcon,
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
    puckIcon,
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

const STATUS_LABELS: Record<string, string> = {
    open: 'Open',
    in_progress: 'In Progress',
    closed: 'Closed',
};

const statusLabel = (status: string) => STATUS_LABELS[status] ?? status.replace('_', ' ');

/**
 * Status has to be readable without colour -- WCAG 1.4.1.
 *
 * Red / amber / green pins of identical shape are the textbook failure: the
 * three hues collapse into one another for the commonest form of colour
 * blindness, and they collapse completely on a greyscale print of the map,
 * which is how a work order actually leaves the building. The asset puck
 * already solves this by being a different *shape* rather than a different
 * colour, so status does the same thing with the knobs `puckIcon` already
 * exposes, instead of inventing a second glyph vocabulary:
 *
 *   open          solid puck              "reported, untouched"
 *   in progress   puck with an inner ring "somebody is on it"
 *   closed        hollow puck             "done; a reference point now"
 *
 * All three share an outer edge and a disc size. "In progress" used to say its
 * piece by thickening the OUTER stroke to 5.5, which shrank its coloured disc
 * to 7.6px against the others' 9.2 and made it read as a white donut -- a
 * different kind of marker rather than a different status, and easily taken for
 * a town asset. The ring moved inside.
 *
 * The closed donut is deliberately the request size (22) while the asset donut
 * is 18, so the two hollow glyphs stay separable by size. They used to be named
 * side by side in a map legend; that legend has gone, because it restated the
 * filters panel next to it.
 */
function statusMarkerIcon(status: string): MarkerIcon {
    const fill = STATUS_COLORS[status as keyof typeof STATUS_COLORS] ?? '#6366f1';
    if (status === 'closed') return puckIcon({ fill, size: 22, hollow: true });
    if (status === 'in_progress') return puckIcon({ fill, size: 22, innerRing: true });
    return puckIcon({ fill, size: 22 });
}

/**
 * The filter panel's echo of those pin shapes, so the three glyphs are taught
 * exactly where they are filtered -- which is the reason the separate legend
 * could go. Decorative: every swatch sits beside the status word, which is what
 * a screen reader reads.
 */
function StatusSwatch({ status }: { status: string }) {
    const color = STATUS_COLORS[status as keyof typeof STATUS_COLORS] ?? '#6366f1';
    // Matches statusMarkerIcon: same outer edge on all three, the interior
    // carries the meaning. `inset` draws the in-progress ring inside the disc
    // rather than as a thick border, which is what the pin does.
    const style = status === 'closed'
        ? { borderColor: color, backgroundColor: 'transparent' }              // hollow
        : {
            borderColor: color,
            backgroundColor: color,
            ...(status === 'in_progress'
                ? { boxShadow: 'inset 0 0 0 2px #ffffff' }
                : {}),
        };
    return (
        <span
            className="w-4 h-4 shrink-0 rounded-full border-2 shadow-lg"
            style={style}
            aria-hidden="true"
        />
    );
}

/**
 * What a screen reader gets for a pin, and what a sighted user gets as a
 * tooltip. `title` was the bare service name, so every hover and every
 * accessible name on a busy map read "Pothole", "Pothole", "Pothole".
 */
function markerTitle(request: ServiceRequest): string {
    return [
        request.service_name,
        request.address ? `at ${request.address}` : null,
        `status ${statusLabel(request.status)}`,
        `request ${request.service_request_id}`,
    ].filter(Boolean).join(', ');
}

interface FilterSectionProps {
    /** Id of the region this header opens; the header points at it. */
    id: string;
    /** Visible header content. */
    title: ReactNode;
    /** Plain-text name, used for the group's legend. */
    label: string;
    expanded: boolean;
    onToggle: () => void;
    /** False for the request list, which is navigation rather than form controls. */
    group?: boolean;
    contentClassName?: string;
    outerClassName?: string;
    children: ReactNode;
}

/**
 * One collapsible section of the filter panel.
 *
 * All seven of these were hand-rolled: a bare <button> with a chevron, no
 * aria-expanded (so the control announced as "Categories, button" whether the
 * list under it was open or shut, and the chevron -- the only thing that said
 * which -- is a picture) and no relationship to the region it opens. WCAG
 * 1.3.1 / 4.1.2.
 *
 * The checkbox lists were bare divs, so a screen reader met fourteen unlabelled
 * checkboxes with nothing tying them to the heading above them. <fieldset> with
 * a <legend> is the HTML element for exactly that, needs no ARIA, and is
 * announced as a group on entry -- so it is used here rather than
 * role="group" + aria-labelledby. The legend is sr-only because the visible
 * header is the toggle button and repeating it would just be noise.
 *
 * One component rather than seven copies, so the next section added cannot
 * quietly ship without the attributes again.
 */
function FilterSection({
    id,
    title,
    label,
    expanded,
    onToggle,
    group = true,
    contentClassName = 'px-4 pb-4 space-y-2',
    outerClassName = 'border-b border-white/5',
    children,
}: FilterSectionProps) {
    const Chevron = expanded ? ChevronDown : ChevronRight;
    return (
        <div className={outerClassName}>
            <button
                type="button"
                onClick={onToggle}
                aria-expanded={expanded}
                aria-controls={id}
                className="w-full flex items-center justify-between p-4 hover:bg-white/5 transition-colors"
            >
                <span className="text-sm font-semibold text-white flex items-center gap-2">{title}</span>
                <Chevron className="w-4 h-4 text-white/50" aria-hidden="true" />
            </button>
            {expanded && (
                group ? (
                    <fieldset id={id} className={contentClassName}>
                        <legend className="sr-only">{label}</legend>
                        {children}
                    </fieldset>
                ) : (
                    <div id={id} className={contentClassName}>{children}</div>
                )
            )}
        </div>
    );
}

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
        requests: false,
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

    /**
     * The set that is actually plotted, computed once and shared.
     *
     * This used to live inside updateMarkers(), which meant the only place the
     * filter logic existed was a side effect that wrote to the map SDK -- so
     * the plotted set could not be rendered as text, counted, or announced.
     * Everything a non-mouse user needs from this map (the request list below,
     * the "N of M" count, the status-message announcement) reads this array,
     * which is also what guarantees the list and the pins can never disagree.
     */
    const filteredRequests = useMemo(() => requests.filter(r => {
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
    }), [requests, statusFilters, categoryFilters, departmentFilters, staffFilters, assignmentFilter, priorityFilters, operationalFilters]);

    /* Toggling a filter used to change the marker set and nothing else: no
     * number moved, no message was spoken, and a screen reader user had no way
     * to tell a filter that removed 40 pins from one that did nothing at all.
     * WCAG 4.1.3 -- routed through the app's single live region rather than a
     * second aria-live node, because two polite regions updating in the same
     * tick get neither announced.
     *
     * The first pass is skipped: the initial render is not a status *change*,
     * and requests arrive asynchronously, so announcing there would talk over
     * the page as it loads.
     *
     * Keyed on the filter *inputs*, never on `filteredRequests`. That array is
     * rebuilt whenever `requests` changes, and the dashboard above replaces the
     * whole request list on a 30-second poll -- so an effect that watched the
     * array announced "N of M requests shown on the map" twice a minute, over
     * whatever the user was actually reading, in response to nothing they did
     * (WCAG 2.2.4, 4.1.3). The counts are read inside the effect instead.
     *
     * The signature is the set of boxes the user has switched *off*, not the
     * whole map: the category, department and staff filters are seeded from
     * data that arrives asynchronously, and seeding them writes `true` for
     * every key. Watching the raw objects would therefore announce again the
     * moment the services list loaded. */
    const announce = useAnnounce();
    const filterSignature = useMemo(() => {
        const off = (m: Record<string | number, boolean>) =>
            Object.keys(m).filter(k => m[k] === false).sort().join(',');
        return [
            off(statusFilters as unknown as Record<string, boolean>),
            off(categoryFilters),
            operationalFilters ? off(departmentFilters) : '',
            operationalFilters ? off(staffFilters) : '',
            operationalFilters ? off(priorityFilters) : '',
            assignmentFilter.trim(),
        ].join('|');
    }, [statusFilters, categoryFilters, departmentFilters, staffFilters, priorityFilters, assignmentFilter, operationalFilters]);
    const lastAnnouncedFilters = useRef<string | null>(null);
    useEffect(() => {
        if (lastAnnouncedFilters.current === null) {
            lastAnnouncedFilters.current = filterSignature;
            return;
        }
        if (lastAnnouncedFilters.current === filterSignature) return;
        lastAnnouncedFilters.current = filterSignature;
        announce(`${filteredRequests.length} of ${requests.length} requests shown on the map`);
        // filteredRequests / requests are read, not tracked -- see above.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filterSignature, announce]);

    // Update markers when filters or requests change
    useEffect(() => {
        if (!mapInstanceRef.current) return;
        updateMarkers();
    }, [filteredRequests, mapReady]);

    // Update GeoJSON layers when layer filters change
    useEffect(() => {
        if (!mapInstanceRef.current) return;
        updateLayers();
    }, [mapLayers, layerFilters, mapReady]);

    const updateMarkers = () => {
        const map = mapInstanceRef.current;
        const requestLayer = requestLayerRef.current;
        if (!map || !requestLayer) return;

        // Create markers
        const markers: MarkerOptions[] = filteredRequests.map(request => ({
            position: { lat: request.lat!, lng: request.long! },
            icon: statusMarkerIcon(request.status),
            title: markerTitle(request),
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
                    <MapPin className="w-12 h-12 mx-auto mb-4 text-white/30" aria-hidden="true" />
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
            {/* The panel does not unmount when it slides shut, it is translated
                off the edge -- and an off-screen control is still in the tab
                order. A keyboard user closing the panel used to Tab into two
                dozen checkboxes they could not see, with the focus ring parked
                somewhere off the right of the map (WCAG 2.4.3 / 2.4.7).
                `inert` removes the subtree from focus and from the
                accessibility tree while keeping the slide animation. React 18
                does not know the attribute, hence the cast. */}
            <div
                id="map-filter-panel"
                {...({ inert: showFilters ? undefined : '' } as any)}
                aria-hidden={showFilters ? undefined : true}
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
                        <Layers className="w-5 h-5 text-primary-400" aria-hidden="true" />
                        {"Requests & Filters"}
                    </h3>
                    <button
                        type="button"
                        onClick={() => setShowFilters(false)}
                        className="p-1.5 hover:bg-white/10 rounded-lg transition-colors"
                        aria-label="Close requests and filters panel"
                    >
                        <X className="w-5 h-5 text-white/60" aria-hidden="true" />
                    </button>
                </div>

                <div className="overflow-y-auto h-[calc(100%-60px)]">
                    {/* The text equivalent of the pins -- WCAG 2.1.1 / 4.1.2.
                        Every request on this map was reachable only by clicking
                        a marker the provider draws onto a canvas, and the
                        popup's "View Full Details" is a DOM button synthesised
                        into an overlay that nothing puts focus into. There was
                        no keyboard path to a single request from this surface.
                        These are real buttons in the tab order calling the same
                        onRequestSelect the popup calls, over the same
                        filteredRequests the markers are built from, so the two
                        views cannot drift apart. */}
                    <FilterSection
                        id="map-request-list"
                        label="Plotted requests"
                        group={false}
                        expanded={expandedSections.requests}
                        onToggle={() => toggleSection('requests')}
                        contentClassName="px-2 pb-4"
                        title={<>
                            <List className="w-4 h-4 text-white/50" aria-hidden="true" />
                            {`Plotted Requests (${filteredRequests.length})`}
                        </>}
                    >
                        {filteredRequests.length === 0 ? (
                            <p className="px-2 text-sm text-white/50">No requests match the current filters.</p>
                        ) : (
                            <ul className="space-y-1 max-h-72 overflow-y-auto">
                                {filteredRequests.map(request => (
                                    <li key={request.service_request_id}>
                                        <button
                                            type="button"
                                            onClick={() => onRequestSelect(request.service_request_id)}
                                            className="w-full text-left px-2 py-2 rounded-lg hover:bg-white/10 focus:bg-white/10 transition-colors"
                                        >
                                            <span className="flex items-center gap-2">
                                                <StatusSwatch status={request.status} />
                                                <span className="text-sm text-white/90 truncate">{request.service_name}</span>
                                            </span>
                                            {/* The address is the only thing that
                                                says *where* on a map nobody can
                                                see; coordinates stand in when a
                                                report has no address. */}
                                            <span className="block text-xs text-white/60 truncate">
                                                {request.address || `${request.lat?.toFixed(5)}, ${request.long?.toFixed(5)}`}
                                            </span>
                                            <span className="block text-xs text-white/60">
                                                {`${statusLabel(request.status)} · ${request.service_request_id}`}
                                            </span>
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </FilterSection>

                    {/* Status Filters */}
                    <FilterSection
                        id="map-filter-status"
                        label="Request status"
                        title="Request Status"
                        expanded={expandedSections.status}
                        onToggle={() => toggleSection('status')}
                        contentClassName="px-4 pb-4 space-y-3"
                    >
                        {Object.entries(statusFilters).map(([status, enabled]) => (
                            <label key={status} className="flex items-center gap-3 cursor-pointer group">
                                <input
                                    type="checkbox"
                                    checked={enabled}
                                    onChange={(e) => setStatusFilters(prev => ({ ...prev, [status]: e.target.checked }))}
                                    className="w-5 h-5 rounded border-2 border-white/20 bg-transparent text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                                />
                                <StatusSwatch status={status} />
                                <span className="text-sm text-white/80 group-hover:text-white transition-colors">
                                    {statusLabel(status)}
                                </span>
                            </label>
                        ))}
                    </FilterSection>

                    {/* Category Filters */}
                    <FilterSection
                        id="map-filter-categories"
                        label="Categories"
                        title="Categories"
                        expanded={expandedSections.categories}
                        onToggle={() => toggleSection('categories')}
                    >
                        <div className="flex gap-3 mb-3 pb-2 border-b border-white/5">
                            <button
                                type="button"
                                onClick={() => toggleAllCategories(true)}
                                className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                            >
                                {"Select All"}
                            </button>
                            <span className="text-white/20" aria-hidden="true">|</span>
                            <button
                                type="button"
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
                    </FilterSection>

                    {/* Department Filters */}
                    {operationalFilters && (
                        <FilterSection
                            id="map-filter-departments"
                            label="Departments"
                            title="Departments"
                            expanded={expandedSections.departments}
                            onToggle={() => toggleSection('departments')}
                        >
                            <div className="flex gap-3 mb-3 pb-2 border-b border-white/5">
                                <button
                                    type="button"
                                    onClick={() => toggleAllDepartments(true)}
                                    className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                >
                                    Select All
                                </button>
                                <span className="text-white/20" aria-hidden="true">|</span>
                                <button
                                    type="button"
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
                        </FilterSection>
                    )}

                    {/* Staff Filters */}
                    {operationalFilters && (
                        <FilterSection
                            id="map-filter-staff"
                            label="Assigned staff"
                            title="Assigned Staff"
                            expanded={expandedSections.staff}
                            onToggle={() => toggleSection('staff')}
                        >
                            <div className="flex gap-3 mb-3 pb-2 border-b border-white/5">
                                <button
                                    type="button"
                                    onClick={() => toggleAllStaff(true)}
                                    className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                >
                                    {"Select All"}
                                </button>
                                <span className="text-white/20" aria-hidden="true">|</span>
                                <button
                                    type="button"
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
                        </FilterSection>
                    )}

                    {/* Priority Level Filter */}
                    {operationalFilters && (
                        <FilterSection
                            id="map-filter-priority"
                            label="Priority level"
                            title="Priority Level"
                            expanded={expandedSections.priority}
                            onToggle={() => toggleSection('priority')}
                        >
                            {BANDS.map(b => ({ value: b.level, label: bandLabel(b.level), color: b.hex })).map(option => (
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
                                        aria-hidden="true"
                                    />
                                    <span className="text-sm text-white/80 group-hover:text-white transition-colors">
                                        {option.label}
                                    </span>
                                </label>
                            ))}
                        </FilterSection>
                    )}

                    {/* GeoJSON Layers */}
                    {operationalFilters && mapLayers.length > 0 && (
                        <FilterSection
                            id="map-filter-layers"
                            label="Map layers"
                            title="Map Layers"
                            expanded={expandedSections.layers}
                            onToggle={() => toggleSection('layers')}
                        >
                            <div className="flex gap-3 mb-3 pb-2 border-b border-white/5">
                                <button
                                    type="button"
                                    onClick={() => toggleAllLayers(true)}
                                    className="text-xs text-primary-400 hover:text-primary-300 font-medium"
                                >
                                    {"Show All"}
                                </button>
                                <span className="text-white/20" aria-hidden="true">|</span>
                                <button
                                    type="button"
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
                                        aria-hidden="true"
                                    />
                                    <span className="text-sm text-white/70 truncate group-hover:text-white transition-colors">
                                        {layer.name}
                                    </span>
                                </label>
                            ))}
                        </FilterSection>
                    )}

                    {/* Assignment Filter */}
                    <FilterSection
                        id="map-filter-search"
                        label="Search requests"
                        expanded={expandedSections.assignment}
                        onToggle={() => toggleSection('assignment')}
                        outerClassName=""
                        contentClassName="px-4 pb-4"
                        title={<>
                            <Users className="w-4 h-4 text-white/50" aria-hidden="true" />
                            {"Search Requests"}
                        </>}
                    >
                        <div className="relative">
                            {/* A placeholder is not a label: it disappears the
                                moment anything is typed, and several screen
                                readers never announce it at all (WCAG 3.3.2). */}
                            <label htmlFor="map-request-search" className="sr-only">Search requests</label>
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" aria-hidden="true" />
                            <input
                                id="map-request-search"
                                type="text"
                                placeholder={"Staff, address, description..."}
                                value={assignmentFilter}
                                aria-describedby="map-request-search-help"
                                onChange={(e) => setAssignmentFilter(e.target.value)}
                                className="w-full pl-10 pr-10 py-3 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder-white/40 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500/50 transition-all"
                            />
                            {assignmentFilter && (
                                <button
                                    type="button"
                                    onClick={() => setAssignmentFilter('')}
                                    aria-label="Clear search"
                                    className="absolute right-3 top-1/2 -translate-y-1/2 p-1 hover:bg-white/10 rounded-full transition-colors"
                                >
                                    <X className="w-4 h-4 text-white/50" aria-hidden="true" />
                                </button>
                            )}
                        </div>
                        <p id="map-request-search-help" className="text-xs text-white/60 mt-2">
                            {"Filter by assigned staff, address, or description"}
                        </p>
                    </FilterSection>
                </div>
            </div>

            {/* Filter Toggle Button */}
            {!showFilters && (
                <button
                    type="button"
                    onClick={() => setShowFilters(true)}
                    aria-expanded={false}
                    aria-controls="map-filter-panel"
                    aria-label="Show requests and filters panel"
                    className="absolute top-4 right-4 z-20 p-3 bg-[#1a1a2e]/95 backdrop-blur-md rounded-xl border border-white/20 hover:bg-primary-500/20 transition-all shadow-xl"
                    title="Show requests and filters"
                >
                    <Layers className="w-5 h-5 text-white" aria-hidden="true" />
                </button>
            )}

            {/* No legend.
                It repeated the filters panel, which already shows the same
                StatusSwatch beside every status it can filter on -- the same
                component, so the colours cannot drift apart -- and lists each
                map layer with its own colour. A key that restates the control
                next to it is furniture.

                One thing did go with it and is worth knowing: the hollow ring
                that marks a town asset, as opposed to a filled request pin, is
                now unexplained anywhere. The Map Layers filter section only
                renders when `operationalFilters` is set, and it defaults to
                false. If that convention needs a key again, it is one item and
                belongs beside the layer list rather than floating over the map. */}
        </div>
    );
}

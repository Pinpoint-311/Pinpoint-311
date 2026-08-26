import React, { useState, useEffect, useMemo, useRef, useCallback, FormEvent } from 'react';
import { resolveMapProviderConfig, mapProviderReady, RawMapsConfig } from '../maps';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate, useParams } from 'react-router-dom';
import {
    RefreshCw,
    Menu,
    X,
    Search,
    AlertCircle,
    CheckCircle,
    Clock,
    FileText,
    Braces,
    EyeOff,
    TrendingUp,
    Map,
    Sparkles,
    LogOut,
    MapPin,
    Mail,
    Phone,
    User,
    BarChart3,
    MessageSquare,
    Trash2,
    Send,
    Camera,
    Link,
    Link2,
    Brain,
    LayoutDashboard,
    ChevronDown,
    ChevronLeft,
    Check,
    ExternalLink,
    AlertTriangle,
    Activity,
    History,
    Cloud,
    Shield,
    Edit3,
    Bell,
    Settings,
    Download,
    FlaskConical,
    Home,
    FlagTriangleRight,
    Lock,
    Globe,
} from 'lucide-react';
import { CommentCard, CommentEmptyState } from '../components/commentUI';
import { Button, Card, Modal, Input, Textarea, Select, StatusBadge, Badge } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { useSettings } from '../context/SettingsContext';
import { useAnnounce } from '../context/AccessibilityContext';
import { api, MapLayer, IntegrationRequestLink } from '../services/api';
import { ServiceRequest, ServiceRequestDetail, ServiceDefinition, Statistics, AdvancedStatistics, RequestComment, ClosedSubstatus, User as UserType, Department, AuditLogEntry, HeatmapData, PlatformFeedbackStatistics } from '../types';
import { XAxis, YAxis, ResponsiveContainer, AreaChart, Area, Tooltip } from 'recharts';
import PlatformFeedbackStats from '../components/PlatformFeedbackStats';
import StaffDashboardMap from '../components/StaffDashboardMap';
import RequestDetailMap from '../components/RequestDetailMap';
import SpatialBiasHeatmap from '../components/SpatialBiasHeatmap';
import { usePageNavigation } from '../hooks/usePageNavigation';
import NotificationSettings from '../components/NotificationSettings';
import ManualIntake from '../components/ManualIntake';
import ActivityFeed from '../components/ActivityFeed';
import { bellAppearance, markKeyRead, readIdsFromStorage, readKey, unreadCount } from '../components/activityBell';
import { bandFor, bandLabel, countByBand } from '../components/priority';
import PrintWorkOrder from '../components/PrintWorkOrder';

type View = 'dashboard' | 'active' | 'in_progress' | 'resolved' | 'statistics';

const VIEW_TITLES: Record<View, string> = {
    dashboard: 'Dashboard',
    active: 'Open Requests',
    in_progress: 'In Progress',
    resolved: 'Resolved',
    statistics: 'Statistics',
};

/* BCP-47 tag for the language the triage step detected — WCAG 3.1.2
 * Language of Parts.
 *
 * The original resident text was rendered inside an English document with no
 * `lang`, so a screen reader read Spanish, Polish or Vietnamese aloud with
 * English pronunciation rules: not merely accented, but frequently
 * unintelligible. The detected language is already in scope on the analysis
 * object -- it just never reached the markup.
 *
 * The detector returns human-readable English names ("Spanish"), not tags, so
 * this maps the languages the town-facing resident portal actually offers.
 * An unmapped language returns undefined rather than a guess: no `lang` at all
 * inherits the document's, which is exactly the status quo, whereas a wrong tag
 * makes the pronunciation worse and lies to a translation tool. */
const DETECTED_LANGUAGE_TAGS: Record<string, string> = {
    arabic: 'ar', bengali: 'bn', chinese: 'zh', 'simplified chinese': 'zh-Hans',
    'traditional chinese': 'zh-Hant', dutch: 'nl', english: 'en', farsi: 'fa',
    french: 'fr', german: 'de', greek: 'el', gujarati: 'gu', haitian: 'ht',
    'haitian creole': 'ht', hebrew: 'he', hindi: 'hi', hungarian: 'hu',
    italian: 'it', japanese: 'ja', korean: 'ko', mandarin: 'zh', persian: 'fa',
    polish: 'pl', portuguese: 'pt', punjabi: 'pa', romanian: 'ro', russian: 'ru',
    somali: 'so', spanish: 'es', swahili: 'sw', tagalog: 'tl', tamil: 'ta',
    telugu: 'te', thai: 'th', turkish: 'tr', ukrainian: 'uk', urdu: 'ur',
    vietnamese: 'vi', yiddish: 'yi',
};

function languageTag(detected: unknown): string | undefined {
    if (typeof detected !== 'string') return undefined;
    return DETECTED_LANGUAGE_TAGS[detected.trim().toLowerCase()];
}

export default function StaffDashboard() {
    const navigate = useNavigate();
    const { requestId: urlRequestId } = useParams<{ requestId?: string }>();
    const { user, logout } = useAuth();
    const { settings } = useSettings();
    const announce = useAnnounce();
    const contentRef = useRef<HTMLDivElement>(null);
    /* Focus bookkeeping for the list -> detail transition (WCAG 2.4.3).
     *
     * `returnFocusRef` holds the actual list button that opened the detail, so
     * closing puts focus back where the user left it instead of dumping it on
     * <body> and restarting the tab order at the top of the document. */
    const pageHeadingRef = useRef<HTMLHeadingElement>(null);
    const detailHeadingRef = useRef<HTMLHeadingElement>(null);
    const returnFocusRef = useRef<HTMLElement | null>(null);

    // Handle browser back/forward navigation
    const handleHashChange = useCallback((hash: string) => {
        // Parse hash: could be 'dashboard', 'statistics', 'active', 'active/request/SR-123', 'detail/SR-123', etc.
        const parts = hash.split("/");
        const view = parts[0] as View;
        const validViews: View[] = ['dashboard', 'active', 'in_progress', 'resolved', 'statistics'];

        /* Handle detail/{id} (from the "similar reports" jumps).
         *
         * This used to load the request and return without touching
         * `currentView`, which left two things wrong at once. The document
         * title said "Request SR-123" while the view underneath was still the
         * dashboard or statistics page (WCAG 2.4.2) -- and worse, the detail
         * panel is only rendered by the list/detail branch, so on those two
         * views the request loaded into a panel that was never on screen and
         * the jump silently did nothing. Switching to a list view when we are
         * on one of the two non-list views makes the destination real, and
         * keeps title and view telling the same story. */
        if (parts[0] === 'detail' && parts[1]) {
            setCurrentView(v => (v === 'dashboard' || v === 'statistics') ? 'active' : v);
            loadRequestDetail(parts[1]);
            return;
        }

        if (validViews.includes(view)) {
            setCurrentView(view);
            if (parts[1] === 'request' && parts[2]) {
                // Has request ID - load it
                loadRequestDetail(parts[2]);
            } else {
                // No request - clear selection
                setSelectedRequest(null);
            }
        } else if (!hash) {
            // Empty hash - go to dashboard
            setCurrentView('dashboard');
            setSelectedRequest(null);
        }
    }, []);

    // URL hashing, dynamic titles, and scroll-to-top
    const { updateHash, updateTitle, scrollToTop, focusMain } = usePageNavigation({
        baseTitle: settings?.township_name ? `Staff Portal | ${settings.township_name}` : 'Staff Portal',
        scrollContainerRef: contentRef,
        onHashChange: handleHashChange,
    });

    const [sidebarOpen, setSidebarOpen] = useState(false);
    const [currentView, setCurrentView] = useState<View>('dashboard');
    const [requests, setRequests] = useState<ServiceRequest[]>([]);
    const [allRequests, setAllRequests] = useState<ServiceRequest[]>([]); // For dashboard map
    const [selectedRequest, setSelectedRequest] = useState<ServiceRequestDetail | null>(null);
    // Which statistics sections failed to load, in words, for the banner.
    const [statsErrors, setStatsErrors] = useState<string[]>([]);
    const [statsLoading, setStatsLoading] = useState(false);
    const [isLoading, setIsLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [showIntakeModal, setShowIntakeModal] = useState(false);
    const [services, setServices] = useState<ServiceDefinition[]>([]);
    const [statistics, setStatistics] = useState<Statistics | null>(null);
    const [advancedStats, setAdvancedStats] = useState<AdvancedStatistics | null>(null);
    const [slaPerf, setSlaPerf] = useState<import('../services/api').SlaPerformance | null>(null);
    // Residents who were redirected instead of filing. Not service requests --
    // nobody worked them and they appear in no queue or feed -- but the count is
    // how a town learns one road is turning away twenty people a month.
    const [redirects, setRedirects] = useState<Awaited<ReturnType<typeof api.getRedirectedStatistics>> | null>(null);
    // Aggregate answers to the optional platform-feedback question. Null when
    // the module is off, in which case the endpoint 404s and the panel below
    // renders nothing -- off is off, not hidden.
    const [platformFeedback, setPlatformFeedback] = useState<PlatformFeedbackStatistics | null>(null);
    const [heatmapData, setHeatmapData] = useState<HeatmapData | null>(null);

    // Dashboard-specific state
    const [departments, setDepartments] = useState<Department[]>([]);
    const [users, setUsers] = useState<UserType[]>([]);
    const [mapLayers, setMapLayers] = useState<MapLayer[]>([]);
    const [mapsConfig, setMapsConfig] = useState<(RawMapsConfig & { township_boundary: object | null; default_center?: { lat: number; lng: number } }) | null>(null);
    // One config for every map on this page, from the town's chosen provider.
    const mapConfig = useMemo(() => resolveMapProviderConfig(mapsConfig), [mapsConfig]);

    // Intake form state
    const [intakeData, setIntakeData] = useState({
        service_code: '',
        description: '',
        address: '',
        first_name: '',
        last_name: '',
        phone: '',
        source: 'phone',
    });

    // Comments state
    const [comments, setComments] = useState<RequestComment[]>([]);
    const [auditLog, setAuditLog] = useState<AuditLogEntry[]>([]);
    const [newComment, setNewComment] = useState('');
    const [commentVisibility, setCommentVisibility] = useState<'internal' | 'external'>('internal');
    const [isSubmittingComment, setIsSubmittingComment] = useState(false);

    // Delete modal state
    const [showDeleteModal, setShowDeleteModal] = useState(false);
    const [deleteJustification, setDeleteJustification] = useState('');
    const [isDeleting, setIsDeleting] = useState(false);

    // Closed substatus state
    const [showClosedModal, setShowClosedModal] = useState(false);
    const [woRefresh, setWoRefresh] = useState<{ busy: boolean; msg: string | null }>({ busy: false, msg: null });
    /* Which external records this request is linked to.
     *
     * GET /api/integrations/requests/{id}/links existed with no client function
     * and no caller, so staff could see *that* a request had gone to Accela --
     * the refresh button's tooltip names the platform -- but never which record
     * it became. Reconciling one report against the county's system meant asking
     * whoever had the county's login. */
    const [externalRecords, setExternalRecords] = useState<IntegrationRequestLink[]>([]);
    const [closedSubstatus, setClosedSubstatus] = useState<ClosedSubstatus>('resolved');
    const [completionMessage, setCompletionMessage] = useState('');
    const [completionPhotoUrl, setCompletionPhotoUrl] = useState('');

    // Lightbox modal state
    const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

    // Assignment editing state
    const [editAssignment, setEditAssignment] = useState<{ departmentId: number | null; assignedTo: string | null } | null>(null);
    const [isSavingAssignment, setIsSavingAssignment] = useState(false);

    // Filter states
    const [filterDepartment, setFilterDepartment] = useState<number | null>(null);
    const [filterService, setFilterService] = useState<string | null>(null);
    // Default to the signed-in user's own assigned requests ("My Requests").
    const [filterAssignment, setFilterAssignment] = useState<'all' | 'me' | 'department'>('me');
    const [showFilters, setShowFilters] = useState(false);
    const [sortOrder, setSortOrder] = useState<'newest' | 'oldest' | 'priority_high' | 'priority_low' | 'alpha'>('newest');

    // Asset-related requests (for matched assets)
    type AssetRelatedRequest = { service_request_id: string; service_name: string; status: string; requested_datetime: string; address: string; description: string; };
    const [assetRelatedRequests, setAssetRelatedRequests] = useState<AssetRelatedRequest[]>([]);
    const [isLoadingAssetHistory, setIsLoadingAssetHistory] = useState(false);

    // Share link state
    const [showShareMenu, setShowShareMenu] = useState(false);
    const [copiedLink, setCopiedLink] = useState<'staff' | 'resident' | null>(null);

    // Detail panel ref for scroll-to-top on request selection
    const detailPanelRef = useRef<HTMLDivElement>(null);

    // Priority editing state
    const [showPriorityEditor, setShowPriorityEditor] = useState(false);
    const [pendingPriority, setPendingPriority] = useState<number | null>(null);
    const [isUpdatingPriority, setIsUpdatingPriority] = useState(false);

    // AI section collapse state (collapsed by default to save space)
    const [isAIExpanded, setIsAIExpanded] = useState(false);

    // Map priority filter state ('all', 'high', 'medium', 'low')
    const [mapPriorityFilter, setMapPriorityFilter] = useState<'all' | 'high' | 'medium' | 'low'>('all');

    // Notification settings modal state
    const [showNotificationSettings, setShowNotificationSettings] = useState(false);
    const [showManualIntake, setShowManualIntake] = useState(false);

    // Activity feed state
    const [showActivityFeed, setShowActivityFeed] = useState(false);
    const [activityTick, setActivityTick] = useState(0);

    // Export dropdown open state (keyboard-operable)
    const [exportOpen, setExportOpen] = useState(false);
    const exportWrapRef = useRef<HTMLDivElement>(null);
    const exportBtnRef = useRef<HTMLButtonElement>(null);
    const shareWrapRef = useRef<HTMLDivElement>(null);
    const shareBtnRef = useRef<HTMLButtonElement>(null);

    // AI Analytics Chat state
    const [chatOpen, setChatOpen] = useState(false);
    const [chatMessages, setChatMessages] = useState<{ role: 'user' | 'assistant'; content: string }[]>([]);
    const [chatInput, setChatInput] = useState('');
    const [chatLoading, setChatLoading] = useState(false);
    const chatEndRef = useRef<HTMLDivElement>(null);


    // Scroll chat to bottom when new messages arrive
    useEffect(() => {
        if (chatEndRef.current) {
            chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [chatMessages, chatLoading]);

    const sendChatMessage = async (e?: FormEvent) => {
        e?.preventDefault();
        const msg = chatInput.trim();
        if (!msg || chatLoading) return;
        const newMessages = [...chatMessages, { role: 'user' as const, content: msg }];
        setChatMessages(newMessages);
        setChatInput('');
        setChatLoading(true);
        try {
            const result = await api.analyticsChat(msg, newMessages.slice(0, -1));
            setChatMessages(prev => [...prev, { role: 'assistant', content: result.response }]);
        } catch (err: any) {
            setChatMessages(prev => [...prev, { role: 'assistant', content: `⚠️ Error: ${err.message || 'Failed to get AI response'}` }]);
        } finally {
            setChatLoading(false);
        }
    };

    /* Dismiss the two disclosure panels on an outside interaction.
     *
     * Both used to stay open until their own trigger was pressed again, so
     * clicking away left a panel of five focusable controls hovering over the
     * page — reachable by Tab, invisible to anyone who had mentally moved on.
     * Bound to pointerdown rather than click so it fires before the panel
     * unmounts under a click that started outside it; `focusin` covers the
     * keyboard case, where Tab can carry focus out of the panel without any
     * pointer event at all. */
    useEffect(() => {
        if (!exportOpen && !showShareMenu) return;
        const dismiss = (event: Event) => {
            const target = event.target as Node | null;
            if (exportOpen && !exportWrapRef.current?.contains(target)) setExportOpen(false);
            if (showShareMenu && !shareWrapRef.current?.contains(target)) setShowShareMenu(false);
        };
        document.addEventListener('pointerdown', dismiss);
        document.addEventListener('focusin', dismiss);
        return () => {
            document.removeEventListener('pointerdown', dismiss);
            document.removeEventListener('focusin', dismiss);
        };
    }, [exportOpen, showShareMenu]);

    // Get current user's department IDs
    const userDepartmentIds = useMemo(() => {
        return user?.departments?.map(d => d.id) || [];
    }, [user]);

    // Recomputed when the polled request list changes, which is the only thing
    // that can make it go up. `activityTick` lets the feed tell us it has
    // marked things read, without this reaching into localStorage on every
    // render the way the inline version did.
    const unreadActivity = useMemo(() => unreadCount({
        requests: allRequests,
        readIds: readIdsFromStorage(localStorage.getItem('activityFeedRead')),
        departmentIds: userDepartmentIds,
        username: user?.username,
        now: Date.now(),
    }), [allRequests, userDepartmentIds, activityTick, showActivityFeed]);

    // Filtered and sorted requests based on current view and filters
    const filteredSortedRequests = useMemo(() => {
        // First, filter by status based on current view
        let filtered = allRequests.filter(r => {
            if (currentView === 'active') return r.status === 'open';
            if (currentView === 'in_progress') return r.status === 'in_progress';
            if (currentView === 'resolved') return r.status === 'closed';
            return true; // dashboard shows all
        });

        // Apply search filter
        if (searchQuery.trim()) {
            const query = searchQuery.toLowerCase();
            filtered = filtered.filter(r =>
                r.service_request_id.toLowerCase().includes(query) ||
                r.description?.toLowerCase().includes(query) ||
                r.address?.toLowerCase().includes(query) ||
                r.service_name?.toLowerCase().includes(query)
            );
        }

        // Apply department filter
        if (filterDepartment !== null) {
            filtered = filtered.filter(r => r.assigned_department_id === filterDepartment);
        }

        // Apply service filter
        if (filterService !== null) {
            filtered = filtered.filter(r => r.service_code === filterService);
        }

        // Apply assignment filter
        if (filterAssignment === 'me' && user) {
            filtered = filtered.filter(r => r.assigned_to === user.username);
        } else if (filterAssignment === 'department') {
            if (userDepartmentIds.length > 0) {
                // Show ALL requests assigned to my department
                filtered = filtered.filter(r =>
                    r.assigned_department_id &&
                    userDepartmentIds.includes(r.assigned_department_id)
                );
            }
            // If no departments configured, show all requests (no additional filter)
        }

        // Sort based on selected sort order
        filtered.sort((a, b) => {
            const getPriority = (r: ServiceRequest) =>
                r.manual_priority_score ?? ((r.ai_analysis as any)?.priority_score) ?? 5;

            switch (sortOrder) {
                case 'oldest':
                    return new Date(a.requested_datetime).getTime() - new Date(b.requested_datetime).getTime();
                case 'priority_high':
                    return getPriority(b) - getPriority(a);
                case 'priority_low':
                    return getPriority(a) - getPriority(b);
                case 'alpha':
                    return (a.service_name || '').localeCompare(b.service_name || '');
                case 'newest':
                default:
                    return new Date(b.requested_datetime).getTime() - new Date(a.requested_datetime).getTime();
            }
        });

        return filtered;
    }, [allRequests, currentView, searchQuery, filterDepartment, filterService, filterAssignment, user, userDepartmentIds, sortOrder]);

    // Quick stats for the current view
    const quickStats = useMemo(() => {
        const viewRequests = allRequests.filter(r => {
            if (currentView === 'active') return r.status === 'open';
            if (currentView === 'in_progress') return r.status === 'in_progress';
            if (currentView === 'resolved') return r.status === 'closed';
            return true;
        });

        const assignedToMe = viewRequests.filter(r => user && r.assigned_to === user.username).length;
        const total = viewRequests.length;
        // Count requests in my department(s) — if no depts configured, count all
        const inMyDepartment = userDepartmentIds.length > 0
            ? viewRequests.filter(r =>
                r.assigned_department_id && userDepartmentIds.includes(r.assigned_department_id)
            ).length
            : total;

        return { assignedToMe, inMyDepartment, total };
    }, [allRequests, currentView, user, userDepartmentIds]);

    // Helper to get effective priority score (checks multiple sources)
    const getEffectivePriority = (r: ServiceRequest): number => {
        // Priority precedence: manual > ai_analysis.priority_score > default 5
        if (r.manual_priority_score != null) return r.manual_priority_score;
        // Check nested ai_analysis for priority_score (AI suggestion)
        const aiAnalysis = r.ai_analysis as any;
        if (aiAnalysis?.priority_score != null) return aiAnalysis.priority_score;
        return 5; // Default
    };

    // Filter requests by priority for the map and list
    const mapFilteredRequests = useMemo(() => {
        if (mapPriorityFilter === 'all') return allRequests;
        return allRequests.filter(r => {
            const priority = getEffectivePriority(r);
            if (mapPriorityFilter === 'high') return bandFor(priority) === 'high';
            if (mapPriorityFilter === 'medium') return bandFor(priority) === 'medium';
            if (mapPriorityFilter === 'low') return priority < 5;
            return true;
        });
    }, [allRequests, mapPriorityFilter]);

    // Clear all filters
    const clearFilters = () => {
        setSearchQuery('');
        setFilterDepartment(null);
        setFilterService(null);
        setFilterAssignment("all");
        setMapPriorityFilter('all');
    };

    const hasActiveFilters = searchQuery.trim() || filterDepartment !== null || filterService !== null || filterAssignment !== 'all' || mapPriorityFilter !== 'all';

    /* Say how many incidents survived the filters — WCAG 4.1.3 Status Messages.
     *
     * Filtering this list was completely silent, and silent in a way nobody
     * could recover from: the panel carried no "N incidents" text anywhere, so
     * there was nothing for a screen reader to go and read even on request.
     * Typing in the search box, switching scope or picking a category rewrote
     * the list under a user who had no way to learn whether it now held forty
     * rows or none, and the "No incidents found" placeholder sits below the
     * fold on a phone.
     *
     * Keyed on the filter inputs rather than on the result length on purpose:
     * the 30-second poll replaces `allRequests` wholesale, and announcing every
     * length change would interrupt whatever the user was reading twice a
     * minute over a change they did not make. Skipped on first render — the
     * initial count is not news. */
    const filterSignature = `${searchQuery.trim()}|${filterDepartment}|${filterService}|${filterAssignment}|${mapPriorityFilter}|${currentView}`;
    const lastAnnouncedFilters = useRef<string | null>(null);
    useEffect(() => {
        if (isLoading) return;
        if (lastAnnouncedFilters.current === null) {
            lastAnnouncedFilters.current = filterSignature;
            return;
        }
        if (lastAnnouncedFilters.current === filterSignature) return;
        lastAnnouncedFilters.current = filterSignature;
        const n = filteredSortedRequests.length;
        announce(n === 1 ? '1 incident matches the current filters' : `${n} incidents match the current filters`);
        // filteredSortedRequests is read, not tracked — see above.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filterSignature, isLoading, announce]);

    useEffect(() => {
        // Initial load - only fetch once
        loadInitialData();
    }, []);

    // Auto-refresh requests every 30 seconds for live updates
    useEffect(() => {
        const refreshRequests = async () => {
            try {
                const freshRequests = await api.getRequests();
                setAllRequests(freshRequests);
                // Re-apply current filter by updating requests state
                // The filtered list will update via the existing useMemo
            } catch (err) {
                console.error('Auto-refresh failed:', err);
            }
        };

        // Polling interval
        const pollInterval = setInterval(refreshRequests, 30000); // 30 seconds

        // Also refresh when tab becomes visible
        const handleVisibilityChange = () => {
            if (document.visibilityState === 'visible') {
                refreshRequests();
            }
        };
        document.addEventListener('visibilitychange', handleVisibilityChange);

        return () => {
            clearInterval(pollInterval);
            document.removeEventListener('visibilitychange', handleVisibilityChange);
        };
    }, []);

    // Separate effect for statistics (only loads when needed)
    useEffect(() => {
        if (currentView === 'statistics' && !statistics) {
            loadStatistics();
        }
    }, [currentView]);

    // Platform feedback loads on its own rather than inside loadStatistics(),
    // for two reasons. It is gated on a module flag that arrives with
    // `settings`, which can land after the statistics fetch has already run --
    // so it needs the flag in its dependency list. And a town that never
    // enabled the module must not request it at all: the endpoint 404s by
    // design, and folding that into loadStatistics() would put "Platform
    // feedback: Not found" in the error banner of every town that left the
    // module off.
    useEffect(() => {
        if (currentView !== 'statistics') return;
        if (!settings?.modules?.platform_feedback) return;
        if (platformFeedback) return;
        let cancelled = false;
        api.getPlatformFeedbackStatistics()
            .then((data) => { if (!cancelled) setPlatformFeedback(data); })
            .catch((err) => {
                if (!cancelled) {
                    setStatsErrors((prev) => [
                        ...prev,
                        `Platform feedback: ${err instanceof Error ? err.message : 'request failed'}`,
                    ]);
                }
            });
        return () => { cancelled = true; };
    }, [currentView, settings?.modules?.platform_feedback]);

    // Refresh the open request, not just the list.
    //
    // The 30s poll above replaces `allRequests`, which is why the list and
    // everything derived from it stays current. `selectedRequest` is fetched
    // once, on click, and never again -- so a report opened the moment it
    // arrives keeps whatever its AI analysis was at that instant. The worker
    // finishes the triage a few seconds later, writes it to the row, and the
    // open panel goes on showing the state it was born with until the page is
    // reloaded by hand.
    //
    // Two rates. The slow one keeps a long-open panel honest. The fast one
    // runs only while the analysis is genuinely still coming and stops as soon
    // as it lands, fails, or the minute is up -- the point is that the panel
    // fills in by itself, not that it polls forever.
    const selectedId = selectedRequest?.service_request_id;
    const analysisPending = !!selectedRequest && (() => {
        const ai = selectedRequest.ai_analysis as Record<string, unknown> | null;
        if (ai && (ai._error || ai.priority_score != null || ai.qualitative_analysis)) return false;
        if (selectedRequest.ai_summary) return false;
        // Only for a report new enough that triage could still be running.
        const submitted = selectedRequest.requested_datetime
            ? Date.parse(selectedRequest.requested_datetime as unknown as string)
            : NaN;
        return Number.isFinite(submitted) && Date.now() - submitted < 10 * 60 * 1000;
    })();

    useEffect(() => {
        if (!selectedId) return;
        const period = analysisPending ? 5000 : 30000;
        const tick = setInterval(async () => {
            try {
                const fresh = await api.getRequestDetail(selectedId);
                // Guard against a slow response landing after the user has
                // moved on, which would reopen the previous request's data.
                setSelectedRequest(prev =>
                    prev && prev.service_request_id === fresh.service_request_id ? fresh : prev);
            } catch {
                // A failed refresh leaves what is on screen alone. The next
                // tick tries again.
            }
        }, period);
        return () => clearInterval(tick);
    }, [selectedId, analysisPending]);

    // Auto-load request if URL contains requestId
    useEffect(() => {
        if (urlRequestId) {
            loadRequestDetail(urlRequestId);
        }
    }, [urlRequestId]);

    // Update URL hash and title when view changes
    useEffect(() => {
        updateHash(currentView);
        updateTitle(VIEW_TITLES[currentView]);
        scrollToTop('instant');
        /* Nothing here moved focus, so a nav click swapped out the whole of
         * #main-content while focus stayed on the sidebar button. See
         * usePageNavigation.focusMain for the full failure mode. Skipped when a
         * request is open, because the detail-panel effect below owns focus in
         * that case and the two would fight over it. */
        if (!selectedRequest) focusMain();
        // Intentionally not depending on selectedRequest: this effect is about
        // view changes. Reading the current value is enough to defer to the
        // detail panel when one is already open.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [currentView, updateHash, updateTitle, scrollToTop, focusMain]);

    /* Title, hash and focus for the open request — WCAG 2.4.2 and 2.4.3.
     *
     * The whole body of this effect used to sit behind `if (selectedRequest)`,
     * with no else. Closing a request therefore left the tab reading
     * "Request SR-123 | Staff Portal" while the screen showed the plain list,
     * and left the hash pointing at a request that was no longer open — so
     * reload or Back reopened something the user had deliberately dismissed.
     *
     * Focus moves to the detail heading on open and returns to the originating
     * list row on close. Without that, selecting a request scrolled the panel
     * but left focus on the list button: a screen reader user heard nothing at
     * all, and below 1024px, where the panel is a `fixed inset-0` overlay, the
     * next Tab walked the list *behind* the overlay with no visible focus ring
     * anywhere on screen. */
    useEffect(() => {
        if (selectedRequest) {
            updateHash(`${currentView}/request/${selectedRequest.service_request_id}`);
            updateTitle(`Request ${selectedRequest.service_request_id}`);
            // Scroll detail panel to top when a new request is selected
            if (detailPanelRef.current) {
                detailPanelRef.current.scrollTo({ top: 0, behavior: 'instant' });
            }
            // Deferred a frame so the heading exists in the committed DOM.
            const frame = requestAnimationFrame(() => {
                detailHeadingRef.current?.focus({ preventScroll: true });
            });
            return () => cancelAnimationFrame(frame);
        }

        updateHash(currentView);
        updateTitle(VIEW_TITLES[currentView]);
        // Only reclaim focus if it is still sitting inside the panel that just
        // went away; if the user has already tabbed elsewhere, leave them be.
        const restoreTo = returnFocusRef.current;
        returnFocusRef.current = null;
        if (restoreTo?.isConnected && (document.activeElement === document.body || document.activeElement === null)) {
            restoreTo.focus({ preventScroll: true });
        }
    }, [selectedRequest, currentView, updateHash, updateTitle]);

    /* Below the `lg` breakpoint the detail panel is `fixed inset-0 z-50` — a
     * full-screen overlay laid over the list, which stays in the DOM behind it,
     * fully tabbable and not hidden from assistive tech. So the very first Tab
     * after opening a request left the visible overlay and walked an
     * off-screen list: no focus ring anywhere on screen, and a screen reader
     * reading rows the user could not see. Tracking the breakpoint in state
     * (rather than reading innerWidth at render, which never re-runs on
     * rotate or resize) lets the list be made inert for exactly as long as the
     * overlay is covering it.
     */
    const [isNarrowViewport, setIsNarrowViewport] = useState(
        () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'
            ? window.matchMedia('(max-width: 1023px)').matches
            : false
    );
    useEffect(() => {
        if (typeof window.matchMedia !== 'function') return;
        const mq = window.matchMedia('(max-width: 1023px)');
        const onChange = (e: MediaQueryListEvent) => setIsNarrowViewport(e.matches);
        setIsNarrowViewport(mq.matches);
        mq.addEventListener('change', onChange);
        return () => mq.removeEventListener('change', onChange);
    }, []);
    const listBehindOverlay = !!selectedRequest && isNarrowViewport;

    // Lock body scroll when mobile overlay is open to prevent scroll bleed-through
    useEffect(() => {
        if (selectedRequest && window.innerWidth < 1024) {
            document.body.style.overflow = 'hidden';
            document.body.style.touchAction = 'none';
        } else {
            document.body.style.overflow = '';
            document.body.style.touchAction = '';
        }
        return () => {
            document.body.style.overflow = '';
            document.body.style.touchAction = '';
        };
    }, [selectedRequest]);

    // Load asset-related requests when selected request has a matched_asset
    useEffect(() => {
        const loadAssetHistory = async () => {
            const matchedAsset = (selectedRequest as any)?.matched_asset;
            if (matchedAsset?.asset_id) {
                setIsLoadingAssetHistory(true);
                try {
                    const related = await api.getAssetRelatedRequests(
                        matchedAsset.asset_id,
                        selectedRequest?.service_request_id
                    );
                    setAssetRelatedRequests(related);
                } catch (err) {
                    console.error('Failed to load asset history:', err);
                    setAssetRelatedRequests([]);
                } finally {
                    setIsLoadingAssetHistory(false);
                }
            } else {
                setAssetRelatedRequests([]);
            }
        };
        loadAssetHistory();
    }, [selectedRequest]);

    const loadInitialData = async () => {
        setIsLoading(true);
        try {
            const [allRequestsData, servicesData, depts, usersData, layers, config] = await Promise.all([
                api.getRequests(), // Fetch ALL requests once
                api.getServices(),
                api.getDepartments(),
                api.getStaffMembers(), // Staff-accessible endpoint
                api.getMapLayers(),
                api.getMapsConfig(),
            ]);
            setAllRequests(allRequestsData);
            setRequests(allRequestsData); // Initial set
            setServices(servicesData);
            setDepartments(depts);
            setUsers(usersData);
            setMapLayers(layers);
            setMapsConfig(config);
        } catch (err) {
            console.error('Failed to load data:', err);
        } finally {
            setIsLoading(false);
        }
    };

    /**
     * Five independent calls, five independent failures.
     *
     * These used to share one Promise.all in which the first two had no
     * .catch(). Promise.all rejects on the first rejection, so a single failing
     * endpoint meant none of the five setState calls ran and the entire
     * statistics page rendered blank -- including the four sections whose data
     * had arrived perfectly. The only trace was a console.error nobody has open.
     *
     * Now each one settles on its own and a failure is reported on screen,
     * naming the section, so a page that is 80% working looks 80% working and
     * says what the missing fifth was.
     */
    const loadStatistics = async () => {
        setStatsLoading(true);
        const failures: string[] = [];

        const load = async <T,>(label: string, call: () => Promise<T>): Promise<T | null> => {
            try {
                return await call();
            } catch (err) {
                failures.push(`${label}: ${err instanceof Error ? err.message : 'request failed'}`);
                return null;
            }
        };

        const [statsData, advancedData, heatmap, sla, redirected] = await Promise.all([
            load('Summary counts', () => api.getStatistics()),
            load('Trends and hotspots', () => api.getAdvancedStatistics()),
            load('Heatmap', () => api.getHeatmapData()),
            load('SLA performance', () => api.getSlaPerformance(90)),
            load('Redirected reports', () => api.getRedirectedStatistics(30)),
        ]);

        if (statsData) setStatistics(statsData);
        if (advancedData) setAdvancedStats(advancedData);
        if (heatmap) setHeatmapData(heatmap);
        setSlaPerf(sla);
        setRedirects(redirected);
        setStatsErrors(failures);
        setStatsLoading(false);
    };

    const loadRequestDetail = async (requestId: string) => {
        // Opening a request's detail view is how a staff user reads it --
        // whether that's a mouse click on a card, Enter/Space on one (both
        // fire the same button onClick), a hash change from browser
        // back/forward, or a "similar reports" jump. Every path lands here,
        // so this is the one place to clear that request's unread bell
        // notification. `markKeyRead` already no-ops (no localStorage write,
        // no re-render) when there was nothing unread to clear.
        if (markKeyRead(readKey({ service_request_id: requestId }))) {
            setActivityTick(t => t + 1);
        }
        try {
            const detail = await api.getRequestDetail(requestId);
            setSelectedRequest(detail);
            // Load comments and audit log for this request
            loadComments(detail.id);
            loadAuditLog(requestId);
            setExternalRecords([]);
            if ((detail.external_links?.length ?? 0) > 0) {
                api.getRequestIntegrationLinks(requestId)
                    .then(setExternalRecords)
                    // Not knowing the external ids is not a reason to fail the
                    // whole detail view.
                    .catch(() => setExternalRecords([]));
            }
        } catch (err) {
            console.error('Failed to load request detail:', err);
        }
    };

    const handleRefreshWorkOrder = async () => {
        if (!selectedRequest) return;
        setWoRefresh({ busy: true, msg: null });
        try {
            const res = await api.refreshRequestWorkOrder(selectedRequest.service_request_id);
            setWoRefresh({ busy: false, msg: res.detail });
            announce(res.detail, res.ok ? 'polite' : 'assertive');
            // Synced work-order updates land as status/assignment/timeline notes;
            // reload the detail + comments shortly so they show up.
            if (res.ok) {
                setTimeout(() => {
                    loadRequestDetail(selectedRequest.service_request_id);
                    if (selectedRequest.id) loadComments(selectedRequest.id);
                }, 2500);
            }
        } catch (err: any) {
            const msg = err?.message || 'Could not refresh the work order.';
            setWoRefresh({ busy: false, msg });
            announce(msg, 'assertive');
        }
        setTimeout(() => setWoRefresh(s => ({ ...s, msg: null })), 6000);
    };

    const handleStatusChange = async (status: string) => {
        if (!selectedRequest) return;

        // If closing, show modal to select substatus
        if (status === 'closed') {
            setShowClosedModal(true);
            return;
        }

        try {
            const updated = await api.updateRequest(selectedRequest.service_request_id, { status });
            setSelectedRequest(updated);
            // Optimistic update: update list immediately without full reload
            setAllRequests(prev => prev.map(r => r.id === updated.id ? updated : r));
            setRequests(prev => prev.map(r => r.id === updated.id ? updated : r));
            loadAuditLog(selectedRequest.service_request_id);
            /* Every write on this surface used to complete in total silence:
             * the only feedback was a button restyling itself. Non-visual users
             * had no way to tell a saved change from a failed one. */
            announce(`Status set to ${status === 'in_progress' ? 'In Progress' : status === 'open' ? 'Open' : status}.`);
        } catch (err) {
            console.error('Failed to update status:', err);
            announce('Could not update the status. Please try again.', 'assertive');
        }
    };

    const handleCloseWithSubstatus = async () => {
        if (!selectedRequest) return;
        try {
            const updated = await api.updateRequest(selectedRequest.service_request_id, {
                status: 'closed',
                closed_substatus: closedSubstatus,
                completion_message: completionMessage || undefined,
                completion_photo_url: closedSubstatus === 'resolved' ? completionPhotoUrl || undefined : undefined,
            });
            setSelectedRequest(updated);
            // Optimistic update: update list immediately without full reload
            setAllRequests(prev => prev.map(r => r.id === updated.id ? updated : r));
            setRequests(prev => prev.map(r => r.id === updated.id ? updated : r));
            setShowClosedModal(false);
            setClosedSubstatus('resolved');
            setCompletionMessage('');
            setCompletionPhotoUrl('');
            loadAuditLog(selectedRequest.service_request_id);
            announce('Request closed.');
        } catch (err) {
            console.error('Failed to close request:', err);
            announce('Could not close the request. Please try again.', 'assertive');
        }
    };

    const loadComments = async (requestId: number) => {
        try {
            const commentsData = await api.getComments(requestId);
            setComments(commentsData);
        } catch (err) {
            console.error('Failed to load comments:', err);
        }
    };

    const loadAuditLog = async (requestId: string) => {
        try {
            const logData = await api.getAuditLog(requestId);
            setAuditLog(logData);
        } catch (err) {
            // Fallback - audit log may not exist for older requests
            setAuditLog([]);
        }
    };

    const handleAddComment = async () => {
        if (!selectedRequest || !newComment.trim()) return;
        setIsSubmittingComment(true);
        try {
            await api.createComment(selectedRequest.id, newComment.trim(), commentVisibility);
            setNewComment('');
            loadComments(selectedRequest.id);
            /* The input clearing is the only visual confirmation, and an empty
             * field is indistinguishable from a field that was never sent. */
            announce(commentVisibility === 'internal'
                ? 'Internal note added.'
                : 'Public reply sent to the reporter.');
        } catch (err) {
            console.error('Failed to add comment:', err);
            announce('Could not post the comment. Please try again.', 'assertive');
        } finally {
            setIsSubmittingComment(false);
        }
    };

    const handleDeleteRequest = async () => {
        if (!selectedRequest || !deleteJustification.trim()) return;
        setIsDeleting(true);
        try {
            await api.deleteRequest(selectedRequest.service_request_id, deleteJustification.trim());
            setShowDeleteModal(false);
            setDeleteJustification('');
            setSelectedRequest(null);
            loadInitialData();
        } catch (err) {
            console.error('Failed to delete request:', err);
        } finally {
            setIsDeleting(false);
        }
    };

    const handleCreateIntake = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await api.createManualIntake({
                ...intakeData,
                source: intakeData.source as 'phone' | 'walk_in' | 'email',
            });
            setShowIntakeModal(false);
            setIntakeData({
                service_code: '',
                description: '',
                address: '',
                first_name: '',
                last_name: '',
                phone: '',
                source: 'phone',
            });
            loadInitialData();
        } catch (err) {
            console.error('Failed to create intake:', err);
        }
    };

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    // Old simple search filter removed - now using filteredSortedRequests above

    const getCounts = () => {
        const open = requests.filter((r) => r.status === 'open').length;
        const inProgress = requests.filter((r) => r.status === 'in_progress').length;
        const closed = requests.filter((r) => r.status === 'closed').length;
        return { open, inProgress, closed, total: requests.length };
    };

    const counts = getCounts();

    const menuItems = [
        { id: 'dashboard', icon: LayoutDashboard, label: 'Dashboard', count: null },
        { id: 'active', icon: AlertCircle, label: 'Open', count: counts.open },
        { id: 'in_progress', icon: Clock, label: 'In Progress', count: counts.inProgress },
        { id: 'resolved', icon: CheckCircle, label: 'Completed', count: counts.closed },
        { id: 'statistics', icon: BarChart3, label: 'Statistics', count: null },
    ];

    // Use the comprehensive filteredSortedRequests (defined above) for the list
    const sortedRequests = filteredSortedRequests;

    // Calculate dashboard stats
    const dashboardStats = useMemo(() => {
        const myRequests = allRequests.filter(r => (r as any).assigned_to === user?.username);
        const myActive = myRequests.filter(r => r.status === 'open').length;
        const myInProgress = myRequests.filter(r => r.status === 'in_progress').length;

        // Department requests - filter by user's department IDs
        const userDeptIds = user?.departments?.map(d => d.id) || [];
        const deptRequests = allRequests.filter(r =>
            userDeptIds.includes(r.assigned_department_id as number)
        );
        const deptActive = deptRequests.filter(r => r.status === 'open').length;

        return {
            myActive,
            myInProgress,
            deptActive,
            totalActive: counts.open,
            totalInProgress: counts.inProgress,
        };
    }, [allRequests, user, counts]);

    const handleMapRequestSelect = (requestId: string) => {
        loadRequestDetail(requestId);
        setCurrentView('active'); // Switch to list view to see details
    };

    // Export handlers with proper error handling
    const handleExportRequests = async (format: 'csv' | 'json' | 'geojson') => {
        try {
            await api.exportRequests({ format });
        } catch (err: any) {
            console.error('Export failed:', err);
            alert(`Export failed: ${err.message || 'Unknown error'}. Please try again.`);
        }
    };

    const handleExportStatistics = async (format: 'csv' | 'json') => {
        try {
            await api.exportStatistics({ format });
        } catch (err: any) {
            console.error('Statistics export failed:', err);
            alert(`Export failed: ${err.message || 'Unknown error'}. Please try again.`);
        }
    };

    return (
        <div className="h-screen flex overflow-hidden">
            {/* Mobile sidebar backdrop */}
            <AnimatePresence>
                {sidebarOpen && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={() => setSidebarOpen(false)}
                        className="fixed inset-0 bg-black/60 z-40 lg:hidden"
                    />
                )}
            </AnimatePresence>

            {/* Sidebar - Fixed position on both mobile and desktop */}
            <aside
                className={`fixed inset-y-0 left-0 z-50 w-72 glass-sidebar transform transition-transform duration-300 lg:translate-x-0 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'
                    }`}
                aria-label="Staff portal navigation"
            >
                <div className="flex flex-col h-full overflow-y-auto">
                    {/* Sidebar Header */}
                    <div className="p-6 border-b border-white/10">
                        <div className="flex items-center justify-between">
                            <button
                                onClick={() => {
                                    setCurrentView('dashboard');
                                    setSelectedRequest(null);
                                    window.location.hash = '';
                                }}
                                className="group flex items-center gap-3 hover:opacity-80 transition-opacity cursor-pointer"
                                aria-label="Go to dashboard home"
                                title="Go to Home"
                            >
                                {settings?.logo_url ? (
                                    <div className="relative">
                                        <img src={settings.logo_url} alt={`${settings?.township_name || 'Municipality'} logo`} className="h-8 w-auto" />
                                        <div className="absolute inset-0 flex items-center justify-center bg-black/50 rounded opacity-0 group-hover:opacity-100 transition-opacity">
                                            <Home className="w-4 h-4 text-white" aria-hidden="true" />
                                        </div>
                                    </div>
                                ) : (
                                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center">
                                        <Home className="w-5 h-5 text-white" aria-hidden="true" />
                                    </div>
                                )}
                                {/* Was an <h2> — a heading nested inside a button,
                                    and the first heading in the document, so the
                                    outline opened at level 2 in the sidebar before
                                    the page's own h1 existed. It is the button's
                                    label, not a section heading. */}
                                <div className="text-left" data-no-translate>
                                    <span className="block font-semibold text-white">
                                        Staff Command
                                    </span>
                                    <span className="block text-xs text-white/50">{settings?.township_name}</span>
                                </div>
                            </button>
                            <div className="flex items-center gap-2">
                                {/* Activity Feed Bell */}
                                {(() => {
                                    // The bell itself changes, not just the dot
                                    // beside it. A grey bell with a small badge,
                                    // on a dark sidebar, next to four other grey
                                    // icons, is the thing you are meant to notice
                                    // drawn like the things you are meant to
                                    // ignore.
                                    const look = bellAppearance(unreadActivity);
                                    return (
                                        <button
                                            onClick={() => setShowActivityFeed(true)}
                                            className={`relative p-2 rounded-lg transition-colors ${unreadActivity > 0 ? 'bg-amber-500/15 hover:bg-amber-500/25 ring-1 ring-amber-400/30' : 'hover:bg-white/10'}`}
                                            aria-label={look.label}
                                        >
                                            <Bell className={`w-5 h-5 transition-colors ${look.icon}`} aria-hidden="true" />
                                            {unreadActivity > 0 && (
                                                <span className="absolute -top-1 -right-1 min-w-5 h-5 px-1 bg-red-500 rounded-full text-[10px] font-bold text-white flex items-center justify-center">
                                                    {unreadActivity > 9 ? '9+' : unreadActivity}
                                                </span>
                                            )}
                                        </button>
                                    );
                                })()}
                                <button
                                    onClick={() => setSidebarOpen(false)}
                                    className="lg:hidden p-2 hover:bg-white/10 rounded-lg"
                                    aria-label="Close navigation menu"
                                >
                                    <X className="w-5 h-5 text-white/60" aria-hidden="true" />
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Menu Items */}
                    {/* The label was on the <aside>, which is a complementary
                        landmark, not a navigation one — so the list of views had
                        no name in the landmark list. */}
                    <nav className="flex-1 p-4 space-y-2" aria-label="Main">
                        {/* Primary action: log a request for a caller / walk-in / email */}
                        <button
                            onClick={() => { setShowManualIntake(true); setSidebarOpen(false); }}
                            className="shimmer-sweep w-full flex items-center justify-center gap-2 px-3 py-2.5 mb-4 rounded-xl text-sm font-semibold text-white bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 shadow-lg shadow-primary-900/40 transition-all hover:-translate-y-0.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                        >
                            <Phone className="w-4 h-4" aria-hidden="true" /> Log a request
                        </button>
                        <p className="text-xs font-medium text-white/40 uppercase tracking-wider px-3 mb-3">
                            Main
                        </p>
                        {/* aria-current="page" is the only thing that tells a
                            screen reader which view is open. The selected item
                            was distinguished purely by a tinted background and
                            a brighter text colour — WCAG 1.4.1: with colour
                            removed, all five read identically. The count Badge
                            needs its own words for the same reason: a bare "12"
                            beside "Open" is a number with no noun. */}
                        {menuItems.map((item) => (
                            <button
                                key={item.id}
                                onClick={() => {
                                    setCurrentView(item.id as View);
                                    setSelectedRequest(null);
                                    setSidebarOpen(false);
                                }}
                                aria-current={currentView === item.id ? 'page' : undefined}
                                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl transition-colors ${currentView === item.id
                                    ? 'bg-primary-500/20 text-white'
                                    : 'text-white/60 hover:bg-white/5 hover:text-white'
                                    }`}
                            >
                                <div className="flex items-center gap-3">
                                    <item.icon className="w-5 h-5" aria-hidden="true" />
                                    <span className="font-medium">{item.label}</span>
                                </div>
                                {item.count !== null && (
                                    <Badge variant={currentView === item.id ? 'info' : 'default'}>
                                        <span aria-hidden="true">{item.count}</span>
                                        <span className="sr-only">{item.count} requests</span>
                                    </Badge>
                                )}
                            </button>
                        ))}


                    </nav>

                    {/* User Footer - Sticky */}
                    <div className="sticky bottom-0 p-4 border-t border-white/10 bg-slate-900/90 backdrop-blur-md">
                        <div className="flex items-center gap-3">
                            <button
                                onClick={() => setShowNotificationSettings(true)}
                                className="flex items-center gap-3 flex-1 min-w-0 p-2 -m-2 hover:bg-white/5 rounded-lg transition-colors cursor-pointer"
                                title="Notification Settings"
                            >
                                <div className="w-10 h-10 flex-shrink-0 rounded-full bg-primary-500/30 flex items-center justify-center text-white font-medium">
                                    {user?.full_name?.charAt(0) || user?.username?.charAt(0) || 'U'}
                                </div>
                                <div className="min-w-0 flex-1 overflow-hidden text-left">
                                    <p className="font-medium text-white text-sm truncate">{user?.full_name || user?.username}</p>
                                    <p className="text-xs text-white/50 capitalize">{user?.role}</p>
                                    {user?.departments && user.departments.length > 0 && (
                                        <p className="text-xs text-primary-400 truncate mt-0.5">{user.departments.map(d => d.name).join(', ')}</p>
                                    )}
                                </div>
                            </button>
                            {user?.role === 'admin' && (
                                <button
                                    onClick={() => window.location.href = '/admin'}
                                    className="flex items-center gap-1.5 px-2 py-1.5 bg-amber-500/20 border border-amber-500/30 rounded-lg hover:bg-amber-500/30 transition-colors"
                                    title="Admin Console"
                                    aria-label="Go to Admin Console"
                                >
                                    <Settings className="w-4 h-4 text-amber-400" aria-hidden="true" />
                                    <span className="text-xs font-medium text-amber-400">Admin</span>
                                </button>
                            )}
                            <button
                                onClick={handleLogout}
                                className="flex-shrink-0 p-2 hover:bg-white/10 rounded-lg transition-colors"
                                title="Sign out"
                                aria-label="Sign out"
                            >
                                <LogOut className="w-5 h-5 text-white/60" aria-hidden="true" />
                            </button>
                        </div>

                        {/* Product credit — quiet, but present on every authenticated
                            screen so the platform is identifiable to staff too. */}
                        <a
                            href="https://pinpoint311.org"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="brand-link group mt-3 pt-3 border-t border-white/5 flex items-center justify-center gap-2"
                        >
                            <span className="text-[10px] uppercase tracking-wider text-white/25 group-hover:text-white/45 transition-colors">
                                Powered by
                            </span>
                            <img
                                src="/pinpoint311_logo_dark_transparent.png"
                                alt="Pinpoint 311"
                                className="h-3.5 w-auto opacity-50 group-hover:opacity-90 transition-opacity"
                            />
                        </a>
                    </div>
                </div>
            </aside>

            {/* Main Content - offset by sidebar width on desktop */}
            {/* `main` rather than a div with role="main": the element carries the
                role natively, and a tabIndex of -1 is what lets the app-wide skip
                link actually land here. */}
            <main id="main-content" tabIndex={-1} className="flex-1 flex flex-col min-w-0 lg:ml-72 focus:outline-none">
                {/* Mobile Header */}
                <header className="lg:hidden glass-sidebar p-4 flex items-center justify-between sticky top-0 z-30">
                    <button
                        onClick={() => setSidebarOpen(true)}
                        className="p-2 hover:bg-white/10 rounded-lg"
                        aria-label="Open navigation menu"
                    >
                        <Menu className="w-6 h-6 text-white" aria-hidden="true" />
                    </button>
                    {/* Was the page's only <h1>, and it is `lg:hidden` — so on
                        every desktop viewport the dashboard and list views had
                        no h1 at all, and the document outline started at h2.
                        This is chrome, not the page heading, so it is now a
                        plain label and the real h1 lives below, once, for
                        every view and every viewport. */}
                    <span className="font-semibold text-white">Staff Dashboard</span>
                    <div className="w-10" aria-hidden="true" />
                </header>

                {/* The one h1 for the whole surface — WCAG 1.3.1.
                    Visually hidden because each view already shows its own
                    heading artwork, but present, first in the main region, and
                    naming the current view. It doubles as the landing point for
                    usePageNavigation.focusMain(), so arriving on a new view
                    announces "Open Requests, heading level 1" rather than
                    silence. */}
                <h1 ref={pageHeadingRef} tabIndex={-1} data-focus-target className="sr-only">
                    {VIEW_TITLES[currentView]}
                </h1>

                {/* Dashboard View */}
                {currentView === 'dashboard' && (
                    <div className="flex-1 flex flex-col p-4 lg:p-6 overflow-auto">
                        {/* Map Section */}
                        <div className="flex-1 min-h-[400px] lg:min-h-[500px] mb-6 rounded-xl overflow-hidden">
                            {mapProviderReady(mapsConfig) ? (
                                <StaffDashboardMap
                                    config={mapConfig}
                                    requests={mapFilteredRequests}
                                    services={services}
                                    departments={departments}
                                    users={users}
                                    mapLayers={mapLayers}
                                    operationalFilters
                                    townshipBoundary={mapsConfig?.township_boundary}
                                    defaultCenter={mapsConfig?.default_center}
                                    onRequestSelect={handleMapRequestSelect}
                                />
                            ) : (
                                <div className="h-full flex items-center justify-center bg-white/5 rounded-xl border border-white/10">
                                    <div className="text-center p-8">
                                        <Map className="w-12 h-12 mx-auto mb-4 text-white/30" aria-hidden="true" />
                                        <p className="text-white/60">No map provider is configured yet</p>
                                        <p className="text-white/40 text-sm mt-2">Choose one in Admin Console → Service Providers → Maps</p>
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Stats Cards - Clickable */}
                        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                            <button
                                onClick={() => setCurrentView('active')}
                                className="text-left transition-all hover:scale-[1.02] active:scale-[0.98]"
                            >
                                <Card className="text-center border-primary-500/30 hover:border-primary-500/60 cursor-pointer transition-colors">
                                    <p className="text-3xl font-bold text-primary-400">{dashboardStats.myActive}</p>
                                    <p className="text-white/60 text-sm">Assigned to You</p>
                                </Card>
                            </button>
                            <button
                                onClick={() => setCurrentView('active')}
                                className="text-left transition-all hover:scale-[1.02] active:scale-[0.98]"
                            >
                                <Card className="text-center border-blue-500/30 hover:border-blue-500/60 cursor-pointer transition-colors">
                                    <p className="text-3xl font-bold text-blue-200">{dashboardStats.deptActive}</p>
                                    <p className="text-white/60 text-sm">Your Department</p>
                                </Card>
                            </button>
                            <button
                                onClick={() => setCurrentView('active')}
                                className="text-left transition-all hover:scale-[1.02] active:scale-[0.98]"
                            >
                                <Card className="text-center border-red-500/30 hover:border-red-500/60 cursor-pointer transition-colors">
                                    <p className="text-3xl font-bold text-red-200">{dashboardStats.totalActive}</p>
                                    <p className="text-white/60 text-sm">All Open</p>
                                </Card>
                            </button>
                            <button
                                onClick={() => setCurrentView('in_progress')}
                                className="text-left transition-all hover:scale-[1.02] active:scale-[0.98]"
                            >
                                <Card className="text-center border-amber-500/30 hover:border-amber-500/60 cursor-pointer transition-colors">
                                    <p className="text-3xl font-bold text-amber-200">{dashboardStats.totalInProgress}</p>
                                    <p className="text-white/60 text-sm">In Progress</p>
                                </Card>
                            </button>
                        </div>
                    </div>
                )}

                {/* Statistics View — Dark Glassmorphism Design */}
                {currentView === 'statistics' && (
                    <div className="flex-1 p-3 sm:p-6 lg:p-8 overflow-auto">
                        <div className="max-w-7xl mx-auto space-y-4 sm:space-y-6">
                            {/* Header */}
                            <div className="space-y-3">
                                <div>
                                    {/* h2: the page's h1 is the view name at the
                                        top of <main>, and there is exactly one. */}
                                    <h2 className="text-xl sm:text-2xl lg:text-3xl font-bold text-white">Analytics Dashboard</h2>
                                    {advancedStats?.cached_at && (
                                        <p className="text-xs sm:text-sm text-white/40 mt-1">
                                            Updated {new Date(advancedStats.cached_at.endsWith('Z') ? advancedStats.cached_at : advancedStats.cached_at + 'Z').toLocaleString()}
                                        </p>
                                    )}
                                </div>
                                <div className="grid grid-cols-3 sm:flex sm:flex-wrap items-center gap-2">
                                    <button
                                        onClick={() => setChatOpen(true)}
                                        className="flex items-center justify-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-2.5 sm:py-2 bg-gradient-to-r from-emerald-600 to-teal-600 text-white rounded-lg hover:from-emerald-700 hover:to-teal-700 transition-all text-xs sm:text-sm font-medium shadow-lg shadow-emerald-500/20"
                                    >
                                        <Sparkles className="w-4 h-4" aria-hidden="true" />
                                        <span>Ask AI</span>
                                    </button>
                                    {/* Gated on the same module flag the backend enforces —
                                        an ungated button on a disabled module is a door
                                        painted on a wall. */}
                                    {settings?.modules?.research_portal && (
                                        <button
                                            onClick={() => window.location.href = '/research'}
                                            className="flex items-center justify-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-2.5 sm:py-2 bg-white/10 border border-white/20 text-white rounded-lg hover:bg-white/20 transition-all text-xs sm:text-sm font-medium"
                                        >
                                            <FlaskConical className="w-4 h-4" aria-hidden="true" />
                                            <span className="hidden sm:inline">Research Portal</span>
                                            <span className="sm:hidden">Research</span>
                                        </button>
                                    )}
                                    {/* A disclosure, not a menu — WCAG 4.1.2 / 2.1.1.
                                        This was `role="menu"` whose children
                                        included `<p>` section headers, which are
                                        not permitted inside a menu: a screen
                                        reader either drops them or reports the
                                        item count wrongly. Nothing moved focus
                                        into the panel, there was no arrow-key
                                        roving between items, and the Escape
                                        handler sat on the wrapper div, so it only
                                        fired once focus was already inside — which
                                        it never was. Rather than build a full
                                        menu-button widget for five download
                                        links, this is now a plain expandable
                                        region of ordinary buttons: Tab reaches
                                        them in order, Escape closes, and focus
                                        returns to the trigger. */}
                                    <div
                                        ref={exportWrapRef}
                                        className="relative group"
                                        onKeyDown={(e) => {
                                            if (e.key === 'Escape' && exportOpen) {
                                                e.stopPropagation();
                                                setExportOpen(false);
                                                exportBtnRef.current?.focus();
                                            }
                                        }}
                                    >
                                        <button
                                            ref={exportBtnRef}
                                            onClick={() => setExportOpen(o => !o)}
                                            aria-expanded={exportOpen}
                                            /* Named only while the panel is really there. The
                                               panel is unmounted when collapsed, so a constant
                                               aria-controls pointed at an id that did not
                                               exist -- a broken reference some screen readers
                                               report as an error and others use to offer a
                                               "move to controlled element" command that goes
                                               nowhere. aria-expanded alone already says the
                                               button opens something (WCAG 4.1.2). */
                                            aria-controls={exportOpen ? 'export-options' : undefined}
                                            className="flex items-center justify-center gap-1.5 sm:gap-2 px-3 sm:px-4 py-2.5 sm:py-2 bg-gradient-to-r from-purple-600 to-blue-600 text-white rounded-lg hover:from-purple-700 hover:to-blue-700 transition-all text-xs sm:text-sm font-medium w-full shadow-lg shadow-purple-900/30"
                                        >
                                            <Download className="w-4 h-4" aria-hidden="true" />
                                            <span>Export</span>
                                            <ChevronDown className={`w-3 h-3 transition-transform duration-200 ${exportOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
                                        </button>
                                        {/* Unmounted rather than merely faded out:
                                            the old panel stayed in the DOM at
                                            `opacity-0 invisible`, and `invisible`
                                            does remove it from the tab order, but
                                            only as long as no descendant overrides
                                            visibility — a fragile way to hide five
                                            focusable controls. */}
                                        {exportOpen && (
                                        <div id="export-options" className="absolute right-0 mt-2 w-64 origin-top-right rounded-2xl border border-white/10 bg-slate-900/95 backdrop-blur-xl shadow-2xl shadow-black/50 ring-1 ring-white/5 z-50 overflow-hidden">
                                            <div className="p-2">
                                                {/* Admin only, like the endpoint behind it. This is the
                                                    whole-database row-level export — exact addresses, raw
                                                    descriptions, staff notes — and offering it to every
                                                    staff login meant any one compromised password was a
                                                    bulk disclosure. Staff keep the aggregate statistics
                                                    export below. */}
                                                {user?.role === 'admin' && <>
                                                <h3 className="px-2.5 pt-1.5 pb-1 text-[10px] font-semibold text-white/40 uppercase tracking-wider">Requests</h3>
                                                {[
                                                    { fmt: 'csv', Icon: FileText, label: 'CSV', hint: 'Full analytical dataset', ext: '.csv', fn: () => handleExportRequests('csv') },
                                                    { fmt: 'json', Icon: Braces, label: 'JSON', hint: 'Same fields, structured', ext: '.json', fn: () => handleExportRequests('json') },
                                                    { fmt: 'geojson', Icon: Map, label: 'GeoJSON', hint: 'Same fields, mapping / GIS', ext: '.geojson', fn: () => handleExportRequests('geojson') },
                                                ].map(({ fmt, Icon, label, hint, ext, fn }) => (
                                                    <button key={fmt} type="button" onClick={() => { fn(); setExportOpen(false); }} className="group/item w-full flex items-center gap-3 px-2.5 py-2 rounded-xl text-left hover:bg-white/[0.07] transition-colors">
                                                        <span className="w-8 h-8 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-primary-300 group-hover/item:bg-primary-500/15 group-hover/item:border-primary-400/30 transition-colors">
                                                            <Icon className="w-4 h-4" aria-hidden="true" />
                                                        </span>
                                                        <span className="flex-1 min-w-0">
                                                            <span className="block text-sm font-medium text-white/90">{label}</span>
                                                            <span className="block text-[11px] text-white/40">{hint}</span>
                                                        </span>
                                                        <span className="text-[10px] font-mono text-white/30">{ext}</span>
                                                    </button>
                                                ))}
                                                <p className="px-2.5 pb-1 text-[10px] text-white/30 leading-snug">Same analytical fields as the Research Portal export, plus operational detail (exact address, assignee, notes). Admin only; every export is audit-logged.</p>
                                                <div className="border-t border-white/10 my-1.5" />
                                                </>}
                                                <h3 className="px-2.5 pt-1.5 pb-1 text-[10px] font-semibold text-white/40 uppercase tracking-wider">Statistics</h3>
                                                {[
                                                    { fmt: 'csv', Icon: BarChart3, label: 'CSV', hint: 'Summary tables', ext: '.csv', fn: () => handleExportStatistics('csv') },
                                                    { fmt: 'json', Icon: TrendingUp, label: 'JSON', hint: 'Structured metrics', ext: '.json', fn: () => handleExportStatistics('json') },
                                                ].map(({ fmt, Icon, label, hint, ext, fn }) => (
                                                    <button key={fmt} type="button" onClick={() => { fn(); setExportOpen(false); }} className="group/item w-full flex items-center gap-3 px-2.5 py-2 rounded-xl text-left hover:bg-white/[0.07] transition-colors">
                                                        <span className="w-8 h-8 rounded-lg bg-white/5 border border-white/10 flex items-center justify-center text-primary-300 group-hover/item:bg-primary-500/15 group-hover/item:border-primary-400/30 transition-colors">
                                                            <Icon className="w-4 h-4" aria-hidden="true" />
                                                        </span>
                                                        <span className="flex-1 min-w-0">
                                                            <span className="block text-sm font-medium text-white/90">{label}</span>
                                                            <span className="block text-[11px] text-white/40">{hint}</span>
                                                        </span>
                                                        <span className="text-[10px] font-mono text-white/30">{ext}</span>
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                        )}
                                    </div>
                                </div>
                            </div>

                            {/* What did not load, and why — WCAG 3.3.1.
                                This banner was rendered inside the `dashboard`
                                branch, but `statsErrors` is only ever written by
                                loadStatistics(), which only runs on the
                                STATISTICS view. So the error never appeared on
                                the page where it happened — a statistics page
                                missing a section just looked empty — and its
                                "Try again" button, on the rare occasion it was
                                visible, retried a page the user was not on. */}
                            {statsErrors.length > 0 && (
                                <div
                                    role="alert"
                                    className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4"
                                >
                                    <div className="flex items-start gap-3">
                                        <AlertTriangle className="w-5 h-5 text-amber-300 mt-0.5 shrink-0" aria-hidden="true" />
                                        <div className="flex-1 min-w-0">
                                            <p className="text-sm font-semibold text-amber-100">
                                                {statsErrors.length === 1
                                                    ? 'One section could not be loaded'
                                                    : `${statsErrors.length} sections could not be loaded`}
                                            </p>
                                            <p className="text-xs text-amber-200/80 mt-1">
                                                Everything else on this page is up to date.
                                            </p>
                                            <ul className="mt-2 space-y-1">
                                                {statsErrors.map((e, i) => (
                                                    <li key={i} className="text-xs text-amber-200/90 break-words">• {e}</li>
                                                ))}
                                            </ul>
                                        </div>
                                        <button
                                            onClick={() => loadStatistics()}
                                            disabled={statsLoading}
                                            className="shrink-0 text-xs font-medium px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-100 border border-amber-500/30 transition-colors disabled:opacity-50"
                                        >
                                            {statsLoading ? 'Retrying…' : 'Try again'}
                                        </button>
                                    </div>
                                </div>
                            )}

                            {/* Overview Stats Row */}
                            <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-4">
                                <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-3 sm:p-5">
                                    <div className="text-[10px] sm:text-xs font-medium text-white/70 uppercase tracking-wider">Total Requests</div>
                                    <div className="text-2xl sm:text-3xl font-bold text-white mt-1 sm:mt-2">{advancedStats?.total_requests || 0}</div>
                                    <div className="text-[10px] sm:text-xs text-white/60 mt-1">All time</div>
                                </div>
                                <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-3 sm:p-5">
                                    <div className="text-[10px] sm:text-xs font-medium text-white/70 uppercase tracking-wider">Open</div>
                                    <div className="text-2xl sm:text-3xl font-bold text-amber-300 mt-1 sm:mt-2">{advancedStats?.open_requests || 0}</div>
                                    <div className="text-[10px] sm:text-xs text-white/60 mt-1">Awaiting action</div>
                                </div>
                                <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-3 sm:p-5">
                                    <div className="text-[10px] sm:text-xs font-medium text-white/70 uppercase tracking-wider">In Progress</div>
                                    <div className="text-2xl sm:text-3xl font-bold text-blue-300 mt-1 sm:mt-2">{advancedStats?.in_progress_requests || 0}</div>
                                    <div className="text-[10px] sm:text-xs text-white/60 mt-1">Being worked on</div>
                                </div>
                                <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-3 sm:p-5">
                                    <div className="text-[10px] sm:text-xs font-medium text-white/70 uppercase tracking-wider">Closed</div>
                                    <div className="text-2xl sm:text-3xl font-bold text-emerald-300 mt-1 sm:mt-2">{advancedStats?.closed_requests || 0}</div>
                                    <div className="text-[10px] sm:text-xs text-white/60 mt-1">{advancedStats?.resolution_rate?.toFixed(0) || 0}% resolution</div>
                                </div>
                            </div>

                            {/* Priority Distribution */}
                            <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-4 sm:p-6">
                                <h2 className="text-lg font-semibold text-white mb-4">Priority Distribution</h2>
                                {(() => {
                                    // One pass over one definition, so the three
                                    // numbers always sum to the total and always
                                    // agree with the labels underneath them.
                                    const { high: highPriority, medium: mediumPriority, low: lowPriority } =
                                        countByBand(allRequests);
                                    const total = allRequests.length || 1;
                                    return (
                                        <div className="space-y-3">
                                            <div className="flex min-h-6 rounded-full overflow-hidden bg-white/5">
                                                <div className="bg-red-600 transition-all flex items-center justify-center text-[11px] font-bold text-white" style={{ width: `${(highPriority / total) * 100}%`, textShadow: '0 1px 2px rgba(0,0,0,0.5)' }}>
                                                    {highPriority > 0 && `${Math.round((highPriority / total) * 100)}%`}
                                                </div>
                                                <div className="bg-amber-600 transition-all flex items-center justify-center text-[11px] font-bold text-white" style={{ width: `${(mediumPriority / total) * 100}%`, textShadow: '0 1px 2px rgba(0,0,0,0.5)' }}>
                                                    {mediumPriority > 0 && `${Math.round((mediumPriority / total) * 100)}%`}
                                                </div>
                                                <div className="bg-emerald-600 transition-all flex items-center justify-center text-[11px] font-bold text-white" style={{ width: `${(lowPriority / total) * 100}%`, textShadow: '0 1px 2px rgba(0,0,0,0.5)' }}>
                                                    {lowPriority > 0 && `${Math.round((lowPriority / total) * 100)}%`}
                                                </div>
                                            </div>
                                            <div className="flex flex-col sm:flex-row justify-between text-xs sm:text-sm gap-1">
                                                <span className="text-red-300">● {bandLabel('high')}: <strong>{highPriority}</strong></span>
                                                <span className="text-amber-300">● {bandLabel('medium')}: <strong>{mediumPriority}</strong></span>
                                                <span className="text-emerald-300">● {bandLabel('low')}: <strong>{lowPriority}</strong></span>
                                            </div>
                                        </div>
                                    );
                                })()}
                            </div>

                            {/* KPI Cards */}
                            <div className="grid grid-cols-2 lg:grid-cols-5 gap-2 sm:gap-4">
                                <div className="bg-gradient-to-br from-purple-500/20 to-purple-500/5 border border-purple-500/30 rounded-xl p-3 sm:p-5">
                                    <div className="text-[10px] sm:text-xs font-medium text-purple-200 uppercase tracking-wider">Next Week Forecast</div>
                                    <div className="text-2xl sm:text-3xl font-bold text-white mt-1 sm:mt-2">{advancedStats?.predictive_insights?.volume_forecast_next_week || 0}</div>
                                    <div className="text-[10px] sm:text-xs text-white/60 mt-1 capitalize">Trend: {advancedStats?.predictive_insights?.trend_direction || 'stable'}</div>
                                </div>
                                <div className="bg-gradient-to-br from-emerald-500/20 to-emerald-500/5 border border-emerald-500/30 rounded-xl p-3 sm:p-5">
                                    <div className="text-[10px] sm:text-xs font-medium text-emerald-200 uppercase tracking-wider">Avg Resolution</div>
                                    <div className="text-2xl sm:text-3xl font-bold text-white mt-1 sm:mt-2">{advancedStats?.avg_resolution_hours ? `${advancedStats.avg_resolution_hours.toFixed(1)}h` : 'N/A'}</div>
                                    <div className="text-[10px] sm:text-xs text-white/60 mt-1">{advancedStats?.resolution_rate?.toFixed(0) || 0}% completion</div>
                                </div>
                                <div className="bg-gradient-to-br from-red-500/20 to-red-500/5 border border-red-500/30 rounded-xl p-3 sm:p-5">
                                    <div className="text-[10px] sm:text-xs font-medium text-red-200 uppercase tracking-wider">High Priority Aging</div>
                                    <div className="text-2xl sm:text-3xl font-bold text-white mt-1 sm:mt-2">{advancedStats?.aging_high_priority_count || 0}</div>
                                    <div className="text-[10px] sm:text-xs text-white/60 mt-1">High priority (8-10) unresolved &gt; 7 days</div>
                                </div>
                                <div className="bg-gradient-to-br from-blue-500/20 to-blue-500/5 border border-blue-500/30 rounded-xl p-3 sm:p-5">
                                    <div className="text-[10px] sm:text-xs font-medium text-blue-200 uppercase tracking-wider">Peak Activity</div>
                                    <div className="text-2xl sm:text-3xl font-bold text-white mt-1 sm:mt-2">{advancedStats?.predictive_insights?.seasonal_peak_day || 'N/A'}</div>
                                    <div className="text-[10px] sm:text-xs text-white/60 mt-1">Peak: {advancedStats?.predictive_insights?.seasonal_peak_month || 'N/A'}</div>
                                </div>
                                {/* Redirected residents. A KPI card like the rest, and shown
                                    even at zero: this used to be hidden entirely until the
                                    first redirect happened, so a town that had just turned
                                    road rules on had no way to tell the difference between
                                    "nobody was redirected" and "the feature isn't reporting".
                                    Zero is a real, useful answer here. */}
                                <div className="bg-gradient-to-br from-amber-500/20 to-amber-500/5 border border-amber-500/30 rounded-xl p-3 sm:p-5">
                                    <div className="text-[10px] sm:text-xs font-medium text-amber-200 uppercase tracking-wider">Redirected</div>
                                    <div className="text-2xl sm:text-3xl font-bold text-white mt-1 sm:mt-2">{redirects?.total ?? 0}</div>
                                    <div className="text-[10px] sm:text-xs text-white/60 mt-1">
                                        {redirects
                                            ? `Sent elsewhere · last ${redirects.days} days`
                                            : 'Sent to another agency'}
                                    </div>
                                </div>
                            </div>

                            {/* SLA performance — only rendered once at least one
                                category has a target configured (the feature is opt-in). */}
                            {/* Redirected reports. Shown only once there are any -- a town
                                that redirects nobody should not carry an empty panel. */}
                            {redirects && redirects.total > 0 && (
                                <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-4 sm:p-6">
                                    <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
                                        <div>
                                            <h3 className="text-lg font-semibold text-white">Redirected to Other Agencies</h3>
                                            <p className="text-xs text-white/40 mt-0.5">
                                                Reports not filed here · last {redirects.days} days
                                            </p>
                                        </div>
                                        <div className="flex items-center gap-5 sm:gap-6">
                                            <div className="text-right">
                                                <div className="text-2xl font-bold text-amber-300">{redirects.total}</div>
                                                <div className="text-[11px] text-white/40 uppercase tracking-wide">Total</div>
                                            </div>
                                            <div className="text-right">
                                                <div className="text-2xl font-bold text-white/70">{redirects.road_based}</div>
                                                <div className="text-[11px] text-white/40 uppercase tracking-wide">By road</div>
                                            </div>
                                            <div className="text-right">
                                                <div className="text-2xl font-bold text-white/70">{redirects.category}</div>
                                                <div className="text-[11px] text-white/40 uppercase tracking-wide">By service</div>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                        {[
                                            { title: 'Agency', rows: redirects.by_jurisdiction },
                                            { title: 'Road', rows: redirects.by_road },
                                            { title: 'Service', rows: redirects.by_service },
                                        ].map(group => (
                                            <div key={group.title} className="rounded-xl bg-white/[0.03] border border-white/10 p-3.5">
                                                <p className="text-[11px] uppercase tracking-wider text-white/35 mb-2.5">{group.title}</p>
                                                {group.rows.length === 0 ? (
                                                    <p className="text-xs text-white/30">None</p>
                                                ) : (
                                                    <ul className="space-y-1.5">
                                                        {group.rows.slice(0, 6).map(row => (
                                                            <li key={row.label} className="flex items-baseline justify-between gap-3 text-sm">
                                                                <span className="text-white/70 truncate">{row.label}</span>
                                                                <span className="text-white font-medium tabular-nums shrink-0">{row.count}</span>
                                                            </li>
                                                        ))}
                                                    </ul>
                                                )}
                                            </div>
                                        ))}
                                    </div>

                                    <p className="text-[11px] text-white/35 mt-3.5 leading-relaxed">
                                        These were never filed as requests, so they are not in any queue or export.
                                        A road appearing often is either worth raising with that agency, or a sign its
                                        routing rule is wrong.
                                    </p>
                                </div>
                            )}

                            {/* Platform feedback, when the town runs that module.
                                Aggregates only -- the table holds a categorical
                                answer and a timestamp per response and nothing
                                else, so there is no individual record to open. */}
                            <PlatformFeedbackStats
                                enabled={settings?.modules?.platform_feedback}
                                stats={platformFeedback}
                            />

                            {slaPerf && slaPerf.categories.length > 0 && (
                                <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-4 sm:p-6">
                                    <div className="flex items-start justify-between gap-4 mb-4 flex-wrap">
                                        <div>
                                            <h3 className="text-lg font-semibold text-white">Service Level Performance</h3>
                                            <p className="text-xs text-white/40 mt-0.5">
                                                Against configured targets · last {slaPerf.period_days} days
                                            </p>
                                        </div>
                                        <div className="flex items-center gap-4 sm:gap-6">
                                            <div className="text-right">
                                                <div className={`text-2xl font-bold ${slaPerf.overall.compliance_rate === null ? 'text-white/40'
                                                    : slaPerf.overall.compliance_rate >= 90 ? 'text-emerald-300'
                                                        : slaPerf.overall.compliance_rate >= 75 ? 'text-amber-300' : 'text-red-300'}`}>
                                                    {slaPerf.overall.compliance_rate === null ? '—' : `${slaPerf.overall.compliance_rate}%`}
                                                </div>
                                                <div className="text-[11px] text-white/70 uppercase tracking-wider">On time</div>
                                            </div>
                                            {slaPerf.overall.open_overdue > 0 && (
                                                <div className="text-right">
                                                    <div className="text-2xl font-bold text-red-300">{slaPerf.overall.open_overdue}</div>
                                                    <div className="text-[11px] text-white/70 uppercase tracking-wider">Overdue now</div>
                                                </div>
                                            )}
                                            {slaPerf.overall.open_at_risk > 0 && (
                                                <div className="text-right">
                                                    <div className="text-2xl font-bold text-amber-300">{slaPerf.overall.open_at_risk}</div>
                                                    <div className="text-[11px] text-white/70 uppercase tracking-wider">At risk</div>
                                                </div>
                                            )}
                                        </div>
                                    </div>

                                    <div className="space-y-2.5">
                                        {slaPerf.categories.map(c => {
                                            const rate = c.compliance_rate;
                                            const barColor = rate === null ? 'bg-white/20'
                                                : rate >= 90 ? 'bg-emerald-400' : rate >= 75 ? 'bg-amber-400' : 'bg-red-400';
                                            return (
                                                <div key={c.service_code} className="p-3 rounded-lg bg-white/[0.03] border border-white/[0.06]">
                                                    <div className="flex items-center justify-between gap-3 mb-1.5 flex-wrap">
                                                        <span className="text-sm font-medium text-white">{c.service_name}</span>
                                                        <span className="text-[11px] text-white/40">
                                                            target {c.sla_hours}h
                                                            {c.avg_resolution_hours !== null && (
                                                                <> · avg {c.avg_resolution_hours}h
                                                                    <span className={c.avg_vs_target_hours !== null && c.avg_vs_target_hours > 0 ? 'text-red-300' : 'text-emerald-300'}>
                                                                        {c.avg_vs_target_hours !== null && (c.avg_vs_target_hours > 0
                                                                            ? ` (+${c.avg_vs_target_hours}h over)` : ` (${Math.abs(c.avg_vs_target_hours)}h under)`)}
                                                                    </span>
                                                                </>
                                                            )}
                                                        </span>
                                                    </div>
                                                    <div className="flex items-center gap-3">
                                                        <div className="flex-1 h-2 rounded-full bg-white/10 overflow-hidden">
                                                            <div className={`h-full rounded-full ${barColor}`} style={{ width: `${rate ?? 0}%` }} />
                                                        </div>
                                                        <span className="text-sm font-semibold text-white min-w-12 text-right">
                                                            {rate === null ? '—' : `${rate}%`}
                                                        </span>
                                                    </div>
                                                    <div className="flex items-center gap-3 mt-1.5 text-[11px] text-white/40 flex-wrap">
                                                        {c.resolved > 0
                                                            ? <span>{c.met} of {c.resolved} resolved on time</span>
                                                            : <span>No requests resolved yet</span>}
                                                        {c.open_overdue > 0 && <span className="text-red-300">{c.open_overdue} overdue</span>}
                                                        {c.open_at_risk > 0 && <span className="text-amber-300">{c.open_at_risk} at risk</span>}
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>

                                    {slaPerf.categories_without_sla.length > 0 && (
                                        <p className="text-[11px] text-white/30 mt-3">
                                            No target set for {slaPerf.categories_without_sla.length} other{' '}
                                            {slaPerf.categories_without_sla.length === 1 ? 'category' : 'categories'} —
                                            these are excluded from the numbers above.
                                        </p>
                                    )}
                                </div>
                            )}

                            {/* Two-Column: Categories + Weekly Trend */}
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">
                                {/* Requests by Category — Horizontal Bars */}
                                <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-4 sm:p-6">
                                    <h3 className="text-lg font-semibold text-white mb-4">Requests by Category</h3>
                                    <div className="space-y-3">
                                        {(() => {
                                            const entries = Object.entries(advancedStats?.requests_by_category || {})
                                                .sort(([, a], [, b]) => (b as number) - (a as number));
                                            const maxCount = entries.length > 0 ? (entries[0][1] as number) : 1;
                                            return entries.map(([category, count]) => (
                                                <div key={category}>
                                                    <div className="flex justify-between text-sm mb-1">
                                                        <span className="text-white/80 truncate mr-2">{category}</span>
                                                        <span className="text-white/60 font-medium flex-shrink-0">{count as number}</span>
                                                    </div>
                                                    <div className="h-2 bg-white/5 rounded-full overflow-hidden">
                                                        <div
                                                            className="h-full bg-gradient-to-r from-purple-500 to-blue-500 rounded-full transition-all"
                                                            style={{ width: `${((count as number) / maxCount) * 100}%` }}
                                                        />
                                                    </div>
                                                </div>
                                            ));
                                        })()}
                                    </div>
                                </div>

                                {/* Weekly Trend Chart */}
                                <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-4 sm:p-6">
                                    <h3 className="text-lg font-semibold text-white mb-4" id="weekly-trend-heading">Weekly Trend</h3>
                                    {/* The chart itself is decoration for assistive tech.
                                        It had no role, no accessible name, no <title>/<desc>
                                        and no text equivalent, so a screen reader reached
                                        this card and got nothing at all (WCAG 1.1.1); and
                                        recharts' tooltip is pointer-driven, so even a
                                        sighted keyboard user could not read a single value
                                        off it (2.1.1). Marking the canvas aria-hidden and
                                        publishing the same numbers as a real table below
                                        gives everyone the data through markup that already
                                        works, rather than trying to make an SVG behave.

                                        Axis colours moved off inline styles: they were
                                        rgba(255,255,255,0.5) ticks (3.77:1) and
                                        rgba(255,255,255,0.3) axis lines (2.30:1), and being
                                        inline meant no CSS override could reach them. The
                                        Area stroke moved from #8b5cf6 (2.35:1 against this
                                        card — below the 3:1 that 1.4.11 requires of a
                                        graphical object carrying meaning) to a lighter
                                        violet that clears it. */}
                                    <div className="h-48 sm:h-64" aria-hidden="true">
                                        <ResponsiveContainer width="100%" height="100%">
                                            <AreaChart data={advancedStats?.weekly_trend || []}>
                                                <XAxis dataKey="period" stroke="rgba(255,255,255,0.75)" style={{ fontSize: '12px' }} tick={{ fill: 'rgba(255,255,255,0.9)' }} />
                                                <YAxis stroke="rgba(255,255,255,0.75)" style={{ fontSize: '12px' }} tick={{ fill: 'rgba(255,255,255,0.9)' }} />
                                                <Tooltip contentStyle={{ backgroundColor: 'rgba(17,24,39,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: 'white' }} />
                                                <Area type="monotone" dataKey="total" stroke="#c4b5fd" fill="url(#purpleGradient)" fillOpacity={0.4} strokeWidth={2} />
                                                <defs>
                                                    <linearGradient id="purpleGradient" x1="0" y1="0" x2="0" y2="1">
                                                        <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.6} />
                                                        <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0.05} />
                                                    </linearGradient>
                                                </defs>
                                            </AreaChart>
                                        </ResponsiveContainer>
                                    </div>
                                    <details className="mt-3 group">
                                        <summary className="cursor-pointer text-xs font-medium text-primary-300 hover:text-primary-200 focus-visible:ring-2 focus-visible:ring-amber-400 rounded">
                                            Weekly trend as a table
                                        </summary>
                                        <div className="mt-2 max-h-56 overflow-auto">
                                            <table className="w-full text-left text-sm">
                                                <caption className="sr-only">
                                                    Requests received per period, the same data plotted in the Weekly Trend chart
                                                </caption>
                                                <thead>
                                                    <tr className="text-xs uppercase tracking-wider text-white/60">
                                                        <th scope="col" className="py-1 pr-3 font-medium">Period</th>
                                                        <th scope="col" className="py-1 font-medium">Requests</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {(advancedStats?.weekly_trend ?? []).map((row: any) => (
                                                        <tr key={String(row.period)} className="border-t border-white/5">
                                                            <th scope="row" className="py-1 pr-3 font-normal text-white/80">{String(row.period)}</th>
                                                            <td className="py-1 text-white tabular-nums">{row.total ?? 0}</td>
                                                        </tr>
                                                    ))}
                                                    {(advancedStats?.weekly_trend ?? []).length === 0 && (
                                                        <tr>
                                                            <td colSpan={2} className="py-2 text-white/60">No trend data yet.</td>
                                                        </tr>
                                                    )}
                                                </tbody>
                                            </table>
                                        </div>
                                    </details>
                                </div>
                            </div>

                            {/* Staff Performance + Workload */}
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">
                                <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-4 sm:p-6">
                                    <h3 className="text-lg font-semibold text-white mb-1">Staff Activity</h3>
                                    <p className="text-xs text-white/40 mb-4">Resolutions and current workload</p>

                                    {/* Top Resolvers */}
                                    {advancedStats?.top_staff_by_resolutions && Object.keys(advancedStats.top_staff_by_resolutions).length > 0 && (
                                        <div className="mb-4">
                                            <div className="text-xs font-medium text-white/50 uppercase tracking-wider mb-2">Top Resolvers</div>
                                            <div className="space-y-1.5">
                                                {Object.entries(advancedStats.top_staff_by_resolutions)
                                                    .sort(([, a], [, b]) => (b as number) - (a as number))
                                                    .slice(0, 5)
                                                    .map(([staff, count], idx) => (
                                                        <div key={staff} className="flex items-center gap-2 p-2 bg-white/5 rounded-lg">
                                                            <span className="text-xs text-white/70 min-w-4">{idx + 1}.</span>
                                                            <span className="text-sm text-white/80 flex-1 truncate">{staff}</span>
                                                            <span className="text-sm font-semibold text-emerald-400">{count as number}</span>
                                                        </div>
                                                    ))}
                                            </div>
                                        </div>
                                    )}

                                    {/* Current Workload */}
                                    {advancedStats?.workload_by_staff && Object.keys(advancedStats.workload_by_staff).length > 0 && (
                                        <div>
                                            <div className="text-xs font-medium text-white/50 uppercase tracking-wider mb-2">Current Workload</div>
                                            <div className="space-y-1.5">
                                                {Object.entries(advancedStats.workload_by_staff)
                                                    .sort(([, a], [, b]) => (b as number) - (a as number))
                                                    .slice(0, 5)
                                                    .map(([staff, count]) => (
                                                        <div key={staff} className="flex items-center gap-2 p-2 bg-white/5 rounded-lg">
                                                            <span className="text-sm text-white/80 flex-1 truncate">{staff}</span>
                                                            <span className="text-sm font-semibold text-blue-400">{count as number} active</span>
                                                        </div>
                                                    ))}
                                            </div>
                                        </div>
                                    )}

                                    {/* Empty state */}
                                    {(!advancedStats?.top_staff_by_resolutions || Object.keys(advancedStats.top_staff_by_resolutions).length === 0) &&
                                        (!advancedStats?.workload_by_staff || Object.keys(advancedStats.workload_by_staff).length === 0) && (
                                            <div className="text-center py-8 text-white/30">
                                                <p className="text-sm">No staff activity data available</p>
                                            </div>
                                        )}
                                </div>
                            </div>

                            {/* Spatial Bias Heatmap — Full Width */}
                            <SpatialBiasHeatmap
                                heatmapData={heatmapData}
                                hotspots={advancedStats?.hotspots || []}
                                config={mapConfig}
                                defaultCenter={mapsConfig?.default_center || advancedStats?.geographic_center || undefined}
                            />
                        </div>
                    </div>
                )} {/* This closes the conditional for currentView === 'statistics' || currentView === 'dashboard' */}

                {/* AI Analytics Chat — Floating Popup (matches marketing site design) */}
                <AnimatePresence>
                    {chatOpen && (
                        <>
                            {/* Subtle backdrop — click to close */}
                            <motion.div
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                                exit={{ opacity: 0 }}
                                className="fixed inset-0 z-[60]"
                                onClick={() => setChatOpen(false)}
                            />
                            {/* Floating popup card */}
                            <motion.div
                                initial={{ opacity: 0, y: 16, scale: 0.97 }}
                                animate={{ opacity: 1, y: 0, scale: 1 }}
                                exit={{ opacity: 0, y: 16, scale: 0.97 }}
                                transition={{ duration: 0.2, ease: 'easeOut' }}
                                className="fixed z-[70] flex flex-col overflow-hidden"
                                style={{
                                    bottom: 'calc(5rem + env(safe-area-inset-bottom, 0px))',
                                    right: '1.25rem',
                                    left: 'auto',
                                    width: 'min(380px, calc(100vw - 2rem))',
                                    maxHeight: 'min(540px, 70vh)',
                                    background: 'rgba(21, 25, 41, 0.97)',
                                    backdropFilter: 'blur(24px)',
                                    border: '1px solid rgba(255,255,255,0.12)',
                                    borderRadius: '18px',
                                    boxShadow: '0 20px 60px rgba(0,0,0,0.5), 0 0 40px rgba(16,185,129,0.1)',
                                }}
                            >
                                {/* Header */}
                                <div className="flex items-center justify-between px-5 py-3.5" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                                    <h3 className="text-[0.92rem] font-bold flex items-center gap-2">
                                        <span className="text-white">✦</span>
                                        <span style={{ background: 'linear-gradient(135deg, #a5b4fc, #22d3a5)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Analytics Advisor</span>
                                    </h3>
                                    <div className="flex items-center gap-1.5">
                                        {chatMessages.length > 0 &&(
                                            /* Named by `aria-label`, not by `title`
                                                alone — WCAG 1.1.1. A `title` on an
                                                icon-only button is a tooltip that
                                                never appears for touch or keyboard
                                                users, and some screen readers
                                                ignore it entirely, so the control
                                                announced as just "button".
                                                Confirmed because it destroys the
                                                whole transcript with no undo —
                                                WCAG 3.3.4. */
                                            <button
                                                type="button"
                                                onClick={() => {
                                                    if (!window.confirm('Clear this conversation?\n\nThe questions and answers above will be discarded. This cannot be undone.')) return;
                                                    setChatMessages([]);
                                                    setChatInput('');
                                                    announce('Conversation cleared.');
                                                }}
                                                className="flex items-center justify-center transition-colors"
                                                aria-label="Clear conversation"
                                                title="Clear conversation"
                                                style={{ background: 'rgba(255,255,255,0.08)', border: 'none', borderRadius: '8px', width: '30px', height: '30px', cursor: 'pointer' }}
                                            >
                                                <Trash2 className="w-3.5 h-3.5 text-white/40 hover:text-red-400" aria-hidden="true" />
                                            </button>
                                        )}
                                        <button
                                            onClick={() => setChatOpen(false)}
                                            aria-label="Close"
                                            className="flex items-center justify-center transition-colors"
                                            style={{ background: 'rgba(255,255,255,0.08)', border: 'none', borderRadius: '8px', width: '30px', height: '30px', cursor: 'pointer', color: 'rgba(255,255,255,0.5)', fontSize: '0.85rem' }}
                                        >
                                            ✕
                                        </button>
                                    </div>
                                </div>

                                {/* Messages */}
                                <div
                                    className="flex-1 overflow-y-auto flex flex-col gap-3 min-h-[200px]"
                                    style={{ padding: '1rem 1.25rem', maxHeight: '340px', scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.1) transparent' }}
                                >
                                    {chatMessages.length === 0 && !chatLoading && (
                                        <div
                                            className="text-[0.82rem] leading-relaxed"
                                            style={{ 
                                                maxWidth: '90%', padding: '0.65rem 0.9rem', borderRadius: '14px', borderBottomLeftRadius: '4px',
                                                background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.8)', alignSelf: 'flex-start'
                                            }}
                                        >
                                            👋 Hi! I'm the AI Analytics Advisor. I can help you understand your data — trends, equity metrics, response times, sentiment, and more. What would you like to know?
                                        </div>
                                    )}

                                    {chatMessages.map((msg, i) => (
                                        <div
                                            key={i}
                                            className="text-[0.82rem] leading-relaxed"
                                            style={{
                                                maxWidth: '90%',
                                                padding: '0.65rem 0.9rem',
                                                borderRadius: '14px',
                                                wordBreak: 'break-word',
                                                alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                                                ...(msg.role === 'user' ? {
                                                    background: 'rgba(16,185,129,0.2)',
                                                    border: '1px solid rgba(16,185,129,0.25)',
                                                    color: '#a7f3d0',
                                                    borderBottomRightRadius: '4px',
                                                } : {
                                                    background: 'rgba(255,255,255,0.06)',
                                                    border: '1px solid rgba(255,255,255,0.08)',
                                                    color: 'rgba(255,255,255,0.8)',
                                                    borderBottomLeftRadius: '4px',
                                                }),
                                            }}
                                        >
                                            {msg.role === 'assistant' ? (
                                                <div
                                                    dangerouslySetInnerHTML={{
                                                        __html: (() => {
                                                            let html = msg.content;
                                                            html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                                                            html = html.replace(/^### (.+)$/gm, '<strong style="display:block;margin:.5rem 0 .2rem">$1</strong>');
                                                            html = html.replace(/^## (.+)$/gm, '<strong style="display:block;margin:.6rem 0 .2rem;font-size:.9rem">$1</strong>');
                                                            html = html.replace(/^# (.+)$/gm, '<strong style="display:block;margin:.7rem 0 .3rem;font-size:1rem">$1</strong>');
                                                            html = html.replace(/\*\*(.+?)\*\*/g, '<strong style="color:white;font-weight:600">$1</strong>');
                                                            html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
                                                            html = html.replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,0.35);padding:.15rem .35rem;border-radius:4px;font-size:.78rem;color:#a5b4fc">$1</code>');
                                                            html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
                                                            html = html.replace(/^(\d+)\. (.+)$/gm, '<li>$2</li>');
                                                            html = html.replace(/((?:<li>[^]*?<\/li>\s*(?:<br\s*\/?>)?)+)/g, (m) => '<ul style="padding-left:1rem;margin:.3rem 0">' + m.replace(/<br\s*\/?>/g, '') + '</ul>');
                                                            html = html.replace(/\n\n/g, '<br/><br/>');
                                                            html = html.replace(/\n/g, '<br/>');
                                                            return html;
                                                        })()
                                                    }}
                                                />
                                            ) : (
                                                <span>{msg.content}</span>
                                            )}
                                        </div>
                                    ))}

                                    {chatLoading && (
                                        <div className="flex gap-1 self-start" style={{ padding: '0.65rem 0.9rem' }}>
                                            {[0, 1, 2].map(j => (
                                                <div
                                                    key={j}
                                                    className="rounded-full"
                                                    style={{
                                                        width: '6px', height: '6px', background: 'rgba(255,255,255,0.3)',
                                                        animation: 'bounce 1.2s ease-in-out infinite',
                                                        animationDelay: `${j * 0.2}s`,
                                                    }}
                                                />
                                            ))}
                                            <span className="text-xs text-white/30 ml-1.5">Analyzing...</span>
                                        </div>
                                    )}
                                    <div ref={chatEndRef} />
                                </div>

                                {/* Suggestion chips (only when empty) */}
                                {chatMessages.length === 0 && !chatLoading && (
                                    <div className="flex flex-wrap gap-1.5" style={{ padding: '0.5rem 1.25rem 0.25rem' }}>
                                        {[
                                            'What are the top issue categories?',
                                            'Show equity gaps in response times',
                                            'How is resident sentiment trending?',
                                            'What should I prioritize today?',
                                        ].map((q, i) => (
                                            <button
                                                key={i}
                                                onClick={() => { setChatInput(q); }}
                                                className="transition-colors"
                                                style={{
                                                    background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.2)',
                                                    borderRadius: '100px', padding: '0.35rem 0.75rem', fontSize: '0.72rem',
                                                    color: '#6ee7b7', cursor: 'pointer', fontFamily: 'inherit',
                                                    // `whiteSpace: nowrap` here forced each chip to one line
                                                    // inside a 380px-wide popup, so at 200% zoom (WCAG 1.4.4)
                                                    // or with a longer translation the text ran under the
                                                    // panel edge and was simply unreadable. Wrapping is
                                                    // slightly less tidy and always legible.
                                                    textAlign: 'left',
                                                }}
                                            >
                                                {q}
                                            </button>
                                        ))}
                                    </div>
                                )}

                                {/* Input area */}
                                <form
                                    onSubmit={sendChatMessage}
                                    className="flex gap-2"
                                    style={{ padding: '0.75rem 1.25rem', borderTop: '1px solid rgba(255,255,255,0.08)', paddingBottom: 'max(0.75rem, env(safe-area-inset-bottom))' }}
                                >
                                    <textarea
                                        value={chatInput}
                                        onChange={(e) => setChatInput(e.target.value)}
                                        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChatMessage(); } }}
                                        placeholder="Ask about your data…"
                                        disabled={chatLoading}
                                        rows={1}
                                        maxLength={2000}
                                        style={{
                                            flex: 1, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
                                            borderRadius: '10px', padding: '0.6rem 0.85rem', color: 'white',
                                            fontSize: '16px', fontFamily: 'inherit', outline: 'none', resize: 'none',
                                            maxHeight: '120px', overflowY: 'auto', lineHeight: '1.4',
                                        }}
                                    />
                                    <button
                                        type="submit"
                                        disabled={!chatInput.trim() || chatLoading}
                                        style={{
                                            background: 'linear-gradient(135deg, #10b981, #14b8a6)', border: 'none', borderRadius: '10px',
                                            width: '38px', height: '38px', display: 'grid', placeItems: 'center',
                                            cursor: 'pointer', color: 'white', fontSize: '0.85rem', flexShrink: 0,
                                            opacity: (!chatInput.trim() || chatLoading) ? 0.35 : 1,
                                        }}
                                    >
                                        →
                                    </button>
                                </form>
                            </motion.div>
                        </>
                    )}
                </AnimatePresence>

                {/* Floating AI Chat FAB Button (visible when chat is closed) */}
                {!chatOpen && (currentView === 'statistics' || currentView === 'dashboard') && (
                    <button
                        onClick={() => setChatOpen(true)}
                        className="fixed z-[55] animate-pulse"
                        style={{
                            bottom: 'calc(1.5rem + env(safe-area-inset-bottom, 0px))',
                            right: '1.5rem',
                            width: '56px', height: '56px', borderRadius: '50%',
                            background: 'linear-gradient(135deg, #10b981 0%, #14b8a6 100%)',
                            border: 'none', cursor: 'pointer', display: 'grid', placeItems: 'center',
                            boxShadow: '0 4px 24px rgba(16,185,129,0.4)',
                        }}
                        aria-label="Ask AI Analytics Advisor"
                    >
                        <MessageSquare className="w-6 h-6 text-white" style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 2 }} aria-hidden="true" />
                    </button>
                )}

                {/* List/Detail View */}
                {currentView !== 'statistics' && currentView !== 'dashboard' && (
                    <div className="flex-1 flex min-h-0 h-full">
                        {/* Request List Panel.
                            `inert` removes the whole subtree from focus, hit
                            testing and the accessibility tree in one attribute;
                            aria-hidden is kept alongside it for the browsers
                            that do not yet implement inert, where it at least
                            silences the screen reader. */}
                        <div
                            className="w-full lg:w-96 flex flex-col border-r border-white/10 h-full overflow-hidden"
                            aria-hidden={listBehindOverlay || undefined}
                            {...(listBehindOverlay ? ({ inert: '' } as Record<string, string>) : {})}
                        >
                            {/* List Header with Quick Stats */}
                            <div className="p-4 border-b border-white/10 space-y-3">
                                <div className="flex items-center justify-between">
                                    <h2 className="text-lg font-semibold text-white">
                                        Incidents{' '}
                                        {/* The visible half of the fix above: the count
                                            has to exist on the page for a screen reader
                                            to be able to go back and re-read it, and for
                                            a sighted user to see the filter did anything
                                            when the list is scrolled past the fold. */}
                                        <span className="font-normal text-sm text-white/60 tabular-nums">
                                            ({isLoading ? '…' : sortedRequests.length})
                                        </span>
                                    </h2>
                                    <div className="flex items-center gap-2">
                                        {/* Was an icon-only toggle with no accessible
                                            name at all (1.1.1), no aria-expanded or
                                            aria-controls to say what it operates
                                            (4.1.2), and "filters are active" conveyed
                                            by a bullet glyph tinted primary-400 — a
                                            bullet is not a word and a colour is not a
                                            state (1.4.1). The name now carries both. */}
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            onClick={() => setShowFilters(!showFilters)}
                                            aria-expanded={showFilters}
                                            /* Only while the panel exists -- it is unmounted when
                                               collapsed, so a constant aria-controls left a dangling
                                               reference for assistive tech to follow nowhere. */
                                            aria-controls={showFilters ? 'request-filters' : undefined}
                                            className={hasActiveFilters ? 'text-primary-400' : ''}
                                        >
                                            <Search className="w-4 h-4" aria-hidden="true" />
                                            <span className="sr-only">
                                                {hasActiveFilters ? 'Filters, filters active' : 'Filters'}
                                            </span>
                                            {hasActiveFilters && <span className="ml-1 text-xs" aria-hidden="true">•</span>}
                                        </Button>
                                    </div>
                                </div>

                                {/* Assignment Filter Buttons - Premium Styling.
                                    Three mutually exclusive scopes whose selection was
                                    signalled only by a gradient fill and a ring (WCAG
                                    1.4.1), with nothing in the markup saying the three
                                    belonged together or that one of them was chosen
                                    (4.1.2). aria-pressed on a real toggle button is the
                                    smallest honest fix; the group wrapper gives the set
                                    a name, so a screen reader says what these three
                                    choices are choosing between. */}
                                <div className="flex gap-2" role="group" aria-label="Filter by assignment">
                                    <button
                                        type="button"
                                        onClick={() => setFilterAssignment("me")}
                                        aria-pressed={filterAssignment === 'me'}
                                        className={`flex-1 px-4 py-3 rounded-xl text-sm font-semibold transition-all ${filterAssignment === 'me'
                                            ? 'bg-gradient-to-r from-primary-500 to-primary-600 text-white shadow-lg shadow-primary-500/40 ring-2 ring-primary-400/60'
                                            : 'bg-white/5 border border-white/15 text-white/80 hover:bg-white/10 hover:text-white hover:border-white/25'
                                            }`}
                                    >
                                        My Requests ({quickStats.assignedToMe})
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => setFilterAssignment("department")}
                                        aria-pressed={filterAssignment === 'department'}
                                        className={`flex-1 px-4 py-3 rounded-xl text-sm font-semibold transition-all ${filterAssignment === 'department'
                                            ? 'bg-gradient-to-r from-purple-500 to-purple-600 text-white shadow-lg shadow-purple-500/40 ring-2 ring-purple-400/60'
                                            : 'bg-white/5 border border-white/15 text-white/80 hover:bg-white/10 hover:text-white hover:border-white/25'
                                            }`}
                                    >
                                        My Department ({quickStats.inMyDepartment})
                                    </button>
                                    <button
                                        type="button"
                                        onClick={() => setFilterAssignment("all")}
                                        aria-pressed={filterAssignment === 'all'}
                                        className={`flex-1 px-4 py-3 rounded-xl text-sm font-semibold transition-all ${filterAssignment === 'all'
                                            ? 'bg-gradient-to-r from-slate-500 to-slate-600 text-white shadow-lg shadow-slate-500/40 ring-2 ring-slate-400/60'
                                            : 'bg-white/5 border border-white/15 text-white/80 hover:bg-white/10 hover:text-white hover:border-white/25'
                                            }`}
                                    >
                                        All Requests ({quickStats.total})
                                    </button>
                                </div>


                                {/* Search Input */}
                                <div className="relative">
                                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" aria-hidden="true" />
                                    <input
                                        type="text"
                                        placeholder="Search by ID, description, address..."
                                        aria-label="Search requests by ID, description, or address"
                                        value={searchQuery}
                                        onChange={(e) => setSearchQuery(e.target.value)}
                                        className="glass-input pl-10 py-2 text-sm"
                                    />
                                    {searchQuery && (
                                        <button
                                            onClick={() => setSearchQuery('')}
                                            className="absolute right-3 top-1/2 -translate-y-1/2 text-white/40 hover:text-white"
                                            aria-label="Clear search"
                                        >
                                            <X className="w-4 h-4" aria-hidden="true" />
                                        </button>
                                    )}
                                </div>

                                {/* Sort Order */}
                                <div>
                                    <label htmlFor="request-sort-order" className="text-xs text-white/50 mb-1 block">Sort order</label>
                                    <select
                                        id="request-sort-order"
                                        value={sortOrder}
                                        onChange={(e) => setSortOrder(e.target.value as typeof sortOrder)}
                                        className="glass-input text-sm py-2 w-full"
                                    >
                                        <option value="newest">Newest First</option>
                                        <option value="oldest">Oldest First</option>
                                        <option value="priority_high">Priority: High → Low</option>
                                        <option value="priority_low">Priority: Low → High</option>
                                        <option value="alpha">Category A → Z</option>
                                    </select>
                                </div>

                                {/* Advanced Filters Panel */}
                                {/* Every field here had a bare `<label>` floating above a
                                    `<select>` with no id — no htmlFor, no association at
                                    all (WCAG 1.3.1/3.3.2). Clicking the word "Department"
                                    did nothing, and the duplicate `aria-label` was a patch
                                    that papered over the missing relationship rather than
                                    creating one: it names the control but still leaves the
                                    visible text orphaned, so speech-input users saying
                                    "Department" hit nothing. Real htmlFor/id throughout. */}
                                {showFilters && (
                                    <div id="request-filters" className="space-y-3 pt-2 border-t border-white/10">
                                        {/* Department Filter */}
                                        <div>
                                            <label htmlFor="filter-department" className="text-xs text-white/50 mb-1 block">Department</label>
                                            <select
                                                id="filter-department"
                                                value={filterDepartment ?? ''}
                                                onChange={(e) => setFilterDepartment(e.target.value ? Number(e.target.value) : null)}
                                                className="glass-input text-sm py-2"
                                            >
                                                <option value="">All Departments</option>
                                                {departments.map(d => (
                                                    <option key={d.id} value={d.id}>{d.name}</option>
                                                ))}
                                            </select>
                                        </div>

                                        {/* Service Category Filter */}
                                        <div>
                                            <label htmlFor="filter-category" className="text-xs text-white/50 mb-1 block">Category</label>
                                            <select
                                                id="filter-category"
                                                value={filterService ?? ''}
                                                onChange={(e) => setFilterService(e.target.value || null)}
                                                className="glass-input text-sm py-2"
                                            >
                                                <option value="">All Categories</option>
                                                {services.map(s => (
                                                    <option key={s.service_code} value={s.service_code}>{s.service_name}</option>
                                                ))}
                                            </select>
                                        </div>

                                        {/* Priority Filter */}
                                        <div>
                                            <label htmlFor="filter-priority" className="text-xs text-white/50 mb-1 block">Priority Level</label>
                                            <select
                                                id="filter-priority"
                                                value={mapPriorityFilter}
                                                onChange={(e) => setMapPriorityFilter(e.target.value as 'all' | 'high' | 'medium' | 'low')}
                                                className="glass-input text-sm py-2"
                                            >
                                                <option value="all">All Priorities</option>
                                                <option value="high">🔴 {bandLabel('high')}</option>
                                                <option value="medium">🟡 {bandLabel('medium')}</option>
                                                <option value="low">🟢 {bandLabel('low')}</option>
                                            </select>
                                        </div>

                                        {/* Clear Filters */}
                                        {hasActiveFilters && (
                                            <button
                                                onClick={clearFilters}
                                                className="text-xs text-primary-400 hover:text-primary-300"
                                            >
                                                Clear all filters
                                            </button>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* Request List */}
                            <div className="flex-1 overflow-auto overscroll-contain">
                                {isLoading ? (
                                    <div className="flex justify-center py-12">
                                        <div className="w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
                                    </div>
                                ) : sortedRequests.length === 0 ? (
                                    <div className="text-center py-12 text-white/50">
                                        No incidents found
                                    </div>
                                ) : (() => {
                                    // Separate requests into needs priority and others
                                    const needsPriorityRequests = sortedRequests.filter(r => {
                                        const ai = r.ai_analysis as any;
                                        return ai?.priority_score != null && r.manual_priority_score == null;
                                    })
                                        // Sort by submission date (newest first) instead of AI priority
                                        .sort((a, b) => new Date(b.requested_datetime).getTime() - new Date(a.requested_datetime).getTime());

                                    const otherRequests = sortedRequests.filter(r => {
                                        const ai = r.ai_analysis as any;
                                        return !(ai?.priority_score != null && r.manual_priority_score == null);
                                    });

                                    // Render a single request item
                                    const renderRequest = (request: typeof sortedRequests[0]) => (
                                        <motion.button
                                            key={request.id}
                                            type="button"
                                            /* Remember the exact row that opened the
                                               detail, so closing it puts focus back
                                               here instead of on <body> — from which
                                               the next Tab restarts at the top of the
                                               document (WCAG 2.4.3). */
                                            onClick={(e) => {
                                                returnFocusRef.current = e.currentTarget as HTMLElement;
                                                loadRequestDetail(request.service_request_id);
                                            }}
                                            /* Which row is open was shown only by a
                                               slightly lighter background — WCAG 1.4.1. */
                                            aria-current={selectedRequest?.service_request_id === request.service_request_id ? 'true' : undefined}
                                            className={`w-full text-left p-4 hover:bg-white/5 transition-colors ${selectedRequest?.service_request_id === request.service_request_id
                                                ? 'bg-white/10'
                                                : ''
                                                }`}
                                            whileTap={{ scale: 0.98 }}
                                        >
                                            <div className="flex items-start justify-between mb-2">
                                                <div className="flex items-center gap-2 flex-wrap">
                                                    <span className="font-mono text-xs text-white/50">
                                                        {request.service_request_id}
                                                    </span>
                                                    {/* NEW badge for requests < 24 hours old */}
                                                    {Date.now() - new Date(request.requested_datetime).getTime() < 24 * 60 * 60 * 1000 && (
                                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-semibold animate-pulse">
                                                            NEW
                                                        </span>
                                                    )}
                                                </div>
                                                <StatusBadge status={request.status} />
                                            </div>
                                            {/* Was an <h3> nested inside this button. A
                                                heading inside a control is not a section
                                                heading — it produced a heading list of
                                                sixty entries that were all buttons, and
                                                it sat under the list's h2 while the
                                                detail panel's h1 came after it, so the
                                                outline ran h2, h3, h1 (WCAG 1.3.1). The
                                                button's own accessible name already
                                                carries this text. */}
                                            <span className="block font-medium text-white mb-1">{request.service_name}</span>
                                            <span className="block text-sm text-white/50 line-clamp-2">{request.description}</span>
                                            <div className="flex items-center justify-between mt-2">
                                                <div className="flex items-center gap-2 text-xs text-white/40">
                                                    <Clock className="w-3 h-3" aria-hidden="true" />
                                                    {new Date(request.requested_datetime).toLocaleDateString()}
                                                </div>
                                                {/* Priority indicator */}
                                                {request.assigned_to === user?.username ? (
                                                    <span className="text-xs px-2 py-0.5 rounded-full bg-primary-500/20 text-primary-400">
                                                        🎯 Mine
                                                    </span>
                                                ) : request.assigned_department_id && userDepartmentIds.includes(request.assigned_department_id) && !request.assigned_to ? (
                                                    <span className="text-xs px-2 py-0.5 rounded-full bg-purple-500/20 text-purple-200">
                                                        🏢 Dept
                                                    </span>
                                                ) : null}
                                            </div>
                                        </motion.button>
                                    );

                                    return (
                                        <div>
                                            {/* Needs Priority Review Section - Bordered box at top */}
                                            {needsPriorityRequests.length > 0 && (
                                                <div className="m-3 rounded-xl border-2 border-amber-500/40 bg-amber-500/5 overflow-hidden">
                                                    {/* Chip Header */}
                                                    <div className="flex items-center justify-center py-2 bg-amber-500/10 border-b border-amber-500/20">
                                                        <span className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-amber-500/20 border border-amber-500/50 text-amber-400 text-sm font-semibold">
                                                            <span className="relative flex h-2 w-2">
                                                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                                                                <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
                                                            </span>
                                                            Needs Priority Review ({needsPriorityRequests.length})
                                                        </span>
                                                    </div>
                                                    {/* Requests in this section */}
                                                    <div className="divide-y divide-amber-500/10">
                                                        {needsPriorityRequests.map(renderRequest)}
                                                    </div>
                                                </div>
                                            )}

                                            {/* Other Requests */}
                                            {otherRequests.length > 0 && (
                                                <div className="divide-y divide-white/5">
                                                    {otherRequests.map(renderRequest)}
                                                </div>
                                            )}
                                        </div>
                                    );
                                })()}
                            </div>
                        </div>

                        {/* Detail Panel - Shows as overlay on mobile, side panel on desktop */}
                        <div
                            ref={detailPanelRef}
                            className={`${selectedRequest ? 'fixed inset-0 z-50 lg:relative lg:inset-auto overflow-y-auto overscroll-contain touch-pan-y' : 'hidden'} lg:flex flex-1 flex-col bg-slate-900 lg:overflow-y-auto h-full`}
                        >
                            {/* Mobile Back Button */}
                            {selectedRequest && (
                                <div className="lg:hidden p-3 border-b border-white/10 flex items-center">
                                    <button
                                        onClick={() => setSelectedRequest(null)}
                                        className="flex items-center gap-2 text-white/70 hover:text-white"
                                    >
                                        <ChevronLeft className="w-5 h-5" aria-hidden="true" />
                                        <span>Back to List</span>
                                    </button>
                                </div>
                            )}
                            {selectedRequest ? (
                                <div className="flex-1 flex flex-col">
                                    {/* Sticky Header with Actions & Assignment - Premium Glass Style */}
                                    <div className="sticky top-0 z-10 bg-gradient-to-b from-slate-900/95 via-slate-800/95 to-slate-800/90 backdrop-blur-md border-b border-white/10 p-3 sm:p-4 space-y-2 sm:space-y-3">
                                        {/* Row 1: Title, ID, Status and Print */}
                                        <div className="flex items-start justify-between gap-2">
                                            <div className="min-w-0 flex-1">
                                                <div className="flex items-center gap-1.5 sm:gap-2 mb-0.5 sm:mb-1 flex-wrap">
                                                    <span className="font-mono text-[10px] sm:text-xs text-white/50 bg-white/5 px-1.5 sm:px-2 py-0.5 rounded">{selectedRequest.service_request_id}</span>
                                                    <StatusBadge status={selectedRequest.status} />
                                                    {(selectedRequest as any).is_public === false &&(
                                                        /* The explanation was `title`-only, so
                                                            keyboard and touch users saw the word
                                                            "Unlisted" and had no way to find out
                                                            what it obliged them to do (1.4.13).
                                                            The full sentence is now in the
                                                            accessible name, and repeated visibly
                                                            below the header for everyone. */
                                                        <span className="inline-flex items-center gap-1 text-[11px] sm:text-xs font-medium px-1.5 sm:px-2 py-0.5 rounded bg-slate-500/20 text-slate-200 border border-slate-400/30">
                                                            <EyeOff className="w-3 h-3" aria-hidden="true" />
                                                            Unlisted
                                                            <span className="sr-only">
                                                                — the resident asked to keep this off the public map and feed. Work it normally, just don't share it publicly.
                                                            </span>
                                                        </span>
                                                    )}
                                                </div>
                                                {/* h2, not h1: the page has exactly one h1
                                                    (the view name at the top of <main>), and
                                                    this one used to come *after* the list's
                                                    h2 and its rows, so the outline went
                                                    h2 then h3 then h1 (WCAG 1.3.1). A tabIndex of -1
                                                    makes it the landing point when a request
                                                    is opened, so a screen reader announces
                                                    the request that just opened instead of
                                                    saying nothing at all. */}
                                                <h2
                                                    ref={detailHeadingRef}
                                                    tabIndex={-1}
                                                    className="text-base sm:text-lg font-semibold text-white truncate focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 rounded"
                                                >
                                                    {selectedRequest.service_name}
                                                    <span className="sr-only">, request {selectedRequest.service_request_id}</span>
                                                </h2>
                                            </div>
                                            <div className="flex items-center gap-1.5 shrink-0">
                                                {/* Only when there is a work order to refresh. Without a
                                                    link this button's own endpoint answers "This request
                                                    isn't linked to any external platform" -- so on a town
                                                    with no integrations it was a control that existed
                                                    solely to report that it does nothing. */}
                                                {(selectedRequest.external_links?.length ?? 0) > 0 && (
                                                <button
                                                    onClick={handleRefreshWorkOrder}
                                                    disabled={woRefresh.busy}
                                                    title={`Pull the latest work-order status (assignment, schedule, resolution) from ${selectedRequest.external_links!.join(', ')}`}
                                                    className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-white/70 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 transition-colors disabled:opacity-50"
                                                >
                                                    <RefreshCw className={`w-3.5 h-3.5 ${woRefresh.busy ? 'animate-spin' : ''}`} aria-hidden="true" />
                                                    <span className="hidden sm:inline">{woRefresh.busy ? 'Refreshing…' : 'Refresh work order'}</span>
                                                </button>
                                                )}
                                                <PrintWorkOrder
                                                    request={selectedRequest}
                                                    auditLog={auditLog}
                                                    comments={comments}
                                                    townshipName={settings?.township_name}
                                                    logoUrl={settings?.logo_url || undefined}
                                                    config={mapConfig}
                                                />
                                            </div>
                                        </div>
                                        {woRefresh.msg && (
                                            <div className="mt-1.5 text-[11px] text-white/60 bg-white/5 border border-white/10 rounded-lg px-2.5 py-1.5">
                                                {woRefresh.msg}
                                            </div>
                                        )}

                                        {/* The external record ids, so this report can be
                                            reconciled against the other system without
                                            needing a login to it. */}
                                        {/* Why an integration failed, in text — WCAG 1.4.13.
                                            The failure reason lived ONLY in a `title` on a
                                            non-focusable <span>. A `title` is revealed by
                                            hovering a mouse and by nothing else: keyboard
                                            users never trigger it, touch users never
                                            trigger it, and it cannot be dismissed or
                                            hovered without disappearing. So "this report
                                            failed to reach Accela, and here is why" was
                                            information available to exactly one input
                                            method. It is now a visible line under the chip,
                                            and the direction ("Sent to" / "Originated in")
                                            is spelled out rather than implied by a
                                            tooltip nobody sees. */}
                                        {externalRecords.length > 0 && (
                                            <ul className="mt-1.5 flex flex-wrap gap-1.5 list-none p-0 m-0">
                                                {externalRecords.map(link => (
                                                    <li
                                                        key={`${link.platform}:${link.external_id}`}
                                                        className={`rounded-lg px-2 py-1 text-[11px] border ${link.sync_error
                                                            ? 'bg-amber-500/10 text-amber-100 border-amber-500/30'
                                                            : 'bg-white/5 text-white/70 border-white/10'}`}
                                                    >
                                                        <span className="inline-flex items-center gap-1.5 flex-wrap">
                                                            {link.sync_error && <AlertCircle className="w-3 h-3 shrink-0" aria-hidden="true" />}
                                                            <span className="text-white/60">
                                                                {link.direction === 'pulled' ? 'Originated in' : 'Sent to'} {link.platform_name}
                                                            </span>
                                                            <span className="font-mono">{link.external_id}</span>
                                                            {link.external_status && (
                                                                <span className="text-white/60">· {link.external_status}</span>
                                                            )}
                                                        </span>
                                                        {link.sync_error && (
                                                            <span className="block mt-0.5 text-amber-100 break-words">
                                                                Last sync problem: {link.sync_error}
                                                            </span>
                                                        )}
                                                    </li>
                                                ))}
                                            </ul>
                                        )}

                                        {/* Row 2: Status Actions - Compact on mobile */}
                                        {/* Which status the request is in was carried
                                            entirely by which of the three buttons had a
                                            gradient fill and a ring — WCAG 1.4.1 and
                                            4.1.2: with colour removed all three read as
                                            "Open / In Progress / Closed, button", with no
                                            hint that one of them describes the current
                                            state. aria-pressed makes the current one
                                            announce as pressed. */}
                                        <div className="flex gap-1.5 sm:gap-2" role="group" aria-label="Set request status">
                                            <button type="button" aria-pressed={selectedRequest.status === 'open'} onClick={() => handleStatusChange('open')} className={`flex-1 py-1.5 sm:py-2 px-2 sm:px-3 rounded-lg text-xs sm:text-sm font-medium transition-all ${selectedRequest.status === 'open' ? 'bg-gradient-to-r from-purple-500 to-violet-600 text-white shadow-lg shadow-purple-500/30 ring-2 ring-white/20' : 'bg-white/5 border border-white/10 text-white/70 hover:bg-white/10 hover:text-white'}`}>Open</button>
                                            <button type="button" aria-pressed={selectedRequest.status === 'in_progress'} onClick={() => handleStatusChange('in_progress')} className={`flex-1 py-1.5 sm:py-2 px-2 sm:px-3 rounded-lg text-xs sm:text-sm font-medium transition-all ${selectedRequest.status === 'in_progress' ? 'bg-gradient-to-r from-blue-500 to-indigo-600 text-white shadow-lg shadow-blue-500/30 ring-2 ring-white/20' : 'bg-white/5 border border-white/10 text-white/70 hover:bg-white/10 hover:text-white'}`}>In Progress</button>
                                            <button type="button" aria-pressed={selectedRequest.status === 'closed'} onClick={() => handleStatusChange('closed')} className={`flex-1 py-1.5 sm:py-2 px-2 sm:px-3 rounded-lg text-xs sm:text-sm font-medium transition-all ${selectedRequest.status === 'closed' ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-500/30 ring-2 ring-white/20' : 'bg-white/5 border border-white/10 text-white/70 hover:bg-white/10 hover:text-white'}`}>Closed</button>
                                        </div>

                                        {/* Row 3: Assignment Dropdowns - More compact on mobile */}
                                        <div className="flex flex-wrap items-center gap-1.5 sm:gap-2">
                                            <select
                                                value={editAssignment?.departmentId ?? selectedRequest.assigned_department_id ?? ''}
                                                onChange={(e) => { const val = e.target.value ? Number(e.target.value) : null; setEditAssignment(prev => ({ departmentId: val, assignedTo: prev?.assignedTo ?? selectedRequest.assigned_to ?? null })); }}
                                                className="flex-1 min-w-0 py-1.5 sm:py-2 px-2 sm:px-3 rounded-lg bg-white/5 border border-white/10 text-white text-xs sm:text-sm focus:border-primary-500/50 focus:ring-1 focus:ring-primary-500/25 transition-all [&>option]:bg-slate-800 [&>option]:text-white"
                                                aria-label="Assign to department"
                                            >
                                                <option value="" className="text-white/50">Department...</option>
                                                {departments.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
                                            </select>
                                            <select
                                                value={editAssignment?.assignedTo ?? selectedRequest.assigned_to ?? ''}
                                                onChange={(e) => { const val = e.target.value; setEditAssignment(prev => ({ departmentId: prev?.departmentId ?? selectedRequest.assigned_department_id ?? null, assignedTo: val })); }}
                                                className="flex-1 min-w-0 py-1.5 sm:py-2 px-2 sm:px-3 rounded-lg bg-white/5 border border-white/10 text-white text-xs sm:text-sm focus:border-primary-500/50 focus:ring-1 focus:ring-primary-500/25 transition-all [&>option]:bg-slate-800 [&>option]:text-white"
                                                aria-label="Assign to staff member"
                                            >
                                                <option value="">Assignee...</option>
                                                {(() => {
                                                    const deptId = editAssignment?.departmentId ?? selectedRequest.assigned_department_id;
                                                    const filteredUsers = deptId ? users.filter(u => u.departments?.some(d => d.id === deptId)) : users;
                                                    return filteredUsers.map(u => (
                                                        <option key={u.id} value={u.username}>
                                                            {u.full_name || u.username}
                                                        </option>
                                                    ));
                                                })()}
                                            </select>
                                            {editAssignment && (
                                                <button onClick={async () => {
                                                    setIsSavingAssignment(true);
                                                    try {
                                                        const updated = await api.updateRequest(selectedRequest.service_request_id, {
                                                            assigned_department_id: editAssignment.departmentId ?? undefined,
                                                            assigned_to: editAssignment.assignedTo === null ? '' : editAssignment.assignedTo
                                                        });
                                                        setSelectedRequest(updated);
                                                        // Optimistic update: update the request in both lists
                                                        setAllRequests(prev => prev.map(r => r.id === updated.id ? updated : r));
                                                        setRequests(prev => prev.map(r => r.id === updated.id ? updated : r));
                                                        setEditAssignment(null);
                                                        loadAuditLog(selectedRequest.service_request_id);
                                                        // The Save button simply vanishes on
                                                        // success, which is indistinguishable
                                                        // from a failure that also cleared it.
                                                        announce(updated.assigned_to
                                                            ? `Assignment saved. Assigned to ${updated.assigned_to}.`
                                                            : 'Assignment saved.');
                                                    } catch (err) {
                                                        console.error(err);
                                                        announce('Could not save the assignment. Please try again.', 'assertive');
                                                    } finally {
                                                        setIsSavingAssignment(false);
                                                    }
                                                }} disabled={isSavingAssignment} className="px-3 sm:px-4 py-1.5 sm:py-2 rounded-lg bg-primary-600 hover:bg-primary-700 text-white text-xs sm:text-sm font-medium disabled:opacity-50 transition-all shadow-lg shadow-primary-500/20">{isSavingAssignment ? '...' : 'Save'}</button>
                                            )}
                                        </div>

                                        {/* Row 4: Legal Hold Toggle (Admin Only) - Hidden on mobile, shown in menu */}
                                        {user?.role === 'admin' && (
                                            <button
                                                onClick={async () => {
                                                    if (selectedRequest.flagged !== true) {
                                                        // Show confirmation before placing on legal hold
                                                        if (window.confirm('Place this request under Legal Hold?\n\nThis will prevent the record from being archived or deleted by the retention policy.\n\nContinue?')) {
                                                            try {
                                                                const updated = await api.updateRequest(selectedRequest.service_request_id, {
                                                                    flagged: true
                                                                });
                                                                setSelectedRequest(updated);
                                                                setRequests(prev => prev.map(r => r.id === updated.id ? updated : r));
                                                                announce('Legal hold placed. This record is now exempt from the retention policy.');
                                                            } catch (err) {
                                                                console.error('Failed to enable legal hold:', err);
                                                                announce('Could not place the legal hold. Please try again.', 'assertive');
                                                            }
                                                        }
                                                    } else {
                                                        // Allow direct removal without confirmation
                                                        try {
                                                            const updated = await api.updateRequest(selectedRequest.service_request_id, {
                                                                flagged: false
                                                            });
                                                            setSelectedRequest(updated);
                                                            setRequests(prev => prev.map(r => r.id === updated.id ? updated : r));
                                                            announce('Legal hold removed.');
                                                        } catch (err) {
                                                            console.error('Failed to remove legal hold:', err);
                                                            announce('Could not remove the legal hold. Please try again.', 'assertive');
                                                        }
                                                    }
                                                }}
                                                className={`w-full py-1.5 sm:py-2 px-3 sm:px-4 rounded-lg text-xs sm:text-sm font-medium transition-all flex items-center justify-center gap-1.5 sm:gap-2 ${selectedRequest.flagged === true
                                                    ? 'bg-gradient-to-r from-amber-500 to-orange-600 text-white shadow-lg shadow-amber-500/30 ring-2 ring-white/20'
                                                    : 'bg-white/5 border border-white/10 text-white/70 hover:bg-amber-500/20 hover:text-amber-400 hover:border-amber-500/30'
                                                    }`}
                                                type="button"
                                                aria-pressed={selectedRequest.flagged === true}
                                                aria-label={selectedRequest.flagged === true ? 'Remove legal hold' : 'Place on legal hold'}
                                            >
                                                <FlagTriangleRight className="w-3.5 h-3.5 sm:w-4 sm:h-4" aria-hidden="true" />
                                                <span className="hidden sm:inline">{selectedRequest.flagged === true ? 'Under Legal Hold (Click to Remove)' : 'Place on Legal Hold'}</span>
                                                <span className="sm:hidden">{selectedRequest.flagged === true ? 'Legal Hold ✓' : 'Legal Hold'}</span>
                                            </button>
                                        )}

                                        {/* Row 5: Archive from public view. Any staff member --
                                            deciding the map does not need last spring's resolved
                                            potholes on it is routine clerk work, not the
                                            legal-hold kind of decision. Nothing is deleted. */}
                                        {/* Confirmed before it fires — WCAG 3.3.4.
                                            This was the one destructive control on the
                                            panel that acted on a single click: Delete,
                                            Close and Legal Hold all confirm, while
                                            "Archive from Public View" removed a report
                                            from the public tracker and the map instantly,
                                            with no dialog and no announcement. It is the
                                            easiest button on the surface to hit by
                                            accident — it sits directly under the legal
                                            hold toggle, full-width — and a resident
                                            watching their own report simply saw it
                                            disappear. Restoring is not confirmed: putting
                                            a report back is not the risky direction. */}
                                        <button
                                            type="button"
                                            aria-pressed={selectedRequest.public_archived === true}
                                            onClick={async () => {
                                                const nowArchived = selectedRequest.public_archived !== true;
                                                if (nowArchived && !window.confirm(
                                                    'Archive this report from public view?\n\n' +
                                                    'It will be removed from the public tracker and the public map straight away. ' +
                                                    'Nothing is deleted — residents holding the link can still see it, and it stays in research exports.\n\n' +
                                                    'Continue?'
                                                )) return;
                                                try {
                                                    const updated = await api.setPublicArchived(
                                                        selectedRequest.service_request_id, nowArchived);
                                                    setSelectedRequest(updated);
                                                    setRequests(prev => prev.map(r => r.id === updated.id ? updated : r));
                                                    loadAuditLog(selectedRequest.service_request_id);
                                                    announce(nowArchived
                                                        ? 'Archived from public view. The report is off the public tracker and map.'
                                                        : 'Restored to public view.');
                                                } catch (err) {
                                                    console.error('Failed to change public visibility:', err);
                                                    announce('Could not change the public visibility. Please try again.', 'assertive');
                                                }
                                            }}
                                            className={`w-full py-1.5 sm:py-2 px-3 sm:px-4 rounded-lg text-xs sm:text-sm font-medium transition-all flex items-center justify-center gap-1.5 sm:gap-2 ${selectedRequest.public_archived === true
                                                ? 'bg-gradient-to-r from-slate-500 to-slate-600 text-white shadow-lg shadow-slate-500/30 ring-2 ring-white/20'
                                                : 'bg-white/5 border border-white/10 text-white/70 hover:bg-slate-500/20 hover:text-slate-200 hover:border-slate-500/30'
                                                }`}
                                            title="Archive from public view \u2014 the report stays, residents with the link still see it"
                                            aria-label={selectedRequest.public_archived === true
                                                ? 'Put this report back on the public tracker and map'
                                                : 'Archive from public view \u2014 the report stays, residents with the link still see it'}
                                        >
                                            <EyeOff className="w-3.5 h-3.5 sm:w-4 sm:h-4" aria-hidden="true" />
                                            <span className="hidden sm:inline">{selectedRequest.public_archived === true
                                                ? 'Archived from Public View (Click to Restore)'
                                                : 'Archive from Public View'}</span>
                                            <span className="sm:hidden">{selectedRequest.public_archived === true ? 'Archived \u2713' : 'Archive'}</span>
                                        </button>

                                        {selectedRequest.public_archived === true && (
                                            <p className="text-[11px] text-white/40 text-center">
                                                Off the public tracker and map. The report stays &mdash; residents with the link still see it, and it is still in research exports.
                                            </p>
                                        )}
                                    </div>

                                    {/* Scrollable Content - Professional Government Styling */}
                                    <div className="flex-1 overflow-auto p-4 space-y-4">

                                        {/* ═══ SECTION 1: Request Details (Description + AI + Photos) ═══ */}
                                        <div className="p-4 rounded-lg bg-slate-800/50 border border-white/10">
                                            <p className="text-white/90 leading-relaxed mb-4">{selectedRequest.description}</p>

                                            {/* Custom Fields / Additional Information - Right below description */}
                                            {selectedRequest.custom_fields && Object.keys(selectedRequest.custom_fields).length > 0 && (
                                                <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 mb-4">
                                                    <p className="text-amber-400 font-medium text-sm mb-2 flex items-center gap-2">
                                                        <FileText className="w-4 h-4" aria-hidden="true" />
                                                        Additional Information
                                                    </p>
                                                    <div className="grid grid-cols-2 gap-2 text-sm">
                                                        {Object.entries(selectedRequest.custom_fields).map(([key, value]) => (
                                                            <div key={key} className="flex flex-col">
                                                                <span className="text-white/40 text-xs capitalize">{key.replace(/_/g, ' ')}</span>
                                                                <span className="text-white/80">{Array.isArray(value) ? value.join(', ') : String(value)}</span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}

                                            {/* Photos - Now ABOVE AI Analysis */}
                                            {/* Each thumbnail was a bare `<img onClick>` —
                                                not focusable, no role, no key handler — so a
                                                keyboard user could not open a single piece
                                                of evidence on any report (WCAG 2.1.1/4.1.2).
                                                Wrapping in a real <button> gets Enter, Space,
                                                the tab order and a name for free. The strip
                                                wraps rather than scrolling horizontally: a
                                                row of photos is not tabular data, and a
                                                horizontal scroller is a second axis of
                                                scrolling at 320px (WCAG 1.4.10). */}
                                            {selectedRequest.media_urls && selectedRequest.media_urls.length > 0 && (
                                                <div className="flex flex-wrap gap-2 pb-2 mb-4">
                                                    {selectedRequest.media_urls.map((url, i) => (
                                                        <button
                                                            key={i}
                                                            type="button"
                                                            onClick={() => setLightboxUrl(url)}
                                                            aria-label={`Open photo ${i + 1} of ${selectedRequest.media_urls!.length} full size`}
                                                            className="rounded-lg overflow-hidden ring-1 ring-white/10 hover:opacity-80 transition-opacity focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-800 p-0"
                                                        >
                                                            <img src={url} alt="" className="w-28 h-20 object-cover block" />
                                                        </button>
                                                    ))}
                                                </div>
                                            )}

                                            {/* Photos the automatic blur could not clear. They are
                                                held out of media_urls entirely, so nothing public
                                                can render one -- this panel is the only place they
                                                appear and the only way one ever becomes public. */}
                                            {!!selectedRequest.media_pending_review?.length && (
                                                <div className="mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/30">
                                                    <p className="text-sm text-amber-200 font-medium mb-1">
                                                        {selectedRequest.media_pending_review.length === 1
                                                            ? '1 photo needs your review'
                                                            : `${selectedRequest.media_pending_review.length} photos need your review`}
                                                    </p>
                                                    <p className="text-xs text-amber-200/70 mb-3">
                                                        The automatic face and licence-plate blur could not run on
                                                        these, so they have been kept off the public tracker, the map
                                                        and the Open311 feed. Check for faces and plates before
                                                        releasing one.
                                                    </p>
                                                    <div className="flex gap-3 flex-wrap">
                                                        {selectedRequest.media_pending_review.map((photo, i) => (
                                                            <div key={i} className="space-y-1">
                                                                <img
                                                                    src={photo.media}
                                                                    alt={`Photo awaiting review ${i + 1}`}
                                                                    className="w-28 h-20 object-cover rounded-lg cursor-pointer ring-1 ring-amber-400/40"
                                                                    onClick={() => setLightboxUrl(photo.media)}
                                                                />
                                                                <div className="flex gap-1">
                                                                    <button
                                                                        type="button"
                                                                        className="px-2 py-1 text-xs rounded bg-emerald-600/80 hover:bg-emerald-600 text-white"
                                                                        onClick={async () => setSelectedRequest(
                                                                            await api.reviewWithheldPhoto(
                                                                                selectedRequest.service_request_id, i, true))}
                                                                    >
                                                                        Publish
                                                                    </button>
                                                                    <button
                                                                        type="button"
                                                                        className="px-2 py-1 text-xs rounded bg-white/10 hover:bg-white/20 text-white/80"
                                                                        onClick={async () => setSelectedRequest(
                                                                            await api.reviewWithheldPhoto(
                                                                                selectedRequest.service_request_id, i, false))}
                                                                    >
                                                                        Discard
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}

                                            {/* AI Analysis - Premium Enhanced Display (Now BELOW Photos) */}
                                            {(() => {
                                                const ai = selectedRequest.ai_analysis as any;
                                                const priorityScore = ai?.priority_score ?? null;
                                                const qualitativeText = ai?.qualitative_analysis ?? selectedRequest.ai_summary ?? null;
                                                const hasError = ai?._error;

                                                // Computed (non-AI) triage facts — populated for every request
                                                // regardless of whether AI ran.
                                                const ctx = ai?.context ?? null;
                                                const aiRan = !!(qualitativeText || priorityScore != null);
                                                const contextChips: string[] = [];
                                                if (ctx) {
                                                    if (ctx.nearby_similar) contextChips.push(`${ctx.nearby_similar} similar nearby`);
                                                    if (ctx.recurrence_count) contextChips.push(`${ctx.recurrence_count} prior at this address`);
                                                    if (ctx.nearby_outages) contextChips.push(`${ctx.nearby_outages} nearby outages`);
                                                    if (ctx.is_school_zone) contextChips.push('School zone');
                                                    if (Array.isArray(ctx.critical_infrastructure) && ctx.critical_infrastructure.length) contextChips.push(`Near ${ctx.critical_infrastructure.slice(0, 2).join(', ')}`);
                                                    if (ctx.weather_at_report) contextChips.push(`Weather: ${ctx.weather_at_report}`);
                                                }
                                                const similarCount = ctx?.similar_reports?.length ?? ai?.similar_reports?.length ?? 0;

                                                if (!qualitativeText && priorityScore == null && contextChips.length === 0 && !similarCount) return null;

                                                return(
                                                    /* The onClick that used to sit on this
                                                        wrapper made the whole card a control
                                                        that contained another control — nested
                                                        interactive content, which is invalid and
                                                        leaves assistive tech unable to say what
                                                        is activated by what. It was also
                                                        keyboard-dead (a div with no role and no
                                                        key handler), so it added a mouse-only
                                                        way to expand and nothing else: the
                                                        toggle button inside already does the job
                                                        for every input method. */
                                                    <div className="relative overflow-hidden rounded-xl bg-slate-800/40 border border-white/10 mb-4 backdrop-blur-sm">
                                                        {/* Professional accent line */}
                                                        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-primary-500/50 via-purple-500/50 to-primary-500/50" />

                                                        <div className="p-4">
                                                            {/* Simple Header - Just label and expand toggle */}
                                                            <button
                                                                type="button"
                                                                onClick={() => setIsAIExpanded(!isAIExpanded)}
                                                                aria-expanded={isAIExpanded}
                                                                /* Only while the details are mounted; collapsed, the
                                                                   id does not exist and the reference dangles. */
                                                                aria-controls={isAIExpanded ? 'ai-analysis-details' : undefined}
                                                                className="w-full flex items-center justify-between mb-3 rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                                                            >
                                                                <div className="flex items-center gap-3">
                                                                    <div className="p-2 rounded-xl bg-gradient-to-br from-primary-500/20 to-purple-500/20 ring-1 ring-white/10">
                                                                        <Brain className="w-5 h-5 text-primary-400" aria-hidden="true" />
                                                                    </div>
                                                                    <div className="text-left">
                                                                        <span className="text-sm font-semibold text-white">{aiRan ? 'AI Analysis' : 'Triage Context'}</span>
                                                                        <p className="text-[10px] text-white/40">{aiRan ? 'AI-assisted summary' : 'Computed from town records'}</p>
                                                                    </div>
                                                                </div>
                                                                <ChevronDown className={`w-5 h-5 text-white/40 transition-transform ${isAIExpanded ? 'rotate-180' : ''}`} aria-hidden="true" />
                                                            </button>

                                                            {/* Computed triage facts — shown whether or not AI ran */}
                                                            {contextChips.length > 0 && (
                                                                <div className="flex flex-wrap gap-1.5 mb-3">
                                                                    {contextChips.map((c, i) => (
                                                                        <span key={i} className="inline-flex items-center rounded-md bg-white/[0.05] border border-white/10 px-2 py-0.5 text-[11px] text-white/70">{c}</span>
                                                                    ))}
                                                                </div>
                                                            )}
                                                            {!aiRan && !hasError && (
                                                                <p className="text-xs text-white/50 mb-3">
                                                                    AI summary is off or not configured — these facts are computed directly from your town's records.
                                                                </p>
                                                            )}

                                                            {/* Translation block for non-English submissions */}
                                                            {ai?.translation && ai.translation.detected_language && ai.translation.detected_language !== 'English' && ai.translation.english_translation && (
                                                                <div className="mb-4 p-3 rounded-xl bg-blue-500/10 border border-blue-500/20">
                                                                    <p className="text-xs font-bold text-blue-400 uppercase tracking-wider mb-2">
                                                                        🌐 Translation ({ai.translation.detected_language})
                                                                    </p>
                                                                    {/* WCAG 3.1.2: without `lang` the browser
                                                                        and the screen reader both treat this as
                                                                        English and pronounce it with English
                                                                        rules — Spanish or Vietnamese read aloud
                                                                        that way is not accented, it is
                                                                        unintelligible. The detected language was
                                                                        already in scope; it just never reached
                                                                        the markup. */}
                                                                    <p lang={languageTag(ai.translation.detected_language)} className="text-xs text-white/40 italic mb-1">"{ai.translation.original_text}"</p>
                                                                    <p className="text-sm text-white/80">"{ai.translation.english_translation}"</p>
                                                                </div>
                                                            )}

                                                            {/* Summary Text - Always visible */}
                                                            {qualitativeText && !hasError && (
                                                                <p className={`text-sm text-white/70 leading-relaxed mb-4 ${!isAIExpanded ? 'line-clamp-2' : ''}`}>
                                                                    {qualitativeText}
                                                                </p>
                                                            )}

                                                            {/* Priority Actions - Large, Easy to Tap Buttons */}
                                                            {(priorityScore || selectedRequest.manual_priority_score) && !hasError && (
                                                                <div className="space-y-4">
                                                                    {/* Priority Display */}
                                                                    <div className={`flex items-center justify-between p-3 rounded-xl ${(selectedRequest.manual_priority_score ?? priorityScore) >= 8 ? 'bg-red-500/10 border border-red-500/20' :
                                                                        (selectedRequest.manual_priority_score ?? priorityScore) >= 6 ? 'bg-amber-500/10 border border-amber-500/20' :
                                                                            (selectedRequest.manual_priority_score ?? priorityScore) >= 4 ? 'bg-blue-500/10 border border-blue-500/20' :
                                                                                'bg-green-500/10 border border-green-500/20'
                                                                        }`}>
                                                                        <div>
                                                                            <p className="text-xs text-white/50 mb-0.5">
                                                                                {selectedRequest.manual_priority_score ? 'Confirmed Priority' : 'AI Suggested Priority'}
                                                                            </p>
                                                                            <p className={`text-2xl font-bold ${(selectedRequest.manual_priority_score ?? priorityScore) >= 8 ? 'text-red-400' :
                                                                                (selectedRequest.manual_priority_score ?? priorityScore) >= 6 ? 'text-amber-400' :
                                                                                    (selectedRequest.manual_priority_score ?? priorityScore) >= 4 ? 'text-blue-400' :
                                                                                        'text-green-400'
                                                                                }`}>
                                                                                {Number(selectedRequest.manual_priority_score ?? priorityScore).toFixed(1)}
                                                                                <span className="text-sm font-normal opacity-50"> / 10</span>
                                                                            </p>
                                                                        </div>
                                                                        {selectedRequest.manual_priority_score && (
                                                                            <div className="flex items-center gap-1 text-emerald-400">
                                                                                <Check className="w-5 h-5" aria-hidden="true" />
                                                                                <span className="text-xs font-medium">Confirmed</span>
                                                                            </div>
                                                                        )}
                                                                    </div>

                                                                    {/* Action Buttons - Full Width, Easy to Tap */}
                                                                    {priorityScore && !selectedRequest.manual_priority_score && (
                                                                        <div className="flex gap-2 mt-3 mb-4">
                                                                            <button
                                                                                onClick={async () => {
                                                                                    setIsUpdatingPriority(true);
                                                                                    try {
                                                                                        await api.acceptAiPriority(selectedRequest.service_request_id);
                                                                                        setSelectedRequest(prev => prev ? { ...prev, manual_priority_score: priorityScore } : null);
                                                                                        setAllRequests(prev => prev.map(r =>
                                                                                            r.service_request_id === selectedRequest.service_request_id
                                                                                                ? { ...r, manual_priority_score: priorityScore }
                                                                                                : r
                                                                                        ));
                                                                                        announce(`AI priority accepted. Priority confirmed at ${priorityScore} out of 10.`);
                                                                                    } catch (e) {
                                                                                        console.error('Failed to accept AI priority:', e);
                                                                                        announce('Could not accept the AI priority. Please try again.', 'assertive');
                                                                                    } finally {
                                                                                        setIsUpdatingPriority(false);
                                                                                    }
                                                                                }}
                                                                                disabled={isUpdatingPriority}
                                                                                className="flex-1 py-3 px-4 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 font-semibold text-sm transition-all flex items-center justify-center gap-2 border border-emerald-500/30 active:scale-[0.98]"
                                                                            >
                                                                                <Check className="w-5 h-5" aria-hidden="true" />
                                                                                Accept AI Priority
                                                                            </button>
                                                                            <button
                                                                                onClick={() => {
                                                                                    setShowPriorityEditor(!showPriorityEditor);
                                                                                    setPendingPriority(selectedRequest.manual_priority_score ?? priorityScore ?? 5);
                                                                                }}
                                                                                className="py-3 px-4 rounded-xl bg-white/5 hover:bg-white/10 text-white/70 font-medium text-sm transition-all flex items-center justify-center gap-2 border border-white/10 active:scale-[0.98]"
                                                                            >
                                                                                <Edit3 className="w-4 h-4" aria-hidden="true" />
                                                                                Edit
                                                                            </button>
                                                                        </div>
                                                                    )}

                                                                    {/* Edit button when already confirmed */}
                                                                    {selectedRequest.manual_priority_score && (
                                                                        <button
                                                                            onClick={() => {
                                                                                setShowPriorityEditor(!showPriorityEditor);
                                                                                setPendingPriority(selectedRequest.manual_priority_score ?? priorityScore ?? 5);
                                                                            }}
                                                                            className="w-full py-2.5 px-4 rounded-xl bg-white/5 hover:bg-white/10 text-white/60 font-medium text-sm transition-all flex items-center justify-center gap-2 border border-white/10"
                                                                        >
                                                                            <Edit3 className="w-4 h-4" aria-hidden="true" />
                                                                            Change Priority
                                                                        </button>
                                                                    )}

                                                                    {/* Priority Editor - Full Width Inline */}
                                                                    {showPriorityEditor && (
                                                                        <div className="p-4 rounded-xl bg-slate-800/80 border border-white/10 space-y-4 max-w-md">
                                                                            <p className="text-sm text-white/70 font-medium" id="priority-grid-label">Set Priority Level</p>
                                                                            {/* The chosen number was distinguished only by fill
                                                                                colour and a ring (WCAG 1.4.1), and the ten buttons
                                                                                had no shared name, so each announced as a bare
                                                                                digit with no indication of what it set. */}
                                                                            <div className="grid grid-cols-5 gap-2" role="group" aria-labelledby="priority-grid-label">
                                                                                {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(p => (
                                                                                    <button
                                                                                        key={p}
                                                                                        type="button"
                                                                                        aria-pressed={pendingPriority === p}
                                                                                        onClick={() => setPendingPriority(p)}
                                                                                        className={`aspect-square md:aspect-auto md:h-10 rounded-xl text-sm md:text-base font-bold transition-all active:scale-95 ${pendingPriority === p
                                                                                            ? 'bg-primary-500 text-white ring-2 ring-primary-400 ring-offset-2 ring-offset-slate-800'
                                                                                            : p >= 8 ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30'
                                                                                                : p >= 6 ? 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30'
                                                                                                    : p >= 4 ? 'bg-blue-500/20 text-blue-400 hover:bg-blue-500/30'
                                                                                                        : 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                                                                                            }`}
                                                                                    >
                                                                                        {p}
                                                                                    </button>
                                                                                ))}
                                                                            </div>
                                                                            <div className="flex gap-2">
                                                                                <button
                                                                                    onClick={async () => {
                                                                                        if (!pendingPriority) return;
                                                                                        setIsUpdatingPriority(true);
                                                                                        try {
                                                                                            await api.updateRequest(
                                                                                                selectedRequest.service_request_id,
                                                                                                { manual_priority_score: pendingPriority }
                                                                                            );
                                                                                            setSelectedRequest(prev => prev ? { ...prev, manual_priority_score: pendingPriority } : null);
                                                                                            setAllRequests(prev => prev.map(r =>
                                                                                                r.service_request_id === selectedRequest.service_request_id
                                                                                                    ? { ...r, manual_priority_score: pendingPriority }
                                                                                                    : r
                                                                                            ));
                                                                                            setShowPriorityEditor(false);
                                                                                            announce(`Priority saved as ${pendingPriority} out of 10.`);
                                                                                        } catch (e) {
                                                                                            console.error('Failed to update priority:', e);
                                                                                            announce('Could not save the priority. Please try again.', 'assertive');
                                                                                        } finally {
                                                                                            setIsUpdatingPriority(false);
                                                                                        }
                                                                                    }}
                                                                                    disabled={isUpdatingPriority}
                                                                                    className="flex-1 py-3 rounded-xl bg-primary-500 hover:bg-primary-600 text-white font-semibold text-sm disabled:opacity-50 transition-all"
                                                                                >
                                                                                    {isUpdatingPriority ? 'Saving...' : 'Save Priority'}
                                                                                </button>
                                                                                <button
                                                                                    onClick={() => setShowPriorityEditor(false)}
                                                                                    className="py-3 px-5 rounded-xl bg-white/10 hover:bg-white/20 text-white/70 font-medium text-sm transition-all"
                                                                                >
                                                                                    Cancel
                                                                                </button>
                                                                            </div>
                                                                            {selectedRequest.manual_priority_score && (
                                                                                <button
                                                                                    onClick={async () => {
                                                                                        setIsUpdatingPriority(true);
                                                                                        try {
                                                                                            await api.updateRequest(
                                                                                                selectedRequest.service_request_id,
                                                                                                { manual_priority_score: null as any }
                                                                                            );
                                                                                            setSelectedRequest(prev => prev ? { ...prev, manual_priority_score: null } : null);
                                                                                            setAllRequests(prev => prev.map(r =>
                                                                                                r.service_request_id === selectedRequest.service_request_id
                                                                                                    ? { ...r, manual_priority_score: null }
                                                                                                    : r
                                                                                            ));
                                                                                            setShowPriorityEditor(false);
                                                                                            announce('Priority reset to the AI suggestion.');
                                                                                        } catch (e) {
                                                                                            console.error('Failed to clear priority:', e);
                                                                                            announce('Could not reset the priority. Please try again.', 'assertive');
                                                                                        } finally {
                                                                                            setIsUpdatingPriority(false);
                                                                                        }
                                                                                    }}
                                                                                    disabled={isUpdatingPriority}
                                                                                    className="w-full py-2 text-xs text-white/40 hover:text-white/60 transition-colors"
                                                                                >
                                                                                    Reset to AI Suggestion
                                                                                </button>
                                                                            )}
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            )}

                                                            {/* Collapsible AI Details */}
                                                            {isAIExpanded && (
                                                                <div id="ai-analysis-details">
                                                                    {/* Content Moderation Warning */}
                                                                    {ai?.content_flags && ai.content_flags.length > 0 && !ai.content_flags.includes('none') && (
                                                                        <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 flex items-start gap-2.5">
                                                                            <AlertTriangle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" aria-hidden="true" />
                                                                            <div>
                                                                                <p className="text-xs font-bold text-red-400 uppercase tracking-tight">Content Warning</p>
                                                                                <p className="text-xs text-red-300/80">AI detected: {ai.content_flags.join(', ').replace(/_/g, ' ')}</p>
                                                                            </div>
                                                                        </div>
                                                                    )}



                                                                    {/* Priority Justification Quote */}
                                                                    {ai?.priority_justification && !hasError && (
                                                                        <div className="relative pl-4 mt-6 mb-5 border-l-2 border-primary-500/20">
                                                                            <p className="text-white/40 text-xs italic leading-relaxed">"{ai.priority_justification}"</p>
                                                                        </div>
                                                                    )}

                                                                    {/* Photo Assessment - New Section */}
                                                                    {ai?.photo_assessment && !hasError && (
                                                                        <div className="mb-5 p-3 rounded-lg bg-white/5 border border-white/5 space-y-2.5">
                                                                            <div className="flex items-center gap-1.5 opacity-50">
                                                                                <Camera className="w-3.5 h-3.5" aria-hidden="true" />
                                                                                <span className="text-[10px] font-bold uppercase tracking-wider">Visual Triage Assessment</span>
                                                                            </div>
                                                                            <div className="grid grid-cols-1 gap-2">
                                                                                <div className="flex justify-between items-center text-xs">
                                                                                    <span className="text-white/40">Physical Scale</span>
                                                                                    <span className="text-white/80 font-medium">{ai.photo_assessment.physical_scale}</span>
                                                                                </div>
                                                                                <div className="flex justify-between items-center text-xs">
                                                                                    <span className="text-white/40">Blocking Severity</span>
                                                                                    <span className={`font-bold ${ai.photo_assessment.blocking_severity === 'full_block' ? 'text-red-400' :
                                                                                        ai.photo_assessment.blocking_severity === 'partial' ? 'text-amber-400' : 'text-green-400'
                                                                                        }`}>{ai.photo_assessment.blocking_severity?.replace('_', ' ').toUpperCase()}</span>
                                                                                </div>
                                                                            </div>
                                                                        </div>
                                                                    )}

                                                                    {/* Quantitative Metrics - Cleaned up Grid */}
                                                                    {ai?.quantitative_metrics && !hasError && (
                                                                        <div className="grid grid-cols-2 gap-2 mb-4">
                                                                            {ai.quantitative_metrics.estimated_severity && ai.quantitative_metrics.estimated_severity !== 'unknown' && (
                                                                                <div className="p-2.5 rounded-lg bg-white/5 border border-white/5">
                                                                                    <p className="text-[11px] uppercase tracking-wider text-white/70 mb-0.5">Severity</p>
                                                                                    <p className={`text-xs font-bold ${ai.quantitative_metrics.estimated_severity === 'critical' ? 'text-red-400' :
                                                                                        ai.quantitative_metrics.estimated_severity === 'high' ? 'text-amber-400' :
                                                                                            ai.quantitative_metrics.estimated_severity === 'medium' ? 'text-blue-400' : 'text-green-400'
                                                                                        }`}>{ai.quantitative_metrics.estimated_severity.toUpperCase()}</p>
                                                                                </div>
                                                                            )}
                                                                            {ai.quantitative_metrics.systemic_failure_probability !== undefined && (
                                                                                <div className="p-2.5 rounded-lg bg-white/5 border border-white/5">
                                                                                    <p className="text-[11px] uppercase tracking-wider text-white/70 mb-0.5">Systemic Risk</p>
                                                                                    <div className="flex items-center gap-1.5">
                                                                                        <p className={`text-xs font-bold ${ai.quantitative_metrics.systemic_failure_probability > 0.7 ? 'text-red-400' : 'text-primary-400'}`}>
                                                                                            {(ai.quantitative_metrics.systemic_failure_probability * 100).toFixed(0)}%
                                                                                        </p>
                                                                                        <Activity className={`w-3 h-3 ${ai.quantitative_metrics.systemic_failure_probability > 0.7 ? 'text-red-400' : 'text-primary-400'}`} aria-hidden="true" />
                                                                                    </div>
                                                                                </div>
                                                                            )}
                                                                        </div>
                                                                    )}

                                                                    {/* Diagnostic Context - New Section */}
                                                                    {ai?.diagnostic_context && !hasError && (
                                                                        <div className="mb-4 space-y-2">
                                                                            {ai.diagnostic_context.infrastructure_proximity && (
                                                                                <div className="px-3 py-2 rounded-lg bg-blue-500/5 border border-blue-500/10 flex items-start gap-2.5">
                                                                                    <Shield className="w-3.5 h-3.5 text-blue-400 mt-0.5 flex-shrink-0" aria-hidden="true" />
                                                                                    <div className="flex-1">
                                                                                        <p className="text-[11px] font-bold text-blue-300 uppercase tracking-tight">Infrastructure Proximity</p>
                                                                                        <p className="text-[11px] text-blue-200/70">
                                                                                            {typeof ai.diagnostic_context.infrastructure_proximity === 'object'
                                                                                                ? ai.diagnostic_context.infrastructure_proximity.details
                                                                                                : ai.diagnostic_context.infrastructure_proximity}
                                                                                        </p>
                                                                                        {ai.diagnostic_context.infrastructure_proximity?.evidence && (
                                                                                            <p className="mt-1 text-[11px] text-blue-200 font-medium italic">
                                                                                                Evidence: {ai.diagnostic_context.infrastructure_proximity.evidence}
                                                                                            </p>
                                                                                        )}
                                                                                    </div>
                                                                                </div>
                                                                            )}
                                                                            {ai.diagnostic_context.historical_trend && (
                                                                                <div className="px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/10 flex items-start gap-2.5">
                                                                                    <History className="w-3.5 h-3.5 text-amber-400 mt-0.5 flex-shrink-0" aria-hidden="true" />
                                                                                    <div className="flex-1">
                                                                                        <p className="text-[11px] font-bold text-amber-300 uppercase tracking-tight">Historical Trend</p>
                                                                                        <p className="text-[11px] text-amber-200/70">
                                                                                            {typeof ai.diagnostic_context.historical_trend === 'object'
                                                                                                ? ai.diagnostic_context.historical_trend.details
                                                                                                : ai.diagnostic_context.historical_trend}
                                                                                        </p>
                                                                                        {ai.diagnostic_context.historical_trend?.evidence && (
                                                                                            <p className="mt-1 text-[11px] text-amber-200 font-medium italic">
                                                                                                Evidence: {ai.diagnostic_context.historical_trend.evidence}
                                                                                            </p>
                                                                                        )}
                                                                                    </div>
                                                                                </div>
                                                                            )}
                                                                            {ai.diagnostic_context.weather_impact && ai.diagnostic_context.weather_impact !== 'None' && (
                                                                                <div className="px-3 py-2 rounded-lg bg-primary-500/5 border border-primary-500/10 flex items-start gap-2.5">
                                                                                    <Cloud className="w-3.5 h-3.5 text-primary-400 mt-0.5 flex-shrink-0" aria-hidden="true" />
                                                                                    <div className="flex-1">
                                                                                        <p className="text-[11px] font-bold text-primary-300 uppercase tracking-tight">Weather Criticality</p>
                                                                                        <p className="text-[11px] text-primary-200/70">
                                                                                            {typeof ai.diagnostic_context.weather_impact === 'object'
                                                                                                ? ai.diagnostic_context.weather_impact.details
                                                                                                : ai.diagnostic_context.weather_impact}
                                                                                        </p>
                                                                                        {ai.diagnostic_context.weather_impact?.evidence && (
                                                                                            <p className="mt-1 text-[11px] text-primary-200 font-medium italic">
                                                                                                Evidence: {ai.diagnostic_context.weather_impact.evidence}
                                                                                            </p>
                                                                                        )}
                                                                                    </div>
                                                                                </div>
                                                                            )}
                                                                        </div>
                                                                    )}

                                                                    {/* Similar Reports - Clickable Links */}
                                                                    {ai.similar_reports && ai.similar_reports.length > 0 && (
                                                                        <div className="mb-4 px-3 py-2 rounded-lg bg-purple-500/5 border border-purple-500/10 flex items-start gap-2.5">
                                                                            <Link2 className="w-3.5 h-3.5 text-purple-400 mt-0.5 flex-shrink-0" aria-hidden="true" />
                                                                            <div className="flex-1">
                                                                                <p className="text-[11px] font-bold text-purple-300 uppercase tracking-tight">Similar Reports</p>
                                                                                <div className="mt-1 space-y-1">
                                                                                    {ai.similar_reports.map((report: { id: string; description: string; similarity: number; justification?: string }) => (
                                                                                        <button
                                                                                            key={report.id}
                                                                                            onClick={() => {
                                                                                                window.location.hash = `detail/${report.id}`;
                                                                                                window.scrollTo({ top: 0, behavior: 'smooth' });
                                                                                            }}
                                                                                            title={report.justification || `${Math.round(report.similarity * 100)}% match`}
                                                                                            className="w-full text-left px-2 py-1.5 rounded bg-purple-500/10 hover:bg-purple-500/20 transition-colors group"
                                                                                        >
                                                                                            <div className="flex items-center justify-between gap-2">
                                                                                                <span className="text-[10px] text-purple-300 font-mono group-hover:text-purple-200">{report.id}</span>
                                                                                                <span className="text-[11px] text-purple-200">{Math.round(report.similarity * 100)}% match</span>
                                                                                            </div>
                                                                                            <p className="text-[11px] text-purple-100 mt-0.5 line-clamp-1">{report.description}</p>
                                                                                            {report.justification && (
                                                                                                <p className="text-[11px] text-purple-200 mt-0.5 italic">{report.justification}</p>
                                                                                            )}
                                                                                        </button>
                                                                                    ))}
                                                                                </div>
                                                                            </div>
                                                                        </div>
                                                                    )}

                                                                    {/* Safety Flags - Cleaned up Pills */}
                                                                    {ai?.safety_flags && Array.isArray(ai.safety_flags) && ai.safety_flags.length > 0 && (
                                                                        <div className="flex flex-wrap gap-1.5 mb-4">
                                                                            {ai.safety_flags.map((flag: string, i: number) => (
                                                                                <span key={i} className="inline-flex items-center px-2 py-1 rounded bg-red-500/10 text-red-400 text-[10px] font-bold ring-1 ring-red-500/20">
                                                                                    {flag.replace(/_/g, ' ').toUpperCase()}
                                                                                </span>
                                                                            ))}
                                                                        </div>
                                                                    )}

                                                                    {/* Footer with timestamp */}
                                                                    <div className="flex items-center justify-between pt-3 border-t border-white/5">
                                                                        {selectedRequest.ai_analyzed_at && (
                                                                            <p className="text-white/70 text-[11px]">
                                                                                Analyzed {new Date(selectedRequest.ai_analyzed_at).toLocaleString()}
                                                                            </p>
                                                                        )}
                                                                        {!hasError && (
                                                                            <div className="flex items-center gap-1.5">
                                                                                <div className="w-1.5 h-1.5 rounded-full bg-green-500/50 animate-pulse" />
                                                                                <p className="text-[11px] text-white/70 font-medium">
                                                                                    Visual + Spatial Context Integrated
                                                                                </p>
                                                                            </div>
                                                                        )}
                                                                    </div>
                                                                </div>
                                                            )}
                                                        </div>

                                                    </div>
                                                );
                                            })()}

                                            {/* Completion info */}
                                            {selectedRequest.status === 'closed' && (selectedRequest.completion_message || selectedRequest.completion_photo_url) && (
                                                <div className="p-3 rounded-lg bg-green-500/10 border border-green-500/20 mb-4">
                                                    <p className="text-green-400 font-medium text-sm mb-1">✓ {selectedRequest.closed_substatus === 'resolved' ? 'Resolved' : selectedRequest.closed_substatus === 'no_action' ? 'No Action Needed' : 'Referred'}</p>
                                                    {selectedRequest.completion_message && (
                                                        <p className="text-white/70 text-sm mb-2">{selectedRequest.completion_message}</p>
                                                    )}
                                                    {/* Same defect as the evidence thumbnails,
                                                        plus this one opened a new tab on click
                                                        with no warning. Routed through the same
                                                        in-page lightbox so it behaves like every
                                                        other photo on the panel and does not
                                                        move the user out of context. */}
                                                    {selectedRequest.completion_photo_url && (
                                                        <button
                                                            type="button"
                                                            onClick={() => setLightboxUrl(selectedRequest.completion_photo_url!)}
                                                            aria-label="Open the completion photo full size"
                                                            className="rounded-lg overflow-hidden hover:opacity-90 transition-opacity focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-800 p-0"
                                                        >
                                                            <img
                                                                src={selectedRequest.completion_photo_url}
                                                                alt=""
                                                                className="rounded-lg max-h-64 object-contain block"
                                                            />
                                                        </button>
                                                    )}
                                                </div>
                                            )}

                                            {/* Reporter Info - Simple inline */}
                                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-white/60 pt-3 border-t border-white/10">
                                                {(selectedRequest.first_name || selectedRequest.last_name) && (
                                                    <span className="flex items-center gap-1"><User className="w-3.5 h-3.5" aria-hidden="true" /> {selectedRequest.first_name} {selectedRequest.last_name}</span>
                                                )}
                                                <a href={`mailto:${selectedRequest.email}`} className="flex items-center gap-1 hover:text-primary-400"><Mail className="w-3.5 h-3.5" aria-hidden="true" /> {selectedRequest.email}</a>
                                                {selectedRequest.phone && (
                                                    <a href={`tel:${selectedRequest.phone}`} className="flex items-center gap-1 hover:text-primary-400"><Phone className="w-3.5 h-3.5" aria-hidden="true" /> {selectedRequest.phone}</a>
                                                )}
                                            </div>
                                        </div>

                                        {/* ═══ SECTION 2: Location & Map ═══ */}
                                        {
                                            (selectedRequest.address || selectedRequest.lat) && (
                                                <div className="p-4 rounded-lg bg-slate-800/50 border border-white/10">
                                                    <div className="flex items-center gap-2 mb-3">
                                                        <MapPin className="w-4 h-4 text-blue-400" aria-hidden="true" />
                                                        <span className="font-medium text-white">Location</span>
                                                    </div>
                                                    {selectedRequest.address && (
                                                        <p className="text-white/80 mb-3">{selectedRequest.address}</p>
                                                    )}
                                                    {/* Interactive Google Maps with Asset Overlay */}
                                                    {selectedRequest.lat && selectedRequest.long && mapProviderReady(mapsConfig) && (
                                                        <div className="rounded-lg overflow-hidden h-64 bg-slate-900">
                                                            <RequestDetailMap
                                                                lat={selectedRequest.lat}
                                                                lng={selectedRequest.long}
                                                                matchedAsset={(selectedRequest as any).matched_asset}
                                                                mapLayers={mapLayers}
                                                                config={mapConfig}
                                                                townshipBoundary={mapsConfig?.township_boundary}
                                                            />
                                                        </div>
                                                    )}
                                                    {/* Fallback for no API key */}
                                                    {selectedRequest.lat && selectedRequest.long && !mapProviderReady(mapsConfig) && (
                                                        <div className="rounded-lg overflow-hidden h-48 bg-slate-900">
                                                            <iframe
                                                                width="100%"
                                                                height="100%"
                                                                style={{ border: 0 }}
                                                                loading="lazy"
                                                                src={`https://www.google.com/maps?q=${selectedRequest.lat},${selectedRequest.long}&z=17&output=embed`}
                                                            />
                                                        </div>
                                                    )}

                                                    {/* Matched Asset Info - Below Map */}
                                                    {(selectedRequest as any).matched_asset && (
                                                        <div className="mt-3 p-3 rounded-lg bg-emerald-500/5 border border-emerald-500/20">
                                                            {/* Clear header label */}
                                                            <div className="flex items-center gap-2 mb-2">
                                                                <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-300">🔗 Matched Asset</span>
                                                                {(selectedRequest as any).matched_asset.distance_meters && (
                                                                    <span className="text-xs text-white/40 ml-auto">
                                                                        {(selectedRequest as any).matched_asset.distance_meters < 1
                                                                            ? '<1m away'
                                                                            : `${Math.round((selectedRequest as any).matched_asset.distance_meters)}m away`}
                                                                    </span>
                                                                )}
                                                            </div>
                                                            <div className="flex items-center gap-2 mb-2">
                                                                <div className="w-3 h-3 rounded bg-emerald-500" />
                                                                <span className="text-sm font-medium text-emerald-400">
                                                                    {(selectedRequest as any).matched_asset.layer_name}
                                                                </span>
                                                            </div>
                                                            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
                                                                {(selectedRequest as any).matched_asset.asset_id && (
                                                                    <>
                                                                        <span className="text-white/40">Asset ID</span>
                                                                        <span className="text-white/80 font-mono">{(selectedRequest as any).matched_asset.asset_id}</span>
                                                                    </>
                                                                )}
                                                                {(selectedRequest as any).matched_asset.asset_type && (
                                                                    <>
                                                                        <span className="text-white/40">Type</span>
                                                                        <span className="text-white/80">{(selectedRequest as any).matched_asset.asset_type}</span>
                                                                    </>
                                                                )}
                                                                {(selectedRequest as any).matched_asset.properties &&
                                                                    Object.entries((selectedRequest as any).matched_asset.properties)
                                                                        .filter(([key, value]) => {
                                                                            // Exclude common ID fields
                                                                            if (['id', 'asset_id', 'name', 'layer_name', 'objectid', 'fid', 'gid'].includes(key.toLowerCase())) return false;
                                                                            // Exclude purely numeric values (likely IDs)
                                                                            if (typeof value === 'number' && String(value).match(/^\d+$/)) return false;
                                                                            // Exclude null/undefined/empty
                                                                            if (value === null || value === undefined || value === '') return false;
                                                                            return true;
                                                                        })
                                                                        .slice(0, 6)
                                                                        .map(([key, value]) => (
                                                                            <React.Fragment key={key}>
                                                                                <span className="text-white/40 truncate">
                                                                                    {key.replace(/_/g, ' ').replace(/([A-Z])/g, ' $1').trim()}
                                                                                </span>
                                                                                <span className="text-white/80 truncate">
                                                                                    {String(value)}
                                                                                </span>
                                                                            </React.Fragment>
                                                                        ))
                                                                }
                                                            </div>

                                                            {/* Asset History - Related Reports */}
                                                            <div className="mt-3 pt-3 border-t border-emerald-500/20">
                                                                <div className="flex items-center gap-2 mb-2">
                                                                    <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-300">📋 Asset History</span>
                                                                    {isLoadingAssetHistory && (
                                                                        <div className="w-3 h-3 border-2 border-emerald-400 border-t-transparent rounded-full animate-spin" />
                                                                    )}
                                                                </div>
                                                                {assetRelatedRequests.length > 0 ? (
                                                                    <div className="space-y-2">
                                                                        <p className="text-xs text-emerald-400/80">
                                                                            {assetRelatedRequests.length} other report{assetRelatedRequests.length !== 1 ? 's' : ''} linked to this asset
                                                                        </p>
                                                                        <div className="space-y-1.5 max-h-32 overflow-y-auto">
                                                                            {assetRelatedRequests.slice(0, 5).map((r) => (
                                                                                <button
                                                                                    key={r.service_request_id}
                                                                                    onClick={() => loadRequestDetail(r.service_request_id)}
                                                                                    className="w-full text-left p-2 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 transition-colors group"
                                                                                >
                                                                                    <div className="flex items-center justify-between">
                                                                                        <span className="text-xs font-mono text-emerald-400 group-hover:text-emerald-300">{r.service_request_id}</span>
                                                                                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${r.status === 'closed' ? 'bg-green-500/20 text-green-400' :
                                                                                            r.status === 'in_progress' ? 'bg-amber-500/20 text-amber-400' :
                                                                                                'bg-red-500/20 text-red-400'
                                                                                            }`}>{r.status.replace('_', ' ')}</span>
                                                                                    </div>
                                                                                    <p className="text-xs text-white/60 truncate mt-0.5">{r.service_name}</p>
                                                                                    <p className="text-[10px] text-white/40 mt-0.5">
                                                                                        {new Date(r.requested_datetime).toLocaleDateString()}
                                                                                    </p>
                                                                                </button>
                                                                            ))}
                                                                        </div>
                                                                        {assetRelatedRequests.length > 5 && (
                                                                            <p className="text-[10px] text-white/40 text-center">
                                                                                +{assetRelatedRequests.length - 5} more reports
                                                                            </p>
                                                                        )}
                                                                    </div>
                                                                ) : !isLoadingAssetHistory ? (
                                                                    <p className="text-xs text-white/40">
                                                                        No previous reports for this asset
                                                                    </p>
                                                                ) : null}
                                                            </div>
                                                        </div>
                                                    )}
                                                </div>
                                            )
                                        }


                                        {/* ═══ SECTION 4: Timeline ═══ */}
                                        <div className="p-4 rounded-lg bg-slate-800/50 border border-white/10">
                                            <div className="flex items-center gap-2 mb-4">
                                                <Clock className="w-4 h-4 text-blue-400" aria-hidden="true" />
                                                <span className="font-medium text-white">Timeline</span>
                                                {auditLog.length > 0 && (
                                                    <span className="px-2 py-0.5 rounded-full text-xs bg-white/10 text-white/60">{auditLog.length} events</span>
                                                )}
                                            </div>

                                            {/* Timeline */}
                                            <div className="relative">
                                                <div className="space-y-3">
                                                    {/* Always show submitted event first, even if not in audit log */}
                                                    {(() => {
                                                        const hasSubmittedEvent = auditLog.some(e => e.action === 'submitted');
                                                        const timelineEntries = hasSubmittedEvent ? auditLog : [
                                                            {
                                                                id: -1,
                                                                service_request_id: 0,
                                                                action: 'submitted' as const,
                                                                new_value: 'open',
                                                                old_value: null,
                                                                actor_type: 'resident' as const,
                                                                actor_name: 'Resident',
                                                                created_at: selectedRequest.requested_datetime,
                                                                extra_data: null
                                                            },
                                                            ...auditLog
                                                        ];

                                                        return timelineEntries.map((entry, idx) => {
                                                            // Determine color and text based on action - simple circles, no emojis
                                                            let actionConfig: { color: string; text: string };

                                                            if (entry.action === 'submitted') {
                                                                actionConfig = { color: 'bg-emerald-500', text: 'Request submitted' };
                                                            } else if (entry.action === 'status_change') {
                                                                // Show both old and new status for clarity
                                                                const oldStatus = entry.old_value || 'unknown';
                                                                const newStatus = entry.new_value || 'unknown';
                                                                let statusText = '';

                                                                if (newStatus === 'closed') {
                                                                    const substatus = entry.extra_data?.substatus;
                                                                    statusText = `Closed ${substatus === 'resolved' ? '- Resolved' : substatus === 'no_action' ? '- No Action Needed' : substatus === 'third_party' ? '- Third Party' : ''}`;
                                                                } else if (newStatus === 'in_progress') {
                                                                    statusText = oldStatus === 'closed' ? 'Reopened as In Progress' : 'Marked as In Progress';
                                                                } else if (newStatus === 'open') {
                                                                    statusText = oldStatus === 'closed' ? 'Reopened' : oldStatus === 'in_progress' ? 'Reverted to Open' : 'Status set to Open';
                                                                } else {
                                                                    statusText = `Status: ${oldStatus} → ${newStatus}`;
                                                                }

                                                                actionConfig = {
                                                                    color: newStatus === 'closed' ? 'bg-emerald-500' : newStatus === 'in_progress' ? 'bg-blue-500' : 'bg-purple-500',
                                                                    text: statusText
                                                                };
                                                            } else if (entry.action === 'department_assigned') {
                                                                actionConfig = { color: 'bg-purple-500', text: `Assigned to ${entry.new_value}` };
                                                            } else if (entry.action === 'staff_assigned') {
                                                                actionConfig = { color: 'bg-indigo-500', text: `Assigned to ${entry.new_value}` };
                                                            } else if (entry.action === 'comment_added') {
                                                                actionConfig = { color: 'bg-teal-500', text: 'Comment added' };
                                                            } else if (entry.action === 'public_archive') {
                                                                const isArchived = entry.new_value === 'archived';
                                                                actionConfig = {
                                                                    color: isArchived ? 'bg-slate-500' : 'bg-emerald-500',
                                                                    text: isArchived
                                                                        ? '\ud83d\udc41\ufe0f Archived from public view'
                                                                        : '\ud83d\udc41\ufe0f Restored to public view'
                                                                };
                                                            } else if (entry.action === 'legal_hold') {
                                                                // Show if legal hold was enabled or removed
                                                                const isEnabled = entry.new_value === 'enabled';
                                                                actionConfig = {
                                                                    color: isEnabled ? 'bg-amber-500' : 'bg-gray-500',
                                                                    text: isEnabled ? '⚖️ Legal Hold Enabled' : '⚖️ Legal Hold Removed'
                                                                };
                                                            } else if (entry.action === 'deleted') {
                                                                actionConfig = {
                                                                    color: 'bg-red-500',
                                                                    text: `🗑️ Soft Deleted: ${entry.new_value || 'No reason given'}`
                                                                };
                                                            } else if (entry.action === 'restored') {
                                                                actionConfig = {
                                                                    color: 'bg-green-500',
                                                                    text: '♻️ Request Restored'
                                                                };
                                                            } else if (entry.action === 'priority_accepted') {
                                                                actionConfig = {
                                                                    color: 'bg-emerald-500',
                                                                    text: `🤖 AI Priority Accepted: ${entry.new_value || ''}`
                                                                };
                                                            } else {
                                                                actionConfig = { color: 'bg-gray-500', text: entry.action };
                                                            }

                                                            const isLast = idx === auditLog.length - 1;

                                                            return (
                                                                <div key={entry.id} className="relative flex items-start gap-3 pl-0">
                                                                    {/* Simple circle indicator - centered on line */}
                                                                    <div className={`w-3.5 h-3.5 rounded-full ${actionConfig.color} shadow-sm ${isLast ? 'ring-2 ring-white/30' : ''}`} />

                                                                    {/* Content */}
                                                                    <div className="flex-1 min-w-0 -mt-0.5">
                                                                        <div className="flex items-center gap-2 flex-wrap">
                                                                            <span className="text-white/90 text-sm font-medium">{actionConfig.text}</span>
                                                                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${entry.actor_type === 'staff' || entry.actor_type === 'admin' ? 'bg-purple-500/20 text-purple-300' : 'bg-blue-500/20 text-blue-300'}`}>
                                                                                {entry.actor_type === 'staff' || entry.actor_type === 'admin' ? entry.actor_name || 'Staff' : 'Resident'}
                                                                            </span>
                                                                        </div>
                                                                        <div className="text-white/40 text-xs mt-0.5">
                                                                            {entry.created_at ? new Date(entry.created_at).toLocaleString() : 'No timestamp'}
                                                                        </div>
                                                                    </div>
                                                                </div>
                                                            );
                                                        });
                                                    })()}
                                                </div>
                                            </div>
                                        </div>

                                        {/* ═══ SECTION 5: Comments ═══ */}
                                        <div className="p-5 rounded-3xl bg-gradient-to-br from-white/[0.06] via-white/[0.02] to-indigo-950/40 border border-white/10 backdrop-blur-2xl">
                                            <div className="flex items-center gap-2 mb-4 text-[11px] uppercase tracking-wider text-white/60 font-semibold">
                                                <MessageSquare className="w-4 h-4 text-primary-200" aria-hidden="true" />
                                                Comments
                                                {comments.length > 0 && (
                                                    <span className="px-2 py-0.5 rounded-2xl border border-white/15 bg-white/[0.07] text-white/70 tabular-nums normal-case tracking-normal">{comments.length}</span>
                                                )}
                                            </div>

                                            {/* Comments List */}
                                            {comments.length > 0 ? (
                                                <div className="space-y-3 max-h-72 overflow-y-auto mb-4 pr-1">
                                                    {comments.map(c => (
                                                        <CommentCard key={c.id} comment={c} showVisibility />
                                                    ))}
                                                </div>
                                            ) : (
                                                <div className="mb-4">
                                                    <CommentEmptyState
                                                        title="No comments yet"
                                                        hint="Internal notes stay with staff; public replies reach the reporter."
                                                    />
                                                </div>
                                            )}

                                            {/* Add Comment */}
                                            <div className={`rounded-2xl border transition-colors ${commentVisibility === 'internal' ? 'bg-amber-500/[0.04] border-amber-400/25' : 'bg-emerald-500/[0.04] border-emerald-400/25'}`}>
                                                <div className="px-3.5 pt-3 flex items-center gap-2 flex-wrap">
                                                    <div className="inline-flex rounded-xl bg-white/[0.05] border border-white/10 p-0.5" role="group" aria-label="Comment visibility">
                                                        <button
                                                            type="button"
                                                            onClick={() => setCommentVisibility('internal')}
                                                            aria-pressed={commentVisibility === 'internal'}
                                                            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[10px] text-xs font-semibold transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-300 ${commentVisibility === 'internal' ? 'bg-gradient-to-r from-amber-500/25 to-orange-500/25 text-amber-200 shadow-sm' : 'text-white/60 hover:text-white/90'}`}
                                                        >
                                                            <Lock className="w-3 h-3" aria-hidden="true" />
                                                            Internal note
                                                        </button>
                                                        <button
                                                            type="button"
                                                            onClick={() => setCommentVisibility('external')}
                                                            aria-pressed={commentVisibility === 'external'}
                                                            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-[10px] text-xs font-semibold transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 ${commentVisibility === 'external' ? 'bg-gradient-to-r from-emerald-500/25 to-teal-500/25 text-emerald-200 shadow-sm' : 'text-white/60 hover:text-white/90'}`}
                                                        >
                                                            <Globe className="w-3 h-3" aria-hidden="true" />
                                                            Public reply
                                                        </button>
                                                    </div>
                                                    <span className={`text-[11px] ${commentVisibility === 'internal' ? 'text-amber-200/70' : 'text-emerald-200/70'}`}>
                                                        {commentVisibility === 'internal' ? 'Staff only' : 'Visible to the reporter'}
                                                    </span>
                                                </div>
                                                <div className="p-3.5 flex gap-2">
                                                    <input
                                                        type="text"
                                                        placeholder={commentVisibility === 'internal' ? 'Add internal note...' : 'Reply to reporter...'}
                                                        aria-label={commentVisibility === 'internal' ? 'Add internal note' : 'Reply to reporter'}
                                                        value={newComment}
                                                        onChange={(e) => setNewComment(e.target.value)}
                                                        onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleAddComment()}
                                                        className="flex-1 rounded-xl bg-white/[0.04] border border-white/10 text-white text-sm px-3.5 py-2.5 placeholder:text-white/40 transition-all focus:outline-none focus:border-primary-400/50 focus:bg-white/[0.06] focus:shadow-[0_0_0_3px_rgba(99,102,241,0.15)]"
                                                    />
                                                    <button
                                                        onClick={handleAddComment}
                                                        disabled={!newComment.trim() || isSubmittingComment}
                                                        className="px-4 py-2 rounded-2xl border border-primary-400/50 bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 text-white text-sm font-semibold shadow-lg shadow-primary-500/25 hover:shadow-primary-500/40 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                                        aria-label="Send comment"
                                                    >
                                                        <Send className="w-4 h-4" aria-hidden="true" />
                                                    </button>
                                                </div>
                                            </div>
                                        </div>

                                        {/* ═══ Actions Footer ═══ */}
                                        <div className="p-4 rounded-lg bg-slate-800/50 border border-white/10">
                                            <div className="flex gap-3">
                                                {/* Share Link Dropdown */}
                                                {/* A disclosure — WCAG 4.1.2 / 2.1.1.
                                                    The trigger had no aria-haspopup and no
                                                    aria-expanded, so nothing announced that a
                                                    panel existed or whether it was open; the
                                                    panel had no role, no Escape, no
                                                    outside-click close and never returned
                                                    focus, so a keyboard user who opened it and
                                                    changed their mind had no way to shut it.
                                                    aria-expanded/aria-controls over ordinary
                                                    buttons is the whole of what this needs —
                                                    two links do not warrant a menu widget.
                                                    Outside-click dismissal is wired up with
                                                    the export panel's, near the top of the
                                                    component. */}
                                                <div className="relative flex-1" ref={shareWrapRef}
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Escape' && showShareMenu) {
                                                            e.stopPropagation();
                                                            setShowShareMenu(false);
                                                            shareBtnRef.current?.focus();
                                                        }
                                                    }}
                                                >
                                                    <button
                                                        ref={shareBtnRef}
                                                        type="button"
                                                        onClick={() => setShowShareMenu(!showShareMenu)}
                                                        aria-expanded={showShareMenu}
                                                        /* Only while the menu is mounted; collapsed, the id
                                                           does not exist and the reference dangles. */
                                                        aria-controls={showShareMenu ? 'share-link-options' : undefined}
                                                        className="w-full py-2.5 px-4 rounded-lg bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium flex items-center justify-center gap-2 transition-colors"
                                                    >
                                                        <Link className="w-4 h-4" aria-hidden="true" />
                                                        Share Link
                                                        <ChevronDown className={`w-4 h-4 transition-transform ${showShareMenu ? 'rotate-180' : ''}`} aria-hidden="true" />
                                                    </button>

                                                    {showShareMenu && (
                                                        <div id="share-link-options" className="absolute bottom-full left-0 right-0 mb-2 bg-slate-800 rounded-lg border border-white/10 shadow-xl overflow-hidden z-20">
                                                            <button
                                                                type="button"
                                                                onClick={() => {
                                                                    // Use current status for staff link (active, in_progress, resolved)
                                                                    const statusPath = selectedRequest.status === 'open' ? 'active' :
                                                                        selectedRequest.status === 'in_progress' ? 'in_progress' : 'resolved';
                                                                    navigator.clipboard.writeText(`${window.location.origin}/staff#${statusPath}/request/${selectedRequest.service_request_id}`);
                                                                    setCopiedLink('staff');
                                                                    // "Copied!" replaced the label
                                                                    // for 1.5 seconds and nothing
                                                                    // else happened — invisible to
                                                                    // anyone not watching it.
                                                                    announce('Staff portal link copied to the clipboard.');
                                                                    setTimeout(() => { setCopiedLink(null); setShowShareMenu(false); }, 1500);
                                                                }}
                                                                className="w-full px-4 py-3 flex items-center gap-3 hover:bg-white/5 transition-colors text-left"
                                                            >
                                                                <div className="w-8 h-8 rounded-lg bg-purple-500/20 flex items-center justify-center">
                                                                    {copiedLink === 'staff' ? <Check className="w-4 h-4 text-green-400" aria-hidden="true" /> : <Link className="w-4 h-4 text-purple-400" aria-hidden="true" />}
                                                                </div>
                                                                <div className="flex-1 min-w-0">
                                                                    <div className="text-sm font-medium text-white">
                                                                        {copiedLink === 'staff' ? 'Copied!' : 'Staff Portal Link'}
                                                                    </div>
                                                                    <div className="text-xs text-white/40 truncate">For internal staff use</div>
                                                                </div>
                                                            </button>
                                                            <div className="border-t border-white/5" />
                                                            <button
                                                                type="button"
                                                                onClick={() => {
                                                                    // Resident portal uses /#track/ID format
                                                                    navigator.clipboard.writeText(`${window.location.origin}/#track/${selectedRequest.service_request_id}`);
                                                                    setCopiedLink('resident');
                                                                    announce('Resident portal link copied to the clipboard.');
                                                                    setTimeout(() => { setCopiedLink(null); setShowShareMenu(false); }, 1500);
                                                                }}
                                                                className="w-full px-4 py-3 flex items-center gap-3 hover:bg-white/5 transition-colors text-left"
                                                            >
                                                                <div className="w-8 h-8 rounded-lg bg-blue-500/20 flex items-center justify-center">
                                                                    {copiedLink === 'resident' ? <Check className="w-4 h-4 text-green-400" aria-hidden="true" /> : <ExternalLink className="w-4 h-4 text-blue-400" aria-hidden="true" />}
                                                                </div>
                                                                <div className="flex-1 min-w-0">
                                                                    <div className="text-sm font-medium text-white">
                                                                        {copiedLink === 'resident' ? 'Copied!' : 'Resident Portal Link'}
                                                                    </div>
                                                                    <div className="text-xs text-white/40 truncate">Share with the reporter</div>
                                                                </div>
                                                            </button>
                                                        </div>
                                                    )}
                                                </div>

                                                <button onClick={() => setShowDeleteModal(true)} aria-label="Delete request" className="py-2.5 px-4 rounded-lg bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-400 text-sm font-medium flex items-center gap-2 transition-colors">
                                                    <Trash2 className="w-4 h-4" aria-hidden="true" />
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <div className="flex-1 flex items-center justify-center text-white/40">
                                    <div className="text-center">
                                        <FileText className="w-12 h-12 mx-auto mb-3 opacity-50" aria-hidden="true" />
                                        <p className="text-sm">Select an incident</p>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                )
                }
            </main>

            {/* Manual Intake Modal */}
            <Modal isOpen={showIntakeModal} onClose={() => setShowIntakeModal(false)} title="New Manual Intake">
                <form onSubmit={handleCreateIntake} className="space-y-4">
                    <Select
                        label="Service Category"
                        options={[
                            { value: '', label: 'Select a category...' },
                            ...services.map((s) => ({ value: s.service_code, label: s.service_name })),
                        ]}
                        value={intakeData.service_code}
                        onChange={(e) => setIntakeData((prev) => ({ ...prev, service_code: e.target.value }))}
                        required
                    />
                    <Input
                        label="Location"
                        placeholder="Address or intersection"
                        value={intakeData.address}
                        onChange={(e) => setIntakeData((prev) => ({ ...prev, address: e.target.value }))}
                    />
                    <Textarea
                        label="Description"
                        placeholder="Describe the issue..."
                        value={intakeData.description}
                        onChange={(e) => setIntakeData((prev) => ({ ...prev, description: e.target.value }))}
                        required
                    />
                    <Select
                        label="Source"
                        options={[
                            { value: 'phone', label: 'Phone Call' },
                            { value: 'walk_in', label: 'Walk-In' },
                            { value: 'email', label: 'Email' },
                        ]}
                        value={intakeData.source}
                        onChange={(e) => setIntakeData((prev) => ({ ...prev, source: e.target.value }))}
                    />
                    <div className="flex justify-end gap-3 pt-4">
                        <Button variant="ghost" onClick={() => setShowIntakeModal(false)}>
                            Cancel
                        </Button>
                        <Button type="submit">Create Intake</Button>
                    </div>
                </form>
            </Modal >

            {/* Close Request Modal - Substatus Selection */}
            < Modal isOpen={showClosedModal} onClose={() => setShowClosedModal(false)} title="Close Request" >
                <div className="space-y-6">
                    {/* fieldset/legend — WCAG 1.3.1.
                        The prompt was a floating <p> with no relationship to the
                        three radios below it, so a screen reader moving through
                        the group announced "No Action Needed, radio, 1 of 3" with
                        no indication of what was being decided. The <p> read out
                        once, on the way past, minutes earlier in the dialog. */}
                    <fieldset className="border-0 p-0 m-0">
                        <legend className="text-white/70 text-sm mb-3">Select a resolution type for this request:</legend>

                    <div className="space-y-3">
                        <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${closedSubstatus === 'no_action' ? 'bg-orange-500/10 border-orange-500/30' : 'bg-white/5 border-white/10 hover:bg-white/10'}`}>
                            <input
                                type="radio"
                                name="closedSubstatus"
                                value="no_action"
                                checked={closedSubstatus === 'no_action'}
                                onChange={() => setClosedSubstatus('no_action')}
                                className="mt-1"
                            />
                            <div>
                                <p className="font-medium text-white">No Action Needed</p>
                                <p className="text-sm text-white/50">Issue doesn't require municipal intervention</p>
                            </div>
                        </label>

                        <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${closedSubstatus === 'resolved' ? 'bg-green-500/10 border-green-500/30' : 'bg-white/5 border-white/10 hover:bg-white/10'}`}>
                            <input
                                type="radio"
                                name="closedSubstatus"
                                value="resolved"
                                checked={closedSubstatus === 'resolved'}
                                onChange={() => setClosedSubstatus('resolved')}
                                className="mt-1"
                            />
                            <div>
                                <p className="font-medium text-white">Resolved</p>
                                <p className="text-sm text-white/50">Issue has been fixed by municipal staff</p>
                            </div>
                        </label>

                        <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${closedSubstatus === 'third_party' ? 'bg-blue-500/10 border-blue-500/30' : 'bg-white/5 border-white/10 hover:bg-white/10'}`}>
                            <input
                                type="radio"
                                name="closedSubstatus"
                                value="third_party"
                                checked={closedSubstatus === 'third_party'}
                                onChange={() => setClosedSubstatus('third_party')}
                                className="mt-1"
                            />
                            <div>
                                <p className="font-medium text-white">Third Party Contacted</p>
                                <p className="text-sm text-white/50">Referred to utility company, state agency, etc.</p>
                            </div>
                        </label>
                    </div>
                    </fieldset>

                    <Textarea
                        label="Completion Message (optional)"
                        placeholder="Add a message about the resolution..."
                        value={completionMessage}
                        onChange={(e) => setCompletionMessage(e.target.value)}
                    />

                    {closedSubstatus === 'resolved' && (
                        <div className="space-y-2">
                            <label className="block text-sm font-medium text-white/70">Completion Photo (optional)</label>
                            <div className="flex items-center gap-3">
                                <input
                                    type="file"
                                    accept="image/*"
                                    id="completion-photo-upload"
                                    className="hidden"
                                    onChange={async (e) => {
                                        const file = e.target.files?.[0];
                                        if (file) {
                                            try {
                                                const result = await api.uploadImage(file);
                                                setCompletionPhotoUrl(result.url);
                                            } catch (err) {
                                                console.error('Upload failed:', err);
                                                alert("Failed to upload image");
                                            }
                                        }
                                    }}
                                />
                                <label
                                    htmlFor="completion-photo-upload"
                                    className="px-4 py-2 rounded-lg bg-white/10 border border-white/20 text-white text-sm cursor-pointer hover:bg-white/20 transition-colors flex items-center gap-2"
                                >
                                    <Camera className="w-4 h-4" aria-hidden="true" />
                                    {completionPhotoUrl ? 'Change Photo' : 'Upload Photo'}
                                </label>
                                {completionPhotoUrl && (
                                    <div className="flex items-center gap-2">
                                        <img src={completionPhotoUrl} alt="Completion" className="h-12 w-12 object-cover rounded-lg" />
                                        <button
                                            onClick={() => setCompletionPhotoUrl('')}
                                            className="text-red-400 hover:text-red-300 text-sm"
                                        >
                                            Remove
                                        </button>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    <div className="flex justify-end gap-3 pt-4">
                        <Button variant="ghost" onClick={() => setShowClosedModal(false)}>
                            Cancel
                        </Button>
                        <Button onClick={handleCloseWithSubstatus}>
                            Close Request
                        </Button>
                    </div>
                </div>
            </Modal >

            {/* Delete Request Modal */}
            < Modal isOpen={showDeleteModal} onClose={() => setShowDeleteModal(false)} title="Delete Request" >
                <div className="space-y-4">
                    <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/20">
                        <p className="text-red-400 font-medium flex items-center gap-2">
                            <Trash2 className="w-5 h-5" aria-hidden="true" />
                            This will soft-delete the request
                        </p>
                        <p className="text-white/60 text-sm mt-2">
                            The request will be hidden from the normal view but will remain accessible to administrators.
                        </p>
                    </div>

                    <Textarea
                        label="Justification *"
                        placeholder="Explain why this request should be deleted (minimum 10 characters)..."
                        value={deleteJustification}
                        onChange={(e) => setDeleteJustification(e.target.value)}
                        required
                    />

                    <div className="flex justify-end gap-3 pt-4">
                        <Button variant="ghost" onClick={() => setShowDeleteModal(false)}>
                            Cancel
                        </Button>
                        <Button
                            variant="danger"
                            onClick={handleDeleteRequest}
                            disabled={deleteJustification.length < 10 || isDeleting}
                        >
                            {isDeleting ? 'Deleting...' : 'Delete Request'}
                        </Button>
                    </div>
                </div>
            </Modal >

            {/* Photo Lightbox — routed through ui/Modal.
                As a hand-rolled overlay this had no role="dialog", no
                aria-modal, and nothing that moved focus into it, so opening a
                photo left focus on the thumbnail behind the backdrop: the only
                way out was the mouse, since there was no Escape handler and the
                instruction on screen said "Click anywhere to close" — an
                instruction that is simply false for anyone not using a pointer
                (WCAG 2.1.2/2.4.3/4.1.2). The list behind it also stayed
                tabbable. Modal already owns the focus trap, Escape, focus
                restore to the trigger and the backdrop, so this is now just the
                image. Untitled, hence the aria-label. */}
            <Modal
                isOpen={!!lightboxUrl}
                onClose={() => setLightboxUrl(null)}
                size="xl"
                aria-label="Photo preview"
                panelClassName="bg-slate-950"
            >
                {lightboxUrl && (
                    <img
                        src={lightboxUrl}
                        alt="Full size preview of the selected photo"
                        className="w-full max-h-[75vh] object-contain rounded-xl bg-black/40"
                    />
                )}
                <p className="mt-3 text-center text-sm text-white/60">
                    Press Escape or use the close button to return.
                </p>
            </Modal>
            {/* Notification Settings Modal */}
            <NotificationSettings
                isOpen={showNotificationSettings}
                onClose={() => setShowNotificationSettings(false)}
                userName={user?.full_name || user?.username || 'User'}
            />
            {/* Manual intake — call taker / walk-in / email */}
            <ManualIntake
                isOpen={showManualIntake}
                onClose={() => setShowManualIntake(false)}
                services={services}
                onCreated={(created) => {
                    // Reflect the new request immediately without a full reload.
                    setAllRequests(prev => [created as any, ...prev]);
                    setRequests(prev => [created as any, ...prev]);
                }}
            />
            {/* Activity Feed Panel */}
            <ActivityFeed
                isOpen={showActivityFeed}
                onClose={() => { setShowActivityFeed(false); setActivityTick(t => t + 1); }}
                requests={allRequests}
                userId={user?.username || ''}
                userDepartmentIds={userDepartmentIds}
                onSelectRequest={(request) => {
                    // Find and select this request by its ID
                    handleMapRequestSelect(request.service_request_id);
                    setSidebarOpen(false);
                }}
            />
        </div >
    );
}

import React, { useState, useEffect, useMemo, useRef, useCallback, FormEvent } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate, useParams } from 'react-router-dom';
import {
    Menu,
    X,
    Search,
    AlertCircle,
    CheckCircle,
    Clock,
    FileText,
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
    LockKeyhole,
    Home,
} from 'lucide-react';
import { Button, Card, Modal, Input, Textarea, Select, StatusBadge, Badge } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { useSettings } from '../context/SettingsContext';
import { api, MapLayer } from '../services/api';
import { ServiceRequest, ServiceRequestDetail, ServiceDefinition, Statistics, AdvancedStatistics, RequestComment, ClosedSubstatus, User as UserType, Department, AuditLogEntry } from '../types';
import { XAxis, YAxis, ResponsiveContainer, AreaChart, Area, Tooltip } from 'recharts';
import StaffDashboardMap from '../components/StaffDashboardMap';
import RequestDetailMap from '../components/RequestDetailMap';
import { usePageNavigation } from '../hooks/usePageNavigation';
import NotificationSettings from '../components/NotificationSettings';
import ActivityFeed from '../components/ActivityFeed';
import PrintWorkOrder from '../components/PrintWorkOrder';
import DemoTour from '../components/DemoTour';

type View = 'dashboard' | 'active' | 'in_progress' | 'resolved' | 'statistics';

export default function StaffDashboard() {
    const navigate = useNavigate();
    const { requestId: urlRequestId } = useParams<{ requestId?: string }>();
    const { user, logout } = useAuth();
    const { settings, demoMode } = useSettings();
    const contentRef = useRef<HTMLDivElement>(null);
    const [demoToast, setDemoToast] = useState<string | null>(null);

    // Demo mode guard — shows toast and blocks action
    const demoGuard = () => {
        if (demoMode) {
            setDemoToast('🔒 Demo mode — changes are disabled. Deploy your own instance to manage requests.');
            setTimeout(() => setDemoToast(null), 4000);
            return true;
        }
        return false;
    };

    // Handle browser back/forward navigation
    const handleHashChange = useCallback((hash: string) => {
        // Parse hash: could be 'dashboard', 'statistics', 'active', 'active/request/SR-123', 'detail/SR-123', etc.
        const parts = hash.split("/");
        const view = parts[0] as View;
        const validViews: View[] = ['dashboard', 'active', 'in_progress', 'resolved', 'statistics'];

        // Handle detail/{id} format (from similar reports buttons)
        if (parts[0] === 'detail' && parts[1]) {
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
    const { updateHash, updateTitle, scrollToTop } = usePageNavigation({
        baseTitle: settings?.township_name ? `Staff Portal | ${settings.township_name}` : 'Staff Portal',
        scrollContainerRef: contentRef,
        onHashChange: handleHashChange,
    });

    const [sidebarOpen, setSidebarOpen] = useState(false);
    const [currentView, setCurrentView] = useState<View>('dashboard');
    const [requests, setRequests] = useState<ServiceRequest[]>([]);
    const [allRequests, setAllRequests] = useState<ServiceRequest[]>([]); // For dashboard map
    const [selectedRequest, setSelectedRequest] = useState<ServiceRequestDetail | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [showIntakeModal, setShowIntakeModal] = useState(false);
    const [services, setServices] = useState<ServiceDefinition[]>([]);
    const [statistics, setStatistics] = useState<Statistics | null>(null);
    const [advancedStats, setAdvancedStats] = useState<AdvancedStatistics | null>(null);

    // Dashboard-specific state
    const [departments, setDepartments] = useState<Department[]>([]);
    const [users, setUsers] = useState<UserType[]>([]);
    const [mapLayers, setMapLayers] = useState<MapLayer[]>([]);
    const [mapsConfig, setMapsConfig] = useState<{ google_maps_api_key: string | null; google_maps_map_id: string | null; township_boundary: object | null; default_center?: { lat: number; lng: number } } | null>(null);

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
    const [filterAssignment, setFilterAssignment] = useState<'all' | 'me' | 'department'>('all');
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

    // Activity feed state
    const [showActivityFeed, setShowActivityFeed] = useState(false);

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

    // Get current user's department IDs
    const userDepartmentIds = useMemo(() => {
        return user?.departments?.map(d => d.id) || [];
    }, [user]);

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
            if (mapPriorityFilter === 'high') return priority >= 8;
            if (mapPriorityFilter === 'medium') return priority >= 5 && priority < 8;
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

    // Auto-load request if URL contains requestId
    useEffect(() => {
        if (urlRequestId) {
            loadRequestDetail(urlRequestId);
        }
    }, [urlRequestId]);

    // Update URL hash and title when view changes
    useEffect(() => {
        updateHash(currentView);
        const viewTitles: Record<View, string> = {
            dashboard: 'Dashboard',
            active: 'Open Requests',
            in_progress: 'In Progress',
            resolved: 'Resolved',
            statistics: 'Statistics'
        };
        updateTitle(viewTitles[currentView]);
        scrollToTop('instant');
    }, [currentView, updateHash, updateTitle, scrollToTop]);

    // Update URL hash when request is selected
    useEffect(() => {
        if (selectedRequest) {
            updateHash(`${currentView}/request/${selectedRequest.service_request_id}`);
            updateTitle(`Request ${selectedRequest.service_request_id}`);
            // Scroll detail panel to top when a new request is selected
            if (detailPanelRef.current) {
                detailPanelRef.current.scrollTo({ top: 0, behavior: 'instant' });
            }
        }
    }, [selectedRequest, currentView, updateHash, updateTitle]);

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

    const loadStatistics = async () => {
        try {
            const [statsData, advancedData] = await Promise.all([
                api.getStatistics(),
                api.getAdvancedStatistics()
            ]);
            setStatistics(statsData);
            setAdvancedStats(advancedData);
        } catch (err) {
            console.error('Failed to load statistics:', err);
        }
    };

    const loadRequestDetail = async (requestId: string) => {
        try {
            const detail = await api.getRequestDetail(requestId);
            setSelectedRequest(detail);
            // Load comments and audit log for this request
            loadComments(detail.id);
            loadAuditLog(requestId);
        } catch (err) {
            console.error('Failed to load request detail:', err);
        }
    };

    const handleStatusChange = async (status: string) => {
        if (demoGuard()) return;
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
        } catch (err) {
            console.error('Failed to update status:', err);
        }
    };

    const handleCloseWithSubstatus = async () => {
        if (demoGuard()) return;
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
        } catch (err) {
            console.error('Failed to close request:', err);
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
        if (demoGuard()) return;
        if (!selectedRequest || !newComment.trim()) return;
        setIsSubmittingComment(true);
        try {
            await api.createComment(selectedRequest.id, newComment.trim(), commentVisibility);
            setNewComment('');
            loadComments(selectedRequest.id);
        } catch (err) {
            console.error('Failed to add comment:', err);
        } finally {
            setIsSubmittingComment(false);
        }
    };

    const handleDeleteRequest = async () => {
        if (demoGuard()) return;
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
        if (demoGuard()) return;
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
            {/* Demo-only guided tour */}
            {demoMode && <DemoTour />}
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
                                            <Home className="w-4 h-4 text-white" />
                                        </div>
                                    </div>
                                ) : (
                                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center">
                                        <Home className="w-5 h-5 text-white" />
                                    </div>
                                )}
                                <div className="text-left" data-no-translate>
                                    <h2 className="font-semibold text-white flex items-center gap-1.5">
                                        Staff Command
                                        <Home className="w-3.5 h-3.5 text-white/40 group-hover:text-white/70 transition-colors" />
                                    </h2>
                                    <p className="text-xs text-white/50">{settings?.township_name}</p>
                                </div>
                            </button>
                            <div className="flex items-center gap-2">
                                {/* Activity Feed Bell */}
                                <button
                                    onClick={() => setShowActivityFeed(true)}
                                    className="relative p-2 hover:bg-white/10 rounded-lg transition-colors"
                                    aria-label="Open activity feed"
                                >
                                    <Bell className="w-5 h-5 text-white/60" aria-hidden="true" />
                                    {/* Calculate and show unread count */}
                                    {(() => {
                                        const now = Date.now();
                                        const twentyFourHours = 24 * 60 * 60 * 1000;
                                        const readItems = JSON.parse(localStorage.getItem('activityFeedRead') || '[]');
                                        const readSet = new Set(readItems);
                                        let count = 0;
                                        allRequests.forEach(req => {
                                            const age = now - new Date(req.requested_datetime).getTime();
                                            if (age < twentyFourHours && req.assigned_department_id && userDepartmentIds.includes(req.assigned_department_id)) {
                                                if (!readSet.has(`new-${req.service_request_id}`)) count++;
                                            }
                                        });
                                        return count > 0 ? (
                                            <span className="absolute -top-1 -right-1 w-5 h-5 bg-red-500 rounded-full text-[10px] font-bold text-white flex items-center justify-center animate-pulse">
                                                {count > 9 ? '9+' : count}
                                            </span>
                                        ) : null;
                                    })()}
                                </button>
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
                    <nav className="flex-1 p-4 space-y-2">
                        <p className="text-xs font-medium text-white/40 uppercase tracking-wider px-3 mb-3">
                            Main
                        </p>
                        {menuItems.map((item) => (
                            <button
                                key={item.id}
                                onClick={() => {
                                    setCurrentView(item.id as View);
                                    setSelectedRequest(null);
                                    setSidebarOpen(false);
                                }}
                                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl transition-colors ${currentView === item.id
                                    ? 'bg-primary-500/20 text-white'
                                    : 'text-white/60 hover:bg-white/5 hover:text-white'
                                    }`}
                            >
                                <div className="flex items-center gap-3">
                                    <item.icon className="w-5 h-5" />
                                    <span className="font-medium">{item.label}</span>
                                </div>
                                {item.count !== null && (
                                    <Badge variant={currentView === item.id ? 'info' : 'default'}>
                                        {item.count}
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
                    </div>
                </div>
            </aside>

            {/* Main Content - offset by sidebar width on desktop */}
            <div id="main-content" role="main" className="flex-1 flex flex-col min-w-0 lg:ml-72">
                {/* Mobile Header */}
                <header className="lg:hidden glass-sidebar p-4 flex items-center justify-between sticky top-0 z-30">
                    <button
                        onClick={() => setSidebarOpen(true)}
                        className="p-2 hover:bg-white/10 rounded-lg"
                        aria-label="Open navigation menu"
                    >
                        <Menu className="w-6 h-6 text-white" aria-hidden="true" />
                    </button>
                    <h1 className="font-semibold text-white">Staff Dashboard</h1>
                    <div className="w-10" aria-hidden="true" />
                </header>

                {/* Demo mode banner */}
                {demoMode && (
                    <div className="mx-4 lg:mx-6 mt-4 flex items-center gap-3 p-3 rounded-xl bg-amber-500/15 border border-amber-500/30 text-amber-300 text-sm">
                        <LockKeyhole className="w-4 h-4 flex-shrink-0" />
                        <span><strong>Demo Mode — View Only.</strong> Browse freely, but changes are disabled.</span>
                    </div>
                )}
                {demoToast && (
                    <div className="mx-4 lg:mx-6 mt-2 flex items-center gap-3 p-3 rounded-xl bg-amber-500/20 border border-amber-500/40 text-amber-200 text-sm animate-pulse">
                        {demoToast}
                    </div>
                )}

                {/* Dashboard View */}
                {currentView === 'dashboard' && (
                    <div className="flex-1 flex flex-col p-4 lg:p-6 overflow-auto">
                        {/* Map Section */}
                        <div className="flex-1 min-h-[400px] lg:min-h-[500px] mb-6 rounded-xl overflow-hidden">
                            {mapsConfig?.google_maps_api_key ? (
                                <StaffDashboardMap
                                    apiKey={mapsConfig.google_maps_api_key}
                                    mapId={mapsConfig.google_maps_map_id}
                                    requests={mapFilteredRequests}
                                    services={services}
                                    departments={departments}
                                    users={users}
                                    mapLayers={mapLayers}
                                    townshipBoundary={mapsConfig.township_boundary}
                                    defaultCenter={mapsConfig.default_center}
                                    onRequestSelect={handleMapRequestSelect}
                                />
                            ) : (
                                <div className="h-full flex items-center justify-center bg-white/5 rounded-xl border border-white/10">
                                    <div className="text-center p-8">
                                        <Map className="w-12 h-12 mx-auto mb-4 text-white/30" />
                                        <p className="text-white/60">Google Maps API key not configured</p>
                                        <p className="text-white/40 text-sm mt-2">Configure in Admin Console → API Keys</p>
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
                            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                                <div>
                                    <h1 className="text-xl sm:text-2xl lg:text-3xl font-bold text-white">Analytics Dashboard</h1>
                                    {advancedStats?.cached_at && (
                                        <p className="text-sm text-white/40 mt-1">
                                            Updated {new Date(advancedStats.cached_at.endsWith('Z') ? advancedStats.cached_at : advancedStats.cached_at + 'Z').toLocaleString()}
                                        </p>
                                    )}
                                </div>
                                <div className="flex flex-wrap items-center gap-2">
                                    <button
                                        onClick={() => setChatOpen(true)}
                                        className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-emerald-600 to-teal-600 text-white rounded-lg hover:from-emerald-700 hover:to-teal-700 transition-all text-sm font-medium shadow-lg shadow-emerald-500/20"
                                    >
                                        <Sparkles className="w-4 h-4" />
                                        Ask AI
                                    </button>
                                    <button
                                        onClick={() => window.location.href = '/research'}
                                        className="flex items-center gap-2 px-4 py-2 bg-white/10 border border-white/20 text-white rounded-lg hover:bg-white/20 transition-all text-sm font-medium"
                                    >
                                        <FlaskConical className="w-4 h-4" />
                                        Research Portal
                                    </button>
                                    <div className="relative group">
                                        <button className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-purple-600 to-blue-600 text-white rounded-lg hover:from-purple-700 hover:to-blue-700 transition-all text-sm font-medium">
                                            <Download className="w-4 h-4" />
                                            Export
                                            <ChevronDown className="w-3 h-3" />
                                        </button>
                                        <div className="absolute right-0 mt-2 w-52 bg-gray-900 border border-white/20 rounded-lg shadow-2xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50">
                                            <div className="p-1.5">
                                                <p className="px-3 py-1.5 text-xs font-semibold text-white/40 uppercase">Requests</p>
                                                <button onClick={() => handleExportRequests('csv')} className="w-full text-left px-3 py-2 text-sm text-white/80 hover:bg-white/10 rounded-md">📄 CSV</button>
                                                <button onClick={() => handleExportRequests('json')} className="w-full text-left px-3 py-2 text-sm text-white/80 hover:bg-white/10 rounded-md">📋 JSON</button>
                                                <button onClick={() => handleExportRequests('geojson')} className="w-full text-left px-3 py-2 text-sm text-white/80 hover:bg-white/10 rounded-md">🗺️ GeoJSON</button>
                                                <div className="border-t border-white/10 my-1" />
                                                <p className="px-3 py-1.5 text-xs font-semibold text-white/40 uppercase">Statistics</p>
                                                <button onClick={() => handleExportStatistics('csv')} className="w-full text-left px-3 py-2 text-sm text-white/80 hover:bg-white/10 rounded-md">📊 CSV</button>
                                                <button onClick={() => handleExportStatistics('json')} className="w-full text-left px-3 py-2 text-sm text-white/80 hover:bg-white/10 rounded-md">📈 JSON</button>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

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
                                    const highPriority = allRequests.filter(r => {
                                        const p = (r as any).manual_priority_score ?? ((r as any).ai_analysis?.priority_score) ?? 5;
                                        return p >= 8;
                                    }).length;
                                    const mediumPriority = allRequests.filter(r => {
                                        const p = (r as any).manual_priority_score ?? ((r as any).ai_analysis?.priority_score) ?? 5;
                                        return p >= 5 && p < 8;
                                    }).length;
                                    const lowPriority = allRequests.filter(r => {
                                        const p = (r as any).manual_priority_score ?? ((r as any).ai_analysis?.priority_score) ?? 5;
                                        return p < 5;
                                    }).length;
                                    const total = allRequests.length || 1;
                                    return (
                                        <div className="space-y-3">
                                            <div className="flex h-6 rounded-full overflow-hidden bg-white/5">
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
                                                <span className="text-red-300">● High (8-10): <strong>{highPriority}</strong></span>
                                                <span className="text-amber-300">● Medium (5-7): <strong>{mediumPriority}</strong></span>
                                                <span className="text-emerald-300">● Low (1-4): <strong>{lowPriority}</strong></span>
                                            </div>
                                        </div>
                                    );
                                })()}
                            </div>

                            {/* KPI Cards */}
                            <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 sm:gap-4">
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
                                    <div className="text-[10px] sm:text-xs text-white/60 mt-1">P1-P3 open &gt; 7 days</div>
                                </div>
                                <div className="bg-gradient-to-br from-blue-500/20 to-blue-500/5 border border-blue-500/30 rounded-xl p-3 sm:p-5">
                                    <div className="text-[10px] sm:text-xs font-medium text-blue-200 uppercase tracking-wider">Peak Activity</div>
                                    <div className="text-2xl sm:text-3xl font-bold text-white mt-1 sm:mt-2">{advancedStats?.predictive_insights?.seasonal_peak_day || 'N/A'}</div>
                                    <div className="text-[10px] sm:text-xs text-white/60 mt-1">Peak: {advancedStats?.predictive_insights?.seasonal_peak_month || 'N/A'}</div>
                                </div>
                            </div>

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
                                    <h3 className="text-lg font-semibold text-white mb-4">Weekly Trend</h3>
                                    <div className="h-48 sm:h-64">
                                        <ResponsiveContainer width="100%" height="100%">
                                            <AreaChart data={advancedStats?.weekly_trend || []}>
                                                <XAxis dataKey="period" stroke="rgba(255,255,255,0.3)" style={{ fontSize: '11px' }} tick={{ fill: 'rgba(255,255,255,0.5)' }} />
                                                <YAxis stroke="rgba(255,255,255,0.3)" style={{ fontSize: '11px' }} tick={{ fill: 'rgba(255,255,255,0.5)' }} />
                                                <Tooltip contentStyle={{ backgroundColor: 'rgba(17,24,39,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: 'white' }} />
                                                <Area type="monotone" dataKey="total" stroke="#8b5cf6" fill="url(#purpleGradient)" fillOpacity={0.4} strokeWidth={2} />
                                                <defs>
                                                    <linearGradient id="purpleGradient" x1="0" y1="0" x2="0" y2="1">
                                                        <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.6} />
                                                        <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0.05} />
                                                    </linearGradient>
                                                </defs>
                                            </AreaChart>
                                        </ResponsiveContainer>
                                    </div>
                                </div>
                            </div>

                            {/* Two-Column: Hotspots + Staff */}
                            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-6">
                                {/* Problem Areas — Compact Table */}
                                {advancedStats?.hotspots && advancedStats.hotspots.length > 0 && (
                                    <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl p-4 sm:p-6">
                                        <h3 className="text-lg font-semibold text-white mb-1">Problem Areas</h3>
                                        <p className="text-xs text-white/40 mb-4">Top locations by request volume</p>
                                        <div className="space-y-2">
                                            {advancedStats.hotspots.slice(0, 5).map((hotspot, idx) => (
                                                <div key={idx} className="flex items-center gap-3 p-3 bg-white/5 rounded-lg hover:bg-white/10 transition">
                                                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">
                                                        {hotspot.count}
                                                    </div>
                                                    <div className="flex-1 min-w-0">
                                                        <div className="text-sm text-white/90 truncate">{hotspot.sample_address || `Area ${idx + 1}`}</div>
                                                        <div className="flex items-center gap-2 mt-0.5">
                                                            {hotspot.top_categories?.slice(0, 2).map((cat, i) => (
                                                                <span key={i} className="text-[10px] px-1.5 py-0.5 bg-white/10 text-white/60 rounded">{cat}</span>
                                                            ))}
                                                            {hotspot.unique_reporters && (
                                                                <span className="text-[10px] text-white/30">{hotspot.unique_reporters} reporter{hotspot.unique_reporters !== 1 ? 's' : ''}</span>
                                                            )}
                                                        </div>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {/* Staff Performance + Workload */}
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
                                                            <span className="text-xs text-white/30 w-4">{idx + 1}.</span>
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
                        </div>
                    </div>
                )} {/* This closes the conditional for currentView === 'statistics' || currentView === 'dashboard' */}

                {/* AI Analytics Chat Panel */}
                <AnimatePresence>
                    {chatOpen && (
                        <>
                            {/* Backdrop */}
                            <motion.div
                                initial={{ opacity: 0 }}
                                animate={{ opacity: 1 }}
                                exit={{ opacity: 0 }}
                                className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[60]"
                                onClick={() => setChatOpen(false)}
                            />
                            {/* Panel */}
                            <motion.div
                                initial={{ x: '100%' }}
                                animate={{ x: 0 }}
                                exit={{ x: '100%' }}
                                transition={{ type: 'spring', damping: 25, stiffness: 200 }}
                                className="fixed right-0 top-0 bottom-0 w-full sm:w-[520px] bg-gray-950/95 backdrop-blur-xl border-l border-white/10 z-[70] flex flex-col shadow-2xl shadow-black/50"
                            >
                                {/* Chat Header */}
                                <div className="flex items-center justify-between px-5 py-4 border-b border-white/10 bg-gradient-to-r from-emerald-600/20 to-teal-600/20">
                                    <div className="flex items-center gap-3">
                                        <div className="w-9 h-9 rounded-full bg-gradient-to-br from-emerald-500 to-teal-500 flex items-center justify-center shadow-lg shadow-emerald-500/30">
                                            <Sparkles className="w-5 h-5 text-white" />
                                        </div>
                                        <div>
                                            <h3 className="text-white font-semibold text-sm">AI Analytics Advisor</h3>
                                            <p className="text-white/40 text-xs">Gemini 3.0 · Research-grade insights</p>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-1.5">
                                        {chatMessages.length > 0 && (
                                            <button
                                                onClick={() => { setChatMessages([]); setChatInput(''); }}
                                                className="w-8 h-8 rounded-lg bg-white/5 hover:bg-red-500/20 flex items-center justify-center transition-colors group"
                                                title="Clear conversation"
                                            >
                                                <Trash2 className="w-3.5 h-3.5 text-white/40 group-hover:text-red-400 transition-colors" />
                                            </button>
                                        )}
                                        <button
                                            onClick={() => setChatOpen(false)}
                                            className="w-8 h-8 rounded-lg bg-white/10 hover:bg-white/20 flex items-center justify-center transition-colors"
                                        >
                                            <X className="w-4 h-4 text-white/70" />
                                        </button>
                                    </div>
                                </div>

                                {/* Messages Area */}
                                <div className="flex-1 overflow-auto p-4 space-y-4" style={{ scrollbarWidth: 'thin', scrollbarColor: 'rgba(255,255,255,0.1) transparent' }}>
                                    {chatMessages.length === 0 && !chatLoading && (
                                        <div className="flex flex-col items-center justify-center h-full text-center px-6">
                                            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-teal-500/20 border border-emerald-500/20 flex items-center justify-center mb-4">
                                                <Sparkles className="w-8 h-8 text-emerald-400" />
                                            </div>
                                            <h4 className="text-white font-semibold mb-2">Ask anything about your data</h4>
                                            <p className="text-white/40 text-sm mb-6 max-w-xs">
                                                I analyze all requests, staff data, geographic patterns, social equity metrics, resident sentiment, and government responsiveness — everything except resident PII.
                                            </p>
                                            <div className="space-y-2 w-full max-w-xs">
                                                {[
                                                    'Which neighborhoods have the highest social vulnerability?',
                                                    'How does resident sentiment vary by category?',
                                                    'What\'s our average triage time and how can we improve?',
                                                    'Are there equity gaps in our response times?',
                                                    'What trends should I watch for this season?',
                                                ].map((q, i) => (
                                                    <button
                                                        key={i}
                                                        onClick={() => { setChatInput(q); }}
                                                        className="w-full text-left px-3 py-2.5 text-sm text-white/70 bg-white/5 border border-white/10 rounded-lg hover:bg-white/10 hover:border-emerald-500/30 transition-all"
                                                    >
                                                        {q}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    )}

                                    {chatMessages.map((msg, i) => (
                                        <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                            <div
                                                className={`max-w-[90%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${msg.role === 'user'
                                                    ? 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white rounded-br-md shadow-lg shadow-emerald-500/10'
                                                    : 'bg-white/[0.03] border border-white/10 text-white/90 rounded-bl-md'
                                                    }`}
                                            >
                                                {msg.role === 'assistant' ? (
                                                    <div
                                                        className="prose prose-invert prose-sm max-w-none [&_p]:mb-2.5 [&_p]:leading-relaxed [&_ul]:mb-2.5 [&_ul]:pl-4 [&_ol]:mb-2.5 [&_ol]:pl-4 [&_li]:mb-1 [&_li]:leading-relaxed [&_h1]:text-lg [&_h1]:font-bold [&_h1]:text-white [&_h1]:mt-4 [&_h1]:mb-2 [&_h2]:text-[15px] [&_h2]:font-semibold [&_h2]:text-emerald-300 [&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:border-b [&_h2]:border-white/10 [&_h2]:pb-1 [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:text-white/90 [&_h3]:mt-3 [&_h3]:mb-1 [&_code]:bg-white/10 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-emerald-300 [&_code]:text-xs [&_strong]:text-emerald-300 [&_strong]:font-semibold [&_em]:text-white/70 [&_table]:w-full [&_table]:my-3 [&_table]:text-xs [&_th]:text-left [&_th]:px-2 [&_th]:py-1.5 [&_th]:border-b [&_th]:border-white/20 [&_th]:text-emerald-300 [&_th]:font-semibold [&_td]:px-2 [&_td]:py-1.5 [&_td]:border-b [&_td]:border-white/5 [&_hr]:border-white/10 [&_hr]:my-3"
                                                        dangerouslySetInnerHTML={{
                                                            __html: (() => {
                                                                let html = msg.content;
                                                                // Escape HTML entities first (except our markdown)
                                                                html = html.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                                                                // Headers (must be before bold processing)
                                                                html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
                                                                html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
                                                                html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
                                                                // Horizontal rules
                                                                html = html.replace(/^---+$/gm, '<hr />');
                                                                // Bold and italic
                                                                html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
                                                                html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
                                                                html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
                                                                // Inline code
                                                                html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
                                                                // Tables
                                                                html = html.replace(/^(\|.+\|)\n(\|[-| :]+\|)\n((?:\|.+\|\n?)+)/gm, (_match, headerRow: string, _sepRow: string, bodyRows: string) => {
                                                                    const headers = headerRow.split('|').filter((c: string) => c.trim()).map((c: string) => `<th>${c.trim()}</th>`).join('');
                                                                    const rows = bodyRows.trim().split('\n').map((row: string) => {
                                                                        const cells = row.split('|').filter((c: string) => c.trim()).map((c: string) => `<td>${c.trim()}</td>`).join('');
                                                                        return `<tr>${cells}</tr>`;
                                                                    }).join('');
                                                                    return `<table><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table>`;
                                                                });
                                                                // Numbered lists
                                                                html = html.replace(/^(\d+)\. (.+)$/gm, '<li data-ol>$2</li>');
                                                                // Unordered lists
                                                                html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
                                                                // Wrap consecutive <li> tags in <ul> or <ol>
                                                                html = html.replace(/((?:<li data-ol>[^]*?<\/li>\n?)+)/g, (match) => {
                                                                    const clean = match.replace(/ data-ol/g, '');
                                                                    return `<ol>${clean}</ol>`;
                                                                });
                                                                html = html.replace(/((?:<li>[^]*?<\/li>\n?)+)/g, '<ul>$1</ul>');
                                                                // Paragraphs: wrap remaining text lines
                                                                html = html.replace(/\n\n/g, '</p><p>');
                                                                html = html.replace(/\n/g, '<br />');
                                                                // Clean up empty paragraphs and extra breaks around block elements
                                                                html = html.replace(/<br \/>\s*(<h[123]>)/g, '$1');
                                                                html = html.replace(/(<\/h[123]>)\s*<br \/>/g, '$1');
                                                                html = html.replace(/<br \/>\s*(<ul>|<ol>|<table>|<hr \/>)/g, '$1');
                                                                html = html.replace(/(<\/ul>|<\/ol>|<\/table>|<hr \/>)\s*<br \/>/g, '$1');
                                                                return html;
                                                            })()
                                                        }}
                                                    />
                                                ) : (
                                                    <span>{msg.content}</span>
                                                )}
                                            </div>
                                        </div>
                                    ))}

                                    {chatLoading && (
                                        <div className="flex justify-start">
                                            <div className="bg-white/[0.03] border border-white/10 rounded-2xl rounded-bl-md px-4 py-3">
                                                <div className="flex items-center gap-2">
                                                    <div className="flex items-center gap-1">
                                                        <div className="w-2 h-2 bg-emerald-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                                                        <div className="w-2 h-2 bg-emerald-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                                                        <div className="w-2 h-2 bg-emerald-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                                                    </div>
                                                    <span className="text-xs text-white/30 ml-1">Analyzing data...</span>
                                                </div>
                                            </div>
                                        </div>
                                    )}
                                    <div ref={chatEndRef} />
                                </div>

                                {/* Input Area */}
                                <form onSubmit={sendChatMessage} className="px-4 py-3 border-t border-white/10 bg-gray-950/80">
                                    <div className="flex items-center gap-2">
                                        <input
                                            type="text"
                                            value={chatInput}
                                            onChange={(e) => setChatInput(e.target.value)}
                                            placeholder="Ask about your data..."
                                            className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/25 transition-all"
                                            disabled={chatLoading}
                                            autoFocus
                                        />
                                        <button
                                            type="submit"
                                            disabled={!chatInput.trim() || chatLoading}
                                            className="w-10 h-10 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 flex items-center justify-center text-white disabled:opacity-30 disabled:cursor-not-allowed hover:from-emerald-700 hover:to-teal-700 transition-all shadow-lg shadow-emerald-500/20"
                                        >
                                            <Send className="w-4 h-4" />
                                        </button>
                                    </div>
                                    <p className="text-[10px] text-white/20 mt-1.5 text-center">Gemini 3.1 Flash-Lite · Equity metrics · Sentiment analysis · All system data except PII</p>
                                </form>
                            </motion.div>
                        </>
                    )}
                </AnimatePresence>

                {/* List/Detail View */}
                {currentView !== 'statistics' && currentView !== 'dashboard' && (
                    <div className="flex-1 flex min-h-0 h-full">
                        {/* Request List Panel */}
                        <div className="w-full lg:w-96 flex flex-col border-r border-white/10 h-full overflow-hidden">
                            {/* List Header with Quick Stats */}
                            <div className="p-4 border-b border-white/10 space-y-3">
                                <div className="flex items-center justify-between">
                                    <h2 className="text-lg font-semibold text-white">Incidents</h2>
                                    <div className="flex items-center gap-2">
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            onClick={() => setShowFilters(!showFilters)}
                                            className={hasActiveFilters ? 'text-primary-400' : ''}
                                        >
                                            <Search className="w-4 h-4" />
                                            {hasActiveFilters && <span className="ml-1 text-xs">•</span>}
                                        </Button>
                                    </div>
                                </div>

                                {/* Assignment Filter Buttons - Premium Styling */}
                                <div className="flex gap-2">
                                    <button
                                        onClick={() => setFilterAssignment("me")}
                                        className={`flex-1 px-4 py-3 rounded-xl text-sm font-semibold transition-all ${filterAssignment === 'me'
                                            ? 'bg-gradient-to-r from-primary-500 to-primary-600 text-white shadow-lg shadow-primary-500/40 ring-2 ring-primary-400/60'
                                            : 'bg-white/5 border border-white/15 text-white/80 hover:bg-white/10 hover:text-white hover:border-white/25'
                                            }`}
                                    >
                                        My Requests ({quickStats.assignedToMe})
                                    </button>
                                    <button
                                        onClick={() => setFilterAssignment("department")}
                                        className={`flex-1 px-4 py-3 rounded-xl text-sm font-semibold transition-all ${filterAssignment === 'department'
                                            ? 'bg-gradient-to-r from-purple-500 to-purple-600 text-white shadow-lg shadow-purple-500/40 ring-2 ring-purple-400/60'
                                            : 'bg-white/5 border border-white/15 text-white/80 hover:bg-white/10 hover:text-white hover:border-white/25'
                                            }`}
                                    >
                                        My Department ({quickStats.inMyDepartment})
                                    </button>
                                    <button
                                        onClick={() => setFilterAssignment("all")}
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
                                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
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
                                    <select
                                        value={sortOrder}
                                        onChange={(e) => setSortOrder(e.target.value as typeof sortOrder)}
                                        className="glass-input text-sm py-2 w-full"
                                        aria-label="Sort order"
                                    >
                                        <option value="newest">Newest First</option>
                                        <option value="oldest">Oldest First</option>
                                        <option value="priority_high">Priority: High → Low</option>
                                        <option value="priority_low">Priority: Low → High</option>
                                        <option value="alpha">Category A → Z</option>
                                    </select>
                                </div>

                                {/* Advanced Filters Panel */}
                                {showFilters && (
                                    <div className="space-y-3 pt-2 border-t border-white/10">
                                        {/* Department Filter */}
                                        <div>
                                            <label className="text-xs text-white/50 mb-1 block">Department</label>
                                            <select
                                                value={filterDepartment ?? ''}
                                                onChange={(e) => setFilterDepartment(e.target.value ? Number(e.target.value) : null)}
                                                className="glass-input text-sm py-2"
                                                aria-label="Filter by department"
                                            >
                                                <option value="">All Departments</option>
                                                {departments.map(d => (
                                                    <option key={d.id} value={d.id}>{d.name}</option>
                                                ))}
                                            </select>
                                        </div>

                                        {/* Service Category Filter */}
                                        <div>
                                            <label className="text-xs text-white/50 mb-1 block">Category</label>
                                            <select
                                                value={filterService ?? ''}
                                                onChange={(e) => setFilterService(e.target.value || null)}
                                                className="glass-input text-sm py-2"
                                                aria-label="Filter by category"
                                            >
                                                <option value="">All Categories</option>
                                                {services.map(s => (
                                                    <option key={s.service_code} value={s.service_code}>{s.service_name}</option>
                                                ))}
                                            </select>
                                        </div>

                                        {/* Priority Filter */}
                                        <div>
                                            <label className="text-xs text-white/50 mb-1 block">Priority Level</label>
                                            <select
                                                value={mapPriorityFilter}
                                                onChange={(e) => setMapPriorityFilter(e.target.value as 'all' | 'high' | 'medium' | 'low')}
                                                className="glass-input text-sm py-2"
                                                aria-label="Filter by priority level"
                                            >
                                                <option value="all">All Priorities</option>
                                                <option value="high">🔴 High (8-10)</option>
                                                <option value="medium">🟡 Medium (5-7)</option>
                                                <option value="low">🟢 Low (1-4)</option>
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
                                            onClick={() => loadRequestDetail(request.service_request_id)}
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
                                            <h3 className="font-medium text-white mb-1">{request.service_name}</h3>
                                            <p className="text-sm text-white/50 line-clamp-2">{request.description}</p>
                                            <div className="flex items-center justify-between mt-2">
                                                <div className="flex items-center gap-2 text-xs text-white/40">
                                                    <Clock className="w-3 h-3" />
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
                                        <ChevronLeft className="w-5 h-5" />
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
                                                </div>
                                                <h1 className="text-base sm:text-lg font-semibold text-white truncate">{selectedRequest.service_name}</h1>
                                            </div>
                                            <PrintWorkOrder
                                                request={selectedRequest}
                                                auditLog={auditLog}
                                                townshipName={settings?.township_name}
                                                logoUrl={settings?.logo_url || undefined}
                                                mapsApiKey={mapsConfig?.google_maps_api_key}
                                            />
                                        </div>

                                        {/* Row 2: Status Actions - Compact on mobile */}
                                        <div className="flex gap-1.5 sm:gap-2">
                                            <button onClick={() => handleStatusChange('open')} className={`flex-1 py-1.5 sm:py-2 px-2 sm:px-3 rounded-lg text-xs sm:text-sm font-medium transition-all ${selectedRequest.status === 'open' ? 'bg-gradient-to-r from-purple-500 to-violet-600 text-white shadow-lg shadow-purple-500/30 ring-2 ring-white/20' : 'bg-white/5 border border-white/10 text-white/70 hover:bg-white/10 hover:text-white'}`}>Open</button>
                                            <button onClick={() => handleStatusChange('in_progress')} className={`flex-1 py-1.5 sm:py-2 px-2 sm:px-3 rounded-lg text-xs sm:text-sm font-medium transition-all ${selectedRequest.status === 'in_progress' ? 'bg-gradient-to-r from-blue-500 to-indigo-600 text-white shadow-lg shadow-blue-500/30 ring-2 ring-white/20' : 'bg-white/5 border border-white/10 text-white/70 hover:bg-white/10 hover:text-white'}`}>In Progress</button>
                                            <button onClick={() => handleStatusChange('closed')} className={`flex-1 py-1.5 sm:py-2 px-2 sm:px-3 rounded-lg text-xs sm:text-sm font-medium transition-all ${selectedRequest.status === 'closed' ? 'bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-500/30 ring-2 ring-white/20' : 'bg-white/5 border border-white/10 text-white/70 hover:bg-white/10 hover:text-white'}`}>Closed</button>
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
                                                    if (demoGuard()) return;
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
                                                    } catch (err) {
                                                        console.error(err);
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
                                                    if (demoGuard()) return;
                                                    if (selectedRequest.flagged !== true) {
                                                        // Show confirmation before placing on legal hold
                                                        if (window.confirm('Place this request under Legal Hold?\n\nThis will prevent the record from being archived or deleted by the retention policy.\n\nContinue?')) {
                                                            try {
                                                                const updated = await api.updateRequest(selectedRequest.service_request_id, {
                                                                    flagged: true
                                                                });
                                                                setSelectedRequest(updated);
                                                                setRequests(prev => prev.map(r => r.id === updated.id ? updated : r));
                                                            } catch (err) {
                                                                console.error('Failed to enable legal hold:', err);
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
                                                        } catch (err) {
                                                            console.error('Failed to remove legal hold:', err);
                                                        }
                                                    }
                                                }}
                                                className={`w-full py-1.5 sm:py-2 px-3 sm:px-4 rounded-lg text-xs sm:text-sm font-medium transition-all flex items-center justify-center gap-1.5 sm:gap-2 ${selectedRequest.flagged === true
                                                    ? 'bg-gradient-to-r from-amber-500 to-orange-600 text-white shadow-lg shadow-amber-500/30 ring-2 ring-white/20'
                                                    : 'bg-white/5 border border-white/10 text-white/70 hover:bg-amber-500/20 hover:text-amber-400 hover:border-amber-500/30'
                                                    }`}
                                                aria-label={selectedRequest.flagged === true ? 'Remove legal hold' : 'Place on legal hold'}
                                            >
                                                <svg className="w-3.5 h-3.5 sm:w-4 sm:h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9" />
                                                </svg>
                                                <span className="hidden sm:inline">{selectedRequest.flagged === true ? 'Under Legal Hold (Click to Remove)' : 'Place on Legal Hold'}</span>
                                                <span className="sm:hidden">{selectedRequest.flagged === true ? 'Legal Hold ✓' : 'Legal Hold'}</span>
                                            </button>
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
                                                        <FileText className="w-4 h-4" />
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
                                            {selectedRequest.media_urls && selectedRequest.media_urls.length > 0 && (
                                                <div className="flex gap-2 overflow-x-auto pb-2 mb-4">
                                                    {selectedRequest.media_urls.map((url, i) => (
                                                        <img key={i} src={url} alt={`Photo ${i + 1}`} className="w-28 h-20 flex-shrink-0 object-cover rounded-lg cursor-pointer hover:opacity-80 ring-1 ring-white/10" onClick={() => setLightboxUrl(url)} />
                                                    ))}
                                                </div>
                                            )}

                                            {/* AI Analysis - Premium Enhanced Display (Now BELOW Photos) */}
                                            {(() => {
                                                const ai = selectedRequest.ai_analysis as any;
                                                const priorityScore = ai?.priority_score ?? null;
                                                const qualitativeText = ai?.qualitative_analysis ?? selectedRequest.vertex_ai_summary ?? null;
                                                const hasError = ai?._error;

                                                if (!ai && !qualitativeText) return null;

                                                return (
                                                    <div
                                                        className={`relative overflow-hidden rounded-xl bg-slate-800/40 border border-white/10 mb-4 backdrop-blur-sm ${!isAIExpanded ? 'cursor-pointer hover:bg-slate-800/60 transition-colors' : ''}`}
                                                        onClick={!isAIExpanded ? () => setIsAIExpanded(true) : undefined}
                                                    >
                                                        {/* Professional accent line */}
                                                        <div className="absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r from-primary-500/50 via-purple-500/50 to-primary-500/50" />

                                                        <div className="p-4">
                                                            {/* Simple Header - Just label and expand toggle */}
                                                            <button
                                                                onClick={() => setIsAIExpanded(!isAIExpanded)}
                                                                className="w-full flex items-center justify-between mb-3"
                                                            >
                                                                <div className="flex items-center gap-3">
                                                                    <div className="p-2 rounded-xl bg-gradient-to-br from-primary-500/20 to-purple-500/20 ring-1 ring-white/10">
                                                                        <Brain className="w-5 h-5 text-primary-400" />
                                                                    </div>
                                                                    <div className="text-left">
                                                                        <span className="text-sm font-semibold text-white">AI Analysis</span>
                                                                        <p className="text-[10px] text-white/40">Gemini 3.1 Flash-Lite</p>
                                                                    </div>
                                                                </div>
                                                                <ChevronDown className={`w-5 h-5 text-white/40 transition-transform ${isAIExpanded ? 'rotate-180' : ''}`} />
                                                            </button>

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
                                                                                <Check className="w-5 h-5" />
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
                                                                                    } catch (e) {
                                                                                        console.error('Failed to accept AI priority:', e);
                                                                                    } finally {
                                                                                        setIsUpdatingPriority(false);
                                                                                    }
                                                                                }}
                                                                                disabled={isUpdatingPriority}
                                                                                className="flex-1 py-3 px-4 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 font-semibold text-sm transition-all flex items-center justify-center gap-2 border border-emerald-500/30 active:scale-[0.98]"
                                                                            >
                                                                                <Check className="w-5 h-5" />
                                                                                Accept AI Priority
                                                                            </button>
                                                                            <button
                                                                                onClick={() => {
                                                                                    setShowPriorityEditor(!showPriorityEditor);
                                                                                    setPendingPriority(selectedRequest.manual_priority_score ?? priorityScore ?? 5);
                                                                                }}
                                                                                className="py-3 px-4 rounded-xl bg-white/5 hover:bg-white/10 text-white/70 font-medium text-sm transition-all flex items-center justify-center gap-2 border border-white/10 active:scale-[0.98]"
                                                                            >
                                                                                <Edit3 className="w-4 h-4" />
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
                                                                            <Edit3 className="w-4 h-4" />
                                                                            Change Priority
                                                                        </button>
                                                                    )}

                                                                    {/* Priority Editor - Full Width Inline */}
                                                                    {showPriorityEditor && (
                                                                        <div className="p-4 rounded-xl bg-slate-800/80 border border-white/10 space-y-4 max-w-md">
                                                                            <p className="text-sm text-white/70 font-medium">Set Priority Level</p>
                                                                            <div className="grid grid-cols-5 gap-2">
                                                                                {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(p => (
                                                                                    <button
                                                                                        key={p}
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
                                                                                        if (demoGuard()) return;
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
                                                                                        } catch (e) {
                                                                                            console.error('Failed to update priority:', e);
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
                                                                                        if (demoGuard()) return;
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
                                                                                        } catch (e) {
                                                                                            console.error('Failed to clear priority:', e);
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
                                                                <>
                                                                    {/* Content Moderation Warning */}
                                                                    {ai?.content_flags && ai.content_flags.length > 0 && !ai.content_flags.includes('none') && (
                                                                        <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 flex items-start gap-2.5">
                                                                            <AlertTriangle className="w-4 h-4 text-red-400 mt-0.5 flex-shrink-0" />
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
                                                                                <Camera className="w-3.5 h-3.5" />
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
                                                                                    <p className="text-[9px] uppercase tracking-wider text-white/30 mb-0.5">Severity</p>
                                                                                    <p className={`text-xs font-bold ${ai.quantitative_metrics.estimated_severity === 'critical' ? 'text-red-400' :
                                                                                        ai.quantitative_metrics.estimated_severity === 'high' ? 'text-amber-400' :
                                                                                            ai.quantitative_metrics.estimated_severity === 'medium' ? 'text-blue-400' : 'text-green-400'
                                                                                        }`}>{ai.quantitative_metrics.estimated_severity.toUpperCase()}</p>
                                                                                </div>
                                                                            )}
                                                                            {ai.quantitative_metrics.systemic_failure_probability !== undefined && (
                                                                                <div className="p-2.5 rounded-lg bg-white/5 border border-white/5">
                                                                                    <p className="text-[9px] uppercase tracking-wider text-white/30 mb-0.5">Systemic Risk</p>
                                                                                    <div className="flex items-center gap-1.5">
                                                                                        <p className={`text-xs font-bold ${ai.quantitative_metrics.systemic_failure_probability > 0.7 ? 'text-red-400' : 'text-primary-400'}`}>
                                                                                            {(ai.quantitative_metrics.systemic_failure_probability * 100).toFixed(0)}%
                                                                                        </p>
                                                                                        <Activity className={`w-3 h-3 ${ai.quantitative_metrics.systemic_failure_probability > 0.7 ? 'text-red-400' : 'text-primary-400'}`} />
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
                                                                                    <Shield className="w-3.5 h-3.5 text-blue-400 mt-0.5 flex-shrink-0" />
                                                                                    <div className="flex-1">
                                                                                        <p className="text-[9px] font-bold text-blue-400 uppercase tracking-tight">Infrastructure Proximity</p>
                                                                                        <p className="text-[11px] text-blue-200/70">
                                                                                            {typeof ai.diagnostic_context.infrastructure_proximity === 'object'
                                                                                                ? ai.diagnostic_context.infrastructure_proximity.details
                                                                                                : ai.diagnostic_context.infrastructure_proximity}
                                                                                        </p>
                                                                                        {ai.diagnostic_context.infrastructure_proximity?.evidence && (
                                                                                            <p className="mt-1 text-[9px] text-blue-400/50 font-medium italic">
                                                                                                Evidence: {ai.diagnostic_context.infrastructure_proximity.evidence}
                                                                                            </p>
                                                                                        )}
                                                                                    </div>
                                                                                </div>
                                                                            )}
                                                                            {ai.diagnostic_context.historical_trend && (
                                                                                <div className="px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/10 flex items-start gap-2.5">
                                                                                    <History className="w-3.5 h-3.5 text-amber-400 mt-0.5 flex-shrink-0" />
                                                                                    <div className="flex-1">
                                                                                        <p className="text-[9px] font-bold text-amber-400 uppercase tracking-tight">Historical Trend</p>
                                                                                        <p className="text-[11px] text-amber-200/70">
                                                                                            {typeof ai.diagnostic_context.historical_trend === 'object'
                                                                                                ? ai.diagnostic_context.historical_trend.details
                                                                                                : ai.diagnostic_context.historical_trend}
                                                                                        </p>
                                                                                        {ai.diagnostic_context.historical_trend?.evidence && (
                                                                                            <p className="mt-1 text-[9px] text-amber-400/50 font-medium italic">
                                                                                                Evidence: {ai.diagnostic_context.historical_trend.evidence}
                                                                                            </p>
                                                                                        )}
                                                                                    </div>
                                                                                </div>
                                                                            )}
                                                                            {ai.diagnostic_context.weather_impact && ai.diagnostic_context.weather_impact !== 'None' && (
                                                                                <div className="px-3 py-2 rounded-lg bg-primary-500/5 border border-primary-500/10 flex items-start gap-2.5">
                                                                                    <Cloud className="w-3.5 h-3.5 text-primary-400 mt-0.5 flex-shrink-0" />
                                                                                    <div className="flex-1">
                                                                                        <p className="text-[9px] font-bold text-primary-400 uppercase tracking-tight">Weather Criticality</p>
                                                                                        <p className="text-[11px] text-primary-200/70">
                                                                                            {typeof ai.diagnostic_context.weather_impact === 'object'
                                                                                                ? ai.diagnostic_context.weather_impact.details
                                                                                                : ai.diagnostic_context.weather_impact}
                                                                                        </p>
                                                                                        {ai.diagnostic_context.weather_impact?.evidence && (
                                                                                            <p className="mt-1 text-[9px] text-primary-400/50 font-medium italic">
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
                                                                            <Link2 className="w-3.5 h-3.5 text-purple-400 mt-0.5 flex-shrink-0" />
                                                                            <div className="flex-1">
                                                                                <p className="text-[9px] font-bold text-purple-400 uppercase tracking-tight">Similar Reports</p>
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
                                                                                                <span className="text-[9px] text-purple-400/60">{Math.round(report.similarity * 100)}% match</span>
                                                                                            </div>
                                                                                            <p className="text-[9px] text-purple-200/50 mt-0.5 line-clamp-1">{report.description}</p>
                                                                                            {report.justification && (
                                                                                                <p className="text-[8px] text-purple-400/40 mt-0.5 italic">{report.justification}</p>
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
                                                                        {selectedRequest.vertex_ai_analyzed_at && (
                                                                            <p className="text-white/20 text-[9px]">
                                                                                Analyzed {new Date(selectedRequest.vertex_ai_analyzed_at).toLocaleString()}
                                                                            </p>
                                                                        )}
                                                                        {!hasError && (
                                                                            <div className="flex items-center gap-1.5">
                                                                                <div className="w-1.5 h-1.5 rounded-full bg-green-500/50 animate-pulse" />
                                                                                <p className="text-[9px] text-white/30 font-medium">
                                                                                    Visual + Spatial Context Integrated
                                                                                </p>
                                                                            </div>
                                                                        )}
                                                                    </div>
                                                                </>
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
                                                    {selectedRequest.completion_photo_url && (
                                                        <img
                                                            src={selectedRequest.completion_photo_url}
                                                            alt="Completion photo"
                                                            className="rounded-lg max-h-64 object-contain cursor-pointer hover:opacity-90 transition-opacity"
                                                            onClick={() => selectedRequest.completion_photo_url && window.open(selectedRequest.completion_photo_url, '_blank')}
                                                        />
                                                    )}
                                                </div>
                                            )}

                                            {/* Reporter Info - Simple inline */}
                                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-white/60 pt-3 border-t border-white/10">
                                                {(selectedRequest.first_name || selectedRequest.last_name) && (
                                                    <span className="flex items-center gap-1"><User className="w-3.5 h-3.5" /> {selectedRequest.first_name} {selectedRequest.last_name}</span>
                                                )}
                                                <a href={`mailto:${selectedRequest.email}`} className="flex items-center gap-1 hover:text-primary-400"><Mail className="w-3.5 h-3.5" /> {selectedRequest.email}</a>
                                                {selectedRequest.phone && (
                                                    <a href={`tel:${selectedRequest.phone}`} className="flex items-center gap-1 hover:text-primary-400"><Phone className="w-3.5 h-3.5" /> {selectedRequest.phone}</a>
                                                )}
                                            </div>
                                        </div>

                                        {/* ═══ SECTION 2: Location & Map ═══ */}
                                        {
                                            (selectedRequest.address || selectedRequest.lat) && (
                                                <div className="p-4 rounded-lg bg-slate-800/50 border border-white/10">
                                                    <div className="flex items-center gap-2 mb-3">
                                                        <MapPin className="w-4 h-4 text-blue-400" />
                                                        <span className="font-medium text-white">Location</span>
                                                    </div>
                                                    {selectedRequest.address && (
                                                        <p className="text-white/80 mb-3">{selectedRequest.address}</p>
                                                    )}
                                                    {/* Interactive Google Maps with Asset Overlay */}
                                                    {selectedRequest.lat && selectedRequest.long && mapsConfig?.google_maps_api_key && (
                                                        <div className="rounded-lg overflow-hidden h-64 bg-slate-900">
                                                            <RequestDetailMap
                                                                lat={selectedRequest.lat}
                                                                lng={selectedRequest.long}
                                                                matchedAsset={(selectedRequest as any).matched_asset}
                                                                mapLayers={mapLayers}
                                                                apiKey={mapsConfig.google_maps_api_key}
                                                            />
                                                        </div>
                                                    )}
                                                    {/* Fallback for no API key */}
                                                    {selectedRequest.lat && selectedRequest.long && !mapsConfig?.google_maps_api_key && (
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
                                                                <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-500/70">🔗 Matched Asset</span>
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
                                                                    <span className="text-[10px] font-semibold uppercase tracking-wider text-emerald-500/70">📋 Asset History</span>
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
                                                <Clock className="w-4 h-4 text-blue-400" />
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
                                        <div className="p-4 rounded-lg bg-slate-800/50 border border-white/10">
                                            <div className="flex items-center gap-2 mb-4">
                                                <MessageSquare className="w-4 h-4 text-blue-400" />
                                                <span className="font-medium text-white">Comments</span>
                                                {comments.length > 0 && (
                                                    <span className="px-2 py-0.5 rounded-full text-xs bg-white/10 text-white/60">{comments.length}</span>
                                                )}
                                            </div>

                                            {/* Comments List */}
                                            {comments.length > 0 && (
                                                <div className="space-y-3 max-h-64 overflow-y-auto mb-4 pr-1">
                                                    {comments.map(c => (
                                                        <div key={c.id} className={`rounded-lg overflow-hidden ${c.visibility === 'internal' ? 'bg-orange-500/5' : 'bg-slate-700/30'}`}>
                                                            {/* Comment Header */}
                                                            <div className={`px-3 py-2 flex items-center gap-2 text-xs ${c.visibility === 'internal' ? 'bg-orange-500/10 border-b border-orange-500/20' : 'bg-slate-600/30 border-b border-white/5'}`}>
                                                                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold ${c.visibility === 'internal' ? 'bg-orange-500/20 text-orange-400' : 'bg-blue-500/20 text-blue-400'}`}>
                                                                    {c.username?.charAt(0).toUpperCase() || '?'}
                                                                </div>
                                                                <span className="font-medium text-white/90">{c.username}</span>
                                                                <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${c.visibility === 'internal' ? 'bg-orange-500/20 text-orange-400' : 'bg-green-500/20 text-green-400'}`}>
                                                                    {c.visibility === 'internal' ? 'Internal' : 'Public'}
                                                                </span>
                                                                <span className="text-white/30 ml-auto">{c.created_at ? new Date(c.created_at).toLocaleString() : ''}</span>
                                                            </div>
                                                            {/* Comment Body */}
                                                            <div className="px-3 py-2.5">
                                                                <p className="text-sm text-white/80 leading-relaxed">{c.content}</p>
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}

                                            {comments.length === 0 && (
                                                <div className="text-center py-6 text-white/30 text-sm mb-4">
                                                    No comments yet
                                                </div>
                                            )}

                                            {/* Add Comment */}
                                            <div className={`rounded-lg overflow-hidden ${commentVisibility === 'internal' ? 'bg-orange-950/20 border border-orange-500/20' : 'bg-green-950/20 border border-green-500/20'}`}>
                                                <div className="px-3 py-2 flex items-center gap-2 border-b border-white/5">
                                                    <span className={`text-xs font-semibold ${commentVisibility === 'internal' ? 'text-orange-400' : 'text-green-400'}`}>
                                                        {commentVisibility === 'internal' ? '🔒 Internal Note - Staff Only' : '🌐 Public Reply - Visible to Reporter'}
                                                    </span>
                                                    <button
                                                        onClick={() => setCommentVisibility(commentVisibility === 'internal' ? 'external' : 'internal')}
                                                        className={`ml-auto px-2 py-1 rounded text-xs font-medium transition-all ${commentVisibility === 'internal' ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30' : 'bg-orange-500/20 text-orange-400 hover:bg-orange-500/30'}`}
                                                    >
                                                        Switch to {commentVisibility === 'internal' ? 'Public' : 'Internal'}
                                                    </button>
                                                </div>
                                                <div className="p-3 flex gap-2">
                                                    <input
                                                        type="text"
                                                        placeholder={commentVisibility === 'internal' ? 'Add internal note...' : 'Reply to reporter...'}
                                                        aria-label={commentVisibility === 'internal' ? 'Add internal note' : 'Reply to reporter'}
                                                        value={newComment}
                                                        onChange={(e) => setNewComment(e.target.value)}
                                                        onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleAddComment()}
                                                        className="flex-1 py-2 px-3 rounded-lg bg-slate-900/50 border border-white/10 text-white text-sm placeholder:text-white/30 focus:outline-none focus:ring-1 focus:ring-blue-500"
                                                    />
                                                    <button
                                                        onClick={handleAddComment}
                                                        disabled={!newComment.trim() || isSubmittingComment}
                                                        className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium disabled:opacity-50 flex items-center gap-2 transition-colors"
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
                                                <div className="relative flex-1">
                                                    <button
                                                        onClick={() => setShowShareMenu(!showShareMenu)}
                                                        className="w-full py-2.5 px-4 rounded-lg bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium flex items-center justify-center gap-2 transition-colors"
                                                    >
                                                        <Link className="w-4 h-4" />
                                                        Share Link
                                                        <ChevronDown className={`w-4 h-4 transition-transform ${showShareMenu ? 'rotate-180' : ''}`} />
                                                    </button>

                                                    {showShareMenu && (
                                                        <div className="absolute bottom-full left-0 right-0 mb-2 bg-slate-800 rounded-lg border border-white/10 shadow-xl overflow-hidden z-20">
                                                            <button
                                                                onClick={() => {
                                                                    // Use current status for staff link (active, in_progress, resolved)
                                                                    const statusPath = selectedRequest.status === 'open' ? 'active' :
                                                                        selectedRequest.status === 'in_progress' ? 'in_progress' : 'resolved';
                                                                    navigator.clipboard.writeText(`${window.location.origin}/staff#${statusPath}/request/${selectedRequest.service_request_id}`);
                                                                    setCopiedLink('staff');
                                                                    setTimeout(() => { setCopiedLink(null); setShowShareMenu(false); }, 1500);
                                                                }}
                                                                className="w-full px-4 py-3 flex items-center gap-3 hover:bg-white/5 transition-colors text-left"
                                                            >
                                                                <div className="w-8 h-8 rounded-lg bg-purple-500/20 flex items-center justify-center">
                                                                    {copiedLink === 'staff' ? <Check className="w-4 h-4 text-green-400" /> : <Link className="w-4 h-4 text-purple-400" />}
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
                                                                onClick={() => {
                                                                    // Resident portal uses /#track/ID format
                                                                    navigator.clipboard.writeText(`${window.location.origin}/#track/${selectedRequest.service_request_id}`);
                                                                    setCopiedLink('resident');
                                                                    setTimeout(() => { setCopiedLink(null); setShowShareMenu(false); }, 1500);
                                                                }}
                                                                className="w-full px-4 py-3 flex items-center gap-3 hover:bg-white/5 transition-colors text-left"
                                                            >
                                                                <div className="w-8 h-8 rounded-lg bg-blue-500/20 flex items-center justify-center">
                                                                    {copiedLink === 'resident' ? <Check className="w-4 h-4 text-green-400" /> : <ExternalLink className="w-4 h-4 text-blue-400" />}
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

                                                <button onClick={() => setShowDeleteModal(true)} className="py-2.5 px-4 rounded-lg bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 text-red-400 text-sm font-medium flex items-center gap-2 transition-colors">
                                                    <Trash2 className="w-4 h-4" />
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            ) : (
                                <div className="flex-1 flex items-center justify-center text-white/40">
                                    <div className="text-center">
                                        <FileText className="w-12 h-12 mx-auto mb-3 opacity-50" />
                                        <p className="text-sm">Select an incident</p>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                )
                }
            </div>

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
                    <p className="text-white/70 text-sm">Select a resolution type for this request:</p>

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
                                    <Camera className="w-4 h-4" />
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
                            <Trash2 className="w-5 h-5" />
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

            {/* Premium Photo Lightbox Modal */}
            {
                lightboxUrl && (
                    <div
                        className="fixed inset-0 z-[100] flex items-center justify-center p-4 md:p-8"
                        onClick={() => setLightboxUrl(null)}
                    >
                        {/* Backdrop with blur */}
                        <div className="absolute inset-0 bg-black/95 backdrop-blur-xl" />

                        {/* Close button */}
                        <button
                            onClick={() => setLightboxUrl(null)}
                            className="absolute top-4 right-4 md:top-6 md:right-6 z-20 p-2 rounded-full bg-white/10 hover:bg-white/20 border border-white/20 transition-all duration-300 group"
                            aria-label="Close image preview"
                        >
                            <X className="w-6 h-6 text-white group-hover:rotate-90 transition-transform duration-300" aria-hidden="true" />
                        </button>

                        {/* Image container with premium styling */}
                        <div
                            className="relative z-10 max-w-[90vw] max-h-[85vh] rounded-2xl overflow-hidden shadow-2xl ring-1 ring-white/20"
                            onClick={(e) => e.stopPropagation()}
                        >
                            {/* Gradient glow effect behind image */}
                            <div className="absolute -inset-1 bg-gradient-to-r from-primary-500/30 via-purple-500/30 to-primary-500/30 blur-xl opacity-50" />

                            {/* Image */}
                            <img
                                src={lightboxUrl}
                                alt="Full size preview"
                                className="relative max-w-full max-h-[85vh] object-contain bg-gray-900/50 rounded-2xl"
                            />
                        </div>

                        {/* Instructions */}
                        <p className="absolute bottom-4 left-1/2 -translate-x-1/2 text-white/50 text-sm">
                            Click anywhere to close
                        </p>
                    </div>
                )
            }
            {/* Notification Settings Modal */}
            <NotificationSettings
                isOpen={showNotificationSettings}
                onClose={() => setShowNotificationSettings(false)}
                userName={user?.full_name || user?.username || 'User'}
            />
            {/* Activity Feed Panel */}
            <ActivityFeed
                isOpen={showActivityFeed}
                onClose={() => setShowActivityFeed(false)}
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

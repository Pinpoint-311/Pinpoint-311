import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
    Menu,
    X,
    Palette,
    Users,
    Grid3X3,
    Key,

    LogOut,
    Save,
    Trash2,
    Plus,
    RefreshCw,
    Sparkles,
    Check,
    AlertTriangle,
    RotateCcw,
    Mail,
    MessageSquare,
    Building2,
    Edit,
    Phone,
    UserCheck,
    AlertCircle,
    Car,
    Trash,
    Lightbulb,
    TreePine,
    Building,
    Hammer,
    Droplet,
    Bug,
    PaintBucket,
    Wrench,
    Route,
    MapPin,
    Home,
    Zap,
    Shield,
    Heart,
    Star,
    Flag,
    Bell,
    Camera,
    Clock,
    FileText,
    Settings,
    HelpCircle,
    Info,
    Layers,
    Upload,
    BarChart3,
    Terminal,
    Copy,
    ExternalLink,
    ChevronDown,
    User as UserIcon,
    type LucideIcon,
} from 'lucide-react';
import { Button, Card, Modal, Input, Select, Badge, AccordionSection } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { useSettings } from '../context/SettingsContext';
import { useDialog } from '../components/DialogProvider';
import { api, MapLayer } from '../services/api';
import { User, ServiceDefinition, SystemSettings, SystemSecret, Department } from '../types';
import { usePageNavigation } from '../hooks/usePageNavigation';
import OperationsPanel from '../components/OperationsPanel';
import SetupIntegrationsPage from '../components/SetupIntegrationsPage';
import AuditLogViewer from '../components/AuditLogViewer';
import VersionSwitcher from '../components/VersionSwitcher';

// Icon library for service categories
const ICON_LIBRARY: { name: string; icon: LucideIcon }[] = [
    { name: 'AlertCircle', icon: AlertCircle },
    { name: 'Car', icon: Car },
    { name: 'Trash', icon: Trash },
    { name: 'Lightbulb', icon: Lightbulb },
    { name: 'TreePine', icon: TreePine },
    { name: 'Building', icon: Building },
    { name: 'Hammer', icon: Hammer },
    { name: 'Droplet', icon: Droplet },
    { name: 'Bug', icon: Bug },
    { name: 'PaintBucket', icon: PaintBucket },
    { name: 'Wrench', icon: Wrench },
    { name: 'Route', icon: Route },
    { name: 'MapPin', icon: MapPin },
    { name: 'Home', icon: Home },
    { name: 'Zap', icon: Zap },
    { name: 'Shield', icon: Shield },
    { name: 'Heart', icon: Heart },
    { name: 'Star', icon: Star },
    { name: 'Flag', icon: Flag },
    { name: 'Bell', icon: Bell },
    { name: 'Camera', icon: Camera },
    { name: 'Mail', icon: Mail },
    { name: 'Phone', icon: Phone },
    { name: 'Clock', icon: Clock },
    { name: 'FileText', icon: FileText },
    { name: 'Settings', icon: Settings },
    { name: 'HelpCircle', icon: HelpCircle },
    { name: 'Info', icon: Info },
    { name: 'Users', icon: Users },
];

type Tab = 'branding' | 'users' | 'departments' | 'services' | 'integration' | 'system' | 'health' | 'compliance';

// Sidebar accordion components
interface SidebarGroupProps {
    title: string;
    icon: LucideIcon;
    isActive: boolean;
    defaultOpen?: boolean;
    children: React.ReactNode;
}

function SidebarGroup({ title, icon: Icon, isActive, defaultOpen = false, children }: SidebarGroupProps) {
    const [isOpen, setIsOpen] = useState(defaultOpen);

    // Auto-open when active
    React.useEffect(() => {
        if (isActive && !isOpen) {
            setIsOpen(true);
        }
    }, [isActive]);

    return (
        <div className="rounded-xl overflow-hidden">
            <button
                onClick={() => setIsOpen(!isOpen)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors ${isActive ? 'bg-white/10 text-white' : 'text-white/60 hover:bg-white/5 hover:text-white'
                    }`}
            >
                <Icon className="w-5 h-5" />
                <span className="font-medium flex-1 text-left">{title}</span>
                <motion.div
                    animate={{ rotate: isOpen ? 180 : 0 }}
                    transition={{ duration: 0.2 }}
                >
                    <ChevronDown className="w-4 h-4 opacity-50" />
                </motion.div>
            </button>
            <AnimatePresence initial={false}>
                {isOpen && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2, ease: 'easeInOut' }}
                        className="overflow-hidden"
                    >
                        <div className="pl-4 py-1 space-y-1">
                            {children}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}

interface SidebarItemProps {
    icon: LucideIcon;
    label: string;
    isActive: boolean;
    onClick: () => void;
}

function SidebarItem({ icon: Icon, label, isActive, onClick }: SidebarItemProps) {
    return (
        <button
            onClick={onClick}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-colors text-sm ${isActive
                ? 'bg-primary-500/20 text-white'
                : 'text-white/50 hover:bg-white/5 hover:text-white'
                }`}
        >
            <Icon className="w-4 h-4" />
            <span className="font-medium">{label}</span>
        </button>
    );
}

export default function AdminConsole() {
    const navigate = useNavigate();
    const { user, logout } = useAuth();
    const { settings, refreshSettings } = useSettings();
    const dialog = useDialog();

    const [sidebarOpen, setSidebarOpen] = useState(false);
    const [currentTab, setCurrentTab] = useState<Tab>('branding');
    const [isLoading, setIsLoading] = useState(false);
    const [saveMessage, setSaveMessage] = useState<string | null>(null);
    const contentRef = useRef<HTMLDivElement>(null);

    // URL hashing, dynamic titles, and scroll-to-top
    const { updateHash, updateTitle, scrollToTop } = usePageNavigation({
        baseTitle: settings?.township_name ? `Admin Console | ${settings.township_name}` : 'Admin Console',
        scrollContainerRef: contentRef,
    });

    // Update hash and title when tab changes
    useEffect(() => {
        updateHash(currentTab);
        const tabTitles: Record<Tab, string> = {
            branding: 'Branding',
            users: 'User Management',
            departments: 'Departments',
            services: 'Service Categories',
            integration: 'Setup & Integration',
            system: 'System Settings',
            health: 'System Health',
            compliance: 'Compliance'
        };
        updateTitle(tabTitles[currentTab]);
        scrollToTop('instant');
    }, [currentTab, updateHash, updateTitle, scrollToTop]);

    // Branding state
    const [brandingForm, setBrandingForm] = useState<Partial<SystemSettings>>({});

    // Users state
    const [users, setUsers] = useState<User[]>([]);
    const [showUserModal, setShowUserModal] = useState(false);
    const [newUser, setNewUser] = useState({
        username: '',
        email: '',
        full_name: '',
        role: 'staff' as 'staff' | 'admin',
        department_ids: [] as number[],
    });

    // Services state
    const [services, setServices] = useState<ServiceDefinition[]>([]);
    const [departments, setDepartments] = useState<Department[]>([]);
    const [showServiceModal, setShowServiceModal] = useState(false);
    const [editingService, setEditingService] = useState<ServiceDefinition | null>(null);
    const [newService, setNewService] = useState({
        service_code: '',
        service_name: '',
        description: '',
        icon: 'AlertCircle',
    });

    // Service routing edit state
    const [showServiceEditModal, setShowServiceEditModal] = useState(false);
    const [serviceRouting, setServiceRouting] = useState({
        routing_mode: 'township' as 'township' | 'third_party' | 'road_based',
        assigned_department_id: null as number | null,
        icon: 'AlertCircle',
        routing_config: {
            // Township mode
            route_to: 'all_staff' as 'all_staff' | 'specific_staff',
            staff_ids: [] as number[],
            // Third party mode
            message: '',
            contacts: [] as { name: string; phone: string; url: string }[],
            // Road-based mode
            default_handler: 'township' as 'township' | 'third_party',
            exclusion_list: '', // County roads (when township is default)
            inclusion_list: '', // Township roads (when third party is default)
            third_party_message: '',
            third_party_contacts: [] as { name: string; phone: string; url: string }[],
            // Custom questions
            custom_questions: [] as { id: string; label: string; type: string; options: string[]; required: boolean; placeholder: string }[],
        },
    });

    // Department management state
    const [showDepartmentModal, setShowDepartmentModal] = useState(false);
    const [editingDepartment, setEditingDepartment] = useState<Department | null>(null);
    const [newDepartment, setNewDepartment] = useState({
        name: '',
        description: '',
        routing_email: '',
    });

    // Secrets state
    const [secrets, setSecrets] = useState<SystemSecret[]>([]);
    const [secretValues, setSecretValues] = useState<Record<string, string>>({});

    // Modules state
    const [modules, setModules] = useState({ ai_analysis: false, sms_alerts: false, email_notifications: false, research_portal: false });

    // Maps tab state
    const [mapsApiKey, setMapsApiKey] = useState<string | null>(null);
    const [townshipSearch, setTownshipSearch] = useState('');
    const [osmSearchResults, setOsmSearchResults] = useState<Array<{
        osm_id: number;
        display_name: string;
        type: string;
        class: string;
        lat: string;
        lon: string;
    }>>([]);
    const [selectedOsmResult, setSelectedOsmResult] = useState<{
        osm_id: number;
        display_name: string;
        lat: string;
        lon: string;
        geojson?: object;  // Boundary GeoJSON from Nominatim
    } | null>(null);
    const [townshipBoundary, setTownshipBoundary] = useState<object | null>(null);


    const [isSearchingTownship, setIsSearchingTownship] = useState(false);
    const [isFetchingBoundary, setIsFetchingBoundary] = useState(false);


    // Custom map layers state
    const [mapLayers, setMapLayers] = useState<MapLayer[]>([]);
    const [showLayerModal, setShowLayerModal] = useState(false);
    const [editingLayer, setEditingLayer] = useState<MapLayer | null>(null);
    const [newLayer, setNewLayer] = useState({
        name: '',
        description: '',
        layer_type: '' as '' | 'point' | 'polygon', // User must select first
        fill_color: '#3b82f6',
        stroke_color: '#1d4ed8',
        fill_opacity: 0.3,
        stroke_width: 2,
        service_codes: [] as string[],
        geojson: null as object | null,
        // Polygon routing options
        routing_mode: 'log' as 'log' | 'block', // log=log in report, block=redirect to third party
        routing_config: null as { message?: string; contacts?: { name: string; phone: string; url: string }[] } | null,
        visible_on_map: true, // Whether to show the layer visually on the map
    });
    // Nominatim search state for polygon boundaries
    const [nominatimSearch, setNominatimSearch] = useState('');
    const [nominatimResults, setNominatimResults] = useState<{ display_name: string; osm_id: number; osm_type: string }[]>([]);
    const [isSearchingNominatim, setIsSearchingNominatim] = useState(false);


    // SSO users don't have passwords - authentication handled by Auth0

    // Update in progress
    const [isUpdating, setIsUpdating] = useState(false);
    const [updateMessage, setUpdateMessage] = useState<string | null>(null);

    // Document Retention state
    const [retentionStates, setRetentionStates] = useState<Array<{
        code: string;
        name: string;
        retention_days: number;
        retention_years: number;
        source: string;
    }>>([]);
    const [retentionPolicy, setRetentionPolicy] = useState<{
        state_code: string;
        policy: { name: string; retention_days: number; retention_years: number; source: string; public_records_law: string };
        override_days: number | null;
        effective_days: number;
        mode: 'anonymize' | 'delete';
        stats: { eligible_for_archival: number; under_legal_hold: number; already_archived: number; cutoff_date: string };
    } | null>(null);
    const [selectedStateCode, setSelectedStateCode] = useState<string>('');
    const [selectedMode, setSelectedMode] = useState<'anonymize' | 'delete'>('anonymize');
    const [overrideDays, setOverrideDays] = useState<string>('');
    const [isSavingRetention, setIsSavingRetention] = useState(false);
    const [isRunningRetention, setIsRunningRetention] = useState(false);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const [deletedRequests, setDeletedRequests] = useState<any[]>([]);

    // Legal hold modal state
    const [showLegalHoldModal, setShowLegalHoldModal] = useState(false);
    const [legalHoldRequests, setLegalHoldRequests] = useState<Array<{
        id: number;
        service_request_id: string;
        service_name: string;
        description: string;
        status: string;
        address: string;
        requested_datetime: string;
        closed_datetime: string | null;
    }>>([]);
    const [isLoadingLegalHold, setIsLoadingLegalHold] = useState(false);

    // Backup management state
    const [backupStatus, setBackupStatus] = useState<{
        configured: boolean;
        message?: string;
        bucket?: string;
        last_backup?: { name: string; size_bytes: number; created_at: string; age_days: number } | null;
        total_backups?: number;
        next_scheduled?: string;
        required_secrets?: string[];
    } | null>(null);
    const [backups, setBackups] = useState<Array<{
        name: string;
        size_bytes: number;
        created_at: string;
        age_days: number;
    }>>([]);
    const [isLoadingBackups, setIsLoadingBackups] = useState(false);
    const [isCreatingBackup, setIsCreatingBackup] = useState(false);

    useEffect(() => {
        if (settings) {
            setBrandingForm({
                township_name: settings.township_name,
                logo_url: settings.logo_url || '',
                favicon_url: settings.favicon_url || '',
                hero_text: settings.hero_text,
                primary_color: settings.primary_color,
            });
            setModules({
                ai_analysis: settings.modules?.ai_analysis || false,
                sms_alerts: settings.modules?.sms_alerts || false,
                email_notifications: settings.modules?.email_notifications || false,
                research_portal: settings.modules?.research_portal || false,
            });
        }
    }, [settings]);

    useEffect(() => {
        loadTabData();
    }, [currentTab]);

    const loadTabData = async () => {
        setIsLoading(true);
        try {
            switch (currentTab) {
                case 'users':
                    const [usersData, userDepts] = await Promise.all([
                        api.getUsers(),
                        api.getDepartments(),
                    ]);
                    setUsers(usersData);
                    setDepartments(userDepts);
                    break;
                case 'departments':
                    const deptsOnly = await api.getDepartments();
                    setDepartments(deptsOnly);
                    break;
                case 'services':
                    const [servicesData, deptsData] = await Promise.all([
                        api.getServices(),
                        api.getDepartments(),
                    ]);
                    setServices(servicesData);
                    setDepartments(deptsData);
                    break;
                case 'integration':
                    // First sync to ensure all default secrets exist
                    try { await api.syncSecrets(); } catch { /* ignore sync errors */ }
                    const secretsData = await api.getSecrets();
                    setSecrets(secretsData);
                    break;
                case 'system':
                    // Load Maps configuration
                    try {
                        const mapsConfig = await api.getMapsConfig();
                        if (mapsConfig.google_maps_api_key) {
                            setMapsApiKey(mapsConfig.google_maps_api_key);
                        }
                        if (mapsConfig.township_boundary) {
                            setTownshipBoundary(mapsConfig.township_boundary);
                        }
                        // Load custom map layers
                        const layers = await api.getAllMapLayers();
                        setMapLayers(layers);
                    } catch (err) {
                        console.error('Failed to load Maps config:', err);
                    }
                    break;
                case 'compliance':
                    try {
                        const [states, policy, allRequests] = await Promise.all([
                            api.getRetentionStates(),
                            api.getRetentionPolicy(),
                            api.getRequests(undefined, true) // include_deleted=true for admins
                        ]);
                        setRetentionStates(states);
                        setRetentionPolicy(policy);
                        setSelectedStateCode(policy.state_code);
                        setSelectedMode(policy.mode);
                        // Filter for deleted requests only
                        const deleted = allRequests.filter((r: { deleted_at?: string | null }) => r.deleted_at != null);
                        setDeletedRequests(deleted);
                    } catch (err) {
                        console.error('Failed to load retention config:', err);
                    }
                    break;

            }

        } catch (err) {
            console.error('Failed to load data:', err);
        } finally {
            setIsLoading(false);
        }
    };

    const handleSaveBranding = async () => {
        setIsLoading(true);
        try {
            await api.updateSettings(brandingForm);
            setSaveMessage('Settings saved!');
            setTimeout(() => setSaveMessage(''), 3000);
        } catch (err) {
            console.error('Failed to save branding:', err);
        } finally {
            setIsLoading(false);
        }
    };


    // OSM Search and Boundary handlers for Maps tab
    const handleOsmSearch = async () => {
        if (!townshipSearch.trim()) return;

        setIsSearchingTownship(true);
        setOsmSearchResults([]);
        setSelectedOsmResult(null);

        try {
            const response = await api.searchOsmTownship(townshipSearch);
            setOsmSearchResults(response.results);

            if (response.results.length === 0) {
                alert("No matching townships found. Try a different search term.");
            }
        } catch (err) {
            console.error('OSM search failed:', err);
            alert("Failed to search for township");
        } finally {
            setIsSearchingTownship(false);
        }
    };

    const handleFetchBoundary = async () => {
        if (!selectedOsmResult) return;

        setIsFetchingBoundary(true);

        try {
            // Use GeoJSON from Nominatim search result if available (polygon_geojson=1)
            // Otherwise fall back to fetching from polygons.openstreetmap.fr
            let geojson = selectedOsmResult.geojson;

            if (!geojson) {
                // Fallback to old method if Nominatim didn't return geojson
                const response = await api.fetchOsmBoundary(selectedOsmResult.osm_id);
                geojson = response.geojson;
            }

            if (!geojson) {
                alert("No boundary data available for this location.");
                return;
            }

            // Save the boundary with center coordinates from Nominatim
            const centerLat = parseFloat(selectedOsmResult.lat);
            const centerLng = parseFloat(selectedOsmResult.lon);
            await api.saveTownshipBoundary(geojson, selectedOsmResult.display_name, centerLat, centerLng);

            setTownshipBoundary(geojson);
            setSelectedOsmResult(null);
            setSaveMessage('Township boundary saved successfully!');
            setTimeout(() => setSaveMessage(null), 3000);
        } catch (err) {
            console.error('Failed to fetch boundary:', err);
            alert("Failed to fetch boundary. The boundary may not be available for this location.");
        } finally {
            setIsFetchingBoundary(false);
        }
    };



    const handleCreateUser = async (e: React.FormEvent) => {

        e.preventDefault();
        try {
            // Clean up data - send proper format for SSO users (no password needed)
            const userData = {
                username: newUser.username,
                email: newUser.email,
                role: newUser.role,
                full_name: newUser.full_name || undefined,
                department_ids: newUser.department_ids.length > 0 ? newUser.department_ids : undefined,
            };
            await api.createUser(userData as any);
            setShowUserModal(false);
            setNewUser({ username: '', email: '', full_name: '', role: 'staff', department_ids: [] });
            loadTabData();
        } catch (err: any) {
            console.error('Failed to create user:', err);
            alert(err.message || 'Failed to create user');
        }
    };

    const handleDeleteUser = async (userId: number) => {
        const confirmed = await dialog.confirm({
            title: 'Delete User',
            message: 'Are you sure you want to delete this user?\n\nThis action cannot be undone.',
            variant: 'danger',
            confirmText: 'Delete',
        });
        if (!confirmed) return;
        try {
            await api.deleteUser(userId);
            loadTabData();
        } catch (err) {
            console.error('Failed to delete user:', err);
        }
    };

    const handleCreateService = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await api.createService(newService);
            setShowServiceModal(false);
            setNewService({ service_code: '', service_name: '', description: '', icon: 'AlertCircle' });
            loadTabData();
        } catch (err) {
            console.error('Failed to create service:', err);
        }
    };

    const handleDeleteService = async (serviceId: number) => {
        const confirmed = await dialog.confirm({
            title: 'Delete Service',
            message: 'Are you sure you want to delete this service?\n\nThis action cannot be undone.',
            variant: 'danger',
            confirmText: 'Delete',
        });
        if (!confirmed) return;
        try {
            await api.deleteService(serviceId);
            loadTabData();
        } catch (err) {
            console.error('Failed to delete service:', err);
        }
    };

    const handleEditService = (service: ServiceDefinition) => {
        // Load users for staff selection
        api.getUsers().then(setUsers).catch(console.error);
        // Load departments for department selection
        api.getDepartments().then(setDepartments).catch(console.error);

        setEditingService(service);
        const config = service.routing_config || {};
        setServiceRouting({
            routing_mode: service.routing_mode || 'township',
            assigned_department_id: service.assigned_department_id || null,
            icon: service.icon || 'AlertCircle',
            routing_config: {
                // Township mode
                route_to: config.route_to || 'all_staff',
                staff_ids: config.staff_ids || [],
                // Third party mode
                message: config.message || '',
                contacts: config.contacts || [],
                // Road-based mode
                default_handler: config.default_handler || 'township',
                exclusion_list: Array.isArray(config.exclusion_list) ? config.exclusion_list.join(', ') : '',
                inclusion_list: Array.isArray(config.inclusion_list) ? config.inclusion_list.join(', ') : '',
                third_party_message: config.third_party_message || '',
                third_party_contacts: config.third_party_contacts || [],
                // Custom questions
                custom_questions: (config.custom_questions || []).map(q => ({
                    id: q.id || crypto.randomUUID(),
                    label: q.label || '',
                    type: q.type || 'text',
                    options: q.options || [],
                    required: q.required || false,
                    placeholder: q.placeholder || '',
                })),
            },
        });
        setShowServiceEditModal(true);
    };

    const handleSaveServiceRouting = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!editingService) return;

        try {
            const config: Record<string, any> = {};

            if (serviceRouting.routing_mode === 'township') {
                config.route_to = serviceRouting.routing_config.route_to;
                config.staff_ids = serviceRouting.routing_config.staff_ids;
            } else if (serviceRouting.routing_mode === 'third_party') {
                config.message = serviceRouting.routing_config.message;
                config.contacts = serviceRouting.routing_config.contacts;
            } else if (serviceRouting.routing_mode === 'road_based') {
                config.default_handler = serviceRouting.routing_config.default_handler;
                config.exclusion_list = serviceRouting.routing_config.exclusion_list
                    .split(",").map((r: string) => r.trim()).filter(Boolean);
                config.inclusion_list = serviceRouting.routing_config.inclusion_list
                    .split(",").map((r: string) => r.trim()).filter(Boolean);
                config.third_party_message = serviceRouting.routing_config.third_party_message;
                config.third_party_contacts = serviceRouting.routing_config.third_party_contacts;
            }

            // Always include custom questions
            config.custom_questions = serviceRouting.routing_config.custom_questions.filter(q => q.label.trim());

            await api.updateService(editingService.id, {
                routing_mode: serviceRouting.routing_mode,
                routing_config: config,
                assigned_department_id: serviceRouting.assigned_department_id || undefined,
                icon: serviceRouting.icon,
            });

            setShowServiceEditModal(false);
            setEditingService(null);
            loadTabData();
            setSaveMessage('Service routing updated!');
            setTimeout(() => setSaveMessage(''), 3000);
        } catch (err: any) {
            console.error('Failed to update service:', err);
            alert(err.message || 'Failed to update service');
        }
    };

    // Department handlers
    const handleCreateDepartment = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            if (editingDepartment) {
                await api.updateDepartment(editingDepartment.id, newDepartment);
            } else {
                await api.createDepartment(newDepartment);
            }
            setShowDepartmentModal(false);
            setEditingDepartment(null);
            setNewDepartment({ name: '', description: '', routing_email: '' });
            loadTabData();
        } catch (err) {
            console.error('Failed to save department:', err);
        }
    };

    const handleEditDepartment = (dept: Department) => {
        setEditingDepartment(dept);
        setNewDepartment({
            name: dept.name,
            description: dept.description || '',
            routing_email: dept.routing_email || '',
        });
        setShowDepartmentModal(true);
    };

    const handleDeleteDepartment = async (deptId: number) => {
        const confirmed = await dialog.confirm({
            title: 'Delete Department',
            message: 'Are you sure you want to delete this department?\n\nThis action cannot be undone.',
            variant: 'danger',
            confirmText: 'Delete',
        });
        if (!confirmed) return;
        try {
            await api.deleteDepartment(deptId);
            loadTabData();
        } catch (err) {
            console.error('Failed to delete department:', err);
        }
    };

    const handleUpdateSecret = async (keyName: string) => {
        const value = secretValues[keyName];
        if (!value) return;
        try {
            await api.updateSecret(keyName, value);
            setSecretValues((prev) => ({ ...prev, [keyName]: '' }));
            loadTabData();
        } catch (err) {
            console.error('Failed to update secret:', err);
        }
    };

    const handleSaveSecretDirect = async (keyName: string, value: string) => {
        try {
            await api.updateSecret(keyName, value);
            loadTabData();
        } catch (err) {
            console.error('Failed to update secret:', err);
        }
    };

    const handleSaveModules = async () => {
        setIsLoading(true);
        try {
            await api.updateSettings({ modules });
            await refreshSettings();
            setSaveMessage('Modules saved successfully');
            setTimeout(() => setSaveMessage(null), 3000);
        } catch (err) {
            console.error('Failed to save modules:', err);
        } finally {
            setIsLoading(false);
        }
    };

    const handleSystemUpdate = async () => {
        if (!confirm('This will pull updates from GitHub and rebuild the system. Continue?')) return;
        setIsUpdating(true);
        setUpdateMessage('Pulling updates...');
        try {
            const result = await api.updateSystem();
            setUpdateMessage(result.message);
        } catch (err) {
            setUpdateMessage('Update failed: ' + (err as Error).message);
        } finally {
            setIsUpdating(false);
        }
    };

    const handleLogout = () => {
        logout();
        navigate('/login');
    };

    // Note: Password reset functionality removed - using Auth0 SSO

    // Tabs are now rendered using SidebarGroup/SidebarItem components in the sidebar

    return (
        <div className="min-h-screen flex">
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

            {/* Sidebar */}
            <aside
                className={`fixed lg:static inset-y-0 left-0 z-50 w-72 glass-sidebar transform transition-transform duration-300 lg:translate-x-0 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'
                    }`}
                aria-label="Admin console navigation"
            >
                <div className="flex flex-col h-full">
                    {/* Header */}
                    <div className="p-6 border-b border-white/10">
                        <div className="flex items-center justify-between">
                            <button
                                onClick={() => {
                                    setCurrentTab('branding');
                                    window.location.hash = '';
                                }}
                                className="flex items-center gap-3 hover:opacity-80 transition-opacity cursor-pointer"
                                aria-label="Go to admin home"
                            >
                                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-400 to-orange-600 flex items-center justify-center">
                                    <Sparkles className="w-5 h-5 text-white" aria-hidden="true" />
                                </div>
                                <div className="text-left" data-no-translate>
                                    <h2 className="font-semibold text-white">Admin Console</h2>
                                    <p className="text-xs text-white/50">{settings?.township_name}</p>
                                </div>
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

                    {/* Menu - Grouped Accordion Navigation */}
                    <nav className="flex-1 p-4 space-y-3 overflow-y-auto" aria-label="Admin configuration">
                        {/* Branding & Setup Group */}
                        <SidebarGroup
                            title="Branding & Setup"
                            icon={Palette}
                            isActive={currentTab === 'branding' || currentTab === 'integration'}
                            defaultOpen={currentTab === 'branding' || currentTab === 'integration'}
                        >
                            <SidebarItem
                                icon={Palette}
                                label="Branding"
                                isActive={currentTab === 'branding'}
                                onClick={() => { setCurrentTab('branding'); setSidebarOpen(false); }}
                            />
                            <SidebarItem
                                icon={Terminal}
                                label="Setup & Integration"
                                isActive={currentTab === 'integration'}
                                onClick={() => { setCurrentTab('integration'); setSidebarOpen(false); }}
                            />
                        </SidebarGroup>

                        {/* Organization Group */}
                        <SidebarGroup
                            title="Organization"
                            icon={Users}
                            isActive={currentTab === 'users' || currentTab === 'departments' || currentTab === 'services'}
                            defaultOpen={currentTab === 'users' || currentTab === 'departments' || currentTab === 'services'}
                        >
                            <SidebarItem
                                icon={Users}
                                label="Users"
                                isActive={currentTab === 'users'}
                                onClick={() => { setCurrentTab('users'); setSidebarOpen(false); }}
                            />
                            <SidebarItem
                                icon={Building2}
                                label="Departments"
                                isActive={currentTab === 'departments'}
                                onClick={() => { setCurrentTab('departments'); setSidebarOpen(false); }}
                            />
                            <SidebarItem
                                icon={Grid3X3}
                                label="Service Categories"
                                isActive={currentTab === 'services'}
                                onClick={() => { setCurrentTab('services'); setSidebarOpen(false); }}
                            />
                        </SidebarGroup>

                        {/* System Group */}
                        <SidebarGroup
                            title="System & Compliance"
                            icon={Settings}
                            isActive={currentTab === 'system' || currentTab === 'health' || currentTab === 'compliance'}
                            defaultOpen={currentTab === 'system' || currentTab === 'health' || currentTab === 'compliance'}
                        >
                            <SidebarItem
                                icon={Settings}
                                label="System Settings"
                                isActive={currentTab === 'system'}
                                onClick={() => { setCurrentTab('system'); setSidebarOpen(false); }}
                            />
                            <SidebarItem
                                icon={BarChart3}
                                label="System Health"
                                isActive={currentTab === 'health'}
                                onClick={() => { setCurrentTab('health'); setSidebarOpen(false); }}
                            />
                            <SidebarItem
                                icon={Shield}
                                label="Compliance"
                                isActive={currentTab === 'compliance'}
                                onClick={() => { setCurrentTab('compliance'); setSidebarOpen(false); }}
                            />
                        </SidebarGroup>

                        {/* System Actions */}
                        <div className="pt-4 border-t border-white/10">
                            <p className="text-xs font-medium text-white/40 uppercase tracking-wider px-3 mb-3">
                                Version Control
                            </p>
                            <div className="px-3 mb-4">
                                <VersionSwitcher />
                            </div>

                            <Button
                                variant="primary"
                                size="sm"
                                className="w-full"
                                onClick={() => navigate('/staff')}
                            >
                                Staff Dashboard →
                            </Button>
                        </div>
                    </nav>

                    {/* User Footer - Sticky */}
                    <div className="sticky bottom-0 p-4 border-t border-white/10 bg-slate-900/90 backdrop-blur-md">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-full bg-amber-500/30 flex items-center justify-center text-white font-medium">
                                    A
                                </div>
                                <div>
                                    <p className="font-medium text-white text-sm">{user?.full_name || 'Administrator'}</p>
                                    <p className="text-xs text-amber-400">Admin</p>
                                </div>
                            </div>
                            <button
                                onClick={handleLogout}
                                className="p-2 hover:bg-white/10 rounded-lg transition-colors"
                                aria-label="Sign out"
                            >
                                <LogOut className="w-5 h-5 text-white/60" aria-hidden="true" />
                            </button>
                        </div>
                    </div>
                </div>
            </aside>

            {/* Main Content */}
            <div id="main-content" role="main" className="flex-1 flex flex-col min-w-0">
                {/* Mobile Header */}
                <header className="lg:hidden glass-sidebar p-4 flex items-center justify-between sticky top-0 z-30">
                    <button
                        onClick={() => setSidebarOpen(true)}
                        className="p-2 hover:bg-white/10 rounded-lg"
                        aria-label="Open navigation menu"
                    >
                        <Menu className="w-6 h-6 text-white" aria-hidden="true" />
                    </button>
                    <h1 className="font-semibold text-white">Admin Console</h1>
                    <div className="w-10" aria-hidden="true" />
                </header>

                {/* Content */}
                <div className="flex-1 p-6 overflow-auto">
                    <div className="max-w-4xl mx-auto">
                        {/* Save message */}
                        <AnimatePresence>
                            {saveMessage && (
                                <motion.div
                                    initial={{ opacity: 0, y: -20 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, y: -20 }}
                                    className="mb-6 flex items-center gap-3 p-4 rounded-xl bg-green-500/20 border border-green-500/30 text-green-300"
                                >
                                    <Check className="w-5 h-5" />
                                    {saveMessage}
                                </motion.div>
                            )}
                        </AnimatePresence>

                        {/* Branding Tab */}
                        {currentTab === 'branding' && (
                            <div className="space-y-6">
                                <div className="flex items-center justify-between">
                                    <h1 className="text-2xl font-bold text-white">Branding Settings</h1>
                                    <Button leftIcon={<Save className="w-4 h-4" />} onClick={handleSaveBranding} isLoading={isLoading}>
                                        Save Changes
                                    </Button>
                                </div>

                                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                    <Card>
                                        <div className="space-y-4">
                                            <Input
                                                label="Municipality Name"
                                                value={brandingForm.township_name || ''}
                                                onChange={(e) => setBrandingForm((p) => ({ ...p, township_name: e.target.value }))}
                                            />
                                            <Input
                                                label="Hero Text"
                                                value={brandingForm.hero_text || ''}
                                                onChange={(e) => setBrandingForm((p) => ({ ...p, hero_text: e.target.value }))}
                                            />
                                            <div>
                                                <label className="block text-sm font-medium text-white/70 mb-2">
                                                    Logo
                                                </label>
                                                <div className="flex items-center gap-3">
                                                    {brandingForm.logo_url && (
                                                        <img src={brandingForm.logo_url} alt="Logo" className="h-10 rounded" />
                                                    )}
                                                    <label className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 cursor-pointer transition-all">
                                                        <Upload className="w-4 h-4 text-white/60" />
                                                        <span className="text-sm text-white/70">Upload Logo</span>
                                                        <input
                                                            type="file"
                                                            accept="image/*"
                                                            className="hidden"
                                                            onChange={async (e) => {
                                                                const file = e.target.files?.[0];
                                                                if (file) {
                                                                    try {
                                                                        const result = await api.uploadImage(file);
                                                                        setBrandingForm((p) => ({ ...p, logo_url: result.url }));
                                                                    } catch (err) {
                                                                        console.error('Logo upload failed:', err);
                                                                    }
                                                                }
                                                            }}
                                                        />
                                                    </label>
                                                    {brandingForm.logo_url && (
                                                        <button
                                                            onClick={() => setBrandingForm((p) => ({ ...p, logo_url: '' }))}
                                                            className="p-2 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                                                            title="Remove logo"
                                                            aria-label="Remove logo"
                                                        >
                                                            <X className="w-4 h-4" aria-hidden="true" />
                                                        </button>
                                                    )}
                                                </div>
                                            </div>
                                            <div>
                                                <label className="block text-sm font-medium text-white/70 mb-2">
                                                    Favicon
                                                </label>
                                                <div className="flex items-center gap-3">
                                                    {brandingForm.favicon_url && (
                                                        <img src={brandingForm.favicon_url} alt="Favicon" className="h-8 w-8 rounded" />
                                                    )}
                                                    <label className="flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 cursor-pointer transition-all">
                                                        <Upload className="w-4 h-4 text-white/60" />
                                                        <span className="text-sm text-white/70">Upload Favicon</span>
                                                        <input
                                                            type="file"
                                                            accept="image/*,.ico"
                                                            className="hidden"
                                                            onChange={async (e) => {
                                                                const file = e.target.files?.[0];
                                                                if (file) {
                                                                    try {
                                                                        const result = await api.uploadImage(file);
                                                                        setBrandingForm((p) => ({ ...p, favicon_url: result.url }));
                                                                    } catch (err) {
                                                                        console.error('Favicon upload failed:', err);
                                                                    }
                                                                }
                                                            }}
                                                        />
                                                    </label>
                                                    {brandingForm.favicon_url && (
                                                        <button
                                                            onClick={() => setBrandingForm((p) => ({ ...p, favicon_url: '' }))}
                                                            className="p-2 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                                                            title="Remove favicon"
                                                            aria-label="Remove favicon"
                                                        >
                                                            <X className="w-4 h-4" aria-hidden="true" />
                                                        </button>
                                                    )}
                                                </div>
                                            </div>
                                            <div>
                                                <label className="block text-sm font-medium text-white/70 mb-2">
                                                    Primary Color
                                                </label>
                                                <div className="flex items-center gap-3">
                                                    <input
                                                        type="color"
                                                        value={brandingForm.primary_color || '#6366f1'}
                                                        onChange={(e) => setBrandingForm((p) => ({ ...p, primary_color: e.target.value }))}
                                                        className="w-12 h-12 rounded-lg cursor-pointer bg-transparent"
                                                        aria-label="Primary color picker"
                                                    />
                                                    <Input
                                                        value={brandingForm.primary_color || '#6366f1'}
                                                        onChange={(e) => setBrandingForm((p) => ({ ...p, primary_color: e.target.value }))}
                                                        className="flex-1"
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    </Card>

                                    <Card>
                                        <h3 className="text-lg font-semibold text-white mb-4">Preview</h3>
                                        <div className="p-4 rounded-xl bg-black/20 space-y-4">
                                            {brandingForm.logo_url ? (
                                                <img src={brandingForm.logo_url} alt="Logo preview" className="h-16" />
                                            ) : (
                                                <div
                                                    className="w-16 h-16 rounded-2xl flex items-center justify-center"
                                                    style={{ background: `linear-gradient(135deg, ${brandingForm.primary_color}, ${brandingForm.primary_color}dd)` }}
                                                >
                                                    <Sparkles className="w-8 h-8 text-white" />
                                                </div>
                                            )}
                                            <h2 className="text-xl font-bold text-white">{brandingForm.township_name}</h2>
                                            <p className="text-white/60">{brandingForm.hero_text}</p>
                                        </div>
                                    </Card>
                                </div>


                                {/* Domain Connection */}
                                <Card className="mt-6">
                                    <h3 className="text-lg font-semibold text-white mb-4">Custom Domain</h3>
                                    <p className="text-sm text-white/50 mb-4">
                                        Connect your own domain (e.g., 311.yourtownship.gov) to this 311 portal.
                                    </p>

                                    <div className="space-y-4">
                                        <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                                            <p className="text-sm font-medium text-white mb-2">Current URL</p>
                                            <code className="text-primary-300 text-sm bg-black/30 px-2 py-1 rounded">
                                                {window.location.origin}
                                            </code>
                                        </div>

                                        {/* Auto-Configure Domain */}
                                        <div className="p-4 rounded-xl bg-primary-500/10 border border-primary-500/20">
                                            <p className="text-sm font-medium text-primary-300 mb-3">Auto-Configure Domain</p>
                                            <p className="text-xs text-white/60 mb-3">
                                                After setting up your DNS records, enter your domain below and we'll configure Nginx + SSL automatically.
                                            </p>
                                            <div className="flex gap-2">
                                                <Input
                                                    placeholder="311.yourtownship.gov"
                                                    value={(brandingForm as any).custom_domain || ''}
                                                    onChange={(e) => setBrandingForm(p => ({ ...p, custom_domain: e.target.value }))}
                                                    className="flex-1"
                                                />
                                                <Button
                                                    onClick={async () => {
                                                        const domain = (brandingForm as any).custom_domain;
                                                        if (!domain) { alert("Please enter a domain"); return; }
                                                        setIsLoading(true);
                                                        try {
                                                            const result = await api.configureDomain(domain);
                                                            if (result.status === 'success') {
                                                                alert(
                                                                    `✅ ${result.message}\n\n` +
                                                                    `Your site will be available at:\n${result.url}\n\n` +
                                                                    `HTTPS certificate is being automatically provisioned by Caddy.`
                                                                );
                                                            } else if (result.status === 'partial') {
                                                                alert(
                                                                    `⚠️ ${result.message}\n\n` +
                                                                    `Next step: ${result.next_step || 'Restart Caddy container'}\n\n` +
                                                                    `Run on server:\nssh ubuntu@132.226.32.116\ncd ~/WWF-Open-Source-311-Template\ndocker-compose restart caddy`
                                                                );
                                                            } else {
                                                                alert(`Error: ${result.message}`);
                                                            }
                                                        } catch (err: any) { alert(`Error: ${err.message}`); }
                                                        finally { setIsLoading(false); }
                                                    }}
                                                    isLoading={isLoading}
                                                >
                                                    Configure Domain
                                                </Button>
                                            </div>
                                        </div>

                                        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20">
                                            <p className="text-sm font-medium text-amber-300 mb-3">Step 1: Set up DNS Records first</p>
                                            <ol className="text-sm text-white/70 space-y-2 list-decimal list-inside">
                                                <li>Log into your domain registrar (GoDaddy, Namecheap, etc.)</li>
                                                <li>Add an <strong className="text-white">A Record</strong> pointing to: <code className="text-primary-300 bg-black/30 px-1 rounded">132.226.32.116</code></li>
                                                <li>Wait 5-30 minutes for DNS propagation</li>
                                                <li>Then enter domain above & click "Configure SSL"</li>
                                            </ol>
                                        </div>

                                        <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                                            <p className="text-sm font-medium text-white mb-3">DNS Records to Add</p>
                                            <table className="w-full text-sm">
                                                <thead>
                                                    <tr className="text-white/50">
                                                        <th className="text-left py-1">Type</th>
                                                        <th className="text-left py-1">Host</th>
                                                        <th className="text-left py-1">Value</th>
                                                    </tr>
                                                </thead>
                                                <tbody className="text-white/80">
                                                    <tr>
                                                        <td className="py-1">A</td>
                                                        <td className="py-1">@ or 311</td>
                                                        <td className="py-1"><code className="text-primary-300">132.226.32.116</code></td>
                                                    </tr>
                                                    <tr>
                                                        <td className="py-1">A</td>
                                                        <td className="py-1">www</td>
                                                        <td className="py-1"><code className="text-primary-300">132.226.32.116</code></td>
                                                    </tr>
                                                </tbody>
                                            </table>
                                        </div>
                                    </div>
                                </Card>
                            </div>
                        )}

                        {/* Users Tab */}
                        {currentTab === 'users' && (
                            <div className="space-y-6">
                                {/* Premium Header */}
                                <div className="flex items-center justify-between">
                                    <div>
                                        <h1 className="text-2xl font-bold text-white">User Management</h1>
                                        <p className="text-sm text-white/50 mt-1">Manage staff and administrator accounts</p>
                                    </div>
                                    <Button
                                        leftIcon={<Plus className="w-4 h-4" />}
                                        onClick={() => setShowUserModal(true)}
                                        className="bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 shadow-lg shadow-primary-500/25"
                                    >
                                        Add User
                                    </Button>
                                </div>

                                {/* Stats Cards */}
                                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                                    <div className="p-4 rounded-2xl bg-gradient-to-br from-blue-500/10 to-blue-600/5 border border-blue-500/20 backdrop-blur-sm">
                                        <div className="flex items-center gap-3">
                                            <div className="w-10 h-10 rounded-xl bg-blue-500/20 flex items-center justify-center">
                                                <UserIcon className="w-5 h-5 text-blue-400" />
                                            </div>
                                            <div>
                                                <p className="text-2xl font-bold text-white">{users.length}</p>
                                                <p className="text-xs text-blue-300/70">Total Users</p>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="p-4 rounded-2xl bg-gradient-to-br from-amber-500/10 to-amber-600/5 border border-amber-500/20 backdrop-blur-sm">
                                        <div className="flex items-center gap-3">
                                            <div className="w-10 h-10 rounded-xl bg-amber-500/20 flex items-center justify-center">
                                                <Shield className="w-5 h-5 text-amber-400" />
                                            </div>
                                            <div>
                                                <p className="text-2xl font-bold text-white">{users.filter(u => u.role === 'admin').length}</p>
                                                <p className="text-xs text-amber-300/70">Administrators</p>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="p-4 rounded-2xl bg-gradient-to-br from-emerald-500/10 to-emerald-600/5 border border-emerald-500/20 backdrop-blur-sm">
                                        <div className="flex items-center gap-3">
                                            <div className="w-10 h-10 rounded-xl bg-emerald-500/20 flex items-center justify-center">
                                                <Users className="w-5 h-5 text-emerald-400" />
                                            </div>
                                            <div>
                                                <p className="text-2xl font-bold text-white">{users.filter(u => u.role === 'staff').length}</p>
                                                <p className="text-xs text-emerald-300/70">Staff Members</p>
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                {/* Premium Table */}
                                <div className="rounded-2xl bg-white/[0.03] backdrop-blur-xl border border-white/10 overflow-hidden shadow-2xl">
                                    {/* Table Header */}
                                    <div className="px-6 py-4 border-b border-white/10 bg-gradient-to-r from-white/[0.05] to-transparent">
                                        <div className="grid grid-cols-12 gap-4 items-center">
                                            <div className="col-span-4 text-xs font-semibold text-white/50 uppercase tracking-wider">User</div>
                                            <div className="col-span-3 text-xs font-semibold text-white/50 uppercase tracking-wider">Email</div>
                                            <div className="col-span-2 text-xs font-semibold text-white/50 uppercase tracking-wider text-center">Role</div>
                                            <div className="col-span-2 text-xs font-semibold text-white/50 uppercase tracking-wider">Department</div>
                                            <div className="col-span-1 text-xs font-semibold text-white/50 uppercase tracking-wider text-right">Actions</div>
                                        </div>
                                    </div>

                                    {/* Table Body */}
                                    <div className="divide-y divide-white/5">
                                        {users.map((u, index) => (
                                            <motion.div
                                                key={u.id}
                                                initial={{ opacity: 0, y: 10 }}
                                                animate={{ opacity: 1, y: 0 }}
                                                transition={{ delay: index * 0.05 }}
                                                className="px-6 py-4 hover:bg-white/[0.03] transition-all duration-200 group"
                                            >
                                                <div className="grid grid-cols-12 gap-4 items-center">
                                                    {/* User Info */}
                                                    <div className="col-span-4 flex items-center gap-4">
                                                        <div className={`relative w-12 h-12 rounded-xl flex items-center justify-center font-bold text-lg shadow-lg ${u.role === 'admin'
                                                            ? 'bg-gradient-to-br from-amber-400 to-orange-500 text-white'
                                                            : 'bg-gradient-to-br from-primary-400 to-primary-600 text-white'
                                                            }`}>
                                                            {u.full_name ? u.full_name.charAt(0).toUpperCase() : u.username.charAt(0).toUpperCase()}
                                                            {/* Online indicator */}
                                                            <div className="absolute -bottom-0.5 -right-0.5 w-3.5 h-3.5 rounded-full bg-emerald-500 border-2 border-slate-900" />
                                                        </div>
                                                        <div>
                                                            <p className="font-semibold text-white group-hover:text-primary-300 transition-colors">{u.full_name || u.username}</p>
                                                            <p className="text-sm text-white/40">@{u.username}</p>
                                                        </div>
                                                    </div>

                                                    {/* Email */}
                                                    <div className="col-span-3">
                                                        <p className="text-sm text-white/60 truncate">{u.email}</p>
                                                    </div>

                                                    {/* Role Badge */}
                                                    <div className="col-span-2 flex justify-center">
                                                        {u.role === 'admin' ? (
                                                            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-gradient-to-r from-amber-500/20 to-orange-500/20 text-amber-300 border border-amber-500/30 shadow-lg shadow-amber-500/10">
                                                                <Shield className="w-3 h-3" />
                                                                Admin
                                                            </span>
                                                        ) : (
                                                            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold bg-gradient-to-r from-blue-500/20 to-cyan-500/20 text-blue-300 border border-blue-500/30 shadow-lg shadow-blue-500/10">
                                                                <UserIcon className="w-3 h-3" />
                                                                Staff
                                                            </span>
                                                        )}
                                                    </div>

                                                    {/* Departments */}
                                                    <div className="col-span-2">
                                                        {u.departments && u.departments.length > 0 ? (
                                                            <div className="flex flex-wrap gap-1.5">
                                                                {u.departments.slice(0, 2).map((dept) => (
                                                                    <span
                                                                        key={dept.id}
                                                                        className="px-2.5 py-1 text-xs font-medium rounded-lg bg-white/5 text-white/70 border border-white/10"
                                                                    >
                                                                        {dept.name}
                                                                    </span>
                                                                ))}
                                                                {u.departments.length > 2 && (
                                                                    <span className="px-2 py-1 text-xs text-white/40">
                                                                        +{u.departments.length - 2}
                                                                    </span>
                                                                )}
                                                            </div>
                                                        ) : (
                                                            <span className="text-sm text-white/25 italic">No department</span>
                                                        )}
                                                    </div>

                                                    {/* Actions */}
                                                    <div className="col-span-1 flex justify-end">
                                                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                            <button
                                                                onClick={() => handleDeleteUser(u.id)}
                                                                disabled={u.id === user?.id}
                                                                className={`p-2 rounded-lg transition-all ${u.id === user?.id
                                                                    ? 'text-white/20 cursor-not-allowed'
                                                                    : 'hover:bg-red-500/20 text-white/40 hover:text-red-400'
                                                                    }`}
                                                                title={u.id === user?.id ? "Cannot delete yourself" : "Delete user"}
                                                            >
                                                                <Trash2 className="w-4 h-4" />
                                                            </button>
                                                        </div>
                                                    </div>
                                                </div>
                                            </motion.div>
                                        ))}
                                    </div>

                                    {/* Empty State */}
                                    {users.length === 0 && (
                                        <div className="px-6 py-16 text-center">
                                            <div className="w-16 h-16 mx-auto mb-4 rounded-2xl bg-white/5 flex items-center justify-center">
                                                <Users className="w-8 h-8 text-white/20" />
                                            </div>
                                            <p className="text-white/50 mb-2">No users found</p>
                                            <p className="text-sm text-white/30">Add your first user to get started</p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                        {/* Departments Tab */}
                        {currentTab === 'departments' && (
                            <div className="space-y-6">
                                <div className="flex items-center justify-between">
                                    <h1 className="text-2xl font-bold text-white">Departments</h1>
                                    <Button
                                        leftIcon={<Plus className="w-4 h-4" />}
                                        onClick={() => {
                                            setEditingDepartment(null);
                                            setNewDepartment({ name: '', description: '', routing_email: '' });
                                            setShowDepartmentModal(true);
                                        }}
                                    >
                                        Add Department
                                    </Button>
                                </div>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    {departments.map((dept) => (
                                        <Card key={dept.id} className="relative group">
                                            <div className="flex items-start gap-4">
                                                <div className="w-12 h-12 rounded-xl bg-blue-500/20 flex items-center justify-center text-blue-300">
                                                    <Building2 className="w-6 h-6" />
                                                </div>
                                                <div className="flex-1">
                                                    <h3 className="font-semibold text-white">{dept.name}</h3>
                                                    <p className="text-sm text-white/50 mt-1">{dept.description || 'No description'}</p>
                                                    {dept.routing_email && (
                                                        <p className="text-xs text-white/30 mt-2 font-mono">{dept.routing_email}</p>
                                                    )}
                                                </div>
                                                <div className="flex gap-1">
                                                    <button
                                                        onClick={() => handleEditDepartment(dept)}
                                                        className="opacity-0 group-hover:opacity-100 p-2 hover:bg-white/10 rounded-lg transition-all"
                                                        aria-label={`Edit ${dept.name} department`}
                                                    >
                                                        <Edit className="w-4 h-4 text-white/60" aria-hidden="true" />
                                                    </button>
                                                    <button
                                                        onClick={() => handleDeleteDepartment(dept.id)}
                                                        className="opacity-0 group-hover:opacity-100 p-2 hover:bg-red-500/20 rounded-lg transition-all"
                                                        aria-label={`Delete ${dept.name} department`}
                                                    >
                                                        <Trash2 className="w-4 h-4 text-red-400" aria-hidden="true" />
                                                    </button>
                                                </div>
                                            </div>
                                        </Card>
                                    ))}
                                </div>

                                {departments.length === 0 && (
                                    <Card className="text-center py-8">
                                        <Building2 className="w-12 h-12 mx-auto text-white/20 mb-3" />
                                        <p className="text-white/50">No departments yet. Add your first department to organize staff.</p>
                                    </Card>
                                )}
                            </div>
                        )}

                        {/* Services Tab */}
                        {currentTab === 'services' && (
                            <div className="space-y-6">
                                <div className="flex items-center justify-between">
                                    <h1 className="text-2xl font-bold text-white">Service Categories</h1>
                                    <Button leftIcon={<Plus className="w-4 h-4" />} onClick={() => setShowServiceModal(true)}>
                                        Add Category
                                    </Button>
                                </div>

                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    {services.map((service) => (
                                        <Card key={service.id} className="relative group">
                                            <div className="flex items-start gap-4">
                                                <div className="w-12 h-12 rounded-xl bg-primary-500/20 flex items-center justify-center text-primary-300">
                                                    <Grid3X3 className="w-6 h-6" />
                                                </div>
                                                <div className="flex-1 min-w-0">
                                                    <h3 className="font-semibold text-white">{service.service_name}</h3>
                                                    <p className="text-sm text-white/50 mt-1 line-clamp-2">{service.description}</p>
                                                    <div className="flex items-center gap-2 mt-2 flex-wrap">
                                                        <span className="text-xs text-white/30 font-mono">{service.service_code}</span>
                                                        {service.routing_mode && service.routing_mode !== 'township' && (
                                                            <Badge variant={service.routing_mode === 'third_party' ? 'warning' : 'info'}>
                                                                {service.routing_mode === 'third_party' ? '3rd Party' : 'Road-Based'}
                                                            </Badge>
                                                        )}
                                                        {service.assigned_department && (
                                                            <Badge variant="default">{service.assigned_department.name}</Badge>
                                                        )}
                                                    </div>
                                                </div>
                                                <div className="flex gap-1">
                                                    <button
                                                        onClick={() => handleEditService(service)}
                                                        className="opacity-0 group-hover:opacity-100 p-2 hover:bg-white/10 rounded-lg transition-all"
                                                        aria-label={`Configure ${service.service_name} routing`}
                                                    >
                                                        <Edit className="w-4 h-4 text-white/60" aria-hidden="true" />
                                                    </button>
                                                    <button
                                                        onClick={() => handleDeleteService(service.id)}
                                                        className="opacity-0 group-hover:opacity-100 p-2 hover:bg-red-500/20 rounded-lg transition-all"
                                                        aria-label={`Delete ${service.service_name}`}
                                                    >
                                                        <Trash2 className="w-4 h-4 text-red-400" aria-hidden="true" />
                                                    </button>
                                                </div>
                                            </div>
                                        </Card>
                                    ))}
                                </div>
                            </div>
                        )}


                        {/* Integrations Tab - Card-based Setup & Integrations */}
                        {currentTab === 'integration' && (
                            <SetupIntegrationsPage
                                secrets={secrets}
                                onSaveSecret={handleSaveSecretDirect}
                                onRefresh={loadTabData}
                            />
                        )}

                        {/* Modules Tab */}
                        {currentTab === 'system' && (
                            <div className="space-y-6">
                                <div className="flex items-center justify-between">
                                    <h1 className="text-2xl font-bold text-white">Feature Modules</h1>
                                    <Button leftIcon={<Save className="w-4 h-4" />} onClick={handleSaveModules} isLoading={isLoading}>
                                        Save Changes
                                    </Button>
                                </div>

                                <div className="space-y-4">
                                    <Card>
                                        <div className="flex items-center justify-between">
                                            <div className="flex items-center gap-4">
                                                <div className="w-12 h-12 rounded-xl bg-blue-500/20 flex items-center justify-center">
                                                    <Sparkles className="w-6 h-6 text-blue-400" />
                                                </div>
                                                <div>
                                                    <h3 className="font-semibold text-white">AI Analysis</h3>
                                                    <p className="text-sm text-white/50">Enable Vertex AI triage for submissions</p>
                                                </div>
                                            </div>
                                            <button
                                                onClick={() => setModules((p) => ({ ...p, ai_analysis: !p.ai_analysis }))}
                                                className={`w-14 h-8 rounded-full transition-colors ${modules.ai_analysis ? 'bg-primary-500' : 'bg-white/20'
                                                    }`}
                                                role="switch"
                                                aria-checked={modules.ai_analysis}
                                                aria-label="Toggle AI Analysis"
                                            >
                                                <div
                                                    className={`w-6 h-6 rounded-full bg-white transition-transform ${modules.ai_analysis ? 'translate-x-7' : 'translate-x-1'
                                                        }`}
                                                    aria-hidden="true"
                                                />
                                            </button>
                                        </div>
                                    </Card>

                                    <Card>
                                        <div className="flex items-center justify-between">
                                            <div className="flex items-center gap-4">
                                                <div className="w-12 h-12 rounded-xl bg-green-500/20 flex items-center justify-center">
                                                    <MessageSquare className="w-6 h-6 text-green-400" />
                                                </div>
                                                <div>
                                                    <h3 className="font-semibold text-white">SMS Alerts</h3>
                                                    <p className="text-sm text-white/50">Enable SMS notifications to residents</p>
                                                </div>
                                            </div>
                                            <button
                                                onClick={() => setModules((p) => ({ ...p, sms_alerts: !p.sms_alerts }))}
                                                className={`w-14 h-8 rounded-full transition-colors ${modules.sms_alerts ? 'bg-primary-500' : 'bg-white/20'
                                                    }`}
                                                role="switch"
                                                aria-checked={modules.sms_alerts}
                                                aria-label="Toggle SMS Alerts"
                                            >
                                                <div
                                                    className={`w-6 h-6 rounded-full bg-white transition-transform ${modules.sms_alerts ? 'translate-x-7' : 'translate-x-1'
                                                        }`}
                                                    aria-hidden="true"
                                                />
                                            </button>
                                        </div>
                                    </Card>

                                    <Card>
                                        <div className="flex items-center justify-between">
                                            <div className="flex items-center gap-4">
                                                <div className="w-12 h-12 rounded-xl bg-blue-500/20 flex items-center justify-center">
                                                    <Mail className="w-6 h-6 text-blue-400" />
                                                </div>
                                                <div>
                                                    <h3 className="font-semibold text-white">Email Notifications</h3>
                                                    <p className="text-sm text-white/50">Send email updates to residents</p>
                                                </div>
                                            </div>
                                            <button
                                                onClick={() => setModules((p) => ({ ...p, email_notifications: !p.email_notifications }))}
                                                className={`w-14 h-8 rounded-full transition-colors ${modules.email_notifications ? 'bg-primary-500' : 'bg-white/20'
                                                    }`}
                                                role="switch"
                                                aria-checked={modules.email_notifications}
                                                aria-label="Toggle Email Notifications"
                                            >
                                                <div
                                                    className={`w-6 h-6 rounded-full bg-white transition-transform ${modules.email_notifications ? 'translate-x-7' : 'translate-x-1'
                                                        }`}
                                                    aria-hidden="true"
                                                />
                                            </button>
                                        </div>
                                    </Card>

                                    <Card>
                                        <div className="flex items-center justify-between">
                                            <div className="flex items-center gap-4">
                                                <div className="w-12 h-12 rounded-xl bg-amber-500/20 flex items-center justify-center">
                                                    <BarChart3 className="w-6 h-6 text-amber-400" />
                                                </div>
                                                <div>
                                                    <h3 className="font-semibold text-white">Research Portal</h3>
                                                    <p className="text-sm text-white/50">Enable researcher access to anonymized data exports</p>
                                                </div>
                                            </div>
                                            <button
                                                onClick={() => setModules((p) => ({ ...p, research_portal: !p.research_portal }))}
                                                className={`w-14 h-8 rounded-full transition-colors ${modules.research_portal ? 'bg-primary-500' : 'bg-white/20'
                                                    }`}
                                                role="switch"
                                                aria-checked={modules.research_portal}
                                                aria-label="Toggle Research Portal"
                                            >
                                                <div
                                                    className={`w-6 h-6 rounded-full bg-white transition-transform ${modules.research_portal ? 'translate-x-7' : 'translate-x-1'
                                                        }`}
                                                    aria-hidden="true"
                                                />
                                            </button>
                                        </div>
                                    </Card>
                                </div>
                            </div>
                        )}

                        {/* Maps Configuration - part of System Settings */}
                        {currentTab === 'system' && (
                            <div className="mt-12 p-6 rounded-2xl bg-white/5 backdrop-blur-sm border border-white/10 space-y-6">
                                <div>
                                    <h2 className="text-2xl font-bold text-white mb-2">Maps Configuration</h2>
                                    <p className="text-white/60">
                                        Configure map settings and township boundary for data-driven styling.
                                    </p>
                                </div>

                                {!mapsApiKey ? (
                                    <Card>
                                        <div className="p-4 rounded-xl bg-yellow-500/10 border border-yellow-500/30">
                                            <p className="text-sm text-yellow-300">
                                                ⚠️ Google Maps API key is required. Please configure it in the API Keys section first.
                                            </p>
                                        </div>
                                    </Card>
                                ) : (
                                    <>
                                        {/* Township Boundary Search */}
                                        <Card>
                                            <h3 className="text-lg font-semibold text-white mb-2">Township Boundary</h3>
                                            <p className="text-sm text-white/50 mb-4">
                                                Search for your township using OpenStreetMap to get its boundary.
                                            </p>

                                            <div className="p-4 rounded-xl bg-primary-500/10 border border-primary-500/20 mb-4">
                                                <p className="text-sm font-medium text-primary-300 mb-2">How it works:</p>
                                                <ol className="text-xs text-white/60 space-y-1 list-decimal list-inside">
                                                    <li>Search for your township name (e.g., "West Windsor Township, NJ")</li>
                                                    <li>Select from the search results</li>
                                                    <li>Click "Fetch Boundary" to get the GeoJSON boundary data</li>
                                                    <li>The boundary will be displayed on the resident portal map</li>
                                                </ol>
                                            </div>

                                            {/* Search Input */}
                                            <div className="flex gap-2 mb-4">
                                                <div className="relative flex-1">
                                                    <MapPin className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/40 pointer-events-none z-10" />
                                                    <input
                                                        type="text"
                                                        placeholder="Search for your township..."
                                                        aria-label="Search for your township"
                                                        value={townshipSearch}
                                                        onChange={(e) => setTownshipSearch(e.target.value)}
                                                        onKeyDown={(e) => {
                                                            if (e.key === 'Enter') {
                                                                e.preventDefault();
                                                                handleOsmSearch();
                                                            }
                                                        }}
                                                        className="w-full h-12 pl-12 pr-4 rounded-xl bg-white/10 border border-white/20 text-white placeholder-white/40 focus:outline-none focus:border-primary-500/50 focus:ring-2 focus:ring-primary-500/20 transition-all"
                                                        disabled={isSearchingTownship}
                                                    />
                                                </div>
                                                <Button
                                                    onClick={handleOsmSearch}
                                                    isLoading={isSearchingTownship}
                                                    disabled={!townshipSearch.trim()}
                                                >
                                                    Search
                                                </Button>
                                            </div>

                                            {/* Search Results */}
                                            {osmSearchResults.length > 0 && (
                                                <div className="mb-4">
                                                    <p className="text-sm text-white/60 mb-2">Select your township:</p>
                                                    <div className="space-y-2 max-h-60 overflow-y-auto">
                                                        {osmSearchResults.map((result) => (
                                                            <button
                                                                key={result.osm_id}
                                                                onClick={() => {
                                                                    setSelectedOsmResult(result);
                                                                    setOsmSearchResults([]);
                                                                }}
                                                                className="w-full p-3 rounded-xl text-left transition-all bg-white/5 hover:bg-white/10 border border-white/10"
                                                            >
                                                                <p className="text-sm text-white font-medium">{result.display_name}</p>
                                                                <p className="text-xs text-white/40 mt-1">
                                                                    OSM ID: {result.osm_id} • Type: {result.type}
                                                                </p>
                                                            </button>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}

                                            {/* Selected Township */}
                                            {selectedOsmResult && (
                                                <div className="p-4 rounded-xl bg-blue-500/10 border border-blue-500/30 mb-4">
                                                    <p className="text-sm text-blue-300 mb-2">Selected Township</p>
                                                    <p className="text-white font-medium text-sm">{selectedOsmResult.display_name}</p>
                                                    <p className="text-xs text-white/50 mt-1">OSM ID: {selectedOsmResult.osm_id}</p>
                                                    <div className="mt-3">
                                                        <Button
                                                            size="sm"
                                                            onClick={handleFetchBoundary}
                                                            isLoading={isFetchingBoundary}
                                                        >
                                                            Fetch & Save Boundary
                                                        </Button>
                                                    </div>
                                                </div>
                                            )}

                                            {/* Current Boundary Status */}
                                            {townshipBoundary && (
                                                <div className="p-4 rounded-xl bg-green-500/10 border border-green-500/30 mb-4">
                                                    <div className="flex justify-between items-start">
                                                        <div>
                                                            <p className="text-sm text-green-300 mb-2">✓ Township Boundary Configured</p>
                                                            <p className="text-xs text-white/60">
                                                                Boundary data is saved and will be displayed on the resident portal map.
                                                            </p>
                                                        </div>
                                                        <div className="flex gap-2">
                                                            <Button
                                                                size="sm"
                                                                variant="ghost"
                                                                onClick={() => {
                                                                    // Download GeoJSON
                                                                    const dataStr = JSON.stringify(townshipBoundary, null, 2);
                                                                    const blob = new Blob([dataStr], { type: 'application/json' });
                                                                    const url = URL.createObjectURL(blob);
                                                                    const a = document.createElement("a");
                                                                    a.href = url;
                                                                    a.download = 'township-boundary.geojson';
                                                                    document.body.appendChild(a);
                                                                    a.click();
                                                                    document.body.removeChild(a);
                                                                    URL.revokeObjectURL(url);
                                                                }}
                                                            >
                                                                Download
                                                            </Button>
                                                            <Button
                                                                size="sm"
                                                                variant="ghost"
                                                                onClick={async () => {
                                                                    if (confirm('Are you sure you want to clear the township boundary?')) {
                                                                        try {
                                                                            await api.saveTownshipBoundary({});
                                                                            setTownshipBoundary(null);
                                                                            setSaveMessage('Boundary cleared');
                                                                            setTimeout(() => setSaveMessage(null), 3000);
                                                                        } catch (err) {
                                                                            alert("Failed to clear boundary");
                                                                        }
                                                                    }
                                                                }}
                                                            >
                                                                Clear
                                                            </Button>
                                                        </div>
                                                    </div>
                                                </div>
                                            )}


                                            {/* Divider */}
                                            <div className="flex items-center gap-4 my-6">
                                                <div className="flex-1 h-px bg-white/10"></div>
                                                <span className="text-sm text-white/40">or upload existing GeoJSON</span>
                                                <div className="flex-1 h-px bg-white/10"></div>
                                            </div>

                                            {/* GeoJSON Upload */}
                                            <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                                                <p className="text-sm text-white/70 mb-3">
                                                    Upload a GeoJSON file containing your township boundary
                                                </p>
                                                <input
                                                    type="file"
                                                    accept=".geojson,.json"
                                                    aria-label="Upload GeoJSON township boundary file"
                                                    onChange={async (e) => {
                                                        const file = e.target.files?.[0];
                                                        if (!file) return;

                                                        try {
                                                            const text = await file.text();
                                                            const geojson = JSON.parse(text);

                                                            // Validate it's a valid GeoJSON
                                                            if (!geojson.type) {
                                                                throw new Error('Invalid GeoJSON format');
                                                            }

                                                            await api.saveTownshipBoundary(geojson, file.name);
                                                            setTownshipBoundary(geojson);
                                                            setSelectedOsmResult(null);
                                                            setSaveMessage('GeoJSON boundary uploaded successfully!');
                                                            setTimeout(() => setSaveMessage(null), 3000);
                                                        } catch (err) {
                                                            console.error('Failed to upload GeoJSON:', err);
                                                            alert("Failed to upload GeoJSON. Make sure the file is valid JSON.");
                                                        }

                                                        // Reset file input
                                                        e.target.value = '';
                                                    }}
                                                    className="block w-full text-sm text-white/60 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-primary-500 file:text-white hover:file:bg-primary-600 file:cursor-pointer"
                                                />
                                            </div>
                                        </Card>

                                        {/* Custom Map Layers */}
                                        <Card>
                                            <div className="flex items-center justify-between mb-4">
                                                <div>
                                                    <h3 className="text-lg font-semibold text-white">Custom Map Layers</h3>
                                                    <p className="text-sm text-white/50">
                                                        Upload GeoJSON files for parks, storm drains, utilities, and other assets.
                                                    </p>
                                                </div>
                                                <Button
                                                    size="sm"
                                                    onClick={() => {
                                                        setEditingLayer(null);
                                                        setNewLayer({
                                                            name: '',
                                                            description: '',
                                                            fill_color: '#3b82f6',
                                                            stroke_color: '#1d4ed8',
                                                            fill_opacity: 0.3,
                                                            stroke_width: 2,
                                                            service_codes: [],
                                                            geojson: null,
                                                            layer_type: '',
                                                            routing_mode: 'log',
                                                            routing_config: null,
                                                            visible_on_map: true,
                                                        });
                                                        // Always load services for category selection
                                                        api.getServices().then(setServices).catch(console.error);
                                                        setShowLayerModal(true);
                                                    }}
                                                    leftIcon={<Plus className="w-4 h-4" />}
                                                >
                                                    Add Layer
                                                </Button>
                                            </div>

                                            {mapLayers.length === 0 ? (
                                                <div className="text-center py-8 text-white/40">
                                                    <Layers className="w-12 h-12 mx-auto mb-2 opacity-50" />
                                                    <p>No custom layers yet</p>
                                                    <p className="text-sm">Upload GeoJSON files to add layers</p>
                                                </div>
                                            ) : (
                                                <div className="space-y-3">
                                                    {mapLayers.map((layer) => (
                                                        <div
                                                            key={layer.id}
                                                            className="flex items-center gap-4 p-4 rounded-xl bg-white/5 border border-white/10"
                                                        >
                                                            <div
                                                                className="w-8 h-8 rounded-lg border-2"
                                                                style={{
                                                                    backgroundColor: layer.fill_color + Math.round(layer.fill_opacity * 255).toString(16).padStart(2, '0'),
                                                                    borderColor: layer.stroke_color,
                                                                }}
                                                            />
                                                            <div className="flex-1">
                                                                <div className="flex items-center gap-2">
                                                                    <span className="font-medium text-white">{layer.name}</span>
                                                                    {layer.layer_type && (
                                                                        <Badge variant="default" size="sm">
                                                                            {layer.layer_type}
                                                                        </Badge>
                                                                    )}
                                                                    {!layer.is_active && (
                                                                        <Badge variant="default" size="sm">
                                                                            Disabled
                                                                        </Badge>
                                                                    )}
                                                                </div>
                                                                {layer.description && (
                                                                    <p className="text-sm text-white/50">{layer.description}</p>
                                                                )}
                                                            </div>
                                                            <div className="flex items-center gap-2">
                                                                <label className="flex items-center gap-2 text-sm text-white/60">
                                                                    <input
                                                                        type="checkbox"
                                                                        checked={(layer as any).visible_on_map ?? true}
                                                                        onChange={async () => {
                                                                            try {
                                                                                await api.updateMapLayer(layer.id, {
                                                                                    visible_on_map: !((layer as any).visible_on_map ?? true),
                                                                                });
                                                                                loadTabData();
                                                                            } catch (err) {
                                                                                console.error('Failed to update layer:', err);
                                                                            }
                                                                        }}
                                                                        className="rounded"
                                                                    />
                                                                    Show
                                                                </label>
                                                                <Button
                                                                    variant="ghost"
                                                                    size="sm"
                                                                    onClick={() => {
                                                                        setEditingLayer(layer);
                                                                        setNewLayer({
                                                                            name: layer.name,
                                                                            description: layer.description || '',
                                                                            layer_type: (layer as any).layer_type || 'polygon',
                                                                            fill_color: layer.fill_color,
                                                                            stroke_color: layer.stroke_color,
                                                                            fill_opacity: layer.fill_opacity,
                                                                            stroke_width: layer.stroke_width,
                                                                            service_codes: layer.service_codes || [],
                                                                            geojson: layer.geojson,
                                                                            routing_mode: ((layer as any).routing_mode === 'block' ? 'block' : 'log') as 'log' | 'block',
                                                                            routing_config: (layer as any).routing_config || null,
                                                                            visible_on_map: (layer as any).visible_on_map ?? true,
                                                                        });
                                                                        // Always load services for category selection
                                                                        api.getServices().then(setServices).catch(console.error);
                                                                        setShowLayerModal(true);
                                                                    }}
                                                                >
                                                                    <Edit className="w-4 h-4" />
                                                                </Button>
                                                                <Button
                                                                    variant="ghost"
                                                                    size="sm"
                                                                    onClick={async () => {
                                                                        if (!confirm(`Delete layer "${layer.name}"?`)) return;
                                                                        try {
                                                                            await api.deleteMapLayer(layer.id);
                                                                            loadTabData();
                                                                            setSaveMessage('Layer deleted');
                                                                            setTimeout(() => setSaveMessage(null), 3000);
                                                                        } catch (err) {
                                                                            console.error('Failed to delete layer:', err);
                                                                        }
                                                                    }}
                                                                >
                                                                    <Trash2 className="w-4 h-4 text-red-400" />
                                                                </Button>
                                                            </div>
                                                        </div>
                                                    ))}
                                                </div>
                                            )}
                                        </Card>

                                    </>

                                )}
                            </div>

                        )}

                        {/* Document Retention Tab */}
                        {currentTab === 'compliance' && (
                            <div className="space-y-6">
                                <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
                                    <h2 className="text-2xl font-bold text-white mb-2">Document Retention</h2>
                                    <p className="text-white/60">Configure state-mandated record retention policies</p>
                                </motion.div>

                                {/* Current Policy Status */}
                                {retentionPolicy && (
                                    <AccordionSection
                                        title={`Current Policy: ${retentionPolicy.policy.name}`}
                                        subtitle={`${retentionPolicy.policy.retention_years} years retention • ${retentionPolicy.mode === 'anonymize' ? 'Anonymize mode' : 'Delete mode'}`}
                                        icon={Shield}
                                        iconClassName="text-green-400"
                                        badge={<Badge variant="success">Active</Badge>}
                                        defaultOpen={true}
                                    >
                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                                            <div className="bg-white/5 rounded-lg p-4">
                                                <div className="text-white/60 text-sm">Active State</div>
                                                <div className="text-2xl font-bold text-white">{retentionPolicy.policy.name}</div>
                                                <div className="text-white/40 text-sm">{retentionPolicy.state_code}</div>
                                            </div>
                                            <div className="bg-white/5 rounded-lg p-4">
                                                <div className="text-white/60 text-sm">Retention Period</div>
                                                <div className="text-2xl font-bold text-amber-400">{retentionPolicy.policy.retention_years} Years</div>
                                                <div className="text-white/40 text-sm">{retentionPolicy.effective_days.toLocaleString()} days</div>
                                            </div>
                                            <div className="bg-white/5 rounded-lg p-4">
                                                <div className="text-white/60 text-sm">Mode</div>
                                                <div className="text-2xl font-bold text-white capitalize">{retentionPolicy.mode}</div>
                                                <div className="text-white/40 text-sm">{retentionPolicy.mode === 'anonymize' ? 'PII removed, stats kept' : 'Permanent deletion'}</div>
                                            </div>
                                        </div>

                                        {/* Archival Stats */}
                                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                                            <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
                                                <div className="text-blue-300 text-sm">Eligible for Archival</div>
                                                <div className="text-2xl font-bold text-blue-300">{retentionPolicy.stats.eligible_for_archival}</div>
                                            </div>
                                            <button
                                                onClick={async () => {
                                                    setIsLoadingLegalHold(true);
                                                    try {
                                                        const result = await api.getLegalHoldRequests();
                                                        setLegalHoldRequests(result.requests);
                                                        setShowLegalHoldModal(true);
                                                    } catch (err) {
                                                        console.error('Failed to load legal hold requests:', err);
                                                    } finally {
                                                        setIsLoadingLegalHold(false);
                                                    }
                                                }}
                                                className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-4 text-left hover:bg-amber-500/20 hover:border-amber-500/50 transition-all cursor-pointer"
                                            >
                                                <div className="text-amber-400 text-sm">Under Legal Hold</div>
                                                <div className="text-2xl font-bold text-amber-400">{retentionPolicy.stats.under_legal_hold}</div>
                                                <div className="text-amber-300 text-xs mt-1">Click to view →</div>
                                            </button>
                                            <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-4">
                                                <div className="text-green-400 text-sm">Already Archived</div>
                                                <div className="text-2xl font-bold text-green-400">{retentionPolicy.stats.already_archived}</div>
                                            </div>
                                        </div>
                                        <p className="text-white/40 text-sm mt-4">
                                            Source: {retentionPolicy.policy.source}
                                        </p>
                                    </AccordionSection>
                                )}

                                {/* Database Backups */}
                                <AccordionSection
                                    title="Database Backups"
                                    subtitle="Encrypted S3-compatible backup management"
                                    icon={Upload}
                                    iconClassName="text-blue-400"
                                >
                                    {backupStatus === null ? (
                                        <div className="text-center py-4">
                                            <Button
                                                variant="ghost"
                                                onClick={async () => {
                                                    setIsLoadingBackups(true);
                                                    try {
                                                        const [status, list] = await Promise.all([
                                                            api.getBackupStatus(),
                                                            api.listBackups()
                                                        ]);
                                                        setBackupStatus(status);
                                                        setBackups(list.backups || []);
                                                    } catch (err) {
                                                        console.error('Failed to load backups:', err);
                                                    } finally {
                                                        setIsLoadingBackups(false);
                                                    }
                                                }}
                                                disabled={isLoadingBackups}
                                            >
                                                <RefreshCw className={`w-4 h-4 mr-2 ${isLoadingBackups ? 'animate-spin' : ''}`} />
                                                {isLoadingBackups ? 'Loading...' : 'Load Backup Status'}
                                            </Button>
                                        </div>
                                    ) : !backupStatus.configured ? (
                                        <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-4">
                                            <p className="text-amber-400 mb-3">
                                                {backupStatus.message || 'Backup not configured'}
                                            </p>
                                            {backupStatus.required_secrets && (
                                                <div className="text-white/60 text-sm">
                                                    <p className="mb-2">Add these secrets in the Secrets tab:</p>
                                                    <ul className="list-disc list-inside space-y-1">
                                                        {backupStatus.required_secrets.map(s => (
                                                            <li key={s} className="font-mono text-xs">{s}</li>
                                                        ))}
                                                    </ul>
                                                </div>
                                            )}
                                        </div>
                                    ) : (
                                        <div className="space-y-4">
                                            {/* Status Summary */}
                                            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                                                <div className="bg-white/5 rounded-lg p-3">
                                                    <div className="text-white/50 text-xs">Storage</div>
                                                    <div className="text-white font-medium truncate">{backupStatus.bucket}</div>
                                                </div>
                                                <div className="bg-white/5 rounded-lg p-3">
                                                    <div className="text-white/50 text-xs">Total Backups</div>
                                                    <div className="text-white font-bold text-lg">{backupStatus.total_backups || 0}</div>
                                                </div>
                                                <div className="bg-white/5 rounded-lg p-3">
                                                    <div className="text-white/50 text-xs">Last Backup</div>
                                                    <div className="text-white font-medium">
                                                        {backupStatus.last_backup
                                                            ? `${backupStatus.last_backup.age_days}d ago`
                                                            : 'Never'}
                                                    </div>
                                                </div>
                                                <div className="bg-white/5 rounded-lg p-3">
                                                    <div className="text-white/50 text-xs">Schedule</div>
                                                    <div className="text-white font-medium text-sm">{backupStatus.next_scheduled || 'Daily'}</div>
                                                </div>
                                            </div>

                                            {/* Actions */}
                                            <div className="flex gap-3">
                                                <Button
                                                    onClick={async () => {
                                                        if (!confirm('Create a new database backup now?')) return;
                                                        setIsCreatingBackup(true);
                                                        try {
                                                            const result = await api.createBackup();
                                                            if (result.status === 'success') {
                                                                alert(`Backup created: ${result.backup_name}`);
                                                                // Refresh list
                                                                const list = await api.listBackups();
                                                                setBackups(list.backups || []);
                                                                const status = await api.getBackupStatus();
                                                                setBackupStatus(status);
                                                            }
                                                        } catch (err) {
                                                            alert('Backup failed: ' + (err as Error).message);
                                                        } finally {
                                                            setIsCreatingBackup(false);
                                                        }
                                                    }}
                                                    disabled={isCreatingBackup}
                                                    className="bg-blue-600 hover:bg-blue-700"
                                                >
                                                    {isCreatingBackup ? (
                                                        <>
                                                            <RefreshCw className="w-4 h-4 mr-2 animate-spin" />
                                                            Creating...
                                                        </>
                                                    ) : (
                                                        <>
                                                            <Upload className="w-4 h-4 mr-2" />
                                                            Create Backup Now
                                                        </>
                                                    )}
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    onClick={async () => {
                                                        setIsLoadingBackups(true);
                                                        try {
                                                            const list = await api.listBackups();
                                                            setBackups(list.backups || []);
                                                        } catch (err) {
                                                            console.error(err);
                                                        } finally {
                                                            setIsLoadingBackups(false);
                                                        }
                                                    }}
                                                >
                                                    <RefreshCw className={`w-4 h-4 mr-2 ${isLoadingBackups ? 'animate-spin' : ''}`} />
                                                    Refresh
                                                </Button>
                                            </div>

                                            {/* Backup List */}
                                            {backups.length > 0 && (
                                                <div className="mt-4">
                                                    <h4 className="text-white/70 text-sm font-medium mb-2">Recent Backups</h4>
                                                    <div className="space-y-2 max-h-48 overflow-y-auto">
                                                        {backups.slice(0, 10).map((backup) => (
                                                            <div key={backup.name} className="flex items-center justify-between bg-white/5 rounded-lg p-3">
                                                                <div>
                                                                    <div className="text-white font-mono text-sm">{backup.name}</div>
                                                                    <div className="text-white/50 text-xs">
                                                                        {new Date(backup.created_at).toLocaleString()} · {(backup.size_bytes / 1024 / 1024).toFixed(2)} MB
                                                                    </div>
                                                                </div>
                                                                <span className={`text-xs px-2 py-1 rounded ${backup.age_days === 0 ? 'bg-green-500/20 text-green-400' :
                                                                    backup.age_days < 7 ? 'bg-blue-500/20 text-blue-400' :
                                                                        'bg-white/10 text-white/60'
                                                                    }`}>
                                                                    {backup.age_days === 0 ? 'Today' : `${backup.age_days}d ago`}
                                                                </span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </AccordionSection>

                                {/* Soft-Deleted Requests */}
                                {deletedRequests.length > 0 && (
                                    <AccordionSection
                                        title={`Soft-Deleted Requests`}
                                        subtitle="Requests removed by administrators but recoverable"
                                        icon={Trash2}
                                        iconClassName="text-red-400"
                                        badge={<Badge variant="danger">{deletedRequests.length}</Badge>}
                                    >
                                        <p className="text-white/60 mb-4 text-sm">
                                            These requests have been soft-deleted by administrators and are no longer visible to staff.
                                        </p>
                                        <div className="space-y-3 max-h-64 overflow-y-auto">
                                            {deletedRequests.map((req) => (
                                                <div key={req.id} className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
                                                    <div className="flex justify-between items-start">
                                                        <div>
                                                            <span className="text-white font-medium">{req.service_request_id}</span>
                                                            <p className="text-white/60 text-sm mt-1 line-clamp-1">{req.description}</p>
                                                        </div>
                                                        <span className="text-red-400 text-xs">
                                                            {req.deleted_at ? new Date(req.deleted_at).toLocaleDateString() : 'N/A'}
                                                        </span>
                                                    </div>
                                                    {req.delete_justification && (
                                                        <div className="mt-2 bg-black/20 rounded p-2">
                                                            <span className="text-xs text-white/50">Deletion Reason:</span>
                                                            <p className="text-sm text-red-300">{req.delete_justification}</p>
                                                        </div>
                                                    )}
                                                    <div className="flex items-center justify-between mt-2">
                                                        <p className="text-xs text-white/40">
                                                            Deleted by: {req.deleted_by || 'Unknown'}
                                                        </p>
                                                        <button
                                                            onClick={async () => {
                                                                if (window.confirm(`Restore request ${req.service_request_id}? This will make it visible to staff again.`)) {
                                                                    try {
                                                                        await api.restoreRequest(req.service_request_id);
                                                                        // Remove from deleted list
                                                                        setDeletedRequests(prev => prev.filter(r => r.id !== req.id));
                                                                    } catch (err) {
                                                                        console.error('Failed to restore:', err);
                                                                        alert("Failed to restore request");
                                                                    }
                                                                }
                                                            }}
                                                            className="px-3 py-1 bg-green-500/20 text-green-400 rounded text-xs hover:bg-green-500/30 transition-colors flex items-center gap-1"
                                                        >
                                                            <RotateCcw className="w-3 h-3" />
                                                            Restore
                                                        </button>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </AccordionSection>
                                )}

                                {/* State Selection */}
                                <AccordionSection
                                    title="Retention Policy Configuration"
                                    subtitle="Configure state-mandated record retention requirements"
                                    icon={Clock}
                                    iconClassName="text-amber-400"
                                >
                                    <p className="text-white/60 mb-4">Choose your state to apply the appropriate record retention requirements.</p>

                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        <div>
                                            <label className="block text-sm font-medium text-white/70 mb-2">State</label>
                                            <select
                                                value={selectedStateCode}
                                                onChange={(e) => setSelectedStateCode(e.target.value)}
                                                className="w-full bg-white/10 border border-white/20 rounded-lg px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-amber-400"
                                                aria-label="Select state for retention policy"
                                            >
                                                <option value="">Select a state...</option>
                                                {retentionStates.map((state) => (
                                                    <option key={state.code} value={state.code} className="bg-slate-800">
                                                        {state.name} ({state.retention_years} years)
                                                    </option>
                                                ))}
                                            </select>
                                        </div>

                                        <div>
                                            <label className="block text-sm font-medium text-white/70 mb-2">Archival Mode</label>
                                            <select
                                                value={selectedMode}
                                                onChange={(e) => setSelectedMode(e.target.value as 'anonymize' | 'delete')}
                                                className="w-full bg-white/10 border border-white/20 rounded-lg px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-amber-400"
                                                aria-label="Select archival mode"
                                            >
                                                <option value="anonymize" className="bg-slate-800">Anonymize (Remove PII, keep statistics)</option>
                                                <option value="delete" className="bg-slate-800">Delete (Permanent removal)</option>
                                            </select>
                                        </div>

                                        <div>
                                            <label className="block text-sm font-medium text-white/70 mb-2">Override Days (Optional)</label>
                                            <input
                                                type="number"
                                                value={overrideDays}
                                                onChange={(e) => setOverrideDays(e.target.value)}
                                                placeholder="Leave blank to use state default"
                                                min="365"
                                                className="w-full bg-white/10 border border-white/20 rounded-lg px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-amber-400 placeholder:text-white/40"
                                                aria-label="Custom retention days override"
                                            />
                                            <p className="text-white/40 text-xs mt-1">Min 365 days. Must be ≥ state requirement.</p>
                                        </div>
                                    </div>

                                    {/* Selected State Preview */}
                                    {selectedStateCode && retentionStates.find(s => s.code === selectedStateCode) && (
                                        <div className="mt-4 p-4 bg-amber-500/10 border border-amber-500/30 rounded-lg">
                                            <div className="flex items-start gap-3">
                                                <Clock className="w-5 h-5 text-amber-400 mt-0.5" />
                                                <div>
                                                    <p className="text-amber-400 font-medium">
                                                        {retentionStates.find(s => s.code === selectedStateCode)?.name}: {retentionStates.find(s => s.code === selectedStateCode)?.retention_years} year retention
                                                    </p>
                                                    <p className="text-white/60 text-sm mt-1">
                                                        Source: {retentionStates.find(s => s.code === selectedStateCode)?.source}
                                                    </p>
                                                </div>
                                            </div>
                                        </div>
                                    )}

                                    <div className="flex gap-4 mt-6">
                                        <Button
                                            onClick={async () => {
                                                if (!selectedStateCode) return;
                                                setIsSavingRetention(true);
                                                try {
                                                    await api.updateRetentionPolicy({
                                                        state_code: selectedStateCode,
                                                        mode: selectedMode,
                                                        override_days: overrideDays ? parseInt(overrideDays) : undefined
                                                    });
                                                    await loadTabData();
                                                    setSaveMessage('Retention policy updated successfully');
                                                    setTimeout(() => setSaveMessage(null), 3000);
                                                } catch (err) {
                                                    console.error('Failed to update retention policy:', err);
                                                } finally {
                                                    setIsSavingRetention(false);
                                                }
                                            }}
                                            disabled={!selectedStateCode || isSavingRetention}
                                            className="bg-gradient-to-r from-amber-400 to-orange-500 text-black"
                                        >
                                            {isSavingRetention ? 'Saving...' : 'Confirm & Apply Policy'}
                                        </Button>

                                        <Button
                                            variant="secondary"
                                            onClick={async () => {
                                                setIsRunningRetention(true);
                                                try {
                                                    const result = await api.runRetentionNow();
                                                    setSaveMessage(`Retention task started: ${result.message}`);
                                                    setTimeout(() => {
                                                        setSaveMessage(null);
                                                        loadTabData();
                                                    }, 3000);
                                                } catch (err) {
                                                    console.error('Failed to run retention:', err);
                                                } finally {
                                                    setIsRunningRetention(false);
                                                }
                                            }}
                                            disabled={isRunningRetention}
                                        >
                                            {isRunningRetention ? 'Running...' : 'Run Retention Now'}
                                        </Button>

                                        <Button
                                            variant="secondary"
                                            onClick={async () => {
                                                try {
                                                    await api.exportForPublicRecords();
                                                    setSaveMessage('Export downloaded successfully');
                                                    setTimeout(() => setSaveMessage(null), 3000);
                                                } catch (err) {
                                                    console.error('Export failed:', err);
                                                }
                                            }}
                                        >
                                            Export for {retentionPolicy?.policy?.public_records_law?.split("(")[0]?.trim() || 'FOIA'}
                                        </Button>
                                    </div>
                                </AccordionSection>

                                {/* All States Reference */}
                                <AccordionSection
                                    title={`All State Policies`}
                                    subtitle={`Reference guide for ${retentionStates.length} states with retention requirements`}
                                    icon={FileText}
                                    iconClassName="text-blue-400"
                                >
                                    <div className="overflow-x-auto">
                                        <table className="w-full text-sm">
                                            <thead>
                                                <tr className="border-b border-white/10">
                                                    <th className="text-left py-2 text-white/60">State</th>
                                                    <th className="text-left py-2 text-white/60">Code</th>
                                                    <th className="text-left py-2 text-white/60">Retention</th>
                                                    <th className="text-left py-2 text-white/60">Source</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {retentionStates.map((state) => (
                                                    <tr key={state.code} className="border-b border-white/5 hover:bg-white/5">
                                                        <td className="py-2 text-white">{state.name}</td>
                                                        <td className="py-2 text-white/60">{state.code}</td>
                                                        <td className="py-2">
                                                            <span className="text-amber-400 font-medium">{state.retention_years} years</span>
                                                        </td>
                                                        <td className="py-2 text-white/40 text-xs">{state.source}</td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                </AccordionSection>
                            </div>
                        )}

                        {/* System Health Tab */}
                        {currentTab === 'health' && (
                            <OperationsPanel />
                        )}

                        {/* Audit Logs - part of Compliance */}
                        {currentTab === 'compliance' && (
                            <div className="mt-8">
                                <AuditLogViewer />
                            </div>
                        )}

                    </div>
                </div>
            </div>

            {/* Add/Edit Department Modal */}
            <Modal
                isOpen={showDepartmentModal}
                onClose={() => {
                    setShowDepartmentModal(false);
                    setEditingDepartment(null);
                }}
                title={editingDepartment ? 'Edit Department' : 'Add New Department'}
            >
                <form onSubmit={handleCreateDepartment} className="space-y-4">
                    <Input
                        label="Department Name"
                        value={newDepartment.name}
                        onChange={(e) => setNewDepartment((p) => ({ ...p, name: e.target.value }))}
                        placeholder="e.g., Public Works"
                        required
                    />
                    <Input
                        label="Description"
                        value={newDepartment.description}
                        onChange={(e) => setNewDepartment((p) => ({ ...p, description: e.target.value }))}
                        placeholder="Handles roads, parks, infrastructure..."
                    />
                    <Input
                        label="Routing Email"
                        type="email"
                        value={newDepartment.routing_email}
                        onChange={(e) => setNewDepartment((p) => ({ ...p, routing_email: e.target.value }))}
                        placeholder="publicworks@township.gov"
                    />
                    <div className="flex justify-end gap-3 pt-4">
                        <Button variant="ghost" onClick={() => setShowDepartmentModal(false)}>Cancel</Button>
                        <Button type="submit">{editingDepartment ? 'Save Changes' : 'Create Department'}</Button>
                    </div>
                </form>
            </Modal>

            {/* Add User Modal */}
            <Modal isOpen={showUserModal} onClose={() => setShowUserModal(false)} title="Add New User">
                <form onSubmit={handleCreateUser} className="space-y-4">
                    <Input
                        label="Username"
                        value={newUser.username}
                        onChange={(e) => setNewUser((p) => ({ ...p, username: e.target.value }))}
                        required
                    />
                    <Input
                        label="Full Name"
                        value={newUser.full_name}
                        onChange={(e) => setNewUser((p) => ({ ...p, full_name: e.target.value }))}
                    />
                    <Input
                        label="Email"
                        type="email"
                        value={newUser.email}
                        onChange={(e) => setNewUser((p) => ({ ...p, email: e.target.value }))}
                        required
                    />

                    {/* SSO Info */}
                    <div className="p-3 rounded-lg bg-blue-500/10 border border-blue-500/20 text-sm text-blue-200">
                        <p className="font-medium">🔐 SSO Authentication</p>
                        <p className="text-blue-200/70 mt-1">
                            Users log in via Auth0 SSO using their email address. No password is required.
                        </p>
                    </div>

                    <Select
                        label="Role"
                        options={[
                            { value: 'staff', label: 'Staff' },
                            { value: 'admin', label: 'Admin' },
                        ]}
                        value={newUser.role}
                        onChange={(e) => setNewUser((p) => ({ ...p, role: e.target.value as 'staff' | 'admin' }))}
                    />

                    {/* Department Assignment */}
                    {newUser.role === 'staff' && departments.length > 0 && (
                        <div className="space-y-2">
                            <label className="block text-sm font-medium text-white/70">Assign to Departments</label>
                            <div className="grid grid-cols-2 gap-2 max-h-32 overflow-y-auto p-2 rounded-lg bg-white/5 border border-white/10">
                                {departments.map((dept) => (
                                    <label key={dept.id} className="flex items-center gap-2 cursor-pointer hover:bg-white/5 p-1 rounded">
                                        <input
                                            type="checkbox"
                                            checked={newUser.department_ids.includes(dept.id)}
                                            onChange={(e) => {
                                                if (e.target.checked) {
                                                    setNewUser((p) => ({ ...p, department_ids: [...p.department_ids, dept.id] }));
                                                } else {
                                                    setNewUser((p) => ({ ...p, department_ids: p.department_ids.filter(id => id !== dept.id) }));
                                                }
                                            }}
                                            className="w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500 focus:ring-primary-500"
                                        />
                                        <span className="text-sm text-white/80">{dept.name}</span>
                                    </label>
                                ))}
                            </div>
                        </div>
                    )}

                    <div className="flex justify-end gap-3 pt-4">
                        <Button variant="ghost" onClick={() => setShowUserModal(false)}>Cancel</Button>
                        <Button type="submit">Create User</Button>
                    </div>
                </form>
            </Modal>

            {/* Legal Hold Requests Modal */}
            <Modal
                isOpen={showLegalHoldModal}
                onClose={() => setShowLegalHoldModal(false)}
                title="Requests Under Legal Hold"
            >
                <div className="space-y-4">
                    {isLoadingLegalHold ? (
                        <div className="text-center py-8 text-white/60">Loading...</div>
                    ) : legalHoldRequests.length === 0 ? (
                        <div className="text-center py-8 text-white/60">
                            No requests are currently under legal hold.
                        </div>
                    ) : (
                        <>
                            <p className="text-white/60 text-sm">
                                These requests have been flagged and are protected from automatic archival or deletion.
                            </p>
                            <div className="space-y-3 max-h-[60vh] overflow-y-auto">
                                {legalHoldRequests.map((req) => (
                                    <button
                                        key={req.id}
                                        onClick={() => {
                                            setShowLegalHoldModal(false);
                                            // Map status to URL path segment
                                            const statusPath = req.status === 'open' ? 'active' :
                                                req.status === 'in_progress' ? 'in_progress' :
                                                    req.status === 'closed' ? 'resolved' : 'active';
                                            navigate(`/staff#${statusPath}/request/${req.service_request_id}`);
                                        }}
                                        className="w-full text-left bg-amber-500/10 border border-amber-500/30 rounded-lg p-4 hover:bg-amber-500/20 transition-colors"
                                    >
                                        <div className="flex justify-between items-start mb-2">
                                            <span className="font-mono text-amber-400 font-semibold">
                                                {req.service_request_id}
                                            </span>
                                            <span className={`text-xs px-2 py-1 rounded capitalize ${req.status === 'open' ? 'bg-emerald-500/20 text-emerald-400' :
                                                req.status === 'in_progress' ? 'bg-blue-500/20 text-blue-400' :
                                                    'bg-gray-500/20 text-gray-400'
                                                }`}>
                                                {req.status.replace('_', ' ')}
                                            </span>
                                        </div>
                                        <div className="text-white font-medium">{req.service_name}</div>
                                        {req.description && (
                                            <div className="text-white/60 text-sm mt-1 line-clamp-2">{req.description}</div>
                                        )}
                                        {req.address && (
                                            <div className="text-white/50 text-xs mt-2 flex items-center gap-1">
                                                <MapPin className="w-3 h-3" />
                                                {req.address}
                                            </div>
                                        )}
                                        <div className="text-white/40 text-xs mt-2">
                                            Submitted: {new Date(req.requested_datetime).toLocaleDateString()}
                                        </div>
                                    </button>
                                ))}
                            </div>
                        </>
                    )}
                    <div className="flex justify-end pt-4 border-t border-white/10">
                        <Button variant="ghost" onClick={() => setShowLegalHoldModal(false)}>Close</Button>
                    </div>
                </div>
            </Modal>

            {/* Add Service Modal */}
            <Modal isOpen={showServiceModal} onClose={() => setShowServiceModal(false)} title="Add Service Category">
                <form onSubmit={handleCreateService} className="space-y-4">
                    <Input
                        label="Service Name"
                        value={newService.service_name}
                        onChange={(e) => setNewService((p) => ({ ...p, service_name: e.target.value }))}
                        required
                    />
                    <Input
                        label="Service Code"
                        placeholder="POTHOLE, STREETLIGHT, etc."
                        value={newService.service_code}
                        onChange={(e) => setNewService((p) => ({ ...p, service_code: e.target.value.toUpperCase() }))}
                        required
                    />
                    <Input
                        label="Description"
                        value={newService.description}
                        onChange={(e) => setNewService((p) => ({ ...p, description: e.target.value }))}
                    />
                    <div className="flex justify-end gap-3 pt-4">
                        <Button variant="ghost" onClick={() => setShowServiceModal(false)}>Cancel</Button>
                        <Button type="submit">Create Category</Button>
                    </div>
                </form>
            </Modal>

            {/* Service Routing Edit Modal */}
            <Modal
                isOpen={showServiceEditModal}
                onClose={() => {
                    setShowServiceEditModal(false);
                    setEditingService(null);
                }}
                title={`Configure Routing: ${editingService?.service_name || ''}`}
            >
                <form onSubmit={handleSaveServiceRouting} className="space-y-5 max-h-[70vh] overflow-y-auto pr-2">
                    {/* Routing Mode */}
                    <div className="space-y-2">
                        <label className="block text-sm font-medium text-white/70">Routing Mode</label>
                        <div className="grid grid-cols-3 gap-2">
                            {[
                                { value: 'township', label: 'Township Handles', desc: 'We process this request' },
                                { value: 'third_party', label: '3rd Party Only', desc: 'Block & redirect' },
                                { value: 'road_based', label: 'Road-Based', desc: 'Route by address' },
                            ].map(mode => (
                                <button
                                    type="button"
                                    key={mode.value}
                                    onClick={() => setServiceRouting(p => ({ ...p, routing_mode: mode.value as any }))}
                                    className={`p-3 rounded-lg border text-left transition-colors ${serviceRouting.routing_mode === mode.value
                                        ? 'bg-primary-500/20 border-primary-500 text-white'
                                        : 'bg-white/5 border-white/10 text-white/70 hover:border-white/30'
                                        }`}
                                >
                                    <div className="font-medium text-sm">{mode.label}</div>
                                    <div className="text-xs text-white/50 mt-1">{mode.desc}</div>
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Icon Picker */}
                    <div className="space-y-2">
                        <label className="block text-sm font-medium text-white/70">Category Icon</label>
                        <div className="grid grid-cols-10 gap-1 p-2 rounded-lg bg-white/5 border border-white/10 max-h-24 overflow-y-auto">
                            {ICON_LIBRARY.map(({ name, icon: IconComponent }) => (
                                <button
                                    type="button"
                                    key={name}
                                    onClick={() => setServiceRouting(p => ({ ...p, icon: name }))}
                                    className={`p-2 rounded transition-colors ${serviceRouting.icon === name
                                        ? 'bg-primary-500 text-white'
                                        : 'bg-white/5 text-white/60 hover:bg-white/10'
                                        }`}
                                    title={name}
                                >
                                    <IconComponent className="w-4 h-4" />
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Township Mode Config */}
                    {serviceRouting.routing_mode === 'township' && (
                        <div className="space-y-4 p-4 rounded-lg bg-green-500/10 border border-green-500/20">
                            <h4 className="font-medium text-green-300 flex items-center gap-2">
                                <Check className="w-4 h-4" /> Township Handles This
                            </h4>

                            <div className="space-y-2">
                                <label className="block text-sm font-medium text-white/70">Assign to Department</label>
                                <select
                                    value={serviceRouting.assigned_department_id || ''}
                                    onChange={(e) => setServiceRouting(p => ({
                                        ...p,
                                        assigned_department_id: e.target.value ? parseInt(e.target.value) : null,
                                        routing_config: { ...p.routing_config, staff_ids: [] }
                                    }))}
                                    className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                                    aria-label="Assign to department"
                                >
                                    <option value="">Select department...</option>
                                    {departments.map(d => (
                                        <option key={d.id} value={d.id}>{d.name}</option>
                                    ))}
                                </select>
                            </div>

                            {serviceRouting.assigned_department_id && (
                                <div className="space-y-2">
                                    <label className="block text-sm font-medium text-white/70">Route To</label>
                                    <div className="grid grid-cols-2 gap-2">
                                        <button
                                            type="button"
                                            onClick={() => setServiceRouting(p => ({
                                                ...p,
                                                routing_config: { ...p.routing_config, route_to: 'all_staff', staff_ids: [] }
                                            }))}
                                            className={`p-3 rounded-lg border text-center ${serviceRouting.routing_config.route_to === 'all_staff'
                                                ? 'bg-primary-500/20 border-primary-500 text-white'
                                                : 'bg-white/5 border-white/10 text-white/70'
                                                }`}
                                        >
                                            <Users className="w-5 h-5 mx-auto mb-1" />
                                            <div className="text-sm font-medium">All Staff in Dept</div>
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => setServiceRouting(p => ({
                                                ...p,
                                                routing_config: { ...p.routing_config, route_to: 'specific_staff' }
                                            }))}
                                            className={`p-3 rounded-lg border text-center ${serviceRouting.routing_config.route_to === 'specific_staff'
                                                ? 'bg-primary-500/20 border-primary-500 text-white'
                                                : 'bg-white/5 border-white/10 text-white/70'
                                                }`}
                                        >
                                            <UserCheck className="w-5 h-5 mx-auto mb-1" />
                                            <div className="text-sm font-medium">Specific Staff</div>
                                        </button>
                                    </div>
                                    {serviceRouting.routing_config.route_to === 'specific_staff' && (
                                        <div className="space-y-2 mt-3">
                                            <label className="block text-xs text-white/50">Select staff members:</label>
                                            <div className="max-h-32 overflow-y-auto p-2 rounded-lg bg-white/5 border border-white/10">
                                                {users
                                                    .filter(u => u.role === 'staff' || u.role === 'admin')
                                                    .map(u => (
                                                        <label key={u.id} className="flex items-center gap-2 p-1.5 hover:bg-white/5 rounded cursor-pointer">
                                                            <input
                                                                type="checkbox"
                                                                checked={(serviceRouting.routing_config.staff_ids || []).includes(u.id)}
                                                                onChange={(e) => {
                                                                    const currentIds = serviceRouting.routing_config.staff_ids || [];
                                                                    const newIds = e.target.checked
                                                                        ? [...currentIds, u.id]
                                                                        : currentIds.filter((id: number) => id !== u.id);
                                                                    setServiceRouting(p => ({
                                                                        ...p,
                                                                        routing_config: { ...p.routing_config, staff_ids: newIds }
                                                                    }));
                                                                }}
                                                                className="w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500"
                                                            />
                                                            <span className="text-sm text-white/80">{u.full_name || u.username}</span>
                                                            <span className="text-xs text-white/40">@{u.username}</span>
                                                        </label>
                                                    ))}
                                            </div>
                                            {(serviceRouting.routing_config.staff_ids || []).length === 0 && (
                                                <p className="text-xs text-amber-400">No staff selected - will route to all staff</p>
                                            )}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Third Party Config */}
                    {serviceRouting.routing_mode === 'third_party' && (
                        <div className="space-y-4 p-4 rounded-lg bg-red-500/10 border border-red-500/20">
                            <h4 className="font-medium text-red-300 flex items-center gap-2">
                                <AlertTriangle className="w-4 h-4" /> Third Party Only (Blocks Submission)
                            </h4>
                            <p className="text-sm text-white/50">Users cannot submit requests. They see message + contacts.</p>

                            <div className="space-y-2">
                                <label className="block text-sm font-medium text-white/70">Message to Display</label>
                                <textarea
                                    rows={3}
                                    placeholder="This service is handled by the County..."
                                    value={serviceRouting.routing_config.message}
                                    onChange={(e) => setServiceRouting(p => ({
                                        ...p,
                                        routing_config: { ...p.routing_config, message: e.target.value }
                                    }))}
                                    className="w-full rounded-lg bg-white/10 border border-white/20 text-white px-3 py-2"
                                    aria-label="Message to display to users"
                                />
                            </div>

                            <div className="space-y-3">
                                <label className="block text-sm font-medium text-white/70">Contact Information</label>
                                {serviceRouting.routing_config.contacts.map((contact, idx) => (
                                    <div key={idx} className="p-3 rounded-lg bg-white/5 border border-white/10 space-y-2">
                                        <div className="flex justify-between items-center">
                                            <span className="text-xs text-white/40">Contact {idx + 1}</span>
                                            <button type="button" onClick={() => {
                                                const c = serviceRouting.routing_config.contacts.filter((_, i) => i !== idx);
                                                setServiceRouting(p => ({ ...p, routing_config: { ...p.routing_config, contacts: c } }));
                                            }} className="p-1 text-red-400 hover:text-red-300"><X className="w-3 h-3" /></button>
                                        </div>
                                        <input placeholder="Name (e.g., Mercer County Roads)" value={contact.name} onChange={(e) => {
                                            const c = [...serviceRouting.routing_config.contacts];
                                            c[idx] = { ...c[idx], name: e.target.value };
                                            setServiceRouting(p => ({ ...p, routing_config: { ...p.routing_config, contacts: c } }));
                                        }} className="w-full h-9 rounded-lg bg-white/10 border border-white/20 text-white px-3 text-sm" />
                                        <div className="grid grid-cols-2 gap-2">
                                            <input placeholder="Phone" value={contact.phone} onChange={(e) => {
                                                const c = [...serviceRouting.routing_config.contacts];
                                                c[idx] = { ...c[idx], phone: e.target.value };
                                                setServiceRouting(p => ({ ...p, routing_config: { ...p.routing_config, contacts: c } }));
                                            }} className="w-full h-9 rounded-lg bg-white/10 border border-white/20 text-white px-3 text-sm" />
                                            <input placeholder="Website URL" value={contact.url} onChange={(e) => {
                                                const c = [...serviceRouting.routing_config.contacts];
                                                c[idx] = { ...c[idx], url: e.target.value };
                                                setServiceRouting(p => ({ ...p, routing_config: { ...p.routing_config, contacts: c } }));
                                            }} className="w-full h-9 rounded-lg bg-white/10 border border-white/20 text-white px-3 text-sm" />
                                        </div>
                                    </div>
                                ))}
                                <button type="button" onClick={() => setServiceRouting(p => ({
                                    ...p,
                                    routing_config: { ...p.routing_config, contacts: [...p.routing_config.contacts, { name: '', phone: '', url: '' }] }
                                }))} className="text-sm text-primary-400 hover:text-primary-300 flex items-center gap-1">
                                    <Plus className="w-4 h-4" /> Add Contact
                                </button>
                            </div>
                        </div>
                    )}

                    {/* Road-Based Config */}
                    {serviceRouting.routing_mode === 'road_based' && (
                        <div className="space-y-4 p-4 rounded-lg bg-amber-500/10 border border-amber-500/20">
                            <h4 className="font-medium text-amber-300 flex items-center gap-2">
                                <Route className="w-4 h-4" /> Road-Based Routing
                            </h4>

                            {/* Default Handler */}
                            <div className="space-y-2">
                                <label className="block text-sm font-medium text-white/70">Default Handler</label>
                                <select
                                    value={serviceRouting.routing_config.default_handler}
                                    onChange={(e) => setServiceRouting(p => ({
                                        ...p,
                                        routing_config: { ...p.routing_config, default_handler: e.target.value as any }
                                    }))}
                                    className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                                    aria-label="Default handler"
                                >
                                    <option value="township">Township handles by default</option>
                                    <option value="third_party">Third party handles by default</option>
                                </select>
                            </div>

                            {/* Township Department */}
                            <div className="space-y-2">
                                <label className="block text-sm font-medium text-white/70">Township Department</label>
                                <select
                                    value={serviceRouting.assigned_department_id || ''}
                                    onChange={(e) => setServiceRouting(p => ({
                                        ...p,
                                        assigned_department_id: e.target.value ? parseInt(e.target.value) : null
                                    }))}
                                    className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                                >
                                    <option value="">Select department...</option>
                                    {departments.map(d => (
                                        <option key={d.id} value={d.id}>{d.name}</option>
                                    ))}
                                </select>
                            </div>

                            {/* Conditional Road Lists */}
                            {serviceRouting.routing_config.default_handler === 'township' ? (
                                <div className="space-y-2">
                                    <label className="block text-sm font-medium text-red-300">
                                        Exclusion List (Roads handled by Third Party)
                                    </label>
                                    <textarea
                                        rows={3}
                                        placeholder="County Rd 1, Route 206, State Hwy 27..."
                                        value={serviceRouting.routing_config.exclusion_list}
                                        onChange={(e) => setServiceRouting(p => ({
                                            ...p,
                                            routing_config: { ...p.routing_config, exclusion_list: e.target.value }
                                        }))}
                                        className="w-full rounded-lg bg-white/10 border border-white/20 text-white px-3 py-2"
                                    />
                                    <p className="text-xs text-white/40">These roads will redirect to third party</p>
                                </div>
                            ) : (
                                <div className="space-y-2">
                                    <label className="block text-sm font-medium text-green-300">
                                        Inclusion List (Roads we handle)
                                    </label>
                                    <textarea
                                        rows={3}
                                        placeholder="Main St, Oak Ave, Elm Rd..."
                                        value={serviceRouting.routing_config.inclusion_list}
                                        onChange={(e) => setServiceRouting(p => ({
                                            ...p,
                                            routing_config: { ...p.routing_config, inclusion_list: e.target.value }
                                        }))}
                                        className="w-full rounded-lg bg-white/10 border border-white/20 text-white px-3 py-2"
                                    />
                                    <p className="text-xs text-white/40">Only these roads will be processed by township</p>
                                </div>
                            )}

                            {/* Third Party Redirect Message */}
                            <div className="space-y-2 pt-2 border-t border-white/10">
                                <label className="block text-sm font-medium text-white/70">Third Party Redirect Message</label>
                                <textarea
                                    rows={2}
                                    placeholder="This road is maintained by the County..."
                                    value={serviceRouting.routing_config.third_party_message}
                                    onChange={(e) => setServiceRouting(p => ({
                                        ...p,
                                        routing_config: { ...p.routing_config, third_party_message: e.target.value }
                                    }))}
                                    className="w-full rounded-lg bg-white/10 border border-white/20 text-white px-3 py-2"
                                />
                            </div>
                        </div>
                    )}

                    {/* Custom Questions Builder - Only for township and road_based */}
                    {serviceRouting.routing_mode !== 'third_party' && (
                        <div className="space-y-4 p-4 rounded-lg bg-purple-500/10 border border-purple-500/20">
                            <div className="flex items-center justify-between">
                                <h4 className="font-medium text-purple-300 flex items-center gap-2">
                                    <AlertCircle className="w-4 h-4" /> Custom Follow-Up Questions
                                </h4>
                                <button
                                    type="button"
                                    onClick={() => setServiceRouting(p => ({
                                        ...p,
                                        routing_config: {
                                            ...p.routing_config,
                                            custom_questions: [
                                                ...p.routing_config.custom_questions,
                                                { id: crypto.randomUUID(), label: '', type: 'text', options: [], required: false, placeholder: '' }
                                            ]
                                        }
                                    }))}
                                    className="text-sm text-purple-400 hover:text-purple-300 flex items-center gap-1"
                                >
                                    <Plus className="w-4 h-4" /> Add Question
                                </button>
                            </div>

                            {serviceRouting.routing_config.custom_questions.length === 0 ? (
                                <p className="text-sm text-white/40 italic">No custom questions. Add questions to collect additional info from residents.</p>
                            ) : (
                                <div className="space-y-3">
                                    {serviceRouting.routing_config.custom_questions.map((q, idx) => (
                                        <div key={q.id} className="p-3 rounded-lg bg-white/5 border border-white/10 space-y-2">
                                            <div className="flex justify-between items-center">
                                                <span className="text-xs text-white/40">Question {idx + 1}</span>
                                                <button type="button" onClick={() => {
                                                    const newQs = serviceRouting.routing_config.custom_questions.filter((_, i) => i !== idx);
                                                    setServiceRouting(p => ({ ...p, routing_config: { ...p.routing_config, custom_questions: newQs } }));
                                                }} className="p-1 text-red-400 hover:text-red-300"><X className="w-3 h-3" /></button>
                                            </div>

                                            {/* Question Label */}
                                            <input
                                                placeholder="Question text..."
                                                value={q.label}
                                                onChange={(e) => {
                                                    const newQs = [...serviceRouting.routing_config.custom_questions];
                                                    newQs[idx] = { ...newQs[idx], label: e.target.value };
                                                    setServiceRouting(p => ({ ...p, routing_config: { ...p.routing_config, custom_questions: newQs } }));
                                                }}
                                                className="w-full h-9 rounded-lg bg-white/10 border border-white/20 text-white px-3 text-sm"
                                            />

                                            {/* Type and Required Row */}
                                            <div className="flex gap-2 items-center">
                                                <select
                                                    value={q.type}
                                                    onChange={(e) => {
                                                        const newQs = [...serviceRouting.routing_config.custom_questions];
                                                        newQs[idx] = { ...newQs[idx], type: e.target.value };
                                                        setServiceRouting(p => ({ ...p, routing_config: { ...p.routing_config, custom_questions: newQs } }));
                                                    }}
                                                    className="flex-1 h-9 rounded-lg bg-white/10 border border-white/20 text-white px-2 text-sm"
                                                >
                                                    <option value="text">Text (short)</option>
                                                    <option value="textarea">Text (long)</option>
                                                    <option value="number">Number</option>
                                                    <option value="date">Date</option>
                                                    <option value="yes_no">Yes / No</option>
                                                    <option value="select">Dropdown</option>
                                                    <option value="radio">Radio Buttons</option>
                                                    <option value="checkbox">Checkboxes</option>
                                                </select>
                                                <label className="flex items-center gap-2 text-sm text-white/70">
                                                    <input
                                                        type="checkbox"
                                                        checked={q.required}
                                                        onChange={(e) => {
                                                            const newQs = [...serviceRouting.routing_config.custom_questions];
                                                            newQs[idx] = { ...newQs[idx], required: e.target.checked };
                                                            setServiceRouting(p => ({ ...p, routing_config: { ...p.routing_config, custom_questions: newQs } }));
                                                        }}
                                                        className="rounded"
                                                    />
                                                    Required
                                                </label>
                                            </div>

                                            {/* Options (for select/radio/checkbox) */}
                                            {['select', 'radio', 'checkbox'].includes(q.type) && (
                                                <input
                                                    placeholder="Options (comma-separated): Option A, Option B, Option C"
                                                    value={q.options?.join(', ') || ''}
                                                    onChange={(e) => {
                                                        const newQs = [...serviceRouting.routing_config.custom_questions];
                                                        newQs[idx] = { ...newQs[idx], options: e.target.value.split(",").map(o => o.trim()) };
                                                        setServiceRouting(p => ({ ...p, routing_config: { ...p.routing_config, custom_questions: newQs } }));
                                                    }}
                                                    className="w-full h-9 rounded-lg bg-white/10 border border-white/20 text-white px-3 text-sm"
                                                />
                                            )}

                                            {/* Placeholder (for text types) */}
                                            {['text', 'textarea', 'number'].includes(q.type) && (
                                                <input
                                                    placeholder="Placeholder text (optional)"
                                                    value={q.placeholder}
                                                    onChange={(e) => {
                                                        const newQs = [...serviceRouting.routing_config.custom_questions];
                                                        newQs[idx] = { ...newQs[idx], placeholder: e.target.value };
                                                        setServiceRouting(p => ({ ...p, routing_config: { ...p.routing_config, custom_questions: newQs } }));
                                                    }}
                                                    className="w-full h-9 rounded-lg bg-white/10 border border-white/20 text-white/60 px-3 text-sm"
                                                />
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    <div className="flex justify-end gap-3 pt-4 border-t border-white/10">
                        <Button variant="ghost" onClick={() => setShowServiceEditModal(false)}>Cancel</Button>
                        <Button type="submit">Save Configuration</Button>
                    </div>
                </form>
            </Modal>

            {/* Layer Upload/Edit Modal */}
            <Modal
                isOpen={showLayerModal}
                onClose={() => setShowLayerModal(false)}
                title={editingLayer ? `Edit Layer: ${editingLayer.name}` : 'Add New Layer'}
            >
                <form
                    onSubmit={async (e) => {
                        e.preventDefault();
                        if (!newLayer.name || !newLayer.geojson) {
                            alert("Please provide a name and upload a GeoJSON file");
                            return;
                        }
                        try {
                            if (editingLayer) {
                                await api.updateMapLayer(editingLayer.id, {
                                    name: newLayer.name,
                                    description: newLayer.description,
                                    layer_type: newLayer.layer_type,
                                    fill_color: newLayer.fill_color,
                                    stroke_color: newLayer.stroke_color,
                                    fill_opacity: newLayer.fill_opacity,
                                    stroke_width: newLayer.stroke_width,
                                    service_codes: newLayer.service_codes,
                                    geojson: newLayer.geojson,
                                    routing_mode: newLayer.routing_mode,
                                    routing_config: newLayer.routing_config,
                                    visible_on_map: newLayer.visible_on_map,
                                });
                                setSaveMessage('Layer updated!');
                            } else {
                                await api.createMapLayer({
                                    name: newLayer.name,
                                    description: newLayer.description,
                                    layer_type: newLayer.layer_type,
                                    fill_color: newLayer.fill_color,
                                    stroke_color: newLayer.stroke_color,
                                    fill_opacity: newLayer.fill_opacity,
                                    stroke_width: newLayer.stroke_width,
                                    service_codes: newLayer.service_codes,
                                    geojson: newLayer.geojson,
                                    routing_mode: newLayer.routing_mode,
                                    routing_config: newLayer.routing_config,
                                    visible_on_map: newLayer.visible_on_map,
                                });
                                setSaveMessage('Layer created!');
                            }
                            setShowLayerModal(false);
                            loadTabData();
                            setTimeout(() => setSaveMessage(null), 3000);
                        } catch (err: any) {
                            console.error('Failed to save layer:', err);
                            alert(err.message || 'Failed to save layer');
                        }
                    }}
                    className="space-y-4"
                >
                    <Input
                        label="Layer Name"
                        placeholder="e.g., Parks, Storm Drains, Utilities"
                        value={newLayer.name}
                        onChange={(e) => setNewLayer(p => ({ ...p, name: e.target.value }))}
                        required
                    />

                    <Input
                        label="Description (optional)"
                        placeholder="Brief description of this layer"
                        value={newLayer.description}
                        onChange={(e) => setNewLayer(p => ({ ...p, description: e.target.value }))}
                    />

                    {/* Layer Type Selection - Must choose first */}
                    <div className="space-y-2">
                        <label className="block text-sm font-medium text-white/70">
                            Layer Type <span className="text-red-400">*</span>
                        </label>
                        <div className="grid grid-cols-1 gap-3">
                            <button
                                type="button"
                                onClick={() => setNewLayer(p => ({ ...p, layer_type: 'point' }))}
                                className={`p-4 rounded-lg border-2 transition-all ${newLayer.layer_type === 'point'
                                    ? 'border-primary-500 bg-primary-500/20 text-white'
                                    : 'border-white/20 bg-white/5 text-white/60 hover:border-white/40'
                                    }`}
                            >
                                <div className="text-2xl mb-1">📍</div>
                                <div className="font-semibold">Points</div>
                                <div className="text-xs opacity-60">Individual locations (trees, lights, signs, etc.)</div>
                            </button>
                        </div>
                    </div>

                    {/* Only show rest of form after layer type is selected */}
                    {newLayer.layer_type && (
                        <>

                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm font-medium text-white/70 mb-2">Fill Color</label>
                                    <div className="flex gap-2">
                                        <input
                                            type="color"
                                            value={newLayer.fill_color}
                                            onChange={(e) => setNewLayer(p => ({ ...p, fill_color: e.target.value }))}
                                            className="w-12 h-10 rounded cursor-pointer"
                                        />
                                        <input
                                            type="text"
                                            value={newLayer.fill_color}
                                            onChange={(e) => setNewLayer(p => ({ ...p, fill_color: e.target.value }))}
                                            className="flex-1 h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                                        />
                                    </div>
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-white/70 mb-2">Stroke Color</label>
                                    <div className="flex gap-2">
                                        <input
                                            type="color"
                                            value={newLayer.stroke_color}
                                            onChange={(e) => setNewLayer(p => ({ ...p, stroke_color: e.target.value }))}
                                            className="w-12 h-10 rounded cursor-pointer"
                                        />
                                        <input
                                            type="text"
                                            value={newLayer.stroke_color}
                                            onChange={(e) => setNewLayer(p => ({ ...p, stroke_color: e.target.value }))}
                                            className="flex-1 h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <label className="block text-sm font-medium text-white/70 mb-2">
                                        Fill Opacity: {Math.round(newLayer.fill_opacity * 100)}%
                                    </label>
                                    <input
                                        type="range"
                                        min="0"
                                        max="1"
                                        step="0.1"
                                        value={newLayer.fill_opacity}
                                        onChange={(e) => setNewLayer(p => ({ ...p, fill_opacity: parseFloat(e.target.value) }))}
                                        className="w-full"
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm font-medium text-white/70 mb-2">
                                        Stroke Width: {newLayer.stroke_width}px
                                    </label>
                                    <input
                                        type="range"
                                        min="1"
                                        max="10"
                                        value={newLayer.stroke_width}
                                        onChange={(e) => setNewLayer(p => ({ ...p, stroke_width: parseInt(e.target.value) }))}
                                        className="w-full"
                                    />
                                </div>
                            </div>

                            {/* Nominatim Boundary Search - Only for polygons */}
                            {newLayer.layer_type === 'polygon' && (
                                <div className="space-y-3 p-4 rounded-lg bg-white/5 border border-white/10">
                                    <label className="block text-sm font-medium text-white/70">
                                        Search for Boundary (from OpenStreetMap)
                                    </label>
                                    <div className="flex gap-2">
                                        <input
                                            type="text"
                                            placeholder="e.g., Princeton University, Central Park..."
                                            value={nominatimSearch}
                                            onChange={(e) => setNominatimSearch(e.target.value)}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter') {
                                                    e.preventDefault();
                                                    // Trigger search
                                                    if (nominatimSearch.trim()) {
                                                        setIsSearchingNominatim(true);
                                                        fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(nominatimSearch)}&format=json&polygon_geojson=0&limit=10`)
                                                            .then(res => res.json())
                                                            .then(results => {
                                                                setNominatimResults(results.filter((r: any) => r.osm_type === 'way' || r.osm_type === 'relation'));
                                                            })
                                                            .catch(console.error)
                                                            .finally(() => setIsSearchingNominatim(false));
                                                    }
                                                }
                                            }}
                                            className="flex-1 h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3 placeholder:text-white/40"
                                        />
                                        <Button
                                            type="button"
                                            variant="secondary"
                                            onClick={() => {
                                                if (nominatimSearch.trim()) {
                                                    setIsSearchingNominatim(true);
                                                    fetch(`https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(nominatimSearch)}&format=json&polygon_geojson=0&limit=10`)
                                                        .then(res => res.json())
                                                        .then(results => {
                                                            setNominatimResults(results.filter((r: any) => r.osm_type === 'way' || r.osm_type === 'relation'));
                                                        })
                                                        .catch(console.error)
                                                        .finally(() => setIsSearchingNominatim(false));
                                                }
                                            }}
                                            disabled={isSearchingNominatim}
                                        >
                                            {isSearchingNominatim ? 'Searching...' : 'Search'}
                                        </Button>
                                    </div>

                                    {nominatimResults.length > 0 && (
                                        <div className="max-h-48 overflow-y-auto space-y-1">
                                            {nominatimResults.map((result: any, idx: number) => (
                                                <button
                                                    key={idx}
                                                    type="button"
                                                    className="w-full text-left p-2 rounded-lg bg-white/5 hover:bg-white/10 text-white/80 text-sm transition-colors"
                                                    onClick={async () => {
                                                        // Fetch the actual boundary GeoJSON
                                                        setIsSearchingNominatim(true);
                                                        try {
                                                            const osmType = result.osm_type === 'way' ? 'W' : 'R';
                                                            const response = await fetch(
                                                                `https://nominatim.openstreetmap.org/details?osmtype=${osmType}&osmid=${result.osm_id}&format=json&polygon_geojson=1`
                                                            );
                                                            const details = await response.json();
                                                            if (details.geometry) {
                                                                const geojson = {
                                                                    type: 'Feature',
                                                                    properties: {
                                                                        name: result.display_name,
                                                                        osm_id: result.osm_id,
                                                                    },
                                                                    geometry: details.geometry,
                                                                };
                                                                setNewLayer(p => ({
                                                                    ...p,
                                                                    geojson,
                                                                    name: p.name || result.display_name.split(",")[0].trim()
                                                                }));
                                                                setNominatimResults([]);
                                                                setNominatimSearch('');
                                                            } else {
                                                                alert("Could not fetch boundary for this location");
                                                            }
                                                        } catch (err) {
                                                            console.error('Failed to fetch boundary:', err);
                                                            alert("Failed to fetch boundary");
                                                        } finally {
                                                            setIsSearchingNominatim(false);
                                                        }
                                                    }}
                                                >
                                                    <div className="font-medium">{result.display_name.split(",")[0]}</div>
                                                    <div className="text-xs text-white/50 truncate">{result.display_name}</div>
                                                </button>
                                            ))}
                                        </div>
                                    )}

                                    <p className="text-xs text-white/40">
                                        Press Enter or click Search to find boundaries. Select a result to load its boundary.
                                    </p>
                                </div>
                            )}

                            <div>
                                <label className="block text-sm font-medium text-white/70 mb-2">
                                    {newLayer.layer_type === 'polygon' ? 'Or Upload GeoJSON File' : 'GeoJSON File'}
                                </label>
                                <input
                                    type="file"
                                    accept=".geojson,.json"
                                    onChange={async (e) => {
                                        const file = e.target.files?.[0];
                                        if (!file) return;
                                        try {
                                            const text = await file.text();
                                            const geojson = JSON.parse(text);
                                            if (!geojson.type) {
                                                throw new Error('Invalid GeoJSON format');
                                            }
                                            setNewLayer(p => ({ ...p, geojson }));
                                        } catch (err) {
                                            alert("Failed to parse GeoJSON file");
                                        }
                                        e.target.value = '';
                                    }}
                                    className="w-full text-sm text-white/60 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-primary-500 file:text-white hover:file:bg-primary-600 file:cursor-pointer"
                                />
                                {newLayer.geojson && (
                                    <p className="text-xs text-green-400 mt-1">✓ GeoJSON loaded</p>
                                )}
                            </div>

                            {/* Category selector */}
                            <div>
                                <div className="flex items-center justify-between mb-2">
                                    <label className="block text-sm font-medium text-white/70">
                                        Show for Categories
                                    </label>
                                    <div className="flex gap-2">
                                        <button
                                            type="button"
                                            onClick={() => setNewLayer(p => ({ ...p, service_codes: services.map(s => s.service_code) }))}
                                            className="text-xs text-primary-400 hover:text-primary-300"
                                        >
                                            Select All
                                        </button>
                                        <span className="text-white/20">|</span>
                                        <button
                                            type="button"
                                            onClick={() => setNewLayer(p => ({ ...p, service_codes: [] }))}
                                            className="text-xs text-white/40 hover:text-white/60"
                                        >
                                            Clear All
                                        </button>
                                    </div>
                                </div>
                                {services.length === 0 ? (
                                    <p className="text-sm text-white/40 p-3 rounded-lg bg-white/5 border border-white/10">
                                        Loading categories...
                                    </p>
                                ) : (
                                    <div className="grid grid-cols-2 gap-2 max-h-48 overflow-y-auto p-3 rounded-lg bg-white/5 border border-white/10">
                                        {services.map((service) => (
                                            <label
                                                key={service.service_code}
                                                className="flex items-center gap-2 text-sm text-white/70 hover:text-white cursor-pointer p-2 rounded hover:bg-white/10"
                                            >
                                                <input
                                                    type="checkbox"
                                                    checked={newLayer.service_codes.includes(service.service_code)}
                                                    onChange={(e) => {
                                                        if (e.target.checked) {
                                                            setNewLayer(p => ({
                                                                ...p,
                                                                service_codes: [...p.service_codes, service.service_code]
                                                            }));
                                                        } else {
                                                            setNewLayer(p => ({
                                                                ...p,
                                                                service_codes: p.service_codes.filter(c => c !== service.service_code)
                                                            }));
                                                        }
                                                    }}
                                                    className="w-4 h-4 rounded border-white/30 bg-white/10 text-primary-500 focus:ring-primary-500 focus:ring-offset-0"
                                                />
                                                {service.service_name}
                                            </label>
                                        ))}
                                    </div>
                                )}
                                <p className="text-xs text-white/40 mt-1">
                                    {newLayer.service_codes.length === 0
                                        ? '⚠️ Layer will be hidden (select at least one category)'
                                        : newLayer.service_codes.length === services.length
                                            ? '✓ Layer visible for all categories'
                                            : `Layer visible for ${newLayer.service_codes.length} ${newLayer.service_codes.length === 1 ? 'category' : 'categories'}`
                                    }
                                </p>
                            </div>

                            <div className="flex justify-end gap-3 pt-4 border-t border-white/10">
                                <Button variant="ghost" onClick={() => setShowLayerModal(false)}>Cancel</Button>
                                <Button type="submit" disabled={!newLayer.layer_type}>{editingLayer ? 'Update Layer' : 'Create Layer'}</Button>
                            </div>
                        </>
                    )}
                </form>
            </Modal>

            {/* Password management handled by Auth0 SSO */}
        </div>
    );
}

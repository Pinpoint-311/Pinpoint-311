import React, { useState, useEffect, useRef, FormEvent } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
    Download,
    FileText,
    Map,
    Code,
    Clock,
    TrendingUp,
    MapPin,
    Filter,
    RefreshCw,
    Shield,
    Eye,
    BarChart3,
    Activity,
    Layers,
    Lock,
    ArrowLeft,
    Users,
    Cloud,
    MessageSquare,
    Building2,
    Brain,
    ChevronDown,
    ChevronUp,
    Database,
    Microscope,
    Sparkles,
    Send,
    X,
} from 'lucide-react';
import { Button, Card } from '../components/ui';
import { useAuth } from '../context/AuthContext';
import { useSettings } from '../context/SettingsContext';
import { api, ResearchAnalytics, ResearchCodeSnippets } from '../services/api';

// Research pack definitions with all fields
const RESEARCH_PACKS = [
    {
        id: 'social_equity',
        name: 'Social Equity Pack',
        icon: Users,
        color: 'purple',
        audience: 'Equity Analysts, Social Researchers',
        fields: [
            { name: 'census_tract_geoid', type: 'string', description: '11-digit FIPS code for Census dataset joins', source: 'US Census Geocoder API (real)' },
            { name: 'social_vulnerability_index', type: 'float (0-1)', description: 'CDC SVI (0=lowest, 1=highest vulnerability)', source: 'Derived from GEOID' },
            { name: 'housing_tenure_renter_pct', type: 'float (0-1)', description: 'Renter % in zone (ownership patterns)', source: 'Derived from GEOID' },
            { name: 'income_quintile', type: 'int (1-5)', description: 'Anonymized income quintile of zone', source: 'Zone-based proxy' },
            { name: 'population_density', type: 'string', description: 'low / medium / high density category', source: 'Zone-based proxy' },
        ],
        suggestedAnalyses: [
            'Join with Census ACS for demographic correlation',
            'SVI vs response time regression',
            'Renter vs owner reporting rate comparison',
            'Income quintile service disparity analysis',
        ],
    },
    {
        id: 'environmental',
        name: 'Environmental Context Pack',
        icon: Cloud,
        color: 'blue',
        audience: 'Planners, Engineers, Operations Staff',
        fields: [
            { name: 'weather_precip_24h_mm', type: 'float', description: 'Precipitation in 24h before report (mm)', source: 'Open-Meteo Archive API (real)' },
            { name: 'weather_temp_max_c', type: 'float', description: 'Max temperature on report day (°C)', source: 'Open-Meteo Archive API (real)' },
            { name: 'weather_temp_min_c', type: 'float', description: 'Min temperature on report day (°C)', source: 'Open-Meteo Archive API (real)' },
            { name: 'weather_code', type: 'int', description: 'WMO weather code (e.g., 61=rain)', source: 'Open-Meteo Archive API (real)' },
            { name: 'nearby_asset_age_years', type: 'float', description: 'Age of matched infrastructure asset', source: 'Asset properties (real)' },
            { name: 'matched_asset_attributes', type: 'JSON string', description: 'Full properties of matched asset', source: 'GeoJSON layer (real)' },
            { name: 'season', type: 'string', description: 'winter / spring / summer / fall', source: 'Calculated' },
        ],
        suggestedAnalyses: [
            'Freeze-thaw cycle pothole correlation',
            'Asset age survival analysis',
            'Precipitation-drainage issue linkage',
            'Seasonal maintenance optimization',
        ],
    },
    {
        id: 'sentiment_trust',
        name: 'Sentiment & Trust Pack',
        icon: MessageSquare,
        color: 'pink',
        audience: 'Civic Engagement Analysts, Administrators',
        fields: [
            { name: 'sentiment_score', type: 'float (-1 to +1)', description: 'NLP sentiment (-1=angry, +1=grateful)', source: 'Word-based NLP (real)' },
            { name: 'is_repeat_report', type: 'boolean', description: 'Text indicates prior report of same issue', source: 'Regex detection (real)' },
            { name: 'prior_report_mentioned', type: 'boolean', description: 'References ticket/case number', source: 'Regex detection (real)' },
            { name: 'frustration_expressed', type: 'boolean', description: 'Trust erosion indicators present', source: 'Regex detection (real)' },
        ],
        suggestedAnalyses: [
            'Sentiment vs income quintile correlation',
            'Repeat report resolution success rates',
            'Trust erosion indicators over time',
            'Politeness variation by submission channel',
        ],
    },
    {
        id: 'bureaucratic_friction',
        name: 'Bureaucratic Friction Pack',
        icon: Building2,
        color: 'orange',
        audience: 'Operations Managers, Process Analysts',
        fields: [
            { name: 'time_to_triage_hours', type: 'float', description: 'Hours from submission to first "In Progress"', source: 'Audit logs (real)' },
            { name: 'reassignment_count', type: 'int', description: 'Times request bounced between departments', source: 'Audit logs (real)' },
            { name: 'off_hours_submission', type: 'boolean', description: 'Submitted before 6am or after 10pm', source: 'Timestamp (real)' },
            { name: 'escalation_occurred', type: 'boolean', description: 'Priority was manually increased by staff', source: 'Audit logs (real)' },
            { name: 'total_hours_to_resolve', type: 'float', description: 'Total hours from submission to closure', source: 'Calculated (real)' },
            { name: 'business_hours_to_resolve', type: 'float', description: 'Business hours only (Mon-Fri 8am-5pm)', source: 'Calculated (real)' },
            { name: 'days_to_first_update', type: 'float', description: 'Days until first staff action', source: 'Calculated (real)' },
            { name: 'status_change_count', type: 'int', description: 'Number of status changes', source: 'Audit logs (real)' },
        ],
        suggestedAnalyses: [
            'Triage time vs resolution outcome',
            'Department routing efficiency audit',
            'Off-hours urgent issue patterns',
            'AI escalation accuracy study',
        ],
    },
    {
        id: 'ai_ml',
        name: 'AI/ML Research Pack',
        icon: Brain,
        color: 'green',
        audience: 'Data Scientists, AI/ML Engineers',
        fields: [
            { name: 'ai_flagged', type: 'boolean', description: 'AI flagged for staff review', source: 'Vertex AI (real)' },
            { name: 'ai_flag_reason', type: 'string', description: 'Reason for AI flag (safety, urgent)', source: 'Vertex AI (real)' },
            { name: 'ai_priority_score', type: 'float (1-10)', description: 'AI-generated priority', source: 'Vertex AI (real)' },
            { name: 'ai_classification', type: 'string', description: 'AI-assigned category', source: 'Vertex AI (real)' },
            { name: 'ai_summary_sanitized', type: 'string', description: 'AI summary (PII redacted)', source: 'Vertex AI (real)' },
            { name: 'ai_analyzed', type: 'boolean', description: 'Whether AI processed this request', source: 'System (real)' },
            { name: 'ai_vs_manual_priority_diff', type: 'float', description: 'manual_priority - ai_priority', source: 'Calculated (real)' },
        ],
        suggestedAnalyses: [
            'AI-human priority alignment study',
            'Flagging accuracy and false positive rates',
            'Classification accuracy compared to final service_code',
            'NLP summarization quality assessment',
        ],
    },
];

// Core fields always included
const CORE_FIELDS = [
    { name: 'request_id', type: 'string', description: 'Unique identifier for the service request' },
    { name: 'service_code', type: 'string', description: 'Category code (e.g., pothole, streetlight)' },
    { name: 'service_name', type: 'string', description: 'Human-readable category name' },
    { name: 'infrastructure_category', type: 'string', description: 'Grouped infrastructure type' },
    { name: 'matched_asset_type', type: 'string', description: 'Type of matched infrastructure asset' },
    { name: 'description_sanitized', type: 'string', description: 'Issue description (PII redacted)' },
    { name: 'description_word_count', type: 'int', description: 'Word count of description' },
    { name: 'has_photos', type: 'boolean', description: 'Request includes photo attachments' },
    { name: 'photo_count', type: 'int', description: 'Number of photos attached' },
    { name: 'status', type: 'string', description: 'Current status (open, in_progress, closed)' },
    { name: 'closed_substatus', type: 'string', description: 'Resolution type (resolved, no_action, etc.)' },
    { name: 'priority', type: 'int (1-10)', description: 'Priority level (1=highest)' },
    { name: 'resolution_outcome', type: 'string', description: 'Standardized resolution category' },
    { name: 'address_anonymized', type: 'string', description: 'Generalized address (street only)' },
    { name: 'latitude', type: 'float', description: 'Latitude (fuzzed in privacy mode)' },
    { name: 'longitude', type: 'float', description: 'Longitude (fuzzed in privacy mode)' },
    { name: 'zone_id', type: 'string', description: 'Geographic zone identifier' },
    { name: 'submitted_datetime', type: 'ISO datetime', description: 'When request was submitted' },
    { name: 'closed_datetime', type: 'ISO datetime', description: 'When request was closed' },
    { name: 'submission_hour', type: 'int (0-23)', description: 'Hour of submission' },
    { name: 'submission_day_of_week', type: 'int (0-6)', description: 'Day of week (0=Monday)' },
    { name: 'is_weekend_submission', type: 'boolean', description: 'Submitted on weekend' },
    { name: 'is_business_hours_submission', type: 'boolean', description: 'Submitted 8am-5pm Mon-Fri' },
    { name: 'submission_channel', type: 'string', description: 'How submitted (portal, phone)' },
    { name: 'department_id', type: 'int', description: 'Assigned department ID' },
    { name: 'comment_count', type: 'int', description: 'Total comments on request' },
    { name: 'public_comment_count', type: 'int', description: 'Public/external comments' },
];

export const ResearchLab: React.FC = () => {
    const navigate = useNavigate();
    const { user } = useAuth();
    const { settings } = useSettings();

    // Check access
    useEffect(() => {
        if (user && user.role !== 'researcher' && user.role !== 'admin') {
            navigate('/staff');
        }
    }, [user, navigate]);

    // Set browser tab title
    useEffect(() => {
        const previousTitle = document.title;
        document.title = 'Research & Analytics Lab | ' + (settings?.township_name || '311');
        return () => {
            document.title = previousTitle;
        };
    }, [settings?.township_name]);

    // Query state
    const [startDate, setStartDate] = useState<string>('');
    const [endDate, setEndDate] = useState<string>('');
    const [serviceCode, setServiceCode] = useState<string>('');
    const [privacyMode, setPrivacyMode] = useState<'fuzzed' | 'exact'>('fuzzed');

    // Data state
    const [analytics, setAnalytics] = useState<ResearchAnalytics | null>(null);
    const [codeSnippets, setCodeSnippets] = useState<ResearchCodeSnippets | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [isEnabled, setIsEnabled] = useState<boolean | null>(null);
    const [error, setError] = useState<string | null>(null);

    // UI state
    const [activeSnippet, setActiveSnippet] = useState<'python' | 'r'>('python');
    const [expandedPack, setExpandedPack] = useState<string | null>('social_equity');
    const [showCoreFields, setShowCoreFields] = useState(false);

    // AI Chat state
    const [showChat, setShowChat] = useState(false);
    const [chatMessages, setChatMessages] = useState<{ role: 'user' | 'assistant'; content: string }[]>([
        { role: 'assistant', content: '👋 Hi! I\'m the Research Data Assistant. I can help you understand our data fields, suggest statistical analyses, explain methodology, and provide code snippets. What would you like to know?' }
    ]);
    const [chatInput, setChatInput] = useState('');
    const [chatLoading, setChatLoading] = useState(false);
    const chatEndRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (chatEndRef.current) chatEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }, [chatMessages, chatLoading]);

    const sendResearchChat = async (e?: FormEvent) => {
        e?.preventDefault();
        const msg = chatInput.trim();
        if (!msg || chatLoading) return;
        const newMessages = [...chatMessages, { role: 'user' as const, content: msg }];
        setChatMessages(newMessages);
        setChatInput('');
        setChatLoading(true);
        try {
            const result = await api.researchChat(msg, newMessages.slice(0, -1));
            setChatMessages(prev => [...prev, { role: 'assistant', content: result.response }]);
        } catch (err: any) {
            setChatMessages(prev => [...prev, { role: 'assistant', content: `⚠️ ${err.message || 'Failed to get AI response'}` }]);
        } finally {
            setChatLoading(false);
        }
    };

    // Check if research suite is enabled
    useEffect(() => {
        checkEnabled();
    }, []);

    const checkEnabled = async () => {
        try {
            const status = await api.getResearchStatus();
            setIsEnabled(status.enabled);
            if (status.enabled) {
                loadAnalytics();
                loadCodeSnippets();
            }
        } catch {
            setIsEnabled(false);
        }
    };

    const loadAnalytics = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const data = await api.getResearchAnalytics({
                start_date: startDate || undefined,
                end_date: endDate || undefined,
                service_code: serviceCode || undefined,
            });
            setAnalytics(data);
        } catch (err: any) {
            setError(err.message || 'Failed to load analytics');
        } finally {
            setIsLoading(false);
        }
    };

    const loadCodeSnippets = async () => {
        try {
            const snippets = await api.getResearchCodeSnippets();
            setCodeSnippets(snippets);
        } catch (err) {
            console.error('Failed to load code snippets', err);
        }
    };

    const handleExportCSV = async () => {
        try {
            const blob = await api.exportResearchCSV({
                start_date: startDate || undefined,
                end_date: endDate || undefined,
                service_code: serviceCode || undefined,
                privacy_mode: privacyMode,
            });
            const url = window.URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = `research_export_${new Date().toISOString().slice(0, 10)}.csv`;
            link.click();
            window.URL.revokeObjectURL(url);
        } catch (err: any) {
            setError(err.message || 'Export failed');
        }
    };

    const handleExportGeoJSON = async () => {
        try {
            const blob = await api.exportResearchGeoJSON({
                start_date: startDate || undefined,
                end_date: endDate || undefined,
                service_code: serviceCode || undefined,
                privacy_mode: privacyMode,
            });
            const url = window.URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = `research_export_${new Date().toISOString().slice(0, 10)}.geojson`;
            link.click();
            window.URL.revokeObjectURL(url);
        } catch (err: any) {
            setError(err.message || 'Export failed');
        }
    };

    const handleExportDataDictionary = async () => {
        try {
            const blob = await api.exportDataDictionary();
            const url = window.URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = `data_dictionary_${new Date().toISOString().slice(0, 10)}.csv`;
            link.click();
            window.URL.revokeObjectURL(url);
        } catch (err: any) {
            setError(err.message || 'Export failed');
        }
    };

    const copyToClipboard = (text: string) => {
        navigator.clipboard.writeText(text);
    };

    const getPackColorClasses = (color: string) => {
        const colors: Record<string, { bg: string; text: string; border: string }> = {
            // Text colors brightened from *-400 to *-200 for WCAG AA contrast
            purple: { bg: 'bg-purple-500/20', text: 'text-purple-200', border: 'border-purple-500/30' },
            blue: { bg: 'bg-blue-500/20', text: 'text-blue-200', border: 'border-blue-500/30' },
            pink: { bg: 'bg-pink-500/20', text: 'text-pink-200', border: 'border-pink-500/30' },
            orange: { bg: 'bg-orange-500/20', text: 'text-orange-200', border: 'border-orange-500/30' },
            green: { bg: 'bg-green-500/20', text: 'text-green-200', border: 'border-green-500/30' },
        };
        return colors[color] || colors.purple;
    };

    // Count total fields
    const totalFields = CORE_FIELDS.length + RESEARCH_PACKS.reduce((sum, pack) => sum + pack.fields.length, 0);

    // Not enabled state
    if (isEnabled === false) {
        return (
            <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center">
                <Card className="max-w-md text-center p-8">
                    <Lock className="w-16 h-16 text-amber-400 mx-auto mb-4" />
                    <h1 className="text-2xl font-bold text-white mb-2">Research Suite Disabled</h1>
                    <p className="text-white/60 mb-4">
                        The Research Suite is not enabled for this installation.
                        Contact your administrator to enable it.
                    </p>
                    <Button onClick={() => navigate(-1)}>
                        <ArrowLeft className="w-4 h-4 mr-2" />
                        Go Back
                    </Button>
                </Card>
            </div>
        );
    }

    // Loading state
    if (isEnabled === null) {
        return (
            <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 flex items-center justify-center" role="status" aria-label="Loading research portal">
                <RefreshCw className="w-8 h-8 text-primary-400 animate-spin" aria-hidden="true" />
                <span className="sr-only">Loading research portal, please wait...</span>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
            {/* Header */}
            <header className="glass-card border-b border-white/10 sticky top-0 z-50">
                <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <Button variant="ghost" onClick={() => navigate(-1)} aria-label="Go back to previous page">
                            <ArrowLeft className="w-5 h-5" aria-hidden="true" />
                        </Button>
                        <div>
                            <h1 className="text-xl font-bold text-white flex items-center gap-2">
                                <Microscope className="w-6 h-6 text-amber-400" />
                                Research & Analytics Lab
                            </h1>
                            <p className="text-sm text-white/50">
                                {settings?.township_name} • {totalFields} research fields available
                            </p>
                        </div>
                    </div>
                    <div className="flex items-center gap-4">
                        <Button
                            variant="ghost"
                            onClick={() => setShowChat(!showChat)}
                            className={`flex items-center gap-2 ${showChat ? 'bg-amber-500/20 text-amber-300' : ''}`}
                        >
                            <Sparkles className="w-4 h-4" />
                            Ask AI
                        </Button>
                        <div className="flex items-center gap-2 text-sm text-white/60">
                            <Database className="w-4 h-4" />
                            <span>{user?.username} ({user?.role})</span>
                        </div>
                    </div>
                </div>
            </header>

            <main className="max-w-7xl mx-auto px-6 py-8">
                {/* Hero Section */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mb-8 text-center"
                >
                    <h2 className="text-3xl font-bold text-white mb-3">
                        Research Data Export
                    </h2>
                    <p className="text-white/60 max-w-2xl mx-auto">
                        Export rich, privacy-preserving datasets for operational analysis, equity studies,
                        infrastructure planning, and data science. All {totalFields} fields computed on-the-fly with real data sources.
                    </p>
                </motion.div>

                {/* Error display */}
                {error && (
                    <motion.div
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="bg-red-500/20 border border-red-500/30 rounded-xl p-4 mb-6"
                        role="alert"
                        aria-live="assertive"
                    >
                        <p className="text-red-400">{error}</p>
                    </motion.div>
                )}

                {/* Research Packs Section */}
                <section className="mb-8" aria-labelledby="research-packs-heading">
                    <h2 id="research-packs-heading" className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                        <Database className="w-5 h-5 text-amber-400" aria-hidden="true" />
                        Research Field Packs ({RESEARCH_PACKS.reduce((sum, p) => sum + p.fields.length, 0)} specialized fields)
                    </h2>
                    <div className="space-y-3">
                        {RESEARCH_PACKS.map((pack) => {
                            const colors = getPackColorClasses(pack.color);
                            const isExpanded = expandedPack === pack.id;
                            const Icon = pack.icon;

                            return (
                                <motion.div
                                    key={pack.id}
                                    initial={{ opacity: 0, y: 10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    className={`rounded-xl border ${colors.border} overflow-hidden`}
                                >
                                    <button
                                        onClick={() => setExpandedPack(isExpanded ? null : pack.id)}
                                        className={`w-full px-5 py-4 flex items-center justify-between ${colors.bg} hover:bg-white/5 transition-colors`}
                                        aria-expanded={isExpanded}
                                        aria-controls={`pack-content-${pack.id}`}
                                    >
                                        <div className="flex items-center gap-4">
                                            <div className={`w-10 h-10 rounded-lg ${colors.bg} flex items-center justify-center`} aria-hidden="true">
                                                <Icon className={`w-5 h-5 ${colors.text}`} />
                                            </div>
                                            <div className="text-left">
                                                <h3 className={`font-semibold ${colors.text}`}>{pack.name}</h3>
                                                <p className="text-sm text-white/50">
                                                    {pack.audience} • {pack.fields.length} fields
                                                </p>
                                            </div>
                                        </div>
                                        {isExpanded ? (
                                            <ChevronUp className="w-5 h-5 text-white/40" />
                                        ) : (
                                            <ChevronDown className="w-5 h-5 text-white/40" />
                                        )}
                                    </button>

                                    <AnimatePresence>
                                        {isExpanded && (
                                            <motion.div
                                                id={`pack-content-${pack.id}`}
                                                initial={{ height: 0, opacity: 0 }}
                                                animate={{ height: 'auto', opacity: 1 }}
                                                exit={{ height: 0, opacity: 0 }}
                                                transition={{ duration: 0.2 }}
                                                className="overflow-hidden"
                                            >
                                                <div className="p-5 bg-white/5 border-t border-white/10">
                                                    {/* Fields Table */}
                                                    <div className="overflow-x-auto mb-4">
                                                        <table className="w-full text-sm">
                                                            <thead>
                                                                <tr className="text-left text-white/50 border-b border-white/10">
                                                                    <th className="pb-2 pr-4">Field Name</th>
                                                                    <th className="pb-2 pr-4">Type</th>
                                                                    <th className="pb-2 pr-4">Description</th>
                                                                    <th className="pb-2">Data Source</th>
                                                                </tr>
                                                            </thead>
                                                            <tbody>
                                                                {pack.fields.map((field) => (
                                                                    <tr key={field.name} className="border-b border-white/5">
                                                                        <td className="py-2 pr-4">
                                                                            <code className={`px-2 py-0.5 rounded ${colors.bg} ${colors.text} text-xs`}>
                                                                                {field.name}
                                                                            </code>
                                                                        </td>
                                                                        <td className="py-2 pr-4 text-white/70 font-mono text-xs">
                                                                            {field.type}
                                                                        </td>
                                                                        <td className="py-2 pr-4 text-white/60">
                                                                            {field.description}
                                                                        </td>
                                                                        <td className="py-2 text-white/50 text-xs">
                                                                            {field.source}
                                                                        </td>
                                                                    </tr>
                                                                ))}
                                                            </tbody>
                                                        </table>
                                                    </div>

                                                    {/* Suggested Analyses */}
                                                    <div>
                                                        <h4 className="text-sm font-medium text-white/70 mb-2">Suggested Analyses:</h4>
                                                        <div className="flex flex-wrap gap-2">
                                                            {pack.suggestedAnalyses.map((analysis, i) => (
                                                                <span
                                                                    key={i}
                                                                    className="px-3 py-1 rounded-full bg-white/10 text-white/60 text-xs"
                                                                >
                                                                    {analysis}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    </div>
                                                </div>
                                            </motion.div>
                                        )}
                                    </AnimatePresence>
                                </motion.div>
                            );
                        })}

                        {/* Core Fields Collapsible */}
                        <motion.div
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="rounded-xl border border-white/20 overflow-hidden"
                        >
                            <button
                                onClick={() => setShowCoreFields(!showCoreFields)}
                                className="w-full px-5 py-4 flex items-center justify-between bg-white/5 hover:bg-white/10 transition-colors"
                            >
                                <div className="flex items-center gap-4">
                                    <div className="w-10 h-10 rounded-lg bg-white/10 flex items-center justify-center">
                                        <Layers className="w-5 h-5 text-white/60" />
                                    </div>
                                    <div className="text-left">
                                        <h3 className="font-semibold text-white/80">Core Request Fields</h3>
                                        <p className="text-sm text-white/50">
                                            Standard fields included in all exports • {CORE_FIELDS.length} fields
                                        </p>
                                    </div>
                                </div>
                                {showCoreFields ? (
                                    <ChevronUp className="w-5 h-5 text-white/40" />
                                ) : (
                                    <ChevronDown className="w-5 h-5 text-white/40" />
                                )}
                            </button>

                            <AnimatePresence>
                                {showCoreFields && (
                                    <motion.div
                                        initial={{ height: 0, opacity: 0 }}
                                        animate={{ height: 'auto', opacity: 1 }}
                                        exit={{ height: 0, opacity: 0 }}
                                        transition={{ duration: 0.2 }}
                                        className="overflow-hidden"
                                    >
                                        <div className="p-5 bg-white/5 border-t border-white/10 max-h-64 overflow-y-auto">
                                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                                {CORE_FIELDS.map((field) => (
                                                    <div key={field.name} className="flex items-start gap-2 text-sm">
                                                        <code className="px-2 py-0.5 rounded bg-white/10 text-white/70 text-xs shrink-0">
                                                            {field.name}
                                                        </code>
                                                        <span className="text-white/50 text-xs">{field.description}</span>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    </motion.div>
                                )}
                            </AnimatePresence>
                        </motion.div>
                    </div>
                </section>

                {/* Query Builder */}
                <Card className="mb-8">
                    <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                        <Filter className="w-5 h-5 text-primary-400" />
                        Query Builder
                    </h2>
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                        <div>
                            <label className="block text-sm text-white/60 mb-2">Start Date</label>
                            <input
                                type="date"
                                value={startDate}
                                onChange={(e) => setStartDate(e.target.value)}
                                className="w-full px-4 py-2 rounded-lg bg-white/10 border border-white/20 text-white focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                            />
                        </div>
                        <div>
                            <label className="block text-sm text-white/60 mb-2">End Date</label>
                            <input
                                type="date"
                                value={endDate}
                                onChange={(e) => setEndDate(e.target.value)}
                                className="w-full px-4 py-2 rounded-lg bg-white/10 border border-white/20 text-white focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                            />
                        </div>
                        <div>
                            <label className="block text-sm text-white/60 mb-2">Service Category</label>
                            <input
                                type="text"
                                value={serviceCode}
                                onChange={(e) => setServiceCode(e.target.value)}
                                placeholder="e.g., pothole"
                                className="w-full px-4 py-2 rounded-lg bg-white/10 border border-white/20 text-white placeholder-white/40 focus:ring-2 focus:ring-primary-500 focus:border-transparent"
                            />
                        </div>
                        <div className="flex items-end">
                            <Button onClick={loadAnalytics} disabled={isLoading} className="w-full">
                                {isLoading ? (
                                    <RefreshCw className="w-4 h-4 animate-spin mr-2" />
                                ) : (
                                    <Activity className="w-4 h-4 mr-2" />
                                )}
                                Run Query
                            </Button>
                        </div>
                    </div>

                    {/* Privacy Mode Toggle */}
                    <div className="mt-4 pt-4 border-t border-white/10 flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <Eye className="w-5 h-5 text-amber-400" />
                            <div>
                                <span className="text-white font-medium">Privacy Mode</span>
                                <p className="text-sm text-white/50">
                                    {privacyMode === 'fuzzed'
                                        ? 'Locations fuzzed to ~100ft grid'
                                        : 'Exact locations (Admin only)'}
                                </p>
                            </div>
                        </div>
                        <div className="flex items-center gap-2">
                            <button
                                onClick={() => setPrivacyMode('fuzzed')}
                                className={`px-4 py-2 rounded-lg transition-colors ${privacyMode === 'fuzzed'
                                    ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                                    : 'bg-white/10 text-white/60 border border-white/10'
                                    }`}
                            >
                                <Shield className="w-4 h-4 inline mr-2" />
                                Fuzzed
                            </button>
                            <button
                                onClick={() => setPrivacyMode('exact')}
                                disabled={user?.role !== 'admin'}
                                className={`px-4 py-2 rounded-lg transition-colors ${privacyMode === 'exact'
                                    ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                                    : 'bg-white/10 text-white/60 border border-white/10'
                                    } ${user?.role !== 'admin' ? 'opacity-50 cursor-not-allowed' : ''}`}
                            >
                                <MapPin className="w-4 h-4 inline mr-2" />
                                Exact {user?.role !== 'admin' && '(Admin)'}
                            </button>
                        </div>
                    </div>
                </Card>

                {/* Analytics Cards */}
                {analytics && (
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8"
                    >
                        <Card>
                            <div className="flex items-center gap-4">
                                <div className="w-12 h-12 rounded-xl bg-primary-500/20 flex items-center justify-center">
                                    <Layers className="w-6 h-6 text-primary-400" />
                                </div>
                                <div>
                                    <p className="text-sm text-white/60">Total Requests</p>
                                    <p className="text-2xl font-bold text-white">
                                        {analytics.total_requests.toLocaleString()}
                                    </p>
                                </div>
                            </div>
                        </Card>

                        <Card>
                            <div className="flex items-center gap-4">
                                <div className="w-12 h-12 rounded-xl bg-green-500/20 flex items-center justify-center">
                                    <Clock className="w-6 h-6 text-green-400" />
                                </div>
                                <div>
                                    <p className="text-sm text-white/60">Avg Resolution Time</p>
                                    <p className="text-2xl font-bold text-white">
                                        {analytics.avg_resolution_hours
                                            ? `${analytics.avg_resolution_hours.toFixed(1)}h`
                                            : 'N/A'}
                                    </p>
                                </div>
                            </div>
                        </Card>

                        <Card>
                            <div className="flex items-center gap-4">
                                <div className="w-12 h-12 rounded-xl bg-amber-500/20 flex items-center justify-center">
                                    <TrendingUp className="w-6 h-6 text-amber-400" />
                                </div>
                                <div>
                                    <p className="text-sm text-white/60">Open Requests</p>
                                    <p className="text-2xl font-bold text-white">
                                        {analytics.status_distribution.open || 0}
                                    </p>
                                </div>
                            </div>
                        </Card>

                        <Card>
                            <div className="flex items-center gap-4">
                                <div className="w-12 h-12 rounded-xl bg-blue-500/20 flex items-center justify-center">
                                    <BarChart3 className="w-6 h-6 text-blue-400" />
                                </div>
                                <div>
                                    <p className="text-sm text-white/60">Top Category</p>
                                    <p className="text-lg font-bold text-white truncate">
                                        {analytics.category_distribution[0]?.name || 'N/A'}
                                    </p>
                                </div>
                            </div>
                        </Card>
                    </motion.div>
                )}

                {/* Export Section */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    {/* Export Buttons */}
                    <Card>
                        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                            <Download className="w-5 h-5 text-primary-400" />
                            Data Export
                        </h2>
                        <p className="text-white/60 text-sm mb-4">
                            Download all {totalFields} fields for offline analysis. Exports are PII-free and respect your privacy mode.
                        </p>
                        <div className="grid grid-cols-2 gap-4 mb-4">
                            <Button onClick={handleExportCSV} variant="secondary" size="lg">
                                <FileText className="w-5 h-5 mr-2" />
                                Export CSV
                            </Button>
                            <Button onClick={handleExportGeoJSON} variant="secondary" size="lg">
                                <Map className="w-5 h-5 mr-2" />
                                Export GeoJSON
                            </Button>
                        </div>
                        <div className="border-t border-white/10 pt-4 mt-4">
                            <Button onClick={handleExportDataDictionary} variant="ghost" className="w-full">
                                <Database className="w-4 h-4 mr-2" />
                                Download Data Dictionary (Column Descriptions)
                            </Button>
                        </div>
                        <div className="text-xs text-white/40 flex items-center gap-2 mt-3">
                            <Shield className="w-3 h-3" />
                            All exports exclude personal identifying information
                        </div>
                    </Card>

                    {/* Code Snippets */}
                    <Card>
                        <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                            <Code className="w-5 h-5 text-primary-400" />
                            API Code Snippets
                        </h2>
                        <div className="flex gap-2 mb-4">
                            <button
                                onClick={() => setActiveSnippet("python")}
                                className={`px-3 py-1 rounded-lg text-sm ${activeSnippet === 'python'
                                    ? 'bg-primary-500/20 text-primary-400'
                                    : 'bg-white/10 text-white/60'
                                    }`}
                            >
                                Python
                            </button>
                            <button
                                onClick={() => setActiveSnippet("r")}
                                className={`px-3 py-1 rounded-lg text-sm ${activeSnippet === 'r'
                                    ? 'bg-primary-500/20 text-primary-400'
                                    : 'bg-white/10 text-white/60'
                                    }`}
                            >
                                R
                            </button>
                        </div>
                        {codeSnippets && (
                            <div className="relative">
                                <pre className="bg-slate-900/50 rounded-lg p-4 text-sm text-green-400 overflow-x-auto max-h-48" tabIndex={0} aria-label="Code snippet">
                                    {activeSnippet === 'python'
                                        ? codeSnippets.python
                                        : codeSnippets.r}
                                </pre>
                                <button
                                    onClick={() =>
                                        copyToClipboard(
                                            activeSnippet === 'python'
                                                ? codeSnippets.python
                                                : codeSnippets.r
                                        )
                                    }
                                    className="absolute top-2 right-2 px-2 py-1 bg-white/10 hover:bg-white/20 rounded text-xs text-white/60"
                                >
                                    Copy
                                </button>
                            </div>
                        )}
                    </Card>
                </div>

                {/* Data Sources Footer */}
                <div className="mt-8 p-6 rounded-xl bg-white/5 border border-white/10">
                    <h3 className="text-sm font-semibold text-white/70 mb-3">Real-Time Data Sources</h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs text-white/50">
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-green-400"></div>
                            <span>US Census Bureau Geocoder</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-green-400"></div>
                            <span>Open-Meteo Archive API</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-green-400"></div>
                            <span>NLP Sentiment Analysis</span>
                        </div>
                        <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-green-400"></div>
                            <span>Vertex AI Analysis Data</span>
                        </div>
                    </div>
                </div>
            </main>

            {/* AI Chat Panel */}
            <AnimatePresence>
                {showChat && (
                    <motion.div
                        initial={{ x: 400, opacity: 0 }}
                        animate={{ x: 0, opacity: 1 }}
                        exit={{ x: 400, opacity: 0 }}
                        transition={{ type: 'spring', damping: 25, stiffness: 250 }}
                        className="fixed right-0 top-0 bottom-0 w-full sm:w-[520px] bg-gray-950/95 backdrop-blur-xl border-l border-white/10 z-[60] flex flex-col shadow-2xl"
                    >
                        {/* Header */}
                        <div className="flex items-center justify-between px-5 py-4 border-b border-white/10 bg-gray-950/80">
                            <div className="flex items-center gap-3">
                                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center">
                                    <Sparkles className="w-4 h-4 text-white" />
                                </div>
                                <div>
                                    <h3 className="font-semibold text-white text-sm">Data Assistant</h3>
                                    <p className="text-xs text-white/40">AI-Powered Analytics</p>
                                </div>
                            </div>
                            <button
                                onClick={() => setShowChat(false)}
                                className="p-2 rounded-lg hover:bg-white/10 text-white/50 hover:text-white transition-colors"
                            >
                                <X className="w-5 h-5" />
                            </button>
                        </div>

                        {/* Suggested Questions */}
                        {chatMessages.length <= 1 && (
                            <div className="px-4 py-3 border-b border-white/5 flex flex-wrap gap-2">
                                {[
                                    'What fields measure social vulnerability?',
                                    'How is sentiment calculated?',
                                    'Best analyses for equity research?',
                                    'Explain the privacy modes',
                                ].map(q => (
                                    <button
                                        key={q}
                                        onClick={() => { setChatInput(q); setTimeout(() => { setChatMessages(prev => [...prev, { role: 'user', content: q }]); setChatLoading(true); api.researchChat(q, chatMessages).then(r => setChatMessages(p => [...p, { role: 'assistant', content: r.response }])).catch(err => setChatMessages(p => [...p, { role: 'assistant', content: '⚠️ ' + (err.message || 'Error') }])).finally(() => setChatLoading(false)); }, 0); }}
                                        className="px-3 py-1.5 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs hover:bg-amber-500/20 transition-colors"
                                    >
                                        {q}
                                    </button>
                                ))}
                            </div>
                        )}

                        {/* Messages */}
                        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
                            {chatMessages.map((msg, i) => (
                                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                                    <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                                        msg.role === 'user'
                                            ? 'bg-amber-500/20 border border-amber-500/25 text-amber-100 rounded-br-md'
                                            : 'bg-white/5 border border-white/8 text-white/80 rounded-bl-md'
                                    }`}>
                                        <div className="whitespace-pre-wrap">
                                            {msg.content.split(/(```\w*\n?[\s\S]*?```)/g).map((segment, si) => {
                                                // Code blocks
                                                const codeBlockMatch = segment.match(/```\w*\n?([\s\S]*?)```/);
                                                if (codeBlockMatch) {
                                                    return <pre key={si} className="bg-black/40 rounded-lg p-3 my-2 overflow-x-auto text-xs text-amber-300"><code>{codeBlockMatch[1]}</code></pre>;
                                                }

                                                // Detect and render markdown tables
                                                const tableMatch = segment.match(/((?:^\|.+\|[ ]*\n?)+)/gm);
                                                if (tableMatch) {
                                                    const parts: React.ReactNode[] = [];
                                                    let remaining = segment;
                                                    tableMatch.forEach((tbl, ti) => {
                                                        const idx = remaining.indexOf(tbl);
                                                        if (idx > 0) parts.push(<span key={`pre-${si}-${ti}`}>{remaining.slice(0, idx)}</span>);
                                                        const rows = tbl.trim().split('\n').filter(r => r.trim());
                                                        const isSeparator = (r: string) => /^\|[\s\-:|]+\|$/.test(r.trim());
                                                        const dataRows = rows.filter(r => !isSeparator(r));
                                                        const parseCells = (r: string) => r.split('|').slice(1, -1).map(c => c.trim());
                                                        if (dataRows.length > 0) {
                                                            const headerCells = parseCells(dataRows[0]);
                                                            const bodyRows = dataRows.slice(1);
                                                            parts.push(
                                                                <div key={`tbl-${si}-${ti}`} className="my-2 overflow-x-auto rounded-lg border border-white/10">
                                                                    <table className="w-full text-xs">
                                                                        <thead><tr className="bg-white/10">{headerCells.map((c, ci) => <th key={ci} className="px-3 py-1.5 text-left text-white font-semibold border-b border-white/10">{c}</th>)}</tr></thead>
                                                                        <tbody>{bodyRows.map((row, ri) => {
                                                                            const cells = parseCells(row);
                                                                            return <tr key={ri} className={ri % 2 ? 'bg-white/5' : ''}>{cells.map((c, ci) => <td key={ci} className="px-3 py-1.5 text-white/70 border-b border-white/5">{c}</td>)}</tr>;
                                                                        })}</tbody>
                                                                    </table>
                                                                </div>
                                                            );
                                                        }
                                                        remaining = remaining.slice(idx + tbl.length);
                                                    });
                                                    if (remaining) parts.push(<span key={`post-${si}`}>{remaining}</span>);
                                                    return <span key={si}>{parts}</span>;
                                                }

                                                // Process inline formatting line by line
                                                const formatInline = (text: string) => {
                                                    return text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).map((part, pi) => {
                                                        if (part.startsWith('`') && part.endsWith('`')) {
                                                            return <code key={pi} className="bg-black/30 px-1.5 py-0.5 rounded text-xs text-amber-300">{part.slice(1, -1)}</code>;
                                                        }
                                                        if (part.startsWith('**') && part.endsWith('**')) {
                                                            return <strong key={pi} className="text-white">{part.slice(2, -2)}</strong>;
                                                        }
                                                        return <span key={pi}>{part}</span>;
                                                    });
                                                };

                                                return segment.split('\n').map((line, li) => {
                                                    // Headers
                                                    const h3Match = line.match(/^### (.+)$/);
                                                    if (h3Match) return <div key={`${si}-${li}`} className="text-sm font-semibold text-white mt-2 mb-1">{formatInline(h3Match[1])}{'\n'}</div>;
                                                    const h2Match = line.match(/^## (.+)$/);
                                                    if (h2Match) return <div key={`${si}-${li}`} className="text-sm font-bold text-white mt-3 mb-1">{formatInline(h2Match[1])}{'\n'}</div>;
                                                    const h1Match = line.match(/^# (.+)$/);
                                                    if (h1Match) return <div key={`${si}-${li}`} className="text-base font-bold text-white mt-3 mb-1">{formatInline(h1Match[1])}{'\n'}</div>;

                                                    // Numbered lists
                                                    const numberedMatch = line.match(/^(\d+)\.\s+(.+)$/);
                                                    if (numberedMatch) {
                                                        return <span key={`${si}-${li}`}>{numberedMatch[1]}. {formatInline(numberedMatch[2])}{'\n'}</span>;
                                                    }

                                                    // Bullet points
                                                    const bulletLine = line.replace(/^- (.+)$/, '• $1');
                                                    const parts = formatInline(bulletLine);
                                                    return <span key={`${si}-${li}`}>{parts}{li < segment.split('\n').length - 1 && '\n'}</span>;
                                                });
                                            })}
                                        </div>
                                    </div>
                                </div>
                            ))}
                            {chatLoading && (
                                <div className="flex justify-start">
                                    <div className="bg-white/5 border border-white/8 rounded-2xl rounded-bl-md px-4 py-3">
                                        <div className="flex gap-1.5">
                                            <span className="w-2 h-2 bg-amber-400/60 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                                            <span className="w-2 h-2 bg-amber-400/60 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                                            <span className="w-2 h-2 bg-amber-400/60 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                                        </div>
                                    </div>
                                </div>
                            )}
                            <div ref={chatEndRef} />
                        </div>

                        {/* Input */}
                        <form onSubmit={sendResearchChat} className="px-4 py-3 border-t border-white/10 bg-gray-950/80">
                            <div className="flex gap-2">
                                <input
                                    type="text"
                                    value={chatInput}
                                    onChange={(e) => setChatInput(e.target.value)}
                                    placeholder="Ask about data fields, methodology, analyses..."
                                    className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/30"
                                    disabled={chatLoading}
                                />
                                <button
                                    type="submit"
                                    disabled={chatLoading || !chatInput.trim()}
                                    className="p-2.5 bg-gradient-to-r from-amber-500 to-orange-500 rounded-xl text-white hover:opacity-90 disabled:opacity-40 transition-opacity"
                                >
                                    <Send className="w-4 h-4" />
                                </button>
                            </div>
                        </form>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
};

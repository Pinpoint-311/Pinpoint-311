import React, { useState, useEffect, useRef, useId, FormEvent } from 'react';
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
    Database,
    Microscope,
    Sparkles,
    Send,
    X,
} from 'lucide-react';
import { CollapsibleSection } from '../components/ui';
import { CapabilityTile, StatusPill, Action } from '../components/capabilityUI';
import { useAuth } from '../context/AuthContext';
import { useSettings } from '../context/SettingsContext';
import { useAnnounce } from '../context/AccessibilityContext';
import { api,ResearchAnalytics, ResearchCodeSnippets, ResearchDataDictionary, ResearchPackInfo } from '../services/api';

/* The glass card treatment the admin console and staff dashboard are built
 * from. One string, used for every panel on this page, so the lab reads as a
 * room in the same building rather than a separate product. */
const GLASS_CARD = 'rounded-3xl bg-gradient-to-br from-white/[0.06] via-white/[0.02] to-indigo-950/40 border border-white/10 backdrop-blur-2xl';

/** The console's section-label idiom: small caps over the card's content. */
const SectionLabel: React.FC<{ icon: React.ElementType; id?: string; children: React.ReactNode }> = ({ icon: Icon, id, children }) => (
    <h2 id={id} className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-white/60 font-semibold mb-4">
        <Icon className="w-4 h-4 text-primary-200" aria-hidden="true" />
        {children}
    </h2>
);

// Presentation-only metadata (icon + color) keyed by pack id. The packs
// themselves — labels, audiences, field lists — come from the server's
// /research/data-dictionary, which applies the admin's per-pack switches. A
// hardcoded pack list here used to promise fields the export could withhold.
const PACK_PRESENTATION: Record<string, { icon: React.ElementType; color: string }> = {
    social_equity: { icon: Users, color: 'purple' },
    environmental_context: { icon: Cloud, color: 'blue' },
    sentiment_trust: { icon: MessageSquare, color: 'pink' },
    bureaucratic_friction: { icon: Building2, color: 'orange' },
    ai_ml_research: { icon: Brain, color: 'green' },
    moderation: { icon: Shield, color: 'purple' },
};

export const ResearchLab: React.FC = () => {
    const navigate = useNavigate();
    const { user } = useAuth();
    const { settings } = useSettings();
    const announce = useAnnounce();
    /* Stable ids for the Query Builder fields. The labels used to be bare
     * `<label class="block">` next to an id-less `<input>` — visually adjacent,
     * programmatically unrelated, so a screen reader announced three unnamed
     * edit boxes (WCAG 1.3.1 / 3.3.2 / 4.1.2). */
    const fieldIds = useId();

    // Check access
    useEffect(() => {
        if (user && user.role !== 'researcher' && user.role !== 'admin') {
            navigate('/staff');
        }
    }, [user, navigate]);

    /* Browser tab title — WCAG 2.4.2 Page Titled.
     *
     * The restore is conditional on purpose. SettingsContext writes the
     * document title asynchronously once settings load, so the snapshot taken
     * when this page mounted can already be stale by the time it unmounts;
     * restoring it unconditionally overwrote whatever the *next* page had just
     * set, leaving the user on a page titled for the one they left. Only hand
     * the title back if nothing else has claimed it since. */
    useEffect(() => {
        const previousTitle = document.title;
        const ourTitle = 'Research & Analytics Lab | ' + (settings?.township_name || '311');
        document.title = ourTitle;
        return () => {
            if (document.title === ourTitle) document.title = previousTitle;
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
    const [dictionary, setDictionary] = useState<ResearchDataDictionary | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [isEnabled, setIsEnabled] = useState<boolean | null>(null);
    const [error, setError] = useState<string | null>(null);

    // UI state
    const [activeSnippet, setActiveSnippet] = useState<'python' | 'r'>('python');
    const [expandedPack, setExpandedPack] = useState<string | null>('social_equity');
    /* Copy result, shown on the button itself. `null` is the resting state; the
     * button used to give no feedback at all and swallow a rejected
     * clipboard promise, so a blocked or unsupported copy looked identical to a
     * successful one (WCAG 4.1.3). */
    const [copyState, setCopyState] = useState<'copied' | 'failed' | null>(null);
    const copyResetRef = useRef<number | null>(null);
    const snippetTabRefs = useRef<Record<'python' | 'r', HTMLButtonElement | null>>({ python: null, r: null });

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
                loadDictionary();
            }
        } catch {
            setIsEnabled(false);
        }
    };

    /* Every long-running action on this page used to complete silently: the
     * results simply appeared, which a sighted user notices and a screen reader
     * user does not (WCAG 4.1.3 Status Messages). These route through the app's
     * single live region rather than adding more aria-live nodes — two polite
     * regions written in the same tick and neither is announced. */
    const loadAnalytics = async () => {
        setIsLoading(true);
        setError(null);
        announce('Running query…');
        try {
            const data = await api.getResearchAnalytics({
                start_date: startDate || undefined,
                end_date: endDate || undefined,
                service_code: serviceCode || undefined,
            });
            setAnalytics(data);
            announce(`Query complete. ${data.total_requests.toLocaleString()} requests matched.`);
        } catch (err: any) {
            const message = err.message || 'Failed to load analytics';
            setError(message);
            // Assertive: the query the user just asked for did not happen.
            announce(message, 'assertive');
        } finally {
            setIsLoading(false);
        }
    };

    const loadDictionary = async () => {
        try {
            const dict = await api.getResearchDataDictionary();
            setDictionary(dict);
        } catch (err) {
            console.error('Failed to load data dictionary', err);
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
        announce('Preparing CSV export…');
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
            announce('CSV export started. Check your downloads.');
        } catch (err: any) {
            const message = err.message || 'Export failed';
            setError(message);
            announce(`CSV export failed. ${message}`, 'assertive');
        }
    };

    const handleExportGeoJSON = async () => {
        announce('Preparing GeoJSON export…');
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
            announce('GeoJSON export started. Check your downloads.');
        } catch (err: any) {
            const message = err.message || 'Export failed';
            setError(message);
            announce(`GeoJSON export failed. ${message}`, 'assertive');
        }
    };

    const handleExportDataDictionary = async () => {
        announce('Preparing data dictionary…');
        try {
            const blob = await api.exportDataDictionary();
            const url = window.URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = `data_dictionary_${new Date().toISOString().slice(0, 10)}.csv`;
            link.click();
            window.URL.revokeObjectURL(url);
            announce('Data dictionary download started.');
        } catch (err: any) {
            const message = err.message || 'Export failed';
            setError(message);
            announce(`Data dictionary export failed. ${message}`, 'assertive');
        }
    };

    /* Clipboard writes reject routinely — no permission, no secure context, no
     * `navigator.clipboard` at all — and this used to fire and forget, so a
     * failed copy was indistinguishable from a successful one. Report both
     * outcomes, on the button and to assistive tech. */
    const copyToClipboard = async (text: string) => {
        if (copyResetRef.current) window.clearTimeout(copyResetRef.current);
        try {
            // Absent on insecure origins; `?.` alone would resolve undefined and
            // report a copy that never happened.
            if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
            await navigator.clipboard.writeText(text);
            setCopyState('copied');
            announce('Code snippet copied to clipboard.');
        } catch {
            setCopyState('failed');
            announce('Could not copy to clipboard. Select the code and copy it manually.', 'assertive');
        }
        copyResetRef.current = window.setTimeout(() => setCopyState(null), 3000);
    };

    useEffect(() => () => {
        if (copyResetRef.current) window.clearTimeout(copyResetRef.current);
    }, []);

    /* Arrow-key navigation for the Python/R tablist.
     *
     * These were two plain buttons that looked like tabs and behaved like
     * nothing in particular. Once they carry role="tab" the keyboard contract
     * comes with them: exactly one tab in the tab sequence, arrows move between
     * them, Home/End jump to the ends, and the panel is reached with a single
     * further Tab. Focus follows selection, which is the right variant here
     * because switching panels is instant and has no cost. */
    const SNIPPET_LANGS = ['python', 'r'] as const;

    const handleSnippetKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
        const current = SNIPPET_LANGS.indexOf(activeSnippet);
        let next = current;
        if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (current + 1) % SNIPPET_LANGS.length;
        else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (current - 1 + SNIPPET_LANGS.length) % SNIPPET_LANGS.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = SNIPPET_LANGS.length - 1;
        else return;

        event.preventDefault();
        const lang = SNIPPET_LANGS[next];
        setActiveSnippet(lang);
        snippetTabRefs.current[lang]?.focus();
    };

    const getPackColorClasses = (color: string) => {
        // Chip colors brightened to *-200 for WCAG AA contrast; tile follows
        // the CapabilityTile gradient recipe so pack icons sit in the same
        // family as the console's capability tiles.
        const colors: Record<string, { bg: string; text: string; border: string; tile: string }> = {
            purple: { bg: 'bg-purple-500/20', text: 'text-purple-200', border: 'border-purple-500/30', tile: 'bg-gradient-to-br from-purple-500/25 to-indigo-500/15 border-purple-400/30 text-purple-200' },
            blue: { bg: 'bg-blue-500/20', text: 'text-blue-200', border: 'border-blue-500/30', tile: 'bg-gradient-to-br from-blue-500/25 to-cyan-500/15 border-blue-400/30 text-blue-200' },
            pink: { bg: 'bg-pink-500/20', text: 'text-pink-200', border: 'border-pink-500/30', tile: 'bg-gradient-to-br from-pink-500/25 to-rose-500/15 border-pink-400/30 text-pink-200' },
            orange: { bg: 'bg-orange-500/20', text: 'text-orange-200', border: 'border-orange-500/30', tile: 'bg-gradient-to-br from-orange-500/25 to-amber-500/15 border-orange-400/30 text-orange-200' },
            green: { bg: 'bg-green-500/20', text: 'text-green-200', border: 'border-green-500/30', tile: 'bg-gradient-to-br from-emerald-500/25 to-teal-500/15 border-emerald-400/30 text-emerald-200' },
        };
        return colors[color] || colors.purple;
    };

    // Packs and fields as the server actually exports them (pack switches applied)
    const researchPacks: ({ id: string } & ResearchPackInfo)[] = dictionary
        ? Object.entries(dictionary.research_packs).map(([id, p]) => ({ id, ...p }))
        : [];
    const coreFields = dictionary?.core_fields ?? [];
    // Count of columns the export will really contain for this town
    const totalFields = dictionary ? Object.keys(dictionary.fields).length : 0;
    const packFieldCount = researchPacks.reduce((sum, pack) => sum + pack.fields.length, 0);

    // Not enabled state
    if (isEnabled === false) {
        return (
            <div className="min-h-screen flex items-center justify-center px-6">
                <div className={`max-w-md w-full text-center p-8 ${GLASS_CARD} shadow-[0_10px_30px_rgba(0,0,0,0.3)]`}>
                    <div className="flex justify-center mb-4">
                        <CapabilityTile icon={Lock} size="lg" />
                    </div>
                    <div className="flex justify-center mb-3">
                        <StatusPill state="unset" label="Module disabled" />
                    </div>
                    <h1 className="text-2xl font-bold text-white mb-2">Research Suite Disabled</h1>
                    <p className="text-white/50 mb-6">
                        The Research Suite is not enabled for this installation.
                        Contact your administrator to enable it.
                    </p>
                    <div className="flex justify-center">
                        <Action variant="ghost" onClick={() => navigate(-1)}>
                            <ArrowLeft className="w-4 h-4" aria-hidden="true" />
                            Go Back
                        </Action>
                    </div>
                </div>
            </div>
        );
    }

    // Loading state
    if (isEnabled === null) {
        return (
            <div className="min-h-screen flex items-center justify-center" role="status" aria-label="Loading research portal">
                <RefreshCw className="w-8 h-8 text-primary-400 animate-spin" aria-hidden="true" />
                <span className="sr-only">Loading research portal, please wait...</span>
            </div>
        );
    }

    return (
        <div className="min-h-screen">
            {/* Header */}
            <header className="glass-sidebar border-b border-white/10 sticky top-0 z-50">
                {/* Wraps rather than overflowing: at 320px the identity block and
                    the action cluster do not fit on one line, and the header is
                    sticky, so anything that overflowed was unreachable (1.4.10). */}
                <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
                    <div className="flex items-center gap-4 min-w-0">
                        <Action variant="ghost" onClick={() => navigate(-1)} title="Go back to previous page">
                            <ArrowLeft className="w-5 h-5" aria-hidden="true" />
                            <span className="sr-only">Go back to previous page</span>
                        </Action>
                        <div className="flex items-center gap-3 min-w-0">
                            <CapabilityTile icon={Microscope} size="md" />
                            <div className="min-w-0">
                                <h1 className="text-lg sm:text-xl font-bold text-white">Research &amp; Analytics Lab</h1>
                                <p className="text-sm text-white/50 truncate">
                                    {settings?.township_name} • {totalFields} research fields available
                                </p>
                            </div>
                        </div>
                    </div>
                    <div className="flex items-center gap-4">
                        <Action
                            variant={showChat ? 'primary' : 'ghost'}
                            onClick={() => setShowChat(!showChat)}
                        >
                            <Sparkles className="w-4 h-4" aria-hidden="true" />
                            Ask AI
                        </Action>
                        <div className="hidden sm:flex items-center gap-2 text-sm text-white/60">
                            <Database className="w-4 h-4" aria-hidden="true" />
                            <span>{user?.username} ({user?.role})</span>
                        </div>
                    </div>
                </div>
            </header>

            {/* The app-wide skip link targets #main-content; without the id it had
                nothing to skip to on this route and silently did nothing. The
                negative tabindex makes the landmark itself focusable so focus
                actually moves, not just the scroll position (WCAG 2.4.1). */}
            <main id="main-content" tabIndex={-1} className="max-w-7xl mx-auto px-4 sm:px-6 py-8 focus:outline-none">
                {/* Hero Section */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mb-8 text-center"
                >
                    <p className="text-[11px] uppercase tracking-wider text-white/60 font-semibold mb-2">
                        Privacy-preserving datasets
                    </p>
                    <h2 className="text-3xl font-bold text-white mb-3">
                        Research Data Export
                    </h2>
                    <p className="text-white/50 max-w-2xl mx-auto">
                        Export rich, privacy-preserving datasets for operational analysis, equity studies,
                        infrastructure planning, and data science. All {totalFields} fields are computed at export time from your live data; see Data Sources & Provenance below for how each is produced.
                    </p>
                </motion.div>

                {/* Error display */}
                {error && (
                    <motion.div
                        initial={{ opacity: 0, y: -10 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="bg-gradient-to-r from-red-500/25 to-rose-500/20 border border-red-400/35 rounded-2xl p-4 mb-6"
                        role="alert"
                        aria-live="assertive"
                    >
                        <p className="text-red-200">{error}</p>
                    </motion.div>
                )}

                {/* Research Packs Section */}
                <section className="mb-8" aria-labelledby="research-packs-heading">
                    <SectionLabel icon={Database} id="research-packs-heading">
                        Research Field Packs ({packFieldCount} specialized fields)
                    </SectionLabel>
                    <div className="space-y-3">
                        {researchPacks.map((pack) => {
                            const presentation = PACK_PRESENTATION[pack.id] ?? { icon: Database, color: 'purple' };
                            const colors = getPackColorClasses(presentation.color);
                            const isExpanded = expandedPack === pack.id;
                            const Icon = presentation.icon;

                            return (
                                <motion.div
                                    key={pack.id}
                                    initial={{ opacity: 0, y: 10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    className="rounded-2xl border border-white/10 bg-white/[0.03] overflow-hidden transition-colors"
                                >
                                    <button
                                        onClick={() => setExpandedPack(isExpanded ? null : pack.id)}
                                        className="group w-full px-4 sm:px-5 py-4 flex items-center justify-between gap-3 text-left hover:bg-white/[0.04] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60"
                                        aria-expanded={isExpanded}
                                        aria-controls={`pack-content-${pack.id}`}
                                    >
                                        <div className="flex items-center gap-3.5 min-w-0">
                                            <span className={`shrink-0 w-10 h-10 rounded-xl border shadow-inner flex items-center justify-center ${colors.tile}`} aria-hidden="true">
                                                <Icon className="w-5 h-5" />
                                            </span>
                                            <span className="min-w-0">
                                                <span className="block text-lg font-semibold text-white truncate">{pack.label}</span>
                                                <span className="block text-white/55 text-xs mt-0.5 truncate">
                                                    {pack.audience} • {pack.fields.length} fields
                                                </span>
                                            </span>
                                        </div>
                                        <motion.span
                                            animate={{ rotate: isExpanded ? 180 : 0 }}
                                            transition={{ duration: 0.25 }}
                                            aria-hidden="true"
                                            className="shrink-0 text-white/45 group-hover:text-white/80"
                                        >
                                            <ChevronDown className="w-5 h-5" />
                                        </motion.span>
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
                                                <div className="px-4 sm:px-5 py-5 border-t border-white/10">
                                                    {/* Fields Table */}
                                                    {/* A scroll container that only responds to a
                                                        mouse wheel or a drag is unreachable content for
                                                        a keyboard-only user (2.1.1). tabIndex puts it in
                                                        the tab order so the arrow keys scroll it; the
                                                        group role and label stop it being announced as
                                                        an unnamed focusable div. */}
                                                    <div
                                                        className="overflow-x-auto mb-4 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                                        tabIndex={0}
                                                        role="group"
                                                        aria-label={`${pack.label} fields, scrollable table`}
                                                    >
                                                        <table className="w-full text-sm">
                                                            <thead>
                                                                <tr className="text-left text-[11px] uppercase tracking-wider text-white/60 font-semibold border-b border-white/10">
                                                                    <th className="pb-2 pr-4">Field Name</th>
                                                                    <th className="pb-2 pr-4">Type</th>
                                                                    <th className="pb-2">Description</th>
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
                                                                        <td className="py-2 text-white/60">
                                                                            {field.description}
                                                                        </td>
                                                                    </tr>
                                                                ))}
                                                            </tbody>
                                                        </table>
                                                    </div>

                                                    {/* Suggested Analyses */}
                                                    <div>
                                                        <h4 className="text-[11px] uppercase tracking-wider text-white/60 font-semibold mb-2">Suggested Analyses</h4>
                                                        <div className="flex flex-wrap gap-2">
                                                            {pack.suggested_analyses.map((analysis, i) => (
                                                                <span
                                                                    key={i}
                                                                    className="px-3 py-1 rounded-2xl bg-white/[0.07] border border-white/15 text-white/70 text-xs font-medium"
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
                        <CollapsibleSection
                            title="Core Request Fields"
                            icon={Layers}
                            subtitle={`Standard fields included in all exports • ${coreFields.length} fields`}
                        >
                            <div className="max-h-64 overflow-y-auto">
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                    {coreFields.map((field) => (
                                        <div key={field.name} className="flex items-start gap-2 text-sm">
                                            <code className="px-2 py-0.5 rounded bg-white/10 text-white/70 text-xs shrink-0">
                                                {field.name}
                                            </code>
                                            <span className="text-white/55 text-xs">{field.description}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </CollapsibleSection>
                    </div>
                </section>

                {/* Query Builder */}
                <div className={`${GLASS_CARD} p-6 mb-8`}>
                    <SectionLabel icon={Filter}>Query Builder</SectionLabel>
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                        <div>
                            <label htmlFor={`${fieldIds}-start`} className="block text-sm text-white/60 mb-2">Start Date</label>
                            <input
                                id={`${fieldIds}-start`}
                                type="date"
                                value={startDate}
                                onChange={(e) => setStartDate(e.target.value)}
                                className="w-full px-4 py-2 rounded-xl bg-white/[0.06] border border-white/15 text-white focus:outline-none focus:ring-2 focus:ring-primary-400/60 focus:border-transparent"
                            />
                        </div>
                        <div>
                            <label htmlFor={`${fieldIds}-end`} className="block text-sm text-white/60 mb-2">End Date</label>
                            <input
                                id={`${fieldIds}-end`}
                                type="date"
                                value={endDate}
                                onChange={(e) => setEndDate(e.target.value)}
                                className="w-full px-4 py-2 rounded-xl bg-white/[0.06] border border-white/15 text-white focus:outline-none focus:ring-2 focus:ring-primary-400/60 focus:border-transparent"
                            />
                        </div>
                        <div>
                            <label htmlFor={`${fieldIds}-service`} className="block text-sm text-white/60 mb-2">Service Category</label>
                            <input
                                id={`${fieldIds}-service`}
                                type="text"
                                value={serviceCode}
                                onChange={(e) => setServiceCode(e.target.value)}
                                placeholder="e.g., pothole"
                                className="w-full px-4 py-2 rounded-xl bg-white/[0.06] border border-white/15 text-white placeholder-white/40 focus:outline-none focus:ring-2 focus:ring-primary-400/60 focus:border-transparent"
                            />
                        </div>
                        <div className="flex items-end [&_button]:w-full [&_button]:justify-center">
                            <Action variant="primary" onClick={loadAnalytics} disabled={isLoading} busy={isLoading}>
                                {!isLoading && <Activity className="w-4 h-4" aria-hidden="true" />}
                                Run Query
                            </Action>
                        </div>
                    </div>

                    {/* Privacy Mode Toggle */}
                    <div className="mt-4 pt-4 border-t border-white/10 flex items-center justify-between gap-4 flex-wrap">
                        <div className="flex items-center gap-3">
                            <Eye className="w-5 h-5 text-primary-200" aria-hidden="true" />
                            <div>
                                <span className="text-white font-medium">Privacy Mode</span>
                                <p className="text-sm text-white/50">
                                    {privacyMode === 'fuzzed'
                                        ? 'Locations fuzzed to ~100ft grid'
                                        : 'Exact locations (Admin only)'}
                                </p>
                            </div>
                        </div>
                        {/* aria-pressed, because "which mode am I in" was carried
                            entirely by the green/amber fill — no information at all
                            without colour (1.4.1) and nothing exposed to assistive
                            tech (4.1.2). */}
                        <div className="flex items-center gap-2 flex-wrap">
                            <button
                                type="button"
                                aria-pressed={privacyMode === 'fuzzed'}
                                onClick={() => setPrivacyMode('fuzzed')}
                                className={`px-4 py-2 rounded-2xl border text-sm font-semibold inline-flex items-center gap-1.5 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${privacyMode === 'fuzzed'
                                    ? 'bg-gradient-to-r from-emerald-500/20 to-teal-500/20 text-emerald-300 border-emerald-500/30 shadow-md shadow-emerald-950/40'
                                    : 'bg-white/[0.08] text-white/70 border-white/15 hover:bg-white/[0.15] hover:text-white'
                                    }`}
                            >
                                <Shield className="w-4 h-4" aria-hidden="true" />
                                Fuzzed
                            </button>
                            <button
                                type="button"
                                aria-pressed={privacyMode === 'exact'}
                                onClick={() => setPrivacyMode('exact')}
                                disabled={user?.role !== 'admin'}
                                className={`px-4 py-2 rounded-2xl border text-sm font-semibold inline-flex items-center gap-1.5 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${privacyMode === 'exact'
                                    ? 'bg-gradient-to-r from-amber-500/20 to-orange-500/20 text-amber-300 border-amber-500/30 shadow-md shadow-amber-950/40'
                                    : 'bg-white/[0.08] text-white/70 border-white/15 hover:bg-white/[0.15] hover:text-white'
                                    } ${user?.role !== 'admin' ? 'opacity-50 cursor-not-allowed' : ''}`}
                            >
                                <MapPin className="w-4 h-4" aria-hidden="true" />
                                Exact
                            </button>
                            {/* The reason this control is disabled lives OUTSIDE it.
                                It used to be the trailing "(Admin)" inside the
                                button's own label, and a disabled button is skipped
                                by several screen readers' browse modes — so the one
                                sentence explaining why the control cannot be used
                                was the one sentence the user could not reach. */}
                            {user?.role !== 'admin' && (
                                <p className="text-xs text-white/60 basis-full sm:basis-auto">
                                    Exact locations are available to administrators only.
                                </p>
                            )}
                        </div>
                    </div>
                </div>

                {/* Analytics Cards */}
                {analytics && (
                    <motion.div
                        initial={{ opacity: 0, y: 20 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8"
                    >
                        <div className={`${GLASS_CARD} p-5`}>
                            <div className="flex items-center gap-4">
                                <CapabilityTile icon={Layers} size="md" />
                                <div className="min-w-0">
                                    <p className="text-[11px] uppercase tracking-wider text-white/60 font-semibold">Total Requests</p>
                                    <p className="text-2xl font-bold text-white">
                                        {analytics.total_requests.toLocaleString()}
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div className={`${GLASS_CARD} p-5`}>
                            <div className="flex items-center gap-4">
                                <CapabilityTile icon={Clock} size="md" />
                                <div className="min-w-0">
                                    <p className="text-[11px] uppercase tracking-wider text-white/60 font-semibold">Avg Resolution Time</p>
                                    <p className="text-2xl font-bold text-white">
                                        {analytics.avg_resolution_hours
                                            ? `${analytics.avg_resolution_hours.toFixed(1)}h`
                                            : 'N/A'}
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div className={`${GLASS_CARD} p-5`}>
                            <div className="flex items-center gap-4">
                                <CapabilityTile icon={TrendingUp} size="md" />
                                <div className="min-w-0">
                                    <p className="text-[11px] uppercase tracking-wider text-white/60 font-semibold">Open Requests</p>
                                    <p className="text-2xl font-bold text-white">
                                        {analytics.status_distribution.open || 0}
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div className={`${GLASS_CARD} p-5`}>
                            <div className="flex items-center gap-4">
                                <CapabilityTile icon={BarChart3} size="md" />
                                <div className="min-w-0">
                                    <p className="text-[11px] uppercase tracking-wider text-white/60 font-semibold">Top Category</p>
                                    <p className="text-lg font-bold text-white truncate">
                                        {analytics.category_distribution[0]?.name || 'N/A'}
                                    </p>
                                </div>
                            </div>
                        </div>
                    </motion.div>
                )}

                {/* Export Section */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    {/* Export Buttons */}
                    <div className={`${GLASS_CARD} p-6`}>
                        <SectionLabel icon={Download}>Data Export</SectionLabel>
                        <p className="text-white/50 text-sm mb-4">
                            Download all {totalFields} fields for offline analysis. Exports apply PII redaction, coordinate grid-snapping, and small-cell suppression (census-tract fields are withheld for tracts with fewer than 5 records). Review before external release.
                        </p>
                        {/* Single column until there is room for two: at 320px each
                            cell was ~130px and "Export GeoJSON" plus its icon
                            overflowed the button (1.4.10 Reflow). */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4 [&_button]:w-full [&_button]:justify-center">
                            <Action variant="primary" onClick={handleExportCSV}>
                                <FileText className="w-5 h-5" aria-hidden="true" />
                                Export CSV
                            </Action>
                            <Action variant="primary" onClick={handleExportGeoJSON}>
                                <Map className="w-5 h-5" aria-hidden="true" />
                                Export GeoJSON
                            </Action>
                        </div>
                        <div className="border-t border-white/10 pt-4 mt-4 [&_button]:w-full [&_button]:justify-center">
                            <Action variant="ghost" onClick={handleExportDataDictionary}>
                                <Database className="w-4 h-4" aria-hidden="true" />
                                Download Data Dictionary (Column Descriptions)
                            </Action>
                        </div>
                        <div className="text-xs text-white/50 flex items-center gap-2 mt-3">
                            <Shield className="w-3 h-3" aria-hidden="true" />
                            All exports exclude personal identifying information
                        </div>
                    </div>

                    {/* Code Snippets */}
                    <div className={`${GLASS_CARD} p-6`}>
                        <SectionLabel icon={Code}>API Code Snippets</SectionLabel>
                        <div className="flex gap-2 mb-4" role="tablist" aria-label="Snippet language">
                            {SNIPPET_LANGS.map(lang => {
                                const selected = activeSnippet === lang;
                                return (
                                    <button
                                        key={lang}
                                        type="button"
                                        role="tab"
                                        id={`snippet-tab-${lang}`}
                                        aria-selected={selected}
                                        aria-controls={`snippet-panel-${lang}`}
                                        // Roving tabindex: the tablist is one stop, not two.
                                        tabIndex={selected ? 0 : -1}
                                        ref={node => { snippetTabRefs.current[lang] = node; }}
                                        onClick={() => setActiveSnippet(lang)}
                                        onKeyDown={handleSnippetKeyDown}
                                        className={`px-3 py-1.5 rounded-2xl border text-xs font-semibold transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300 ${selected
                                            ? 'bg-primary-500/20 text-primary-200 border-primary-400/30'
                                            : 'bg-white/[0.08] text-white/70 border-white/15 hover:bg-white/[0.15] hover:text-white'
                                            }`}
                                    >
                                        {lang === 'python' ? 'Python' : 'R'}
                                    </button>
                                );
                            })}
                        </div>
                        {codeSnippets && (
                            <div className="relative">
                                <pre
                                    id={`snippet-panel-${activeSnippet}`}
                                    role="tabpanel"
                                    aria-labelledby={`snippet-tab-${activeSnippet}`}
                                    className="bg-slate-950/60 border border-white/10 rounded-xl p-4 text-sm text-emerald-300 overflow-x-auto max-h-48 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                    tabIndex={0}
                                >
                                    {activeSnippet === 'python'
                                        ? codeSnippets.python
                                        : codeSnippets.r}
                                </pre>
                                <button
                                    type="button"
                                    onClick={() =>
                                        copyToClipboard(
                                            activeSnippet === 'python'
                                                ? codeSnippets.python
                                                : codeSnippets.r
                                        )
                                    }
                                    className="absolute top-2 right-2 px-2.5 py-1 rounded-xl bg-white/[0.08] hover:bg-white/[0.15] border border-white/15 text-xs font-medium text-white/70 hover:text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                >
                                    {/* The outcome is in the button's own label, so it
                                        reaches a screen reader on the next visit to the
                                        control as well as through the live region. */}
                                    {copyState === 'copied' ? 'Copied' : copyState === 'failed' ? 'Copy failed' : 'Copy'}
                                </button>
                            </div>
                        )}
                    </div>
                </div>

                {/* Data provenance. These are descriptions of where each field comes
                    from — not live health indicators. The previous version showed
                    hardcoded green "online" dots that stayed green even when a source
                    was failing, which misrepresented data quality. */}
                <div className={`mt-8 p-6 ${GLASS_CARD}`}>
                    <h3 className="text-[11px] uppercase tracking-wider text-white/60 font-semibold mb-1">Data Sources &amp; Provenance</h3>
                    <p className="text-xs text-white/50 mb-3">
                        How each field is produced. When an external source is unavailable, the affected
                        fields are left empty rather than estimated.
                    </p>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-2.5 text-xs">
                        {[
                            ['US Census Bureau Geocoder + ACS', 'Live API (free, no key). Coordinates are grid-snapped BEFORE any external lookup. Tract, income, tenure.'],
                            ['Open-Meteo Archive API', 'Live API, ~1km-rounded coordinates. Blank when the call fails — never estimated.'],
                            ['Social vulnerability', 'Official CDC/ATSDR SVI; local ACS fallback is marked in svi_source.'],
                            ['AI analysis fields', 'From stored model output; blank when AI never ran.'],
                            // Rows for switchable packs only appear when the town exports them.
                            ...(dictionary?.research_packs?.sentiment_trust
                                ? [['Sentiment & trust indicators', 'VADER rule-based scoring in-app — handles negation.']]
                                : []),
                            ...(dictionary?.research_packs?.moderation
                                ? [['Flags', 'Content-moderation wordlist at intake, not AI. Reasons are PII-redacted.']]
                                : []),
                        ].map(([name, detail]) => (
                            <div key={name} className="flex items-start gap-2">
                                <div className="w-1.5 h-1.5 rounded-full bg-white/30 mt-1.5 shrink-0" />
                                <div className="min-w-0">
                                    <div className="text-white/70">{name}</div>
                                    <div className="text-white/50">{detail}</div>
                                </div>
                            </div>
                        ))}
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
                        className="fixed right-0 top-0 bottom-0 w-full sm:w-[520px] bg-slate-950/95 backdrop-blur-2xl border-l border-white/10 z-[60] flex flex-col shadow-2xl"
                    >
                        {/* Header */}
                        <div className="flex items-center justify-between px-5 py-4 border-b border-white/10 bg-slate-950/80">
                            <div className="flex items-center gap-3">
                                <CapabilityTile icon={Sparkles} size="sm" />
                                <div>
                                    <h3 className="font-semibold text-white text-sm">Data Assistant</h3>
                                    <p className="text-xs text-white/50">AI-Powered Analytics</p>
                                </div>
                            </div>
                            <button
                                onClick={() => setShowChat(false)}
                                className="p-2 rounded-xl hover:bg-white/10 text-white/50 hover:text-white transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                aria-label="Close chat panel"
                            >
                                <X className="w-5 h-5" aria-hidden="true" />
                            </button>
                        </div>

                        {/* Suggested Questions */}
                        {chatMessages.length <= 1 && (
                            <div className="px-4 py-3 border-b border-white/5 flex flex-wrap gap-2">
                                {[
                                    'What fields measure social vulnerability?',
                                    'Which research packs are available?',
                                    'Best analyses for equity research?',
                                    'Explain the privacy modes',
                                ].map(q => (
                                    <button
                                        key={q}
                                        onClick={() => { setChatInput(q); setTimeout(() => { setChatMessages(prev => [...prev, { role: 'user', content: q }]); setChatLoading(true); api.researchChat(q, chatMessages).then(r => setChatMessages(p => [...p, { role: 'assistant', content: r.response }])).catch(err => setChatMessages(p => [...p, { role: 'assistant', content: '⚠️ ' + (err.message || 'Error') }])).finally(() => setChatLoading(false)); }, 0); }}
                                        className="px-3 py-1.5 rounded-2xl bg-primary-500/10 border border-primary-400/25 text-primary-200 text-xs font-medium hover:bg-primary-500/20 transition-colors"
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
                                            ? 'bg-primary-500/20 border border-primary-400/25 text-primary-100 rounded-br-md'
                                            : 'bg-white/5 border border-white/10 text-white/80 rounded-bl-md'
                                    }`}>
                                        <div className="whitespace-pre-wrap">
                                            {msg.content.split(/(```\w*\n?[\s\S]*?```)/g).map((segment, si) => {
                                                // Code blocks
                                                const codeBlockMatch = segment.match(/```\w*\n?([\s\S]*?)```/);
                                                if (codeBlockMatch) {
                                                    return <pre key={si} className="bg-black/40 rounded-lg p-3 my-2 overflow-x-auto text-xs text-primary-200"><code>{codeBlockMatch[1]}</code></pre>;
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
                                                                // tabIndex so the horizontal scroll is
                                                                // reachable without a pointer (2.1.1).
                                                                <div
                                                                    key={`tbl-${si}-${ti}`}
                                                                    className="my-2 overflow-x-auto rounded-lg border border-white/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                                                    tabIndex={0}
                                                                    role="group"
                                                                    aria-label="Scrollable table from the assistant"
                                                                >
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
                                                            return <code key={pi} className="bg-black/30 px-1.5 py-0.5 rounded text-xs text-primary-200">{part.slice(1, -1)}</code>;
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
                                    <div className="bg-white/5 border border-white/10 rounded-2xl rounded-bl-md px-4 py-3">
                                        {/* The three dots were the entire message: no text
                                            alternative (1.1.1), and under reduced motion
                                            they stop bouncing and become three grey dots
                                            that say nothing at all. The words carry the
                                            meaning; the dots are now decoration. */}
                                        <div className="flex gap-1.5" aria-hidden="true">
                                            <span className="w-2 h-2 bg-primary-300/70 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                                            <span className="w-2 h-2 bg-primary-300/70 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                                            <span className="w-2 h-2 bg-primary-300/70 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                                        </div>
                                        <span className="sr-only">The assistant is writing a reply…</span>
                                    </div>
                                </div>
                            )}
                            <div ref={chatEndRef} />
                        </div>

                        {/* Input */}
                        <form onSubmit={sendResearchChat} className="px-4 py-3 border-t border-white/10 bg-slate-950/80">
                            <div className="flex gap-2">
                                {/* A placeholder is not a label: it disappears the moment
                                    the user types, and several screen readers never
                                    announce it at all, so this field had no accessible
                                    name (3.3.2 / 4.1.2). Real label, visually hidden. */}
                                <label htmlFor={`${fieldIds}-chat`} className="sr-only">
                                    Ask the Data Assistant a question
                                </label>
                                <input
                                    id={`${fieldIds}-chat`}
                                    type="text"
                                    value={chatInput}
                                    onChange={(e) => setChatInput(e.target.value)}
                                    placeholder="Ask about data fields, methodology, analyses..."
                                    className="flex-1 bg-white/[0.06] border border-white/15 rounded-2xl px-4 py-2.5 text-sm text-white placeholder-white/40 focus:outline-none focus:ring-2 focus:ring-primary-400/60 focus:border-transparent"
                                    disabled={chatLoading}
                                />
                                <button
                                    type="submit"
                                    disabled={chatLoading || !chatInput.trim()}
                                    className="p-2.5 bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 border border-primary-400/50 shadow-lg shadow-primary-500/25 rounded-2xl text-white disabled:opacity-40 transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                    aria-label="Send message"
                                >
                                    <Send className="w-4 h-4" aria-hidden="true" />
                                </button>
                            </div>
                        </form>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
};

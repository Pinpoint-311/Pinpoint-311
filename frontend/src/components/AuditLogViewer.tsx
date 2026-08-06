import { Fragment, useState, useEffect, useCallback } from 'react';
import { Shield, Download, RefreshCw, AlertCircle, CheckCircle, XCircle, User, ChevronLeft, ChevronRight, ChevronDown, Sparkles } from 'lucide-react';
import { AccordionSection } from './ui';

interface AuditLog {
    id: number;
    event_type: string;
    success: boolean;
    username: string | null;
    ip_address: string | null;
    user_agent: string | null;
    timestamp: string;
    failure_reason: string | null;
    details: any;
}

interface AuditStats {
    total_events: number;
    successful_logins: number;
    failed_logins: number;
    total_logouts: number;
    unique_users: number;
    recent_failures: number;
}

type Details = Record<string, any>;

const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? '' : 's'}`;
const listOf = (v: unknown): string => Array.isArray(v) ? v.join(', ') : String(v ?? '');

/** One sentence per event type: who did what to what — the "who" and "when"
 * are their own columns, so the sentence carries the "what".
 *
 * "connector_alerts_muted" with a details blob nobody could see read as
 * noise; "Muted alert emails for sms for 7 days" is a row a clerk can answer
 * a question from. Each template reads only the keys its backend writer
 * actually sends; an event type with no template (or whose details are
 * missing the expected keys) falls through to a readable key: value list
 * rather than raw JSON or a dash. */
const EVENT_SENTENCES: Record<string, (d: Details) => string | null> = {
    login_success: d => d.mfa_type ? `Signed in (MFA: ${d.mfa_type})` : 'Signed in',
    logout: () => 'Signed out',
    session_expired: () => 'Session expired',
    role_changed: d => (d.old_role && d.new_role)
        ? `Role changed from ${d.old_role} to ${d.new_role}${d.changed_by ? ` by ${d.changed_by}` : ''}`
        : null,
    // The backstop middleware already writes its own sentence.
    admin_change: d => typeof d.action === 'string' && d.action
        ? d.action
        : (d.method && d.path ? `${d.method} ${d.path}` : null),
    connector_alerts_muted: d => d.connector
        ? `Muted alert emails for ${d.connector}${d.days ? ` for ${plural(d.days, 'day')}` : ''}`
        : null,
    connector_alerts_unmuted: d => d.connector ? `Unmuted alert emails for ${d.connector}` : null,
    'setup.complete': () => 'Marked the setup guide as complete',
    'secret_store.choose': d => d.store ? `Chose ${d.store} as the secret store` : null,
    provider_saved: d => {
        if (!d.capability || !d.provider) return null;
        let s = `Selected ${d.provider} as the ${d.capability} provider`;
        if (d.model) s += ` (model ${d.model})`;
        if (Array.isArray(d.settings_updated) && d.settings_updated.length) {
            s += `; updated ${listOf(d.settings_updated)}`;
        }
        return s;
    },
    secret_saved: d => d.key_name
        ? (d.configured === false
            ? `Cleared the ${d.key_name} credential`
            : `Saved the ${d.key_name} credential${d.stored_in === 'secret_manager' ? ' to the secret store' : ''}`)
        : null,
    capability_switches_changed: d => {
        const on = Array.isArray(d.turned_on) ? d.turned_on : [];
        const off = Array.isArray(d.turned_off) ? d.turned_off : [];
        const parts = [];
        if (on.length) parts.push(`Turned on ${on.join(', ')}`);
        if (off.length) parts.push(`${on.length ? 'turned' : 'Turned'} off ${off.join(', ')}`);
        return parts.length ? parts.join('; ') : null;
    },
    user_created: d => d.target_username
        ? `Created account ${d.target_username}${d.role ? ` with role ${d.role}` : ''}`
        : null,
    user_updated: d => d.target_username
        ? `Updated account ${d.target_username}`
            + (d.role ? ` — role set to ${d.role}` : '')
            + (Array.isArray(d.fields) && d.fields.length ? ` (changed: ${listOf(d.fields)})` : '')
        : null,
    user_deleted: d => d.target_username
        ? `Deleted account ${d.target_username}${d.role ? ` (${d.role})` : ''}`
        : null,
    user_password_reset: d => d.target_username ? `Reset the password for ${d.target_username}` : null,
    department_created: d => d.name ? `Created department "${d.name}"` : null,
    department_deleted: d => d.name ? `Deleted department "${d.name}"` : null,
    service_created: d => `Created service category "${d.service_name || d.service_code || '?'}"`,
    service_deleted: d => `Deleted service category "${d.service_name || d.service_code || '?'}"`,
    service_toggled: d => d.service_code
        ? `Turned ${d.is_active ? 'on' : 'off'} the ${d.service_code} service category`
        : null,
    public_records_export: d => typeof d.records === 'number'
        ? `Exported ${plural(d.records, 'record')} to CSV`
            + (Array.isArray(d.sensitive_fields) && d.sensitive_fields.length
                ? ` including sensitive fields (${listOf(d.sensitive_fields)})` : '')
        : null,
    data_export_pii: d => `Exported service requests including resident PII (${d.format || 'csv'})`,
    backup_key_generated: () => 'Generated a new backup encryption key',
    pii_reencryption: d => `Re-encrypted resident records (${plural(d.rows ?? 0, 'row')}, ${plural(d.fields ?? 0, 'field')})`,
    gcp_configured: d => d.project_id ? `Connected Google Cloud project ${d.project_id}` : null,
    auth0_configured: d => d.domain ? `Connected Auth0 tenant ${d.domain}` : null,
    version_deployed: d => d.to_sha ? `Deployed version ${d.to_sha}` : null,
    version_deployment_failed: d => d.target_ref ? `Deployment of ${d.target_ref} failed and was rolled back` : null,
    onboarding_redeemed: () => 'Signed in with a one-time onboarding link',
};

/** The fallback, and the expanded view: every detail as a readable
 * "key: value" pair instead of raw JSON. Values are shallow — an array joins,
 * a nested object stringifies — because the payloads are written flat. */
const detailEntries = (details: unknown): Array<[string, string]> => {
    if (!details || typeof details !== 'object') return [];
    return Object.entries(details as Details)
        .filter(([, v]) => v !== null && v !== undefined && v !== '')
        .map(([k, v]) => [
            k.replace(/_/g, ' '),
            Array.isArray(v) ? v.join(', ')
                : typeof v === 'object' ? JSON.stringify(v)
                : String(v),
        ]);
};

const describeEvent = (eventType: string, details: unknown): string => {
    const template = EVENT_SENTENCES[eventType];
    const d = (details && typeof details === 'object') ? details as Details : {};
    const sentence = template ? template(d) : null;
    if (sentence) return sentence;
    return detailEntries(details).map(([k, v]) => `${k}: ${v}`).join(' · ');
};

export default function AuditLogViewer() {
    const [logs, setLogs] = useState<AuditLog[]>([]);
    const [stats, setStats] = useState<AuditStats | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [expandedId, setExpandedId] = useState<number | null>(null);

    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(25);
    const [totalCount, setTotalCount] = useState(0);

    const [filterEventType, setFilterEventType] = useState('all');
    const [filterSuccess, setFilterSuccess] = useState('all');
    const [filterUsername, setFilterUsername] = useState('');
    const [startDate, setStartDate] = useState('');
    const [endDate, setEndDate] = useState('');
    const [quickRange, setQuickRange] = useState<string>('7');

    const totalPages = Math.ceil(totalCount / pageSize);

    const applyQuickRange = useCallback((days: string) => {
        setQuickRange(days);
        const end = new Date();
        const start = new Date();

        if (days === 'today') {
            start.setHours(0, 0, 0, 0);
        } else if (days === 'custom') {
            return;
        } else {
            start.setDate(start.getDate() - parseInt(days));
        }

        setEndDate(end.toISOString().split('T')[0]);
        setStartDate(start.toISOString().split('T')[0]);
    }, []);

    useEffect(() => {
        applyQuickRange('7');
    }, [applyQuickRange]);

    const fetchLogs = async () => {
        setIsLoading(true);
        setError(null);

        try {
            const token = localStorage.getItem('token');

            const params = new URLSearchParams();
            if (filterEventType !== 'all') params.append('event_type', filterEventType);
            if (filterSuccess !== 'all') params.append('success', filterSuccess);
            if (filterUsername) params.append('username', filterUsername);
            if (startDate) params.append('start_date', startDate);
            if (endDate) params.append('end_date', endDate);
            params.append('page', currentPage.toString());
            params.append('page_size', pageSize.toString());

            const response = await fetch(`/api/audit/logs?${params}`, {
                headers: { 'Authorization': `Bearer ${token}` },
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            setLogs(data.logs || []);
            setTotalCount(data.total_count || data.logs?.length || 0);

            const statsResponse = await fetch('/api/audit/stats', {
                headers: { 'Authorization': `Bearer ${token}` },
            });

            if (statsResponse.ok) {
                const statsData = await statsResponse.json();
                setStats(statsData);
            }
        } catch (err: any) {
            setError(err.message || 'Failed to fetch audit logs');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        if (startDate && endDate) {
            fetchLogs();
        }
    }, [filterEventType, filterSuccess, currentPage, pageSize, startDate, endDate]);

    useEffect(() => {
        setCurrentPage(1);
    }, [filterEventType, filterSuccess, filterUsername, startDate, endDate, pageSize]);

    const handleExport = async () => {
        try {
            const token = localStorage.getItem('token');
            const params = new URLSearchParams();
            if (filterEventType !== 'all') params.append('event_type', filterEventType);
            if (filterSuccess !== 'all') params.append('success', filterSuccess);
            if (filterUsername) params.append('username', filterUsername);
            if (startDate) params.append('start_date', startDate);
            if (endDate) params.append('end_date', endDate);

            const response = await fetch(`/api/audit/export?${params}`, {
                headers: { 'Authorization': `Bearer ${token}` },
            });

            if (response.ok) {
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `audit_logs_${new Date().toISOString().split('T')[0]}.csv`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
            }
        } catch (err) {
            console.error('Export failed:', err);
        }
    };

    const handleSearch = () => {
        setCurrentPage(1);
        fetchLogs();
    };

    const getEventIcon = (eventType: string, success: boolean) => {
        if (!success) return <XCircle className="w-4 h-4 text-red-400" />;
        if (eventType.includes('login')) return <CheckCircle className="w-4 h-4 text-emerald-400" />;
        if (eventType.includes('logout')) return <User className="w-4 h-4 text-blue-400" />;
        if (eventType.includes('emergency')) return <Sparkles className="w-4 h-4 text-indigo-400" />;
        return <Shield className="w-4 h-4 text-slate-400" />;
    };

    const getEventLabel = (eventType: string) => {
        const labels: Record<string, string> = {
            'login_success': 'Login Success',
            'login_failed': 'Login Failed',
            'logout': 'Logout',
            'role_changed': 'Role Changed',
            'mfa_enrolled': 'MFA Enrolled',
            'mfa_disabled': 'MFA Disabled',
            'password_changed': 'Password Changed',
            'session_expired': 'Session Expired',
            'account_locked': 'Account Locked',
            'account_unlocked': 'Account Unlocked',
            'emergency_access_success': 'Emergency Access',
            'emergency_access_failed': 'Emergency Access Failed',
            // Dots defeat the generic snake_case fallback below.
            'setup.complete': 'Setup Completed',
            'secret_store.choose': 'Secret Store Chosen',
            'connector_alerts_muted': 'Alerts Muted',
            'connector_alerts_unmuted': 'Alerts Unmuted',
            'data_export_pii': 'PII Export',
            'public_records_export': 'Records Export',
            'capability_switches_changed': 'Integrations Switched',
            'provider_saved': 'Provider Saved',
            'secret_saved': 'Credential Saved',
        };
        return labels[eventType] || eventType.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    };

    const formatTimestamp = (timestamp: string) => {
        return new Date(timestamp).toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        });
    };

    // Common input style
    const inputStyle = "bg-white/10 border border-white/20 rounded-lg px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-indigo-400 text-sm";
    const labelStyle = "block text-sm font-medium text-white/70 mb-2";

    return (
        <AccordionSection
            title="Audit Logs"
            subtitle="Authentication event logging (NIST 800-53 compliant)"
            icon={Shield}
            iconClassName="text-indigo-400"
            badge={
                stats ? (
                    <span className="px-2.5 py-1 text-xs font-medium bg-indigo-500/20 text-indigo-300 rounded-md border border-indigo-500/30">
                        {stats.total_events.toLocaleString()} Events
                    </span>
                ) : undefined
            }
        >
            <div className="space-y-8">
                {/* Filters */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    <div>
                        <label className={labelStyle}>Time Range</label>
                        <select
                            value={quickRange}
                            onChange={(e) => applyQuickRange(e.target.value)}
                            className={inputStyle + " w-full"}
                        >
                            <option value="today" className="bg-slate-800">Today</option>
                            <option value="7" className="bg-slate-800">Last 7 Days</option>
                            <option value="30" className="bg-slate-800">Last 30 Days</option>
                            <option value="90" className="bg-slate-800">Last 90 Days</option>
                            <option value="365" className="bg-slate-800">Last Year</option>
                            <option value="custom" className="bg-slate-800">Custom Range</option>
                        </select>
                    </div>

                    <div>
                        <label className={labelStyle}>Event Type</label>
                        <select
                            value={filterEventType}
                            onChange={(e) => setFilterEventType(e.target.value)}
                            className={inputStyle + " w-full"}
                        >
                            <option value="all" className="bg-slate-800">All Events</option>
                            <optgroup label="Sign-in">
                                <option value="login_success" className="bg-slate-800">Login Success</option>
                                <option value="login_failed" className="bg-slate-800">Login Failed</option>
                                <option value="logout" className="bg-slate-800">Logout</option>
                                <option value="emergency_access_success" className="bg-slate-800">Emergency Access</option>
                            </optgroup>
                            <optgroup label="Admin actions">
                                <option value="admin_change" className="bg-slate-800">Admin Change</option>
                                <option value="user_created" className="bg-slate-800">Account Created</option>
                                <option value="user_updated" className="bg-slate-800">Account Updated</option>
                                <option value="user_deleted" className="bg-slate-800">Account Deleted</option>
                                <option value="provider_saved" className="bg-slate-800">Provider Saved</option>
                                <option value="secret_saved" className="bg-slate-800">Credential Saved</option>
                                <option value="capability_switches_changed" className="bg-slate-800">Integrations Switched</option>
                                <option value="connector_alerts_muted" className="bg-slate-800">Alerts Muted</option>
                                <option value="public_records_export" className="bg-slate-800">Records Export</option>
                                <option value="data_export_pii" className="bg-slate-800">PII Export</option>
                            </optgroup>
                        </select>
                    </div>

                    <div>
                        <label className={labelStyle}>Status</label>
                        <select
                            value={filterSuccess}
                            onChange={(e) => setFilterSuccess(e.target.value)}
                            className={inputStyle + " w-full"}
                        >
                            <option value="all" className="bg-slate-800">All</option>
                            <option value="true" className="bg-slate-800">Success Only</option>
                            <option value="false" className="bg-slate-800">Failed Only</option>
                        </select>
                    </div>

                    <div>
                        <label className={labelStyle}>Username</label>
                        <input
                            type="text"
                            value={filterUsername}
                            onChange={(e) => setFilterUsername(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                            placeholder="Search by username..."
                            className={inputStyle + " w-full placeholder:text-white/40"}
                        />
                    </div>
                </div>

                {/* Custom Date Range */}
                {quickRange === 'custom' && (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                        <div>
                            <label className={labelStyle}>From Date</label>
                            <input
                                type="date"
                                value={startDate}
                                onChange={(e) => setStartDate(e.target.value)}
                                className={inputStyle + " w-full"}
                            />
                        </div>
                        <div>
                            <label className={labelStyle}>To Date</label>
                            <input
                                type="date"
                                value={endDate}
                                onChange={(e) => setEndDate(e.target.value)}
                                className={inputStyle + " w-full"}
                            />
                        </div>
                    </div>
                )}

                {/* Actions */}
                <div className="flex gap-3">
                    <button
                        onClick={fetchLogs}
                        disabled={isLoading}
                        className="flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50 font-medium"
                    >
                        <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                        Refresh
                    </button>
                    <button
                        onClick={handleExport}
                        className="flex items-center gap-2 px-5 py-2.5 bg-white/10 hover:bg-white/20 text-white rounded-lg transition-colors"
                    >
                        <Download className="w-4 h-4" />
                        Export CSV
                    </button>
                </div>

                {/* Table */}
                <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
                    {error && (
                        <div className="p-4 bg-red-500/10 border-b border-red-500/20 flex items-center gap-3">
                            <AlertCircle className="w-5 h-5 text-red-400" />
                            <span className="text-red-400 text-sm">{error}</span>
                        </div>
                    )}

                    {isLoading ? (
                        <div className="p-16 text-center">
                            <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-4 text-indigo-400" />
                            <div className="text-white/50">Loading audit logs...</div>
                        </div>
                    ) : logs.length === 0 ? (
                        <div className="p-16 text-center text-white/50">
                            No audit logs found for selected filters.
                        </div>
                    ) : (
                        <>
                            <div className="overflow-x-auto">
                                <table className="w-full">
                                    <thead>
                                        <tr className="border-b border-white/10 text-left bg-white/5">
                                            <th className="px-6 py-4 text-xs font-semibold text-white/60 uppercase tracking-wider">Event</th>
                                            <th className="px-6 py-4 text-xs font-semibold text-white/60 uppercase tracking-wider">User</th>
                                            <th className="px-6 py-4 text-xs font-semibold text-white/60 uppercase tracking-wider">IP Address</th>
                                            <th className="px-6 py-4 text-xs font-semibold text-white/60 uppercase tracking-wider">Timestamp</th>
                                            <th className="px-6 py-4 text-xs font-semibold text-white/60 uppercase tracking-wider">Details</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-white/5">
                                        {logs.map((log) => {
                                            const sentence = describeEvent(log.event_type, log.details);
                                            const entries = detailEntries(log.details);
                                            const expandable = entries.length > 0 || !!log.user_agent;
                                            const expanded = expandedId === log.id;
                                            return (
                                                <Fragment key={log.id}>
                                                    <tr
                                                        className={`hover:bg-white/5 transition-colors ${expandable ? 'cursor-pointer' : ''}`}
                                                        onClick={() => expandable && setExpandedId(expanded ? null : log.id)}
                                                    >
                                                        <td className="px-6 py-4">
                                                            <div className="flex items-center gap-3">
                                                                {getEventIcon(log.event_type, log.success)}
                                                                <span className={`text-sm font-medium ${log.success ? 'text-white' : 'text-red-400'}`}>
                                                                    {getEventLabel(log.event_type)}
                                                                </span>
                                                            </div>
                                                        </td>
                                                        <td className="px-6 py-4 text-sm text-white/80">{log.username || 'Unknown'}</td>
                                                        <td className="px-6 py-4 text-sm text-white/50 font-mono">{log.ip_address || '-'}</td>
                                                        <td className="px-6 py-4 text-sm text-white/60">{formatTimestamp(log.timestamp)}</td>
                                                        <td className="px-6 py-4 text-sm">
                                                            <div className="flex items-start gap-2">
                                                                <div className="min-w-0">
                                                                    {sentence && (
                                                                        <span className="text-white/70">{sentence}</span>
                                                                    )}
                                                                    {log.failure_reason && (
                                                                        <div className="text-red-400">{log.failure_reason}</div>
                                                                    )}
                                                                    {!sentence && !log.failure_reason && (
                                                                        <span className="text-white/30">-</span>
                                                                    )}
                                                                </div>
                                                                {expandable && (
                                                                    <ChevronDown
                                                                        className={`w-4 h-4 mt-0.5 shrink-0 text-white/40 transition-transform ${expanded ? 'rotate-180' : ''}`}
                                                                    />
                                                                )}
                                                            </div>
                                                        </td>
                                                    </tr>
                                                    {expanded && (
                                                        <tr key={`${log.id}-details`} className="bg-white/5">
                                                            <td colSpan={5} className="px-6 py-4">
                                                                <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-2 text-sm">
                                                                    {entries.map(([k, v]) => (
                                                                        <div key={k} className="flex gap-2">
                                                                            <dt className="text-white/50 capitalize shrink-0">{k}:</dt>
                                                                            <dd className="text-white/80 break-all">{v}</dd>
                                                                        </div>
                                                                    ))}
                                                                    {log.user_agent && (
                                                                        <div className="flex gap-2 md:col-span-2">
                                                                            <dt className="text-white/50 shrink-0">Browser:</dt>
                                                                            <dd className="text-white/60 break-all">{log.user_agent}</dd>
                                                                        </div>
                                                                    )}
                                                                </dl>
                                                            </td>
                                                        </tr>
                                                    )}
                                                </Fragment>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>

                            {/* Pagination */}
                            <div className="flex items-center justify-between px-6 py-4 border-t border-white/10 bg-white/5">
                                <div className="flex items-center gap-3 text-sm text-white/60">
                                    <span>Showing</span>
                                    <select
                                        value={pageSize}
                                        onChange={(e) => setPageSize(parseInt(e.target.value))}
                                        className="bg-white/10 text-white rounded-lg px-3 py-1.5 border border-white/20"
                                    >
                                        <option value="10" className="bg-slate-800">10</option>
                                        <option value="25" className="bg-slate-800">25</option>
                                        <option value="50" className="bg-slate-800">50</option>
                                    </select>
                                    <span>of {totalCount.toLocaleString()} entries</span>
                                </div>

                                <div className="flex items-center gap-2">
                                    <button
                                        onClick={() => setCurrentPage(1)}
                                        disabled={currentPage === 1}
                                        className="px-3 py-1.5 text-sm text-white/70 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
                                    >
                                        First
                                    </button>
                                    <button
                                        onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                        disabled={currentPage === 1}
                                        className="p-1.5 text-white/70 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
                                    >
                                        <ChevronLeft className="w-5 h-5" />
                                    </button>
                                    <span className="px-3 text-sm text-white/70">
                                        Page <span className="text-white font-medium">{currentPage}</span> of {totalPages}
                                    </span>
                                    <button
                                        onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                        disabled={currentPage === totalPages}
                                        className="p-1.5 text-white/70 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
                                    >
                                        <ChevronRight className="w-5 h-5" />
                                    </button>
                                    <button
                                        onClick={() => setCurrentPage(totalPages)}
                                        disabled={currentPage === totalPages}
                                        className="px-3 py-1.5 text-sm text-white/70 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
                                    >
                                        Last
                                    </button>
                                </div>
                            </div>
                        </>
                    )}
                </div>

                {/* Compliance Footer */}
                <p className="text-xs text-white/40 flex items-center gap-2">
                    <Shield className="w-4 h-4" />
                    NIST 800-53 compliant · Tamper-detection hash chaining (AU-9) · Immutable retention
                </p>
            </div>
        </AccordionSection>
    );
}

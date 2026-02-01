import { useState, useEffect, useCallback } from 'react';
import { Shield, Download, RefreshCw, AlertCircle, CheckCircle, XCircle, User, Clock, MapPin, ChevronLeft, ChevronRight, Calendar, Search, Filter, Sparkles } from 'lucide-react';
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

export default function AuditLogViewer() {
    const [logs, setLogs] = useState<AuditLog[]>([]);
    const [stats, setStats] = useState<AuditStats | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Pagination
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(25);
    const [totalCount, setTotalCount] = useState(0);

    // Filters
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
            <div className="space-y-5">
                {/* Statistics Cards - Clean Premium Style */}
                {stats && (
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                        <div className="bg-white/5 backdrop-blur-sm border border-white/10 p-4 rounded-xl">
                            <div className="text-white/50 text-xs uppercase tracking-wide font-medium">Total Events</div>
                            <div className="text-2xl font-semibold text-white mt-1">{stats.total_events.toLocaleString()}</div>
                        </div>
                        <div className="bg-white/5 backdrop-blur-sm border border-emerald-500/20 p-4 rounded-xl">
                            <div className="text-emerald-400/70 text-xs uppercase tracking-wide font-medium">Successful</div>
                            <div className="text-2xl font-semibold text-emerald-400 mt-1">{stats.successful_logins.toLocaleString()}</div>
                        </div>
                        <div className="bg-white/5 backdrop-blur-sm border border-red-500/20 p-4 rounded-xl">
                            <div className="text-red-400/70 text-xs uppercase tracking-wide font-medium">Failed</div>
                            <div className="text-2xl font-semibold text-red-400 mt-1">{stats.failed_logins.toLocaleString()}</div>
                        </div>
                        <div className="bg-white/5 backdrop-blur-sm border border-blue-500/20 p-4 rounded-xl">
                            <div className="text-blue-400/70 text-xs uppercase tracking-wide font-medium">Logouts</div>
                            <div className="text-2xl font-semibold text-blue-400 mt-1">{stats.total_logouts.toLocaleString()}</div>
                        </div>
                        <div className="bg-white/5 backdrop-blur-sm border border-purple-500/20 p-4 rounded-xl">
                            <div className="text-purple-400/70 text-xs uppercase tracking-wide font-medium">Unique Users</div>
                            <div className="text-2xl font-semibold text-purple-400 mt-1">{stats.unique_users.toLocaleString()}</div>
                        </div>
                        <div className="bg-white/5 backdrop-blur-sm border border-yellow-500/20 p-4 rounded-xl">
                            <div className="text-yellow-400/70 text-xs uppercase tracking-wide font-medium">Recent Failures</div>
                            <div className="text-2xl font-semibold text-yellow-400 mt-1">{stats.recent_failures.toLocaleString()}</div>
                        </div>
                    </div>
                )}

                {/* Filters - Clean Formal Style */}
                <div className="bg-white/5 backdrop-blur-sm border border-white/10 p-5 rounded-xl">
                    <div className="flex items-center gap-2 mb-4">
                        <Filter className="w-4 h-4 text-indigo-400" />
                        <span className="text-sm font-medium text-white/90 uppercase tracking-wide">Search & Filter</span>
                    </div>

                    {/* Quick Date Range Buttons */}
                    <div className="flex flex-wrap gap-2 mb-4">
                        {[
                            { value: 'today', label: 'Today' },
                            { value: '7', label: 'Last 7 Days' },
                            { value: '30', label: 'Last 30 Days' },
                            { value: '90', label: 'Last 90 Days' },
                            { value: '365', label: 'Last Year' },
                            { value: 'custom', label: 'Custom Range' },
                        ].map((range) => (
                            <button
                                key={range.value}
                                onClick={() => applyQuickRange(range.value)}
                                className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-all ${quickRange === range.value
                                        ? 'bg-indigo-600 text-white'
                                        : 'bg-white/10 text-white/70 hover:bg-white/15 hover:text-white'
                                    }`}
                            >
                                {range.label}
                            </button>
                        ))}
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-3">
                        {/* Start Date */}
                        <div>
                            <label className="block text-xs font-medium text-white/50 uppercase tracking-wide mb-1.5">Start Date</label>
                            <div className="relative">
                                <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
                                <input
                                    type="date"
                                    value={startDate}
                                    onChange={(e) => {
                                        setStartDate(e.target.value);
                                        setQuickRange('custom');
                                    }}
                                    className="w-full bg-white/10 text-white rounded-lg pl-10 pr-3 py-2 border border-white/15 focus:outline-none focus:border-indigo-500/50 text-sm transition-colors"
                                />
                            </div>
                        </div>

                        {/* End Date */}
                        <div>
                            <label className="block text-xs font-medium text-white/50 uppercase tracking-wide mb-1.5">End Date</label>
                            <div className="relative">
                                <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
                                <input
                                    type="date"
                                    value={endDate}
                                    onChange={(e) => {
                                        setEndDate(e.target.value);
                                        setQuickRange('custom');
                                    }}
                                    className="w-full bg-white/10 text-white rounded-lg pl-10 pr-3 py-2 border border-white/15 focus:outline-none focus:border-indigo-500/50 text-sm transition-colors"
                                />
                            </div>
                        </div>

                        {/* Event Type */}
                        <div>
                            <label className="block text-xs font-medium text-white/50 uppercase tracking-wide mb-1.5">Event Type</label>
                            <select
                                value={filterEventType}
                                onChange={(e) => setFilterEventType(e.target.value)}
                                className="w-full bg-white/10 text-white rounded-lg px-3 py-2 border border-white/15 focus:outline-none focus:border-indigo-500/50 text-sm transition-colors"
                            >
                                <option value="all" className="bg-slate-800">All Events</option>
                                <option value="login_success" className="bg-slate-800">Login Success</option>
                                <option value="login_failed" className="bg-slate-800">Login Failed</option>
                                <option value="logout" className="bg-slate-800">Logout</option>
                                <option value="emergency_access_success" className="bg-slate-800">Emergency Access</option>
                                <option value="emergency_access_failed" className="bg-slate-800">Emergency Failed</option>
                            </select>
                        </div>

                        {/* Status */}
                        <div>
                            <label className="block text-xs font-medium text-white/50 uppercase tracking-wide mb-1.5">Status</label>
                            <select
                                value={filterSuccess}
                                onChange={(e) => setFilterSuccess(e.target.value)}
                                className="w-full bg-white/10 text-white rounded-lg px-3 py-2 border border-white/15 focus:outline-none focus:border-indigo-500/50 text-sm transition-colors"
                            >
                                <option value="all" className="bg-slate-800">All</option>
                                <option value="true" className="bg-slate-800">Success Only</option>
                                <option value="false" className="bg-slate-800">Failures Only</option>
                            </select>
                        </div>

                        {/* Username Search */}
                        <div>
                            <label className="block text-xs font-medium text-white/50 uppercase tracking-wide mb-1.5">Username</label>
                            <div className="relative">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
                                <input
                                    type="text"
                                    value={filterUsername}
                                    onChange={(e) => setFilterUsername(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                                    placeholder="Search user..."
                                    className="w-full bg-white/10 text-white rounded-lg pl-10 pr-3 py-2 border border-white/15 focus:outline-none focus:border-indigo-500/50 placeholder-white/30 text-sm transition-colors"
                                />
                            </div>
                        </div>

                        {/* Page Size */}
                        <div>
                            <label className="block text-xs font-medium text-white/50 uppercase tracking-wide mb-1.5">Per Page</label>
                            <select
                                value={pageSize}
                                onChange={(e) => setPageSize(parseInt(e.target.value))}
                                className="w-full bg-white/10 text-white rounded-lg px-3 py-2 border border-white/15 focus:outline-none focus:border-indigo-500/50 text-sm transition-colors"
                            >
                                <option value="10" className="bg-slate-800">10</option>
                                <option value="25" className="bg-slate-800">25</option>
                                <option value="50" className="bg-slate-800">50</option>
                                <option value="100" className="bg-slate-800">100</option>
                            </select>
                        </div>
                    </div>

                    <div className="flex gap-2 mt-4">
                        <button
                            onClick={handleSearch}
                            disabled={isLoading}
                            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors disabled:opacity-50 text-sm font-medium"
                        >
                            <Search className="w-4 h-4" />
                            Search
                        </button>

                        <button
                            onClick={fetchLogs}
                            disabled={isLoading}
                            className="flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/15 text-white rounded-lg transition-colors disabled:opacity-50 text-sm"
                        >
                            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                            Refresh
                        </button>

                        <button
                            onClick={handleExport}
                            className="flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/15 text-white rounded-lg transition-colors text-sm"
                        >
                            <Download className="w-4 h-4" />
                            Export CSV
                        </button>
                    </div>
                </div>

                {/* Audit Logs Table */}
                <div className="bg-white/5 backdrop-blur-sm border border-white/10 rounded-xl overflow-hidden">
                    {error && (
                        <div className="p-4 bg-red-500/10 border-b border-red-500/20 flex items-start gap-3">
                            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                            <div>
                                <div className="text-red-400 font-medium text-sm">Error</div>
                                <div className="text-white/70 text-sm mt-1">{error}</div>
                            </div>
                        </div>
                    )}

                    {isLoading ? (
                        <div className="p-12 text-center">
                            <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-3 text-indigo-400" />
                            <div className="text-white/50 text-sm">Loading audit logs...</div>
                        </div>
                    ) : logs.length === 0 ? (
                        <div className="p-12 text-center text-white/50 text-sm">
                            No audit logs found for the selected filters.
                        </div>
                    ) : (
                        <>
                            <div className="overflow-x-auto">
                                <table className="w-full">
                                    <thead>
                                        <tr className="border-b border-white/10">
                                            <th className="text-left p-4 text-xs font-medium text-white/50 uppercase tracking-wide">Event</th>
                                            <th className="text-left p-4 text-xs font-medium text-white/50 uppercase tracking-wide">User</th>
                                            <th className="text-left p-4 text-xs font-medium text-white/50 uppercase tracking-wide">IP Address</th>
                                            <th className="text-left p-4 text-xs font-medium text-white/50 uppercase tracking-wide">Timestamp</th>
                                            <th className="text-left p-4 text-xs font-medium text-white/50 uppercase tracking-wide">Details</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {logs.map((log, index) => (
                                            <tr
                                                key={log.id}
                                                className={`border-b border-white/5 hover:bg-white/5 transition-colors ${index % 2 === 0 ? 'bg-white/[0.02]' : ''
                                                    }`}
                                            >
                                                <td className="p-4">
                                                    <div className="flex items-center gap-2">
                                                        {getEventIcon(log.event_type, log.success)}
                                                        <span className={`text-sm ${log.success ? 'text-white' : 'text-red-400'}`}>
                                                            {getEventLabel(log.event_type)}
                                                        </span>
                                                    </div>
                                                </td>
                                                <td className="p-4">
                                                    <div className="flex items-center gap-2">
                                                        <User className="w-4 h-4 text-white/30" />
                                                        <span className="text-white/80 text-sm">{log.username || 'Unknown'}</span>
                                                    </div>
                                                </td>
                                                <td className="p-4">
                                                    <span className="text-white/50 font-mono text-xs">
                                                        {log.ip_address || '-'}
                                                    </span>
                                                </td>
                                                <td className="p-4">
                                                    <div className="flex items-center gap-2 text-white/50 text-sm">
                                                        <Clock className="w-4 h-4 text-white/30" />
                                                        {formatTimestamp(log.timestamp)}
                                                    </div>
                                                </td>
                                                <td className="p-4">
                                                    {log.failure_reason ? (
                                                        <span className="text-red-400 text-sm">{log.failure_reason}</span>
                                                    ) : log.details?.mfa_type ? (
                                                        <span className="text-emerald-400 text-sm">MFA: {log.details.mfa_type}</span>
                                                    ) : (
                                                        <span className="text-white/30 text-sm">-</span>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            {/* Pagination */}
                            <div className="flex items-center justify-between p-4 border-t border-white/10">
                                <div className="text-sm text-white/50">
                                    Showing {((currentPage - 1) * pageSize) + 1} - {Math.min(currentPage * pageSize, totalCount)} of {totalCount.toLocaleString()} entries
                                </div>

                                <div className="flex items-center gap-1">
                                    <button
                                        onClick={() => setCurrentPage(1)}
                                        disabled={currentPage === 1}
                                        className="px-3 py-1.5 text-sm bg-white/10 hover:bg-white/15 text-white rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                                    >
                                        First
                                    </button>
                                    <button
                                        onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                        disabled={currentPage === 1}
                                        className="p-1.5 bg-white/10 hover:bg-white/15 text-white rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                                    >
                                        <ChevronLeft className="w-4 h-4" />
                                    </button>

                                    <div className="flex items-center gap-1 px-2">
                                        <span className="text-white/50 text-sm">Page</span>
                                        <input
                                            type="number"
                                            min={1}
                                            max={totalPages}
                                            value={currentPage}
                                            onChange={(e) => {
                                                const page = parseInt(e.target.value);
                                                if (page >= 1 && page <= totalPages) {
                                                    setCurrentPage(page);
                                                }
                                            }}
                                            className="w-12 bg-white/10 text-white text-center rounded-md px-1 py-1 border border-white/15 focus:outline-none focus:border-indigo-500/50 text-sm"
                                        />
                                        <span className="text-white/50 text-sm">of {totalPages}</span>
                                    </div>

                                    <button
                                        onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                        disabled={currentPage === totalPages}
                                        className="p-1.5 bg-white/10 hover:bg-white/15 text-white rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                                    >
                                        <ChevronRight className="w-4 h-4" />
                                    </button>
                                    <button
                                        onClick={() => setCurrentPage(totalPages)}
                                        disabled={currentPage === totalPages}
                                        className="px-3 py-1.5 text-sm bg-white/10 hover:bg-white/15 text-white rounded-lg transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                                    >
                                        Last
                                    </button>
                                </div>
                            </div>
                        </>
                    )}
                </div>

                {/* Compliance Note */}
                <div className="bg-indigo-500/10 border border-indigo-500/20 p-4 rounded-xl">
                    <div className="flex items-start gap-3">
                        <Shield className="w-5 h-5 text-indigo-400 flex-shrink-0 mt-0.5" />
                        <div>
                            <div className="text-indigo-300 font-medium text-sm">Government Compliance (NIST 800-53)</div>
                            <div className="text-white/60 text-sm mt-1">
                                All authentication events are logged with tamper-detection hash chaining (AU-9).
                                Logs are immutable and retained per state retention policy. Use Export for compliance audits.
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </AccordionSection>
    );
}

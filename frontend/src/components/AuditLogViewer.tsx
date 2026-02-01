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

    // Calculate total pages
    const totalPages = Math.ceil(totalCount / pageSize);

    // Set date range based on quick range selection
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

    // Initialize with 7-day range
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
        if (eventType.includes('emergency')) return <Sparkles className="w-4 h-4 text-amber-400" />;
        return <Shield className="w-4 h-4 text-purple-400" />;
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
            iconClassName="text-amber-400"
            badge={
                stats ? (
                    <span className="px-2.5 py-1 text-xs font-semibold bg-gradient-to-r from-amber-500/20 to-orange-500/20 text-amber-300 rounded-full border border-amber-500/30">
                        {stats.total_events.toLocaleString()} Events
                    </span>
                ) : undefined
            }
        >
            <div className="space-y-6">
                {/* Statistics Cards - Premium Modern Style */}
                {stats && (
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
                        <div className="group relative bg-gradient-to-br from-white/10 to-white/5 backdrop-blur-sm border border-white/10 p-4 rounded-xl hover:border-white/20 transition-all duration-300">
                            <div className="absolute inset-0 bg-gradient-to-br from-blue-500/10 to-transparent rounded-xl opacity-0 group-hover:opacity-100 transition-opacity" />
                            <div className="relative">
                                <div className="text-white/50 text-xs uppercase tracking-wider font-medium">Total Events</div>
                                <div className="text-2xl font-bold bg-gradient-to-r from-white to-white/80 bg-clip-text text-transparent mt-1">
                                    {stats.total_events.toLocaleString()}
                                </div>
                            </div>
                        </div>
                        <div className="group relative bg-gradient-to-br from-emerald-500/10 to-emerald-500/5 backdrop-blur-sm border border-emerald-500/20 p-4 rounded-xl hover:border-emerald-500/40 transition-all duration-300">
                            <div className="text-emerald-400/70 text-xs uppercase tracking-wider font-medium">Successful</div>
                            <div className="text-2xl font-bold text-emerald-400 mt-1">{stats.successful_logins.toLocaleString()}</div>
                        </div>
                        <div className="group relative bg-gradient-to-br from-red-500/10 to-red-500/5 backdrop-blur-sm border border-red-500/20 p-4 rounded-xl hover:border-red-500/40 transition-all duration-300">
                            <div className="text-red-400/70 text-xs uppercase tracking-wider font-medium">Failed</div>
                            <div className="text-2xl font-bold text-red-400 mt-1">{stats.failed_logins.toLocaleString()}</div>
                        </div>
                        <div className="group relative bg-gradient-to-br from-blue-500/10 to-blue-500/5 backdrop-blur-sm border border-blue-500/20 p-4 rounded-xl hover:border-blue-500/40 transition-all duration-300">
                            <div className="text-blue-400/70 text-xs uppercase tracking-wider font-medium">Logouts</div>
                            <div className="text-2xl font-bold text-blue-400 mt-1">{stats.total_logouts.toLocaleString()}</div>
                        </div>
                        <div className="group relative bg-gradient-to-br from-purple-500/10 to-purple-500/5 backdrop-blur-sm border border-purple-500/20 p-4 rounded-xl hover:border-purple-500/40 transition-all duration-300">
                            <div className="text-purple-400/70 text-xs uppercase tracking-wider font-medium">Unique Users</div>
                            <div className="text-2xl font-bold text-purple-400 mt-1">{stats.unique_users.toLocaleString()}</div>
                        </div>
                        <div className="group relative bg-gradient-to-br from-amber-500/10 to-orange-500/5 backdrop-blur-sm border border-amber-500/20 p-4 rounded-xl hover:border-amber-500/40 transition-all duration-300">
                            <div className="text-amber-400/70 text-xs uppercase tracking-wider font-medium">Recent Failures</div>
                            <div className="text-2xl font-bold text-amber-400 mt-1">{stats.recent_failures.toLocaleString()}</div>
                        </div>
                    </div>
                )}

                {/* Filters - Premium Glassmorphism */}
                <div className="relative bg-gradient-to-br from-white/10 to-white/5 backdrop-blur-xl border border-white/10 p-6 rounded-2xl">
                    <div className="absolute inset-0 bg-gradient-to-br from-amber-500/5 to-transparent rounded-2xl" />
                    <div className="relative">
                        <div className="flex items-center gap-2 mb-5">
                            <Filter className="w-4 h-4 text-amber-400" />
                            <span className="text-sm font-semibold text-white uppercase tracking-wider">Search & Filter</span>
                        </div>

                        {/* Quick Date Range Buttons */}
                        <div className="flex flex-wrap gap-2 mb-5">
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
                                    className={`px-4 py-2 text-sm font-medium rounded-lg transition-all duration-200 ${quickRange === range.value
                                            ? 'bg-gradient-to-r from-amber-500 to-orange-500 text-black shadow-lg shadow-amber-500/25'
                                            : 'bg-white/10 text-white/80 hover:bg-white/20 border border-white/10'
                                        }`}
                                >
                                    {range.label}
                                </button>
                            ))}
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-4">
                            {/* Start Date */}
                            <div>
                                <label className="block text-xs font-medium text-white/60 uppercase tracking-wider mb-2">Start Date</label>
                                <div className="relative">
                                    <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
                                    <input
                                        type="date"
                                        value={startDate}
                                        onChange={(e) => {
                                            setStartDate(e.target.value);
                                            setQuickRange('custom');
                                        }}
                                        className="w-full bg-white/10 text-white rounded-lg pl-10 pr-3 py-2.5 border border-white/20 focus:outline-none focus:border-amber-400/50 focus:ring-2 focus:ring-amber-400/20 text-sm transition-all"
                                    />
                                </div>
                            </div>

                            {/* End Date */}
                            <div>
                                <label className="block text-xs font-medium text-white/60 uppercase tracking-wider mb-2">End Date</label>
                                <div className="relative">
                                    <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
                                    <input
                                        type="date"
                                        value={endDate}
                                        onChange={(e) => {
                                            setEndDate(e.target.value);
                                            setQuickRange('custom');
                                        }}
                                        className="w-full bg-white/10 text-white rounded-lg pl-10 pr-3 py-2.5 border border-white/20 focus:outline-none focus:border-amber-400/50 focus:ring-2 focus:ring-amber-400/20 text-sm transition-all"
                                    />
                                </div>
                            </div>

                            {/* Event Type */}
                            <div>
                                <label className="block text-xs font-medium text-white/60 uppercase tracking-wider mb-2">Event Type</label>
                                <select
                                    value={filterEventType}
                                    onChange={(e) => setFilterEventType(e.target.value)}
                                    className="w-full bg-white/10 text-white rounded-lg px-3 py-2.5 border border-white/20 focus:outline-none focus:border-amber-400/50 focus:ring-2 focus:ring-amber-400/20 text-sm transition-all"
                                >
                                    <option value="all" className="bg-slate-900">All Events</option>
                                    <option value="login_success" className="bg-slate-900">Login Success</option>
                                    <option value="login_failed" className="bg-slate-900">Login Failed</option>
                                    <option value="logout" className="bg-slate-900">Logout</option>
                                    <option value="emergency_access_success" className="bg-slate-900">Emergency Access</option>
                                    <option value="emergency_access_failed" className="bg-slate-900">Emergency Failed</option>
                                </select>
                            </div>

                            {/* Status */}
                            <div>
                                <label className="block text-xs font-medium text-white/60 uppercase tracking-wider mb-2">Status</label>
                                <select
                                    value={filterSuccess}
                                    onChange={(e) => setFilterSuccess(e.target.value)}
                                    className="w-full bg-white/10 text-white rounded-lg px-3 py-2.5 border border-white/20 focus:outline-none focus:border-amber-400/50 focus:ring-2 focus:ring-amber-400/20 text-sm transition-all"
                                >
                                    <option value="all" className="bg-slate-900">All</option>
                                    <option value="true" className="bg-slate-900">Success Only</option>
                                    <option value="false" className="bg-slate-900">Failures Only</option>
                                </select>
                            </div>

                            {/* Username Search */}
                            <div>
                                <label className="block text-xs font-medium text-white/60 uppercase tracking-wider mb-2">Username</label>
                                <div className="relative">
                                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
                                    <input
                                        type="text"
                                        value={filterUsername}
                                        onChange={(e) => setFilterUsername(e.target.value)}
                                        onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                                        placeholder="Search user..."
                                        className="w-full bg-white/10 text-white rounded-lg pl-10 pr-3 py-2.5 border border-white/20 focus:outline-none focus:border-amber-400/50 focus:ring-2 focus:ring-amber-400/20 placeholder-white/30 text-sm transition-all"
                                    />
                                </div>
                            </div>

                            {/* Page Size */}
                            <div>
                                <label className="block text-xs font-medium text-white/60 uppercase tracking-wider mb-2">Per Page</label>
                                <select
                                    value={pageSize}
                                    onChange={(e) => setPageSize(parseInt(e.target.value))}
                                    className="w-full bg-white/10 text-white rounded-lg px-3 py-2.5 border border-white/20 focus:outline-none focus:border-amber-400/50 focus:ring-2 focus:ring-amber-400/20 text-sm transition-all"
                                >
                                    <option value="10" className="bg-slate-900">10</option>
                                    <option value="25" className="bg-slate-900">25</option>
                                    <option value="50" className="bg-slate-900">50</option>
                                    <option value="100" className="bg-slate-900">100</option>
                                </select>
                            </div>
                        </div>

                        <div className="flex gap-3 mt-5">
                            <button
                                onClick={handleSearch}
                                disabled={isLoading}
                                className="flex items-center gap-2 px-5 py-2.5 bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-black rounded-lg transition-all duration-200 disabled:opacity-50 text-sm font-semibold shadow-lg shadow-amber-500/25"
                            >
                                <Search className="w-4 h-4" />
                                Search
                            </button>

                            <button
                                onClick={fetchLogs}
                                disabled={isLoading}
                                className="flex items-center gap-2 px-4 py-2.5 bg-white/10 hover:bg-white/20 text-white rounded-lg transition-all duration-200 disabled:opacity-50 text-sm font-medium border border-white/10"
                            >
                                <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                                Refresh
                            </button>

                            <button
                                onClick={handleExport}
                                className="flex items-center gap-2 px-4 py-2.5 bg-white/10 hover:bg-white/20 text-white rounded-lg transition-all duration-200 text-sm font-medium border border-white/10"
                            >
                                <Download className="w-4 h-4" />
                                Export CSV
                            </button>
                        </div>
                    </div>
                </div>

                {/* Audit Logs Table - Premium Glass */}
                <div className="relative bg-gradient-to-br from-white/10 to-white/5 backdrop-blur-xl border border-white/10 rounded-2xl overflow-hidden">
                    {error && (
                        <div className="p-4 bg-red-500/20 border-b border-red-500/30 flex items-start gap-3">
                            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                            <div>
                                <div className="text-red-400 font-medium text-sm">Error</div>
                                <div className="text-white/80 text-sm mt-1">{error}</div>
                            </div>
                        </div>
                    )}

                    {isLoading ? (
                        <div className="p-16 text-center">
                            <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-4 text-amber-400" />
                            <div className="text-white/60">Loading audit logs...</div>
                        </div>
                    ) : logs.length === 0 ? (
                        <div className="p-16 text-center text-white/60">
                            No audit logs found for the selected filters.
                        </div>
                    ) : (
                        <>
                            <div className="overflow-x-auto">
                                <table className="w-full">
                                    <thead>
                                        <tr className="bg-white/5 border-b border-white/10">
                                            <th className="text-left p-4 text-xs font-semibold text-white/60 uppercase tracking-wider">Event</th>
                                            <th className="text-left p-4 text-xs font-semibold text-white/60 uppercase tracking-wider">User</th>
                                            <th className="text-left p-4 text-xs font-semibold text-white/60 uppercase tracking-wider">IP Address</th>
                                            <th className="text-left p-4 text-xs font-semibold text-white/60 uppercase tracking-wider">Timestamp</th>
                                            <th className="text-left p-4 text-xs font-semibold text-white/60 uppercase tracking-wider">Details</th>
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
                                                    <div className="flex items-center gap-3">
                                                        <div className={`p-2 rounded-lg ${log.success
                                                                ? 'bg-emerald-500/20'
                                                                : 'bg-red-500/20'
                                                            }`}>
                                                            {getEventIcon(log.event_type, log.success)}
                                                        </div>
                                                        <span className={`text-sm font-medium ${log.success ? 'text-white' : 'text-red-400'}`}>
                                                            {getEventLabel(log.event_type)}
                                                        </span>
                                                    </div>
                                                </td>
                                                <td className="p-4">
                                                    <div className="flex items-center gap-2">
                                                        <User className="w-4 h-4 text-white/40" />
                                                        <span className="text-white/80 text-sm">{log.username || 'Unknown'}</span>
                                                    </div>
                                                </td>
                                                <td className="p-4">
                                                    <div className="flex items-center gap-2">
                                                        <MapPin className="w-4 h-4 text-white/40" />
                                                        <span className="text-white/60 font-mono text-xs bg-white/10 px-2 py-1 rounded">
                                                            {log.ip_address || '-'}
                                                        </span>
                                                    </div>
                                                </td>
                                                <td className="p-4">
                                                    <div className="flex items-center gap-2 text-white/60 text-sm">
                                                        <Clock className="w-4 h-4 text-white/40" />
                                                        {formatTimestamp(log.timestamp)}
                                                    </div>
                                                </td>
                                                <td className="p-4">
                                                    {log.failure_reason ? (
                                                        <span className="text-red-400 text-sm bg-red-500/10 px-2 py-1 rounded">{log.failure_reason}</span>
                                                    ) : log.details?.mfa_type ? (
                                                        <span className="text-emerald-400 text-sm">MFA: {log.details.mfa_type}</span>
                                                    ) : (
                                                        <span className="text-white/40 text-sm">-</span>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            {/* Pagination Controls - Premium */}
                            <div className="flex items-center justify-between p-4 bg-white/5 border-t border-white/10">
                                <div className="text-sm text-white/60">
                                    Showing <span className="text-white font-medium">{((currentPage - 1) * pageSize) + 1}</span> - <span className="text-white font-medium">{Math.min(currentPage * pageSize, totalCount)}</span> of <span className="text-white font-medium">{totalCount.toLocaleString()}</span> entries
                                </div>

                                <div className="flex items-center gap-2">
                                    <button
                                        onClick={() => setCurrentPage(1)}
                                        disabled={currentPage === 1}
                                        className="px-3 py-2 text-sm bg-white/10 hover:bg-white/20 text-white rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed font-medium"
                                    >
                                        First
                                    </button>
                                    <button
                                        onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                        disabled={currentPage === 1}
                                        className="p-2 bg-white/10 hover:bg-white/20 text-white rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                                    >
                                        <ChevronLeft className="w-4 h-4" />
                                    </button>

                                    <div className="flex items-center gap-2 px-3">
                                        <span className="text-white/60 text-sm">Page</span>
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
                                            className="w-14 bg-white/10 text-white text-center rounded-lg px-2 py-1.5 border border-white/20 focus:outline-none focus:border-amber-400/50 text-sm font-medium"
                                        />
                                        <span className="text-white/60 text-sm">of <span className="text-white font-medium">{totalPages}</span></span>
                                    </div>

                                    <button
                                        onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                        disabled={currentPage === totalPages}
                                        className="p-2 bg-white/10 hover:bg-white/20 text-white rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                                    >
                                        <ChevronRight className="w-4 h-4" />
                                    </button>
                                    <button
                                        onClick={() => setCurrentPage(totalPages)}
                                        disabled={currentPage === totalPages}
                                        className="px-3 py-2 text-sm bg-white/10 hover:bg-white/20 text-white rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed font-medium"
                                    >
                                        Last
                                    </button>
                                </div>
                            </div>
                        </>
                    )}
                </div>

                {/* Compliance Note - Premium */}
                <div className="relative bg-gradient-to-r from-blue-500/10 to-purple-500/10 backdrop-blur-sm border border-blue-500/20 p-5 rounded-2xl">
                    <div className="absolute inset-0 bg-gradient-to-r from-blue-500/5 to-transparent rounded-2xl" />
                    <div className="relative flex items-start gap-4">
                        <div className="p-2.5 bg-blue-500/20 rounded-xl">
                            <Shield className="w-5 h-5 text-blue-400" />
                        </div>
                        <div>
                            <div className="text-blue-300 font-semibold">Government Compliance (NIST 800-53)</div>
                            <div className="text-white/60 text-sm mt-1 leading-relaxed">
                                All authentication events are cryptographically logged with tamper-detection hash chaining (AU-9).
                                Logs are immutable and retained per state retention policy. Use Export for compliance audits.
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </AccordionSection>
    );
}

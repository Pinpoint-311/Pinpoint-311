import { useState, useEffect, useCallback } from 'react';
import { Shield, Download, RefreshCw, AlertCircle, CheckCircle, XCircle, User, Clock, MapPin, ChevronLeft, ChevronRight, Calendar, Search, Filter } from 'lucide-react';
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
            // Don't change dates for custom
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

            // Build query parameters
            const params = new URLSearchParams();
            if (filterEventType !== 'all') params.append('event_type', filterEventType);
            if (filterSuccess !== 'all') params.append('success', filterSuccess);
            if (filterUsername) params.append('username', filterUsername);
            if (startDate) params.append('start_date', startDate);
            if (endDate) params.append('end_date', endDate);
            params.append('page', currentPage.toString());
            params.append('page_size', pageSize.toString());

            const response = await fetch(`/api/audit/logs?${params}`, {
                headers: {
                    'Authorization': `Bearer ${token}`,
                },
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            setLogs(data.logs || []);
            setTotalCount(data.total_count || data.logs?.length || 0);

            // Fetch stats
            const statsResponse = await fetch('/api/audit/stats', {
                headers: {
                    'Authorization': `Bearer ${token}`,
                },
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

    // Reset to page 1 when filters change
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
                headers: {
                    'Authorization': `Bearer ${token}`,
                },
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
        if (!success) return <XCircle className="w-4 h-4 text-red-500" />;
        if (eventType.includes('login')) return <CheckCircle className="w-4 h-4 text-green-600" />;
        if (eventType.includes('logout')) return <User className="w-4 h-4 text-blue-600" />;
        return <Shield className="w-4 h-4 text-slate-600" />;
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
        };
        return labels[eventType] || eventType;
    };

    const formatTimestamp = (timestamp: string) => {
        return new Date(timestamp).toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    };

    return (
        <AccordionSection
            title="Audit Logs"
            subtitle="Authentication event logging (NIST 800-53 compliant)"
            icon={Shield}
            iconClassName="text-slate-600"
            badge={
                stats ? (
                    <span className="px-2 py-0.5 text-xs font-medium bg-slate-200 text-slate-700 rounded">
                        {stats.total_events.toLocaleString()} Events
                    </span>
                ) : undefined
            }
        >
            <div className="space-y-6">
                {/* Statistics Cards - Professional Government Style */}
                {stats && (
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
                        <div className="bg-slate-800/80 border border-slate-700 p-4 rounded-lg">
                            <div className="text-slate-400 text-xs uppercase tracking-wide font-medium">Total Events</div>
                            <div className="text-2xl font-bold text-white mt-1">{stats.total_events.toLocaleString()}</div>
                        </div>
                        <div className="bg-slate-800/80 border border-green-800/50 p-4 rounded-lg">
                            <div className="text-slate-400 text-xs uppercase tracking-wide font-medium">Successful</div>
                            <div className="text-2xl font-bold text-green-400 mt-1">{stats.successful_logins.toLocaleString()}</div>
                        </div>
                        <div className="bg-slate-800/80 border border-red-800/50 p-4 rounded-lg">
                            <div className="text-slate-400 text-xs uppercase tracking-wide font-medium">Failed</div>
                            <div className="text-2xl font-bold text-red-400 mt-1">{stats.failed_logins.toLocaleString()}</div>
                        </div>
                        <div className="bg-slate-800/80 border border-blue-800/50 p-4 rounded-lg">
                            <div className="text-slate-400 text-xs uppercase tracking-wide font-medium">Logouts</div>
                            <div className="text-2xl font-bold text-blue-400 mt-1">{stats.total_logouts.toLocaleString()}</div>
                        </div>
                        <div className="bg-slate-800/80 border border-purple-800/50 p-4 rounded-lg">
                            <div className="text-slate-400 text-xs uppercase tracking-wide font-medium">Unique Users</div>
                            <div className="text-2xl font-bold text-purple-400 mt-1">{stats.unique_users.toLocaleString()}</div>
                        </div>
                        <div className="bg-slate-800/80 border border-amber-800/50 p-4 rounded-lg">
                            <div className="text-slate-400 text-xs uppercase tracking-wide font-medium">Recent Failures</div>
                            <div className="text-2xl font-bold text-amber-400 mt-1">{stats.recent_failures.toLocaleString()}</div>
                        </div>
                    </div>
                )}

                {/* Filters - Professional Style */}
                <div className="bg-slate-800/60 border border-slate-700 p-5 rounded-lg">
                    <div className="flex items-center gap-2 mb-4">
                        <Filter className="w-4 h-4 text-slate-400" />
                        <span className="text-sm font-medium text-slate-300 uppercase tracking-wide">Search & Filter</span>
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
                                className={`px-3 py-1.5 text-sm rounded-md transition-colors ${quickRange === range.value
                                        ? 'bg-blue-600 text-white'
                                        : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                                    }`}
                            >
                                {range.label}
                            </button>
                        ))}
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-6 gap-4">
                        {/* Start Date */}
                        <div>
                            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wide mb-1.5">Start Date</label>
                            <div className="relative">
                                <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                                <input
                                    type="date"
                                    value={startDate}
                                    onChange={(e) => {
                                        setStartDate(e.target.value);
                                        setQuickRange('custom');
                                    }}
                                    className="w-full bg-slate-900 text-white rounded-md pl-10 pr-3 py-2 border border-slate-600 focus:outline-none focus:border-blue-500 text-sm"
                                />
                            </div>
                        </div>

                        {/* End Date */}
                        <div>
                            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wide mb-1.5">End Date</label>
                            <div className="relative">
                                <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                                <input
                                    type="date"
                                    value={endDate}
                                    onChange={(e) => {
                                        setEndDate(e.target.value);
                                        setQuickRange('custom');
                                    }}
                                    className="w-full bg-slate-900 text-white rounded-md pl-10 pr-3 py-2 border border-slate-600 focus:outline-none focus:border-blue-500 text-sm"
                                />
                            </div>
                        </div>

                        {/* Event Type */}
                        <div>
                            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wide mb-1.5">Event Type</label>
                            <select
                                value={filterEventType}
                                onChange={(e) => setFilterEventType(e.target.value)}
                                className="w-full bg-slate-900 text-white rounded-md px-3 py-2 border border-slate-600 focus:outline-none focus:border-blue-500 text-sm"
                            >
                                <option value="all">All Events</option>
                                <option value="login_success">Login Success</option>
                                <option value="login_failed">Login Failed</option>
                                <option value="logout">Logout</option>
                                <option value="role_changed">Role Changed</option>
                                <option value="mfa_enrolled">MFA Enrolled</option>
                                <option value="password_changed">Password Changed</option>
                            </select>
                        </div>

                        {/* Status */}
                        <div>
                            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wide mb-1.5">Status</label>
                            <select
                                value={filterSuccess}
                                onChange={(e) => setFilterSuccess(e.target.value)}
                                className="w-full bg-slate-900 text-white rounded-md px-3 py-2 border border-slate-600 focus:outline-none focus:border-blue-500 text-sm"
                            >
                                <option value="all">All</option>
                                <option value="true">Success Only</option>
                                <option value="false">Failures Only</option>
                            </select>
                        </div>

                        {/* Username Search */}
                        <div>
                            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wide mb-1.5">Username</label>
                            <div className="relative">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                                <input
                                    type="text"
                                    value={filterUsername}
                                    onChange={(e) => setFilterUsername(e.target.value)}
                                    onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                                    placeholder="Search user..."
                                    className="w-full bg-slate-900 text-white rounded-md pl-10 pr-3 py-2 border border-slate-600 focus:outline-none focus:border-blue-500 placeholder-slate-500 text-sm"
                                />
                            </div>
                        </div>

                        {/* Page Size */}
                        <div>
                            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wide mb-1.5">Per Page</label>
                            <select
                                value={pageSize}
                                onChange={(e) => setPageSize(parseInt(e.target.value))}
                                className="w-full bg-slate-900 text-white rounded-md px-3 py-2 border border-slate-600 focus:outline-none focus:border-blue-500 text-sm"
                            >
                                <option value="10">10</option>
                                <option value="25">25</option>
                                <option value="50">50</option>
                                <option value="100">100</option>
                            </select>
                        </div>
                    </div>

                    <div className="flex gap-3 mt-4">
                        <button
                            onClick={handleSearch}
                            disabled={isLoading}
                            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-md transition-colors disabled:opacity-50 text-sm font-medium"
                        >
                            <Search className="w-4 h-4" />
                            Search
                        </button>

                        <button
                            onClick={fetchLogs}
                            disabled={isLoading}
                            className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-md transition-colors disabled:opacity-50 text-sm"
                        >
                            <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                            Refresh
                        </button>

                        <button
                            onClick={handleExport}
                            className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-md transition-colors text-sm"
                        >
                            <Download className="w-4 h-4" />
                            Export CSV
                        </button>
                    </div>
                </div>

                {/* Audit Logs Table - Professional Style */}
                <div className="bg-slate-800/60 border border-slate-700 rounded-lg overflow-hidden">
                    {error && (
                        <div className="p-4 bg-red-900/30 border-b border-red-800 flex items-start gap-3">
                            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                            <div>
                                <div className="text-red-400 font-medium text-sm">Error</div>
                                <div className="text-slate-300 text-sm mt-1">{error}</div>
                            </div>
                        </div>
                    )}

                    {isLoading ? (
                        <div className="p-12 text-center text-slate-400">
                            <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-3" />
                            Loading audit logs...
                        </div>
                    ) : logs.length === 0 ? (
                        <div className="p-12 text-center text-slate-400">
                            No audit logs found for the selected filters.
                        </div>
                    ) : (
                        <>
                            <div className="overflow-x-auto">
                                <table className="w-full">
                                    <thead>
                                        <tr className="bg-slate-900/50 border-b border-slate-700">
                                            <th className="text-left p-4 text-xs font-medium text-slate-400 uppercase tracking-wide">Event</th>
                                            <th className="text-left p-4 text-xs font-medium text-slate-400 uppercase tracking-wide">User</th>
                                            <th className="text-left p-4 text-xs font-medium text-slate-400 uppercase tracking-wide">IP Address</th>
                                            <th className="text-left p-4 text-xs font-medium text-slate-400 uppercase tracking-wide">Timestamp</th>
                                            <th className="text-left p-4 text-xs font-medium text-slate-400 uppercase tracking-wide">Details</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {logs.map((log, index) => (
                                            <tr
                                                key={log.id}
                                                className={`border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors ${index % 2 === 0 ? 'bg-slate-800/30' : ''
                                                    }`}
                                            >
                                                <td className="p-4">
                                                    <div className="flex items-center gap-2">
                                                        {getEventIcon(log.event_type, log.success)}
                                                        <span className={`text-sm font-medium ${log.success ? 'text-white' : 'text-red-400'}`}>
                                                            {getEventLabel(log.event_type)}
                                                        </span>
                                                    </div>
                                                </td>
                                                <td className="p-4">
                                                    <div className="flex items-center gap-2 text-slate-300 text-sm">
                                                        <User className="w-4 h-4 text-slate-500" />
                                                        {log.username || 'Unknown'}
                                                    </div>
                                                </td>
                                                <td className="p-4">
                                                    <div className="flex items-center gap-2 text-slate-400 font-mono text-xs">
                                                        <MapPin className="w-4 h-4 text-slate-500" />
                                                        {log.ip_address || '-'}
                                                    </div>
                                                </td>
                                                <td className="p-4">
                                                    <div className="flex items-center gap-2 text-slate-400 text-sm">
                                                        <Clock className="w-4 h-4 text-slate-500" />
                                                        {formatTimestamp(log.timestamp)}
                                                    </div>
                                                </td>
                                                <td className="p-4">
                                                    {log.failure_reason ? (
                                                        <div className="text-red-400 text-sm">{log.failure_reason}</div>
                                                    ) : log.details?.mfa_type ? (
                                                        <div className="text-green-400 text-sm">MFA: {log.details.mfa_type}</div>
                                                    ) : (
                                                        <div className="text-slate-500 text-sm">-</div>
                                                    )}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>

                            {/* Pagination Controls */}
                            <div className="flex items-center justify-between p-4 bg-slate-900/50 border-t border-slate-700">
                                <div className="text-sm text-slate-400">
                                    Showing {((currentPage - 1) * pageSize) + 1} - {Math.min(currentPage * pageSize, totalCount)} of {totalCount.toLocaleString()} entries
                                </div>

                                <div className="flex items-center gap-2">
                                    <button
                                        onClick={() => setCurrentPage(1)}
                                        disabled={currentPage === 1}
                                        className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        First
                                    </button>
                                    <button
                                        onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                        disabled={currentPage === 1}
                                        className="p-1.5 bg-slate-700 hover:bg-slate-600 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        <ChevronLeft className="w-4 h-4" />
                                    </button>

                                    <div className="flex items-center gap-1 px-3">
                                        <span className="text-slate-400 text-sm">Page</span>
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
                                            className="w-16 bg-slate-900 text-white text-center rounded-md px-2 py-1 border border-slate-600 focus:outline-none focus:border-blue-500 text-sm"
                                        />
                                        <span className="text-slate-400 text-sm">of {totalPages}</span>
                                    </div>

                                    <button
                                        onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                        disabled={currentPage === totalPages}
                                        className="p-1.5 bg-slate-700 hover:bg-slate-600 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        <ChevronRight className="w-4 h-4" />
                                    </button>
                                    <button
                                        onClick={() => setCurrentPage(totalPages)}
                                        disabled={currentPage === totalPages}
                                        className="px-3 py-1.5 text-sm bg-slate-700 hover:bg-slate-600 text-white rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        Last
                                    </button>
                                </div>
                            </div>
                        </>
                    )}
                </div>

                {/* Compliance Note - Professional */}
                <div className="bg-slate-800/60 border border-blue-800/50 p-4 rounded-lg">
                    <div className="flex items-start gap-3">
                        <Shield className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
                        <div>
                            <div className="text-blue-400 font-medium text-sm">Government Compliance (NIST 800-53)</div>
                            <div className="text-slate-400 text-sm mt-1">
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

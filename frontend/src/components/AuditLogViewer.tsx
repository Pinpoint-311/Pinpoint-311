import { useState, useEffect, useCallback } from 'react';
import { Shield, Download, RefreshCw, AlertCircle, CheckCircle, XCircle, User, Clock, ChevronLeft, ChevronRight, Search, Sparkles } from 'lucide-react';
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
            <div className="space-y-4">
                {/* Statistics Row */}
                {stats && (
                    <div className="grid grid-cols-5 gap-4 text-sm">
                        <div className="flex items-baseline gap-2">
                            <span className="text-white/50">Total</span>
                            <span className="text-lg font-medium text-white">{stats.total_events}</span>
                        </div>
                        <div className="flex items-baseline gap-2">
                            <span className="text-white/50">Success</span>
                            <span className="text-lg font-medium text-emerald-400">{stats.successful_logins}</span>
                        </div>
                        <div className="flex items-baseline gap-2">
                            <span className="text-white/50">Failed</span>
                            <span className="text-lg font-medium text-red-400">{stats.failed_logins}</span>
                        </div>
                        <div className="flex items-baseline gap-2">
                            <span className="text-white/50">Logouts</span>
                            <span className="text-lg font-medium text-blue-400">{stats.total_logouts}</span>
                        </div>
                        <div className="flex items-baseline gap-2">
                            <span className="text-white/50">Users</span>
                            <span className="text-lg font-medium text-purple-400">{stats.unique_users}</span>
                        </div>
                    </div>
                )}

                {/* Filters Row */}
                <div className="grid grid-cols-6 gap-3 items-end">
                    <div>
                        <label className="block text-xs text-white/50 mb-1.5">Time Range</label>
                        <select
                            value={quickRange}
                            onChange={(e) => applyQuickRange(e.target.value)}
                            className="w-full h-10 bg-white/10 text-white text-sm rounded-lg px-3 border border-white/15 focus:outline-none focus:border-indigo-500/50"
                        >
                            <option value="today" className="bg-slate-800">Today</option>
                            <option value="7" className="bg-slate-800">Last 7 Days</option>
                            <option value="30" className="bg-slate-800">Last 30 Days</option>
                            <option value="90" className="bg-slate-800">Last 90 Days</option>
                            <option value="365" className="bg-slate-800">Last Year</option>
                            <option value="custom" className="bg-slate-800">Custom</option>
                        </select>
                    </div>

                    <div>
                        <label className="block text-xs text-white/50 mb-1.5">Event Type</label>
                        <select
                            value={filterEventType}
                            onChange={(e) => setFilterEventType(e.target.value)}
                            className="w-full h-10 bg-white/10 text-white text-sm rounded-lg px-3 border border-white/15 focus:outline-none focus:border-indigo-500/50"
                        >
                            <option value="all" className="bg-slate-800">All Events</option>
                            <option value="login_success" className="bg-slate-800">Login Success</option>
                            <option value="login_failed" className="bg-slate-800">Login Failed</option>
                            <option value="logout" className="bg-slate-800">Logout</option>
                            <option value="emergency_access_success" className="bg-slate-800">Emergency</option>
                        </select>
                    </div>

                    <div>
                        <label className="block text-xs text-white/50 mb-1.5">Status</label>
                        <select
                            value={filterSuccess}
                            onChange={(e) => setFilterSuccess(e.target.value)}
                            className="w-full h-10 bg-white/10 text-white text-sm rounded-lg px-3 border border-white/15 focus:outline-none focus:border-indigo-500/50"
                        >
                            <option value="all" className="bg-slate-800">All</option>
                            <option value="true" className="bg-slate-800">Success</option>
                            <option value="false" className="bg-slate-800">Failed</option>
                        </select>
                    </div>

                    <div>
                        <label className="block text-xs text-white/50 mb-1.5">Username</label>
                        <div className="relative">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30" />
                            <input
                                type="text"
                                value={filterUsername}
                                onChange={(e) => setFilterUsername(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                                placeholder="Search..."
                                className="w-full h-10 bg-white/10 text-white text-sm rounded-lg pl-9 pr-3 border border-white/15 focus:outline-none focus:border-indigo-500/50 placeholder-white/30"
                            />
                        </div>
                    </div>

                    <button
                        onClick={fetchLogs}
                        disabled={isLoading}
                        className="h-10 flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
                    >
                        <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                        Refresh
                    </button>

                    <button
                        onClick={handleExport}
                        className="h-10 flex items-center justify-center gap-2 bg-white/10 hover:bg-white/15 text-white text-sm rounded-lg transition-colors"
                    >
                        <Download className="w-4 h-4" />
                        Export
                    </button>
                </div>

                {/* Custom Date Range (only when custom selected) */}
                {quickRange === 'custom' && (
                    <div className="grid grid-cols-6 gap-3">
                        <div>
                            <label className="block text-xs text-white/50 mb-1.5">From</label>
                            <input
                                type="date"
                                value={startDate}
                                onChange={(e) => setStartDate(e.target.value)}
                                className="w-full h-10 bg-white/10 text-white text-sm rounded-lg px-3 border border-white/15 focus:outline-none focus:border-indigo-500/50"
                            />
                        </div>
                        <div>
                            <label className="block text-xs text-white/50 mb-1.5">To</label>
                            <input
                                type="date"
                                value={endDate}
                                onChange={(e) => setEndDate(e.target.value)}
                                className="w-full h-10 bg-white/10 text-white text-sm rounded-lg px-3 border border-white/15 focus:outline-none focus:border-indigo-500/50"
                            />
                        </div>
                    </div>
                )}

                {/* Table */}
                <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
                    {error && (
                        <div className="p-4 bg-red-500/10 border-b border-red-500/20 flex items-center gap-3">
                            <AlertCircle className="w-5 h-5 text-red-400" />
                            <span className="text-red-400 text-sm">{error}</span>
                        </div>
                    )}

                    {isLoading ? (
                        <div className="p-12 text-center">
                            <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-3 text-indigo-400" />
                            <div className="text-white/50 text-sm">Loading...</div>
                        </div>
                    ) : logs.length === 0 ? (
                        <div className="p-12 text-center text-white/50 text-sm">
                            No logs found for selected filters.
                        </div>
                    ) : (
                        <>
                            <table className="w-full">
                                <thead>
                                    <tr className="border-b border-white/10 text-left">
                                        <th className="p-4 text-xs font-medium text-white/50 uppercase">Event</th>
                                        <th className="p-4 text-xs font-medium text-white/50 uppercase">User</th>
                                        <th className="p-4 text-xs font-medium text-white/50 uppercase">IP Address</th>
                                        <th className="p-4 text-xs font-medium text-white/50 uppercase">Timestamp</th>
                                        <th className="p-4 text-xs font-medium text-white/50 uppercase">Details</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {logs.map((log, index) => (
                                        <tr
                                            key={log.id}
                                            className={`border-b border-white/5 ${index % 2 === 0 ? 'bg-white/[0.02]' : ''}`}
                                        >
                                            <td className="p-4">
                                                <div className="flex items-center gap-2">
                                                    {getEventIcon(log.event_type, log.success)}
                                                    <span className={`text-sm ${log.success ? 'text-white' : 'text-red-400'}`}>
                                                        {getEventLabel(log.event_type)}
                                                    </span>
                                                </div>
                                            </td>
                                            <td className="p-4 text-sm text-white/80">{log.username || 'Unknown'}</td>
                                            <td className="p-4 text-sm text-white/50 font-mono">{log.ip_address || '-'}</td>
                                            <td className="p-4 text-sm text-white/50">{formatTimestamp(log.timestamp)}</td>
                                            <td className="p-4 text-sm">
                                                {log.failure_reason ? (
                                                    <span className="text-red-400">{log.failure_reason}</span>
                                                ) : (
                                                    <span className="text-white/30">-</span>
                                                )}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>

                            {/* Pagination */}
                            <div className="flex items-center justify-between p-4 border-t border-white/10 text-sm">
                                <div className="flex items-center gap-2 text-white/50">
                                    <span>Show</span>
                                    <select
                                        value={pageSize}
                                        onChange={(e) => setPageSize(parseInt(e.target.value))}
                                        className="h-8 bg-white/10 text-white rounded px-2 border border-white/15"
                                    >
                                        <option value="10" className="bg-slate-800">10</option>
                                        <option value="25" className="bg-slate-800">25</option>
                                        <option value="50" className="bg-slate-800">50</option>
                                    </select>
                                    <span>of {totalCount.toLocaleString()}</span>
                                </div>

                                <div className="flex items-center gap-2 text-white/70">
                                    <button
                                        onClick={() => setCurrentPage(1)}
                                        disabled={currentPage === 1}
                                        className="px-2 py-1 hover:text-white disabled:opacity-30"
                                    >
                                        First
                                    </button>
                                    <button
                                        onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                                        disabled={currentPage === 1}
                                        className="p-1 hover:text-white disabled:opacity-30"
                                    >
                                        <ChevronLeft className="w-4 h-4" />
                                    </button>
                                    <span className="px-2">
                                        Page <span className="text-white">{currentPage}</span> of {totalPages}
                                    </span>
                                    <button
                                        onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                                        disabled={currentPage === totalPages}
                                        className="p-1 hover:text-white disabled:opacity-30"
                                    >
                                        <ChevronRight className="w-4 h-4" />
                                    </button>
                                    <button
                                        onClick={() => setCurrentPage(totalPages)}
                                        disabled={currentPage === totalPages}
                                        className="px-2 py-1 hover:text-white disabled:opacity-30"
                                    >
                                        Last
                                    </button>
                                </div>
                            </div>
                        </>
                    )}
                </div>

                {/* Compliance Note */}
                <p className="text-xs text-white/40 flex items-center gap-2">
                    <Shield className="w-3.5 h-3.5" />
                    NIST 800-53 compliant · Tamper-detection hash chaining (AU-9) · Immutable retention
                </p>
            </div>
        </AccordionSection>
    );
}

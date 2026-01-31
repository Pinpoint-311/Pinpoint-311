import { useState, useEffect } from 'react';
import { Shield, Download, RefreshCw, AlertCircle, CheckCircle, XCircle, User, Clock, MapPin } from 'lucide-react';

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

    // Filters
    const [filterEventType, setFilterEventType] = useState('all');
    const [filterSuccess, setFilterSuccess] = useState('all');
    const [filterUsername, setFilterUsername] = useState('');
    const [filterDays, setFilterDays] = useState('7');

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
            params.append('days', filterDays);

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
        fetchLogs();
    }, [filterEventType, filterSuccess, filterDays]);

    const handleExport = async () => {
        try {
            const token = localStorage.getItem('token');
            const params = new URLSearchParams();
            if (filterEventType !== 'all') params.append('event_type', filterEventType);
            if (filterSuccess !== 'all') params.append('success', filterSuccess);
            if (filterUsername) params.append('username', filterUsername);
            params.append('days', filterDays);

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

    const getEventIcon = (eventType: string, success: boolean) => {
        if (!success) return <XCircle className="w-4 h-4 text-red-400" />;
        if (eventType.includes('login')) return <CheckCircle className="w-4 h-4 text-green-400" />;
        if (eventType.includes('logout')) return <User className="w-4 h-4 text-blue-400" />;
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
        <div className="space-y-6">
            {/* Header */}
            <div>
                <h1 className="text-2xl font-bold text-white flex items-center gap-2">
                    <Shield className="w-7 h-7" />
                    Audit Logs
                </h1>
                <p className="text-white/60 mt-2">
                    Government-compliant authentication event logging (NIST 800-53)
                </p>
            </div>

            {/* Statistics Cards */}
            {stats && (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
                    <div className="glassmorphism p-4 rounded-xl">
                        <div className="text-white/60 text-sm">Total Events</div>
                        <div className="text-2xl font-bold text-white mt-1">{stats.total_events}</div>
                    </div>
                    <div className="glassmorphism p-4 rounded-xl">
                        <div className="text-white/60 text-sm">Successful Logins</div>
                        <div className="text-2xl font-bold text-green-400 mt-1">{stats.successful_logins}</div>
                    </div>
                    <div className="glassmorphism p-4 rounded-xl">
                        <div className="text-white/60 text-sm">Failed Logins</div>
                        <div className="text-2xl font-bold text-red-400 mt-1">{stats.failed_logins}</div>
                    </div>
                    <div className="glassmorphism p-4 rounded-xl">
                        <div className="text-white/60 text-sm">Logouts</div>
                        <div className="text-2xl font-bold text-blue-400 mt-1">{stats.total_logouts}</div>
                    </div>
                    <div className="glassmorphism p-4 rounded-xl">
                        <div className="text-white/60 text-sm">Unique Users</div>
                        <div className="text-2xl font-bold text-purple-400 mt-1">{stats.unique_users}</div>
                    </div>
                    <div className="glassmorphism p-4 rounded-xl">
                        <div className="text-white/60 text-sm">Recent Failures</div>
                        <div className="text-2xl font-bold text-yellow-400 mt-1">{stats.recent_failures}</div>
                    </div>
                </div>
            )}

            {/* Filters */}
            <div className="glassmorphism p-6 rounded-xl">
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                    <div>
                        <label className="block text-sm font-medium text-white/80 mb-2">Event Type</label>
                        <select
                            value={filterEventType}
                            onChange={(e) => setFilterEventType(e.target.value)}
                            className="w-full bg-white/10 text-white rounded-lg px-4 py-2 border border-white/20 focus:outline-none focus:border-white/40"
                        >
                            <option value="all">All Events</option>
                            <option value="login_success">Login Success</option>
                            <option value="login_failed">Login Failed</option>
                            <option value="logout">Logout</option>
                            <option value="role_changed">Role Changed</option>
                        </select>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-white/80 mb-2">Status</label>
                        <select
                            value={filterSuccess}
                            onChange={(e) => setFilterSuccess(e.target.value)}
                            className="w-full bg-white/10 text-white rounded-lg px-4 py-2 border border-white/20 focus:outline-none focus:border-white/40"
                        >
                            <option value="all">All</option>
                            <option value="true">Success Only</option>
                            <option value="false">Failures Only</option>
                        </select>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-white/80 mb-2">Time Range</label>
                        <select
                            value={filterDays}
                            onChange={(e) => setFilterDays(e.target.value)}
                            className="w-full bg-white/10 text-white rounded-lg px-4 py-2 border border-white/20 focus:outline-none focus:border-white/40"
                        >
                            <option value="1">Last 24 hours</option>
                            <option value="7">Last 7 days</option>
                            <option value="30">Last 30 days</option>
                            <option value="90">Last 90 days</option>
                            <option value="365">Last year</option>
                        </select>
                    </div>

                    <div>
                        <label className="block text-sm font-medium text-white/80 mb-2">Username</label>
                        <input
                            type="text"
                            value={filterUsername}
                            onChange={(e) => setFilterUsername(e.target.value)}
                            placeholder="Filter by username..."
                            className="w-full bg-white/10 text-white rounded-lg px-4 py-2 border border-white/20 focus:outline-none focus:border-white/40 placeholder-white/40"
                        />
                    </div>
                </div>

                <div className="flex gap-3 mt-4">
                    <button
                        onClick={fetchLogs}
                        disabled={isLoading}
                        className="flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg transition-colors disabled:opacity-50"
                    >
                        <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
                        Refresh
                    </button>

                    <button
                        onClick={handleExport}
                        className="flex items-center gap-2 px-4 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg transition-colors"
                    >
                        <Download className="w-4 h-4" />
                        Export CSV
                    </button>
                </div>
            </div>

            {/* Audit Logs Table */}
            <div className="glassmorphism rounded-xl overflow-hidden">
                {error && (
                    <div className="p-4 bg-red-500/20 border border-red-500/30 rounded-lg flex items-start gap-3">
                        <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                        <div>
                            <div className="text-red-400 font-medium">Error</div>
                            <div className="text-white/80 text-sm mt-1">{error}</div>
                        </div>
                    </div>
                )}

                {isLoading ? (
                    <div className="p-12 text-center text-white/60">
                        <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-3" />
                        Loading audit logs...
                    </div>
                ) : logs.length === 0 ? (
                    <div className="p-12 text-center text-white/60">
                        No audit logs found for the selected filters.
                    </div>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full">
                            <thead>
                                <tr className="border-b border-white/10">
                                    <th className="text-left p-4 text-white/80 font-medium">Event</th>
                                    <th className="text-left p-4 text-white/80 font-medium">User</th>
                                    <th className="text-left p-4 text-white/80 font-medium">IP Address</th>
                                    <th className="text-left p-4 text-white/80 font-medium">Time</th>
                                    <th className="text-left p-4 text-white/80 font-medium">Details</th>
                                </tr>
                            </thead>
                            <tbody>
                                {logs.map((log) => (
                                    <tr key={log.id} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                                        <td className="p-4">
                                            <div className="flex items-center gap-2">
                                                {getEventIcon(log.event_type, log.success)}
                                                <span className="text-white">{getEventLabel(log.event_type)}</span>
                                            </div>
                                        </td>
                                        <td className="p-4">
                                            <div className="flex items-center gap-2 text-white/80">
                                                <User className="w-4 h-4" />
                                                {log.username || 'Unknown'}
                                            </div>
                                        </td>
                                        <td className="p-4">
                                            <div className="flex items-center gap-2 text-white/60 font-mono text-sm">
                                                <MapPin className="w-4 h-4" />
                                                {log.ip_address || '-'}
                                            </div>
                                        </td>
                                        <td className="p-4">
                                            <div className="flex items-center gap-2 text-white/60 text-sm">
                                                <Clock className="w-4 h-4" />
                                                {formatTimestamp(log.timestamp)}
                                            </div>
                                        </td>
                                        <td className="p-4">
                                            {log.failure_reason ? (
                                                <div className="text-red-400 text-sm">{log.failure_reason}</div>
                                            ) : log.details?.mfa_type ? (
                                                <div className="text-green-400 text-sm">MFA: {log.details.mfa_type}</div>
                                            ) : (
                                                <div className="text-white/40 text-sm">-</div>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            {/* Note about compliance */}
            <div className="glassmorphism p-4 rounded-xl border border-blue-500/30">
                <div className="flex items-start gap-3">
                    <Shield className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
                    <div>
                        <div className="text-blue-400 font-medium">Government Compliance</div>
                        <div className="text-white/80 text-sm mt-1">
                            All authentication events are logged with tamper-detection hash chaining (NIST 800-53 AU-9).
                            Logs are immutable and cannot be modified or deleted. Use the Export feature for compliance audits.
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

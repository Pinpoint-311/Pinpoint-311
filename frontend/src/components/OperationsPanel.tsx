import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Server, Database, RefreshCw, Play, Trash2, HardDrive, Clock,
    CheckCircle, XCircle, AlertCircle, Loader2, RotateCcw
} from 'lucide-react';
import { Card, Button } from './ui';
import api, { HealthDashboard, RunbookResult } from '../services/api';
import { useDialog } from './DialogProvider';

interface ServiceStatus {
    status: 'running' | 'stopped' | 'unknown';
    uptime?: string;
    error?: string;
}

const SERVICE_ICONS: Record<string, typeof Server> = {
    backend: Server,
    frontend: Server,
    db: Database,
    redis: HardDrive,
    caddy: Server,
};

export default function OperationsPanel() {
    const [health, setHealth] = useState<HealthDashboard | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [runbookLoading, setRunbookLoading] = useState<string | null>(null);
    const [lastAction, setLastAction] = useState<RunbookResult | null>(null);
    const dialog = useDialog();

    const fetchHealth = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const data = await api.getHealthDashboard();
            setHealth(data);
        } catch (err: any) {
            setError(err.message || 'Failed to fetch system status');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchHealth();
        // Refresh every 30 seconds
        const interval = setInterval(fetchHealth, 30000);
        return () => clearInterval(interval);
    }, []);

    const executeRunbook = async (action: string, label: string) => {
        const confirmed = await dialog.confirm({
            title: `Execute: ${label}`,
            message: `Are you sure you want to execute "${label}"?\n\nThis action will be logged and may affect system availability briefly.`,
            variant: action.includes('restart') ? 'warning' : 'info',
            confirmText: 'Execute',
        });

        if (!confirmed) return;

        setRunbookLoading(action);
        try {
            const result = await api.executeRunbook(action);
            setLastAction(result);
            // Refresh health after action
            setTimeout(fetchHealth, 2000);
        } catch (err: any) {
            setLastAction({
                action,
                executed_by: 'unknown',
                timestamp: new Date().toISOString(),
                status: 'error',
                details: { error: err.message },
            });
        } finally {
            setRunbookLoading(null);
        }
    };

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'running':
            case 'healthy':
                return <CheckCircle className="w-5 h-5 text-green-400" />;
            case 'stopped':
            case 'error':
                return <XCircle className="w-5 h-5 text-red-400" />;
            default:
                return <AlertCircle className="w-5 h-5 text-yellow-400" />;
        }
    };

    const getStatusBadge = (status: string) => {
        const colors: Record<string, string> = {
            running: 'bg-green-500/20 text-green-300 border-green-500/30',
            healthy: 'bg-green-500/20 text-green-300 border-green-500/30',
            stopped: 'bg-red-500/20 text-red-300 border-red-500/30',
            error: 'bg-red-500/20 text-red-300 border-red-500/30',
            unknown: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
            not_configured: 'bg-gray-500/20 text-gray-300 border-gray-500/30',
        };
        return colors[status] || colors.unknown;
    };

    if (error) {
        return (
            <Card className="bg-red-500/10 border-red-500/20">
                <div className="flex items-center gap-3">
                    <XCircle className="w-6 h-6 text-red-400" />
                    <div className="flex-1">
                        <h3 className="text-lg font-semibold text-red-300">Error Loading Operations Dashboard</h3>
                        <p className="text-red-200/80 mt-1">{error}</p>
                    </div>
                    <Button onClick={fetchHealth} disabled={isLoading}>
                        <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
                        Retry
                    </Button>
                </div>
            </Card>
        );
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-xl font-bold text-white flex items-center gap-2">
                        <Server className="w-6 h-6 text-blue-400" />
                        Operations Dashboard
                    </h2>
                    <p className="text-gray-400 text-sm mt-1">
                        Monitor infrastructure and execute emergency operations
                    </p>
                </div>
                <Button onClick={fetchHealth} disabled={isLoading} variant="secondary">
                    <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
                    Refresh
                </Button>
            </div>

            {/* Overall Status Banner */}
            {health && (
                <Card className={`
                    ${health.overall_status === 'healthy' ? 'bg-green-500/10 border-green-500/30' : ''}
                    ${health.overall_status === 'degraded' ? 'bg-yellow-500/10 border-yellow-500/30' : ''}
                    ${health.overall_status === 'critical' ? 'bg-red-500/10 border-red-500/30' : ''}
                `}>
                    <div className="flex items-center gap-4">
                        {getStatusIcon(health.overall_status)}
                        <div className="flex-1">
                            <span className="text-lg font-semibold text-white capitalize">
                                System {health.overall_status}
                            </span>
                            <span className="text-gray-400 text-sm ml-3">
                                Last checked: {new Date(health.timestamp).toLocaleTimeString()}
                            </span>
                        </div>
                    </div>
                </Card>
            )}

            {/* Services Grid */}
            {health && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {Object.entries(health.services).map(([name, service]) => {
                        const Icon = SERVICE_ICONS[name] || Server;
                        return (
                            <Card key={name} className="relative overflow-hidden">
                                <div className="flex items-center gap-3">
                                    <div className="p-2 bg-slate-700/50 rounded-lg">
                                        <Icon className="w-5 h-5 text-blue-400" />
                                    </div>
                                    <div className="flex-1">
                                        <h3 className="font-medium text-white capitalize">{name}</h3>
                                        {(service as ServiceStatus).uptime && (
                                            <p className="text-gray-400 text-xs truncate">
                                                {(service as ServiceStatus).uptime}
                                            </p>
                                        )}
                                    </div>
                                    <span className={`px-2 py-1 text-xs rounded-full border ${getStatusBadge((service as ServiceStatus).status)}`}>
                                        {(service as ServiceStatus).status}
                                    </span>
                                </div>
                                {/* Restart button for eligible services */}
                                {['backend', 'frontend', 'redis', 'caddy'].includes(name) && (
                                    <Button
                                        size="sm"
                                        variant="secondary"
                                        className="mt-3 w-full"
                                        onClick={() => executeRunbook(`restart-${name}`, `Restart ${name}`)}
                                        disabled={runbookLoading !== null}
                                    >
                                        {runbookLoading === `restart-${name}` ? (
                                            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                                        ) : (
                                            <RotateCcw className="w-4 h-4 mr-2" />
                                        )}
                                        Restart
                                    </Button>
                                )}
                            </Card>
                        );
                    })}

                    {/* Database Status */}
                    <Card>
                        <div className="flex items-center gap-3">
                            <div className="p-2 bg-slate-700/50 rounded-lg">
                                <Database className="w-5 h-5 text-purple-400" />
                            </div>
                            <div className="flex-1">
                                <h3 className="font-medium text-white">Database</h3>
                                <p className="text-gray-400 text-xs">
                                    {health.database.size || 'Size unknown'} • {health.database.connections || 0} connections
                                </p>
                            </div>
                            <span className={`px-2 py-1 text-xs rounded-full border ${getStatusBadge(health.database.status)}`}>
                                {health.database.status}
                            </span>
                        </div>
                    </Card>

                    {/* Cache Status */}
                    <Card>
                        <div className="flex items-center gap-3">
                            <div className="p-2 bg-slate-700/50 rounded-lg">
                                <HardDrive className="w-5 h-5 text-orange-400" />
                            </div>
                            <div className="flex-1">
                                <h3 className="font-medium text-white">Redis Cache</h3>
                                <p className="text-gray-400 text-xs">
                                    {health.cache.used_memory || 'Unknown'} used
                                </p>
                            </div>
                            <span className={`px-2 py-1 text-xs rounded-full border ${getStatusBadge(health.cache.status)}`}>
                                {health.cache.status}
                            </span>
                        </div>
                    </Card>

                    {/* Last Backup */}
                    <Card>
                        <div className="flex items-center gap-3">
                            <div className="p-2 bg-slate-700/50 rounded-lg">
                                <Clock className="w-5 h-5 text-green-400" />
                            </div>
                            <div className="flex-1">
                                <h3 className="font-medium text-white">Last Backup</h3>
                                <p className="text-gray-400 text-xs truncate">
                                    {health.last_backup?.created
                                        ? new Date(health.last_backup.created).toLocaleString()
                                        : 'No backup info'}
                                </p>
                            </div>
                        </div>
                    </Card>
                </div>
            )}

            {/* Quick Actions */}
            <Card className="bg-slate-800/50">
                <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <Play className="w-5 h-5 text-green-400" />
                    Emergency Operations
                </h3>
                <p className="text-gray-400 text-sm mb-4">
                    These actions are logged and can be executed by administrators when troubleshooting.
                </p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <Button
                        variant="secondary"
                        onClick={() => executeRunbook('restart-all', 'Restart All Services')}
                        disabled={runbookLoading !== null}
                    >
                        {runbookLoading === 'restart-all' ? (
                            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        ) : (
                            <RotateCcw className="w-4 h-4 mr-2" />
                        )}
                        Restart All
                    </Button>
                    <Button
                        variant="secondary"
                        onClick={() => executeRunbook('clear-cache', 'Clear Cache')}
                        disabled={runbookLoading !== null}
                    >
                        {runbookLoading === 'clear-cache' ? (
                            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        ) : (
                            <Trash2 className="w-4 h-4 mr-2" />
                        )}
                        Clear Cache
                    </Button>
                    <Button
                        variant="secondary"
                        onClick={() => executeRunbook('vacuum', 'DB Maintenance')}
                        disabled={runbookLoading !== null}
                    >
                        {runbookLoading === 'vacuum' ? (
                            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        ) : (
                            <Database className="w-4 h-4 mr-2" />
                        )}
                        DB Maintenance
                    </Button>
                    <Button
                        variant="secondary"
                        onClick={fetchHealth}
                        disabled={isLoading}
                    >
                        <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
                        Refresh Status
                    </Button>
                </div>
            </Card>

            {/* Last Action Result */}
            <AnimatePresence>
                {lastAction && (
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                    >
                        <Card className={`
                            ${lastAction.status === 'success' ? 'bg-green-500/10 border-green-500/30' : ''}
                            ${lastAction.status === 'error' ? 'bg-red-500/10 border-red-500/30' : ''}
                        `}>
                            <div className="flex items-center gap-3">
                                {lastAction.status === 'success' ? (
                                    <CheckCircle className="w-5 h-5 text-green-400" />
                                ) : (
                                    <XCircle className="w-5 h-5 text-red-400" />
                                )}
                                <div className="flex-1">
                                    <span className="font-medium text-white">
                                        {lastAction.action}: {lastAction.status}
                                    </span>
                                    <span className="text-gray-400 text-sm ml-2">
                                        at {new Date(lastAction.timestamp).toLocaleTimeString()}
                                    </span>
                                </div>
                                <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => setLastAction(null)}
                                >
                                    Dismiss
                                </Button>
                            </div>
                        </Card>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Loading State */}
            {isLoading && !health && (
                <div className="flex items-center justify-center py-12">
                    <RefreshCw className="w-8 h-8 text-blue-400 animate-spin" />
                    <span className="ml-3 text-gray-400">Loading operations dashboard...</span>
                </div>
            )}
        </div>
    );
}

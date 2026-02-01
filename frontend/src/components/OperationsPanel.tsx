import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Server, Database, RefreshCw, Play, Trash2, HardDrive, Clock,
    CheckCircle, XCircle, AlertCircle, Loader2, RotateCcw, Wrench, ExternalLink
} from 'lucide-react';
import { Card, Button } from './ui';
import api, { HealthDashboard, RunbookResult } from '../services/api';
import { useDialog } from './DialogProvider';

interface ServiceStatus {
    status: 'running' | 'stopped' | 'unknown' | 'error' | 'not_configured';
    uptime?: string;
    error?: string;
}

// Resolution tips for common issues
const RESOLUTION_TIPS: Record<string, { issue: string; steps: string[] }> = {
    backend: {
        issue: 'Backend API not responding',
        steps: ['Click "Restart Backend" button', 'Check server logs for errors', 'Verify database connection']
    },
    frontend: {
        issue: 'Frontend not reachable',
        steps: ['Click "Restart Frontend" button', 'Check if Vite dev server is running', 'Review build errors']
    },
    db: {
        issue: 'Database connection failed',
        steps: ['Check PostgreSQL container status', 'Verify disk space availability', 'Review connection limits']
    },
    redis: {
        issue: 'Redis cache unavailable',
        steps: ['Click "Restart Redis" button', 'Check Redis container logs', 'Verify memory limits']
    },
    caddy: {
        issue: 'Reverse proxy not routing',
        steps: ['Click "Restart Caddy" button', 'Check Caddyfile configuration', 'Verify SSL certificates']
    }
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
        const interval = setInterval(fetchHealth, 30000);
        return () => clearInterval(interval);
    }, []);

    const executeRunbook = async (action: string, label: string) => {
        const confirmed = await dialog.confirm({
            title: `Execute: ${label}`,
            message: `Are you sure you want to execute "${label}"?\n\nThis action will be logged and may briefly affect availability.`,
            variant: action.includes('restart') ? 'warning' : 'info',
            confirmText: 'Execute',
        });

        if (!confirmed) return;

        setRunbookLoading(action);
        try {
            const result = await api.executeRunbook(action);
            setLastAction(result);
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

    const getIconForService = (name: string) => {
        const icons: Record<string, typeof Server> = {
            backend: Server,
            frontend: Server,
            db: Database,
            redis: HardDrive,
            caddy: Server,
        };
        return icons[name] || Server;
    };

    const getIconColor = (name: string) => {
        const colors: Record<string, string> = {
            backend: 'text-blue-400',
            frontend: 'text-cyan-400',
            db: 'text-purple-400',
            redis: 'text-orange-400',
            caddy: 'text-green-400',
        };
        return colors[name] || 'text-blue-400';
    };

    const canRestart = (name: string) => ['backend', 'frontend', 'redis', 'caddy'].includes(name);

    // Find services with issues
    const degradedServices = health ?
        Object.entries(health.services)
            .filter(([_, s]) => (s as ServiceStatus).status !== 'running')
            .map(([name]) => name)
        : [];

    if (error) {
        return (
            <Card className="bg-red-500/10 border-red-500/20">
                <div className="flex items-center gap-3">
                    <XCircle className="w-6 h-6 text-red-400" />
                    <div className="flex-1">
                        <h3 className="text-lg font-semibold text-red-300">Error Loading Dashboard</h3>
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
                        {health.overall_status === 'healthy' ? (
                            <CheckCircle className="w-6 h-6 text-green-400" />
                        ) : (
                            <AlertCircle className="w-6 h-6 text-yellow-400" />
                        )}
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

            {/* Uniform Services Grid */}
            {health && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {Object.entries(health.services).map(([name, service]) => {
                        const Icon = getIconForService(name);
                        const svc = service as ServiceStatus;
                        const showError = svc.status !== 'running' && svc.error;

                        return (
                            <Card key={name} className="relative">
                                <div className="flex items-center gap-3 mb-3">
                                    <div className="p-2 bg-slate-700/50 rounded-lg">
                                        <Icon className={`w-5 h-5 ${getIconColor(name)}`} />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <h3 className="font-medium text-white capitalize">{name}</h3>
                                        <p className="text-gray-400 text-xs truncate">
                                            {svc.uptime || 'Status check pending'}
                                        </p>
                                    </div>
                                    <span className={`px-2 py-1 text-xs rounded-full border whitespace-nowrap ${getStatusBadge(svc.status)}`}>
                                        {svc.status}
                                    </span>
                                </div>

                                {/* Error message if any */}
                                {showError && (
                                    <p className="text-red-300/80 text-xs mb-3 truncate">
                                        ⚠️ {svc.error}
                                    </p>
                                )}

                                {/* All cards get a button for uniformity */}
                                {canRestart(name) ? (
                                    <Button
                                        size="sm"
                                        variant="secondary"
                                        className="w-full"
                                        onClick={() => executeRunbook(`restart-${name}`, `Restart ${name}`)}
                                        disabled={runbookLoading !== null}
                                    >
                                        {runbookLoading === `restart-${name}` ? (
                                            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                                        ) : (
                                            <RotateCcw className="w-4 h-4 mr-2" />
                                        )}
                                        Restart {name}
                                    </Button>
                                ) : (
                                    <div className="h-9 flex items-center justify-center text-gray-500 text-xs border border-slate-600/30 rounded-lg bg-slate-800/30">
                                        Managed by Docker Compose
                                    </div>
                                )}
                            </Card>
                        );
                    })}
                </div>
            )}

            {/* System Metrics Row */}
            {health && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {/* Database Metrics */}
                    <Card className="bg-slate-800/30">
                        <div className="flex items-center gap-3">
                            <Database className="w-5 h-5 text-purple-400" />
                            <div className="flex-1">
                                <h4 className="font-medium text-white text-sm">PostgreSQL</h4>
                                <p className="text-gray-400 text-xs">
                                    {health.database.size || '?'} • {health.database.connections || 0} connections
                                </p>
                            </div>
                            <span className={`px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(health.database.status)}`}>
                                {health.database.status}
                            </span>
                        </div>
                    </Card>

                    {/* Redis Metrics */}
                    <Card className="bg-slate-800/30">
                        <div className="flex items-center gap-3">
                            <HardDrive className="w-5 h-5 text-orange-400" />
                            <div className="flex-1">
                                <h4 className="font-medium text-white text-sm">Redis Cache</h4>
                                <p className="text-gray-400 text-xs">
                                    {health.cache.used_memory || 'Unknown'} used
                                </p>
                            </div>
                            <span className={`px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(health.cache.status)}`}>
                                {health.cache.status}
                            </span>
                        </div>
                    </Card>

                    {/* Last Backup */}
                    <Card className="bg-slate-800/30">
                        <div className="flex items-center gap-3">
                            <Clock className="w-5 h-5 text-green-400" />
                            <div className="flex-1">
                                <h4 className="font-medium text-white text-sm">Last Backup</h4>
                                <p className="text-gray-400 text-xs truncate">
                                    {health.last_backup?.created
                                        ? new Date(health.last_backup.created).toLocaleString()
                                        : 'No backup recorded'}
                                </p>
                            </div>
                        </div>
                    </Card>
                </div>
            )}

            {/* Troubleshooting Tips - shown when degraded */}
            {health && degradedServices.length > 0 && (
                <Card className="bg-amber-500/5 border-amber-500/20">
                    <h3 className="text-lg font-semibold text-amber-300 mb-3 flex items-center gap-2">
                        <Wrench className="w-5 h-5" />
                        Troubleshooting Tips
                    </h3>
                    <div className="space-y-4">
                        {degradedServices.map(serviceName => {
                            const tips = RESOLUTION_TIPS[serviceName];
                            if (!tips) return null;
                            return (
                                <div key={serviceName} className="bg-slate-800/50 rounded-lg p-3">
                                    <h4 className="font-medium text-white text-sm capitalize mb-2">
                                        {serviceName}: {tips.issue}
                                    </h4>
                                    <ol className="list-decimal list-inside text-gray-300 text-sm space-y-1">
                                        {tips.steps.map((step, i) => (
                                            <li key={i}>{step}</li>
                                        ))}
                                    </ol>
                                </div>
                            );
                        })}
                        <a
                            href="https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/blob/main/docs/DISASTER_RECOVERY.md"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-blue-400 text-sm hover:underline"
                        >
                            View full disaster recovery guide
                            <ExternalLink className="w-3 h-3" />
                        </a>
                    </div>
                </Card>
            )}

            {/* Emergency Operations */}
            <Card className="bg-slate-800/50">
                <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <Play className="w-5 h-5 text-green-400" />
                    Emergency Operations
                </h3>
                <p className="text-gray-400 text-sm mb-4">
                    Administrative actions for troubleshooting. All actions are logged.
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
                        DB Vacuum
                    </Button>
                    <Button
                        variant="secondary"
                        onClick={fetchHealth}
                        disabled={isLoading}
                    >
                        <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
                        Refresh
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
                                <Button size="sm" variant="ghost" onClick={() => setLastAction(null)}>
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

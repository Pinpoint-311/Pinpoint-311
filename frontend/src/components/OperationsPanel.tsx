import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Server, Database, RefreshCw, Play, Trash2, HardDrive, Clock,
    CheckCircle, XCircle, Loader2, RotateCcw, Wrench,
    Shield, Cloud, Languages, Sparkles, Key, Activity
} from 'lucide-react';
import { Card, Button } from './ui';
import api, { HealthDashboard, RunbookResult } from '../services/api';
import { useDialog } from './DialogProvider';

interface ServiceStatus {
    status: 'running' | 'stopped' | 'unknown' | 'error' | 'not_configured';
    uptime?: string;
    error?: string;
}

interface IntegrationCheck {
    status: string;
    message: string;
    [key: string]: any;
}

interface IntegrationHealth {
    overall_status: string;
    checks: {
        database: IntegrationCheck;
        auth0: IntegrationCheck;
        google_kms: IntegrationCheck;
        google_secret_manager: IntegrationCheck;
        vertex_ai: IntegrationCheck;
        translation_api: IntegrationCheck;
    };
    timestamp: string;
}

// Resolution tips for common issues
const RESOLUTION_TIPS: Record<string, { issue: string; steps: string[] }> = {
    backend: { issue: 'Backend API not responding', steps: ['Click "Restart Backend"', 'Check server logs', 'Verify database'] },
    frontend: { issue: 'Frontend not reachable', steps: ['Click "Restart Frontend"', 'Check if Vite is running', 'Review build errors'] },
    db: { issue: 'Database connection failed', steps: ['Check PostgreSQL container', 'Verify disk space', 'Review connection limits'] },
    redis: { issue: 'Redis cache unavailable', steps: ['Click "Restart Redis"', 'Check Redis logs', 'Verify memory limits'] },
    caddy: { issue: 'Reverse proxy not routing', steps: ['Click "Restart Caddy"', 'Check Caddyfile', 'Verify SSL certificates'] }
};

export default function OperationsPanel() {
    const [health, setHealth] = useState<HealthDashboard | null>(null);
    const [integrations, setIntegrations] = useState<IntegrationHealth | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [runbookLoading, setRunbookLoading] = useState<string | null>(null);
    const [lastAction, setLastAction] = useState<RunbookResult | null>(null);
    const dialog = useDialog();

    const fetchAll = async () => {
        setIsLoading(true);
        setError(null);
        try {
            // Fetch both infrastructure and integrations health
            const [healthData, integrationsData] = await Promise.all([
                api.getHealthDashboard(),
                fetch('/api/health/', {
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                }).then(r => r.ok ? r.json() : null).catch(() => null)
            ]);
            setHealth(healthData);
            setIntegrations(integrationsData);
        } catch (err: any) {
            setError(err.message || 'Failed to fetch system status');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchAll();
        const interval = setInterval(fetchAll, 30000);
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
            setTimeout(fetchAll, 2000);
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
            configured: 'bg-green-500/20 text-green-300 border-green-500/30',
            stopped: 'bg-red-500/20 text-red-300 border-red-500/30',
            error: 'bg-red-500/20 text-red-300 border-red-500/30',
            unknown: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
            not_configured: 'bg-gray-500/20 text-gray-300 border-gray-500/30',
            disabled: 'bg-gray-500/20 text-gray-300 border-gray-500/30',
            fallback: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
        };
        return colors[status] || colors.unknown;
    };

    const canRestart = (name: string) => ['backend', 'frontend', 'redis', 'caddy'].includes(name);

    // Find services with issues
    const degradedServices = health ?
        Object.entries(health.services)
            .filter(([_, s]) => (s as ServiceStatus).status !== 'running')
            .map(([name]) => name)
        : [];

    // Count healthy integrations
    const integrationCounts = integrations ? {
        healthy: Object.values(integrations.checks).filter(c => c.status === 'healthy' || c.status === 'configured').length,
        total: Object.keys(integrations.checks).length
    } : { healthy: 0, total: 6 };

    if (error) {
        return (
            <Card className="bg-red-500/10 border-red-500/20">
                <div className="flex items-center gap-3">
                    <XCircle className="w-6 h-6 text-red-400" />
                    <div className="flex-1">
                        <h3 className="text-lg font-semibold text-red-300">Error Loading Dashboard</h3>
                        <p className="text-red-200/80 mt-1">{error}</p>
                    </div>
                    <Button onClick={fetchAll} disabled={isLoading}>
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
                        <Activity className="w-6 h-6 text-blue-400" />
                        System Dashboard
                    </h2>
                    <p className="text-gray-400 text-sm mt-1">
                        Infrastructure, integrations, and emergency operations
                    </p>
                </div>
                <Button onClick={fetchAll} disabled={isLoading} variant="secondary">
                    <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
                    Refresh
                </Button>
            </div>

            {/* Status Summary Cards */}
            {health && (
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {/* Infrastructure Status */}
                    <Card className={`${health.overall_status === 'healthy' ? 'bg-green-500/10 border-green-500/30' : 'bg-yellow-500/10 border-yellow-500/30'}`}>
                        <div className="flex items-center gap-3">
                            <Server className="w-8 h-8 text-blue-400" />
                            <div>
                                <p className="text-gray-400 text-xs uppercase tracking-wide">Infrastructure</p>
                                <p className="text-white font-semibold">
                                    {Object.values(health.services).filter((s: any) => s.status === 'running').length}/{Object.keys(health.services).length} Running
                                </p>
                            </div>
                        </div>
                    </Card>

                    {/* Integrations Status */}
                    <Card className={`${integrationCounts.healthy === integrationCounts.total ? 'bg-green-500/10 border-green-500/30' : 'bg-yellow-500/10 border-yellow-500/30'}`}>
                        <div className="flex items-center gap-3">
                            <Cloud className="w-8 h-8 text-purple-400" />
                            <div>
                                <p className="text-gray-400 text-xs uppercase tracking-wide">Integrations</p>
                                <p className="text-white font-semibold">
                                    {integrationCounts.healthy}/{integrationCounts.total} Configured
                                </p>
                            </div>
                        </div>
                    </Card>

                    {/* Database Status */}
                    <Card className={`${health.database.status === 'healthy' ? 'bg-green-500/10 border-green-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
                        <div className="flex items-center gap-3">
                            <Database className="w-8 h-8 text-purple-400" />
                            <div>
                                <p className="text-gray-400 text-xs uppercase tracking-wide">PostgreSQL</p>
                                <p className="text-white font-semibold">{health.database.size || '?'}</p>
                                <p className="text-gray-500 text-xs">{health.database.connections || 0} connections</p>
                            </div>
                        </div>
                    </Card>

                    {/* Cache Status */}
                    <Card className={`${health.cache.status === 'healthy' ? 'bg-green-500/10 border-green-500/30' : 'bg-yellow-500/10 border-yellow-500/30'}`}>
                        <div className="flex items-center gap-3">
                            <HardDrive className="w-8 h-8 text-orange-400" />
                            <div>
                                <p className="text-gray-400 text-xs uppercase tracking-wide">Redis Cache</p>
                                <p className="text-white font-semibold">{health.cache.used_memory || 'N/A'}</p>
                            </div>
                        </div>
                    </Card>
                </div>
            )}

            {/* Infrastructure Services */}
            {health && (
                <Card>
                    <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                        <Server className="w-5 h-5 text-blue-400" />
                        Infrastructure Services
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3">
                        {Object.entries(health.services).map(([name, service]) => {
                            const svc = service as ServiceStatus;
                            return (
                                <div key={name} className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
                                    <div className="flex items-center justify-between mb-2">
                                        <span className="text-white font-medium capitalize">{name}</span>
                                        <span className={`px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(svc.status)}`}>
                                            {svc.status}
                                        </span>
                                    </div>
                                    <p className="text-gray-500 text-xs truncate mb-2">{svc.uptime || 'Checking...'}</p>
                                    {canRestart(name) && (
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            className="w-full text-xs"
                                            onClick={() => executeRunbook(`restart-${name}`, `Restart ${name}`)}
                                            disabled={runbookLoading !== null}
                                        >
                                            <RotateCcw className="w-3 h-3 mr-1" />
                                            Restart
                                        </Button>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </Card>
            )}

            {/* Cloud Integrations */}
            {integrations && (
                <Card>
                    <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                        <Cloud className="w-5 h-5 text-purple-400" />
                        Cloud Integrations
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        {/* Auth0 */}
                        <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
                            <div className="flex items-center gap-3 mb-2">
                                <Key className="w-5 h-5 text-orange-400" />
                                <span className="text-white font-medium">Auth0 SSO</span>
                                <span className={`ml-auto px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(integrations.checks.auth0.status)}`}>
                                    {integrations.checks.auth0.status}
                                </span>
                            </div>
                            <p className="text-gray-400 text-xs">{integrations.checks.auth0.message}</p>
                        </div>

                        {/* Google KMS */}
                        <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
                            <div className="flex items-center gap-3 mb-2">
                                <Shield className="w-5 h-5 text-blue-400" />
                                <span className="text-white font-medium">Google KMS</span>
                                <span className={`ml-auto px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(integrations.checks.google_kms.status)}`}>
                                    {integrations.checks.google_kms.status}
                                </span>
                            </div>
                            <p className="text-gray-400 text-xs">{integrations.checks.google_kms.message}</p>
                        </div>

                        {/* Secret Manager */}
                        <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
                            <div className="flex items-center gap-3 mb-2">
                                <Key className="w-5 h-5 text-green-400" />
                                <span className="text-white font-medium">Secret Manager</span>
                                <span className={`ml-auto px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(integrations.checks.google_secret_manager.status)}`}>
                                    {integrations.checks.google_secret_manager.status}
                                </span>
                            </div>
                            <p className="text-gray-400 text-xs">{integrations.checks.google_secret_manager.message}</p>
                        </div>

                        {/* Vertex AI */}
                        <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
                            <div className="flex items-center gap-3 mb-2">
                                <Sparkles className="w-5 h-5 text-purple-400" />
                                <span className="text-white font-medium">Vertex AI</span>
                                <span className={`ml-auto px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(integrations.checks.vertex_ai.status)}`}>
                                    {integrations.checks.vertex_ai.status}
                                </span>
                            </div>
                            <p className="text-gray-400 text-xs">{integrations.checks.vertex_ai.message}</p>
                        </div>

                        {/* Translation API */}
                        <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
                            <div className="flex items-center gap-3 mb-2">
                                <Languages className="w-5 h-5 text-cyan-400" />
                                <span className="text-white font-medium">Translation API</span>
                                <span className={`ml-auto px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(integrations.checks.translation_api.status)}`}>
                                    {integrations.checks.translation_api.status}
                                </span>
                            </div>
                            <p className="text-gray-400 text-xs">{integrations.checks.translation_api.message}</p>
                        </div>

                        {/* Database */}
                        <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700/50">
                            <div className="flex items-center gap-3 mb-2">
                                <Database className="w-5 h-5 text-purple-400" />
                                <span className="text-white font-medium">PostgreSQL</span>
                                <span className={`ml-auto px-2 py-0.5 text-xs rounded-full border ${getStatusBadge(integrations.checks.database.status)}`}>
                                    {integrations.checks.database.status}
                                </span>
                            </div>
                            <p className="text-gray-400 text-xs">{integrations.checks.database.message}</p>
                        </div>
                    </div>
                </Card>
            )}

            {/* Troubleshooting Tips - shown when degraded */}
            {degradedServices.length > 0 && (
                <Card className="bg-amber-500/5 border-amber-500/20">
                    <h3 className="text-lg font-semibold text-amber-300 mb-3 flex items-center gap-2">
                        <Wrench className="w-5 h-5" />
                        Troubleshooting Tips
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {degradedServices.map(serviceName => {
                            const tips = RESOLUTION_TIPS[serviceName];
                            if (!tips) return null;
                            return (
                                <div key={serviceName} className="bg-slate-800/50 rounded-lg p-3">
                                    <h4 className="font-medium text-white text-sm capitalize mb-2">
                                        {serviceName}: {tips.issue}
                                    </h4>
                                    <ol className="list-decimal list-inside text-gray-300 text-xs space-y-1">
                                        {tips.steps.map((step, i) => (
                                            <li key={i}>{step}</li>
                                        ))}
                                    </ol>
                                </div>
                            );
                        })}
                    </div>
                </Card>
            )}

            {/* Emergency Operations */}
            <Card className="bg-slate-800/50">
                <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <Play className="w-5 h-5 text-green-400" />
                    Emergency Operations
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    <Button
                        variant="secondary"
                        onClick={() => executeRunbook('restart-all', 'Restart All Services')}
                        disabled={runbookLoading !== null}
                    >
                        {runbookLoading === 'restart-all' ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <RotateCcw className="w-4 h-4 mr-2" />}
                        Restart All
                    </Button>
                    <Button
                        variant="secondary"
                        onClick={() => executeRunbook('clear-cache', 'Clear Cache')}
                        disabled={runbookLoading !== null}
                    >
                        {runbookLoading === 'clear-cache' ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Trash2 className="w-4 h-4 mr-2" />}
                        Clear Cache
                    </Button>
                    <Button
                        variant="secondary"
                        onClick={() => executeRunbook('vacuum', 'DB Maintenance')}
                        disabled={runbookLoading !== null}
                    >
                        {runbookLoading === 'vacuum' ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Database className="w-4 h-4 mr-2" />}
                        DB Vacuum
                    </Button>
                    <Button
                        variant="secondary"
                        onClick={fetchAll}
                        disabled={isLoading}
                    >
                        <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
                        Refresh
                    </Button>
                </div>
            </Card>

            {/* Last Backup Info */}
            {health?.last_backup?.created && (
                <Card className="bg-slate-800/30">
                    <div className="flex items-center gap-3">
                        <Clock className="w-5 h-5 text-green-400" />
                        <div>
                            <span className="text-white font-medium">Last Backup</span>
                            <span className="text-gray-400 text-sm ml-3">
                                {new Date(health.last_backup.created).toLocaleString()}
                            </span>
                        </div>
                    </div>
                </Card>
            )}

            {/* Last Action Result */}
            <AnimatePresence>
                {lastAction && (
                    <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                    >
                        <Card className={`${lastAction.status === 'success' ? 'bg-green-500/10 border-green-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
                            <div className="flex items-center gap-3">
                                {lastAction.status === 'success' ? <CheckCircle className="w-5 h-5 text-green-400" /> : <XCircle className="w-5 h-5 text-red-400" />}
                                <div className="flex-1">
                                    <span className="font-medium text-white">{lastAction.action}: {lastAction.status}</span>
                                    <span className="text-gray-400 text-sm ml-2">at {new Date(lastAction.timestamp).toLocaleTimeString()}</span>
                                </div>
                                <Button size="sm" variant="ghost" onClick={() => setLastAction(null)}>Dismiss</Button>
                            </div>
                        </Card>
                    </motion.div>
                )}
            </AnimatePresence>

            {/* Loading State */}
            {isLoading && !health && (
                <div className="flex items-center justify-center py-12">
                    <RefreshCw className="w-8 h-8 text-blue-400 animate-spin" />
                    <span className="ml-3 text-gray-400">Loading system dashboard...</span>
                </div>
            )}
        </div>
    );
}

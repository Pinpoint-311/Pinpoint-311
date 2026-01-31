import { useState, useEffect } from 'react';
import { CheckCircle, XCircle, AlertCircle, RefreshCw, Activity } from 'lucide-react';
import { Card, Button } from '../components/ui';

interface HealthCheckResult {
    status: string;
    message: string;
    [key: string]: any;
}

interface HealthCheckResponse {
    overall_status: string;
    checks: {
        database: HealthCheckResult;
        zitadel_sso: HealthCheckResult;
        google_kms: HealthCheckResult;
        google_secret_manager: HealthCheckResult;
        vertex_ai: HealthCheckResult;
        translation_api: HealthCheckResult;
    };
    timestamp: string;
}

export default function SystemHealthDashboard() {
    const [health, setHealth] = useState<HealthCheckResponse | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchHealth = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const token = localStorage.getItem('token');
            const response = await fetch('/api/health/', {
                headers: {
                    'Authorization': `Bearer ${token}`,
                },
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            setHealth(data);
        } catch (err: any) {
            setError(err.message || 'Failed to fetch health status');
        } finally {
            setIsLoading(false);
        }
    };

    useEffect(() => {
        fetchHealth();
    }, []);

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'healthy':
            case 'configured':
                return <CheckCircle className="w-6 h-6 text-green-400" />;
            case 'not_configured':
            case 'disabled':
            case 'fallback':
                return <AlertCircle className="w-6 h-6 text-yellow-400" />;
            case 'error':
                return <XCircle className="w-6 h-6 text-red-400" />;
            default:
                return <Activity className="w-6 h-6 text-gray-400" />;
        }
    };

    const getStatusColor = (status: string) => {
        switch (status) {
            case 'healthy':
            case 'configured':
                return 'text-green-400';
            case 'not_configured':
            case 'disabled':
            case 'fallback':
                return 'text-yellow-400';
            case 'error':
                return 'text-red-400';
            default:
                return 'text-gray-400';
        }
    };

    const renderCheckDetails = (check: HealthCheckResult) => {
        const details = Object.entries(check).filter(
            ([key]) => key !== 'status' && key !== 'message'
        );

        if (details.length === 0) return null;

        return (
            <div className="mt-3 space-y-1 text-sm">
                {details.map(([key, value]) => {
                    if (value === null || value === undefined) return null;
                    const displayValue = typeof value === 'boolean'
                        ? (value ? 'Yes' : 'No')
                        : String(value);

                    return (
                        <div key={key} className="flex justify-between text-gray-300">
                            <span className="capitalize">{key.replace(/_/g, ' ')}:</span>
                            <span className="text-gray-400 font-mono text-xs">{displayValue}</span>
                        </div>
                    );
                })}
            </div>
        );
    };

    if (error) {
        return (
            <div className="p-6">
                <Card className="bg-red-500/10 border-red-500/20">
                    <div className="flex items-center gap-3">
                        <XCircle className="w-6 h-6 text-red-400" />
                        <div className="flex-1">
                            <h3 className="text-lg font-semibold text-red-300">Error Loading Health Check</h3>
                            <p className="text-red-200/80 mt-1">{error}</p>
                        </div>
                        <Button onClick={fetchHealth} disabled={isLoading}>
                            <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
                            Retry
                        </Button>
                    </div>
                </Card>
            </div>
        );
    }

    return (
        <div className="p-6 space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">System Health</h1>
                    <p className="text-gray-400 mt-1">Monitor all system integrations and dependencies</p>
                </div>
                <Button onClick={fetchHealth} disabled={isLoading}>
                    <RefreshCw className={`w-4 h-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
                    Refresh
                </Button>
            </div>

            {/* Overall Status */}
            {health && (
                <Card className={`
                    ${health.overall_status === 'healthy' ? 'bg-green-500/10 border-green-500/20' : ''}
                    ${health.overall_status === 'degraded' ? 'bg-red-500/10 border-red-500/20' : ''}
                    ${health.overall_status === 'partial' ? 'bg-yellow-500/10 border-yellow-500/20' : ''}
                `}>
                    <div className="flex items-center gap-3">
                        {getStatusIcon(health.overall_status)}
                        <div className="flex-1">
                            <h2 className="text-xl font-semibold text-white">
                                {health.overall_status === 'healthy' && 'All Systems Operational'}
                                {health.overall_status === 'degraded' && 'System Degraded'}
                                {health.overall_status === 'partial' && 'Partial Configuration'}
                            </h2>
                            <p className="text-gray-400 text-sm">
                                Last checked: {new Date(health.timestamp).toLocaleString()}
                            </p>
                        </div>
                    </div>
                </Card>
            )}

            {/* Individual Checks */}
            {health && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Database */}
                    <Card>
                        <div className="flex items-start gap-3">
                            {getStatusIcon(health.checks.database.status)}
                            <div className="flex-1">
                                <h3 className="font-semibold text-white">Database</h3>
                                <p className={`text-sm mt-1 ${getStatusColor(health.checks.database.status)}`}>
                                    {health.checks.database.message}
                                </p>
                                {renderCheckDetails(health.checks.database)}
                            </div>
                        </div>
                    </Card>

                    {/* Zitadel SSO */}
                    <Card>
                        <div className="flex items-start gap-3">
                            {getStatusIcon(health.checks.zitadel_sso.status)}
                            <div className="flex-1">
                                <h3 className="font-semibold text-white">Zitadel SSO</h3>
                                <p className={`text-sm mt-1 ${getStatusColor(health.checks.zitadel_sso.status)}`}>
                                    {health.checks.zitadel_sso.message}
                                </p>
                                {renderCheckDetails(health.checks.zitadel_sso)}
                            </div>
                        </div>
                    </Card>

                    {/* Google Cloud KMS */}
                    <Card>
                        <div className="flex items-start gap-3">
                            {getStatusIcon(health.checks.google_kms.status)}
                            <div className="flex-1">
                                <h3 className="font-semibold text-white">Google Cloud KMS</h3>
                                <p className="text-xs text-gray-500 mb-1">PII Encryption</p>
                                <p className={`text-sm ${getStatusColor(health.checks.google_kms.status)}`}>
                                    {health.checks.google_kms.message}
                                </p>
                                {renderCheckDetails(health.checks.google_kms)}
                            </div>
                        </div>
                    </Card>

                    {/* Secret Manager */}
                    <Card>
                        <div className="flex items-start gap-3">
                            {getStatusIcon(health.checks.google_secret_manager.status)}
                            <div className="flex-1">
                                <h3 className="font-semibold text-white">Secret Manager</h3>
                                <p className="text-xs text-gray-500 mb-1">Google Cloud</p>
                                <p className={`text-sm ${getStatusColor(health.checks.google_secret_manager.status)}`}>
                                    {health.checks.google_secret_manager.message}
                                </p>
                                {renderCheckDetails(health.checks.google_secret_manager)}
                            </div>
                        </div>
                    </Card>

                    {/* Vertex AI */}
                    <Card>
                        <div className="flex items-start gap-3">
                            {getStatusIcon(health.checks.vertex_ai.status)}
                            <div className="flex-1">
                                <h3 className="font-semibold text-white">Vertex AI</h3>
                                <p className="text-xs text-gray-500 mb-1">AI Analysis (Gemini)</p>
                                <p className={`text-sm ${getStatusColor(health.checks.vertex_ai.status)}`}>
                                    {health.checks.vertex_ai.message}
                                </p>
                                {renderCheckDetails(health.checks.vertex_ai)}
                            </div>
                        </div>
                    </Card>

                    {/* Translation API */}
                    <Card>
                        <div className="flex items-start gap-3">
                            {getStatusIcon(health.checks.translation_api.status)}
                            <div className="flex-1">
                                <h3 className="font-semibold text-white">Translation API</h3>
                                <p className="text-xs text-gray-500 mb-1">Multi-Language Support</p>
                                <p className={`text-sm ${getStatusColor(health.checks.translation_api.status)}`}>
                                    {health.checks.translation_api.message}
                                </p>
                                {renderCheckDetails(health.checks.translation_api)}
                            </div>
                        </div>
                    </Card>
                </div>
            )}

            {/* Loading State */}
            {isLoading && !health && (
                <div className="flex items-center justify-center py-12">
                    <RefreshCw className="w-8 h-8 text-blue-400 animate-spin" />
                    <span className="ml-3 text-gray-400">Loading system health...</span>
                </div>
            )}

            {/* Quick Actions / Help */}
            {health && health.overall_status !== 'healthy' && (
                <Card className="bg-blue-500/10 border-blue-500/20">
                    <div className="flex items-start gap-3">
                        <AlertCircle className="w-6 h-6 text-blue-400 flex-shrink-0" />
                        <div className="flex-1">
                            <h3 className="font-semibold text-blue-300">Need Help?</h3>
                            <p className="text-blue-200/80 text-sm mt-1">
                                Check the <strong>Setup Guide</strong> tab for instructions on configuring missing services.
                                Most integrations can be set up through the Admin Console.
                            </p>
                        </div>
                    </div>
                </Card>
            )}
        </div>
    );
}

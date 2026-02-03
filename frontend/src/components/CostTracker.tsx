import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
    DollarSign,
    TrendingUp,
    Server,
    RefreshCw,
    Activity,
    Cloud,
    Brain,
    Globe,
    MapPin,
    Key,
    Lock,
    AlertCircle,
    CheckCircle2,
    BarChart3,
} from 'lucide-react';
import { Button, AccordionSection } from '../components/ui';
import { api, CostEstimate, DailyUsageResponse } from '../services/api';

interface SecurityAuditItem {
    service: string;
    protocol: string;
    auth_method: string;
    encryption: string;
    status: 'secure' | 'warning' | 'insecure';
    notes: string;
}

const SERVICE_ICONS: Record<string, React.ReactNode> = {
    vertex_ai: <Brain className="w-5 h-5" />,
    translation: <Globe className="w-5 h-5" />,
    maps_geocode: <MapPin className="w-5 h-5" />,
    maps_reverse_geocode: <MapPin className="w-5 h-5" />,
    maps_static: <MapPin className="w-5 h-5" />,
    secret_manager: <Key className="w-5 h-5" />,
    kms: <Lock className="w-5 h-5" />,
};

const SERVICE_COLORS: Record<string, string> = {
    vertex_ai: 'from-purple-500 to-indigo-600',
    translation: 'from-blue-500 to-cyan-600',
    maps_geocode: 'from-green-500 to-emerald-600',
    maps_reverse_geocode: 'from-teal-500 to-green-600',
    maps_static: 'from-lime-500 to-green-600',
    secret_manager: 'from-orange-500 to-amber-600',
    kms: 'from-red-500 to-rose-600',
};

// Security audit data - hardcoded based on implementation review
const SECURITY_AUDIT: SecurityAuditItem[] = [
    {
        service: 'Vertex AI (Gemini)',
        protocol: 'HTTPS',
        auth_method: 'OAuth 2.0 / Service Account',
        encryption: 'TLS 1.3',
        status: 'secure',
        notes: 'Uses Google Cloud authentication with encrypted credentials stored in Secret Manager',
    },
    {
        service: 'Google Cloud Translation',
        protocol: 'HTTPS',
        auth_method: 'API Key',
        encryption: 'TLS 1.3',
        status: 'secure',
        notes: 'API key stored securely, all requests over HTTPS',
    },
    {
        service: 'Google Maps Geocoding',
        protocol: 'HTTPS',
        auth_method: 'API Key',
        encryption: 'TLS 1.3',
        status: 'secure',
        notes: 'API key stored in Secret Manager, restricted by domain',
    },
    {
        service: 'Auth0 Identity',
        protocol: 'HTTPS',
        auth_method: 'OAuth 2.0 / OIDC',
        encryption: 'TLS 1.3',
        status: 'secure',
        notes: 'SSO with JWT tokens, MFA supported, credentials in Secret Manager',
    },
    {
        service: 'Google Secret Manager',
        protocol: 'HTTPS',
        auth_method: 'Service Account / ADC',
        encryption: 'TLS 1.3 + AES-256',
        status: 'secure',
        notes: 'All secrets encrypted at rest with customer-managed keys',
    },
    {
        service: 'Google Cloud KMS',
        protocol: 'HTTPS',
        auth_method: 'Service Account / ADC',
        encryption: 'TLS 1.3',
        status: 'secure',
        notes: 'Used for PII encryption, FIPS 140-2 compliant',
    },
    {
        service: 'PostgreSQL Database',
        protocol: 'PostgreSQL Wire Protocol',
        auth_method: 'Username/Password',
        encryption: 'TLS 1.2+',
        status: 'secure',
        notes: 'Connection uses SSL/TLS, credentials in Secret Manager',
    },
    {
        service: 'SMTP Email',
        protocol: 'SMTP',
        auth_method: 'Username/Password',
        encryption: 'TLS (STARTTLS)',
        status: 'warning',
        notes: 'TLS should be enforced via SMTP_USE_TLS=true setting',
    },
    {
        service: 'Redis Cache',
        protocol: 'Redis Protocol',
        auth_method: 'Password (optional)',
        encryption: 'TLS (optional)',
        status: 'warning',
        notes: 'Ensure REDIS_URL uses rediss:// for TLS in production',
    },
];

export default function CostTracker() {
    const [loading, setLoading] = useState(true);
    const [costData, setCostData] = useState<CostEstimate | null>(null);
    const [_dailyUsage, setDailyUsage] = useState<DailyUsageResponse['data']>([]);
    const [period, setPeriod] = useState(30);
    const [error, setError] = useState<string | null>(null);

    const loadData = async () => {
        setLoading(true);
        setError(null);
        try {
            // Fetch cost estimate
            const costResponse = await api.getCostEstimate(period);
            setCostData(costResponse);

            // Fetch daily usage for charts
            const dailyResponse = await api.getDailyUsage(period);
            setDailyUsage(dailyResponse.data || []);
        } catch (err: unknown) {
            console.error('Failed to load cost data:', err);
            setError(err instanceof Error ? err.message : 'Failed to load cost data');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadData();
    }, [period]);

    const formatCurrency = (amount: number) => {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD',
            minimumFractionDigits: 2,
            maximumFractionDigits: 4,
        }).format(amount);
    };

    const formatNumber = (num: number) => {
        if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(2)}M`;
        if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
        return num.toString();
    };

    // Calculate totals for each metric across all services
    const totals = costData?.services
        ? Object.values(costData.services).reduce(
            (acc, svc) => ({
                tokens_input: acc.tokens_input + (svc.usage.tokens_input || 0),
                tokens_output: acc.tokens_output + (svc.usage.tokens_output || 0),
                characters: acc.characters + (svc.usage.characters || 0),
                api_calls: acc.api_calls + (svc.usage.api_calls || 0),
            }),
            { tokens_input: 0, tokens_output: 0, characters: 0, api_calls: 0 }
        )
        : null;

    const getStatusBadge = (status: 'secure' | 'warning' | 'insecure') => {
        if (status === 'secure') {
            return (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400">
                    <CheckCircle2 className="w-3 h-3" />
                    Secure
                </span>
            );
        }
        if (status === 'warning') {
            return (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                    <AlertCircle className="w-3 h-3" />
                    Review
                </span>
            );
        }
        return (
            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
                <AlertCircle className="w-3 h-3" />
                Insecure
            </span>
        );
    };

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-2xl font-bold text-slate-900 dark:text-white">
                        API Cost Tracker
                    </h2>
                    <p className="text-slate-600 dark:text-slate-400 mt-1">
                        Monitor API usage and estimated costs across all services
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <select
                        value={period}
                        onChange={(e) => setPeriod(Number(e.target.value))}
                        className="px-3 py-2 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-sm"
                    >
                        <option value={7}>Last 7 days</option>
                        <option value={30}>Last 30 days</option>
                        <option value={90}>Last 90 days</option>
                    </select>
                    <Button
                        variant="ghost"
                        onClick={loadData}
                        disabled={loading}
                        className="flex items-center gap-2"
                    >
                        <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
                        Refresh
                    </Button>
                </div>
            </div>

            {error && (
                <div className="p-4 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl">
                    <div className="flex items-center gap-2 text-red-600 dark:text-red-400">
                        <AlertCircle className="w-5 h-5" />
                        <span className="font-medium">{error}</span>
                    </div>
                </div>
            )}

            {/* Summary Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                {/* Total Cost */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 p-5 text-white"
                >
                    <div className="absolute top-0 right-0 w-24 h-24 bg-white/10 rounded-full -mr-8 -mt-8" />
                    <div className="relative">
                        <div className="flex items-center gap-2 text-white/80 mb-2">
                            <DollarSign className="w-4 h-4" />
                            <span className="text-sm font-medium">Estimated Cost</span>
                        </div>
                        <div className="text-3xl font-bold">
                            {loading ? '...' : formatCurrency(costData?.total_estimated_cost || 0)}
                        </div>
                        <p className="text-sm text-white/70 mt-1">
                            Last {period} days
                        </p>
                    </div>
                </motion.div>

                {/* Monthly Projection */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.1 }}
                    className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 p-5 text-white"
                >
                    <div className="absolute top-0 right-0 w-24 h-24 bg-white/10 rounded-full -mr-8 -mt-8" />
                    <div className="relative">
                        <div className="flex items-center gap-2 text-white/80 mb-2">
                            <TrendingUp className="w-4 h-4" />
                            <span className="text-sm font-medium">Monthly Projection</span>
                        </div>
                        <div className="text-3xl font-bold">
                            {loading ? '...' : formatCurrency(costData?.monthly_projection || 0)}
                        </div>
                        <p className="text-sm text-white/70 mt-1">
                            Based on current usage
                        </p>
                    </div>
                </motion.div>

                {/* Total API Calls */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.2 }}
                    className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-purple-500 to-pink-600 p-5 text-white"
                >
                    <div className="absolute top-0 right-0 w-24 h-24 bg-white/10 rounded-full -mr-8 -mt-8" />
                    <div className="relative">
                        <div className="flex items-center gap-2 text-white/80 mb-2">
                            <Activity className="w-4 h-4" />
                            <span className="text-sm font-medium">Total API Calls</span>
                        </div>
                        <div className="text-3xl font-bold">
                            {loading ? '...' : formatNumber(totals?.api_calls || 0)}
                        </div>
                        <p className="text-sm text-white/70 mt-1">
                            Across all services
                        </p>
                    </div>
                </motion.div>

                {/* Total Tokens */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.3 }}
                    className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-amber-500 to-orange-600 p-5 text-white"
                >
                    <div className="absolute top-0 right-0 w-24 h-24 bg-white/10 rounded-full -mr-8 -mt-8" />
                    <div className="relative">
                        <div className="flex items-center gap-2 text-white/80 mb-2">
                            <Brain className="w-4 h-4" />
                            <span className="text-sm font-medium">AI Tokens</span>
                        </div>
                        <div className="text-3xl font-bold">
                            {loading
                                ? '...'
                                : formatNumber((totals?.tokens_input || 0) + (totals?.tokens_output || 0))}
                        </div>
                        <p className="text-sm text-white/70 mt-1">
                            Input + Output
                        </p>
                    </div>
                </motion.div>
            </div>

            {/* Service Breakdown */}
            <AccordionSection title="Service Breakdown" defaultOpen>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {costData?.services &&
                        Object.entries(costData.services).map(([serviceName, data]) => (
                            <motion.div
                                key={serviceName}
                                initial={{ opacity: 0, scale: 0.95 }}
                                animate={{ opacity: 1, scale: 1 }}
                                className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-4 hover:shadow-lg transition-shadow"
                            >
                                <div className="flex items-center justify-between mb-3">
                                    <div className="flex items-center gap-3">
                                        <div
                                            className={`w-10 h-10 rounded-lg bg-gradient-to-br ${SERVICE_COLORS[serviceName] || 'from-slate-400 to-slate-500'
                                                } flex items-center justify-center text-white`}
                                        >
                                            {SERVICE_ICONS[serviceName] || <Server className="w-5 h-5" />}
                                        </div>
                                        <div>
                                            <h4 className="font-semibold text-slate-900 dark:text-white capitalize">
                                                {serviceName.replace(/_/g, ' ')}
                                            </h4>
                                            <p className="text-xs text-slate-500 dark:text-slate-400">
                                                {data.description}
                                            </p>
                                        </div>
                                    </div>
                                </div>

                                <div className="space-y-2">
                                    <div className="flex justify-between text-sm">
                                        <span className="text-slate-600 dark:text-slate-400">API Calls</span>
                                        <span className="font-medium text-slate-900 dark:text-white">
                                            {formatNumber(data.usage.api_calls)}
                                        </span>
                                    </div>

                                    {data.usage.tokens_input > 0 && (
                                        <div className="flex justify-between text-sm">
                                            <span className="text-slate-600 dark:text-slate-400">
                                                Tokens (in/out)
                                            </span>
                                            <span className="font-medium text-slate-900 dark:text-white">
                                                {formatNumber(data.usage.tokens_input)} /{' '}
                                                {formatNumber(data.usage.tokens_output)}
                                            </span>
                                        </div>
                                    )}

                                    {data.usage.characters > 0 && (
                                        <div className="flex justify-between text-sm">
                                            <span className="text-slate-600 dark:text-slate-400">Characters</span>
                                            <span className="font-medium text-slate-900 dark:text-white">
                                                {formatNumber(data.usage.characters)}
                                            </span>
                                        </div>
                                    )}

                                    <div className="pt-2 mt-2 border-t border-slate-100 dark:border-slate-700 flex justify-between">
                                        <span className="text-sm font-medium text-slate-600 dark:text-slate-400">
                                            Est. Cost
                                        </span>
                                        <span className="font-bold text-emerald-600 dark:text-emerald-400">
                                            {formatCurrency(data.estimated_cost)}
                                        </span>
                                    </div>
                                </div>
                            </motion.div>
                        ))}

                    {!loading && (!costData?.services || Object.keys(costData.services).length === 0) && (
                        <div className="col-span-full text-center py-12 text-slate-500 dark:text-slate-400">
                            <Cloud className="w-12 h-12 mx-auto mb-3 opacity-50" />
                            <p>No API usage recorded yet</p>
                            <p className="text-sm mt-1">Usage will appear here as services are used</p>
                        </div>
                    )}
                </div>
            </AccordionSection>

            {/* Security Audit */}
            <AccordionSection title="Security Audit - API Connections" defaultOpen>
                <div className="overflow-x-auto">
                    <table className="w-full">
                        <thead>
                            <tr className="bg-slate-50 dark:bg-slate-800/50">
                                <th className="text-left py-3 px-4 text-sm font-semibold text-slate-600 dark:text-slate-300">
                                    Service
                                </th>
                                <th className="text-left py-3 px-4 text-sm font-semibold text-slate-600 dark:text-slate-300">
                                    Protocol
                                </th>
                                <th className="text-left py-3 px-4 text-sm font-semibold text-slate-600 dark:text-slate-300">
                                    Authentication
                                </th>
                                <th className="text-left py-3 px-4 text-sm font-semibold text-slate-600 dark:text-slate-300">
                                    Encryption
                                </th>
                                <th className="text-left py-3 px-4 text-sm font-semibold text-slate-600 dark:text-slate-300">
                                    Status
                                </th>
                                <th className="text-left py-3 px-4 text-sm font-semibold text-slate-600 dark:text-slate-300">
                                    Notes
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {SECURITY_AUDIT.map((item, idx) => (
                                <tr
                                    key={idx}
                                    className="border-t border-slate-100 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800/30"
                                >
                                    <td className="py-3 px-4 font-medium text-slate-900 dark:text-white">
                                        {item.service}
                                    </td>
                                    <td className="py-3 px-4 text-slate-600 dark:text-slate-300">
                                        <code className="px-2 py-0.5 bg-slate-100 dark:bg-slate-700 rounded text-sm">
                                            {item.protocol}
                                        </code>
                                    </td>
                                    <td className="py-3 px-4 text-slate-600 dark:text-slate-300 text-sm">
                                        {item.auth_method}
                                    </td>
                                    <td className="py-3 px-4 text-slate-600 dark:text-slate-300 text-sm">
                                        {item.encryption}
                                    </td>
                                    <td className="py-3 px-4">
                                        {getStatusBadge(item.status)}
                                    </td>
                                    <td className="py-3 px-4 text-slate-500 dark:text-slate-400 text-sm max-w-xs">
                                        {item.notes}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <div className="mt-4 p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-800 rounded-lg">
                    <div className="flex items-start gap-3">
                        <div className="w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-800 flex items-center justify-center flex-shrink-0">
                            <BarChart3 className="w-4 h-4 text-blue-600 dark:text-blue-300" />
                        </div>
                        <div>
                            <h4 className="font-semibold text-blue-900 dark:text-blue-200">Security Summary</h4>
                            <p className="text-sm text-blue-700 dark:text-blue-300 mt-1">
                                {SECURITY_AUDIT.filter((s) => s.status === 'secure').length} of{' '}
                                {SECURITY_AUDIT.length} services are fully secured.{' '}
                                {SECURITY_AUDIT.filter((s) => s.status === 'warning').length > 0 &&
                                    `${SECURITY_AUDIT.filter((s) => s.status === 'warning').length} items need review for production hardening.`}
                            </p>
                        </div>
                    </div>
                </div>
            </AccordionSection>

            {/* Pricing Disclaimer */}
            {costData?.pricing_disclaimer && (
                <div className="p-4 bg-slate-100 dark:bg-slate-800 rounded-xl text-sm text-slate-600 dark:text-slate-400">
                    <strong className="text-slate-700 dark:text-slate-300">Disclaimer:</strong>{' '}
                    {costData.pricing_disclaimer}
                </div>
            )}
        </div>
    );
}

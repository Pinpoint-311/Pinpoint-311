import { useEffect, useState } from 'react';
import { CheckCircle, AlertTriangle, AlertCircle } from 'lucide-react';
import { api, HealthSummary } from '../services/api';

/**
 * A tiny, plain-language system-status pill for non-technical staff. It answers
 * one question — "is everything working?" — with no numbers or jargon. Detailed
 * diagnostics and controls live in the admin System Health panel.
 */
export default function SystemStatusPill() {
    const [summary, setSummary] = useState<HealthSummary | null>(null);

    useEffect(() => {
        let active = true;
        const load = () => api.getHealthSummary().then(s => { if (active) setSummary(s); }).catch(() => { });
        load();
        const id = setInterval(load, 5 * 60 * 1000); // refresh every 5 min
        return () => { active = false; clearInterval(id); };
    }, []);

    if (!summary) return null;

    const styles = {
        ok: { cls: 'bg-emerald-500/15 border-emerald-400/30 text-emerald-200', Icon: CheckCircle, dot: 'bg-emerald-400' },
        warning: { cls: 'bg-amber-500/15 border-amber-400/30 text-amber-200', Icon: AlertTriangle, dot: 'bg-amber-400' },
        critical: { cls: 'bg-red-500/15 border-red-400/30 text-red-200', Icon: AlertCircle, dot: 'bg-red-400' },
    }[summary.level] || { cls: 'bg-white/10 border-white/20 text-white/70', Icon: CheckCircle, dot: 'bg-white/50' };

    const { Icon } = styles;

    return (
        <div
            className={`hidden sm:inline-flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-medium ${styles.cls}`}
            title={summary.detail}
            role="status"
            aria-label={`System status: ${summary.label}`}
        >
            <span className={`w-1.5 h-1.5 rounded-full ${styles.dot} ${summary.level === 'ok' ? 'animate-pulse' : ''}`} />
            <Icon className="w-3.5 h-3.5" aria-hidden="true" />
            <span>{summary.label}</span>
        </div>
    );
}

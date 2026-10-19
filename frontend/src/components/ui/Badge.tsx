import React from 'react';
import { FlaskConical, Shield, User as UserIcon, type LucideIcon } from 'lucide-react';
import { RequestStatus } from '../../types';
import { humanize } from '../../utils/humanize';

export type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info' | 'accent';

interface BadgeProps {
    children: React.ReactNode;
    variant?: BadgeVariant;
    /** xs is the compact chip used inside rows and cards. */
    size?: 'xs' | 'sm' | 'md';
    /** Optional lucide icon, drawn before the text and hidden from AT. */
    icon?: LucideIcon;
    /** Monospace, for a value a person must copy or match exactly. */
    mono?: boolean;
    title?: string;
    className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
    default: 'bg-white/10 text-white/80 border-white/20',
    success: 'bg-green-500/20 text-green-200 border-green-500/30',
    warning: 'bg-amber-500/20 text-amber-200 border-amber-500/30',
    danger: 'bg-red-500/20 text-red-200 border-red-500/30',
    info: 'bg-blue-500/20 text-blue-200 border-blue-500/30',
    accent: 'bg-indigo-500/20 text-indigo-200 border-indigo-500/30',
};

const sizeStyles = {
    xs: 'px-2 py-0.5 text-[11px] gap-1',
    sm: 'px-2.5 py-1 text-xs gap-1.5',
    md: 'px-3 py-1.5 text-sm gap-1.5',
};

export const Badge: React.FC<BadgeProps> = ({
    children,
    variant = 'default',
    size = 'sm',
    icon: Icon,
    mono = false,
    title,
    className = '',
}) => (
    <span
        title={title}
        className={`inline-flex items-center font-medium rounded-full border ${variantStyles[variant]} ${sizeStyles[size]} ${mono ? 'font-mono' : ''} ${className}`.trim()}
    >
        {Icon && <Icon className={size === 'xs' ? 'w-3 h-3 shrink-0' : 'w-3.5 h-3.5 shrink-0'} aria-hidden="true" />}
        {children}
    </span>
);

/** The tone names a chip speaks in; `neutral` is Badge's `default`. */
export type ChipTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'accent';

interface ChipProps extends Omit<BadgeProps, 'variant' | 'size' | 'children'> {
    tone?: ChipTone;
    size?: 'xs' | 'sm';
    /** A machine value (`push_status`) -- shown humanized when no children are given. */
    value?: string | null;
    children?: React.ReactNode;
}

/**
 * The compact chip for showing an enum-ish value to a person. Pass `value` to
 * have it humanized (`in_progress` -> "In progress"), or children for a label
 * you already have.
 */
export const Chip: React.FC<ChipProps> = ({ tone = 'neutral', size = 'xs', value, children, ...rest }) => (
    <Badge variant={tone === 'neutral' ? 'default' : tone} size={size} {...rest}>
        {children ?? humanize(value)}
    </Badge>
);

/**
 * The colour a status-like value carries. Shared so "failed" is red and
 * "in progress" amber everywhere. Request `open` is red, as StatusBadge has it.
 */
export function statusTone(value: string | null | undefined): ChipTone {
    const v = String(value ?? '').toLowerCase();
    if (/^(ok|success|succeeded|healthy|completed?|done|closed|resolved|active|connected|enabled|sent|delivered|passed|pass|valid|up|online|ready|configured|verified|accepted|approved|current)$/.test(v)) return 'success';
    if (/^(failed?|failure|error|errored|unhealthy|down|offline|critical|rejected|denied|invalid|open|expired|blocked|missing|dead)$/.test(v)) return 'danger';
    if (/^(pending|in_progress|running|queued|degraded|warn|warning|partial|retrying|stalled|waiting|scheduled|stale)$/.test(v)) return 'warning';
    return 'neutral';
}

interface StatusBadgeProps {
    status: RequestStatus | string;
    size?: 'xs' | 'sm';
}

const REQUEST_STATUS: Record<string, { label: string; variant: BadgeVariant }> = {
    open: { label: 'Open', variant: 'danger' },
    in_progress: { label: 'In Progress', variant: 'warning' },
    closed: { label: 'Closed', variant: 'success' },
};

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, size = 'sm' }) => {
    // An unexpected value still renders as a readable chip rather than crashing.
    const config = REQUEST_STATUS[status] ?? { label: humanize(status), variant: 'default' as const };

    return (
        <Badge variant={config.variant} size={size}>
            {config.label}
        </Badge>
    );
};

const ROLES: Record<string, { label: string; tone: ChipTone; icon: LucideIcon }> = {
    admin: { label: 'Admin', tone: 'warning', icon: Shield },
    staff: { label: 'Staff', tone: 'info', icon: UserIcon },
    researcher: { label: 'Researcher', tone: 'accent', icon: FlaskConical },
};

/** "Admin" / "Staff" / "Researcher" for an account role. */
export const roleLabel = (role?: string | null): string => (role && ROLES[role]?.label) || humanize(role);

/** An account's role, as one chip everywhere it is shown. */
export const RoleChip: React.FC<{ role?: string | null; size?: 'xs' | 'sm' }> = ({ role, size = 'xs' }) => {
    const r = (role && ROLES[role]) || { label: humanize(role) || 'Unknown', tone: 'neutral' as const, icon: UserIcon };
    return <Chip tone={r.tone} icon={r.icon} size={size}>{r.label}</Chip>;
};

export default Badge;

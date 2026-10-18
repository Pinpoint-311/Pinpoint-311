import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { AlertCircle, CheckCircle, RefreshCw, Plus, ChevronDown, ChevronUp } from 'lucide-react';

import type { IntegrationConfig, IntegrationPlatform } from '../services/api';
import type { ServiceDefinition } from '../types';
import {
    integrationsApi,
    type BacklogItem, type IntegrationLookups, type LookupItem, type MappingSave, type SyncProblems,
} from '../services/integrationsApi';
import { Action, ResultNote, Switch } from './capabilityUI';

/** The extra fields the connections list sends that the shared type omits. */
export type MappedIntegration = IntegrationConfig & {
    lookups?: IntegrationLookups;
    lookups_fetched_at?: string | null;
    mapping_approved_at?: string | null;
    mapping_approved_by?: string | null;
    backlog_open?: number;
    backlog_stalled?: number;
};

export type MappedPlatform = IntegrationPlatform & {
    default_status_map_out?: Record<string, string>;
    default_status_map_in?: Record<string, string>;
    status_push?: boolean;
};

const STATUSES: { code: string; label: string }[] = [
    { code: 'open', label: 'Open' },
    { code: 'in_progress', label: 'In progress' },
    { code: 'closed', label: 'Closed' },
];

/** Pinpoint fields an ArcGIS layer can receive, in the order a clerk thinks of them. */
const LAYER_FIELDS: { key: string; label: string; pii?: boolean }[] = [
    { key: 'service_request_id', label: 'Request number' },
    { key: 'service_name', label: 'Category name' },
    { key: 'service_code', label: 'Category code' },
    { key: 'description', label: 'Description' },
    { key: 'address', label: 'Address' },
    { key: 'status', label: 'Status' },
    { key: 'requested_datetime', label: 'Date submitted' },
    // No Esri template column; mapping one lets priority changes follow the report.
    { key: 'priority', label: 'Priority' },
    { key: 'first_name', label: 'First name', pii: true },
    { key: 'last_name', label: 'Last name', pii: true },
    { key: 'email', label: 'Email', pii: true },
    { key: 'phone', label: 'Phone', pii: true },
];

/** Esri's citizen-request template names, which the connector uses by default. */
const ARCGIS_DEFAULT_COLUMNS: Record<string, string> = {
    service_request_id: 'reqid', service_name: 'reqcategory', service_code: 'reqtype',
    description: 'details', address: 'address', status: 'status', requested_datetime: 'submitdt',
    first_name: 'firstname', last_name: 'lastname', email: 'email', phone: 'phone', priority: '',
};

const CATEGORY_TARGET: Record<string, string> = {
    accela: 'Accela record type',
    arcgis: 'Layer category value',
    tyler: 'Tyler service code',
    open311: 'Open311 service code',
    generic_rest: 'Vendor category code',
};

const asMap = (value: unknown): Record<string, string> => {
    if (!value || typeof value !== 'object') return {};
    return Object.fromEntries(
        Object.entries(value as Record<string, unknown>)
            .filter(([, v]) => v !== null && v !== undefined)
            .map(([k, v]) => [k, String(v)]),
    );
};

const isOn = (value: unknown) => ['1', 'true', 'yes', 'on'].includes(String(value ?? '').trim().toLowerCase());

const listOf = (lookups: IntegrationLookups | undefined, name: string): LookupItem[] => {
    const items = lookups?.[name];
    return Array.isArray(items) ? items : [];
};

const inputCls = 'w-full rounded-xl bg-white/[0.04] border border-white/10 text-white text-sm px-3 py-2 placeholder:text-white/35 focus:outline-none focus:border-primary-400/50 focus:bg-white/[0.06]';
const sectionCls = 'rounded-2xl border border-white/10 bg-white/[0.03] p-4';

/** A picker over the vendor's list that still takes a typed value. */
function VendorValue({ id, value, onChange, options, placeholder, label }: {
    id: string; value: string; onChange: (v: string) => void;
    options: LookupItem[]; placeholder?: string; label: string;
}) {
    const listId = options.length ? `${id}-options` : undefined;
    return (
        <>
            <input
                id={id}
                aria-label={label}
                className={inputCls}
                value={value}
                list={listId}
                placeholder={placeholder || (options.length ? 'Pick or type a value' : 'Type the vendor’s value')}
                onChange={(e) => onChange(e.target.value)}
            />
            {listId && (
                <datalist id={listId}>
                    {options.map(o => (
                        <option key={o.code} value={o.code}>{o.name !== o.code ? o.name : undefined}</option>
                    ))}
                </datalist>
            )}
        </>
    );
}

function Disclosure({ id, title, children, defaultOpen = false }: {
    id: string; title: string; children: ReactNode; defaultOpen?: boolean;
}) {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <div>
            <button
                type="button"
                onClick={() => setOpen(v => !v)}
                aria-expanded={open}
                aria-controls={id}
                className="btn-outline"
            >
                {open ? <ChevronUp className="w-3 h-3" aria-hidden="true" /> : <ChevronDown className="w-3 h-3" aria-hidden="true" />}
                {title}
            </button>
            {open && <div id={id} className="mt-3 space-y-2">{children}</div>}
        </div>
    );
}

/**
 * How Pinpoint's words line up with the vendor's: categories, statuses, layer
 * columns, and what is shared. Everything here was settable only through the
 * API, so a town could connect a system and never be asked which of its
 * categories was which on the other side.
 */
export function MappingPanel({ integration, platform, onSaved }: {
    integration: MappedIntegration;
    platform: MappedPlatform;
    onSaved: (updated: MappedIntegration) => void;
}) {
    const name = platform.name;
    const config = (integration.config || {}) as Record<string, unknown>;
    const canLookup = platform.capabilities.includes('lookups');
    const canPull = platform.capabilities.includes('pull');
    const statusPush = platform.status_push ?? platform.capabilities.includes('push_status');
    const isArcgis = platform.platform === 'arcgis';
    const isOpen311 = platform.integration_mode === 'open311';
    // Where a priority can go, and what it takes for a later change to follow.
    // Open311 has no priority and no way to update a request, so no section.
    const priorityNote: string | null = {
        accela: 'Accela only accepts your agency’s own priority values. Until these are filled in, no priority is sent, on new reports or after staff change one.',
        arcgis: 'Needs a Priority column under Layer columns. Blank sends the 1–10 score. Once mapped, a priority staff set or accept is updated on the layer too.',
        generic_rest: 'Blank sends the 1–10 score. For a change staff make later to reach the vendor, set the update path in the connection settings.',
    }[platform.platform as string] ?? null;

    const [lookups, setLookups] = useState<IntegrationLookups>(integration.lookups || {});
    const [fetchedAt, setFetchedAt] = useState<string | null>(integration.lookups_fetched_at || null);
    const [categories, setCategories] = useState<ServiceDefinition[]>([]);
    const [codeOut, setCodeOut] = useState<Record<string, string>>(
        asMap(config.service_code_map_out ?? config.service_code_map));
    const [statusOut, setStatusOut] = useState<Record<string, string>>(asMap(config.status_map_out));
    const [statusIn, setStatusIn] = useState<Record<string, string>>(asMap(config.status_map_in));
    const [fieldMap, setFieldMap] = useState<Record<string, string>>(asMap(config.field_map));
    const [priorityOut, setPriorityOut] = useState<Record<string, string>>(asMap(config.priority_map_out));
    const [sharePii, setSharePii] = useState(isOn(config.share_pii));
    const [importNew, setImportNew] = useState(isOn(config.import_new_records));
    const [newWord, setNewWord] = useState('');
    const [refreshing, setRefreshing] = useState(false);
    const [saving, setSaving] = useState(false);
    const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

    useEffect(() => {
        let live = true;
        integrationsApi.getCategories()
            .then(list => { if (live) setCategories((list || []).filter(c => c.is_active)); })
            .catch(() => { if (live) setCategories([]); });
        return () => { live = false; };
    }, []);

    const services = listOf(lookups, 'services');
    const statuses = listOf(lookups, 'statuses');
    const fields = listOf(lookups, 'fields');
    const sources = (lookups._source || {}) as Record<string, string>;
    const defaultsOut = platform.default_status_map_out || {};

    // The vendor words to map inbound: the vendor's own list when it publishes
    // one, otherwise whatever the town has mapped plus the defaults in force.
    const inboundWords = useMemo(() => {
        if (statuses.length) return statuses.map(s => s.code);
        const words = new Set<string>([
            ...Object.keys(statusIn),
            ...Object.keys(platform.default_status_map_in || {}),
        ]);
        return Array.from(words);
    }, [statuses, statusIn, platform.default_status_map_in]);

    const refresh = async () => {
        setRefreshing(true);
        setMessage(null);
        try {
            const result = await integrationsApi.refreshLookups(integration.id);
            if (result.ok && result.lookups) {
                setLookups(result.lookups);
                setFetchedAt(result.fetched_at || new Date().toISOString());
                setMessage({ ok: true, text: `Lists refreshed from ${name}.` });
            } else {
                setMessage({ ok: false, text: result.detail || `${name} does not publish its lists.` });
            }
        } catch (err: any) {
            setMessage({ ok: false, text: err?.message || 'Could not refresh the lists.' });
        } finally {
            setRefreshing(false);
        }
    };

    const save = async () => {
        setSaving(true);
        setMessage(null);
        try {
            const body: MappingSave = {
                service_code_map_out: codeOut,
                status_map_in: statusIn,
                share_pii: sharePii,
            };
            if (statusPush) body.status_map_out = statusOut;
            if (canPull) body.import_new_records = importNew;
            if (isArcgis) body.field_map = fieldMap;
            if (priorityNote) body.priority_map_out = priorityOut;
            const updated = await integrationsApi.saveMapping<MappedIntegration>(integration.id, body);
            setMessage({ ok: true, text: 'Mapping saved. New reports use it right away.' });
            onSaved(updated);
        } catch (err: any) {
            setMessage({ ok: false, text: err?.message || 'Could not save the mapping.' });
        } finally {
            setSaving(false);
        }
    };

    const fallbackCode = String(config.default_service_code || '');

    return (
        <div className="relative mt-4 space-y-3" role="group" aria-label={`${name} mapping`}>
            {/* Vendor lists */}
            <div className={`${sectionCls} flex flex-wrap items-center justify-between gap-3`}>
                <div className="min-w-0">
                    <p className="text-white text-sm font-semibold">{name}’s own lists</p>
                    <p className="text-white/60 text-xs mt-0.5">
                        {canLookup
                            ? (fetchedAt
                                ? `Last read ${new Date(fetchedAt).toLocaleString()}. Pickers below offer these values.`
                                : `Read ${name}’s codes so you can pick them instead of typing.`)
                            : `${name} does not publish its codes, so type the values your vendor gave you.`}
                    </p>
                </div>
                {canLookup && (
                    <Action size="sm" onClick={refresh} busy={refreshing} disabled={refreshing}>
                        {!refreshing && <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />}
                        {refreshing ? 'Reading…' : `Refresh from ${name}`}
                    </Action>
                )}
            </div>

            {/* Categories */}
            <div className={sectionCls}>
                <h4 className="text-white text-sm font-semibold">Categories</h4>
                <p className="text-white/60 text-xs mt-0.5 mb-3">
                    {isOpen311
                        ? `Unmapped categories use the fallback service code${fallbackCode ? ` (${fallbackCode})` : ''}, or Pinpoint’s own code if there is none.`
                        : platform.platform === 'accela'
                            ? 'Unmapped categories use the record type from Settings.'
                            : 'Unmapped categories send Pinpoint’s own code.'}
                    {sources.services ? ` Values from ${sources.services}.` : ''}
                </p>
                {categories.length === 0 ? (
                    <p className="text-white/50 text-xs">No active categories yet.</p>
                ) : (
                    <div className="space-y-2">
                        {categories.map(cat => (
                            <div key={cat.service_code} className="grid grid-cols-1 sm:grid-cols-2 gap-2 items-center">
                                <label htmlFor={`map-cat-${integration.id}-${cat.service_code}`} className="text-white/80 text-sm truncate">
                                    {cat.service_name} <span className="text-white/40 text-xs">({cat.service_code})</span>
                                </label>
                                <VendorValue
                                    id={`map-cat-${integration.id}-${cat.service_code}`}
                                    label={`${CATEGORY_TARGET[platform.platform] || 'Vendor value'} for ${cat.service_name}`}
                                    value={codeOut[cat.service_code] || ''}
                                    options={services}
                                    onChange={(v) => setCodeOut(prev => ({ ...prev, [cat.service_code]: v }))}
                                />
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Status */}
            <div className={sectionCls}>
                <h4 className="text-white text-sm font-semibold">Status</h4>
                {statusPush ? (
                    <>
                        <p className="text-white/60 text-xs mt-0.5 mb-3">
                            What {name} is told when staff change a status here.
                            {statuses.length ? '' : ' The grey values are defaults. Confirm them with your vendor.'}
                        </p>
                        <div className="space-y-2">
                            {STATUSES.map(st => (
                                <div key={st.code} className="grid grid-cols-1 sm:grid-cols-2 gap-2 items-center">
                                    <label htmlFor={`map-out-${integration.id}-${st.code}`} className="text-white/80 text-sm">{st.label}</label>
                                    <VendorValue
                                        id={`map-out-${integration.id}-${st.code}`}
                                        label={`${name} status for ${st.label}`}
                                        value={statusOut[st.code] || ''}
                                        options={statuses}
                                        placeholder={defaultsOut[st.code] ? `Default: ${defaultsOut[st.code]}` : undefined}
                                        onChange={(v) => setStatusOut(prev => ({ ...prev, [st.code]: v }))}
                                    />
                                </div>
                            ))}
                        </div>
                    </>
                ) : (
                    <p className="text-white/60 text-xs mt-0.5">
                        {isOpen311
                            ? `Open311 has no way to send a status change back. Status flows one way, from ${name} to Pinpoint.`
                            : `${name} does not take status changes from Pinpoint.`}
                    </p>
                )}

                {canPull && (
                    <div className="mt-3">
                        <Disclosure id={`map-in-${integration.id}`} title={`Statuses coming back from ${name}`} defaultOpen={statuses.length > 0}>
                            <p className="text-white/60 text-xs">
                                Unlisted words count as open, or closed when they say closed, resolved or complete.
                            </p>
                            {inboundWords.map(word => (
                                <div key={word} className="grid grid-cols-1 sm:grid-cols-2 gap-2 items-center">
                                    <label htmlFor={`map-in-${integration.id}-${word}`} className="text-white/80 text-sm truncate">{word}</label>
                                    <select
                                        id={`map-in-${integration.id}-${word}`}
                                        className={inputCls}
                                        value={statusIn[word] || ''}
                                        onChange={(e) => setStatusIn(prev => ({ ...prev, [word]: e.target.value }))}
                                    >
                                        <option value="">
                                            {platform.default_status_map_in?.[word.toLowerCase()]
                                                ? `Default: ${STATUSES.find(s => s.code === platform.default_status_map_in![word.toLowerCase()])?.label}`
                                                : 'Default'}
                                        </option>
                                        {STATUSES.map(s => <option key={s.code} value={s.code}>{s.label}</option>)}
                                    </select>
                                </div>
                            ))}
                            {!statuses.length && (
                                <div className="flex items-center gap-2">
                                    <input
                                        aria-label={`Add a ${name} status word`}
                                        className={inputCls}
                                        placeholder={`Another ${name} status word`}
                                        value={newWord}
                                        onChange={(e) => setNewWord(e.target.value)}
                                    />
                                    <Action size="sm" disabled={!newWord.trim()} onClick={() => {
                                        setStatusIn(prev => ({ ...prev, [newWord.trim()]: prev[newWord.trim()] || 'open' }));
                                        setNewWord('');
                                    }}>
                                        <Plus className="w-3.5 h-3.5" aria-hidden="true" /> Add
                                    </Action>
                                </div>
                            )}
                        </Disclosure>
                    </div>
                )}
            </div>

            {/* ArcGIS layer columns */}
            {isArcgis && (
                <div className={sectionCls}>
                    <Disclosure id={`map-fields-${integration.id}`} title="Layer columns">
                        <p className="text-white/60 text-xs">
                            Which column each piece of a report goes into. Blank uses Esri’s template name.
                        </p>
                        {LAYER_FIELDS.filter(f => !f.pii || sharePii).map(f => (
                            <div key={f.key} className="grid grid-cols-1 sm:grid-cols-2 gap-2 items-center">
                                <label htmlFor={`map-field-${integration.id}-${f.key}`} className="text-white/80 text-sm">{f.label}</label>
                                {fields.length ? (
                                    <select
                                        id={`map-field-${integration.id}-${f.key}`}
                                        className={inputCls}
                                        value={f.key in fieldMap ? fieldMap[f.key] : ARCGIS_DEFAULT_COLUMNS[f.key]}
                                        onChange={(e) => setFieldMap(prev => ({ ...prev, [f.key]: e.target.value }))}
                                    >
                                        <option value="">Don’t send</option>
                                        {ARCGIS_DEFAULT_COLUMNS[f.key] && !fields.some(c => c.code === ARCGIS_DEFAULT_COLUMNS[f.key]) && !(f.key in fieldMap) && (
                                            <option value={ARCGIS_DEFAULT_COLUMNS[f.key]}>{ARCGIS_DEFAULT_COLUMNS[f.key]} (not on this layer)</option>
                                        )}
                                        {fields.map(c => (
                                            <option key={c.code} value={c.code}>{c.name !== c.code ? `${c.name} (${c.code})` : c.code}</option>
                                        ))}
                                    </select>
                                ) : (
                                    <input
                                        id={`map-field-${integration.id}-${f.key}`}
                                        className={inputCls}
                                        placeholder={ARCGIS_DEFAULT_COLUMNS[f.key]}
                                        value={fieldMap[f.key] ?? ''}
                                        onChange={(e) => {
                                            // Blank here means "use the default column", not "send nothing".
                                            const v = e.target.value;
                                            setFieldMap(prev => {
                                                const next = { ...prev };
                                                if (v.trim()) next[f.key] = v; else delete next[f.key];
                                                return next;
                                            });
                                        }}
                                    />
                                )}
                            </div>
                        ))}
                        {!fields.length && (
                            <p className="text-white/50 text-[11px]">Refresh from {name} to pick from the layer’s columns.</p>
                        )}
                    </Disclosure>
                </div>
            )}

            {/* Priority values */}
            {priorityNote && (
                <div className={sectionCls}>
                    <Disclosure id={`map-priority-${integration.id}`} title="Priority">
                        <p className="text-white/60 text-xs">{priorityNote}</p>
                        {([['high', 'High (8–10)'], ['medium', 'Medium (5–7)'], ['low', 'Low (1–4)']] as const).map(([band, label]) => (
                            <div key={band} className="grid grid-cols-1 sm:grid-cols-2 gap-2 items-center">
                                <label htmlFor={`map-priority-${integration.id}-${band}`} className="text-white/80 text-sm">{label}</label>
                                <input
                                    id={`map-priority-${integration.id}-${band}`}
                                    className={inputCls}
                                    placeholder={platform.platform === 'accela' ? 'Your agency’s value' : 'Send the score'}
                                    value={priorityOut[band] ?? ''}
                                    onChange={(e) => {
                                        const v = e.target.value;
                                        setPriorityOut(prev => {
                                            const next = { ...prev };
                                            if (v.trim()) next[band] = v; else delete next[band];
                                            return next;
                                        });
                                    }}
                                />
                            </div>
                        ))}
                    </Disclosure>
                </div>
            )}

            {/* Sharing */}
            <div className={`${sectionCls} space-y-3`}>
                <div className="flex items-start justify-between gap-3">
                    <div>
                        <p id={`pii-${integration.id}`} className="text-white text-sm">Send resident contact details</p>
                        <p className="text-white/60 text-xs">Name, email and phone go to {name} with each report. Off keeps them in Pinpoint.</p>
                    </div>
                    <Switch on={sharePii} onChange={() => setSharePii(v => !v)}
                        label="Send resident contact details" aria-describedby={`pii-${integration.id}`} />
                </div>
                {canPull && (
                    <div className="flex items-start justify-between gap-3">
                        <div>
                            <p id={`import-${integration.id}`} className="text-white text-sm">Import reports filed in {name}</p>
                            <p className="text-white/60 text-xs">Records created there become Pinpoint requests, filed under the mapped category.</p>
                        </div>
                        <Switch on={importNew} onChange={() => setImportNew(v => !v)}
                            label={`Import reports filed in ${name}`} aria-describedby={`import-${integration.id}`} />
                    </div>
                )}
            </div>

            {message && <ResultNote tone={message.ok ? 'ok' : 'bad'}>{message.text}</ResultNote>}

            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-white/50 text-[11px]">
                    {integration.mapping_approved_at
                        ? `Last saved by ${integration.mapping_approved_by || 'an administrator'} on ${new Date(integration.mapping_approved_at).toLocaleDateString()}.`
                        : 'Not reviewed yet.'}
                </p>
                <Action size="sm" variant="primary" onClick={save} busy={saving} disabled={saving}>
                    {saving ? 'Saving…' : 'Save mapping'}
                </Action>
            </div>
        </div>
    );
}

const OPERATION_LABEL: Record<string, string> = {
    push: 'New report',
    push_status: 'Status update',
    push_comment: 'Comment',
    push_priority: 'Priority update',
};

/**
 * Work that has not reached the vendor yet, with Retry and Discard, plus the
 * per-request errors and the "sent, but something was left off" warnings.
 */
export function FailedSyncsPanel({ integration, platformName, enabled, onChanged }: {
    integration: MappedIntegration;
    platformName: string;
    enabled: boolean;
    onChanged?: () => void;
}) {
    const [items, setItems] = useState<BacklogItem[] | null>(null);
    const [problems, setProblems] = useState<SyncProblems | null>(null);
    const [busyId, setBusyId] = useState<number | null>(null);
    const [discarding, setDiscarding] = useState<number | null>(null);
    const [reason, setReason] = useState('');
    const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

    const load = useCallback(async () => {
        try {
            const [backlog, issues] = await Promise.all([
                integrationsApi.getBacklog(integration.id),
                integrationsApi.getSyncProblems(integration.id).catch(() => null),
            ]);
            setItems(backlog || []);
            setProblems(issues);
        } catch (err: any) {
            setItems([]);
            setMessage({ ok: false, text: err?.message || 'Could not load failed syncs.' });
        }
    }, [integration.id]);

    useEffect(() => { load(); }, [load]);

    const retry = async (item: BacklogItem) => {
        setBusyId(item.id);
        setMessage(null);
        try {
            const result = await integrationsApi.retryBacklogItem(integration.id, item.id);
            setMessage({ ok: true, text: result.detail });
            await load();
            onChanged?.();
        } catch (err: any) {
            setMessage({ ok: false, text: err?.message || 'Could not retry.' });
        } finally {
            setBusyId(null);
        }
    };

    const discard = async (item: BacklogItem) => {
        setBusyId(item.id);
        setMessage(null);
        try {
            const result = await integrationsApi.discardBacklogItem(integration.id, item.id, reason.trim());
            setMessage({ ok: true, text: result.detail });
            setDiscarding(null);
            setReason('');
            await load();
            onChanged?.();
        } catch (err: any) {
            setMessage({ ok: false, text: err?.message || 'Could not discard.' });
        } finally {
            setBusyId(null);
        }
    };

    if (items === null) {
        return <p className="relative mt-3 text-white/60 text-xs">Loading failed syncs…</p>;
    }

    const linkErrors = problems?.link_errors || [];
    const warnings = problems?.warnings || [];
    const nothing = items.length === 0 && linkErrors.length === 0 && warnings.length === 0;

    return (
        <div className="relative mt-4 space-y-3" role="group" aria-label={`${platformName} failed syncs`}>
            {nothing && (
                <p className="text-emerald-200/85 text-xs flex items-center gap-1.5">
                    <CheckCircle className="w-3.5 h-3.5" aria-hidden="true" />
                    Nothing waiting. Everything reached {platformName}.
                </p>
            )}

            {items.length > 0 && (
                <div className={sectionCls}>
                    <h4 className="text-white text-sm font-semibold mb-2">Not sent yet</h4>
                    <ul className="divide-y divide-white/5">
                        {items.map(item => (
                            <li key={item.id} className="py-2.5 first:pt-0 last:pb-0">
                                <div className="flex flex-wrap items-start justify-between gap-2">
                                    <div className="min-w-0">
                                        <p className="text-white/85 text-sm">
                                            {OPERATION_LABEL[item.operation] || item.operation}
                                            {item.request_id && <span className="text-white/50"> · {item.request_id}</span>}
                                        </p>
                                        {item.last_error && (
                                            <p className="text-amber-200/80 text-xs mt-0.5 break-words">{item.last_error}</p>
                                        )}
                                        <p className="text-white/50 text-[11px] mt-0.5">
                                            {item.attempts} attempt{item.attempts === 1 ? '' : 's'}
                                            {item.stalled
                                                ? ' · No more automatic tries. Retry or discard it.'
                                                : item.next_attempt_at
                                                    ? ` · Next try ${new Date(item.next_attempt_at).toLocaleString()}`
                                                    : ''}
                                        </p>
                                    </div>
                                    <div className="flex items-center gap-2 shrink-0">
                                        <Action size="sm" onClick={() => retry(item)}
                                            busy={busyId === item.id && discarding !== item.id}
                                            disabled={busyId !== null || !enabled}
                                            title={enabled ? undefined : 'Turn the connection on to retry'}>
                                            Retry
                                        </Action>
                                        <Action size="sm" onClick={() => { setDiscarding(item.id); setReason(''); }}
                                            disabled={busyId !== null}>
                                            Discard
                                        </Action>
                                    </div>
                                </div>
                                {discarding === item.id && (
                                    <div className="mt-2 flex flex-wrap items-center gap-2">
                                        <input
                                            aria-label="Reason for not sending"
                                            className={`${inputCls} flex-1 min-w-[12rem]`}
                                            placeholder="Why it should not be sent (kept in the activity trail)"
                                            value={reason}
                                            onChange={(e) => setReason(e.target.value)}
                                        />
                                        <Action size="sm" variant="primary" onClick={() => discard(item)}
                                            busy={busyId === item.id} disabled={reason.trim().length < 3 || busyId !== null}>
                                            Confirm discard
                                        </Action>
                                        <Action size="sm" onClick={() => setDiscarding(null)}>Cancel</Action>
                                    </div>
                                )}
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {linkErrors.length > 0 && (
                <div className={sectionCls}>
                    <h4 className="text-white text-sm font-semibold mb-2">Requests with a sync problem</h4>
                    <ul className="space-y-2">
                        {linkErrors.map(link => (
                            <li key={`${link.request_id}-${link.external_id}`} className="text-xs">
                                <p className="text-white/85">
                                    {link.request_id}
                                    <span className="text-white/45"> → {link.pending ? 'record number pending' : link.external_id}</span>
                                </p>
                                {link.error && (
                                    <p className="text-amber-200/80 mt-0.5 break-words flex items-start gap-1.5">
                                        <AlertCircle className="w-3 h-3 mt-0.5 shrink-0" aria-hidden="true" /> {link.error}
                                    </p>
                                )}
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {warnings.length > 0 && (
                <div className={sectionCls}>
                    <h4 className="text-white text-sm font-semibold mb-2">Sent, with something left off</h4>
                    <ul className="space-y-1.5">
                        {warnings.map(w => (
                            <li key={w.id} className="text-amber-100/80 text-xs break-words">
                                {w.detail}
                                {w.created_at && <span className="text-white/40"> · {new Date(w.created_at).toLocaleString()}</span>}
                            </li>
                        ))}
                    </ul>
                </div>
            )}

            {message && <ResultNote tone={message.ok ? 'ok' : 'bad'}>{message.text}</ResultNote>}
        </div>
    );
}

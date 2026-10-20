import { useCallback, useEffect, useId, useMemo, useRef, useState, type RefObject } from 'react';
import {
    AlertTriangle, Check, ExternalLink, GitBranch, KeyRound, Loader2, Package, RefreshCw, RotateCcw,
    ShieldCheck, Terminal, X,
} from 'lucide-react';
import api from '../services/api';
import {
    ACTIVE_UPGRADE_STATUSES, IN_FLIGHT_UPGRADE_STATUSES,
    type CurrentVersion, type UpdaterRelease, type UpdaterState, type UpdaterTokenRecord,
    type UpgradeAction, type UpgradeRequestRecord, type UpgradeStatus,
} from '../services/upgradeTypes';
import { useOptionalAnnounce } from './liveAnnounce';
import { AccordionSection, Checkbox, Chip, Modal, statusTone, type ChipTone } from './ui';
import { humanize } from '../utils/humanize';

/**
 * Version Control (docs/design/secure-upgrades.md, Phase 3).
 *
 * The console no longer deploys anything. An admin picks a release the host
 * updater reported as signed and schema-compatible and files a request with a
 * reason; while two-person approval is on, a different admin approves it; the
 * updater (a systemd service on the server, with no port of its own) claims
 * it, verifies, backs up, migrates, health-checks or rolls back, and reports
 * every step back here.
 *
 * The sidebar shows the running version and the active request; the full
 * panel opens in a dialog because the sidebar is too narrow for release notes
 * and a step log.
 */

export const INSTALL_DOCS_URL = 'https://github.com/Pinpoint-311/Pinpoint-311/blob/main/updater/README.md';
export const CONNECT_DOCS_URL = 'https://github.com/Pinpoint-311/Pinpoint-311/blob/main/docs/RELEASES.md#connecting-the-host-updater';
const POLL_MS = 5000;

const STATUS_WORDS: Record<UpgradeStatus, { label: string; tone: ChipTone }> = {
    pending_approval: { label: 'Waiting for approval', tone: 'warning' },
    approved: { label: 'Approved, waiting for the updater', tone: 'info' },
    claimed: { label: 'Starting', tone: 'warning' },
    running: { label: 'Running', tone: 'warning' },
    succeeded: { label: 'Succeeded', tone: 'success' },
    failed: { label: 'Failed', tone: 'danger' },
    rolled_back: { label: 'Rolled back', tone: 'danger' },
    needs_approval: { label: 'On hold: destructive migration', tone: 'warning' },
    cancelled: { label: 'Cancelled', tone: 'neutral' },
    refused: { label: 'Refused', tone: 'danger' },
};

export function RequestStatusChip({ status }: { status: UpgradeStatus }) {
    const s = STATUS_WORDS[status] ?? { label: humanize(status), tone: statusTone(status) };
    return <Chip tone={s.tone}>{s.label}</Chip>;
}

const describe = (r: Pick<UpgradeRequestRecord, 'action' | 'target_tag'>) =>
    r.action === 'upgrade' ? `Upgrade to ${r.target_tag}`
        : r.action === 'rollback' ? 'Roll back to the previous release'
            : 'Restart the app containers';

const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : '');
const shortDigest = (d: string | null | undefined) => (d ? `${d.slice(0, 19)}…` : 'not reported');

/** A three-state check as a chip: verified, failed, or not checked. Words, not
 *  just colour, carry the result. */
function CheckChip({ value, yes, no, unknown }: { value: boolean | null; yes: string; no: string; unknown: string }) {
    if (value === true) return <Chip tone="success" icon={Check}>{yes}</Chip>;
    if (value === false) return <Chip tone="danger" icon={X}>{no}</Chip>;
    return <Chip tone="neutral">{unknown}</Chip>;
}

function ReleaseChips({ r }: { r: UpdaterRelease }) {
    return (
        <div className="flex flex-wrap gap-1.5">
            <CheckChip value={r.signature_verified} yes="Signature verified" no="Signature failed" unknown="Signature not checked" />
            <CheckChip value={r.gate_passed} yes="Gate passed" no="Gate failed" unknown="Gate unknown" />
            <CheckChip value={r.compatible_with_this_instance} yes="Schema compatible" no="Schema incompatible" unknown="Schema not checked" />
            <CheckChip value={r.attested} yes="Attested" no="Attestation failed" unknown="Attestation not checked" />
            {r.prerelease && <Chip tone="accent">Pre-release</Chip>}
            {r.current && <Chip tone="info">Running now</Chip>}
        </div>
    );
}

function StepList({ steps, live }: { steps: UpgradeRequestRecord['steps']; live?: boolean }) {
    if (!steps || steps.length === 0) {
        return <p className="text-xs text-white/50">{live ? 'Waiting for the updater to report its first step…' : 'No steps were reported.'}</p>;
    }
    return (
        <ol className="space-y-1.5" aria-label="Updater steps">
            {steps.map((s, i) => (
                <li key={`${s.step}-${i}`} className="flex items-start gap-2 text-xs">
                    <Chip tone={statusTone(s.status === 'ok' ? 'succeeded' : s.status)}>{humanize(s.status)}</Chip>
                    <div className="min-w-0">
                        <span className="font-medium text-white/85">{humanize(s.step)}</span>
                        {s.at && <span className="text-white/40 ml-2">{new Date(s.at).toLocaleTimeString()}</span>}
                        {s.detail && <p className="text-white/55 break-words whitespace-pre-line mt-0.5">{s.detail}</p>}
                    </div>
                </li>
            ))}
        </ol>
    );
}

function CommandLineSteps() {
    return (
        <div className="space-y-2 text-xs text-white/70">
            <p>Until an updater is connected, upgrade from the server&apos;s command line:</p>
            <pre className="bg-black/30 border border-white/10 rounded-lg p-3 overflow-x-auto font-mono text-[11px] leading-relaxed text-white/80">{`sudo -u pinpoint-updater pinpoint-updater releases --instance <name>
sudo -u pinpoint-updater pinpoint-updater plan     <name> <tag>
sudo -u pinpoint-updater pinpoint-updater upgrade  <name> <tag>
sudo -u pinpoint-updater pinpoint-updater rollback <name>`}</pre>
        </div>
    );
}

/* ------------------------------------------------------------------------ */
/* Updater connection: tokens                                                 */
/* ------------------------------------------------------------------------ */

export function UpdaterTokens({ readOnly, onChange }: { readOnly?: boolean; onChange?: () => void }) {
    const [tokens, setTokens] = useState<UpdaterTokenRecord[] | null>(null);
    const [label, setLabel] = useState('');
    const [created, setCreated] = useState<UpdaterTokenRecord | null>(null);
    const [busy, setBusy] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const announce = useOptionalAnnounce();
    const labelId = useId();

    const load = useCallback(async () => {
        try {
            setTokens((await api.getUpdaterTokens()).tokens);
        } catch (e: any) {
            setError(e?.message || 'Could not load updater tokens');
        }
    }, []);
    useEffect(() => { load(); }, [load]);

    const create = async () => {
        setBusy('create');
        setError(null);
        try {
            const t = await api.createUpdaterToken(label.trim() || undefined);
            setCreated(t);
            setLabel('');
            announce('Updater token created. Copy it now: it is shown only once.');
            await load();
            onChange?.();
        } catch (e: any) {
            setError(e?.message || 'The token was not created');
            announce(`The token was not created: ${e?.message || 'error'}`, 'assertive');
        } finally {
            setBusy(null);
        }
    };

    const revoke = async (t: UpdaterTokenRecord) => {
        setBusy(`revoke-${t.id}`);
        setError(null);
        try {
            await api.revokeUpdaterToken(t.id);
            announce(`Token ${t.token_prefix} revoked.`);
            if (created?.id === t.id) setCreated(null);
            await load();
        } catch (e: any) {
            setError(e?.message || 'The token was not revoked');
        } finally {
            setBusy(null);
        }
    };

    return (
        <div className="space-y-3 text-sm">
            <p className="text-xs text-white/60">
                The updater is a program on the server. It uses one of these tokens to connect to this instance.
                Pinpoint keeps only a fingerprint of each token, not the token itself. See <a className="underline text-indigo-300" href={CONNECT_DOCS_URL} target="_blank" rel="noopener noreferrer">how to connect the updater<span className="sr-only"> (opens in a new tab)</span></a>.
            </p>
            {created?.token && (
                <div className="rounded-lg border border-amber-400/40 bg-amber-500/10 p-3 space-y-2">
                    <p className="text-xs text-amber-100">Copy this token now. It will not be shown again. Put it in the instance&apos;s <code>token_file</code> (mode 0600) on the server.</p>
                    <code className="block font-mono text-xs break-all bg-black/30 rounded p-2 text-white" data-testid="new-updater-token">{created.token}</code>
                </div>
            )}
            {!readOnly && (
                <div className="flex flex-wrap items-end gap-2">
                    <div className="flex-1 min-w-[10rem]">
                        <label htmlFor={labelId} className="block text-xs text-white/60 mb-1">Label (optional)</label>
                        <input id={labelId} value={label} onChange={e => setLabel(e.target.value)} maxLength={100}
                            placeholder="e.g. town server updater"
                            className="w-full bg-white/10 border border-white/20 rounded-lg px-3 py-1.5 text-white text-sm" />
                    </div>
                    <button type="button" className="btn-outline text-sm" onClick={create} disabled={busy !== null}>
                        {busy === 'create' ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> : <KeyRound className="w-4 h-4" aria-hidden="true" />}
                        <span className="ml-1.5">Create token</span>
                    </button>
                </div>
            )}
            {error && <p className="text-xs text-red-300">{error}</p>}
            {tokens && tokens.length > 0 && (
                <ul className="divide-y divide-white/10 rounded-lg border border-white/10">
                    {tokens.map(t => (
                        <li key={t.id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-xs">
                            <code className="font-mono text-white">{t.token_prefix}…</code>
                            {t.label && <span className="text-white/70">{t.label}</span>}
                            <Chip tone={t.status === 'active' ? 'success' : 'neutral'}>{t.status === 'active' ? 'Active' : 'Revoked'}</Chip>
                            <span className="text-white/45">
                                created {when(t.created_at)}{t.created_by ? ` by ${t.created_by}` : ''}
                                {' · '}{t.last_used_at ? `last used ${when(t.last_used_at)}` : 'never used'}
                            </span>
                            {t.status === 'active' && !readOnly && (
                                <button type="button" className="btn-outline text-xs ml-auto" onClick={() => revoke(t)}
                                    disabled={busy !== null} aria-label={`Revoke token ${t.token_prefix}`}>
                                    Revoke
                                </button>
                            )}
                        </li>
                    ))}
                </ul>
            )}
            {tokens && tokens.length === 0 && <p className="text-xs text-white/50">No tokens yet.</p>}
        </div>
    );
}

/* ------------------------------------------------------------------------ */
/* The full panel                                                             */
/* ------------------------------------------------------------------------ */

interface FormState {
    action: UpgradeAction;
    tag: string | null;
}

export function VersionControlPanel({ managed = false }: { managed?: boolean }) {
    const [current, setCurrent] = useState<CurrentVersion | null>(null);
    const [releases, setReleases] = useState<UpdaterRelease[]>([]);
    const [updater, setUpdater] = useState<UpdaterState | null>(null);
    const [requests, setRequests] = useState<UpgradeRequestRecord[]>([]);
    const [active, setActive] = useState<UpgradeRequestRecord | null>(null);
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);
    const [busy, setBusy] = useState<string | null>(null);
    const [form, setForm] = useState<FormState | null>(null);
    const [reason, setReason] = useState('');
    const [schedule, setSchedule] = useState('');
    const [allowDestructive, setAllowDestructive] = useState(false);
    const [expanded, setExpanded] = useState<Record<number, UpgradeRequestRecord>>({});
    const announce = useOptionalAnnounce();
    const ids = useId();

    useEffect(() => { if (message) announce(message); }, [message, announce]);
    useEffect(() => { if (error) announce(error, 'assertive'); }, [error, announce]);

    const load = useCallback(async () => {
        const [cv, rel, reqs] = await Promise.allSettled([
            api.getCurrentVersion(), api.getUpdaterReleases(), api.getUpgradeRequests(),
        ]);
        if (cv.status === 'fulfilled') setCurrent(cv.value);
        if (rel.status === 'fulfilled') { setReleases(rel.value.releases); setUpdater(rel.value.updater); }
        if (reqs.status === 'fulfilled') {
            setRequests(reqs.value.requests);
            setUpdater(reqs.value.updater);
            const a = reqs.value.requests.find(r => IN_FLIGHT_UPGRADE_STATUSES.includes(r.status))
                ?? reqs.value.requests.find(r => ACTIVE_UPGRADE_STATUSES.includes(r.status));
            if (a) {
                try { setActive(await api.getUpgradeRequest(a.id)); } catch { setActive(a); }
            } else {
                setActive(null);
            }
        }
        const failed = [cv, rel, reqs].find(r => r.status === 'rejected') as PromiseRejectedResult | undefined;
        setError(failed ? (failed.reason?.message || 'Could not load version information') : null);
        setLoaded(true);
    }, []);

    useEffect(() => { load(); }, [load]);

    // A live step list: poll while the updater is working on something.
    const inFlight = !!active && IN_FLIGHT_UPGRADE_STATUSES.includes(active.status);
    const lastStatus = useRef<string | null>(null);
    useEffect(() => {
        if (!inFlight) return;
        const t = setInterval(load, POLL_MS);
        return () => clearInterval(t);
    }, [inFlight, load]);
    useEffect(() => {
        const key = active ? `${active.id}:${active.status}` : null;
        if (lastStatus.current && key && lastStatus.current !== key && active) {
            announce(`${describe(active)}: ${STATUS_WORDS[active.status]?.label ?? active.status}.`);
        }
        lastStatus.current = key;
    }, [active, announce]);

    const twoPerson = updater?.require_two_person_approval ?? true;
    const connected = !!updater?.connected;
    const pending = useMemo(() => requests.filter(r => r.status === 'pending_approval' || r.status === 'approved'), [requests]);
    const history = useMemo(() => requests.filter(r => !ACTIVE_UPGRADE_STATUSES.includes(r.status)), [requests]);
    const upgradeLaneBusy = requests.some(r => r.action !== 'restart' && ACTIVE_UPGRADE_STATUSES.includes(r.status));

    const openForm = (action: UpgradeAction, tag: string | null) => {
        setForm({ action, tag });
        setReason('');
        setSchedule('');
        setAllowDestructive(false);
        setError(null);
        setMessage(null);
    };

    const submit = async () => {
        if (!form) return;
        if (reason.trim().length < 3) {
            setError('Give a reason: it goes to every admin and into the audit log.');
            return;
        }
        setBusy('submit');
        setError(null);
        try {
            const created = await api.createUpgradeRequest({
                action: form.action, target_tag: form.tag, reason: reason.trim(),
                scheduled_for: schedule ? new Date(schedule).toISOString() : null,
                allow_destructive: form.action === 'upgrade' ? allowDestructive : false,
            });
            setForm(null);
            setMessage(created.status === 'pending_approval'
                ? `${describe(created)} requested. Another admin must approve it.`
                : `${describe(created)} requested. The updater will pick it up ${created.scheduled_for ? 'at the scheduled time' : 'within about a minute'}.`);
            await load();
        } catch (e: any) {
            setError(e?.message || 'The request was not filed');
        } finally {
            setBusy(null);
        }
    };

    const act = async (r: UpgradeRequestRecord, kind: 'approve' | 'cancel' | 'fail') => {
        setBusy(`${kind}-${r.id}`);
        setError(null);
        const word = kind === 'approve' ? 'approved' : kind === 'cancel' ? 'cancelled' : 'marked failed';
        try {
            const out = kind === 'approve' ? await api.approveUpgradeRequest(r.id)
                : kind === 'cancel' ? await api.cancelUpgradeRequest(r.id)
                    : await api.markUpgradeRequestFailed(r.id);
            setMessage(`${describe(out)}: ${word}.`);
            await load();
        } catch (e: any) {
            setError(e?.message || `The request was not ${word}`);
        } finally {
            setBusy(null);
        }
    };

    const toggleTwoPerson = async (on: boolean) => {
        setBusy('settings');
        setError(null);
        try {
            setUpdater(await api.setUpgradeSettings(on));
            setMessage(on ? 'Two-person approval is on.' : 'Two-person approval is off: one admin can now upgrade this instance.');
            await load();
        } catch (e: any) {
            setError(e?.message || 'The setting did not save');
        } finally {
            setBusy(null);
        }
    };

    const toggleSteps = async (r: UpgradeRequestRecord) => {
        if (expanded[r.id]) {
            const next = { ...expanded };
            delete next[r.id];
            setExpanded(next);
            return;
        }
        try {
            const d = await api.getUpgradeRequest(r.id);
            setExpanded(prev => ({ ...prev, [r.id]: d }));
        } catch (e: any) {
            setError(e?.message || 'Could not load the step log');
        }
    };

    const formRelease = form?.tag ? releases.find(x => x.tag === form.tag) : null;
    const reasonId = `${ids}-reason`;
    const scheduleId = `${ids}-schedule`;
    const destructiveId = `${ids}-destructive`;

    return (
        <div className="space-y-4 text-sm text-white">
            {/* Current */}
            <section aria-labelledby={`${ids}-current`} className="rounded-xl bg-white/5 border border-white/10 p-4">
                <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                        <h3 id={`${ids}-current`} className="text-xs uppercase tracking-wider text-white/50">Running now</h3>
                        <p className="font-mono text-lg">{current?.display ?? '…'}</p>
                        <dl className="mt-2 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-xs">
                            <dt className="text-white/50">Git SHA</dt><dd className="font-mono break-all">{current?.git_sha || 'not stamped'}</dd>
                            <dt className="text-white/50">Backend digest</dt><dd className="font-mono break-all" title={current?.backend_digest ?? undefined}>{shortDigest(current?.backend_digest)}</dd>
                            <dt className="text-white/50">Frontend digest</dt><dd className="font-mono break-all" title={current?.frontend_digest ?? undefined}>{shortDigest(current?.frontend_digest)}</dd>
                            <dt className="text-white/50">Database version</dt><dd className="font-mono">{current?.db_revision || 'unknown'}</dd>
                        </dl>
                    </div>
                    <button type="button" className="btn-outline text-xs" onClick={load} aria-label="Refresh version information">
                        <RefreshCw className="w-3.5 h-3.5" aria-hidden="true" />
                    </button>
                </div>
                <p className="mt-3 text-xs text-white/55">
                    {connected
                        ? <>Updater {updater?.version ? `v${updater.version} ` : ''}last checked in {when(updater?.last_seen_at)}.</>
                        : 'No updater has checked in from this server.'}
                </p>
            </section>

            {error && (
                <div className="p-2.5 bg-red-500/10 border border-red-500/30 rounded-lg text-red-300 text-xs flex items-start gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" aria-hidden="true" />
                    <span>{error}</span>
                </div>
            )}
            {message && (
                <div className="p-2.5 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-300 text-xs flex items-start gap-1.5">
                    <Check className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" aria-hidden="true" />
                    <span>{message}</span>
                </div>
            )}

            {managed ? (
                <p role="note" className="text-xs text-white/70 bg-white/5 border border-white/10 rounded-lg p-3">
                    Upgrades for this town come from your state&apos;s hosting platform, so this panel is read-only.
                </p>
            ) : loaded && !connected ? (
                <section aria-labelledby={`${ids}-none`} className="rounded-xl border border-amber-400/30 bg-amber-500/10 p-4 space-y-3">
                    <h3 id={`${ids}-none`} className="font-semibold flex items-center gap-2">
                        <Terminal className="w-4 h-4" aria-hidden="true" /> No updater connected
                    </h3>
                    <p className="text-xs text-white/75">
                        Upgrades run on the server, by the Pinpoint updater, never from this web app. Install it,
                        create a token below, and register this instance. <a className="underline text-indigo-200" href={INSTALL_DOCS_URL} target="_blank" rel="noopener noreferrer">Install the updater<ExternalLink className="inline w-3 h-3 ml-0.5" aria-hidden="true" /><span className="sr-only"> (opens in a new tab)</span></a>
                    </p>
                    <CommandLineSteps />
                </section>
            ) : connected ? (
                <>
                    {/* Active request with its live step list */}
                    {active && (
                        <section aria-labelledby={`${ids}-active`} className="rounded-xl bg-white/5 border border-white/10 p-4 space-y-3">
                            <div className="flex flex-wrap items-center gap-2">
                                <h3 id={`${ids}-active`} className="font-semibold">#{active.id} {describe(active)}</h3>
                                <RequestStatusChip status={active.status} />
                                {inFlight && <Loader2 className="w-3.5 h-3.5 animate-spin text-white/60" aria-hidden="true" />}
                            </div>
                            <p className="text-xs text-white/60">Requested by {active.requested_by} {when(active.requested_at)}: “{active.reason}”</p>
                            {(inFlight || (active.steps && active.steps.length > 0)) && <StepList steps={active.steps} live={inFlight} />}
                            {active.can_mark_failed && (
                                <div className="flex flex-wrap items-center gap-2 pt-1">
                                    <button type="button" className="btn-outline text-xs" onClick={() => act(active, 'fail')} disabled={busy !== null}>
                                        Mark failed
                                    </button>
                                    <span className="text-xs text-white/50">
                                        Only if the updater has stopped{active.last_report_at ? ` (last report ${when(active.last_report_at)})` : ''}. This doesn’t stop anything on the server. If the updater reports back later, that report is ignored. A run that stops reporting fails on its own after its time limit.
                                    </span>
                                </div>
                            )}
                        </section>
                    )}

                    {/* Pending approvals and queued requests */}
                    {pending.length > 0 && (
                        <section aria-labelledby={`${ids}-pending`} className="space-y-2">
                            <h3 id={`${ids}-pending`} className="text-xs uppercase tracking-wider text-white/50">Waiting</h3>
                            {pending.map(r => {
                                const blockedId = `${ids}-blocked-${r.id}`;
                                return (
                                    <div key={r.id} className="rounded-lg border border-white/10 bg-white/5 p-3 space-y-2">
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span className="font-medium">#{r.id} {describe(r)}</span>
                                            <RequestStatusChip status={r.status} />
                                            {r.allow_destructive && <Chip tone="danger" icon={AlertTriangle}>Destructive migration allowed</Chip>}
                                            {r.scheduled_for && <Chip tone="info">Scheduled {when(r.scheduled_for)}</Chip>}
                                        </div>
                                        <p className="text-xs text-white/60">By {r.requested_by} {when(r.requested_at)}: “{r.reason}”{r.approved_by ? ` · approved by ${r.approved_by}` : ''}</p>
                                        <div className="flex flex-wrap items-center gap-2">
                                            {r.status === 'pending_approval' && (
                                                <button type="button" className="btn-outline text-xs" onClick={() => act(r, 'approve')}
                                                    disabled={!r.can_approve || busy !== null}
                                                    aria-describedby={r.approve_blocked_reason ? blockedId : undefined}>
                                                    <ShieldCheck className="w-3.5 h-3.5" aria-hidden="true" /><span className="ml-1">Approve</span>
                                                </button>
                                            )}
                                            {r.can_cancel && (
                                                <button type="button" className="btn-outline text-xs" onClick={() => act(r, 'cancel')} disabled={busy !== null}>
                                                    Cancel
                                                </button>
                                            )}
                                            {r.status === 'pending_approval' && r.approve_blocked_reason && (
                                                <span id={blockedId} className="text-xs text-amber-200/90">{r.approve_blocked_reason}</span>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </section>
                    )}

                    {/* Releases */}
                    <section aria-labelledby={`${ids}-releases`} className="space-y-2">
                        <div className="flex items-center justify-between">
                            <h3 id={`${ids}-releases`} className="text-xs uppercase tracking-wider text-white/50">Signed releases</h3>
                            <button type="button" className="btn-outline text-xs" onClick={() => openForm('rollback', null)}
                                disabled={upgradeLaneBusy || busy !== null}>
                                <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" /><span className="ml-1">Request rollback</span>
                            </button>
                        </div>
                        {releases.length === 0 && <p className="text-xs text-white/50">The updater has not reported any releases yet.</p>}
                        {releases.map(r => (
                            <div key={r.tag} className="rounded-lg border border-white/10 bg-white/5 p-3 space-y-2">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="font-mono font-medium">{r.tag}</span>
                                    {r.name && r.name !== r.tag && <span className="text-white/60 text-xs">{r.name}</span>}
                                    {r.published_at && <span className="text-white/40 text-xs">{new Date(r.published_at).toLocaleDateString()}</span>}
                                </div>
                                <ReleaseChips r={r} />
                                {r.notes && (
                                    <details className="text-xs">
                                        <summary className="cursor-pointer text-white/70">Release notes</summary>
                                        <div className="mt-1 whitespace-pre-line text-white/65 max-h-60 overflow-y-auto">{r.notes}</div>
                                        {r.url && <a className="underline text-indigo-300" href={r.url} target="_blank" rel="noopener noreferrer">Full release<span className="sr-only"> (opens in a new tab)</span></a>}
                                    </details>
                                )}
                                <div className="flex flex-wrap items-center gap-2">
                                    <button type="button" className="btn-outline text-xs" onClick={() => openForm('upgrade', r.tag)}
                                        disabled={!r.requestable || upgradeLaneBusy || busy !== null}
                                        aria-label={`Request upgrade to ${r.tag}`}>
                                        <Package className="w-3.5 h-3.5" aria-hidden="true" /><span className="ml-1">Request upgrade</span>
                                    </button>
                                    {!r.requestable && r.refusal && <span className="text-xs text-white/50">{r.refusal}</span>}
                                </div>
                            </div>
                        ))}
                    </section>

                    {/* Request form */}
                    {form && (
                        <section aria-labelledby={`${ids}-form`} className="rounded-xl border border-indigo-400/30 bg-indigo-500/10 p-4 space-y-3">
                            <h3 id={`${ids}-form`} className="font-semibold">{form.action === 'upgrade' ? `Request upgrade to ${form.tag}` : 'Request rollback to the previous release'}</h3>
                            <p className="text-xs text-white/65">
                                {twoPerson ? 'A different admin must approve this before it runs. ' : ''}
                                Every admin is emailed. The updater takes a verified backup first and rolls back automatically if the new version is unhealthy.
                            </p>
                            <div>
                                <label htmlFor={reasonId} className="block text-xs text-white/70 mb-1">Reason (required)</label>
                                <textarea id={reasonId} required value={reason} onChange={e => setReason(e.target.value)} rows={2} maxLength={2000}
                                    className="w-full bg-white/10 border border-white/20 rounded-lg px-3 py-2 text-white text-sm" />
                            </div>
                            <div>
                                <label htmlFor={scheduleId} className="block text-xs text-white/70 mb-1">Run at (optional, your local time)</label>
                                <input id={scheduleId} type="datetime-local" value={schedule} onChange={e => setSchedule(e.target.value)}
                                    className="bg-white/10 border border-white/20 rounded-lg px-3 py-1.5 text-white text-sm" />
                            </div>
                            {form.action === 'upgrade' && (
                                <div className="rounded-lg border border-red-400/30 bg-red-500/10 p-3 space-y-1">
                                    <div className="flex items-start gap-2">
                                        <Checkbox id={destructiveId} checked={allowDestructive}
                                            onChange={e => setAllowDestructive(e.target.checked)} size="sm" />
                                        <label htmlFor={destructiveId} className="text-xs font-medium">Allow a destructive migration</label>
                                    </div>
                                    <p className="text-xs text-red-200/90">
                                        Leave this off unless a previous attempt stopped “on hold: destructive migration”. A destructive
                                        migration drops or rewrites data and cannot be rolled back without restoring the backup.
                                        {formRelease?.min_db_revision ? ` This release needs database version ${formRelease.min_db_revision} or later.` : ''}
                                    </p>
                                </div>
                            )}
                            <div className="flex gap-2">
                                <button type="button" className="btn-outline text-sm" onClick={submit} disabled={busy !== null}>
                                    {busy === 'submit' && <Loader2 className="w-4 h-4 animate-spin mr-1" aria-hidden="true" />}
                                    Submit request
                                </button>
                                <button type="button" className="btn-outline text-sm" onClick={() => setForm(null)}>Back</button>
                            </div>
                        </section>
                    )}

                    {/* History */}
                    {history.length > 0 && (
                        <section aria-labelledby={`${ids}-history`} className="space-y-2">
                            <h3 id={`${ids}-history`} className="text-xs uppercase tracking-wider text-white/50">History</h3>
                            <ul className="space-y-2">
                                {history.map(r => (
                                    <li key={r.id} className="rounded-lg border border-white/10 bg-white/[0.03] p-3 space-y-1.5">
                                        <div className="flex flex-wrap items-center gap-2">
                                            <span className="font-medium">#{r.id} {describe(r)}</span>
                                            <RequestStatusChip status={r.status} />
                                            <span className="text-xs text-white/40">{when(r.finished_at || r.requested_at)}</span>
                                        </div>
                                        <p className="text-xs text-white/55">
                                            {r.requested_by}{r.approved_by && r.approved_by !== r.requested_by ? `, approved by ${r.approved_by}` : ''}
                                            {r.cancelled_by ? `, cancelled by ${r.cancelled_by}` : ''}: “{r.reason}”
                                        </p>
                                        {r.outcome_summary && <p className="text-xs text-white/70">{r.outcome_summary}</p>}
                                        {r.status !== 'cancelled' && (
                                            <button type="button" className="text-xs underline text-white/60" aria-expanded={!!expanded[r.id]} onClick={() => toggleSteps(r)}>
                                                {expanded[r.id] ? 'Hide steps' : 'Show steps'}
                                            </button>
                                        )}
                                        {expanded[r.id] && <StepList steps={expanded[r.id].steps} />}
                                    </li>
                                ))}
                            </ul>
                        </section>
                    )}

                    <label className="flex !items-start gap-2 text-xs text-white/70">
                        <Checkbox checked={twoPerson} disabled={busy !== null}
                            onChange={e => toggleTwoPerson(e.target.checked)} size="sm" />
                        <span>Require a second admin to approve upgrades and rollbacks (recommended). Restarts need one admin. Changes to this setting are audited.</span>
                    </label>
                </>
            ) : null}

            {!managed && (
                <AccordionSection title="Updater connection" subtitle="Tokens the host updater uses" icon={KeyRound} defaultOpen={loaded && !connected}>
                    <UpdaterTokens onChange={load} />
                </AccordionSection>
            )}
        </div>
    );
}

/* ------------------------------------------------------------------------ */
/* Sidebar summary                                                            */
/* ------------------------------------------------------------------------ */

export default function VersionSwitcher() {
    const [current, setCurrent] = useState<CurrentVersion | null>(null);
    const [summary, setSummary] = useState<{ updater: UpdaterState; active: UpgradeRequestRecord | null } | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [open, setOpen] = useState(false);
    const [managed, setManaged] = useState(false);
    const trigger = useRef<HTMLButtonElement>(null);
    const announce = useOptionalAnnounce();

    useEffect(() => { if (error) announce(error, 'assertive'); }, [error, announce]);

    const load = useCallback(async () => {
        const [cv, reqs, cfg] = await Promise.allSettled([api.getCurrentVersion(), api.getUpgradeRequests(), api.getSystemConfig()]);
        if (cv.status === 'fulfilled') setCurrent(cv.value);
        if (cfg.status === 'fulfilled') setManaged(!!cfg.value?.managed_mode);
        if (reqs.status === 'fulfilled') {
            const active = reqs.value.requests.find(r => ACTIVE_UPGRADE_STATUSES.includes(r.status)) ?? null;
            setSummary({ updater: reqs.value.updater, active });
        }
        const failed = [cv, reqs].find(r => r.status === 'rejected') as PromiseRejectedResult | undefined;
        setError(failed ? (failed.reason?.message || 'Could not load version information') : null);
    }, []);
    useEffect(() => { load(); }, [load]);

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2 min-w-0">
                <div className="w-8 h-8 rounded-lg bg-indigo-500/20 flex items-center justify-center flex-shrink-0">
                    <GitBranch className="w-4 h-4 text-indigo-400" aria-hidden="true" />
                </div>
                <div className="min-w-0">
                    <p className="text-xs text-white/50">Current</p>
                    <p className="font-mono text-sm text-white font-medium truncate">{current?.display || '…'}</p>
                </div>
            </div>
            {summary?.active ? (
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-white/70">
                    <span className="truncate">{describe(summary.active)}</span>
                    <RequestStatusChip status={summary.active.status} />
                </div>
            ) : summary && !summary.updater.connected && !managed ? (
                <p className="text-xs text-amber-200/80">No updater connected</p>
            ) : null}
            {error && <p className="text-xs text-red-300 break-words">{error}</p>}
            <button ref={trigger} type="button" className="btn-outline w-full text-sm justify-center" onClick={() => setOpen(true)}>
                <Package className="w-3.5 h-3.5" aria-hidden="true" /><span className="ml-1.5">Version control</span>
            </button>
            <Modal isOpen={open} onClose={() => { setOpen(false); load(); }} title="Version Control" size="lg" triggerRef={trigger as RefObject<HTMLElement>}>
                <VersionControlPanel managed={managed} />
            </Modal>
        </div>
    );
}

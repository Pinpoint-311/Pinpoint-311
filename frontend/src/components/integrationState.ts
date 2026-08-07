/**
 * The arithmetic behind the town-systems cards, with no JSX and no fetching.
 *
 * Four decisions that were being made inline, each of which was wrong in a way
 * a rendered-component test would not have caught:
 *
 *   - which required fields are still empty. This checked config fields only,
 *     and no credential field in the registry was marked required, so an
 *     all-blank Accela save succeeded and failed later on a resident's report;
 *   - what a save actually sends. Blank meant "keep", so a wrong jurisdiction_id
 *     could never be blanked -- it stayed in every outbound payload forever;
 *   - whether a connector may be switched on without a warning;
 *   - which of the health rows belong to the town's own connections.
 *
 * Pure, so each can be checked directly rather than through a mounted page.
 */

import type { IntegrationConfig, IntegrationPlatform, IntegrationTestResult } from '../services/api';
import type { CapabilityState } from './capabilityUI';

/** One connector's row from GET /api/system/connectors/health. */
export interface ConnectorHealthRow {
    connector: string;
    status: string;
    summary?: string;
    last_result?: string | null;
    last_error?: string | null;
    verifiable?: boolean | null;
    alerts_muted_until?: string | null;
}

/** The health row a connection reports under. Shared with the backend's
 *  `health_key`, and with the push path, so one connector has one row. */
export const healthKey = (platform: string) => `govtech:${platform}`;

/**
 * What a connection is actually doing, in the same vocabulary as a capability.
 *
 * Deliberately the same shape as `capabilityState` in ServiceProviders, because
 * these are the same question asked about a different vendor, and the town-system
 * cards had been answering a different one: `enabled && last_sync_status !==
 * 'error'` drew a green "Connected" pill. Both halves of that are wrong in the
 * direction this whole health system exists to prevent -- `enabled` is a fact
 * about our own database that stays true through a revoked key, and
 * `last_sync_status` is the outcome of the last *poll*, which is null forever on
 * a push-only connection.
 *
 * `unchecked` stays its own answer. A connection nobody has exercised is not
 * healthy and not broken, and collapsing it into either is how an expired
 * credential keeps a green tick for a month.
 */
export function connectionState(
    existing: IntegrationConfig | undefined,
    health?: ConnectorHealthRow,
    sessionResult?: IntegrationTestResult | null,
): CapabilityState | null {
    if (!existing) return 'unset';
    if (!existing.enabled) return 'unset';

    // A check run on this page is fresher than the stored row. Same precedence
    // as capabilityState: the stored value is a fallback for a fresh page, not a
    // second opinion -- otherwise a connection that just passed would keep being
    // reported as broken by the row the failure wrote.
    if (sessionResult) {
        if (!sessionResult.ok) return 'failing';
        return sessionResult.verified === false ? 'unverifiable' : 'working';
    }

    if (health?.verifiable === false) return 'unverifiable';
    if (!health || health.status === 'unknown' || health.status === 'stale') return 'unchecked';
    return health.status === 'working' ? 'working' : 'failing';
}

/** The pill's words, where "unset" covers two different situations. */
export function connectionStateLabel(
    existing: IntegrationConfig | undefined,
    state: CapabilityState | null,
): string | undefined {
    if (state !== 'unset') return undefined;
    return existing ? 'Turned off' : 'Not connected';
}

/** A vendor error is unbounded remote text; the card has room for a line of it. */
export const ERROR_PREVIEW_CHARS = 160;

export function truncate(text: string, max = ERROR_PREVIEW_CHARS): string {
    return text.length > max ? `${text.slice(0, max).trimEnd()}…` : text;
}

/** Whether a field already holds a stored value, so blank means "keep it". */
export function alreadyStored(
    existing: IntegrationConfig | undefined,
    key: string,
    isCredential: boolean,
    cleared: ReadonlySet<string> = new Set(),
): boolean {
    if (!existing) return false;
    if (isCredential) return existing.configured_credentials.includes(key);
    return (existing.config as Record<string, unknown>)[key] !== undefined && !cleared.has(key);
}

/**
 * Required fields still empty, by label.
 *
 * Credentials count. A field that already has a stored value is satisfied by
 * that value -- the wizard shows blanks for secrets it will not re-display, and
 * treating those as missing would make every re-save of a working connection
 * demand the password again.
 */
export function requiredMissing(
    platform: IntegrationPlatform,
    values: Record<string, string>,
    existing: IntegrationConfig | undefined,
    cleared: ReadonlySet<string> = new Set(),
): string[] {
    const empty = (key: string) => !(values[key] || '').trim();
    return [
        ...platform.config_fields
            .filter(f => f.required)
            .filter(f => empty(f.key) && !alreadyStored(existing, f.key, false, cleared)),
        ...platform.credential_fields
            .filter(f => f.required)
            .filter(f => empty(f.key) && !alreadyStored(existing, f.key, true, cleared)),
    ].map(f => f.label);
}

/**
 * The credentials and config a save should send.
 *
 * Values are trimmed: a stray copy-paste space is the most common reason a
 * correct key or URL is rejected by the vendor. A key the admin asked to clear
 * is sent as an explicit null, which the backend removes -- blank still means
 * "leave it alone", so clearing has to be asked for by name.
 */
export function buildSavePayload(
    platform: IntegrationPlatform,
    values: Record<string, string>,
    cleared: ReadonlySet<string> = new Set(),
): { credentials: Record<string, string>; config: Record<string, unknown> } {
    const credentials: Record<string, string> = {};
    const config: Record<string, unknown> = {};
    platform.credential_fields.forEach(f => {
        const v = (values[f.key] || '').trim();
        if (v) credentials[f.key] = v;
    });
    platform.config_fields.forEach(f => {
        const v = (values[f.key] ?? '').trim();
        if (v !== '') config[f.key] = v;
        else if (cleared.has(f.key)) config[f.key] = null;
    });
    return { credentials, config };
}

/**
 * Whether turning this connector on deserves a confirmation first.
 *
 * The wizard promises a connection stays off until a check passes; the toggle
 * bypassed that, so a connector whose last check failed could be switched on
 * with one click and start dropping resident reports. Only the on direction
 * asks -- switching something off is always allowed and always safe.
 */
export function needsEnableConfirmation(
    existing: Pick<IntegrationConfig, 'enabled' | 'last_sync_status'>,
    lastResult?: { ok: boolean } | null,
): boolean {
    if (existing.enabled) return false;
    return existing.last_sync_status === 'error' || (!!lastResult && !lastResult.ok);
}

/**
 * The town's own govtech connections, out of the whole connector-health map.
 *
 * `unknown` means nobody has looked and `stale` means not lately -- neither is
 * evidence of a fault, and badging them as one produces a number that never
 * reaches zero on a town whose sweep has not run yet.
 *
 * Only platforms in `enabledPlatforms` count at all. A health row outlives the
 * integration that wrote it: the backend never decays a failing row, and the
 * sweep only tests enabled integrations, so nothing ever writes over the last
 * failure of a connector that was disabled or deleted. Without the cross-check
 * the badge stayed red forever for a connection the town had already turned
 * off -- which is the fix, not the fault.
 */
export function townSystemHealth(
    health: Record<string, string>,
    enabledPlatforms: ReadonlySet<string>,
): {
    all: string[];
    broken: string[];
} {
    const all: string[] = [];
    const broken: string[] = [];
    for (const [connector, status] of Object.entries(health || {})) {
        if (!connector.startsWith('govtech:')) continue;
        const name = connector.slice('govtech:'.length);
        if (!enabledPlatforms.has(name)) continue;
        all.push(name);
        if (status === 'failing' || status === 'down') broken.push(name);
    }
    return { all, broken };
}

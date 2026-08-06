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

import type { IntegrationConfig, IntegrationPlatform } from '../services/api';

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
 */
export function townSystemHealth(health: Record<string, string>): {
    all: string[];
    broken: string[];
} {
    const all: string[] = [];
    const broken: string[] = [];
    for (const [connector, status] of Object.entries(health || {})) {
        if (!connector.startsWith('govtech:')) continue;
        const name = connector.slice('govtech:'.length);
        all.push(name);
        if (status === 'failing' || status === 'down') broken.push(name);
    }
    return { all, broken };
}

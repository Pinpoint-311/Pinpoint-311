import { describe, it, expect } from 'vitest';

import {
    alreadyStored,
    connectionState,
    connectionStateLabel,
    healthKey,
    buildSavePayload,
    needsEnableConfirmation,
    requiredMissing,
    townSystemHealth,
    truncate,
} from './integrationState';
import type { IntegrationConfig, IntegrationPlatform } from '../services/api';

/**
 * The card decisions that were being made wrong.
 *
 * Each of these describes something a clerk could do, and what the software did
 * about it: save a connection with every credential box empty and be told it
 * worked; try to remove a wrong setting and find it permanent; switch a broken
 * connector on with one click.
 */

const accela = {
    platform: 'accela',
    name: 'Accela',
    capabilities: ['push', 'pull'],
    credential_fields: [
        { key: 'client_id', label: 'Client ID', required: true },
        { key: 'client_secret', label: 'Client Secret', secret: true, required: true },
        { key: 'note', label: 'Optional note' },
    ],
    config_fields: [
        { key: 'agency_name', label: 'Agency Name', required: true },
        { key: 'jurisdiction_id', label: 'Jurisdiction ID' },
    ],
} as unknown as IntegrationPlatform;

const saved = (over: Partial<IntegrationConfig> = {}) => ({
    id: 1,
    platform: 'accela',
    enabled: false,
    configured_credentials: [],
    config: {},
    last_sync_status: null,
    ...over,
} as unknown as IntegrationConfig);

// ---------------------------------------------------------------------------
// Required fields
// ---------------------------------------------------------------------------

describe('what still has to be filled in', () => {
    it('counts empty credentials, not only empty settings', () => {
        /* The bug: this checked config_fields only, and no credential field in
         * the registry carried `required`. An all-blank Accela save therefore
         * succeeded -- creating a connection with no client id, no secret and no
         * password, which failed on the first resident report instead. */
        const missing = requiredMissing(accela, {}, undefined);
        expect(missing).toContain('Client ID');
        expect(missing).toContain('Client Secret');
        expect(missing).toContain('Agency Name');
    });

    it('leaves optional fields alone', () => {
        expect(requiredMissing(accela, {}, undefined)).not.toContain('Optional note');
        expect(requiredMissing(accela, {}, undefined)).not.toContain('Jurisdiction ID');
    });

    it('treats whitespace as empty', () => {
        expect(requiredMissing(accela, { client_id: '   ' }, undefined)).toContain('Client ID');
    });

    it('accepts a credential that is already stored', () => {
        /* The wizard never re-displays a saved secret, so a blank box means
         * "keep it". Demanding the password again on every edit of a working
         * connection would make changing an agency name a credential hunt. */
        const existing = saved({ configured_credentials: ['client_id', 'client_secret'] });
        const missing = requiredMissing(accela, {}, existing);
        expect(missing).not.toContain('Client ID');
        expect(missing).not.toContain('Client Secret');
    });

    it('accepts a setting that is already stored', () => {
        const existing = saved({ config: { agency_name: 'SPRINGFIELD' } });
        expect(requiredMissing(accela, {}, existing)).not.toContain('Agency Name');
    });

    it('asks again for a stored setting the admin just cleared', () => {
        const existing = saved({ config: { agency_name: 'SPRINGFIELD' } });
        const missing = requiredMissing(accela, {}, existing, new Set(['agency_name']));
        expect(missing).toContain('Agency Name');
    });

    it('is satisfied once everything is typed', () => {
        expect(requiredMissing(accela, {
            client_id: 'id', client_secret: 'secret', agency_name: 'SPRINGFIELD',
        }, undefined)).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// What a save sends
// ---------------------------------------------------------------------------

describe('the payload a save sends', () => {
    it('trims values', () => {
        /* A stray copy-paste space is the most common reason a correct key is
         * rejected by the vendor, and the rejection says nothing about spaces. */
        const { credentials, config } = buildSavePayload(accela, {
            client_id: '  id  ', agency_name: ' SPRINGFIELD ',
        });
        expect(credentials.client_id).toBe('id');
        expect(config.agency_name).toBe('SPRINGFIELD');
    });

    it('omits untouched fields so they keep their stored values', () => {
        const { credentials, config } = buildSavePayload(accela, { client_id: 'id' });
        expect(credentials).toEqual({ client_id: 'id' });
        expect(config).toEqual({});
    });

    it('sends an explicit null for a setting the admin cleared', () => {
        /* The backend merges config and the wizard skipped empty strings, so
         * between them a wrong jurisdiction_id could never be blanked -- it went
         * out in every payload forever. A null is the delete. */
        const { config } = buildSavePayload(accela, {}, new Set(['jurisdiction_id']));
        expect(config).toHaveProperty('jurisdiction_id', null);
    });

    it('prefers a retyped value over a clear', () => {
        /* Changing your mind by typing has to win, or the field would be wiped
         * by a Clear pressed earlier in the same visit. */
        const { config } = buildSavePayload(
            accela, { jurisdiction_id: 'springfield.gov' }, new Set(['jurisdiction_id']),
        );
        expect(config.jurisdiction_id).toBe('springfield.gov');
    });

    it('never sends a null for a credential', () => {
        /* Clearing is offered for settings only. A blanked credential would
         * leave a connection authenticated by nothing. */
        const { credentials } = buildSavePayload(accela, {}, new Set(['client_secret']));
        expect(credentials).toEqual({});
    });
});

// ---------------------------------------------------------------------------
// Stored-value rule
// ---------------------------------------------------------------------------

describe('whether a field already holds something', () => {
    it('reads credentials off the configured list', () => {
        const existing = saved({ configured_credentials: ['client_id'] });
        expect(alreadyStored(existing, 'client_id', true)).toBe(true);
        expect(alreadyStored(existing, 'client_secret', true)).toBe(false);
    });

    it('is false for a connection that does not exist yet', () => {
        expect(alreadyStored(undefined, 'client_id', true)).toBe(false);
    });

    it('counts a stored empty string as stored', () => {
        /* `''` is a value somebody chose. Treating it as absent would make the
         * placeholder show a stale previous value. */
        const existing = saved({ config: { jurisdiction_id: '' } });
        expect(alreadyStored(existing, 'jurisdiction_id', false)).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// The toggle
// ---------------------------------------------------------------------------

describe('turning a connector on', () => {
    it('asks first when the last sync failed', () => {
        /* The wizard promises the connection stays off until a check passes.
         * The toggle bypassed that, so a broken connector could be switched on
         * with one click and start dropping resident reports. */
        expect(needsEnableConfirmation(saved({ last_sync_status: 'error' }))).toBe(true);
    });

    it('asks first when the last check on this page failed', () => {
        expect(needsEnableConfirmation(saved(), { ok: false })).toBe(true);
    });

    it('does not ask when the last check passed', () => {
        expect(needsEnableConfirmation(saved({ last_sync_status: 'success' }), { ok: true })).toBe(false);
    });

    it('does not ask for a connector nothing has tested yet', () => {
        /* Unknown is not failing. Warning here would train people to click
         * through the warning, which is the one outcome that makes it useless. */
        expect(needsEnableConfirmation(saved())).toBe(false);
    });

    it('never asks on the way off', () => {
        /* Switching a broken connector off is the fix, not the risk. */
        expect(needsEnableConfirmation(
            saved({ enabled: true, last_sync_status: 'error' }), { ok: false },
        )).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// Page-level rollup
// ---------------------------------------------------------------------------

describe('the town-systems health rollup', () => {
    const enabled = (...platforms: string[]) => new Set(platforms);

    it('picks out the town\'s own connections', () => {
        const { all, broken } = townSystemHealth({
            'govtech:accela': 'down',
            'govtech:civicplus': 'working',
            email: 'down',
            'system:disk': 'down',
        }, enabled('accela', 'civicplus'));
        expect(all.sort()).toEqual(['accela', 'civicplus']);
        expect(broken).toEqual(['accela']);
    });

    it('does not count unknown or stale as broken', () => {
        /* Nobody has looked, and not lately. Neither is evidence of a fault, and
         * badging them as one produces a number that never reaches zero on a
         * town whose sweep has not run yet. */
        const { all, broken } = townSystemHealth({
            'govtech:accela': 'unknown',
            'govtech:tyler': 'stale',
        }, enabled('accela', 'tyler'));
        expect(all.sort()).toEqual(['accela', 'tyler']);
        expect(broken).toEqual([]);
    });

    it('counts both failing and down', () => {
        const { broken } = townSystemHealth({
            'govtech:accela': 'failing',
            'govtech:tyler': 'down',
        }, enabled('accela', 'tyler'));
        expect(broken.sort()).toEqual(['accela', 'tyler']);
    });

    it('ignores rows whose integration is no longer enabled', () => {
        /* A health row outlives the integration that wrote it: nothing decays a
         * failing row once its connector is disabled or deleted, and the sweep
         * only tests enabled integrations. Counting the orphan kept the badge
         * red forever after the town turned the broken thing off -- which is
         * the fix, not the fault. */
        const { all, broken } = townSystemHealth({
            'govtech:accela': 'down',      // disabled after it broke
            'govtech:seeclickfix': 'down', // deleted entirely
            'govtech:tyler': 'working',
        }, enabled('tyler'));
        expect(all).toEqual(['tyler']);
        expect(broken).toEqual([]);
    });

    it('survives an empty or missing health map', () => {
        expect(townSystemHealth({}, enabled())).toEqual({ all: [], broken: [] });
        expect(townSystemHealth(undefined as never, enabled())).toEqual({ all: [], broken: [] });
    });
});

// ---------------------------------------------------------------------------
// Error text
// ---------------------------------------------------------------------------

describe('clipping a vendor error for the card', () => {
    it('leaves a short message alone', () => {
        expect(truncate('HTTP 401 — invalid_client')).toBe('HTTP 401 — invalid_client');
    });

    it('clips a long one and says it clipped', () => {
        const clipped = truncate('x'.repeat(400));
        expect(clipped.length).toBeLessThan(400);
        expect(clipped.endsWith('…')).toBe(true);
    });

    it('does not leave a space before the ellipsis', () => {
        expect(truncate('abcd efgh', 5)).toBe('abcd…');
    });
});


// ---------------------------------------------------------------------------
// The badge, in the same vocabulary as a capability card
// ---------------------------------------------------------------------------

describe('what a connection card says it is doing', () => {
    const on = (over = {}) => saved({ enabled: true, ...over });
    const row = (status: string, extra = {}) =>
        ({ connector: 'govtech:accela', status, ...extra });

    it('reports a platform with no connection as unset', () => {
        expect(connectionState(undefined)).toBe('unset');
        expect(connectionStateLabel(undefined, 'unset')).toBe('Not connected');
    });

    it('distinguishes turned-off from never-connected', () => {
        /* Both are "unset" as far as health goes, and they are completely
         * different situations for the person reading the card. */
        expect(connectionState(saved())).toBe('unset');
        expect(connectionStateLabel(saved(), 'unset')).toBe('Turned off');
    });

    it('does not call a connection working just because it is switched on', () => {
        /* The bug this replaces: the pill was `enabled && last_sync_status !==
         * "error"`, so a connection whose credentials were revoked months ago
         * showed a green "Connected" -- and on a push-only connection
         * last_sync_status is null forever, so it never went any other way. */
        expect(connectionState(on({ last_sync_status: null }))).toBe('unchecked');
    });

    it('reports working only when a real call succeeded', () => {
        expect(connectionState(on(), row('working'))).toBe('working');
    });

    it('reports failing when the last real call failed', () => {
        expect(connectionState(on(), row('failing'))).toBe('failing');
        expect(connectionState(on(), row('down'))).toBe('failing');
    });

    it('keeps unchecked as its own answer', () => {
        /* A connection nobody has exercised is not healthy and not broken.
         * Collapsing it into either is how an expired credential keeps a green
         * tick for a month. */
        expect(connectionState(on(), row('unknown'))).toBe('unchecked');
        expect(connectionState(on())).toBe('unchecked');
    });

    it('treats stale as unchecked rather than broken', () => {
        /* It alerts, but it is not evidence of a fault -- the sweep simply has
         * not recorded a success lately. Same call the provider cards make. */
        expect(connectionState(on(), row('stale'))).toBe('unchecked');
    });

    it('reports unverifiable where nothing can check the credentials', () => {
        expect(connectionState(on(), row('working', { verifiable: false }))).toBe('unverifiable');
    });

    it('prefers a check run on this page over the stored row', () => {
        /* Otherwise a connection that was just fixed keeps being reported as
         * broken by the row the failure wrote. The stored value is a fallback
         * for a fresh page, not a second opinion. */
        expect(connectionState(on(), row('down'), { ok: true, detail: '' })).toBe('working');
        expect(connectionState(on(), row('working'), { ok: false, detail: '' })).toBe('failing');
    });

    it('carries a this-session unverified result through', () => {
        expect(connectionState(on(), row('working'), { ok: true, detail: '', verified: false }))
            .toBe('unverifiable');
    });

    it('labels only the unset state, leaving the shared pill to name the rest', () => {
        expect(connectionStateLabel(on(), 'working')).toBeUndefined();
        expect(connectionStateLabel(on(), 'failing')).toBeUndefined();
    });

    it('agrees with the backend on the health row name', () => {
        /* One connector, one row. A second spelling would give the card and the
         * push path different rows and show whichever ran last. */
        expect(healthKey('accela')).toBe('govtech:accela');
    });
});

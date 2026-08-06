import { describe, it, expect } from 'vitest';

import {
    alreadyStored,
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
    it('picks out the town\'s own connections', () => {
        const { all, broken } = townSystemHealth({
            'govtech:accela': 'down',
            'govtech:civicplus': 'working',
            email: 'down',
            'system:disk': 'down',
        });
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
        });
        expect(all.sort()).toEqual(['accela', 'tyler']);
        expect(broken).toEqual([]);
    });

    it('counts both failing and down', () => {
        const { broken } = townSystemHealth({
            'govtech:accela': 'failing',
            'govtech:tyler': 'down',
        });
        expect(broken.sort()).toEqual(['accela', 'tyler']);
    });

    it('survives an empty or missing health map', () => {
        expect(townSystemHealth({})).toEqual({ all: [], broken: [] });
        expect(townSystemHealth(undefined as never)).toEqual({ all: [], broken: [] });
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

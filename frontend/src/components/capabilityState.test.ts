import { describe, it, expect } from 'vitest';

import { capabilityState, healthIsAboutCurrentProvider, providerLabel } from './ServiceProviders';

/**
 * Which of the two questions a badge is answering.
 *
 * "Are the credentials stored" is a fact about our own database. It goes true
 * the moment somebody pastes a key and stays true through the key being
 * revoked, the card on file lapsing and the secret expiring. Every version of
 * this page that reported it as health was wrong in the same direction, and the
 * Spotlight layout now sorts on the answer -- so getting it wrong no longer
 * just mislabels a card, it files a broken connector under "healthy" and hides
 * it in a bubble.
 */
// Module scope, so every block below shares one definition of what a health
// row looks like rather than each growing its own.
const health = (status: string, extra: Record<string, unknown> = {}) =>
    ({ connector: 'x', status, consecutive_failures: 0, ...extra }) as never;

describe('capabilityState', () => {

    it('says nothing at all until the catalog has loaded', () => {
        // Not "unset". A page that is merely slow must not accuse a town of
        // having failed to configure something.
        expect(capabilityState(undefined, health('working'))).toBeNull();
    });

    it('is unset when there are no credentials, whatever health says', () => {
        expect(capabilityState({ configured: false }, health('working'))).toBe('unset');
    });

    it('is unchecked when credentials exist but nothing has exercised them', () => {
        expect(capabilityState({ configured: true }, undefined)).toBe('unchecked');
        expect(capabilityState({ configured: true }, health('unknown'))).toBe('unchecked');
    });

    it('treats a stale success as unchecked rather than as working', () => {
        // No successful call in over a week. That is not evidence of health;
        // it is the absence of evidence, and it is exactly the state a revoked
        // key produces on a connector nobody has used.
        expect(capabilityState({ configured: true }, health('stale'))).toBe('unchecked');
    });

    it('reports a live failure as failing', () => {
        expect(capabilityState({ configured: true }, health('failing'))).toBe('failing');
        expect(capabilityState({ configured: true }, health('down'))).toBe('failing');
    });

    it('reports a live success as working', () => {
        expect(capabilityState({ configured: true }, health('working'))).toBe('working');
    });

    it('says "cannot be tested" rather than "not working" when there is no test', () => {
        // A generic HTTP SMS gateway cannot be exercised without sending a real
        // text message, so the backend returns ok:false with recorded:false.
        // Passing that straight through as a failure put a red "Not working"
        // pill on a connector whose own message said it could not be checked --
        // a badge that can never go green, which is the thing this whole page
        // is built around not doing.
        expect(capabilityState({ configured: true, verifiable: false }, health('unknown')))
            .toBe('unverifiable');
    });

    it('does not let a stale health row override "cannot be tested"', () => {
        expect(capabilityState({ configured: true, verifiable: false }, health('down')))
            .toBe('unverifiable');
    });

    it('still reports "not set up" over "cannot be tested"', () => {
        // No credentials is the more actionable of the two, and the only one
        // the clerk can do something about.
        expect(capabilityState({ configured: false, verifiable: false }, undefined)).toBe('unset');
    });

    it('prefers a test run in this session over the stored health row', () => {
        // Pressing "Test now" and watching the card stay green because the
        // nightly sweep last succeeded is the whole reason that button exists.
        expect(capabilityState({ configured: true, verified: false }, health('working'))).toBe('failing');
        expect(capabilityState({ configured: true, verified: true }, health('down'))).toBe('working');
    });

    it('does not let a session test override the absence of credentials', () => {
        expect(capabilityState({ configured: false, verified: true }, health('working'))).toBe('unset');
    });
});

describe('a check result outlives the session that ran it', () => {
    it('remembers "cannot be tested" from the stored health row', () => {
        // Without this the answer lives only in the browser session that ran
        // the test: reload, and the card is back to "not checked yet",
        // inviting another press of a button that can never succeed.
        expect(capabilityState({ configured: true }, health('unknown', { verifiable: false })))
            .toBe('unverifiable');
    });

    it('lets a fresh session result override the stored one', () => {
        // A town that swapped an HTTP gateway for Twilio must not keep being
        // told its text messages cannot be tested.
        expect(capabilityState({ configured: true, verified: true, verifiable: true },
                               health('working', { verifiable: false })))
            .toBe('working');
    });

    it('still puts "not set up" ahead of "cannot be tested"', () => {
        expect(capabilityState({ configured: false }, health('unknown', { verifiable: false })))
            .toBe('unset');
    });

    it('treats an absent flag as unknown rather than as unverifiable', () => {
        // Rows written before the column existed have neither value.
        expect(capabilityState({ configured: true }, health('unknown'))).toBe('unchecked');
    });
});

describe('a verdict belongs to the provider that produced it', () => {
    /* `connector_health` has always carried the provider a result was recorded
     * against and nothing compared it. Live, the text messages card read "There
     * is no way to check http without sending a real text" while SMS_PROVIDER
     * was 'acs' -- a true sentence about the gateway the town had switched away
     * from, shown as the state of the one it is on. The green direction is the
     * same bug and nobody notices it: a passing check on the old provider would
     * have kept the card green for a vendor that had never been tested. */

    it('ignores a stored result recorded against a different provider', () => {
        expect(capabilityState(
            { configured: true, provider: 'acs' },
            health('working', { provider: 'http' }),
        )).toBe('unchecked');
    });

    it('does not carry "cannot be tested" across a provider change', () => {
        // The live case. Azure Communication Services has an endpoint that can
        // be checked; the generic HTTP gateway does not, and its verdict was
        // being shown on the ACS card.
        expect(capabilityState(
            { configured: true, provider: 'acs' },
            health('unknown', { provider: 'http', verifiable: false }),
        )).toBe('unchecked');
    });

    it('does not carry a failure across a provider change either', () => {
        // Switching provider because the old one was broken must not leave the
        // new one red before anything has tried it.
        expect(capabilityState(
            { configured: true, provider: 'twilio' },
            health('down', { provider: 'http' }),
        )).toBe('unchecked');
    });

    it('uses a stored result recorded against the provider in use', () => {
        expect(capabilityState(
            { configured: true, provider: 'twilio' },
            health('working', { provider: 'twilio' }),
        )).toBe('working');
    });

    it('keeps a row that names no provider', () => {
        // Every row written before the column was filled looks like this.
        // Discarding a real verdict is the more expensive of the two mistakes.
        expect(capabilityState(
            { configured: true, provider: 'twilio' },
            health('working'),
        )).toBe('working');
    });

    it('keeps a row when the catalog has not said which provider is current', () => {
        expect(capabilityState(
            { configured: true },
            health('failing', { provider: 'http' }),
        )).toBe('failing');
    });
});

describe('healthIsAboutCurrentProvider', () => {
    it('is false when there is no health row at all', () => {
        expect(healthIsAboutCurrentProvider({ configured: true, provider: 'acs' }, undefined))
            .toBe(false);
    });

    it('is true when both name the same provider', () => {
        expect(healthIsAboutCurrentProvider(
            { provider: 'acs' }, health('working', { provider: 'acs' }),
        )).toBe(true);
    });

    it('is false when they disagree', () => {
        expect(healthIsAboutCurrentProvider(
            { provider: 'acs' }, health('working', { provider: 'http' }),
        )).toBe(false);
    });
});

describe('providerLabel', () => {
    it('uses the vendor name the catalog gives', () => {
        // "acs" is our word for it; "Azure Communication Services" is theirs.
        expect(providerLabel(
            { providers: [{ provider: 'acs', name: 'Azure Communication Services' }] }, 'acs',
        )).toBe('Azure Communication Services');
    });

    it('falls back to the id rather than showing nothing', () => {
        expect(providerLabel({ providers: [] }, 'http')).toBe('http');
    });

    it('has something to say when no provider was recorded', () => {
        expect(providerLabel(null, null)).toBe('the previous provider');
    });
});

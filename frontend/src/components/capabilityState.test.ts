import { describe, it, expect } from 'vitest';

import { capabilityState } from './ServiceProviders';

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
describe('capabilityState', () => {
    const health = (status: string, extra: Record<string, unknown> = {}) =>
        ({ connector: 'x', status, consecutive_failures: 0, ...extra }) as never;

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

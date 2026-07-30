import { describe, expect, it } from 'vitest';

import { diagnosePaste, looksLikePlaceholder } from './SecretField';

/**
 * These exist because of how credential setup actually fails. The clerk pastes
 * something, the field looks correct, they save, and the provider returns a
 * generic "invalid credentials" days later with nothing to go on.
 *
 * Every case here is a paste that is wrong and does not look wrong. The one
 * rule that matters more than any individual check: nothing is ever rewritten
 * automatically. A credential is the worst possible input to silently "help"
 * with — if we strip something that was genuinely part of the key, we convert a
 * visible mistake into an invisible one.
 */

describe('invisible characters', () => {
    // Copying out of a PDF or a vendor docs page brings these along. They are
    // undetectable by eye, which is what makes them the worst case.
    it.each([
        ['zero-width space', '​AIzaSyABC123'],
        ['zero-width non-joiner', 'AIzaSy‌ABC123'],
        ['byte order mark', '﻿AIzaSyABC123'],
        ['non-breaking space', 'AIzaSy ABC123'],
        ['word joiner', 'AIzaSy⁠ABC123'],
    ])('detects and strips a %s', (_label, input) => {
        const problem = diagnosePaste(input)!;
        expect(problem).not.toBeNull();
        expect(problem.fixed).toBe('AIzaSyABC123');
        expect(problem.label).toMatch(/invisible/i);
    });

    it('is reported ahead of anything else, being the only invisible one', () => {
        // Also has surrounding whitespace; the invisible char still wins.
        expect(diagnosePaste('  ​AIzaSy  ')!.label).toMatch(/invisible/i);
    });
});

describe('a whole config line', () => {
    it.each([
        'GOOGLE_MAPS_API_KEY=AIzaSyABC123',
        'GOOGLE_MAPS_API_KEY = AIzaSyABC123',
        'GOOGLE_MAPS_API_KEY: AIzaSyABC123',
    ])('extracts the value from %s', input => {
        const problem = diagnosePaste(input)!;
        expect(problem.fixed).toBe('AIzaSyABC123');
        expect(problem.label).toContain('GOOGLE_MAPS_API_KEY');
    });

    it('names the key it found, so the clerk can confirm it is the right field', () => {
        expect(diagnosePaste('AUTH0_CLIENT_SECRET=shh')!.label).toContain('AUTH0_CLIENT_SECRET');
    });

    it('also unwraps quotes around the extracted value', () => {
        expect(diagnosePaste('SMTP_HOST="smtp.sendgrid.net"')!.fixed).toBe('smtp.sendgrid.net');
    });

    it('leaves a real value containing = alone', () => {
        // Base64 and JWTs end in padding; these are not config lines.
        expect(diagnosePaste('dGhpcyBpcyBhIGtleQ==')).toBeNull();
        expect(diagnosePaste('eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc')).toBeNull();
    });

    it('does not treat a URL with a query string as an assignment', () => {
        expect(diagnosePaste('https://example.gov/oauth?client=abc')).toBeNull();
    });
});

describe('quotes and whitespace', () => {
    it.each(['"secret"', "'secret'", '“secret”', '‘secret’'])('unwraps %s', input => {
        expect(diagnosePaste(input)!.fixed).toBe('secret');
    });

    it('reports a trailing space, which is invisible in a password field', () => {
        const problem = diagnosePaste('AIzaSyABC123 ')!;
        expect(problem.fixed).toBe('AIzaSyABC123');
        expect(problem.label).toMatch(/space|line break/i);
    });

    it('reports a trailing newline from a copied code block', () => {
        expect(diagnosePaste('AIzaSyABC123\n')!.fixed).toBe('AIzaSyABC123');
    });
});

describe('a clean value is left completely alone', () => {
    it.each([
        'AIzaSyD-abc123_XYZ',
        'https://yourorg.us.auth0.com',
        'smtp.sendgrid.net',
        '-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----',
        '{"type":"service_account","project_id":"x"}',
        'sk_live_51ABCdef',
    ])('no complaint about %s', input => {
        expect(diagnosePaste(input)).toBeNull();
    });

    it('says nothing about an empty field', () => {
        expect(diagnosePaste('')).toBeNull();
    });

    it('never returns a fix identical to the input', () => {
        // A no-op "Fix this for me" button would be baffling.
        for (const input of ['​x', 'K_EY=v', '"q"', ' s ']) {
            const problem = diagnosePaste(input);
            if (problem) expect(problem.fixed).not.toBe(input);
        }
    });
});

describe('placeholders left unreplaced', () => {
    it.each(['xxx', 'XXXXXX', 'your-key-here', 'yourorg.auth0.com', 'changeme', 'TODO', '••••', '...'])(
        'flags %s', input => expect(looksLikePlaceholder(input)).toBe(true));

    it.each(['AIzaSyD-abc123', 'smtp.sendgrid.net', 'sk_live_51ABC', 'a'])(
        'does not flag %s', input => expect(looksLikePlaceholder(input)).toBe(false));

    it('says nothing about an empty field', () => {
        expect(looksLikePlaceholder('')).toBe(false);
        expect(looksLikePlaceholder('   ')).toBe(false);
    });
});

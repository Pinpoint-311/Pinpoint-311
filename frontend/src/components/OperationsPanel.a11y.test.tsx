// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * Three ways this panel spoke only to people who could see it:
 *
 *   Restart All / Clear Cache / DB Vacuum reported their result in a card that
 *   slid in at the bottom of a long page and announced nothing at all, so
 *   "restarted everything" and "the restart failed" were the same experience.
 *
 *   The service badges printed the raw enum -- `not_configured`, `fallback` --
 *   and left the colour to say whether that was good or bad news.
 *
 *   The resource meters dropped aria-valuenow when a probe could not measure
 *   anything, and a meter with no value is announced as zero: "we could not
 *   read your memory usage" and "your memory usage is nil" read identically.
 */

let runbookResult: any = { action: 'restart-all', status: 'success', timestamp: '2026-08-18T00:00:00Z', details: {} };
let runbookThrows = false;
let healthPayload: any = null;
let proactivePayload: any = null;

vi.mock('../services/api', () => {
    const handlers: Record<string, (...args: any[]) => Promise<any>> = {
        getHealthDashboard: async () => healthPayload,
        getConnectorHealth: async () => ({ connectors: [], needs_attention: [] }),
        getProactiveHealth: async () => proactivePayload,
        executeRunbook: async () => {
            if (runbookThrows) throw new Error('the server did not answer');
            return runbookResult;
        },
    };
    const api: any = new Proxy({}, {
        get: (_t, prop: string) => handlers[prop] ?? (async () => ({})),
    });
    return { default: api, api };
});

vi.mock('./DialogProvider', () => ({
    useDialog: () => ({ confirm: async () => true, alert: async () => undefined }),
}));

import OperationsPanel from './OperationsPanel';
import { AccessibilityProvider } from '../context/AccessibilityContext';

if (!window.matchMedia) {
    (window as any).matchMedia = (query: string) => ({
        matches: false, media: query, onchange: null,
        addEventListener: () => { }, removeEventListener: () => { },
        addListener: () => { }, removeListener: () => { }, dispatchEvent: () => false,
    });
}

const health = (services: Record<string, any>) => ({
    overall_status: 'degraded',
    services,
    database: { status: 'healthy', size: '2 GB', connections: 4 },
    cache: { status: 'healthy', used_memory: '30 MB' },
    last_backup: {},
});

const proactive = (checks: any[]) => ({
    overall_status: 'ok',
    summary: { level: 'ok', label: 'Fine', detail: '' },
    checks,
    timestamp: '2026-08-18T00:00:00Z',
});

const mount = () => render(
    <AccessibilityProvider><OperationsPanel /></AccessibilityProvider>,
);

const polite = () => document.getElementById('aria-live-region')!.textContent || '';
const assertive = () => document.getElementById('aria-live-region-assertive')!.textContent || '';

beforeEach(() => {
    runbookThrows = false;
    runbookResult = { action: 'restart-all', status: 'success', timestamp: '2026-08-18T00:00:00Z', details: {} };
    healthPayload = null;
    proactivePayload = null;
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('runbook results', () => {
    it('announces a successful runbook', async () => {
        const user = userEvent.setup();
        mount();

        await user.click(await screen.findByRole('button', { name: /restart all/i }));

        await waitFor(() => expect(polite()).toContain('Restart All Services finished successfully'));
    });

    it('announces a failure assertively', async () => {
        const user = userEvent.setup();
        runbookThrows = true;
        mount();

        await user.click(await screen.findByRole('button', { name: /clear cache/i }));

        await waitFor(() => expect(assertive()).toContain('Clear Cache failed'));
    });

    it('announces a runbook the server reports as failed', async () => {
        const user = userEvent.setup();
        runbookResult = { action: 'vacuum', status: 'error', timestamp: '2026-08-18T00:00:00Z', details: { error: 'no space' } };
        mount();

        await user.click(await screen.findByRole('button', { name: /db vacuum/i }));

        await waitFor(() => expect(assertive()).toContain('DB Maintenance failed'));
    });
});

describe('service status labels', () => {
    it('says what a status means rather than printing the enum', async () => {
        healthPayload = health({
            backend: { status: 'running', uptime: 'up 3 days' },
            translation: { status: 'not_configured' },
            geocoder: { status: 'fallback' },
        });
        mount();

        expect(await screen.findByText('Not set up')).toBeTruthy();
        expect(screen.getByText('Using a fallback')).toBeTruthy();
        expect(screen.getByText('Running')).toBeTruthy();
        expect(screen.queryByText('not_configured')).toBeNull();
        expect(screen.queryByText('fallback')).toBeNull();
    });
});

describe('container resource meters', () => {
    it('exposes a measured reading as a meter with its value', async () => {
        proactivePayload = proactive([
            { key: 'memory', label: 'Memory', status: 'ok', value: 42, message: '42% of the limit.' },
        ]);
        mount();

        const meter = await screen.findByRole('meter', { name: 'Memory' });
        expect(meter.getAttribute('aria-valuenow')).toBe('42');
        expect(meter.getAttribute('aria-valuetext')).toBe('42% of the limit used');
    });

    it('does not render a failed probe as a meter reading zero', async () => {
        proactivePayload = proactive([
            { key: 'memory', label: 'Memory', status: 'ok', value: null, message: 'Could not read the limit.' },
        ]);
        mount();

        expect(await screen.findByText('Could not read the limit.')).toBeTruthy();
        // No meter at all beats a meter that says nought.
        expect(screen.queryByRole('meter')).toBeNull();
        // And the dash on screen has words behind it.
        expect(screen.getByText('no reading')).toBeTruthy();
    });
});

describe('decorative icons', () => {
    it('hides every lucide glyph from the accessibility tree', async () => {
        healthPayload = health({ backend: { status: 'running', uptime: 'up 3 days' } });
        mount();
        await screen.findByText('Running');

        const svgs = Array.from(document.querySelectorAll('svg.lucide'));
        expect(svgs.length).toBeGreaterThan(0);
        expect(svgs.filter(s => s.getAttribute('aria-hidden') !== 'true')).toHaveLength(0);
    });
});

// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * Version Control (docs/design/secure-upgrades.md, Phase 3). The console
 * requests; the host updater executes. Pinned here: the no-updater state, the
 * release list and its badges, the request flow (reason required, destructive
 * opt-in), Approve disabled for the requester with the reason shown, the live
 * step list of a running request, and that errors are spoken once.
 */

if (typeof window.matchMedia !== 'function') {
    window.matchMedia = ((query: string) => ({
        matches: false, media: query, onchange: null,
        addListener() { }, removeListener() { },
        addEventListener() { }, removeEventListener() { },
        dispatchEvent: () => false,
    })) as any;
}

const connected = { connected: true, last_seen_at: '2026-10-18T10:00:00Z', version: '0.2.0', current: null, require_two_person_approval: true };
const disconnected = { ...connected, connected: false, last_seen_at: null, version: null };

const release = (over: any = {}) => ({
    tag: 'v1.8.0', version: '1.8.0', name: '1.8.0', published_at: '2026-10-10T00:00:00Z', notes: 'Faster maps', url: null,
    prerelease: false, signature_verified: true, gate_passed: true, attested: null, db_revision: 'e3', min_db_revision: 'd2',
    compatible_with_this_instance: true, compatibility_detail: null, backend_digest: 'sha256:aa', frontend_digest: 'sha256:bb',
    reported_at: null, requestable: true, refusal: null, current: false, ...over,
});

const request = (over: any = {}) => ({
    id: 7, action: 'upgrade', target_tag: 'v1.8.0', reason: 'patch window', requested_by: 'alice',
    requested_at: '2026-10-18T09:00:00Z', scheduled_for: null, status: 'pending_approval', approved_by: null,
    approved_at: null, cancelled_by: null, claimed_at: null, finished_at: null, outcome: null, outcome_summary: null,
    allow_destructive: false, can_approve: false,
    approve_blocked_reason: 'You requested this. Two-person approval needs a different admin to approve it.',
    can_cancel: true, ...over,
});

let state: any;
const calls: any[] = [];

vi.mock('../services/api', () => {
    const handlers: Record<string, (...args: any[]) => Promise<any>> = {
        getCurrentVersion: async () => {
            if (state.fail) throw new Error(state.fail);
            return { version: '1.7.0', git_sha: 'abcdef1234', sha: 'abcdef1', tag: 'v1.7.0', display: 'v1.7.0',
                backend_digest: 'sha256:' + '1'.repeat(64), frontend_digest: null, db_revision: 'd2' };
        },
        getUpdaterReleases: async () => ({ releases: state.releases, updater: state.updater, db_revision: 'd2' }),
        getUpgradeRequests: async () => ({ requests: state.requests, updater: state.updater, require_two_person_approval: true }),
        getUpgradeRequest: async (id: number) => ({ ...state.requests.find((r: any) => r.id === id), steps: state.steps }),
        getUpdaterTokens: async () => ({ tokens: [], updater: state.updater }),
        getSystemConfig: async () => ({ managed_mode: false }),
        createUpgradeRequest: async (body: any) => { calls.push(['create', body]); return request({ id: 9, ...body }); },
        approveUpgradeRequest: async (id: number) => { calls.push(['approve', id]); return request({ id, status: 'approved' }); },
        markUpgradeRequestFailed: async (id: number) => { calls.push(['fail', id]); return request({ id, status: 'failed' }); },
        cancelUpgradeRequest: async (id: number) => { calls.push(['cancel', id]); return request({ id, status: 'cancelled' }); },
    };
    const api: any = new Proxy({}, { get: (_t, prop: string) => handlers[prop] ?? (async () => ({})) });
    return { default: api, api };
});

import VersionSwitcher, { VersionControlPanel } from './VersionSwitcher';
import { AccessibilityProvider } from '../context/AccessibilityContext';

const panel = () => render(<AccessibilityProvider><VersionControlPanel /></AccessibilityProvider>);

beforeEach(() => {
    calls.length = 0;
    state = { updater: connected, releases: [release()], requests: [], steps: [], fail: null };
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('Version Control', () => {
    it('shows "No updater connected" with install docs and CLI steps instead of buttons', async () => {
        state.updater = disconnected;
        panel();
        expect(await screen.findByText('No updater connected')).toBeTruthy();
        expect(screen.getByRole('link', { name: /install the updater/i }).getAttribute('href')).toContain('updater/README.md');
        expect(screen.getByText(/pinpoint-updater upgrade/)).toBeTruthy();
        expect(screen.queryByRole('button', { name: /request upgrade/i })).toBeNull();
        expect(screen.getByRole('button', { name: /updater connection/i })).toBeTruthy();
    });

    it('lists signed releases with their badges and notes in a disclosure', async () => {
        state.releases = [release(), release({ tag: 'v2.0.0', compatible_with_this_instance: false, requestable: false,
            refusal: 'v2.0.0 is not compatible with this instance\'s database schema.', signature_verified: null, gate_passed: null })];
        panel();
        expect(await screen.findByText('v1.8.0')).toBeTruthy();
        expect(screen.getAllByText('Signature verified').length).toBe(1);
        expect(screen.getByText('Gate passed')).toBeTruthy();
        expect(screen.getByText('Schema compatible')).toBeTruthy();
        expect(screen.getByText('Schema incompatible')).toBeTruthy();
        expect(screen.getByText('Signature not checked')).toBeTruthy();
        expect(screen.getAllByText('Attestation not checked').length).toBe(2);
        expect(screen.getAllByText('Release notes')[0].tagName).toBe('SUMMARY');
        expect((screen.getByRole('button', { name: 'Request upgrade to v2.0.0' }) as HTMLButtonElement).disabled).toBe(true);
        expect(screen.getByText(/not compatible with this instance/)).toBeTruthy();
        expect(screen.getByText('v1.7.0')).toBeTruthy();
        expect(screen.getByText('abcdef1234')).toBeTruthy();
    });

    it('files a request with a required reason, a schedule and an explicit destructive opt-in', async () => {
        const user = userEvent.setup();
        panel();
        await user.click(await screen.findByRole('button', { name: 'Request upgrade to v1.8.0' }));
        expect(screen.getByText(/drops or rewrites data/)).toBeTruthy();
        await user.click(screen.getByRole('button', { name: /submit request/i }));
        expect(calls).toEqual([]);
        expect(screen.getByText(/Give a reason/)).toBeTruthy();

        await user.type(screen.getByLabelText(/reason/i), 'October patch');
        await user.click(screen.getByLabelText(/allow a destructive migration/i));
        await user.click(screen.getByRole('button', { name: /submit request/i }));
        await waitFor(() => expect(calls).toHaveLength(1));
        expect(calls[0]).toEqual(['create', { action: 'upgrade', target_tag: 'v1.8.0', reason: 'October patch',
            scheduled_for: null, allow_destructive: true }]);
    });

    it('disables Approve for the requester and says why; Cancel stays available', async () => {
        const user = userEvent.setup();
        state.requests = [request()];
        panel();
        const approve = await screen.findByRole('button', { name: /^approve$/i }) as HTMLButtonElement;
        expect(approve.disabled).toBe(true);
        const reason = screen.getAllByText(/needs a different admin/)[0];
        expect(approve.getAttribute('aria-describedby')).toBe(reason.id);
        await user.click(screen.getAllByRole('button', { name: /^cancel$/i })[0]);
        await waitFor(() => expect(calls).toContainEqual(['cancel', 7]));
    });

    it('lets a different admin approve', async () => {
        const user = userEvent.setup();
        state.requests = [request({ can_approve: true, approve_blocked_reason: null })];
        panel();
        const approve = await screen.findByRole('button', { name: /^approve$/i }) as HTMLButtonElement;
        expect(approve.disabled).toBe(false);
        await user.click(approve);
        await waitFor(() => expect(calls).toContainEqual(['approve', 7]));
    });

    it('shows a running request\'s steps and polls every 5 seconds', async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        state.requests = [request({ status: 'running', can_cancel: false })];
        state.steps = [{ step: 'preflight', status: 'ok', detail: 'signatures verified', at: '2026-10-18T10:00:00Z' }];
        panel();
        const list = await screen.findByRole('list', { name: /updater steps/i });
        expect(within(list).getByText('Preflight')).toBeTruthy();
        expect(screen.getAllByText('Running').length).toBeGreaterThan(0);

        state.steps = [...state.steps, { step: 'backup', status: 'ok', detail: 'verified backup', at: '2026-10-18T10:01:00Z' }];
        await vi.advanceTimersByTimeAsync(5200);
        await waitFor(() => expect(screen.getByText('verified backup')).toBeTruthy());
    });

    it('speaks a load failure once, through the shared assertive region', async () => {
        state.fail = 'the server did not answer';
        render(<AccessibilityProvider><VersionSwitcher /></AccessibilityProvider>);
        await waitFor(() => expect(screen.getByText(/the server did not answer/)).toBeTruthy());
        const assertive = document.getElementById('aria-live-region-assertive')!;
        await waitFor(() => expect(assertive.textContent).toMatch(/the server did not answer/));
        const own = Array.from(document.querySelectorAll('[role="status"], [role="alert"], [aria-live]'))
            .filter(n => !n.id.startsWith('aria-live-region'));
        expect(own).toHaveLength(0);
    });
});

describe('a stalled run', () => {
    it('offers Mark failed for an in-flight request', async () => {
        const user = userEvent.setup();
        state.requests = [request({ status: 'running', can_cancel: false, can_mark_failed: true, last_report_at: '2026-10-18T10:00:00Z' })];
        state.steps = [];
        render(<AccessibilityProvider><VersionControlPanel /></AccessibilityProvider>);
        await user.click(await screen.findByRole('button', { name: /mark failed/i }));
        await waitFor(() => expect(calls).toContainEqual(['fail', 7]));
    });
});

// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/** Restarts are requests the host updater runs for this instance only
 *  (docs/design/secure-upgrades.md, Phase 3). One admin, a reason required,
 *  and the request's status shown. */

let updater: any;
let requests: any[];
const created: any[] = [];

vi.mock('../services/api', () => {
    const handlers: Record<string, (...args: any[]) => Promise<any>> = {
        getHealthDashboard: async () => ({
            overall_status: 'healthy', services: { backend: { status: 'running', uptime: 'ok' } },
            database: { status: 'healthy', size: '2 GB', connections: 4 }, cache: { status: 'healthy', used_memory: '30 MB' },
            last_backup: {},
        }),
        getConnectorHealth: async () => ({ connectors: [], needs_attention: [] }),
        getProactiveHealth: async () => ({ overall_status: 'ok', summary: { level: 'ok', label: 'Fine', detail: '' }, checks: [], timestamp: '2026-08-18T00:00:00Z' }),
        getUpgradeRequests: async () => ({ requests, updater, require_two_person_approval: true }),
        createUpgradeRequest: async (body: any) => {
            created.push(body);
            return { id: 11, action: 'restart', target_tag: null, reason: body.reason, requested_by: 'alice', status: 'approved',
                requested_at: null, scheduled_for: null, approved_by: 'alice', outcome_summary: null, allow_destructive: false };
        },
    };
    const api: any = new Proxy({}, { get: (_t, prop: string) => handlers[prop] ?? (async () => ({})) });
    return { default: api, api };
});
vi.mock('./DialogProvider', () => ({ useDialog: () => ({ confirm: async () => true, alert: async () => {} }) }));

import OperationsPanel from './OperationsPanel';
import { AccessibilityProvider } from '../context/AccessibilityContext';

if (!window.matchMedia) {
    (window as any).matchMedia = (query: string) => ({
        matches: false, media: query, onchange: null, addEventListener: () => { }, removeEventListener: () => { },
        addListener: () => { }, removeListener: () => { }, dispatchEvent: () => false,
    });
}

const mount = () => render(<AccessibilityProvider><OperationsPanel /></AccessibilityProvider>);

beforeEach(() => {
    created.length = 0;
    requests = [];
    updater = { connected: true, last_seen_at: '2026-10-18T10:00:00Z', version: '0.2.0', current: null, require_two_person_approval: true };
});
afterEach(cleanup);

describe('OperationsPanel restarts', () => {
    it('files a restart request with a reason and shows its status', async () => {
        const user = userEvent.setup();
        mount();
        const button = await screen.findByRole('button', { name: /request restart/i }) as HTMLButtonElement;
        expect(button.disabled).toBe(true);             // a reason is required
        expect(screen.queryByRole('button', { name: /restart all/i })).toBeNull();
        await user.type(screen.getByLabelText(/why restart/i), 'worker stuck');
        await user.click(button);
        await waitFor(() => expect(created).toEqual([{ action: 'restart', reason: 'worker stuck' }]));
        expect((await screen.findByTestId('restart-request-status')).textContent).toMatch(/Restart #11.*Approved, waiting for the updater/);
    });

    it('shows a finished restart and its outcome', async () => {
        requests = [{ id: 4, action: 'restart', status: 'succeeded', requested_by: 'bob', outcome_summary: 'town restarted backend, worker, frontend on v1.7.0' }];
        mount();
        const status = await screen.findByTestId('restart-request-status');
        expect(status.textContent).toMatch(/Restart #4 by bob.*Succeeded.*restarted backend/);
    });

    it('explains the host command when no updater is connected', async () => {
        updater = { ...updater, connected: false };
        mount();
        expect(await screen.findByText(/none is connected/)).toBeTruthy();
        expect(screen.queryByRole('button', { name: /request restart/i })).toBeNull();
    });
});

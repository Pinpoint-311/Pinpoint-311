// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AuditLogViewer from './AuditLogViewer';

/**
 * The audit log is the compliance record, and its detail payload -- who did
 * what, from which browser -- was reachable by mouse only. The expander was an
 * onClick on the <tr>: no tabIndex, no role, no key handler, no aria-expanded.
 * A keyboard or screen-reader auditor could read the five summary columns and
 * nothing else, on the one screen in the product whose entire purpose is being
 * auditable.
 *
 * The filter bar was in the same state for a different reason: six controls
 * whose <label>s pointed at nothing, so the whole thing announced as unnamed
 * combo boxes.
 */

const LOGS = [
    {
        id: 1,
        event_type: 'login_failed',
        success: false,
        username: 'clerk@town.gov',
        ip_address: '198.51.100.4',
        user_agent: 'Mozilla/5.0 (Macintosh)',
        timestamp: '2026-06-03T10:00:00Z',
        failure_reason: 'Bad password',
        details: { attempts: 3 },
    },
    {
        id: 2,
        event_type: 'login_success',
        success: true,
        username: 'admin@town.gov',
        ip_address: '198.51.100.9',
        user_agent: 'Mozilla/5.0 (Windows)',
        timestamp: '2026-06-04T10:00:00Z',
        failure_reason: null,
        details: {},
    },
];

beforeEach(() => {
    localStorage.setItem('token', 'test-token');
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
        if (String(url).includes('/api/audit/stats')) {
            return { ok: true, json: async () => ({ total_events: 2 }) } as any;
        }
        return { ok: true, json: async () => ({ logs: LOGS, total_count: 2 }) } as any;
    }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

/** The viewer lives inside a collapsed AccordionSection. */
async function open() {
    const user = userEvent.setup();
    render(<AuditLogViewer />);
    await user.click(screen.getByRole('button', { name: /Audit Logs/i }));
    await screen.findByText('clerk@town.gov');
    return user;
}

describe('the audit log, from a keyboard', () => {
    it('offers each expandable row as a named button rather than a clickable row', async () => {
        await open();

        const expander = screen.getByRole('button', { name: /Show details for Login Failed by clerk@town\.gov/i });
        expect(expander.getAttribute('aria-expanded')).toBe('false');
    });

    it('opens the detail payload with Enter and reports the state change', async () => {
        const user = await open();
        const expander = screen.getByRole('button', { name: /Show details for Login Failed/i });

        expander.focus();
        expect(document.activeElement).toBe(expander);
        await user.keyboard('{Enter}');

        // The user agent and the details payload were both mouse-only before.
        await screen.findByText(/Mozilla\/5.0 \(Macintosh\)/);
        const nowOpen = screen.getByRole('button', { name: /Hide details for Login Failed/i });
        expect(nowOpen.getAttribute('aria-expanded')).toBe('true');

        // aria-controls has to point at the panel that actually appeared.
        const controls = nowOpen.getAttribute('aria-controls')!;
        expect(document.getElementById(controls)).toBeTruthy();
    });

    it('closes again with Space, without losing focus', async () => {
        const user = await open();
        const expander = screen.getByRole('button', { name: /Show details for Login Failed/i });
        expander.focus();

        await user.keyboard('{Enter}');
        await user.keyboard(' ');

        await waitFor(() =>
            expect(screen.getByRole('button', { name: /Show details for Login Failed/i })
                .getAttribute('aria-expanded')).toBe('false'));
        expect(document.activeElement).toBe(expander);
    });

    it('names every filter control', async () => {
        await open();

        for (const name of [/Time Range/i, /Event Type/i, /Status/i, /Username/i]) {
            expect(screen.getByLabelText(name)).toBeTruthy();
        }
    });

    it('names the pagination arrows, which were bare chevrons', async () => {
        await open();

        expect(screen.getByRole('button', { name: /previous page/i })).toBeTruthy();
        expect(screen.getByRole('button', { name: /next page/i })).toBeTruthy();
    });

    it('says in words whether an event succeeded, not only in icon colour', async () => {
        await open();

        expect(screen.getByText('Failed')).toBeTruthy();
        expect(screen.getByText('Succeeded')).toBeTruthy();
    });
});

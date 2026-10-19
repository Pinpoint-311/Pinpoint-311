// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AuditLogViewer from './AuditLogViewer';

/**
 * "Verify integrity" recomputes the audit log's hash chain on the server. The
 * endpoint used to 500 on every call and nothing in the console called it, so
 * an administrator had no way to show a records officer the trail was intact.
 * The result has to say which of three things is true: verified (and how
 * many), how many earlier entries predate verification, or exactly where the
 * chain breaks.
 */

let verifyBody: any;
let verifyStatus = 200;

beforeEach(() => {
    localStorage.setItem('token', 'test-token');
    verifyStatus = 200;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
        const u = String(url);
        if (u.includes('/api/audit/verify-integrity')) {
            return { ok: verifyStatus === 200, status: verifyStatus, json: async () => verifyBody } as any;
        }
        if (u.includes('/api/audit/stats')) {
            return { ok: true, json: async () => ({ total_events: 1 }) } as any;
        }
        return {
            ok: true,
            json: async () => ({
                logs: [{
                    id: 1, event_type: 'logout', success: true, username: 'clerk@town.gov',
                    ip_address: null, user_agent: null, timestamp: '2026-06-03T10:00:00Z',
                    failure_reason: null, details: {},
                }],
                total_count: 1,
            }),
        } as any;
    }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function verify() {
    const user = userEvent.setup();
    render(<AuditLogViewer />);
    await user.click(screen.getByRole('button', { name: /Audit Logs/i }));
    await screen.findByText('clerk@town.gov');
    await user.click(screen.getByRole('button', { name: /Verify integrity/i }));
    return screen.findByTestId('integrity-result');
}

const base = {
    total_entries: 1250, legacy_entries: 0, verified_entries: 1250,
    anchors_checked: 0, first_break: null,
};

describe('Verify integrity', () => {
    it('calls the verify endpoint with the admin token', async () => {
        verifyBody = { ...base, integrity_valid: true };
        await verify();
        const call = (fetch as any).mock.calls.find((c: any[]) => String(c[0]).includes('verify-integrity'));
        expect(call[1].headers.Authorization).toBe('Bearer test-token');
    });

    it('shows a verified chain with its count', async () => {
        verifyBody = { ...base, integrity_valid: true, anchors_checked: 3 };
        const box = await verify();
        expect(within(box).getByText('Chain intact')).toBeTruthy();
        expect(box.textContent).toContain('✓ 1,250 entries verified');
        expect(box.textContent).toContain('3 nightly anchors matched');
        expect(box.textContent).not.toContain('legacy');
    });

    it('reports legacy entries as unchecked rather than broken', async () => {
        verifyBody = { ...base, integrity_valid: true, legacy_entries: 40, verified_entries: 1210 };
        const box = await verify();
        expect(within(box).getByText('Chain intact')).toBeTruthy();
        expect(box.textContent).toContain('40 legacy entries (before verification; not checked)');
        expect(within(box).queryByText('Chain broken')).toBeNull();
    });

    it('names the first broken entry and both hash prefixes', async () => {
        verifyBody = {
            ...base, integrity_valid: false, verified_entries: 811,
            first_break: {
                id: 812, timestamp: '2026-09-01T12:00:00+00:00',
                reason: 'entry contents do not match its hash',
                expected_hash_prefix: 'a1b2c3d4e5f6', stored_hash_prefix: '0f9e8d7c6b5a',
            },
        };
        const box = await verify();
        expect(within(box).getByText('Chain broken')).toBeTruthy();
        expect(box.textContent).toContain('Entry #812');
        expect(box.textContent).toContain('entry contents do not match its hash');
        expect(box.textContent).toContain('expected a1b2c3d4e5f6');
        expect(box.textContent).toContain('stored 0f9e8d7c6b5a');
        expect(box.textContent).toContain('811 entries verified before the break');
    });

    it('says so when the check itself fails', async () => {
        verifyStatus = 500;
        verifyBody = {};
        const box = await verify();
        expect(box.textContent).toContain('Integrity check failed (500)');
    });
});

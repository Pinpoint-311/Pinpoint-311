// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * The staff side of the opt-in Resident History module. The server enforces
 * scoping, minimal fields and auditing; what this pins is that the UI tells the
 * clerk the truth about it (matched by email, logged), opens reports through
 * the dashboard's own handler, and keeps the searched value out of anything but
 * the POST body.
 */

const api = vi.hoisted(() => ({
    getResidentHistory: vi.fn(),
    searchResidents: vi.fn(),
}));
vi.mock('../services/api', () => ({ api, default: api }));

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
});
afterEach(() => {
    act(() => root.unmount());
    host.remove();
    vi.clearAllMocks();
});

const flush = () => act(async () => { await new Promise(r => setTimeout(r, 0)); });

const rows = [
    { service_request_id: 'SR-1042', service_name: 'Pothole', status: 'closed', requested_datetime: '2026-09-02T10:00:00Z' },
    { service_request_id: 'SR-0977', service_name: 'Streetlight out', status: 'in_progress', requested_datetime: '2026-08-14T10:00:00Z' },
];

describe('ResidentHistoryCard', () => {
    it('lists earlier reports and says how they were matched and that viewing is logged', async () => {
        api.getResidentHistory.mockResolvedValue({ matched_by: 'email', total: 2, reports: rows });
        const { ResidentHistoryCard } = await import('./ResidentHistory');
        const onOpen = vi.fn();
        await act(async () => {
            root.render(React.createElement(ResidentHistoryCard, { serviceRequestId: 'SR-2001', onOpen }));
        });
        await flush();

        expect(api.getResidentHistory).toHaveBeenCalledWith('SR-2001');
        expect(host.textContent).toContain('2 found');
        expect(host.textContent).toContain('SR-1042');
        expect(host.textContent).toContain('In progress');
        expect(host.textContent).toContain('Matched by email');
        expect(host.textContent).toContain('Viewing is logged');

        const first = host.querySelector('button[aria-label^="Open SR-1042"]') as HTMLButtonElement;
        await act(async () => { first.click(); });
        expect(onOpen).toHaveBeenCalledWith('SR-1042');
    });

    it('says so when the report has no email to match on', async () => {
        api.getResidentHistory.mockResolvedValue({ matched_by: null, total: 0, reports: [] });
        const { ResidentHistoryCard } = await import('./ResidentHistory');
        await act(async () => {
            root.render(React.createElement(ResidentHistoryCard, { serviceRequestId: 'SR-1', onOpen: vi.fn() }));
        });
        await flush();
        expect(host.textContent).toContain('no email address to match on');
    });

    it('shows the server\'s refusal, such as an audit failure, instead of an empty list', async () => {
        api.getResidentHistory.mockRejectedValue(new Error("This lookup couldn't be recorded in the audit log, so it wasn't run."));
        const { ResidentHistoryCard } = await import('./ResidentHistory');
        await act(async () => {
            root.render(React.createElement(ResidentHistoryCard, { serviceRequestId: 'SR-1', onOpen: vi.fn() }));
        });
        await flush();
        expect(host.querySelector('[role="alert"]')?.textContent).toContain('audit log');
    });
});

describe('ResidentSearch', () => {
    async function mountSearch() {
        const { ResidentSearch } = await import('./ResidentHistory');
        const onOpen = vi.fn();
        await act(async () => { root.render(React.createElement(ResidentSearch, { onOpen })); });
        return onOpen;
    }

    function type(value: string) {
        const input = host.querySelector('input') as HTMLInputElement;
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
        act(() => {
            setter.call(input, value);
            input.dispatchEvent(new Event('input', { bubbles: true }));
        });
    }

    async function submit() {
        const form = host.querySelector('form') as HTMLFormElement;
        await act(async () => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); });
        await flush();
    }

    it('refuses a partial email before asking the server', async () => {
        await mountSearch();
        type('jane');
        await submit();
        expect(api.searchResidents).not.toHaveBeenCalled();
        expect(host.querySelector('[role="alert"]')?.textContent).toContain('full email');
    });

    it('searches by exact email and lists what the server returned', async () => {
        api.searchResidents.mockResolvedValue({ searched_by: 'email', total: 1, reports: rows.slice(0, 1) });
        await mountSearch();
        type('jane.doe@example.com');
        await submit();
        expect(api.searchResidents).toHaveBeenCalledWith({ email: 'jane.doe@example.com' });
        expect(host.textContent).toContain('1 report found');
        expect(host.textContent).toContain('SR-1042');
        expect(host.textContent).toContain('logged without what you typed');
    });

    it('needs a first and a last name when searching by name', async () => {
        await mountSearch();
        const nameTab = Array.from(host.querySelectorAll('button[role="radio"]'))
            .find(b => b.textContent?.includes('Name')) as HTMLButtonElement;
        await act(async () => { nameTab.click(); });
        type('Jane');
        await submit();
        expect(api.searchResidents).not.toHaveBeenCalled();

        api.searchResidents.mockResolvedValue({ searched_by: 'name', total: 0, reports: [] });
        type('Jane Doe');
        await submit();
        expect(api.searchResidents).toHaveBeenCalledWith({ name: 'Jane Doe' });
        expect(host.textContent).toContain('No reports you have access to match exactly');
    });
});

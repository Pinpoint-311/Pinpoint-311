// @vitest-environment jsdom
import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState, useRef } from 'react';

import ActivityFeed from './ActivityFeed';
import { AccessibilityProvider } from '../context/AccessibilityContext';
import { ServiceRequest } from '../types';

/**
 * The Activity Feed slide-over looked modal (it dims the dashboard and eats
 * outside clicks) without behaving modally for anyone not using a mouse:
 *
 *   - no role/aria-modal, so it was announced as ordinary page content sitting
 *     on top of the dashboard it covers;
 *   - Tab from the last feed item continued straight into the dashboard behind
 *     it (WCAG 2.4.3), where every control was still reachable and still
 *     clickable underneath the dimmer;
 *   - Escape did nothing, so the only way out was to tab all the way round to
 *     the close button (2.1.2);
 *   - and closing dropped focus onto <body>, so the next Tab started at the
 *     top of the document instead of at the bell that opened the panel.
 *
 * These drive the keyboard, not synthetic clicks, and assert on
 * document.activeElement, because "the trap holds" is a statement about where
 * focus actually is.
 */

function req(over: Partial<ServiceRequest>): ServiceRequest {
    return {
        service_request_id: 'REQ-2',
        service_code: 'pothole',
        service_name: 'Pothole',
        status: 'open',
        description: 'Deep pothole near the crosswalk',
        requested_datetime: new Date().toISOString(),
        assigned_department_id: null,
        assigned_to: null,
        ...over,
    } as ServiceRequest;
}

/** The dashboard shape that matters: a bell that opens the panel, and another
 *  focusable control behind it that the trap must never let Tab reach. */
function Harness({ requests }: { requests: ServiceRequest[] }) {
    const [open, setOpen] = useState(false);
    const bell = useRef<HTMLButtonElement>(null);
    return (
        <AccessibilityProvider>
            <button ref={bell} onClick={() => setOpen(true)}>Activity</button>
            <button>Behind the dialog</button>
            <ActivityFeed
                isOpen={open}
                onClose={() => setOpen(false)}
                requests={requests}
                userId="pat"
                userDepartmentIds={[]}
                onSelectRequest={() => { }}
            />
        </AccessibilityProvider>
    );
}

const openFeed = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole('button', { name: 'Activity' }));
    const dialog = await screen.findByRole('dialog');
    // Initial focus lands a tick after mount.
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    return dialog;
};


// jsdom ships no matchMedia; AccessibilityProvider queries it on mount for the
// reduced-motion and high-contrast preferences.
beforeAll(() => {
    if (!window.matchMedia) {
        window.matchMedia = ((query: string) => ({
            matches: false,
            media: query,
            onchange: null,
            addEventListener: () => {},
            removeEventListener: () => {},
            addListener: () => {},
            removeListener: () => {},
            dispatchEvent: () => false,
        })) as unknown as typeof window.matchMedia;
    }
});

beforeEach(() => {
    localStorage.clear();
});
afterEach(cleanup);

describe('ActivityFeed slide-over dialog semantics', () => {
    it('is a modal dialog named by its heading', async () => {
        const user = userEvent.setup();
        render(<Harness requests={[req({ service_request_id: 'REQ-2' })]} />);
        const dialog = await openFeed(user);

        expect(dialog.getAttribute('aria-modal')).toBe('true');
        expect(within(dialog).getByRole('heading', { name: 'Activity Feed' })).toBeTruthy();
        // Named by that heading, not left as a bare "dialog".
        expect(screen.getByRole('dialog', { name: 'Activity Feed' })).toBe(dialog);
    });

    it('hides the backdrop from assistive tech without hiding the dialog with it', async () => {
        const user = userEvent.setup();
        const { container } = render(<Harness requests={[req({ service_request_id: 'REQ-2' })]} />);
        const dialog = await openFeed(user);

        // The dimmer is a decorative click target; it must be aria-hidden, and
        // it must not be an ancestor of the panel (which would hide the whole
        // dialog from the accessibility tree along with it).
        const backdrop = container.querySelector('[aria-hidden="true"].fixed.inset-0');
        expect(backdrop).toBeTruthy();
        expect(backdrop!.contains(dialog)).toBe(false);
    });

    it('moves focus into the panel when it opens', async () => {
        const user = userEvent.setup();
        render(<Harness requests={[req({ service_request_id: 'REQ-2' })]} />);
        const dialog = await openFeed(user);

        expect(dialog.contains(document.activeElement)).toBe(true);
        expect(document.activeElement).not.toBe(document.body);
    });

    it('wraps Tab at the last control instead of leaking into the dashboard behind', async () => {
        const user = userEvent.setup();
        render(<Harness requests={[req({ service_request_id: 'REQ-2' })]} />);
        const dialog = await openFeed(user);
        const behind = screen.getByRole('button', { name: 'Behind the dialog' });

        // Walk further than there are controls in the panel; focus must stay in.
        for (let i = 0; i < 10; i++) {
            await user.tab();
            expect(dialog.contains(document.activeElement)).toBe(true);
            expect(document.activeElement).not.toBe(behind);
        }
    });

    it('wraps Shift+Tab backwards out of the first control', async () => {
        const user = userEvent.setup();
        render(<Harness requests={[req({ service_request_id: 'REQ-2' })]} />);
        const dialog = await openFeed(user);

        for (let i = 0; i < 6; i++) {
            await user.tab({ shift: true });
            expect(dialog.contains(document.activeElement)).toBe(true);
        }
    });

    it('closes on Escape and returns focus to the control that opened it', async () => {
        const user = userEvent.setup();
        render(<Harness requests={[req({ service_request_id: 'REQ-2' })]} />);
        await openFeed(user);
        const bell = screen.getByRole('button', { name: 'Activity' });

        await user.keyboard('{Escape}');

        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        await waitFor(() => expect(document.activeElement).toBe(bell));
    });

    it('returns focus to the opener when closed with the close button', async () => {
        const user = userEvent.setup();
        render(<Harness requests={[req({ service_request_id: 'REQ-2' })]} />);
        await openFeed(user);
        const bell = screen.getByRole('button', { name: 'Activity' });

        screen.getByRole('button', { name: 'Close activity feed' }).focus();
        await user.keyboard('{Enter}');

        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        await waitFor(() => expect(document.activeElement).toBe(bell));
    });
});

describe('ActivityFeed status messages', () => {
    it('announces the result of "Mark all read" rather than silently zeroing the count', async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        try {
            const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
            render(<Harness requests={[req({ service_request_id: 'REQ-2' })]} />);
            await openFeed(user);

            await user.click(screen.getByRole('button', { name: 'Mark all read' }));

            // announce() clears then writes, so the text lands a beat later.
            await vi.advanceTimersByTimeAsync(200);
            const region = document.getElementById('aria-live-region');
            expect(region?.textContent).toMatch(/marked as read/i);
        } finally {
            vi.useRealTimers();
        }
    });
});

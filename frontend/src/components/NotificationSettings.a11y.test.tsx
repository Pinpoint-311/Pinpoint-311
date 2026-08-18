// @vitest-environment jsdom
import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState, useRef } from 'react';

/**
 * Notification Settings was a hand-rolled backdrop and panel: no dialog role,
 * no accessible name, no focus trap, no Escape, no focus restore. Its sibling
 * ManualIntake already used the shared ui/Modal, so a call taker got a working
 * dialog when logging a request and a broken one when setting their own
 * notification preferences.
 *
 * Two more things this covers, both of which a keyboard-only tester hits
 * within seconds:
 *
 *   - the SMS switches are inert until a phone number is typed, and that was
 *     communicated by opacity alone (WCAG 1.4.1) while the switch still sat in
 *     the tab order reporting aria-checked (4.1.2) — press Space, nothing
 *     happens, no explanation;
 *   - Save produced a green strip that self-destructs after three seconds and
 *     nothing at all for a screen reader (4.1.3).
 */

const prefs = {
    email_new_requests: true,
    email_status_changes: true,
    email_comments: true,
    email_assigned_only: false,
    sms_new_requests: false,
    sms_status_changes: false,
    phone: null as string | null,
};

vi.mock('../services/api', () => {
    const api = {
        getNotificationPreferences: vi.fn(),
        updateNotificationPreferences: vi.fn(),
    };
    return { api, default: api };
});

import NotificationSettings from './NotificationSettings';
import { AccessibilityProvider } from '../context/AccessibilityContext';
import { api } from '../services/api';

const mocked = api as unknown as {
    getNotificationPreferences: ReturnType<typeof vi.fn>;
    updateNotificationPreferences: ReturnType<typeof vi.fn>;
};

function Harness() {
    const [open, setOpen] = useState(false);
    const trigger = useRef<HTMLButtonElement>(null);
    return (
        <AccessibilityProvider>
            <button ref={trigger} onClick={() => setOpen(true)}>Settings</button>
            <button>Behind the dialog</button>
            <NotificationSettings isOpen={open} onClose={() => setOpen(false)} userName="Pat Ranger" />
        </AccessibilityProvider>
    );
}

const openDialog = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole('button', { name: 'Settings' }));
    const dialog = await screen.findByRole('dialog');
    await screen.findByRole('switch', { name: 'Email notifications for New Requests' });
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
    mocked.getNotificationPreferences.mockReset().mockResolvedValue({ ...prefs });
    mocked.updateNotificationPreferences.mockReset().mockImplementation(async (d: typeof prefs) => d);
});
afterEach(cleanup);

describe('NotificationSettings dialog semantics', () => {
    it('is a modal dialog with an accessible name', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        const dialog = await openDialog(user);

        expect(dialog.getAttribute('aria-modal')).toBe('true');
        expect(screen.getByRole('dialog', { name: /notification settings/i })).toBe(dialog);
        expect(within(dialog).getByRole('heading', { name: /notification settings/i })).toBeTruthy();
    });

    it('keeps Tab inside the dialog', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        const dialog = await openDialog(user);
        const behind = screen.getByRole('button', { name: 'Behind the dialog' });

        for (let i = 0; i < 14; i++) {
            await user.tab();
            expect(dialog.contains(document.activeElement)).toBe(true);
            expect(document.activeElement).not.toBe(behind);
        }
    });

    it('closes on Escape and restores focus to the opener', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        await openDialog(user);
        const trigger = screen.getByRole('button', { name: 'Settings' });

        await user.keyboard('{Escape}');

        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        await waitFor(() => expect(document.activeElement).toBe(trigger));
    });
});

describe('NotificationSettings SMS switches', () => {
    it('takes the disabled SMS switches out of the tab order and says why', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        const dialog = await openDialog(user);

        // Each switch is named for its channel: "New Requests" appears under
        // both Email and SMS, and two identically named switches in one dialog
        // are indistinguishable in speech.
        const smsSwitch = within(dialog).getByRole('switch', { name: 'SMS notifications for Status Changes', hidden: true });
        expect((smsSwitch as HTMLButtonElement).disabled).toBe(true);

        // The reason is text, not opacity.
        expect(within(dialog).getAllByText(/add a phone number above/i).length).toBeGreaterThan(0);

        // A real disabled button: never focusable, so Tab cannot land on a
        // control that would silently swallow the keypress.
        const disabledSwitches = within(dialog)
            .getAllByRole('switch', { hidden: true })
            .filter(el => (el as HTMLButtonElement).disabled);
        expect(disabledSwitches.length).toBe(2);
        for (const el of disabledSwitches) {
            el.focus();
            expect(document.activeElement).not.toBe(el);
        }
    });

    it('enables the SMS switches once a phone number is typed, and they toggle from the keyboard', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        const dialog = await openDialog(user);

        await user.click(within(dialog).getByLabelText('Phone Number'));
        await user.keyboard('+1 555-123-4567');

        const smsSwitches = within(dialog)
            .getAllByRole('switch')
            .filter(el => !(el as HTMLButtonElement).disabled);
        // Four email switches plus the two SMS ones.
        expect(smsSwitches.length).toBe(6);

        const target = smsSwitches[smsSwitches.length - 1];
        target.focus();
        expect(document.activeElement).toBe(target);
        expect(target.getAttribute('aria-checked')).toBe('false');

        await user.keyboard(' ');
        expect(target.getAttribute('aria-checked')).toBe('true');
    });

    it('labels the phone field via htmlFor/id, not proximity', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        const dialog = await openDialog(user);

        const input = within(dialog).getByLabelText('Phone Number') as HTMLInputElement;
        expect(input.tagName).toBe('INPUT');
        expect(input.type).toBe('tel');
    });
});

describe('NotificationSettings save feedback', () => {
    it('announces a successful save', async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        try {
            const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
            render(<Harness />);
            const dialog = await openDialog(user);

            await user.click(within(dialog).getByRole('button', { name: 'Save Changes' }));
            await vi.advanceTimersByTimeAsync(300);

            expect(document.getElementById('aria-live-region')?.textContent)
                .toMatch(/preferences saved/i);
        } finally {
            vi.useRealTimers();
        }
    });

    it('announces a failed save assertively', async () => {
        mocked.updateNotificationPreferences.mockRejectedValue(new Error('boom'));
        const err = vi.spyOn(console, 'error').mockImplementation(() => { });
        vi.useFakeTimers({ shouldAdvanceTime: true });
        try {
            const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
            render(<Harness />);
            const dialog = await openDialog(user);

            await user.click(within(dialog).getByRole('button', { name: 'Save Changes' }));
            await vi.advanceTimersByTimeAsync(300);

            expect(document.getElementById('aria-live-region-assertive')?.textContent)
                .toMatch(/failed to save/i);
        } finally {
            vi.useRealTimers();
            err.mockRestore();
        }
    });
});

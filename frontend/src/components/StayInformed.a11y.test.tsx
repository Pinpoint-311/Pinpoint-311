// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * The registration prompt declared role="dialog" and aria-modal="true" and then
 * behaved like neither.
 *
 * aria-modal tells a screen reader that everything outside the dialog is
 * unavailable, so a Tab that escapes it strands somebody in content their
 * screen reader has already written off. Nothing focused the dialog when it
 * appeared, Tab walked straight out of it, and Escape did nothing at all.
 *
 * Separately: clicking the backdrop called finish('not-now'), which both threw
 * away a part-filled seven-field form and recorded a permanent dismissal, off
 * the kind of click that is most often a mis-aimed one.
 */

vi.mock('../services/api', () => {
    const api: any = new Proxy({}, {
        get: () => vi.fn().mockResolvedValue({}),
    });
    return { default: api, api };
});

import { StayInformedHost } from './StayInformed';

beforeEach(() => {
    localStorage.clear();
    if (!window.matchMedia) {
        (window as any).matchMedia = () => ({
            matches: false, addEventListener: () => { }, removeEventListener: () => { },
        });
    }
});
afterEach(() => { cleanup(); localStorage.clear(); });

const openDialog = async () => {
    render(<StayInformedHost ready />);
    return await screen.findByRole('dialog');
};

describe('the registration dialog', () => {
    it('takes focus when it opens instead of leaving it on the body', async () => {
        const dialog = await openDialog();
        await waitFor(() => expect(document.activeElement).toBe(dialog));
    });

    it('holds Tab inside itself', async () => {
        const user = userEvent.setup();
        const dialog = await openDialog();

        for (let i = 0; i < 14; i++) {
            await user.tab();
            expect(dialog.contains(document.activeElement)).toBe(true);
        }
        for (let i = 0; i < 14; i++) {
            await user.tab({ shift: true });
            expect(dialog.contains(document.activeElement)).toBe(true);
        }
    });

    it('closes on Escape while the form is untouched', async () => {
        const user = userEvent.setup();
        const dialog = await openDialog();
        // The key has to land inside the dialog, which is exactly why the
        // dialog takes focus when it opens.
        await waitFor(() => expect(document.activeElement).toBe(dialog));

        await user.keyboard('{Escape}');

        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });

    it('makes Escape ask first once something has been typed', async () => {
        const user = userEvent.setup();
        await openDialog();

        await user.type(screen.getByRole('textbox', { name: /Organization/ }), 'Township of Example');

        await user.keyboard('{Escape}');
        // Still open, and the reason is in the dialog's live region rather than
        // only implied by nothing having happened.
        expect(screen.queryByRole('dialog')).not.toBeNull();
        expect(screen.getByRole('status').textContent).toMatch(/Escape again/i);

        await user.keyboard('{Escape}');
        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });

    it('does not let a stray backdrop click destroy a part-filled form', async () => {
        const user = userEvent.setup();
        const dialog = await openDialog();
        const backdrop = dialog.parentElement!;

        // Pristine: clicking away is an ordinary dismissal.
        await user.click(backdrop);
        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());

        // Reopened, with something typed into it this time.
        cleanup();
        localStorage.clear();
        const reopened = await openDialog();
        await user.type(screen.getByRole('textbox', { name: /Organization/ }), 'Township of Example');

        await user.click(reopened.parentElement!);

        expect(screen.queryByRole('dialog')).not.toBeNull();
        expect((screen.getByRole('textbox', { name: /Organization/ }) as HTMLInputElement).value)
            .toBe('Township of Example');
    });
});

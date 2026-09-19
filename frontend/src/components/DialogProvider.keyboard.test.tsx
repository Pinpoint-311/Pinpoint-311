// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import { DialogProvider, useDialog } from './DialogProvider';

/**
 * This is the confirmation layer in front of every delete in the admin console
 * -- users, departments, services, integrations, token regeneration, retention
 * purge, deploy -- and it was a bare animated div. No role, no name, no focus
 * trap, and no Escape: Tab walked straight out of an open "Delete user" and
 * into the page behind it, where the row that raised the dialog was still
 * clickable. A keyboard user could confirm a destructive action they were never
 * told they had opened.
 *
 * The contract now: the panel is a labelled modal dialog, focus enters it and
 * cannot leave it by Tab, Escape cancels, and focus goes back to the control
 * that opened it.
 */

function Harness({ requireTyped }: { requireTyped?: string }) {
    const dialog = useDialog();
    const [result, setResult] = useState<string>('none');
    return (
        <div>
            <button onClick={async () => {
                const ok = await dialog.confirm({
                    title: 'Delete User',
                    message: 'This cannot be undone.',
                    variant: 'danger',
                    confirmText: 'Delete',
                    requireTyped,
                });
                setResult(ok ? 'confirmed' : 'cancelled');
            }}>
                Delete user Sam
            </button>
            <button>Somewhere else on the page</button>
            <output>{result}</output>
        </div>
    );
}

const setup = (requireTyped?: string) => {
    const user = userEvent.setup();
    render(<DialogProvider><Harness requireTyped={requireTyped} /></DialogProvider>);
    return user;
};

const openDialog = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole('button', { name: 'Delete user Sam' }));
    return screen.findByRole('dialog');
};

/* No jest-dom in this repo, so names and descriptions are resolved the long
   way: follow aria-labelledby / aria-describedby and read the text. */
const textOf = (ids: string | null) => (ids || '')
    .split(/\s+/).filter(Boolean)
    .map(id => document.getElementById(id)?.textContent || '')
    .join(' ');
const accName = (el: Element) => el.getAttribute('aria-label') || textOf(el.getAttribute('aria-labelledby'));
const accDescription = (el: Element) => textOf(el.getAttribute('aria-describedby'));

afterEach(cleanup);

describe('the confirmation dialog, from a keyboard', () => {
    it('is a modal dialog named by its title and described by its message', async () => {
        const user = setup();
        const dialog = await openDialog(user);

        expect(dialog.getAttribute('aria-modal')).toBe('true');
        expect(accName(dialog)).toBe('Delete User');
        expect(accDescription(dialog)).toMatch(/cannot be undone/i);
    });

    it('moves focus into the dialog when it opens', async () => {
        const user = setup();
        const dialog = await openDialog(user);

        await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    });

    it('keeps Tab inside the dialog instead of letting it reach the page behind', async () => {
        const user = setup();
        const dialog = await openDialog(user);
        await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));

        // Round the whole cycle twice: whatever the tab order is, it must never
        // leave the panel. The page behind still has two live buttons on it.
        for (let i = 0; i < 8; i++) {
            await user.tab();
            expect(dialog.contains(document.activeElement)).toBe(true);
        }

        for (let i = 0; i < 8; i++) {
            await user.tab({ shift: true });
            expect(dialog.contains(document.activeElement)).toBe(true);
        }
    });

    it('cancels on Escape and hands focus back to the button that opened it', async () => {
        const user = setup();
        const trigger = screen.getByRole('button', { name: 'Delete user Sam' });
        await openDialog(user);

        await user.keyboard('{Escape}');

        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        await waitFor(() => expect(document.activeElement).toBe(trigger));
        expect(screen.getByText('cancelled')).toBeTruthy();
    });

    it('restores focus after a confirm as well, not only a cancel', async () => {
        const user = setup();
        const trigger = screen.getByRole('button', { name: 'Delete user Sam' });
        await openDialog(user);

        await user.click(screen.getByRole('button', { name: 'Delete' }));

        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        await waitFor(() => expect(document.activeElement).toBe(trigger));
        expect(screen.getByText('confirmed')).toBeTruthy();
    });

    it('gives the close control a name rather than a bare icon', async () => {
        const user = setup();
        await openDialog(user);

        expect(screen.getByRole('button', { name: /close dialog/i })).toBeTruthy();
    });
});

describe('the type-to-confirm gate on a permanent deletion', () => {
    it('labels the box and says why Confirm is unavailable', async () => {
        const user = setup('DELETE');
        await openDialog(user);

        const box = screen.getByRole('textbox', { name: /type DELETE to continue/i });
        expect(accDescription(box)).toMatch(/stays unavailable until you type DELETE/i);
    });

    it('opens with focus in the box, and unlocks Confirm once it is typed', async () => {
        const user = setup('DELETE');
        await openDialog(user);
        const box = screen.getByRole('textbox', { name: /type DELETE to continue/i });

        await waitFor(() => expect(document.activeElement).toBe(box));
        expect((screen.getByRole('button', { name: 'Delete' }) as HTMLButtonElement).disabled).toBe(true);

        await user.keyboard('DELETE');

        expect((screen.getByRole('button', { name: 'Delete' }) as HTMLButtonElement).disabled).toBe(false);
        expect(accDescription(box)).toMatch(/Delete is now available/i);
    });
});

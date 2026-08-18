// @vitest-environment jsdom
import { describe, it, expect, afterEach, beforeAll } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Modal } from './Modal';
import { Button } from './Button';

/**
 * The dialog's focus trap picked its boundary elements with a plain
 * `querySelectorAll('button, [href], input, select, textarea, …')`, matching
 * disabled and hidden controls along with the real ones. Both failure modes
 * end the same way — focus outside an open modal, on the page it is supposed
 * to be covering (WCAG 2.4.3, 2.1.2):
 *
 *   `.focus()` on a disabled button silently does nothing, so a dialog whose
 *   first control starts disabled — the delete confirmations in this product,
 *   which stay disabled until a justification is typed — opened with focus
 *   left on <body>.
 *
 *   Tab wrapping used the last MATCHED element rather than the last reachable
 *   one, so the wrap could target something the browser refuses to focus.
 */

beforeAll(() => {
    if (!window.matchMedia) {
        window.matchMedia = ((query: string) => ({
            matches: false, media: query, onchange: null,
            addEventListener: () => {}, removeEventListener: () => {},
            addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
        })) as unknown as typeof window.matchMedia;
    }
});

afterEach(cleanup);

describe('Modal focus management', () => {
    it('places initial focus inside the dialog, never on the page behind it', async () => {
        render(
            <Modal isOpen onClose={() => {}} title="Delete request">
                <button type="button" disabled>Confirm delete</button>
                <button type="button">Cancel</button>
            </Modal>
        );

        await waitFor(() => {
            expect(screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
        });
        expect(document.activeElement).not.toBe(document.body);
        expect(document.activeElement).not.toBe(
            screen.getByRole('button', { name: 'Confirm delete' })
        );
    });

    it('skips a disabled control when tabbing, and wraps rather than escaping', async () => {
        const user = userEvent.setup();
        render(
            <Modal isOpen onClose={() => {}} title="Delete request">
                <button type="button" disabled>Confirm delete</button>
                <button type="button">Cancel</button>
            </Modal>
        );

        const dialog = screen.getByRole('dialog');
        await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));

        screen.getByRole('button', { name: 'Close dialog' }).focus();
        await user.tab();

        // The disabled Confirm is the next element in DOM order; a browser
        // will not focus it, and the trap must not treat it as the boundary.
        expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' }));

        // Cancel is the last reachable control, so Tab wraps back into the
        // dialog instead of stepping out onto the page underneath.
        await user.tab();
        expect(dialog.contains(document.activeElement)).toBe(true);
    });

    it('names an untitled dialog from aria-label', () => {
        render(
            <Modal isOpen onClose={() => {}} aria-label="Photo viewer">
                <img src="/x.jpg" alt="Submitted photo 1" />
            </Modal>
        );

        expect(screen.getByRole('dialog', { name: 'Photo viewer' })).toBeTruthy();
    });
});

describe('Button forwards ARIA to the underlying control', () => {
    /**
     * Every prop was previously listed by hand and destructured with no rest
     * spread, so `aria-expanded`, `aria-pressed`, `aria-controls` and friends
     * were dropped on the floor — which is why so many toggles across the
     * staff and admin surfaces announced as plain buttons with no state
     * (WCAG 4.1.2). No call site could work around it.
     */
    it('passes through toggle state and disclosure wiring', () => {
        render(
            <Button aria-pressed aria-expanded={false} aria-controls="panel-1" id="toggle">
                Filters
            </Button>
        );

        const button = screen.getByRole('button', { name: 'Filters' });
        expect(button.getAttribute('aria-pressed')).toBe('true');
        expect(button.getAttribute('aria-expanded')).toBe('false');
        expect(button.getAttribute('aria-controls')).toBe('panel-1');
        expect(button.getAttribute('id')).toBe('toggle');
    });

    it('marks itself busy while loading without opening a live region', () => {
        render(<Button isLoading>Save</Button>);

        const button = screen.getByRole('button', { name: /Save/ });
        expect(button.getAttribute('aria-busy')).toBe('true');
        // The spinner used to be its own role="status" with a duplicate
        // sr-only sibling: two announcements of the same thing, and a live
        // region opened by every button that started loading.
        expect(button.querySelector('[role="status"]')).toBeNull();
    });
});

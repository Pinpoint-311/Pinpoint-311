// @vitest-environment jsdom
import { describe, it, expect, afterEach, beforeAll, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';
import { AccessibilityProvider, useAnnounce } from './AccessibilityContext';

// jsdom ships no matchMedia; the provider queries it for the reduced-motion
// and high-contrast preferences on mount.
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

/**
 * WCAG 4.1.3 Status Messages.
 *
 * `announce()` looked up `#aria-live-region` and quietly did nothing when it
 * was absent — and it was absent from the React tree entirely, so every
 * announcement the product believed it was making went nowhere. These tests
 * pin the two things that were broken: the regions exist for the whole app
 * lifetime, and a message actually lands in one of them.
 */

afterEach(cleanup);

function Announcer({ message, priority }: { message: string; priority?: 'polite' | 'assertive' }) {
    const announce = useAnnounce();
    return (
        <button type="button" onClick={() => announce(message, priority)}>
            announce
        </button>
    );
}

describe('AccessibilityProvider live regions', () => {
    it('renders both regions before anything is announced', () => {
        render(<AccessibilityProvider><div /></AccessibilityProvider>);

        const polite = document.getElementById('aria-live-region')!;
        const assertive = document.getElementById('aria-live-region-assertive')!;

        expect(polite).toBeTruthy();
        expect(polite.getAttribute('aria-live')).toBe('polite');
        expect(assertive.getAttribute('aria-live')).toBe('assertive');

        // Empty at first. A region whose text appears in the same commit as the
        // region itself is routinely not announced at all.
        expect(polite.textContent).toBe('');
    });

    it('writes a polite message into the polite region', () => {
        vi.useFakeTimers();
        try {
            render(
                <AccessibilityProvider>
                    <Announcer message="Report submitted" />
                </AccessibilityProvider>
            );

            act(() => { screen.getByRole('button', { name: 'announce' }).click(); });
            act(() => { vi.advanceTimersByTime(150); });

            expect(document.getElementById('aria-live-region')!.textContent).toBe('Report submitted');
            expect(document.getElementById('aria-live-region-assertive')!.textContent).toBe('');

            // Cleared afterwards so the same message can be announced twice.
            act(() => { vi.advanceTimersByTime(3000); });
            expect(document.getElementById('aria-live-region')!.textContent).toBe('');
        } finally {
            vi.useRealTimers();
        }
    });

    it('keeps assertive messages in a separate region', () => {
        vi.useFakeTimers();
        try {
            render(
                <AccessibilityProvider>
                    <Announcer message="Could not save" priority="assertive" />
                </AccessibilityProvider>
            );

            act(() => { screen.getByRole('button', { name: 'announce' }).click(); });
            act(() => { vi.advanceTimersByTime(150); });

            // Politeness is cached by assistive tech when the region is
            // registered, so swapping aria-live on one node is unreliable —
            // hence two nodes, each written only by its own priority.
            expect(document.getElementById('aria-live-region-assertive')!.textContent).toBe('Could not save');
            expect(document.getElementById('aria-live-region')!.textContent).toBe('');
        } finally {
            vi.useRealTimers();
        }
    });
});

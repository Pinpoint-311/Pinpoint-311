// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Action, StatusPill } from './capabilityUI';
import { AccessibilityProvider } from '../context/AccessibilityContext';

/**
 * `Action` is the button every capability surface renders, and its prop list was
 * closed: a caller could not pass aria-label, aria-expanded or aria-controls at
 * all, so no consumer of it could ever be made conformant. Exactly the defect
 * ui/Button.tsx had. Asserted here rather than in one caller because the fix is
 * only worth anything if it holds for all of them.
 *
 * `StatusPill` is driven by live health checks, so it can flip from Working to
 * Not working with no focus change and no other signal — WCAG 4.1.3.
 */

if (typeof window.matchMedia !== 'function') {
    window.matchMedia = ((query: string) => ({
        matches: false, media: query, onchange: null,
        addListener() { }, removeListener() { },
        addEventListener() { }, removeEventListener() { },
        dispatchEvent: () => false,
    })) as any;
}

afterEach(cleanup);

describe('Action prop forwarding', () => {
    it('passes ARIA through to the button instead of dropping it', () => {
        render(
            <Action aria-label="Open provider menu" aria-controls="menu-1" data-testid="act">
                Configure
            </Action>
        );

        const button = screen.getByRole('button', { name: 'Open provider menu' });
        expect(button.getAttribute('aria-controls')).toBe('menu-1');
        expect(button.getAttribute('data-testid')).toBe('act');
    });

    it('declares the popup a caret promises, and whether it is open', async () => {
        const { rerender } = render(<Action chevron expanded={false}>Provider</Action>);

        const button = screen.getByRole('button', { name: 'Provider' });
        expect(button.getAttribute('aria-haspopup')).toBe('menu');
        expect(button.getAttribute('aria-expanded')).toBe('false');

        rerender(<Action chevron expanded>Provider</Action>);
        await waitFor(() => expect(button.getAttribute('aria-expanded')).toBe('true'));
    });

    it('claims neither when there is no caret, so a plain button stays a plain button', () => {
        render(<Action>Save</Action>);
        const button = screen.getByRole('button', { name: 'Save' });
        expect(button.getAttribute('aria-haspopup')).toBeNull();
        expect(button.getAttribute('aria-expanded')).toBeNull();
    });

    it('marks itself busy while it is spinning, not just disabled', () => {
        render(<Action busy>Test now</Action>);
        const button = screen.getByRole('button', { name: 'Test now' });
        expect(button.getAttribute('aria-busy')).toBe('true');
        expect((button as HTMLButtonElement).disabled).toBe(true);
    });

    it('is still operable from the keyboard with the extra props in place', async () => {
        const user = userEvent.setup();
        const onClick = vi.fn();
        render(<Action aria-label="Run the test" onClick={onClick}>Test</Action>);

        const button = screen.getByRole('button', { name: 'Run the test' });
        button.focus();
        expect(document.activeElement).toBe(button);

        await user.keyboard('{Enter}');
        expect(onClick).toHaveBeenCalledTimes(1);
    });
});

describe('StatusPill status messages', () => {
    const renderPill = (state: any, name?: string) => render(
        <AccessibilityProvider>
            <StatusPill state={state} name={name} />
        </AccessibilityProvider>
    );

    it('says nothing on first render — an initial state is not a change', async () => {
        renderPill('working', 'Email');
        const region = document.getElementById('aria-live-region')!;
        await new Promise(resolve => setTimeout(resolve, 200));
        expect(region.textContent).toBe('');
    });

    it('announces a working-to-failing flip, assertively, and names what failed', async () => {
        const { rerender } = renderPill('working', 'Email');

        rerender(
            <AccessibilityProvider>
                <StatusPill state="failing" name="Email" />
            </AccessibilityProvider>
        );

        const region = document.getElementById('aria-live-region-assertive')!;
        await waitFor(() => expect(region.textContent).toBe('Email: Not working'));
    });

    it('keeps a non-alerting change polite', async () => {
        const { rerender } = renderPill('unset', 'Maps');

        rerender(
            <AccessibilityProvider>
                <StatusPill state="working" name="Maps" />
            </AccessibilityProvider>
        );

        const polite = document.getElementById('aria-live-region')!;
        await waitFor(() => expect(polite.textContent).toBe('Maps: Working'));
    });

    it('renders outside an AccessibilityProvider without throwing', () => {
        // It is a leaf presentational component and is used in isolation; the
        // announce hook throws without a provider, so this reads the context
        // directly and no-ops.
        expect(() => render(<StatusPill state="working" />)).not.toThrow();
    });
});

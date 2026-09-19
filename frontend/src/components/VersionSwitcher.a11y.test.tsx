// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';

/**
 * A deploy narrates itself, and it used to narrate itself twice.
 *
 * `message` changes repeatedly while a deployment runs -- "Starting", "Server
 * is restarting", a percentage, "Deployment complete" -- and each change went
 * both to announce() and to a role="status" strip rendered in the same commit.
 * Two polite regions written in one tick means a screen reader announces
 * neither, so the one flow in the console where waiting blind is genuinely
 * uncomfortable was also the one saying nothing. Same for the error path and
 * its role="alert".
 *
 * The strips are visible text now and announce() is the only spoken channel,
 * matching NotificationSettings.
 */

if (typeof window.matchMedia !== 'function') {
    window.matchMedia = ((query: string) => ({
        matches: false, media: query, onchange: null,
        addListener() { }, removeListener() { },
        addEventListener() { }, removeEventListener() { },
        dispatchEvent: () => false,
    })) as any;
}

import VersionSwitcher from './VersionSwitcher';
import { DialogProvider } from './DialogProvider';
import { AccessibilityProvider } from '../context/AccessibilityContext';

beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('GitHub is unreachable from this host')));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('the deploy panel speaks once', () => {
    it('sends a failure to the shared assertive region and leaves the strip as text', async () => {
        render(
            <AccessibilityProvider>
                <DialogProvider>
                    <VersionSwitcher />
                </DialogProvider>
            </AccessibilityProvider>
        );

        // Visible where somebody reading the panel will find it...
        await waitFor(() => expect(screen.getByText(/GitHub is unreachable/)).toBeTruthy());

        // ...and spoken through the app's one assertive region, not a second
        // one of this component's own.
        const assertive = document.getElementById('aria-live-region-assertive')!;
        await waitFor(() => expect(assertive.textContent).toMatch(/GitHub is unreachable/));

        const ownRegions = Array.from(
            document.querySelectorAll('[role="status"], [role="alert"], [aria-live]'),
        ).filter(n => !n.id.startsWith('aria-live-region'));
        expect(ownRegions).toHaveLength(0);
    });
});

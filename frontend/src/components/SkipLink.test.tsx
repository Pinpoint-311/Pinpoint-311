// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SkipLink from './SkipLink';

/**
 * WCAG 2.4.1 Bypass Blocks.
 *
 * The product shipped the CSS for a skip link and `#main-content` targets on
 * the pages, and a static link in index.html that navigated to the fragment.
 * Fragment navigation scrolls but does not reliably move focus, and on the
 * staff and admin surfaces — which route their views through the URL hash —
 * setting `#main-content` looked like a request to switch to a view of that
 * name. So the contract asserted here is: first tab stop, Enter moves focus
 * into the landmark, and the URL is left alone.
 */

afterEach(cleanup);

function Page() {
    return (
        <>
            <SkipLink />
            <nav>
                <a href="/one">Nav one</a>
                <a href="/two">Nav two</a>
            </nav>
            <main id="main-content">
                <h1>Report an issue</h1>
                <button type="button">First control in main</button>
            </main>
        </>
    );
}

describe('SkipLink', () => {
    it('is the first thing keyboard focus reaches', async () => {
        const user = userEvent.setup();
        render(<Page />);

        await user.tab();

        expect(document.activeElement).toBe(
            screen.getByRole('link', { name: 'Skip to main content' })
        );
    });

    it('moves focus into the main landmark on Enter', async () => {
        const user = userEvent.setup();
        render(<Page />);

        await user.tab();
        await user.keyboard('{Enter}');

        const main = document.getElementById('main-content')!;
        expect(document.activeElement).toBe(main);

        // And the next Tab continues from inside the content, which is the
        // whole point — scrolling to the landmark while focus stays in the
        // header bypasses nothing.
        await user.tab();
        expect(document.activeElement).toBe(
            screen.getByRole('button', { name: 'First control in main' })
        );
    });

    it('leaves the URL hash alone, so hash-routed views are not disturbed', async () => {
        const user = userEvent.setup();
        render(<Page />);
        window.location.hash = 'requests';

        await user.tab();
        await user.keyboard('{Enter}');

        expect(window.location.hash).toBe('#requests');
    });

    it('does not strand focus when the page has no main landmark', async () => {
        const user = userEvent.setup();
        render(
            <>
                <SkipLink />
                <div>No landmark on this page yet</div>
            </>
        );

        await user.tab();
        const link = screen.getByRole('link', { name: 'Skip to main content' });
        expect(document.activeElement).toBe(link);

        // No target: the handler bails out rather than throwing, and focus
        // stays somewhere sane.
        await user.keyboard('{Enter}');
        expect(document.activeElement).toBe(link);
    });
});

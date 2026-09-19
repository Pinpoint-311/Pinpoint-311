// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, cleanup, act } from '@testing-library/react';
import usePageNavigation from './usePageNavigation';

/**
 * The focus half of the view-change contract.
 *
 * Both hash-routed pages in this product -- the staff dashboard and the admin
 * console -- change views by swapping the contents of #main-content while the
 * sidebar button that was clicked keeps focus. Title and scroll were already
 * handled; focus was not, and focus is the half a keyboard or screen-reader
 * user actually experiences: the button re-announces itself, says nothing
 * about the view that just loaded, and the next Tab continues through the rest
 * of the nav instead of into the content.
 *
 * focusMain is deliberately defensive -- the two callers have differently
 * shaped DOM and one of them may render neither the landmark nor a heading --
 * so the no-op paths are as much a part of the contract as the happy one and
 * are pinned here too.
 */

/** Drives focusMain with whatever container id the test wants. */
function Harness({ containerId }: { containerId?: string }) {
    const { focusMain } = usePageNavigation({ baseTitle: 'Test' });
    return (
        <button type="button" onClick={() => focusMain(containerId)}>
            go
        </button>
    );
}

/** The rAF stub below fires synchronously; this just flushes the act queue. */
const runFrame = async () => {
    await act(async () => {
        await Promise.resolve();
    });
};

beforeEach(() => {
    // Run the scheduled callback immediately: jsdom has no frame timing of its
    // own worth waiting on, and the deferral is an implementation detail here.
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
        cb(0);
        return 0;
    });
});

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
});

describe('usePageNavigation focusMain', () => {
    it('moves focus to the first heading in the view, not the container', async () => {
        document.body.insertAdjacentHTML(
            'beforeend',
            '<div id="main-content"><h1>Open Requests</h1><p>body</p></div>'
        );
        const { getByRole } = render(<Harness />);

        act(() => {
            getByRole('button', { name: 'go' }).click();
        });
        await runFrame();

        const heading = document.querySelector('h1')!;
        // The heading, because that is what is read on arrival: "Open Requests,
        // heading level 1" names the destination where a focused div says
        // nothing at all.
        expect(document.activeElement).toBe(heading);
    });

    it('makes the heading focusable without adding it to the tab sequence', async () => {
        document.body.insertAdjacentHTML(
            'beforeend',
            '<div id="main-content"><h2>System Health</h2></div>'
        );
        const { getByRole } = render(<Harness />);

        act(() => {
            getByRole('button', { name: 'go' }).click();
        });
        await runFrame();

        const heading = document.querySelector('h2')!;
        // .focus() is a no-op on an element with no tabindex, so the attribute
        // has to be applied -- but at -1, or a phantom stop appears in the tab
        // order every time a view changes.
        expect(heading.getAttribute('tabindex')).toBe('-1');
        expect(document.activeElement).toBe(heading);
    });

    it('falls back to the container when the view has no heading', async () => {
        document.body.insertAdjacentHTML(
            'beforeend',
            '<div id="main-content"><p>no heading here</p></div>'
        );
        const { getByRole } = render(<Harness />);

        act(() => {
            getByRole('button', { name: 'go' }).click();
        });
        await runFrame();

        expect(document.activeElement).toBe(document.getElementById('main-content'));
    });

    it('leaves focus alone when the container is not in the DOM', async () => {
        const { getByRole } = render(<Harness containerId="not-rendered" />);
        const trigger = getByRole('button', { name: 'go' });
        trigger.focus();

        act(() => {
            trigger.click();
        });
        await runFrame();

        // Defensive no-op rather than a throw: one caller may legitimately not
        // render the landmark, and a missing container must not take the page
        // down or strand focus on <body>.
        expect(document.activeElement).toBe(trigger);
    });
});

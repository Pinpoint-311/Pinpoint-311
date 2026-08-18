import React, { useCallback } from 'react';

/**
 * Skip to main content — WCAG 2.4.1 Bypass Blocks.
 *
 * The styling for this (`.skip-link` in index.css) and the `#main-content`
 * targets on the pages have both been in the codebase for a long time; the link
 * itself was never rendered, so there was nothing to bypass the header and
 * navigation with, on any page. The accessibility statement claimed otherwise.
 *
 * Activation is handled in JS rather than left to the browser's fragment
 * navigation, for two reasons:
 *
 *   The staff dashboard and admin console route their views through the URL
 *   hash. Letting the browser set `#main-content` would look to those pages
 *   like a request to switch to a view named "main-content" and would blow away
 *   whatever the user was looking at.
 *
 *   Fragment navigation scrolls but does not reliably move focus, which is the
 *   half that matters — a keyboard user who is scrolled to the content but
 *   still focused in the header has not skipped anything. Focus is moved
 *   explicitly, with a temporary tabindex if the target does not already carry
 *   one, so the next Tab continues from inside the content.
 *
 * It stays a real link so it is announced as one and appears in the links list.
 */
export const SkipLink: React.FC<{ targetId?: string; children?: React.ReactNode }> = ({
    targetId = 'main-content',
    children = 'Skip to main content',
}) => {
    const skip = useCallback((event: React.MouseEvent | React.KeyboardEvent) => {
        const target = document.getElementById(targetId);
        if (!target) return;   // No target on this page: fall through to default behaviour.

        event.preventDefault();

        if (!target.hasAttribute('tabindex')) {
            target.setAttribute('tabindex', '-1');
            // Drop it again once focus leaves, so the element does not linger in
            // a state where a click gives it a focus ring.
            target.addEventListener('blur', () => target.removeAttribute('tabindex'), { once: true });
        }
        target.focus({ preventScroll: true });
        // Guarded: not every environment implements it (jsdom does not), and
        // failing to scroll must not cost the user the focus move above.
        target.scrollIntoView?.({ block: 'start', behavior: 'auto' });
    }, [targetId]);

    return (
        <a
            href={`#${targetId}`}
            className="skip-link"
            onClick={skip}
            /* Enter on a link fires click, so this only adds Space, which some
             * users press out of habit and which would otherwise scroll. */
            onKeyDown={(event) => {
                if (event.key === ' ' || event.key === 'Spacebar') skip(event);
            }}
        >
            {children}
        </a>
    );
};

export default SkipLink;

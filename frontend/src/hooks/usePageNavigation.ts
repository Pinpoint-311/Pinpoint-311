import { useCallback, useRef, useEffect, useState } from 'react';

interface UsePageNavigationOptions {
    baseTitle: string;        // e.g., "Staff Portal"
    scrollContainerRef?: React.RefObject<HTMLElement>;  // Container to scroll (or window if not provided)
    onHashChange?: (hash: string) => void;  // Callback when hash changes (for back/forward navigation)
}

/**
 * Custom hook for URL hashing, dynamic document titles, and scroll-to-top behavior.
 * Supports browser back/forward navigation via popstate listener.
 */
export function usePageNavigation({ baseTitle, scrollContainerRef, onHashChange }: UsePageNavigationOptions) {
    const initialLoad = useRef(true);
    const lastHash = useRef<string>('');
    const [currentHash, setCurrentHash] = useState(() =>
        typeof window !== 'undefined' ? window.location.hash.slice(1) : ''
    );

    // Update URL hash and add to browser history
    const updateHash = useCallback((hash: string, replace: boolean = false) => {
        // Don't push duplicate hash entries
        if (hash === lastHash.current) return;

        lastHash.current = hash;
        setCurrentHash(hash);

        if (hash) {
            if (replace) {
                window.history.replaceState(null, '', `${window.location.pathname}#${hash}`);
            } else {
                window.history.pushState(null, '', `${window.location.pathname}#${hash}`);
            }
        } else {
            if (replace) {
                window.history.replaceState(null, '', window.location.pathname);
            } else {
                window.history.pushState(null, '', window.location.pathname);
            }
        }
    }, []);

    // Update document title
    const updateTitle = useCallback((subtitle?: string) => {
        if (subtitle) {
            document.title = `${subtitle} | ${baseTitle}`;
        } else {
            document.title = baseTitle;
        }
    }, [baseTitle]);

    // Scroll to top of content area. Depending on the page layout the actual
    // scroller may be the inner content container OR the window, so reset both —
    // scrolling only one silently no-ops when the other is the real scroller.
    const scrollToTop = useCallback((behavior: ScrollBehavior = 'smooth') => {
        scrollContainerRef?.current?.scrollTo({ top: 0, behavior });
        window.scrollTo({ top: 0, behavior });
    }, [scrollContainerRef]);

    /* Move focus into the new view — WCAG 2.4.3 Focus Order.
     *
     * This hook's whole view-change contract was updateTitle + scrollToTop.
     * Neither touches focus, so a sidebar click replaced the entire contents of
     * #main-content while focus stayed on the sidebar button that had been
     * pressed. A screen reader user heard the button re-announce itself and
     * nothing at all about the page that had just loaded; a keyboard user's
     * next Tab carried on through the *rest of the nav*, walking every
     * remaining sidebar item before reaching the content they asked for.
     *
     * Focus lands on the first heading in the region rather than the region
     * itself, because that is what gets read on arrival -- "Open Requests,
     * heading level 1" names the destination, where a focused <div> says
     * nothing. tabIndex=-1 is applied here rather than demanded of every
     * caller: .focus() is a no-op on an element with no tabindex, and -1 keeps
     * the heading out of the tab sequence so nothing new appears when tabbing.
     *
     * Additive and defensive by design -- AdminConsole shares this hook and may
     * have neither #main-content nor a heading, so every step no-ops rather
     * than throwing when the DOM is not shaped as expected.
     */
    const focusMain = useCallback((containerId: string = 'main-content') => {
        // Deferred one frame: callers set view state and call this in the same
        // effect, before React has committed the new view. Focusing now would
        // land on the *outgoing* heading, or on nothing.
        const run = () => {
            const container = document.getElementById(containerId);
            if (!container) return;
            const target =
                container.querySelector<HTMLElement>('[data-focus-target], h1, h2') ?? container;
            if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
            // preventScroll because scrollToTop owns the scroll position; without
            // it the browser scrolls the heading into view and fights that reset.
            target.focus({ preventScroll: true });
        };
        if (typeof window.requestAnimationFrame === 'function') {
            window.requestAnimationFrame(run);
        } else {
            run();
        }
    }, []);

    // Get current hash
    const getHash = useCallback(() => {
        return window.location.hash.slice(1);  // Remove the # prefix
    }, []);

    // Parse hash into sections (e.g., "request/12345" -> { section: 'request', id: '12345' })
    const parseHash = useCallback((hash?: string) => {
        const h = hash ?? getHash();
        if (!h) return { section: '', id: '', parts: [] as string[] };

        const parts = h.split('/');
        return {
            section: parts[0] || '',
            id: parts[1] || '',
            parts
        };
    }, [getHash]);

    // Listen for back/forward browser navigation (popstate event)
    useEffect(() => {
        const handlePopState = () => {
            const newHash = window.location.hash.slice(1);
            lastHash.current = newHash;
            setCurrentHash(newHash);
            if (onHashChange) {
                onHashChange(newHash);
            }
        };

        window.addEventListener('popstate', handlePopState);
        return () => window.removeEventListener('popstate', handlePopState);
    }, [onHashChange]);

    // On initial load, set base title and check for existing hash
    useEffect(() => {
        if (initialLoad.current) {
            initialLoad.current = false;
            /* Set the base title unconditionally — WCAG 2.4.2 Page Titled.
             *
             * This assignment used to live only in the `else`, so a deep link
             * carrying any hash skipped it entirely and relied on the hash
             * handler to title the page. When the handler did not resolve the
             * hash — an unknown section, a request id that 404s, a view the
             * signed-in user cannot see — nothing ever set the title and the
             * tab kept whatever the previous document was called, or the bare
             * URL. Setting the base first means the worst case is a correct
             * but general title; a handler that does resolve overwrites it
             * with the specific one a moment later. */
            document.title = baseTitle;
            const existingHash = window.location.hash.slice(1);
            if (existingHash) {
                lastHash.current = existingHash;
                setCurrentHash(existingHash);
                if (onHashChange) {
                    onHashChange(existingHash);
                }
            }
        }
    }, [baseTitle, onHashChange]);

    return {
        updateHash,
        updateTitle,
        scrollToTop,
        focusMain,
        getHash,
        parseHash,
        currentHash
    };
}

export default usePageNavigation;

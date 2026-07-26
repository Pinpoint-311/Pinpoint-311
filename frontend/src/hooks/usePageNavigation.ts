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
            const existingHash = window.location.hash.slice(1);
            if (existingHash) {
                lastHash.current = existingHash;
                setCurrentHash(existingHash);
                if (onHashChange) {
                    onHashChange(existingHash);
                }
            } else {
                document.title = baseTitle;
            }
        }
    }, [baseTitle, onHashChange]);

    return {
        updateHash,
        updateTitle,
        scrollToTop,
        getHash,
        parseHash,
        currentHash
    };
}

export default usePageNavigation;

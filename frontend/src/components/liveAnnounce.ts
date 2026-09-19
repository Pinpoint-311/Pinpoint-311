import { useCallback, useContext } from 'react';
import AccessibilityContext from '../context/AccessibilityContext';

/**
 * `announce()` when an AccessibilityProvider is above us, a no-op when it is not.
 *
 * App.tsx mounts AccessibilityProvider above every route, so in the running
 * product this is exactly `useAnnounce()`. The difference is unit tests: the
 * admin components here are mounted directly (SetupIntegrationsPage's six
 * suites render the page inside a bare DialogProvider, for instance), and
 * `useAnnounce()` throws outright when the provider is missing. A status
 * message that cannot be announced in a test harness must not take the whole
 * component down with it, so the announcement degrades instead of throwing.
 *
 * Announcements deliberately route through the provider's single pair of live
 * regions rather than through per-component `aria-live` nodes: two polite
 * regions updating in the same tick means a screen reader announces neither.
 */
export function useOptionalAnnounce() {
    const context = useContext(AccessibilityContext);
    const announce = context?.announce;
    return useCallback((message: string, priority: 'polite' | 'assertive' = 'polite') => {
        announce?.(message, priority);
    }, [announce]);
}

export default useOptionalAnnounce;

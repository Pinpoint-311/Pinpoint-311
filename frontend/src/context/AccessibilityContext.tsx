import React, { createContext, useContext, useCallback, useEffect, useRef, useState } from 'react';

interface AccessibilityContextType {
    /** Announce a message to screen readers */
    announce: (message: string, priority?: 'polite' | 'assertive') => void;
    /** Whether user prefers reduced motion */
    prefersReducedMotion: boolean;
    /** Whether user is using high contrast mode */
    prefersHighContrast: boolean;
    /** Current focus trap element (if any) */
    focusTrapElement: HTMLElement | null;
    /** Set focus trap on an element */
    setFocusTrap: (element: HTMLElement | null) => void;
}

const AccessibilityContext = createContext<AccessibilityContextType | undefined>(undefined);

interface AccessibilityProviderProps {
    children: React.ReactNode;
}

export const AccessibilityProvider: React.FC<AccessibilityProviderProps> = ({ children }) => {
    const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);
    const [prefersHighContrast, setPrefersHighContrast] = useState(false);
    const [focusTrapElement, setFocusTrapElement] = useState<HTMLElement | null>(null);

    // Detect reduced motion preference
    useEffect(() => {
        const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
        setPrefersReducedMotion(mediaQuery.matches);

        const handler = (event: MediaQueryListEvent) => {
            setPrefersReducedMotion(event.matches);
        };

        mediaQuery.addEventListener('change', handler);
        return () => mediaQuery.removeEventListener('change', handler);
    }, []);

    // Detect high contrast preference
    useEffect(() => {
        const mediaQuery = window.matchMedia('(prefers-contrast: more)');
        setPrefersHighContrast(mediaQuery.matches);

        const handler = (event: MediaQueryListEvent) => {
            setPrefersHighContrast(event.matches);
        };

        mediaQuery.addEventListener('change', handler);
        return () => mediaQuery.removeEventListener('change', handler);
    }, []);

    /* Screen reader announcement — WCAG 4.1.3 Status Messages.
     *
     * This used to look up `#aria-live-region` and silently do nothing when it
     * was missing, and it was ALWAYS missing: nothing in the app ever rendered
     * that element. Every announcement the product thought it was making went
     * nowhere. The region is now rendered by this provider, so it exists for
     * the whole app lifetime and screen readers have it registered before the
     * first message lands (a region inserted at the same moment as its text is
     * routinely not announced at all).
     *
     * Two regions, not one, and only one of them is ever written at a time:
     * a polite region and an assertive one. Swapping `aria-live` on a single
     * node is unreliable — assistive tech caches the politeness at the time
     * the region is registered.
     *
     * Deliberately the ONLY general-purpose live region in the product. Two
     * polite regions updating in the same tick means a screen reader announces
     * neither, so new status messages should route through `announce()` rather
     * than adding another `aria-live` node. */
    const politeRef = useRef<HTMLDivElement>(null);
    const assertiveRef = useRef<HTMLDivElement>(null);
    const timers = useRef<number[]>([]);

    useEffect(() => () => {
        timers.current.forEach(id => window.clearTimeout(id));
    }, []);

    const announce = useCallback((message: string, priority: 'polite' | 'assertive' = 'polite') => {
        const region = priority === 'assertive' ? assertiveRef.current : politeRef.current;
        if (!region || !message) return;

        // Clear first so an identical repeated message still reads as a change.
        region.textContent = '';
        timers.current.push(window.setTimeout(() => {
            if (region.isConnected) region.textContent = message;
        }, 100));
        timers.current.push(window.setTimeout(() => {
            if (region.isConnected) region.textContent = '';
        }, 3000));
    }, []);

    // Focus trap management
    const setFocusTrap = useCallback((element: HTMLElement | null) => {
        setFocusTrapElement(element);
    }, []);

    const value: AccessibilityContextType = {
        announce,
        prefersReducedMotion,
        prefersHighContrast,
        focusTrapElement,
        setFocusTrap,
    };

    return (
        <AccessibilityContext.Provider value={value}>
            {children}
            {/* Mounted for the app's whole lifetime so assistive tech has both
              * regions registered long before anything is written into them. */}
            <div
                id="aria-live-region"
                ref={politeRef}
                className="sr-only"
                role="status"
                aria-live="polite"
                aria-atomic="true"
            />
            <div
                id="aria-live-region-assertive"
                ref={assertiveRef}
                className="sr-only"
                role="alert"
                aria-live="assertive"
                aria-atomic="true"
            />
        </AccessibilityContext.Provider>
    );
};

export const useAccessibility = (): AccessibilityContextType => {
    const context = useContext(AccessibilityContext);
    if (context === undefined) {
        throw new Error('useAccessibility must be used within an AccessibilityProvider');
    }
    return context;
};

/**
 * Hook to announce messages to screen readers
 * Usage: const announce = useAnnounce();
 *        announce("Form submitted successfully");
 */
export const useAnnounce = () => {
    const { announce } = useAccessibility();
    return announce;
};

/**
 * Hook to check if user prefers reduced motion
 */
export const usePrefersReducedMotion = () => {
    const { prefersReducedMotion } = useAccessibility();
    return prefersReducedMotion;
};

export default AccessibilityContext;

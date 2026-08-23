import React, { createContext, useContext, useCallback, useEffect, useState } from 'react';
import { announceStatus } from '../components/capabilityUI';

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

    /* Screen reader announcement.
     *
     * One implementation, in capabilityUI, because the setup page's cards
     * announce from outside this provider and two copies of the clear/set/clear
     * dance is two things to keep in step. It also writes textContent rather
     * than innerHTML: a good deal of what gets announced is a vendor's own error
     * string, and remote text should never be parsed as markup. */
    const announce = useCallback(announceStatus, []);

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

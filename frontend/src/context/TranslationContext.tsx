import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

interface TranslationContextType {
    language: string;
    setLanguage: (lang: string) => void;
}

const TranslationContext = createContext<TranslationContextType | undefined>(undefined);

interface TranslationProviderProps {
    children: ReactNode;
}

// Storage key for persisting language preference
const LANGUAGE_STORAGE_KEY = 'preferred_language';

export function TranslationProvider({ children }: TranslationProviderProps) {
    // Initialize from localStorage or default to 'en'
    const [language, setLanguageState] = useState<string>(() => {
        try {
            return localStorage.getItem(LANGUAGE_STORAGE_KEY) || 'en';
        } catch {
            return 'en';
        }
    });

    // Wrapper to persist language to localStorage
    const setLanguage = (lang: string) => {
        setLanguageState(lang);
        try {
            localStorage.setItem(LANGUAGE_STORAGE_KEY, lang);
        } catch (err) {
            console.error('Failed to save language preference:', err);
        }
    };

    // Also sync from localStorage on mount (in case of multiple tabs)
    useEffect(() => {
        const handleStorageChange = (e: StorageEvent) => {
            if (e.key === LANGUAGE_STORAGE_KEY && e.newValue) {
                setLanguageState(e.newValue);
            }
        };
        window.addEventListener('storage', handleStorageChange);
        return () => window.removeEventListener('storage', handleStorageChange);
    }, []);

    return (
        <TranslationContext.Provider value={{ language, setLanguage }}>
            {children}
        </TranslationContext.Provider>
    );
}

export function useTranslation() {
    const context = useContext(TranslationContext);
    if (!context) {
        throw new Error('useTranslation must be used within TranslationProvider');
    }
    return context;
}

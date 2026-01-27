import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

interface TranslationContextType {
    language: string;
    setLanguage: (lang: string) => void;
    isRTL: boolean;
}

const TranslationContext = createContext<TranslationContextType | undefined>(undefined);

interface TranslationProviderProps {
    children: ReactNode;
}

// Storage key for persisting language preference
const LANGUAGE_STORAGE_KEY = 'preferred_language';

// RTL (Right-to-Left) languages
const RTL_LANGUAGES = ['ar', 'he', 'fa', 'ur', 'yi', 'ps', 'sd', 'ug'];

export function TranslationProvider({ children }: TranslationProviderProps) {
    // Initialize from localStorage or default to 'en'
    const [language, setLanguageState] = useState<string>(() => {
        try {
            return localStorage.getItem(LANGUAGE_STORAGE_KEY) || 'en';
        } catch {
            return 'en';
        }
    });

    // Check if current language is RTL
    const isRTL = RTL_LANGUAGES.includes(language);

    // Update document direction and lang attribute when language changes
    useEffect(() => {
        document.documentElement.lang = language;
        document.documentElement.dir = isRTL ? 'rtl' : 'ltr';

        // Add RTL class for custom styling if needed
        if (isRTL) {
            document.documentElement.classList.add('rtl');
        } else {
            document.documentElement.classList.remove('rtl');
        }
    }, [language, isRTL]);

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
        <TranslationContext.Provider value={{ language, setLanguage, isRTL }}>
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

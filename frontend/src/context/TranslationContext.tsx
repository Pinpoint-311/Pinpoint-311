import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { useTranslation as useI18n } from 'react-i18next';

interface TranslationContextType {
    language: string;
    setLanguage: (lang: string) => void;
}

const TranslationContext = createContext<TranslationContextType | undefined>(undefined);

interface TranslationProviderProps {
    children: ReactNode;
}

export function TranslationProvider({ children }: TranslationProviderProps) {
    const { i18n } = useI18n();
    const [language, setLanguageState] = useState<string>(i18n.language || 'en');

    // Sync with i18next language changes
    useEffect(() => {
        const handleLanguageChange = (lng: string) => {
            setLanguageState(lng);
        };

        i18n.on('languageChanged', handleLanguageChange);
        return () => {
            i18n.off('languageChanged', handleLanguageChange);
        };
    }, [i18n]);

    const setLanguage = (lang: string) => {
        i18n.changeLanguage(lang);
        setLanguageState(lang);
    };

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

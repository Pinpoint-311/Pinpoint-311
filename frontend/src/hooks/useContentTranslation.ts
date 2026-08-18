import { useState, useEffect } from 'react';
import { useTranslation } from '../context/TranslationContext';

// In-memory cache for translated content
const contentCache = new Map<string, string>();

/** The platform's authoring language: what resident-submitted text is assumed
 *  to be in when nothing says otherwise. */
const DEFAULT_SOURCE_LANGUAGE = 'en';

/**
 * Hook to translate dynamic user-generated content
 * @param originalText The original text to translate
 * @param contentId Unique identifier for caching (e.g., "desc_123" or "comment_456")
 * @param assumedSourceLang Language `originalText` is in, when the caller knows
 * @returns The translated text, plus the language the ORIGINAL is in
 *
 * WCAG 3.1.2 Language of Parts. The request used to carry `target_lang` and
 * nothing else, so neither this hook nor its callers could say what language
 * the untranslated string was in — and a string that fails to translate stays
 * in the source language on a page whose `<html lang>` has already changed.
 * TranslatedContent takes a `sourceLang` prop precisely so it can tag that
 * case; `sourceLang` here is the value it needs, threaded back out.
 *
 * The source is declared rather than detected. `POST /api/system/translate/batch`
 * hard-codes "en" as the source and returns no language field, so detection is
 * not available to ask for today (see the report accompanying this change); the
 * assumption is now explicit in the request and in the return value rather than
 * implicit in an omission, and `data.source_lang` is honoured the moment the
 * endpoint starts sending one.
 */
export function useContentTranslation(
    originalText: string,
    contentId: string,
    assumedSourceLang: string = DEFAULT_SOURCE_LANGUAGE,
) {
    const { language } = useTranslation();
    const [translatedText, setTranslatedText] = useState(originalText);
    const [isTranslating, setIsTranslating] = useState(false);
    const [sourceLang, setSourceLang] = useState(assumedSourceLang);

    useEffect(() => {
        // If English or no text, return original
        if (language === 'en' || !originalText) {
            setTranslatedText(originalText);
            return;
        }

        // Check cache first
        const cacheKey = `${contentId}_${language}`;
        if (contentCache.has(cacheKey)) {
            setTranslatedText(contentCache.get(cacheKey)!);
            return;
        }

        // Translate the content
        const translateContent = async () => {
            setIsTranslating(true);
            try {
                const response = await fetch('/api/system/translate/batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        texts: [originalText],
                        target_lang: language,
                        source_lang: assumedSourceLang
                    })
                });

                if (response.ok) {
                    const data = await response.json();
                    // Honoured if the endpoint ever detects and reports a source.
                    if (typeof data.source_lang === 'string' && data.source_lang) {
                        setSourceLang(data.source_lang);
                    }
                    if (data.translations && data.translations[0]) {
                        const translated = data.translations[0];
                        contentCache.set(cacheKey, translated);
                        setTranslatedText(translated);
                    } else {
                        setTranslatedText(originalText);
                    }
                } else {
                    setTranslatedText(originalText);
                }
            } catch (error) {
                console.error('Failed to translate content:', error);
                setTranslatedText(originalText);
            } finally {
                setIsTranslating(false);
            }
        };

        translateContent();
    }, [originalText, contentId, language, assumedSourceLang]);

    const isTranslated = language !== 'en' && translatedText !== originalText;

    return {
        translatedText,
        isTranslating,
        isTranslated,
        /** Language `originalText` is in. */
        sourceLang,
        /** Language the string this hook returns is ACTUALLY in — the target when
         *  translation succeeded, the source when it did not. This is the value a
         *  `lang` attribute needs, and computing it here keeps every caller from
         *  re-deriving it (and getting it wrong for the failure case). */
        renderedLang: isTranslated ? language : sourceLang,
    };
}

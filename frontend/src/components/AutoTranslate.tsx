import React, { useEffect, useRef, useCallback } from 'react';
import { useTranslation } from '../context/TranslationContext';

interface AutoTranslateProps {
    children: React.ReactNode;
}

// Attributes that should be translated
const TRANSLATABLE_ATTRIBUTES = [
    'placeholder',
    'aria-label',
    'title',
    'alt',
    'data-tooltip',
    'data-title',
];

// Cache for translations to avoid re-translating the same text
const translationCache = new Map<string, Map<string, string>>();

// Get cache key for language pair
const getCacheKey = (sourceLang: string, targetLang: string) => `${sourceLang}->${targetLang}`;

// Load cache from localStorage
const loadCacheFromStorage = () => {
    try {
        const stored = localStorage.getItem('auto_translate_cache');
        if (stored) {
            const parsed = JSON.parse(stored);
            Object.entries(parsed).forEach(([key, value]) => {
                translationCache.set(key, new Map(Object.entries(value as Record<string, string>)));
            });
        }
    } catch (err) {
        console.error('Failed to load translation cache:', err);
    }
};

// Save cache to localStorage
const saveCacheToStorage = () => {
    try {
        const cacheObj: Record<string, Record<string, string>> = {};
        translationCache.forEach((translations, key) => {
            cacheObj[key] = Object.fromEntries(translations);
        });
        localStorage.setItem('auto_translate_cache', JSON.stringify(cacheObj));
    } catch (err) {
        console.error('Failed to save translation cache:', err);
    }
};

// Get translation from cache
const getCachedTranslation = (text: string, sourceLang: string, targetLang: string): string | null => {
    const key = getCacheKey(sourceLang, targetLang);
    return translationCache.get(key)?.get(text) || null;
};

// Store translation in cache
const setCachedTranslation = (text: string, translation: string, sourceLang: string, targetLang: string) => {
    const key = getCacheKey(sourceLang, targetLang);
    if (!translationCache.has(key)) {
        translationCache.set(key, new Map());
    }
    translationCache.get(key)!.set(text, translation);
};

// Store original attribute values
interface AttributeOriginal {
    element: HTMLElement;
    attribute: string;
    originalValue: string;
}

export function AutoTranslate({ children }: AutoTranslateProps) {
    const { language } = useTranslation();
    const containerRef = useRef<HTMLDivElement>(null);
    const observerRef = useRef<MutationObserver | null>(null);
    const translationTimeoutRef = useRef<number | null>(null);
    const originalTextsRef = useRef(new Map<Node, string>());
    const originalAttributesRef = useRef<AttributeOriginal[]>([]);

    // Load cache on mount
    useEffect(() => {
        loadCacheFromStorage();
    }, []);

    // Get all text nodes in an element
    const getTextNodes = useCallback((element: HTMLElement): Text[] => {
        const textNodes: Text[] = [];
        const walker = document.createTreeWalker(
            element,
            NodeFilter.SHOW_TEXT,
            {
                acceptNode: (node) => {
                    const parent = node.parentElement;
                    if (!parent) return NodeFilter.FILTER_REJECT;

                    // Skip script, style, noscript tags
                    const tag = parent.tagName.toLowerCase();
                    if (['script', 'style', 'noscript', 'code', 'pre'].includes(tag)) {
                        return NodeFilter.FILTER_REJECT;
                    }

                    // Skip empty text
                    const text = node.textContent?.trim();
                    if (!text) return NodeFilter.FILTER_REJECT;

                    // Skip if parent has data-no-translate attribute
                    if (parent.closest('[data-no-translate]')) {
                        return NodeFilter.FILTER_REJECT;
                    }

                    return NodeFilter.FILTER_ACCEPT;
                }
            }
        );

        let node;
        while ((node = walker.nextNode())) {
            textNodes.push(node as Text);
        }
        return textNodes;
    }, []);

    // Get all elements with translatable attributes
    const getTranslatableAttributes = useCallback((element: HTMLElement): { element: HTMLElement; attribute: string; value: string }[] => {
        const results: { element: HTMLElement; attribute: string; value: string }[] = [];

        // Walk through all elements
        const allElements = element.querySelectorAll('*');
        allElements.forEach(el => {
            if (!(el instanceof HTMLElement)) return;

            // Skip if element has data-no-translate
            if (el.closest('[data-no-translate]')) return;

            TRANSLATABLE_ATTRIBUTES.forEach(attr => {
                const value = el.getAttribute(attr);
                if (value && value.trim()) {
                    results.push({ element: el, attribute: attr, value: value.trim() });
                }
            });

            // Also handle button values
            if (el instanceof HTMLButtonElement && el.value && el.value.trim()) {
                results.push({ element: el, attribute: 'value', value: el.value.trim() });
            }

            // Handle input buttons
            if (el instanceof HTMLInputElement && (el.type === 'button' || el.type === 'submit') && el.value && el.value.trim()) {
                results.push({ element: el, attribute: 'value', value: el.value.trim() });
            }
        });

        return results;
    }, []);

    // Translate text using the API
    const translateTexts = useCallback(async (texts: string[], targetLang: string): Promise<Map<string, string>> => {
        if (targetLang === 'en' || texts.length === 0) {
            return new Map(texts.map(t => [t, t]));
        }

        try {
            const response = await fetch('/api/system/translate/batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    texts,
                    target_lang: targetLang,
                    source_lang: 'en'
                })
            });

            if (response.ok) {
                const data = await response.json();
                const results = new Map<string, string>();
                texts.forEach((text, idx) => {
                    const translation = data.translations?.[idx] || text;
                    results.set(text, translation);
                    setCachedTranslation(text, translation, 'en', targetLang);
                });
                saveCacheToStorage();
                return results;
            }
        } catch (err) {
            console.error('Translation failed:', err);
        }

        // Fallback: return original texts
        return new Map(texts.map(t => [t, t]));
    }, []);

    // Process and translate all text nodes AND attributes
    const processTranslation = useCallback(async () => {
        if (!containerRef.current) return;

        // If English, restore original texts and attributes
        if (language === 'en') {
            originalTextsRef.current.forEach((originalText, node) => {
                if (node.textContent !== originalText) {
                    node.textContent = originalText;
                }
            });
            originalAttributesRef.current.forEach(({ element, attribute, originalValue }) => {
                if (element.getAttribute(attribute) !== originalValue) {
                    element.setAttribute(attribute, originalValue);
                }
            });
            return;
        }

        // Get all text nodes
        const textNodes = getTextNodes(containerRef.current);

        // Get all translatable attributes
        const attributeItems = getTranslatableAttributes(containerRef.current);

        // Collect unique texts to translate (both from nodes and attributes)
        const textsToTranslate: string[] = [];
        const nodeTextMap = new Map<string, Text[]>();
        const attributeTextMap = new Map<string, { element: HTMLElement; attribute: string }[]>();

        // Process text nodes
        textNodes.forEach(node => {
            const text = node.textContent?.trim();
            if (!text) return;

            // Store original text if not already stored
            if (!originalTextsRef.current.has(node)) {
                originalTextsRef.current.set(node, text);
            }

            // Check if already translated
            const cached = getCachedTranslation(text, 'en', language);
            if (cached) {
                node.textContent = cached;
                return;
            }

            // Group nodes by text for batch translation
            if (!nodeTextMap.has(text)) {
                nodeTextMap.set(text, []);
                if (!attributeTextMap.has(text)) {
                    textsToTranslate.push(text);
                }
            }
            nodeTextMap.get(text)!.push(node);
        });

        // Process attributes
        attributeItems.forEach(({ element, attribute, value }) => {
            // Store original attribute if not already stored
            const existingOriginal = originalAttributesRef.current.find(
                o => o.element === element && o.attribute === attribute
            );
            if (!existingOriginal) {
                originalAttributesRef.current.push({ element, attribute, originalValue: value });
            }

            // Check if already translated
            const cached = getCachedTranslation(value, 'en', language);
            if (cached) {
                element.setAttribute(attribute, cached);
                return;
            }

            // Group attributes by text for batch translation
            if (!attributeTextMap.has(value)) {
                attributeTextMap.set(value, []);
                if (!nodeTextMap.has(value)) {
                    textsToTranslate.push(value);
                }
            }
            attributeTextMap.get(value)!.push({ element, attribute });
        });

        // Translate in batches of 100
        if (textsToTranslate.length > 0) {
            for (let i = 0; i < textsToTranslate.length; i += 100) {
                const batch = textsToTranslate.slice(i, i + 100);
                const translations = await translateTexts(batch, language);

                // Apply translations to text nodes
                translations.forEach((translation, originalText) => {
                    const nodes = nodeTextMap.get(originalText) || [];
                    nodes.forEach(node => {
                        node.textContent = translation;
                    });

                    // Apply translations to attributes
                    const attrs = attributeTextMap.get(originalText) || [];
                    attrs.forEach(({ element, attribute }) => {
                        element.setAttribute(attribute, translation);
                    });
                });
            }
        }
    }, [language, getTextNodes, getTranslatableAttributes, translateTexts]);

    // Debounced translation
    const scheduleTranslation = useCallback(() => {
        if (translationTimeoutRef.current) {
            clearTimeout(translationTimeoutRef.current);
        }
        translationTimeoutRef.current = setTimeout(() => {
            processTranslation();
        }, 100);
    }, [processTranslation]);

    // Set up MutationObserver to watch for DOM changes
    useEffect(() => {
        if (!containerRef.current) return;

        observerRef.current = new MutationObserver(() => {
            scheduleTranslation();
        });

        observerRef.current.observe(containerRef.current, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true, // Also watch for attribute changes
            attributeFilter: TRANSLATABLE_ATTRIBUTES
        });

        return () => {
            if (observerRef.current) {
                observerRef.current.disconnect();
            }
            if (translationTimeoutRef.current) {
                clearTimeout(translationTimeoutRef.current);
            }
        };
    }, [scheduleTranslation]);

    // Translate when language changes
    useEffect(() => {
        processTranslation();
    }, [language, processTranslation]);

    // Get language display name
    const getLanguageName = (code: string) => {
        const names: Record<string, string> = {
            en: 'English',
            es: 'Español',
            zh: '中文',
            hi: 'हिन्दी',
            gu: 'ગુજરાતી',
            ko: '한국어',
            sq: 'Shqip',
            ar: 'العربية',
            pt: 'Português',
            fr: 'Français',
            de: 'Deutsch',
            it: 'Italiano',
            ja: '日本語',
            ru: 'Русский',
            vi: 'Tiếng Việt',
            tl: 'Tagalog',
        };
        return names[code] || code.toUpperCase();
    };

    return (
        <>
            {/* Translation accuracy banner */}
            {language !== 'en' && (
                <div
                    className="fixed top-0 left-0 right-0 z-[9999] bg-gradient-to-r from-amber-500/95 to-orange-500/95 text-white py-2 px-4 text-center text-sm font-medium shadow-lg backdrop-blur-sm"
                    data-no-translate
                >
                    <div className="flex items-center justify-center gap-2">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
                        </svg>
                        <span>
                            Translated by <strong>Google Translate</strong> to {getLanguageName(language)}.
                            Translations may not be 100% accurate.
                        </span>
                    </div>
                </div>
            )}
            {/* Add top padding when banner is shown */}
            <div ref={containerRef} style={{ display: 'contents', paddingTop: language !== 'en' ? '40px' : 0 }}>
                {language !== 'en' && <div style={{ height: '40px' }} />}
                {children}
            </div>
        </>
    );
}

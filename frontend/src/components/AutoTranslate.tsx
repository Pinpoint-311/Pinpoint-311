import React, { useEffect, useRef, useCallback } from 'react';
import { useTranslation } from '../context/TranslationContext';

interface AutoTranslateProps {
    children: React.ReactNode;
}

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

export function AutoTranslate({ children }: AutoTranslateProps) {
    const { language } = useTranslation();
    const containerRef = useRef<HTMLDivElement>(null);
    const observerRef = useRef<MutationObserver | null>(null);
    const translationTimeoutRef = useRef<number | null>(null);
    const originalTextsRef = useRef(new Map<Node, string>());

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

    // Process and translate all text nodes
    const processTranslation = useCallback(async () => {
        if (!containerRef.current || language === 'en') {
            // If English, restore original texts
            if (language === 'en') {
                originalTextsRef.current.forEach((originalText, node) => {
                    if (node.textContent !== originalText) {
                        node.textContent = originalText;
                    }
                });
            }
            return;
        }

        const textNodes = getTextNodes(containerRef.current);

        // Collect unique texts to translate
        const textsToTranslate: string[] = [];
        const nodeTextMap = new Map<string, Text[]>();

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
                textsToTranslate.push(text);
            }
            nodeTextMap.get(text)!.push(node);
        });

        // Translate in batches of 100
        if (textsToTranslate.length > 0) {
            for (let i = 0; i < textsToTranslate.length; i += 100) {
                const batch = textsToTranslate.slice(i, i + 100);
                const translations = await translateTexts(batch, language);

                // Apply translations
                translations.forEach((translation, originalText) => {
                    const nodes = nodeTextMap.get(originalText) || [];
                    nodes.forEach(node => {
                        node.textContent = translation;
                    });
                });
            }
        }
    }, [language, getTextNodes, translateTexts]);

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
            characterData: true
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

    return (
        <div ref={containerRef} style={{ display: 'contents' }}>
            {children}
        </div>
    );
}

import React, { useEffect, useRef, useCallback, useState } from 'react';
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

    // Translation progress state
    const [translationProgress, setTranslationProgress] = useState(100);
    const [isTranslating, setIsTranslating] = useState(false);
    const isTranslatingRef = useRef(false); // Ref to prevent re-triggering

    // Dynamic banner message translation
    const [bannerMessage, setBannerMessage] = useState('Translated by Google Translate. Translations may not be 100% accurate.');
    const BANNER_BASE_TEXT = 'Translated by Google Translate. Translations may not be 100% accurate.';

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
            // Get the original text or current content if first time
            let originalText = originalTextsRef.current.get(node);

            // If we don't have original stored, store current (first capture)
            if (!originalText) {
                const currentText = node.textContent?.trim();
                if (!currentText) return;
                originalTextsRef.current.set(node, currentText);
                originalText = currentText;
            }

            // Always use the stored ORIGINAL English text for translation
            const textToTranslate = originalText;

            // Check if already translated (using original text, not current)
            const cached = getCachedTranslation(textToTranslate, 'en', language);
            if (cached) {
                node.textContent = cached;
                return;
            }

            // Group nodes by text for batch translation
            if (!nodeTextMap.has(textToTranslate)) {
                nodeTextMap.set(textToTranslate, []);
                if (!attributeTextMap.has(textToTranslate)) {
                    textsToTranslate.push(textToTranslate);
                }
            }
            nodeTextMap.get(textToTranslate)!.push(node);
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
            setIsTranslating(true);
            isTranslatingRef.current = true;
            setTranslationProgress(0);
            const totalTexts = textsToTranslate.length;
            let translatedCount = 0;

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

                translatedCount += batch.length;
                setTranslationProgress(Math.round((translatedCount / totalTexts) * 100));
            }

            setIsTranslating(false);
            isTranslatingRef.current = false;
            setTranslationProgress(100);
        }
    }, [language, getTextNodes, getTranslatableAttributes, translateTexts]);

    // Debounced translation
    const scheduleTranslation = useCallback(() => {
        // Skip if already translating
        if (isTranslatingRef.current) return;

        if (translationTimeoutRef.current) {
            clearTimeout(translationTimeoutRef.current);
        }
        translationTimeoutRef.current = setTimeout(() => {
            processTranslation();
        }, 300); // Increased debounce
    }, [processTranslation]);

    // Set up MutationObserver to watch for DOM changes
    useEffect(() => {
        if (!containerRef.current) return;

        observerRef.current = new MutationObserver((mutations) => {
            // Ignore mutations that are just user typing in input/textarea
            const isUserInput = mutations.every(mutation => {
                const target = mutation.target as Node;
                const parent = target.parentElement;

                // Check if mutation is in an input, textarea, or contenteditable
                if (target.nodeName === 'INPUT' || target.nodeName === 'TEXTAREA') return true;
                if (parent?.nodeName === 'INPUT' || parent?.nodeName === 'TEXTAREA') return true;
                if (parent?.getAttribute('contenteditable') === 'true') return true;

                // Check if it's a text change in a form field
                if (mutation.type === 'characterData') {
                    const closestInput = (target.parentElement as HTMLElement)?.closest('input, textarea, [contenteditable="true"]');
                    if (closestInput) return true;
                }

                return false;
            });

            // Skip if all mutations are user input
            if (isUserInput) return;

            scheduleTranslation();
        });

        observerRef.current.observe(containerRef.current, {
            childList: true,
            subtree: true,
            characterData: true,
            attributes: true,
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

    // Translate banner message when language changes
    useEffect(() => {
        // Pre-translated messages for common languages (instant display)
        const preTranslatedMessages: Record<string, string> = {
            es: 'Traducido por Google Translate. Las traducciones pueden no ser 100% precisas.',
            zh: '由 Google 翻译翻译。翻译可能不是 100% 准确。',
            hi: 'Google Translate द्वारा अनुवादित। अनुवाद 100% सटीक नहीं हो सकते।',
            gu: 'Google Translate દ્વારા અનુવાદિત. અનુવાદો 100% ચોક્કસ ન હોઈ શકે.',
            ko: 'Google 번역으로 번역되었습니다. 번역이 100% 정확하지 않을 수 있습니다.',
            sq: 'Përkthyer nga Google Translate. Përkthimet mund të mos jenë 100% të sakta.',
            ar: 'مترجم بواسطة Google Translate. قد لا تكون الترجمات دقيقة 100%.',
            pt: 'Traduzido pelo Google Tradutor. As traduções podem não ser 100% precisas.',
            fr: 'Traduit par Google Translate. Les traductions peuvent ne pas être 100% exactes.',
            de: 'Übersetzt von Google Translate. Übersetzungen sind möglicherweise nicht 100% genau.',
            it: 'Tradotto da Google Translate. Le traduzioni potrebbero non essere accurate al 100%.',
            ja: 'Google 翻訳で翻訳されました。翻訳は100%正確ではない場合があります。',
            ru: 'Переведено Google Translate. Переводы могут быть не на 100% точными.',
            vi: 'Được dịch bởi Google Dịch. Bản dịch có thể không chính xác 100%.',
            tl: 'Isinalin ng Google Translate. Ang mga pagsasalin ay maaaring hindi 100% tumpak.',
        };

        if (language === 'en') {
            setBannerMessage(BANNER_BASE_TEXT);
            return;
        }

        // Use pre-translated if available (instant)
        if (preTranslatedMessages[language]) {
            setBannerMessage(preTranslatedMessages[language]);
            return;
        }

        // For other languages, fetch translation from API
        const fetchTranslation = async () => {
            // Check localStorage cache first
            const cached = getCachedTranslation(BANNER_BASE_TEXT, 'en', language);
            if (cached) {
                setBannerMessage(cached);
                return;
            }

            try {
                const result = await translateTexts([BANNER_BASE_TEXT], language);
                const translated = result.get(BANNER_BASE_TEXT);
                if (translated) {
                    setBannerMessage(translated);
                }
            } catch (err) {
                // Fallback to English if translation fails
                setBannerMessage(BANNER_BASE_TEXT);
            }
        };

        fetchTranslation();
    }, [language, translateTexts]);

    return (
        <>
            {/* Translation accuracy banner - in the user's selected language */}
            {language !== 'en' && (
                <div
                    className="fixed top-0 left-0 right-0 z-[100] bg-gradient-to-r from-slate-700/95 to-slate-800/95 text-white/90 shadow-lg backdrop-blur-sm border-b border-white/10"
                    data-no-translate
                >
                    <div className="py-2 px-4 text-center text-sm font-medium">
                        <div className="flex items-center justify-center gap-2">
                            {isTranslating ? (
                                <>
                                    <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                                    </svg>
                                    <span>
                                        {language === 'zh' ? '正在翻译...' :
                                            language === 'es' ? 'Traduciendo...' :
                                                language === 'hi' ? 'अनुवाद किया जा रहा है...' :
                                                    language === 'ko' ? '번역 중...' :
                                                        language === 'sq' ? 'Duke përkthyer...' :
                                                            language === 'ar' ? 'جاري الترجمة...' :
                                                                language === 'fr' ? 'Traduction en cours...' :
                                                                    language === 'de' ? 'Übersetzen...' :
                                                                        language === 'ja' ? '翻訳中...' :
                                                                            language === 'pt' ? 'Traduzindo...' :
                                                                                'Translating...'} {translationProgress}%
                                    </span>
                                </>
                            ) : (
                                <>
                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
                                    </svg>
                                    <span>{bannerMessage}</span>
                                </>
                            )}
                        </div>
                    </div>
                    {/* Progress bar */}
                    {isTranslating && (
                        <div className="h-1 bg-black/20">
                            <div
                                className="h-full bg-white transition-all duration-300 ease-out"
                                style={{ width: `${translationProgress}%` }}
                            />
                        </div>
                    )}
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


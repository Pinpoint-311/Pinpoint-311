import React, { useEffect, useRef, useCallback, useState } from 'react';
import { Languages, RefreshCw } from 'lucide-react';
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

/** The language this product is authored in, and the `source_lang` every
 *  translate call already declares. */
const SOURCE_LANGUAGE = 'en';

/**
 * Mark a subtree that translation deliberately skipped — WCAG 3.1.2 Language of
 * Parts.
 *
 * This component translates text nodes in place: `node.textContent =
 * translation`. After that pass, translated and skipped text are
 * indistinguishable siblings in the same document — there is no wrapper, no
 * class and no marker separating them, which is why this has to happen on the
 * skip branch itself. It is the last moment the difference is known.
 *
 * What goes wrong without it is not subtle. `<html lang>` has already been
 * switched to the target language, so a screen reader applies (say) Spanish
 * pronunciation rules to the whole page — including the code samples and every
 * `[data-no-translate]` block, which are still English. A Spanish synthesiser
 * reading English word by word is not accented English; it is noise.
 *
 * `lang` is not in TRANSLATABLE_ATTRIBUTES, so writing it does not wake the
 * MutationObserver and re-enter translation.
 */
function markAsSourceLanguage(element: HTMLElement): void {
    // Never overwrite a lang the author set deliberately — they know better
    // than this heuristic what language their content is in.
    if (element.getAttribute('lang')) return;
    element.setAttribute('lang', SOURCE_LANGUAGE);
}

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

    /* Measured height of the fixed banner, mirrored into the spacer below it.
     * 40px is the one-line English case and nothing else; see the spacer. */
    const bannerRef = useRef<HTMLDivElement>(null);
    const [bannerHeight, setBannerHeight] = useState(0);

    useEffect(() => {
        const banner = bannerRef.current;
        if (language === 'en' || !banner) {
            setBannerHeight(0);
            return;
        }
        const measure = () => setBannerHeight(banner.offsetHeight);
        measure();
        // Guarded: jsdom and older Safari have no ResizeObserver, and failing to
        // observe must not cost the initial measurement above.
        if (typeof ResizeObserver === 'undefined') return;
        const observer = new ResizeObserver(measure);
        observer.observe(banner);
        return () => observer.disconnect();
    }, [language, isTranslating]);

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
                    if (['script', 'style', 'noscript'].includes(tag)) {
                        return NodeFilter.FILTER_REJECT;
                    }
                    if (tag === 'code' || tag === 'pre') {
                        markAsSourceLanguage(parent);
                        return NodeFilter.FILTER_REJECT;
                    }

                    // Skip empty text
                    const text = node.textContent?.trim();
                    if (!text) return NodeFilter.FILTER_REJECT;

                    // Skip if parent has data-no-translate attribute
                    const optedOut = parent.closest('[data-no-translate]');
                    if (optedOut instanceof HTMLElement) {
                        markAsSourceLanguage(optedOut);
                        return NodeFilter.FILTER_REJECT;
                    }
                    if (optedOut) return NodeFilter.FILTER_REJECT;

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
                    // The backend answers with the source text unchanged when
                    // translation is off or unconfigured. Caching that would
                    // persist English into the Spanish cache in localStorage,
                    // where it keeps winning after translation starts working.
                    if (translation !== text) {
                        setCachedTranslation(text, translation, 'en', targetLang);
                    }
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
                    ref={bannerRef}
                    className="fixed top-0 left-0 right-0 z-[100] bg-gradient-to-r from-slate-700/95 to-slate-800/95 text-white/90 shadow-lg backdrop-blur-sm border-b border-white/10"
                    data-no-translate
                    /* data-no-translate keeps this banner out of the translation
                     * pass, but its text is written in the target language, not the
                     * authoring one — the "Traduciendo…" strings below are literally
                     * Spanish. Without this, `markAsSourceLanguage` would stamp it
                     * `lang="en"` on the way past and a Spanish voice would read it
                     * with English rules (3.1.2). The explicit lang also wins over
                     * that stamp, by design. */
                    lang={language}
                >
                    <div className="py-2 px-4 text-center text-sm font-medium">
                        <div className="flex items-center justify-center gap-2">
                            {isTranslating ? (
                                <>
                                    <RefreshCw className="w-4 h-4 animate-spin" aria-hidden="true" />
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
                                    <Languages className="w-4 h-4" aria-hidden="true" />
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
            {/* Push the page down by however tall the banner actually is.
              *
              * The old version set `paddingTop: 40px` on this element and hard-coded
              * a 40px spacer. The padding was inert — `display: contents` removes
              * the box the padding would apply to — and the 40px was only ever right
              * for a single line of English. "Traducido por Google Translate. Es
              * posible que las traducciones no sean 100% precisas." wraps to two
              * lines well before 320px and three at the narrowest supported width,
              * so the fixed banner sat on top of the page header: content obscured
              * with no way to reach it, which is 1.4.10 Reflow.
              *
              * Measured rather than estimated, because the height depends on the
              * translated string, the viewport and the user's font size — none of
              * which are knowable here. */}
            <div ref={containerRef} style={{ display: 'contents' }}>
                {language !== 'en' && <div aria-hidden="true" style={{ height: bannerHeight }} />}
                {children}
            </div>
        </>
    );
}


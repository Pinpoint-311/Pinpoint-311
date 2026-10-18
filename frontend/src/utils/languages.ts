/**
 * Every language the platform translates into (Google Translate's set).
 *
 * One list for the resident portal's language picker and the staff intake
 * form's "preferred language" field, so a caller can be logged in any language
 * a resident could have picked for themselves -- and their confirmation goes
 * out in it.
 */
export interface PlatformLanguage {
    code: string;
    name: string;
    nativeName: string;
}

import { useEffect, useState } from 'react';

/**
 * What one public translate request may carry (backend/app/api/system.py:
 * MAX_TRANSLATE_TEXTS, MAX_TRANSLATE_TEXT_CHARS, MAX_TRANSLATE_TOTAL_CHARS_ANON),
 * with a little headroom under the character cap.
 */
export const TRANSLATE_MAX_TEXTS = 100;
export const TRANSLATE_MAX_TEXT_CHARS = 2_000;
export const TRANSLATE_MAX_BATCH_CHARS = 7_500;

/**
 * Split strings into requests the public endpoint accepts. A string longer than
 * the per-string limit is left out (it stays in the source language) rather
 * than sent and getting the whole batch refused with a 413.
 */
export function chunkForTranslation(
    texts: string[],
    maxTexts = TRANSLATE_MAX_TEXTS,
    maxChars = TRANSLATE_MAX_BATCH_CHARS,
    maxText = TRANSLATE_MAX_TEXT_CHARS,
): string[][] {
    const chunks: string[][] = [];
    let current: string[] = [];
    let chars = 0;
    for (const t of texts) {
        if (t.length > maxText) continue;
        if (current.length && (current.length >= maxTexts || chars + t.length > maxChars)) {
            chunks.push(current);
            current = [];
            chars = 0;
        }
        current.push(t);
        chars += t.length;
    }
    if (current.length) chunks.push(current);
    return chunks;
}

/**
 * Codes the town's translation provider supports, from
 * GET /api/system/translate/languages -- the backend's list is the one source
 * of truth for *which* languages; this file only supplies their names.
 * Fetched once per page load. Null until it answers, and stays null if it
 * fails, in which case callers offer the full list as before.
 */
let supportedPromise: Promise<string[] | null> | null = null;

export function fetchSupportedLanguageCodes(): Promise<string[] | null> {
    if (!supportedPromise) {
        supportedPromise = fetch('/api/system/translate/languages')
            .then(r => (r.ok ? r.json() : null))
            .then(body => (body && Array.isArray(body.codes) ? (body.codes as string[]) : null))
            .catch(() => null);
    }
    return supportedPromise;
}

/** Test hook: forget the cached answer. */
export function resetSupportedLanguageCache(): void {
    supportedPromise = null;
}

/**
 * LANGUAGES narrowed to what the provider supports. English and `keep` (the
 * language currently chosen) are always included, so a resident is never left
 * with a picker that cannot show where they are.
 */
export function filterSupported(codes: string[] | null, keep?: string): PlatformLanguage[] {
    if (!codes) return LANGUAGES;
    const allowed = new Set([...codes, 'en', ...(keep ? [keep] : [])]);
    return LANGUAGES.filter(l => allowed.has(l.code));
}

export function useSupportedLanguages(keep?: string): PlatformLanguage[] {
    const [codes, setCodes] = useState<string[] | null>(null);
    useEffect(() => {
        let live = true;
        fetchSupportedLanguageCodes().then(c => { if (live) setCodes(c); });
        return () => { live = false; };
    }, []);
    return filterSupported(codes, keep);
}

/** "Spanish (Español)" for a code, or the code itself when unknown. */
export function languageLabel(code?: string | null): string {
    if (!code) return 'English';
    const lang = LANGUAGES.find(l => l.code === code);
    if (!lang) return code;
    return lang.name === lang.nativeName ? lang.name : `${lang.name} (${lang.nativeName})`;
}

export const LANGUAGES: PlatformLanguage[] = [
    { code: 'af', name: 'Afrikaans', nativeName: 'Afrikaans' },
    { code: 'sq', name: 'Albanian', nativeName: 'Shqip' },
    { code: 'am', name: 'Amharic', nativeName: 'አማርኛ' },
    { code: 'ar', name: 'Arabic', nativeName: 'العربية' },
    { code: 'hy', name: 'Armenian', nativeName: 'Հայերեն' },
    { code: 'az', name: 'Azerbaijani', nativeName: 'Azərbaycan' },
    { code: 'eu', name: 'Basque', nativeName: 'Euskara' },
    { code: 'be', name: 'Belarusian', nativeName: 'Беларуская' },
    { code: 'bn', name: 'Bengali', nativeName: 'বাংলা' },
    { code: 'bs', name: 'Bosnian', nativeName: 'Bosanski' },
    { code: 'bg', name: 'Bulgarian', nativeName: 'Български' },
    { code: 'ca', name: 'Catalan', nativeName: 'Català' },
    { code: 'ceb', name: 'Cebuano', nativeName: 'Cebuano' },
    { code: 'ny', name: 'Chichewa', nativeName: 'Chichewa' },
    { code: 'zh', name: 'Chinese (Simplified)', nativeName: '中文(简体)' },
    { code: 'zh-TW', name: 'Chinese (Traditional)', nativeName: '中文(繁體)' },
    { code: 'co', name: 'Corsican', nativeName: 'Corsu' },
    { code: 'hr', name: 'Croatian', nativeName: 'Hrvatski' },
    { code: 'cs', name: 'Czech', nativeName: 'Čeština' },
    { code: 'da', name: 'Danish', nativeName: 'Dansk' },
    { code: 'nl', name: 'Dutch', nativeName: 'Nederlands' },
    { code: 'en', name: 'English', nativeName: 'English' },
    { code: 'eo', name: 'Esperanto', nativeName: 'Esperanto' },
    { code: 'et', name: 'Estonian', nativeName: 'Eesti' },
    { code: 'tl', name: 'Filipino (Tagalog)', nativeName: 'Filipino' },
    { code: 'fi', name: 'Finnish', nativeName: 'Suomi' },
    { code: 'fr', name: 'French', nativeName: 'Français' },
    { code: 'fy', name: 'Frisian', nativeName: 'Frysk' },
    { code: 'gl', name: 'Galician', nativeName: 'Galego' },
    { code: 'ka', name: 'Georgian', nativeName: 'ქართული' },
    { code: 'de', name: 'German', nativeName: 'Deutsch' },
    { code: 'el', name: 'Greek', nativeName: 'Ελληνικά' },
    { code: 'gu', name: 'Gujarati', nativeName: 'ગુજરાતી' },
    { code: 'ht', name: 'Haitian Creole', nativeName: 'Kreyòl Ayisyen' },
    { code: 'ha', name: 'Hausa', nativeName: 'Hausa' },
    { code: 'haw', name: 'Hawaiian', nativeName: 'ʻŌlelo Hawaiʻi' },
    { code: 'he', name: 'Hebrew', nativeName: 'עברית' },
    { code: 'hi', name: 'Hindi', nativeName: 'हिन्दी' },
    { code: 'hmn', name: 'Hmong', nativeName: 'Hmong' },
    { code: 'hu', name: 'Hungarian', nativeName: 'Magyar' },
    { code: 'is', name: 'Icelandic', nativeName: 'Íslenska' },
    { code: 'ig', name: 'Igbo', nativeName: 'Igbo' },
    { code: 'id', name: 'Indonesian', nativeName: 'Bahasa Indonesia' },
    { code: 'ga', name: 'Irish', nativeName: 'Gaeilge' },
    { code: 'it', name: 'Italian', nativeName: 'Italiano' },
    { code: 'ja', name: 'Japanese', nativeName: '日本語' },
    { code: 'jw', name: 'Javanese', nativeName: 'Basa Jawa' },
    { code: 'kn', name: 'Kannada', nativeName: 'ಕನ್ನಡ' },
    { code: 'kk', name: 'Kazakh', nativeName: 'Қазақ' },
    { code: 'km', name: 'Khmer', nativeName: 'ភាសាខ្មែរ' },
    { code: 'rw', name: 'Kinyarwanda', nativeName: 'Kinyarwanda' },
    { code: 'ko', name: 'Korean', nativeName: '한국어' },
    { code: 'ku', name: 'Kurdish (Kurmanji)', nativeName: 'Kurdî' },
    { code: 'ky', name: 'Kyrgyz', nativeName: 'Кыргызча' },
    { code: 'lo', name: 'Lao', nativeName: 'ລາວ' },
    { code: 'la', name: 'Latin', nativeName: 'Latina' },
    { code: 'lv', name: 'Latvian', nativeName: 'Latviešu' },
    { code: 'lt', name: 'Lithuanian', nativeName: 'Lietuvių' },
    { code: 'lb', name: 'Luxembourgish', nativeName: 'Lëtzebuergesch' },
    { code: 'mk', name: 'Macedonian', nativeName: 'Македонски' },
    { code: 'mg', name: 'Malagasy', nativeName: 'Malagasy' },
    { code: 'ms', name: 'Malay', nativeName: 'Bahasa Melayu' },
    { code: 'ml', name: 'Malayalam', nativeName: 'മലയാളം' },
    { code: 'mt', name: 'Maltese', nativeName: 'Malti' },
    { code: 'mi', name: 'Maori', nativeName: 'Māori' },
    { code: 'mr', name: 'Marathi', nativeName: 'मराठी' },
    { code: 'mn', name: 'Mongolian', nativeName: 'Монгол' },
    { code: 'my', name: 'Myanmar (Burmese)', nativeName: 'မြန်မာဘာသာ' },
    { code: 'ne', name: 'Nepali', nativeName: 'नेपाली' },
    { code: 'no', name: 'Norwegian', nativeName: 'Norsk' },
    { code: 'or', name: 'Odia (Oriya)', nativeName: 'ଓଡ଼ିଆ' },
    { code: 'ps', name: 'Pashto', nativeName: 'پښتو' },
    { code: 'fa', name: 'Persian', nativeName: 'فارسی' },
    { code: 'pl', name: 'Polish', nativeName: 'Polski' },
    { code: 'pt', name: 'Portuguese', nativeName: 'Português' },
    { code: 'pa', name: 'Punjabi', nativeName: 'ਪੰਜਾਬੀ' },
    { code: 'ro', name: 'Romanian', nativeName: 'Română' },
    { code: 'ru', name: 'Russian', nativeName: 'Русский' },
    { code: 'sm', name: 'Samoan', nativeName: 'Gagana Samoa' },
    { code: 'gd', name: 'Scots Gaelic', nativeName: 'Gàidhlig' },
    { code: 'sr', name: 'Serbian', nativeName: 'Српски' },
    { code: 'st', name: 'Sesotho', nativeName: 'Sesotho' },
    { code: 'sn', name: 'Shona', nativeName: 'Shona' },
    { code: 'sd', name: 'Sindhi', nativeName: 'سنڌي' },
    { code: 'si', name: 'Sinhala', nativeName: 'සිංහල' },
    { code: 'sk', name: 'Slovak', nativeName: 'Slovenčina' },
    { code: 'sl', name: 'Slovenian', nativeName: 'Slovenščina' },
    { code: 'so', name: 'Somali', nativeName: 'Soomaali' },
    { code: 'es', name: 'Spanish', nativeName: 'Español' },
    { code: 'su', name: 'Sundanese', nativeName: 'Basa Sunda' },
    { code: 'sw', name: 'Swahili', nativeName: 'Kiswahili' },
    { code: 'sv', name: 'Swedish', nativeName: 'Svenska' },
    { code: 'tg', name: 'Tajik', nativeName: 'Тоҷикӣ' },
    { code: 'ta', name: 'Tamil', nativeName: 'தமிழ்' },
    { code: 'tt', name: 'Tatar', nativeName: 'Татар' },
    { code: 'te', name: 'Telugu', nativeName: 'తెలుగు' },
    { code: 'th', name: 'Thai', nativeName: 'ไทย' },
    { code: 'tr', name: 'Turkish', nativeName: 'Türkçe' },
    { code: 'tk', name: 'Turkmen', nativeName: 'Türkmen' },
    { code: 'uk', name: 'Ukrainian', nativeName: 'Українська' },
    { code: 'ur', name: 'Urdu', nativeName: 'اردو' },
    { code: 'ug', name: 'Uyghur', nativeName: 'ئۇيغۇرچە' },
    { code: 'uz', name: 'Uzbek', nativeName: 'Oʻzbek' },
    { code: 'vi', name: 'Vietnamese', nativeName: 'Tiếng Việt' },
    { code: 'cy', name: 'Welsh', nativeName: 'Cymraeg' },
    { code: 'xh', name: 'Xhosa', nativeName: 'isiXhosa' },
    { code: 'yi', name: 'Yiddish', nativeName: 'ייִדיש' },
    { code: 'yo', name: 'Yoruba', nativeName: 'Yorùbá' },
    { code: 'zu', name: 'Zulu', nativeName: 'isiZulu' },
];

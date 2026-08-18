import { useContentTranslation } from '../hooks/useContentTranslation';
import { useTranslation } from '../context/TranslationContext';

interface TranslatedContentProps {
    text: string;
    contentId: string;
    className?: string;
    /**
     * Language of `text` as authored, when the caller knows it. Resident-submitted
     * text carries no recorded source language today, so this defaults to the
     * platform's authoring language.
     */
    sourceLang?: string;
}

/**
 * Displays user-generated content, translated into the reader's language when
 * one is selected.
 *
 * WCAG 3.1.2 (Language of Parts): whatever this renders is tagged with the
 * language it is actually in, because that can differ from the document's. On a
 * Spanish page a translated description is Spanish and is tagged `es`; one
 * still awaiting translation, or whose translation failed, is still in the
 * authoring language and is tagged with that. Without the tag a screen reader
 * applies the document language to both and reads English words with a Spanish
 * synthesiser, which is unintelligible.
 */
export function TranslatedContent({ text, contentId, className = '', sourceLang = 'en' }: TranslatedContentProps) {
    const { language } = useTranslation();
    const { translatedText, isTranslating } = useContentTranslation(text, contentId);

    if (isTranslating) {
        // The original text is still what is on screen — tag it as such.
        return (
            <span className={`${className} opacity-50`} lang={sourceLang}>
                {text}
            </span>
        );
    }

    /* The hook falls back to the original string both when translation is off
     * and when the request failed, so compare the strings rather than trusting
     * the selected language. */
    const renderedLang = translatedText === text ? sourceLang : language;

    return <span className={className} lang={renderedLang}>{translatedText}</span>;
}

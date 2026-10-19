/**
 * The resident's in-progress report, kept for the life of the browser tab.
 *
 * Following the Terms of Service link on the form leaves the portal route, and
 * React unmounts the whole form with it. Coming back used to land on an empty
 * form (or on the home page), so anything typed was gone. The draft lives here
 * between those two visits.
 *
 * sessionStorage, deliberately not localStorage: it is scoped to this tab and
 * dies with it, and the draft carries contact details (name, email, phone)
 * that must not outlive the visit on a shared or library computer. It is
 * cleared on a successful submit and whenever the resident deliberately starts
 * over or goes home.
 *
 * Photos are NOT kept: a screened photo is a server handle that expires, and
 * the originals are megabytes of base64 that would blow the storage quota.
 * Only how many there were is kept, so the form can ask for them again.
 *
 * Every storage access is wrapped: private windows, blocked site data and
 * quota errors all throw, and a draft that cannot be saved must never break
 * the form it is meant to protect.
 */

export const RESIDENT_DRAFT_KEY = 'pinpoint311:resident-draft:v1';

export interface ResidentDraft {
    service_code: string;
    description: string;
    address: string;
    lat: number | null;
    lng: number | null;
    first_name: string;
    last_name: string;
    email: string;
    phone: string;
    is_public: boolean;
    custom_answers: Record<string, string | string[]>;
    preferred_language: string;
    photo_count: number;
}

export function saveResidentDraft(draft: ResidentDraft): void {
    try {
        window.sessionStorage.setItem(RESIDENT_DRAFT_KEY, JSON.stringify(draft));
    } catch {
        /* storage unavailable or full -- the form still works without it */
    }
}

export function loadResidentDraft(): ResidentDraft | null {
    try {
        const raw = window.sessionStorage.getItem(RESIDENT_DRAFT_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object' || typeof parsed.service_code !== 'string') return null;
        const str = (v: unknown) => (typeof v === 'string' ? v : '');
        const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
        return {
            service_code: parsed.service_code,
            description: str(parsed.description),
            address: str(parsed.address),
            lat: num(parsed.lat),
            lng: num(parsed.lng),
            first_name: str(parsed.first_name),
            last_name: str(parsed.last_name),
            email: str(parsed.email),
            phone: str(parsed.phone),
            is_public: parsed.is_public !== false,
            custom_answers:
                parsed.custom_answers && typeof parsed.custom_answers === 'object' && !Array.isArray(parsed.custom_answers)
                    ? parsed.custom_answers
                    : {},
            preferred_language: str(parsed.preferred_language),
            photo_count: typeof parsed.photo_count === 'number' ? parsed.photo_count : 0,
        };
    } catch {
        return null;
    }
}

export function clearResidentDraft(): void {
    try {
        window.sessionStorage.removeItem(RESIDENT_DRAFT_KEY);
    } catch {
        /* nothing to clear if storage is unavailable */
    }
}

/** Whether a draft holds anything worth restoring (an untouched form is not). */
export function draftHasContent(d: ResidentDraft): boolean {
    return Boolean(
        d.description.trim() || d.address.trim() || d.lat != null || d.first_name.trim() ||
        d.last_name.trim() || d.email.trim() || d.phone.trim() || !d.is_public ||
        Object.keys(d.custom_answers).length > 0 || d.photo_count > 0,
    );
}

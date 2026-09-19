// @vitest-environment jsdom
import type React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render as rtlRender, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * What a resident is told when their photo is not on their report.
 *
 * A photo the face-and-plate blur could not clear is held out of `media_urls`,
 * so no public surface renders it. That is correct and it is the whole point.
 * From the tracker, though, it was indistinguishable from the photo having
 * been lost: the resident attached one, was told at the thumbnail that it was
 * being dealt with, and then found a report with no photo on it and no
 * explanation anywhere. The owner's words were "the resident can't even see
 * the withhold alert".
 *
 * The commonest shape of this is the one that used to render nothing at all:
 * a report whose ONLY photo is held, so `media_urls` is empty and the photos
 * card does not draw. The notice therefore cannot live inside that card.
 *
 * A count and no bytes, deliberately. The held photo is unredacted -- nobody
 * has confirmed there is not a face in it -- and this route is
 * unauthenticated.
 */

const HELD_ONLY = {
    service_request_id: 'REQ-001',
    service_code: 'pothole',
    service_name: 'Pothole',
    status: 'open',
    description: 'Deep pothole near the crosswalk',
    address: '12 Main St',
    requested_datetime: '2026-06-03T10:00:00Z',
    media_urls: [],
    photos_pending_review: 1,
    photo_count: 0,
};

const NOTHING_HELD = { ...HELD_ONLY, photos_pending_review: 0 };

const detail = vi.hoisted(() => ({ current: null as any }));

vi.mock('../services/api', () => {
    const api = {
        getPublicRequests: vi.fn().mockImplementation(async () => [detail.current]),
        getPublicRequestDetail: vi.fn().mockImplementation(async () => detail.current),
        getPublicComments: vi.fn().mockResolvedValue([]),
        getPublicAuditLog: vi.fn().mockResolvedValue([]),
        getMapsConfig: vi.fn().mockResolvedValue({}),
    };
    return { api, default: api };
});

vi.mock('../hooks/useContentTranslation', () => ({
    useContentTranslation: (text: string) => ({ translatedText: text, isTranslating: false }),
}));
vi.mock('../context/TranslationContext', () => ({
    useTranslation: () => ({ language: 'en' }),
}));
vi.mock('./RequestDetailMap', () => ({ default: () => null }));

import { AccessibilityProvider } from '../context/AccessibilityContext';
import TrackRequests from './TrackRequests';

const render = (ui: React.ReactElement) => rtlRender(ui, { wrapper: AccessibilityProvider });

if (typeof window.PointerEvent === 'undefined') {
    (window as any).PointerEvent = class PointerEvent extends MouseEvent { };
}

beforeEach(() => {
    localStorage.clear();
    window.scrollTo = vi.fn();
    if (!window.matchMedia) {
        (window as any).matchMedia = () => ({
            matches: false,
            addEventListener: () => { },
            removeEventListener: () => { },
        });
    }
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const openTheReport = async () => {
    const user = userEvent.setup();
    render(<TrackRequests />);
    await user.click(await screen.findByText(/Deep pothole near the crosswalk/));
};

describe('a photo held back from the tracker', () => {
    it('is accounted for, on a report that shows no photos at all', async () => {
        detail.current = HELD_ONLY;
        await openTheReport();

        // media_urls is empty, so the "Submitted Photos" card does not render.
        // This notice has to be outside it or the commonest case says nothing.
        expect(await screen.findByText(/1 photo is waiting to be checked/i)).toBeTruthy();
    });

    it('says why, and that the report itself is unaffected', async () => {
        detail.current = HELD_ONLY;
        await openTheReport();

        // "Where did my photo go" needs an answer, and "is my report stuck"
        // needs a no -- the report goes through either way, which is the part
        // a resident actually cares about.
        const notice = (await screen.findByText(/waiting to be checked/i)).closest('div')!;
        expect(notice.textContent).toMatch(/blurred automatically/i);
        expect(notice.textContent).toMatch(/does not hold up the report/i);
    });

    it('never puts the held photo itself on a public page', async () => {
        // The reason it is being held is that nobody has confirmed there is no
        // face in it, and this route is unauthenticated.
        detail.current = { ...HELD_ONLY, media_pending_review: [{ media: 'data:image/jpeg;base64,FACE', reason: 'provider-error' }] };
        await openTheReport();

        await screen.findByText(/waiting to be checked/i);
        expect(document.body.innerHTML).not.toContain('base64,FACE');
    });

    it('says nothing when nothing was held', async () => {
        detail.current = NOTHING_HELD;
        await openTheReport();

        await screen.findByText(/Deep pothole near the crosswalk/);
        expect(screen.queryByText(/waiting to be checked/i)).toBeNull();
    });
});

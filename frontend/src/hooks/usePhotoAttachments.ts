import { useRef, useState } from 'react';
import { api } from '../services/api';
import type { PhotoState, PhotoStatus } from '../components/PhotoUpload';

/**
 * One attached photo and where it has got to in pick-time screening.
 *
 * Moved here from ResidentPortal so the staff intake form attaches photos the
 * same way: screened and blurred the moment they are picked, quoted at submit
 * by handle, and resent inline only when a handle has expired.
 */
export type AttachedPhoto = {
    id: string;
    previewUrl: string;
    original: string;
    state: PhotoState;
    message?: string;
    handle?: string;
};

/** What the staff form says about a photo the content screen flagged. */
export const STAFF_FLAGGED_MESSAGE = 'Flagged by the content screen. It will be held for staff review, not published. Remove it unless it belongs on the record.';

export interface PhotoAttachmentOptions {
    /**
     * What a pick-time `blocked` verdict means.
     *
     * 'refuse' (the resident form): the photo cannot be attached, and the form
     * will not submit until it is removed.
     * 'attach' (staff intake): the photo stays attached, travels inline, and is
     * redacted -- not moderated -- at submit. The server's staff path has never
     * image-moderated, and this keeps the browser from deciding otherwise.
     */
    blockedVerdict?: 'refuse' | 'attach';
}

export function usePhotoAttachments({ blockedVerdict = 'refuse' }: PhotoAttachmentOptions = {}) {
    /**
     * Photos, and where each one has got to in screening.
     *
     * Screening -- moderation plus the face and plate blur -- used to happen
     * inside the create-request POST, which put a Google Vision round trip on
     * the Submit button: attach a 6MB photo and the form sat under a generic
     * spinner long enough that residents pressed Submit twice. It happens here
     * instead, the moment the photo is picked, while they are still writing the
     * description. By the time they submit, the answer is already in.
     *
     * Each entry keeps three things that look redundant and are not:
     *   previewUrl  what the resident sees. Swapped for the REDACTED image once
     *               screening finishes, so the thumbnail is what the town will
     *               actually publish rather than the original they chose.
     *   original    the bytes as picked, in memory only, kept solely so a handle
     *               that expires mid-form can fall back to the inline path.
     *   handle      what goes into media_urls in place of megabytes of base64.
     */
    const [attachedPhotos, setAttachedPhotos] = useState<AttachedPhoto[]>([]);
    const photoPreviewUrls = attachedPhotos.map((p) => p.previewUrl);
    const photoStatuses: PhotoStatus[] = attachedPhotos.map(
        ({ state, message }) => ({ state, message }),
    );
    const blockedPhotos = attachedPhotos.filter((p) => p.state === 'blocked');
    const photosStillChecking = attachedPhotos.some(
        (p) => p.state === 'uploading' || p.state === 'checking',
    );

    /* Screening verdicts that arrived before their photo row existed, keyed by
     * photo id. Screening and the FileReader preview run in parallel and either
     * can finish first; this is where the fast one waits. */
    const pendingPhotoPatches = useRef<Record<string, Partial<AttachedPhoto>>>({});

    /** Update one photo by identity rather than position.
     *
     * Positions move: a resident can remove the first photo while the third is
     * still being screened, and an index captured when the upload started would
     * by then name someone else's photo. Every screening result is applied by
     * id, and a result for a photo that has since been removed lands nowhere,
     * which is what should happen. */
    const updatePhoto = (id: string, patch: Partial<AttachedPhoto>) => {
        setAttachedPhotos((prev) => {
            if (!prev.some((p) => p.id === id)) {
                // The result beat the preview. Screening starts in parallel with
                // the FileReader and is often faster, so the row this patch names
                // may not exist yet -- and mapping over a list that does not
                // contain it drops the verdict on the floor, after which the
                // insert below writes `uploading` and the photo sits there
                // forever. Hold the patch and let the insert apply it.
                pendingPhotoPatches.current[id] = {
                    ...(pendingPhotoPatches.current[id] || {}),
                    ...patch,
                };
                return prev;
            }
            return prev.map((p) => (p.id === id ? { ...p, ...patch } : p));
        });
    };

    const handlePhotoUpload = (files: FileList) => {
        const remaining = 3 - attachedPhotos.length;
        const chosen = Array.from(files).slice(0, Math.max(0, remaining)); // Max 3 photos

        chosen.forEach((file) => {
            const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;

            // The preview still arrives one FileReader at a time, so the photo
            // count climbs one render at a time -- PhotoUpload's focus handling
            // is built on that and must not be collapsed into a single update.
            const reader = new FileReader();
            reader.onloadend = () => {
                const dataUrl = reader.result as string;
                setAttachedPhotos((prev) => {
                    if (prev.length >= 3) return prev;
                    // Anything screening decided while this preview was loading.
                    const early = pendingPhotoPatches.current[id];
                    delete pendingPhotoPatches.current[id];
                    return [...prev, {
                        id,
                        previewUrl: dataUrl,
                        original: dataUrl,
                        state: 'uploading',
                        ...(early || {}),
                    }];
                });
            };
            reader.readAsDataURL(file);

            // Screening starts immediately and in parallel with the preview:
            // the network round trip is the slow half, and there is no reason
            // for it to wait on a local FileReader.
            api.screenPhoto(file, () => updatePhoto(id, { state: 'checking' }))
                .then((result) => {
                    if (result.status === 'blocked') {
                        if (blockedVerdict === 'attach') {
                            // Staff intake never refuses a photo on a SafeSearch
                            // score -- the clerk is the judge of their own
                            // record. It travels inline instead (the handle holds
                            // no bytes) and is blurred at submit like any other;
                            // the clerk is told so they can take it off.
                            updatePhoto(id, {
                                state: 'review',
                                message: STAFF_FLAGGED_MESSAGE,
                                handle: undefined,
                            });
                            return;
                        }
                        updatePhoto(id, {
                            state: 'blocked',
                            message: result.message
                                || "This photo can't be used. Choose a different one.",
                            handle: undefined,
                        });
                        return;
                    }
                    if (result.status === 'needs_review') {
                        // The handle holds no bytes -- nothing was screened --
                        // so this photo is submitted inline and screened again
                        // at submit. That second pass usually succeeds, in
                        // which case no person is ever involved; only if it
                        // fails too does the photo land in the staff queue.
                        // The message therefore promises the guarantee (it is
                        // attached, and nothing publishes it unchecked) rather
                        // than a human, which this state cannot promise.
                        updatePhoto(id, { state: 'review', message: result.message });
                        return;
                    }
                    updatePhoto(id, {
                        state: 'ready',
                        handle: result.handle,
                        // Show them the blurred version, not the original.
                        ...(result.preview ? { previewUrl: result.preview } : {}),
                        message: result.faces || result.plates
                            ? 'Ready to send — faces and license plates blurred'
                            : undefined,
                    });
                })
                .catch(() => {
                    // The screen call itself never got an answer -- offline,
                    // rate limited, or the backend restarting under us. We did
                    // not ask, so we know nothing about this photo: not whether
                    // it is publishable, not whether anyone will look at it. It
                    // still goes inline with the report and is screened at
                    // submit like every non-portal client's photo.
                    //
                    // No `message`, deliberately: LABELS.error is the only
                    // wording for this state and it is written to be true of
                    // it. Passing the *review* message here is what made a
                    // failed call announce a staff review nobody had queued.
                    updatePhoto(id, { state: 'error' });
                });
        });
    };

    const handleRemovePhoto = (index: number) => {
        setAttachedPhotos((prev) => prev.filter((_, i) => i !== index));
    };

    /** What goes in media_urls, and the originals to resend if a handle went
     *  stale -- the same split the resident form has always submitted. */
    const submission = () => {
        const usable = attachedPhotos.filter((p) => p.state !== 'blocked').slice(0, 3);
        // Staff-attached photos the content screen flagged travel separately, so
        // the server holds them for review instead of publishing them.
        const flagged = usable.filter((p) => p.state === 'review' && p.message === STAFF_FLAGGED_MESSAGE);
        const publishable = usable.filter((p) => !flagged.includes(p));
        const inlineFallback: Record<string, string> = {};
        publishable.forEach((p) => { if (p.handle) inlineFallback[p.handle] = p.original; });
        return {
            media_urls: publishable.map((p) => p.handle || p.original),
            media_flagged: flagged.map((p) => p.original),
            inlineFallback,
        };
    };

    const reset = () => {
        pendingPhotoPatches.current = {};
        setAttachedPhotos([]);
    };

    return {
        photos: attachedPhotos,
        previewUrls: photoPreviewUrls,
        statuses: photoStatuses,
        blocked: blockedPhotos,
        stillChecking: photosStillChecking,
        add: handlePhotoUpload,
        remove: handleRemovePhoto,
        reset,
        submission,
    };
}

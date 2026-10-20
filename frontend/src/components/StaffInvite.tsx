import { CheckCircle2, Info, X } from 'lucide-react';
import type { InviteOutcome } from '../types';

/**
 * The staff-invite pieces of Admin Console -> Users: the "Send an invite
 * email" option on the Add User form, and the line that says afterwards what
 * happened to the invite.
 *
 * The checkbox is the same native input the department checkboxes on that form
 * use, wrapped in its <label> so the association survives a swap to the shared
 * Checkbox component when it lands.
 */

export function InviteCheckbox({ checked, onChange }: { checked: boolean; onChange: (next: boolean) => void }) {
    return (
        <div className="space-y-1">
            <label className="flex items-center gap-2 cursor-pointer">
                <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => onChange(e.target.checked)}
                    aria-describedby="send-invite-hint"
                    className="w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500 focus:ring-primary-500"
                />
                <span className="text-sm text-white/80">Send an invite email</span>
            </label>
            <p id="send-invite-hint" className="text-xs text-white/50 pl-6">
                Tells them they have an account and links to the sign-in page.
            </p>
        </div>
    );
}

/** What to tell the admin about an invite, or null when there is nothing to say. */
export function inviteResultMessage(
    invite: InviteOutcome | undefined,
    email: string,
    context: 'created' | 'resent' = 'created',
): string | null {
    switch (invite) {
        case 'queued':
            return `Invite sent to ${email}.`;
        case 'skipped_email_off':
            return 'Email is turned off, so no invite was sent.';
        case 'queue_failed':
            return context === 'created'
                ? `The account was created, but the invite to ${email} could not be sent right now. Use “Resend invite” to try again.`
                : `The invite to ${email} could not be sent right now. Try again in a few minutes.`;
        default:
            return null;
    }
}

/** The outcome line above the users table. A polite live region, so a screen
 *  reader hears it once without losing its place. */
export function InviteNotice({ message, ok, onDismiss }: { message: string | null; ok: boolean; onDismiss: () => void }) {
    return (
        <div role="status" aria-live="polite">
            {message && (
                <div className={`flex items-start gap-3 p-3 rounded-xl border text-sm ${ok
                    ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-100'
                    : 'bg-amber-500/10 border-amber-400/40 text-amber-100'}`}
                >
                    {ok
                        ? <CheckCircle2 className="w-4 h-4 mt-0.5 flex-shrink-0" aria-hidden="true" />
                        : <Info className="w-4 h-4 mt-0.5 flex-shrink-0" aria-hidden="true" />}
                    <p className="flex-1">{message}</p>
                    <button
                        type="button"
                        onClick={onDismiss}
                        aria-label="Dismiss"
                        className="p-1 -m-1 rounded-md text-white/60 hover:text-white hover:bg-white/10"
                    >
                        <X className="w-4 h-4" aria-hidden="true" />
                    </button>
                </div>
            )}
        </div>
    );
}

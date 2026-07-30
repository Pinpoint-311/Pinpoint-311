import { Check, Copy } from 'lucide-react';

import { defineSteps } from './setupSteps';
import type { StepContext } from './setupSteps';

/**
 * The steps themselves, one registration per provider.
 *
 * Separate from setupSteps.tsx on purpose: that file is the mechanism and does
 * not go stale, this one is content about somebody else's console and will.
 * Vendors reorganise their menus on their own schedule, so entries here are
 * expected to be corrected over time, and a provider with no entry is a normal
 * state -- the card falls back to its plain field list.
 *
 * The rule for writing one: every step either does something or produces
 * something. `check` is what tells a clerk they are in the right place, and it
 * only earns its line when the next thing they do is paste a value. Where a
 * value must be copied exactly -- callback URLs, key restrictions -- give them
 * the copy button rather than a string to retype, because one missing character
 * fails silently and looks like a wrong password.
 */

/** A copy-to-clipboard chip for a value that must be exact. */
function CopyValue({ ctx, id, value }: { ctx: StepContext; id: string; value: string }) {
    return (
        <span className="inline-flex items-center gap-1 align-middle">
            <code className="bg-black/30 px-1.5 py-0.5 rounded text-[11px] text-primary-200 break-all">{value}</code>
            <button
                type="button"
                onClick={() => ctx.copy(value, id)}
                aria-label="Copy to clipboard"
                className="inline-flex text-white/40 hover:text-white/80 transition-colors"
            >
                {ctx.copied === id ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            </button>
        </span>
    );
}

const B = ({ children }: { children: React.ReactNode }) => (
    <strong className="text-white/90">{children}</strong>
);

// ---------------------------------------------------------------------------
// Staff sign-in — Auth0
//
// Transcribed from the long-form guide, which was written against the Auth0
// dashboard and is the one path here that has been walked end to end. The
// ordering is what matters: the callback URLs go in before the credentials come
// out, because a tenant configured in the other order accepts the password and
// then fails on the redirect, which reads as a wrong secret.
// ---------------------------------------------------------------------------

defineSteps('identity', 'auth0', (ctx) => [
    {
        body: (
            <>
                Create the account at <a href="https://auth0.com" target="_blank" rel="noopener noreferrer"
                    className="text-primary-300 underline underline-offset-2">auth0.com</a>, using a{' '}
                <B>shared town email address</B> rather than a personal one — whoever replaces you will
                need to get in. When it asks for a region, pick one in the US if your town or state has a
                rule about where data is held; it cannot be changed afterwards.
            </>
        ),
        check: <>the Auth0 dashboard, with your town's name in the top-left corner.</>,
    },
    {
        body: (
            <>
                In the left menu open <B>Applications → Applications</B> and press <B>Create
                Application</B>. Choose <B>Regular Web Application</B> — not Single Page, not Machine to
                Machine. If it then offers to pick a technology, close that; it only shows sample code.
            </>
        ),
        check: <>a settings page with boxes labelled Domain, Client ID and Client Secret.</>,
    },
    {
        body: (
            <>
                Still on <B>Settings</B>, scroll to <B>Application URIs</B> and paste these in, using the
                copy buttons rather than retyping:
                <span className="mt-2 grid gap-1.5">
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-40 shrink-0">Allowed Callback URLs</span>
                        <CopyValue ctx={ctx} id="a0cb" value={`${ctx.origin}/api/auth/callback`} />
                    </span>
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-40 shrink-0">Allowed Logout URLs</span>
                        <CopyValue ctx={ctx} id="a0lo" value={ctx.origin} />
                    </span>
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-40 shrink-0">Allowed Web Origins</span>
                        <CopyValue ctx={ctx} id="a0wo" value={ctx.origin} />
                    </span>
                </span>
                Then press <B>Save Changes</B> at the bottom.
            </>
        ),
        trouble: <>Do this before the next step. A tenant missing the callback URL accepts the password and then fails on the redirect, which looks like a wrong secret.</>,
    },
    {
        body: <>Copy the three values from that same Settings page into these boxes.</>,
        fields: ['AUTH0_DOMAIN', 'AUTH0_CLIENT_ID', 'AUTH0_CLIENT_SECRET'],
    },
]);

// ---------------------------------------------------------------------------
// Maps — Google
//
// Also transcribed from the long-form guide. Billing is step one rather than a
// footnote: without it Google issues a key that looks correct and the map shows
// a grey box, which is the single most common failure on this page.
// ---------------------------------------------------------------------------

defineSteps('maps', 'google', (ctx) => [
    {
        body: (
            <>
                In <a href="https://console.cloud.google.com" target="_blank" rel="noopener noreferrer"
                    className="text-primary-300 underline underline-offset-2">Google Cloud</a>, open{' '}
                <B>APIs &amp; Services → Library</B> and enable all three of{' '}
                <code className="bg-black/30 px-1 rounded text-[11px]">Maps JavaScript API</code>,{' '}
                <code className="bg-black/30 px-1 rounded text-[11px]">Geocoding API</code> and{' '}
                <code className="bg-black/30 px-1 rounded text-[11px]">Places API</code>. Then open{' '}
                <B>Billing</B> and attach a payment method.
            </>
        ),
        check: <>an "API Enabled" banner on each of the three, and a billing account listed under Billing.</>,
        trouble: <>The payment method is not optional and it is the step people skip. Google will issue a key without it, the key will look correct, and the map will show a grey box saying "this page can't load Google Maps correctly".</>,
    },
    {
        body: (
            <>
                Go to <B>APIs &amp; Services → Credentials → Create Credentials → API key</B>. Then open
                the key and restrict it: under <B>Application restrictions</B> choose <B>Websites</B> and
                add <CopyValue ctx={ctx} id="gmref" value={`${ctx.origin}/*`} /> — the{' '}
                <code className="bg-black/30 px-1 rounded text-[11px]">/*</code> matters. Under{' '}
                <B>API restrictions</B> choose <B>Restrict key</B> and tick the same three APIs.
            </>
        ),
        check: <>your site under Website restrictions, and only those three APIs ticked.</>,
        trouble: <>An unrestricted key can be lifted off your site and run up a bill on the town's card.</>,
    },
    {
        body: <>Paste the key here. The Map ID is optional and only changes how the map looks — leave it empty.</>,
        fields: ['GOOGLE_MAPS_API_KEY', 'GOOGLE_MAPS_MAP_ID'],
        trouble: <>Changes to a Google key can take up to five minutes. If the map is still grey straight after saving, wait before changing anything else.</>,
    },
]);

// ---------------------------------------------------------------------------
// Text messages — Twilio
//
// Short because the console is short: everything needed is on the dashboard
// home page, and the only real trap is the number format.
// ---------------------------------------------------------------------------

defineSteps('sms', 'twilio', () => [
    {
        body: (
            <>
                Sign in at <a href="https://console.twilio.com" target="_blank" rel="noopener noreferrer"
                    className="text-primary-300 underline underline-offset-2">console.twilio.com</a>. The{' '}
                <B>Account SID</B> and <B>Auth Token</B> are on the dashboard home page.
            </>
        ),
        fields: ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN'],
    },
    {
        body: <>Buy or select a number under <B>Phone Numbers → Manage → Active numbers</B>, and enter it in <code className="bg-black/30 px-1 rounded text-[11px]">+1XXXXXXXXXX</code> form.</>,
        fields: ['TWILIO_PHONE_NUMBER'],
        trouble: <>It has to be a number you own in Twilio. A trial account can only text numbers you have verified.</>,
    },
]);

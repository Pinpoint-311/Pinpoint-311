import { useEffect, useState } from 'react';
import { api, type AuthStatus } from '../services/api';

/**
 * Which staff sign-in provider this town is on, as the town would name it.
 *
 * Staff sign-in is pluggable (Auth0, Microsoft Entra ID, Okta, any OIDC
 * provider), but the copy around it said "Auth0" everywhere, so a town on
 * Entra was told its staff would sign in with a service it had never heard
 * of. Anything that wants to say who staff sign in with reads it from here.
 *
 * `status` is `undefined` while loading or when the request failed, which the
 * copy treats as "don't know" (neutral wording) rather than "not configured".
 */
export interface SignInProvider {
    status: AuthStatus | undefined;
    /** Catalog display name, or null when unknown or not configured. */
    name: string | null;
    /** True only when the server said no provider is configured. */
    unconfigured: boolean;
}

export function useSignInProvider(): SignInProvider {
    const [status, setStatus] = useState<AuthStatus | undefined>(undefined);

    useEffect(() => {
        let alive = true;
        api.getAuthStatus()
            .then(s => { if (alive) setStatus(s); })
            .catch(() => { /* neutral copy is the fallback */ });
        return () => { alive = false; };
    }, []);

    return {
        status,
        name: status?.auth0_configured ? (status.provider_name || null) : null,
        unconfigured: status !== undefined && !status.auth0_configured,
    };
}

/** The sentence a staff-account screen shows about how people sign in. */
export function signInSentence({ name, unconfigured }: Pick<SignInProvider, 'name' | 'unconfigured'>): string {
    if (unconfigured) {
        return 'Staff sign-in isn’t set up yet. Choose a sign-in provider in Setup & Integrations before this person can log in. Pinpoint never stores a password.';
    }
    if (name) {
        return `Staff sign in with ${name} using their work email. Pinpoint never stores a password.`;
    }
    return 'Staff sign in through your town’s sign-in provider using their work email. Pinpoint never stores a password.';
}

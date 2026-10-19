import { Shield } from 'lucide-react';
import { useSignInProvider, signInSentence } from '../hooks/useSignInProvider';

/**
 * The "how will this person sign in" note on the staff-account forms.
 *
 * It read "Users log in via Auth0 SSO" on every town, including the ones on
 * Microsoft Entra ID or Okta. It now names whatever /api/auth/status reports,
 * and says something true but provider-neutral until that answer arrives.
 */
export default function SignInProviderNote() {
    const provider = useSignInProvider();
    return (
        <div
            className={provider.unconfigured
                ? 'p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-sm text-amber-200'
                : 'p-3 rounded-lg bg-blue-500/10 border border-blue-500/20 text-sm text-blue-200'}
            data-testid="sign-in-provider-note"
        >
            <p className="font-medium flex items-center gap-1.5">
                <Shield className="w-4 h-4" aria-hidden="true" />
                {provider.name ? `Single sign-on with ${provider.name}` : 'Single sign-on'}
            </p>
            <p className={provider.unconfigured ? 'text-amber-200/70 mt-1' : 'text-blue-200/70 mt-1'}>
                {signInSentence(provider)}
            </p>
        </div>
    );
}

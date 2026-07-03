import { useState } from 'react';
import { Eye, EyeOff, Lock, CheckCircle } from 'lucide-react';

/**
 * A credential/config input tuned for non-technical staff:
 *   - a show/hide reveal toggle on secrets, so a clerk can eyeball a pasted
 *     key and catch a wrong or truncated paste before saving;
 *   - a "Saved" badge + "leave blank to keep" affordance for already-stored
 *     secrets, so re-editing never forces re-entry;
 *   - inline plain-language help.
 *
 * Whitespace is NOT trimmed here (that would fight mid-word typing); callers
 * trim credential values at save time instead — see ServiceProviders /
 * GovtechIntegrations save handlers.
 */
export default function SecretField({
    label, value, onChange, secret = false, placeholder, help,
    savedHint = false, required = false, autoFocus = false,
}: {
    label: string;
    value: string;
    onChange: (v: string) => void;
    secret?: boolean;
    placeholder?: string;
    help?: string;
    savedHint?: boolean;
    required?: boolean;
    autoFocus?: boolean;
}) {
    const [reveal, setReveal] = useState(false);
    const isPassword = secret && !reveal;

    return (
        <div>
            <label className="text-[11px] uppercase tracking-wider text-white/60 mb-1.5 font-semibold flex items-center gap-1.5">
                {secret && <Lock className="w-3 h-3 text-white/35" aria-hidden="true" />}
                {label}
                {required && !savedHint && <span className="normal-case tracking-normal text-amber-300 font-medium">(required)</span>}
                {savedHint && (
                    <span className="ml-auto normal-case tracking-normal text-[10px] font-medium text-emerald-300/80 inline-flex items-center gap-1">
                        <CheckCircle className="w-3 h-3" aria-hidden="true" /> Saved
                    </span>
                )}
            </label>
            <div className="relative">
                <input
                    type={isPassword ? 'password' : 'text'}
                    autoFocus={autoFocus}
                    placeholder={savedHint ? '•••••••••  leave blank to keep' : (placeholder || '')}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    className={`w-full rounded-xl bg-white/[0.04] border border-white/10 text-white text-sm px-3.5 py-2.5 ${secret ? 'pr-10' : ''} placeholder:text-white/40 transition-all focus:outline-none focus:border-primary-400/50 focus:bg-white/[0.06] focus:shadow-[0_0_0_3px_rgba(99,102,241,0.15)]`}
                    spellCheck={false}
                    autoComplete="off"
                />
                {secret && (
                    <button
                        type="button"
                        onClick={() => setReveal(v => !v)}
                        className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-white/40 hover:text-white/80 hover:bg-white/10 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60"
                        aria-label={reveal ? 'Hide value' : 'Show value'}
                        title={reveal ? 'Hide' : 'Show'}
                        tabIndex={-1}
                    >
                        {reveal ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                )}
            </div>
            {help && <p className="text-white/50 text-xs mt-1.5 leading-relaxed">{help}</p>}
        </div>
    );
}

import React, { useEffect, useId, useRef, useState } from 'react';
import {
    Save, Upload, X, Sparkles, Plus, Globe, Facebook, Instagram, Youtube, Twitter, Linkedin, ExternalLink,
} from 'lucide-react';
import { Button, Card, Input, Select, Tooltip } from './ui';
import { api } from '../services/api';
import type { SystemSettings } from '../types';
import { validateDomain, validateSocialUrl, DOMAIN_EXAMPLE } from './brandingValidation';

/* Admin Console -> Branding.
 *
 * Moved out of AdminConsole.tsx so it can be tested on its own, and reworked
 * after a WCAG 2.1 AA review of this page:
 *  - upload controls are real buttons (they were a <label> around a
 *    display:none file input, which Tab skipped entirely);
 *  - every field has a programmatic label, and helper text is linked with
 *    aria-describedby;
 *  - the custom domain and social links are checked as the admin types, with
 *    the message tied to the field, and Save is blocked while one is wrong;
 *  - icon-only buttons get a tooltip that shows on focus as well as hover;
 *  - nothing here has a fixed height, so user text-spacing overrides
 *    (WCAG 1.4.12) grow the layout instead of clipping it. */

export interface SocialLinkRow {
    platform: string;
    url: string;
    icon: string;
}

export type BrandingForm = Partial<SystemSettings> & {
    custom_domain?: string;
    social_links?: SocialLinkRow[];
    privacy_policy?: string | null;
    terms_of_service?: string | null;
    accessibility_statement?: string | null;
};

interface BrandingSettingsProps {
    form: BrandingForm;
    setForm: React.Dispatch<React.SetStateAction<BrandingForm>>;
    onSave: () => void;
    isLoading: boolean;
    setIsLoading: (v: boolean) => void;
}

const ICON_FOR_PLATFORM: Record<string, string> = {
    website: 'Globe',
    facebook: 'Facebook',
    instagram: 'Instagram',
    youtube: 'Youtube',
    twitter: 'Twitter',
    linkedin: 'Linkedin',
};

const PLATFORM_OPTIONS = [
    { value: 'website', label: 'Website' },
    { value: 'facebook', label: 'Facebook' },
    { value: 'instagram', label: 'Instagram' },
    { value: 'youtube', label: 'YouTube' },
    { value: 'twitter', label: 'X (Twitter)' },
    { value: 'linkedin', label: 'LinkedIn' },
];

function PlatformIcon({ icon }: { icon: string }) {
    const cls = 'w-5 h-5';
    switch (icon) {
        case 'Facebook': return <Facebook className={`${cls} text-blue-400`} aria-hidden="true" />;
        case 'Instagram': return <Instagram className={`${cls} text-pink-400`} aria-hidden="true" />;
        case 'Youtube': return <Youtube className={`${cls} text-red-400`} aria-hidden="true" />;
        case 'Twitter': return <Twitter className={`${cls} text-sky-400`} aria-hidden="true" />;
        case 'Linkedin': return <Linkedin className={`${cls} text-blue-400`} aria-hidden="true" />;
        default: return <Globe className={`${cls} text-blue-400`} aria-hidden="true" />;
    }
}

/** Shared look for buttons on this page that are not ui/Button. */
const FOCUS_RING = 'focus:outline-none focus-visible:ring-[3px] focus-visible:ring-amber-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#1B1B3A]';

/* ------------------------------------------------------------------ */
/* Upload control                                                     */
/* ------------------------------------------------------------------ */

interface ImageUploadFieldProps {
    /** "Logo", "Favicon" -- used in the label, button name and alt text. */
    label: string;
    value: string | null | undefined;
    accept: string;
    helperText: string;
    onUploaded: (url: string) => void;
    onRemove: () => void;
    thumbClassName: string;
}

export function ImageUploadField({ label, value, accept, helperText, onUploaded, onRemove, thumbClassName }: ImageUploadFieldProps) {
    const inputRef = useRef<HTMLInputElement>(null);
    const baseId = useId();
    const labelId = `${baseId}-label`;
    const helperId = `${baseId}-helper`;
    const statusId = `${baseId}-status`;
    const [status, setStatus] = useState<{ kind: 'idle' | 'busy' | 'error'; text: string }>({ kind: 'idle', text: '' });
    const lower = label.toLowerCase();

    const handleFile = async (file: File | undefined) => {
        if (!file) return;
        setStatus({ kind: 'busy', text: `Uploading ${lower}…` });
        try {
            const result = await api.uploadImage(file);
            onUploaded(result.url);
            setStatus({ kind: 'idle', text: `${label} uploaded.` });
        } catch (err) {
            console.error(`${label} upload failed:`, err);
            setStatus({ kind: 'error', text: `Could not upload the ${lower}. Try a smaller image, or a PNG or JPG file.` });
        } finally {
            if (inputRef.current) inputRef.current.value = '';
        }
    };

    return (
        <div role="group" aria-labelledby={labelId}>
            <p id={labelId} className="block text-sm font-medium text-white/70 mb-2">{label}</p>
            <div className="flex flex-wrap items-center gap-3">
                {value && <img src={value} alt={`Current ${lower}`} className={thumbClassName} />}
                {/* A real button, so it is in the Tab order and works with
                  * Enter and Space. It opens the file picker by clicking the
                  * hidden input, which is kept out of the Tab order and the
                  * accessibility tree so it is not announced twice. */}
                <button
                    type="button"
                    onClick={() => inputRef.current?.click()}
                    aria-describedby={`${helperId} ${status.text ? statusId : ''}`.trim()}
                    disabled={status.kind === 'busy'}
                    className={`flex-1 min-w-[10rem] flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-white/5 border border-white/[0.55] hover:bg-white/10 hover:border-white/80 transition-colors text-sm text-white/80 disabled:opacity-60 ${FOCUS_RING}`}
                >
                    <Upload className="w-4 h-4" aria-hidden="true" />
                    <span>{value ? `Replace ${lower}` : `Upload ${lower}`}</span>
                </button>
                <input
                    ref={inputRef}
                    type="file"
                    accept={accept}
                    className="hidden"
                    tabIndex={-1}
                    aria-hidden="true"
                    data-testid={`${lower}-file-input`}
                    onChange={(e) => handleFile(e.target.files?.[0])}
                />
                {value && (
                    <Tooltip content={`Remove ${lower}`}>
                        <button
                            type="button"
                            onClick={() => { onRemove(); setStatus({ kind: 'idle', text: `${label} removed.` }); }}
                            className={`p-2 rounded-lg bg-red-500/10 border border-red-300 text-red-200 hover:bg-red-500/25 transition-colors ${FOCUS_RING}`}
                            aria-label={`Remove ${lower}`}
                        >
                            <X className="w-4 h-4" aria-hidden="true" />
                        </button>
                    </Tooltip>
                )}
            </div>
            <p id={helperId} className="mt-1.5 text-sm text-white/50">{helperText}</p>
            <p
                id={statusId}
                role={status.kind === 'error' ? 'alert' : 'status'}
                className={status.kind === 'error' ? 'error-message' : 'sr-only'}
            >
                {status.text}
            </p>
        </div>
    );
}

/* ------------------------------------------------------------------ */
/* Legal document field                                               */
/* ------------------------------------------------------------------ */

function LegalField({ id, label, previewHref, value, placeholder, helper, onChange }: {
    id: string; label: string; previewHref: string; value: string; placeholder: string; helper: string;
    onChange: (v: string | null) => void;
}) {
    return (
        <div>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                <label htmlFor={id} className="text-sm font-medium text-white/70">{label}</label>
                <a
                    href={previewHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="preview-link inline-flex items-center gap-1 text-sm text-primary-300 underline decoration-1 underline-offset-2 hover:text-white hover:decoration-2 focus-visible:text-white focus-visible:decoration-2 rounded"
                >
                    Preview {label.toLowerCase()}
                    <ExternalLink className="w-3.5 h-3.5" aria-hidden="true" />
                    <span className="sr-only">(opens in a new tab)</span>
                </a>
            </div>
            <textarea
                id={id}
                value={value}
                onChange={(e) => onChange(e.target.value || null)}
                placeholder={placeholder}
                aria-describedby={`${id}-helper`}
                rows={6}
                className="glass-input min-h-[8rem] font-mono text-sm resize-y"
            />
            <p id={`${id}-helper`} className="text-sm text-white/50 mt-1">{helper}</p>
        </div>
    );
}

/* ------------------------------------------------------------------ */
/* Page                                                               */
/* ------------------------------------------------------------------ */

export function BrandingSettings({ form, setForm, onSave, isLoading, setIsLoading }: BrandingSettingsProps) {
    const links: SocialLinkRow[] = form.social_links || [];
    const [domainTouched, setDomainTouched] = useState(false);
    const [domainRequired, setDomainRequired] = useState(false);
    const [touchedLinks, setTouchedLinks] = useState<Record<number, boolean>>({});
    const [saveBlocked, setSaveBlocked] = useState('');
    // The address DNS should point at comes from this deployment, never a
    // hardcoded IP: every town runs on its own server.
    const [serverIp, setServerIp] = useState<string | null>(null);
    useEffect(() => {
        let live = true;
        api.getDomainStatus()
            .then((s) => { if (live) setServerIp(s.server_ip || null); })
            .catch(() => { /* unknown: the copy below says so */ });
        return () => { live = false; };
    }, []);
    const ipLabel = serverIp ?? "this server's public IP address";
    const domainInputRef = useRef<HTMLInputElement>(null);

    const domainError = validateDomain(form.custom_domain, domainRequired);
    const shownDomainError = domainTouched ? domainError : null;
    const linkErrors = links.map((l) => validateSocialUrl(l.platform, l.url));

    const setLinks = (next: SocialLinkRow[]) => setForm((p) => ({ ...p, social_links: next }));

    const updateLink = (index: number, patch: Partial<SocialLinkRow>) => {
        const next = [...links];
        next[index] = { ...next[index], ...patch };
        setLinks(next);
    };

    const removeLink = (index: number) => {
        setLinks(links.filter((_, i) => i !== index));
        // Re-key touched state so it follows the rows that moved up.
        setTouchedLinks((t) => {
            const out: Record<number, boolean> = {};
            Object.entries(t).forEach(([k, v]) => {
                const i = Number(k);
                if (i < index) out[i] = v;
                else if (i > index) out[i - 1] = v;
            });
            return out;
        });
    };

    const handleSave = () => {
        const badDomain = validateDomain(form.custom_domain);
        const badLinks = linkErrors.map((e, i) => (e ? i : -1)).filter((i) => i >= 0);
        if (badDomain || badLinks.length) {
            setDomainTouched(true);
            setTouchedLinks((t) => ({ ...t, ...Object.fromEntries(badLinks.map((i) => [i, true])) }));
            const parts: string[] = [];
            if (badDomain) parts.push('the custom domain');
            if (badLinks.length) parts.push(badLinks.length === 1 ? '1 social link' : `${badLinks.length} social links`);
            setSaveBlocked(`Not saved. Fix ${parts.join(' and ')} first. Each problem is described under its field.`);
            // Put focus on the first field that needs fixing.
            const first = badDomain
                ? domainInputRef.current
                : document.getElementById(`social-link-url-${badLinks[0]}`);
            first?.focus();
            return;
        }
        setSaveBlocked('');
        onSave();
    };

    const handleConfigureDomain = async () => {
        setDomainRequired(true);
        setDomainTouched(true);
        const domain = (form.custom_domain || '').trim();
        if (validateDomain(domain, true)) {
            domainInputRef.current?.focus();
            return;
        }
        setIsLoading(true);
        try {
            const result = await api.configureDomain(domain);
            if (result.status === 'success') {
                alert(
                    `${result.message}\n\n` +
                    `Your site will be available at:\n${result.url}\n\n` +
                    `HTTPS certificate is being automatically provisioned by Caddy.`
                );
            } else if (result.status === 'partial') {
                alert(
                    `${result.message}\n\n` +
                    `Next step: ${result.next_step || 'Restart Caddy container'}\n\n` +
                    `On the server, in the Pinpoint 311 folder, run:\ndocker compose restart caddy`
                );
            } else {
                alert(`Error: ${result.message}`);
            }
        } catch (err: any) {
            alert(`Error: ${err.message}`);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <h1 className="text-xl sm:text-2xl font-bold text-white">Branding Settings</h1>
                <Button className="w-full sm:w-auto" leftIcon={<Save className="w-4 h-4" />} onClick={handleSave} isLoading={isLoading}>
                    Save Changes
                </Button>
            </div>
            <div role="alert" className={saveBlocked ? 'p-3 rounded-xl bg-red-500/15 border border-red-300/60 text-sm text-red-100' : 'sr-only'}>
                {saveBlocked}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-6">
                <Card>
                    <section aria-labelledby="branding-identity-heading" className="space-y-4">
                        <h2 id="branding-identity-heading" className="text-lg font-semibold text-white">Name and images</h2>
                        <Input
                            label="Municipality name"
                            value={form.township_name || ''}
                            onChange={(e) => setForm((p) => ({ ...p, township_name: e.target.value }))}
                        />
                        <Input
                            label="Hero text"
                            helperText="The welcome line residents see at the top of the portal."
                            value={form.hero_text || ''}
                            onChange={(e) => setForm((p) => ({ ...p, hero_text: e.target.value }))}
                        />
                        <ImageUploadField
                            label="Logo"
                            value={form.logo_url}
                            accept="image/*"
                            helperText="PNG, JPG or SVG. A wide logo on a clear background works best."
                            thumbClassName="h-10 rounded"
                            onUploaded={(url) => setForm((p) => ({ ...p, logo_url: url }))}
                            onRemove={() => setForm((p) => ({ ...p, logo_url: '' }))}
                        />
                        <ImageUploadField
                            label="Favicon"
                            value={form.favicon_url}
                            accept="image/*,.ico"
                            helperText="The small icon shown in browser tabs. A square PNG or ICO file."
                            thumbClassName="h-8 w-8 rounded"
                            onUploaded={(url) => setForm((p) => ({ ...p, favicon_url: url }))}
                            onRemove={() => setForm((p) => ({ ...p, favicon_url: '' }))}
                        />
                    </section>
                </Card>

                <Card>
                    <section aria-labelledby="branding-preview-heading">
                        <h2 id="branding-preview-heading" className="text-lg font-semibold text-white mb-4">Preview</h2>
                        <div className="p-4 rounded-xl bg-black/20 space-y-4">
                            {form.logo_url ? (
                                <img
                                    src={form.logo_url}
                                    alt={form.township_name ? `${form.township_name} logo preview` : 'Logo preview'}
                                    className="h-16"
                                />
                            ) : (
                                <div className="flex items-center gap-3">
                                    {/* Placeholder art only. The words beside it
                                      * say what it is, so the graphic is hidden
                                      * from assistive tech. */}
                                    <div
                                        className="w-16 h-16 shrink-0 rounded-2xl flex items-center justify-center"
                                        style={{ background: 'linear-gradient(135deg, #6366f1, #6366f1dd)' }}
                                        aria-hidden="true"
                                        data-testid="logo-placeholder"
                                    >
                                        <Sparkles className="w-8 h-8 text-white" aria-hidden="true" />
                                    </div>
                                    <p className="text-sm text-white/70">No logo uploaded</p>
                                </div>
                            )}
                            <p className="text-xl font-bold text-white break-words">{form.township_name}</p>
                            <p className="text-white/60 break-words">{form.hero_text}</p>
                        </div>
                    </section>
                </Card>
            </div>

            {/* Domain Connection */}
            <Card className="mt-6">
                <section aria-labelledby="branding-domain-heading" aria-describedby="branding-domain-intro">
                    <h2 id="branding-domain-heading" className="text-lg font-semibold text-white mb-4">Custom Domain</h2>
                    <p id="branding-domain-intro" className="text-sm text-white/50 mb-4">
                        Connect your own domain (for example, {DOMAIN_EXAMPLE}) to this 311 portal.
                    </p>

                    <div className="space-y-4">
                        <div className="p-4 rounded-xl bg-white/5 border border-white/10">
                            <p className="text-sm font-medium text-white mb-2">Current URL</p>
                            <code className="text-primary-300 text-sm bg-black/30 px-2 py-1 rounded break-all">
                                {window.location.origin}
                            </code>
                        </div>

                        <div className="p-4 rounded-xl bg-primary-500/10 border border-primary-500/20">
                            <div className="flex flex-col sm:flex-row sm:items-start gap-2">
                                <div className="flex-1 min-w-0">
                                    <Input
                                        ref={domainInputRef}
                                        id="branding-custom-domain"
                                        label="Custom domain"
                                        placeholder={DOMAIN_EXAMPLE}
                                        autoComplete="off"
                                        spellCheck={false}
                                        inputMode="url"
                                        helperText="Once your DNS records are in place, enter your domain and select Configure Domain. HTTPS is set up automatically."
                                        value={form.custom_domain || ''}
                                        onChange={(e) => setForm((p) => ({ ...p, custom_domain: e.target.value }))}
                                        onBlur={() => setDomainTouched(true)}
                                        error={shownDomainError || undefined}
                                        errorAsAlert={false}
                                    />
                                </div>
                                <Button className="sm:mt-7" onClick={handleConfigureDomain} isLoading={isLoading}>
                                    Configure Domain
                                </Button>
                            </div>
                        </div>

                        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/20">
                            <h3 className="text-sm font-medium text-amber-300 mb-3">Step 1: Set up DNS records first</h3>
                            <ol className="text-sm text-white/70 space-y-2 list-decimal list-inside">
                                <li>Log into your domain registrar (GoDaddy, Namecheap, etc.)</li>
                                <li>Add an <strong className="text-white">A record</strong> pointing to: <code className="text-primary-300 bg-black/30 px-1 rounded">{ipLabel}</code></li>
                                <li>Wait 5-30 minutes for DNS to update</li>
                                <li>Enter the domain above and select Configure Domain</li>
                            </ol>
                        </div>

                        <div className="p-4 rounded-xl bg-white/5 border border-white/10 overflow-x-auto">
                            <table className="w-full text-sm">
                                <caption className="text-left text-sm font-medium text-white mb-3">DNS records to add</caption>
                                <thead>
                                    <tr className="text-white/50">
                                        <th scope="col" className="text-left py-1">Type</th>
                                        <th scope="col" className="text-left py-1">Host</th>
                                        <th scope="col" className="text-left py-1">Value</th>
                                    </tr>
                                </thead>
                                <tbody className="text-white/80">
                                    <tr>
                                        <td className="py-1">A</td>
                                        <td className="py-1">@ or 311</td>
                                        <td className="py-1"><code className="text-primary-300">{ipLabel}</code></td>
                                    </tr>
                                    <tr>
                                        <td className="py-1">A</td>
                                        <td className="py-1">www</td>
                                        <td className="py-1"><code className="text-primary-300">{ipLabel}</code></td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </section>
            </Card>

            {/* Social Links */}
            <Card className="mt-6">
                <section aria-labelledby="branding-social-heading" aria-describedby="branding-social-intro">
                    <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                        <div>
                            <h2 id="branding-social-heading" className="text-lg font-semibold text-white">Social Links</h2>
                            <p id="branding-social-intro" className="text-sm text-white/50">Add links to display in the resident portal footer</p>
                        </div>
                        <Button
                            size="sm"
                            leftIcon={<Plus className="w-4 h-4" />}
                            onClick={() => setLinks([...links, { platform: 'website', url: '', icon: 'Globe' }])}
                        >
                            Add Link
                        </Button>
                    </div>

                    <div className="space-y-3">
                        {links.map((link, index) => {
                            const urlId = `social-link-url-${index}`;
                            const error = touchedLinks[index] ? linkErrors[index] : null;
                            const markTouched = () => setTouchedLinks((t) => ({ ...t, [index]: true }));
                            return (
                                <fieldset key={index} className="p-3 rounded-xl bg-white/5 border border-white/10 min-w-0">
                                    <legend className="sr-only">Link {index + 1}</legend>
                                    <div className="flex flex-wrap items-start gap-3">
                                        <div className="w-10 h-10 shrink-0 rounded-lg bg-white/10 flex items-center justify-center" aria-hidden="true">
                                            <PlatformIcon icon={link.icon} />
                                        </div>
                                        <div className="w-40 shrink-0">
                                            <Select
                                                id={`social-link-platform-${index}`}
                                                aria-label={`Platform for link ${index + 1}`}
                                                value={link.platform}
                                                onChange={(e) => {
                                                    updateLink(index, { platform: e.target.value, icon: ICON_FOR_PLATFORM[e.target.value] || 'Globe' });
                                                }}
                                                options={PLATFORM_OPTIONS}
                                            />
                                        </div>
                                        <div className="flex-1 min-w-[12rem]">
                                            <Input
                                                id={urlId}
                                                type="url"
                                                inputMode="url"
                                                aria-label={`Web address for link ${index + 1}`}
                                                placeholder="https://..."
                                                value={link.url}
                                                onChange={(e) => {
                                                    updateLink(index, { url: e.target.value });
                                                    if (touchedLinks[index] === undefined && e.target.value.length > 8) markTouched();
                                                }}
                                                onBlur={markTouched}
                                                error={error || undefined}
                                                errorAsAlert={false}
                                            />
                                        </div>
                                        <Tooltip content={`Remove link ${index + 1}`}>
                                            <button
                                                type="button"
                                                onClick={() => removeLink(index)}
                                                className={`p-2.5 rounded-lg bg-red-500/10 border border-red-300 text-red-200 hover:bg-red-500/25 transition-colors ${FOCUS_RING}`}
                                                aria-label={`Remove link ${index + 1}`}
                                            >
                                                <X className="w-4 h-4" aria-hidden="true" />
                                            </button>
                                        </Tooltip>
                                    </div>
                                </fieldset>
                            );
                        })}
                        {links.length === 0 && (
                            <div className="text-center py-8 text-white/50">
                                <Globe className="w-8 h-8 mx-auto mb-2" aria-hidden="true" />
                                <p className="text-sm">No social links configured</p>
                                <p className="text-sm mt-1">Select Add Link to add your social media profiles.</p>
                            </div>
                        )}
                    </div>
                </section>
            </Card>

            {/* Legal Documents */}
            <Card className="mt-6">
                <section aria-labelledby="branding-legal-heading" aria-describedby="branding-legal-intro">
                    <div className="mb-4">
                        <h2 id="branding-legal-heading" className="text-lg font-semibold text-white">Legal Documents</h2>
                        <p id="branding-legal-intro" className="text-sm text-white/50">Customize your Privacy Policy, Terms of Service, and Accessibility Statement</p>
                    </div>

                    <div className="space-y-6">
                        <LegalField
                            id="branding-privacy-policy"
                            label="Privacy Policy"
                            previewHref="/privacy"
                            value={form.privacy_policy || ''}
                            onChange={(v) => setForm((p) => ({ ...p, privacy_policy: v }))}
                            placeholder="Leave blank to use the default privacy policy."
                            helper="Supports Markdown formatting. Leave blank for sensible defaults."
                        />
                        <LegalField
                            id="branding-terms"
                            label="Terms of Service"
                            previewHref="/terms"
                            value={form.terms_of_service || ''}
                            onChange={(v) => setForm((p) => ({ ...p, terms_of_service: v }))}
                            placeholder="Leave blank to use the default terms, with a non-emergency notice."
                            helper="The default includes a clear non-emergency notice. Supports Markdown."
                        />
                        <LegalField
                            id="branding-accessibility"
                            label="Accessibility Statement"
                            previewHref="/accessibility"
                            value={form.accessibility_statement || ''}
                            onChange={(v) => setForm((p) => ({ ...p, accessibility_statement: v }))}
                            placeholder="Leave blank to use the default accessibility statement."
                            helper="The default covers WCAG 2.1 AA, Section 508, and ADA requirements."
                        />
                    </div>
                </section>
            </Card>
        </div>
    );
}

export default BrandingSettings;

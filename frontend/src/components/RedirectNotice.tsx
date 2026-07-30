import { motion } from 'framer-motion';
import { ArrowUpRight, Building2, ExternalLink, Mail, MapPin, Phone } from 'lucide-react';

/**
 * What a resident sees when the thing they are reporting is not the town's to fix.
 *
 * This is the least satisfying moment in the portal, so it carries the most
 * design weight. Someone has already picked a category, dropped a pin and, very
 * often, taken a photo. Being turned away at that point reads as rejection
 * unless three things are unmistakable:
 *
 *   1. WHO. Named, once, in the heading -- not "another agency". The redirect is
 *      only credible if it can say whose road it is.
 *   2. WHY. The road that decided it, spelled out, because the most common cause
 *      of a wrong redirect is a pin one lane off. Naming the road is what lets
 *      someone notice that and drag it back.
 *   3. WHAT NOW. The contact details as things you can press -- a phone number
 *      that dials, an address that composes, a site that opens -- rather than
 *      text to copy down. On a phone at the roadside that difference is the
 *      whole interaction.
 *
 * It is deliberately not styled as an error. Nothing has gone wrong; the report
 * is being pointed somewhere it will actually be read.
 */

export interface RedirectContact {
    name?: string;
    phone?: string;
    email?: string;
    url?: string;
}

interface RedirectNoticeProps {
    /** The agency, already resolved to the one that owns this road. */
    jurisdiction?: string | null;
    /** The clerk's own wording for this agency, if they wrote any. */
    message?: string;
    /** True when `message` is the backend's generated sentence rather than the
     *  clerk's. It restates the heading, so the notice says something more
     *  useful instead. */
    messageIsDefault?: boolean;
    contacts: RedirectContact[];
    /** The road the pin landed on, when the redirect was decided spatially. */
    roadName?: string | null;
    /** The category being reported, e.g. "Pothole". Lets the heading say what
     *  is handled elsewhere, not just where. */
    serviceName?: string | null;
    /** Whole-service redirects are not about a location, so they say less. */
    variant?: 'road' | 'service';
}

function href(kind: 'phone' | 'email' | 'url', value: string): string {
    if (kind === 'phone') return `tel:${value.replace(/[^\d+]/g, '')}`;
    if (kind === 'email') return `mailto:${value}`;
    return /^https?:\/\//i.test(value) ? value : `https://${value}`;
}

/** One pressable contact row: what it is, the actual value, and an affordance. */
function ContactAction({ icon: Icon, label, value, kind }: {
    icon: typeof Phone;
    label: string;
    value: string;
    kind: 'phone' | 'email' | 'url';
}) {
    const external = kind === 'url';
    return (
        <a
            href={href(kind, value)}
            {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
            className="contact-action group flex items-center gap-3 rounded-2xl bg-white/[0.09] hover:bg-white/[0.15] border border-white/[0.14] hover:border-white/25 px-4 py-3 transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-300/70"
        >
            <span className="w-9 h-9 rounded-xl bg-white/[0.13] flex items-center justify-center shrink-0">
                <Icon className="w-4 h-4 text-rose-200" aria-hidden="true" />
            </span>
            <span className="min-w-0 flex-1">
                <span className="block text-[11px] uppercase tracking-wider text-white/55 font-semibold">{label}</span>
                {/* anywhere, not break-all: a long address still wraps rather than
                    widening the card, but it breaks at a sensible point instead of
                    mid-word ("example.go / v"). */}
                <span className="block text-sm text-white font-medium [overflow-wrap:anywhere]">{value}</span>
            </span>
            {/* Decorative -- the leading icon and the label already say this is an
                action. Hidden on narrow screens because the ~28px it occupies is
                the difference between an email address fitting on one line and
                breaking mid-word. */}
            <ArrowUpRight
                className="hidden sm:block w-4 h-4 text-white/25 group-hover:text-white/60 shrink-0 transition-colors"
                aria-hidden="true"
            />
        </a>
    );
}

export default function RedirectNotice({
    jurisdiction, message, messageIsDefault, contacts, roadName, serviceName,
    variant = 'road',
}: RedirectNoticeProps) {
    const agency = (jurisdiction || '').trim();
    const category = (serviceName || '').trim();

    /* One sentence carrying all three facts: what is being reported, where, and
       whose it is -- "Pothole reports on Route 1 are handled by New Jersey DOT".
       That is the whole explanation, so nothing below needs to restate it.
       "reports" keeps it grammatical whatever the category is called, singular
       ("Pothole") or not ("Street Light Out"). */
    const heading = (() => {
        const who = agency || 'another agency';
        if (category && roadName && variant === 'road') {
            return `${category} reports on ${roadName} are handled by ${who}`;
        }
        if (category) return `${category} reports are handled by ${who}`;
        if (roadName && variant === 'road') return `${roadName} is maintained by ${who}`;
        return `${who} handles this`;
    })();

    // Empty names would render as a blank contact block.
    const usable = contacts.filter(c => c && (c.phone || c.email || c.url || c.name));

    return (
        <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
            role="status"
            className="relative overflow-hidden rounded-3xl border border-white/[0.14] bg-white/[0.06] bg-gradient-to-br from-rose-400/[0.10] via-transparent to-transparent shadow-xl"
        >
            {/* Top glow accent, matching the service cards. */}
            <div
                className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-rose-200/70 to-transparent"
                aria-hidden="true"
            />
            <div
                className="pointer-events-none absolute -top-20 -left-10 w-64 h-40 rounded-full bg-rose-400/15 blur-3xl"
                aria-hidden="true"
            />

            <div className="relative p-6 sm:p-7">
                <div className="flex items-start gap-4">
                    <span className="w-11 h-11 rounded-2xl bg-rose-400/20 border border-rose-300/35 flex items-center justify-center shrink-0">
                        <Building2 className="w-5 h-5 text-rose-200" aria-hidden="true" />
                    </span>
                    <div className="min-w-0 flex-1">
                        <p className="text-[11px] uppercase tracking-[0.14em] text-rose-200/90 font-bold">
                            Report this to another agency
                        </p>
                        <h3 className="text-lg sm:text-xl font-semibold text-white mt-1 leading-snug">
                            {heading}
                        </h3>

                        {/* Only the clerk's own words. When they wrote none, the
                            backend's default just restates the heading, and a
                            paragraph of filler underneath it reads as padding. */}
                        {message && !messageIsDefault && (
                            <p className="text-white/70 mt-2.5 leading-relaxed">{message}</p>
                        )}
                    </div>
                </div>

                {/* Why this road, and how to disagree with it. The most common cause of
                    a wrong redirect is a pin a lane off, and only the resident can see that. */}
                {variant === 'road' && roadName && (
                    <div className="mt-5 flex items-start gap-2.5 rounded-2xl bg-white/[0.07] border border-white/[0.12] px-4 py-3">
                        <MapPin className="w-4 h-4 text-white/40 mt-0.5 shrink-0" aria-hidden="true" />
                        <p className="text-sm text-white/70 leading-relaxed">
                            Your pin is on <span className="text-white/90 font-medium">{roadName}</span>.
                            If that is not the road you meant, move the pin and this will update.
                        </p>
                    </div>
                )}

                {usable.length > 0 && (
                    <div className="mt-5">
                        <p className="text-[11px] uppercase tracking-wider text-white/55 font-semibold mb-2.5">
                            How to reach them
                        </p>
                        <div className="space-y-3">
                            {usable.map((contact, idx) => (
                                <div key={idx} className="space-y-2">
                                    {/* Only when there is more than one to tell apart. With a
                                        single contact this just reprints the heading. */}
                                    {usable.length > 1 && contact.name && (
                                        <p className="text-sm font-semibold text-white/85">{contact.name}</p>
                                    )}
                                    <div className="grid gap-2 sm:grid-cols-2">
                                        {contact.phone && (
                                            <ContactAction icon={Phone} label="Call" value={contact.phone} kind="phone" />
                                        )}
                                        {contact.email && (
                                            <ContactAction icon={Mail} label="Email" value={contact.email} kind="email" />
                                        )}
                                        {contact.url && (
                                            <ContactAction icon={ExternalLink} label="Report online" value={contact.url} kind="url" />
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </motion.div>
    );
}

import { ReactNode, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown } from 'lucide-react';

interface CollapsibleSectionProps {
    title: string;
    icon?: React.ElementType;
    /** Shown under the title as context (kept while collapsed so it stays scannable). */
    subtitle?: string;
    /** Small status node rendered next to the title (e.g. a "3 connected" badge). */
    badge?: ReactNode;
    /** Actions rendered on the right of the header, OUTSIDE the toggle button
     *  (e.g. a "Recheck all" button) so we never nest interactive elements. */
    trailing?: ReactNode;
    /** Marks the section as core (not optional) with a subtle accent rail. */
    accent?: 'primary' | 'neutral';
    defaultOpen?: boolean;
    children: ReactNode;
}

/**
 * A premium collapsible section presented as a card, so a collapsed section
 * reads as an intentional, polished summary row rather than hidden/bare text.
 * The header doubles as the toggle to keep the setup page compact.
 */
export function CollapsibleSection({
    title, icon: Icon, subtitle, badge, trailing, accent = 'neutral', defaultOpen = false, children,
}: CollapsibleSectionProps) {
    const [open, setOpen] = useState(defaultOpen);
    const isPrimary = accent === 'primary';
    return (
        <section className={`rounded-2xl border overflow-hidden transition-colors ${isPrimary
            ? 'border-primary-400/25 bg-primary-500/[0.04]'
            : 'border-white/10 bg-white/[0.03]'}`}>
            <div className="flex items-center gap-3 p-4 sm:p-5">
                <button
                    type="button"
                    onClick={() => setOpen(o => !o)}
                    aria-expanded={open}
                    className="group flex items-center gap-3.5 flex-1 min-w-0 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60 rounded-xl"
                >
                    {Icon && (
                        <span className={`shrink-0 w-10 h-10 rounded-xl flex items-center justify-center border ${isPrimary
                            ? 'bg-primary-500/20 border-primary-400/30'
                            : 'bg-white/[0.06] border-white/10'}`}>
                            <Icon className={`w-5 h-5 ${isPrimary ? 'text-primary-200' : 'text-white/70'}`} aria-hidden={true} />
                        </span>
                    )}
                    <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2 flex-wrap">
                            <span className="text-lg font-semibold text-white truncate">{title}</span>
                            {badge}
                        </span>
                        {subtitle && <span className="block text-white/55 text-xs mt-0.5 truncate">{subtitle}</span>}
                    </span>
                    <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.25 }} aria-hidden="true" className="shrink-0 text-white/45 group-hover:text-white/80">
                        <ChevronDown className="w-5 h-5" />
                    </motion.span>
                </button>
                {trailing && <div className="shrink-0">{trailing}</div>}
            </div>

            <AnimatePresence initial={false}>
                {open && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                        className="overflow-hidden"
                    >
                        <div className="px-4 sm:px-5 pb-5 pt-1 border-t border-white/10">
                            <div className="pt-4">{children}</div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </section>
    );
}

export default CollapsibleSection;

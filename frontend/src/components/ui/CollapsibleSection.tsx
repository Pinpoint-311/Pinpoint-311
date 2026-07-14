import { ReactNode, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown } from 'lucide-react';

interface CollapsibleSectionProps {
    title: string;
    icon?: React.ElementType;
    /** Shown under the title while collapsed, so the section stays scannable. */
    subtitle?: string;
    /** Small status node rendered next to the title (e.g. a "3 connected" badge). */
    badge?: ReactNode;
    /** Actions rendered on the right of the header, OUTSIDE the toggle button
     *  (e.g. a "Recheck all" button) so we never nest interactive elements. */
    trailing?: ReactNode;
    defaultOpen?: boolean;
    children: ReactNode;
}

/**
 * A premium, calm collapsible section wrapper. Its header doubles as the toggle
 * so large sections (connectors, providers, optional integrations) can collapse
 * to a single row and keep the setup page compact.
 */
export function CollapsibleSection({
    title, icon: Icon, subtitle, badge, trailing, defaultOpen = false, children,
}: CollapsibleSectionProps) {
    const [open, setOpen] = useState(defaultOpen);
    return (
        <section className="mb-3">
            <div className="flex items-center justify-between gap-3">
                <button
                    type="button"
                    onClick={() => setOpen(o => !o)}
                    aria-expanded={open}
                    className="group flex items-center gap-2.5 flex-1 min-w-0 text-left rounded-xl px-1 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60"
                >
                    <motion.span animate={{ rotate: open ? 0 : -90 }} transition={{ duration: 0.25 }} aria-hidden="true" className="text-white/50 group-hover:text-white/80 shrink-0">
                        <ChevronDown className="w-4 h-4" />
                    </motion.span>
                    {Icon && <Icon className="w-5 h-5 text-primary-300" aria-hidden={true} />}
                    <span className="min-w-0">
                        <span className="flex items-center gap-2">
                            <span className="text-lg font-semibold text-white truncate">{title}</span>
                            {badge}
                        </span>
                        {subtitle && !open && (
                            <span className="block text-white/55 text-xs mt-0.5 truncate">{subtitle}</span>
                        )}
                    </span>
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
                        <div className="pt-3">{children}</div>
                    </motion.div>
                )}
            </AnimatePresence>
        </section>
    );
}

export default CollapsibleSection;

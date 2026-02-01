import { useState, ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown } from 'lucide-react';

interface AccordionSectionProps {
    title: string;
    subtitle?: string;
    icon?: ReactNode;
    badge?: ReactNode;
    defaultOpen?: boolean;
    children: ReactNode;
    className?: string;
}

export function AccordionSection({
    title,
    subtitle,
    icon,
    badge,
    defaultOpen = false,
    children,
    className = '',
}: AccordionSectionProps) {
    const [isOpen, setIsOpen] = useState(defaultOpen);

    return (
        <div className={`rounded-2xl bg-white/5 border border-white/10 overflow-hidden ${className}`}>
            {/* Header - clickable to expand/collapse */}
            <button
                onClick={() => setIsOpen(!isOpen)}
                className="w-full flex items-center gap-3 p-4 hover:bg-white/5 transition-colors text-left"
                aria-expanded={isOpen}
            >
                {icon && (
                    <div className="flex-shrink-0">
                        {icon}
                    </div>
                )}
                <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-white truncate">{title}</h3>
                    {subtitle && (
                        <p className="text-sm text-white/50 truncate">{subtitle}</p>
                    )}
                </div>
                {badge && (
                    <div className="flex-shrink-0">
                        {badge}
                    </div>
                )}
                <motion.div
                    animate={{ rotate: isOpen ? 180 : 0 }}
                    transition={{ duration: 0.2 }}
                    className="flex-shrink-0"
                >
                    <ChevronDown className="w-5 h-5 text-white/40" />
                </motion.div>
            </button>

            {/* Content - animated expand/collapse */}
            <AnimatePresence initial={false}>
                {isOpen && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2, ease: 'easeInOut' }}
                        className="overflow-hidden"
                    >
                        <div className="p-4 pt-0 border-t border-white/10">
                            {children}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}

interface AccordionGroupProps {
    children: ReactNode;
    className?: string;
}

export function AccordionGroup({ children, className = '' }: AccordionGroupProps) {
    return (
        <div className={`space-y-3 ${className}`}>
            {children}
        </div>
    );
}

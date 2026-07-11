import React, { useEffect, useRef, useCallback, useId } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X } from 'lucide-react';

interface ModalProps {
    isOpen: boolean;
    onClose: () => void;
    title?: string;
    children: React.ReactNode;
    size?: 'sm' | 'md' | 'lg' | 'xl';
    /** Element to return focus to when modal closes */
    triggerRef?: React.RefObject<HTMLElement>;
    /** Description for screen readers */
    'aria-describedby'?: string;
    /**
     * Override the panel surface. Defaults to the translucent `glass-card`.
     * Pass a solid class (e.g. a slate gradient) for dialogs that must sit
     * opaquely over busy backgrounds like a map.
     */
    panelClassName?: string;
    /** Optional class for the sticky header surface (defaults to bg-slate-900). */
    headerClassName?: string;
}

export const Modal: React.FC<ModalProps> = ({
    isOpen,
    onClose,
    title,
    children,
    size = 'md',
    triggerRef,
    'aria-describedby': ariaDescribedBy,
    panelClassName,
    headerClassName,
}) => {
    const modalRef = useRef<HTMLDivElement>(null);
    const previousActiveElement = useRef<HTMLElement | null>(null);
    const modalId = useId();
    const titleId = title ? `${modalId}-title` : undefined;

    const sizeStyles = {
        sm: 'max-w-sm',
        md: 'max-w-lg',
        lg: 'max-w-2xl',
        xl: 'max-w-4xl',
    };

    // Handle body scroll lock
    useEffect(() => {
        if (isOpen) {
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = 'unset';
        }
        return () => {
            document.body.style.overflow = 'unset';
        };
    }, [isOpen]);

    // Focus management
    useEffect(() => {
        if (isOpen) {
            // Store the previously focused element
            previousActiveElement.current = document.activeElement as HTMLElement;

            // Focus the modal or first focusable element
            setTimeout(() => {
                const focusableElements = modalRef.current?.querySelectorAll<HTMLElement>(
                    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
                );
                if (focusableElements && focusableElements.length > 0) {
                    focusableElements[0].focus();
                } else {
                    modalRef.current?.focus();
                }
            }, 50);
        } else {
            // Return focus to trigger element or previous element
            if (triggerRef?.current) {
                triggerRef.current.focus();
            } else if (previousActiveElement.current) {
                previousActiveElement.current.focus();
            }
        }
    }, [isOpen, triggerRef]);

    // Handle Escape key - WCAG 2.1.2 No Keyboard Trap
    const handleKeyDown = useCallback((event: KeyboardEvent) => {
        if (event.key === 'Escape') {
            event.preventDefault();
            onClose();
        }

        // Focus trap
        if (event.key === 'Tab' && modalRef.current) {
            const focusableElements = modalRef.current.querySelectorAll<HTMLElement>(
                'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
            );
            const firstElement = focusableElements[0];
            const lastElement = focusableElements[focusableElements.length - 1];

            if (event.shiftKey && document.activeElement === firstElement) {
                event.preventDefault();
                lastElement?.focus();
            } else if (!event.shiftKey && document.activeElement === lastElement) {
                event.preventDefault();
                firstElement?.focus();
            }
        }
    }, [onClose]);

    useEffect(() => {
        if (isOpen) {
            document.addEventListener('keydown', handleKeyDown);
        }
        return () => {
            document.removeEventListener('keydown', handleKeyDown);
        };
    }, [isOpen, handleKeyDown]);

    return (
        <AnimatePresence>
            {isOpen && (
                <>
                    {/* Backdrop */}
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={onClose}
                        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
                        aria-hidden="true"
                    />

                    {/* Modal Container - centered with flexbox */}
                    <div
                        className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none"
                        role="presentation"
                    >
                        <motion.div
                            ref={modalRef}
                            initial={{ opacity: 0, scale: 0.95, y: 20 }}
                            animate={{ opacity: 1, scale: 1, y: 0 }}
                            exit={{ opacity: 0, scale: 0.95, y: 20 }}
                            className={`w-full ${sizeStyles[size]} ${panelClassName ?? 'glass-card'} rounded-2xl p-0 pointer-events-auto max-h-[90vh] overflow-auto`}
                            role="dialog"
                            aria-modal="true"
                            aria-labelledby={titleId}
                            aria-describedby={ariaDescribedBy}
                            tabIndex={-1}
                        >
                            {/* Header — opaque so scrolled content never shows through it */}
                            {title && (
                                <div className={`flex items-center justify-between gap-3 p-4 sm:p-6 border-b border-white/10 sticky top-0 z-20 rounded-t-2xl ${headerClassName ?? 'bg-slate-900'}`}>
                                    <h2
                                        id={titleId}
                                        className="text-lg sm:text-xl font-semibold text-white"
                                    >
                                        {title}
                                    </h2>
                                    <button
                                        onClick={onClose}
                                        className="p-2 rounded-lg hover:bg-white/10 transition-colors focus-visible:ring-2 focus-visible:ring-amber-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900"
                                        aria-label="Close dialog"
                                        type="button"
                                    >
                                        <X className="w-5 h-5 text-white/60" aria-hidden="true" />
                                    </button>
                                </div>
                            )}

                            {/* Close button when no title */}
                            {!title && (
                                <button
                                    onClick={onClose}
                                    className="absolute top-4 right-4 p-2 rounded-lg hover:bg-white/10 transition-colors z-10 focus-visible:ring-2 focus-visible:ring-amber-400"
                                    aria-label="Close dialog"
                                    type="button"
                                >
                                    <X className="w-5 h-5 text-white/60" aria-hidden="true" />
                                </button>
                            )}

                            {/* Content */}
                            <div className="p-6">
                                {children}
                            </div>
                        </motion.div>
                    </div>
                </>
            )}
        </AnimatePresence>
    );
};

export default Modal;

import { useState, useCallback, useEffect, useRef, useId, createContext, useContext, ReactNode } from 'react';
import { X, AlertTriangle, Info, CheckCircle2, Rocket, Trash2, Shield, Download } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

// ============ Types ============

type DialogVariant = 'default' | 'danger' | 'warning' | 'info' | 'deploy';

interface DialogConfig {
    title: string;
    message: string | ReactNode;
    variant?: DialogVariant;
    confirmText?: string;
    cancelText?: string;
    icon?: ReactNode;
    /** A word the person has to type before Confirm becomes available.
     *
     * For the small number of actions that destroy data permanently. A dialog
     * on its own is a speed bump: it appears where a click was already going,
     * and Confirm is under the cursor. Typing the word is the difference
     * between agreeing and noticing. */
    requireTyped?: string;
}

interface DialogContextType {
    confirm: (config: DialogConfig) => Promise<boolean>;
    alert: (config: Omit<DialogConfig, 'cancelText'>) => Promise<void>;
}

// ============ Context ============

const DialogContext = createContext<DialogContextType | null>(null);

export const useDialog = () => {
    const context = useContext(DialogContext);
    if (!context) {
        throw new Error('useDialog must be used within a DialogProvider');
    }
    return context;
};

// ============ Styling ============

const variantStyles: Record<DialogVariant, {
    icon: ReactNode;
    iconBg: string;
    confirmBtn: string;
}> = {
    default: {
        icon: <Info size={24} />,
        iconBg: 'bg-blue-500/20 text-blue-400',
        confirmBtn: 'bg-blue-600 hover:bg-blue-700',
    },
    danger: {
        icon: <Trash2 size={24} />,
        iconBg: 'bg-red-500/20 text-red-400',
        confirmBtn: 'bg-red-600 hover:bg-red-700',
    },
    warning: {
        icon: <AlertTriangle size={24} />,
        iconBg: 'bg-amber-500/20 text-amber-400',
        confirmBtn: 'bg-amber-600 hover:bg-amber-700',
    },
    info: {
        icon: <CheckCircle2 size={24} />,
        iconBg: 'bg-emerald-500/20 text-emerald-400',
        confirmBtn: 'bg-emerald-600 hover:bg-emerald-700',
    },
    deploy: {
        icon: <Rocket size={24} />,
        iconBg: 'bg-violet-500/20 text-violet-400',
        confirmBtn: 'bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-700 hover:to-purple-700',
    },
};

// ============ Dialog Component ============

interface DialogProps {
    isOpen: boolean;
    config: DialogConfig;
    onConfirm: () => void;
    onCancel: () => void;
    showCancel?: boolean;
}

/**
 * The focusable children of the dialog, in tab order.
 *
 * Disabled and hidden controls are filtered out for the same reason ui/Modal
 * filters them: `.focus()` on a disabled element silently does nothing, and
 * the Confirm button here starts disabled on every type-to-confirm dialog, so
 * an unfiltered list would open the dialog with focus still on <body> —
 * outside the dialog, with the page behind it fully tabbable.
 */
function getFocusable(root: HTMLElement | null): HTMLElement[] {
    if (!root) return [];
    const candidates = root.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    return Array.from(candidates).filter(el =>
        !el.hasAttribute('disabled') &&
        el.getAttribute('aria-hidden') !== 'true' &&
        (el.offsetParent !== null || el.getClientRects().length > 0)
    );
}

/* Deliberately NOT rendered through ui/Modal, even though it duplicates that
 * component's focus handling: confirmations here are routinely raised from
 * inside an already-open ui/Modal (delete a user from the user editor, purge
 * from the retention modal). Two Modals would mean two document-level Escape
 * and Tab handlers fighting, and one Escape closing both. The handler below
 * instead runs in the CAPTURE phase and stops propagation, so while a confirm
 * is open it wins over any Modal underneath it, and Escape dismisses only the
 * confirmation. The z-index above ui/Modal's z-50 is part of the same story. */
const Dialog = ({ isOpen, config, onConfirm, onCancel, showCancel = true }: DialogProps) => {
    /* Cleared whenever the dialog opens, so the word typed to authorise one
     * deletion is never sitting in the box pre-approving the next. */
    const [typed, setTyped] = useState('');
    useEffect(() => { if (isOpen) setTyped(''); }, [isOpen]);

    const variant = config.variant || 'default';
    const styles = variantStyles[variant];

    const panelRef = useRef<HTMLDivElement>(null);
    const typedInputRef = useRef<HTMLInputElement>(null);
    const previouslyFocused = useRef<HTMLElement | null>(null);
    const baseId = useId();
    const titleId = `${baseId}-title`;
    const descId = `${baseId}-desc`;
    const typedInputId = `${baseId}-typed`;
    const typedHintId = `${baseId}-typed-hint`;

    const typedSatisfied = !config.requireTyped || typed.trim() === config.requireTyped;

    /* Focus in on open, focus back out on close. Without the restore, cancelling
     * a delete drops focus to <body> and a keyboard user restarts at the top of
     * the console instead of on the row they came from. */
    useEffect(() => {
        if (!isOpen) return;
        previouslyFocused.current = document.activeElement as HTMLElement | null;
        const timer = window.setTimeout(() => {
            const focusable = getFocusable(panelRef.current);
            // The type-to-confirm box, when present, is the thing the person has
            // to act on; otherwise the first control (Close) carries focus in.
            (typedInputRef.current || focusable[0] || panelRef.current)?.focus();
        }, 30);
        return () => {
            window.clearTimeout(timer);
            previouslyFocused.current?.focus?.();
        };
    }, [isOpen]);

    useEffect(() => {
        if (!isOpen) return;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                onCancel();
                return;
            }
            if (event.key !== 'Tab' || !panelRef.current) return;
            const focusable = getFocusable(panelRef.current);
            if (focusable.length === 0) {
                event.preventDefault();
                return;
            }
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            const active = document.activeElement as HTMLElement | null;
            // Focus starting outside the panel (or on the panel itself) has to be
            // pulled back in, otherwise Tab walks the page underneath the confirm.
            if (!active || !panelRef.current.contains(active) || active === panelRef.current) {
                event.preventDefault();
                (event.shiftKey ? last : first).focus();
                return;
            }
            if (event.shiftKey && active === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && active === last) {
                event.preventDefault();
                first.focus();
            }
        };
        document.addEventListener('keydown', onKeyDown, true);
        return () => document.removeEventListener('keydown', onKeyDown, true);
    }, [isOpen, onCancel]);

    return (
        <AnimatePresence>
            {isOpen && (
                <>
                    {/* Backdrop */}
                    <motion.div
                        className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[9999]"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={onCancel}
                        aria-hidden="true"
                    />

                    {/* Dialog */}
                    <motion.div
                        className="fixed inset-0 flex items-center justify-center z-[10000] p-4"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                    >
                        <motion.div
                            ref={panelRef}
                            className="bg-slate-800 backdrop-blur-xl border border-slate-600/40 rounded-3xl shadow-2xl max-w-xl w-full overflow-hidden"
                            initial={{ scale: 0.9, y: 20 }}
                            animate={{ scale: 1, y: 0 }}
                            exit={{ scale: 0.9, y: 20 }}
                            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
                            onClick={(e) => e.stopPropagation()}
                            role="dialog"
                            aria-modal="true"
                            aria-labelledby={titleId}
                            aria-describedby={descId}
                            tabIndex={-1}
                        >
                            {/* Header */}
                            <div className="p-8 pb-6">
                                <div className="flex items-start gap-5">
                                    {/* Icon — decorative; the variant is already carried by the title and message */}
                                    <div className={`p-4 rounded-2xl ${styles.iconBg}`} aria-hidden="true">
                                        {config.icon || styles.icon}
                                    </div>

                                    {/* Title & Close */}
                                    <div className="flex-1 min-w-0 pt-1">
                                        <div className="flex items-center justify-between">
                                            <h2 id={titleId} className="text-xl font-semibold text-white">
                                                {config.title}
                                            </h2>
                                            <button
                                                type="button"
                                                onClick={onCancel}
                                                aria-label="Close dialog"
                                                className="p-2.5 text-slate-400 hover:text-white hover:bg-white/10 rounded-xl transition-colors ml-4 focus-visible:ring-2 focus-visible:ring-amber-400"
                                            >
                                                <X size={22} aria-hidden="true" />
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            {/* Content */}
                            <div className="px-8 pb-8">
                                <div id={descId} className="text-slate-300 text-base leading-relaxed whitespace-pre-wrap">
                                    {config.message}
                                </div>
                                {config.requireTyped && (
                                    <div className="mt-5">
                                        <label htmlFor={typedInputId} className="block text-sm text-slate-300 mb-2">
                                            Type <code className="px-1.5 py-0.5 rounded bg-slate-700 text-white font-semibold">{config.requireTyped}</code> to continue
                                        </label>
                                        <input
                                            ref={typedInputRef}
                                            id={typedInputId}
                                            value={typed}
                                            onChange={(e) => setTyped(e.target.value)}
                                            aria-describedby={typedHintId}
                                            className="w-full rounded-xl bg-slate-900 border border-slate-600 px-4 py-3 text-white placeholder-slate-500 focus:outline-none focus:border-red-400 focus-visible:ring-2 focus-visible:ring-amber-400"
                                            placeholder={config.requireTyped}
                                        />
                                        {/* Says out loud why Confirm is unavailable. A disabled button
                                          * announces nothing and cannot carry a description of its own,
                                          * so the explanation has to live on the input the person is in. */}
                                        <p id={typedHintId} className="mt-2 text-sm text-slate-300">
                                            {typedSatisfied
                                                ? `${config.confirmText || 'Confirm'} is now available.`
                                                : `${config.confirmText || 'Confirm'} stays unavailable until you type ${config.requireTyped} exactly.`}
                                        </p>
                                    </div>
                                )}
                            </div>

                            {/* Actions */}
                            <div className="px-8 py-6 flex gap-4 justify-end bg-slate-900/50 border-t border-slate-700/50">
                                {showCancel && (
                                    <button
                                        type="button"
                                        onClick={onCancel}
                                        className="px-8 py-3.5 text-base font-medium text-slate-200 hover:text-white bg-slate-700 hover:bg-slate-600 border border-slate-500/50 rounded-xl transition-all"
                                    >
                                        {config.cancelText || 'Cancel'}
                                    </button>
                                )}
                                <button
                                    type="button"
                                    onClick={onConfirm}
                                    disabled={!typedSatisfied}
                                    aria-describedby={config.requireTyped ? typedHintId : undefined}
                                    className={`px-8 py-3.5 text-base font-medium text-white rounded-xl transition-all disabled:opacity-40 disabled:cursor-not-allowed ${styles.confirmBtn}`}
                                >
                                    {config.confirmText || 'Confirm'}
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                </>
            )}
        </AnimatePresence>
    );
};

// ============ Provider ============

interface DialogProviderProps {
    children: ReactNode;
}

export const DialogProvider = ({ children }: DialogProviderProps) => {
    const [isOpen, setIsOpen] = useState(false);
    const [showCancel, setShowCancel] = useState(true);
    const [config, setConfig] = useState<DialogConfig>({
        title: '',
        message: '',
    });
    const [resolveRef, setResolveRef] = useState<{
        resolve: (value: boolean) => void;
    } | null>(null);

    const confirm = useCallback((dialogConfig: DialogConfig): Promise<boolean> => {
        return new Promise((resolve) => {
            setConfig(dialogConfig);
            setShowCancel(true);
            setResolveRef({ resolve });
            setIsOpen(true);
        });
    }, []);

    const alert = useCallback((dialogConfig: Omit<DialogConfig, 'cancelText'>): Promise<void> => {
        return new Promise((resolve) => {
            setConfig({ ...dialogConfig, confirmText: dialogConfig.confirmText || 'OK' });
            setShowCancel(false);
            setResolveRef({ resolve: () => resolve() });
            setIsOpen(true);
        });
    }, []);

    const handleConfirm = useCallback(() => {
        setIsOpen(false);
        resolveRef?.resolve(true);
        setResolveRef(null);
    }, [resolveRef]);

    const handleCancel = useCallback(() => {
        setIsOpen(false);
        resolveRef?.resolve(false);
        setResolveRef(null);
    }, [resolveRef]);

    return (
        <DialogContext.Provider value={{ confirm, alert }}>
            {children}
            <Dialog
                isOpen={isOpen}
                config={config}
                onConfirm={handleConfirm}
                onCancel={handleCancel}
                showCancel={showCancel}
            />
        </DialogContext.Provider>
    );
};

// ============ Pre-built Dialogs ============

export const useConfirmDelete = () => {
    const { confirm } = useDialog();

    return useCallback((itemName: string) => {
        return confirm({
            title: 'Confirm Delete',
            message: `Are you sure you want to delete "${itemName}"?\n\nThis action cannot be undone.`,
            variant: 'danger',
            confirmText: 'Delete',
            icon: <Trash2 size={24} />,
        });
    }, [confirm]);
};

export const useConfirmDeploy = () => {
    const { confirm } = useDialog();

    return useCallback((version: string, hasWarnings: boolean = false) => {
        return confirm({
            title: '🚀 Deploy Version',
            message: (
                <div className="space-y-3">
                    <p>This will perform a <strong className="text-violet-400">full deployment</strong>:</p>
                    <ol className="list-decimal list-inside space-y-1 text-slate-400">
                        <li>Create database backup</li>
                        <li>Checkout version <code className="text-violet-400 bg-violet-500/10 px-1.5 py-0.5 rounded">{version}</code></li>
                        <li>Run database migrations</li>
                        <li>Rebuild all containers</li>
                        <li>Health check deployment</li>
                    </ol>
                    {hasWarnings && (
                        <div className="flex items-center gap-2 text-amber-400 bg-amber-500/10 p-2 rounded-lg mt-3">
                            <AlertTriangle size={16} />
                            <span className="text-sm">Some security checks did not pass</span>
                        </div>
                    )}
                    <p className="text-emerald-400 text-sm">
                        ✓ Automatic rollback on failure
                    </p>
                </div>
            ),
            variant: 'deploy',
            confirmText: 'Deploy',
            icon: <Rocket size={24} />,
        });
    }, [confirm]);
};

export const useConfirmLegalHold = () => {
    const { confirm } = useDialog();

    return useCallback((requestId: string) => {
        return confirm({
            title: 'Place Legal Hold',
            message: (
                <div className="space-y-2">
                    <p>Place request <strong className="text-amber-400">{requestId}</strong> under Legal Hold?</p>
                    <p className="text-slate-400 text-sm">
                        This will prevent the record from being archived or deleted by the retention policy.
                    </p>
                </div>
            ),
            variant: 'warning',
            confirmText: 'Apply Hold',
            icon: <Shield size={24} />,
        });
    }, [confirm]);
};

export const useConfirmBackup = () => {
    const { confirm } = useDialog();

    return useCallback(() => {
        return confirm({
            title: 'Create Backup',
            message: 'Create a new database backup now?\n\nThis may take a few moments depending on database size.',
            variant: 'info',
            confirmText: 'Create Backup',
            icon: <Download size={24} />,
        });
    }, [confirm]);
};

export default DialogProvider;

import { useState, useCallback, createContext, useContext, ReactNode } from 'react';
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

const Dialog = ({ isOpen, config, onConfirm, onCancel, showCancel = true }: DialogProps) => {
    const variant = config.variant || 'default';
    const styles = variantStyles[variant];

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
                    />

                    {/* Dialog */}
                    <motion.div
                        className="fixed inset-0 flex items-center justify-center z-[10000] p-4"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                    >
                        <motion.div
                            className="bg-slate-800 backdrop-blur-xl border border-slate-600/40 rounded-3xl shadow-2xl max-w-xl w-full overflow-hidden"
                            initial={{ scale: 0.9, y: 20 }}
                            animate={{ scale: 1, y: 0 }}
                            exit={{ scale: 0.9, y: 20 }}
                            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
                            onClick={(e) => e.stopPropagation()}
                        >
                            {/* Header */}
                            <div className="p-8 pb-6">
                                <div className="flex items-start gap-5">
                                    {/* Icon */}
                                    <div className={`p-4 rounded-2xl ${styles.iconBg}`}>
                                        {config.icon || styles.icon}
                                    </div>

                                    {/* Title & Close */}
                                    <div className="flex-1 min-w-0 pt-1">
                                        <div className="flex items-center justify-between">
                                            <h3 className="text-xl font-semibold text-white">
                                                {config.title}
                                            </h3>
                                            <button
                                                onClick={onCancel}
                                                className="p-2.5 text-slate-400 hover:text-white hover:bg-white/10 rounded-xl transition-colors ml-4"
                                            >
                                                <X size={22} />
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            {/* Content */}
                            <div className="px-8 pb-8">
                                <div className="text-slate-300 text-base leading-relaxed whitespace-pre-wrap">
                                    {config.message}
                                </div>
                            </div>

                            {/* Actions */}
                            <div className="px-8 py-6 flex gap-4 justify-end bg-slate-900/50 border-t border-slate-700/50">
                                {showCancel && (
                                    <button
                                        onClick={onCancel}
                                        className="px-8 py-3.5 text-base font-medium text-slate-200 hover:text-white bg-slate-700 hover:bg-slate-600 border border-slate-500/50 rounded-xl transition-all"
                                    >
                                        {config.cancelText || 'Cancel'}
                                    </button>
                                )}
                                <button
                                    onClick={onConfirm}
                                    className={`px-8 py-3.5 text-base font-medium text-white rounded-xl transition-all ${styles.confirmBtn}`}
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

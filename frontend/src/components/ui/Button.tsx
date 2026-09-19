import React from 'react';
import { motion, HTMLMotionProps } from 'framer-motion';

/* Every prop was listed out by hand here and destructured explicitly, with no
 * rest spread — which meant any attribute not on the list was silently dropped
 * on the floor. That included the entire ARIA surface: a caller writing
 * `<Button aria-expanded={open} aria-controls="panel">` got a button with
 * neither. Toggles, disclosure triggers and menu buttons across the staff and
 * admin surfaces were therefore missing their *value* (WCAG 4.1.2) — they
 * announced as plain buttons with no state, and no amount of care at the call
 * site could fix it.
 *
 * Extending the native button props and spreading the rest means a caller can
 * reach for any of them and have it work, rather than having to come back here
 * and add another line each time. */
type NativeButtonProps = Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'ref'>;

interface ButtonProps extends NativeButtonProps {
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
    size?: 'sm' | 'md' | 'lg';
    isLoading?: boolean;
    leftIcon?: React.ReactNode;
    rightIcon?: React.ReactNode;
    children?: React.ReactNode;
    className?: string;
    disabled?: boolean;
    type?: 'button' | 'submit' | 'reset';
    onClick?: React.MouseEventHandler<HTMLButtonElement>;
}

export const Button: React.FC<ButtonProps> = ({
    children,
    variant = 'primary',
    size = 'md',
    isLoading = false,
    leftIcon,
    rightIcon,
    className = '',
    disabled,
    type = 'button',
    onClick,
    ...rest
}) => {
    const baseStyles = 'inline-flex items-center justify-center font-medium transition-all duration-300 rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900';

    const variantStyles = {
        primary: 'glass-button',
        secondary: 'bg-white/10 hover:bg-white/20 border border-white/20 text-white',
        ghost: 'bg-transparent hover:bg-white/10 text-white/80 hover:text-white',
        danger: 'bg-red-500/80 hover:bg-red-500 border border-red-400/30 text-white',
    };

    const sizeStyles = {
        sm: 'px-3 py-1.5 text-sm min-h-[36px]',
        md: 'px-5 py-2.5 text-sm min-h-[44px]',
        lg: 'px-6 py-3 text-base min-h-[52px]',
    };

    const isDisabled = disabled || isLoading;

    const motionProps: HTMLMotionProps<'button'> = {
        whileHover: isDisabled ? undefined : { scale: 1.02 },
        whileTap: isDisabled ? undefined : { scale: 0.98 },
    };

    return (
        <motion.button
            {...motionProps}
            className={`${baseStyles} ${variantStyles[variant]} ${sizeStyles[size]} ${className} ${isDisabled ? 'opacity-50 cursor-not-allowed' : ''
                }`}
            {...(rest as HTMLMotionProps<'button'>)}
            disabled={isDisabled}
            type={type}
            onClick={onClick}
            aria-disabled={isDisabled || undefined}
            aria-busy={isLoading || undefined}
        >
            {isLoading ? (
                <>
                    {/* The spinner used to be a `role="status"` region with its
                      * own aria-label AND a sr-only sibling saying the same
                      * thing, so a loading button announced "Loading" twice —
                      * and every button that started loading opened a live
                      * region, which competes with the app's own. `aria-busy`
                      * on the button already tells assistive tech what is
                      * happening, so the spinner is now purely decorative. */}
                    <div
                        className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"
                        aria-hidden="true"
                    />
                    <span className="sr-only">Loading, please wait…</span>
                </>
            ) : leftIcon ? (
                <span className="mr-2" aria-hidden="true">{leftIcon}</span>
            ) : null}
            {children}
            {rightIcon && <span className="ml-2" aria-hidden="true">{rightIcon}</span>}
        </motion.button>
    );
};

export default Button;

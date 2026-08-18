import React, { forwardRef, useId } from 'react';

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
    label?: string;
    error?: string;
    /** Marks the field as required */
    required?: boolean;
    /** Helper text displayed below the textarea */
    helperText?: string;
    /** Character count limit (if provided, shows count) */
    maxLength?: number;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
    ({ label, error, className = '', required, helperText, maxLength, id: providedId, value, ...props }, ref) => {
        // Generate unique IDs for accessibility associations
        const generatedId = useId();
        const textareaId = providedId || `textarea-${generatedId}`;
        const errorId = error ? `${textareaId}-error` : undefined;
        const helperId = helperText ? `${textareaId}-helper` : undefined;
        const countId = maxLength ? `${textareaId}-count` : undefined;

        // Combine IDs for aria-describedby
        const describedBy = [errorId, helperId, countId].filter(Boolean).join(' ') || undefined;

        // Calculate character count
        const charCount = typeof value === 'string' ? value.length : 0;

        return (
            <div className="w-full">
                {label && (
                    <label
                        htmlFor={textareaId}
                        className="block text-sm font-medium text-white/70 mb-2"
                    >
                        {label}
                        {required && (
                            <span className="required-indicator" aria-hidden="true">*</span>
                        )}
                        {required && <span className="sr-only">(required)</span>}
                    </label>
                )}
                <textarea
                    ref={ref}
                    id={textareaId}
                    className={`glass-input min-h-[120px] resize-none ${error ? 'border-red-400/50 focus:border-red-400' : ''
                        } ${className}`}
                    aria-required={required}
                    aria-invalid={error ? 'true' : undefined}
                    aria-describedby={describedBy}
                    maxLength={maxLength}
                    value={value}
                    {...props}
                />
                <div className="flex justify-between items-start mt-1.5">
                    <div>
                        {helperText && !error && (
                            <p id={helperId} className="text-sm text-white/50">
                                {helperText}
                            </p>
                        )}
                        {error && (
                            <p id={errorId} className="text-sm text-red-400 error-message" role="alert">
                                {error}
                            </p>
                        )}
                    </div>
                    {maxLength && (
                        <p
                            id={countId}
                            className={`text-sm ${charCount > maxLength * 0.9 ? 'text-amber-400' : 'text-white/40'}`}
                            /* Deliberately NOT a live region. The count is already
                             * referenced by the textarea's aria-describedby, so it is
                             * read on focus. As aria-live it re-announced on every
                             * keystroke, and it competed with the app's polite
                             * region — two polite regions updating in the same tick
                             * and a screen reader announces neither. (WCAG 4.1.3) */
                        >
                            <span className="sr-only">Character count:</span>
                            {charCount}/{maxLength}
                        </p>
                    )}
                </div>
            </div>
        );
    }
);

Textarea.displayName = 'Textarea';

export default Textarea;

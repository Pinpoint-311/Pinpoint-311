import React, { forwardRef, useId } from 'react';
import { ChevronDown } from 'lucide-react';

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
    label?: string;
    error?: string;
    options: { value: string; label: string }[];
    /** Marks the field as required */
    required?: boolean;
    /** Helper text displayed below the select */
    helperText?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
    ({ label, error, options, className = '', required, helperText, id: providedId, ...props }, ref) => {
        // Generate unique IDs for accessibility associations
        const generatedId = useId();
        const selectId = providedId || `select-${generatedId}`;
        const errorId = error ? `${selectId}-error` : undefined;
        const helperId = helperText ? `${selectId}-helper` : undefined;

        // Combine IDs for aria-describedby
        const describedBy = [errorId, helperId].filter(Boolean).join(' ') || undefined;

        return (
            <div className="w-full">
                {label && (
                    <label
                        htmlFor={selectId}
                        className="block text-sm font-medium text-white/70 mb-2"
                    >
                        {label}
                        {required && (
                            <span className="required-indicator" aria-hidden="true">*</span>
                        )}
                        {required && <span className="sr-only">(required)</span>}
                    </label>
                )}
                <div className="relative z-10">
                    <select
                        ref={ref}
                        id={selectId}
                        className={`glass-input appearance-none pr-10 cursor-pointer ${error ? 'border-red-400/50 focus:border-red-400' : ''
                            } ${className}`}
                        aria-required={required}
                        aria-invalid={error ? 'true' : undefined}
                        aria-describedby={describedBy}
                        {...props}
                    >
                        {options.map((option) => (
                            <option key={option.value} value={option.value} className="bg-primary-950 text-white">
                                {option.label}
                            </option>
                        ))}
                    </select>
                    <ChevronDown
                        className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/40 pointer-events-none"
                        aria-hidden="true"
                    />
                </div>
                {helperText && !error && (
                    <p id={helperId} className="mt-1.5 text-sm text-white/50">
                        {helperText}
                    </p>
                )}
                {error && (
                    <p id={errorId} className="mt-1.5 text-sm text-red-400 error-message" role="alert">
                        {error}
                    </p>
                )}
            </div>
        );
    }
);

Select.displayName = 'Select';

export default Select;

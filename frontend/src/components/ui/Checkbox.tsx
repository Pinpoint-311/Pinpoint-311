import React, { forwardRef, useCallback, useEffect, useRef } from 'react';

/* One checkbox for the whole product.
 *
 * It is a real <input type="checkbox">, restyled with appearance-none rather
 * than hidden behind a drawn square. That keeps everything the browser gives a
 * native control: the label click, Space to toggle, form submission, the
 * accessible name from a wrapping <label> or htmlFor, and "mixed" announced for
 * the indeterminate state. The earlier mix was three looks (browser yellow,
 * Tailwind forms-less defaults, and two hand-drawn sr-only surrogates) and the
 * surrogates each had to re-implement focus to pass WCAG 2.4.7.
 *
 * Contrast (WCAG 1.4.11), against #1B1B3A, #23234A and #454390, the lightest
 * panel a control sits on:
 *   the unchecked white/60 edge is 4:1 or better on every one of them;
 *   the checked fill carries a primary-400 edge (4.3:1 on #454390) and a
 *   white mark at 4.4:1 or better against the primary-500/600 fill.
 *
 * Width and height are set inline on purpose: index.css sizes every
 * input[type="checkbox"] at 18px with a selector that outranks a utility class.
 */

export type CheckboxSize = 'sm' | 'md';

export interface CheckboxProps
    extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type' | 'size'> {
    size?: CheckboxSize;
    /** Shows a dash and is announced as "mixed". Purely visual state: clicking
     *  still toggles `checked`, as with the native property. */
    indeterminate?: boolean;
    /** Red edge, and aria-invalid unless the caller set it themselves. */
    error?: boolean;
    /** Classes for the wrapper that positions the box (margins, alignment). */
    className?: string;
    /** Classes added to the input itself. */
    inputClassName?: string;
}

const BOX: Record<CheckboxSize, { px: number; icon: string; radius: string }> = {
    sm: { px: 16, icon: 'w-3 h-3', radius: 'rounded-[5px]' },
    md: { px: 20, icon: 'w-3.5 h-3.5', radius: 'rounded-md' },
};

function assignRef<T>(ref: React.ForwardedRef<T>, value: T | null) {
    if (typeof ref === 'function') ref(value);
    else if (ref) (ref as React.MutableRefObject<T | null>).current = value;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
    { size = 'md', indeterminate = false, error = false, className = '', inputClassName = '', style, ...rest },
    ref,
) {
    const inner = useRef<HTMLInputElement | null>(null);
    const setRefs = useCallback((el: HTMLInputElement | null) => {
        inner.current = el;
        assignRef(ref, el);
    }, [ref]);

    // `indeterminate` is a DOM property with no attribute, so it has to be set
    // on the element; React does not pass it through.
    useEffect(() => {
        if (inner.current) inner.current.indeterminate = indeterminate;
    }, [indeterminate]);

    const box = BOX[size];
    const ariaInvalid = rest['aria-invalid'] ?? (error ? true : undefined);

    const inputClasses = [
        'peer m-0 shrink-0 appearance-none cursor-pointer border-[1.5px] bg-white/[0.06]',
        box.radius,
        'shadow-[inset_0_1px_2px_rgba(0,0,0,0.35)]',
        'transition-[background-color,border-color,box-shadow,transform] duration-200 ease-out motion-reduce:transition-none',
        error ? 'border-red-300' : 'border-white/60 hover:border-white/90 group-hover:border-white/90',
        // Checked and mixed share a fill; the mark above tells them apart.
        'checked:border-primary-400 checked:bg-gradient-to-br checked:from-primary-500 checked:to-primary-600 checked:shadow-[0_1px_6px_rgba(79,70,229,0.45)]',
        'indeterminate:border-primary-400 indeterminate:bg-gradient-to-br indeterminate:from-primary-500 indeterminate:to-primary-600',
        'active:scale-90 motion-reduce:active:scale-100',
        // The system focus style: the same 3px amber-300 ring as Button and Switch.
        'focus:outline-none focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-amber-300 focus-visible:ring-offset-2 focus-visible:ring-offset-[#1B1B3A]',
        'disabled:cursor-not-allowed disabled:opacity-50 disabled:active:scale-100',
        inputClassName,
    ].join(' ');

    // Hidden with [opacity:0], not opacity-0: index.css reveals every
    // .opacity-0 inside a focused .group (hover-only buttons, for keyboard
    // users), and a clicked checkbox keeps focus, so an unchecked box in a
    // CheckboxCard went on showing a half-size tick.
    const markBase = `pointer-events-none absolute inset-0 m-auto ${box.icon} text-white transition-[opacity,transform] duration-200 ease-out motion-reduce:transition-none`;

    return (
        <span
            className={`relative inline-flex shrink-0 align-middle ${className}`}
            style={{ width: box.px, height: box.px }}
        >
            <input
                ref={setRefs}
                type="checkbox"
                aria-invalid={ariaInvalid}
                className={inputClasses}
                style={{ width: box.px, height: box.px, minWidth: box.px, minHeight: box.px, ...style }}
                {...rest}
            />
            {indeterminate ? (
                <svg viewBox="0 0 16 16" fill="none" aria-hidden="true" className={`${markBase} [opacity:0] scale-50 peer-indeterminate:opacity-100 peer-indeterminate:scale-100`}>
                    <path d="M4 8h8" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" />
                </svg>
            ) : (
                <svg viewBox="0 0 16 16" fill="none" aria-hidden="true" className={`${markBase} [opacity:0] scale-50 peer-checked:opacity-100 peer-checked:scale-100`}>
                    <path d="M3.5 8.5l3 3 6-6.5" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
            )}
        </span>
    );
});

export interface CheckboxCardProps extends Omit<CheckboxProps, 'title' | 'size'> {
    title: React.ReactNode;
    description?: React.ReactNode;
    /** id for the description, so the caller can point aria-describedby at it. */
    descriptionId?: string;
    icon?: React.ReactNode;
    /** Rendered under the description: an error message, a note. */
    children?: React.ReactNode;
    /** Classes for the card (the <label>). */
    cardClassName?: string;
}

/* A selectable option card. The whole card is the <label>, so a click anywhere
 * on it toggles the box, and the box is pinned to the title's first line: a
 * 20px box in a 20px line box, rather than centred on the text block, which put
 * it beside the title on a one-line card and beside the description on a
 * two-line one.
 *
 * index.css makes every label holding a checkbox `display:flex; align-items:
 * center` with a selector that outranks utilities. The single full-width child
 * below, pinned with self-start, is what makes that rule harmless here: without
 * it a card stretched to its row's height centres its content. */
export const CheckboxCard = forwardRef<HTMLInputElement, CheckboxCardProps>(function CheckboxCard(
    { title, description, descriptionId, icon, children, cardClassName = '', error, disabled, ...rest },
    ref,
) {
    return (
        <label
            className={[
                'group relative block w-full rounded-xl border p-3.5 transition-colors duration-200 motion-reduce:transition-none',
                disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
                error
                    ? 'border-red-300/70 bg-red-500/10'
                    : 'border-white/15 bg-white/[0.03] hover:border-white/35 hover:bg-white/[0.06] has-[:checked]:border-primary-400/70 has-[:checked]:bg-primary-500/[0.14] has-[:checked]:hover:border-primary-300',
                'has-[:focus-visible]:border-amber-300/80',
                cardClassName,
            ].join(' ')}
        >
            <span className="flex w-full self-start items-start gap-3">
                <span className="flex h-5 shrink-0 items-center">
                    <Checkbox ref={ref} error={error} disabled={disabled} {...rest} />
                </span>
                {icon && (
                    <span className="flex h-5 shrink-0 items-center text-white/60 group-has-[:checked]:text-primary-300" aria-hidden="true">
                        {icon}
                    </span>
                )}
                <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium leading-5 text-white">{title}</span>
                    {description && (
                        <span id={descriptionId} className="mt-0.5 block text-xs leading-relaxed text-white/65">
                            {description}
                        </span>
                    )}
                    {children}
                </span>
            </span>
        </label>
    );
});

export default Checkbox;

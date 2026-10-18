import React, { useEffect, useId, useState } from 'react';

interface TooltipProps {
    /** The tooltip text. For an icon-only button, match its aria-label. */
    content: string;
    /** One focusable element, usually an icon-only button. */
    children: React.ReactElement;
    /** Extra classes for the wrapper. */
    className?: string;
}

/**
 * A visible label for icon-only controls (WCAG 1.4.13).
 *
 * A `title` attribute only shows on mouse hover, after a delay, and never on
 * keyboard focus, so a keyboard user had no way to see what an X button did.
 * This shows on hover AND focus, stays open while the pointer is over the
 * tooltip itself (hoverable), and Escape hides it without moving focus
 * (dismissible). The child keeps its own aria-label as its accessible name,
 * so the tooltip is linked by aria-describedby only when it says something
 * different.
 */
export const Tooltip: React.FC<TooltipProps> = ({ content, children, className = '' }) => {
    const [open, setOpen] = useState(false);
    const tooltipId = `${useId()}-tooltip`;

    useEffect(() => {
        if (!open) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') setOpen(false);
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [open]);

    const childLabel = (children.props as { 'aria-label'?: string })['aria-label'];
    const child = childLabel === content
        ? children
        : React.cloneElement(children as React.ReactElement<Record<string, unknown>>, {
            'aria-describedby': open ? tooltipId : undefined,
        });

    return (
        <span
            className={`relative inline-flex ${className}`}
            onMouseEnter={() => setOpen(true)}
            onMouseLeave={() => setOpen(false)}
            onFocus={() => setOpen(true)}
            onBlur={() => setOpen(false)}
        >
            {child}
            {open && (
                /* The transparent bottom padding bridges the gap between the
                 * control and the bubble, so moving the pointer onto the
                 * tooltip does not close it. */
                <span
                    role="tooltip"
                    id={tooltipId}
                    className="absolute bottom-full left-1/2 -translate-x-1/2 pb-2 z-50 pointer-events-auto"
                >
                    <span className="block whitespace-nowrap rounded-md bg-slate-950 text-white text-xs font-medium px-2 py-1 border border-white/60 shadow-lg">
                        {content}
                    </span>
                </span>
            )}
        </span>
    );
};

export default Tooltip;

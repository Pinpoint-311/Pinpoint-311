/**
 * DOM builders for popup content.
 *
 * Popup bodies used to be HTML strings with request descriptions, addresses and
 * GeoJSON property values concatenated straight into the markup — a stored-XSS
 * vector, since every one of those values is resident- or import-supplied. Text
 * here is only ever assigned through `textContent`, so a value can never become
 * markup no matter what it contains.
 *
 * Building nodes rather than strings also keeps vendor DOM out of content:
 * handlers are real listeners on real elements instead of `onclick="..."`
 * attributes reaching for window globals or an SDK's own close button.
 */

export interface ElementSpec {
    /** Inline CSS. An attribute value, never parsed as markup. */
    style?: string;
    /** Assigned as text — the safe channel for any untrusted value. */
    text?: string | number | null;
    title?: string;
    onClick?: (event: MouseEvent) => void;
    children?: PopupChild[];
}

export type PopupChild = Node | string | number | null | false | undefined;

export function el(tag: string, spec: ElementSpec = {}): HTMLElement {
    const node = document.createElement(tag);

    if (spec.style) node.setAttribute('style', spec.style);
    if (spec.title) node.title = spec.title;
    if (spec.text !== undefined && spec.text !== null) node.textContent = String(spec.text);

    for (const child of spec.children ?? []) {
        if (child === null || child === undefined || child === false) continue;
        node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
    }

    if (spec.onClick) {
        node.addEventListener('click', spec.onClick);
        // Popup content is generated, so give non-button clickables the
        // affordances the browser would otherwise only give real controls.
        if (tag !== 'button' && tag !== 'a') {
            node.setAttribute('role', 'button');
            node.setAttribute('tabindex', '0');
        }
    }

    return node;
}

/** Root wrapper every popup body shares: system font stack, nothing else. */
export function popupRoot(style: string, children: PopupChild[]): HTMLElement {
    return el('div', {
        style: `font-family: system-ui, -apple-system, sans-serif; ${style}`,
        children,
    });
}

export interface PropertyRowStyles {
    row: string;
    key: string;
    value: string;
}

/**
 * "key: value" rows from an arbitrary GeoJSON property bag. Keys are as
 * untrusted as values — both go through `text`.
 */
export function propertyRows(
    properties: Record<string, unknown>,
    styles: PropertyRowStyles,
    options: { skipKeys?: string[]; limit?: number; humanizeKeys?: boolean } = {},
): HTMLElement[] {
    const skip = new Set((options.skipKeys ?? []).map(k => k.toLowerCase()));

    let entries = Object.entries(properties).filter(([key]) => !skip.has(key.toLowerCase()));
    if (options.limit !== undefined) entries = entries.slice(0, options.limit);

    return entries.map(([key, value]) => el('div', {
        style: styles.row,
        children: [
            el('span', { style: styles.key, text: options.humanizeKeys === false ? key : key.replace(/_/g, ' ') }),
            el('span', { style: styles.value, text: formatValue(value) }),
        ],
    }));
}

function formatValue(value: unknown): string {
    if (value === null || value === undefined) return '';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
}

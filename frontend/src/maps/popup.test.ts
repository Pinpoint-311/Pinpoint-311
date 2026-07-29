import { describe, expect, it, vi } from 'vitest';

import { el, popupRoot } from './popup';

/**
 * These exist because popup bodies used to be HTML strings with request
 * descriptions, addresses and uploaded GeoJSON property values concatenated
 * into them. A resident filing a report with markup in the description had it
 * execute in a clerk's browser.
 *
 * So the property under test is not "the helper builds nice DOM" — it is that
 * no input, however hostile, can become markup.
 */

const PAYLOADS = [
    '<img src=x onerror=alert(1)>',
    '<script>alert(1)</script>',
    '"><svg/onload=alert(1)>',
    "javascript:alert(1)",
    '</div><iframe src="evil"></iframe>',
    '&lt;script&gt;alert(1)&lt;/script&gt;',
];

describe('untrusted text can never become markup', () => {
    it.each(PAYLOADS)('renders %s as text', payload => {
        const node = el('p', { text: payload });
        expect(node.textContent).toBe(payload);
        // The decisive assertion: no element was created from the payload.
        expect(node.querySelector('*')).toBeNull();
        expect(node.children.length).toBe(0);
    });

    it.each(PAYLOADS)('renders %s as text when passed as a child', payload => {
        const node = el('div', { children: [payload] });
        expect(node.textContent).toBe(payload);
        expect(node.querySelector('*')).toBeNull();
    });

    it('keeps a hostile value out of the markup even nested deeply', () => {
        const root = popupRoot('', [
            el('div', { children: [el('span', { text: '<script>alert(1)</script>' })] }),
        ]);
        expect(root.innerHTML).not.toContain('<script');
        expect(root.querySelector('script')).toBeNull();
    });

    it('treats a hostile title as an attribute value, not markup', () => {
        const node = el('button', { title: '"><script>alert(1)</script>' });
        expect(node.getAttribute('title')).toBe('"><script>alert(1)</script>');
        expect(node.querySelector('script')).toBeNull();
    });
});

describe('element building', () => {
    it('sets style as an attribute', () => {
        expect(el('div', { style: 'color: red;' }).getAttribute('style')).toBe('color: red;');
    });

    it('renders numeric text, including zero', () => {
        // Zero is the one that a truthiness check would silently drop, and it is
        // a real value here — a hotspot with 0 reports.
        expect(el('span', { text: 0 }).textContent).toBe('0');
        expect(el('span', { text: 42 }).textContent).toBe('42');
    });

    it('renders nothing for null or undefined text rather than the word "null"', () => {
        expect(el('span', { text: null }).textContent).toBe('');
        expect(el('span', {}).textContent).toBe('');
    });

    it('skips false and null children so conditional rendering reads naturally', () => {
        const node = el('div', {
            children: [el('span', { text: 'kept' }), false, null, undefined],
        });
        expect(node.children.length).toBe(1);
        expect(node.textContent).toBe('kept');
    });

    it('attaches a real listener rather than an inline handler', () => {
        const onClick = vi.fn();
        const node = el('button', { text: 'go', onClick });
        node.dispatchEvent(new MouseEvent('click'));
        expect(onClick).toHaveBeenCalledTimes(1);
        // An onclick attribute was the old pattern; it reached for window
        // globals and was an injection surface of its own.
        expect(node.getAttribute('onclick')).toBeNull();
    });
});

describe('popupRoot', () => {
    it('applies its own style alongside the caller’s', () => {
        const root = popupRoot('min-width: 220px;', []);
        expect(root.getAttribute('style')).toContain('min-width: 220px;');
        expect(root.getAttribute('style')).toContain('font-family');
    });

    it('nests children in order', () => {
        const root = popupRoot('', [el('h4', { text: 'one' }), el('p', { text: 'two' })]);
        expect(Array.from(root.children).map(c => c.textContent)).toEqual(['one', 'two']);
    });
});

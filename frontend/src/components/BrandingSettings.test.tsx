// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent, within, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import BrandingSettings, { type BrandingForm } from './BrandingSettings';
import { validateDomain, validateSocialUrl } from './brandingValidation';
import adminConsoleSource from '../pages/AdminConsole.tsx?raw';

vi.mock('../services/api', () => ({
    api: {
        uploadImage: vi.fn(async () => ({ url: '/uploads/logo.png', filename: 'logo.png' })),
        configureDomain: vi.fn(),
        getDomainStatus: vi.fn(async () => ({ configured_domains: [], server_ip: '203.0.113.10' })),
    },
}));

/* Admin Console -> Branding, after a WCAG 2.1 AA review (VPAT). */

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

function Harness({ initial = {}, onSave = () => { } }: { initial?: BrandingForm; onSave?: () => void }) {
    const [form, setForm] = useState<BrandingForm>({ township_name: 'Springfield', hero_text: 'Hi', ...initial });
    const [loading, setLoading] = useState(false);
    return <BrandingSettings form={form} setForm={setForm} onSave={onSave} isLoading={loading} setIsLoading={setLoading} />;
}

describe('upload controls (2.1.1, 4.1.2)', () => {
    it('are real buttons in the Tab order with accessible names', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        const logo = screen.getByRole('button', { name: 'Upload logo' });
        const favicon = screen.getByRole('button', { name: 'Upload favicon' });

        // Tab until we land on the logo button; it must be reachable.
        for (let i = 0; i < 10 && document.activeElement !== logo; i++) await user.tab();
        expect(document.activeElement).toBe(logo);
        await user.tab();
        expect(document.activeElement).toBe(favicon);

        // The hidden file inputs are out of the Tab order and the a11y tree.
        const input = screen.getByTestId('logo-file-input');
        expect(input.getAttribute('tabindex')).toBe('-1');
        expect(input.getAttribute('aria-hidden')).toBe('true');
        // And the button explains what to upload.
        expect(logo.getAttribute('aria-describedby')).toBeTruthy();
        expect(document.getElementById(logo.getAttribute('aria-describedby')!.split(' ')[0])!.textContent)
            .toMatch(/PNG/);
    });

    it('open the file picker with Enter and with Space', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        const clickSpy = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => { });
        const logo = screen.getByRole('button', { name: 'Upload logo' });
        logo.focus();
        await user.keyboard('{Enter}');
        expect(clickSpy).toHaveBeenCalledTimes(1);
        await user.keyboard(' ');
        expect(clickSpy).toHaveBeenCalledTimes(2);
    });

    it('sits in a group named by its visible label', () => {
        render(<Harness />);
        expect(screen.getByRole('group', { name: 'Logo' })).toBeTruthy();
        expect(screen.getByRole('group', { name: 'Favicon' })).toBeTruthy();
    });
});

describe('logo preview (1.1.1)', () => {
    it('hides the placeholder art and says no logo is uploaded', () => {
        render(<Harness />);
        expect(screen.getByTestId('logo-placeholder').getAttribute('aria-hidden')).toBe('true');
        expect(screen.getByText('No logo uploaded')).toBeTruthy();
    });

    it('names a real logo preview', () => {
        render(<Harness initial={{ logo_url: '/x.png' }} />);
        expect(screen.getByRole('img', { name: 'Springfield logo preview' })).toBeTruthy();
        expect(screen.getByRole('img', { name: 'Current logo' })).toBeTruthy();
        expect(screen.queryByText('No logo uploaded')).toBeNull();
    });
});

describe('custom domain (3.3.1, 3.3.3)', () => {
    it('validates on blur and links the error to the field', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        const field = screen.getByLabelText('Custom domain');
        await user.type(field, 'https://311.town.gov');
        expect(field.getAttribute('aria-invalid')).toBeNull(); // not before blur
        await user.tab();
        expect(field.getAttribute('aria-invalid')).toBe('true');
        const errId = field.getAttribute('aria-describedby')!;
        expect(document.getElementById(errId)!.textContent).toMatch(/without http/);

        // Fixing it as you type clears the error.
        await user.clear(field);
        await user.type(field, '311.town.gov');
        expect(field.getAttribute('aria-invalid')).toBeNull();
    });

    it('describes the field with helper text before any error', () => {
        render(<Harness />);
        const field = screen.getByLabelText('Custom domain');
        const ids = field.getAttribute('aria-describedby')!;
        expect(document.getElementById(ids)!.textContent).toMatch(/DNS records/);
    });
});

describe('social links (3.3.1, 3.3.3, 1.3.1)', () => {
    it('labels each field and groups each row', () => {
        render(<Harness initial={{ social_links: [{ platform: 'facebook', url: '', icon: 'Facebook' }] }} />);
        expect(screen.getByRole('group', { name: 'Link 1' })).toBeTruthy();
        expect(screen.getByLabelText('Platform for link 1')).toBeTruthy();
        expect(screen.getByLabelText('Web address for link 1')).toBeTruthy();
    });

    it('checks the host against the platform and explains the fix', async () => {
        const user = userEvent.setup();
        render(<Harness initial={{ social_links: [{ platform: 'facebook', url: '', icon: 'Facebook' }] }} />);
        const url = screen.getByLabelText('Web address for link 1');
        await user.type(url, 'https://instagram.com/town');
        await user.tab();
        expect(url.getAttribute('aria-invalid')).toBe('true');
        const msg = document.getElementById(url.getAttribute('aria-describedby')!)!.textContent;
        expect(msg).toMatch(/Facebook/);
        expect(msg).toMatch(/facebook\.com/);

        // Switching the platform to match makes it valid.
        await user.selectOptions(screen.getByLabelText('Platform for link 1'), 'instagram');
        expect(url.getAttribute('aria-invalid')).toBeNull();
    });

    it('blocks Save while a link is invalid, says why, and focuses the field', async () => {
        const user = userEvent.setup();
        const onSave = vi.fn();
        render(<Harness onSave={onSave} initial={{ social_links: [{ platform: 'website', url: 'town.gov', icon: 'Globe' }] }} />);
        await user.click(screen.getByRole('button', { name: /Save Changes/ }));
        expect(onSave).not.toHaveBeenCalled();
        const alert = screen.getAllByRole('alert').find((a) => a.textContent);
        expect(alert!.textContent).toMatch(/Not saved/);
        const url = screen.getByLabelText('Web address for link 1');
        expect(document.activeElement).toBe(url);
        expect(url.getAttribute('aria-invalid')).toBe('true');
        expect(document.getElementById(url.getAttribute('aria-describedby')!)!.textContent).toMatch(/https:\/\//);

        await user.clear(url);
        await user.type(url, 'https://town.gov');
        await user.click(screen.getByRole('button', { name: /Save Changes/ }));
        expect(onSave).toHaveBeenCalledTimes(1);
    });
});

describe('icon-only buttons (1.4.13, 4.1.2)', () => {
    it('show a tooltip on keyboard focus that Escape dismisses', async () => {
        const user = userEvent.setup();
        render(<Harness initial={{ social_links: [{ platform: 'website', url: 'https://town.gov', icon: 'Globe' }] }} />);
        const remove = screen.getByRole('button', { name: 'Remove link 1' });
        expect(remove.getAttribute('title')).toBeNull();
        act(() => remove.focus());
        expect(screen.getByRole('tooltip').textContent).toBe('Remove link 1');
        await user.keyboard('{Escape}');
        expect(screen.queryByRole('tooltip')).toBeNull();
        expect(document.activeElement).toBe(remove);
    });

    it('show a tooltip on hover that stays while the pointer is on it', () => {
        render(<Harness initial={{ logo_url: '/x.png' }} />);
        const remove = screen.getByRole('button', { name: 'Remove logo' });
        fireEvent.mouseEnter(remove.parentElement!);
        const tip = screen.getByRole('tooltip');
        fireEvent.mouseEnter(tip);
        expect(screen.getByRole('tooltip').textContent).toBe('Remove logo');
    });
});

describe('legal documents (1.3.1, 1.4.1)', () => {
    it('labels each textarea and links its helper text', () => {
        render(<Harness />);
        const privacy = screen.getByLabelText('Privacy Policy');
        expect(privacy.tagName).toBe('TEXTAREA');
        expect(document.getElementById(privacy.getAttribute('aria-describedby')!)!.textContent).toMatch(/Markdown/);
    });

    it('preview links are underlined and say they open a new tab', () => {
        render(<Harness />);
        const link = screen.getByRole('link', { name: /Preview privacy policy/ });
        expect(link.className).toMatch(/underline/);
        expect(link.className).toMatch(/preview-link/);
        expect(within(link).getByText('(opens in a new tab)')).toBeTruthy();
        expect(link.getAttribute('rel')).toMatch(/noopener/);
    });

    it('uses no fixed heights that would clip under text-spacing overrides (1.4.12)', () => {
        const { container } = render(<Harness />);
        container.querySelectorAll('textarea').forEach((t) => expect(t.className).not.toMatch(/(^|\s)h-\d/));
    });
});

describe('validators', () => {
    it('domain', () => {
        expect(validateDomain('')).toBeNull();
        expect(validateDomain('', true)).toMatch(/Enter a domain/);
        expect(validateDomain('311.town.gov')).toBeNull();
        expect(validateDomain('town')).toMatch(/\.gov/);
        expect(validateDomain('311.town.gov/path')).toMatch(/after the domain/);
        expect(validateDomain('bad_host.gov')).toMatch(/valid domain/);
        expect(validateDomain('-x.gov')).toMatch(/valid domain/);
    });

    it('social url', () => {
        expect(validateSocialUrl('website', 'https://town.gov')).toBeNull();
        expect(validateSocialUrl('website', 'ftp://town.gov')).toMatch(/https/);
        expect(validateSocialUrl('twitter', 'https://x.com/town')).toBeNull();
        expect(validateSocialUrl('twitter', 'https://twitter.com/town')).toBeNull();
        expect(validateSocialUrl('youtube', 'https://youtu.be/abc')).toBeNull();
        expect(validateSocialUrl('linkedin', 'https://www.linkedin.com/company/x')).toBeNull();
        expect(validateSocialUrl('facebook', 'https://notfacebook.com/x')).toMatch(/Facebook/);
        expect(validateSocialUrl('instagram', 'https://instagram.com.evil.io/x')).toMatch(/Instagram/);
    });
});

describe('admin console drawer and shared styles', () => {
    it('mobile navigation toggles report aria-expanded and control the sidebar', () => {
        expect(adminConsoleSource).toMatch(/id="admin-sidebar"/);
        const opens = adminConsoleSource.match(/aria-expanded=\{sidebarOpen\}\s*\n\s*aria-controls="admin-sidebar"/g) || [];
        expect(opens.length).toBe(2);
    });

});

describe('DNS instructions', () => {
    it("show this deployment's address, never a hardcoded one", async () => {
        render(<Harness />);
        expect((await screen.findAllByText('203.0.113.10')).length).toBeGreaterThan(0);
    });
});

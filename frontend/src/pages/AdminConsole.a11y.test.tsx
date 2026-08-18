// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Palette, Users } from 'lucide-react';
import { SidebarGroup, SidebarItem } from './AdminConsole';

/**
 * The admin console's sidebar: "where am I", and is the disclosure honest.
 *
 * The console routes eight sections through the URL hash. Which one you were
 * in was carried by a background tint and a brighter label and nothing else --
 * meaning by colour alone (WCAG 1.4.1), and to a screen reader all eight items
 * announced identically, so there was no way to answer "where am I" at all.
 *
 * The collapsible groups above them were silent disclosures: the only signal
 * that a group was open was a rotated chevron, which is nothing to a screen
 * reader, and no attribute tied the button to the items it revealed.
 *
 * These two components are exported for this test the same way the console
 * already exports ServiceCategoriesTab and DepartmentsTab. The third fix on
 * this page -- moving focus into the section that just loaded -- lives in
 * usePageNavigation's focusMain and is covered in that hook's own test; the
 * console's wiring of it is not exercised here.
 */

afterEach(cleanup);

describe('SidebarItem', () => {
    it('marks the current section with aria-current, not only a colour', () => {
        render(
            <>
                <SidebarItem icon={Palette} label="Branding" isActive onClick={() => { }} />
                <SidebarItem icon={Users} label="Users" isActive={false} onClick={() => { }} />
            </>
        );

        expect(screen.getByRole('button', { name: 'Branding' }).getAttribute('aria-current')).toBe('page');
        // Not aria-current="false": the attribute is absent on inactive items,
        // so exactly one button in the nav answers "where am I".
        expect(screen.getByRole('button', { name: 'Users' }).hasAttribute('aria-current')).toBe(false);
        expect(screen.getAllByRole('button', { current: 'page' })).toHaveLength(1);
    });

    it('names the item by its label alone, with the icon kept out of the name', () => {
        render(<SidebarItem icon={Users} label="Users" isActive={false} onClick={() => { }} />);
        // The decorative icon must not leak into the accessible name — "Users"
        // is the whole of it, which is also what a voice-control user says.
        expect(screen.getByRole('button', { name: 'Users' })).not.toBeNull();
    });

    it('activates from the keyboard', async () => {
        const user = userEvent.setup();
        const onClick = vi.fn();
        render(<SidebarItem icon={Users} label="Users" isActive={false} onClick={onClick} />);

        await user.tab();
        expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Users' }));

        await user.keyboard('{Enter}');
        expect(onClick).toHaveBeenCalledTimes(1);

        await user.keyboard(' ');
        expect(onClick).toHaveBeenCalledTimes(2);
    });
});

describe('SidebarGroup', () => {
    it('reports its open state and points aria-controls at a real element', async () => {
        render(
            <SidebarGroup title="Branding & Setup" icon={Palette} isActive defaultOpen>
                <SidebarItem icon={Palette} label="Branding" isActive onClick={() => { }} />
            </SidebarGroup>
        );

        const group = screen.getByRole('button', { name: 'Branding & Setup' });
        await waitFor(() => expect(group.getAttribute('aria-expanded')).toBe('true'));

        const controlled = group.getAttribute('aria-controls');
        expect(controlled).toBeTruthy();
        // A dangling aria-controls is decoration, not a relationship.
        expect(document.getElementById(controlled!)).not.toBeNull();
    });

    it('says it is collapsed when it is, and reveals its items on activation', async () => {
        const user = userEvent.setup();
        render(
            <SidebarGroup title="Organization" icon={Users} isActive={false}>
                <SidebarItem icon={Users} label="Users" isActive={false} onClick={() => { }} />
            </SidebarGroup>
        );

        const group = screen.getByRole('button', { name: 'Organization' });
        expect(group.getAttribute('aria-expanded')).toBe('false');
        expect(screen.queryByRole('button', { name: 'Users' })).toBeNull();

        await user.click(group);

        await waitFor(() => expect(group.getAttribute('aria-expanded')).toBe('true'));
        expect(await screen.findByRole('button', { name: 'Users' })).not.toBeNull();
    });

    it('opens itself when it holds the active section, and says so', async () => {
        const { rerender } = render(
            <SidebarGroup title="Organization" icon={Users} isActive={false}>
                <SidebarItem icon={Users} label="Users" isActive={false} onClick={() => { }} />
            </SidebarGroup>
        );
        const group = screen.getByRole('button', { name: 'Organization' });
        expect(group.getAttribute('aria-expanded')).toBe('false');

        rerender(
            <SidebarGroup title="Organization" icon={Users} isActive>
                <SidebarItem icon={Users} label="Users" isActive onClick={() => { }} />
            </SidebarGroup>
        );

        // The auto-open has to update the announced state too, or the group
        // reads as collapsed while its items sit visible on screen.
        await waitFor(() => expect(group.getAttribute('aria-expanded')).toBe('true'));
    });
});

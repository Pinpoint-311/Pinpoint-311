// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Tooltip } from './Tooltip';

afterEach(cleanup);

describe('Tooltip (WCAG 1.4.13)', () => {
    it('appears on keyboard focus and hides on blur', async () => {
        const user = userEvent.setup();
        render(<><Tooltip content="Delete"><button aria-label="Delete">x</button></Tooltip><button>next</button></>);
        expect(screen.queryByRole('tooltip')).toBeNull();
        await user.tab();
        expect(screen.getByRole('tooltip').textContent).toBe('Delete');
        await user.tab();
        expect(screen.queryByRole('tooltip')).toBeNull();
    });

    it('is dismissible with Escape without moving focus', async () => {
        const user = userEvent.setup();
        render(<Tooltip content="Delete"><button aria-label="Delete">x</button></Tooltip>);
        await user.tab();
        await user.keyboard('{Escape}');
        expect(screen.queryByRole('tooltip')).toBeNull();
        expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Delete' }));
    });

    it('appears on hover and stays while hovering the tooltip', () => {
        render(<Tooltip content="Delete"><button aria-label="Delete">x</button></Tooltip>);
        const wrapper = screen.getByRole('button').parentElement!;
        fireEvent.mouseEnter(wrapper);
        // Moving onto the tooltip stays inside the wrapper, so no mouseleave.
        fireEvent.mouseOver(screen.getByRole('tooltip'));
        expect(screen.getByRole('tooltip')).toBeTruthy();
        fireEvent.mouseLeave(wrapper);
        expect(screen.queryByRole('tooltip')).toBeNull();
    });

    it('describes the control when its text differs from the name', async () => {
        const user = userEvent.setup();
        render(<Tooltip content="Removes it for everyone"><button aria-label="Delete">x</button></Tooltip>);
        await user.tab();
        const btn = screen.getByRole('button', { name: 'Delete' });
        expect(btn.getAttribute('aria-describedby')).toBe(screen.getByRole('tooltip').id);
    });
});

// @vitest-environment jsdom
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import { Shield } from 'lucide-react';
import { Chip, RoleChip, StatusBadge, statusTone, roleLabel } from './Badge';

afterEach(cleanup);

describe('Chip', () => {
    it('shows a machine value as words, never the raw identifier', () => {
        render(<Chip value="priority_accepted" />);
        expect(screen.getByText('Priority accepted')).toBeTruthy();
        expect(screen.queryByText('priority_accepted')).toBeNull();
    });

    it('prefers children over value', () => {
        render(<Chip value="push_status">Status update</Chip>);
        expect(screen.getByText('Status update')).toBeTruthy();
    });

    it('carries its tone in colour and keeps the icon out of the accessible text', () => {
        const { container } = render(<Chip tone="danger" icon={Shield}>Failed</Chip>);
        const chip = screen.getByText('Failed');
        expect(chip.className).toContain('bg-red-500/20');
        expect(chip.className).toContain('rounded-full');
        expect(container.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true');
    });

    it('can be monospace for a value a person must match exactly', () => {
        render(<Chip mono>float</Chip>);
        expect(screen.getByText('float').className).toContain('font-mono');
    });
});

describe('statusTone', () => {
    it('keeps the shared status colours', () => {
        expect(statusTone('success')).toBe('success');
        expect(statusTone('failed')).toBe('danger');
        expect(statusTone('open')).toBe('danger');
        expect(statusTone('in_progress')).toBe('warning');
        expect(statusTone('closed')).toBe('success');
        expect(statusTone('something_else')).toBe('neutral');
    });
});

describe('RoleChip and StatusBadge', () => {
    it('names every role, including researcher', () => {
        render(<RoleChip role="researcher" />);
        expect(screen.getByText('Researcher')).toBeTruthy();
        expect(roleLabel('admin')).toBe('Admin');
    });

    it('renders an unexpected request status as words instead of crashing', () => {
        render(<StatusBadge status="on_hold" size="xs" />);
        expect(screen.getByText('On hold')).toBeTruthy();
    });
});

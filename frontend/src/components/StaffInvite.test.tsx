// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from 'vitest';
import { useState } from 'react';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { InviteCheckbox, InviteNotice, inviteResultMessage } from './StaffInvite';

afterEach(cleanup);

/** The Add User form's state, as AdminConsole holds it: on by default. */
function Form({ onValue }: { onValue?: (v: boolean) => void }) {
    const [sendInvite, setSendInvite] = useState(true);
    return <InviteCheckbox checked={sendInvite} onChange={(v) => { setSendInvite(v); onValue?.(v); }} />;
}

describe('InviteCheckbox', () => {
    it('is on by default and found by its label', () => {
        render(<Form />);
        const box = screen.getByLabelText('Send an invite email') as HTMLInputElement;
        expect(box.type).toBe('checkbox');
        expect(box.checked).toBe(true);
    });

    it('can be turned off, and says what it does', () => {
        const seen = vi.fn();
        render(<Form onValue={seen} />);
        const box = screen.getByLabelText('Send an invite email') as HTMLInputElement;
        fireEvent.click(box);
        expect(box.checked).toBe(false);
        expect(seen).toHaveBeenCalledWith(false);
        const hint = document.getElementById(box.getAttribute('aria-describedby') || '');
        expect(hint?.textContent).toMatch(/sign-in page/);
    });
});

describe('inviteResultMessage', () => {
    it('confirms a queued invite with the address', () => {
        expect(inviteResultMessage('queued', 'x@y.gov')).toBe('Invite sent to x@y.gov.');
    });

    it('says plainly when email is off', () => {
        expect(inviteResultMessage('skipped_email_off', 'x@y.gov'))
            .toBe('Email is turned off, so no invite was sent.');
    });

    it('says nothing when no invite was asked for', () => {
        expect(inviteResultMessage('not_requested', 'x@y.gov')).toBeNull();
    });

    it('points at Resend invite when queuing failed on create', () => {
        expect(inviteResultMessage('queue_failed', 'x@y.gov')).toMatch(/Resend invite/);
        expect(inviteResultMessage('queue_failed', 'x@y.gov', 'resent')).not.toMatch(/Resend invite/);
    });
});

describe('InviteNotice', () => {
    it('announces the confirmation in a live region and can be dismissed', () => {
        const dismiss = vi.fn();
        render(<InviteNotice message="Invite sent to x@y.gov." ok onDismiss={dismiss} />);
        const region = screen.getByRole('status');
        expect(region.textContent).toContain('Invite sent to x@y.gov.');
        fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
        expect(dismiss).toHaveBeenCalled();
    });

    it('keeps the live region mounted with nothing in it', () => {
        render(<InviteNotice message={null} ok={false} onDismiss={() => {}} />);
        expect(screen.getByRole('status').textContent).toBe('');
    });
});

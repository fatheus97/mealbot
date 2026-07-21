import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ResetPasswordModal } from './ResetPasswordModal';

vi.mock('../api', () => ({
  resetPassword: vi.fn(),
}));

import { resetPassword } from '../api';
const mockedReset = resetPassword as ReturnType<typeof vi.fn>;

function setUrl(search: string) {
  window.history.replaceState(null, '', `/${search}`);
}

beforeEach(() => {
  mockedReset.mockReset();
  setUrl('');
});

afterEach(() => {
  setUrl('');
});

describe('ResetPasswordModal', () => {
  it('renders nothing when there is no reset_token in the URL', () => {
    const { container } = render(<ResetPasswordModal />);
    expect(container).toBeEmptyDOMElement();
  });

  it('opens on a reset_token and strips it from the URL immediately', async () => {
    setUrl('?reset_token=secret-tok&other=keep');
    render(<ResetPasswordModal />);

    expect(screen.getByRole('heading', { name: /choose a new password/i })).toBeInTheDocument();
    // The single-use secret must not linger in the address bar / history.
    await waitFor(() => {
      expect(window.location.search).not.toContain('reset_token');
    });
    // Unrelated params are preserved.
    expect(window.location.search).toContain('other=keep');
  });

  it('gates submit on the backend complexity rules and confirmation match', async () => {
    setUrl('?reset_token=tok');
    const user = userEvent.setup();
    render(<ResetPasswordModal />);

    const [pw, confirm] = screen.getAllByPlaceholderText(/password/i);
    const submit = screen.getByRole('button', { name: /set new password/i });

    await user.type(pw, 'short');
    expect(screen.getByText(/at least 8 characters/i)).toBeInTheDocument();
    expect(submit).toBeDisabled();

    await user.clear(pw);
    await user.type(pw, 'longenoughbutnocaps1');
    expect(screen.getByText(/an upper-case letter/i)).toBeInTheDocument();
    expect(submit).toBeDisabled();

    await user.clear(pw);
    await user.type(pw, 'ValidPass123');
    await user.type(confirm, 'Different123');
    expect(screen.getByText(/don't match/i)).toBeInTheDocument();
    expect(submit).toBeDisabled();

    await user.clear(confirm);
    await user.type(confirm, 'ValidPass123');
    expect(submit).toBeEnabled();

    expect(mockedReset).not.toHaveBeenCalled();
  });

  it('resets, shows the sign-in prompt, and signals a global logout', async () => {
    setUrl('?reset_token=tok-xyz');
    mockedReset.mockResolvedValue(undefined);
    const onLogout = vi.fn();
    window.addEventListener('mealbot:logout', onLogout);

    const user = userEvent.setup();
    render(<ResetPasswordModal />);

    const [pw, confirm] = screen.getAllByPlaceholderText(/password/i);
    await user.type(pw, 'ValidPass123');
    await user.type(confirm, 'ValidPass123');
    await user.click(screen.getByRole('button', { name: /set new password/i }));

    expect(mockedReset).toHaveBeenCalledWith('tok-xyz', 'ValidPass123');
    expect(await screen.findByText(/your password has been updated/i)).toBeInTheDocument();
    // Does NOT auto-login — offers a sign-in action instead.
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    // The reset revoked every session server-side, so stale UI must be cleared.
    expect(onLogout).toHaveBeenCalledTimes(1);

    window.removeEventListener('mealbot:logout', onLogout);
  });

  it('surfaces a friendly error for an invalid/expired link and stays on the form', async () => {
    setUrl('?reset_token=stale');
    mockedReset.mockRejectedValue(
      new Error('This reset link is invalid or has expired. Please request a new one.'),
    );
    const user = userEvent.setup();
    render(<ResetPasswordModal />);

    const [pw, confirm] = screen.getAllByPlaceholderText(/password/i);
    await user.type(pw, 'ValidPass123');
    await user.type(confirm, 'ValidPass123');
    await user.click(screen.getByRole('button', { name: /set new password/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/invalid or has expired/i);
    expect(screen.queryByText(/your password has been updated/i)).not.toBeInTheDocument();
  });
});

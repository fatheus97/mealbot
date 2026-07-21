import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ForgotPasswordModal } from './ForgotPasswordModal';

vi.mock('../api', () => ({
  requestPasswordReset: vi.fn(),
}));

import { requestPasswordReset } from '../api';
const mockedRequest = requestPasswordReset as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockedRequest.mockReset();
});

describe('ForgotPasswordModal', () => {
  it('submits the email and shows a neutral confirmation', async () => {
    mockedRequest.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ForgotPasswordModal onClose={vi.fn()} />);

    await user.type(screen.getByPlaceholderText(/you@example/i), 'real@user.com');
    await user.click(screen.getByRole('button', { name: /send reset link/i }));

    expect(mockedRequest).toHaveBeenCalledWith('real@user.com');
    // The confirmation must reveal nothing about whether the account exists.
    expect(await screen.findByText(/if an account exists/i)).toBeInTheDocument();
  });

  it('shows the SAME confirmation copy whether or not the address is registered', async () => {
    // The component cannot know (backend 204s either way) and must not imply it.
    // Both a "found" and "not found" backend outcome resolve identically here.
    mockedRequest.mockResolvedValue(undefined);
    const user = userEvent.setup();

    const { unmount } = render(<ForgotPasswordModal onClose={vi.fn()} initialEmail="a@b.com" />);
    await user.click(screen.getByRole('button', { name: /send reset link/i }));
    const first = (await screen.findByText(/if an account exists/i)).textContent;
    unmount();

    render(<ForgotPasswordModal onClose={vi.fn()} initialEmail="nobody@nowhere.com" />);
    await user.click(screen.getByRole('button', { name: /send reset link/i }));
    const second = (await screen.findByText(/if an account exists/i)).textContent;

    // Only the echoed address differs; the surrounding copy is identical.
    expect(first?.replace('a@b.com', 'X')).toEqual(second?.replace('nobody@nowhere.com', 'X'));
  });

  it('surfaces an error without moving to the confirmation state', async () => {
    mockedRequest.mockRejectedValue(new Error('Too many attempts. Please wait a minute and try again.'));
    const user = userEvent.setup();
    render(<ForgotPasswordModal onClose={vi.fn()} initialEmail="x@y.com" />);

    await user.click(screen.getByRole('button', { name: /send reset link/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/too many attempts/i);
    expect(screen.queryByText(/if an account exists/i)).not.toBeInTheDocument();
  });

  it('prefills the email passed from the login form', () => {
    render(<ForgotPasswordModal onClose={vi.fn()} initialEmail="prefill@x.com" />);
    expect(screen.getByPlaceholderText(/you@example/i)).toHaveValue('prefill@x.com');
  });
});

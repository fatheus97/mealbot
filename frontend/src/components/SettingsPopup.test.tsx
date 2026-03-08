import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SettingsPopup } from './SettingsPopup';
import { AuthProvider } from '../contexts/AuthContext';
import type { ReactNode } from 'react';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { fetchUserProfile, updateUserProfile } from '../api';

const mockedFetchProfile = fetchUserProfile as ReturnType<typeof vi.fn>;
const mockedUpdateProfile = updateUserProfile as ReturnType<typeof vi.fn>;

const mockProfile = {
  id: 1,
  email: 'test@test.com',
  country: 'Germany',
  measurement_system: 'metric' as const,
  variability: 'traditional' as const,
  include_spices: true,
  onboarding_completed: true,
};

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

function loginUser() {
  localStorage.setItem('mealbot_token', 'test-token');
  localStorage.setItem('mealbot_user_id', '1');
  localStorage.setItem('mealbot_user_email', 'test@test.com');
}

beforeEach(() => {
  vi.stubGlobal(
    'location',
    Object.defineProperties(
      {},
      {
        ...Object.getOwnPropertyDescriptors(window.location),
        reload: { configurable: true, value: vi.fn() },
      },
    ),
  );
});

describe('SettingsPopup', () => {
  it('renders settings heading and close button', async () => {
    loginUser();
    mockedFetchProfile.mockResolvedValueOnce(mockProfile);

    render(<SettingsPopup onClose={vi.fn()} />, { wrapper: createWrapper() });

    expect(screen.getByText('Settings')).toBeInTheDocument();
    expect(screen.getByLabelText(/close settings/i)).toBeInTheDocument();
  });

  it('shows loading state before profile loads', () => {
    loginUser();
    mockedFetchProfile.mockReturnValue(new Promise(() => {})); // Never resolves

    render(<SettingsPopup onClose={vi.fn()} />, { wrapper: createWrapper() });

    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('loads and displays user profile data', async () => {
    loginUser();
    mockedFetchProfile.mockResolvedValueOnce(mockProfile);

    render(<SettingsPopup onClose={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Germany')).toBeInTheDocument();
    });
    expect(screen.getByLabelText(/traditional/i)).toBeChecked();
  });

  it('calls onClose when close button clicked', async () => {
    loginUser();
    mockedFetchProfile.mockResolvedValueOnce(mockProfile);
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<SettingsPopup onClose={onClose} />, { wrapper: createWrapper() });

    await user.click(screen.getByLabelText(/close settings/i));
    expect(onClose).toHaveBeenCalled();
  });

  it('calls onClose when backdrop mousedown fires on itself', async () => {
    loginUser();
    mockedFetchProfile.mockResolvedValueOnce(mockProfile);
    const onClose = vi.fn();

    const { container } = render(
      <SettingsPopup onClose={onClose} />,
      { wrapper: createWrapper() },
    );

    // The backdrop is the outermost fixed div; fire mousedown directly on it
    const backdrop = container.firstElementChild as HTMLElement;
    // fireEvent gives us control over target === currentTarget
    const { fireEvent } = await import('@testing-library/react');
    fireEvent.mouseDown(backdrop);

    expect(onClose).toHaveBeenCalled();
  });

  it('submits updated preferences and closes', async () => {
    loginUser();
    // fetchUserProfile is called on mount AND after mutation invalidation
    mockedFetchProfile.mockResolvedValue(mockProfile);
    mockedUpdateProfile.mockResolvedValueOnce({
      ...mockProfile,
      variability: 'experimental',
    });
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<SettingsPopup onClose={onClose} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Germany')).toBeInTheDocument();
    });

    // Switch to experimental
    await user.click(screen.getByLabelText(/experimental/i));
    await user.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(mockedUpdateProfile).toHaveBeenCalledWith({
        country: 'Germany',
        variability: 'experimental',
        include_spices: true,
      });
    });

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('shows alert on save failure', async () => {
    loginUser();
    mockedFetchProfile.mockResolvedValueOnce(mockProfile);
    mockedUpdateProfile.mockRejectedValueOnce(new Error('Server error'));
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    const user = userEvent.setup();

    render(<SettingsPopup onClose={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Germany')).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        'Failed to save preferences. Please try again.',
      );
    });
  });
});

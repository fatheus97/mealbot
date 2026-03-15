import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { OnboardingModal } from './OnboardingModal';
import { AuthProvider } from '../contexts/AuthContext';
import type { ReactNode } from 'react';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { updateUserProfile } from '../api';

const mockedUpdateProfile = updateUserProfile as ReturnType<typeof vi.fn>;

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

describe('OnboardingModal', () => {
  it('renders welcome heading and preferences form', () => {
    loginUser();
    render(<OnboardingModal />, { wrapper: createWrapper() });

    expect(screen.getByText(/welcome/i)).toBeInTheDocument();
    expect(screen.getByText(/set up your preferences/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /get started/i })).toBeInTheDocument();
  });

  it('renders country input and variability options', () => {
    loginUser();
    render(<OnboardingModal />, { wrapper: createWrapper() });

    expect(screen.getByPlaceholderText(/start typing to search/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/traditional/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/experimental/i)).toBeInTheDocument();
  });

  it('submits preferences and calls API', async () => {
    loginUser();
    const user = userEvent.setup();
    mockedUpdateProfile.mockResolvedValueOnce({
      id: 1,
      email: 'test@test.com',
      country: 'Germany',
      variability: 'traditional',
      include_spices: true,
      onboarding_completed: true,
      measurement_system: 'metric',
    });

    render(<OnboardingModal />, { wrapper: createWrapper() });

    const countryInput = screen.getByPlaceholderText(/start typing to search/i);
    await user.type(countryInput, 'Germany');

    await user.click(screen.getByRole('button', { name: /get started/i }));

    await waitFor(() => {
      expect(mockedUpdateProfile).toHaveBeenCalledWith({
        country: 'Germany',
        language: 'English',
        variability: 'traditional',
        include_spices: true,
        track_snacks: true,
        onboarding_completed: true,
      });
    });
  });

  it('shows alert on API failure', async () => {
    loginUser();
    const user = userEvent.setup();
    mockedUpdateProfile.mockRejectedValueOnce(new Error('Network error'));
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});

    render(<OnboardingModal />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /get started/i }));

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        'Failed to save preferences. Please try again.',
      );
    });
  });
});

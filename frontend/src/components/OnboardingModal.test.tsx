import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { OnboardingModal } from './OnboardingModal';
import { useLocaleStore, DEFAULT_LOCALE } from '../store/useLocaleStore';
import { untranslatedEnglishIn } from '../test/i18nAssertions';
import { AuthProvider } from '../contexts/AuthContext';
import type { ReactNode } from 'react';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { authFetch, updateUserProfile } from '../api';

const mockedUpdateProfile = updateUserProfile as ReturnType<typeof vi.fn>;
const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;

// PreferencesForm fetches /countries and /languages on mount to validate the
// picker input against the backend whitelists. AuthProvider fetches /config.
function stubAuthFetch() {
  mockedAuthFetch.mockImplementation((url: string) => {
    if (url === '/countries') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ countries: ['Germany', 'France', 'Italy'] }),
      });
    }
    if (url === '/languages') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ languages: ['English', 'Czech', 'Spanish'] }),
      });
    }
    if (url === '/config') {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }
    return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
  });
}

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
  mockedAuthFetch.mockReset();
  stubAuthFetch();
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
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it('renders welcome heading and preferences form', () => {
    loginUser();
    render(<OnboardingModal />, { wrapper: createWrapper() });

    expect(screen.getByText(/welcome/i)).toBeInTheDocument();
    expect(screen.getByText(/set up your preferences/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /get started/i })).toBeInTheDocument();
  });

  it('translates every visible string, not just the heading', () => {
    // The subtitle sat hardcoded in English directly under a translated title,
    // through a full browser pass — because that pass walked the SETTINGS
    // modal and the claim was generalised to onboarding, which renders only
    // for a user who has not completed it. Assert the whole dialog instead of
    // spot-checking the heading.
    loginUser();
    useLocaleStore.setState({ locale: 'cs', explicit: true });
    const { container } = render(<OnboardingModal />, { wrapper: createWrapper() });

    expect(screen.getByText('Vítejte! Nastavte si své předvolby')).toBeInTheDocument();
    expect(
      screen.getByText('Pomohou nám vytvářet jídelníčky na míru právě vám.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Začít' })).toBeInTheDocument();

    // Exact check: is any string we have an English value for — and a
    // DIFFERENT Czech value for — still in the DOM? A "looks English" regex
    // cannot do this; it flags "Jednotky v postupu" and misses anything with a
    // diacritic. See test/i18nAssertions.ts.
    expect(untranslatedEnglishIn(container)).toEqual([]);
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

    // Wait for /countries to populate so 'Germany' passes the whitelist gate.
    await waitFor(() =>
      expect(mockedAuthFetch).toHaveBeenCalledWith('/countries'),
    );

    const countryInput = screen.getByPlaceholderText(/start typing to search/i);
    await user.type(countryInput, 'Germany');

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /get started/i })).toBeEnabled(),
    );
    await user.click(screen.getByRole('button', { name: /get started/i }));

    await waitFor(() => {
      expect(mockedUpdateProfile).toHaveBeenCalledWith({
        country: 'Germany',
        language: 'English',
        variability: 'traditional',
        measurement_system: 'metric',
        include_spices: true,
        show_pieces: false,
        track_snacks: true,
        need_to_use_enabled: true,
        default_day_layout: [],
        onboarding_completed: true,
      });
    });
  });

  it('shows inline error on API failure', async () => {
    loginUser();
    const user = userEvent.setup();
    mockedUpdateProfile.mockRejectedValueOnce(new Error('Network error'));

    render(<OnboardingModal />, { wrapper: createWrapper() });

    await user.click(screen.getByRole('button', { name: /get started/i }));

    // Inline <p role="alert">, not window.alert — the latter blocks screen
    // readers and interrupts flow, the former stays attached to the form.
    const alerts = await screen.findAllByRole('alert');
    const savedErrors = alerts.filter(
      (el) => el.textContent === 'Failed to save preferences. Please try again.',
    );
    expect(savedErrors).toHaveLength(1);
  });
});

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

import { authFetch, fetchUserProfile, updateUserProfile } from '../api';
import type { UserProfile } from '../types';

const mockedUpdateProfile = updateUserProfile as ReturnType<typeof vi.fn>;
const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;
const mockedFetchProfile = fetchUserProfile as ReturnType<typeof vi.fn>;

// GET /users for an account that has never saved a preference: every column at
// its default in db_models.User. Onboarding's defaults are exactly these.
const freshProfile: UserProfile = {
  id: 1,
  email: 'test@test.com',
  country: null,
  language: 'English',
  measurement_system: 'metric',
  variability: 'traditional',
  include_spices: true,
  track_snacks: true,
  show_pieces: false,
  need_to_use_enabled: true,
  waste_tracking_enabled: false,
  onboarding_completed: false,
  is_admin: false,
  default_day_layout: null,
};

// An account an admin sent back through onboarding. Admin "Reset onboarding"
// clears only onboarding_completed, so everything else is still saved. Every
// preference differs from its default, so a form seeded with the defaults
// cannot pass for one seeded from the profile.
const resetProfile: UserProfile = {
  ...freshProfile,
  country: 'Germany',
  language: 'Czech',
  measurement_system: 'imperial',
  variability: 'experimental',
  include_spices: false,
  track_snacks: false,
  show_pieces: true,
  need_to_use_enabled: false,
  waste_tracking_enabled: true,
  default_day_layout: ['sweet_breakfast', 'main_course'],
};

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
  mockedUpdateProfile.mockReset();
  mockedFetchProfile.mockReset();
  mockedFetchProfile.mockResolvedValue(freshProfile);
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

  it('renders welcome heading and preferences form', async () => {
    loginUser();
    render(<OnboardingModal />, { wrapper: createWrapper() });

    expect(screen.getByText(/welcome/i)).toBeInTheDocument();
    expect(screen.getByText(/set up your preferences/i)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /get started/i })).toBeInTheDocument();
  });

  it('translates every visible string, not just the heading', async () => {
    // The subtitle sat hardcoded in English directly under a translated title,
    // through a full browser pass — because that pass walked the SETTINGS
    // modal and the claim was generalised to onboarding, which renders only
    // for a user who has not completed it. Assert the whole dialog instead of
    // spot-checking the heading.
    loginUser();
    useLocaleStore.setState({ locale: 'cs', explicit: true });
    const { container } = render(<OnboardingModal />, { wrapper: createWrapper() });

    // Awaited first, so the sweep below runs over the form and not over the
    // loading line that precedes it.
    expect(await screen.findByRole('button', { name: 'Začít' })).toBeInTheDocument();
    expect(screen.getByText('Vítejte! Nastavte si své předvolby')).toBeInTheDocument();
    expect(
      screen.getByText('Pomohou nám vytvářet jídelníčky na míru právě vám.'),
    ).toBeInTheDocument();

    // Exact check: is any string we have an English value for — and a
    // DIFFERENT Czech value for — still in the DOM? A "looks English" regex
    // cannot do this; it flags "Jednotky v postupu" and misses anything with a
    // diacritic. See test/i18nAssertions.ts.
    expect(untranslatedEnglishIn(container)).toEqual([]);
  });

  it('renders country input and variability options', async () => {
    loginUser();
    render(<OnboardingModal />, { wrapper: createWrapper() });

    expect(await screen.findByPlaceholderText(/start typing to search/i)).toBeInTheDocument();
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

    const countryInput = await screen.findByPlaceholderText(/start typing to search/i);
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
        waste_tracking_enabled: false,
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

    await user.click(await screen.findByRole('button', { name: /get started/i }));

    // Inline <p role="alert">, not window.alert — the latter blocks screen
    // readers and interrupts flow, the former stays attached to the form.
    const alerts = await screen.findAllByRole('alert');
    const savedErrors = alerts.filter(
      (el) => el.textContent === 'Failed to save preferences. Please try again.',
    );
    expect(savedErrors).toHaveLength(1);
  });

  it('gives a brand-new user exactly the default preferences', async () => {
    loginUser();
    const user = userEvent.setup();
    mockedUpdateProfile.mockResolvedValueOnce({ ...freshProfile, onboarding_completed: true });

    render(<OnboardingModal />, { wrapper: createWrapper() });
    await user.click(await screen.findByRole('button', { name: /get started/i }));

    await waitFor(() => {
      expect(mockedUpdateProfile).toHaveBeenCalledWith({
        country: null,
        language: 'English',
        variability: 'traditional',
        measurement_system: 'metric',
        include_spices: true,
        show_pieces: false,
        track_snacks: true,
        need_to_use_enabled: true,
        waste_tracking_enabled: false,
        default_day_layout: [],
        onboarding_completed: true,
      });
    });
  });

  it("shows a reset user's saved preferences, not the defaults", async () => {
    // The bug: the form was seeded from hard-coded defaults, so a user an admin
    // sent back through onboarding saw (and on "Get Started" saved) the
    // defaults over every preference they had set.
    loginUser();
    mockedFetchProfile.mockResolvedValue(resetProfile);

    render(<OnboardingModal />, { wrapper: createWrapper() });

    expect(await screen.findByDisplayValue('Germany')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Czech')).toBeInTheDocument();
    expect(screen.getByLabelText(/experimental/i)).toBeChecked();
    expect(screen.getByRole('radio', { name: /imperial/i })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /show pieces instead of grams/i })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /ask where food went/i })).toBeChecked();
  });

  it("saves a reset user's untouched form back unchanged", async () => {
    loginUser();
    const user = userEvent.setup();
    mockedFetchProfile.mockResolvedValue(resetProfile);
    mockedUpdateProfile.mockResolvedValueOnce({ ...resetProfile, onboarding_completed: true });

    render(<OnboardingModal />, { wrapper: createWrapper() });
    await screen.findByDisplayValue('Germany');
    await user.click(screen.getByRole('button', { name: /get started/i }));

    await waitFor(() => {
      expect(mockedUpdateProfile).toHaveBeenCalledWith({
        country: 'Germany',
        language: 'Czech',
        variability: 'experimental',
        measurement_system: 'imperial',
        include_spices: false,
        show_pieces: true,
        track_snacks: false,
        need_to_use_enabled: false,
        waste_tracking_enabled: true,
        default_day_layout: ['sweet_breakfast', 'main_course'],
        onboarding_completed: true,
      });
    });
  });

  it('holds the form back until the profile is known', () => {
    // PreferencesForm reads initialValues once, on mount. A form painted with
    // the defaults while the profile loads would keep them after it arrives.
    loginUser();
    mockedFetchProfile.mockReturnValue(new Promise(() => {})); // never resolves

    render(<OnboardingModal />, { wrapper: createWrapper() });

    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /get started/i })).not.toBeInTheDocument();
  });

  it('offers a retry, not a defaults form, when the profile fails to load', async () => {
    loginUser();
    const user = userEvent.setup();
    mockedFetchProfile.mockRejectedValueOnce(new Error('Profile fetch failed: 500'));
    mockedFetchProfile.mockResolvedValueOnce(resetProfile);

    render(<OnboardingModal />, { wrapper: createWrapper() });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load your preferences.',
    );
    expect(screen.queryByRole('button', { name: /get started/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByDisplayValue('Germany')).toBeInTheDocument();
  });
});

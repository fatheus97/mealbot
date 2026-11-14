import { describe, it, expect, vi, beforeEach } from 'vitest';
import { stubLocationReload } from '../test/location';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { OnboardingModal } from './OnboardingModal';
import { useLocaleStore, DEFAULT_LOCALE } from '../store/useLocaleStore';
import { untranslatedEnglishIn } from '../test/i18nAssertions';
import { AuthProvider, useAuth } from '../contexts/AuthContext';
import type { ReactNode } from 'react';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
  answerRestockPrompt: vi.fn(),
}));

import { answerRestockPrompt, authFetch, fetchUserProfile, updateUserProfile } from '../api';
import type { UserProfile } from '../types';

const mockedUpdateProfile = updateUserProfile as ReturnType<typeof vi.fn>;
const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;
const mockedFetchProfile = fetchUserProfile as ReturnType<typeof vi.fn>;
const mockedAnswerRestock = answerRestockPrompt as ReturnType<typeof vi.fn>;

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
  show_nutrition: false,
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
  show_nutrition: true,
  need_to_use_enabled: false,
  waste_tracking_enabled: true,
  default_day_layout: ['sweet_breakfast', 'main_course'],
};

/** GET /fridge as the server answers it: the list and its version token. */
const fridgeReply = (items: unknown[], token: string | null = '1:3', status = 200) =>
  ({
    ok: status < 400,
    status,
    headers: new Headers(token ? { 'X-Fridge-Version': token } : {}),
    json: () => Promise.resolve(items),
  }) as Response;
const MILK = { name: 'Milk', quantity: 1, unit: 'l' };
// Served in order to the modal's fridge GETs (the load, then the PATCH's
// refetch); the last one repeats.
let fridgeReplies: Response[] = [];

// PreferencesForm fetches /countries and /languages on mount to validate the
// picker input against the backend whitelists. AuthProvider fetches /config.
function stubAuthFetch() {
  mockedAuthFetch.mockImplementation((url: string) => {
    if (url === '/fridge') {
      return Promise.resolve(fridgeReplies.length > 1 ? fridgeReplies.shift() : fridgeReplies[0]);
    }
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

function createWrapper(
  queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  }),
) {
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

/** MainLayout's half: the modal shows until onboarding completes. */
function renderOnboarding() {
  const onStartRestock = vi.fn();
  function Harness() {
    const { onboardingCompleted } = useAuth();
    return onboardingCompleted ? <p>ONBOARDING_DONE</p> : <OnboardingModal onStartRestock={onStartRestock} />;
  }
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const view = render(<Harness />, { wrapper: createWrapper(queryClient) });
  return { ...view, onStartRestock, queryClient };
}

beforeEach(() => {
  // A stocked fridge, so the cases that predate the stock step close as before.
  fridgeReplies = [fridgeReply([MILK])];
  mockedAuthFetch.mockReset();
  stubAuthFetch();
  mockedUpdateProfile.mockReset();
  mockedAnswerRestock.mockReset();
  mockedAnswerRestock.mockResolvedValue({ due: false, days_since_write: null });
  mockedFetchProfile.mockReset();
  mockedFetchProfile.mockResolvedValue(freshProfile);
  stubLocationReload();
});

describe('OnboardingModal', () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it('renders welcome heading and preferences form', async () => {
    loginUser();
    render(<OnboardingModal onStartRestock={() => {}} />, { wrapper: createWrapper() });

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
    const { container } = render(<OnboardingModal onStartRestock={() => {}} />, { wrapper: createWrapper() });

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
    render(<OnboardingModal onStartRestock={() => {}} />, { wrapper: createWrapper() });

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

    render(<OnboardingModal onStartRestock={() => {}} />, { wrapper: createWrapper() });

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
        show_nutrition: false,
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

    render(<OnboardingModal onStartRestock={() => {}} />, { wrapper: createWrapper() });

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

    render(<OnboardingModal onStartRestock={() => {}} />, { wrapper: createWrapper() });
    await user.click(await screen.findByRole('button', { name: /get started/i }));

    await waitFor(() => {
      expect(mockedUpdateProfile).toHaveBeenCalledWith({
        country: null,
        language: 'English',
        variability: 'traditional',
        measurement_system: 'metric',
        include_spices: true,
        show_pieces: false,
        show_nutrition: false,
        track_snacks: true,
        need_to_use_enabled: true,
        waste_tracking_enabled: false,
        default_day_layout: [],
        onboarding_completed: true,
      });
    });
  });

  it('sends the nutrition preference when it is ticked', async () => {
    // This builder rebuilds the PATCH body field by field, and Partial<Pick>
    // type-checks a dropped field, so only the API call proves it is sent.
    loginUser();
    const user = userEvent.setup();
    mockedUpdateProfile.mockResolvedValueOnce({
      ...freshProfile,
      show_nutrition: true,
      onboarding_completed: true,
    });

    render(<OnboardingModal onStartRestock={() => {}} />, { wrapper: createWrapper() });
    const box = await screen.findByRole('checkbox', { name: /show approximate nutrition/i });
    expect(box).not.toBeChecked();
    await user.click(box);
    await user.click(screen.getByRole('button', { name: /get started/i }));

    await waitFor(() => {
      expect(mockedUpdateProfile).toHaveBeenCalledWith(
        expect.objectContaining({ show_nutrition: true }),
      );
    });
  });

  it("shows a reset user's saved preferences, not the defaults", async () => {
    // The bug: the form was seeded from hard-coded defaults, so a user an admin
    // sent back through onboarding saw (and on "Get Started" saved) the
    // defaults over every preference they had set.
    loginUser();
    mockedFetchProfile.mockResolvedValue(resetProfile);

    render(<OnboardingModal onStartRestock={() => {}} />, { wrapper: createWrapper() });

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

    render(<OnboardingModal onStartRestock={() => {}} />, { wrapper: createWrapper() });
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
        show_nutrition: true,
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

    render(<OnboardingModal onStartRestock={() => {}} />, { wrapper: createWrapper() });

    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /get started/i })).not.toBeInTheDocument();
  });

  it('offers a retry, not a defaults form, when the profile fails to load', async () => {
    loginUser();
    const user = userEvent.setup();
    mockedFetchProfile.mockRejectedValueOnce(new Error('Profile fetch failed: 500'));
    mockedFetchProfile.mockResolvedValueOnce(resetProfile);

    render(<OnboardingModal onStartRestock={() => {}} />, { wrapper: createWrapper() });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not load your preferences.',
    );
    expect(screen.queryByRole('button', { name: /get started/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByDisplayValue('Germany')).toBeInTheDocument();
  });
});

describe('OnboardingModal stock step', () => {
  // A brand-new user's PATCH, the same as before the stock step existed.
  const FRESH_PAYLOAD = {
    country: null,
    language: 'English',
    variability: 'traditional',
    measurement_system: 'metric',
    include_spices: true,
    show_pieces: false,
    show_nutrition: false,
    track_snacks: true,
    need_to_use_enabled: true,
    waste_tracking_enabled: false,
    default_day_layout: [],
    onboarding_completed: true,
  };

  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
    loginUser();
    mockedUpdateProfile.mockResolvedValue({ ...freshProfile, onboarding_completed: true });
    fridgeReplies = [fridgeReply([])];
  });

  async function submit(user: ReturnType<typeof userEvent.setup>, label: RegExp | string = /get started/i) {
    await user.click(await screen.findByRole('button', { name: label }));
  }

  it('offers to stock an empty fridge; Scan completes onboarding and opens Start fresh', async () => {
    const user = userEvent.setup();
    const { onStartRestock } = renderOnboarding();
    await submit(user);

    expect(await screen.findByRole('heading', { name: 'Stock your fridge now?' })).toBeInTheDocument();
    // Focus jumps to Scan, so the question is announced as the dialog's description.
    expect(
      screen.getByRole('dialog', {
        name: 'Stock your fridge now?',
        description: 'Take photos of your food and your latest receipts, check the list, save.',
      }),
    ).toBeInTheDocument();
    expect(mockedUpdateProfile).toHaveBeenCalledTimes(1);
    expect(mockedUpdateProfile).toHaveBeenCalledWith(FRESH_PAYLOAD);
    // The server flag is already true, so the session hint is written now: a
    // reload skips the preferences form. The step itself still shows.
    expect(localStorage.getItem('mealbot_onboarding')).toBe('true');
    expect(screen.queryByText('ONBOARDING_DONE')).not.toBeInTheDocument();
    expect(onStartRestock).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Scan my food' }));
    expect(onStartRestock).toHaveBeenCalledTimes(1);
    expect(screen.getByText('ONBOARDING_DONE')).toBeInTheDocument();
    expect(localStorage.getItem('mealbot_onboarding')).toBe('true');
    expect(mockedUpdateProfile).toHaveBeenCalledTimes(1);
    // The stock step answered the restock question too.
    expect(mockedAnswerRestock).toHaveBeenCalledTimes(1);
  });

  it('Later completes onboarding without opening Start fresh', async () => {
    const user = userEvent.setup();
    const { onStartRestock, queryClient } = renderOnboarding();
    await submit(user);

    await user.click(await screen.findByRole('button', { name: 'Later' }));
    expect(screen.getByText('ONBOARDING_DONE')).toBeInTheDocument();
    expect(onStartRestock).not.toHaveBeenCalled();
    // Later is an answer: "Start fresh?" must not follow it straight away. The
    // seed is what holds the prompt's query back while the POST is in flight.
    expect(mockedAnswerRestock).toHaveBeenCalledTimes(1);
    expect(queryClient.getQueryData(['restock', 1])).toEqual({ due: false, days_since_write: null });
  });

  it('closes as before when the fridge has food in it (an admin reset, a new household member)', async () => {
    fridgeReplies = [fridgeReply([MILK])];
    const user = userEvent.setup();
    const { onStartRestock } = renderOnboarding();
    await submit(user);

    expect(await screen.findByText('ONBOARDING_DONE')).toBeInTheDocument();
    expect(onStartRestock).not.toHaveBeenCalled();
  });

  it('closes as before when the fridge came without a token, which Start fresh needs', async () => {
    fridgeReplies = [fridgeReply([], null)];
    const user = userEvent.setup();
    renderOnboarding();
    await submit(user);

    expect(await screen.findByText('ONBOARDING_DONE')).toBeInTheDocument();
  });

  it('closes as before when the fridge never loaded, or its refetch after the save failed', async () => {
    fridgeReplies = [fridgeReply([MILK], '1:3', 500)];
    const user = userEvent.setup();
    const never = renderOnboarding();
    await submit(user);
    expect(await screen.findByText('ONBOARDING_DONE')).toBeInTheDocument();
    never.unmount();
    localStorage.removeItem('mealbot_onboarding');

    // An empty list with a token loaded first; the save's refetch then failed,
    // so that list is no longer known to be current.
    fridgeReplies = [fridgeReply([]), fridgeReply([], '1:4', 500)];
    renderOnboarding();
    await submit(user);
    expect(await screen.findByText('ONBOARDING_DONE')).toBeInTheDocument();
  });

  it('points an unconfirmed email at confirming first, with OK instead of Scan', async () => {
    // Every scan returns 403 until the email is confirmed.
    localStorage.setItem('mealbot_email_verified', 'false');
    const user = userEvent.setup();
    const { onStartRestock, queryClient } = renderOnboarding();
    await submit(user);

    expect(await screen.findByRole('heading', { name: 'Stock your fridge now?' })).toBeInTheDocument();
    // The pointer is the instruction that matters here, and focus is on OK.
    expect(
      screen.getByRole('dialog', {
        name: 'Stock your fridge now?',
        description:
          'Take photos of your food and your latest receipts, check the list, save. ' +
          'Confirm your email first. Then Start fresh in the Fridge section scans your food.',
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Scan my food' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Later' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'OK' }));
    expect(screen.getByText('ONBOARDING_DONE')).toBeInTheDocument();
    expect(onStartRestock).not.toHaveBeenCalled();
    expect(mockedAnswerRestock).toHaveBeenCalledTimes(1);
    expect(queryClient.getQueryData(['restock', 1])).toEqual({ due: false, days_since_write: null });
  });

  it('leaves no untranslated English in Czech, in either branch', async () => {
    useLocaleStore.setState({ locale: 'cs', explicit: true });
    const user = userEvent.setup();
    const verified = renderOnboarding();
    await submit(user, 'Začít');
    expect(
      await screen.findByRole('heading', { name: 'Chcete hned zapsat, co máte v lednici?' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Naskenovat jídlo' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Později' })).toBeInTheDocument();
    expect(untranslatedEnglishIn(verified.container)).toEqual([]);
    verified.unmount();

    // A second fresh account: the first one's stock step wrote the onboarding hint.
    localStorage.removeItem('mealbot_onboarding');
    localStorage.setItem('mealbot_email_verified', 'false');
    const unverified = renderOnboarding();
    await submit(user, 'Začít');
    expect(
      await screen.findByText(
        'Nejdřív si potvrďte e-mail. Potom jídlo naskenujete v sekci Lednice tlačítkem „Začít nanovo“.',
      ),
    ).toBeInTheDocument();
    expect(untranslatedEnglishIn(unverified.container)).toEqual([]);
  });
});

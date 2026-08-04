import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SettingsPopup } from './SettingsPopup';
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

const mockedFetchProfile = fetchUserProfile as ReturnType<typeof vi.fn>;
const mockedUpdateProfile = updateUserProfile as ReturnType<typeof vi.fn>;
const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;

// PreferencesForm fetches /countries and /languages. AuthProvider fetches /config.
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
    if (url === '/staples') {
      // PantryStaples (embedded in the modal) reads its list on mount.
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) });
    }
    return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
  });
}

const mockProfile = {
  id: 1,
  email: 'test@test.com',
  country: 'Germany',
  language: 'English',
  measurement_system: 'metric' as const,
  variability: 'traditional' as const,
  include_spices: true,
  track_snacks: true,
  onboarding_completed: true,
  default_day_layout: null,
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

describe('SettingsPopup', () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

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

    // Specifically the profile-loading text — the embedded PantryStaples shows
    // its own "Loading staples…" while its list fetches, so match exactly.
    expect(screen.getByText('Loading...')).toBeInTheDocument();
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

  // The gap this closes: PreferencesForm reported show_pieces correctly, but
  // this component rebuilt the PATCH body field-by-field and dropped it. Saving
  // looked like it worked and the preference silently reverted. `Partial<Pick<…>>`
  // makes every field optional, so nothing type-checked the omission — only an
  // assertion on what actually reaches the API can catch it.
  it('sends the show-pieces preference when it is toggled on', async () => {
    loginUser();
    mockedFetchProfile.mockResolvedValue(mockProfile);
    mockedUpdateProfile.mockResolvedValueOnce({ ...mockProfile, show_pieces: true });
    const user = userEvent.setup();

    render(<SettingsPopup onClose={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => expect(screen.getByDisplayValue('Germany')).toBeInTheDocument());
    await waitFor(() => expect(mockedAuthFetch).toHaveBeenCalledWith('/countries'));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /save preferences/i })).toBeEnabled(),
    );

    await user.click(screen.getByRole('checkbox', { name: /show pieces instead of grams/i }));
    await user.click(screen.getByRole('button', { name: /save preferences/i }));

    await waitFor(() => {
      expect(mockedUpdateProfile).toHaveBeenCalledWith(
        expect.objectContaining({ show_pieces: true }),
      );
    });
  });

  // Same class of bug as show_pieces: the payload is rebuilt field-by-field
  // here, and `Partial<Pick<…>>` type-checks an omission. Only an assertion on
  // what reaches the API catches a dropped field.
  it('sends the measurement system when it is changed', async () => {
    loginUser();
    mockedFetchProfile.mockResolvedValue(mockProfile);
    mockedUpdateProfile.mockResolvedValueOnce({ ...mockProfile, measurement_system: 'imperial' });
    const user = userEvent.setup();

    render(<SettingsPopup onClose={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => expect(screen.getByDisplayValue('Germany')).toBeInTheDocument());
    await waitFor(() => expect(mockedAuthFetch).toHaveBeenCalledWith('/countries'));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /save preferences/i })).toBeEnabled(),
    );

    await user.click(screen.getByRole('radio', { name: /imperial/i }));
    await user.click(screen.getByRole('button', { name: /save preferences/i }));

    await waitFor(() => {
      expect(mockedUpdateProfile).toHaveBeenCalledWith(
        expect.objectContaining({ measurement_system: 'imperial' }),
      );
    });
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

    // Wait for /countries fetch so the 'Germany' initial value passes the
    // whitelist gate and the Save button is enabled.
    await waitFor(() =>
      expect(mockedAuthFetch).toHaveBeenCalledWith('/countries'),
    );
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /save preferences/i })).toBeEnabled(),
    );

    // Switch to experimental
    await user.click(screen.getByLabelText(/experimental/i));
    await user.click(screen.getByRole('button', { name: /save preferences/i }));

    await waitFor(() => {
      expect(mockedUpdateProfile).toHaveBeenCalledWith({
        country: 'Germany',
        language: 'English',
        variability: 'experimental',
        measurement_system: 'metric',
        include_spices: true,
        show_pieces: false,
        track_snacks: true,
        default_day_layout: [],
      });
    });

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('leaves no English string in the modal when switched to Czech', async () => {
    // The same check as OnboardingModal's. It is worth having on BOTH: the
    // browser pass that missed the onboarding subtitle missed it precisely
    // because it walked this modal and generalised.
    loginUser();
    mockedFetchProfile.mockResolvedValueOnce(mockProfile);
    useLocaleStore.setState({ locale: 'cs', explicit: true });

    const { container } = render(<SettingsPopup onClose={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    await screen.findByRole('heading', { name: /Zásoby spíže/ });

    expect(untranslatedEnglishIn(container)).toEqual([]);
  });

  it('embeds the Pantry staples section (co-located with Include spices)', async () => {
    loginUser();
    mockedFetchProfile.mockResolvedValueOnce(mockProfile);

    render(<SettingsPopup onClose={vi.fn()} />, { wrapper: createWrapper() });

    // The staples editor lives in the modal now (loads its list via /staples),
    // right alongside the "Include spices" preference.
    expect(
      await screen.findByRole('heading', { name: /pantry staples/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/include spices in shopping list/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save staples/i })).toBeInTheDocument();
  });

  it('guards close against unsaved pantry staples (no silent loss)', async () => {
    loginUser();
    mockedFetchProfile.mockResolvedValueOnce(mockProfile);
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<SettingsPopup onClose={onClose} />, { wrapper: createWrapper() });

    // Add a staple — now dirty and unsaved.
    await user.type(await screen.findByLabelText('New staple name'), 'flour');
    await user.click(screen.getByRole('button', { name: 'Add' }));

    // Closing via ✕ must NOT silently close — it prompts to discard.
    await user.click(screen.getByLabelText(/close settings/i));
    expect(onClose).not.toHaveBeenCalled();
    expect(
      screen.getByRole('alertdialog', { name: /discard unsaved pantry staples/i }),
    ).toBeInTheDocument();

    // "Keep editing" dismisses the prompt without closing.
    await user.click(screen.getByRole('button', { name: /keep editing/i }));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    // Re-open the prompt, then confirm discard → closes.
    await user.click(screen.getByLabelText(/close settings/i));
    await user.click(screen.getByRole('button', { name: /discard/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it('shows inline error on save failure', async () => {
    loginUser();
    mockedFetchProfile.mockResolvedValueOnce(mockProfile);
    mockedUpdateProfile.mockRejectedValueOnce(new Error('Server error'));
    const user = userEvent.setup();

    render(<SettingsPopup onClose={vi.fn()} />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByDisplayValue('Germany')).toBeInTheDocument();
    });
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /save preferences/i })).toBeEnabled(),
    );

    await user.click(screen.getByRole('button', { name: /save preferences/i }));

    // Inline alert banner, not window.alert — the save action should not be
    // interrupted by a blocking modal dialog.
    const alerts = await screen.findAllByRole('alert');
    const savedErrors = alerts.filter(
      (el) => el.textContent === 'Failed to save preferences. Please try again.',
    );
    expect(savedErrors).toHaveLength(1);
  });
});

describe('SettingsPopup — account email section', () => {
  it('shows the address with a Change control', async () => {
    // The banner escape hatch only exists for UNVERIFIED users. A verified user
    // who loses access to their inbox has the same problem and no banner, so
    // this is their only route out.
    loginUser();
    mockedFetchProfile.mockResolvedValue(mockProfile);
    const Wrapper = createWrapper();
    render(<SettingsPopup onClose={vi.fn()} />, { wrapper: Wrapper });

    expect(await screen.findByText('Email address')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^change$/i })).toBeInTheDocument();
  });

  it('hides it for a demo session', async () => {
    // The address is server-generated and POST /auth/email refuses demo
    // accounts with a 403 — so the control could only ever fail.
    const AuthCtx = await import('../contexts/AuthContext');
    vi.spyOn(AuthCtx, 'useAuth').mockReturnValue({
      userId: 1,
      email: 'demo-abc@mealbot.local',
      isDemo: true,
    } as unknown as ReturnType<typeof AuthCtx.useAuth>);

    loginUser();
    mockedFetchProfile.mockResolvedValue(mockProfile);
    const Wrapper = createWrapper();
    render(<SettingsPopup onClose={vi.fn()} />, { wrapper: Wrapper });

    await waitFor(() => expect(screen.getByText('Settings')).toBeInTheDocument());
    expect(screen.queryByText('Email address')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^change$/i })).not.toBeInTheDocument();
  });
});

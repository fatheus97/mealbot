import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PreferencesForm } from './PreferencesForm';
import type { PreferencesFormValues } from './PreferencesForm';

vi.mock('../api.ts', () => ({
  authFetch: vi.fn(),
}));

import { authFetch } from '../api.ts';
const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;

const defaultValues: PreferencesFormValues = {
  country: '',
  language: 'English',
  variability: 'traditional',
  include_spices: true,
  track_snacks: true,
  default_day_layout: [],
};

function mockWhitelists(
  countries: string[] = ['France', 'Germany', 'Italy'],
  languages: string[] = ['English', 'Czech', 'Spanish'],
) {
  mockedAuthFetch.mockImplementation((url: string) => {
    if (url === '/countries') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ countries }),
      });
    }
    if (url === '/languages') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ languages }),
      });
    }
    return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
  });
}

beforeEach(() => {
  mockedAuthFetch.mockReset();
  mockWhitelists();
});

describe('PreferencesForm', () => {
  it('renders all form fields', () => {
    render(
      <PreferencesForm
        initialValues={defaultValues}
        onSubmit={vi.fn()}
        submitLabel="Save"
      />,
    );

    expect(screen.getByPlaceholderText(/start typing to search/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/traditional/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/experimental/i)).toBeInTheDocument();
    expect(screen.getByText(/include spices/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
  });

  it('renders with custom submit label', () => {
    render(
      <PreferencesForm
        initialValues={defaultValues}
        onSubmit={vi.fn()}
        submitLabel="Get Started"
      />,
    );

    expect(screen.getByRole('button', { name: /get started/i })).toBeInTheDocument();
  });

  it('calls onSubmit with form values', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(
      <PreferencesForm
        initialValues={defaultValues}
        onSubmit={onSubmit}
        submitLabel="Save"
      />,
    );

    // The component fetches /countries on mount — wait for it so the
    // whitelist check passes when we type 'Germany' below.
    await waitFor(() =>
      expect(mockedAuthFetch).toHaveBeenCalledWith('/countries'),
    );

    // Type a country
    const countryInput = screen.getByPlaceholderText(/start typing to search/i);
    await user.type(countryInput, 'Germany');

    // Select experimental
    await user.click(screen.getByLabelText(/experimental/i));

    // Uncheck spices (first checkbox)
    const checkboxes = screen.getAllByRole('checkbox');
    await user.click(checkboxes[0]); // include_spices

    // Submit
    await user.click(screen.getByRole('button', { name: /save/i }));

    expect(onSubmit).toHaveBeenCalledWith({
      country: 'Germany',
      language: 'English',
      variability: 'experimental',
      include_spices: false,
      track_snacks: true,
      default_day_layout: [],
    });
  });

  it('submits with initial values when nothing is changed', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(
      <PreferencesForm
        initialValues={{
          country: 'France',
          language: 'English',
          variability: 'traditional',
          include_spices: true,
          track_snacks: true,
          default_day_layout: [],
        }}
        onSubmit={onSubmit}
        submitLabel="Save"
      />,
    );

    // Wait for /countries fetch so 'France' passes the whitelist gate.
    await waitFor(() => expect(screen.getByRole('button', { name: /save/i })).toBeEnabled());

    await user.click(screen.getByRole('button', { name: /save/i }));

    expect(onSubmit).toHaveBeenCalledWith({
      country: 'France',
      language: 'English',
      variability: 'traditional',
      include_spices: true,
      track_snacks: true,
      default_day_layout: [],
    });
  });

  it('shows "Saving..." when loading', () => {
    render(
      <PreferencesForm
        initialValues={defaultValues}
        onSubmit={vi.fn()}
        submitLabel="Save"
        loading={true}
      />,
    );

    const button = screen.getByRole('button', { name: /saving/i });
    expect(button).toBeDisabled();
  });

  it('button is enabled when not loading', () => {
    render(
      <PreferencesForm
        initialValues={defaultValues}
        onSubmit={vi.fn()}
        submitLabel="Save"
        loading={false}
      />,
    );

    expect(screen.getByRole('button', { name: /save/i })).toBeEnabled();
  });

  it('shows correct description for traditional variability', () => {
    render(
      <PreferencesForm
        initialValues={defaultValues}
        onSubmit={vi.fn()}
        submitLabel="Save"
      />,
    );

    expect(screen.getByText(/classic dishes/i)).toBeInTheDocument();
  });

  it('shows correct description for experimental variability', async () => {
    const user = userEvent.setup();

    render(
      <PreferencesForm
        initialValues={defaultValues}
        onSubmit={vi.fn()}
        submitLabel="Save"
      />,
    );

    await user.click(screen.getByLabelText(/experimental/i));
    expect(screen.getByText(/creative combinations/i)).toBeInTheDocument();
  });

  it('disables submit when country is not in the whitelist', async () => {
    // Backend's country list is the source of truth — the picker can offer
    // free typing (datalist), but a non-matching value must not reach PATCH.
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(
      <PreferencesForm
        initialValues={defaultValues}
        onSubmit={onSubmit}
        submitLabel="Save"
      />,
    );

    await waitFor(() =>
      expect(mockedAuthFetch).toHaveBeenCalledWith('/countries'),
    );

    await user.type(
      screen.getByPlaceholderText(/start typing to search/i),
      'Atlantis',
    );

    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
    expect(screen.getByText(/pick a country from the list/i)).toBeInTheDocument();

    // Submission is also blocked at the form level (button disabled is a UX
    // hint, not a guarantee — assert the click doesn't call onSubmit either).
    await user.click(screen.getByRole('button', { name: /save/i }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('does not lock out a returning user when /countries fetch fails', async () => {
    // Regression: if the whitelist fetch errors, the client used to leave
    // countrySet empty and reject every pre-populated country. The backend
    // still whitelists at PATCH — the client should fall back to server-side
    // validation, not block saves entirely.
    mockedAuthFetch.mockImplementation((url: string) => {
      if (url === '/countries') return Promise.reject(new Error('network'));
      return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
    });

    render(
      <PreferencesForm
        initialValues={{
          country: 'France',
          language: 'English',
          variability: 'traditional',
          include_spices: true,
          track_snacks: true,
          default_day_layout: [],
        }}
        onSubmit={vi.fn()}
        submitLabel="Save"
      />,
    );

    await waitFor(() =>
      expect(mockedAuthFetch).toHaveBeenCalledWith('/countries'),
    );

    expect(screen.getByRole('button', { name: /save/i })).toBeEnabled();
    expect(screen.queryByText(/pick a country from the list/i)).not.toBeInTheDocument();
  });

  it('populates the datalist from the fetched country list', async () => {
    mockWhitelists(['Czech Republic', 'Slovakia']);

    render(
      <PreferencesForm
        initialValues={defaultValues}
        onSubmit={vi.fn()}
        submitLabel="Save"
      />,
    );

    await waitFor(() => {
      // datalist options are not exposed via getByRole('option') in jsdom
      // reliably, so check via the raw DOM.
      const options = document.querySelectorAll('#country-list option');
      expect(options).toHaveLength(2);
    });
  });

  it('disables submit when language is not in the whitelist', async () => {
    // Same pattern as country — the language field is templated into the LLM
    // prompt, so a non-whitelist value must be blocked at the form level
    // instead of falling through to the opaque "failed to save" path.
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(
      <PreferencesForm
        initialValues={defaultValues}
        onSubmit={onSubmit}
        submitLabel="Save"
      />,
    );

    await waitFor(() =>
      expect(mockedAuthFetch).toHaveBeenCalledWith('/languages'),
    );

    const languageInput = screen.getByPlaceholderText(/e\.g\. english/i);
    await user.clear(languageInput);
    await user.type(languageInput, 'Klingon');

    expect(screen.getByRole('button', { name: /save/i })).toBeDisabled();
    expect(screen.getByText(/pick a language from the list/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /save/i }));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('Tab completes country from a prefix match', async () => {
    mockWhitelists(['Czech Republic', 'Slovakia', 'Italy']);
    const user = userEvent.setup();

    render(
      <PreferencesForm
        initialValues={defaultValues}
        onSubmit={vi.fn()}
        submitLabel="Save"
      />,
    );

    await waitFor(() =>
      expect(mockedAuthFetch).toHaveBeenCalledWith('/countries'),
    );

    const countryInput = screen.getByPlaceholderText(/start typing to search/i);
    await user.click(countryInput);
    await user.keyboard('cz');
    await user.keyboard('{Tab}');

    expect(countryInput).toHaveValue('Czech Republic');
  });

  it('Enter completes language from a prefix match without submitting', async () => {
    mockWhitelists(['France'], ['English', 'Czech']);
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(
      <PreferencesForm
        initialValues={{ ...defaultValues, country: 'France' }}
        onSubmit={onSubmit}
        submitLabel="Save"
      />,
    );

    await waitFor(() =>
      expect(mockedAuthFetch).toHaveBeenCalledWith('/languages'),
    );

    const languageInput = screen.getByPlaceholderText(/e\.g\. english/i);
    await user.clear(languageInput);
    await user.type(languageInput, 'cz');
    await user.keyboard('{Enter}');

    expect(languageInput).toHaveValue('Czech');
    // Enter must not have slipped through to submit the form.
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('Tab canonicalizes case (italy → Italy)', async () => {
    const user = userEvent.setup();

    render(
      <PreferencesForm
        initialValues={defaultValues}
        onSubmit={vi.fn()}
        submitLabel="Save"
      />,
    );

    await waitFor(() =>
      expect(mockedAuthFetch).toHaveBeenCalledWith('/countries'),
    );

    const countryInput = screen.getByPlaceholderText(/start typing to search/i);
    await user.click(countryInput);
    await user.keyboard('italy');
    await user.keyboard('{Tab}');

    expect(countryInput).toHaveValue('Italy');
  });
});

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
};

function mockCountries(list: string[] = ['France', 'Germany', 'Italy']) {
  mockedAuthFetch.mockImplementation((url: string) => {
    if (url === '/countries') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ countries: list }),
      });
    }
    return Promise.reject(new Error(`Unexpected authFetch: ${url}`));
  });
}

beforeEach(() => {
  mockedAuthFetch.mockReset();
  mockCountries();
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

  it('populates the datalist from the fetched country list', async () => {
    mockCountries(['Czech Republic', 'Slovakia']);

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
});

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PreferencesForm } from './PreferencesForm';
import type { PreferencesFormValues } from './PreferencesForm';

const defaultValues: PreferencesFormValues = {
  country: '',
  language: 'English',
  variability: 'traditional',
  include_spices: true,
  track_snacks: true,
};

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
});

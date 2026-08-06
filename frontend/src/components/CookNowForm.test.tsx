import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CookNowForm } from './CookNowForm';
import { useLocaleStore, DEFAULT_LOCALE } from '../store/useLocaleStore';
import { untranslatedEnglishIn } from '../test/i18nAssertions';
import { AuthProvider } from '../contexts/AuthContext';
import type { ReactNode } from 'react';
import { setColorScheme } from '../test/media';
import { PAGE_TEXT, MUTED_PAGE_OPACITY } from '../constants/theme';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  generateRecipe: vi.fn(),
  cookRecipe: vi.fn(),
  favoriteRecipe: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
  mergeFridgeItems: vi.fn(),
  scanReceipt: vi.fn(),
}));

import { authFetch, generateRecipe, cookRecipe, favoriteRecipe } from '../api';

const mockedAuthFetch = authFetch as ReturnType<typeof vi.fn>;
const mockedGenerate = generateRecipe as ReturnType<typeof vi.fn>;
const mockedCook = cookRecipe as ReturnType<typeof vi.fn>;
const mockedFavorite = favoriteRecipe as ReturnType<typeof vi.fn>;

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
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

const okEmpty = () =>
  ({ ok: true, status: 200, json: () => Promise.resolve({}) }) as unknown as Response;

beforeEach(() => {
  localStorage.clear();
  mockedAuthFetch.mockReset();
  mockedGenerate.mockReset();
  mockedCook.mockReset();
  mockedFavorite.mockReset();
  // AuthProvider + useFridge hit authFetch; stub harmlessly.
  mockedAuthFetch.mockImplementation(() => Promise.resolve(okEmpty()));
});

describe('CookNowForm', () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it('leaves no untranslated English when switched to Czech', () => {
    // Exact dictionary comparison, not a "looks English" regex. Only sees what
    // is RENDERED — the generated-recipe branch is covered by the next case.
    loginUser();
    useLocaleStore.setState({ locale: 'cs', explicit: true });
    render(<CookNowForm />, { wrapper: createWrapper() });
    expect(untranslatedEnglishIn(document.body)).toEqual([]);
  });

  it('stays translated once a recipe is generated, and after cooking it', async () => {
    // The branch the case above cannot reach. It hid TWO raw English literals
    // ("Edit", "✓ Cooked") through a full review of this slice, and the
    // comment that used to sit above claimed they were "covered above" — they
    // were not; this was the file's only Czech-locale test.
    loginUser();
    const czechRecipe = {
      name: 'Rajská polévka',
      meal_type: 'soup',
      meal_type_label: 'Polévka',
      ingredients: [{ name: 'rajčata', quantity_grams: 300, is_spice: false }],
      steps: ['Vařit', 'Podávat'],
      total_time_minutes: 20,
    };
    mockedGenerate.mockResolvedValueOnce({ recipe: czechRecipe, generation_id: 7 });
    mockedCook.mockResolvedValueOnce({ id: 42, name: 'Rajská polévka', is_favorite: false });
    useLocaleStore.setState({ locale: 'cs', explicit: true });

    const user = userEvent.setup();
    render(<CookNowForm />, { wrapper: createWrapper() });
    await user.click(screen.getByRole('button', { name: 'Vytvořit recept' }));
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Rajská polévka' })).toBeInTheDocument(),
    );
    expect(untranslatedEnglishIn(document.body)).toEqual([]);

    // …and the post-cook state, which swaps the button row for a "Cooked" mark.
    await user.click(screen.getByRole('button', { name: 'Označit jako uvařené' }));
    await waitFor(() => expect(screen.getByText(/Uvařeno/)).toBeInTheDocument());
    expect(untranslatedEnglishIn(document.body)).toEqual([]);
  });

  it('generates a recipe and displays it', async () => {
    loginUser();
    mockedGenerate.mockResolvedValueOnce({
      recipe: {
        name: 'Quick Soup',
        meal_type: 'soup',
        meal_type_label: 'Soup',
        ingredients: [{ name: 'chicken', quantity_grams: 200, is_spice: false }],
        steps: ['Simmer', 'Serve'],
        total_time_minutes: 20,
      },
      generation_id: 7,
    });

    render(<CookNowForm />, { wrapper: createWrapper() });

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText(/meal type/i), 'soup');
    await user.click(screen.getByRole('button', { name: /generate recipe/i }));

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: /quick soup/i })).toBeInTheDocument(),
    );
    // slot_layout enforces the user-chosen meal_type on the backend.
    expect(mockedGenerate).toHaveBeenCalledTimes(1);
    const call = mockedGenerate.mock.calls[0][0];
    expect(call.meal_type).toBe('soup');
  });

  it('calls cookRecipe with the same request + recipe when Mark cooked is clicked', async () => {
    loginUser();
    mockedGenerate.mockResolvedValueOnce({
      recipe: {
        name: 'Quick Soup',
        meal_type: 'soup',
        meal_type_label: 'Soup',
        ingredients: [{ name: 'chicken', quantity_grams: 200, is_spice: false }],
        steps: ['Simmer'],
      },
      generation_id: 7,
    });
    mockedCook.mockResolvedValueOnce({
      id: 42,
      day_index: 1,
      meal_index: 1,
      name: 'Quick Soup',
      meal_type: 'soup',
      cooked_at: '2026-04-23T10:00:00Z',
      is_favorite: false,
    });

    render(<CookNowForm />, { wrapper: createWrapper() });
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /generate recipe/i }));
    await waitFor(() => screen.getByRole('button', { name: /mark as cooked/i }));

    await user.click(screen.getByRole('button', { name: /mark as cooked/i }));

    await waitFor(() => expect(mockedCook).toHaveBeenCalledTimes(1));
    const payload = mockedCook.mock.calls[0][0];
    expect(payload.meal_type).toBe('main_course');  // default
    expect(payload.recipe.name).toBe('Quick Soup');
    // The generation id from /generate rides back so the server can link edits.
    expect(payload.generation_id).toBe(7);

    await waitFor(() => expect(screen.getByText(/✓ cooked/i)).toBeInTheDocument());
  });

  it('threads generation_id into the favorite payload when the star is clicked', async () => {
    loginUser();
    mockedGenerate.mockResolvedValueOnce({
      recipe: {
        name: 'Quick Soup',
        meal_type: 'soup',
        meal_type_label: 'Soup',
        ingredients: [{ name: 'chicken', quantity_grams: 200, is_spice: false }],
        steps: ['Simmer'],
      },
      generation_id: 7,
    });
    mockedFavorite.mockResolvedValueOnce({
      id: 99,
      day_index: 1,
      meal_index: 1,
      name: 'Quick Soup',
      meal_type: 'soup',
      cooked_at: null,
      is_favorite: true,
    });

    render(<CookNowForm />, { wrapper: createWrapper() });
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /generate recipe/i }));
    await waitFor(() => screen.getByRole('switch', { name: /add to cookbook/i }));

    await user.click(screen.getByRole('switch', { name: /add to cookbook/i }));

    await waitFor(() => expect(mockedFavorite).toHaveBeenCalledTimes(1));
    const payload = mockedFavorite.mock.calls[0][0];
    expect(payload.recipe.name).toBe('Quick Soup');
    // Same edit-telemetry linkage as the cook path.
    expect(payload.generation_id).toBe(7);
  });

  it('collects "ingredients to avoid" as chips and sends them in the request', async () => {
    // Ticket #2 (mealbot-tickets): the avoid field now uses the same chip input as
    // "ingredients to feature". Each committed chip must land in avoid_ingredients.
    loginUser();
    mockedGenerate.mockResolvedValueOnce({
      recipe: {
        name: 'Bowl',
        meal_type: 'main_course',
        meal_type_label: 'Main course',
        ingredients: [],
        steps: ['Toss'],
      },
      generation_id: null,
    });

    render(<CookNowForm />, { wrapper: createWrapper() });
    const user = userEvent.setup();
    await user.type(
      screen.getByPlaceholderText(/to avoid and press enter/i),
      'peanuts{Enter}cilantro{Enter}',
    );
    await user.click(screen.getByRole('button', { name: /generate recipe/i }));

    await waitFor(() => expect(mockedGenerate).toHaveBeenCalledTimes(1));
    const call = mockedGenerate.mock.calls[0][0];
    expect(call.avoid_ingredients).toEqual(['peanuts', 'cilantro']);
  });

  it('sends the selected diet_types + allergens (and no legacy diet_type) in the generate request', async () => {
    // The FE->BE contract line for safety-relevant allergen data: a click on a
    // diet/allergen chip must land in the outgoing SingleRecipeRequest so the
    // backend's deterministic allergen screen actually sees it. buildRequest is
    // the one link the isolated component/store tests don't cover.
    loginUser();
    mockedGenerate.mockResolvedValueOnce({
      recipe: {
        name: 'Veg Bowl',
        meal_type: 'main_course',
        meal_type_label: 'Main course',
        ingredients: [],
        steps: ['Toss'],
      },
      generation_id: null,
    });

    render(<CookNowForm />, { wrapper: createWrapper() });
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Vegan' }));
    await user.click(screen.getByRole('button', { name: 'Peanuts' }));
    await user.click(screen.getByRole('button', { name: /generate recipe/i }));

    await waitFor(() => expect(mockedGenerate).toHaveBeenCalledTimes(1));
    const call = mockedGenerate.mock.calls[0][0];
    expect(call.diet_types).toEqual(['vegan']);
    expect(call.allergens).toEqual(['peanuts']);
    // The multi-select UI no longer sends the legacy scalar — backend reconciles.
    expect(call.diet_type).toBeUndefined();
  });

  it('surfaces generation errors inline without clearing the form', async () => {
    loginUser();
    mockedGenerate.mockRejectedValueOnce(new Error('LLM down'));

    render(<CookNowForm />, { wrapper: createWrapper() });
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /generate recipe/i }));

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/llm down/i),
    );
    // No recipe card rendered on error.
    expect(screen.queryByRole('button', { name: /mark as cooked/i })).toBeNull();
  });
});

describe('CookNowForm colours on the adaptive page background', () => {
  // This form pins no surface of its own until the recipe card, so the intro
  // line and the generate-failure alert render straight onto the page
  // background — #242424 in dark mode. #555 measured 2.08:1 there and #b91c1c
  // 2.40:1. Ratios are pinned in test/contrast.test.ts; this asserts the branch.
  const rgb = (hex: string) => {
    const i = parseInt(hex.slice(1), 16);
    return `rgb(${(i >> 16) & 255}, ${(i >> 8) & 255}, ${i & 255})`;
  };

  it('dims the intro with inherit+opacity rather than a fixed grey', () => {
    loginUser();
    render(<CookNowForm />, { wrapper: createWrapper() });
    const intro = screen.getByText(/generate one recipe for what/i);
    // `inherit` cannot invert with the scheme, so it needs no per-theme branch —
    // but the opacity is a real contrast lever, so pin it.
    expect(intro.style.color).toBe('inherit');
    expect(intro.style.opacity).toBe(String(MUTED_PAGE_OPACITY));
  });

  it('flips the generate-failure alert with the OS colour scheme', async () => {
    setColorScheme('dark');
    loginUser();
    mockedGenerate.mockRejectedValueOnce(new Error("boom"));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<CookNowForm />, { wrapper: createWrapper() });
    await userEvent.setup().click(screen.getByRole('button', { name: /generate recipe/i }));
    const alert = await screen.findByRole('alert');
    expect(alert.style.color).toBe(rgb(PAGE_TEXT.error.dark));
    // The border was left at a fixed #fca5a5 while the text moved — pin that
    // they now travel together.
    expect(alert.style.border).toContain(rgb(PAGE_TEXT.error.dark));
  });
});

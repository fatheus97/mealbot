import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act, screen, waitFor, fireEvent, render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../contexts/AuthContext';
import { ReceiptScanner } from './ReceiptScanner';
import { useLocaleStore, DEFAULT_LOCALE } from '../store/useLocaleStore';
import { untranslatedEnglishIn } from '../test/i18nAssertions';
import { renderWithProviders, setMobileViewport } from '../test/test-utils';

vi.mock('../api', () => ({
  authFetch: vi.fn(),
  fetchUserProfile: vi.fn(),
  updateUserProfile: vi.fn(),
  scanReceipt: vi.fn(),
  mergeFridgeItems: vi.fn(),
}));

import { scanReceipt, mergeFridgeItems } from '../api';

const mockedScanReceipt = scanReceipt as ReturnType<typeof vi.fn>;
const mockedMergeFridge = mergeFridgeItems as ReturnType<typeof vi.fn>;

beforeEach(() => {
  localStorage.clear(); // isolate the demo-mode test's mealbot_is_demo hint
  mockedScanReceipt.mockReset();
  mockedMergeFridge.mockReset();
});

function createFile(name = 'receipt.jpg', type = 'image/jpeg'): File {
  return new File(['fake-image-data'], name, { type });
}

/** Install a navigator.mediaDevices.getUserMedia mock. Returns the spy + the
 *  per-track stop() spy so tests can assert the camera is released. */
function mockCamera(behavior: 'granted' | 'denied' | 'notfound') {
  const stop = vi.fn();
  const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
  const getUserMedia = vi.fn(() =>
    behavior === 'granted'
      ? Promise.resolve(stream)
      : Promise.reject(
          new DOMException('x', behavior === 'denied' ? 'NotAllowedError' : 'NotFoundError'),
        ),
  );
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  });
  return { getUserMedia, stop };
}

/** Stub canvas 2D + toBlob (jsdom implements neither). mode 'deferred' holds the
 *  toBlob callback so a test can fire it after a cancel/double-tap. */
function mockCanvas(mode: 'sync' | 'deferred') {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage: vi.fn(),
  } as unknown as CanvasRenderingContext2D);
  let deferred: (() => void) | null = null;
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(
    ((cb: BlobCallback) => {
      const blob = new Blob(['jpeg-bytes'], { type: 'image/jpeg' });
      if (mode === 'sync') cb(blob);
      else deferred = () => cb(blob);
    }) as HTMLCanvasElement['toBlob'],
  );
  return { flush: () => deferred?.() };
}

describe('ReceiptScanner', () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  it('leaves no untranslated English when switched to Czech, idle AND in review', async () => {
    // The REVIEW state is where almost all of this component's copy lives —
    // the table headers, the type badges, the per-item labels. None of it
    // renders until a scan resolves, so an idle-only assertion proves nothing
    // about it.
    useLocaleStore.setState({ locale: 'cs', explicit: true });
    mockedScanReceipt.mockResolvedValue({
      generation_id: 7,
      items: [
        { name: 'kuřecí prsa', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
        { name: 'sušenky', quantity_grams: 200, need_to_use: true, item_type: 'snack' as const },
      ],
    });

    const user = userEvent.setup();
    const { container } = renderWithProviders(<ReceiptScanner currentFridge={[]} />);
    expect(untranslatedEnglishIn(container)).toEqual([]);

    await user.upload(screen.getByLabelText(/vyberte obrázek/i), createFile());
    await waitFor(() => expect(screen.getByDisplayValue('kuřecí prsa')).toBeInTheDocument());
    expect(untranslatedEnglishIn(container)).toEqual([]);
  });

  it('renders file input (no scan button — upload auto-triggers)', () => {
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);
    expect(screen.getByLabelText(/select receipt image/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^scan receipt$/i })).not.toBeInTheDocument();
  });

  it('shows scanning state during scan', async () => {
    // Make scanReceipt hang indefinitely
    mockedScanReceipt.mockReturnValue(new Promise(() => {}));

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    const input = screen.getByLabelText(/select receipt image/i);
    const file = createFile();
    await user.upload(input, file);

    await waitFor(() => {
      expect(screen.getByText(/scanning receipt/i)).toBeInTheDocument();
    });
  });

  describe('food photo mode', () => {
    afterEach(() => {
      Reflect.deleteProperty(navigator, 'mediaDevices');
    });

    it('scans as a receipt by default', async () => {
      mockedScanReceipt.mockResolvedValue({ generation_id: 1, items: [] });
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);

      expect(screen.getByRole('radio', { name: /^receipt$/i })).toBeChecked();
      await user.upload(screen.getByLabelText(/select receipt image/i), createFile());

      await waitFor(() => expect(mockedScanReceipt).toHaveBeenCalledTimes(1));
      expect(mockedScanReceipt.mock.calls[0][1]).toBe('receipt');
      expect(await screen.findByText(/no food items found in receipt/i)).toBeInTheDocument();
    });

    it('sends source=food_photo, images only, with its own copy', async () => {
      let resolveScan: (v: unknown) => void = () => {};
      mockedScanReceipt.mockReturnValue(new Promise((r) => { resolveScan = r; }));
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);

      await user.click(screen.getByRole('radio', { name: /food photo/i }));
      const input = screen.getByLabelText(/select a photo of your food/i);
      expect(input).toHaveAttribute('accept', 'image/jpeg,image/png');
      await user.upload(input, createFile('food.jpg'));

      expect(await screen.findByText(/looking at your photo/i)).toBeInTheDocument();
      expect(mockedScanReceipt.mock.calls[0][1]).toBe('food_photo');

      resolveScan({ generation_id: 2, items: [] });
      expect(await screen.findByText(/no food found in the photo/i)).toBeInTheDocument();
    });

    it('asks how much is left in an opened package before it can be added', async () => {
      mockedScanReceipt.mockResolvedValue({
        generation_id: 4,
        items: [
          { name: 'cane sugar', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const, opened: true },
          { name: 'penne', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
        ],
      });
      mockedMergeFridge.mockResolvedValue([]);
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);

      await user.click(screen.getByRole('radio', { name: /food photo/i }));
      await user.upload(screen.getByLabelText(/select a photo of your food/i), createFile('food.jpg'));

      expect(await screen.findByText(/opened package \(500 g\)\. how much is left\?/i)).toBeInTheDocument();
      // The opened row starts empty (no full-bag guess); the sealed one is prefilled.
      expect(screen.getAllByDisplayValue('500')).toHaveLength(1);

      await user.click(screen.getByRole('button', { name: /add to fridge/i }));
      expect(screen.getByText(/row 1 \(cane sugar\) needs a quantity/i)).toBeInTheDocument();
      expect(mockedMergeFridge).not.toHaveBeenCalled();

      await user.click(screen.getByRole('button', { name: 'Item 1: almost nothing left' }));
      expect(screen.getByDisplayValue('25')).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Item 1: ½ left' }));
      expect(screen.getByDisplayValue('250')).toBeInTheDocument();
      // Typing an exact amount still works.
      const qty = screen.getByDisplayValue('250');
      await user.clear(qty);
      await user.type(qty, '30');

      await user.click(screen.getByRole('button', { name: /add to fridge/i }));
      await waitFor(() => expect(mockedMergeFridge).toHaveBeenCalledTimes(1));
      const merged = mockedMergeFridge.mock.calls[0][0] as Array<{ name: string; quantity_grams: number }>;
      expect(merged.map((i) => [i.name, i.quantity_grams])).toEqual([['cane sugar', 30], ['penne', 500]]);
    });

    it('a camera capture in food photo mode is scanned as a food photo', async () => {
      mockCamera('granted');
      mockCanvas('sync');
      mockedScanReceipt.mockResolvedValue({ generation_id: 3, items: [] });
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);

      await user.click(screen.getByRole('radio', { name: /food photo/i }));
      await user.click(screen.getByRole('button', { name: /take photo/i }));
      fireEvent.loadedMetadata(await screen.findByLabelText(/camera preview/i));
      await user.click(screen.getByRole('button', { name: /^capture$/i }));

      await waitFor(() => expect(mockedScanReceipt).toHaveBeenCalledTimes(1));
      expect(mockedScanReceipt.mock.calls[0][1]).toBe('food_photo');
    });
  });

  it('shows review table after successful scan with new items', async () => {
    mockedScanReceipt.mockResolvedValue({
      generation_id: 7,
      items: [
        { name: 'chicken breast', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
        { name: 'rice', quantity_grams: 1000, need_to_use: false, item_type: 'ingredient' as const },
      ],
    });

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    const input = screen.getByLabelText(/select receipt image/i);
    await user.upload(input, createFile());

    await waitFor(() => {
      expect(screen.getByDisplayValue('chicken breast')).toBeInTheDocument();
      expect(screen.getByDisplayValue('rice')).toBeInTheDocument();
    });

    // New items should show "(new)"
    expect(screen.getByText(/500g \(new\)/)).toBeInTheDocument();
    expect(screen.getByText(/1000g \(new\)/)).toBeInTheDocument();

    // Should show Add to Fridge and Cancel buttons
    expect(screen.getByRole('button', { name: /add to fridge/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
  });

  it.each([
    ['desktop table', false],
    ['mobile cards', true],
  ])('explains the estimated expiry dates once, in review only (%s)', async (_layout, mobile) => {
    // ONE hint on the intro line, not one per "Expires" label: on mobile that
    // label repeats on every card.
    setMobileViewport(mobile);
    mockedScanReceipt.mockResolvedValue({
      generation_id: 7,
      items: [
        { name: 'chicken breast', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
        { name: 'rice', quantity_grams: 1000, need_to_use: false, item_type: 'ingredient' as const },
      ],
    });

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);
    expect(screen.queryByRole('button', { name: 'About expiry dates' })).not.toBeInTheDocument();

    await user.upload(screen.getByLabelText(/select receipt image/i), createFile());
    await waitFor(() => expect(screen.getByDisplayValue('rice')).toBeInTheDocument());

    const hints = screen.getAllByRole('button', { name: 'About expiry dates' });
    expect(hints).toHaveLength(1);
    await user.click(hints[0]);
    expect(screen.getByRole('tooltip')).toHaveTextContent(/not read from the package/i);
  });

  it('renders review items as cards (not a table) on mobile, edits still flow', async () => {
    setMobileViewport(true);
    mockedScanReceipt.mockResolvedValue({
      generation_id: 7,
      items: [
        { name: 'chicken breast', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
        { name: 'rice', quantity_grams: 1000, need_to_use: true, item_type: 'ingredient' as const },
      ],
    });

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);
    await user.upload(screen.getByLabelText(/select receipt image/i), createFile());
    await waitFor(() =>
      expect(screen.getByDisplayValue('chicken breast')).toBeInTheDocument(),
    );

    // Mobile branch: the 7-col editable table becomes labelled cards.
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByLabelText(/item 1 name/i)).toBeInTheDocument();
    const qty = screen.getByLabelText(/item 1 quantity/i);
    // Edits still flow through the same updateReviewItem handler + qty validation.
    await user.clear(qty);
    await user.type(qty, '250');
    expect(qty).toHaveValue('250');
    // Result label recomputes from the edited value (derive() is shared with the
    // table renderer), and the confirm control is preserved.
    expect(screen.getByText(/250g \(new\)/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add to fridge/i })).toBeInTheDocument();
  });

  it('shows delta for existing fridge items', async () => {
    mockedScanReceipt.mockResolvedValue({
      generation_id: 7,
      items: [
        { name: 'chicken breast', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
      ],
    });

    const currentFridge = [
      { name: 'chicken breast', quantity_grams: 200, need_to_use: false },
    ];

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={currentFridge} />);

    const input = screen.getByLabelText(/select receipt image/i);
    await user.upload(input, createFile());

    await waitFor(() => {
      // Should show "+500 → 700g" for existing item
      expect(screen.getByText(/\+500 → 700g/)).toBeInTheDocument();
    });
  });

  it('calls merge on confirm and shows success', async () => {
    mockedScanReceipt.mockResolvedValue({
      generation_id: 7,
      items: [
        { name: 'olive oil', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
      ],
    });
    mockedMergeFridge.mockResolvedValue([
      { name: 'olive oil', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
    ]);

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    const input = screen.getByLabelText(/select receipt image/i);
    await user.upload(input, createFile());

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add to fridge/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /add to fridge/i }));

    await waitFor(() => {
      expect(mockedMergeFridge).toHaveBeenCalledWith([
        { name: 'olive oil', quantity_grams: 500, need_to_use: false, expiration_date: null },
      ], [7], expect.anything());
      expect(screen.getByText(/items added to fridge/i)).toBeInTheDocument();
    });
  });

  it('threads a null generation_id (guarded-commit degrade) through to merge', async () => {
    // Server returns generation_id: null when the scan telemetry write is
    // skipped. The client must send no id so api.ts omits the query param.
    mockedScanReceipt.mockResolvedValue({
      generation_id: null,
      items: [
        { name: 'olive oil', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
      ],
    });
    mockedMergeFridge.mockResolvedValue([]);

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);
    await user.upload(screen.getByLabelText(/select receipt image/i), createFile());
    await waitFor(() => screen.getByRole('button', { name: /add to fridge/i }));
    await user.click(screen.getByRole('button', { name: /add to fridge/i }));

    await waitFor(() => {
      expect(mockedMergeFridge).toHaveBeenCalledWith([
        { name: 'olive oil', quantity_grams: 500, need_to_use: false, expiration_date: null },
      ], [], expect.anything());
    });
  });

  it('with onSave, Confirm saves through it instead of merging, with no ids when a scan is unlinked', async () => {
    const row = (name: string) => ({ name, quantity_grams: 100, need_to_use: false, item_type: 'ingredient' as const });
    mockedScanReceipt
      .mockResolvedValueOnce({ generation_id: 3, items: [row('Eggs')] })
      .mockResolvedValueOnce({ generation_id: null, items: [row('Milk')] });
    let finish: () => void = () => {};
    const onSave = vi.fn(() => new Promise<void>((r) => { finish = () => r(); }));

    const user = userEvent.setup();
    renderWithProviders(
      <ReceiptScanner currentFridge={[]} onSave={onSave} saveLabel={(n) => `Replace with ${n}`} />,
    );
    await user.upload(screen.getByLabelText(/select receipt image/i), createFile());
    await screen.findByDisplayValue('Eggs');
    await user.upload(screen.getByLabelText(/select receipt image/i), createFile());
    await screen.findByDisplayValue('Milk');
    await user.click(screen.getByRole('button', { name: 'Replace with 2' }));

    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0]).toEqual([
      [
        { name: 'Eggs', quantity_grams: 100, need_to_use: false, expiration_date: null },
        { name: 'Milk', quantity_grams: 100, need_to_use: false, expiration_date: null },
      ],
      [],
    ]);
    // In flight, a second Confirm must not go out (the parent may be reloading
    // the token it needs).
    expect(screen.getByRole('button', { name: 'Replace with 2' })).toBeDisabled();
    await act(async () => finish());
    expect(mockedMergeFridge).not.toHaveBeenCalled();
  });

  it('with onSave, the idle state offers Empty the fridge, which saves an empty list', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('Refused, reloaded.'));
    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} onSave={onSave} />);

    await user.click(screen.getByRole('button', { name: 'Empty the fridge' }));
    expect(onSave).toHaveBeenCalledWith([], []);
    // A refusal shows, and the pickers stay for the next try.
    expect(await screen.findByText('Refused, reloaded.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Empty the fridge' })).toBeEnabled();
  });

  it('without onSave there is no Empty the fridge button', () => {
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);
    expect(screen.queryByRole('button', { name: 'Empty the fridge' })).not.toBeInTheDocument();
  });

  it('demo scan merges with a null generation_id (no real /scan call)', async () => {
    localStorage.setItem('mealbot_is_demo', 'true'); // isDemo → demo branch
    mockedMergeFridge.mockResolvedValue([]);

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    await user.click(screen.getByRole('button', { name: /scan demo receipt/i }));
    // Demo scan populates the review table via a ~1.2s timer, no API call.
    await waitFor(
      () => screen.getByRole('button', { name: /add to fridge/i }),
      { timeout: 3000 },
    );
    await user.click(screen.getByRole('button', { name: /add to fridge/i }));

    await waitFor(() => {
      expect(mockedScanReceipt).not.toHaveBeenCalled();
      expect(mockedMergeFridge).toHaveBeenCalledTimes(1);
      // Demo has no generation, so merge must receive no id (not a stale one).
      expect(mockedMergeFridge.mock.calls[0][1]).toEqual([]);
    });
  });

  it('shows error on scan failure', async () => {
    mockedScanReceipt.mockRejectedValue(new Error('Receipt scan failed: 502'));

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    const input = screen.getByLabelText(/select receipt image/i);
    await user.upload(input, createFile());

    await waitFor(() => {
      expect(screen.getByText(/receipt scan failed/i)).toBeInTheDocument();
    });
  });

  it('cancel returns to idle state', async () => {
    mockedScanReceipt.mockResolvedValue({
      generation_id: 7,
      items: [
        { name: 'rice', quantity_grams: 1000, need_to_use: false, item_type: 'ingredient' as const },
      ],
    });

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    const input = screen.getByLabelText(/select receipt image/i);
    await user.upload(input, createFile());

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /cancel/i }));

    // Should be back to idle state — file input visible, no review rows
    expect(screen.getByLabelText(/select receipt image/i)).toBeInTheDocument();
    expect(screen.queryByDisplayValue('rice')).not.toBeInTheDocument();
  });

  it('clears the qty cell on backspace without auto-zero', async () => {
    mockedScanReceipt.mockResolvedValue({
      generation_id: 7,
      items: [
        { name: 'rice', quantity_grams: 1000, need_to_use: false, item_type: 'ingredient' as const },
      ],
    });

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    await user.upload(screen.getByLabelText(/select receipt image/i), createFile());

    const qty = (await screen.findByDisplayValue('1000')) as HTMLInputElement;
    await user.clear(qty);

    expect(qty.value).toBe('');
  });

  it('blocks confirm when a row has an invalid qty', async () => {
    mockedScanReceipt.mockResolvedValue({
      generation_id: 7,
      items: [
        { name: 'rice', quantity_grams: 1000, need_to_use: false, item_type: 'ingredient' as const },
      ],
    });

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    await user.upload(screen.getByLabelText(/select receipt image/i), createFile());

    const qty = await screen.findByDisplayValue('1000');
    await user.clear(qty);
    await user.click(screen.getByRole('button', { name: /add to fridge/i }));

    expect(screen.getByText(/needs a quantity greater than 0/i)).toBeInTheDocument();
    expect(mockedMergeFridge).not.toHaveBeenCalled();
  });

  it('forwards decimal qty values as floats on confirm', async () => {
    mockedScanReceipt.mockResolvedValue({
      generation_id: 7,
      items: [
        { name: 'yeast', quantity_grams: 100, need_to_use: false, item_type: 'ingredient' as const },
      ],
    });
    mockedMergeFridge.mockResolvedValue([
      { name: 'yeast', quantity_grams: 12.5, need_to_use: false, item_type: 'ingredient' as const },
    ]);

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    await user.upload(screen.getByLabelText(/select receipt image/i), createFile());

    const qty = await screen.findByDisplayValue('100');
    await user.clear(qty);
    await user.type(qty, '12.5');
    await user.click(screen.getByRole('button', { name: /add to fridge/i }));

    await waitFor(() => {
      expect(mockedMergeFridge).toHaveBeenCalledWith([
        { name: 'yeast', quantity_grams: 12.5, need_to_use: false, expiration_date: null },
      ], [7], expect.anything());
    });
  });

  it('allows removing items from review', async () => {
    mockedScanReceipt.mockResolvedValue({
      generation_id: 7,
      items: [
        { name: 'chicken', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
        { name: 'rice', quantity_grams: 1000, need_to_use: false, item_type: 'ingredient' as const },
      ],
    });

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    const input = screen.getByLabelText(/select receipt image/i);
    await user.upload(input, createFile());

    await waitFor(() => {
      expect(screen.getByDisplayValue('chicken')).toBeInTheDocument();
    });

    // Remove the first item
    const removeButtons = screen.getAllByRole('button', { name: /remove/i });
    await user.click(removeButtons[0]);

    expect(screen.queryByDisplayValue('chicken')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('rice')).toBeInTheDocument();
  });

  describe('several scans in one list', () => {
    const item = (name: string, expiration_date: string | null = null) => ({
      name, quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const, expiration_date,
    });

    afterEach(() => {
      Reflect.deleteProperty(navigator, 'mediaDevices');
    });

    /** Scan once (rice), so the review list is on screen. */
    async function firstScan(user: ReturnType<typeof userEvent.setup>) {
      await user.upload(screen.getByLabelText(/select receipt image/i), createFile());
      await screen.findByDisplayValue('rice');
    }

    it('appends a second scan and sends every scan id to merge', async () => {
      mockedScanReceipt
        .mockResolvedValueOnce({ generation_id: 7, items: [item('rice')] })
        .mockResolvedValueOnce({ generation_id: 8, items: [item('milk')] });
      mockedMergeFridge.mockResolvedValue([]);
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await firstScan(user);

      expect(screen.getByText('Add another photo or receipt')).toBeInTheDocument();
      // The source can change between scans.
      await user.click(screen.getByRole('radio', { name: /food photo/i }));
      await user.upload(screen.getByLabelText(/select a photo of your food/i), createFile('food.jpg'));
      await screen.findByDisplayValue('milk');
      expect(screen.getByDisplayValue('rice')).toBeInTheDocument();
      expect(mockedScanReceipt.mock.calls[1][1]).toBe('food_photo');

      await user.click(screen.getByRole('button', { name: /add to fridge/i }));
      await waitFor(() => expect(mockedMergeFridge).toHaveBeenCalledTimes(1));
      const [items, ids, copy] = mockedMergeFridge.mock.calls[0];
      expect((items as Array<{ name: string }>).map((i) => i.name)).toEqual(['rice', 'milk']);
      expect(ids).toEqual([7, 8]);
      expect(copy).toEqual({
        rateLimited: 'Too many scans at once. Wait a minute and try again.',
        fallback: 'Failed to merge items.',
        connectionLost:
          "The connection dropped, so we can't tell whether the items were added. Check your fridge list before adding them again.",
      });
    });

    it('a scan without a telemetry id still appends, and then the save sends no ids', async () => {
      // The server compares the scans it can resolve with the whole list, so
      // sending [7] here would record a correction nobody made.
      mockedScanReceipt
        .mockResolvedValueOnce({ generation_id: 7, items: [item('rice')] })
        .mockResolvedValueOnce({ generation_id: null, items: [item('milk')] });
      mockedMergeFridge.mockResolvedValue([]);
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await firstScan(user);
      await user.upload(screen.getByLabelText(/select receipt image/i), createFile());
      await screen.findByDisplayValue('milk');

      await user.click(screen.getByRole('button', { name: /add to fridge/i }));
      await waitFor(() => expect(mockedMergeFridge).toHaveBeenCalledTimes(1));
      expect(mockedMergeFridge.mock.calls[0][1]).toEqual([]);
    });

    it('flags a name found in another scan, never a repeat within one scan', async () => {
      mockedScanReceipt
        .mockResolvedValueOnce({ generation_id: 7, items: [item('rice'), item('Milk'), item(' milk ')] })
        .mockResolvedValueOnce({ generation_id: 8, items: [item('MILK'), item('butter')] });
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await firstScan(user);
      expect(screen.queryByText(/also in another scan/i)).not.toBeInTheDocument();

      await user.upload(screen.getByLabelText(/select receipt image/i), createFile());
      await screen.findByDisplayValue('butter');
      // The three milk rows (two from scan 1, one from scan 2); not rice or butter.
      expect(screen.getAllByText("Also in another scan. Remove one if it's the same food.")).toHaveLength(3);

      // Removing the second scan's milk clears the flag on the first scan's rows.
      await user.click(screen.getAllByRole('button', { name: /remove/i })[3]);
      expect(screen.queryByText(/also in another scan/i)).not.toBeInTheDocument();
    });

    it('flags a row whose date has passed', async () => {
      mockedScanReceipt.mockResolvedValueOnce({
        generation_id: 7,
        items: [item('rice', '2999-01-01'), item('old yoghurt', '2001-01-01'), item('salt')],
      });
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await firstScan(user);

      expect(screen.getAllByText('Past its date')).toHaveLength(1);
      // Moving the date into the future clears it.
      fireEvent.change(screen.getByDisplayValue('2001-01-01'), { target: { value: '2999-02-02' } });
      expect(screen.queryByText('Past its date')).not.toBeInTheDocument();
    });

    it('keeps the rows when a later scan fails, and shows why', async () => {
      mockedScanReceipt
        .mockResolvedValueOnce({ generation_id: 7, items: [item('rice')] })
        .mockRejectedValueOnce(new Error('That photo could not be read.'));
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await firstScan(user);
      await user.upload(screen.getByLabelText(/select receipt image/i), createFile());

      expect(await screen.findByText('That photo could not be read.')).toBeInTheDocument();
      expect(screen.getByRole('alert')).toHaveTextContent('That photo could not be read.');
      expect(screen.getByDisplayValue('rice')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /add to fridge/i })).toBeEnabled();
    });

    it('keeps the rows when the save fails, and shows why', async () => {
      mockedScanReceipt.mockResolvedValueOnce({ generation_id: 7, items: [item('rice')] });
      mockedMergeFridge.mockRejectedValueOnce(new Error('The server said no.'));
      const user = userEvent.setup();
      const { queryClient } = renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
      await firstScan(user);
      await user.click(screen.getByRole('button', { name: /add to fridge/i }));

      expect(await screen.findByText('The server said no.')).toBeInTheDocument();
      expect(screen.getByRole('alert')).toHaveTextContent('The server said no.');
      // A failed merge may still have landed (dropped connection): refetch the truth.
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['fridge'] });
      expect(screen.getByDisplayValue('rice')).toBeInTheDocument();
      // A retry sends the same list again.
      mockedMergeFridge.mockResolvedValueOnce([]);
      await user.click(screen.getByRole('button', { name: /add to fridge/i }));
      await waitFor(() => expect(mockedMergeFridge).toHaveBeenCalledTimes(2));
      expect(mockedMergeFridge.mock.calls[1][1]).toEqual([7]);
    });

    it.each([
      ['the rate limit', 'Too many scans at once. Wait a minute and try again.'],
      ['the usage cap', 'You have used your €2.00 of AI generation for this month.'],
    ])('shows %s message from the scan call, with translated copy passed in', async (_case, message) => {
      // scanReceipt picks the sentence (api.test.ts covers the 429 split); the
      // scanner must hand it translated copy and show what it throws.
      mockedScanReceipt
        .mockResolvedValueOnce({ generation_id: 7, items: [item('rice')] })
        .mockImplementationOnce((_f: File, _s: string, copy: { rateLimited: string }) =>
          Promise.reject(new Error(message.startsWith('Too many') ? copy.rateLimited : message)));
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await firstScan(user);
      expect(mockedScanReceipt.mock.calls[0][2]).toEqual({
        rateLimited: 'Too many scans at once. Wait a minute and try again.',
        fallback: 'Failed to scan receipt.',
      });
      await user.upload(screen.getByLabelText(/select receipt image/i), createFile());

      expect(await screen.findByText(message)).toBeInTheDocument();
      expect(screen.getByDisplayValue('rice')).toBeInTheDocument();
    });

    it('passes Czech copy to the scan call when the UI is Czech', async () => {
      useLocaleStore.setState({ locale: 'cs', explicit: true });
      mockedScanReceipt.mockResolvedValueOnce({ generation_id: 7, items: [item('rýže')] });
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await user.upload(screen.getByLabelText(/vyberte obrázek/i), createFile());
      await screen.findByDisplayValue('rýže');
      expect(mockedScanReceipt.mock.calls[0][2]).toEqual({
        rateLimited: 'Příliš mnoho skenů najednou. Chvíli počkejte a zkuste to znovu.',
        fallback: 'Účtenku se nepodařilo naskenovat.',
      });
    });

    it('keeps the table up and disables Add and Cancel while a scan runs', async () => {
      let resolveScan: (v: unknown) => void = () => {};
      mockedScanReceipt
        .mockResolvedValueOnce({ generation_id: 7, items: [item('rice')] })
        .mockReturnValueOnce(new Promise((r) => { resolveScan = r; }));
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await firstScan(user);
      await user.upload(screen.getByLabelText(/select receipt image/i), createFile());

      expect(await screen.findByText(/scanning receipt/i)).toBeInTheDocument();
      expect(screen.getByRole('status')).toHaveTextContent(/scanning receipt/i);
      expect(screen.getByDisplayValue('rice')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /add to fridge/i })).toBeDisabled();
      // Cancel would let the scan land after the list is gone and reopen it.
      expect(screen.getByRole('button', { name: /^cancel$/i })).toBeDisabled();
      expect(screen.getByLabelText(/select receipt image/i)).toBeDisabled();

      resolveScan({ generation_id: 8, items: [item('milk')] });
      await screen.findByDisplayValue('milk');
      expect(screen.getByRole('button', { name: /add to fridge/i })).toBeEnabled();
    });

    it('opens the camera from the list: Cancel goes back to it, a capture appends', async () => {
      mockCamera('granted');
      mockCanvas('sync');
      mockedScanReceipt
        .mockResolvedValueOnce({ generation_id: 7, items: [item('rice')] })
        .mockResolvedValueOnce({ generation_id: 8, items: [item('milk')] });
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await firstScan(user);

      await user.click(screen.getByRole('button', { name: /take photo/i }));
      await screen.findByLabelText(/camera preview/i);
      await user.click(screen.getByRole('button', { name: /^cancel$/i }));
      expect(screen.getByDisplayValue('rice')).toBeInTheDocument();

      await user.click(screen.getByRole('button', { name: /take photo/i }));
      fireEvent.loadedMetadata(await screen.findByLabelText(/camera preview/i));
      await user.click(screen.getByRole('button', { name: /^capture$/i }));
      await screen.findByDisplayValue('milk');
      expect(screen.getByDisplayValue('rice')).toBeInTheDocument();
    });

    it('blocks Add and Cancel while the camera is acquired; after a save nothing holds it', async () => {
      let resolveStream!: (s: MediaStream) => void;
      const stop = vi.fn();
      const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
      const getUserMedia = vi.fn(() => new Promise<MediaStream>((r) => { resolveStream = r; }));
      Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });
      mockedScanReceipt.mockResolvedValueOnce({ generation_id: 7, items: [item('rice')] });
      mockedMergeFridge.mockResolvedValue([]);
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await firstScan(user);

      await user.click(screen.getByRole('button', { name: /take photo/i })); // permission prompt open
      expect(screen.getByRole('button', { name: /add to fridge/i })).toBeDisabled();
      expect(screen.getByRole('button', { name: /^cancel$/i })).toBeDisabled();

      resolveStream(stream);
      await screen.findByLabelText(/camera preview/i);
      await user.click(screen.getByRole('button', { name: /^cancel$/i })); // back to the list
      await user.click(screen.getByRole('button', { name: /add to fridge/i }));
      expect(await screen.findByText(/items added to fridge/i)).toBeInTheDocument();
      expect(stop).toHaveBeenCalled();
      // No stream left behind: Take photo asks for a fresh camera.
      await user.click(screen.getByRole('button', { name: /take photo/i }));
      expect(getUserMedia).toHaveBeenCalledTimes(2);
    });

    it.each([
      ['receipt', /select receipt image/i, 'No food items found in receipt.'],
      ['food photo', /select a photo of your food/i, 'No food found in the photo.'],
    ])('an added %s scan that finds nothing says so and keeps the list', async (kind, label, message) => {
      mockedScanReceipt
        .mockResolvedValueOnce({ generation_id: 7, items: [item('rice')] })
        .mockResolvedValueOnce({ generation_id: 8, items: [] });
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await firstScan(user);
      if (kind === 'food photo') await user.click(screen.getByRole('radio', { name: /food photo/i }));
      await user.upload(screen.getByLabelText(label), createFile());

      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(message));
      expect(screen.queryByRole('alert')).not.toBeInTheDocument(); // information, not an error
      expect(screen.getByDisplayValue('rice')).toBeInTheDocument();
    });

    it('an edit made before a finished scan renders keeps the new rows', async () => {
      let resolveScan: (v: unknown) => void = () => {};
      mockedScanReceipt
        .mockResolvedValueOnce({ generation_id: 7, items: [item('rice')] })
        .mockReturnValueOnce(new Promise((r) => { resolveScan = r; }));
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await firstScan(user);
      await user.upload(screen.getByLabelText(/select receipt image/i), createFile());
      await screen.findByText(/scanning receipt/i);

      // The scan finishes and queues its rows (microtasks only, so React has
      // not rendered them yet); then an edit arrives from the list on screen.
      const rice = screen.getByDisplayValue('rice');
      resolveScan({ generation_id: 8, items: [item('milk')] });
      for (let i = 0; i < 50; i++) await Promise.resolve();
      fireEvent.change(rice, { target: { value: 'brown rice' } });

      expect(await screen.findByDisplayValue('milk')).toBeInTheDocument();
      expect(screen.getByDisplayValue('brown rice')).toBeInTheDocument();
    });

    it('a camera denied from the list keeps the rows', async () => {
      mockCamera('denied');
      mockedScanReceipt.mockResolvedValueOnce({ generation_id: 7, items: [item('rice')] });
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await firstScan(user);

      await user.click(screen.getByRole('button', { name: /take photo/i }));
      expect(await screen.findByText(/permission denied/i)).toBeInTheDocument();
      expect(screen.getByDisplayValue('rice')).toBeInTheDocument();
    });
  });

  describe('camera capture', () => {
    afterEach(() => {
      Reflect.deleteProperty(navigator, 'mediaDevices');
    });

    it('hides "Take photo" when getUserMedia is unavailable', () => {
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      expect(screen.queryByRole('button', { name: /take photo/i })).not.toBeInTheDocument();
      // File upload is still the available path.
      expect(screen.getByLabelText(/select receipt image/i)).toBeInTheDocument();
    });

    it('opens a live camera preview when permission is granted', async () => {
      const { getUserMedia } = mockCamera('granted');
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);

      await user.click(screen.getByRole('button', { name: /take photo/i }));

      const video = await screen.findByLabelText(/camera preview/i);
      expect(getUserMedia).toHaveBeenCalledWith({ video: { facingMode: 'environment' } });
      expect(screen.getByRole('button', { name: /^cancel$/i })).toBeInTheDocument();
      // Capture is gated until the video reports a frame (avoids a black capture).
      expect(screen.getByRole('button', { name: /starting camera/i })).toBeDisabled();
      fireEvent.loadedMetadata(video);
      expect(screen.getByRole('button', { name: /^capture$/i })).toBeEnabled();
    });

    it('disables the file input while the camera is being acquired', async () => {
      // getUserMedia stays pending so the "opening" window is observable.
      const getUserMedia = vi.fn(() => new Promise<MediaStream>(() => {}));
      Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: { getUserMedia },
      });
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);

      await user.click(screen.getByRole('button', { name: /take photo/i }));
      // The file input can't race the in-flight getUserMedia (clobber/leak fix).
      expect(screen.getByLabelText(/select receipt image/i)).toBeDisabled();
      expect(screen.getByRole('button', { name: /opening camera/i })).toBeDisabled();
    });

    it('opens under StrictMode (mountedRef reset on the simulated remount)', async () => {
      // Regression guard: StrictMode runs effect setup→cleanup→setup; if the
      // mount effect doesn't reset mountedRef=true, openCamera treats the live
      // component as unmounted and the preview never appears.
      mockCamera('granted');
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
      });
      const user = userEvent.setup();
      render(
        <StrictMode>
          <QueryClientProvider client={queryClient}>
            <AuthProvider>
              <ReceiptScanner currentFridge={[]} />
            </AuthProvider>
          </QueryClientProvider>
        </StrictMode>,
      );

      await user.click(screen.getByRole('button', { name: /take photo/i }));
      await waitFor(() =>
        expect(screen.getByLabelText(/camera preview/i)).toBeInTheDocument(),
      );
    });

    it('falls back to file upload with a message when permission is denied', async () => {
      mockCamera('denied');
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);

      await user.click(screen.getByRole('button', { name: /take photo/i }));

      await waitFor(() =>
        expect(screen.getByText(/permission denied/i)).toBeInTheDocument(),
      );
      // Fallback preserved: no preview, file input still present.
      expect(screen.queryByLabelText(/camera preview/i)).not.toBeInTheDocument();
      expect(screen.getByLabelText(/select receipt image/i)).toBeInTheDocument();
    });

    it('can retry the camera after a denial (opens from the error state)', async () => {
      const stop = vi.fn();
      const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
      const getUserMedia = vi
        .fn()
        .mockRejectedValueOnce(new DOMException('x', 'NotAllowedError'))
        .mockResolvedValueOnce(stream);
      Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: { getUserMedia },
      });

      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);

      // 1st attempt denied → error state (button still shown).
      await user.click(screen.getByRole('button', { name: /take photo/i }));
      await waitFor(() =>
        expect(screen.getByText(/permission denied/i)).toBeInTheDocument(),
      );
      // 2nd attempt granted → the post-await openable-state check must NOT reject
      // the "error" state, so the preview opens.
      await user.click(screen.getByRole('button', { name: /take photo/i }));
      await waitFor(() =>
        expect(screen.getByLabelText(/camera preview/i)).toBeInTheDocument(),
      );
      expect(getUserMedia).toHaveBeenCalledTimes(2);
    });

    it('releases the camera (stops tracks) on cancel', async () => {
      const { stop } = mockCamera('granted');
      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);

      await user.click(screen.getByRole('button', { name: /take photo/i }));
      await waitFor(() => screen.getByRole('button', { name: /^cancel$/i }));
      await user.click(screen.getByRole('button', { name: /^cancel$/i }));

      expect(stop).toHaveBeenCalled();
      // Back to idle — file input visible again.
      expect(screen.getByLabelText(/select receipt image/i)).toBeInTheDocument();
      expect(screen.queryByLabelText(/camera preview/i)).not.toBeInTheDocument();
    });

    it('does not double-open on rapid re-clicks (no stranded stream)', async () => {
      // getUserMedia stays pending so both clicks land while "opening".
      let resolveStream!: (s: MediaStream) => void;
      const stop = vi.fn();
      const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
      const getUserMedia = vi.fn(
        () => new Promise<MediaStream>((r) => { resolveStream = r; }),
      );
      Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: { getUserMedia },
      });

      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      const btn = screen.getByRole('button', { name: /take photo/i });
      await user.click(btn); // opening (getUserMedia pending)
      await user.click(btn); // guarded — must NOT fire a second getUserMedia
      expect(getUserMedia).toHaveBeenCalledTimes(1);

      resolveStream(stream);
      await waitFor(() =>
        expect(screen.getByLabelText(/camera preview/i)).toBeInTheDocument(),
      );
    });

    it('captures a photo and scans it (canvas → JPEG → handleScan)', async () => {
      mockCamera('granted');
      mockCanvas('sync');
      mockedScanReceipt.mockResolvedValue({ generation_id: 3, items: [] });

      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await user.click(screen.getByRole('button', { name: /take photo/i }));
      fireEvent.loadedMetadata(await screen.findByLabelText(/camera preview/i));
      await user.click(screen.getByRole('button', { name: /^capture$/i }));

      await waitFor(() => expect(mockedScanReceipt).toHaveBeenCalledTimes(1));
      const file = mockedScanReceipt.mock.calls[0][0] as File;
      expect(file.name).toBe('receipt.jpg');
      expect(file.type).toBe('image/jpeg');
    });

    it('drops the capture (no scan) if the user cancels during the encode', async () => {
      mockCamera('granted');
      const canvas = mockCanvas('deferred');

      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await user.click(screen.getByRole('button', { name: /take photo/i }));
      fireEvent.loadedMetadata(await screen.findByLabelText(/camera preview/i));
      await user.click(screen.getByRole('button', { name: /^capture$/i })); // toBlob pending
      await user.click(screen.getByRole('button', { name: /^cancel$/i })); // → idle
      canvas.flush(); // toBlob callback fires after the cancel

      expect(mockedScanReceipt).not.toHaveBeenCalled();
      expect(screen.getByLabelText(/select receipt image/i)).toBeInTheDocument();
    });

    it('does not double-scan on a rapid double-tap of Capture', async () => {
      mockCamera('granted');
      const canvas = mockCanvas('deferred');
      mockedScanReceipt.mockResolvedValue({ generation_id: 3, items: [] });

      const user = userEvent.setup();
      renderWithProviders(<ReceiptScanner currentFridge={[]} />);
      await user.click(screen.getByRole('button', { name: /take photo/i }));
      fireEvent.loadedMetadata(await screen.findByLabelText(/camera preview/i));
      const capture = screen.getByRole('button', { name: /^capture$/i });
      await user.click(capture); // capturing → toBlob pending
      await user.click(capture); // guarded — no second encode
      canvas.flush();

      await waitFor(() => expect(mockedScanReceipt).toHaveBeenCalledTimes(1));
    });
  });
});

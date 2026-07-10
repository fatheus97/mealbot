import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { screen, waitFor, fireEvent, render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from '../contexts/AuthContext';
import { ReceiptScanner } from './ReceiptScanner';
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

describe('ReceiptScanner', () => {
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
      ], 7);
      expect(screen.getByText(/items added to fridge/i)).toBeInTheDocument();
    });
  });

  it('threads a null generation_id (guarded-commit degrade) through to merge', async () => {
    // Server returns generation_id: null when the scan telemetry write is
    // skipped. The client must forward null so api.ts omits the query param.
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
      ], null);
    });
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
      // Demo has no generation, so merge must receive null (not a stale id).
      expect(mockedMergeFridge.mock.calls[0][1]).toBeNull();
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
      ], 7);
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
  });
});

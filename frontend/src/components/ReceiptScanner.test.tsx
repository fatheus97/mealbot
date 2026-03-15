import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ReceiptScanner } from './ReceiptScanner';
import { renderWithProviders } from '../test/test-utils';

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
  mockedScanReceipt.mockReset();
  mockedMergeFridge.mockReset();
});

function createFile(name = 'receipt.jpg', type = 'image/jpeg'): File {
  return new File(['fake-image-data'], name, { type });
}

describe('ReceiptScanner', () => {
  it('renders file input and scan button', () => {
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);
    expect(screen.getByLabelText(/select receipt image/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /scan receipt/i })).toBeInTheDocument();
  });

  it('shows scanning state during scan', async () => {
    // Make scanReceipt hang indefinitely
    mockedScanReceipt.mockReturnValue(new Promise(() => {}));

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    const input = screen.getByLabelText(/select receipt image/i);
    const file = createFile();
    await user.upload(input, file);
    await user.click(screen.getByRole('button', { name: /scan receipt/i }));

    await waitFor(() => {
      expect(screen.getByText(/scanning receipt/i)).toBeInTheDocument();
    });
  });

  it('shows review table after successful scan with new items', async () => {
    mockedScanReceipt.mockResolvedValue([
      { name: 'chicken breast', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
      { name: 'rice', quantity_grams: 1000, need_to_use: false, item_type: 'ingredient' as const },
    ]);

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    const input = screen.getByLabelText(/select receipt image/i);
    await user.upload(input, createFile());
    await user.click(screen.getByRole('button', { name: /scan receipt/i }));

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

  it('shows delta for existing fridge items', async () => {
    mockedScanReceipt.mockResolvedValue([
      { name: 'chicken breast', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
    ]);

    const currentFridge = [
      { name: 'chicken breast', quantity_grams: 200, need_to_use: false },
    ];

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={currentFridge} />);

    const input = screen.getByLabelText(/select receipt image/i);
    await user.upload(input, createFile());
    await user.click(screen.getByRole('button', { name: /scan receipt/i }));

    await waitFor(() => {
      // Should show "+500 → 700g" for existing item
      expect(screen.getByText(/\+500 → 700g/)).toBeInTheDocument();
    });
  });

  it('calls merge on confirm and shows success', async () => {
    mockedScanReceipt.mockResolvedValue([
      { name: 'olive oil', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
    ]);
    mockedMergeFridge.mockResolvedValue([
      { name: 'olive oil', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
    ]);

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    const input = screen.getByLabelText(/select receipt image/i);
    await user.upload(input, createFile());
    await user.click(screen.getByRole('button', { name: /scan receipt/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add to fridge/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /add to fridge/i }));

    await waitFor(() => {
      expect(mockedMergeFridge).toHaveBeenCalledWith([
        { name: 'olive oil', quantity_grams: 500, need_to_use: false, expiration_date: null },
      ]);
      expect(screen.getByText(/items added to fridge/i)).toBeInTheDocument();
    });
  });

  it('shows error on scan failure', async () => {
    mockedScanReceipt.mockRejectedValue(new Error('Receipt scan failed: 502'));

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    const input = screen.getByLabelText(/select receipt image/i);
    await user.upload(input, createFile());
    await user.click(screen.getByRole('button', { name: /scan receipt/i }));

    await waitFor(() => {
      expect(screen.getByText(/receipt scan failed/i)).toBeInTheDocument();
    });
  });

  it('cancel returns to idle state', async () => {
    mockedScanReceipt.mockResolvedValue([
      { name: 'rice', quantity_grams: 1000, need_to_use: false, item_type: 'ingredient' as const },
    ]);

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    const input = screen.getByLabelText(/select receipt image/i);
    await user.upload(input, createFile());
    await user.click(screen.getByRole('button', { name: /scan receipt/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: /cancel/i }));

    // Should be back to idle state
    expect(screen.getByRole('button', { name: /scan receipt/i })).toBeInTheDocument();
    expect(screen.queryByDisplayValue('rice')).not.toBeInTheDocument();
  });

  it('allows removing items from review', async () => {
    mockedScanReceipt.mockResolvedValue([
      { name: 'chicken', quantity_grams: 500, need_to_use: false, item_type: 'ingredient' as const },
      { name: 'rice', quantity_grams: 1000, need_to_use: false, item_type: 'ingredient' as const },
    ]);

    const user = userEvent.setup();
    renderWithProviders(<ReceiptScanner currentFridge={[]} />);

    const input = screen.getByLabelText(/select receipt image/i);
    await user.upload(input, createFile());
    await user.click(screen.getByRole('button', { name: /scan receipt/i }));

    await waitFor(() => {
      expect(screen.getByDisplayValue('chicken')).toBeInTheDocument();
    });

    // Remove the first item
    const removeButtons = screen.getAllByRole('button', { name: /remove/i });
    await user.click(removeButtons[0]);

    expect(screen.queryByDisplayValue('chicken')).not.toBeInTheDocument();
    expect(screen.getByDisplayValue('rice')).toBeInTheDocument();
  });
});

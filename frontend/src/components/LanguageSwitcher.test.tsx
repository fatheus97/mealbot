import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LanguageSwitcher } from './LanguageSwitcher';
import { useLocaleStore, DEFAULT_LOCALE } from '../store/useLocaleStore';
import { syncDocumentLang } from '../i18n/documentLang';

describe('LanguageSwitcher', () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
  });

  // Rendered with plain RTL `render` — no provider of any kind. That is the
  // point of reading locale from the zustand store: 41 of this repo's 50 test
  // files render without providers, and a context-based i18n library would
  // have required editing all of them.
  it('renders without any provider', () => {
    render(<LanguageSwitcher />);
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });

  it('names each language in itself, not in the current language', () => {
    // Someone hunting for this control cannot, by definition, read the
    // language it is currently displaying — "Czech" would be useless to them.
    render(<LanguageSwitcher />);
    expect(screen.getByRole('option', { name: 'Čeština' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'English' })).toBeInTheDocument();
  });

  it('has an accessible name so the control is not announced bare', () => {
    render(<LanguageSwitcher />);
    expect(screen.getByRole('combobox', { name: 'Language' })).toBeInTheDocument();
  });

  it('shows the active locale as the selected option', () => {
    useLocaleStore.setState({ locale: 'cs', explicit: true });
    render(<LanguageSwitcher />);
    expect(screen.getByRole('combobox')).toHaveValue('cs');
  });

  it('switches the locale and re-renders its own label in the new language', () => {
    render(<LanguageSwitcher />);
    return userEvent
      .selectOptions(screen.getByRole('combobox'), 'cs')
      .then(() => {
        expect(useLocaleStore.getState().locale).toBe('cs');
        // Proves the store subscription actually drives a re-render — without
        // it the value would change and the UI would not.
        expect(screen.getByRole('combobox', { name: 'Jazyk' })).toBeInTheDocument();
      });
  });

  it('marks the switch explicit so browser detection cannot undo it', async () => {
    render(<LanguageSwitcher />);
    await userEvent.selectOptions(screen.getByRole('combobox'), 'cs');
    expect(useLocaleStore.getState().explicit).toBe(true);
  });
});

describe('syncDocumentLang', () => {
  beforeEach(() => {
    useLocaleStore.setState({ locale: DEFAULT_LOCALE, explicit: false });
    document.documentElement.lang = 'en';
  });

  it('follows a locale change so screen readers use the right phonetics', () => {
    const unsubscribe = syncDocumentLang();
    try {
      expect(document.documentElement.lang).toBe('en');
      useLocaleStore.getState().setLocale('cs');
      expect(document.documentElement.lang).toBe('cs');
    } finally {
      unsubscribe();
    }
  });

  it('stops updating once unsubscribed', () => {
    syncDocumentLang()();
    useLocaleStore.getState().setLocale('cs');
    expect(document.documentElement.lang).toBe('en');
  });
});
